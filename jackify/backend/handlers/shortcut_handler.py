#!/usr/bin/env python3
import os
import random
import subprocess
import logging
import readline  # For tab completion
import time
import glob
from pathlib import Path
import vdf
from typing import Optional, List, Dict, Callable, Tuple
import re
import shutil

# Import other necessary modules
from .protontricks_handler import ProtontricksHandler
from .vdf_handler import VDFHandler # Changed to relative import
from .path_handler import PathHandler # Added PathHandler import
from .completers import path_completer

# Get logger for the module
logger = logging.getLogger(__name__)

class ShortcutHandler:
    """Handles creation and management of Steam shortcuts"""
    
    def __init__(self, steamdeck: bool, verbose: bool = False):
        """
        Initialize the ShortcutHandler.

        Args:
            steamdeck (bool): True if running on Steam Deck, False otherwise.
            verbose (bool): Controls verbose output for methods like secure_steam_restart.
        """
        self.logger = logging.getLogger(__name__)
        self.vdf_handler = VDFHandler()
        self.steamdeck = steamdeck
        self.verbose = verbose # Store verbose flag
        self.path_handler = PathHandler() # Add PathHandler instance
        self.shortcuts_path = self.path_handler._find_shortcuts_vdf() # Use PathHandler method
        self._last_shortcuts_backup = None # Track the last backup path
        self._safe_shortcuts_backup = None # Track backup made just before restart
        # Initialize ProtontricksHandler here, passing steamdeck status
        self.protontricks_handler = ProtontricksHandler(steamdeck=self.steamdeck)
        
    def _enable_tab_completion(self):
        """Enable tab completion for file paths using the shared completer"""
        readline.set_completer(path_completer)
        readline.set_completer_delims(' \t\n;')
        readline.parse_and_bind("tab: complete")
        
    def _get_mo2_path(self):
        """
        Get the path to ModOrganizer.exe from user with tab completion
        Returns:
            tuple: (mo2_dir, mo2_path) or (None, None) if cancelled
        """
        self._enable_tab_completion()
        while True:
            try:
                path = input("\nEnter the path to ModOrganizer.exe or its containing directory: ").strip()
                if not path:
                    return None, None
                
                # Convert to absolute path
                path = os.path.expanduser(path)
                path = os.path.abspath(path)
                
                # If directory provided, look for ModOrganizer.exe
                if os.path.isdir(path):
                    mo2_path = os.path.join(path, "ModOrganizer.exe")
                else:
                    mo2_path = path
                    path = os.path.dirname(path)
                
                # Verify ModOrganizer.exe exists
                if os.path.isfile(mo2_path):
                    self.logger.debug(f"Found ModOrganizer.exe at: {mo2_path}")
                    return path, mo2_path
                else:
                    print("ModOrganizer.exe not found at specified location. Please try again.")
            except KeyboardInterrupt:
                return None, None
    
    def _get_modlist_name(self):
        """
        Get the modlist name from user
        Returns:
            str: Modlist name or None if cancelled
        """
        try:
            name = input("\nEnter a name for the modlist: ").strip()
            if not name:
                return None
            return name
        except KeyboardInterrupt:
            return None
    
    def _check_and_restore_shortcuts_vdf(self):
        """
        Check if shortcuts.vdf exists and restore from backup if missing.
        Returns:
            bool: True if file exists or was restored, False if unable to restore
        """
        # Find all shortcuts.vdf paths
        shortcuts_files = []
        for user_dir in os.listdir(self.shortcuts_path):
            shortcuts_file = os.path.join(self.shortcuts_path, user_dir, "config", "shortcuts.vdf")
            if os.path.dirname(shortcuts_file):
                shortcuts_files.append(shortcuts_file)
        
        # Check if any are missing and need restoration
        missing_files = []
        for file_path in shortcuts_files:
            if not os.path.exists(file_path):
                self.logger.warning(f"shortcuts.vdf is missing at: {file_path}")
                missing_files.append(file_path)
        
        if not missing_files:
            self.logger.debug("All shortcuts.vdf files are present")
            return True
        
        # Try to restore from backups
        restored = 0
        for file_path in missing_files:
            # Try timestamped backup first
            backup_files = sorted(glob.glob(f"{file_path}.*.bak"), reverse=True)
            if backup_files:
                try:
                    import shutil
                    shutil.copy2(backup_files[0], file_path)
                    self.logger.info(f"Restored {file_path} from {backup_files[0]}")
                    restored += 1
                    continue
                except Exception as e:
                    self.logger.error(f"Failed to restore from timestamped backup: {e}")
            
            # Try simple backup
            simple_backup = f"{file_path}.bak"
            if os.path.exists(simple_backup):
                try:
                    import shutil
                    shutil.copy2(simple_backup, file_path)
                    self.logger.info(f"Restored {file_path} from simple backup")
                    restored += 1
                    continue
                except Exception as e:
                    self.logger.error(f"Failed to restore from simple backup: {e}")
        
        if restored == len(missing_files):
            self.logger.info("Successfully restored all missing shortcuts.vdf files")
            return True
        elif restored > 0:
            self.logger.warning(f"Partially restored {restored}/{len(missing_files)} shortcuts.vdf files")
            return True
        else:
            self.logger.error("Failed to restore any shortcuts.vdf files")
            return False

    def _modify_shortcuts_directly(self, shortcuts_file, modlist_name, mo2_path, mo2_dir):
        """
        Directly modify shortcuts.vdf in a way that preserves Steam's exact binary format.
        This is a fallback method when regular VDF handling might cause issues.
        
        Args:
            shortcuts_file (str): Path to shortcuts.vdf
            modlist_name (str): Name for the modlist
            mo2_path (str): Path to ModOrganizer.exe
            mo2_dir (str): Directory containing ModOrganizer.exe
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Make a secure backup first
            import shutil
            backup_path = f"{shortcuts_file}.{int(time.time())}.bak"
            shutil.copy2(shortcuts_file, backup_path)
            self.logger.info(f"Created backup before direct modification: {backup_path}")
            
            # Create a new shortcut entry using Steam's expected format
            
            # Pre-populate shortcuts.vdf if it doesn't exist or is empty
            if not os.path.exists(shortcuts_file) or os.path.getsize(shortcuts_file) == 0:
                with open(shortcuts_file, 'wb') as f:
                    f.write(b'\x00shortcuts\x00\x08\x08')
                self.logger.info(f"Created new shortcuts.vdf file at {shortcuts_file}")
                
            # Use direct steam-vdf library for reliable binary operations
            try:
                # Try to import the steam-vdf library
                import sys
                import importlib.util
                
                # Check if steam_vdf is installed
                steam_vdf_spec = importlib.util.find_spec("steam_vdf")
                
                if steam_vdf_spec is None:
                    # Try to install steam-vdf using pip
                    print("Installing required dependency (steam-vdf)...")
                    subprocess.check_call([sys.executable, "-m", "pip", "install", "steam-vdf", "--user"])
                    time.sleep(1)  # Give some time for the install to complete
                
                # Now import it
                import steam_vdf
                
                with open(shortcuts_file, 'rb') as f:
                    shortcuts_data = steam_vdf.load(f)
                
                # Find the highest shortcut ID to use for the new entry
                max_id = -1
                if 'shortcuts' in shortcuts_data:
                    for id_str in shortcuts_data['shortcuts']:
                        try:
                            id_num = int(id_str)
                            if id_num > max_id:
                                max_id = id_num
                        except ValueError:
                            pass
                
                # Create a new shortcut entry
                new_id = max_id + 1
                
                # Ensure 'shortcuts' key exists
                if 'shortcuts' not in shortcuts_data:
                    shortcuts_data['shortcuts'] = {}
                
                # Add the new shortcut
                shortcuts_data['shortcuts'][str(new_id)] = {
                    'AppName': modlist_name,
                    'Exe': f'"{mo2_path}"',
                    'StartDir': mo2_dir,
                    'icon': '',
                    'ShortcutPath': '',
                    'LaunchOptions': '',
                    'IsHidden': 0,
                    'AllowDesktopConfig': 1,
                    'AllowOverlay': 1,
                    'OpenVR': 0,
                    'Devkit': 0,
                    'DevkitGameID': '',
                    'LastPlayTime': 0
                }
                
                # Write back to file
                with open(shortcuts_file, 'wb') as f:
                    steam_vdf.dump(shortcuts_data, f)
                
                self.logger.info(f"Added shortcut for {modlist_name} using steam-vdf library")
                return True
                
            except Exception as e:
                self.logger.warning(f"Failed to use steam-vdf library: {e}")
                
                # Fall back to our safe VDFHandler
                self.logger.info("Falling back to VDFHandler for shortcuts.vdf modification")
                shortcuts_data = VDFHandler.load(shortcuts_file, binary=True)
                
                # If the data is empty, initialize it
                if not shortcuts_data:
                    shortcuts_data = {'shortcuts': {}}
                
                # Create new shortcut entry
                new_id = len(shortcuts_data.get('shortcuts', {}))
                new_entry = {
                    'AppName': modlist_name,
                    'Exe': f'"{mo2_path}"',
                    'StartDir': mo2_dir,
                    'icon': '',
                    'ShortcutPath': '',
                    'LaunchOptions': '',
                    'IsHidden': 0,
                    'AllowDesktopConfig': 1,
                    'AllowOverlay': 1,
                    'OpenVR': 0,
                    'Devkit': 0,
                    'DevkitGameID': '',
                    'LastPlayTime': 0
                }
                
                # Add to shortcuts
                if 'shortcuts' not in shortcuts_data:
                    shortcuts_data['shortcuts'] = {}
                shortcuts_data['shortcuts'][str(new_id)] = new_entry
                
                # Write back to file using our safe VDFHandler
                result = VDFHandler.save(shortcuts_file, shortcuts_data, binary=True)
                
                self.logger.info(f"Added shortcut for {modlist_name} using VDFHandler")
                return result
        
        except Exception as e:
            self.logger.error(f"Error in direct shortcut modification: {e}")
            return False
    
    def _add_steam_shortcut_safely(self, shortcuts_file, app_name, exe_path, start_dir, icon_path="", launch_options="", tags=None):
        """
        Adds a new shortcut entry to the shortcuts.vdf file using the correct binary format.
        This method is carefully designed to maintain file integrity.
        
        Args:
            shortcuts_file (str): Path to shortcuts.vdf
            app_name (str): Name for the shortcut
            exe_path (str): Path to the executable
            start_dir (str): Start directory for the executable
            icon_path (str): Path to icon file (optional)
            launch_options (str): Command line options (optional)
            tags (list): List of tags (optional)
            
        Returns:
            tuple: (bool success, str app_id) - Success status and calculated AppID
        """
        if tags is None:
            tags = []  # Ensure tags is a list
            
        # Initialize data structure
        data = {'shortcuts': {}}  # Default structure if file doesn't exist or is empty
        
        try:
            # CRITICAL: Open in BINARY READ mode ('rb')
            if os.path.exists(shortcuts_file):
                with open(shortcuts_file, 'rb') as f:
                    file_data = f.read()
                    if file_data:  # Only try to parse if the file has content
                        try:
                            data = vdf.binary_loads(file_data)
                            # Ensure the top-level 'shortcuts' key exists
                            if 'shortcuts' not in data:
                                data['shortcuts'] = {}
                        except Exception as e:
                            self.logger.warning(f"Could not parse existing shortcuts.vdf: {e}")
                            # Reset to default structure if loading fails
                            data = {'shortcuts': {}}
            else:
                self.logger.info(f"shortcuts.vdf not found at {shortcuts_file}. A new file will be created.")
        except Exception as e:
            self.logger.warning(f"Error accessing shortcuts.vdf: {e}")
            # Reset to default structure if loading fails
            data = {'shortcuts': {}}
        
        # Ensure the shortcuts key exists
        if 'shortcuts' not in data:
            data['shortcuts'] = {}
            
        # Find the next available index key (0, 1, 2, ...)
        next_index = 0
        if data.get('shortcuts'):  # Check if shortcuts dictionary exists and is not empty
            shortcut_indices = [int(k) for k in data['shortcuts'].keys() if k.isdigit()]
            if shortcut_indices:
                next_index = max(shortcut_indices) + 1
        
        # Steam expects specific fields for each shortcut.
        # Even empty ones are often necessary.
        new_shortcut = {
            'AppName': app_name,
            'Exe': f'"{exe_path}"',  # Enclose executable path in quotes
            'StartDir': f'"{start_dir}"',  # Enclose start directory in quotes
            'icon': icon_path,
            'ShortcutPath': "",  # Usually empty for non-Steam games
            'LaunchOptions': launch_options,
            'IsHidden': 0,  # 0 for visible, 1 for hidden
            'AllowDesktopConfig': 1,  # Allow Steam Input configuration
            'AllowOverlay': 1,  # Allow Steam Overlay
            'OpenVR': 0,  # Set to 1 for VR games
            'Devkit': 0,
            'DevkitGameID': '',
            'DevkitOverrideAppID': 0,
            'LastPlayTime': 0,  # Timestamp, 0 for never played
            'FlatpakAppID': '',  # For Flatpak apps on Linux
            'IsInstalled': 1,  # Make it appear in "Locally Installed" filter
        }
        
        # Add tags in the correct format if any
        if tags:
            new_shortcut['tags'] = {str(i): tag for i, tag in enumerate(tags)}
        
        # Calculate the AppID - this is how Steam does it
        app_id = (0x80000000 + int(next_index)) % (2**32)
        
        # Ensure the AppID is within the valid 32-bit signed integer range
        if app_id > 0x7FFFFFFF:
            app_id = app_id - 0x100000000
        
        # Add the appid to the shortcut entry (like STL does)
        new_shortcut['appid'] = app_id
        
        # Add the new shortcut entry using the string representation of the index
        data['shortcuts'][str(next_index)] = new_shortcut
        self.logger.info(f"Adding shortcut '{app_name}' at index {next_index}")
        
        try:
            # CRITICAL: Open in BINARY WRITE mode ('wb')
            # First create a temp file to ensure we don't corrupt the original if something goes wrong
            temp_file = f"{shortcuts_file}.temp"
            with open(temp_file, 'wb') as f:
                vdf_data = vdf.binary_dumps(data)
                f.write(vdf_data)
                
            # Now rename the temp file to the actual file
            import shutil
            shutil.move(temp_file, shortcuts_file)
            
            self.logger.info(f"Successfully updated shortcuts.vdf! AppID: {app_id}")
            return True, app_id
        except Exception as e:
            self.logger.error(f"Error: Failed to write updated shortcuts.vdf: {e}")
            return False, None
    
    def create_shortcut(self, executable_path=None, shortcut_name=None, launch_options="", icon_path=""):
        """
        Create a new Steam shortcut entry.

        Args:
            executable_path (str): Path to the main executable (e.g., Hoolamike.exe)
            shortcut_name (str): Name for the Steam shortcut
            launch_options (str): Launch options string (optional)
            icon_path (str): Path to the icon for the shortcut (optional)

        Returns:
            tuple: (bool success, Optional[str] app_id) - Success status and the generated AppID, or None if failed.
        """
        self.logger.info(f"Attempting to create shortcut for: {shortcut_name}")
        self.logger.debug(f"[DEBUG] create_shortcut called with executable_path={executable_path}, shortcut_name={shortcut_name}, icon_path={icon_path}")
        self._last_shortcuts_backup = None
        self._safe_shortcuts_backup = None
        self._shortcuts_file = None # Ensure this is reset/set correctly

        # --- Steam Icons normalization (move here for all flows) ---
        if executable_path:
            exe_dir = os.path.dirname(executable_path)
            steam_icons_path = Path(exe_dir) / "Steam Icons"
            steamicons_path = Path(exe_dir) / "SteamIcons"
            if steam_icons_path.is_dir() and not steamicons_path.is_dir():
                try:
                    steam_icons_path.rename(steamicons_path)
                    self.logger.info(f"Renamed 'Steam Icons' to 'SteamIcons' in {exe_dir}")
                except Exception as e:
                    self.logger.warning(f"Failed to rename 'Steam Icons' to 'SteamIcons': {e}")
        # ----------------------------------------------------------

        # Validate inputs
        if not executable_path or not os.path.exists(executable_path):
            self.logger.error(f"Invalid or non-existent executable path provided: {executable_path}")
            return False, None
        else:
            start_dir = os.path.dirname(executable_path)

        if not shortcut_name:
            self.logger.error("Shortcut name not provided.")
            return False, None

        try:
            # Use the shortcuts.vdf path found during initialization
            shortcuts_file = self.shortcuts_path
            self._shortcuts_file = shortcuts_file # Store for potential use

            if not shortcuts_file or not os.path.isfile(shortcuts_file):
                self.logger.error("shortcuts.vdf path not found or is invalid.")
                print("Error: Could not find the Steam shortcuts file (shortcuts.vdf).")
                # Attempt to create a blank one? Might be risky.
                # Let's try creating it if the directory exists.
                config_dir = os.path.dirname(shortcuts_file) if shortcuts_file else None
                if config_dir and os.path.isdir(config_dir):
                    self.logger.warning(f"Attempting to create blank shortcuts.vdf at {shortcuts_file}")
                    with open(shortcuts_file, 'wb') as f:
                        f.write(b'\x00shortcuts\x00\x08\x08') # Minimal valid binary VDF structure
                    self.logger.info("Created blank shortcuts.vdf.")
                else:
                    self.logger.error("Cannot create shortcuts.vdf as parent directory doesn't exist.")
                    return False, None
            else:
                # Ensure the parent directory exists for backups if shortcuts_file was valid
                config_dir = os.path.dirname(shortcuts_file)
                if not os.path.isdir(config_dir):
                    self.logger.error(f"Config directory not found: {config_dir}")
                    print(f"Error: Steam config directory not found: {config_dir}")
                    return False, None

                # Create a direct backup before making any changes
                backup_dir = os.path.join(config_dir, "backups")
                os.makedirs(backup_dir, exist_ok=True)
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                backup_path = os.path.join(backup_dir, f"shortcuts_{timestamp}.bak")

                # Check if the shortcuts file exists before backing up
                if os.path.exists(shortcuts_file):
                    import shutil
                    shutil.copy2(shortcuts_file, backup_path)
                    self._last_shortcuts_backup = backup_path # Store for potential restoration
                    self.logger.info(f"Created backup at {backup_path}")
                else:
                    self.logger.warning(f"shortcuts.vdf does not exist at {shortcuts_file}, cannot create backup. Proceeding with potentially new file.")

            # --- Add STEAM_COMPAT_MOUNTS --- (Keep this logic)
            compat_mounts_str = ""
            try:
                self.logger.info("Determining necessary STEAM_COMPAT_MOUNTS...")
                all_libs = self.path_handler.get_all_steam_library_paths()
                main_steam_lib_path_obj = self.path_handler.find_steam_library()
                if main_steam_lib_path_obj and main_steam_lib_path_obj.name == "common":
                    main_steam_lib_path = main_steam_lib_path_obj.parent.parent
                else:
                    main_steam_lib_path = main_steam_lib_path_obj

                mount_paths = []
                if main_steam_lib_path:
                    self.logger.debug(f"Identified main Steam library: {main_steam_lib_path}")
                    main_resolved = main_steam_lib_path.resolve()
                    for lib_path in all_libs:
                        if lib_path.resolve() != main_resolved:
                            mount_paths.append(str(lib_path.resolve()))
                        else:
                            self.logger.debug(f"Excluding main library {lib_path} from mounts.")
                else:
                    self.logger.warning("Could not reliably determine the main Steam library. STEAM_COMPAT_MOUNTS may include it or be empty.")
                    mount_paths = []

                if mount_paths:
                    compat_mounts_str = f'STEAM_COMPAT_MOUNTS="{":".join(mount_paths)}"'
                    self.logger.info(f"Generated STEAM_COMPAT_MOUNTS string: {compat_mounts_str}")
                else:
                    self.logger.info("No additional libraries identified or needed for STEAM_COMPAT_MOUNTS.")

            except Exception as e:
                self.logger.error(f"Error determining STEAM_COMPAT_MOUNTS: {e}", exc_info=True)

            # Prepend STEAM_COMPAT_MOUNTS to existing launch options
            final_launch_options = launch_options
            if compat_mounts_str:
                 if final_launch_options:
                     final_launch_options = f"{compat_mounts_str} {final_launch_options}"
                 else:
                     final_launch_options = compat_mounts_str

            # Ensure %command% is at the end if not already present
            if not final_launch_options.strip().endswith("%command%"):
                if final_launch_options:
                    final_launch_options = f"{final_launch_options} %command%"
                else:
                    final_launch_options = "%command%"

            self.logger.debug(f"Final launch options string: {final_launch_options}")
            # --- End STEAM_COMPAT_MOUNTS ---

            # Add the shortcut using our safe method
            success, app_id = self._add_steam_shortcut_safely(
                shortcuts_file,
                shortcut_name,
                executable_path,  # Use the validated path
                start_dir,        # Use the derived start_dir
                icon_path=icon_path,      # Pass the icon path
                launch_options=final_launch_options, # Pass the combined options
                tags=["Jackify", "Tool"] # Add relevant tags
            )

            if not success:
                self.logger.error("Failed to add shortcut entry safely.")
                return False, None

            self.logger.info(f"Shortcut created successfully for {shortcut_name} with AppID {app_id}")
            return True, app_id

        except Exception as e:
            self.logger.error(f"Error creating shortcut: {e}", exc_info=True)
            print(f"An error occurred while creating the shortcut: {e}")
            return False, None
    
    def _is_steam_deck(self):
        # Check /etc/os-release for 'steamdeck' or if the systemd service exists
        try:
            if os.path.exists('/etc/os-release'):
                with open('/etc/os-release') as f:
                    if 'steamdeck' in f.read().lower():
                        return True
            # Check for the systemd user service
            user_services = subprocess.run(['systemctl', '--user', 'list-units', '--type=service', '--no-pager'], capture_output=True, text=True)
            if 'app-steam@autostart.service' in user_services.stdout:
                return True
        except Exception as e:
            self.logger.warning(f"Error detecting Steam Deck: {e}")
        return False

    def secure_steam_restart(self, status_callback: Optional[Callable[[str], None]] = None) -> bool:
        """
        Secure Steam restart with comprehensive error handling to prevent segfaults.
        Now delegates to the robust steam restart service for cross-distro compatibility.
        """
        try:
            from ..services.steam_restart_service import robust_steam_restart
            return robust_steam_restart(progress_callback=status_callback, timeout=60)
        except ImportError as e:
            self.logger.error(f"Failed to import steam restart service: {e}")
            # Fallback to original implementation if service is not available
            return self._legacy_secure_steam_restart(status_callback)
        except Exception as e:
            self.logger.error(f"Error in robust steam restart: {e}")
            # Fallback to original implementation on any error
            return self._legacy_secure_steam_restart(status_callback)
    
    def _legacy_secure_steam_restart(self, status_callback: Optional[Callable[[str], None]] = None) -> bool:
        """
        Legacy secure Steam restart implementation (fallback).
        """
        import subprocess
        import time
        import os
        
        self.logger.info("Attempting secure Steam restart sequence...")
        
        # Wrap all subprocess calls in try-catch to prevent segfaults
        def safe_subprocess_run(cmd, **kwargs):
            """Safely run subprocess with error handling"""
            try:
                return subprocess.run(cmd, **kwargs)
            except Exception as e:
                self.logger.error(f"Subprocess error with cmd {cmd}: {e}")
                return subprocess.CompletedProcess(cmd, 1, "", str(e))
        
        def safe_subprocess_popen(cmd, **kwargs):
            """Safely start subprocess with error handling"""
            try:
                return subprocess.Popen(cmd, **kwargs)
            except Exception as e:
                self.logger.error(f"Popen error with cmd {cmd}: {e}")
                return None
        
        if self._is_steam_deck():
            self.logger.info("Detected Steam Deck. Using systemd to restart Steam.")
            if status_callback: 
                try:
                    status_callback("Restarting Steam via systemd...")
                except Exception as e:
                    self.logger.warning(f"Status callback error: {e}")
            
            try:
                result = safe_subprocess_run(['systemctl', '--user', 'restart', 'app-steam@autostart.service'], capture_output=True, text=True, timeout=30)
                self.logger.info(f"systemctl restart output: {result.stdout.strip()} {result.stderr.strip()}")
                # Wait a bit for Steam to come up
                time.sleep(10)
                # Optionally, check if Steam is running
                check = safe_subprocess_run(['pgrep', '-f', 'steam'], capture_output=True, timeout=10)
                if check.returncode == 0:
                    self.logger.info("Steam restarted successfully via systemd.")
                    if status_callback: 
                        try:
                            status_callback("Steam Started")
                        except Exception as e:
                            self.logger.warning(f"Status callback error: {e}")
                    return True
                else:
                    self.logger.error("Steam did not start after systemd restart.")
                    if status_callback: 
                        try:
                            status_callback("Start Failed")
                        except Exception as e:
                            self.logger.warning(f"Status callback error: {e}")
                    return False
            except Exception as e:
                self.logger.error(f"Error restarting Steam via systemd: {e}")
                if status_callback: 
                    try:
                        status_callback("Restart Failed")
                    except Exception as e:
                        self.logger.warning(f"Status callback error: {e}")
                return False
        
        # --- Non-Steam Deck (generic Linux) implementation ---
        try:
            if status_callback: 
                try:
                    status_callback("Stopping Steam...")
                except Exception as e:
                    self.logger.warning(f"Status callback error: {e}")
            
            self.logger.info("Attempting clean Steam shutdown via 'steam -shutdown'...")
            shutdown_timeout = 30
            result = safe_subprocess_run(['steam', '-shutdown'], timeout=shutdown_timeout, check=False, capture_output=True, text=True)
            if result.returncode != 1:  # subprocess.run returns CompletedProcess even on error
                self.logger.debug("'steam -shutdown' command executed (exit code ignored, verification follows).")
            else:
                self.logger.warning(f"'steam -shutdown' had issues: {result.stderr}")
        except Exception as e:
            self.logger.warning(f"Error executing 'steam -shutdown': {e}. Will proceed to check processes.")
        
        if status_callback: 
            try:
                status_callback("Waiting for Steam to close...")
            except Exception as e:
                self.logger.warning(f"Status callback error: {e}")
        
        self.logger.info("Verifying Steam processes are terminated...")
        max_attempts = 6
        steam_closed_successfully = False
        
        for attempt in range(max_attempts):
            try:
                check_cmd = ['pgrep', '-f', 'steamwebhelper']
                self.logger.debug(f"Executing check: {' '.join(check_cmd)}")
                result = safe_subprocess_run(check_cmd, capture_output=True, timeout=10)
                if result.returncode != 0:
                    self.logger.info("No Steam web helper processes found via pgrep.")
                    steam_closed_successfully = True
                    break
                else:
                    try:
                        steam_pids = result.stdout.decode().strip().split('\n') if result.stdout else []
                        self.logger.debug(f"Steam web helper processes still detected (PIDs: {steam_pids}). Waiting... (Attempt {attempt + 1}/{max_attempts} after shutdown cmd)")
                    except Exception as e:
                        self.logger.warning(f"Error parsing pgrep output: {e}")
                    time.sleep(5)
            except Exception as e:
                self.logger.warning(f"Error checking Steam processes (attempt {attempt + 1}): {e}")
                time.sleep(5)
        
        if not steam_closed_successfully:
            self.logger.debug("Steam processes still running after 'steam -shutdown'. Attempting fallback with 'pkill steam'...")
            if status_callback: 
                try:
                    status_callback("Force stopping Steam...")
                except Exception as e:
                    self.logger.warning(f"Status callback error: {e}")
            
            # Fallback: Use pkill to force terminate Steam processes
            try:
                self.logger.info("Attempting force shutdown via 'pkill steam'...")
                pkill_result = safe_subprocess_run(['pkill', '-f', 'steam'], timeout=15, check=False, capture_output=True, text=True)
                self.logger.info(f"pkill steam result: {pkill_result.returncode} - {pkill_result.stdout.strip()} {pkill_result.stderr.strip()}")
                
                # Wait a bit for processes to terminate
                time.sleep(3)
                
                # Check again if Steam processes are terminated
                final_check = safe_subprocess_run(['pgrep', '-f', 'steamwebhelper'], capture_output=True, timeout=10)
                if final_check.returncode != 0:
                    self.logger.info("Steam processes successfully terminated via pkill fallback.")
                    steam_closed_successfully = True
                else:
                    self.logger.debug("Steam processes still running after pkill fallback.")
                    if status_callback: 
                        try:
                            status_callback("Shutdown Failed")
                        except Exception as e:
                            self.logger.warning(f"Status callback error: {e}")
                    return False
                    
            except Exception as e:
                self.logger.error(f"Error during pkill fallback: {e}")
                if status_callback: 
                    try:
                        status_callback("Shutdown Failed")
                    except Exception as e:
                        self.logger.warning(f"Status callback error: {e}")
                return False
        
        if not steam_closed_successfully:
            self.logger.error("Failed to terminate Steam processes via all methods.")
            if status_callback: 
                try:
                    status_callback("Shutdown Failed")
                except Exception as e:
                    self.logger.warning(f"Status callback error: {e}")
            return False
        
        self.logger.info("Steam confirmed closed.")
        
        start_methods = [
            {"name": "Popen", "cmd": ["steam", "-silent"], "kwargs": {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "stdin": subprocess.DEVNULL, "start_new_session": True}},
            {"name": "setsid", "cmd": ["setsid", "steam", "-silent"], "kwargs": {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "stdin": subprocess.DEVNULL}},
            {"name": "nohup", "cmd": ["nohup", "steam", "-silent"], "kwargs": {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "stdin": subprocess.DEVNULL, "start_new_session": True, "preexec_fn": os.setpgrp}}
        ]
        steam_start_initiated = False
        
        for i, method in enumerate(start_methods):
            method_name = method["name"]
            status_msg = f"Starting Steam ({method_name})"
            if status_callback: 
                try:
                    status_callback(status_msg)
                except Exception as e:
                    self.logger.warning(f"Status callback error: {e}")
            
            self.logger.info(f"Attempting to start Steam using method: {method_name}")
            try:
                process = safe_subprocess_popen(method["cmd"], **method["kwargs"])
                if process is not None:
                    self.logger.info(f"Initiated Steam start with {method_name}.")
                    time.sleep(5)
                    check_result = safe_subprocess_run(['pgrep', '-f', 'steam'], capture_output=True, timeout=10)
                    if check_result.returncode == 0:
                        self.logger.info(f"Steam process detected after using {method_name}. Proceeding to wait phase.")
                        steam_start_initiated = True
                        break
                    else:
                        self.logger.warning(f"Steam process not detected after initiating with {method_name}. Trying next method.")
                else:
                    self.logger.warning(f"Failed to start process with {method_name}. Trying next method.")
            except FileNotFoundError:
                self.logger.error(f"Command not found for method {method_name} (e.g., setsid, nohup). Trying next method.")
            except Exception as e:
                self.logger.error(f"Error starting Steam with {method_name}: {e}. Trying next method.")
        
        if not steam_start_initiated:
            self.logger.error("All methods to initiate Steam start failed.")
            if status_callback: 
                try:
                    status_callback("Start Failed")
                except Exception as e:
                    self.logger.warning(f"Status callback error: {e}")
            return False
        
        status_msg = "Waiting for Steam to fully start"
        if status_callback: 
            try:
                status_callback(status_msg)
            except Exception as e:
                self.logger.warning(f"Status callback error: {e}")
        
        self.logger.info("Waiting up to 2 minutes for Steam to fully initialize...")
        max_startup_wait = 120
        elapsed_wait = 0
        initial_wait_done = False
        
        while elapsed_wait < max_startup_wait:
            try:
                result = safe_subprocess_run(['pgrep', '-f', 'steam'], capture_output=True, timeout=10)
                if result.returncode == 0:
                    if not initial_wait_done:
                        self.logger.info("Steam process detected. Waiting additional time for full initialization...")
                        initial_wait_done = True
                    time.sleep(5)
                    elapsed_wait += 5
                    if initial_wait_done and elapsed_wait >= 15:
                        final_check = safe_subprocess_run(['pgrep', '-f', 'steam'], capture_output=True, timeout=10)
                        if final_check.returncode == 0:
                            if status_callback: 
                                try:
                                    status_callback("Steam Started")
                                except Exception as e:
                                    self.logger.warning(f"Status callback error: {e}")
                            self.logger.info("Steam confirmed running after wait.")
                            return True
                        else:
                            self.logger.warning("Steam process disappeared during final initialization wait.")
                            break
                else:
                    self.logger.debug(f"Steam process not yet detected. Waiting... ({elapsed_wait + 5}s)")
                    time.sleep(5)
                    elapsed_wait += 5
            except Exception as e:
                self.logger.warning(f"Error during Steam startup wait: {e}")
                time.sleep(5)
                elapsed_wait += 5
        
        self.logger.error("Steam failed to start/initialize within the allowed time.")
        if status_callback: 
            try:
                status_callback("Start Timed Out")
            except Exception as e:
                self.logger.warning(f"Status callback error: {e}")
        return False
    
    def _verify_and_restore_shortcuts(self):
        """
        Verify shortcuts.vdf exists after Steam restart and restore it if needed.
        """
        shortcuts_file = getattr(self, '_shortcuts_file', None)
        if not shortcuts_file:
            self.logger.warning("No shortcuts file to verify")
            return
            
        if not os.path.exists(shortcuts_file) or os.path.getsize(shortcuts_file) == 0:
            self.logger.warning(f"shortcuts.vdf missing or empty after restart: {shortcuts_file}")
            
            # Try to restore from pre-restart backup
            safe_backup = getattr(self, '_safe_shortcuts_backup', None)
            if safe_backup and os.path.exists(safe_backup):
                try:
                    import shutil
                    shutil.copy2(safe_backup, shortcuts_file)
                    self.logger.info(f"Restored shortcuts.vdf from pre-restart backup")
                    print("Restored shortcuts file after Steam restart")
                    return
                except Exception as e:
                    self.logger.error(f"Failed to restore from pre-restart backup: {e}")
            
            # Try regular backup if pre-restart failed
            backup = getattr(self, '_last_shortcuts_backup', None)
            if backup and os.path.exists(backup):
                try:
                    import shutil
                    shutil.copy2(backup, shortcuts_file)
                    self.logger.info(f"Restored shortcuts.vdf from regular backup")
                    print("Restored shortcuts file after Steam restart")
                except Exception as e:
                    self.logger.error(f"Failed to restore from backup: {e}")
                    print("Failed to restore shortcuts file. You may need to recreate your shortcut.")
        else:
            self.logger.info(f"shortcuts.vdf verified intact after restart")
    
    def create_shortcut_workflow(self):
        """
        Run the complete shortcut creation workflow
        Returns:
            bool: True if successful, False otherwise
        """
        # Create the shortcut
        shortcut_data = self.create_shortcut()
        if not shortcut_data:
            return False
        
        # Note: Steam restart is now handled within create_shortcut()
        return True
    
    def create_new_modlist_shortcut(self):
        """
        Create a new modlist shortcut in Steam
        This follows the procedure described in the documentation
        
        Returns:
            bool: True if successful, False otherwise
        """
        print("\nShortcut Creation")
        print("───────────────────────────────────────────────────────────────────")
        print("This will create a new Steam shortcut for your modlist.")
        print("You will need to provide the path to ModOrganizer.exe and a name for your modlist.")
        
        # Create the shortcut
        modlist_data = self.create_shortcut()
        if not modlist_data:
            print("Shortcut creation cancelled or failed.")
            return False
        
        # Present the user with a summary of what was created
        print("\nShortcut created successfully!")
        print("───────────────────────────────────────────────────────────────────")
        print(f"Modlist Name: {modlist_data['name']}")
        print(f"Directory: {modlist_data['directory']}")
        print(f"Steam AppID: {modlist_data['app_id']}")
        print("───────────────────────────────────────────────────────────────────")
        
        return True
    
    def get_selected_modlist(self):
        """
        Get the selected modlist string in the format expected by ModlistHandler.configure_modlist
        
        Returns:
            str: Selected modlist string in the format "Non-Steam shortcut: Name (AppID)"
                 or None if no modlist was selected
        """
        return getattr(self, 'selected_modlist', None)

    def get_appid_for_shortcut(self, shortcut_name: str, exe_path: Optional[str] = None) -> Optional[str]:
        """
        Find the current AppID for a given shortcut name and (optionally) executable path using protontricks.

        Args:
            shortcut_name (str): The name of the Steam shortcut.
            exe_path (Optional[str]): The path to the executable (for robust matching after Steam restart).

        Returns:
            Optional[str]: The found AppID string, or None if not found or error occurs.
        """
        self.logger.info(f"Attempting to find current AppID for shortcut: '{shortcut_name}' (exe_path: '{exe_path}')")
        try:
            from .protontricks_handler import ProtontricksHandler # Local import
            pt_handler = ProtontricksHandler(steamdeck=self.steamdeck)
            if not pt_handler.detect_protontricks():
                self.logger.error("Protontricks not detected")
                return None
            result = pt_handler.run_protontricks("-l")
            if not result or result.returncode != 0:
                self.logger.error(f"Protontricks failed to list applications: {result.stderr if result else 'No result'}")
                return None
            # Build a list of all shortcuts
            found_shortcuts = []
            for line in result.stdout.splitlines():
                m = re.search(r"Non-Steam shortcut:\s*(.*?)\s*\((\d+)\)$", line)
                if m:
                    pt_name = m.group(1).strip()
                    pt_appid = m.group(2)
                    found_shortcuts.append((pt_name, pt_appid))
            # For robust matching, also parse shortcuts.vdf for exe paths
            vdf_shortcuts = []
            shortcuts_vdf_path = self.shortcuts_path
            if shortcuts_vdf_path and os.path.isfile(shortcuts_vdf_path):
                try:
                    shortcuts_data = VDFHandler.load(shortcuts_vdf_path, binary=True)
                    if shortcuts_data and 'shortcuts' in shortcuts_data:
                        for idx, shortcut in shortcuts_data['shortcuts'].items():
                            app_name = shortcut.get('AppName', '').strip()
                            exe = shortcut.get('Exe', '').strip('"').strip()
                            vdf_shortcuts.append((app_name, exe, idx))
                except Exception as e:
                    self.logger.error(f"Error parsing shortcuts.vdf for exe path matching: {e}")
            # Try to match by both name and exe_path if exe_path is provided
            if exe_path:
                exe_path_norm = os.path.abspath(os.path.expanduser(exe_path)).lower()
                shortcut_name_clean = shortcut_name.strip().lower()
                for pt_name, pt_appid in found_shortcuts:
                    for vdf_name, vdf_exe, vdf_idx in vdf_shortcuts:
                        if vdf_name.strip().lower() == pt_name.strip().lower() == shortcut_name_clean:
                            vdf_exe_norm = os.path.abspath(os.path.expanduser(vdf_exe)).lower()
                            if vdf_exe_norm == exe_path_norm:
                                self.logger.info(f"Found matching AppID {pt_appid} for shortcut '{pt_name}' with exe '{vdf_exe}' (input: '{exe_path}')")
                                return pt_appid
                self.logger.error(f"No shortcut found matching both name '{shortcut_name}' and exe_path '{exe_path}'.")
                return None
            # Fallback: match by name only (for existing modlist config)
            shortcut_name_clean = shortcut_name.strip().lower()
            for pt_name, pt_appid in found_shortcuts:
                if pt_name.strip().lower() == shortcut_name_clean:
                    self.logger.info(f"Found matching AppID {pt_appid} for shortcut '{pt_name}' (input: '{shortcut_name}')")
                    return pt_appid
            self.logger.error(f"Could not find an AppID for shortcut named '{shortcut_name}' via protontricks.")
            return None
        except Exception as e:
            self.logger.error(f"Error getting AppID for shortcut '{shortcut_name}': {e}")
            self.logger.exception("Traceback:")
            return None

    # --- Discovery Methods Moved from ModlistHandler ---
    
    def _scan_shortcuts_for_executable(self, executable_name: str) -> List[Dict[str, str]]:
        """
        Scans the user's shortcuts.vdf file for entries pointing to a specific executable.

        Args:
            executable_name (str): The base name of the executable (e.g., "ModOrganizer.exe")

        Returns:
            List[Dict[str, str]]: A list of dictionaries, each containing {'name': AppName, 'path': StartDir}
                                  for shortcuts matching the executable name.
        """
        self.logger.info(f"Scanning {self.shortcuts_path} for executable '{executable_name}'...")
        matched_shortcuts = []

        if not self.shortcuts_path or not os.path.isfile(self.shortcuts_path):
            self.logger.error(f"shortcuts.vdf path not found or invalid: {self.shortcuts_path}")
            return []

        # Directly process the single shortcuts.vdf file found during init
        shortcuts_file = self.shortcuts_path
        try:
            # Use VDFHandler static method for loading
            shortcuts_data = VDFHandler.load(shortcuts_file, binary=True)
            if shortcuts_data is None or 'shortcuts' not in shortcuts_data:
                self.logger.warning(f"Could not load or parse data from {shortcuts_file}")
                return [] # Cannot proceed if file is empty/invalid

            for shortcut_id, shortcut in shortcuts_data['shortcuts'].items():
                # Ensure shortcut entry is a dictionary
                if not isinstance(shortcut, dict):
                    self.logger.warning(f"Skipping invalid shortcut entry (not a dict) at index {shortcut_id} in {shortcuts_file}")
                    continue 
                    
                app_name = shortcut.get('AppName')
                exe_path = shortcut.get('Exe', '').strip('"')
                start_dir = shortcut.get('StartDir', '').strip('"')
                
                # Check if the base name of the exe_path matches the target
                if app_name and start_dir and os.path.basename(exe_path) == executable_name:
                    # Perform a basic check for MO2 ini if looking for MO2
                    is_valid = True
                    if executable_name == "ModOrganizer.exe":
                        # Use Path object for exists check
                        if not (Path(start_dir) / 'ModOrganizer.ini').exists():
                            self.logger.warning(f"Found MO2 shortcut '{app_name}' but ModOrganizer.ini missing in '{start_dir}'")
                            is_valid = False
                    
                    if is_valid:
                        matched_shortcuts.append({'name': app_name, 'path': start_dir})
                        self.logger.debug(f"Found '{executable_name}' shortcut in VDF: {app_name} -> {start_dir}")

        except Exception as e:
            self.logger.error(f"Error processing {shortcuts_file}: {e}")
            # Return empty list on error processing the file
            return []

        self.logger.info(f"Scan complete. Found {len(matched_shortcuts)} potential '{executable_name}' shortcuts in VDF file.")
        return matched_shortcuts

    def discover_executable_shortcuts(self, executable_name: str) -> List[str]:
        """
        Discovers non-Steam shortcuts for a specific executable, cross-referencing
        VDF files with the Protontricks runtime list.

        Args:
            executable_name (str): The base name of the executable (e.g., "ModOrganizer.exe")

        Returns:
            List[str]: A list of strings in the format "Non-Steam shortcut: Name (AppID)"
                       for valid, matched shortcuts.
        """
        self.logger.info(f"Discovering configured shortcuts for '{executable_name}'...")
        
        # 1. Get potential shortcuts from VDF files
        vdf_shortcuts = self._scan_shortcuts_for_executable(executable_name)
        if not vdf_shortcuts:
            self.logger.warning(f"No '{executable_name}' shortcuts found in VDF files.")
            # Don't exit yet, maybe protontricks lists something VDF missed?

        # 2. Get the list of shortcuts known to Protontricks
        # Use the handler initialized in __init__
        pt_result = self.protontricks_handler.run_protontricks("-l") 
        if not pt_result or pt_result.returncode != 0:
            self.logger.error(f"Protontricks failed to list applications: {pt_result.stderr if pt_result else 'No result'}")
            return [] # Cannot proceed without protontricks list
        
        # Extract names and AppIDs from protontricks output
        pt_shortcuts = {}
        for line in pt_result.stdout.splitlines():
            line = line.strip()
            if "Non-Steam shortcut:" in line:
                match = re.search(r"Non-Steam shortcut:\s*(.*?)\s*\((\d+)\)$", line)
                if match:
                    pt_name = match.group(1).strip()
                    pt_appid = match.group(2)
                    pt_shortcuts[pt_name] = pt_appid # Store AppName -> AppID

        if not pt_shortcuts:
            self.logger.warning("No Non-Steam shortcuts listed by Protontricks.")
            return []

        # 3. Cross-reference VDF shortcuts with Protontricks list
        final_list = []
        vdf_names_found = {item['name'] for item in vdf_shortcuts}
        # pt_names_found = set(pt_shortcuts.keys()) # Not needed directly
        
        for vdf_shortcut in vdf_shortcuts:
            vdf_name = vdf_shortcut['name']
            if vdf_name in pt_shortcuts:
                # Match found!
                runtime_appid = pt_shortcuts[vdf_name]
                modlist_string = f"Non-Steam shortcut: {vdf_name} ({runtime_appid})"
                final_list.append(modlist_string)
                self.logger.debug(f"Validated shortcut: {modlist_string}")
        
        if not final_list:
             self.logger.warning(f"No shortcuts for '{executable_name}' found in VDF matched the Protontricks list.")

        self.logger.info(f"Discovery complete. Found {len(final_list)} validated shortcuts for '{executable_name}'.")
        return final_list 

    def find_shortcuts_by_exe(self, executable_name: str) -> List[Dict]:
        """Finds shortcuts in shortcuts.vdf that point to a specific executable.

        Args:
            executable_name: The name of the executable (e.g., "ModOrganizer.exe")
                             to search for within the 'Exe' path.

        Returns:
            A list of dictionaries, each representing a matching shortcut 
            and containing keys like 'AppName', 'Exe', 'StartDir'.
            Returns an empty list if no matches are found or an error occurs.
        """
        self.logger.info(f"Scanning {self.shortcuts_path} for executable: {executable_name}")
        matching_shortcuts = []

        # --- Use the single shortcuts.vdf path found during init --- 
        if not self.shortcuts_path or not os.path.isfile(self.shortcuts_path):
            self.logger.error(f"shortcuts.vdf path not found or invalid: {self.shortcuts_path}")
            return []
        
        vdf_path = self.shortcuts_path
        try:
            self.logger.debug(f"Parsing shortcuts file: {vdf_path}")
            shortcuts_data = VDFHandler.load(vdf_path, binary=True)
            
            if not shortcuts_data or 'shortcuts' not in shortcuts_data:
                self.logger.warning(f"Shortcuts data is empty or invalid in {vdf_path}")
                return [] # Return empty if no data

            # The shortcuts are under a top-level 'shortcuts' key
            shortcuts_dict = shortcuts_data.get('shortcuts', {})
            
            for index, shortcut_details in shortcuts_dict.items():
                # Ensure shortcut_details is a dictionary
                if not isinstance(shortcut_details, dict):
                    self.logger.warning(f"Skipping invalid shortcut entry at index {index} in {vdf_path}")
                    continue

                exe_path = shortcut_details.get('Exe', '').strip('"') # Get Exe path, remove quotes
                app_name = shortcut_details.get('AppName', 'Unknown Shortcut')

                # Check if the executable_name is present in the Exe path
                if executable_name in os.path.basename(exe_path):
                    self.logger.info(f"Found matching shortcut '{app_name}' in {vdf_path}")
                    # Extract relevant details
                    match = {
                        'AppName': app_name,
                        'Exe': exe_path, # Store unquoted path
                        'StartDir': shortcut_details.get('StartDir', '').strip('"') # Unquoted
                        # Add other useful fields if needed, e.g., 'ShortcutPath'
                    }
                    matching_shortcuts.append(match)
                else:
                     self.logger.debug(f"Skipping shortcut '{app_name}': Exe path '{exe_path}' does not contain '{executable_name}'")

        except Exception as e:
            self.logger.error(f"Error processing shortcuts file {vdf_path}: {e}", exc_info=True)
            # Return empty list on error
            return []
        
        if not matching_shortcuts:
            # Changed log level to debug as this is an expected outcome sometimes
             self.logger.debug(f"No shortcuts found pointing to '{executable_name}' in {vdf_path}.")

        return matching_shortcuts

    def update_shortcut_launch_options(self, app_name, exe_path, new_launch_options):
        """
        Updates the LaunchOptions for a specific existing shortcut in shortcuts.vdf by matching AppName and Exe.

        Args:
            app_name (str): The AppName of the shortcut to update (from config summary).
            exe_path (str): The Exe path of the shortcut to update (from config summary, including quotes if present in VDF).
            new_launch_options (str): The new string to set for LaunchOptions.

        Returns:
            bool: True if the update was successful, False otherwise.
        """
        self.logger.info(f"Attempting to update launch options for shortcut with AppName '{app_name}' and Exe '{exe_path}' (no AppID matching)...")

        # Find the user's shortcuts.vdf
        shortcuts_file = self.path_handler._find_shortcuts_vdf()
        if not shortcuts_file:
            self.logger.error("Could not find shortcuts.vdf to update.")
            return False

        data = {'shortcuts': {}}
        # Load existing shortcuts safely (binary read)
        try:
            if os.path.exists(shortcuts_file):
                with open(shortcuts_file, 'rb') as f:
                    file_data = f.read()
                    if file_data:
                        data = vdf.binary_loads(file_data)
                        if 'shortcuts' not in data:
                            data['shortcuts'] = {}
            else:
                self.logger.error(f"shortcuts.vdf does not exist at {shortcuts_file}. Cannot update.")
                return False
        except Exception as e:
            self.logger.error(f"Error reading or parsing shortcuts.vdf: {e}")
            return False

        # Normalize paths for robust matching (handle quotes, absolute paths, case)
        def _normalize_path(p: str) -> str:
            try:
                # Strip surrounding quotes, expanduser, abspath, collapse duplicate slashes
                p_clean = os.path.abspath(os.path.expanduser(p.strip().strip('"')))
                return os.path.normpath(p_clean).lower()
            except Exception:
                return p.strip().strip('"').lower()

        exe_norm = _normalize_path(exe_path)
        target_index = None
        for index, shortcut_data in data.get('shortcuts', {}).items():
            shortcut_name = (shortcut_data.get('AppName', '') or '').strip()
            shortcut_exe_raw = shortcut_data.get('Exe', '')
            shortcut_exe_norm = _normalize_path(shortcut_exe_raw)
            if shortcut_name == app_name and shortcut_exe_norm == exe_norm:
                target_index = index
                break

        if target_index is None:
            self.logger.error(f"Could not find shortcut with AppName '{app_name}' and Exe '{exe_path}' in shortcuts.vdf.")
            # Log all AppNames and Exe values for debugging
            for index, shortcut_data in data.get('shortcuts', {}).items():
                shortcut_name = shortcut_data.get('AppName', '')
                shortcut_exe = shortcut_data.get('Exe', '')
                self.logger.error(f"Found shortcut: AppName='{shortcut_name}', Exe='{shortcut_exe}' -> norm='{_normalize_path(shortcut_exe)}'")
            return False

        # Update the LaunchOptions for the found shortcut
        if target_index in data['shortcuts']:
            self.logger.info(f"Found shortcut at index {target_index}. Updating LaunchOptions...")
            data['shortcuts'][target_index]['LaunchOptions'] = new_launch_options
        else:
            self.logger.error(f"Target index {target_index} not found in shortcuts dictionary after identification.")
            return False

        # Write the updated data back safely (binary write to temp file first)
        try:
            temp_file = f"{shortcuts_file}.temp"
            with open(temp_file, 'wb') as f:
                vdf_data = vdf.binary_dumps(data)
                f.write(vdf_data)

            # Create backup before overwriting
            backup_dir = os.path.join(os.path.dirname(shortcuts_file), "backups")
            os.makedirs(backup_dir, exist_ok=True)
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            backup_path = os.path.join(backup_dir, f"shortcuts_update_{app_name}_{timestamp}.bak")
            if os.path.exists(shortcuts_file):
                shutil.copy2(shortcuts_file, backup_path)
                self.logger.info(f"Created backup before update at {backup_path}")

            shutil.move(temp_file, shortcuts_file)
            self.logger.info(f"Successfully updated LaunchOptions for shortcut '{app_name}' in {shortcuts_file}.")
            return True
        except Exception as e:
            self.logger.error(f"Error writing updated shortcuts.vdf: {e}")
            # Attempt to restore backup if update failed
            if 'backup_path' in locals() and os.path.exists(backup_path):
                try:
                    shutil.copy2(backup_path, shortcuts_file)
                    self.logger.warning(f"Restored shortcuts.vdf from backup {backup_path} after update failure.")
                except Exception as restore_e:
                    self.logger.critical(f"CRITICAL: Failed to write updated shortcuts.vdf AND failed to restore backup! Error: {restore_e}")
            return False

    @staticmethod
    def get_steam_shortcut_icon_path(exe_path, steamicons_dir=None, logger=None):
        """
        Select the best icon for a Steam shortcut given an executable path and optional SteamIcons directory.
        Prefers grid-tall.png, else any .png, else returns ''.
        Logs selection steps if logger is provided.
        """
        exe_dir = os.path.dirname(exe_path)
        if not steamicons_dir:
            steamicons_dir = os.path.join(exe_dir, "SteamIcons")
        if logger:
            logger.debug(f"[DEBUG] Looking for Steam shortcut icon in: {steamicons_dir}")
        if os.path.isdir(steamicons_dir):
            preferred_icon = os.path.join(steamicons_dir, "grid-tall.png")
            if os.path.isfile(preferred_icon):
                if logger:
                    logger.debug(f"[DEBUG] Using grid-tall.png as shortcut icon: {preferred_icon}")
                return preferred_icon
            pngs = [f for f in os.listdir(steamicons_dir) if f.lower().endswith('.png')]
            if pngs:
                icon_path = os.path.join(steamicons_dir, pngs[0])
                if logger:
                    logger.debug(f"[DEBUG] Using fallback icon for shortcut: {icon_path}")
                return icon_path
            if logger:
                logger.debug("[DEBUG] No .png icon found in SteamIcons directory.")
            return ""
        if logger:
            logger.debug("[DEBUG] No SteamIcons directory found; shortcut will have no icon.")
        return ""

    def write_nxmhandler_ini(self, modlist_dir, mo2_exe_path):
        """
        Create nxmhandler.ini in the modlist directory to suppress the NXM Handling popup on first MO2 launch.
        If the file already exists, do nothing.
        The executable path will be written as Z:\\<absolute path with double backslashes>, matching MO2's format.
        """
        ini_path = os.path.join(modlist_dir, "nxmhandler.ini")
        if os.path.exists(ini_path):
            self.logger.info(f"nxmhandler.ini already exists at {ini_path}")
            return
        # Build the correct executable path: Z:\\<absolute path with double backslashes>
        abs_path = os.path.abspath(mo2_exe_path)
        z_path = f"Z:{abs_path}"
        win_path = z_path.replace('/', '\\')  # single backslash first
        win_path = win_path.replace('\\', '\\\\')  # double all backslashes
        content = (
            "[handlers]\n"
            "size=1\n"
            "1\\games=\"skyrimse,skyrim\"\n"
            f"1\\executable={win_path}\n"
            "1\\arguments=\n"
        )
        with open(ini_path, "w") as f:
            f.write(content)
        self.logger.info(f"[SUCCESS] nxmhandler.ini written to {ini_path}")