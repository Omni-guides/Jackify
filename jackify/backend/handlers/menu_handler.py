#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Menu Handler Module
Handles CLI menu system for Jackify
"""

import os
import sys
import logging
import time
import subprocess # Add subprocess import
# from datetime import datetime # Not used currently
import argparse
import re
from typing import List, Dict, Optional
from pathlib import Path
import glob  # Add for the simpler tab completion

# Import colors from the new central location
from .ui_colors import (
    COLOR_PROMPT, COLOR_SELECTION, COLOR_RESET, COLOR_INFO, COLOR_ERROR,
    COLOR_SUCCESS, COLOR_WARNING, COLOR_DISABLED, COLOR_ACTION, COLOR_INPUT
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
from .mo2_handler import MO2Handler
from jackify.shared.ui_utils import print_section_header
from .completers import path_completer

# Define exports for this module
__all__ = [
    'MenuHandler', 
    'ModlistMenuHandler',
    'simple_path_completer'  # Export the function without underscore
]

# Initialize logger
logger = logging.getLogger(__name__)

# --- Input Handling with Readline Tab Completion ---
# Simple function for basic input
def basic_input_prompt(message, **kwargs):
    return input(message)

# --- Readline for tab completion ---
READLINE_AVAILABLE = False
READLINE_HAS_PROMPT = False
READLINE_HAS_DISPLAY_HOOK = False
try:
    import readline
    READLINE_AVAILABLE = True
    logging.debug("Readline imported for tab completion")
    
    # Check for the specific features we want to use
    if hasattr(readline, 'set_prompt'):
        READLINE_HAS_PROMPT = True
        logging.debug("Readline has set_prompt capability")
    else:
        logging.debug("Readline does not have set_prompt capability, will use fallback")
    
    # Test readline tab completion functionality
    try:
        # Try to parse tab configuration to confirm readline is properly configured
        readline.parse_and_bind('tab: complete')
        logging.debug("Readline tab completion successfully configured")
    except Exception as e:
        logging.warning(f"Error configuring readline tab completion: {e}. Tab completion may be limited.")
        
    # Set better readline behavior for displaying completions if available
    if hasattr(readline, 'set_completion_display_matches_hook'):
        READLINE_HAS_DISPLAY_HOOK = True
        logging.debug("Readline has completion display hook capability")
        
        def custom_display_completions(substitution, matches, longest_match_length):
            """Custom function to display completions with better formatting"""
            # Print a newline to avoid overwriting the prompt
            print()
            # Get terminal width
            try:
                import shutil
                term_width = shutil.get_terminal_size().columns
            except (ImportError, AttributeError):
                term_width = 80  # Default fallback
                
            # Calculate how many completions to display per line
            items_per_line = max(1, term_width // (longest_match_length + 2))
            
            # Print completions in columns
            for i, match in enumerate(matches):
                print(f"{match:<{longest_match_length + 2}}", end='' if (i + 1) % items_per_line else '\n')
            
            if len(matches) % items_per_line != 0:
                print()  # Ensure we end with a newline
                
            # Re-display the prompt with the current input - use the safe approach
            current_input = readline.get_line_buffer()
            # Use the visual prompt string which may not be exactly what readline knows as the prompt
            print(f"{COLOR_PROMPT}> {COLOR_RESET}{current_input}", end='', flush=True)
        
        try:    
            # Set the custom display function
            readline.set_completion_display_matches_hook(custom_display_completions)
            logging.debug("Custom completion display hook successfully set")
        except Exception as e:
            logging.warning(f"Error setting completion display hook: {e}. Using default display behavior.")
            READLINE_HAS_DISPLAY_HOOK = False
    else:
        logging.debug("Readline doesn't have completion display hook capability, using default")
except ImportError:
    READLINE_AVAILABLE = False
    READLINE_HAS_PROMPT = False
    READLINE_HAS_DISPLAY_HOOK = False
    logging.warning("readline not available. Tab completion for paths will be disabled.")
except Exception as e:
    READLINE_AVAILABLE = False
    READLINE_HAS_PROMPT = False
    READLINE_HAS_DISPLAY_HOOK = False
    logging.warning(f"Error initializing readline: {e}. Tab completion for paths will be disabled.")

# --- DEBUG PRINT ---
# --- END DEBUG PRINT ---

class ModlistMenuHandler:
    """
    Handles modlist-specific menu operations
    """
    
    def __init__(self, config_handler, test_mode=False):
        """Initialize the ModlistMenuHandler with configuration"""
        
        self.config_handler = config_handler
        self.test_mode = test_mode
        self.exit_flag = False
        self.logger = logging.getLogger(__name__)
        
        # Initialize handlers
        try:
            # Initialize filesystem handler first, others may depend on it
            self.filesystem_handler = FileSystemHandler()
            
            # Initialize basic handlers
            self.path_handler = PathHandler()
            self.vdf_handler = VDFHandler()
            
            # Determine Steam Deck status (already done by ConfigHandler, use it)
            self.steamdeck = config_handler.settings.get('steamdeck', False)
            
            # Create the resolution handler
            self.resolution_handler = ResolutionHandler()
            
            # Initialize menu handler for consistent UI
            self.menu_handler = MenuHandler()
            
            # Initialize modlist handler
            self.modlist_handler = ModlistHandler(
                self.config_handler.settings,
                steamdeck=self.steamdeck,
                verbose=False,
                filesystem_handler=self.filesystem_handler
            )
            
            self.shortcut_handler = self.modlist_handler.shortcut_handler

            # Initialize the wabbajack installation handler
            self.install_wabbajack_handler = None
            
        except Exception as e:
            self.logger.error(f"Error initializing ModlistMenuHandler: {e}")
            # Initialize with defaults/empty to prevent errors
            self.filesystem_handler = FileSystemHandler()
            self.steamdeck = False
            self.modlist_handler = None

    def show_modlist_menu(self):
        while True:
            os.system('cls' if os.name == 'nt' else 'clear')
            # Banner display handled by frontend
            print_section_header('Modlist Configuration')
            print(f"{COLOR_SELECTION}1.{COLOR_RESET} Configure a New modlist not yet in Steam")
            print(f"{COLOR_SELECTION}2.{COLOR_RESET} Configure a modlist already in Steam")
            print(f"{COLOR_SELECTION}0.{COLOR_RESET} Return to Main Menu")
            choice = input(f"\n{COLOR_PROMPT}Enter your selection (0-2): {COLOR_RESET}")
            if choice == "1":
                if not self._configure_new_modlist():
                    return False
            elif choice == "2":
                if not self._configure_existing_modlist():
                    return False
            elif choice == "0":
                logger.info("Returning to main menu from Modlist Configuration menu.")
                return False
            else:
                logger.warning(f"Invalid menu selection: {choice}")
                print("\nInvalid selection. Please try again.")
                input("\nPress Enter to continue...")

    def _display_manual_proton_steps(self, modlist_name):
        """Displays the detailed manual steps required for Proton setup."""
        # Keep these as print for clear user instructions
        print(f"\n{COLOR_PROMPT}--- Manual Proton Setup Required ---{COLOR_RESET}") 
        print("Please complete the following steps in Steam:")
        print(f"  1. Locate the '{COLOR_INFO}{modlist_name}{COLOR_RESET}' entry in your Steam Library")
        print("  2. Right-click and select 'Properties'")
        print("  3. Switch to the 'Compatibility' tab")
        print("  4. Check the box labeled 'Force the use of a specific Steam Play compatibility tool'")
        print("  5. Select 'Proton - Experimental' from the dropdown menu")
        print("  6. Close the Properties window")
        print(f"  7. Launch '{COLOR_INFO}{modlist_name}{COLOR_RESET}' from your Steam Library")
        print("  8. If Mod Organizer opens or produces any error message, that's normal")
        print("  9. No matter what,CLOSE Mod Organizer completely and return here")
        print(f"{COLOR_PROMPT}------------------------------------{COLOR_RESET}")

    def _get_mo2_path(self) -> Optional[str]:
        """
        Get the path to ModOrganizer.exe from user input.
        Returns the validated path or None if cancelled/invalid.
        """
        self.logger.info("Prompting for ModOrganizer.exe path...")
        print("\n" + "-" * 28) # Separator
        print(f"{COLOR_PROMPT}Please provide the path to ModOrganizer.exe for your modlist.{COLOR_RESET}")
        print(f"{COLOR_INFO}This is typically found in the modlist's installation directory.")
        print(f"{COLOR_INFO}Example: ~/Games/MyModlist/ModOrganizer.exe")
        print(f"{COLOR_INFO}You can also provide the path to the directory containing ModOrganizer.exe.")

        # Use the menu_handler's get_existing_file_path for consistency if self.menu_handler is available
        # Note: self.menu_handler here is an instance of MenuHandler, not ModlistMenuHandler
        if hasattr(self, 'menu_handler') and self.menu_handler is not None:
            # get_existing_file_path will use its own standard prompting style internally
            # We pass no_header=False so it shows its full prompt.
            # The prompt_message here becomes the main instruction for get_existing_file_path.
            path_result = self.menu_handler.get_existing_file_path(
                prompt_message=f"Path to ModOrganizer.exe or its directory",
                extension_filter=".exe",
                no_header=False # Let get_existing_file_path handle its full prompt including separator
            )
            if path_result is None: # User cancelled
                self.logger.info("User cancelled ModOrganizer.exe path input via get_existing_file_path.")
                return None
            
            path_str = str(path_result)
            if os.path.isdir(path_str):
                potential_mo2_path = os.path.join(path_str, "ModOrganizer.exe")
                if os.path.isfile(potential_mo2_path):
                    self.logger.info(f"Found ModOrganizer.exe in directory: {potential_mo2_path}")
                    return potential_mo2_path
                else:
                    print(f"\n{COLOR_ERROR}Error: ModOrganizer.exe not found in directory: {path_str}{COLOR_RESET}")
                    # Allow to try again - this might need a loop or rely on get_existing_file_path loop
                    return self._get_mo2_path() # Recursive call to try again, simple loop better
            elif os.path.isfile(path_str) and os.path.basename(path_str).lower() == "modorganizer.exe":
                self.logger.info(f"ModOrganizer.exe path validated: {path_str}")
                return path_str
            else:
                print(f"\n{COLOR_ERROR}Error: Path is not ModOrganizer.exe or a directory containing it.{COLOR_RESET}")
                return self._get_mo2_path() # Recursive call

        # Fallback to basic input if self.menu_handler is not available (should ideally not happen)
        self.logger.warning("_get_mo2_path: self.menu_handler not available, using basic input as fallback.")
        while True:
            try:
                # Basic input prompt if menu_handler isn't used
                mo2_path_input = input(f"{COLOR_PROMPT}Enter path to ModOrganizer.exe (or 'q' to cancel): {COLOR_RESET}").strip()
                if mo2_path_input.lower() == 'q':
                    self.logger.info("User cancelled ModOrganizer.exe path input (fallback).")
                    return None
                
                expanded_path = os.path.expanduser(mo2_path_input)
                normalized_path = os.path.normpath(expanded_path)

                if os.path.isdir(normalized_path):
                    potential_mo2_path = os.path.join(normalized_path, "ModOrganizer.exe")
                    if os.path.isfile(potential_mo2_path):
                        self.logger.info(f"Found ModOrganizer.exe in directory (fallback): {potential_mo2_path}")
                        return potential_mo2_path
                    else:
                        print(f"{COLOR_ERROR}Error: ModOrganizer.exe not found in directory: {normalized_path}{COLOR_RESET}")
                        continue
                
                if not normalized_path.lower().endswith('modorganizer.exe'):
                    print(f"{COLOR_ERROR}Error: Path must be ModOrganizer.exe or a directory containing it.{COLOR_RESET}")
                    continue
                if not os.path.isfile(normalized_path):
                    print(f"{COLOR_ERROR}Error: File does not exist: {normalized_path}{COLOR_RESET}")
                    continue
                
                self.logger.info(f"ModOrganizer.exe path validated (fallback): {normalized_path}")
                return normalized_path
            except KeyboardInterrupt:
                print("\nOperation cancelled.")
                self.logger.info("User cancelled ModOrganizer.exe path input via Ctrl+C (fallback).")
                return None
            except Exception as e:
                self.logger.error(f"Error processing ModOrganizer.exe path (fallback): {e}")
                print(f"{COLOR_ERROR}An error occurred: {e}{COLOR_RESET}")
                return None

    def _get_modlist_name(self) -> Optional[str]:
        """
        Get the modlist name from user input.
        Returns the validated name or None if cancelled.
        """
        self.logger.info("Prompting for modlist name...")
        
        print("\n" + "-" * 28) # Separator
        print(f"{COLOR_PROMPT}Please provide a name for your modlist.{COLOR_RESET}")
        print(f"{COLOR_INFO}(This will be the name used for the Steam shortcut.){COLOR_RESET}")
        
        while True:
            try:
                modlist_name = input(f"{COLOR_PROMPT}Modlist Name (or 'q' to cancel): {COLOR_RESET}").strip()
                
                if modlist_name.lower() == 'q':
                    self.logger.info("User cancelled modlist name input.")
                    return None
                
                if not modlist_name:
                    print(f"{COLOR_ERROR}Error: Name cannot be empty.{COLOR_RESET}")
                    continue
                    
                if len(modlist_name) > 100: 
                    print(f"{COLOR_ERROR}Error: Name is too long (max 100 characters).{COLOR_RESET}")
                    continue
                    
                invalid_chars = '< > : " / \\ | ? *' # String of invalid chars for message
                if any(char in modlist_name for char in invalid_chars.replace(' ','')):
                    print(f"{COLOR_ERROR}Error: Name contains invalid characters (e.g., {invalid_chars}).{COLOR_RESET}")
                    continue
                
                self.logger.info(f"Modlist name validated: {modlist_name}")
                return modlist_name
                
            except KeyboardInterrupt:
                print("\nOperation cancelled.")
                self.logger.info("User cancelled modlist name input via Ctrl+C.")
                return None
            except Exception as e:
                self.logger.error(f"Error processing modlist name: {e}")
                print(f"{COLOR_ERROR}An error occurred: {e}{COLOR_RESET}")
                return None

    def _configure_new_modlist(self, default_modlist_dir=None, default_modlist_name=None):
        """Handle configuration of a new modlist. Returns True to continue menu, False to exit."""
        # --- Get ModOrganizer.exe Path ---
        if default_modlist_dir:
            # Try to infer ModOrganizer.exe path
            mo2_path = os.path.join(default_modlist_dir, "ModOrganizer.exe")
            if not os.path.isfile(mo2_path):
                print(f"{COLOR_ERROR}Could not find ModOrganizer.exe in {default_modlist_dir}{COLOR_RESET}")
                mo2_path = self._get_mo2_path()
        else:
            mo2_path = self._get_mo2_path()
        if not mo2_path:
            return True
        # --- Get Modlist Name ---
        if default_modlist_name:
            modlist_name = default_modlist_name
        else:
            modlist_name = self._get_modlist_name()
        if not modlist_name:
            return True
        # Add a blank line for padding
        print("")
        try:
            # --- Ensure SteamIcons directory is normalized before icon selection ---
            mo2_dir = os.path.dirname(mo2_path)
            # --- Auto-create nxmhandler.ini to suppress NXM Handling popup (MOVED UP) ---
            self.shortcut_handler.write_nxmhandler_ini(mo2_dir, mo2_path)
            steam_icons_path = os.path.join(mo2_dir, "Steam Icons")
            steamicons_path = os.path.join(mo2_dir, "SteamIcons")
            if os.path.isdir(steam_icons_path) and not os.path.isdir(steamicons_path):
                try:
                    os.rename(steam_icons_path, steamicons_path)
                    self.logger.info(f"Renamed 'Steam Icons' to 'SteamIcons' in {mo2_dir}")
                except Exception as e:
                    self.logger.warning(f"Failed to rename 'Steam Icons' to 'SteamIcons': {e}")
            self.logger.debug(f"[DEBUG] After normalization, SteamIcons exists: {os.path.isdir(steamicons_path)}")
            # --- Create shortcut with working NativeSteamService ---
            try:
                from ..services.native_steam_service import NativeSteamService
                steam_service = NativeSteamService()
                
                success, app_id = steam_service.create_shortcut_with_proton(
                    app_name=modlist_name,
                    exe_path=mo2_path,
                    start_dir=os.path.dirname(mo2_path),
                    launch_options="%command%",
                    tags=["Jackify"],
                    proton_version="proton_experimental"
                )
                if not success or not app_id:
                    self.logger.error("Failed to create Steam shortcut.")
                    print(f"\n{COLOR_ERROR}Failed to create Steam shortcut. Check the logs for details.{COLOR_RESET}")
                    return True
                mo2_dir = os.path.dirname(mo2_path)
                if os.environ.get('JACKIFY_GUI_MODE'):
                    print('[PROMPT:RESTART_STEAM]')
                    input()  # Wait for GUI to send confirmation
                    print('[PROMPT:MANUAL_STEPS]')
                    input()  # Wait for GUI to send confirmation
                    # Continue as before
                else:
                    print("\n───────────────────────────────────────────────────────────────────")
                    print(f"{COLOR_INFO}Important:{COLOR_RESET} Steam needs to restart to detect the new shortcut.")
                    print("This process involves several manual steps after the restart.")
                    restart_choice = input("\nRestart Steam automatically now? (Y/n): ").strip().lower()
                    if restart_choice == 'n':
                        self.logger.info("User opted out of automatic Steam restart.")
                        print("\nPlease restart Steam manually to see your new shortcut:")
                        print("1. Exit Steam completely (Steam -> Exit or right-click tray icon -> Exit)")
                        print("2. Wait a few seconds")
                        print("3. Start Steam again")
                        print("\nAfter restarting, you MUST perform the manual Proton setup steps:")
                        self._display_manual_proton_steps(modlist_name)
                        print(f"\n{COLOR_ERROR}You will need to re-run this configuration option after completing these steps.{COLOR_RESET}")
                        print("───────────────────────────────────────────────────────────────────")
                        return True
                    self.logger.info("Attempting secure Steam restart...")
                    print()
                    status_line = ""
                    def update_status(msg):
                        nonlocal status_line
                        if status_line:
                            print("\r" + " " * len(status_line), end="\r")
                        status_line = f"\r{COLOR_INFO}{msg}{COLOR_RESET}"
                        print(status_line, end="", flush=True)
                    # Actually restart Steam and wait for completion
                    if self.shortcut_handler.secure_steam_restart(status_callback=update_status):
                        print()
                        self.logger.info("Secure Steam restart successful.")
                        self._display_manual_proton_steps(modlist_name)
                        print()
                        input(f"{COLOR_PROMPT}Once you have completed ALL the steps above, press Enter to continue...{COLOR_RESET}")
                        self.logger.info("User confirmed completion of manual steps.")
                        # Re-detect the shortcut and get the new, positive AppID
                        new_app_id = self.shortcut_handler.get_appid_for_shortcut(modlist_name, mo2_path)
                        self.logger.info(f"Pre-launch AppID: {app_id}, Post-launch AppID: {new_app_id}")
                        if not new_app_id or not new_app_id.isdigit() or int(new_app_id) < 0:
                            print(f"{COLOR_ERROR}Could not find a valid AppID for '{modlist_name}' after launch. Please ensure you launched the shortcut from Steam at least once, then try again.{COLOR_RESET}")
                            return True
                        context = {
                            "name": modlist_name,
                            "appid": new_app_id,
                            "path": mo2_dir,
                            "manual_steps_completed": True,
                            "resolution": None
                        }
                        self.logger.debug(f"[DEBUG] New Modlist Context (post-launch): {context}")
                        return self.run_modlist_configuration_phase(context)
            except Exception as e:
                self.logger.error(f"Error creating Steam shortcut: {e}", exc_info=True)
                print(f"\n{COLOR_ERROR}Failed to create Steam shortcut: {e}{COLOR_RESET}")
                return True
        except Exception as e:
            self.logger.error(f"Error in _configure_new_modlist: {e}", exc_info=True)
            print(f"\n{COLOR_ERROR}Unexpected error in new modlist configuration: {e}{COLOR_RESET}")
            return True

    def _configure_existing_modlist(self):
        """Handle configuration of an existing modlist. Returns True to continue menu, False to exit."""
        logger.info("Detecting installed modlists...")
        try:
            if not self.modlist_handler:
                print("Internal Error: Modlist handler not available.")
                input("\nPress Enter to continue...")
                return True
            configurable_modlists = self.modlist_handler.discover_executable_shortcuts("ModOrganizer.exe")
            if not configurable_modlists:
                logger.warning("No configurable ModOrganizer modlists found.")
                print(f"{COLOR_ERROR}\nCould not find any recognized ModOrganizer modlists.{COLOR_RESET}")
                print("Ensure the shortcut exists in Steam, points to ModOrganizer.exe, and has been run once.")
                input(f"\n{COLOR_PROMPT}Press Enter to return to menu...{COLOR_RESET}")
                return True
            selected_modlist_dict = self.select_from_list(configurable_modlists, f"{COLOR_PROMPT}Select Modlist to Configure:{COLOR_RESET}")
            if not selected_modlist_dict:
                logger.info("Modlist selection cancelled by user.")
                return True
            logger.info(f"Setting context for selected modlist: {selected_modlist_dict.get('name')}")
            context = {
                "name": selected_modlist_dict.get("name"),
                "appid": selected_modlist_dict.get("appid"),
                "path": selected_modlist_dict.get("path"),
                "resolution": selected_modlist_dict.get("resolution") if selected_modlist_dict.get("resolution") else None
            }
            self.logger.debug(f"[DEBUG] Existing Modlist Context: {context}")
            return self.run_modlist_configuration_phase(context)
        except KeyboardInterrupt:
            print("\nConfiguration cancelled by user.")
            return True
        except Exception as e:
            logger.exception(f"Error configuring existing modlist: {e}", exc_info=True)
            print(f"{COLOR_ERROR}\nAn unexpected error occurred: {str(e)}{COLOR_RESET}")
            input(f"\n{COLOR_PROMPT}Press Enter to continue...{COLOR_RESET}")
            return True

    def select_from_list(self, items: List[Dict], prompt="Select an option") -> Optional[Dict]:
        """
        Display a list of items (dictionaries) and let the user select one.
        
        Args:
            items: A list of dictionaries, each expected to have at least 'name' and 'appid'.
            prompt: The message to display before the list.
            
        Returns:
            The selected dictionary item or None if cancelled.
        """
        if not items:
            print(f"{COLOR_WARNING}No items available to select from.{COLOR_RESET}")
            return None
        
        print("\n" + "-" * 28) # Separator
        print(f"{COLOR_PROMPT}{prompt}{COLOR_RESET}") # Main prompt message (e.g., "Select Modlist to Configure:")
        
        for i, item_dict in enumerate(items, 1):
            display_name = item_dict.get('name', 'Unknown Item')
            # Optionally display other relevant info if available, e.g., AppID or path
            # For now, keeping it simple with just the name for selection clarity.
            print(f"  {COLOR_SELECTION}{i}.{COLOR_RESET} {display_name}")
        print(f"  {COLOR_SELECTION}0.{COLOR_RESET} Cancel selection") # Added cancel option
        
        while True:
            try:
                choice_input = input(f"{COLOR_PROMPT}Enter your choice (0-{len(items)}): {COLOR_RESET}").strip()
                if choice_input.lower() == 'q' or choice_input == '0': # Allow 'q' or '0' for cancel
                    self.logger.info("User cancelled selection from list.")
                    print(f"{COLOR_INFO}Selection cancelled.{COLOR_RESET}")
                    return None
                if choice_input.isdigit():
                    choice_int = int(choice_input)
                    if 1 <= choice_int <= len(items):
                        return items[choice_int - 1]
                
                print(f"{COLOR_ERROR}Invalid choice. Please enter a number between 0 and {len(items)}.{COLOR_RESET}")
            except ValueError:
                print(f"{COLOR_ERROR}Invalid input. Please enter a number.{COLOR_RESET}")
            except KeyboardInterrupt:
                print("\nSelection cancelled (Ctrl+C).")
                self.logger.info("User cancelled selection from list via Ctrl+C.")
                return None
                
    def run_modlist_configuration_phase(self, context: dict) -> bool:
        """
        Shared configuration phase for both new and existing modlists.
        Expects context dict with keys: name, appid, path (at minimum).
        """
        self.logger.debug(f"[DEBUG] Entering run_modlist_configuration_phase with context: {context}")
        # Robust AppID lookup for GUI/CLI: if appid missing but mo2_exe_path present, look it up
        if 'appid' not in context or not context.get('appid'):
            if 'mo2_exe_path' in context and context['mo2_exe_path']:
                appid = self.shortcut_handler.get_appid_for_shortcut(context['name'], context['mo2_exe_path'])
                if appid:
                    context['appid'] = appid
                else:
                    self.logger.warning(f"[DEBUG] Could not find AppID for {context['name']} with exe {context['mo2_exe_path']}")
        set_modlist_result = self.modlist_handler.set_modlist(context)
        self.logger.debug(f"[DEBUG] set_modlist returned: {set_modlist_result}")
        if not set_modlist_result:
            print(f"{COLOR_ERROR}\nError setting up context for configuration.{COLOR_RESET}")
            self.logger.error(f"set_modlist failed for {context.get('name')}")
            input(f"\n{COLOR_PROMPT}Press Enter to continue...{COLOR_RESET}")
            return False

        # --- Resolution selection logic for GUI mode ---
        import os
        gui_mode = os.environ.get('JACKIFY_GUI_MODE') == '1'
        selected_resolution = context.get('resolution', None)
        if gui_mode:
            # If resolution is provided, set it and do not prompt
            if selected_resolution:
                self.modlist_handler.selected_resolution = selected_resolution
                self.logger.info(f"[GUI MODE] Resolution set from GUI: {selected_resolution}")
            else:
                # If on Steam Deck, set to 1280x800; else leave unchanged
                if self.steamdeck:
                    self.modlist_handler.selected_resolution = "1280x800"
                    self.logger.info("[GUI MODE] Steam Deck detected, setting resolution to 1280x800.")
                else:
                    self.logger.info("[GUI MODE] No resolution set, leaving unchanged.")
        else:
            # CLI mode: prompt as before
            print()  # Add padding before resolution prompt
            selected_res = self.resolution_handler.select_resolution(steamdeck=self.steamdeck)
            if selected_res:
                self.modlist_handler.selected_resolution = selected_res
                self.logger.info(f"Resolution preference set to: {selected_res}")
            elif self.steamdeck:
                self.modlist_handler.selected_resolution = "1280x800"
                self.logger.info(f"Using default Steam Deck resolution: {self.modlist_handler.selected_resolution}")
            else:
                self.logger.info("User cancelled resolution selection or not applicable.")

        skip_confirmation = context.get('skip_confirmation', False)
        if gui_mode:
            skip_confirmation = True
        if not self.modlist_handler.display_modlist_summary(skip_confirmation=skip_confirmation):
            self.logger.info("User chose not to proceed with configuration after summary.")
            return True

        self.logger.info(f"Starting configuration steps for {context.get('name')}")
        print()  # Add padding before status line
        status_line = ""
        import os
        gui_mode = os.environ.get('JACKIFY_GUI_MODE') == '1'
        def update_status(msg):
            nonlocal status_line
            if status_line:
                print("\r" + " " * len(status_line), end="\r")
            if gui_mode:
                print(msg, flush=True)
            else:
                status_line = f"\r{COLOR_INFO}{msg}{COLOR_RESET}"
                print(status_line, end="", flush=True)
        manual_steps_completed = context.get("manual_steps_completed", False)
        if not self.modlist_handler._execute_configuration_steps(status_callback=update_status, manual_steps_completed=manual_steps_completed):
            if status_line:
                print()
            self.logger.error(f"Core configuration steps failed for {context.get('name')}")
            print(f"{COLOR_ERROR}\nModlist configuration failed. Check logs for details.{COLOR_RESET}")
            # Only wait for input in CLI mode, not GUI mode
            if not gui_mode:
                input(f"\n{COLOR_PROMPT}Press Enter to continue...{COLOR_RESET}")
            return False
        if status_line:
            print()
        
        print("")
        print("")
        print("")  # Extra blank line before completion
        print("=" * 35)
        print("= Configuration phase complete =")
        print("=" * 35)
        print("")
        print("Modlist Install and Configuration complete!")
        print(f"• You should now be able to Launch '{context.get('name')}' through Steam")
        print("• Congratulations and enjoy the game!")
        print("Detailed log available at: ~/Jackify/logs/Configure_New_Modlist_workflow.log")
        # Only wait for input in CLI mode, not GUI mode
        if not gui_mode:
            input(f"{COLOR_PROMPT}Press Enter to return to the menu...{COLOR_RESET}")
        return True

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
        self.mo2_handler = MO2Handler(self)
    
    def display_banner(self):
        """Display the application banner - DEPRECATED: Banner display should be handled by frontend"""
        os.system('cls' if os.name == 'nt' else 'clear')
        # Banner display handled by frontend
    




    def _show_recovery_menu(self, cli_instance):
        """Show the recovery tools menu."""
        while True:
            self._clear_screen()
            # Banner display handled by frontend
            print_section_header('Recovery Tools')
            print(f"{COLOR_INFO}This allows restoring original Steam configuration files from backups created by Jackify.{COLOR_RESET}")
            print(f"{COLOR_SELECTION}1.{COLOR_RESET} Restore all backups")
            print(f"{COLOR_SELECTION}2.{COLOR_RESET} Restore config.vdf only")
            print(f"{COLOR_SELECTION}3.{COLOR_RESET} Restore libraryfolders.vdf only")
            print(f"{COLOR_SELECTION}4.{COLOR_RESET} Restore shortcuts.vdf only")
            print(f"{COLOR_SELECTION}0.{COLOR_RESET} Return to Main Menu")
            
            choice = input(f"\n{COLOR_PROMPT}Enter your selection (0-4): {COLOR_RESET}").strip()

            if choice == "1":
                logger.info("Recovery selected: Restore all Steam config files")
                print("\nAttempting to restore all supported Steam config files...")
                # Logic to find and restore backups for all three files
                paths_to_check = {
                    "libraryfolders": cli_instance.path_handler.find_steam_library_vdf_path(), # Need method to find vdf itself
                    "config": cli_instance.path_handler.find_steam_config_vdf(),
                    "shortcuts": cli_instance.shortcut_handler._find_shortcuts_vdf() # Assumes this returns the path
                }
                restored_count = 0
                for file_type, file_path in paths_to_check.items():
                    if file_path:
                        print(f"Restoring {file_type} ({file_path})...")
                        # Find latest backup (needs helper function)
                        latest_backup = cli_instance.filesystem_handler.find_latest_backup(Path(file_path))
                        if latest_backup:
                            if cli_instance.filesystem_handler.restore_backup(latest_backup, Path(file_path)):
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
            elif choice == "2":
                logger.info("Recovery selected: Restore config.vdf only")
                print("\nAttempting to restore config.vdf...")
                # Logic for config.vdf
                file_path = cli_instance.path_handler.find_steam_config_vdf()
                if file_path:
                    latest_backup = cli_instance.filesystem_handler.find_latest_backup(Path(file_path))
                    if latest_backup:
                        if cli_instance.filesystem_handler.restore_backup(latest_backup, Path(file_path)):
                            print(f"Successfully restored config.vdf from {latest_backup}.")
                        else:
                            print(f"{COLOR_ERROR}Failed to restore config.vdf from {latest_backup}.{COLOR_RESET}")
                    else:
                        print("No backup found for config.vdf.")
                else:
                    print("Could not locate config.vdf.")
                input("\nPress Enter to continue...")
            elif choice == "3":
                logger.info("Recovery selected: Restore libraryfolders.vdf only")
                print("\nAttempting to restore libraryfolders.vdf...")
                # Logic for libraryfolders.vdf
                file_path = cli_instance.path_handler.find_steam_library_vdf_path()
                if file_path:
                    latest_backup = cli_instance.filesystem_handler.find_latest_backup(Path(file_path))
                    if latest_backup:
                        if cli_instance.filesystem_handler.restore_backup(latest_backup, Path(file_path)):
                            print(f"Successfully restored libraryfolders.vdf from {latest_backup}.")
                        else:
                            print(f"{COLOR_ERROR}Failed to restore libraryfolders.vdf from {latest_backup}.{COLOR_RESET}")
                    else:
                        print("No backup found for libraryfolders.vdf.")
                else:
                    print("Could not locate libraryfolders.vdf.")
                input("\nPress Enter to continue...")
            elif choice == "4":
                logger.info("Recovery selected: Restore shortcuts.vdf only")
                print("\nAttempting to restore shortcuts.vdf...")
                # Logic for shortcuts.vdf
                file_path = cli_instance.shortcut_handler._find_shortcuts_vdf()
                if file_path:
                    latest_backup = cli_instance.filesystem_handler.find_latest_backup(Path(file_path))
                    if latest_backup:
                        if cli_instance.filesystem_handler.restore_backup(latest_backup, Path(file_path)):
                            print(f"Successfully restored shortcuts.vdf from {latest_backup}.")
                        else:
                            print(f"{COLOR_ERROR}Failed to restore shortcuts.vdf from {latest_backup}.{COLOR_RESET}")
                    else:
                        print("No backup found for shortcuts.vdf.")
                else:
                    print("Could not locate shortcuts.vdf.")
                input("\nPress Enter to continue...")
            elif choice == "0":
                logger.info("Returning to main menu from recovery.")
                break # Exit recovery menu loop
            else:
                logger.warning(f"Invalid recovery menu selection: {choice}")
                print("\nInvalid selection. Please try again.")
                time.sleep(1)

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

    def show_hoolamike_menu(self, cli_instance):
        """Show the Hoolamike Modlist Management menu"""
        if not hasattr(cli_instance, 'hoolamike_handler') or cli_instance.hoolamike_handler is None:
            try:
                from .hoolamike_handler import HoolamikeHandler
                cli_instance.hoolamike_handler = HoolamikeHandler(
                    steamdeck=getattr(cli_instance, 'steamdeck', False),
                    verbose=getattr(cli_instance, 'verbose', False),
                    filesystem_handler=getattr(cli_instance, 'filesystem_handler', None),
                    config_handler=getattr(cli_instance, 'config_handler', None),
                    menu_handler=self
                )
            except Exception as e:
                self.logger.error(f"Failed to initialize Hoolamike features: {e}", exc_info=True)
                print(f"{COLOR_ERROR}Error: Failed to initialize Hoolamike features. Check logs.{COLOR_RESET}")
                input("\nPress Enter to return to the main menu...")
                return # Exit this menu if handler fails

        while True:
            self._clear_screen()
            # Banner display handled by frontend
            # Use print_section_header for consistency if available, otherwise manual with COLOR_SELECTION
            if hasattr(self, 'print_section_header'): # Check if method exists (it's from ui_utils)
                print_section_header("Hoolamike Modlist Management")
            else: # Fallback if not imported or available directly on self
                print(f"{COLOR_SELECTION}Hoolamike Modlist Management{COLOR_RESET}")
                print(f"{COLOR_SELECTION}{'-'*30}{COLOR_RESET}")
            
            print(f"{COLOR_SELECTION}1.{COLOR_RESET} Install or Update Hoolamike App")
            print(f"{COLOR_SELECTION}2.{COLOR_RESET} Install Modlist (Nexus Premium)")
            print(f"{COLOR_SELECTION}3.{COLOR_RESET} Install Modlist (Non-Premium) {COLOR_DISABLED}(Not Implemented){COLOR_RESET}")
            print(f"{COLOR_SELECTION}4.{COLOR_RESET} Install Tale of Two Wastelands (TTW)")
            print(f"{COLOR_SELECTION}5.{COLOR_RESET} Edit Hoolamike Configuration")
            print(f"{COLOR_SELECTION}0.{COLOR_RESET} Return to Main Menu")
            selection = input(f"\n{COLOR_PROMPT}Enter your selection (0-5): {COLOR_RESET}").strip()
            
            if selection.lower() == 'q': # Allow 'q' to re-display menu
                continue
            if selection == "1":
                cli_instance.hoolamike_handler.install_update_hoolamike()
            elif selection == "2":
                cli_instance.hoolamike_handler.install_modlist(premium=True)
            elif selection == "3":
                print(f"{COLOR_INFO}Install Modlist (Non-Premium) is not yet implemented.{COLOR_RESET}")
                input("\nPress Enter to return to the Hoolamike menu...")
            elif selection == "4":
                cli_instance.hoolamike_handler.install_ttw()
            elif selection == "5":
                cli_instance.hoolamike_handler.edit_hoolamike_config()
            elif selection == "0":
                break
            else:
                print("Invalid selection. Please try again.")
                time.sleep(1)



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
                            self.logger.warning(f"Path exists but is not a directory: {chosen_path}")
                            print(f"{COLOR_ERROR}Error: Path exists but is not a directory: {chosen_path}{COLOR_RESET}")
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
                    print(f"{COLOR_ERROR}Error: Path is not a valid '{extension_filter}' file or a directory: {file_path}{COLOR_RESET}")
                    print("Please check the path and try again, or press Ctrl+C or 'q' to cancel.")
                    if not self._ask_try_again():
                        print("")
                        return None
        except KeyboardInterrupt:
            print("\nInput cancelled.")
            print("")
            return None
        finally:
            if READLINE_AVAILABLE:
                readline.set_completer(None)

# Basic input prompt function for use throughout the application
input_prompt = basic_input_prompt

# --- Robust shell-like path completer function ---
def _shell_path_completer(text, state):
    """
    Shell-like pathname completer for readline.
    Expands ~, handles absolute/relative paths, and completes inside directories.
    """
    import os
    import glob
    # Expand ~ and environment variables
    expanded = os.path.expanduser(os.path.expandvars(text))
    # If the expanded path is a directory, list its contents
    if os.path.isdir(expanded):
        pattern = os.path.join(expanded, '*')
    else:
        # Complete the last component
        pattern = expanded + '*'
    matches = glob.glob(pattern)
    # Add trailing slash to directories
    matches = [m + ('/' if os.path.isdir(m) else '') for m in matches]
    # If the user hasn't typed anything, show current dir
    if not text:
        matches = glob.glob('*')
        matches = [m + ('/' if os.path.isdir(m) else '') for m in matches]
    # Return the state-th match or None
    try:
        return matches[state]
    except IndexError:
        return None

# Create a public reference to the robust completer
simple_path_completer = _shell_path_completer 

# --- Simple path completer function ---
def _simple_path_completer(text, state):
    """
    Simple pathname completer for readline.
    Logic:
    - If text is empty (at beginning of line), returns options for current dir
    - If text has content, does prefix matching on path components
    - Tab completion will fill up to next / or complete the filename
    - State is an integer index representing which match to return
    Args:
        text: The text to complete
        state: The state index (0 for first match, 1 for second, etc.)
    Returns:
        The matching completion or None if no more matches
    """
    import glob, os
    matches = glob.glob(text + '*')
    matches = [f + ('/' if os.path.isdir(f) else '') for f in matches]
    try:
        return matches[state]
    except IndexError:
        return None

simple_path_completer = _simple_path_completer 