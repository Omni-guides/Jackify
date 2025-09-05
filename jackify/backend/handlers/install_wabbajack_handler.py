#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Install Wabbajack Handler Module
Handles the installation and updating of Wabbajack
"""

import os
import logging
from pathlib import Path
from typing import Optional, Tuple
import shutil
import subprocess
import pwd
import requests
from tqdm import tqdm
import tempfile
import time
import re

# Attempt to import readline for tab completion
READLINE_AVAILABLE = False
try:
    import readline
    READLINE_AVAILABLE = True
    # Check if running in a non-interactive environment (e.g., some CI)
    if 'libedit' in readline.__doc__:
         # libedit doesn't support set_completion_display_matches_hook
         pass
    # Add other potential checks if needed
except ImportError:
    # readline not available on Windows or potentially minimal environments
    pass
except Exception as e:
    # Catch other potential errors during readline import/setup
    logging.warning(f"Readline import failed: {e}")
    pass

# Import UI Colors first - these should always be available
from .ui_colors import COLOR_PROMPT, COLOR_RESET, COLOR_INFO, COLOR_ERROR

# Import necessary components from other modules
try:
    from .path_handler import PathHandler
    from .protontricks_handler import ProtontricksHandler
    from .shortcut_handler import ShortcutHandler
    from .vdf_handler import VDFHandler
    from .modlist_handler import ModlistHandler
    from .filesystem_handler import FileSystemHandler
    from .menu_handler import MenuHandler, simple_path_completer
    # Standard logging (no file handler) - LoggingHandler import removed
    from .status_utils import show_status, clear_status
    from jackify.shared.ui_utils import print_section_header
except ImportError as e:
    logging.error(f"Import error in InstallWabbajackHandler: {e}")
    logging.error("Could not import FileSystemHandler or simple_path_completer. Ensure structure is correct.")

# Default locations
WABBAJACK_DEFAULT_DIR = os.path.expanduser("~/.config/Jackify/Wabbajack")

# Initialize logger for the module
logger = logging.getLogger(__name__)

DEFAULT_WABBAJACK_PATH = "~/Wabbajack"
DEFAULT_WABBAJACK_NAME = "Wabbajack"

class InstallWabbajackHandler:
    """Handles the workflow for installing Wabbajack via Jackify."""

    def __init__(self, steamdeck: bool, protontricks_handler: ProtontricksHandler, shortcut_handler: ShortcutHandler, path_handler: PathHandler, vdf_handler: VDFHandler, modlist_handler: ModlistHandler, filesystem_handler: FileSystemHandler, menu_handler=None):
        """
        Initializes the handler.

        Args:
            steamdeck (bool): True if running on a Steam Deck, False otherwise.
            protontricks_handler (ProtontricksHandler): An initialized instance.
            shortcut_handler (ShortcutHandler): An initialized instance.
            path_handler (PathHandler): An initialized instance.
            vdf_handler (VDFHandler): An initialized instance.
            modlist_handler (ModlistHandler): An initialized instance.
            filesystem_handler (FileSystemHandler): An initialized instance.
            menu_handler: An optional MenuHandler instance for improved UI interactions.
        """
        # Use standard logging (no file handler)
        self.logger = logging.getLogger(__name__)
        self.logger.propagate = False
        self.steamdeck = steamdeck
        self.protontricks_handler = protontricks_handler # Store the handler
        self.shortcut_handler = shortcut_handler       # Store the handler
        self.path_handler = path_handler             # Store the handler
        self.vdf_handler = vdf_handler               # Store the handler
        self.modlist_handler = modlist_handler         # Store the handler
        self.filesystem_handler = filesystem_handler   # Store the handler
        self.menu_handler = menu_handler             # Store the menu handler
        self.logger.info(f"InstallWabbajackHandler initialized. Steam Deck status: {self.steamdeck}")
        self.install_path: Optional[Path] = None
        self.shortcut_name: Optional[str] = None
        self.initial_appid: Optional[str] = None # To store the AppID from shortcut creation
        self.final_appid: Optional[str] = None   # To store the AppID after verification
        self.compatdata_path: Optional[Path] = None # To store the compatdata path
        # Add other state variables as needed

    def _print_default_status(self, message: str):
        """Prints overwriting status line, ONLY if not in verbose/debug mode."""
        verbose_console = False
        for handler in logging.getLogger().handlers:
            if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler):
                if handler.level <= logging.INFO:
                    verbose_console = True
                break
        
        if not verbose_console:
             # Use \r to return to start, \033[K to clear line, then print message
             # Prepend "Current Task: " to the message
             status_text = f"Current Task: {message}"
             # Use a fixed-width field for consistent display and proper line clearing
             status_width = 80  # Ensure sufficient width to cover previous text
             # Pad with spaces and use \r to stay on the same line
             print(f"\r\033[K{COLOR_INFO}{status_text:<{status_width}}{COLOR_RESET}", end="", flush=True)

    def _clear_default_status(self):
        """Clears the status line, ONLY if not in verbose/debug mode."""
        verbose_console = False 
        for handler in logging.getLogger().handlers:
            if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler):
                if handler.level <= logging.INFO:
                    verbose_console = True
                break
        if not verbose_console:
            print("\r\033[K", end="", flush=True)

    def _download_file(self, url: str, destination_path: Path) -> bool:
        """Downloads a file from a URL to a destination path.
        Handles temporary file and overwrites destination if download succeeds.

        Args:
            url (str): The URL to download from.
            destination_path (Path): The path to save the downloaded file.

        Returns:
            bool: True if download succeeds, False otherwise.
        """
        self.logger.info(f"Downloading {destination_path.name} from {url}")

        # Ensure parent directory exists
        destination_path.parent.mkdir(parents=True, exist_ok=True)

        # --- Download --- 
        temp_path = destination_path.with_suffix(destination_path.suffix + ".part")
        self.logger.debug(f"Downloading to temporary path: {temp_path}")
        
        try:
            with requests.get(url, stream=True, timeout=30, verify=True) as r:
                r.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
                # total_size_in_bytes = int(r.headers.get('content-length', 0))
                block_size = 8192 # 8KB chunks
                
                with open(temp_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=block_size):
                        if chunk: # filter out keep-alive new chunks
                            f.write(chunk)
                
            # --- Post-Download Actions ---
            actual_downloaded_size = temp_path.stat().st_size
            self.logger.debug(f"Download finished. Actual size: {actual_downloaded_size} bytes.")

            # Overwrite final destination with temp file
            # Use shutil.move for better cross-filesystem compatibility if needed
            # temp_path.rename(destination_path) # Simple rename
            shutil.move(str(temp_path), str(destination_path)) 
            self.logger.info(f"Successfully downloaded and moved to {destination_path}")
            return True

        except requests.exceptions.RequestException as e:
            self.logger.error(f"Download failed for {url}: {e}", exc_info=True)
            print(f"\n{COLOR_ERROR}Error downloading {destination_path.name}: {e}{COLOR_RESET}")
            # Clean up partial file if download fails
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError as unlink_err:
                    self.logger.error(f"Failed to remove partial download {temp_path}: {unlink_err}")
            return False
        except Exception as e:
            self.logger.error(f"An unexpected error occurred during download: {e}", exc_info=True)
            print(f"\n{COLOR_ERROR}An unexpected error occurred during download: {e}{COLOR_RESET}")
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError as unlink_err:
                    self.logger.error(f"Failed to remove partial download {temp_path}: {unlink_err}")
            return False

    def _prepare_install_directory(self) -> bool:
        """
        Ensures the target installation directory exists and is accessible.
        Handles directory creation, prompting the user if outside $HOME.

        Returns:
            bool: True if the directory exists and is ready, False otherwise.
        """
        if not self.install_path:
            self.logger.error("Cannot prepare directory: install_path is not set.")
            return False

        self.logger.info(f"Preparing installation directory: {self.install_path}")

        if self.install_path.exists():
            if self.install_path.is_dir():
                self.logger.info(f"Directory already exists: {self.install_path}")
                # Check write permissions
                if not os.access(self.install_path, os.W_OK | os.X_OK):
                     self.logger.error(f"Directory exists but lacks write/execute permissions: {self.install_path}")
                     print(f"\n{COLOR_ERROR}Error: Directory exists but lacks necessary write/execute permissions.{COLOR_RESET}")
                     return False
                return True
            else:
                self.logger.error(f"Path exists but is not a directory: {self.install_path}")
                print(f"\n{COLOR_ERROR}Error: The specified path exists but is a file, not a directory.{COLOR_RESET}")
                return False
        else:
            # Directory does not exist, attempt creation
            self.logger.info("Directory does not exist. Attempting creation...")
            try:
                home_dir = Path.home()
                is_outside_home = not str(self.install_path.resolve()).startswith(str(home_dir.resolve()))

                if is_outside_home:
                    self.logger.warning(f"Install path {self.install_path} is outside home directory {home_dir}.")
                    print(f"\n{COLOR_PROMPT}The chosen path is outside your home directory and may require manual creation.{COLOR_RESET}")
                    while True:
                        response = input(f"{COLOR_PROMPT}Please create the directory \"{self.install_path}\" manually,\nensure you have write permissions, and then press Enter to continue (or 'q' to quit): {COLOR_RESET}").lower()
                        if response == 'q':
                            self.logger.warning("User aborted manual directory creation.")
                            return False
                        # Re-check after user presses Enter
                        if self.install_path.exists():
                            if self.install_path.is_dir():
                                self.logger.info("Directory created manually by user.")
                                if not os.access(self.install_path, os.W_OK | os.X_OK):
                                     self.logger.warning(f"Directory created but may lack write/execute permissions: {self.install_path}")
                                     print(f"\n{COLOR_ERROR}Warning: Directory created, but write/execute permissions might be missing.{COLOR_RESET}")
                                     # Decide whether to proceed or fail here - let's proceed but warn
                                return True
                            else:
                                self.logger.error("User indicated directory created, but path is not a directory.")
                                print(f"\n{COLOR_ERROR}Error: Path exists now, but it is not a directory. Please fix and try again.{COLOR_RESET}")
                        else:
                            print(f"\n{COLOR_ERROR}Directory still not found. Please create it or enter 'q' to quit.{COLOR_RESET}")
                else:
                    # Inside home directory, attempt direct creation
                    self.logger.info("Path is inside home directory. Creating...")
                    os.makedirs(self.install_path)
                    self.logger.info(f"Successfully created directory: {self.install_path}")
                    # Verify permissions after creation
                    if not os.access(self.install_path, os.W_OK | os.X_OK):
                        self.logger.warning(f"Directory created but lacks write/execute permissions: {self.install_path}")
                        print(f"\n{COLOR_ERROR}Warning: Directory created, but lacks write/execute permissions. Subsequent steps might fail.{COLOR_RESET}")
                        # Proceed anyway?
                    return True

            except PermissionError:
                self.logger.error(f"Permission denied when trying to create directory: {self.install_path}", exc_info=True)
                print(f"\n{COLOR_ERROR}Error: Permission denied creating directory.{COLOR_RESET}")
                print(f"{COLOR_INFO}Please check permissions for the parent directory or choose a different location.{COLOR_RESET}")
                return False
            except OSError as e:
                self.logger.error(f"Failed to create directory {self.install_path}: {e}", exc_info=True)
                print(f"\n{COLOR_ERROR}Error creating directory: {e}{COLOR_RESET}")
                return False
            except Exception as e:
                self.logger.error(f"An unexpected error occurred during directory preparation: {e}", exc_info=True)
                print(f"\n{COLOR_ERROR}An unexpected error occurred: {e}{COLOR_RESET}")
                return False

    def _get_wabbajack_install_path(self) -> Optional[Path]:
        """
        Prompts the user for the Wabbajack installation path with tab completion.
        Uses the FileSystemHandler for path validation and completion.
        
        Returns:
            Optional[Path]: The chosen installation path as a Path object, or None if cancelled.
        """
        self.logger.info("Prompting for Wabbajack installation path.")
        # Use default path if set, otherwise prompt with suggestion
        current_path = self.install_path if self.install_path else Path(DEFAULT_WABBAJACK_PATH).expanduser()
        
        # Enable tab completion if readline is available
        if READLINE_AVAILABLE:
            readline.set_completer_delims(' \t\n;')
            readline.parse_and_bind("tab: complete")
            # Use the simple_path_completer from FileSystemHandler for directory completion
            readline.set_completer(simple_path_completer)
            
        while True:
            try:
                prompt_text = f"{COLOR_PROMPT}Enter Wabbajack installation path (default: {current_path}): {COLOR_RESET}"
                user_input = input(prompt_text).strip()
                
                if not user_input:  # User pressed Enter for default
                    chosen_path_str = str(current_path)
                else:
                    chosen_path_str = user_input
                
                # Expand ~ and make absolute
                chosen_path = Path(chosen_path_str).expanduser().resolve()
                
                # Basic validation (is it a plausible path format?)
                if not chosen_path.name: # e.g. if user entered just "/"
                    print(f"{COLOR_ERROR}Invalid path. Please enter a valid directory path.{COLOR_RESET}")
                    continue

                # Check if path exists and is a directory, or can be created
                if chosen_path.exists() and not chosen_path.is_dir():
                    print(f"{COLOR_ERROR}Path exists but is not a directory: {chosen_path}{COLOR_RESET}")
                    continue
                
                # Confirm with user
                confirm_prompt = f"{COLOR_PROMPT}Install Wabbajack to {chosen_path}? (Y/n/c to cancel): {COLOR_RESET}"
                confirmation = input(confirm_prompt).lower()
                
                if confirmation == 'c':
                    self.logger.info("Wabbajack installation path selection cancelled by user.")
                    return None # User cancelled
                elif confirmation != 'n':
                    self.install_path = chosen_path # Store the confirmed path
                    self.logger.info(f"Wabbajack installation path set to: {self.install_path}")
                    return self.install_path
                # If 'n', loop again to ask for path
            except KeyboardInterrupt:
                self.logger.info("Wabbajack installation path selection cancelled by user (Ctrl+C).")
                print("\nPath selection cancelled.")
                return None
            except Exception as e:
                self.logger.error(f"Error during path input: {e}", exc_info=True)
                print(f"{COLOR_ERROR}An unexpected error occurred: {e}{COLOR_RESET}")
                # Decide if we should return None or retry on general exception
                return None 
            finally:
                # Restore default completer if it was changed
                if READLINE_AVAILABLE:
                    readline.set_completer(None)

    def _get_wabbajack_shortcut_name(self) -> Optional[str]:
        """
        Prompts the user for the Wabbajack shortcut name.

        Returns:
            Optional[str]: The name chosen by the user, or None if cancelled.
        """
        self.logger.debug("Getting Wabbajack shortcut name.")
        
        # Return pre-configured shortcut name if already set
        if self.shortcut_name:
            self.logger.info(f"Using pre-configured shortcut name: {self.shortcut_name}")
            return self.shortcut_name
            
        chosen_name = DEFAULT_WABBAJACK_NAME

        # Use menu_handler if available for consistent UI
        if self.menu_handler:
            self.logger.debug("Using menu_handler for shortcut name input")
            print(f"\nWabbajack Shortcut Name:")
            name_input = self.menu_handler.get_input_with_default(
                prompt=f"Enter the desired name for the Wabbajack Steam shortcut (default: {chosen_name})",
                default=chosen_name
            )
            
            if name_input is not None:
                self.logger.info(f"User provided shortcut name: {name_input}")
                return name_input
            else:
                self.logger.info("User cancelled shortcut name input")
                return None

        # Fallback to direct input if no menu_handler
        try:
            print(f"\n{COLOR_PROMPT}Enter the desired name for the Wabbajack Steam shortcut.{COLOR_RESET}")
            name_input = input(f"{COLOR_PROMPT}Name [{chosen_name}]: {COLOR_RESET}").strip()

            if not name_input:
                self.logger.info(f"User did not provide input, using default name: {chosen_name}")
            else:
                chosen_name = name_input
                self.logger.info(f"User provided name: {chosen_name}")

            return chosen_name

        except KeyboardInterrupt:
            print(f"\n{COLOR_ERROR}Input cancelled by user.{COLOR_RESET}")
            self.logger.warning("User cancelled name input.")
            return None
        except Exception as e:
            self.logger.error(f"An unexpected error occurred while getting name input: {e}", exc_info=True)
            return None

    def run_install_workflow(self, context: dict = None) -> bool:
        """
        Main entry point for the Wabbajack installation workflow.
        """
        os.system('cls' if os.name == 'nt' else 'clear')
                    # Banner display handled by frontend
        print_section_header('Wabbajack Installation')
        # Standard logging (no file handler) - LoggingHandler calls removed

        self.logger.info("Starting Wabbajack installation workflow...")
        # Remove legacy divider
        # print(f"\n{COLOR_INFO}--- Wabbajack Installation ---{COLOR_RESET}")
        # 1. Get Installation Path
        if self.menu_handler:
            print("\nWabbajack Installation Location:")
            default_path = Path.home() / 'Wabbajackify'
            install_path_result = self.menu_handler.get_directory_path(
                prompt_message=f"Enter path (Default: {default_path}):",
                default_path=default_path,
                create_if_missing=True,
                no_header=True
            )
            if not install_path_result:
                self.logger.info("User cancelled path input via menu_handler")
                return True # Return to menu to allow user to retry or exit gracefully
            # Handle the result from get_directory_path (could be Path or tuple)
            if isinstance(install_path_result, tuple):
                self.install_path = install_path_result[0]  # Path object
                self.logger.info(f"Install path set to {self.install_path}, user confirmed creation if new.")
            else:
                self.install_path = install_path_result  # Already a Path object
                self.logger.info(f"Install path set to {self.install_path}.")
        else: # Fallback if no menu_handler (should ideally not happen in normal flow)
            default_path = Path.home() / 'Wabbajackify'
            print(f"\n{COLOR_PROMPT}Enter the full path where Wabbajack should be installed.{COLOR_RESET}")
            print(f"Default: {default_path}")
            try:
                user_input = input(f"{COLOR_PROMPT}Enter path (or press Enter for default: {default_path}): {COLOR_RESET}").strip()
                if not user_input:
                    install_path = default_path
                else:
                    install_path = Path(user_input).expanduser().resolve()
                self.install_path = install_path
            except KeyboardInterrupt:
                print("\nOperation cancelled by user.")
                self.logger.info("User cancelled path input.")
                return True

        # 2. Get Shortcut Name
        self.shortcut_name = self._get_wabbajack_shortcut_name()
        if not self.shortcut_name:
            self.logger.warning("Workflow aborted: Failed to get shortcut name.")
            return True # Return to menu

        # 3. Steam Deck status is already known (self.steamdeck)
        self.logger.info(f"Proceeding with Steam Deck status: {self.steamdeck}")

        # 4. Check Prerequisite: Protontricks
        self.logger.info("Checking Protontricks prerequisite...")
        protontricks_ok = self.protontricks_handler.check_and_setup_protontricks()
        if not protontricks_ok:
             self.logger.error("Workflow aborted: Protontricks requirement not met or setup failed.")
             input(f"\n{COLOR_PROMPT}Press Enter to return to the main menu...{COLOR_RESET}")
             return True # Return to menu
        self.logger.info("Protontricks check successful.")

        # --- Show summary (no input required) ---
        self._display_summary()  # Show the summary only, no input here
        # --- Single confirmation prompt before making changes/restarting Steam ---
        print("\n───────────────────────────────────────────────────────────────────")
        print(f"{COLOR_PROMPT}Important:{COLOR_RESET} Steam will now restart so Jackify can create the Wabbajack shortcut.\n\nPlease do not manually start or close Steam until Jackify is finished.")
        print("───────────────────────────────────────────────────────────────────")
        confirm = input(f"{COLOR_PROMPT}Do you wish to continue? (y/N): {COLOR_RESET}").strip().lower()
        if confirm not in ('y', ''):
            print("Installation cancelled by user.")
            return True

        # --- Phase 2: All changes happen after confirmation ---

        # 5. Prepare Install Directory
        show_status("Preparing install directory")
        if not self._prepare_install_directory():
            self.logger.error("Workflow aborted: Failed to prepare installation directory.")
            clear_status()
            input(f"\n{COLOR_PROMPT}Press Enter to return to the main menu...{COLOR_RESET}")
            return True # Return to menu
        self.logger.info("Installation directory prepared successfully.")

        # 6. Download Wabbajack.exe
        show_status("Downloading Wabbajack.exe")
        if not self._download_wabbajack_executable():
            self.logger.error("Workflow aborted: Failed to download Wabbajack.exe.")
            clear_status()
            input(f"\n{COLOR_PROMPT}Press Enter to return to the main menu...{COLOR_RESET}")
            return True # Return to menu
        clear_status()

        # 7. Create Steam Shortcut
        show_status("Creating Steam shortcut")
        shortcut_created = self._create_steam_shortcut()
        clear_status()
        if not shortcut_created:
            self.logger.error("Workflow aborted: Failed to create Steam shortcut.")
            input(f"\n{COLOR_PROMPT}Press Enter to return to the main menu...{COLOR_RESET}")
            return True # Return to menu

        # Print the AppID immediately after shortcut creation, before any other output
        print("\n==================== Steam Shortcut Created ====================")
        if self.initial_appid:
            print(f"{COLOR_INFO}Initial Steam AppID (before Steam restart): {self.initial_appid}{COLOR_RESET}")
        else:
            print(f"{COLOR_ERROR}Warning: Could not determine initial AppID after shortcut creation.{COLOR_RESET}")
        print("==============================================================\n")

        # 8. Handle Steam Restart & Manual Steps (Calls _print_default_status internally)
        if not self._handle_steam_restart_and_manual_steps():
            # Status already cleared by the function if needed
            self.logger.info("Workflow aborted: Steam restart/manual steps issue or user needs to re-run.")
            return True # Return to menu, user needs to act

        # 9. Verify Manual Steps
        # Move cursor up, return to start, clear line - attempt to overwrite input prompt line
        print("\033[A\r\033[K", end="", flush=True) 
        show_status("Verifying Proton Setup")
        while True:
            if self._verify_manual_steps():
                show_status("Manual Steps Successful")
                # Print the AppID after Steam restart and re-detection
                if self.final_appid:
                    print(f"\n{COLOR_INFO}Final Steam AppID (after Steam restart): {self.final_appid}{COLOR_RESET}")
                else:
                    print(f"\n{COLOR_ERROR}Warning: Could not determine AppID after Steam restart.{COLOR_RESET}")
                break # Verification successful
            else:
                self.logger.warning("Manual steps verification failed.")
                clear_status() # Clear status before printing error/prompt
                print(f"\n{COLOR_ERROR}Verification failed. Please ensure you have completed all manual steps correctly.{COLOR_RESET}")
                self._display_manual_proton_steps() # Re-display steps
                try:
                    # Add a newline before the input prompt for clarity
                    response = input(f"\n{COLOR_PROMPT}Press Enter to retry verification, or 'q' to quit: {COLOR_RESET}").lower()
                    if response == 'q':
                        self.logger.warning("User quit during verification loop.")
                        return True # Return to menu, aborting config
                    show_status("Retrying Verification") 
                except KeyboardInterrupt:
                     clear_status()
                     print("\nOperation cancelled by user.")
                     self.logger.warning("User cancelled during verification loop.")
                     return True # Return to menu

        # --- Start Actual Configuration ---
        self.logger.info(f"Starting final configuration for AppID {self.final_appid}...")
        # logger.info("--- Configuration --- Applying final configurations...") # Keep this log for file

        # Check console level for verbose output
        verbose_console = False
        for handler in logging.getLogger().handlers:
            if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler):
                if handler.level <= logging.INFO: # Check if INFO or DEBUG
                     verbose_console = True
                break
        
        if verbose_console:
             print(f"{COLOR_INFO}Applying final configurations...{COLOR_RESET}")

        # 10. Set Protontricks Permissions (Flatpak)
        show_status("Setting Protontricks permissions")
        if not self.protontricks_handler.set_protontricks_permissions(str(self.install_path), self.steamdeck):
            self.logger.warning("Failed to set Flatpak Protontricks permissions. Continuing, but subsequent steps might fail if Flatpak Protontricks is used.")
            clear_status() # Clear status before printing warning
            print(f"\n{COLOR_ERROR}Warning: Could not set Flatpak permissions automatically.{COLOR_RESET}") 

        # 12. Download WebView Installer (Check happens BEFORE setting prefix)
        show_status("Checking WebView Installer")
        if not self._download_webview_installer():
            self.logger.error("Workflow aborted: Failed to download WebView installer.")
            # Error message printed by the download function
            clear_status()
            input(f"\n{COLOR_PROMPT}Press Enter to return to the main menu...{COLOR_RESET}")
            return True # Return to menu

        # 13. Configure Prefix (Set to Win7 for WebView install)
        show_status("Applying Initial Win7 Registry Settings (for WebView install)")
        try:
            import requests
            # Download minimal Win7 system.reg (corrected URL)
            system_reg_win7_url = "https://raw.githubusercontent.com/Omni-guides/Wabbajack-Modlist-Linux/refs/heads/main/files/system.reg.wj.win7"
            system_reg_dest = self.compatdata_path / 'pfx' / 'system.reg'
            system_reg_dest.parent.mkdir(parents=True, exist_ok=True)
            self.logger.info(f"Downloading system.reg.wj.win7 from {system_reg_win7_url} to {system_reg_dest}")
            response = requests.get(system_reg_win7_url, verify=True)
            response.raise_for_status()
            with open(system_reg_dest, "wb") as f:
                f.write(response.content)
            self.logger.info(f"system.reg.wj.win7 downloaded and applied to {system_reg_dest}")
        except Exception as e:
            self.logger.error(f"Failed to download or apply initial Win7 system.reg: {e}")
            print(f"{COLOR_ERROR}Error: Failed to download or apply initial Win7 system.reg. {e}{COLOR_RESET}")
            clear_status()
            input(f"\n{COLOR_PROMPT}Press Enter to return to the main menu...{COLOR_RESET}")
            return True

        # 14. Install WebView (using protontricks-launch)
        show_status("Installing WebView (Edge)")
        webview_installer_path = self.install_path / "MicrosoftEdgeWebView2RuntimeInstallerX64-WabbajackProton.exe"
        webview_result = self.protontricks_handler.run_protontricks_launch(
            self.final_appid, webview_installer_path, "/silent", "/install"
        )
        self.logger.debug(f"WebView install result: {webview_result}")
        if not webview_result or webview_result.returncode != 0:
            self.logger.error("WebView installation failed via protontricks-launch.")
            print(f"{COLOR_ERROR}Error: WebView installation failed via protontricks-launch.{COLOR_RESET}")
            clear_status()
            input(f"\n{COLOR_PROMPT}Press Enter to return to the main menu...{COLOR_RESET}")
            return True
        show_status("WebView installation Complete")

        # 15. Configure Prefix (Part 2 - Final Settings)
        show_status("Applying Final Registry Settings")
        try:
            # Download final system.reg
            system_reg_url = "https://raw.githubusercontent.com/Omni-guides/Wabbajack-Modlist-Linux/refs/heads/main/files/system.reg.wj"
            system_reg_dest = self.compatdata_path / 'pfx' / 'system.reg'
            self.logger.info(f"Downloading final system.reg from {system_reg_url} to {system_reg_dest}")
            response = requests.get(system_reg_url, verify=True)
            response.raise_for_status()
            with open(system_reg_dest, "wb") as f:
                f.write(response.content)
            self.logger.info(f"Final system.reg downloaded and applied to {system_reg_dest}")
            # Download final user.reg
            user_reg_url = "https://raw.githubusercontent.com/Omni-guides/Wabbajack-Modlist-Linux/refs/heads/main/files/user.reg.wj"
            user_reg_dest = self.compatdata_path / 'pfx' / 'user.reg'
            self.logger.info(f"Downloading final user.reg from {user_reg_url} to {user_reg_dest}")
            response = requests.get(user_reg_url, verify=True)
            response.raise_for_status()
            with open(user_reg_dest, "wb") as f:
                f.write(response.content)
            self.logger.info(f"Final user.reg downloaded and applied to {user_reg_dest}")
        except Exception as e:
            self.logger.error(f"Failed to download or apply final user.reg/system.reg: {e}")
            print(f"{COLOR_ERROR}Error: Failed to download or apply final user.reg/system.reg. {e}{COLOR_RESET}")
            clear_status()
            input(f"\n{COLOR_PROMPT}Press Enter to return to the main menu...{COLOR_RESET}")
            return True

        # 16. Configure Prefix Steam Library VDF
        show_status("Configuring Steam Library in Prefix")
        if not self._create_prefix_library_vdf(): return False

        # 17. Create Dotnet Bundle Cache Directory
        show_status("Creating .NET Cache Directory")
        if not self._create_dotnet_cache_dir():
            self.logger.error("Workflow aborted: Failed to create dotnet cache directory.")
            clear_status()
            input(f"\n{COLOR_PROMPT}Press Enter to return to the main menu...{COLOR_RESET}")
            return True # Return to menu

        # --- Final Steps ---
        # Check for and optionally apply Flatpak overrides *before* final cleanup/completion
        self._check_and_prompt_flatpak_overrides()

        # Attempt to clean up any stray Wine/Protontricks processes as a final measure
        self.logger.info("Performing final Wine process cleanup...")
        try:
            # Ensure the ProtontricksHandler instance exists and has the method
            if hasattr(self, 'protontricks_handler') and hasattr(self.protontricks_handler, '_cleanup_wine_processes'):
                 self.protontricks_handler._cleanup_wine_processes()
                 self.logger.info("Wine process cleanup command executed.")
            else:
                 self.logger.warning("Protontricks handler or cleanup method not available, skipping cleanup.")
        except Exception as cleanup_e:
            self.logger.error(f"Error during final Wine process cleanup: {cleanup_e}", exc_info=True)
            # Don't abort the whole workflow for a cleanup failure, just log it.

        # 18b. Display Completion Message
        clear_status()
        self._display_completion_message()
        
        # End of successful workflow
        self.logger.info("Wabbajack installation workflow completed successfully.")
        clear_status() # Clear status before final prompt
        input(f"\n{COLOR_PROMPT}Press Enter to return to the main menu...{COLOR_RESET}")
        return True # Return to menu

    def _display_summary(self):
        """Displays a summary of settings (no confirmation prompt)."""
        if not self.install_path or not self.shortcut_name:
            self.logger.error("Cannot display summary: Install path or shortcut name missing.")
            return False # Should not happen if called at the right time
        print("\n───────────────────────────────────────────────────────────────────")
        print(f"{COLOR_PROMPT}--- Installation Summary ---{COLOR_RESET}")
        print(f"  Install Path:    {self.install_path}")
        print(f"  Shortcut Name:   {self.shortcut_name}")
        print(f"  Environment:     {'Steam Deck' if self.steamdeck else 'Desktop Linux'}")
        print(f"  Protontricks:    {self.protontricks_handler.which_protontricks or 'Unknown'}")
        print("───────────────────────────────────────────────────────────────────")
        return True

    def _backup_and_replace_final_reg_files(self) -> bool:
        """Backs up current reg files and replaces them with the final downloaded versions."""
        if not self.compatdata_path:
            self.logger.error("Cannot backup/replace reg files: compatdata_path not set.")
            return False

        pfx_path = self.compatdata_path / 'pfx'
        system_reg = pfx_path / 'system.reg'
        user_reg = pfx_path / 'user.reg'
        system_reg_bak = pfx_path / 'system.reg.orig'
        user_reg_bak = pfx_path / 'user.reg.orig'

        # Backup existing files
        self.logger.info("Backing up existing registry files...")
        logger.info("Backing up current registry files...") 
        try:
            if system_reg.exists():
                shutil.copy2(system_reg, system_reg_bak)
                self.logger.debug(f"Backed up {system_reg} to {system_reg_bak}")
            else:
                 self.logger.warning(f"Original {system_reg} not found for backup.")
                 
            if user_reg.exists():
                shutil.copy2(user_reg, user_reg_bak)
                self.logger.debug(f"Backed up {user_reg} to {user_reg_bak}")
            else:
                 self.logger.warning(f"Original {user_reg} not found for backup.")
                 
        except Exception as e:
            self.logger.error(f"Error backing up registry files: {e}", exc_info=True)
            print(f"{COLOR_ERROR}Error backing up registry files: {e}{COLOR_RESET}")
            return False # Treat backup failure as critical?

        # Define final registry file URLs
        final_system_reg_url = "https://github.com/Omni-guides/Wabbajack-Modlist-Linux/raw/refs/heads/main/files/system.reg.github"
        final_user_reg_url = "https://github.com/Omni-guides/Wabbajack-Modlist-Linux/raw/refs/heads/main/files/user.reg.github"

        # Download and replace
        logger.info("Downloading and applying final registry settings...") 
        system_ok = self._download_and_replace_reg_file(final_system_reg_url, system_reg)
        user_ok = self._download_and_replace_reg_file(final_user_reg_url, user_reg)

        if system_ok and user_ok:
            self.logger.info("Successfully applied final registry files.")
            return True
        else:
            self.logger.error("Failed to download or replace one or both final registry files.")
            print(f"{COLOR_ERROR}Error: Failed to apply final registry settings.{COLOR_RESET}")
            # Should we attempt to restore backups here?
            return False

    def _install_webview(self) -> bool:
        """Installs the WebView2 runtime using protontricks-launch."""
        if not self.final_appid or not self.install_path:
            self.logger.error("Cannot install WebView: final_appid or install_path not set.")
            return False

        installer_name = "MicrosoftEdgeWebView2RuntimeInstallerX64-WabbajackProton.exe"
        installer_path = self.install_path / installer_name

        if not installer_path.is_file():
            self.logger.error(f"WebView installer not found at {installer_path}. Cannot install.")
            print(f"{COLOR_ERROR}Error: WebView installer file missing. Please ensure step 12 completed.{COLOR_RESET}")
            return False

        self.logger.info(f"Starting WebView installation for AppID {self.final_appid}...")
        # Remove print, handled by caller
        # print("\nInstalling WebView (this can take a while, please be patient)...") 

        cmd_prefix = []
        if self.protontricks_handler.which_protontricks == 'flatpak':
            # Using full command path is safer than relying on alias being sourced
            cmd_prefix = ["flatpak", "run", "--command=protontricks-launch", "com.github.Matoking.protontricks"]
        else:
            launch_path = shutil.which("protontricks-launch")
            if not launch_path:
                self.logger.error("protontricks-launch command not found in PATH.")
                print(f"{COLOR_ERROR}Error: protontricks-launch command not found.{COLOR_RESET}")
                return False
            cmd_prefix = [launch_path]
            
        # Arguments for protontricks-launch
        args = ["--appid", self.final_appid, str(installer_path), "/silent", "/install"]
        full_cmd = cmd_prefix + args
        
        self.logger.debug(f"Executing WebView install command: {' '.join(full_cmd)}")

        try:
            # Use check=True to raise CalledProcessError on non-zero exit
            # Set a longer timeout as this can take time.
            result = subprocess.run(full_cmd, check=True, capture_output=True, text=True, timeout=600) # 10 minute timeout
            self.logger.info("WebView installation command completed successfully.")
            # Do NOT log result.stdout or result.stderr here
            return True
        except FileNotFoundError:
             self.logger.error(f"Command not found: {cmd_prefix[0]}")
             print(f"{COLOR_ERROR}Error: Could not execute {cmd_prefix[0]}. Is it installed correctly?{COLOR_RESET}")
             return False
        except subprocess.TimeoutExpired:
            self.logger.error("WebView installation timed out after 10 minutes.")
            print(f"{COLOR_ERROR}Error: WebView installation took too long and timed out.{COLOR_RESET}")
            return False
        except subprocess.CalledProcessError as e:
            self.logger.error(f"WebView installation failed with return code {e.returncode}")
            # Only log a short snippet of output for debugging
            self.logger.error(f"STDERR (truncated):\n{e.stderr[:500] if e.stderr else ''}")
            print(f"{COLOR_ERROR}Error: WebView installation failed (Return Code: {e.returncode}). Check logs for details.{COLOR_RESET}")
            return False
        except Exception as e:
            self.logger.error(f"Unexpected error during WebView installation: {e}", exc_info=True)
            print(f"{COLOR_ERROR}An unexpected error occurred during WebView installation: {e}{COLOR_RESET}")
            return False

    def _find_steam_library_and_vdf_path(self) -> Tuple[Optional[Path], Optional[Path]]:
        """Finds the Steam library root and the path to the real libraryfolders.vdf."""
        self.logger.info("Attempting to find Steam library and libraryfolders.vdf...")
        try:
            # Check if PathHandler uses static methods or needs instantiation
            if isinstance(self.path_handler, type):
                common_path = self.path_handler.find_steam_library()
            else:
                common_path = self.path_handler.find_steam_library()

            if not common_path or not common_path.is_dir():
                self.logger.error("Could not find Steam library common path.")
                return None, None

            # Navigate up to find the library root
            library_root = common_path.parent.parent # steamapps/common -> steamapps -> library_root
            self.logger.debug(f"Deduced library root: {library_root}")

            # Construct path to the real libraryfolders.vdf
            # Common locations relative to library root
            vdf_path_candidates = [
                library_root / 'config/libraryfolders.vdf', # For non-Flatpak? ~/.steam/steam/config
                library_root / '../config/libraryfolders.vdf' # Flatpak? ~/.var/app/../Steam/config
            ]
            
            real_vdf_path = None
            for candidate in vdf_path_candidates:
                 resolved_candidate = candidate.resolve() # Resolve symlinks/.. parts
                 if resolved_candidate.is_file():
                     real_vdf_path = resolved_candidate
                     self.logger.info(f"Found real libraryfolders.vdf at: {real_vdf_path}")
                     break
            
            if not real_vdf_path:
                self.logger.error(f"Could not find libraryfolders.vdf within library root: {library_root}")
                return None, None
                
            return library_root, real_vdf_path
            
        except Exception as e:
            self.logger.error(f"Error finding Steam library/VDF: {e}", exc_info=True)
            return None, None

    def _link_steam_library_config(self) -> bool:
        """Creates the necessary directory structure and symlinks libraryfolders.vdf."""
        if not self.compatdata_path:
            self.logger.error("Cannot link Steam library: compatdata_path not set.")
            return False
            
        self.logger.info("Linking Steam library configuration (libraryfolders.vdf)...")
        
        library_root, real_vdf_path = self._find_steam_library_and_vdf_path()
        if not library_root or not real_vdf_path:
            print(f"{COLOR_ERROR}Error: Could not locate Steam library or libraryfolders.vdf.{COLOR_RESET}")
            return False

        target_dir = self.compatdata_path / 'pfx/drive_c/Program Files (x86)/Steam/config'
        link_path = target_dir / 'libraryfolders.vdf'

        try:
            # Backup the original libraryfolders.vdf before doing anything else
            # Use FileSystemHandler for consistency - NOW USE INSTANCE
            self.logger.debug(f"Backing up original libraryfolders.vdf: {real_vdf_path}")
            if not self.filesystem_handler.backup_file(real_vdf_path):
                 self.logger.warning(f"Failed to backup {real_vdf_path}. Proceeding with caution.")
                 # Optionally, prompt user or fail here? For now, just warn.
                 print(f"{COLOR_ERROR}Warning: Failed to create backup of libraryfolders.vdf.{COLOR_RESET}")

            # Create the target directory
            self.logger.debug(f"Creating directory: {target_dir}")
            os.makedirs(target_dir, exist_ok=True)

            # Remove existing symlink if it exists
            if link_path.is_symlink():
                self.logger.debug(f"Removing existing symlink at {link_path}")
                link_path.unlink()
            elif link_path.exists():
                # It exists but isn't a symlink - this is unexpected
                self.logger.warning(f"Path {link_path} exists but is not a symlink. Removing it.")
                if link_path.is_dir():
                    shutil.rmtree(link_path)
                else:
                    link_path.unlink()

            # Create the symlink
            self.logger.info(f"Creating symlink from {real_vdf_path} to {link_path}")
            os.symlink(real_vdf_path, link_path)
            
            # Verification (optional but good)
            if link_path.is_symlink() and link_path.resolve() == real_vdf_path.resolve():
                self.logger.info("Symlink created and verified successfully.")
                return True
            else:
                self.logger.error("Symlink creation failed or verification failed.")
                return False

        except OSError as e:
            self.logger.error(f"OSError during symlink creation: {e}", exc_info=True)
            print(f"{COLOR_ERROR}Error creating Steam library link: {e}{COLOR_RESET}")
            return False
        except Exception as e:
             self.logger.error(f"Unexpected error during symlink creation: {e}", exc_info=True)
             print(f"{COLOR_ERROR}An unexpected error occurred: {e}{COLOR_RESET}")
             return False

    def _create_prefix_library_vdf(self) -> bool:
        """Creates the necessary directory structure and copies a modified libraryfolders.vdf."""
        if not self.compatdata_path:
            self.logger.error("Cannot create prefix VDF: compatdata_path not set.")
            return False
            
        self.logger.info("Creating modified libraryfolders.vdf in prefix...")
        
        # 1. Find the real host VDF file
        library_root, real_vdf_path = self._find_steam_library_and_vdf_path()
        if not real_vdf_path:
            # Error logged by _find_steam_library_and_vdf_path
            print(f"{COLOR_ERROR}Error: Could not locate real libraryfolders.vdf.{COLOR_RESET}")
            return False
        
        # 2. Backup the real VDF file
        self.logger.debug(f"Backing up original libraryfolders.vdf: {real_vdf_path}")
        if not self.filesystem_handler.backup_file(real_vdf_path):
            self.logger.warning(f"Failed to backup {real_vdf_path}. Proceeding with caution.")
            print(f"{COLOR_ERROR}Warning: Failed to create backup of libraryfolders.vdf.{COLOR_RESET}")
        
        # 3. Define target location in prefix
        target_dir = self.compatdata_path / 'pfx/drive_c/Program Files (x86)/Steam/config'
        target_vdf_path = target_dir / 'libraryfolders.vdf'

        try:
            # 4. Read the content of the real VDF
            self.logger.debug(f"Reading content from {real_vdf_path}")
            vdf_content = real_vdf_path.read_text(encoding='utf-8')
            
            # 5. Convert Linux paths to Wine paths within the content string
            modified_content = vdf_content
            # Regex to find "path" "/linux/path" entries reliably
            path_pattern = re.compile(r'("path"\s*")([^"]+)(")')

            # Use a function for replacement logic to handle potential errors
            def replace_path(match):
                prefix, linux_path_str, suffix = match.groups()
                self.logger.debug(f"Found path entry to convert: {linux_path_str}")
                try:
                    linux_path = Path(linux_path_str)
                    # Check if it's an SD card path
                    if self.filesystem_handler.is_sd_card(linux_path):
                        # Assuming SD card maps to D:
                        # Remove prefix like /run/media/mmcblk0p1/
                        relative_sd_path_str = self.filesystem_handler._strip_sdcard_path_prefix(linux_path)
                        wine_path = "D:\\" + relative_sd_path_str.replace('/', '\\')
                        self.logger.debug(f"  Converted SD card path: {linux_path_str} -> {wine_path}")
                    else:
                        # Assume non-SD maps relative to Z:
                        # Need the full path prefixed with Z:
                        wine_path = "Z:\\" + linux_path_str.strip('/').replace('/', '\\')
                        self.logger.debug(f"  Converted standard path: {linux_path_str} -> {wine_path}")
                    
                    # Ensure backslashes are doubled for VDF format
                    wine_path_vdf_escaped = wine_path.replace('\\', '\\\\')
                    return f'{prefix}{wine_path_vdf_escaped}{suffix}'
                except Exception as e:
                    self.logger.error(f"Error converting path '{linux_path_str}': {e}. Keeping original.")
                    return match.group(0) # Return original match on error

            # Perform the replacement using re.sub with the function
            modified_content = path_pattern.sub(replace_path, vdf_content)
            
            # Log comparison if content changed (optional)
            if modified_content != vdf_content:
                self.logger.info("Successfully converted Linux paths to Wine paths in VDF content.")
            else:
                self.logger.warning("VDF content unchanged after conversion attempt. Did it contain Linux paths?")

            # 6. Ensure target directory exists
            self.logger.debug(f"Ensuring target directory exists: {target_dir}")
            os.makedirs(target_dir, exist_ok=True)

            # 7. Write the modified content to the target file in the prefix
            self.logger.info(f"Writing modified VDF content to {target_vdf_path}")
            target_vdf_path.write_text(modified_content, encoding='utf-8')
            
            # 8. Verification (optional: check file exists and content)
            if target_vdf_path.is_file():
                 self.logger.info("Prefix libraryfolders.vdf created successfully.")
                 return True
            else:
                 self.logger.error("Failed to create prefix libraryfolders.vdf.")
                 return False

        except Exception as e:
            self.logger.error(f"Error processing or writing prefix libraryfolders.vdf: {e}", exc_info=True)
            print(f"{COLOR_ERROR}An error occurred configuring the Steam library in the prefix: {e}{COLOR_RESET}")
            return False

    def _create_dotnet_cache_dir(self) -> bool:
        """Creates the dotnet_bundle_extract cache directory."""
        if not self.install_path:
            self.logger.error("Cannot create dotnet cache dir: install_path not set.")
            return False

        try:
            # Get username reliably
            username = pwd.getpwuid(os.getuid()).pw_name
            # Fallback if pwd fails for some reason?
            # username = os.getlogin() # Can fail in some environments
        except Exception as e:
            self.logger.error(f"Could not determine username: {e}")
            print(f"{COLOR_ERROR}Error: Could not determine username to create cache directory.{COLOR_RESET}")
            return False
            
        cache_dir = self.install_path / 'home' / username / '.cache' / 'dotnet_bundle_extract'
        self.logger.info(f"Creating dotnet bundle cache directory: {cache_dir}")
        
        try:
            os.makedirs(cache_dir, exist_ok=True)
            # Optionally set permissions? The bash script didn't explicitly.
            self.logger.info("dotnet cache directory created successfully.")
            return True
        except OSError as e:
            self.logger.error(f"Failed to create dotnet cache directory {cache_dir}: {e}", exc_info=True)
            print(f"{COLOR_ERROR}Error creating dotnet cache directory: {e}{COLOR_RESET}")
            return False
        except Exception as e:
            self.logger.error(f"Unexpected error creating dotnet cache directory: {e}", exc_info=True)
            print(f"{COLOR_ERROR}An unexpected error occurred: {e}{COLOR_RESET}")
            return False

    def _check_and_prompt_flatpak_overrides(self):
        """Checks if Flatpak Steam needs filesystem overrides and prompts the user to apply them."""
        self.logger.info("Checking for necessary Flatpak Steam filesystem overrides...")
        is_flatpak_steam = False
        # Use compatdata_path as indicator
        if self.compatdata_path and ".var/app/com.valvesoftware.Steam" in str(self.compatdata_path):
            is_flatpak_steam = True
            self.logger.debug("Flatpak Steam detected based on compatdata path.")
        # Add other checks if needed (e.g., check if `flatpak info com.valvesoftware.Steam` runs)
        
        if not is_flatpak_steam:
            self.logger.info("Flatpak Steam not detected, skipping override check.")
            return

        paths_to_check = []
        if self.install_path:
            paths_to_check.append(self.install_path)

        # Get all library paths from libraryfolders.vdf
        try:
            all_libs = self.path_handler.get_all_steam_libraries()
            paths_to_check.extend(all_libs)
        except Exception as e:
            self.logger.warning(f"Could not get all Steam libraries to check for overrides: {e}")

        needed_overrides = set() # Use a set to store unique parent paths needing override
        home_dir = Path.home()
        flatpak_steam_data_dir = home_dir / ".var/app/com.valvesoftware.Steam"

        for path in paths_to_check:
            if not path:
                continue
            resolved_path = path.resolve()
            # Check if path is outside $HOME AND outside the Flatpak data dir
            is_outside_home = not str(resolved_path).startswith(str(home_dir))
            is_outside_flatpak_data = not str(resolved_path).startswith(str(flatpak_steam_data_dir))

            if is_outside_home and is_outside_flatpak_data:
                # Need override for the parent directory containing this path
                # Go up levels until we find a reasonable base (e.g., /mnt/Games, /data/Steam)
                # Avoid adding /, /home, etc.
                parent_to_add = resolved_path.parent 
                while parent_to_add != parent_to_add.parent and len(str(parent_to_add)) > 1 and parent_to_add.name != 'home': 
                    # Check if adding this parent makes sense (e.g., it exists, not too high up)
                    if parent_to_add.is_dir(): # Simple check for existence
                        # Further heuristics could be added here
                        needed_overrides.add(str(parent_to_add))
                        self.logger.debug(f"Path {resolved_path} is outside sandbox. Adding parent {parent_to_add} to needed overrides.")
                        break # Add the first reasonable parent found
                    parent_to_add = parent_to_add.parent

        if not needed_overrides:
            self.logger.info("No external paths requiring Flatpak overrides detected.")
            return

        # Construct the command string(s)
        override_commands = []
        for path_str in sorted(list(needed_overrides)):
             # Add specific path override
             override_commands.append(f"flatpak override --user --filesystem=\"{path_str}\" com.valvesoftware.Steam")
        
        # Combine into a single string for display, but keep list for execution
        command_display = "\n".join([f"  {cmd}" for cmd in override_commands])

        print(f"\n{COLOR_PROMPT}--- Flatpak Steam Permissions ---{COLOR_RESET}")
        print("Jackify has detected that you are using Flatpak Steam and have paths")
        print("(e.g., Wabbajack install location or other Steam libraries) outside")
        print("the standard Flatpak sandbox. For Wabbajack to access these locations,")
        print("Steam needs the following filesystem permissions:")
        print(f"{COLOR_INFO}{command_display}{COLOR_RESET}")
        print("───────────────────────────────────────────────────────────────────")

        try:
            confirm = input(f"{COLOR_PROMPT}Do you want Jackify to apply these permissions now? (y/N): {COLOR_RESET}").lower().strip()
            if confirm == 'y':
                self.logger.info("User confirmed applying Flatpak overrides.")
                success_count = 0
                for cmd_str in override_commands:
                     self.logger.info(f"Executing: {cmd_str}")
                     try:
                          # Split command string for subprocess
                          cmd_list = cmd_str.split()
                          result = subprocess.run(cmd_list, check=True, capture_output=True, text=True, timeout=30)
                          self.logger.debug(f"Override command successful: {result.stdout}")
                          success_count += 1
                     except FileNotFoundError:
                          self.logger.error(f"'flatpak' command not found. Cannot apply override: {cmd_str}")
                          print(f"{COLOR_ERROR}Error: 'flatpak' command not found.{COLOR_RESET}")
                          break # Stop trying if flatpak isn't found
                     except subprocess.TimeoutExpired:
                         self.logger.error(f"Flatpak override command timed out: {cmd_str}")
                         print(f"{COLOR_ERROR}Error: Command timed out: {cmd_str}{COLOR_RESET}")
                     except subprocess.CalledProcessError as e:
                         self.logger.error(f"Flatpak override failed: {cmd_str}. Error: {e.stderr}")
                         print(f"{COLOR_ERROR}Error applying override: {cmd_str}\n{e.stderr}{COLOR_RESET}")
                     except Exception as e:
                         self.logger.error(f"Unexpected error applying override {cmd_str}: {e}")
                         print(f"{COLOR_ERROR}An unexpected error occurred: {e}{COLOR_RESET}")
                
                if success_count == len(override_commands):
                    print(f"{COLOR_INFO}Successfully applied necessary Flatpak permissions.{COLOR_RESET}")
                else:
                    print(f"{COLOR_ERROR}Applied {success_count}/{len(override_commands)} permissions. Some overrides may have failed. Check logs.{COLOR_RESET}")
            else:
                self.logger.info("User declined applying Flatpak overrides.")
                print("Permissions not applied. You may need to run the override command(s) manually")
                print("if Wabbajack has issues accessing files or game installations.")
                
        except KeyboardInterrupt:
            print("\nOperation cancelled by user.")
            self.logger.warning("User cancelled during Flatpak override prompt.")
        except Exception as e:
            self.logger.error(f"Error during Flatpak override prompt/execution: {e}")

    def _disable_prefix_decoration(self) -> bool:
        """Disables window manager decoration in the Wine prefix using protontricks -c."""
        if not self.final_appid:
            self.logger.error("Cannot disable decoration: final_appid not set.")
            return False
            
        self.logger.info(f"Disabling window manager decoration for AppID {self.final_appid} via -c 'wine reg add...'")
        # Original command string
        command = 'wine reg add "HKCU\\Software\\Wine\\X11 Driver" /v Decorated /t REG_SZ /d N /f'
        
        try:
            # Ensure ProtontricksHandler is available
            if not hasattr(self, 'protontricks_handler') or not self.protontricks_handler:
                 self.logger.critical("ProtontricksHandler not initialized!")
                 print(f"{COLOR_ERROR}Internal Error: Protontricks handler not available.{COLOR_RESET}")
                 return False
                 
            # Use the original -c method
            result = self.protontricks_handler.run_protontricks(
                '-c',
                command,
                self.final_appid # AppID comes last for -c commands
            )
            
            # Check the return code
            if result and result.returncode == 0:
                self.logger.info("Successfully disabled window decoration (command returned 0).")
                # Add a small delay just in case there's a write lag?
                time.sleep(1) 
                return True
            else:
                err_msg = result.stderr if result else "Command execution failed or returned non-zero"
                 # Add stdout to error message if stderr is empty
                if result and not result.stderr and result.stdout:
                    err_msg += f"\nSTDOUT: {result.stdout}"
                self.logger.error(f"Failed to disable window decoration via -c. Error: {err_msg}")
                print(f"{COLOR_ERROR}Error: Failed to disable window decoration via protontricks -c.{COLOR_RESET}")
                return False
        except Exception as e:
            self.logger.error(f"Exception disabling window decoration: {e}", exc_info=True)
            print(f"{COLOR_ERROR}Error disabling window decoration: {e}.{COLOR_RESET}")
            return False

    def _display_completion_message(self):
        """Displays the final success message and next steps."""
        # Basic log file path (assuming standard location)
        # TODO: Get log file path more reliably if needed
        log_path = Path.home() / "Jackify" / "logs" / "jackify-cli.log"

        print("\n───────────────────────────────────────────────────────────────────")
        print(f"{COLOR_INFO}Wabbajack Installation Completed Successfully!{COLOR_RESET}")
        print("───────────────────────────────────────────────────────────────────")
        print("Next Steps:")
        print(f"  • Launch '{COLOR_INFO}{self.shortcut_name or 'Wabbajack'}{COLOR_RESET}' through Steam.")
        print(f"  • When Wabbajack opens, log in to Nexus using the Settings button (cog icon).")
        print(f"  • Once logged in, you can browse and install modlists as usual!")
        
        # Check for Flatpak Steam (Placeholder check)
        # A more robust check might involve inspecting self.path_handler findings or config
        # For now, check if compatdata path hints at flatpak
        is_flatpak_steam = False
        if self.compatdata_path and ".var/app/com.valvesoftware.Steam" in str(self.compatdata_path):
            is_flatpak_steam = True
            
        if is_flatpak_steam:
             self.logger.info("Detected Flatpak Steam usage.")
             print(f"\n{COLOR_PROMPT}Note: Flatpak Steam Detected:{COLOR_RESET}")
             print(f"   You may need to grant Wabbajack filesystem access for modlist downloads/installations.")
             print(f"   Example: If installing to \"/home/{os.getlogin()}/Games/SkyrimSEModlist\", run:")
             print(f"   {COLOR_INFO}flatpak override --user --filesystem=/home/{os.getlogin()}/Games com.valvesoftware.Steam{COLOR_RESET}")

        print(f"\nDetailed log available at: {log_path}")
        print("───────────────────────────────────────────────────────────────────")

    def _download_wabbajack_executable(self) -> bool:
        """
        Downloads the latest Wabbajack.exe to the install directory.
        Checks existence first.

        Returns:
            bool: True on success or if file exists, False otherwise.
        """
        if not self.install_path:
            self.logger.error("Cannot download Wabbajack.exe: install_path is not set.")
            return False

        url = "https://github.com/wabbajack-tools/wabbajack/releases/latest/download/Wabbajack.exe"
        destination = self.install_path / "Wabbajack.exe"

        # Check if file exists first
        if destination.is_file():
            self.logger.info(f"Wabbajack.exe already exists at {destination}. Skipping download.")
            # print("Wabbajack.exe already present.") # Replaced by logger
            return True
            
        # print(f"\nDownloading latest Wabbajack.exe...") # Replaced by logger
        self.logger.info("Wabbajack.exe not found. Downloading...")
        if self._download_file(url, destination):
            # print("Wabbajack.exe downloaded successfully.") # Replaced by logger
            # Set executable permissions
            try:
                os.chmod(destination, 0o755)
                self.logger.info(f"Set execute permissions on {destination}")
            except Exception as e:
                self.logger.warning(f"Could not set execute permission on {destination}: {e}")
                print(f"{COLOR_ERROR}Warning: Could not set execute permission on Wabbajack.exe.{COLOR_RESET}")
            return True
        else:
            self.logger.error("Failed to download Wabbajack.exe.")
            # Error message printed by _download_file
            return False

    def _create_steam_shortcut(self) -> bool:
        """
        Creates the Steam shortcut for Wabbajack using the ShortcutHandler.

        Returns:
            bool: True on success, False otherwise.
        """
        if not self.shortcut_name or not self.install_path:
            self.logger.error("Cannot create shortcut: Missing shortcut name or install path.")
            return False

        self.logger.info(f"Creating Steam shortcut '{self.shortcut_name}'...")
        executable_path = str(self.install_path / "Wabbajack.exe")

        # Ensure the ShortcutHandler instance exists
        # Create shortcut with working NativeSteamService
        from ..services.native_steam_service import NativeSteamService
        steam_service = NativeSteamService()
        
        success, app_id = steam_service.create_shortcut_with_proton(
            app_name=self.shortcut_name,
            exe_path=executable_path,
            start_dir=os.path.dirname(executable_path),
            launch_options="PROTON_USE_WINED3D=1 %command%",
            tags=["Jackify", "Wabbajack"],
            proton_version="proton_experimental"
        )

        if success and app_id:
            self.initial_appid = app_id # Store the initially generated AppID
            self.logger.info(f"Shortcut created successfully with initial AppID: {self.initial_appid}")
            # Remove direct print, rely on status indicator from caller
            # print(f"Steam shortcut '{self.shortcut_name}' created.") 
            return True
        else:
            self.logger.error("Failed to create Steam shortcut via ShortcutHandler.")
            print(f"{COLOR_ERROR}Error: Failed to create the Steam shortcut for Wabbajack.{COLOR_RESET}")
            # Further error details should be logged by the ShortcutHandler
            return False

    # --- Helper Methods for Workflow Steps ---

    def _display_manual_proton_steps(self):
        """Displays the detailed manual steps required for Proton setup."""
        if not self.shortcut_name:
            self.logger.error("Cannot display manual steps: shortcut_name not set.")
            print(f"{COLOR_ERROR}Internal Error: Shortcut name missing.{COLOR_RESET}")
            return

        print(f"\n{COLOR_PROMPT}--- Manual Proton Setup Required ---{COLOR_RESET}")
        print("Please complete the following steps in Steam:") 
        print(f"  1. Locate the '{COLOR_INFO}{self.shortcut_name}{COLOR_RESET}' entry in your Steam Library")
        print("  2. Right-click and select 'Properties'")
        print("  3. Switch to the 'Compatibility' tab")
        print("  4. Check the box labeled 'Force the use of a specific Steam Play compatibility tool'")
        print("  5. Select 'Proton - Experimental' from the dropdown menu")
        print("  6. Close the Properties window")
        print(f"  7. Launch '{COLOR_INFO}{self.shortcut_name}{COLOR_RESET}' from your Steam Library")
        print("  8. Wait for Wabbajack to download its files and fully load")
        print("  9. Once Wabbajack has fully loaded, CLOSE IT completely and return here")
        print(f"{COLOR_PROMPT}------------------------------------{COLOR_RESET}")

    def _handle_steam_restart_and_manual_steps(self) -> bool:
        """
        Handles Steam restart and manual steps prompt, with GUI mode support.
        """
        self.logger.info("Handling Steam restart and manual steps prompt.")
        clear_status()
        
        if os.environ.get('JACKIFY_GUI_MODE'):
            # GUI mode: emit prompt markers like ModlistMenuHandler does
            print('[PROMPT:RESTART_STEAM]')
            input()  # Wait for GUI to send confirmation
            print('[PROMPT:MANUAL_STEPS]')
            input()  # Wait for GUI to send confirmation
            # Continue with verification as before
            return True
        else:
            # CLI mode: original behavior
            # Condensed message: only show essential manual steps guidance
            print("\n───────────────────────────────────────────────────────────────────")
            print(f"{COLOR_INFO}Manual Steps Required:{COLOR_RESET} After Steam restarts, follow the on-screen instructions to set Proton Experimental.")
            print("───────────────────────────────────────────────────────────────────")
            self.logger.info("Attempting secure Steam restart...")
            show_status("Restarting Steam")
            if not hasattr(self, 'shortcut_handler') or not self.shortcut_handler:
                self.logger.critical("ShortcutHandler not initialized in InstallWabbajackHandler!")
                print(f"{COLOR_ERROR}Internal Error: Shortcut handler not available for restart.{COLOR_RESET}")
                return False
            if self.shortcut_handler.secure_steam_restart():
                self.logger.info("Secure Steam restart successful.")
                clear_status()
                self._display_manual_proton_steps()
                print()
                input(f"{COLOR_PROMPT}Once you have completed ALL the steps above, press Enter to continue...{COLOR_RESET}")
                self.logger.info("User confirmed completion of manual steps.")
                return True
            else:
                self.logger.error("Secure Steam restart failed.")
                clear_status()
                print(f"\n{COLOR_ERROR}Error: Steam restart failed.{COLOR_RESET}")
                print("Please try restarting Steam manually:")
                print("1. Exit Steam completely (Steam -> Exit or right-click tray icon -> Exit)")
                print("2. Wait a few seconds")
                print("3. Start Steam again")
                print("\nAfter restarting, you MUST perform the manual Proton setup steps:")
                self._display_manual_proton_steps()
                print(f"\n{COLOR_ERROR}You will need to re-run this Jackify option after completing these steps.{COLOR_RESET}")
                print("───────────────────────────────────────────────────────────────────")
                return False

    def _redetect_appid(self) -> bool:
        """
        Re-detects the AppID for the shortcut after Steam restart.

        Returns:
            bool: True if AppID is found, False otherwise.
        """
        if not self.shortcut_name:
            self.logger.error("Cannot redetect AppID: shortcut_name not set.")
            return False

        self.logger.info(f"Re-detecting AppID for shortcut '{self.shortcut_name}'...")
        try:
            # Ensure the ProtontricksHandler instance exists
            if not hasattr(self, 'protontricks_handler') or not self.protontricks_handler:
                self.logger.critical("ProtontricksHandler not initialized in InstallWabbajackHandler!")
                print(f"{COLOR_ERROR}Internal Error: Protontricks handler not available.{COLOR_RESET}")
                return False
                
            all_shortcuts = self.protontricks_handler.list_non_steam_shortcuts()
            
            if not all_shortcuts:
                self.logger.error("Protontricks listed no non-Steam shortcuts.")
                return False

            found_appid = None
            for name, appid in all_shortcuts.items():
                if name.lower() == self.shortcut_name.lower():
                    found_appid = appid
                    break
            
            if found_appid:
                self.final_appid = found_appid
                self.logger.info(f"Successfully re-detected AppID: {self.final_appid}")
                if self.initial_appid and self.initial_appid != self.final_appid:
                    # Change Warning to Info - this is expected behavior
                    self.logger.info(f"AppID changed after Steam restart: {self.initial_appid} -> {self.final_appid}") 
                elif not self.initial_appid:
                     self.logger.warning("Initial AppID was not set, cannot compare.")
                return True
            else:
                self.logger.error(f"Shortcut '{self.shortcut_name}' not found in protontricks list after restart.")
                return False

        except Exception as e:
            self.logger.error(f"Error re-detecting AppID: {e}", exc_info=True)
            return False

    def _find_steam_config_vdf(self) -> Optional[Path]:
        """Finds the path to the primary Steam config.vdf file."""
        self.logger.debug("Searching for Steam config.vdf...")
        # Use PathHandler if it has this logic? For now, check common paths.
        common_paths = [
            Path.home() / ".steam/steam/config/config.vdf",
            Path.home() / ".local/share/Steam/config/config.vdf",
            Path.home() / ".var/app/com.valvesoftware.Steam/.config/Valve Corporation/Steam/config/config.vdf" # Check Flatpak path
        ]
        for path in common_paths:
            if path.is_file():
                self.logger.info(f"Found config.vdf at: {path}")
                return path
        self.logger.error("Could not find Steam config.vdf in common locations.")
        return None

    def _verify_manual_steps(self) -> bool:
        """
        Verifies that the user has performed the manual steps using ModlistHandler.
        Checks AppID, Proton version set, and prefix existence.

        Returns:
            bool: True if verification passes AND compatdata_path is set, False otherwise.
        """
        self.logger.info("Verifying manual Proton setup steps...")
        self.compatdata_path = None # Explicitly reset before verification

        # 1. Re-detect AppID
        # Clear status BEFORE potentially failing here
        clear_status() 
        if not self._redetect_appid():
            print(f"{COLOR_ERROR}Error: Could not find the Steam shortcut '{self.shortcut_name}' using protontricks.{COLOR_RESET}")
            print(f"{COLOR_INFO}Ensure Steam has restarted and the shortcut is visible.{COLOR_RESET}")
            return False # Indicate failure

        self.logger.debug(f"Verification using final AppID: {self.final_appid}")

        # Add padding after user confirmation before the next status update
        # Removed print() call - padding should come AFTER status clear
        
        # Print status JUST before calling the verification logic
        show_status("Verifying Proton Setup") 

        # Ensure ModlistHandler is available
        if not hasattr(self, 'modlist_handler') or not self.modlist_handler:
            self.logger.critical("ModlistHandler not initialized in InstallWabbajackHandler!")
            print(f"{COLOR_ERROR}Internal Error: Modlist handler not available for verification.{COLOR_RESET}")
            return False

        # 2. Call the existing verification logic from ModlistHandler
        verified, status_code = self.modlist_handler.verify_proton_setup(self.final_appid)

        if not verified:
            # Handle Verification Failure Messages based on status_code
            if status_code == 'wrong_proton_version':
                proton_ver = getattr(self.modlist_handler, 'proton_ver', 'Unknown')
                print(f"{COLOR_ERROR}\nVerification Failed: Incorrect Proton version detected ('{proton_ver}'). Expected 'Proton Experimental' (or similar).{COLOR_RESET}")
                print(f"{COLOR_INFO}Please ensure you selected the correct Proton version in the shortcut's Compatibility properties.{COLOR_RESET}")
            elif status_code == 'proton_check_failed':
                print(f"{COLOR_ERROR}\nVerification Failed: Compatibility tool not detected as set for '{self.shortcut_name}' in Steam config.{COLOR_RESET}")
                print(f"{COLOR_INFO}Please ensure you forced a Proton version in the shortcut's Compatibility properties.{COLOR_RESET}")
            elif status_code == 'compatdata_missing':
                print(f"{COLOR_ERROR}\nVerification Failed: Steam compatdata directory for AppID {self.final_appid} not found.{COLOR_RESET}")
                print(f"{COLOR_INFO}Have you launched the shortcut '{self.shortcut_name}' at least once after setting Proton?{COLOR_RESET}")
            elif status_code == 'prefix_missing':
                print(f"{COLOR_ERROR}\nVerification Failed: Wine prefix directory (pfx) not found inside compatdata.{COLOR_RESET}")
                print(f"{COLOR_INFO}This usually means the shortcut hasn't been launched successfully after setting Proton.{COLOR_RESET}")
            elif status_code == 'config_vdf_missing' or status_code == 'config_vdf_error':
                 print(f"{COLOR_ERROR}\nVerification Failed: Could not read or parse Steam's config.vdf file ({status_code}).{COLOR_RESET}")
                 print(f"{COLOR_INFO}Check file permissions or integrity. Check logs for details.{COLOR_RESET}")
            else: # General/unknown error
                print(f"{COLOR_ERROR}\nVerification Failed: An unexpected error occurred ({status_code}). Check logs.{COLOR_RESET}")
            return False # Indicate verification failure

        # If we reach here, basic verification passed (proton set, prefix exists)
        # Now, ensure we have the compatdata path.
        self.logger.info("Basic verification checks passed. Confirming compatdata path...")

        modlist_handler_compat_path = getattr(self.modlist_handler, 'compat_data_path', None)
        if modlist_handler_compat_path:
            self.compatdata_path = modlist_handler_compat_path
            self.logger.info(f"Compatdata path obtained from ModlistHandler: {self.compatdata_path}")
        else:
            # If modlist_handler didn't set it, try path_handler
            # Change Warning to Info - Fallback is acceptable
            self.logger.info("ModlistHandler did not set compat_data_path. Attempting manual lookup via PathHandler.") 
            # Ensure path_handler is available
            if not hasattr(self, 'path_handler') or not self.path_handler:
                 self.logger.critical("PathHandler not initialized in InstallWabbajackHandler!")
                 print(f"{COLOR_ERROR}Internal Error: Path handler not available for verification.{COLOR_RESET}")
                 return False
                 
            self.compatdata_path = self.path_handler.find_compat_data(self.final_appid)
            if self.compatdata_path:
                self.logger.info(f"Manually found compatdata path via PathHandler: {self.compatdata_path}")
            else:
                self.logger.error("Verification checks passed, but COULD NOT FIND compatdata path via ModlistHandler or PathHandler.")
                print(f"{COLOR_ERROR}\nVerification Error: Basic checks passed, but failed to locate the compatdata directory for AppID {self.final_appid}.{COLOR_RESET}")
                print(f"{COLOR_INFO}This is unexpected. Check Steam filesystem structure and logs.{COLOR_RESET}")
                return False # CRITICAL: Return False if path is unobtainable

        # If we get here, verification passed AND we have the compatdata_path
        self.logger.info("Manual steps verification successful (including path confirmation).")
        logger.info(f"Verification successful! (AppID: {self.final_appid}, Path: {self.compatdata_path})")
        return True

    def _download_webview_installer(self) -> bool:
        """
        Downloads the specific WebView2 installer needed by Wabbajack.
        Checks existence first.

        Returns:
            bool: True on success or if file already exists correctly, False otherwise.
        """
        if not self.install_path:
            self.logger.error("Cannot download WebView installer: install_path is not set.")
            return False

        url = "https://node10.sokloud.com/filebrowser/api/public/dl/yqVTbUT8/rwatch/WebView/MicrosoftEdgeWebView2RuntimeInstallerX64-WabbajackProton.exe"
        file_name = "MicrosoftEdgeWebView2RuntimeInstallerX64-WabbajackProton.exe"
        destination = self.install_path / file_name

        self.logger.info(f"Checking WebView installer: {destination}")
        # print(f"\nChecking required WebView installer ({file_name})...") # Replaced by logger

        if destination.is_file():
            self.logger.info(f"WebView installer {destination.name} already exists. Skipping download.")
            # Consider adding a message here if verbose/debug?
            return True
            
        # File doesn't exist, attempt download
        self.logger.info(f"WebView installer not found locally. Downloading {file_name}...")
        # Update status before starting download - Use a more user-friendly message
        show_status("Downloading WebView Installer") 
        
        if self._download_file(url, destination):
            # Status will be cleared by caller or next step
            return True
        else:
            self.logger.error(f"Failed to download WebView installer from {url}.")
            # Error message already printed by _download_file
            return False

    def _set_prefix_renderer(self, renderer: str = 'vulkan') -> bool:
        """Sets the prefix renderer using protontricks."""
        if not self.final_appid:
            self.logger.error("Cannot set renderer: final_appid not set.")
            return False
            
        self.logger.info(f"Setting prefix renderer to {renderer} for AppID {self.final_appid}...")
        try:
            # Ensure the ProtontricksHandler instance exists
            if not hasattr(self, 'protontricks_handler') or not self.protontricks_handler:
                 self.logger.critical("ProtontricksHandler not initialized in InstallWabbajackHandler!")
                 print(f"{COLOR_ERROR}Internal Error: Protontricks handler not available.{COLOR_RESET}")
                 return False
                 
            result = self.protontricks_handler.run_protontricks(
                self.final_appid, 
                'settings', 
                f'renderer={renderer}'
            )
            if result and result.returncode == 0:
                self.logger.info(f"Successfully set renderer to {renderer}.")
                return True
            else:
                err_msg = result.stderr if result else "Command execution failed"
                self.logger.error(f"Failed to set renderer to {renderer}. Error: {err_msg}")
                print(f"{COLOR_ERROR}Error: Failed to set prefix renderer to {renderer}.{COLOR_RESET}")
                return False
        except Exception as e:
            self.logger.error(f"Exception setting renderer: {e}", exc_info=True)
            print(f"{COLOR_ERROR}Error setting prefix renderer: {e}.{COLOR_RESET}")
            return False

    def _download_and_replace_reg_file(self, url: str, target_reg_path: Path) -> bool:
        """Downloads a .reg file and replaces the target file.
           Always downloads and overwrites.
        """
        self.logger.info(f"Downloading registry file from {url} to replace {target_reg_path}")
        
        # Always download and replace for registry files
        if self._download_file(url, target_reg_path):
            self.logger.info(f"Successfully downloaded and replaced {target_reg_path}")
            return True
        else:
            self.logger.error(f"Failed to download/replace {target_reg_path} from {url}")
            return False

# Example usage (for testing - keep this section for easy module testing)
if __name__ == '__main__':
    # Configure logging for standalone testing
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    print("Testing Wabbajack Install Handler...")
    # Simulate running on or off deck
    test_on_deck = False
    print(f"Simulating run with steamdeck={test_on_deck}")

    # Need dummy handlers for direct testing
    class DummyProton:
        which_protontricks = 'native'
        def check_and_setup_protontricks(self): return True
        def set_protontricks_permissions(self, path, steamdeck): return True
        def enable_dotfiles(self, appid): return True
        def _cleanup_wine_processes(self): pass
        def run_protontricks(self, *args, **kwargs): return subprocess.CompletedProcess(args=[], returncode=0)
        def list_non_steam_shortcuts(self): return {"Wabbajack": "12345"}

    class DummyShortcut:
        def create_shortcut(self, *args, **kwargs): return True, "12345"
        def secure_steam_restart(self): return True
        
    class DummyPath:
        def find_compat_data(self, appid): return Path(f"/tmp/jackify_test/compatdata/{appid}")
        def find_steam_library(self): return Path("/tmp/jackify_test/steam/steamapps/common")
        
    class DummyVDF:
        @staticmethod
        def load(path):
            if "config.vdf" in str(path):
                 # Simulate structure needed for proton check
                 return {'UserLocalConfigStore': {'Software': {'Valve': {'Steam': {'apps': {'12345': {'CompatTool': 'proton_experimental'}}}}}}}
            return {}

    handler = InstallWabbajackHandler(
        steamdeck=test_on_deck, 
        protontricks_handler=DummyProton(), 
        shortcut_handler=DummyShortcut(),
        path_handler=DummyPath(),
        vdf_handler=DummyVDF(),
        modlist_handler=ModlistHandler(),
        filesystem_handler=FileSystemHandler()
    )
    # Pre-create dummy compatdata dir for verification step
    if not Path("/tmp/jackify_test/compatdata/12345/pfx").exists():
        os.makedirs("/tmp/jackify_test/compatdata/12345/pfx", exist_ok=True)
        
    handler.run_install_workflow()

    print("\nTesting completed.") 