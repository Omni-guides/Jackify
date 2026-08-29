#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Menu Handler Module
Handles CLI menu system for Jackify
"""

import os
import sys
import logging
import subprocess # Add subprocess import
import argparse
import re
from typing import List, Dict, Optional
from pathlib import Path
import glob  # Add for the simpler tab completion

# Import colors from the new central location
from jackify.shared.colors import (
    COLOR_PROMPT, COLOR_RESET, COLOR_INFO, COLOR_ERROR, COLOR_WARNING
)

# Import our modules
# Ensure these imports are correct based on your project structure
from .modlist_handler import ModlistHandler
from .shortcut_handler import ShortcutHandler
from .config_handler import ConfigHandler
from .filesystem_handler import FileSystemHandler
from .resolution_handler import ResolutionHandler
from .protontricks_handler import ProtontricksHandler
from .path_handler import PathHandler
from .vdf_handler import VDFHandler
from .completers import path_completer

try:
    import readline
except ImportError:
    readline = None

# Define exports for this module
__all__ = [
    'MenuHandler', 
    'ModlistMenuHandler',
    'simple_path_completer'  # Export the function without underscore
]

# Initialize logger
logger = logging.getLogger(__name__)

from .menu_handler_input import (
    basic_input_prompt, input_prompt, simple_path_completer,
    READLINE_AVAILABLE, READLINE_HAS_PROMPT, READLINE_HAS_DISPLAY_HOOK,
)
from .menu_handler_modlist import ModlistMenuHandler

class MenuHandler:
    """
    Handles CLI menu display and interaction
    """
    
    def __init__(self, logger_instance=None):
        if logger_instance:
            self.logger = logger_instance
        else:
            self.logger = logging.getLogger(__name__)
        self.config_handler = ConfigHandler()
        self.shortcut_handler = ShortcutHandler(
            steamdeck=self.config_handler.settings.get('steamdeck', False),
            verbose=False
        )
    
    def display_banner(self):
        """Display the application banner - DEPRECATED: Banner display should be handled by frontend"""
        os.system('cls' if os.name == 'nt' else 'clear')
        # Banner display handled by frontend
    




    def get_input_with_default(self, prompt, default=None):
        """
        Get user input with an optional default value.
        Returns the user input or the default value, or None if cancelled by 'q'.
        """
        print("\n" + "-" * 28) # Separator
        print(f"{COLOR_PROMPT}{prompt}{COLOR_RESET}") # Main prompt message
        if default is not None:
            print(f"{COLOR_INFO}(Default: {default}){COLOR_RESET}")
        
        try:
            # Consistent input line
            user_input = input(f"{COLOR_PROMPT}Enter value (or 'q' to cancel, Enter for default): {COLOR_RESET}").strip()
            if user_input.lower() == 'q':
                self.logger.info(f"User cancelled input for prompt: '{prompt}'")
                print(f"{COLOR_INFO}Input cancelled by user.{COLOR_RESET}")
                return None # Explicit None for cancellation
            return user_input if user_input else default
        except KeyboardInterrupt:
            self.logger.info(f"User cancelled input via Ctrl+C for prompt: '{prompt}'")
            print("\nInput cancelled.") 
            return None # Explicit None for cancellation

    def show_progress(self, step, percent, message):
        """
        Display a progress bar with the current step and message
        """
        # Ensure percent is within bounds
        percent = max(0, min(100, int(percent))) 
        bar_length = 50
        filled_length = int(bar_length * percent / 100)
        bar = '=' * filled_length + ' ' * (bar_length - filled_length)
        
        # Use \r to return to the beginning of the line, \033[K to clear the rest
        print(f"\r\033[K[{bar}] {percent}% - {step}: {message}", end='')
        if percent == 100:
             print() # Add a newline when complete
        sys.stdout.flush()
    
    def _clear_screen(self):
        """Clears the terminal screen with fallbacks."""
        self.logger.debug(f"_clear_screen: Detected os.name: {os.name}")
        if os.name == 'nt':
            self.logger.debug("_clear_screen: Clearing screen for NT by attempting command: cls via os.system")
            os.system('cls')
        else:
            try:
                # Attempt 1: Specific path to clear
                self.logger.debug("_clear_screen: Attempting /usr/bin/clear")
                subprocess.run(['/usr/bin/clear'], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                self.logger.debug("_clear_screen: /usr/bin/clear succeeded")
                return
            except FileNotFoundError:
                self.logger.warning("_clear_screen: /usr/bin/clear not found.")
            except subprocess.CalledProcessError as e:
                self.logger.warning(f"_clear_screen: /usr/bin/clear failed: {e}")
            except Exception as e:
                self.logger.error(f"_clear_screen: Unexpected error with /usr/bin/clear: {e}")

            try:
                # Attempt 2: 'clear' command (relies on PATH)
                self.logger.debug("_clear_screen: Attempting 'clear' from PATH")
                subprocess.run(['clear'], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                self.logger.debug("_clear_screen: 'clear' from PATH succeeded")
                return
            except FileNotFoundError:
                self.logger.warning("_clear_screen: 'clear' not found in PATH.")
            except subprocess.CalledProcessError as e:
                self.logger.warning(f"_clear_screen: 'clear' from PATH failed: {e}")
            except Exception as e:
                self.logger.error(f"_clear_screen: Unexpected error with 'clear' from PATH: {e}")

            # Attempt 3: Fallback to printing newlines (guaranteed)
            self.logger.debug("_clear_screen: Clearing screen for POSIX by printing 100 newlines.")
            print("\n" * 100, flush=True)




    def _ask_try_again(self):
        """Prompt the user to try again or cancel. Returns True to retry, False to cancel."""
        while True:
            choice = input(f"{COLOR_PROMPT}Try again? (Y/n/q): {COLOR_RESET}").strip().lower()
            if choice == '' or choice.startswith('y'):
                return True
            elif choice == 'n' or choice == 'q':
                return False
            else:
                print(f"{COLOR_ERROR}Invalid input. Please enter 'y', 'n', or 'q'.{COLOR_RESET}")

    def get_directory_path(self, prompt_message: str, default_path: Optional[Path], create_if_missing: bool = True, no_header: bool = False) -> Optional[Path]:
        """
        Prompts the user for a directory path. If the directory does not exist, asks if it should be created.
        Returns a tuple (chosen_path, should_create) if creation is needed, or just the path if it exists.
        The actual directory creation should be performed after summary confirmation.
        """
        if not no_header:
            print("\n" + "-" * 28)
            print(f"{COLOR_PROMPT}{prompt_message}{COLOR_RESET}")
            if default_path is not None: # Explicit check
                print(f"{COLOR_INFO}(Default: {default_path}){COLOR_RESET}")
            print(f"{COLOR_PROMPT}Enter path (or 'q' to cancel, Enter for default):{COLOR_RESET}")
        else:
            print(f"{COLOR_PROMPT}{prompt_message}{COLOR_RESET}")
        if READLINE_AVAILABLE:
            readline.set_completer_delims(' \t\n;')
            readline.set_completer(path_completer)
            readline.parse_and_bind('tab: complete')
        elif not no_header:
            print(f"{COLOR_INFO}Note: Tab completion is not available in this environment.{COLOR_RESET}")
        try:
            while True:
                chosen_path: Optional[Path] = None
                try:
                    user_input = input("Path: ").strip()
                    if user_input.lower() == 'q':
                        self.logger.info("User cancelled path input with 'q'.")
                        print(f"{COLOR_INFO}Input cancelled by user.{COLOR_RESET}")
                        return None
                    if not user_input: # User pressed Enter (empty input)
                        if default_path is not None: # Explicitly check if a default_path object was provided
                            self.logger.debug(f"User pressed Enter, using default_path: {default_path}")
                            chosen_path = default_path.expanduser().resolve()
                        else:
                            self.logger.warning("User pressed Enter, but no default_path was available.")
                            print(f"{COLOR_ERROR}No path entered and no default path was available.{COLOR_RESET}")
                            if not self._ask_try_again(): return None
                            continue
                    else:
                        self.logger.debug(f"User entered path: {user_input}")
                        chosen_path = Path(os.path.expanduser(user_input)).resolve()
                    if chosen_path.exists():
                        if chosen_path.is_dir():
                            self.logger.info(f"Selected directory (exists): {chosen_path}")
                            return chosen_path
                        else:
                            print(f"{COLOR_ERROR}Path exists but is not a directory: {chosen_path}{COLOR_RESET}")
                            if not self._ask_try_again(): return None
                            continue
                    elif create_if_missing:
                        self.logger.info(f"Directory does not exist: {chosen_path}. Prompting to create.")
                        print(f"{COLOR_WARNING}Directory does not exist: {chosen_path}{COLOR_RESET}")
                        print("\n" + "-" * 28)
                        print(f"{COLOR_PROMPT}Create this directory?{COLOR_RESET}")
                        create_choice = input(f"{COLOR_PROMPT}(Y/n/q): {COLOR_RESET}").strip().lower()
                        print("-" * 28)
                        if create_choice == '' or create_choice.startswith('y'):
                            self.logger.info(f"User chose to create directory: {chosen_path}")
                            return (chosen_path, True)
                        elif create_choice.startswith('n') or create_choice.startswith('q'):
                            self.logger.info(f"User chose not to create directory: {chosen_path}")
                            print("Directory creation skipped by user.")
                            if create_choice.startswith('q') or not self._ask_try_again(): return None
                            continue
                        else:
                            print(f"{COLOR_ERROR}Invalid input. Please enter 'y', 'n', or 'q'.{COLOR_RESET}")
                            if not self._ask_try_again(): return None
                            continue
                except EOFError:
                    print("\nInput cancelled (EOF).")
                    return None
                except KeyboardInterrupt:
                    print("\nInput cancelled (Ctrl+C).")
                    return None
        finally:
            if READLINE_AVAILABLE:
                readline.set_completer(None)

    def get_existing_file_path(self, prompt_message: str, extension_filter: str = ".wabbajack", no_header: bool = False) -> Optional[Path]:
        if not no_header:
            print("\n" + "-" * 28)
            print(f"{COLOR_PROMPT}{prompt_message}{COLOR_RESET}")
            print(f"Looking for files with extension: {extension_filter}")
            print("You can also select a directory containing the file.")
            print("")
        print(f"{COLOR_PROMPT}Enter file path (or 'q' to cancel):{COLOR_RESET}")
        if READLINE_AVAILABLE:
            readline.set_completer_delims(' \t\n;')
            readline.set_completer(path_completer)
            readline.parse_and_bind('tab: complete')
        else:
            print(f"{COLOR_INFO}Note: Tab completion is not available in this environment.{COLOR_RESET}")
            print(f"{COLOR_INFO}You'll need to manually type the full path to the file.{COLOR_RESET}")
        try:
            while True:
                raw_path = input("File: ").strip()
                if raw_path.lower() == 'q':
                    print(f"{COLOR_INFO}Input cancelled by user.{COLOR_RESET}")
                    print("")
                    return None
                if not raw_path:
                    print("Input cancelled.")
                    print("")
                    return None
                file_path = Path(os.path.expanduser(raw_path)).resolve()
                if file_path.is_dir():
                    print("")
                    return file_path
                if file_path.is_file() and file_path.name.lower().endswith(extension_filter.lower()):
                    print("")
                    return file_path
                else:
                    print(f"{COLOR_ERROR}Path is not a valid '{extension_filter}' file or a directory: {file_path}{COLOR_RESET}")
                    print(f"{COLOR_INFO}Please check the path and try again, or press Ctrl+C or 'q' to cancel.{COLOR_RESET}")
                    if not self._ask_try_again():
                        print("")
                        return None
        except KeyboardInterrupt:
            print("\nInput cancelled.")
            print("")
            return None
        finally:
            if READLINE_AVAILABLE and readline:
                readline.set_completer(None)