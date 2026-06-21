"""
Main Menu Handler for Jackify CLI Frontend
Extracted from src.modules.menu_handler.MenuHandler.show_main_menu()
"""

import time
from typing import Optional

from jackify.shared.colors import (
    COLOR_SELECTION, COLOR_RESET, COLOR_ACTION, COLOR_PROMPT, COLOR_ERROR
)
from jackify.shared.ui_utils import print_jackify_banner, clear_screen

class MainMenuHandler:
    """
    Handles the main interactive menu display and user input routing
    Extracted from legacy MenuHandler class
    """
    
    def __init__(self, dev_mode=False):
        self.logger = None  # Will be set by CLI when needed
        self.dev_mode = dev_mode
    
    def _clear_screen(self):
        """Clear the terminal screen with AppImage compatibility"""
        clear_screen()
    
    def show_main_menu(self, cli_instance) -> str:
        """
        Show the main menu and return user selection
        
        Args:
            cli_instance: Reference to main CLI instance for access to handlers
            
        Returns:
            str: Menu choice ("wabbajack", "hoolamike", "additional", "exit", "tuxborn")
        """
        while True:
            self._clear_screen()
            print_jackify_banner()
            print(f"{COLOR_SELECTION}Main Menu{COLOR_RESET}")
            print(f"{COLOR_SELECTION}{'-'*22}{COLOR_RESET}")  # Standard separator
            print(f"{COLOR_SELECTION}1.{COLOR_RESET} Modlist Tasks")
            print(f"   {COLOR_ACTION}→ Install & Configure Modlists{COLOR_RESET}")
            print(f"{COLOR_SELECTION}2.{COLOR_RESET} Additional Tasks & Tools")
            print(f"   {COLOR_ACTION}→ Verifier, Diagnostics, Nexus OAuth & more{COLOR_RESET}")
            print(f"{COLOR_SELECTION}3.{COLOR_RESET} Tools Hub")
            print(f"   {COLOR_ACTION}→ Install, update, or switch engines and tools{COLOR_RESET}")
            print(f"{COLOR_SELECTION}0.{COLOR_RESET} Exit Jackify")
            choice = input(f"\n{COLOR_PROMPT}Enter your selection (0-3): {COLOR_RESET}").strip()

            if choice.lower() == 'q':  # Allow 'q' to re-display menu
                continue
            if choice == "1":
                return "wabbajack"
            elif choice == "2":
                return "additional"
            elif choice == "3":
                return "tools_hub"
            elif choice == "0":
                return "exit"
            else:
                print(f"{COLOR_ERROR}Invalid selection. Please try again.{COLOR_RESET}")
                time.sleep(1)  # Brief pause for readability 