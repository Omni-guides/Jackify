"""
Recovery Menu Handler for Jackify CLI Frontend
Extracted from src.modules.menu_handler.MenuHandler._show_recovery_menu()
"""

import logging
from pathlib import Path

from jackify.shared.colors import (
    COLOR_SELECTION, COLOR_RESET, COLOR_PROMPT, COLOR_INFO, COLOR_ERROR
)
from jackify.shared.ui_utils import print_jackify_banner, print_section_header

class RecoveryMenuHandler:
    """
    Handles the Recovery Tools menu
    Extracted from legacy MenuHandler class
    """
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    def _clear_screen(self):
        """Clear the terminal screen"""
        import os
        os.system('cls' if os.name == 'nt' else 'clear')
    
    def show_recovery_menu(self, cli_instance):
        """Show the recovery tools menu."""
        while True:
            self._clear_screen()
            print_jackify_banner()
            print_section_header('Recovery Tools')
            print(f"{COLOR_INFO}This allows restoring original Steam configuration files from backups created by Jackify.{COLOR_RESET}")
            print(f"{COLOR_SELECTION}1.{COLOR_RESET} Restore all backups")
            print(f"{COLOR_SELECTION}2.{COLOR_RESET} Restore config.vdf only")
            print(f"{COLOR_SELECTION}3.{COLOR_RESET} Restore libraryfolders.vdf only")
            print(f"{COLOR_SELECTION}4.{COLOR_RESET} Restore shortcuts.vdf only")
            print(f"{COLOR_SELECTION}0.{COLOR_RESET} Return to Main Menu")
            
            choice = input(f"\n{COLOR_PROMPT}Enter your selection (0-4): {COLOR_RESET}").strip()

            if choice == "1":
                self._restore_all_backups(cli_instance)
            elif choice == "2":
                self._restore_config_vdf(cli_instance)
            elif choice == "3":
                self._restore_libraryfolders_vdf(cli_instance)
            elif choice == "4":
                self._restore_shortcuts_vdf(cli_instance)
            elif choice == "0":
                break
            else:
                print("Invalid selection. Please try again.")
                input("\nPress Enter to continue...")

    def _restore_all_backups(self, cli_instance):
        """Restore all supported Steam config files"""
        self.logger.info("Recovery selected: Restore all Steam config files")
        print("\nAttempting to restore all supported Steam config files...")
        
        # LEGACY BRIDGE: Use legacy handlers until backend migration complete
        paths_to_check = {
            "libraryfolders": self._get_library_vdf_path(cli_instance),
            "config": self._get_config_vdf_path(cli_instance),
            "shortcuts": self._get_shortcuts_vdf_path(cli_instance)
        }
        
        restored_count = 0
        for file_type, file_path in paths_to_check.items():
            if file_path:
                print(f"Restoring {file_type} ({file_path})...")
                latest_backup = self._find_latest_backup(cli_instance, Path(file_path))
                if latest_backup:
                    if self._restore_backup(cli_instance, latest_backup, Path(file_path)):
                        print(f"Successfully restored {file_type}.")
                        restored_count += 1
                    else:
                        print(f"{COLOR_ERROR}Failed to restore {file_type} from {latest_backup}.{COLOR_RESET}")
                else:
                    print(f"No backup found for {file_type}.")
            else:
                print(f"Could not locate original file for {file_type} to restore.")
        
        print(f"\nRestore process completed. {restored_count}/{len(paths_to_check)} files potentially restored.")
        input("\nPress Enter to continue...")

    def _restore_config_vdf(self, cli_instance):
        """Restore config.vdf only"""
        self.logger.info("Recovery selected: Restore config.vdf only")
        print("\nAttempting to restore config.vdf...")
        
        file_path = self._get_config_vdf_path(cli_instance)
        if file_path:
            latest_backup = self._find_latest_backup(cli_instance, Path(file_path))
            if latest_backup:
                if self._restore_backup(cli_instance, latest_backup, Path(file_path)):
                    print(f"Successfully restored config.vdf from {latest_backup}.")
                else:
                    print(f"{COLOR_ERROR}Failed to restore config.vdf from {latest_backup}.{COLOR_RESET}")
            else:
                print("No backup found for config.vdf.")
        else:
            print("Could not locate config.vdf.")
        input("\nPress Enter to continue...")

    def _restore_libraryfolders_vdf(self, cli_instance):
        """Restore libraryfolders.vdf only"""
        self.logger.info("Recovery selected: Restore libraryfolders.vdf only")
        print("\nAttempting to restore libraryfolders.vdf...")
        
        file_path = self._get_library_vdf_path(cli_instance)
        if file_path:
            latest_backup = self._find_latest_backup(cli_instance, Path(file_path))
            if latest_backup:
                if self._restore_backup(cli_instance, latest_backup, Path(file_path)):
                    print(f"Successfully restored libraryfolders.vdf from {latest_backup}.")
                else:
                    print(f"{COLOR_ERROR}Failed to restore libraryfolders.vdf from {latest_backup}.{COLOR_RESET}")
            else:
                print("No backup found for libraryfolders.vdf.")
        else:
            print("Could not locate libraryfolders.vdf.")
        input("\nPress Enter to continue...")

    def _restore_shortcuts_vdf(self, cli_instance):
        """Restore shortcuts.vdf only"""
        self.logger.info("Recovery selected: Restore shortcuts.vdf only")
        print("\nAttempting to restore shortcuts.vdf...")
        
        file_path = self._get_shortcuts_vdf_path(cli_instance)
        if file_path:
            latest_backup = self._find_latest_backup(cli_instance, Path(file_path))
            if latest_backup:
                if self._restore_backup(cli_instance, latest_backup, Path(file_path)):
                    print(f"Successfully restored shortcuts.vdf from {latest_backup}.")
                else:
                    print(f"{COLOR_ERROR}Failed to restore shortcuts.vdf from {latest_backup}.{COLOR_RESET}")
            else:
                print("No backup found for shortcuts.vdf.")
        else:
            print("Could not locate shortcuts.vdf.")
        input("\nPress Enter to continue...")

    # LEGACY BRIDGE methods - delegate to existing handlers
    def _get_library_vdf_path(self, cli_instance):
        """LEGACY BRIDGE: Get libraryfolders.vdf path"""
        if hasattr(cli_instance, 'path_handler'):
            return cli_instance.path_handler.find_steam_library_vdf_path()
        return None

    def _get_config_vdf_path(self, cli_instance):
        """LEGACY BRIDGE: Get config.vdf path"""
        if hasattr(cli_instance, 'path_handler'):
            return cli_instance.path_handler.find_steam_config_vdf()
        return None

    def _get_shortcuts_vdf_path(self, cli_instance):
        """LEGACY BRIDGE: Get shortcuts.vdf path"""
        if hasattr(cli_instance, 'shortcut_handler'):
            return cli_instance.shortcut_handler._find_shortcuts_vdf()
        return None

    def _find_latest_backup(self, cli_instance, file_path: Path):
        """LEGACY BRIDGE: Find latest backup file"""
        if hasattr(cli_instance, 'filesystem_handler'):
            return cli_instance.filesystem_handler.find_latest_backup(file_path)
        return None

    def _restore_backup(self, cli_instance, backup_path, target_path: Path) -> bool:
        """LEGACY BRIDGE: Restore backup file"""
        if hasattr(cli_instance, 'filesystem_handler'):
            return cli_instance.filesystem_handler.restore_backup(backup_path, target_path)
        return False 