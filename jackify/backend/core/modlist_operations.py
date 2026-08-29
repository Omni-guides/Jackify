import os
from pathlib import Path
from typing import Optional, Dict, List, Any, Union
from ..handlers.protontricks_handler import ProtontricksHandler
from ..handlers.shortcut_handler import ShortcutHandler
from ..handlers.menu_handler import MenuHandler
from jackify.shared.colors import COLOR_PROMPT, COLOR_INFO, COLOR_ERROR, COLOR_RESET, COLOR_SUCCESS, COLOR_WARNING, COLOR_SELECTION
import logging
from ..handlers.wabbajack_parser import WabbajackParser
import re
import subprocess
import logging
import sys
import json
import shlex
import time
import pty
from jackify.backend.services.modlist_service import ModlistService
from jackify.backend.models.configuration import SystemInfo
from jackify.backend.handlers.config_handler import ConfigHandler

from .modlist_operations_discovery import ModlistOperationsDiscoveryMixin
from .modlist_operations_configuration_cli import ModlistOperationsConfigurationCLIMixin
from .modlist_operations_game_detection import ModlistOperationsGameDetectionMixin
from .modlist_operations_nexus import ModlistOperationsNexusMixin
from jackify.backend.services.update_detection import (
    evaluate_update_candidate as _svc_evaluate,
    find_existing_shortcut_appid as _svc_find_appid,
    normalize_version_token,
    normalize_modlist_name,
)


def _get_user_proton_version():
    """Get user's preferred Proton version from config, with fallback to auto-detection"""
    try:
        from jackify.backend.handlers.config_handler import ConfigHandler
        from jackify.backend.handlers.wine_utils import WineUtils

        config_handler = ConfigHandler()
        # Use Install Proton (not Game Proton) for installation/texture processing
        # get_proton_path() returns the Install Proton path
        user_proton_path = config_handler.get_proton_path()

        if not user_proton_path or user_proton_path == 'auto':
            # Use enhanced fallback logic with GE-Proton preference
            logging.info("User selected auto-detect, using GE-Proton → Experimental → Proton precedence")
            return WineUtils.select_best_proton()
        else:
            # User has selected a specific Proton version
            # Use the exact directory name for Steam config.vdf
            try:
                proton_version = os.path.basename(user_proton_path)
                # GE-Proton uses exact directory name, Valve Proton needs lowercase conversion
                if proton_version.startswith('GE-Proton'):
                    # Keep GE-Proton name exactly as-is
                    steam_proton_name = proton_version
                else:
                    # Convert Valve Proton names to Steam's format
                    steam_proton_name = proton_version.lower().replace(' - ', '_').replace(' ', '_').replace('-', '_')
                    if not steam_proton_name.startswith('proton'):
                        steam_proton_name = f"proton_{steam_proton_name}"

                logging.info(f"Using user-selected Proton: {steam_proton_name}")
                return steam_proton_name
            except Exception as e:
                logging.warning(f"Invalid user Proton path '{user_proton_path}', falling back to auto: {e}")
                return WineUtils.select_best_proton()

    except Exception as e:
        logging.error(f"Failed to get user Proton preference, using default: {e}")
        return "proton_experimental"

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

# Initialize logger for the module
logger = logging.getLogger(__name__) # Standard logger init

# Helper function to get path to jackify-install-engine
def get_jackify_engine_path():
    # Priority 1: Environment variable override (for AppImage writable engine copy)
    env_engine_path = os.environ.get('JACKIFY_ENGINE_PATH')
    if env_engine_path and os.path.exists(env_engine_path):
        logger.debug(f"Using engine from environment variable: {env_engine_path}")
        return env_engine_path
    
    # Priority 2: AppImage bundle (most specific detection)
    appdir = os.environ.get('APPDIR')
    if appdir:
        # Running inside AppImage
        # Engine is expected at <appdir>/opt/jackify/engine/jackify-engine
        engine_path = os.path.join(appdir, 'opt', 'jackify', 'engine', 'jackify-engine')
        if os.path.exists(engine_path):
            return engine_path
        # Fallback: log warning but continue to other detection methods
        logger.warning(f"AppImage engine not found at expected path: {engine_path}")
    
    # Priority 3: Check if THIS process is actually running from Jackify AppImage
    # (not just inheriting APPDIR from another AppImage context)
    appdir = os.environ.get('APPDIR')
    if appdir and sys.argv[0] and 'jackify' in sys.argv[0].lower() and '/tmp/.mount_' in sys.argv[0]:
        # Only use AppImage path if we're actually running a Jackify AppImage
        engine_path = os.path.join(appdir, 'opt', 'jackify', 'engine', 'jackify-engine')
        if os.path.exists(engine_path):
            return engine_path
        # Log if AppImage engine is missing
        logger.warning(f"AppImage engine not found at expected path: {engine_path}")
    
    # Priority 3: Source execution (development/normal Python environment)
    # Current file is in src/jackify/backend/core/modlist_operations.py
    # Engine is at src/jackify/engine/jackify-engine
    current_file_dir = os.path.dirname(os.path.abspath(__file__))
    # Navigate up from src/jackify/backend/core/ to src/jackify/
    jackify_dir = os.path.dirname(os.path.dirname(current_file_dir))
    engine_path = os.path.join(jackify_dir, 'engine', 'jackify-engine')
    if os.path.exists(engine_path):
        return engine_path
        
    # If all else fails, log error and return the source path anyway
    logger.error(f"jackify-engine not found in any expected location. Tried:")
    logger.error(f"  AppImage: {appdir or 'N/A'}/opt/jackify/engine/jackify-engine") 
    logger.error(f"  Source: {engine_path}")
    logger.error("This will likely cause installation failures.")
    
    # Return source path as final fallback
    return engine_path

class ModlistInstallCLI(
    ModlistOperationsDiscoveryMixin,
    ModlistOperationsConfigurationCLIMixin,
    ModlistOperationsGameDetectionMixin,
    ModlistOperationsNexusMixin,
):
    """CLI interface for modlist installation operations."""
    def __init__(self, menu_handler_or_system_info, steamdeck: bool = False):
        # Support both initialization patterns:
        # 1. ModlistInstallCLI(menu_handler, steamdeck) - CLI frontend pattern
        # 2. ModlistInstallCLI(system_info) - GUI frontend pattern
        
        from ..models.configuration import SystemInfo
        
        if isinstance(menu_handler_or_system_info, SystemInfo):
            # GUI frontend initialization pattern
            self.system_info = menu_handler_or_system_info
            self.steamdeck = self.system_info.is_steamdeck
            
            # Initialize menu_handler for GUI mode
            from ..handlers.menu_handler import MenuHandler
            self.menu_handler = MenuHandler()
        else:
            # CLI frontend initialization pattern
            self.menu_handler = menu_handler_or_system_info
            self.steamdeck = steamdeck
            # Create system_info for CLI mode
            from ..models.configuration import SystemInfo
            self.system_info = SystemInfo(is_steamdeck=steamdeck)
        
        self.protontricks_handler = ProtontricksHandler(self.steamdeck)
        self.shortcut_handler = ShortcutHandler(steamdeck=self.steamdeck)
        self.context = {}
        # Use standard logging (no file handler)
        self.logger = logging.getLogger('jackify-cli')
        
        # Initialize Wabbajack parser for game detection
        self.wabbajack_parser = WabbajackParser()
        
        # Initialize process tracking for cleanup
        self._current_process = None

    _normalize_version_token = staticmethod(normalize_version_token)
    _normalize_modlist_name = staticmethod(normalize_modlist_name)

    def _get_requested_modlist_version(self) -> str | None:
        info = self.context.get("selected_modlist_info") or {}
        return normalize_version_token(info.get("version"))

    def _evaluate_update_candidate(
        self,
        modlist_name: str,
        install_dir: str,
        existing_appid: str | None,
    ) -> tuple[bool, dict]:
        requested_version = self._get_requested_modlist_version()
        return _svc_evaluate(modlist_name, install_dir, existing_appid, requested_version)

    def _find_existing_shortcut_appid(self, modlist_name: str, install_dir: str) -> str | None:
        return _svc_find_appid(modlist_name, install_dir)

    def cleanup(self):
        """Clean up any running jackify-engine process, including its process group
        so tools it spawned (wine, hash utilities, etc.) don't survive it."""
        if self._current_process and self._current_process.poll() is None:
            import signal
            try:
                pgid = os.getpgid(self._current_process.pid)
                os.killpg(pgid, signal.SIGTERM)
            except Exception:
                pass
            try:
                self._current_process.terminate()
                self._current_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    pgid = os.getpgid(self._current_process.pid)
                    os.killpg(pgid, signal.SIGKILL)
                except Exception:
                    pass
                self._current_process.kill()
            except Exception:
                # Process may have already died
                pass
            finally:
                self._current_process = None

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
