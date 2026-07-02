"""
modlist_install_cli.py
Discovery phase for Jackify's modlist install CLI feature.
"""
import os
from pathlib import Path
from typing import Optional, Dict, List, Any, Union
from .protontricks_handler import ProtontricksHandler
from .shortcut_handler import ShortcutHandler
from .menu_handler import MenuHandler, ModlistMenuHandler
from jackify.shared.colors import COLOR_PROMPT, COLOR_INFO, COLOR_ERROR, COLOR_RESET, COLOR_SUCCESS, COLOR_WARNING, COLOR_SELECTION
# Standard logging (no file handler) - LoggingHandler import removed
import re
import subprocess
import logging
import sys
import json
import shlex
import time
import pty

# Import UI Colors first - these should always be available
from jackify.shared.colors import COLOR_PROMPT, COLOR_RESET, COLOR_INFO, COLOR_ERROR, COLOR_SELECTION, COLOR_WARNING

# Standard logging (no file handler) - LoggingHandler import removed

# Attempt to import readline for tab completion
READLINE_AVAILABLE = False
try:
    import readline
    READLINE_AVAILABLE = True
    # Check if running in a non-interactive environment (e.g., some CI)
    if 'libedit' in readline.__doc__:
         # libedit doesn't support set_completion_display_matches_hook
         pass
    # Add other potential checks if needed
except ImportError:
    # readline not available on Windows or potentially minimal environments
    pass
except Exception as e:
    # Catch other potential errors during readline import/setup
    logging.warning(f"Readline import failed: {e}") # Use standard logging before our handler
    pass

logger = logging.getLogger(__name__)

from .modlist_install_cli_discovery import ModlistInstallCLIDiscoveryMixin
from .modlist_install_cli_configuration import ModlistInstallCLIConfigurationMixin
from .modlist_install_cli_ttw import ModlistInstallCLITTWMixin
from .modlist_install_cli_nexus import ModlistInstallCLINexusMixin


def get_jackify_engine_path():
    appdir = os.environ.get('APPDIR')
    if appdir:
        # Running inside AppImage
        # Engine is expected at <appdir>/opt/jackify/engine/jackify-engine
        return os.path.join(appdir, 'opt', 'jackify', 'engine', 'jackify-engine')
    else:
        # Running in a normal Python environment from source
        # Current file is in src/jackify/backend/handlers/modlist_install_cli.py
        # Engine is at src/jackify/engine/jackify-engine
        current_file_dir = os.path.dirname(os.path.abspath(__file__))
        # Navigate up from src/jackify/backend/handlers/ to src/jackify/
        jackify_dir = os.path.dirname(os.path.dirname(current_file_dir))
        return os.path.join(jackify_dir, 'engine', 'jackify-engine')

class ModlistInstallCLI(
    ModlistInstallCLIDiscoveryMixin,
    ModlistInstallCLIConfigurationMixin,
    ModlistInstallCLITTWMixin,
    ModlistInstallCLINexusMixin,
):
    """
    Handles the discovery phase for installing a Wabbajack modlist via CLI.
    """
    def __init__(self, menu_handler: MenuHandler, steamdeck: bool = False):
        self.menu_handler = menu_handler
        self.steamdeck = steamdeck
        self.protontricks_handler = ProtontricksHandler(steamdeck)
        self.shortcut_handler = ShortcutHandler(steamdeck=steamdeck)
        self.context = {}
        # Use standard logging (no file handler)
        self.logger = logging.getLogger(__name__)
        self.logger.propagate = False # Prevent duplicate logs if root logger is also configured

    def _display_summary(self):
        """
        Display a summary of the collected context (excluding API key).
        """
        print(f"\n{COLOR_INFO}--- Summary of Collected Information ---{COLOR_RESET}")
        if self.context.get('modlist_source_type') == 'online_list':
            print(f"Modlist Source: Selected from online list")
            print(f"Modlist Identifier: {self.context.get('modlist_value')}")
            print(f"Detected Game: {self.context.get('modlist_game', 'N/A')}")
        elif self.context.get('modlist_source_type') == 'local_file':
            print(f"Modlist Source: Local .wabbajack file")
            print(f"File Path: {self.context.get('modlist_value')}")
        elif 'machineid' in self.context: # For Tuxborn/override flow
             print(f"Modlist Identifier (Tuxborn/MachineID): {self.context.get('machineid')}")
        
        print(f"Steam Shortcut Name: {self.context.get('modlist_name', 'N/A')}")

        install_dir_display = self.context.get('install_dir')
        if isinstance(install_dir_display, tuple):
            install_dir_display = install_dir_display[0] # Get the Path object from (Path, bool)
        print(f"Install Directory: {install_dir_display}")

        download_dir_display = self.context.get('download_dir')
        if isinstance(download_dir_display, tuple):
            download_dir_display = download_dir_display[0] # Get the Path object from (Path, bool)
        print(f"Download Directory: {download_dir_display}")

        # Show authentication method
        from jackify.backend.services.nexus_auth_service import NexusAuthService
        auth_service = NexusAuthService()
        authenticated, method, username = auth_service.get_auth_status()

        if method == 'oauth':
            auth_display = f"Nexus Authentication: OAuth"
            if username:
                auth_display += f" ({username})"
        elif method == 'api_key':
            auth_display = "Nexus Authentication: API Key (Legacy)"
        else:
            # Should never reach here since we validate auth before getting to summary
            auth_display = "Nexus Authentication: Unknown"

        print(auth_display)
        print(f"{COLOR_INFO}----------------------------------------{COLOR_RESET}")

    def _display_summary(self):
        # REMOVE pass AND RESTORE THE METHOD BODY
        print(f"\n{COLOR_INFO}--- Summary of Collected Information ---{COLOR_RESET}")
        if self.context.get('modlist_source_type') == 'online_list':
            print(f"Modlist Source: Selected from online list")
            print(f"Modlist Identifier: {self.context.get('modlist_value')}")
            print(f"Detected Game: {self.context.get('modlist_game', 'N/A')}")
        elif self.context.get('modlist_source_type') == 'local_file':
            print(f"Modlist Source: Local .wabbajack file")
            print(f"File Path: {self.context.get('modlist_value')}")
        elif 'machineid' in self.context: # For Tuxborn/override flow
             print(f"Modlist Identifier (Tuxborn/MachineID): {self.context.get('machineid')}")
        
        print(f"Steam Shortcut Name: {self.context.get('modlist_name', 'N/A')}")

        install_dir_display = self.context.get('install_dir')
        if isinstance(install_dir_display, tuple):
            install_dir_display = install_dir_display[0] # Get the Path object from (Path, bool)
        print(f"Install Directory: {install_dir_display}")

        download_dir_display = self.context.get('download_dir')
        if isinstance(download_dir_display, tuple):
            download_dir_display = download_dir_display[0] # Get the Path object from (Path, bool)
        print(f"Download Directory: {download_dir_display}")

        # Show authentication method
        from jackify.backend.services.nexus_auth_service import NexusAuthService
        auth_service = NexusAuthService()
        authenticated, method, username = auth_service.get_auth_status()

        if method == 'oauth':
            auth_display = f"Nexus Authentication: OAuth"
            if username:
                auth_display += f" ({username})"
        elif method == 'api_key':
            auth_display = "Nexus Authentication: API Key (Legacy)"
        else:
            # Should never reach here since we validate auth before getting to summary
            auth_display = "Nexus Authentication: Unknown"

        print(auth_display)
        print(f"{COLOR_INFO}----------------------------------------{COLOR_RESET}")

