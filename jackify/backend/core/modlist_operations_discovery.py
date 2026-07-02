"""Discovery phase methods for ModlistInstallCLI (Mixin)."""
import logging
import os
from pathlib import Path
from typing import Optional, Dict

from jackify.shared.colors import (
    COLOR_PROMPT,
    COLOR_RESET,
    COLOR_INFO,
    COLOR_ERROR,
    COLOR_SUCCESS,
    COLOR_WARNING,
    COLOR_SELECTION,
)
from ..handlers.config_handler import ConfigHandler
from jackify.backend.models.configuration import SystemInfo
from jackify.backend.services.modlist_service import ModlistService

logger = logging.getLogger(__name__)


class ModlistOperationsDiscoveryMixin:
    """Mixin providing modlist discovery phase methods."""

    def run_discovery_phase(self, context_override=None) -> Optional[Dict]:
        """
        Run the discovery phase: prompt for all required info, and validate inputs.
        Returns a context dict with all collected info, or None if cancelled.
        Accepts context_override for pre-filled values (e.g., for Tuxborn/machineid flow).
        """
        from .modlist_operations import get_jackify_engine_path

        self.logger.info("Starting modlist discovery phase (restored logic).")
        print(f"\n{COLOR_PROMPT}--- Wabbajack Modlist Install: Discovery Phase ---{COLOR_RESET}")

        if context_override:
            self.context.update(context_override)
            if 'resolution' in context_override:
                self.context['resolution'] = context_override['resolution']
        else:
            self.context = {}

        is_gui_mode = os.environ.get('JACKIFY_GUI_MODE') == '1'
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

        engine_executable = get_jackify_engine_path()
        self.logger.debug(f"Engine executable path: {engine_executable}")

        if not os.path.exists(engine_executable):
            print(f"{COLOR_ERROR}Error: jackify-install-engine not found at expected location.{COLOR_RESET}")
            print(f"{COLOR_INFO}Expected: {engine_executable}{COLOR_RESET}")
            return None

        engine_dir = os.path.dirname(engine_executable)

        if 'machineid' not in self.context:
            print("\n" + "-" * 28)
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
                    is_steamdeck = False
                    if os.path.exists('/etc/os-release'):
                        with open('/etc/os-release') as f:
                            if 'steamdeck' in f.read().lower():
                                is_steamdeck = True
                    system_info = SystemInfo(is_steamdeck=is_steamdeck)
                    modlist_service = ModlistService(system_info)

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
                    extension_filter=".wabbajack",
                    no_header=True
                )
                if modlist_path is None:
                    self.logger.info("User cancelled .wabbajack file selection.")
                    print(f"{COLOR_INFO}Cancelled by user.{COLOR_RESET}")
                    return None

                self.context['modlist_source'] = 'path'
                self.context['modlist_value'] = str(modlist_path)
                self.context['modlist_name_suggestion'] = Path(modlist_path).stem
                self.logger.info(f"User selected local .wabbajack file: {modlist_path}")

            elif source_choice == '0':
                self.logger.info("User cancelled modlist source selection.")
                print(f"{COLOR_INFO}Returning to previous menu.{COLOR_RESET}")
                return None
            else:
                self.logger.warning(f"Invalid modlist source choice: {source_choice}")
                print(f"{COLOR_ERROR}Invalid selection. Please try again.{COLOR_RESET}")
                return self.run_discovery_phase()

        if 'modlist_name' not in self.context or not self.context['modlist_name']:
            default_name = self.context.get('modlist_name_suggestion', 'MyModlist')
            print("\n" + "-" * 28)
            print(f"{COLOR_PROMPT}Enter a name for this modlist installation in Steam.{COLOR_RESET}")
            print(f"{COLOR_INFO}(This will be the shortcut name. Default: {default_name}){COLOR_RESET}")
            modlist_name_input = input(f"{COLOR_PROMPT}Modlist Name (or 'q' to cancel): {COLOR_RESET}").strip()
            if not modlist_name_input:
                modlist_name = default_name
            elif modlist_name_input.lower() == 'q':
                self.logger.info("User cancelled at modlist name prompt.")
                return None
            else:
                modlist_name = modlist_name_input
            self.context['modlist_name'] = modlist_name
        self.logger.debug(f"Modlist name set to: {self.context['modlist_name']}")

        if 'install_dir' not in self.context:
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

        if 'download_dir' not in self.context:
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

        install_dir_value = self.context.get('install_dir')
        install_dir_real = os.path.realpath(str(install_dir_value[0] if isinstance(install_dir_value, tuple) else install_dir_value))
        existing_appid = self._find_existing_shortcut_appid(self.context['modlist_name'], install_dir_real)
        eligible_update, update_meta = self._evaluate_update_candidate(
            self.context['modlist_name'],
            install_dir_real,
            existing_appid,
        )
        if eligible_update:
            print("\n" + "-" * 28)
            print(f"{COLOR_WARNING}Existing modlist installation detected in this directory.{COLOR_RESET}")
            relation = update_meta.get("version_relation")
            if relation == "different":
                print(
                    f"{COLOR_INFO}Detected version change: installed v{update_meta.get('installed_version')} -> "
                    f"selected v{update_meta.get('requested_version')}.{COLOR_RESET}"
                )
            elif relation == "same" and update_meta.get("installed_version"):
                print(
                    f"{COLOR_INFO}Detected same version (v{update_meta.get('installed_version')}). "
                    "Use update mode for repair/reconfigure behavior." + f"{COLOR_RESET}"
                )
            print("Choose how to proceed:")
            print("  1. Update existing install (recommended)")
            print("  2. New install with a different Steam shortcut name")
            print("  0. Cancel")
            update_choice = input(f"{COLOR_PROMPT}Enter your selection (0-2): {COLOR_RESET}").strip()
            if update_choice == "1":
                self.context['update_existing_install'] = True
                self.context['existing_shortcut_appid'] = existing_appid
                self.logger.info("CLI update mode selected; reusing AppID %s", existing_appid)
            elif update_choice == "2":
                print(
                    f"{COLOR_WARNING}For a new install, choose a different Modlist Name before proceeding.{COLOR_RESET}"
                )
                return None
            else:
                self.logger.info("User cancelled at CLI update detection prompt.")
                return None

        if 'nexus_api_key' not in self.context or not self.context.get('nexus_api_key'):
            from jackify.backend.services.nexus_auth_service import NexusAuthService
            auth_service = NexusAuthService()
            authenticated, method, username = auth_service.get_auth_status()

            if authenticated:
                if method == 'oauth':
                    print("\n" + "-" * 28)
                    print(f"{COLOR_SUCCESS}Nexus Authentication: Authorized via OAuth{COLOR_RESET}")
                    if username:
                        print(f"{COLOR_INFO}Logged in as: {username}{COLOR_RESET}")
                elif method == 'api_key':
                    print("\n" + "-" * 28)
                    print(f"{COLOR_INFO}Nexus Authentication: Using API Key (Legacy){COLOR_RESET}")

                api_key, oauth_info = auth_service.get_auth_for_engine()
                if api_key:
                    self.context['nexus_api_key'] = api_key
                    self.context['nexus_oauth_info'] = oauth_info
                else:
                    print(f"\n{COLOR_WARNING}Your authentication has expired or is invalid.{COLOR_RESET}")
                    authenticated = False

            if not authenticated:
                print("\n" + "-" * 28)
                print(f"{COLOR_WARNING}Nexus Mods authentication is required for downloading mods.{COLOR_RESET}")
                print(f"\n{COLOR_PROMPT}Would you like to authorize with Nexus now?{COLOR_RESET}")
                print(f"{COLOR_INFO}This will open your browser for secure OAuth authorization.{COLOR_RESET}")

                authorize = input(f"{COLOR_PROMPT}Authorize now? [Y/n]: {COLOR_RESET}").strip().lower()

                if authorize in ('', 'y', 'yes'):
                    print(f"\n{COLOR_INFO}Starting OAuth authorization...{COLOR_RESET}")
                    print(f"{COLOR_WARNING}Your browser will open shortly.{COLOR_RESET}")
                    print(f"{COLOR_INFO}Note: You may see a security warning about a self-signed certificate.{COLOR_RESET}")
                    print(f"{COLOR_INFO}This is normal - click 'Advanced' and 'Proceed' to continue.{COLOR_RESET}")

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
                            self.context['nexus_oauth_info'] = oauth_info
                        else:
                            print(f"{COLOR_ERROR}Failed to retrieve auth token after authorization.{COLOR_RESET}")
                            return None
                    else:
                        print(f"\n{COLOR_ERROR}OAuth authorization failed.{COLOR_RESET}")
                        return None
                else:
                    print(f"\n{COLOR_INFO}Authorization required to proceed. Installation cancelled.{COLOR_RESET}")
                    self.logger.info("User declined Nexus authorization.")
                    return None
        self.logger.debug("Nexus authentication configured for engine.")

        self._display_summary()

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

        if game_type and not self.wabbajack_parser.is_supported_game(game_type):
            print("\n" + "─" * 46)
            print("  Game Support Notice\n")
            print(f"You are about to install a modlist for: {game_name or 'Unknown'}\n")
            print("Jackify does not provide post-install configuration for this game.")
            print("You can still install and use the modlist, but you will need to manually set up Steam shortcuts and other steps after installation.\n")
            print("Press [Enter] to continue, or [Ctrl+C] to cancel.")
            print("─" * 46 + "\n")
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

        self.logger.info("Discovery phase complete.")
        context_for_logging = self.context.copy()
        if 'nexus_api_key' in context_for_logging and context_for_logging['nexus_api_key'] is not None:
            context_for_logging['nexus_api_key'] = "[REDACTED]"
        self.logger.info(f"Context: {context_for_logging}")
        return self.context
