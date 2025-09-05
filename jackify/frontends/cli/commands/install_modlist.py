"""
Install Modlist Command

CLI command for installing modlists.
Extracted from the original jackify-cli.py.
"""

import os
import logging
from typing import Optional

# Import the backend services we'll need
from jackify.backend.models.modlist import ModlistContext
from jackify.shared.colors import COLOR_INFO, COLOR_ERROR, COLOR_RESET

logger = logging.getLogger(__name__)


class InstallModlistCommand:
    """Handler for the install-modlist CLI command."""
    
    def __init__(self, backend_services, system_info):
        """Initialize with backend services.
        
        Args:
            backend_services: Dictionary of backend service instances
            system_info: System information (steamdeck flag, etc.)
        """
        self.backend_services = backend_services
        self.system_info = system_info
    
    def add_top_level_args(self, parser):
        """Add top-level install-modlist arguments to the main parser.
        
        Args:
            parser: The main ArgumentParser
        """
        parser.add_argument(
            "--install-modlist", 
            action="store_true", 
            help="Enable modlist install/list feature (for GUI integration)"
        )
        parser.add_argument(
            "--list-modlists", 
            action="store_true", 
            help="List available modlists for a game type (with --install-modlist)"
        )
        parser.add_argument(
            "--install", 
            action="store_true", 
            help="Install a modlist non-interactively (with --install-modlist)"
        )
        parser.add_argument(
            "--game-type", 
            type=str, 
            default=None, 
            help="Game type to filter modlists (skyrim, fallout4, falloutnv, oblivion, starfield, oblivion_remastered, other)"
        )
        parser.add_argument(
            "--modlist-value", 
            type=str, 
            help="Modlist identifier for online modlists"
        )
    
    def add_parser(self, subparsers):
        """Add the install-modlist subcommand parser.
        
        Args:
            subparsers: The ArgumentParser subparsers object
        """
        install_modlist_parser = subparsers.add_parser(
            "install-modlist", 
            help="Install or list available modlists"
        )
        install_modlist_parser.add_argument(
            "--list", 
            action="store_true", 
            help="List available modlists for a game type"
        )
        install_modlist_parser.add_argument(
            "--game-type", 
            type=str, 
            default=None, 
            help="Game type to filter modlists (skyrim, fallout4, falloutnv, oblivion, starfield, oblivion_remastered, other)"
        )
        return install_modlist_parser
    
    def execute_top_level(self, args) -> int:
        """Execute top-level install-modlist functionality.
        
        Args:
            args: Parsed command-line arguments
            
        Returns:
            Exit code (0 for success, 1 for failure)
        """
        if getattr(args, 'list_modlists', False):
            return self.list_modlists(args)
        elif getattr(args, 'install', False):
            return self.install_modlist_auto(args)
        else:
            print(f"{COLOR_ERROR}No valid install-modlist operation specified{COLOR_RESET}")
            return 1
    
    def execute_subcommand(self, args) -> int:
        """Execute the install-modlist subcommand.
        
        Args:
            args: Parsed command-line arguments
            
        Returns:
            Exit code (0 for success, 1 for failure)
        """
        if getattr(args, 'list', False):
            return self.list_modlists(args)
        else:
            # Default behavior: run interactive modlist installation
            logger.info("Starting interactive modlist installation via subcommand")
            
            try:
                # Use the working ModlistInstallCLI for interactive installation
                from jackify.backend.core.modlist_operations import ModlistInstallCLI
                
                # Use new SystemInfo pattern
                modlist_cli = ModlistInstallCLI(self.system_info)
                
                # Run interactive discovery phase
                context = modlist_cli.run_discovery_phase()
                if context:
                    # Run configuration phase (installation + Steam setup)
                    modlist_cli.configuration_phase()
                    logger.info("Interactive modlist installation completed successfully")
                    return 0
                else:
                    logger.info("Modlist installation cancelled by user")
                    return 1
                    
            except Exception as e:
                logger.error(f"Failed to install modlist: {e}")
                print(f"{COLOR_ERROR}Installation failed: {e}{COLOR_RESET}")
                return 1
    
    def list_modlists(self, args) -> int:
        """List available modlists for a game type.
        
        Args:
            args: Parsed command-line arguments
            
        Returns:
            Exit code (0 for success, 1 for failure)
        """
        logger.info("Listing available modlists")
        
        try:
            # Use legacy implementation for now - will migrate to backend services later
            result = self._execute_legacy_list_modlists(args)
            return 0
            
        except Exception as e:
            logger.error(f"Failed to list modlists: {e}")
            print(f"{COLOR_ERROR}Failed to list modlists: {e}{COLOR_RESET}")
            return 1
    
    def install_modlist_auto(self, args) -> int:
        """Install a modlist non-interactively.
        
        Args:
            args: Parsed command-line arguments
            
        Returns:
            Exit code (0 for success, 1 for failure)
        """
        logger.info("Starting non-interactive modlist installation")
        
        try:
            # Build context from args
            context = self._build_install_context_from_args(args)
            
            # Validate required fields
            if not self._validate_install_context(context):
                return 1
            
            # Use legacy implementation for now - will migrate to backend services later
            result = self._execute_legacy_install(context)
            
            logger.info("Finished non-interactive modlist installation")
            return result
            
        except Exception as e:
            logger.error(f"Failed to install modlist: {e}")
            print(f"{COLOR_ERROR}Installation failed: {e}{COLOR_RESET}")
            return 1
    
    def _build_install_context_from_args(self, args) -> dict:
        """Build installation context from command arguments.
        
        Args:
            args: Parsed command-line arguments
            
        Returns:
            Context dictionary
        """
        return {
            'modlist_name': getattr(args, 'modlist_name', None),
            'install_dir': getattr(args, 'install_dir', None),
            'download_dir': getattr(args, 'download_dir', None),
            'nexus_api_key': os.environ.get('NEXUS_API_KEY'),
            'game_type': getattr(args, 'game_type', None),
            'modlist_value': getattr(args, 'modlist_value', None),
            'skip_confirmation': True,
            'resolution': getattr(args, 'resolution', None),
        }
    
    def _validate_install_context(self, context: dict) -> bool:
        """Validate installation context.
        
        Args:
            context: Installation context dictionary
            
        Returns:
            True if valid, False otherwise
        """
        is_gui_mode = os.environ.get('JACKIFY_GUI_MODE') == '1'
        required_keys = ['modlist_name', 'install_dir', 'download_dir', 'nexus_api_key', 'game_type']
        missing = [k for k in required_keys if not context.get(k)]
        
        if is_gui_mode and missing:
            print(f"ERROR: Missing required arguments for GUI workflow: {', '.join(missing)}")
            print("This workflow must be fully non-interactive. Please report this as a bug if you see this message.")
            return False
        
        return True
    
    def _execute_legacy_list_modlists(self, args):
        """Execute list modlists using backend implementation.
        
        Args:
            args: Parsed command-line arguments
        """
        # Import backend services
        from jackify.backend.core.modlist_operations import ModlistInstallCLI
        
        # Use new SystemInfo pattern
        modlist_cli = ModlistInstallCLI(self.system_info)
        
        # Get all modlists from engine
        raw_modlists = modlist_cli.get_all_modlists_from_engine()
        
        # Group by game type as in original CLI
        game_type_map = {
            'skyrim': ['Skyrim', 'Skyrim Special Edition'],
            'fallout4': ['Fallout 4'],
            'falloutnv': ['Fallout New Vegas'],
            'oblivion': ['Oblivion'],
            'starfield': ['Starfield'],
            'oblivion_remastered': ['Oblivion Remastered', 'OblivionRemastered'],
            'other': None
        }
        
        grouped_modlists = {k: [] for k in game_type_map}

        for m_info in raw_modlists:  # m_info is like {'id': ..., 'game': ...}
            found_category = False
            for cat_key, cat_keywords in game_type_map.items():
                if cat_key == 'other':
                    continue
                if cat_keywords:
                    for keyword in cat_keywords:
                        if keyword.lower() in m_info.get('game', '').lower():
                            grouped_modlists[cat_key].append(m_info)
                            found_category = True
                            break
                if found_category:
                    break
            if not found_category:
                grouped_modlists['other'].append(m_info)
        
        # Output modlists for the requested game type
        game_type = (getattr(args, 'game_type', '') or '').lower()
        if game_type and game_type in grouped_modlists:
            for m in grouped_modlists[game_type]:
                print(m.get('id', ''))
        else:
            # Output all modlists
            for cat_key in ['skyrim', 'fallout4', 'falloutnv', 'oblivion', 'starfield', 'oblivion_remastered', 'other']:
                for m in grouped_modlists[cat_key]:
                    print(m.get('id', ''))
    
    def _execute_legacy_install(self, context: dict) -> int:
        """Execute installation using backend implementation.
        
        Args:
            context: Installation context dictionary
            
        Returns:
            Exit code
        """
        # Import backend services
        from jackify.backend.core.modlist_operations import ModlistInstallCLI
        from jackify.shared.colors import COLOR_WARNING, COLOR_PROMPT
        
        # Use new SystemInfo pattern
        modlist_cli = ModlistInstallCLI(self.system_info)
        
        # Detect game type and check support
        game_type = None
        wabbajack_file_path = context.get('wabbajack_file_path')
        modlist_info = context.get('modlist_info')
        
        if wabbajack_file_path:
            game_type = modlist_cli.detect_game_type(wabbajack_file_path=wabbajack_file_path)
        elif modlist_info:
            game_type = modlist_cli.detect_game_type(modlist_info=modlist_info)
        elif context.get('game_type'):
            game_type = context['game_type']
        
        # Check if game is supported
        if game_type and not modlist_cli.check_game_support(game_type):
            # Show unsupported game warning
            supported_games = modlist_cli.wabbajack_parser.get_supported_games_display_names()
            supported_games_str = ", ".join(supported_games)
            
            print(f"\n{COLOR_WARNING}Game Support Notice{COLOR_RESET}")
            print(f"{COLOR_WARNING}While any modlist can be downloaded with Jackify, the post-install configuration can only be automatically applied to: {supported_games_str}.{COLOR_RESET}")
            print(f"{COLOR_WARNING}We are working to add more automated support in future releases!{COLOR_RESET}")
            
            # Ask for confirmation to continue
            response = input(f"{COLOR_PROMPT}Click Enter to continue with the modlist installation, or type 'cancel' to abort: {COLOR_RESET}").strip().lower()
            if response == 'cancel':
                print("[INFO] Modlist installation cancelled by user.")
                return 1
        
        is_gui_mode = os.environ.get('JACKIFY_GUI_MODE') == '1'
        
        if is_gui_mode:
            confirmed_context = modlist_cli.run_discovery_phase(context_override=context)
            if confirmed_context:
                # For unsupported games, skip post-install configuration
                if game_type and not modlist_cli.check_game_support(game_type):
                    print(f"{COLOR_WARNING}Modlist installation completed successfully.{COLOR_RESET}")
                    print(f"{COLOR_WARNING}Note: Post-install configuration was skipped for unsupported game type: {game_type}{COLOR_RESET}")
                    return 0
                else:
                    modlist_cli.configuration_phase()
                return 0
            else:
                print("[INFO] Modlist installation cancelled or not confirmed.")
                return 1
        else:
            # CLI mode: allow interactive prompts as before
            confirmed_context = modlist_cli.run_discovery_phase(context_override=context)
            if confirmed_context:
                # For unsupported games, skip post-install configuration
                if game_type and not modlist_cli.check_game_support(game_type):
                    print(f"{COLOR_WARNING}Modlist installation completed successfully.{COLOR_RESET}")
                    print(f"{COLOR_WARNING}Note: Post-install configuration was skipped for unsupported game type: {game_type}{COLOR_RESET}")
                    return 0
                else:
                    modlist_cli.configuration_phase()
                return 0
            else:
                print("[INFO] Modlist installation cancelled or not confirmed.")
                return 1 