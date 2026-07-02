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

# Import UI Colors first - these should always be available
from jackify.shared.colors import COLOR_PROMPT, COLOR_RESET, COLOR_INFO, COLOR_ERROR, COLOR_WARNING

# Import necessary components from other modules
try:
    from .path_handler import PathHandler
    from .protontricks_handler import ProtontricksHandler
    from .shortcut_handler import ShortcutHandler
    from .vdf_handler import VDFHandler
    from .modlist_handler import ModlistHandler
    from .filesystem_handler import FileSystemHandler
    from .menu_handler import MenuHandler
    from .status_utils import show_status, clear_status
    from jackify.shared.ui_utils import print_section_header
except ImportError as e:
    logging.error(f"Import error in InstallWabbajackHandler: {e}")
    logging.error("Could not import required handlers. Ensure structure is correct.")

# Default locations
WABBAJACK_DEFAULT_DIR = os.path.expanduser("~/.config/Jackify/Wabbajack")

# Initialize logger for the module
logger = logging.getLogger(__name__)

from .wabbajack_webview import WabbajackWebViewMixin
from .wabbajack_steam_integration import WabbajackSteamIntegrationMixin
from .wabbajack_prefix_setup import WabbajackPrefixSetupMixin
from .wabbajack_verification import WabbajackVerificationMixin
from .wabbajack_directory import WabbajackDirectoryMixin


class InstallWabbajackHandler(
    WabbajackWebViewMixin,
    WabbajackSteamIntegrationMixin,
    WabbajackPrefixSetupMixin,
    WabbajackVerificationMixin,
    WabbajackDirectoryMixin,
):
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

    def run_install_workflow(self, context: dict = None) -> bool:
        """
        Main entry point for the Wabbajack installation workflow.
        """
        os.system('cls' if os.name == 'nt' else 'clear')
                    # Banner display handled by frontend
        print_section_header('Wabbajack Installation')
        # Standard logging (no file handler) - LoggingHandler calls removed

        self.logger.info("Starting Wabbajack installation workflow...")
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
            self.logger.warning("Could not determine initial AppID after shortcut creation.")
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
                    self.logger.warning("Could not determine AppID after Steam restart.")
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
            print(f"\n{COLOR_WARNING}Warning: Could not set Flatpak permissions automatically.{COLOR_RESET}")

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
            self.logger.error(f"Failed to download or apply initial Win7 system.reg. {e}")
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
            self.logger.error("WebView installation failed via protontricks-launch.")
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
            self.logger.error(f"Failed to download or apply final user.reg/system.reg. {e}")
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

    def _display_completion_message(self):
        """Displays the final success message and next steps."""
        from jackify.shared.paths import get_jackify_logs_dir
        log_path = get_jackify_logs_dir() / "jackify-cli.log"

        print("\n───────────────────────────────────────────────────────────────────")
        print(f"{COLOR_INFO}Wabbajack Installation Completed Successfully!{COLOR_RESET}")
        print("───────────────────────────────────────────────────────────────────")
        print("Next Steps:")
        print(f"  • Launch '{COLOR_INFO}{self.shortcut_name or 'Wabbajack'}{COLOR_RESET}' through Steam.")
        print(f"  • When Wabbajack opens, log in to Nexus using the Settings button (cog icon).")
        print(f"  • Once logged in, you can browse and install modlists as usual!")

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

