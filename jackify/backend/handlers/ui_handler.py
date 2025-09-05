"""
UIHandler module for managing user interface operations.
This module handles menus, prompts, and user interaction.
"""

import os
import logging
from typing import Optional, List, Dict, Tuple, Callable, Any
from pathlib import Path

class UIHandler:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
    def show_menu(self, title: str, options: List[Dict[str, Any]]) -> Optional[str]:
        """Display a menu and get user selection."""
        try:
            print(f"\n{title}")
            print("=" * len(title))
            
            for i, option in enumerate(options, 1):
                print(f"{i}. {option['label']}")
                
            while True:
                try:
                    choice = input("\nEnter your choice (or 'q' to quit): ")
                    if choice.lower() == 'q':
                        return None
                        
                    choice = int(choice)
                    if 1 <= choice <= len(options):
                        return options[choice - 1]['value']
                    else:
                        print("Invalid choice. Please try again.")
                except ValueError:
                    print("Please enter a number.")
        except Exception as e:
            self.logger.error(f"Failed to show menu: {e}")
            return None
        
    def show_progress(self, message: str, total: int = 100) -> None:
        """Display a progress indicator."""
        try:
            print(f"\n{message}")
            print("[" + " " * 50 + "] 0%", end="\r")
        except Exception as e:
            self.logger.error(f"Failed to show progress: {e}")
        
    def update_progress(self, current: int, message: Optional[str] = None) -> None:
        """Update the progress indicator."""
        try:
            if message:
                print(f"\n{message}")
            progress = int(current / 2)
            print("[" + "=" * progress + " " * (50 - progress) + f"] {current}%", end="\r")
        except Exception as e:
            self.logger.error(f"Failed to update progress: {e}")
        
    def show_error(self, message: str, details: Optional[str] = None) -> None:
        """Display an error message."""
        try:
            print(f"\nError: {message}")
            if details:
                print(f"Details: {details}")
        except Exception as e:
            self.logger.error(f"Failed to show error: {e}")
        
    def show_success(self, message: str, details: Optional[str] = None) -> None:
        """Display a success message."""
        try:
            print(f"\n✓ Success: {message}")
            if details:
                print(f"Details: {details}")
        except Exception as e:
            self.logger.error(f"Failed to show success: {e}")
        
    def show_warning(self, message: str, details: Optional[str] = None) -> None:
        """Display a warning message."""
        try:
            print(f"\nWarning: {message}")
            if details:
                print(f"Details: {details}")
        except Exception as e:
            self.logger.error(f"Failed to show warning: {e}")
        
    def get_input(self, prompt: str, default: Optional[str] = None) -> str:
        """Get user input with optional default value."""
        try:
            if default:
                user_input = input(f"{prompt} [{default}]: ")
                return user_input if user_input else default
            return input(f"{prompt}: ")
        except Exception as e:
            self.logger.error(f"Failed to get input: {e}")
            return ""
        
    def get_confirmation(self, message: str, default: bool = True) -> bool:
        """Get user confirmation for an action."""
        try:
            default_str = "Y/n" if default else "y/N"
            while True:
                response = input(f"{message} [{default_str}]: ").lower()
                if not response:
                    return default
                if response in ['y', 'yes']:
                    return True
                if response in ['n', 'no']:
                    return False
                print("Please enter 'y' or 'n'.")
        except Exception as e:
            self.logger.error(f"Failed to get confirmation: {e}")
            return default
        
    def show_list(self, title: str, items: List[str], selectable: bool = True) -> Optional[str]:
        """Display a list of items, optionally selectable."""
        try:
            print(f"\n{title}")
            print("=" * len(title))
            
            for i, item in enumerate(items, 1):
                print(f"{i}. {item}")
                
            if selectable:
                while True:
                    try:
                        choice = input("\nEnter your choice (or 'q' to quit): ")
                        if choice.lower() == 'q':
                            return None
                            
                        choice = int(choice)
                        if 1 <= choice <= len(items):
                            return items[choice - 1]
                        else:
                            print("Invalid choice. Please try again.")
                    except ValueError:
                        print("Please enter a number.")
            return None
        except Exception as e:
            self.logger.error(f"Failed to show list: {e}")
            return None
        
    def show_table(self, title: str, headers: List[str], rows: List[List[str]]) -> None:
        """Display data in a table format."""
        try:
            print(f"\n{title}")
            print("=" * len(title))
            
            # Calculate column widths
            widths = [len(h) for h in headers]
            for row in rows:
                for i, cell in enumerate(row):
                    widths[i] = max(widths[i], len(str(cell)))
                    
            # Print headers
            header_str = " | ".join(f"{h:<{w}}" for h, w in zip(headers, widths))
            print(header_str)
            print("-" * len(header_str))
            
            # Print rows
            for row in rows:
                print(" | ".join(f"{str(cell):<{w}}" for cell, w in zip(row, widths)))
        except Exception as e:
            self.logger.error(f"Failed to show table: {e}")
        
    def show_help(self, topic: str) -> None:
        """Display help information for a topic."""
        try:
            # This would typically load help content from a file or database
            print(f"\nHelp: {topic}")
            print("=" * (len(topic) + 6))
            print("Help content would be displayed here.")
        except Exception as e:
            self.logger.error(f"Failed to show help: {e}")
        
    def clear_screen(self) -> None:
        """Clear the terminal screen."""
        try:
            os.system('clear' if os.name == 'posix' else 'cls')
        except Exception as e:
            self.logger.error(f"Failed to clear screen: {e}") 