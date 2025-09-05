#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Protontricks Handler Module
Handles detection and operation of Protontricks
"""

import os
import re
import subprocess
from pathlib import Path
import shutil
import logging
from typing import Dict, Optional, List
import sys

# Initialize logger
logger = logging.getLogger(__name__)


class ProtontricksHandler:
    """
    Handles operations related to Protontricks detection and usage
    """
    
    def __init__(self, steamdeck: bool, logger=None):
        self.logger = logger or logging.getLogger(__name__)
        self.which_protontricks = None  # 'flatpak' or 'native'
        self.protontricks_version = None
        self.protontricks_path = None
        self.steamdeck = steamdeck # Store steamdeck status
    
    def _get_clean_subprocess_env(self):
        """
        Create a clean environment for subprocess calls by removing PyInstaller-specific
        environment variables that can interfere with external program execution.
        
        Returns:
            dict: Cleaned environment dictionary
        """
        env = os.environ.copy()
        
        # Remove PyInstaller-specific environment variables
        env.pop('_MEIPASS', None)
        env.pop('_MEIPASS2', None)
        
        # Clean library path variables that PyInstaller modifies (Linux/Unix)
        if 'LD_LIBRARY_PATH_ORIG' in env:
            # Restore original LD_LIBRARY_PATH if it was backed up by PyInstaller
            env['LD_LIBRARY_PATH'] = env['LD_LIBRARY_PATH_ORIG']
        else:
            # Remove PyInstaller-modified LD_LIBRARY_PATH
            env.pop('LD_LIBRARY_PATH', None)
        
        # Clean PATH of PyInstaller-specific entries
        if 'PATH' in env and hasattr(sys, '_MEIPASS'):
            path_entries = env['PATH'].split(os.pathsep)
            # Remove any PATH entries that point to PyInstaller temp directory
            cleaned_path = [p for p in path_entries if not p.startswith(sys._MEIPASS)]
            env['PATH'] = os.pathsep.join(cleaned_path)
        
        # Clean macOS library path (if present)
        if 'DYLD_LIBRARY_PATH' in env and hasattr(sys, '_MEIPASS'):
            dyld_entries = env['DYLD_LIBRARY_PATH'].split(os.pathsep)
            cleaned_dyld = [p for p in dyld_entries if not p.startswith(sys._MEIPASS)]
            if cleaned_dyld:
                env['DYLD_LIBRARY_PATH'] = os.pathsep.join(cleaned_dyld)
            else:
                env.pop('DYLD_LIBRARY_PATH', None)
        
        return env
    
    def detect_protontricks(self):
        """
        Detect if protontricks is installed and whether it's flatpak or native.
        If not found, prompts the user to install the Flatpak version.

        Returns True if protontricks is found or successfully installed, False otherwise
        """
        logger.debug("Detecting if protontricks is installed...")
        
        # Check if protontricks exists as a command
        protontricks_path_which = shutil.which("protontricks")
        self.flatpak_path = shutil.which("flatpak")  # Store for later use
        
        if protontricks_path_which:
            # Check if it's a flatpak wrapper
            try:
                with open(protontricks_path_which, 'r') as f:
                    content = f.read()
                    if "flatpak run" in content:
                        logger.debug(f"Detected Protontricks is a Flatpak wrapper at {protontricks_path_which}")
                        self.which_protontricks = 'flatpak'
                        # Continue to check flatpak list just to be sure
                    else:
                        logger.info(f"Native Protontricks found at {protontricks_path_which}")
                        self.which_protontricks = 'native'
                        self.protontricks_path = protontricks_path_which
                        return True
            except Exception as e:
                logger.error(f"Error reading protontricks executable: {e}")
        
        # Check if flatpak protontricks is installed (or if wrapper check indicated flatpak)
        flatpak_installed = False
        try:
            # PyInstaller fix: Comprehensive environment cleaning for subprocess calls
            env = self._get_clean_subprocess_env()
            
            result = subprocess.run(
                ["flatpak", "list"], 
                capture_output=True, 
                text=True,
                check=True,
                env=env  # Use comprehensively cleaned environment
            )
            if "com.github.Matoking.protontricks" in result.stdout:
                logger.info("Flatpak Protontricks is installed")
                self.which_protontricks = 'flatpak'
                flatpak_installed = True
                return True
        except FileNotFoundError:
             logger.warning("'flatpak' command not found. Cannot check for Flatpak Protontricks.")
        except subprocess.CalledProcessError as e:
            logger.warning(f"Error checking flatpak list: {e}")
        except Exception as e:
            logger.error(f"Unexpected error checking flatpak: {e}")

        # If neither native nor flatpak found, prompt for installation
        if not self.which_protontricks:
            logger.warning("Protontricks not found (native or flatpak).")
            
            should_install = False
            if self.steamdeck:
                logger.info("Running on Steam Deck, attempting automatic Flatpak installation.")
                # Maybe add a brief pause or message?
                print("Protontricks not found. Attempting automatic installation via Flatpak...")
                should_install = True
            else:
                try:
                    response = input("Protontricks not found. Install the Flatpak version? (Y/n): ").lower()
                    if response == 'y' or response == '':
                        should_install = True
                except KeyboardInterrupt:
                     print("\nInstallation cancelled.")
                     return False
            
            if should_install:
                try:
                    logger.info("Attempting to install Flatpak Protontricks...")
                    # Use --noninteractive for automatic install where applicable
                    install_cmd = ["flatpak", "install", "-u", "-y", "--noninteractive", "flathub", "com.github.Matoking.protontricks"]
                    
                    # PyInstaller fix: Comprehensive environment cleaning for subprocess calls
                    env = self._get_clean_subprocess_env()
                    
                    # Run with output visible to user
                    process = subprocess.run(install_cmd, check=True, text=True, env=env)
                    logger.info("Flatpak Protontricks installation successful.")
                    print("Flatpak Protontricks installed successfully.")
                    self.which_protontricks = 'flatpak'
                    return True
                except FileNotFoundError:
                    logger.error("'flatpak' command not found. Cannot install.")
                    print("Error: 'flatpak' command not found. Please install Flatpak first.")
                    return False
                except subprocess.CalledProcessError as e:
                    logger.error(f"Flatpak installation failed: {e}")
                    print(f"Error: Flatpak installation failed (Command: {' '.join(e.cmd)}). Please try installing manually.")
                    return False
                except Exception as e:
                    logger.error(f"Unexpected error during Flatpak installation: {e}")
                    print("An unexpected error occurred during installation.")
                    return False
            else:
                logger.error("User chose not to install Protontricks or installation skipped.")
                print("Protontricks installation skipped. Cannot continue without Protontricks.")
                return False
                
        # Should not reach here if logic is correct, but acts as a fallback
        logger.error("Protontricks detection failed unexpectedly.")
        return False
    
    def check_protontricks_version(self):
        """
        Check if the protontricks version is sufficient
        Returns True if version is sufficient, False otherwise
        """
        try:
            if self.which_protontricks == 'flatpak':
                cmd = ["flatpak", "run", "com.github.Matoking.protontricks", "-V"]
            else:
                cmd = ["protontricks", "-V"]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            version_str = result.stdout.split(' ')[1].strip('()')
            
            # Clean version string
            cleaned_version = re.sub(r'[^0-9.]', '', version_str)
            self.protontricks_version = cleaned_version
            
            # Parse version components
            version_parts = cleaned_version.split('.')
            if len(version_parts) >= 2:
                major, minor = int(version_parts[0]), int(version_parts[1])
                if major < 1 or (major == 1 and minor < 12):
                    logger.error(f"Protontricks version {cleaned_version} is too old. Version 1.12.0 or newer is required.")
                    return False
                return True
            else:
                logger.error(f"Could not parse protontricks version: {cleaned_version}")
                return False
                
        except Exception as e:
            logger.error(f"Error checking protontricks version: {e}")
            return False
    
    def run_protontricks(self, *args, **kwargs):
        """
        Run protontricks with the given arguments and keyword arguments.
        kwargs are passed directly to subprocess.run (e.g., stderr=subprocess.DEVNULL).
        Use stdout=subprocess.PIPE, stderr=subprocess.PIPE/DEVNULL instead of capture_output=True.
        Returns subprocess.CompletedProcess object
        """
        # Ensure protontricks is detected first
        if self.which_protontricks is None:
            if not self.detect_protontricks():
                logger.error("Could not detect protontricks installation")
                return None

        if self.which_protontricks == 'flatpak':
            cmd = ["flatpak", "run", "com.github.Matoking.protontricks"]
        else:
            cmd = ["protontricks"]
        
        cmd.extend(args)
        
        # Default to capturing stdout/stderr unless specified otherwise in kwargs
        run_kwargs = {
            'stdout': subprocess.PIPE,
            'stderr': subprocess.PIPE,
            'text': True,
            **kwargs # Allow overriding defaults (like stderr=DEVNULL)
        }
        # PyInstaller fix: Use cleaned environment for all protontricks calls
        env = self._get_clean_subprocess_env()
        # Suppress Wine debug output
        env['WINEDEBUG'] = '-all'
        run_kwargs['env'] = env
        try:
            return subprocess.run(cmd, **run_kwargs)
        except Exception as e:
            logger.error(f"Error running protontricks: {e}")
            # Consider returning a mock CompletedProcess with an error code?
            return None
    
    def set_protontricks_permissions(self, modlist_dir, steamdeck=False):
        """
        Set permissions for Protontricks to access the modlist directory
        Returns True on success, False on failure
        """
        if self.which_protontricks != 'flatpak':
            logger.debug("Using Native protontricks, skip setting permissions")
            return True
        
        logger.info("Setting Protontricks permissions...")
        try:
            # PyInstaller fix: Use cleaned environment
            env = self._get_clean_subprocess_env()
            
            subprocess.run(["flatpak", "override", "--user", "com.github.Matoking.protontricks", 
                           f"--filesystem={modlist_dir}"], check=True, env=env)
            
            if steamdeck:
                logger.warn("Checking for SDCard and setting permissions appropriately...")
                # Find sdcard path
                result = subprocess.run(["df", "-h"], capture_output=True, text=True, env=env)
                for line in result.stdout.splitlines():
                    if "/run/media" in line:
                        sdcard_path = line.split()[-1]
                        logger.debug(f"SDCard path: {sdcard_path}")
                        subprocess.run(["flatpak", "override", "--user", f"--filesystem={sdcard_path}", 
                                      "com.github.Matoking.protontricks"], check=True, env=env)
                # Add standard Steam Deck SD card path as fallback
                subprocess.run(["flatpak", "override", "--user", "--filesystem=/run/media/mmcblk0p1", 
                              "com.github.Matoking.protontricks"], check=True, env=env)
            logger.debug("Permissions set successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to set Protontricks permissions: {e}")
            return False
    
    def create_protontricks_alias(self):
        """
        Create aliases for protontricks in ~/.bashrc if using flatpak
        Returns True if created or already exists, False on failure
        """
        if self.which_protontricks != 'flatpak':
            logger.debug("Not using flatpak, skipping alias creation")
            return True
        
        try:
            bashrc_path = os.path.expanduser("~/.bashrc")
            
            # Check if file exists and read content
            if os.path.exists(bashrc_path):
                with open(bashrc_path, 'r') as f:
                    content = f.read()
                
                # Check if aliases already exist
                protontricks_alias_exists = "alias protontricks=" in content
                launch_alias_exists = "alias protontricks-launch" in content
                
                # Add missing aliases
                with open(bashrc_path, 'a') as f:
                    if not protontricks_alias_exists:
                        logger.info("Adding protontricks alias to ~/.bashrc")
                        f.write("\nalias protontricks='flatpak run com.github.Matoking.protontricks'\n")
                    
                    if not launch_alias_exists:
                        logger.info("Adding protontricks-launch alias to ~/.bashrc")
                        f.write("\nalias protontricks-launch='flatpak run --command=protontricks-launch com.github.Matoking.protontricks'\n")
                
                return True
            else:
                logger.error("~/.bashrc not found, skipping alias creation")
                return False
                
        except Exception as e:
            logger.error(f"Failed to create protontricks aliases: {e}")
            return False
    
    # def get_modlists(self): # Keep commented out or remove old method
    #     """
    #     Get a list of Skyrim, Fallout, Oblivion modlists from Steam via protontricks
    #     Returns a list of modlist names
    #     """
        # ... (old implementation with filtering) ...
    
    # Renamed from list_non_steam_games for clarity and purpose
    def list_non_steam_shortcuts(self) -> Dict[str, str]:
        """List ALL non-Steam shortcuts recognized by Protontricks.

        Runs 'protontricks -l' and parses the output for lines matching
        "Non-Steam shortcut: [Name] ([AppID])".

        Returns:
            A dictionary mapping the shortcut name (AppName) to its AppID.
            Returns an empty dictionary if none are found or an error occurs.
        """
        logger.info("Listing ALL non-Steam shortcuts via protontricks...")
        non_steam_shortcuts = {}
        # --- Ensure protontricks is detected before proceeding ---
        if not self.which_protontricks:
            self.logger.info("Protontricks type/path not yet determined. Running detection...")
            if not self.detect_protontricks():
                self.logger.error("Protontricks detection failed. Cannot list shortcuts.")
                return {}
            self.logger.info(f"Protontricks detection successful: {self.which_protontricks}")
        # --- End detection check ---
        try:
            cmd = [] # Initialize cmd list
            if self.which_protontricks == 'flatpak':
                cmd = ["flatpak", "run", "com.github.Matoking.protontricks", "-l"]
            elif self.protontricks_path:
                cmd = [self.protontricks_path, "-l"]
            else:
                logger.error("Protontricks path not determined, cannot list shortcuts.")
                return {}
            self.logger.debug(f"Running command: {' '.join(cmd)}")
            # PyInstaller fix: Use cleaned environment
            env = self._get_clean_subprocess_env()
            result = subprocess.run(cmd, capture_output=True, text=True, check=True, encoding='utf-8', errors='ignore', env=env)
            # Regex to capture name and AppID
            pattern = re.compile(r"Non-Steam shortcut:\s+(.+)\s+\((\d+)\)")
            for line in result.stdout.splitlines():
                line = line.strip()
                match = pattern.match(line)
                if match:
                    app_name = match.group(1).strip() # Get the name
                    app_id = match.group(2).strip()   # Get the AppID
                    non_steam_shortcuts[app_name] = app_id
                    logger.debug(f"Found non-Steam shortcut: '{app_name}' with AppID {app_id}")
            if not non_steam_shortcuts:
                logger.warning("No non-Steam shortcuts found in protontricks output.")
        except FileNotFoundError:
             logger.error(f"Protontricks command not found. Path: {cmd[0] if cmd else 'N/A'}")
             return {}
        except subprocess.CalledProcessError as e:
            # Log error but don't necessarily stop; might have partial output
            logger.error(f"Error running protontricks -l (Exit code: {e.returncode}): {e}")
            logger.error(f"Stderr (truncated): {e.stderr[:500] if e.stderr else ''}")
            # Return what we have, might be useful
        except Exception as e:
            logger.error(f"Unexpected error listing non-Steam shortcuts: {e}", exc_info=True)
            return {}
        return non_steam_shortcuts
    
    def enable_dotfiles(self, appid):
        """
        Enable visibility of (.)dot files in the Wine prefix
        Returns True on success, False on failure
        
        Args:
            appid (str): The app ID to use
        
        Returns:
            bool: True on success, False on failure
        """
        logger.debug(f"APPID={appid}")
        logger.info("Enabling visibility of (.)dot files...")
        
        try:
            # Check current setting
            result = self.run_protontricks(
                "-c", "WINEDEBUG=-all wine reg query \"HKEY_CURRENT_USER\\Software\\Wine\" /v ShowDotFiles", 
                appid,
                stderr=subprocess.DEVNULL # Suppress stderr for this query
            )
            
            # Check if the initial query command ran successfully and contained expected output
            if result and result.returncode == 0 and "ShowDotFiles" in result.stdout and "Y" in result.stdout:
                logger.info("DotFiles already enabled via registry... skipping")
                return True
            elif result and result.returncode != 0:
                # Log as info/debug since non-zero exit is expected if key doesn't exist
                logger.info(f"Initial query for ShowDotFiles likely failed because the key doesn't exist yet (Exit Code: {result.returncode}). Proceeding to set it. Stderr: {result.stderr}") 
            elif not result:
                 logger.error("Failed to execute initial dotfile query command.")
                 # Proceed cautiously

            # --- Try to set the value --- 
            dotfiles_set_success = False

            # Method 1: Set registry key (Primary Method)
            logger.debug("Attempting to set ShowDotFiles registry key...")
            result_add = self.run_protontricks(
                "-c", "WINEDEBUG=-all wine reg add \"HKEY_CURRENT_USER\\Software\\Wine\" /v ShowDotFiles /d Y /f", 
                appid,
                # Keep stderr for this one to log potential errors from reg add
                # stderr=subprocess.DEVNULL 
            )
            if result_add and result_add.returncode == 0:
                 logger.info("'wine reg add' command executed successfully.")
                 dotfiles_set_success = True # Tentative success
            elif result_add:
                 logger.warning(f"'wine reg add' command failed (Exit Code: {result_add.returncode}). Stderr: {result_add.stderr}")
            else:
                 logger.error("Failed to execute 'wine reg add' command.")

            # Method 2: Create user.reg entry (Backup Method)
            # This is useful if registry commands fail but direct file access works
            logger.debug("Ensuring user.reg has correct entry...")
            prefix_path = self.get_wine_prefix_path(appid) 
            if prefix_path:
                user_reg_path = Path(prefix_path) / "user.reg" 
                try:
                    if user_reg_path.exists():
                        content = user_reg_path.read_text(encoding='utf-8', errors='ignore')
                        if "ShowDotFiles" not in content:
                            logger.debug(f"Adding ShowDotFiles entry to {user_reg_path}")
                            with open(user_reg_path, 'a', encoding='utf-8') as f:
                                f.write('\n[Software\\Wine] 1603891765\n') 
                                f.write('"ShowDotFiles"="Y"\n')
                            dotfiles_set_success = True # Count file write as success too
                        else:
                             logger.debug("ShowDotFiles already present in user.reg")
                             dotfiles_set_success = True # Already there counts as success
                    else:
                        logger.warning(f"user.reg not found at {user_reg_path}, creating it.")
                        with open(user_reg_path, 'w', encoding='utf-8') as f:
                             f.write('[Software\\Wine] 1603891765\n') 
                             f.write('"ShowDotFiles"="Y"\n')
                        dotfiles_set_success = True # Creating file counts as success
                except Exception as e:
                    logger.warning(f"Error reading/writing user.reg: {e}")
            else:
                logger.warning("Could not get WINEPREFIX path, skipping user.reg modification.")
            
            # --- Verification Step --- 
            logger.debug("Verifying dotfile setting after attempts...")
            verify_result = self.run_protontricks( 
                "-c", "WINEDEBUG=-all wine reg query \"HKEY_CURRENT_USER\\Software\\Wine\" /v ShowDotFiles", 
                appid,
                stderr=subprocess.DEVNULL # Suppress stderr for verification query
            )
            
            query_verified = False
            if verify_result and verify_result.returncode == 0 and "ShowDotFiles" in verify_result.stdout and "Y" in verify_result.stdout:
                 logger.debug("Verification query successful and key is set.")
                 query_verified = True
            elif verify_result:
                 # Change Warning to Info - verification failing right after setting is common
                 logger.info(f"Verification query failed or key not found (Exit Code: {verify_result.returncode}). Stderr: {verify_result.stderr}") 
            else:
                 logger.error("Failed to execute verification query command.")

            # --- Final Decision --- 
            if dotfiles_set_success:
                 # If the add command or file write succeeded, we report overall success,
                 # even if the verification query failed, but log the query status.
                 if query_verified:
                      logger.info("Dotfiles enabled and verified successfully!")
                 else:
                      # Change Warning to Info - verification failing right after setting is common
                      logger.info("Dotfiles potentially enabled (reg add/user.reg succeeded), but verification query failed.") 
                 return True # Report success based on the setting action
            else:
                 # If both the reg add and user.reg steps failed
                 logger.error("Failed to enable dotfiles using registry and user.reg methods.")
                 return False
                
        except Exception as e:
            logger.error(f"Unexpected error enabling dotfiles: {e}", exc_info=True) 
            return False
    
    def set_win10_prefix(self, appid):
        """
        Set Windows 10 version in the proton prefix
        Returns True on success, False on failure
        """
        try:
            # PyInstaller fix: Use cleaned environment
            env = self._get_clean_subprocess_env()
            env["WINEDEBUG"] = "-all"
            
            if self.which_protontricks == 'flatpak':
                cmd = ["flatpak", "run", "com.github.Matoking.protontricks", "--no-bwrap", appid, "win10"]
            else:
                cmd = ["protontricks", "--no-bwrap", appid, "win10"]
            
            subprocess.run(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception as e:
            logger.error(f"Error setting Windows 10 prefix: {e}")
            return False
    
    def protontricks_alias(self):
        """
        Create protontricks alias in ~/.bashrc
        """
        logger.info("Creating protontricks alias in ~/.bashrc...")
        
        try:
            if self.which_protontricks == 'flatpak':
                # Check if aliases already exist
                bashrc_path = os.path.expanduser("~/.bashrc")
                protontricks_alias_exists = False
                launch_alias_exists = False
                
                if os.path.exists(bashrc_path):
                    with open(bashrc_path, 'r') as f:
                        content = f.read()
                        protontricks_alias_exists = "alias protontricks='flatpak run com.github.Matoking.protontricks'" in content
                        launch_alias_exists = "alias protontricks-launch='flatpak run --command=protontricks-launch com.github.Matoking.protontricks'" in content
                
                # Add aliases if they don't exist
                with open(bashrc_path, 'a') as f:
                    if not protontricks_alias_exists:
                        f.write("\n# Jackify: Protontricks alias\n")
                        f.write("alias protontricks='flatpak run com.github.Matoking.protontricks'\n")
                        logger.debug("Added protontricks alias to ~/.bashrc")
                    
                    if not launch_alias_exists:
                        f.write("\n# Jackify: Protontricks-launch alias\n")
                        f.write("alias protontricks-launch='flatpak run --command=protontricks-launch com.github.Matoking.protontricks'\n")
                        logger.debug("Added protontricks-launch alias to ~/.bashrc")
                
                logger.info("Protontricks aliases created successfully")
                return True
            else:
                logger.info("Protontricks is not installed via flatpak, skipping alias creation")
                return True
        except Exception as e:
            logger.error(f"Error creating protontricks alias: {e}")
            return False
    
    def get_wine_prefix_path(self, appid) -> Optional[str]:
        """Gets the WINEPREFIX path for a given AppID.

        Args:
            appid (str): The Steam AppID.

        Returns:
            The WINEPREFIX path as a string, or None if detection fails.
        """
        logger.debug(f"Getting WINEPREFIX for AppID {appid}")
        result = self.run_protontricks("-c", "echo $WINEPREFIX", appid)
        if result and result.returncode == 0 and result.stdout.strip():
            prefix_path = result.stdout.strip()
            logger.debug(f"Detected WINEPREFIX: {prefix_path}")
            return prefix_path
        else:
            logger.error(f"Failed to get WINEPREFIX for AppID {appid}. Stderr: {result.stderr if result else 'N/A'}")
            return None
    
    def run_protontricks_launch(self, appid, installer_path, *extra_args):
        """
        Run protontricks-launch (for WebView or similar installers) using the correct method for flatpak or native.
        Returns subprocess.CompletedProcess object.
        """
        if self.which_protontricks is None:
            if not self.detect_protontricks():
                self.logger.error("Could not detect protontricks installation")
                return None
        if self.which_protontricks == 'flatpak':
            cmd = ["flatpak", "run", "--command=protontricks-launch", "com.github.Matoking.protontricks", "--appid", appid, str(installer_path)]
        else:
            launch_path = shutil.which("protontricks-launch")
            if not launch_path:
                self.logger.error("protontricks-launch command not found in PATH.")
                return None
            cmd = [launch_path, "--appid", appid, str(installer_path)]
        if extra_args:
            cmd.extend(extra_args)
        self.logger.debug(f"Running protontricks-launch: {' '.join(map(str, cmd))}")
        try:
            # PyInstaller fix: Use cleaned environment
            env = self._get_clean_subprocess_env()
            return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        except Exception as e:
            self.logger.error(f"Error running protontricks-launch: {e}")
            return None
    
    def install_wine_components(self, appid, game_var, specific_components: Optional[List[str]] = None):
        """
        Install the specified Wine components into the given prefix using protontricks.
        If specific_components is None, use the default set (fontsmooth=rgb, xact, xact_x64, vcrun2022).
        """
        env = self._get_clean_subprocess_env()
        env["WINEDEBUG"] = "-all"
        if specific_components is not None:
            components_to_install = specific_components
            self.logger.info(f"Installing specific components: {components_to_install}")
        else:
            components_to_install = ["fontsmooth=rgb", "xact", "xact_x64", "vcrun2022"]
            self.logger.info(f"Installing default components: {components_to_install}")
        if not components_to_install:
            self.logger.info("No Wine components to install.")
            return True
        self.logger.info(f"AppID: {appid}, Game: {game_var}, Components: {components_to_install}")
        # print(f"\n[Jackify] Installing Wine components for AppID {appid} ({game_var}):\n  {', '.join(components_to_install)}\n")  # Suppressed per user request
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            if attempt > 1:
                self.logger.warning(f"Retrying component installation (attempt {attempt}/{max_attempts})...")
                self._cleanup_wine_processes()
            try:
                result = self.run_protontricks("--no-bwrap", appid, "-q", *components_to_install, env=env, timeout=600)
                self.logger.debug(f"Protontricks output: {result.stdout if result else ''}")
                if result and result.returncode == 0:
                    self.logger.info("Wine Component installation command completed successfully.")
                    return True
                else:
                    self.logger.error(f"Protontricks command failed (Attempt {attempt}/{max_attempts}). Return Code: {result.returncode if result else 'N/A'}")
                    self.logger.error(f"Stdout: {result.stdout.strip() if result else ''}")
                    self.logger.error(f"Stderr: {result.stderr.strip() if result else ''}")
            except Exception as e:
                self.logger.error(f"Error during protontricks run (Attempt {attempt}/{max_attempts}): {e}", exc_info=True)
        self.logger.error(f"Failed to install Wine components after {max_attempts} attempts.")
        return False
    
    def _cleanup_wine_processes(self):
        """
        Internal method to clean up wine processes during component installation
        """
        try:
            subprocess.run("pgrep -f 'win7|win10|ShowDotFiles|protontricks' | xargs -r kill -9", 
                          shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run("pkill -9 winetricks", 
                          shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            logger.error(f"Error cleaning up wine processes: {e}") 
    
    def check_and_setup_protontricks(self) -> bool:
        """
        Runs all necessary checks and setup steps for Protontricks.
        - Detects (and prompts for install if missing)
        - Checks version
        - Creates aliases if using Flatpak

        Returns:
            bool: True if Protontricks is ready to use, False otherwise.
        """
        logger.info("Checking and setting up Protontricks...")

        logger.info("Checking Protontricks installation...")
        if not self.detect_protontricks():
            # Error message already printed by detect_protontricks if install fails/skipped
            return False
        logger.info(f"Protontricks detected: {self.which_protontricks}")

        logger.info("Checking Protontricks version...")
        if not self.check_protontricks_version():
            # Error message already printed by check_protontricks_version
            print(f"Error: Protontricks version {self.protontricks_version} is too old or could not be checked.")
            return False
        logger.info(f"Protontricks version {self.protontricks_version} is sufficient.")

        # Aliases are non-critical, log warning if creation fails
        if self.which_protontricks == 'flatpak':
            logger.info("Ensuring Flatpak aliases exist in ~/.bashrc...")
            if not self.protontricks_alias():
                # Logged by protontricks_alias, maybe add print?
                print("Warning: Failed to create/verify protontricks aliases in ~/.bashrc")
                # Don't necessarily fail the whole setup for this

        logger.info("Protontricks check and setup completed successfully.")
        return True 