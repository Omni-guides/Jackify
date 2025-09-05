"""
Tuxborn Menu Handler for Jackify CLI Frontend  
Extracted from src.modules.menu_handler.MenuHandler.show_tuxborn_installer_menu()
"""

from pathlib import Path
from typing import Optional

from jackify.shared.colors import (
    COLOR_SELECTION, COLOR_RESET, COLOR_INFO, COLOR_PROMPT, COLOR_WARNING
)
from jackify.shared.ui_utils import print_jackify_banner
from jackify.backend.handlers.config_handler import ConfigHandler

class TuxbornMenuHandler:
    """
    Handles the Tuxborn Automatic Installer workflow
    Extracted from legacy MenuHandler class
    """
    
    def __init__(self):
        self.logger = None  # Will be set by CLI when needed
    
    def show_tuxborn_installer_menu(self, cli_instance):
        """
        Implements the Tuxborn Automatic Installer workflow.
        Prompts for install path, downloads path, and Nexus API key, then runs the one-shot install from start to finish
        
        Args:
            cli_instance: Reference to main CLI instance for access to handlers
        """
        # Import backend service
        from jackify.backend.core.modlist_operations import ModlistInstallCLI
        
        print_jackify_banner()
        print(f"{COLOR_SELECTION}Tuxborn Automatic Installer{COLOR_RESET}")
        print(f"{COLOR_SELECTION}{'-'*32}{COLOR_RESET}")
        print(f"{COLOR_INFO}This will install the Tuxborn modlist using the custom Jackify Install Engine in one automated flow.{COLOR_RESET}")
        print(f"{COLOR_INFO}You will be prompted for the install location, downloads directory, and your Nexus API key.{COLOR_RESET}\n")
        
        tuxborn_machineid = "Tuxborn/Tuxborn"
        tuxborn_modlist_name = "Tuxborn"

        # Prompt for install directory
        print("----------------------------")
        config_handler = ConfigHandler()
        base_install_dir = Path(config_handler.get_modlist_install_base_dir())
        default_install_dir = base_install_dir / "Skyrim" / "Tuxborn"
        print(f"{COLOR_PROMPT}Please enter the directory you wish to use for Tuxborn installation.{COLOR_RESET}")
        print(f"(Default: {default_install_dir})")
        install_dir_result = self._get_directory_path_legacy(
            cli_instance,
            prompt_message=f"{COLOR_PROMPT}Install directory (Enter for default, 'q' to cancel): {COLOR_RESET}",
            default_path=default_install_dir,
            create_if_missing=True,
            no_header=True
        )
        if not install_dir_result:
            print(f"{COLOR_INFO}Cancelled by user.{COLOR_RESET}")
            input("Press Enter to return to the main menu...")
            return
        if isinstance(install_dir_result, tuple):
            install_dir, _ = install_dir_result  # We'll use the path, creation handled by engine or later
        else:
            install_dir = install_dir_result

        # Prompt for download directory
        print("----------------------------")
        base_download_dir = Path(config_handler.get_modlist_downloads_base_dir())
        default_download_dir = base_download_dir / "Tuxborn"
        print(f"{COLOR_PROMPT}Please enter the directory you wish to use for Tuxborn downloads.{COLOR_RESET}")
        print(f"(Default: {default_download_dir})")
        download_dir_result = self._get_directory_path_legacy(
            cli_instance,
            prompt_message=f"{COLOR_PROMPT}Download directory (Enter for default, 'q' to cancel): {COLOR_RESET}",
            default_path=default_download_dir,
            create_if_missing=True,
            no_header=True
        )
        if not download_dir_result:
            print(f"{COLOR_INFO}Cancelled by user.{COLOR_RESET}")
            input("Press Enter to return to the main menu...")
            return
        if isinstance(download_dir_result, tuple):
            download_dir, _ = download_dir_result  # We'll use the path, creation handled by engine or later
        else:
            download_dir = download_dir_result

        # Prompt for Nexus API key
        print("----------------------------")
        from jackify.backend.services.api_key_service import APIKeyService
        api_key_service = APIKeyService()
        saved_key = api_key_service.get_saved_api_key()
        api_key = None
        
        if saved_key:
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
                            print(f"{COLOR_INFO}API key saved successfully.{COLOR_RESET}")
                        else:
                            print(f"{COLOR_WARNING}Failed to save API key. Using for this session only.{COLOR_RESET}")
                    else:
                        print(f"{COLOR_INFO}Using new key for this session only. Saved key unchanged.{COLOR_RESET}")
                else:
                    api_key = saved_key
        else:
            print(f"{COLOR_PROMPT}A Nexus Mods API key is required for downloading mods.{COLOR_RESET}")
            print(f"{COLOR_INFO}You can get your personal key at: {COLOR_SELECTION}https://www.nexusmods.com/users/myaccount?tab=api{COLOR_RESET}")
            print(f"{COLOR_WARNING}Your API Key is NOT saved locally. It is used only for this session unless you choose to save it.{COLOR_RESET}")
            api_key = input(f"{COLOR_PROMPT}Enter Nexus API Key (or 'q' to cancel): {COLOR_RESET}").strip()
            if not api_key or api_key.lower() == 'q':
                print(f"{COLOR_INFO}Cancelled by user.{COLOR_RESET}")
                input("Press Enter to return to the main menu...")
                return
            save = input(f"{COLOR_PROMPT}Would you like to save this API key for future use? [y/N]: {COLOR_RESET}").strip().lower()
            if save == 'y':
                if api_key_service.save_api_key(api_key):
                    print(f"{COLOR_INFO}API key saved successfully.{COLOR_RESET}")
                else:
                    print(f"{COLOR_WARNING}Failed to save API key. Using for this session only.{COLOR_RESET}")
            else:
                print(f"{COLOR_INFO}Using API key for this session only. It will not be saved.{COLOR_RESET}")

        # Context for ModlistInstallCLI
        context = {
            'machineid': tuxborn_machineid,
            'modlist_name': tuxborn_modlist_name,  # Will be used for shortcut name
            'install_dir': install_dir_result,  # Pass tuple (path, create_flag) or path
            'download_dir': download_dir_result,  # Pass tuple (path, create_flag) or path
            'nexus_api_key': api_key,
            'resolution': None
        }

        modlist_cli = ModlistInstallCLI(self, getattr(cli_instance, 'steamdeck', False))
        
        # run_discovery_phase will use context_override, display summary, and ask for confirmation.
        # If user confirms, it returns the context, otherwise None.
        confirmed_context = modlist_cli.run_discovery_phase(context_override=context)

        if confirmed_context:
            if self.logger:
                self.logger.info("Tuxborn discovery confirmed by user. Proceeding to configuration/installation.")
            # The modlist_cli instance now holds the confirmed context.
            # configuration_phase will use modlist_cli.context
            modlist_cli.configuration_phase() 
            # After configuration_phase, messages about success or next steps are handled within it or by _configure_new_modlist
        else:
            if self.logger:
                self.logger.info("Tuxborn discovery/confirmation cancelled or failed.")
            print(f"{COLOR_INFO}Tuxborn installation cancelled or not confirmed.{COLOR_RESET}")
            input(f"{COLOR_PROMPT}Press Enter to return to the main menu...{COLOR_RESET}")
            return

    def _get_directory_path_legacy(self, cli_instance, prompt_message: str, default_path: Optional[Path], 
                                  create_if_missing: bool = True, no_header: bool = False) -> Optional[Path]:
        """
        LEGACY BRIDGE: Delegate to legacy menu handler until full backend migration
        
        Args:
            cli_instance: Reference to main CLI instance
            prompt_message: The prompt to show user
            default_path: Default path if user presses Enter
            create_if_missing: Whether to create directory if it doesn't exist
            no_header: Whether to skip header display
            
        Returns:
            Path object or None if cancelled
        """
        # LEGACY BRIDGE: Use the original menu handler's method
        if hasattr(cli_instance, 'menu') and hasattr(cli_instance.menu, 'get_directory_path'):
            return cli_instance.menu.get_directory_path(
                prompt_message=prompt_message,
                default_path=default_path,
                create_if_missing=create_if_missing,
                no_header=no_header
            )
        else:
            # Fallback: simple input for now (will be replaced in future phases)
            response = input(prompt_message).strip()
            if response.lower() == 'q':
                return None
            elif response == '':
                return default_path
            else:
                return Path(response) 