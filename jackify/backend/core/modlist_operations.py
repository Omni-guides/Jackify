import os
from pathlib import Path
from typing import Optional, Dict, List, Any, Union
from ..handlers.protontricks_handler import ProtontricksHandler
from ..handlers.shortcut_handler import ShortcutHandler
from ..handlers.menu_handler import MenuHandler, ModlistMenuHandler
from ..handlers.ui_colors import COLOR_PROMPT, COLOR_INFO, COLOR_ERROR, COLOR_RESET, COLOR_SUCCESS, COLOR_WARNING, COLOR_SELECTION
# Standard logging (no file handler) - LoggingHandler import removed
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
# from src.core.compressonator import run_compressonatorcli  # TODO: Implement compressonator integration
from jackify.backend.services.modlist_service import ModlistService
from jackify.backend.models.configuration import SystemInfo
from jackify.backend.handlers.config_handler import ConfigHandler

# UI Colors already imported above

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
    
    # Priority 2: PyInstaller bundle (most specific detection)
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        # Running in a PyInstaller bundle
        # Engine is expected at <bundle_root>/jackify/engine/jackify-engine
        engine_path = os.path.join(sys._MEIPASS, 'jackify', 'engine', 'jackify-engine')
        if os.path.exists(engine_path):
            return engine_path
        # Fallback: log warning but continue to other detection methods
        logger.warning(f"PyInstaller engine not found at expected path: {engine_path}")
    
    # Priority 3: Check if THIS process is actually running from Jackify AppImage
    # (not just inheriting APPDIR from another AppImage like Cursor)
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
    logger.error(f"  PyInstaller: {getattr(sys, '_MEIPASS', 'N/A')}/jackify/engine/jackify-engine")
    logger.error(f"  AppImage: {appdir or 'N/A'}/opt/jackify/engine/jackify-engine") 
    logger.error(f"  Source: {engine_path}")
    logger.error("This will likely cause installation failures.")
    
    # Return source path as final fallback
    return engine_path

class ModlistInstallCLI:
    """CLI interface for modlist installation operations."""
    def __init__(self, menu_handler_or_system_info, steamdeck: bool = False):
        # Support both initialization patterns:
        # 1. ModlistInstallCLI(menu_handler, steamdeck) - CLI frontend pattern
        # 2. ModlistInstallCLI(system_info) - GUI frontend pattern
        
        from ..models.configuration import SystemInfo
        
        if isinstance(menu_handler_or_system_info, SystemInfo):
            # GUI frontend initialization pattern
            system_info = menu_handler_or_system_info
            self.steamdeck = system_info.is_steamdeck
            
            # Initialize menu_handler for GUI mode
            from ..handlers.menu_handler import MenuHandler
            self.menu_handler = MenuHandler()
        else:
            # CLI frontend initialization pattern
            self.menu_handler = menu_handler_or_system_info
            self.steamdeck = steamdeck
        
        self.protontricks_handler = ProtontricksHandler(steamdeck=self.steamdeck)
        self.shortcut_handler = ShortcutHandler(steamdeck=self.steamdeck)
        self.context = {}
        # Use standard logging (no file handler)
        self.logger = logging.getLogger(__name__)
        self.logger.propagate = False # Prevent duplicate logs if root logger is also configured
        
        # Initialize Wabbajack parser for game detection
        self.wabbajack_parser = WabbajackParser()
        
        # Initialize process tracking for cleanup
        self._current_process = None

    def cleanup(self):
        """Clean up any running jackify-engine process"""
        if self._current_process and self._current_process.poll() is None:
            try:
                self._current_process.terminate()
                self._current_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._current_process.kill()
            except Exception:
                # Process may have already died
                pass
            finally:
                self._current_process = None

    def detect_game_type(self, modlist_info: Optional[Dict] = None, wabbajack_file_path: Optional[Path] = None) -> Optional[str]:
        """
        Detect the game type for a modlist installation.
        
        Args:
            modlist_info: Dictionary containing modlist information (for online modlists)
            wabbajack_file_path: Path to .wabbajack file (for local files)
            
        Returns:
            Jackify game type string or None if detection fails
        """
        if wabbajack_file_path:
            # Parse .wabbajack file to get game type
            self.logger.info(f"Detecting game type from .wabbajack file: {wabbajack_file_path}")
            game_type = self.wabbajack_parser.parse_wabbajack_game_type(wabbajack_file_path)
            if game_type:
                self.logger.info(f"Detected game type from .wabbajack file: {game_type}")
                return game_type
            else:
                self.logger.warning(f"Could not detect game type from .wabbajack file: {wabbajack_file_path}")
                return None
        elif modlist_info and 'game' in modlist_info:
            # Use game type from modlist info
            game_name = modlist_info['game'].lower()
            self.logger.info(f"Detecting game type from modlist info: {game_name}")
            
            # Map common game names to Jackify game types
            game_mapping = {
                'skyrim special edition': 'skyrim',
                'skyrim': 'skyrim',
                'fallout 4': 'fallout4',
                'fallout new vegas': 'falloutnv',
                'oblivion': 'oblivion',
                'starfield': 'starfield',
                'oblivion remastered': 'oblivion_remastered'
            }
            
            game_type = game_mapping.get(game_name)
            if game_type:
                self.logger.info(f"Mapped game name '{game_name}' to game type: {game_type}")
                return game_type
            else:
                self.logger.warning(f"Unknown game name in modlist info: {game_name}")
                return None
        else:
            self.logger.warning("No modlist info or .wabbajack file path provided for game detection")
            return None

    def check_game_support(self, game_type: str) -> bool:
        """
        Check if a game type is supported by Jackify's post-install configuration.
        
        Args:
            game_type: Jackify game type string
            
        Returns:
            True if the game is supported, False otherwise
        """
        return self.wabbajack_parser.is_supported_game(game_type)

    def run_discovery_phase(self, context_override=None) -> Optional[Dict]:
        """
        Run the discovery phase: prompt for all required info, and validate inputs.
        Returns a context dict with all collected info, or None if cancelled.
        Accepts context_override for pre-filled values (e.g., for Tuxborn/machineid flow).
        """
        self.logger.info("Starting modlist discovery phase (restored logic).")
        print(f"\n{COLOR_PROMPT}--- Wabbajack Modlist Install: Discovery Phase ---{COLOR_RESET}")

        if context_override:
            self.context.update(context_override)
            if 'resolution' in context_override:
                self.context['resolution'] = context_override['resolution']
        else:
            self.context = {}

        is_gui_mode = os.environ.get('JACKIFY_GUI_MODE') == '1'
        # Only require game_type for non-Tuxborn workflows
        if self.context.get('machineid'):
            required_keys = ['modlist_name', 'install_dir', 'download_dir', 'nexus_api_key']
        else:
            required_keys = ['modlist_name', 'install_dir', 'download_dir', 'nexus_api_key', 'game_type']
        has_modlist = self.context.get('modlist_value') or self.context.get('machineid')
        missing = [k for k in required_keys if not self.context.get(k)]
        if is_gui_mode:
            if missing or not has_modlist:
                print(f"ERROR: Missing required arguments for GUI workflow: {', '.join(missing)}")
                if not has_modlist:
                    print("ERROR: Missing modlist_value or machineid for GUI workflow.")
                print("This workflow must be fully non-interactive. Please report this as a bug if you see this message.")
                return None
            self.logger.info("All required context present in GUI mode, skipping prompts.")
            return self.context

        # Get engine path using the helper
        engine_executable = get_jackify_engine_path()
        self.logger.debug(f"Engine executable path: {engine_executable}")

        if not os.path.exists(engine_executable):
            self.logger.error(f"jackify-install-engine not found at {engine_executable}")
            print(f"{COLOR_ERROR}Error: jackify-install-engine not found at expected location.{COLOR_RESET}")
            print(f"{COLOR_INFO}Expected: {engine_executable}{COLOR_RESET}")
            return None
        
        engine_dir = os.path.dirname(engine_executable)

        # 1. Prompt for modlist source (unless using machineid from context_override)
        if 'machineid' not in self.context:
            print("\n" + "-" * 28) # Separator
            print(f"{COLOR_PROMPT}How would you like to select your modlist?{COLOR_RESET}")
            print(f"{COLOR_SELECTION}1.{COLOR_RESET} Select from a list of available modlists")
            print(f"{COLOR_SELECTION}2.{COLOR_RESET} Provide the path to a .wabbajack file on disk")
            print(f"{COLOR_SELECTION}0.{COLOR_RESET} Cancel and return to previous menu")
            source_choice = input(f"{COLOR_PROMPT}Enter your selection (0-2): {COLOR_RESET}").strip()
            self.logger.debug(f"User selected modlist source option: {source_choice}")

            if source_choice == '1':
                self.context['modlist_source_type'] = 'online_list'
                print(f"\n{COLOR_INFO}Fetching available modlists... This may take a moment.{COLOR_RESET}")
                try:
                    # Use the same backend service as the GUI
                    is_steamdeck = False
                    if os.path.exists('/etc/os-release'):
                        with open('/etc/os-release') as f:
                            if 'steamdeck' in f.read().lower():
                                is_steamdeck = True
                    system_info = SystemInfo(is_steamdeck=is_steamdeck)
                    modlist_service = ModlistService(system_info)

                    # Define categories and their backend keys
                    categories = [
                        ("Skyrim", "skyrim"),
                        ("Fallout 4", "fallout4"),
                        ("Fallout New Vegas", "falloutnv"),
                        ("Oblivion", "oblivion"),
                        ("Starfield", "starfield"),
                        ("Oblivion Remastered", "oblivion_remastered"),
                        ("Other Games", "other")
                    ]
                    grouped_modlists = {}
                    for label, key in categories:
                        grouped_modlists[label] = modlist_service.list_modlists(game_type=key)

                    selected_modlist_info = None
                    while not selected_modlist_info:
                        print(f"\n{COLOR_PROMPT}Select a game category:{COLOR_RESET}")
                        category_display_map = {}
                        display_idx = 1
                        for label, _ in categories:
                            modlists = grouped_modlists[label]
                            # Always show Oblivion Remastered, even if empty
                            if label == "Oblivion Remastered" or modlists:
                                print(f"  {COLOR_SELECTION}{display_idx}.{COLOR_RESET} {label} ({len(modlists)} modlists)")
                                category_display_map[str(display_idx)] = label
                                display_idx += 1
                        if display_idx == 1:
                            print(f"{COLOR_WARNING}No modlists found to display after grouping. Engine output might be empty or filtered entirely.{COLOR_RESET}")
                            return None
                        print(f"  {COLOR_SELECTION}0.{COLOR_RESET} Cancel")
                        game_cat_choice = input(f"{COLOR_PROMPT}Enter selection: {COLOR_RESET}").strip()
                        if game_cat_choice == '0':
                            self.logger.info("User cancelled game category selection.")
                            return None
                        actual_label = category_display_map.get(game_cat_choice)
                        if not actual_label:
                            print(f"{COLOR_ERROR}Invalid selection. Please try again.{COLOR_RESET}")
                            continue
                        modlist_group_for_game = sorted(grouped_modlists[actual_label], key=lambda x: x.id.lower())
                        print(f"\n{COLOR_SUCCESS}Available Modlists for {actual_label}:{COLOR_RESET}")
                        for idx, m_detail in enumerate(modlist_group_for_game, 1):
                            # Show game name for Other Games
                            if actual_label == "Other Games":
                                print(f"  {COLOR_SELECTION}{idx}.{COLOR_RESET} {m_detail.id} ({m_detail.game})")
                            else:
                                print(f"  {COLOR_SELECTION}{idx}.{COLOR_RESET} {m_detail.id}")
                        print(f"  {COLOR_SELECTION}0.{COLOR_RESET} Back to game categories")
                        while True:
                            mod_choice_idx_str = input(f"{COLOR_PROMPT}Select modlist (or 0): {COLOR_RESET}").strip()
                            if mod_choice_idx_str == '0':
                                break
                            if mod_choice_idx_str.isdigit():
                                mod_idx = int(mod_choice_idx_str) - 1
                                if 0 <= mod_idx < len(modlist_group_for_game):
                                    selected_modlist_info = {
                                        'id': modlist_group_for_game[mod_idx].id,
                                        'game': modlist_group_for_game[mod_idx].game,
                                        'machine_url': getattr(modlist_group_for_game[mod_idx], 'machine_url', modlist_group_for_game[mod_idx].id)
                                    }
                                    self.context['modlist_source'] = 'identifier'
                                    # Use machine_url for installation, display name for suggestions
                                    self.context['modlist_value'] = selected_modlist_info.get('machine_url', selected_modlist_info['id'])
                                    self.context['modlist_game'] = selected_modlist_info['game']
                                    self.context['modlist_name_suggestion'] = selected_modlist_info['id'].split('/')[-1]
                                    self.logger.info(f"User selected online modlist: {selected_modlist_info}")
                                    break
                                else:
                                    print(f"{COLOR_ERROR}Invalid modlist number.{COLOR_RESET}")
                            else:
                                print(f"{COLOR_ERROR}Invalid input. Please enter a number.{COLOR_RESET}")
                        if selected_modlist_info:
                            break
                except Exception as e:
                    self.logger.error(f"Unexpected error fetching modlists: {e}", exc_info=True)
                    print(f"{COLOR_ERROR}Unexpected error fetching modlists: {e}{COLOR_RESET}")
                    return None

            elif source_choice == '2':
                self.context['modlist_source_type'] = 'local_file'
                print(f"\n{COLOR_PROMPT}Please provide the path to your .wabbajack file (tab-completion supported).{COLOR_RESET}")
                modlist_path = self.menu_handler.get_existing_file_path(
                    prompt_message="Enter the path to your .wabbajack file (or 'q' to cancel):",
                    extension_filter=".wabbajack", # Ensure this is the exact filter used by the method
                    no_header=True # To avoid re-printing a header if get_existing_file_path has one
                )
                if modlist_path is None: # Assumes get_existing_file_path returns None on cancel/'q'
                    self.logger.info("User cancelled .wabbajack file selection.")
                    print(f"{COLOR_INFO}Cancelled by user.{COLOR_RESET}")
                    return None
                
                self.context['modlist_source'] = 'path' # For install command
                self.context['modlist_value'] = str(modlist_path)
                # Suggest a name based on the file
                self.context['modlist_name_suggestion'] = Path(modlist_path).stem 
                self.logger.info(f"User selected local .wabbajack file: {modlist_path}")

            elif source_choice == '0':
                self.logger.info("User cancelled modlist source selection.")
                print(f"{COLOR_INFO}Returning to previous menu.{COLOR_RESET}")
                return None
            else:
                self.logger.warning(f"Invalid modlist source choice: {source_choice}")
                print(f"{COLOR_ERROR}Invalid selection. Please try again.{COLOR_RESET}")
                return self.run_discovery_phase() # Re-prompt

        # --- Prompts for install_dir, download_dir, modlist_name, api_key ---
        # (This part is largely similar to the restored version, adapt as needed)
        # It will use self.context['modlist_name_suggestion'] if available.

        # 2. Prompt for modlist name (skip if 'modlist_name' already in context from override)
        if 'modlist_name' not in self.context or not self.context['modlist_name']:
            default_name = self.context.get('modlist_name_suggestion', 'MyModlist')
            print("\n" + "-" * 28)
            print(f"{COLOR_PROMPT}Enter a name for this modlist installation in Steam.{COLOR_RESET}")
            print(f"{COLOR_INFO}(This will be the shortcut name. Default: {default_name}){COLOR_RESET}")
            modlist_name_input = input(f"{COLOR_PROMPT}Modlist Name (or 'q' to cancel): {COLOR_RESET}").strip()
            if not modlist_name_input: # User hit enter for default
                modlist_name = default_name
            elif modlist_name_input.lower() == 'q':
                self.logger.info("User cancelled at modlist name prompt.")
                return None
            else:
                modlist_name = modlist_name_input
            self.context['modlist_name'] = modlist_name
        self.logger.debug(f"Modlist name set to: {self.context['modlist_name']}")

        # 3. Prompt for install directory
        if 'install_dir' not in self.context:
            # Use configurable base directory
            config_handler = ConfigHandler()
            base_install_dir = Path(config_handler.get_modlist_install_base_dir())
            default_install_dir = base_install_dir / self.context['modlist_name']
            print("\n" + "-" * 28)
            print(f"{COLOR_PROMPT}Enter the main installation directory for '{self.context['modlist_name']}'.{COLOR_RESET}")
            print(f"{COLOR_INFO}(Default: {default_install_dir}){COLOR_RESET}")
            install_dir_path = self.menu_handler.get_directory_path(
                prompt_message=f"{COLOR_PROMPT}Install directory (or 'q' to cancel, Enter for default): {COLOR_RESET}",
                default_path=default_install_dir,
                create_if_missing=True,
                no_header=True
            )
            if install_dir_path is None:
                self.logger.info("User cancelled at install directory prompt.")
                return None
            self.context['install_dir'] = install_dir_path 
        self.logger.debug(f"Install directory context set to: {self.context['install_dir']}")

        # 4. Prompt for download directory
        if 'download_dir' not in self.context:
            # Use configurable base directory for downloads
            config_handler = ConfigHandler()
            base_download_dir = Path(config_handler.get_modlist_downloads_base_dir())
            default_download_dir = base_download_dir / self.context['modlist_name']
            
            print("\n" + "-" * 28)
            print(f"{COLOR_PROMPT}Enter the downloads directory for modlist archives.{COLOR_RESET}")
            print(f"{COLOR_INFO}(Default: {default_download_dir}){COLOR_RESET}")
            download_dir_path = self.menu_handler.get_directory_path(
                prompt_message=f"{COLOR_PROMPT}Download directory (or 'q' to cancel, Enter for default): {COLOR_RESET}",
                default_path=default_download_dir,
                create_if_missing=True,
                no_header=True
            )
            if download_dir_path is None:
                self.logger.info("User cancelled at download directory prompt.")
                return None
            self.context['download_dir'] = download_dir_path
        self.logger.debug(f"Download directory context set to: {self.context['download_dir']}")
        
        # 5. Prompt for Nexus API key (skip if in context and valid)
        if 'nexus_api_key' not in self.context or not self.context.get('nexus_api_key'):
            from jackify.backend.services.api_key_service import APIKeyService
            api_key_service = APIKeyService()
            saved_key = api_key_service.get_saved_api_key()
            api_key = None
            if saved_key:
                print("\n" + "-" * 28)
                print(f"{COLOR_INFO}A Nexus API Key is already saved.{COLOR_RESET}")
                use_saved = input(f"{COLOR_PROMPT}Use the saved API key? [Y/n]: {COLOR_RESET}").strip().lower()
                if use_saved in ('', 'y', 'yes'):
                    api_key = saved_key
                else:
                    new_key = input(f"{COLOR_PROMPT}Enter a new Nexus API Key (or press Enter to keep the saved one): {COLOR_RESET}").strip()
                    if new_key:
                        api_key = new_key
                        replace = input(f"{COLOR_PROMPT}Replace the saved key with this one? [y/N]: {COLOR_RESET}").strip().lower()
                        if replace == 'y':
                            if api_key_service.save_api_key(api_key):
                                print(f"{COLOR_SUCCESS}API key saved successfully.{COLOR_RESET}")
                            else:
                                print(f"{COLOR_WARNING}Failed to save API key. Using for this session only.{COLOR_RESET}")
                        else:
                            print(f"{COLOR_INFO}Using new key for this session only. Saved key unchanged.{COLOR_RESET}")
                    else:
                        api_key = saved_key
            else:
                print("\n" + "-" * 28)
                print(f"{COLOR_INFO}A Nexus Mods API key is required for downloading mods.{COLOR_RESET}")
                print(f"{COLOR_INFO}You can get your personal key at: {COLOR_SELECTION}https://www.nexusmods.com/users/myaccount?tab=api{COLOR_RESET}")
                print(f"{COLOR_WARNING}Your API Key is NOT saved locally. It is used only for this session unless you choose to save it.{COLOR_RESET}")
                api_key = input(f"{COLOR_PROMPT}Enter Nexus API Key (or 'q' to cancel): {COLOR_RESET}").strip()
                if not api_key or api_key.lower() == 'q':
                    self.logger.info("User cancelled or provided no API key.")
                    return None
                save = input(f"{COLOR_PROMPT}Would you like to save this API key for future use? [y/N]: {COLOR_RESET}").strip().lower()
                if save == 'y':
                    if api_key_service.save_api_key(api_key):
                        print(f"{COLOR_SUCCESS}API key saved successfully.{COLOR_RESET}")
                    else:
                        print(f"{COLOR_WARNING}Failed to save API key. Using for this session only.{COLOR_RESET}")
                else:
                    print(f"{COLOR_INFO}Using API key for this session only. It will not be saved.{COLOR_RESET}")
            
            # Set the API key in context regardless of which path was taken
            self.context['nexus_api_key'] = api_key
        self.logger.debug(f"NEXUS_API_KEY is set in environment for engine (presence check).")

        # Display summary and confirm
        self._display_summary() # Ensure this method exists or implement it

        # --- Unsupported game warning and Enter-to-continue prompt ---
        # Determine the game type and name
        game_type = None
        game_name = None
        if self.context.get('modlist_source_type') == 'online_list':
            game_name = self.context.get('modlist_game', '')
            game_mapping = {
                'skyrim special edition': 'skyrim',
                'skyrim': 'skyrim',
                'fallout 4': 'fallout4',
                'fallout new vegas': 'falloutnv',
                'oblivion': 'oblivion',
                'starfield': 'starfield',
                'oblivion remastered': 'oblivion_remastered'
            }
            game_type = game_mapping.get(game_name.lower())
            if not game_type:
                game_type = 'unknown'
        elif self.context.get('modlist_source_type') == 'local_file':
            # Use the parser to get the game type from the .wabbajack file
            wabbajack_path = self.context.get('modlist_value')
            if wabbajack_path:
                result = self.wabbajack_parser.parse_wabbajack_game_type(Path(wabbajack_path))
                if result:
                    if isinstance(result, tuple):
                        game_type, raw_game_type = result
                        game_name = raw_game_type if game_type == 'unknown' else game_type
                    else:
                        game_type = result
                        game_name = game_type
        # If unsupported, show warning and require Enter
        if game_type and not self.wabbajack_parser.is_supported_game(game_type):
            print("\n" + "─"*46)
            print("\u26A0\uFE0F  Game Support Notice\n")
            print(f"You are about to install a modlist for: {game_name or 'Unknown'}\n")
            print("Jackify does not provide post-install configuration for this game.")
            print("You can still install and use the modlist, but you will need to manually set up Steam shortcuts and other steps after installation.\n")
            print("Press [Enter] to continue, or [Ctrl+C] to cancel.")
            print("─"*46 + "\n")
            try:
                input()
            except KeyboardInterrupt:
                print(f"{COLOR_INFO}Installation cancelled by user.{COLOR_RESET}")
                return None

        if self.context.get('skip_confirmation'):
            confirm = 'y'
        else:
            confirm = input(f"{COLOR_PROMPT}Proceed with installation using these settings? (y/N): {COLOR_RESET}").strip().lower()
        if confirm != 'y':
            self.logger.info("User cancelled at final confirmation.")
            print(f"{COLOR_INFO}Installation cancelled by user.{COLOR_RESET}")
            return None
        
        self.logger.info("Discovery phase complete.") # Log completion first
        
        # Create a copy of the context for logging, so we don't alter the original
        context_for_logging = self.context.copy()
        if 'nexus_api_key' in context_for_logging and context_for_logging['nexus_api_key'] is not None:
            context_for_logging['nexus_api_key'] = "[REDACTED]" # Redact the API key for logging
            
        self.logger.info(f"Context: {context_for_logging}") # Log the redacted context
        return self.context

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
        
        if self.context.get('nexus_api_key'):
            print(f"Nexus API Key: [SET]")
        else:
            print(f"Nexus API Key: [NOT SET - WILL LIKELY FAIL]")
        print(f"{COLOR_INFO}----------------------------------------{COLOR_RESET}")

    def configuration_phase(self):
        """
        Run the configuration phase: execute the Linux-native Jackify Install Engine.
        """
        import os
        import subprocess
        import time
        import sys
        from pathlib import Path
                            # UI Colors already imported at module level
        print(f"\n{COLOR_PROMPT}--- Configuration Phase: Installing Modlist ---{COLOR_RESET}")
        start_time = time.time()

        # --- BEGIN: TEE LOGGING SETUP & LOG ROTATION ---
        log_dir = Path.home() / "Jackify" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        workflow_log_path = log_dir / "Modlist_Install_workflow.log"
        # Log rotation: keep last 3 logs, 1MB each (adjust as needed)
        max_logs = 3
        max_size = 1024 * 1024  # 1MB
        if workflow_log_path.exists() and workflow_log_path.stat().st_size > max_size:
            for i in range(max_logs, 0, -1):
                prev = log_dir / f"Modlist_Install_workflow.log.{i-1}" if i > 1 else workflow_log_path
                dest = log_dir / f"Modlist_Install_workflow.log.{i}"
                if prev.exists():
                    if dest.exists():
                        dest.unlink()
                    prev.rename(dest)
        workflow_log = open(workflow_log_path, 'a')
        class TeeStdout:
            def __init__(self, *files):
                self.files = files
            def write(self, data):
                for f in self.files:
                    f.write(data)
                    f.flush()
            def flush(self):
                for f in self.files:
                    f.flush()
        orig_stdout, orig_stderr = sys.stdout, sys.stderr
        sys.stdout = TeeStdout(sys.stdout, workflow_log)
        sys.stderr = TeeStdout(sys.stderr, workflow_log)
        # --- END: TEE LOGGING SETUP & LOG ROTATION ---
        try:
            # --- Process Paths from context ---
            install_dir_context = self.context['install_dir']
            if isinstance(install_dir_context, tuple):
                actual_install_path = Path(install_dir_context[0])
                if install_dir_context[1]: # Second element is True if creation was intended
                    self.logger.info(f"Creating install directory as it was marked for creation: {actual_install_path}")
                    actual_install_path.mkdir(parents=True, exist_ok=True)
            else: # Should be a Path object or string already
                actual_install_path = Path(install_dir_context)
            install_dir_str = str(actual_install_path)
            self.logger.debug(f"Processed install directory for engine: {install_dir_str}")

            download_dir_context = self.context['download_dir']
            if isinstance(download_dir_context, tuple):
                actual_download_path = Path(download_dir_context[0])
                if download_dir_context[1]: # Second element is True if creation was intended
                    self.logger.info(f"Creating download directory as it was marked for creation: {actual_download_path}")
                    actual_download_path.mkdir(parents=True, exist_ok=True)
            else: # Should be a Path object or string already
                actual_download_path = Path(download_dir_context)
            download_dir_str = str(actual_download_path)
            self.logger.debug(f"Processed download directory for engine: {download_dir_str}")
            # --- End Process Paths ---

            modlist_arg = self.context.get('modlist_value') or self.context.get('machineid')
            machineid = self.context.get('machineid')
            api_key = self.context.get('nexus_api_key')

            # Path to the engine binary
            engine_path = get_jackify_engine_path()
            engine_dir = os.path.dirname(engine_path)
            if not os.path.isfile(engine_path) or not os.access(engine_path, os.X_OK):
                print(f"{COLOR_ERROR}Jackify Install Engine not found or not executable at: {engine_path}{COLOR_RESET}")
                return

            # --- Patch for GUI/auto: always set modlist_source to 'identifier' if not set, and ensure modlist_value is present ---
            if os.environ.get('JACKIFY_GUI_MODE') == '1':
                if not self.context.get('modlist_source'):
                    self.context['modlist_source'] = 'identifier'
                if not self.context.get('modlist_value'):
                    print(f"{COLOR_ERROR}ERROR: modlist_value is missing in context for GUI workflow!{COLOR_RESET}")
                    self.logger.error("modlist_value is missing in context for GUI workflow!")
                    return
            # --- End Patch ---

            # Build command
            cmd = [engine_path, 'install']
            # Determine if this is a local .wabbajack file or an online modlist
            modlist_value = self.context.get('modlist_value')
            if modlist_value and modlist_value.endswith('.wabbajack') and os.path.isfile(modlist_value):
                cmd += ['-w', modlist_value]
            elif modlist_value:
                cmd += ['-m', modlist_value]
            elif self.context.get('machineid'):
                cmd += ['-m', self.context['machineid']]
            cmd += ['-o', install_dir_str, '-d', download_dir_str]

            # Store original environment values to restore later
            original_env_values = {
                'NEXUS_API_KEY': os.environ.get('NEXUS_API_KEY'),
                'DOTNET_SYSTEM_GLOBALIZATION_INVARIANT': os.environ.get('DOTNET_SYSTEM_GLOBALIZATION_INVARIANT')
            }

            try:
                # Temporarily modify current process's environment
                if api_key:
                    os.environ['NEXUS_API_KEY'] = api_key
                    self.logger.debug(f"Temporarily set os.environ['NEXUS_API_KEY'] for engine call using session-provided key.")
                elif 'NEXUS_API_KEY' in os.environ: # api_key is None/empty, but a system key might exist
                    self.logger.debug(f"Session API key not provided. Temporarily removing inherited NEXUS_API_KEY ('{'[REDACTED]' if os.environ.get('NEXUS_API_KEY') else 'None'}') from os.environ for engine call to ensure it is not used.")
                    del os.environ['NEXUS_API_KEY'] 
                # If api_key is None and NEXUS_API_KEY was not in os.environ, it remains unset, which is correct.

                os.environ['DOTNET_SYSTEM_GLOBALIZATION_INVARIANT'] = "1"
                self.logger.debug(f"Temporarily set os.environ['DOTNET_SYSTEM_GLOBALIZATION_INVARIANT'] = '1' for engine call.")
                
                self.logger.info("Environment prepared for jackify-engine install process by modifying os.environ.")
                self.logger.debug(f"NEXUS_API_KEY in os.environ (pre-call): {'[SET]' if os.environ.get('NEXUS_API_KEY') else '[NOT SET]'}")
                
                pretty_cmd = ' '.join([f'"{arg}"' if ' ' in arg else arg for arg in cmd])
                print(f"{COLOR_INFO}Launching Jackify Install Engine with command:{COLOR_RESET} {pretty_cmd}")
                
                # Temporarily increase file descriptor limit for engine process
                from jackify.backend.handlers.subprocess_utils import increase_file_descriptor_limit
                success, old_limit, new_limit, message = increase_file_descriptor_limit()
                if success:
                    self.logger.debug(f"File descriptor limit: {message}")
                else:
                    self.logger.warning(f"File descriptor limit: {message}")
                
                # Popen now inherits the modified os.environ because env=None
                # Store process reference for cleanup
                self._current_process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=False, env=None, cwd=engine_dir)
                proc = self._current_process
                
                # Read output in binary mode to properly handle carriage returns
                buffer = b''
                while True:
                    chunk = proc.stdout.read(1)
                    if not chunk:
                        break
                    buffer += chunk
                    
                    # Process complete lines or carriage return updates
                    if chunk == b'\n':
                        # Complete line - decode and print
                        line = buffer.decode('utf-8', errors='replace')
                        print(line, end='')
                        buffer = b''
                    elif chunk == b'\r':
                        # Carriage return - decode and print without newline
                        line = buffer.decode('utf-8', errors='replace')
                        print(line, end='')
                        sys.stdout.flush()
                        buffer = b''
                
                # Print any remaining buffer content
                if buffer:
                    line = buffer.decode('utf-8', errors='replace')
                    print(line, end='')
                
                proc.wait()
                # Clear process reference after completion
                self._current_process = None
                if proc.returncode != 0:
                    print(f"{COLOR_ERROR}Jackify Install Engine exited with code {proc.returncode}.{COLOR_RESET}")
                    self.logger.error(f"Engine exited with code {proc.returncode}.")
                    return # Configuration phase failed
                self.logger.info(f"Engine completed with code {proc.returncode}.")
            except Exception as e:
                error_message = str(e)
                print(f"{COLOR_ERROR}Error running Jackify Install Engine: {error_message}{COLOR_RESET}\n")
                self.logger.error(f"Exception running engine: {error_message}", exc_info=True)
                
                # Check for file descriptor limit issues and attempt to handle them
                try:
                    from jackify.backend.services.resource_manager import handle_file_descriptor_error
                    if any(indicator in error_message.lower() for indicator in ['too many open files', 'emfile', 'resource temporarily unavailable']):
                        result = handle_file_descriptor_error(error_message, "Jackify Install Engine execution")
                        if result['auto_fix_success']:
                            print(f"{COLOR_INFO}File descriptor limit increased automatically. {result['recommendation']}{COLOR_RESET}")
                            self.logger.info(f"File descriptor limit increased automatically. {result['recommendation']}")
                        elif result['error_detected']:
                            print(f"{COLOR_WARNING}File descriptor limit issue detected. {result['recommendation']}{COLOR_RESET}")
                            self.logger.warning(f"File descriptor limit issue detected but automatic fix failed. {result['recommendation']}")
                            if result['manual_instructions']:
                                distro = result['manual_instructions']['distribution']
                                print(f"{COLOR_INFO}Manual ulimit increase instructions available for {distro} distribution{COLOR_RESET}")
                                self.logger.info(f"Manual ulimit increase instructions available for {distro} distribution")
                except Exception as resource_error:
                    self.logger.debug(f"Error checking for resource limit issues: {resource_error}")
                
                return # Configuration phase failed
            finally:
                # Restore original environment state
                for key, original_value in original_env_values.items():
                    current_value_in_os_environ = os.environ.get(key) # Value after Popen and before our restoration for this key

                    # Determine display values for logging, redacting NEXUS_API_KEY
                    display_original_value = f"'[REDACTED]'" if key == 'NEXUS_API_KEY' else f"'{original_value}'"
                    # display_current_value_before_restore = f"'[REDACTED]'" if key == 'NEXUS_API_KEY' else f"'{current_value_in_os_environ}'"

                    if original_value is not None:
                        # Original value existed. We must restore it.
                        if current_value_in_os_environ != original_value:
                            os.environ[key] = original_value
                            self.logger.debug(f"Restored os.environ['{key}'] to its original value: {display_original_value}.")
                        else:
                            # If current value is already the original, ensure it's correctly set (os.environ[key] = original_value is harmless)
                            os.environ[key] = original_value # Ensure it is set
                            self.logger.debug(f"os.environ['{key}'] ('{display_original_value}') matched original value. Ensured restoration.")
                    else:
                        # Original value was None (key was not in os.environ initially).
                        if key in os.environ: # If it's in os.environ now, it means we must have set it or it was set by other means.
                            self.logger.debug(f"Original os.environ['{key}'] was not set. Removing current value ('{'[REDACTED]' if os.environ.get(key) and key == 'NEXUS_API_KEY' else os.environ.get(key)}') that was set for the call.")
                            del os.environ[key]
                        # If original_value was None and key is not in os.environ now, nothing to do.

        except Exception as e:
            error_message = str(e)
            print(f"{COLOR_ERROR}Error during Tuxborn installation workflow: {error_message}{COLOR_RESET}\n")
            self.logger.error(f"Exception in Tuxborn workflow: {error_message}", exc_info=True)
            
            # Check for file descriptor limit issues and attempt to handle them
            try:
                from jackify.backend.services.resource_manager import handle_file_descriptor_error
                if any(indicator in error_message.lower() for indicator in ['too many open files', 'emfile', 'resource temporarily unavailable']):
                    result = handle_file_descriptor_error(error_message, "Tuxborn installation workflow")
                    if result['auto_fix_success']:
                        print(f"{COLOR_INFO}File descriptor limit increased automatically. {result['recommendation']}{COLOR_RESET}")
                        self.logger.info(f"File descriptor limit increased automatically. {result['recommendation']}")
                    elif result['error_detected']:
                        print(f"{COLOR_WARNING}File descriptor limit issue detected. {result['recommendation']}{COLOR_RESET}")
                        self.logger.warning(f"File descriptor limit issue detected but automatic fix failed. {result['recommendation']}")
                        if result['manual_instructions']:
                            distro = result['manual_instructions']['distribution']
                            print(f"{COLOR_INFO}Manual ulimit increase instructions available for {distro} distribution{COLOR_RESET}")
                            self.logger.info(f"Manual ulimit increase instructions available for {distro} distribution")
            except Exception as resource_error:
                self.logger.debug(f"Error checking for resource limit issues: {resource_error}")
            
            return
        finally:
            # --- BEGIN: RESTORE STDOUT/STDERR ---
            sys.stdout = orig_stdout
            sys.stderr = orig_stderr
            workflow_log.close()
            # --- END: RESTORE STDOUT/STDERR ---

        elapsed = int(time.time() - start_time)
        print(f"\nElapsed time: {elapsed//3600:02d}:{(elapsed%3600)//60:02d}:{elapsed%60:02d} (hh:mm:ss)\n")
        print(f"{COLOR_INFO}Your modlist has been installed to: {install_dir_str}{COLOR_RESET}\n")
        if self.context.get('machineid') != 'Tuxborn/Tuxborn':
            print(f"{COLOR_WARNING}Only Skyrim, Fallout 4, Fallout New Vegas, Oblivion, Starfield, and Oblivion Remastered modlists are compatible with Jackify's post-install configuration. Any modlist can be downloaded/installed, but only these games are supported for automated configuration.{COLOR_RESET}")
        
        self.logger.debug("configuration_phase: Starting post-install game detection...")
        
        # After install, use self.context['modlist_game'] to determine if configuration should be offered
        # After install, detect game type from ModOrganizer.ini
        modorganizer_ini = os.path.join(install_dir_str, "ModOrganizer.ini")
        detected_game = None
        self.logger.debug(f"configuration_phase: Looking for ModOrganizer.ini at: {modorganizer_ini}")
        if os.path.isfile(modorganizer_ini):
            self.logger.debug("configuration_phase: Found ModOrganizer.ini, detecting game...")
            from ..handlers.modlist_handler import ModlistHandler
            handler = ModlistHandler({}, steamdeck=self.steamdeck)
            handler.modlist_ini = modorganizer_ini
            handler.modlist_dir = install_dir_str
            if handler._detect_game_variables():
                detected_game = handler.game_var_full
                self.logger.debug(f"configuration_phase: Detected game: {detected_game}")
            else:
                self.logger.debug("configuration_phase: Failed to detect game variables")
        else:
            self.logger.debug("configuration_phase: ModOrganizer.ini not found")
            
        supported_games = ["Skyrim Special Edition", "Fallout 4", "Fallout New Vegas", "Oblivion", "Starfield", "Oblivion Remastered", "Enderal"]
        is_tuxborn = self.context.get('machineid') == 'Tuxborn/Tuxborn'
        self.logger.debug(f"configuration_phase: detected_game='{detected_game}', is_tuxborn={is_tuxborn}")
        self.logger.debug(f"configuration_phase: Checking condition: (detected_game in supported_games) or is_tuxborn")
        self.logger.debug(f"configuration_phase: Result: {(detected_game in supported_games) or is_tuxborn}")
        
        if (detected_game in supported_games) or is_tuxborn:
            self.logger.debug("configuration_phase: Entering Steam configuration workflow...")
            shortcut_name = self.context.get('modlist_name')
            self.logger.debug(f"configuration_phase: shortcut_name from context: '{shortcut_name}'")
            
            if is_tuxborn and not shortcut_name:
                self.logger.warning("Tuxborn is true, but shortcut_name (modlist_name in context) is missing. Defaulting to 'Tuxborn Automatic Installer'")
                shortcut_name = "Tuxborn Automatic Installer" # Provide a fallback default
            elif not shortcut_name: # For non-Tuxborn, prompt if missing
                print("\n" + "-" * 28)
                print(f"{COLOR_PROMPT}Please provide a name for the Steam shortcut for '{self.context.get('modlist_name', 'this modlist')}'.{COLOR_RESET}")
                raw_shortcut_name = input(f"{COLOR_PROMPT}Steam Shortcut Name (or 'q' to cancel): {COLOR_RESET} ").strip()
                if raw_shortcut_name.lower() == 'q' or not raw_shortcut_name:
                    self.logger.debug("configuration_phase: User cancelled shortcut name input")
                    return
                shortcut_name = raw_shortcut_name
            
            self.logger.debug(f"configuration_phase: Final shortcut_name: '{shortcut_name}'")
            
            # Check if GUI mode to skip interactive prompts
            is_gui_mode = os.environ.get('JACKIFY_GUI_MODE') == '1'
            self.logger.debug(f"configuration_phase: is_gui_mode={is_gui_mode}")
            
            if not is_gui_mode:
                self.logger.debug("configuration_phase: Not in GUI mode, prompting user for configuration...")
                # Prompt user if they want to configure Steam shortcut now
                print("\n" + "-" * 28)
                print(f"{COLOR_PROMPT}Would you like to add '{shortcut_name}' to Steam and configure it now?{COLOR_RESET}")
                configure_choice = input(f"{COLOR_PROMPT}Configure now? (Y/n): {COLOR_RESET}").strip().lower()
                self.logger.debug(f"configuration_phase: User choice: '{configure_choice}'")
                
                if configure_choice == 'n':
                    print(f"{COLOR_INFO}Skipping Steam configuration. You can configure it later using 'Configure New Modlist'.{COLOR_RESET}")
                    self.logger.debug("configuration_phase: User chose to skip Steam configuration")
                    return
            else:
                self.logger.debug("configuration_phase: In GUI mode, proceeding automatically...")
            
            self.logger.debug("configuration_phase: Proceeding with Steam configuration...")
            
            # Proceed with Steam configuration
            self.logger.info(f"Starting Steam configuration for '{shortcut_name}'")
            
            # Step 1: Create Steam shortcut first
            mo2_exe_path = os.path.join(install_dir_str, 'ModOrganizer.exe')
            
            # Check if we should use automated prefix creation
            use_automated_prefix = os.environ.get('JACKIFY_USE_AUTOMATED_PREFIX', '1') == '1'
            
            if use_automated_prefix:
                # Use automated prefix service for modern workflow
                print(f"\n{COLOR_INFO}Using automated Steam setup workflow...{COLOR_RESET}")
                
                from ..services.automated_prefix_service import AutomatedPrefixService
                prefix_service = AutomatedPrefixService()
                
                # Define progress callback for CLI with jackify-engine style timestamps
                import time
                start_time = time.time()
                
                def progress_callback(message):
                    elapsed = time.time() - start_time
                    hours = int(elapsed // 3600)
                    minutes = int((elapsed % 3600) // 60)
                    seconds = int(elapsed % 60)
                    timestamp = f"[{hours:02d}:{minutes:02d}:{seconds:02d}]"
                    print(f"{COLOR_INFO}{timestamp} {message}{COLOR_RESET}")
                
                # Run the automated workflow
                # Detect Steam Deck once and pass through to workflow
                try:
                    import os
                    _is_steamdeck = False
                    if os.path.exists('/etc/os-release'):
                        with open('/etc/os-release') as f:
                            if 'steamdeck' in f.read().lower():
                                _is_steamdeck = True
                except Exception:
                    _is_steamdeck = False
                result = prefix_service.run_working_workflow(
                    shortcut_name, install_dir_str, mo2_exe_path, progress_callback, steamdeck=_is_steamdeck
                )
                
                # Handle the result
                if isinstance(result, tuple) and len(result) == 3:
                    if result[0] == "CONFLICT":
                        # Handle conflict
                        conflicts = result[1]
                        print(f"\n{COLOR_WARNING}Found existing Steam shortcut(s) with the same name and path:{COLOR_RESET}")
                        
                        for i, conflict in enumerate(conflicts, 1):
                            print(f"  {i}. Name: {conflict['name']}")
                            print(f"     Executable: {conflict['exe']}")
                            print(f"     Start Directory: {conflict['startdir']}")
                        
                        print(f"\n{COLOR_PROMPT}Options:{COLOR_RESET}")
                        print("  • Replace - Remove the existing shortcut and create a new one")
                        print("  • Cancel - Keep the existing shortcut and stop the installation")
                        print("  • Skip - Continue without creating a Steam shortcut")
                        
                        choice = input(f"\n{COLOR_PROMPT}Choose an option (replace/cancel/skip): {COLOR_RESET}").strip().lower()
                        
                        if choice == 'replace':
                            print(f"{COLOR_INFO}Replacing existing shortcut...{COLOR_RESET}")
                            success, app_id = prefix_service.replace_existing_shortcut(shortcut_name, mo2_exe_path, install_dir_str)
                            if success and app_id:
                                # Continue the workflow after replacement
                                result = prefix_service.continue_workflow_after_conflict_resolution(
                                    shortcut_name, install_dir_str, mo2_exe_path, app_id, progress_callback
                                )
                                if isinstance(result, tuple) and len(result) == 3:
                                    success, prefix_path, app_id = result
                                else:
                                    success, prefix_path, app_id = False, None, None
                            else:
                                success, prefix_path, app_id = False, None, None
                        elif choice == 'cancel':
                            print(f"{COLOR_INFO}Cancelling installation.{COLOR_RESET}")
                            return
                        elif choice == 'skip':
                            print(f"{COLOR_INFO}Skipping Steam shortcut creation.{COLOR_RESET}")
                            success, prefix_path, app_id = True, None, None
                        else:
                            print(f"{COLOR_ERROR}Invalid choice. Cancelling.{COLOR_RESET}")
                            return
                    else:
                        # Normal result
                        success, prefix_path, app_id = result
                else:
                    success, prefix_path, app_id = False, None, None
                
                if success:
                    print(f"{COLOR_SUCCESS}Automated Steam setup completed successfully!{COLOR_RESET}")
                    if prefix_path:
                        print(f"{COLOR_INFO}Proton prefix created at: {prefix_path}{COLOR_RESET}")
                    if app_id:
                        print(f"{COLOR_INFO}Steam AppID: {app_id}{COLOR_RESET}")
                    return
                else:
                    print(f"{COLOR_WARNING}Automated Steam setup failed. Falling back to manual setup...{COLOR_RESET}")
            
            # Fallback to manual shortcut creation process
            print(f"\n{COLOR_INFO}Using manual Steam setup workflow...{COLOR_RESET}")
            
            # Use the working shortcut creation process from legacy code
            from ..handlers.shortcut_handler import ShortcutHandler
            shortcut_handler = ShortcutHandler(steamdeck=self.steamdeck, verbose=False)
            
            # Create nxmhandler.ini to suppress NXM popup
            shortcut_handler.write_nxmhandler_ini(install_dir_str, mo2_exe_path)
            
            # Create shortcut with working NativeSteamService
            from ..services.native_steam_service import NativeSteamService
            steam_service = NativeSteamService()
            
            success, app_id = steam_service.create_shortcut_with_proton(
                app_name=shortcut_name,
                exe_path=mo2_exe_path,
                start_dir=os.path.dirname(mo2_exe_path),
                launch_options="%command%",
                tags=["Jackify"],
                proton_version="proton_experimental"
            )
            
            if not success or not app_id:
                self.logger.error("Failed to create Steam shortcut")
                print(f"{COLOR_ERROR}Failed to create Steam shortcut. Check logs for details.{COLOR_RESET}")
                return
            
            # Step 2: Handle Steam restart and manual steps (if not in GUI mode)
            if not is_gui_mode:
                print(f"\n{COLOR_INFO}Steam shortcut created successfully!{COLOR_RESET}")
                print("Steam needs to restart to detect the new shortcut. WARNING: This will close all running Steam instances, and games.")
                
                restart_choice = input("\nRestart Steam automatically now? (Y/n): ").strip().lower()
                if restart_choice == 'n':
                    print("\nPlease restart Steam manually and complete the Proton setup steps.")
                    print("You can configure this modlist later using 'Configure Existing Modlist'.")
                    return
                
                # Restart Steam
                print("\nRestarting Steam...")
                if shortcut_handler.secure_steam_restart():
                    print(f"{COLOR_INFO}Steam restarted successfully.{COLOR_RESET}")
                    
                    # Display manual Proton steps
                    from ..handlers.menu_handler import ModlistMenuHandler
                    from ..handlers.config_handler import ConfigHandler
                    config_handler = ConfigHandler()
                    menu_handler = ModlistMenuHandler(config_handler)
                    menu_handler._display_manual_proton_steps(shortcut_name)
                    
                    retry_count = 0
                    max_retries = 3
                    while retry_count < max_retries:
                        input(f"\n{COLOR_PROMPT}Once you have completed ALL the steps above, press Enter to continue...{COLOR_RESET}")
                        print(f"\n{COLOR_INFO}Verifying manual steps...{COLOR_RESET}")
                        new_app_id = shortcut_handler.get_appid_for_shortcut(shortcut_name, mo2_exe_path)
                        if new_app_id and new_app_id.isdigit() and int(new_app_id) > 0:
                            app_id = new_app_id
                            from ..handlers.modlist_handler import ModlistHandler
                            modlist_handler = ModlistHandler({}, steamdeck=self.steamdeck)
                            verified, status_code = modlist_handler.verify_proton_setup(app_id)
                            if verified:
                                print(f"{COLOR_SUCCESS}Manual steps verification successful!{COLOR_RESET}")
                                break
                            else:
                                retry_count += 1
                                if retry_count < max_retries:
                                    print(f"\n{COLOR_ERROR}Verification failed: {status_code}{COLOR_RESET}")
                                    print(f"{COLOR_WARNING}Please ensure you have completed all manual steps correctly.{COLOR_RESET}")
                                    menu_handler._display_manual_proton_steps(shortcut_name)
                                else:
                                    print(f"\n{COLOR_ERROR}Manual steps verification failed after {max_retries} attempts.{COLOR_RESET}")
                                    print(f"{COLOR_WARNING}Configuration may not work properly.{COLOR_RESET}")
                                    return
                        else:
                            retry_count += 1
                            if retry_count < max_retries:
                                print(f"\n{COLOR_ERROR}Could not find valid AppID after launch.{COLOR_RESET}")
                                print(f"{COLOR_WARNING}Please ensure you have launched the shortcut from Steam.{COLOR_RESET}")
                                menu_handler._display_manual_proton_steps(shortcut_name)
                            else:
                                print(f"\n{COLOR_ERROR}Could not find valid AppID after {max_retries} attempts.{COLOR_RESET}")
                                print(f"{COLOR_WARNING}Configuration may not work properly.{COLOR_RESET}")
                                return
                else:
                    print(f"{COLOR_ERROR}Steam restart failed. Please restart manually and configure later.{COLOR_RESET}")
                    return
            
            # Step 3: Build configuration context with the AppID
            config_context = {
                'name': shortcut_name,
                'appid': app_id,
                'path': install_dir_str,
                'mo2_exe_path': mo2_exe_path,
                'resolution': self.context.get('resolution'),
                'skip_confirmation': is_gui_mode,
                'manual_steps_completed': not is_gui_mode  # True if we did manual steps above
            }
            
            # Step 4: Use ModlistMenuHandler to run the complete configuration
            from ..handlers.menu_handler import ModlistMenuHandler
            from ..handlers.config_handler import ConfigHandler
            
            config_handler = ConfigHandler()
            modlist_menu = ModlistMenuHandler(config_handler)
            
            # Add section header for configuration phase if progress callback is available
            if 'progress_callback' in locals() and progress_callback:
                progress_callback("")  # Blank line for spacing
                progress_callback("=== Configuring Modlist ===")
            
            self.logger.info("Running post-installation configuration phase")
            configuration_success = modlist_menu.run_modlist_configuration_phase(config_context)
            
            if configuration_success:
                self.logger.info("Post-installation configuration completed successfully")
            else:
                self.logger.warning("Post-installation configuration had issues")
        else:
            # Game not supported for automated configuration
            print(f"{COLOR_INFO}Modlist installation complete.{COLOR_RESET}")
            if detected_game:
                print(f"{COLOR_WARNING}Detected game '{detected_game}' is not supported for automated Steam configuration.{COLOR_RESET}")
            else:
                print(f"{COLOR_WARNING}Could not detect game type from ModOrganizer.ini for automated configuration.{COLOR_RESET}")
            print(f"{COLOR_INFO}You may need to manually configure the modlist for Steam/Proton.{COLOR_RESET}")

    def configuration_phase_gui_mode(self, context, 
                                     progress_callback=None,
                                     manual_steps_callback=None, 
                                     completion_callback=None):
        """
        GUI-friendly configuration phase that uses callbacks instead of prompts.
        
        This method provides the same functionality as configuration_phase() but
        integrates with GUI frontends using Qt callbacks instead of CLI prompts.
        
        Args:
            context: Configuration context dict with modlist details
            progress_callback: Called with progress messages (str)
            manual_steps_callback: Called when manual steps needed (modlist_name, retry_count)
            completion_callback: Called when configuration completes (success, message, modlist_name)
        """
        # Section header now provided by GUI layer to avoid duplication
        
        try:
            # Set GUI mode for backend operations
            import os
            original_gui_mode = os.environ.get('JACKIFY_GUI_MODE')
            os.environ['JACKIFY_GUI_MODE'] = '1'
            
            try:
                # Build context for configuration
                config_context = {
                    'name': context.get('modlist_name', ''),
                    'path': context.get('install_dir', ''),
                    'mo2_exe_path': context.get('mo2_exe_path', ''),
                    'modlist_value': context.get('modlist_value'),
                    'modlist_source': context.get('modlist_source'),
                    'resolution': context.get('resolution'),
                    'skip_confirmation': True,  # GUI mode is non-interactive
                    'manual_steps_completed': False
                }
                
                # Handle existing modlist configuration with app_id
                existing_app_id = context.get('app_id')
                if existing_app_id:
                    # This is an existing modlist configuration
                    config_context['appid'] = existing_app_id
                    
                    if progress_callback:
                        progress_callback(f"Configuring existing modlist with AppID {existing_app_id}...")
                    
                    # Get the modlist menu handler
                    from jackify.backend.handlers.menu_handler import ModlistMenuHandler
                    from jackify.backend.handlers.config_handler import ConfigHandler
                    
                    config_handler = ConfigHandler()
                    modlist_menu = ModlistMenuHandler(config_handler)
                    
                    # Run configuration phase with GUI callbacks for existing modlist
                    retry_count = 0
                    max_retries = 3
                    
                    while retry_count < max_retries:
                        if progress_callback:
                            progress_callback("Running modlist configuration...")
                        
                        # Run the actual configuration
                        result = modlist_menu.run_modlist_configuration_phase(config_context)
                        
                        if progress_callback:
                            progress_callback(f"Configuration attempt {retry_count}: {'Success' if result else 'Failed'}")
                        
                        if result:
                            # Configuration successful
                            if completion_callback:
                                completion_callback(True, "Configuration completed successfully!", config_context['name'])
                            return True
                        else:
                            # Configuration failed - might need manual steps
                            retry_count += 1
                            
                            if retry_count < max_retries:
                                # Show manual steps dialog
                                if progress_callback:
                                    progress_callback(f"Configuration failed on attempt {retry_count}, showing manual steps dialog...")
                                if manual_steps_callback:
                                    if progress_callback:
                                        progress_callback(f"Calling manual_steps_callback for {config_context['name']}, retry {retry_count}")
                                    manual_steps_callback(config_context['name'], retry_count)
                                
                                # Update context to indicate manual steps were attempted
                                config_context['manual_steps_completed'] = True
                            else:
                                # Max retries reached
                                if completion_callback:
                                    completion_callback(False, "Manual steps failed after multiple attempts", config_context['name'])
                                return False
                    
                    # Should not reach here
                    if completion_callback:
                        completion_callback(False, "Configuration failed", config_context['name'])
                    return False
                
                # NEW modlist configuration - create Steam shortcut first
                else:
                    # Get the modlist menu handler
                    from jackify.backend.handlers.menu_handler import ModlistMenuHandler
                    from jackify.backend.handlers.config_handler import ConfigHandler
                    
                    config_handler = ConfigHandler()
                    modlist_menu = ModlistMenuHandler(config_handler)
                    
                    # Create Steam shortcut first
                    if progress_callback:
                        progress_callback("Creating Steam shortcut...")
                    
                    # Create shortcut with working NativeSteamService
                    from jackify.backend.services.native_steam_service import NativeSteamService
                    steam_service = NativeSteamService()
                    
                    success, app_id = steam_service.create_shortcut_with_proton(
                        app_name=config_context['name'],
                        exe_path=config_context['mo2_exe_path'],
                        start_dir=os.path.dirname(config_context['mo2_exe_path']),
                        launch_options="%command%",
                        tags=["Jackify"],
                        proton_version="proton_experimental"
                    )
                    
                    if not success or not app_id:
                        if completion_callback:
                            completion_callback(False, "Failed to create Steam shortcut", config_context['name'])
                        return False
                    
                    # Add the new app_id to context
                    config_context['appid'] = app_id
                    
                    if progress_callback:
                        # Import here to avoid circular imports
                        from jackify.shared.timing import get_timestamp
                        progress_callback(f"{get_timestamp()} Steam shortcut created successfully")
                    
                    # For GUI mode, run configuration once and let GUI handle manual steps retry
                    if progress_callback:
                        progress_callback("Running modlist configuration...")
                    
                    # Run the actual configuration
                    if progress_callback:
                        progress_callback(f"About to call run_modlist_configuration_phase with context: {config_context}")
                    
                    result = modlist_menu.run_modlist_configuration_phase(config_context)
                    
                    if progress_callback:
                        progress_callback(f"run_modlist_configuration_phase returned: {result}")
                    
                    if result:
                        # Configuration successful
                        if completion_callback:
                            completion_callback(True, "Configuration completed successfully!", config_context['name'])
                        return True
                    else:
                        # Configuration failed - need manual steps
                        if progress_callback:
                            progress_callback("Configuration failed, manual Steam/Proton setup required")
                        if manual_steps_callback:
                            if progress_callback:
                                progress_callback(f"About to call manual_steps_callback for {config_context['name']}, retry 1")
                            # Call manual steps callback - GUI will handle validation and retry logic
                            manual_steps_callback(config_context['name'], 1)
                            if progress_callback:
                                progress_callback("manual_steps_callback completed")
                        
                        # Don't complete here - let GUI handle retry when user is done
                        return True
                    
                    # Should not reach here
                    if completion_callback:
                        completion_callback(False, "Configuration failed", config_context['name'])
                    return False
                
            finally:
                # Restore original GUI mode
                if original_gui_mode is not None:
                    os.environ['JACKIFY_GUI_MODE'] = original_gui_mode
                else:
                    os.environ.pop('JACKIFY_GUI_MODE', None)
                    
        except Exception as e:
            error_msg = f"Configuration failed: {str(e)}"
            if completion_callback:
                completion_callback(False, error_msg, context.get('modlist_name', 'Unknown'))
            return False

    def install_modlist(self, selected_modlist_info: Optional[Dict[str, Any]] = None, wabbajack_file_path: Optional[Union[str, Path]] = None):
        # This is where we would get the engine path for the actual installation
        engine_path = get_jackify_engine_path() # Use the helper
        self.logger.info(f"Using engine path for installation: {engine_path}")

        # --- The rest of your install_modlist logic ---
        # ...
        # When constructing the subprocess command for install, use `engine_path`
        # For example:
        # install_command = [engine_path, 'install', '--modlist-url', modlist_url, ...]
        # ...
        self.logger.info("Placeholder for actual modlist installation logic using the engine.")
        print("Modlist installation logic would run here.")
        return True # Placeholder 

    def _get_nexus_api_key(self) -> Optional[str]:
        # This method is not provided in the original file or the code block
        # It's assumed to exist as it's called in the _display_summary method
        # Implement the logic to retrieve the Nexus API key from the context
        return self.context.get('nexus_api_key')

    def get_all_modlists_from_engine(self, game_type=None):
        """
        Call the Jackify engine with 'list-modlists' and return a list of modlist dicts.
        Each dict should have at least 'id', 'game', 'download_size', 'install_size', 'total_size', and status flags.
        
        Args:
            game_type (str, optional): Filter by game type (e.g., "Skyrim", "Fallout New Vegas")
        """
        import subprocess
        import re
        from pathlib import Path
                    # COLOR_ERROR already imported at module level
        engine_executable = get_jackify_engine_path()
        engine_dir = os.path.dirname(engine_executable)
        if not os.path.exists(engine_executable):
            self.logger.error(f"jackify-install-engine not found at {engine_executable}")
            print(f"{COLOR_ERROR}Error: jackify-install-engine not found at expected location.{COLOR_ERROR}")
            return []
        env = os.environ.copy()
        env["DOTNET_SYSTEM_GLOBALIZATION_INVARIANT"] = "1"
        command = [engine_executable, 'list-modlists', '--show-all-sizes', '--show-machine-url']
        
        # Add game filter if specified
        if game_type:
            command.extend(['--game', game_type])
        try:
            result = subprocess.run(
                command,
                capture_output=True, text=True, check=True,
                env=env, cwd=engine_dir
            )
            lines = result.stdout.splitlines()
            modlists = []
            for line in lines:
                line = line.strip()
                if not line or line.startswith('Loading') or line.startswith('Loaded'):
                    continue
                
                # Parse new format: [STATUS] Modlist Name - Game - Download|Install|Total - MachineURL
                # STATUS indicators: [DOWN], [NSFW], or both [DOWN] [NSFW]
                
                # Extract status indicators
                status_down = '[DOWN]' in line
                status_nsfw = '[NSFW]' in line
                
                # Remove status indicators to get clean line
                clean_line = line.replace('[DOWN]', '').replace('[NSFW]', '').strip()
                
                # Split on ' - ' to get: [Modlist Name, Game, Sizes, MachineURL]
                parts = clean_line.split(' - ')
                if len(parts) != 4:
                    continue  # Skip malformed lines
                
                modlist_name = parts[0].strip()
                game_name = parts[1].strip()
                sizes_str = parts[2].strip()
                machine_url = parts[3].strip()
                
                # Parse sizes: "Download|Install|Total" (e.g., "203GB|130GB|333GB")
                size_parts = sizes_str.split('|')
                if len(size_parts) != 3:
                    continue  # Skip if sizes don't match expected format
                
                download_size = size_parts[0].strip()
                install_size = size_parts[1].strip()
                total_size = size_parts[2].strip()
                
                # Skip if any required data is missing
                if not modlist_name or not game_name or not machine_url:
                    continue
                
                modlists.append({
                    'id': modlist_name,  # Use modlist name as ID for compatibility
                    'name': modlist_name,
                    'game': game_name,
                    'download_size': download_size,
                    'install_size': install_size, 
                    'total_size': total_size,
                    'machine_url': machine_url,  # Store machine URL for installation
                    'status_down': status_down,
                    'status_nsfw': status_nsfw
                })
            return modlists
        except subprocess.CalledProcessError as e:
            self.logger.error(f"list-modlists failed. Code: {e.returncode}")
            if e.stdout: self.logger.error(f"Engine stdout:\n{e.stdout}")
            if e.stderr: self.logger.error(f"Engine stderr:\n{e.stderr}")
            print(f"{COLOR_ERROR}Failed to fetch modlist list. Engine error (Code: {e.returncode}).{COLOR_ERROR}")
            return []
        except Exception as e:
            self.logger.error(f"Unexpected error fetching modlists: {e}", exc_info=True)
            print(f"{COLOR_ERROR}Unexpected error fetching modlists: {e}{COLOR_ERROR}")
            return []

    def _display_summary(self):
        # REMOVE pass AND RESTORE THE METHOD BODY
        # print(f"{COLOR_WARNING}DEBUG: _display_summary called. Current context keys: {list(self.context.keys())}{COLOR_RESET}") # Keep commented
        # self.logger.info(f"DEBUG: _display_summary called. Current context keys: {list(self.context.keys())}") # Keep commented
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
        
        if self.context.get('nexus_api_key'):
            print(f"Nexus API Key: [SET]")
        else:
            print(f"Nexus API Key: [NOT SET - WILL LIKELY FAIL]")
        print(f"{COLOR_INFO}----------------------------------------{COLOR_RESET}") 