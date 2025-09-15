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
from .ui_colors import COLOR_PROMPT, COLOR_INFO, COLOR_ERROR, COLOR_RESET, COLOR_SUCCESS, COLOR_WARNING, COLOR_SELECTION
# Standard logging (no file handler) - LoggingHandler import removed
import re
import subprocess
import logging
import sys
import json
import shlex
import time
import pty
# from src.core.compressonator import run_compressonatorcli  # TODO: Implement compressonator integration

# Import UI Colors first - these should always be available
from .ui_colors import COLOR_PROMPT, COLOR_RESET, COLOR_INFO, COLOR_ERROR, COLOR_SELECTION, COLOR_WARNING

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

# Initialize logger for the module
logger = logging.getLogger(__name__) # Standard logger init

# Helper function to get path to jackify-install-engine
def get_jackify_engine_path():
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        # Running in a PyInstaller bundle
        # Engine is expected at <bundle_root>/jackify/engine/jackify-engine
        return os.path.join(sys._MEIPASS, 'jackify', 'engine', 'jackify-engine')
    else:
        # Running in a normal Python environment from source
        # Current file is in src/jackify/backend/handlers/modlist_install_cli.py
        # Engine is at src/jackify/engine/jackify-engine
        current_file_dir = os.path.dirname(os.path.abspath(__file__))
        # Navigate up from src/jackify/backend/handlers/ to src/jackify/
        jackify_dir = os.path.dirname(os.path.dirname(current_file_dir))
        return os.path.join(jackify_dir, 'engine', 'jackify-engine')

class ModlistInstallCLI:
    """
    Handles the discovery phase for installing a Wabbajack modlist via CLI.
    """
    def __init__(self, menu_handler: MenuHandler, steamdeck: bool = False):
        self.menu_handler = menu_handler
        self.steamdeck = steamdeck
        self.protontricks_handler = ProtontricksHandler(steamdeck=steamdeck)
        self.shortcut_handler = ShortcutHandler(steamdeck=steamdeck)
        self.context = {}
        # Use standard logging (no file handler)
        self.logger = logging.getLogger(__name__)
        self.logger.propagate = False # Prevent duplicate logs if root logger is also configured

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
                    env = os.environ.copy()
                    env["DOTNET_SYSTEM_GLOBALIZATION_INVARIANT"] = "1"
                    self.logger.info("Setting DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1 for jackify-engine process.")
                    
                    # Use the engine path from the helper function, but the command structure from restored.
                    engine_executable_path_for_subprocess = get_jackify_engine_path() 
                    command = [engine_executable_path_for_subprocess, 'list-modlists', '--show-all-sizes', '--show-machine-url']
                    self.logger.info(f"Executing command: {' '.join(command)} in CWD: {engine_dir}")

                    # check=True as in restored logic
                    result = subprocess.run(
                        command,
                        capture_output=True, text=True, check=True, 
                        env=env, cwd=engine_dir
                    )
                    
                    # self.logger.debug(f"Engine stdout (raw):\n{result.stdout}") # COMMENTED OUT - too verbose

                    lines = result.stdout.splitlines()
                    
                    # Parse new format: [STATUS] Modlist Name - Game - Download|Install|Total - MachineURL
                    # STATUS indicators: [DOWN], [NSFW], or both [DOWN] [NSFW]
                    raw_modlists_from_engine = []
                    for line in lines:
                        line = line.strip()
                        if not line or line.startswith('Loading') or line.startswith('Loaded'):
                            continue
                        
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
                        
                        raw_modlists_from_engine.append({
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
                    
                    self.logger.info(f"Scraped {len(raw_modlists_from_engine)} modlists after revised regex and filtering logic.")

                    if not raw_modlists_from_engine:
                        print(f"{COLOR_WARNING}No modlists found after applying revised regex and filtering logic.{COLOR_RESET}")
                        return None

                    # EXACT game_type_map and grouping logic from restored file
                    game_type_map = {
                        '1': ('Skyrim', ['Skyrim', 'Skyrim Special Edition']),
                        '2': ('Fallout 4', ['Fallout 4']),
                        '3': ('Fallout New Vegas', ['Fallout New Vegas']),
                        '4': ('Oblivion', ['Oblivion']),
                        '5': ('Other Games', None) # Using None as in restored for keyword list
                    }
                    
                    grouped_modlists = {k: [] for k in game_type_map}
                    
                    for m_info in raw_modlists_from_engine: # m_info is like {'id': ..., 'game': ...}
                        found_category = False
                        for cat_key, (cat_label, cat_keywords) in game_type_map.items():
                            if cat_key == '5': # Skip 'Other Games' for direct matching initially
                                continue
                            if cat_keywords: # Ensure there are keywords to check (handles 'Other Games' with None)
                                for keyword in cat_keywords:
                                    if keyword.lower() in m_info['game'].lower():
                                        grouped_modlists[cat_key].append(m_info)
                                        found_category = True
                                        break # Found category for this modlist
                            if found_category:
                                break # Move to next modlist
                        if not found_category:
                            grouped_modlists['5'].append(m_info) # Add to 'Other Games'
                    
                    selected_modlist_info = None # Will store {'id': ..., 'game': ...}
                    while not selected_modlist_info:
                        print(f"\n{COLOR_PROMPT}Select a game category:{COLOR_RESET}")
                        
                        category_display_map = {} # Maps displayed number to actual game_type_map key
                        display_idx = 1
                        # Iterate in a defined order for consistent menu
                        for cat_key_ordered in ['1','2','3','4','5']:
                            if cat_key_ordered in grouped_modlists and grouped_modlists[cat_key_ordered]: # Only show if non-empty
                                cat_label = game_type_map[cat_key_ordered][0]
                                print(f"  {COLOR_SELECTION}{display_idx}.{COLOR_RESET} {cat_label} ({len(grouped_modlists[cat_key_ordered])} modlists)")
                                category_display_map[str(display_idx)] = cat_key_ordered
                                display_idx += 1
                        
                        if display_idx == 1: # No categories had any modlists
                            print(f"{COLOR_WARNING}No modlists found to display after grouping. Engine output might be empty or filtered entirely.{COLOR_RESET}")
                            return None

                        print(f"  {COLOR_SELECTION}0.{COLOR_RESET} Cancel")
                        
                        game_cat_choice = input(f"{COLOR_PROMPT}Enter selection: {COLOR_RESET}").strip()
                        if game_cat_choice == '0':
                            self.logger.info("User cancelled game category selection.")
                            return None
                        
                        actual_cat_key = category_display_map.get(game_cat_choice)
                        if not actual_cat_key:
                            print(f"{COLOR_ERROR}Invalid selection. Please try again.{COLOR_RESET}")
                            continue

                        # modlist_group_for_game is a list of dicts like {'id': ..., 'game': ...}
                        modlist_group_for_game = sorted(grouped_modlists[actual_cat_key], key=lambda x: x['id'].lower())
                        
                        print(f"\n{COLOR_SUCCESS}Available Modlists for {game_type_map[actual_cat_key][0]}:{COLOR_RESET}")
                        for idx, m_detail in enumerate(modlist_group_for_game, 1):
                            if actual_cat_key == '5':  # 'Other Games' category
                                print(f"  {COLOR_SELECTION}{idx}.{COLOR_RESET} {m_detail['id']} ({m_detail['game']})")
                            else:
                                print(f"  {COLOR_SELECTION}{idx}.{COLOR_RESET} {m_detail['id']}")
                        print(f"  {COLOR_SELECTION}0.{COLOR_RESET} Back to game categories")

                        while True:
                            mod_choice_idx_str = input(f"{COLOR_PROMPT}Select modlist (or 0): {COLOR_RESET}").strip()
                            if mod_choice_idx_str == '0':
                                break
                            if mod_choice_idx_str.isdigit():
                                mod_idx = int(mod_choice_idx_str) - 1
                                if 0 <= mod_idx < len(modlist_group_for_game):
                                    selected_modlist_info = modlist_group_for_game[mod_idx]
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
                
                except subprocess.CalledProcessError as e:
                    self.logger.error(f"list-modlists failed. Code: {e.returncode}")
                    if e.stdout: self.logger.error(f"Engine stdout:\n{e.stdout}")
                    if e.stderr: self.logger.error(f"Engine stderr:\n{e.stderr}")
                    print(f"{COLOR_ERROR}Failed to fetch modlist list. Engine error (Code: {e.returncode}).{COLOR_RESET}")
                    return None
                except FileNotFoundError: 
                    self.logger.error(f"Engine not found: {engine_executable_path_for_subprocess}")
                    print(f"{COLOR_ERROR}Critical error: jackify-install-engine not found.{COLOR_RESET}")
                    return None
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
        
        # 5. Prompt for Nexus API key (skip if in context)
        if 'nexus_api_key' not in self.context:
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
            self.context['nexus_api_key'] = api_key
        self.logger.debug(f"NEXUS_API_KEY is set in environment for engine (presence check).")

        # Display summary and confirm
        self._display_summary() # Ensure this method exists or implement it
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
        import subprocess
        import time
        import sys
        from pathlib import Path
                            # UI Colors and LoggingHandler already imported at module level
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
            api_key = self.context['nexus_api_key']

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
            
            # Check for debug mode and pass --debug to engine if needed
            from jackify.backend.handlers.config_handler import ConfigHandler
            config_handler = ConfigHandler()
            debug_mode = config_handler.get('debug_mode', False)
            if debug_mode:
                cmd.append('--debug')
                self.logger.info("Debug mode enabled in config - passing --debug flag to jackify-engine")
            
            # Determine if this is a local .wabbajack file or an online modlist
            modlist_value = self.context.get('modlist_value')
            machineid = self.context.get('machineid')
            
            # Check if there's a cached .wabbajack file for this modlist
            cached_wabbajack_path = None
            if machineid:
                # Convert machineid to filename (e.g., "Tuxborn/Tuxborn" -> "Tuxborn.wabbajack")
                modlist_name = machineid.split('/')[-1] if '/' in machineid else machineid
                cached_wabbajack_path = os.path.expanduser(f"~/Jackify/downloaded_mod_lists/{modlist_name}.wabbajack")
                self.logger.debug(f"Checking for cached .wabbajack file: {cached_wabbajack_path}")
            
            if modlist_value and modlist_value.endswith('.wabbajack') and os.path.isfile(modlist_value):
                cmd += ['-w', modlist_value]
                self.logger.info(f"Using local .wabbajack file: {modlist_value}")
            elif cached_wabbajack_path and os.path.isfile(cached_wabbajack_path):
                cmd += ['-w', cached_wabbajack_path]
                self.logger.info(f"Using cached .wabbajack file: {cached_wabbajack_path}")
            elif modlist_value:
                cmd += ['-m', modlist_value]
                self.logger.info(f"Using modlist identifier: {modlist_value}")
            elif machineid:
                cmd += ['-m', machineid]
                self.logger.info(f"Using machineid: {machineid}")
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
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=False, env=None, cwd=engine_dir)
                
                # Start performance monitoring for the engine process
                # Adjust monitoring based on debug mode
                if debug_mode:
                    # More aggressive monitoring in debug mode
                    performance_monitor = EnginePerformanceMonitor(
                        logger=self.logger,
                        stall_threshold=5.0,  # CPU below 5% is considered stalled
                        stall_duration=60.0,  # 1 minute of low CPU = stall (faster detection)
                        sample_interval=5.0   # Check every 5 seconds (more frequent)
                    )
                    # Add debug callback for detailed metrics
                    from .engine_monitor import create_debug_callback
                    performance_monitor.add_callback(create_debug_callback(self.logger))
                    self.logger.info("Enhanced performance monitoring enabled for debug mode")
                else:
                    # Standard monitoring
                    performance_monitor = EnginePerformanceMonitor(
                        logger=self.logger,
                        stall_threshold=5.0,  # CPU below 5% is considered stalled
                        stall_duration=120.0,  # 2 minutes of low CPU = stall
                        sample_interval=10.0   # Check every 10 seconds
                    )
                
                # Add callback to alert about performance issues
                def stall_alert(message: str):
                    print(f"\nWarning: {message}")
                    print("If the process appears stuck, you may need to restart it.")
                    if debug_mode:
                        print("Debug mode: Use 'python -m jackify.backend.handlers.diagnostic_helper' for detailed analysis")
                    
                performance_monitor.add_callback(create_stall_alert_callback(self.logger, stall_alert))
                
                # Start monitoring
                monitoring_started = performance_monitor.start_monitoring(proc.pid)
                if monitoring_started:
                    self.logger.info(f"Performance monitoring started for engine PID {proc.pid}")
                else:
                    self.logger.warning("Failed to start performance monitoring")
                
                try:
                    # Read output in binary mode to properly handle carriage returns
                    buffer = b''
                    last_progress_time = time.time()
                    
                    while True:
                        chunk = proc.stdout.read(1)
                        if not chunk:
                            break
                        buffer += chunk
                        
                        # Process complete lines or carriage return updates
                        if chunk == b'\n':
                            # Complete line - decode and print
                            line = buffer.decode('utf-8', errors='replace')
                            # Enhance Nexus download errors with modlist context
                            enhanced_line = self._enhance_nexus_error(line)
                            print(enhanced_line, end='')
                            buffer = b''
                            last_progress_time = time.time()
                        elif chunk == b'\r':
                            # Carriage return - decode and print without newline
                            line = buffer.decode('utf-8', errors='replace')
                            # Enhance Nexus download errors with modlist context
                            enhanced_line = self._enhance_nexus_error(line)
                            print(enhanced_line, end='')
                            sys.stdout.flush()
                            buffer = b''
                            last_progress_time = time.time()
                            
                        # Check for timeout (no output for too long)
                        current_time = time.time()
                        if current_time - last_progress_time > 300:  # 5 minutes no output
                            self.logger.warning("No output from engine for 5 minutes - possible stall")
                            last_progress_time = current_time  # Reset to avoid spam
                    
                    # Print any remaining buffer content
                    if buffer:
                        line = buffer.decode('utf-8', errors='replace')
                        print(line, end='')
                    
                    proc.wait()
                    
                finally:
                    # Stop performance monitoring and get summary
                    if monitoring_started:
                        performance_monitor.stop_monitoring()
                        summary = performance_monitor.get_metrics_summary()
                        
                        if summary:
                            self.logger.info(f"Engine Performance Summary: "
                                           f"Duration: {summary.get('monitoring_duration', 0):.1f}s, "
                                           f"Avg CPU: {summary.get('avg_cpu_percent', 0):.1f}%, "
                                           f"Max Memory: {summary.get('max_memory_mb', 0):.1f}MB, "
                                           f"Stalls: {summary.get('stall_percentage', 0):.1f}%")
                            
                            # Log detailed summary for debugging
                            self.logger.debug(f"Detailed performance summary: {summary}")
                if proc.returncode != 0:
                    print(f"{COLOR_ERROR}Jackify Install Engine exited with code {proc.returncode}.{COLOR_RESET}")
                    self.logger.error(f"Engine exited with code {proc.returncode}.")
                    return # Configuration phase failed
                self.logger.info(f"Engine completed with code {proc.returncode}.")
            except Exception as e:
                print(f"{COLOR_ERROR}Error running Jackify Install Engine: {e}{COLOR_RESET}\n")
                self.logger.error(f"Exception running engine: {e}", exc_info=True)
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
            print(f"{COLOR_ERROR}Error during Tuxborn installation workflow: {e}{COLOR_RESET}\n")
            self.logger.error(f"Exception in Tuxborn workflow: {e}", exc_info=True)
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
        # After install, use self.context['modlist_game'] to determine if configuration should be offered
        # After install, detect game type from ModOrganizer.ini
        modorganizer_ini = os.path.join(install_dir_str, "ModOrganizer.ini")
        detected_game = None
        if os.path.isfile(modorganizer_ini):
            from .modlist_handler import ModlistHandler
            handler = ModlistHandler({}, steamdeck=self.steamdeck)
            handler.modlist_ini = modorganizer_ini
            handler.modlist_dir = install_dir_str
            if handler._detect_game_variables():
                detected_game = handler.game_var_full
        supported_games = ["Skyrim Special Edition", "Fallout 4", "Fallout New Vegas", "Oblivion", "Starfield", "Oblivion Remastered", "Enderal"]
        is_tuxborn = self.context.get('machineid') == 'Tuxborn/Tuxborn'
        if (detected_game in supported_games) or is_tuxborn:
            shortcut_name = self.context.get('modlist_name')
            if is_tuxborn and not shortcut_name:
                self.logger.warning("Tuxborn is true, but shortcut_name (modlist_name in context) is missing. Defaulting to 'Tuxborn Automatic Installer'")
                shortcut_name = "Tuxborn Automatic Installer" # Provide a fallback default
            elif not shortcut_name: # For non-Tuxborn, prompt if missing
                print("\n" + "-" * 28)
                print(f"{COLOR_PROMPT}Please provide a name for the Steam shortcut for '{self.context.get('modlist_name', 'this modlist')}'.{COLOR_RESET}")
                raw_shortcut_name = input(f"{COLOR_PROMPT}Steam Shortcut Name (or 'q' to cancel): {COLOR_RESET} ").strip()
                if raw_shortcut_name.lower() == 'q' or not raw_shortcut_name:
                    return
                shortcut_name = raw_shortcut_name
            
            # Check if GUI mode to skip interactive prompts
            is_gui_mode = os.environ.get('JACKIFY_GUI_MODE') == '1'
            
            if not is_gui_mode:
                # Prompt user if they want to configure Steam shortcut now
                print("\n" + "-" * 28)
                print(f"{COLOR_PROMPT}Would you like to add '{shortcut_name}' to Steam and configure it now?{COLOR_RESET}")
                configure_choice = input(f"{COLOR_PROMPT}Configure now? (Y/n): {COLOR_RESET}").strip().lower()
                
                if configure_choice == 'n':
                    print(f"{COLOR_INFO}Skipping Steam configuration. You can configure it later using 'Configure New Modlist'.{COLOR_RESET}")
                    return
            
            # Proceed with Steam configuration
            self.logger.info(f"Starting Steam configuration for '{shortcut_name}'")
            
            # Step 1: Create Steam shortcut first
            mo2_exe_path = os.path.join(install_dir_str, 'ModOrganizer.exe')
            
            # Use the working shortcut creation process from legacy code
            from .shortcut_handler import ShortcutHandler
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
                print("Steam needs to restart to detect the new shortcut.")
                
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
                    from .menu_handler import ModlistMenuHandler
                    from .config_handler import ConfigHandler
                    config_handler = ConfigHandler()
                    menu_handler = ModlistMenuHandler(config_handler)
                    menu_handler._display_manual_proton_steps(shortcut_name)
                    
                    input(f"\n{COLOR_PROMPT}Once you have completed ALL the steps above, press Enter to continue...{COLOR_RESET}")
                    
                    # Get the updated AppID after launch
                    new_app_id = shortcut_handler.get_appid_for_shortcut(shortcut_name, mo2_exe_path)
                    if new_app_id and new_app_id.isdigit() and int(new_app_id) > 0:
                        app_id = new_app_id
                    else:
                        print(f"{COLOR_ERROR}Could not find valid AppID after launch. Configuration may not work properly.{COLOR_RESET}")
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
            from .menu_handler import ModlistMenuHandler
            from .config_handler import ConfigHandler
            
            config_handler = ConfigHandler()
            modlist_menu = ModlistMenuHandler(config_handler)
            
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
                
                # Parse the new format: [STATUS] Modlist Name - Game - Download|Install|Total - MachineURL
                # STATUS indicators: [DOWN], [NSFW], or both [DOWN] [NSFW]
                
                # Extract status indicators
                status_down = '[DOWN]' in line
                status_nsfw = '[NSFW]' in line
                
                # Remove status indicators to get clean line
                clean_line = line.replace('[DOWN]', '').replace('[NSFW]', '').strip()
                
                # Split from right to handle modlist names with dashes
                # Format: "NAME - GAME - SIZES - MACHINE_URL"
                parts = clean_line.rsplit(' - ', 3)  # Split from right, max 3 splits = 4 parts
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

    def _enhance_nexus_error(self, line: str) -> str:
        """
        Enhance Nexus download error messages by adding the mod URL for easier troubleshooting.
        """
        import re
        
        # Pattern to match Nexus download errors with ModID and FileID
        nexus_error_pattern = r"Failed to download '[^']+' from Nexus \(Game: ([^,]+), ModID: (\d+), FileID: \d+\):"
        
        match = re.search(nexus_error_pattern, line)
        if match:
            game_name = match.group(1)
            mod_id = match.group(2)
            
            # Map game names to Nexus URL segments
            game_url_map = {
                'SkyrimSpecialEdition': 'skyrimspecialedition',
                'Skyrim': 'skyrim', 
                'Fallout4': 'fallout4',
                'FalloutNewVegas': 'newvegas',
                'Oblivion': 'oblivion',
                'Starfield': 'starfield'
            }
            
            game_url = game_url_map.get(game_name, game_name.lower())
            mod_url = f"https://www.nexusmods.com/{game_url}/mods/{mod_id}"
            
            # Add URL on next line for easier debugging
            return f"{line}\n  Nexus URL: {mod_url}"
        
        return line