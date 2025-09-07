"""
Additional Tasks Menu Handler for Jackify CLI Frontend
Extracted from src.modules.menu_handler.MenuHandler.show_additional_tasks_menu()
"""

import time

from jackify.shared.colors import (
    COLOR_SELECTION, COLOR_RESET, COLOR_ACTION, COLOR_PROMPT, COLOR_INFO, COLOR_DISABLED
)
from jackify.shared.ui_utils import print_jackify_banner, print_section_header, clear_screen

class AdditionalMenuHandler:
    """
    Handles the Additional Tasks menu (MO2, NXM Handling & Recovery)
    Extracted from legacy MenuHandler class
    """
    
    def __init__(self):
        self.logger = None  # Will be set by CLI when needed
    
    def _clear_screen(self):
        """Clear the terminal screen with AppImage compatibility"""
        clear_screen()
    
    def show_additional_tasks_menu(self, cli_instance):
        """Show the MO2, NXM Handling & Recovery submenu"""
        while True:
            self._clear_screen()
            print_jackify_banner()
            print_section_header("Additional Utilities")  # Broader title
            
            print(f"{COLOR_SELECTION}1.{COLOR_RESET} Install Mod Organizer 2 (Base Setup)")
            print(f"   {COLOR_ACTION}→ Proton setup for a standalone MO2 instance{COLOR_RESET}")
            print(f"{COLOR_SELECTION}2.{COLOR_RESET} Configure NXM Handling {COLOR_DISABLED}(Not Implemented){COLOR_RESET}")
            print(f"{COLOR_SELECTION}3.{COLOR_RESET} Jackify Recovery Tools")
            print(f"   {COLOR_ACTION}→ Restore files modified or backed up by Jackify{COLOR_RESET}")
            print(f"{COLOR_SELECTION}0.{COLOR_RESET} Return to Main Menu")
            selection = input(f"\n{COLOR_PROMPT}Enter your selection (0-3): {COLOR_RESET}").strip()
            
            if selection.lower() == 'q':  # Allow 'q' to re-display menu
                continue
            if selection == "1":
                self._execute_legacy_install_mo2(cli_instance)
            elif selection == "2":
                print(f"{COLOR_INFO}Configure NXM Handling is not yet implemented.{COLOR_RESET}")
                input("\nPress Enter to return to the Utilities menu...")
            elif selection == "3":
                self._execute_legacy_recovery_menu(cli_instance)
            elif selection == "0":
                break
            else:
                print("Invalid selection. Please try again.")
                time.sleep(1)

    def _execute_legacy_install_mo2(self, cli_instance):
        """LEGACY BRIDGE: Execute MO2 installation"""
        # LEGACY BRIDGE: Use legacy imports until backend migration complete
        if hasattr(cli_instance, 'menu') and hasattr(cli_instance.menu, 'mo2_handler'):
            cli_instance.menu.mo2_handler.install_mo2()
        else:
            print(f"{COLOR_INFO}MO2 handler not available - this will be implemented in Phase 2.3{COLOR_RESET}")
            input("\nPress Enter to continue...")

    def _execute_legacy_recovery_menu(self, cli_instance):
        """LEGACY BRIDGE: Execute recovery menu"""
        # This will be handled by the RecoveryMenuHandler
        from .recovery_menu import RecoveryMenuHandler
        
        recovery_handler = RecoveryMenuHandler()
        recovery_handler.logger = self.logger
        recovery_handler.show_recovery_menu(cli_instance) 