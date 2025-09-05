"""
Hoolamike Menu Handler for Jackify CLI Frontend
Extracted from src.modules.menu_handler.MenuHandler.show_hoolamike_menu()
"""

from jackify.shared.colors import COLOR_INFO, COLOR_PROMPT, COLOR_RESET

class HoolamikeMenuHandler:
    """
    Handles the Hoolamike Tasks menu
    Extracted from legacy MenuHandler class
    """
    
    def __init__(self):
        self.logger = None  # Will be set by CLI when needed
    
    def show_hoolamike_menu(self, cli_instance):
        """
        LEGACY BRIDGE: Delegate to legacy menu handler until full backend migration
        
        Args:
            cli_instance: Reference to main CLI instance for access to handlers
        """
        print(f"{COLOR_INFO}Hoolamike menu functionality has been extracted but needs migration to backend services.{COLOR_RESET}")
        print(f"{COLOR_INFO}This will be implemented in Phase 2.3 (Menu Backend Integration).{COLOR_RESET}")
        
        # LEGACY BRIDGE: Use the original menu handler's method
        if hasattr(cli_instance, 'menu') and hasattr(cli_instance.menu, 'show_hoolamike_menu'):
            cli_instance.menu.show_hoolamike_menu(cli_instance)
        else:
            print(f"{COLOR_INFO}Legacy menu handler not available - returning to main menu.{COLOR_RESET}")
            input(f"{COLOR_PROMPT}Press Enter to continue...{COLOR_RESET}") 