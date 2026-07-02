"""Discovery phase methods for ModlistInstallCLI (Mixin)."""
import logging
import os
import subprocess
from pathlib import Path
from typing import Optional, Dict

from .config_handler import ConfigHandler
from jackify.shared.colors import (
    COLOR_PROMPT,
    COLOR_RESET,
    COLOR_INFO,
    COLOR_ERROR,
    COLOR_SUCCESS,
    COLOR_WARNING,
    COLOR_SELECTION,
)

logger = logging.getLogger(__name__)


class ModlistInstallCLIDiscoveryMixin:
    """Mixin providing discovery phase methods."""

    def run_discovery_phase(self, context_override=None) -> Optional[Dict]:
        """
        Run the discovery phase: prompt for all required info, and validate inputs.
        Returns a context dict with all collected info, or None if cancelled.
        Accepts context_override for pre-filled values (e.g., for Tuxborn/machineid flow).
        """
        self.logger.info("Starting modlist discovery phase (restored logic).")
        from .modlist_install_cli import get_jackify_engine_path

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
                self.logger.error(f"Missing required arguments for GUI workflow: {', '.join(missing)}")
                if not has_modlist:
                    self.logger.error("Missing modlist_value or machineid for GUI workflow.")
                self.logger.error("This workflow must be fully non-interactive. Please report this as a bug if you see this message.")
                return None
            self.logger.info("All required context present in GUI mode, skipping prompts.")
            return self.context

        # Get engine path using the helper
        engine_executable = get_jackify_engine_path()
        self.logger.debug(f"Engine executable path: {engine_executable}")

        if not os.path.exists(engine_executable):
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
        
        # 5. Get Nexus authentication (OAuth or API key)
        if 'nexus_api_key' not in self.context:
            from jackify.backend.services.nexus_auth_service import NexusAuthService
            auth_service = NexusAuthService()

            # Get current auth status
            authenticated, method, username = auth_service.get_auth_status()

            if authenticated:
                # Already authenticated - use existing auth
                if method == 'oauth':
                    print("\n" + "-" * 28)
                    print(f"{COLOR_SUCCESS}Nexus Authentication: Authorized via OAuth{COLOR_RESET}")
                    if username:
                        print(f"{COLOR_INFO}Logged in as: {username}{COLOR_RESET}")
                elif method == 'api_key':
                    print("\n" + "-" * 28)
                    print(f"{COLOR_INFO}Nexus Authentication: Using API Key (Legacy){COLOR_RESET}")

                # Get valid token/key and OAuth state for engine auto-refresh
                api_key, oauth_info = auth_service.get_auth_for_engine()
                if api_key:
                    self.context['nexus_api_key'] = api_key
                    self.context['nexus_oauth_info'] = oauth_info  # For engine auto-refresh
                else:
                    # Auth expired or invalid - prompt to set up
                    print(f"\n{COLOR_WARNING}Your authentication has expired or is invalid.{COLOR_RESET}")
                    authenticated = False

            if not authenticated:
                # Not authenticated - offer to set up OAuth
                print("\n" + "-" * 28)
                print(f"{COLOR_WARNING}Nexus Mods authentication is required for downloading mods.{COLOR_RESET}")
                print(f"\n{COLOR_PROMPT}Would you like to authorize with Nexus now?{COLOR_RESET}")
                print(f"{COLOR_INFO}This will open your browser for secure OAuth authorization.{COLOR_RESET}")

                authorize = input(f"{COLOR_PROMPT}Authorize now? [Y/n]: {COLOR_RESET}").strip().lower()

                if authorize in ('', 'y', 'yes'):
                    # Launch OAuth authorization
                    print(f"\n{COLOR_INFO}Starting OAuth authorization...{COLOR_RESET}")
                    print(f"{COLOR_WARNING}Your browser will open shortly.{COLOR_RESET}")
                    print(f"{COLOR_INFO}Note: Your browser may ask permission to open 'xdg-open' or{COLOR_RESET}")
                    print(f"{COLOR_INFO}Jackify's protocol handler - please click 'Open' or 'Allow'.{COLOR_RESET}")

                    def show_message(msg):
                        print(f"\n{COLOR_INFO}{msg}{COLOR_RESET}")

                    success = auth_service.authorize_oauth(show_browser_message_callback=show_message)

                    if success:
                        print(f"\n{COLOR_SUCCESS}OAuth authorization successful!{COLOR_RESET}")
                        _, _, username = auth_service.get_auth_status()
                        if username:
                            print(f"{COLOR_INFO}Authorized as: {username}{COLOR_RESET}")

                        api_key, oauth_info = auth_service.get_auth_for_engine()
                        if api_key:
                            self.context['nexus_api_key'] = api_key
                            self.context['nexus_oauth_info'] = oauth_info  # For engine auto-refresh
                        else:
                            print(f"{COLOR_ERROR}Failed to retrieve auth token after authorization.{COLOR_RESET}")
                            return None
                    else:
                        print(f"\n{COLOR_ERROR}OAuth authorization failed.{COLOR_RESET}")
                        return None
                else:
                    # User declined OAuth - cancelled
                    print(f"\n{COLOR_INFO}Authorization required to proceed. Installation cancelled.{COLOR_RESET}")
                    self.logger.info("User declined Nexus authorization.")
                    return None
        self.logger.debug(f"Nexus authentication configured for engine.")

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

