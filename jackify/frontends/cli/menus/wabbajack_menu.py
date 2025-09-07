"""
Wabbajack Tasks Menu Handler for Jackify CLI Frontend
Extracted from src.modules.menu_handler.MenuHandler.show_wabbajack_tasks_menu()
"""

import time

from jackify.shared.colors import (
    COLOR_SELECTION, COLOR_RESET, COLOR_ACTION, COLOR_PROMPT, COLOR_INFO
)
from jackify.shared.ui_utils import print_jackify_banner, print_section_header, clear_screen

class WabbajackMenuHandler:
    """
    Handles the Modlist and Wabbajack Tasks menu
    Extracted from legacy MenuHandler class
    """
    
    def __init__(self):
        self.logger = None  # Will be set by CLI when needed
    
    def _clear_screen(self):
        """Clear the terminal screen with AppImage compatibility"""
        clear_screen()
    
    def show_wabbajack_tasks_menu(self, cli_instance):
        """Show the Modlist and Wabbajack Tasks menu"""
        while True:
            self._clear_screen()
            print_jackify_banner()
            # Use print_section_header for consistency
            print_section_header("Modlist and Wabbajack Tasks")

            print(f"{COLOR_SELECTION}1.{COLOR_RESET} Install a Modlist (Automated)")
            print(f"   {COLOR_ACTION}→ Uses jackify-engine for a full install flow{COLOR_RESET}")
            print(f"{COLOR_SELECTION}2.{COLOR_RESET} Configure New Modlist (Post-Download)")
            print(f"   {COLOR_ACTION}→ Modlist .wabbajack file downloaded? Configure it for Steam{COLOR_RESET}")
            print(f"{COLOR_SELECTION}3.{COLOR_RESET} Configure Existing Modlist (In Steam)")
            print(f"   {COLOR_ACTION}→ Modlist already in Steam? Re-configure it here{COLOR_RESET}")
            # HIDDEN FOR FIRST RELEASE - UNCOMMENT WHEN READY
            # print(f"{COLOR_SELECTION}4.{COLOR_RESET} Install Wabbajack Application")
            # print(f"   {COLOR_ACTION}→ Downloads and configures the Wabbajack app itself (via WINE){COLOR_RESET}")
            print(f"{COLOR_SELECTION}0.{COLOR_RESET} Return to Main Menu")
            selection = input(f"\n{COLOR_PROMPT}Enter your selection (0-3): {COLOR_RESET}").strip()
            
            if selection.lower() == 'q':  # Allow 'q' to re-display menu
                continue

            if selection == "1":
                self._execute_legacy_install_modlist(cli_instance)
            elif selection == "2":
                self._execute_legacy_configure_new_modlist(cli_instance)
            elif selection == "3":
                self._execute_legacy_configure_existing_modlist(cli_instance)
            # HIDDEN FOR FIRST RELEASE - UNCOMMENT WHEN READY
            # elif selection == "4":
            #     self._execute_legacy_install_wabbajack(cli_instance)
            elif selection == "0":
                break
            else:
                print("Invalid selection. Please try again.")
                time.sleep(1)

    def _execute_legacy_install_modlist(self, cli_instance):
        """LEGACY BRIDGE: Execute modlist installation workflow"""
        # Import backend services
        from jackify.backend.core.modlist_operations import ModlistInstallCLI
        from jackify.backend.handlers.menu_handler import MenuHandler
        
        # Create a proper MenuHandler instance with the required methods
        menu_handler = MenuHandler()
        
        # Pass the MenuHandler instance and steamdeck status
        steamdeck_status = getattr(cli_instance, 'steamdeck', False)
        installer = ModlistInstallCLI(menu_handler, steamdeck_status)
        if self.logger:
            self.logger.debug("MenuHandler: ModlistInstallCLI instance created for Install a Modlist.")
        context = installer.run_discovery_phase()
        if context:
            if self.logger:
                self.logger.info("MenuHandler: Discovery phase complete, proceeding to configuration phase.")
            installer.configuration_phase() 
        else:
            if self.logger:
                self.logger.info("MenuHandler: Discovery phase did not return context. Skipping configuration.")
        input("\nPress Enter to return to the Modlist Tasks menu...")  # Standard return prompt

    def _execute_legacy_install_wabbajack(self, cli_instance):
        """LEGACY BRIDGE: Execute Wabbajack application installation"""
        if self.logger:
            self.logger.info("User selected 'Install Wabbajack' from Modlist Tasks menu.")
        # Add introductory text before calling the Wabbajack installation workflow
        self._clear_screen()
        print_jackify_banner()
        print_section_header("Install Wabbajack Application")
        print(f"{COLOR_INFO}This process will guide you through downloading and setting up\nthe Wabbajack application itself.{COLOR_RESET}")
        print("\n")  # Spacer
        cli_instance._cmd_install_wabbajack(None)  # Pass the cli_instance itself

    def _execute_legacy_configure_new_modlist(self, cli_instance):
        """LEGACY BRIDGE: Execute new modlist configuration"""
        # Import backend service
        from jackify.backend.handlers.menu_handler import ModlistMenuHandler
        
        modlist_menu = ModlistMenuHandler(cli_instance.config_handler)
        modlist_menu._configure_new_modlist()

    def _execute_legacy_configure_existing_modlist(self, cli_instance):
        """LEGACY BRIDGE: Execute existing modlist configuration"""
        # Import backend service
        from jackify.backend.handlers.menu_handler import ModlistMenuHandler
        
        modlist_menu = ModlistMenuHandler(cli_instance.config_handler)
        modlist_menu._configure_existing_modlist() 