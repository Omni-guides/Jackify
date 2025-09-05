"""
Configure Modlist Command

CLI command for configuring a modlist post-install.
Extracted from the original jackify-cli.py.
"""

import os
import logging
from typing import Optional

# Import the backend services we'll need
from jackify.backend.models.configuration import ConfigurationContext
from jackify.shared.colors import COLOR_INFO, COLOR_ERROR, COLOR_RESET

logger = logging.getLogger(__name__)


class ConfigureModlistCommand:
    """Handler for the configure-modlist CLI command."""
    
    def __init__(self, backend_services):
        """Initialize with backend services.
        
        Args:
            backend_services: Dictionary of backend service instances
        """
        self.backend_services = backend_services
        self.test_mode = False  # TODO: Get from global config
    
    def add_parser(self, subparsers):
        """Add the configure-modlist subcommand parser.
        
        Args:
            subparsers: The ArgumentParser subparsers object
        """
        configure_modlist_parser = subparsers.add_parser(
            "configure-modlist", 
            help="Configure a modlist post-install (for GUI integration)"
        )
        configure_modlist_parser.add_argument(
            "--modlist-name", 
            type=str, 
            required=True, 
            help="Name of the modlist to configure (Steam shortcut name)"
        )
        configure_modlist_parser.add_argument(
            "--install-dir", 
            type=str, 
            required=True, 
            help="Install directory of the modlist"
        )
        configure_modlist_parser.add_argument(
            "--download-dir", 
            type=str, 
            help="Downloads directory (optional)"
        )
        configure_modlist_parser.add_argument(
            "--nexus-api-key", 
            type=str, 
            help="Nexus API key (optional)"
        )
        configure_modlist_parser.add_argument(
            "--mo2-exe-path", 
            type=str, 
            help="Path to ModOrganizer.exe (for AppID lookup)"
        )
        configure_modlist_parser.add_argument(
            "--resolution", 
            type=str, 
            help="Resolution to set (optional)"
        )
        configure_modlist_parser.add_argument(
            "--skip-confirmation", 
            action='store_true', 
            help="Skip confirmation prompts"
        )
        return configure_modlist_parser
    
    def execute(self, args) -> int:
        """Execute the configure-modlist command.
        
        Args:
            args: Parsed command-line arguments
            
        Returns:
            Exit code (0 for success, 1 for failure)
        """
        logger.info("Starting non-interactive modlist configuration (CLI mode)")
        
        try:
            # Build configuration context from args
            context = self._build_context_from_args(args)
            
            # Use legacy implementation for now - will migrate to backend services later
            result = self._execute_legacy_configuration(context)
            
            logger.info("Finished non-interactive modlist configuration")
            return 0 if result is not True else 1
            
        except Exception as e:
            logger.error(f"Failed to configure modlist: {e}")
            print(f"{COLOR_ERROR}Configuration failed: {e}{COLOR_RESET}")
            return 1
    
    def _build_context_from_args(self, args) -> dict:
        """Build context dictionary from command arguments.
        
        Args:
            args: Parsed command-line arguments
            
        Returns:
            Context dictionary
        """
        return {
            'modlist_name': getattr(args, 'modlist_name', None),
            'install_dir': getattr(args, 'install_dir', None),
            'download_dir': getattr(args, 'download_dir', None),
            'nexus_api_key': getattr(args, 'nexus_api_key', os.environ.get('NEXUS_API_KEY')),
            'mo2_exe_path': getattr(args, 'mo2_exe_path', None),
            'resolution': getattr(args, 'resolution', None),
            'skip_confirmation': getattr(args, 'skip_confirmation', False),
            'modlist_value': getattr(args, 'modlist_value', None),
            'modlist_source': getattr(args, 'modlist_source', None),
        }
    
    def _execute_legacy_configuration(self, context: dict):
        """Execute configuration using legacy implementation.
        
        This is a temporary bridge - will be replaced with backend service calls.
        
        Args:
            context: Configuration context dictionary
            
        Returns:
            Result from legacy configuration
        """
        # Import backend services
        from jackify.backend.handlers.menu_handler import ModlistMenuHandler
        from jackify.backend.handlers.config_handler import ConfigHandler
        
        # Create legacy handler instances
        config_handler = ConfigHandler()
        modlist_menu = ModlistMenuHandler(
            config_handler=config_handler,
            test_mode=self.test_mode
        )
        
        # Execute legacy configuration workflow
        # The _configure_new_modlist method already handles Steam restart, manual steps, and configuration
        result = modlist_menu._configure_new_modlist(
            default_modlist_dir=context['install_dir'],
            default_modlist_name=context['modlist_name']
        )
        
        # The _configure_new_modlist method already calls run_modlist_configuration_phase internally
        # So we don't need to call it again here
        
        return result 