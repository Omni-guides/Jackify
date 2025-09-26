#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Jackify CLI Frontend - Main Entry Point

Command-line interface for Jackify that uses the backend services.
Extracted and refactored from the original jackify-cli.py.
"""

import sys
import os
import argparse
import logging

# Import from our new backend structure
from jackify.backend.models.configuration import SystemInfo
from jackify.backend.services.modlist_service import ModlistService
from jackify.shared.colors import COLOR_INFO, COLOR_ERROR, COLOR_RESET
from jackify import __version__ as jackify_version

# Import our command handlers
from .commands.configure_modlist import ConfigureModlistCommand
from .commands.install_modlist import InstallModlistCommand

# Import our menu handlers
from .menus.main_menu import MainMenuHandler
from .menus.wabbajack_menu import WabbajackMenuHandler
from .menus.hoolamike_menu import HoolamikeMenuHandler
from .menus.additional_menu import AdditionalMenuHandler

# Import backend handlers for legacy compatibility
from jackify.backend.handlers.config_handler import ConfigHandler
from jackify.backend.handlers.filesystem_handler import FileSystemHandler
from jackify.backend.handlers.path_handler import PathHandler
from jackify.backend.handlers.shortcut_handler import ShortcutHandler
from jackify.backend.handlers.menu_handler import MenuHandler
from jackify.backend.handlers.mo2_handler import MO2Handler

logger = logging.getLogger(__name__)


class JackifyCLI:
    """Main application class for Jackify CLI Frontend"""
    
    def __init__(self, test_mode=False, dev_mode=False):
        """Initialize the JackifyCLI frontend.
        
        Args:
            test_mode (bool): If True, run in test mode with minimal side effects
            dev_mode (bool): If True, enable development features
        """
        # Initialize early (debug flag not yet available)
        self._debug_mode = False
        
        # Set test mode flag
        self.test_mode = test_mode
        self.dev_mode = dev_mode
        self.verbose = False
        
        # Configure logging to be quiet by default - will be adjusted after arg parsing
        self._configure_logging_early()
        
        # Determine system info
        self.system_info = SystemInfo(is_steamdeck=self._is_steamdeck())
        
        # Apply resource limits for optimal operation
        self._apply_resource_limits()
        
        # Initialize backend services
        self.backend_services = self._initialize_backend_services()
        
        # Initialize command handlers
        self.commands = self._initialize_command_handlers()
        
        # Initialize menu handlers with dev_mode
        self.menus = self._initialize_menu_handlers()
        
        # Initialize legacy compatibility attributes for menu bridge
        self._initialize_legacy_compatibility()
        
        # Initialize state variables
        self.parser = None
        self.subparsers = None
        self.args = None
        self.selected_modlist = None
        self.setup_complete = False
    
    def _debug_print(self, message):
        """Print debug message only if debug mode is enabled"""
        if hasattr(self, '_debug_mode') and self._debug_mode:
            logger.debug(message)
    
    def _configure_logging_early(self):
        """Configure logging to be quiet during initialization, will be adjusted after arg parsing"""
        # Set root logger to WARNING level initially to suppress INFO messages during init
        logging.getLogger().setLevel(logging.WARNING)
        
        # Configure basic logging format
        if not logging.getLogger().handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            logging.getLogger().addHandler(handler)
    
    def _configure_logging_final(self):
        """Configure final logging level based on parsed arguments"""
        # Use the existing LoggingHandler for proper log rotation
        from jackify.backend.handlers.logging_handler import LoggingHandler
        
        # Set up CLI-specific logging with rotation
        logging_handler = LoggingHandler()
        logging_handler.rotate_log_for_logger('jackify-cli', 'Modlist_Install_workflow_cli.log')
        cli_logger = logging_handler.setup_logger('jackify-cli', 'Modlist_Install_workflow_cli.log')
        
        # Configure logging level
        if self.args.debug:
            cli_logger.setLevel(logging.DEBUG)
            print("Debug logging enabled for console and file")
        elif self.args.verbose:
            cli_logger.setLevel(logging.INFO)
            print("Verbose logging enabled for console and file")
        else:
            # Keep it at WARNING level for clean startup
            cli_logger.setLevel(logging.WARNING)
    
    def _is_steamdeck(self):
        """Check if running on Steam Deck"""
        try:
            if os.path.exists("/etc/os-release"):
                with open("/etc/os-release", "r") as f:
                    content = f.read()
                    if "steamdeck" in content:
                        logger.info("Running on Steam Deck")
                        return True
            logger.info("Not running on Steam Deck")
            return False
        except Exception as e:
            logger.error(f"Error detecting Steam Deck: {e}")
            return False
    
    def _apply_resource_limits(self):
        """Apply recommended resource limits for optimal Jackify operation"""
        try:
            from jackify.backend.services.resource_manager import ResourceManager
            
            resource_manager = ResourceManager()
            success = resource_manager.apply_recommended_limits()
            
            if success:
                status = resource_manager.get_limit_status()
                if status['target_achieved']:
                    logger.info(f"Resource limits optimized: file descriptors set to {status['current_soft']}")
                else:
                    logger.info(f"Resource limits improved: file descriptors increased to {status['current_soft']} (target: {status['target_limit']})")
            else:
                # Log the issue but don't block startup
                status = resource_manager.get_limit_status()
                logger.warning(f"Could not optimize resource limits: current file descriptors={status['current_soft']}, target={status['target_limit']}")
                
                # If we can't increase automatically, provide manual instructions in debug mode
                if hasattr(self, '_debug_mode') and self._debug_mode:
                    instructions = resource_manager.get_manual_increase_instructions()
                    logger.debug(f"Manual increase instructions available for {instructions['distribution']}")
                    
        except Exception as e:
            # Don't block startup on resource management errors
            logger.warning(f"Error applying resource limits: {e}")
    
    def _initialize_backend_services(self):
        """Initialize backend services.
        
        Returns:
            Dictionary of backend service instances
        """
        # Initialize update service
        from jackify.backend.services.update_service import UpdateService
        update_service = UpdateService(jackify_version)
        
        services = {
            'modlist_service': ModlistService(self.system_info),
            'update_service': update_service
        }
        return services
    
    def _check_for_updates_on_startup(self):
        """Check for updates on startup in background thread"""
        try:
            self._debug_print("Checking for updates on startup...")
            
            def update_check_callback(update_info):
                """Handle update check results"""
                try:
                    if update_info:
                        print(f"\n{COLOR_INFO}Update available: v{update_info.version}{COLOR_RESET}")
                        print(f"Current version: v{jackify_version}")
                        print(f"Release date: {update_info.release_date}")
                        if update_info.changelog:
                            print(f"Changelog: {update_info.changelog[:200]}...")
                        print(f"Download size: {update_info.file_size / (1024*1024):.1f} MB" if update_info.file_size else "Download size: Unknown")
                        print(f"\nTo update, run: jackify --update")
                        print("Or visit: https://github.com/Omni-guides/Jackify/releases")
                    else:
                        self._debug_print("No updates available")
                except Exception as e:
                    self._debug_print(f"Error showing update info: {e}")
            
            # Check for updates in background
            self.backend_services['update_service'].check_for_updates_async(update_check_callback)
            
        except Exception as e:
            self._debug_print(f"Error checking for updates on startup: {e}")
            # Continue anyway - don't block startup on update check errors
    
    def _handle_update(self):
        """Handle manual update check and installation"""
        try:
            print("Checking for updates...")
            update_service = self.backend_services['update_service']
            
            # Check if updating is possible
            if not update_service.can_update():
                print(f"{COLOR_ERROR}Update not possible: not running as AppImage or insufficient permissions{COLOR_RESET}")
                return 1
            
            # Check for updates
            update_info = update_service.check_for_updates()
            
            if update_info:
                print(f"{COLOR_INFO}Update available: v{update_info.version}{COLOR_RESET}")
                print(f"Current version: v{jackify_version}")
                print(f"Release date: {update_info.release_date}")
                if update_info.changelog:
                    print(f"Changelog: {update_info.changelog}")
                print(f"Download size: {update_info.file_size / (1024*1024):.1f} MB" if update_info.file_size else "Download size: Unknown")
                
                # Ask for confirmation
                response = input("\nDo you want to download and install this update? (y/N): ").strip().lower()
                if response in ['y', 'yes']:
                    print("Downloading update...")
                    
                    def progress_callback(downloaded, total):
                        if total > 0:
                            percentage = int((downloaded / total) * 100)
                            downloaded_mb = downloaded / (1024 * 1024)
                            total_mb = total / (1024 * 1024)
                            print(f"\rDownloaded {downloaded_mb:.1f} MB of {total_mb:.1f} MB ({percentage}%)", end='', flush=True)
                    
                    downloaded_path = update_service.download_update(update_info, progress_callback)
                    
                    if downloaded_path:
                        print(f"\nDownload completed. Installing update...")
                        if update_service.apply_update(downloaded_path):
                            print(f"{COLOR_INFO}Update applied successfully! Jackify will restart...{COLOR_RESET}")
                            return 0
                        else:
                            print(f"{COLOR_ERROR}Failed to apply update{COLOR_RESET}")
                            return 1
                    else:
                        print(f"\n{COLOR_ERROR}Failed to download update{COLOR_RESET}")
                        return 1
                else:
                    print("Update cancelled.")
                    return 0
            else:
                print(f"{COLOR_INFO}You are already running the latest version (v{jackify_version}){COLOR_RESET}")
                return 0
                
        except Exception as e:
            print(f"{COLOR_ERROR}Update failed: {e}{COLOR_RESET}")
            return 1
    
    def _initialize_command_handlers(self):
        """Initialize command handler instances.
        
        Returns:
            Dictionary of command handler instances
        """
        commands = {
            'configure_modlist': ConfigureModlistCommand(self.backend_services),
            'install_modlist': InstallModlistCommand(self.backend_services, self.system_info),
        }
        return commands

    def _initialize_menu_handlers(self):
        """Initialize menu handler instances.
        
        Returns:
            Dictionary of menu handler instances
        """
        menus = {
            'main': MainMenuHandler(dev_mode=getattr(self, 'dev_mode', False)),
            'wabbajack': WabbajackMenuHandler(),
            'hoolamike': HoolamikeMenuHandler(),
            'additional': AdditionalMenuHandler()
        }
        
        # Set up logging for menu handlers
        for menu in menus.values():
            menu.logger = logger
            
        return menus

    def _initialize_legacy_compatibility(self):
        """
        Initialize legacy compatibility attributes for menu bridge.
        
        This provides the legacy attributes that menu handlers expect from cli_instance
        until the backend migration is complete.
        """
        # LEGACY BRIDGE: Add legacy imports to access original handlers
        # Backend handlers are now imported directly from backend package
        
        try:
            # Initialize legacy handlers for compatibility
            self.config_handler = ConfigHandler()
            self.filesystem_handler = FileSystemHandler()
            self.path_handler = PathHandler()
            self.shortcut_handler = ShortcutHandler(self.config_handler.settings)
            self.menu = MenuHandler()  # Original menu handler for fallback
            self.menu_handler = self.menu  # Alias for backend compatibility
            
            # Add MO2 handler to the menu handler for additional tasks menu
            self.menu.mo2_handler = MO2Handler(self.menu)
            
            # Set steamdeck attribute that menus expect
            self.steamdeck = self.system_info.is_steamdeck
            
            # Initialize settings that legacy code expects
            if not hasattr(self.config_handler, 'settings'):
                self.config_handler.settings = {}
            self.config_handler.settings['steamdeck'] = self.steamdeck
            
            logger.info("Legacy compatibility layer initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize legacy compatibility layer: {e}")
            # Continue anyway - some functionality might still work
            self.config_handler = None
            self.filesystem_handler = None
            self.path_handler = None
            self.shortcut_handler = None
            self.menu = None
            self.steamdeck = self.system_info.is_steamdeck
    
    def run(self):
        self.parser, self.subparsers, self.args = self._parse_args()
        self._debug_mode = self.args.debug
        self.verbose = self.args.verbose or self.args.debug
        self.dev_mode = getattr(self.args, 'dev', False)
        # Re-initialize menus with dev_mode after parsing args
        self.menus = self._initialize_menu_handlers()
        
        # Now that we have args, configure logging properly
        self._configure_logging_final()
        
        self._debug_print('Initializing Jackify CLI Frontend')
        self._debug_print('JackifyCLI.run() called')
        self._debug_print(f'Parsed args: {self.args}')
        
        # Handle update functionality
        if getattr(self.args, 'update', False):
            self._debug_print('Entering update workflow')
            return self._handle_update()
        
        # Handle legacy restart-steam functionality (temporary)
        if getattr(self.args, 'restart_steam', False):
            self._debug_print('Entering restart_steam workflow')
            return self._handle_restart_steam()
        
        
        # Handle install-modlist top-level functionality
        if getattr(self.args, 'install_modlist', False):
            self._debug_print('Entering install_modlist workflow')
            return self.commands['install_modlist'].execute_top_level(self.args)
        
        # Handle subcommands
        if getattr(self.args, 'command', None):
            return self._run_command(self.args.command, self.args)
        
        # Check for updates on startup (non-blocking)
        self._check_for_updates_on_startup()
        
        # Run interactive mode (legacy for now)
        self._run_interactive()
    
    def _parse_args(self):
        """Parse command-line arguments using command handlers"""
        parser = argparse.ArgumentParser(description="Jackify: Wabbajack Modlist Manager for Linux/Steam Deck")
        parser.add_argument("-V", "--version", action="store_true", help="Show Jackify version and exit")
        parser.add_argument("-d", "--debug", action="store_true", help="Enable debug logging (implies verbose)")
        parser.add_argument("-v", "--verbose", action="store_true", help="Enable informational console output")
        parser.add_argument("--cli", action="store_true", help="Run in CLI mode (default if no GUI available)")
        parser.add_argument("--resolution", type=str, help="Resolution to set (optional)")
        parser.add_argument('--restart-steam', action='store_true', help='Restart Steam (native, for GUI integration)')
        parser.add_argument('--dev', action='store_true', help='Enable development features (show hidden menu items)')
        parser.add_argument('--update', action='store_true', help='Check for and install updates')
        
        # Add command-specific arguments
        self.commands['install_modlist'].add_top_level_args(parser)
        
        # Add subcommands
        subparsers = parser.add_subparsers(dest="command", help="Command to run")
        self.commands['configure_modlist'].add_parser(subparsers)
        self.commands['install_modlist'].add_parser(subparsers)
        
        args = parser.parse_args()
        if args.version:
            print(f"Jackify version {jackify_version}")
            sys.exit(0)
        
        return parser, subparsers, args
    
    def _run_command(self, command, args):
        """Run a specific command using command handlers"""
        if command == "install-modlist":
            return self.commands['install_modlist'].execute_subcommand(args)
        elif command == "configure-modlist":
            return self.commands['configure_modlist'].execute(args)
        elif command == "install-wabbajack":
            # Legacy functionality - TODO: extract to command handler
            return self._handle_legacy_install_wabbajack()
        elif command == "hoolamike":
            # Legacy functionality - TODO: extract to command handler
            return self._handle_legacy_hoolamike()
        elif command == "install-mo2":
            print("MO2 installation not yet implemented")
            print("This functionality is coming soon!")
            return 1
        elif command == "configure-nxm":
            print("NXM configuration not yet implemented")
            print("This functionality is coming soon!")
            return 1
        elif command == "recovery":
            return self._handle_legacy_recovery(args)
        elif command == "test-protontricks":
            return self._handle_legacy_protontricks_test()
        else:
            print(f"Unknown command: {command}")
            return 1
    
    def _run_interactive(self):
        """Run the CLI interface interactively using the new menu system"""
        try:
            while True:
                # Show main menu and get user's choice
                choice = self.menus['main'].show_main_menu(self)
                
                if choice == "exit":
                    print(f"{COLOR_INFO}Thank you for using Jackify!{COLOR_RESET}")
                    return 0
                elif choice == "wabbajack":
                    self.menus['wabbajack'].show_wabbajack_tasks_menu(self)
                # HIDDEN FOR FIRST RELEASE - UNCOMMENT WHEN READY
                # elif choice == "hoolamike":
                #     self.menus['hoolamike'].show_hoolamike_menu(self)
                # elif choice == "additional":
                #     self.menus['additional'].show_additional_tasks_menu(self)
                else:
                    logger.warning(f"Invalid choice '{choice}' received from show_main_menu.")
                    
        except KeyboardInterrupt:
            print(f"\n{COLOR_INFO}Exiting Jackify...{COLOR_RESET}")
            return 0
        except Exception as e:
            logger.error(f"Error in interactive mode: {e}")
            print(f"{COLOR_ERROR}An error occurred: {e}{COLOR_RESET}")
            return 1
    
    def _handle_restart_steam(self):
        """Handle restart-steam command - now properly implemented"""
        print("[Jackify] Attempting to restart Steam...")
        logger.debug("About to call secure_steam_restart()")
        
        try:
            # Use the already initialized shortcut_handler
            if self.shortcut_handler:
                success = self.shortcut_handler.secure_steam_restart()
                logger.debug(f"secure_steam_restart() returned: {success}")
                
                if success:
                    print("[Jackify] Steam restart completed successfully.")
                    return 0
                else:
                    print("[Jackify] Failed to restart Steam.")
                    return 1
            else:
                print("[Jackify] ERROR: ShortcutHandler not initialized")
                return 1
                
        except Exception as e:
            print(f"[Jackify] ERROR: Exception during Steam restart: {e}")
            logger.error(f"Steam restart failed with exception: {e}")
            return 1
    
    def _handle_legacy_install_wabbajack(self):
        """Handle install-wabbajack command (legacy functionality)"""
        print("Install Wabbajack functionality not yet migrated to new structure")
        return 1
    
    def _handle_legacy_hoolamike(self):
        """Handle hoolamike command (legacy functionality)"""
        print("Hoolamike functionality not yet migrated to new structure")
        return 1
    
    def _handle_legacy_recovery(self, args):
        """Handle recovery command (legacy functionality)"""
        print("Recovery functionality not yet migrated to new structure")
        return 1
    
    def _handle_legacy_protontricks_test(self):
        """Handle test-protontricks command (legacy functionality)"""
        print("Protontricks test functionality not yet migrated to new structure")
        return 1

    # LEGACY BRIDGE: Methods that menu handlers expect to find on cli_instance
    def _cmd_install_wabbajack(self, args):
        """LEGACY BRIDGE: Install Wabbajack application"""
        return self._handle_legacy_install_wabbajack()


def main():
    """Legacy main function (not used in new structure)"""
    pass


if __name__ == "__main__":
    # This should not be called directly - use __main__.py instead
    print("Please use: python -m jackify.frontends.cli")
    sys.exit(1)
