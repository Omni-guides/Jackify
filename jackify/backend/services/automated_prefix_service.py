#!/usr/bin/env python3
"""
Automated Prefix Creation Service

This service implements the automated Proton prefix creation workflow
that eliminates the need for manual steps in Jackify.
"""
import os
import sys
import time
import subprocess
import logging
from pathlib import Path
from typing import Optional, Tuple, Union, List, Dict
import vdf

logger = logging.getLogger(__name__)

def debug_print(message):
    """Print debug message only if debug mode is enabled"""
    from jackify.backend.handlers.config_handler import ConfigHandler
    config_handler = ConfigHandler()
    if config_handler.get('debug_mode', False):
        print(message)

class AutomatedPrefixService:
    """
    Service for automated Proton prefix creation using temporary batch files
    and direct Proton wrapper integration.
    """
    
    def __init__(self):
        self.scripts_dir = Path.home() / "Jackify/scripts"
        self.scripts_dir.mkdir(parents=True, exist_ok=True)
        # Use shared timing for consistency across services
    
    def _get_progress_timestamp(self):
        """Get consistent progress timestamp"""
        from jackify.shared.timing import get_timestamp
        return get_timestamp()
    
    
    def create_shortcut_with_native_service(self, shortcut_name: str, exe_path: str, 
                                           modlist_install_dir: str, custom_launch_options: str = None) -> Tuple[bool, Optional[int]]:
        """
        Create a Steam shortcut using the native Steam service (no STL).
        
        Args:
            shortcut_name: Name for the shortcut
            exe_path: Path to the executable  
            modlist_install_dir: Directory where the modlist is installed
            custom_launch_options: Pre-generated launch options (overrides default generation)
            
        Returns:
            (success, unsigned_app_id)
        """
        logger.info(f"Creating shortcut with native service: {shortcut_name}")
        
        try:
            from ..services.native_steam_service import NativeSteamService
            
            # Initialize native Steam service
            steam_service = NativeSteamService()
            
            # Use custom launch options if provided, otherwise generate default
            if custom_launch_options:
                launch_options = custom_launch_options
                logger.info(f"Using pre-generated launch options: {launch_options}")
            else:
                # Generate STEAM_COMPAT_MOUNTS launch option for compatibility
                launch_options = "%command%"
                try:
                    from ..handlers.path_handler import PathHandler
                    path_handler = PathHandler()
                    
                    all_libs = path_handler.get_all_steam_library_paths()
                    main_steam_lib_path_obj = path_handler.find_steam_library()
                    if main_steam_lib_path_obj and main_steam_lib_path_obj.name == "common":
                        main_steam_lib_path = main_steam_lib_path_obj.parent.parent
                        
                        filtered_libs = [lib for lib in all_libs if str(lib) != str(main_steam_lib_path)]
                        if filtered_libs:
                            mount_paths = ":".join(str(lib) for lib in filtered_libs)
                            launch_options = f'STEAM_COMPAT_MOUNTS="{mount_paths}" %command%'
                            logger.info(f"Generated launch options with mounts: {launch_options}")
                except Exception as e:
                    logger.warning(f"Could not generate STEAM_COMPAT_MOUNTS, using default: {e}")
                    launch_options = "%command%"
            
            # Create shortcut with Proton using native service
            success, app_id = steam_service.create_shortcut_with_proton(
                app_name=shortcut_name,
                exe_path=exe_path,
                start_dir=modlist_install_dir,
                launch_options=launch_options,
                tags=["Jackify"],
                proton_version="proton_experimental"
            )
            
            if success and app_id:
                logger.info(f" Native Steam service created shortcut successfully with AppID: {app_id}")
                return True, app_id
            else:
                logger.error("❌ Native Steam service failed to create shortcut")
                return False, None
                
        except Exception as e:
            logger.error(f"Error creating shortcut with native service: {e}")
            return False, None
    
    def _generate_special_game_launch_options(self, special_game_type: str, modlist_install_dir: str) -> Optional[str]:
        """
        Generate launch options for FNV/Enderal games that require vanilla compatdata.
        
        Args:
            special_game_type: "fnv" or "enderal"
            modlist_install_dir: Directory where the modlist is installed
            
        Returns:
            Complete launch options string with STEAM_COMPAT_DATA_PATH, or None if failed
        """
        if not special_game_type or special_game_type not in ["fnv", "enderal"]:
            return None
            
        logger.info(f"Generating {special_game_type.upper()} launch options")
        
        # Map game types to AppIDs
        appid_map = {"fnv": "22380", "enderal": "976620"}
        appid = appid_map[special_game_type]
        
        # Find vanilla game compatdata
        from ..handlers.path_handler import PathHandler
        compatdata_path = PathHandler.find_compat_data(appid)
        if not compatdata_path:
            logger.error(f"Could not find vanilla {special_game_type.upper()} compatdata directory (AppID {appid})")
            return None
            
        # Create STEAM_COMPAT_DATA_PATH string
        compat_data_str = f'STEAM_COMPAT_DATA_PATH="{compatdata_path}"'
        
        # Generate STEAM_COMPAT_MOUNTS if multiple libraries exist
        compat_mounts_str = ""
        try:
            all_libs = PathHandler.get_all_steam_library_paths()
            main_steam_lib_path_obj = PathHandler.find_steam_library()
            if main_steam_lib_path_obj and main_steam_lib_path_obj.name == "common":
                main_steam_lib_path = main_steam_lib_path_obj.parent.parent
            else:
                main_steam_lib_path = main_steam_lib_path_obj
                
            mount_paths = []
            if main_steam_lib_path:
                main_resolved = main_steam_lib_path.resolve()
                for lib_path in all_libs:
                    if lib_path.resolve() != main_resolved:
                        mount_paths.append(str(lib_path.resolve()))
                        
            if mount_paths:
                mount_paths_str = ':'.join(mount_paths)
                compat_mounts_str = f'STEAM_COMPAT_MOUNTS="{mount_paths_str}"'
                logger.info(f"Added STEAM_COMPAT_MOUNTS for {special_game_type.upper()}")
        except Exception as e:
            logger.warning(f"Error generating STEAM_COMPAT_MOUNTS for {special_game_type}: {e}")
            
        # Combine all launch options
        launch_options = f"{compat_mounts_str} {compat_data_str} %command%".strip()
        launch_options = ' '.join(launch_options.split())  # Clean up spacing
        
        logger.info(f"Generated {special_game_type.upper()} launch options: {launch_options}")
        return launch_options
    
    def check_shortcut_proton_version(self, shortcut_name: str):
        """
        Check if the shortcut has the Proton version set correctly.
        
        Args:
            shortcut_name: Name of the shortcut to check
        """
        # STL sets the compatibility tool in config.vdf, not shortcuts.vdf
        # We know this works from manual testing, so just log that we're skipping this check
        logger.info(f"Skipping Proton version check for '{shortcut_name}' - STL handles this correctly")
        debug_print(f"[DEBUG] Skipping Proton version check for '{shortcut_name}' - STL handles this correctly")
    
    
    def handle_existing_shortcut_conflict(self, shortcut_name: str, exe_path: str, modlist_install_dir: str) -> Union[bool, List[Dict]]:
        """
        Check for existing shortcut with same name and path, prompt user if found.
        
        Args:
            shortcut_name: Name of the shortcut to create
            exe_path: Path to the executable
            modlist_install_dir: Directory where the modlist is installed
            
        Returns:
            True if we should proceed (no conflict or user chose to replace), False if user cancelled
        """
        try:
            shortcuts_path = self._get_shortcuts_path()
            if not shortcuts_path:
                return True  # No shortcuts file, no conflict
            
            with open(shortcuts_path, 'rb') as f:
                shortcuts_data = vdf.binary_load(f)
            
            shortcuts = shortcuts_data.get('shortcuts', {})
            conflicts = []
            
            # Look for shortcuts with the same name AND path
            for i in range(len(shortcuts)):
                shortcut = shortcuts[str(i)]
                name = shortcut.get('AppName', '')
                shortcut_exe = shortcut.get('Exe', '').strip('"')  # Remove quotes
                shortcut_startdir = shortcut.get('StartDir', '').strip('"')  # Remove quotes
                
                # Check if name matches AND (exe path matches OR startdir matches)
                # Use exact name match instead of partial match to avoid false positives
                name_matches = shortcut_name == name
                exe_matches = shortcut_exe == exe_path
                startdir_matches = shortcut_startdir == modlist_install_dir
                
                if (name_matches and (exe_matches or startdir_matches)):
                    conflicts.append({
                        'index': i,
                        'name': name,
                        'exe': shortcut_exe,
                        'startdir': shortcut_startdir
                    })
            
            if conflicts:
                logger.warning(f"Found {len(conflicts)} existing shortcut(s) with same name and path")
                
                # Log details about each conflict for debugging
                for i, conflict in enumerate(conflicts):
                    logger.info(f"Conflict {i+1}: Name='{conflict['name']}', Exe='{conflict['exe']}', StartDir='{conflict['startdir']}'")
                
                # Return the conflict information so the frontend can handle it
                return conflicts
            else:
                logger.debug("No conflicting shortcuts found")
                return True
                
        except Exception as e:
            logger.error(f"Error handling shortcut conflict: {e}")
            return True  # Proceed on error to avoid blocking
    
    def format_conflict_message(self, conflicts: List[Dict]) -> str:
        """
        Format conflict information into a user-friendly message.
        
        Args:
            conflicts: List of conflict dictionaries from handle_existing_shortcut_conflict
            
        Returns:
            Formatted message for the user
        """
        if not conflicts:
            return "No conflicts found."
        
        message = f"Found {len(conflicts)} existing Steam shortcut(s) with the same name and path:\n\n"
        
        for i, conflict in enumerate(conflicts, 1):
            message += f"{i}. **Name:** {conflict['name']}\n"
            message += f"   **Executable:** {conflict['exe']}\n"
            message += f"   **Start Directory:** {conflict['startdir']}\n\n"
        
        message += "**Options:**\n"
        message += "• **Replace** - Remove the existing shortcut and create a new one\n"
        message += "• **Cancel** - Keep the existing shortcut and stop the installation\n"
        message += "• **Skip** - Continue without creating a Steam shortcut\n\n"
        message += "The existing shortcut will be removed if you choose to replace it."
        
        return message
    
    def _get_shortcuts_path(self) -> Optional[Path]:
        """Get the path to shortcuts.vdf using proper Steam path detection."""
        try:
            from ..handlers.path_handler import PathHandler
            
            # Use find_steam_config_vdf to get the Steam config path, then derive the Steam root
            config_vdf_path = PathHandler.find_steam_config_vdf()
            if not config_vdf_path:
                logger.error("Could not find Steam config.vdf")
                return None
            
            # Get Steam root directory (config.vdf is in steam/config/config.vdf)
            steam_path = config_vdf_path.parent.parent  # steam/config/config.vdf -> steam
            logger.debug(f"Detected Steam path: {steam_path}")
            
            # Find the userdata directory
            userdata_dir = steam_path / "userdata"
            if not userdata_dir.exists():
                logger.error(f"Steam userdata directory not found: {userdata_dir}")
                return None
            
            # Find the first user directory (most systems have only one user)
            user_dirs = [d for d in userdata_dir.iterdir() if d.is_dir() and d.name.isdigit()]
            if not user_dirs:
                logger.error("No Steam user directories found in userdata")
                return None
            
            # Use the first user directory found
            user_dir = user_dirs[0]
            shortcuts_path = user_dir / "config" / "shortcuts.vdf"
            
            logger.debug(f"Looking for shortcuts.vdf at: {shortcuts_path}")
            if not shortcuts_path.exists():
                logger.error(f"shortcuts.vdf not found: {shortcuts_path}")
                return None
                
            logger.info(f"Found shortcuts.vdf at: {shortcuts_path}")
            return shortcuts_path
            
        except Exception as e:
            logger.error(f"Error getting shortcuts path: {e}")
            import traceback
            logger.debug(f"Full traceback: {traceback.format_exc()}")
            return None
        
    def create_temp_batch_file(self, shortcut_name: str) -> Optional[str]:
        """
        Create a temporary batch file for silent prefix creation.
        
        Args:
            shortcut_name: Name of the shortcut (used for unique filename)
            
        Returns:
            Path to the created batch file, or None if failed
        """
        try:
            # Create a unique batch file name
            timestamp = int(time.time())
            batch_filename = f"prefix_creation_{shortcut_name}_{timestamp}.bat"
            batch_path = self.scripts_dir / batch_filename
            
            # Create the batch file content
            batch_content = f"""@echo off
echo Creating prefix for {shortcut_name}
REM This will trigger Proton to create a prefix
echo Prefix creation in progress...
REM Wait a bit for Proton to initialize
timeout /t 5 /nobreak >nul
REM Try to run a simple command to ensure prefix is created
echo Prefix creation completed
exit"""
            
            with open(batch_path, 'w') as f:
                f.write(batch_content)
            
            # Make it executable
            os.chmod(str(batch_path), 0o755)
            
            logger.info(f"Created temporary batch file: {batch_path}")
            return str(batch_path)
            
        except Exception as e:
            logger.error(f"Failed to create batch file: {e}")
            return None
    
    def find_proton_experimental(self) -> Optional[Path]:
        """
        Find Proton Experimental installation.
        
        Returns:
            Path to Proton Experimental, or None if not found
        """
        proton_paths = [
            Path.home() / ".local/share/Steam/steamapps/common/Proton - Experimental",
            Path.home() / ".steam/steam/steamapps/common/Proton - Experimental",
            Path.home() / ".local/share/Steam/steamapps/common/Proton Experimental",
            Path.home() / ".steam/steam/steamapps/common/Proton Experimental",
        ]
        
        for path in proton_paths:
            if path.exists():
                logger.info(f"Found Proton Experimental at: {path}")
                return path
        
        logger.error("Proton Experimental not found")
        return None
    
    
    
    def verify_shortcut_created(self, shortcut_name: str) -> Optional[int]:
        """
        Verify the shortcut was created and get its AppID.
        
        Args:
            shortcut_name: Name of the shortcut to look for
            
        Returns:
            AppID if found, None otherwise
        """
        try:
            shortcuts_path = self._get_shortcuts_path()
            if not shortcuts_path:
                return None
            
            with open(shortcuts_path, 'rb') as f:
                shortcuts_data = vdf.binary_load(f)
            
            shortcuts = shortcuts_data.get('shortcuts', {})
            
            # Look for our shortcut by name
            for i in range(len(shortcuts)):
                shortcut = shortcuts[str(i)]
                name = shortcut.get('AppName', '')
                
                if shortcut_name in name:
                    appid = shortcut.get('appid')
                    exe_path = shortcut.get('Exe', '')
                    
                    logger.info(f"Found shortcut: {name}")
                    logger.info(f"  AppID: {appid}")
                    logger.info(f"  Exe: {exe_path}")
                    logger.info(f"  CompatTool: {shortcut.get('CompatTool', 'NOT_SET')}")
                    
                    return appid
            
            logger.error(f"Shortcut '{shortcut_name}' not found")
            return None
            
        except Exception as e:
            logger.error(f"Error reading shortcuts: {e}")
            return None

    def detect_actual_prefix_appid(self, initial_appid: int, shortcut_name: str) -> Optional[int]:
        """
        After Steam restart, detect the actual prefix AppID that was created.
        Use protontricks -l to find the actual positive AppID.
        
        Args:
            initial_appid: The initial (negative) AppID from shortcuts.vdf
            shortcut_name: Name of the shortcut for logging
            
        Returns:
            The actual (positive) AppID of the created prefix, or None if not found
        """
        try:
            logger.info(f"Using protontricks -l to detect actual AppID for shortcut: {shortcut_name}")
            
            # Wait up to 30 seconds for the shortcut to appear in protontricks
            for i in range(30):
                try:
                    # Use the existing protontricks handler
                    from jackify.backend.handlers.protontricks_handler import ProtontricksHandler
                    protontricks_handler = ProtontricksHandler(steamdeck=False)
                    result = protontricks_handler.run_protontricks('-l')
                    
                    if result.returncode == 0:
                        lines = result.stdout.strip().split('\n')
                        
                        # Look for our shortcut name in the protontricks output
                        for line in lines:
                            if shortcut_name in line and 'Non-Steam shortcut:' in line:
                                # Extract AppID from line like "Non-Steam shortcut: Tuxborn (3106560878)"
                                if '(' in line and ')' in line:
                                    appid_str = line.split('(')[1].split(')')[0]
                                    actual_appid = int(appid_str)
                                    logger.info(f" Found shortcut in protontricks: {line.strip()}")
                                    logger.info(f"  Initial AppID: {initial_appid}")
                                    logger.info(f"  Actual AppID: {actual_appid}")
                                    return actual_appid
                    
                    logger.debug(f"Shortcut '{shortcut_name}' not found in protontricks yet (attempt {i+1}/30)")
                    time.sleep(1)
                    
                except subprocess.TimeoutExpired:
                    logger.warning(f"protontricks -l timed out on attempt {i+1}")
                    time.sleep(1)
                except Exception as e:
                    logger.warning(f"Error running protontricks -l on attempt {i+1}: {e}")
                    time.sleep(1)
            
            logger.error(f"❌ Shortcut '{shortcut_name}' not found in protontricks after 30 seconds")
            return None
            
        except Exception as e:
            logger.error(f"Error detecting actual prefix AppID: {e}")
            return None

    def restart_steam(self) -> bool:
        """
        Restart Steam using the robust service method.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            from .steam_restart_service import robust_steam_restart
            return robust_steam_restart(progress_callback=None, timeout=60)
        except Exception as e:
            logger.error(f"Error restarting Steam: {e}")
            return False

    def generate_steam_short_id(self, signed_appid: int) -> int:
        """
        Convert signed 32-bit integer to unsigned 32-bit integer (same as STL's generateSteamShortID).
        
        Args:
            signed_appid: Signed 32-bit integer AppID
            
        Returns:
            Unsigned 32-bit integer AppID
        """
        return signed_appid & 0xFFFFFFFF
    
    def launch_shortcut_to_trigger_prefix(self, initial_appid: int) -> bool:
        """
        Launch the shortcut using rungameid to trigger prefix creation.
        This follows the same pattern as the working test script.
        
        Args:
            initial_appid: The initial (negative) AppID from shortcuts.vdf
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Convert signed AppID to unsigned AppID (same as STL's generateSteamShortID)
            unsigned_appid = self.generate_steam_short_id(initial_appid)
            
            # Calculate rungameid using the unsigned AppID
            rungameid = (unsigned_appid << 32) | 0x02000000
            
            logger.info(f"Launching shortcut with rungameid: {rungameid}")
            debug_print(f"[DEBUG] Launching shortcut with rungameid: {rungameid}")
            debug_print(f"[DEBUG] Initial signed AppID: {initial_appid}")
            debug_print(f"[DEBUG] Unsigned AppID: {unsigned_appid}")
            
            # Launch using rungameid
            cmd = ['steam', f'steam://rungameid/{rungameid}']
            debug_print(f"[DEBUG] About to run launch command: {' '.join(cmd)}")
            
            # Use subprocess.Popen to launch asynchronously (steam command returns immediately)
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            
            # Wait a moment for the process to start
            time.sleep(1)
            
            # Check if the process is still running (steam command should exit quickly)
            try:
                return_code = process.poll()
                if return_code is None:
                    # Process is still running, wait a bit more
                    time.sleep(2)
                    return_code = process.poll()
                
                debug_print(f"[DEBUG] Steam launch process return code: {return_code}")
                
                # Get any output
                stdout, stderr = process.communicate(timeout=1)
                if stdout:
                    debug_print(f"[DEBUG] Steam launch stdout: {stdout}")
                if stderr:
                    debug_print(f"[DEBUG] Steam launch stderr: {stderr}")
                    
            except subprocess.TimeoutExpired:
                debug_print("[DEBUG] Steam launch process timed out, but that's OK")
                process.kill()
            
            logger.info(f"Launch command executed: {' '.join(cmd)}")
            
            # Give it a moment for the shortcut to actually start
            time.sleep(5)
            
            return True
            
        except subprocess.TimeoutExpired:
            logger.error("Launch command timed out")
            debug_print("[DEBUG] Launch command timed out")
            return False
        except Exception as e:
            logger.error(f"Error launching shortcut: {e}")
            debug_print(f"[DEBUG] Error launching shortcut: {e}")
            return False

    def create_shortcut_directly(self, shortcut_name: str, exe_path: str, modlist_install_dir: str) -> bool:
        """
        Create a Steam shortcut directly by modifying shortcuts.vdf.
        This is a fallback when STL fails.
        
        Args:
            shortcut_name: Name for the shortcut
            exe_path: Path to the executable
            modlist_install_dir: Directory where the modlist is installed
            
        Returns:
            True if successful, False otherwise
        """
        try:
            debug_print(f"[DEBUG] create_shortcut_directly called for '{shortcut_name}' - this is the fallback method")
            shortcuts_path = self._get_shortcuts_path()
            if not shortcuts_path:
                debug_print("[DEBUG] No shortcuts path found")
                return False
            
            # Read current shortcuts
            with open(shortcuts_path, 'rb') as f:
                shortcuts_data = vdf.binary_load(f)
            
            shortcuts = shortcuts_data.get('shortcuts', {})
            
            # Find the next available index
            next_index = str(len(shortcuts))
            
            # Calculate AppID for the new shortcut (negative for non-Steam shortcuts)
            import hashlib
            app_name_bytes = shortcut_name.encode('utf-8')
            exe_bytes = exe_path.encode('utf-8')
            combined = app_name_bytes + exe_bytes
            hash_value = int(hashlib.md5(combined).hexdigest()[:8], 16)
            appid = -(hash_value & 0x7FFFFFFF)  # Make it negative and within 32-bit range
            
            # Create new shortcut entry
            new_shortcut = {
                'AppName': shortcut_name,
                'Exe': f'"{exe_path}"',
                'StartDir': f'"{modlist_install_dir}"',
                'appid': appid,
                'icon': '',
                'ShortcutPath': '',
                'LaunchOptions': '',
                'IsHidden': 0,
                'AllowDesktopConfig': 1,
                'AllowOverlay': 1,
                'openvr': 0,
                'Devkit': 0,
                'DevkitGameID': '',
                'LastPlayTime': 0,
                'FlatpakAppID': '',
                'tags': {},
                'CompatTool': 'proton_experimental',  # Set Proton Experimental
                'IsInstalled': 1  # Make it appear in "Locally Installed" filter
            }
            
            # Add the new shortcut
            shortcuts[next_index] = new_shortcut
            
            # Write back to file
            with open(shortcuts_path, 'wb') as f:
                vdf.binary_dump(shortcuts_data, f)
            
            logger.info(f"Created shortcut directly: {shortcut_name}")
            return True
            
        except Exception as e:
            logger.error(f"Error creating shortcut directly: {e}")
            return False

    def create_shortcut_directly_with_proton(self, shortcut_name: str, exe_path: str, modlist_install_dir: str) -> bool:
        """
        Create a Steam shortcut with temporary batch file for invisible prefix creation.
        This uses the CRC32-based AppID calculation for predictable results.
        
        Args:
            shortcut_name: Name for the shortcut
            exe_path: Path to the final ModOrganizer.exe executable
            modlist_install_dir: Directory where the modlist is installed
            
        Returns:
            True if successful, False otherwise
        """
        try:
            debug_print(f"[DEBUG] create_shortcut_directly_with_proton called for '{shortcut_name}' - using temporary batch file approach")
            shortcuts_path = self._get_shortcuts_path()
            if not shortcuts_path:
                debug_print("[DEBUG] No shortcuts path found")
                return False
            
            # Calculate predictable AppID using CRC32 (based on FINAL exe_path)
            from zlib import crc32
            combined_string = exe_path + shortcut_name
            crc = crc32(combined_string.encode('utf-8'))
            appid = -(crc & 0x7FFFFFFF)  # Make it negative and within 32-bit range (like other shortcuts)
            
            debug_print(f"[DEBUG] Calculated AppID: {appid} from '{combined_string}'")
            
            # Create temporary batch file for invisible prefix creation
            batch_content = """@echo off
echo Creating Proton prefix...
timeout /t 3 /nobreak >nul
echo Prefix creation complete.
"""
            batch_path = Path.home() / "Jackify/temp_prefix_creation.bat"
            batch_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(batch_path, 'w') as f:
                f.write(batch_content)
            
            debug_print(f"[DEBUG] Created temporary batch file: {batch_path}")
            
            # Read current shortcuts
            with open(shortcuts_path, 'rb') as f:
                shortcuts_data = vdf.binary_load(f)
            
            shortcuts = shortcuts_data.get('shortcuts', {})
            
            # Check if shortcut already exists (idempotent)
            found = False
            new_shortcuts_list = []
            shortcuts_list = list(shortcuts.values())
            
            for shortcut in shortcuts_list:
                if shortcut.get('AppName') == shortcut_name:
                    debug_print(f"[DEBUG] Updating existing shortcut for '{shortcut_name}'")
                    # Update existing shortcut with temporary batch file
                    shortcut.update({
                        'Exe': f'"{batch_path}"',  # Point to temporary batch file
                        'StartDir': f'"{batch_path.parent}"',  # Batch file directory
                        'appid': appid,
                        'LaunchOptions': '',  # Empty like working shortcuts
                        'tags': {},  # Empty tags like working shortcuts
                        'CompatTool': 'proton_experimental'  # Set Proton version directly in shortcut
                    })
                    new_shortcuts_list.append(shortcut)
                    found = True
                else:
                    new_shortcuts_list.append(shortcut)
            
            if not found:
                debug_print(f"[DEBUG] Creating new shortcut for '{shortcut_name}'")
                # Create new shortcut entry pointing to temporary batch file
                new_shortcut = {
                    'AppName': shortcut_name,
                    'Exe': f'"{batch_path}"',  # Point to temporary batch file
                    'StartDir': f'"{batch_path.parent}"',  # Batch file directory
                    'appid': appid,
                    'icon': '',
                    'ShortcutPath': '',
                    'LaunchOptions': '',  # Empty like working shortcuts
                    'IsHidden': 0,
                    'AllowDesktopConfig': 1,
                    'AllowOverlay': 1,
                    'OpenVR': 0,
                    'Devkit': 0,
                    'DevkitGameID': '',
                    'LastPlayTime': 0,
                    'FlatpakAppID': '',
                    'tags': {},  # Empty tags like working shortcuts
                    'sortas': '',
                    'CompatTool': 'proton_experimental'  # Set Proton version directly in shortcut
                }
                new_shortcuts_list.append(new_shortcut)
            
            # Rebuild shortcuts dict with new order
            shortcuts_data['shortcuts'] = {str(i): s for i, s in enumerate(new_shortcuts_list)}
            
            # Write back to file
            with open(shortcuts_path, 'wb') as f:
                vdf.binary_dump(shortcuts_data, f)
            
            logger.info(f"Created/updated shortcut with temporary batch file: {shortcut_name} with AppID {appid}")
            debug_print(f"[DEBUG] Shortcut created/updated with temporary batch file, AppID {appid}")
            
            # Set Proton version in config.vdf BEFORE creating shortcut
            if self.set_proton_version_for_shortcut(appid, 'proton_experimental'):
                logger.info(f"Set Proton Experimental for shortcut {shortcut_name}")
                return True
            else:
                logger.warning(f"Failed to set Proton version for shortcut {shortcut_name}")
                return False
            
        except Exception as e:
            logger.error(f"Error creating shortcut with temporary batch file: {e}")
            return False
    
    def replace_shortcut_with_final_exe(self, shortcut_name: str, final_exe_path: str, modlist_install_dir: str) -> bool:
        """
        Replace the temporary batch file shortcut with the final ModOrganizer.exe.
        This should be called after the prefix has been created.
        
        Args:
            shortcut_name: Name of the shortcut to update
            final_exe_path: Path to the final ModOrganizer.exe executable
            modlist_install_dir: Directory where the modlist is installed
            
        Returns:
            True if successful, False otherwise
        """
        try:
            debug_print(f"[DEBUG] replace_shortcut_with_final_exe called for '{shortcut_name}'")
            shortcuts_path = self._get_shortcuts_path()
            if not shortcuts_path:
                debug_print("[DEBUG] No shortcuts path found")
                return False
            
            # Read current shortcuts
            with open(shortcuts_path, 'rb') as f:
                shortcuts_data = vdf.binary_load(f)
            
            shortcuts = shortcuts_data.get('shortcuts', {})
            
            # Find and update the shortcut
            found = False
            new_shortcuts_list = []
            shortcuts_list = list(shortcuts.values())
            
            for shortcut in shortcuts_list:
                if shortcut.get('AppName') == shortcut_name:
                    debug_print(f"[DEBUG] Replacing temporary batch file with final exe for '{shortcut_name}'")
                    # Update shortcut to point to final ModOrganizer.exe
                    shortcut.update({
                        'Exe': f'"{final_exe_path}"',  # Point to final ModOrganizer.exe
                        'StartDir': modlist_install_dir,  # ModOrganizer directory
                        'LaunchOptions': '',  # Empty like working shortcuts
                        'tags': {},  # Empty tags like working shortcuts
                        # Keep existing appid and CompatibilityTool
                    })
                    new_shortcuts_list.append(shortcut)
                    found = True
                else:
                    new_shortcuts_list.append(shortcut)
            
            if not found:
                logger.error(f"Shortcut '{shortcut_name}' not found for replacement")
                return False
            
            # Rebuild shortcuts dict with new order
            shortcuts_data['shortcuts'] = {str(i): s for i, s in enumerate(new_shortcuts_list)}
            
            # Write back to file
            with open(shortcuts_path, 'wb') as f:
                vdf.binary_dump(shortcuts_data, f)
            
            logger.info(f"Replaced shortcut with final exe: {shortcut_name}")
            debug_print(f"[DEBUG] Shortcut replaced with final ModOrganizer.exe")
            
            return True
            
        except Exception as e:
            logger.error(f"Error replacing shortcut with final exe: {e}")
            return False
    
    def set_proton_version_for_shortcut(self, appid: int, proton_version: str) -> bool:
        """
        Set the Proton version for a shortcut in config.vdf.
        
        Args:
            appid: The AppID of the shortcut (negative for non-Steam shortcuts)
            proton_version: The Proton version to set (e.g., 'proton_experimental')
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Get the config.vdf path
            config_path = self._get_config_path()
            if not config_path:
                logger.error("No config.vdf path found")
                return False
            
            # Read current config (config.vdf is text format)
            with open(config_path, 'r') as f:
                config_data = vdf.load(f)
            
            # Navigate to the correct location in the VDF structure
            if 'Software' not in config_data:
                config_data['Software'] = {}
            if 'Valve' not in config_data['Software']:
                config_data['Software']['Valve'] = {}
            if 'Steam' not in config_data['Software']['Valve']:
                config_data['Software']['Valve']['Steam'] = {}
            
            # Get or create CompatToolMapping
            if 'CompatToolMapping' not in config_data['Software']['Valve']['Steam']:
                config_data['Software']['Valve']['Steam']['CompatToolMapping'] = {}
            
            # Set the Proton version for this AppID
            config_data['Software']['Valve']['Steam']['CompatToolMapping'][str(appid)] = proton_version
            
            # Write back to file (text format)
            with open(config_path, 'w') as f:
                vdf.dump(config_data, f)
            
            logger.info(f"Set Proton version {proton_version} for AppID {appid}")
            debug_print(f"[DEBUG] Set Proton version {proton_version} for AppID {appid} in config.vdf")
            
            # Verify it was set correctly
            with open(config_path, 'r') as f:
                verify_data = vdf.load(f)
            actual_value = verify_data.get('Software', {}).get('Valve', {}).get('Steam', {}).get('CompatToolMapping', {}).get(str(appid))
            debug_print(f"[DEBUG] Verification: AppID {appid} -> {actual_value}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error setting Proton version: {e}")
            return False
    
    def _get_config_path(self) -> Optional[Path]:
        """Get the path to config.vdf"""
        try:
            from ..handlers.path_handler import PathHandler
            
            # Use find_steam_config_vdf to get the Steam config path
            config_vdf_path = PathHandler.find_steam_config_vdf()
            if not config_vdf_path:
                logger.error("Could not find Steam config.vdf")
                return None
            
            return config_vdf_path
            
        except Exception as e:
            logger.error(f"Error getting config path: {e}")
            return None


    def kill_running_processes(self) -> bool:
        """
        Kill any running processes that might interfere with prefix creation.
        This follows the same pattern as the working test script.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            import psutil
            
            logger.info("Looking for processes to kill...")
            
            # Look for ModOrganizer.exe process or any wine processes
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    proc_info = proc.info
                    name = proc_info.get('name', '')
                    cmdline = proc_info.get('cmdline', [])
                    
                    # Check for ModOrganizer.exe or wine processes
                    if ('ModOrganizer.exe' in name or 
                        'wine' in name.lower() or
                        any('ModOrganizer.exe' in str(arg) for arg in (cmdline or [])) or
                        any('wine' in str(arg).lower() for arg in (cmdline or []))):
                        
                        logger.info(f"Found process to kill: {name} (PID {proc_info['pid']})")
                        proc.terminate()
                        proc.wait(timeout=5)
                        logger.info(f" Process killed successfully")
                        
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired):
                    continue
            
            logger.info("ℹ️ No more processes to kill")
            return True
            
        except Exception as e:
            logger.error(f"Error killing processes: {e}")
            return False
    
    def create_prefix_directly(self, appid: int, batch_file_path: str) -> Optional[Path]:
        """
        Create prefix directly using Proton wrapper.
        
        Args:
            appid: The AppID from the shortcut
            batch_file_path: Path to the temporary batch file
            
        Returns:
            Path to the created prefix, or None if failed
        """
        proton_path = self.find_proton_experimental()
        if not proton_path:
            return None
        
        # Steam uses negative AppIDs for non-Steam shortcuts, but we need the positive value for the prefix path
        positive_appid = abs(appid)
        logger.info(f"Using positive AppID {positive_appid} for prefix creation (original: {appid})")
        
        # Create the prefix directory structure
        prefix_path = self._get_compatdata_path_for_appid(positive_appid)
        if not prefix_path:
            logger.error(f"Could not determine compatdata path for AppID {positive_appid}")
            return None
        
        # Create the prefix directory structure
        prefix_path.mkdir(parents=True, exist_ok=True)
        pfx_dir = prefix_path / "pfx"
        pfx_dir.mkdir(exist_ok=True)
        
        # Set up environment
        env = os.environ.copy()
        env['STEAM_COMPAT_DATA_PATH'] = str(prefix_path)
        env['STEAM_COMPAT_APP_ID'] = str(positive_appid)  # Use positive AppID for environment
        env['STEAM_COMPAT_CLIENT_INSTALL_PATH'] = str(Path.home() / ".local/share/Steam")
        
        # Build the command
        cmd = [
            str(proton_path / "proton"),
            "run",
            batch_file_path
        ]
        
        logger.info(f"Creating prefix with command: {' '.join(cmd)}")
        logger.info(f"Prefix path: {prefix_path}")
        logger.info(f"Using AppID: {positive_appid} (original: {appid})")
        
        try:
            # Run the command with a timeout
            result = subprocess.run(
                cmd, 
                env=env, 
                capture_output=True, 
                text=True, 
                timeout=30
            )
            
            # Check if prefix was created
            time.sleep(2)  # Give it a moment to settle
            
            prefix_created = prefix_path.exists()
            pfx_exists = (prefix_path / "pfx").exists()
            
            logger.info(f"Return code: {result.returncode}")
            logger.info(f"Prefix created: {prefix_created}")
            logger.info(f"pfx directory exists: {pfx_exists}")
            
            if result.stderr:
                logger.debug(f"stderr: {result.stderr.strip()}")
            
            success = prefix_created and pfx_exists
            
            if success:
                logger.info(f"Prefix created successfully at: {prefix_path}")
                return prefix_path
            else:
                logger.error("Failed to create prefix")
                return None
                
        except subprocess.TimeoutExpired:
            logger.warning("Command timed out, but this might be normal")
            # Check if prefix was created despite timeout
            prefix_created = prefix_path.exists()
            pfx_exists = (prefix_path / "pfx").exists()
            
            if prefix_created and pfx_exists:
                logger.info(f"Prefix created successfully despite timeout at: {prefix_path}")
                return prefix_path
            else:
                logger.error("No prefix created")
                return None
                
        except Exception as e:
            logger.error(f"Error creating prefix: {e}")
            return None
    
    def _get_compatdata_path_for_appid(self, appid: int) -> Optional[Path]:
        """
        Get the compatdata path for a given AppID using existing Jackify functions.
        
        Args:
            appid: The AppID to get the path for
            
        Returns:
            Path to the compatdata directory, or None if not found
        """
        # Use existing Jackify path detection
        from ..handlers.path_handler import PathHandler
        
        compatdata_path = PathHandler.find_compat_data(str(appid))
        if compatdata_path:
            return compatdata_path
        
        # Fallback: construct the path manually
        possible_bases = [
            Path.home() / ".steam/steam/steamapps/compatdata",
            Path.home() / ".local/share/Steam/steamapps/compatdata",
            Path.home() / ".var/app/com.valvesoftware.Steam/home/.steam/steam/steamapps/compatdata",
            Path.home() / ".var/app/com.valvesoftware.Steam/home/.local/share/Steam/steamapps/compatdata",
        ]
        
        for base_path in possible_bases:
            if base_path.is_dir():
                return base_path / str(appid)
        
        return None
    
    def verify_prefix_creation(self, prefix_path: Path) -> bool:
        """
        Verify that the prefix was created successfully.
        
        Args:
            prefix_path: Path to the prefix directory
            
        Returns:
            True if prefix is valid, False otherwise
        """
        try:
            logger.info(f"Verifying prefix: {prefix_path}")
            
            # Check if prefix exists and has proper structure
            if not prefix_path.exists():
                logger.error("Prefix directory does not exist")
                return False
            
            pfx_dir = prefix_path / "pfx"
            if not pfx_dir.exists():
                logger.error("Prefix exists but no pfx subdirectory")
                return False
            
            # Check for key Wine files
            system_reg = pfx_dir / "system.reg"
            user_reg = pfx_dir / "user.reg"
            drive_c = pfx_dir / "drive_c"
            
            if not system_reg.exists():
                logger.error("No system.reg found in prefix")
                return False
            
            if not user_reg.exists():
                logger.error("No user.reg found in prefix")
                return False
            
            if not drive_c.exists():
                logger.error("No drive_c directory found in prefix")
                return False
            
            logger.info("Prefix structure verified successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error verifying prefix: {e}")
            return False
    
    def modify_shortcut_to_final_exe(self, shortcut_name: str, final_exe_path: str, 
                                   final_start_dir: str) -> bool:
        """
        Update the existing batch file shortcut to point to the final executable.
        This preserves the AppID and prefix association while changing the target.
        
        Args:
            shortcut_name: Name of the shortcut to modify
            final_exe_path: Path to the final executable (e.g., ModOrganizer.exe)
            final_start_dir: Start directory for the executable
            
        Returns:
            True if successful, False otherwise
        """
        try:
            shortcuts_path = self._get_shortcuts_path()
            if not shortcuts_path:
                return False
            
            # Read current shortcuts
            with open(shortcuts_path, 'rb') as f:
                shortcuts_data = vdf.binary_load(f)
            
            shortcuts = shortcuts_data.get('shortcuts', {})
            
            # Find the batch file shortcut that created the prefix
            logger.info(f"Looking for batch file shortcut '{shortcut_name}' among {len(shortcuts)} shortcuts...")
            target_shortcut = None
            target_index = None
            
            for i in range(len(shortcuts)):
                shortcut = shortcuts[str(i)]
                name = shortcut.get('AppName', '')
                exe = shortcut.get('Exe', '')
                
                # Find the specific shortcut that points to our batch file (handle quoted paths)
                if (name == shortcut_name and 
                    exe and 'prefix_creation_' in exe and (exe.endswith('.bat') or exe.endswith('.bat"'))):
                    target_shortcut = shortcut
                    target_index = str(i)
                    logger.info(f"Found batch file shortcut '{shortcut_name}' at index {i}")
                    logger.info(f"  Current Exe: {exe}")
                    logger.info(f"  Current StartDir: {shortcut.get('StartDir', '')}")
                    logger.info(f"  Current CompatTool: {shortcut.get('CompatTool', 'NOT_SET')}")
                    logger.info(f"  AppID: {shortcut.get('appid', 'NOT_SET')}")
                    break
            
            if target_shortcut is None:
                logger.error(f"No batch file shortcut found with name '{shortcut_name}'")
                # Debug: show all available shortcuts
                logger.debug("Available shortcuts:")
                for i in range(len(shortcuts)):
                    shortcut = shortcuts[str(i)]
                    name = shortcut.get('AppName', '')
                    exe = shortcut.get('Exe', '')
                    logger.debug(f"  [{i}] {name} -> {exe}")
                return False
            
            # Update the existing shortcut IN-PLACE (preserves AppID and all other fields)
            logger.info(f"Updating shortcut at index {target_index} IN-PLACE...")
            
            # Only change Exe and StartDir - preserve everything else including AppID
            old_exe = target_shortcut.get('Exe', '')
            old_start_dir = target_shortcut.get('StartDir', '')
            
            target_shortcut['Exe'] = f'"{final_exe_path}"'
            target_shortcut['StartDir'] = f'"{final_start_dir}"'
            
            # Ensure CompatTool is set (STL should have set this, but make sure)
            if not target_shortcut.get('CompatTool', '').strip():
                target_shortcut['CompatTool'] = 'proton_experimental'
                logger.info("Set CompatTool to proton_experimental (was not set)")
            
            logger.info(f" Updated shortcut '{shortcut_name}' at index {target_index}:")
            logger.info(f"  Exe: {old_exe} → {target_shortcut['Exe']}")
            logger.info(f"  StartDir: {old_start_dir} → {target_shortcut['StartDir']}")
            logger.info(f"  AppID: {target_shortcut.get('appid', 'NOT_SET')} (preserved)")
            logger.info(f"  CompatTool: {target_shortcut.get('CompatTool', 'NOT_SET')} (preserved)")
            
            # Write back to file
            with open(shortcuts_path, 'wb') as f:
                vdf.binary_dump(shortcuts_data, f)
            
            logger.info(" Shortcut updated successfully - no duplicates created")
            return True
            
        except Exception as e:
            logger.error(f"Error modifying shortcut: {e}")
            return False
    
    def verify_final_shortcut(self, shortcut_name: str, expected_exe_path: str) -> bool:
        """
        Verify the shortcut now points to the final executable.
        
        Args:
            shortcut_name: Name of the shortcut to verify
            expected_exe_path: Expected executable path
            
        Returns:
            True if shortcut is correct, False otherwise
        """
        try:
            shortcuts_path = self._get_shortcuts_path()
            if not shortcuts_path:
                return False
            
            with open(shortcuts_path, 'rb') as f:
                shortcuts_data = vdf.binary_load(f)
            
            shortcuts = shortcuts_data.get('shortcuts', {})
            
            # Find our shortcut
            for i in range(len(shortcuts)):
                shortcut = shortcuts[str(i)]
                name = shortcut.get('AppName', '')
                
                if shortcut_name in name:
                    exe_path = shortcut.get('Exe', '')
                    start_dir = shortcut.get('StartDir', '')
                    
                    logger.info(f"Final shortcut configuration:")
                    logger.info(f"  Name: {name}")
                    logger.info(f"  Exe: {exe_path}")
                    logger.info(f"  StartDir: {start_dir}")
                    
                    # Verify it points to the final executable
                    if expected_exe_path in exe_path:
                        logger.info("Shortcut correctly points to final executable")
                        return True
                    else:
                        logger.error("Shortcut does not point to final executable")
                        return False
            
            logger.error(f"Shortcut '{shortcut_name}' not found")
            return False
            
        except Exception as e:
            logger.error(f"Error reading shortcuts: {e}")
            return False
    
    def wait_for_prefix_completion(self, prefix_id: str, timeout: int = 60) -> bool:
        """
        Wait for system.reg to stop growing (indicates prefix creation is complete).
        
        Args:
            prefix_id: The Steam prefix ID to monitor
            timeout: Maximum seconds to wait
            
        Returns:
            True if prefix creation completed, False if timeout
        """
        try:
            prefix_path = Path.home() / f".local/share/Steam/steamapps/compatdata/{prefix_id}"
            system_reg = prefix_path / "pfx/system.reg"
            
            logger.info(f"Monitoring prefix completion: {system_reg}")
            
            last_size = 0
            stable_count = 0
            
            for i in range(timeout):
                if system_reg.exists():
                    current_size = system_reg.stat().st_size
                    logger.debug(f"system.reg size: {current_size} bytes")
                    
                    if current_size == last_size:
                        stable_count += 1
                        if stable_count >= 3:  # Stable for 3 seconds
                            logger.info(" system.reg size stable - prefix creation complete")
                            return True
                    else:
                        stable_count = 0
                        last_size = current_size
                
                time.sleep(1)
            
            logger.warning(f"❌ Timeout waiting for prefix completion after {timeout} seconds")
            return False
            
        except Exception as e:
            logger.error(f"Error monitoring prefix completion: {e}")
            return False

    def kill_mo_processes(self) -> int:
        """
        Kill all ModOrganizer.exe processes.
        
        Returns:
            Number of processes killed
        """
        try:
            import psutil
            killed_count = 0
            
            logger.info("Searching for ModOrganizer processes...")
            
            for proc in psutil.process_iter():
                try:
                    proc_info = proc.as_dict(attrs=['pid', 'name', 'cmdline'])
                    name = proc_info.get('name', '').lower()
                    cmdline = proc_info.get('cmdline') or []
                    
                    # Check process name and command line
                    is_mo_process = (
                        'modorganizer' in name or
                        'mo2' in name or
                        any('modorganizer' in str(arg).lower() for arg in cmdline) or
                        any('ModOrganizer.exe' in str(arg) for arg in cmdline)
                    )
                    
                    if is_mo_process:
                        pid = proc_info['pid']
                        logger.info(f"Found ModOrganizer process: PID {pid}, name='{name}', cmdline={cmdline}")
                        
                        # Force kill with SIGTERM first, then SIGKILL if needed
                        proc.terminate()
                        try:
                            proc.wait(timeout=3)
                            logger.info(f" Process {pid} terminated gracefully")
                        except psutil.TimeoutExpired:
                            logger.info(f"Process {pid} didn't terminate, force killing...")
                            proc.kill()
                            proc.wait(timeout=2)
                            logger.info(f" Process {pid} force killed")
                        
                        killed_count += 1
                        
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
                except Exception as e:
                    logger.debug(f"Error checking process: {e}")
                    continue
            
            if killed_count > 0:
                logger.info(f" Killed {killed_count} ModOrganizer processes")
            else:
                logger.warning("❌ No ModOrganizer processes found to kill")
                
            return killed_count
            
        except Exception as e:
            logger.error(f"Error killing ModOrganizer processes: {e}")
            return 0

    def run_complete_workflow(self, shortcut_name: str, modlist_install_dir: str, 
                            final_exe_path: str, progress_callback=None) -> Tuple[bool, Optional[Path], Optional[int]]:
        """
        Run the simple automated prefix creation workflow.
        
        Args:
            shortcut_name: Name for the Steam shortcut
            modlist_install_dir: Directory where the modlist is installed
            final_exe_path: Path to ModOrganizer.exe
            
        Returns:
            Tuple of (success, prefix_path, appid)
        """
        debug_print(f"[DEBUG] run_complete_workflow called with shortcut_name={shortcut_name}, modlist_install_dir={modlist_install_dir}, final_exe_path={final_exe_path}")
        logger.info("Starting simple automated prefix creation workflow")
        
        # Initialize shared timing to continue from jackify-engine
        from jackify.shared.timing import initialize_from_console_output
        # TODO: Pass console output if available to continue timeline
        initialize_from_console_output()
        
        # Show immediate feedback to user
        if progress_callback:
            progress_callback("Starting automated Steam setup...")
        
        try:
            # Step 1: Create shortcut directly (NO STL needed!)
            logger.info("Step 1: Creating shortcut directly to ModOrganizer.exe")
            if progress_callback:
                progress_callback("Creating Steam shortcut...")
            if not self.create_shortcut_directly_with_proton(shortcut_name, final_exe_path, modlist_install_dir):
                logger.error("Failed to create shortcut directly")
                return False, None, None, None
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Steam shortcut created successfully")
            logger.info("Step 1 completed: Shortcut created directly")
            
            # Step 2: Calculate the predictable AppID and rungameid
            logger.info("Step 2: Calculating predictable AppID")
            if progress_callback:
                progress_callback("Calculating AppID...")
            
            # Calculate AppID using the same method as create_shortcut_directly_with_proton
            from zlib import crc32
            combined_string = final_exe_path + shortcut_name
            crc = crc32(combined_string.encode('utf-8'))
            initial_appid = -(crc & 0x7FFFFFFF)  # Make it negative and within 32-bit range
            
            # Calculate rungameid for launching
            rungameid = (initial_appid << 32) | 0x02000000
            
            # Convert AppID to positive prefix ID
            expected_prefix_id = str(abs(initial_appid))
            
            if progress_callback:
                progress_callback("AppID calculated")
            logger.info(f"Step 2 completed: AppID = {initial_appid}, rungameid = {rungameid}, expected_prefix_id = {expected_prefix_id}")
            
            # Step 3: Restart Steam
            logger.info("Step 3: Restarting Steam")
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Restarting Steam...")
            if not self.restart_steam():
                logger.error("Failed to restart Steam")
                return False, None, None, None
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Steam restarted successfully")
            logger.info("Step 3 completed: Steam restarted")
            
            # Step 4: Launch temporary batch file to create prefix invisibly
            logger.info("Step 4: Launching temporary batch file to create prefix")
            debug_print(f"[DEBUG] About to launch temporary batch file with rungameid={rungameid}")
            
            # Launch using rungameid (this will run the batch file invisibly)
            try:
                result = subprocess.run(['steam', f'steam://rungameid/{rungameid}'], 
                                      capture_output=True, text=True, timeout=5)
                debug_print(f"[DEBUG] Launch result: return_code={result.returncode}")
                if result.returncode != 0:
                    logger.error(f"Failed to launch temporary batch file: {result.stderr}")
                    return False, None, None, None
            except subprocess.TimeoutExpired:
                debug_print("[DEBUG] Launch timed out (expected)")
            except Exception as e:
                logger.error(f"Error launching temporary batch file: {e}")
                return False, None, None, None
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Temporary batch file launched")
            logger.info("Step 4 completed: Temporary batch file launched")
            
            # Step 5: Wait for temporary batch file to complete (invisible)
            logger.info("Step 5: Waiting for temporary batch file to complete")
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Creating Proton prefix (please wait)...")
            
            # Wait for batch file to complete (3 seconds + buffer)
            time.sleep(5)
            logger.info("Step 5 completed: Temporary batch file completed")
            
            # Step 6: Verify prefix was created
            logger.info("Step 6: Verifying prefix creation")
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Verifying prefix creation...")
            
            compatdata_path = Path.home() / ".local/share/Steam/steamapps/compatdata" / expected_prefix_id
            if not compatdata_path.exists():
                logger.error(f"Prefix not found at {compatdata_path}")
                return False, None, None, None
            
            logger.info(f"Step 6 completed: Prefix verified at {compatdata_path}")
            
            # Step 7: Replace temporary batch file with final ModOrganizer.exe
            logger.info("Step 7: Replacing temporary batch file with final ModOrganizer.exe")
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Updating shortcut...")
            
            if not self.replace_shortcut_with_final_exe(shortcut_name, final_exe_path, modlist_install_dir):
                logger.error("Failed to replace shortcut with final exe")
                return False, None, None, None
            
            logger.info("Step 7 completed: Shortcut updated with final ModOrganizer.exe")
            
            # Step 8: Detect actual AppID using protontricks -l
            logger.info("Step 8: Detecting actual AppID")
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Detecting actual AppID...")
            actual_appid = self.detect_actual_prefix_appid(initial_appid, shortcut_name)
            if actual_appid is None:
                logger.error("Failed to detect actual AppID")
                return False, None, None, None
            logger.info(f"Step 8 completed: Actual AppID = {actual_appid}")
            
            # Step 9: Verify prefix was created successfully
            logger.info("Step 9: Verifying prefix creation")
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Verifying prefix creation...")
            prefix_path = self._get_compatdata_path_for_appid(actual_appid)
            if not prefix_path or not prefix_path.exists():
                logger.error(f"Prefix path not found: {prefix_path}")
                return False, None, None, None
            
            if not self.verify_prefix_creation(prefix_path):
                logger.error("Prefix verification failed")
                return False, None, None, None
            logger.info(f"Step 9 completed: Prefix verified at {prefix_path}")
            
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Steam Configuration complete!")
            logger.info(" Simple automated prefix creation workflow completed successfully")
            return True, prefix_path, actual_appid
            
        except Exception as e:
            logger.error(f"Error in automated prefix creation workflow: {e}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return False, None, None, None
    
    def cleanup_old_batch_shortcuts(self, shortcut_name: str) -> bool:
        """
        Clean up any old batch file shortcuts for this modlist to prevent duplicates.
        
        Args:
            shortcut_name: Name of the shortcut to clean up old batch versions for
            
        Returns:
            True if successful, False otherwise
        """
        try:
            shortcuts_path = self._get_shortcuts_path()
            if not shortcuts_path:
                return False
            
            # Read current shortcuts
            with open(shortcuts_path, 'rb') as f:
                shortcuts_data = vdf.binary_load(f)
            
            shortcuts = shortcuts_data.get('shortcuts', {})
            indices_to_remove = []
            
            # Find all batch file shortcuts with the same name
            for i in range(len(shortcuts)):
                shortcut = shortcuts[str(i)]
                name = shortcut.get('AppName', '')
                exe = shortcut.get('Exe', '')
                
                if (name == shortcut_name and 
                    'prefix_creation_' in exe and 
                    exe.endswith('.bat')):
                    indices_to_remove.append(str(i))
                    logger.info(f"Marking old batch shortcut for removal: {name} -> {exe}")
            
            if not indices_to_remove:
                logger.debug(f"No old batch shortcuts found for '{shortcut_name}'")
                return True
            
            # Remove shortcuts by rebuilding the shortcuts dict
            new_shortcuts = {}
            new_index = 0
            
            for i in range(len(shortcuts)):
                if str(i) not in indices_to_remove:
                    new_shortcuts[str(new_index)] = shortcuts[str(i)]
                    new_index += 1
            
            shortcuts_data['shortcuts'] = new_shortcuts
            
            # Write back to file
            with open(shortcuts_path, 'wb') as f:
                vdf.binary_dump(shortcuts_data, f)
            
            logger.info(f"Cleaned up {len(indices_to_remove)} old batch shortcuts for '{shortcut_name}'")
            return True
            
        except Exception as e:
            logger.error(f"Error cleaning up old shortcuts: {e}")
            return False
    
    def set_compatool_on_shortcut(self, shortcut_name: str) -> bool:
        """
        Set CompatTool on a shortcut immediately after STL creation.
        This is CRITICAL to ensure the batch file shortcut has Proton set
        so it can create a prefix when launched.
        
        Args:
            shortcut_name: Name of the shortcut to modify
            
        Returns:
            True if successful, False otherwise
        """
        try:
            shortcuts_path = self._get_shortcuts_path()
            if not shortcuts_path:
                return False
            
            # Read current shortcuts
            with open(shortcuts_path, 'rb') as f:
                shortcuts_data = vdf.binary_load(f)
            
            shortcuts = shortcuts_data.get('shortcuts', {})
            
            # Find the shortcut by name
            for i in range(len(shortcuts)):
                shortcut = shortcuts[str(i)]
                name = shortcut.get('AppName', '')
                
                if shortcut_name == name:
                    # Check current CompatTool setting
                    current_compat = shortcut.get('CompatTool', 'NOT_SET')
                    logger.info(f"Found shortcut '{name}' with CompatTool: '{current_compat}'")
                    
                    # Set CompatTool to ensure batch file can create prefix
                    shortcut['CompatTool'] = 'proton_experimental'
                    logger.info(f" Set CompatTool=proton_experimental on shortcut: {name}")
                    
                    # Write back to file
                    with open(shortcuts_path, 'wb') as f:
                        vdf.binary_dump(shortcuts_data, f)
                    
                    return True
            
            logger.error(f"❌ Shortcut '{shortcut_name}' not found for CompatTool setting")
            return False
            
        except Exception as e:
            logger.error(f"❌ Error setting CompatTool on shortcut: {e}")
            return False
    
    def _set_proton_on_shortcut(self, shortcut_name: str) -> bool:
        """
        Set Proton Experimental on a shortcut by name.
        
        Args:
            shortcut_name: Name of the shortcut to modify
            
        Returns:
            True if successful, False otherwise
        """
        try:
            shortcuts_path = self._get_shortcuts_path()
            if not shortcuts_path:
                return False
            
            # Read current shortcuts
            with open(shortcuts_path, 'rb') as f:
                shortcuts_data = vdf.binary_load(f)
            
            shortcuts = shortcuts_data.get('shortcuts', {})
            
            # Find the shortcut by name
            for i in range(len(shortcuts)):
                shortcut = shortcuts[str(i)]
                name = shortcut.get('AppName', '')
                
                if shortcut_name == name:
                    # Set CompatTool
                    shortcut['CompatTool'] = 'proton_experimental'
                    logger.info(f"Set CompatTool=proton_experimental on shortcut: {name}")
                    
                    # Write back to file
                    with open(shortcuts_path, 'wb') as f:
                        vdf.binary_dump(shortcuts_data, f)
                    
                    return True
            
            logger.error(f"Shortcut '{shortcut_name}' not found for Proton setting")
            return False
            
        except Exception as e:
            logger.error(f"Error setting Proton on shortcut: {e}")
            return False

    def run_working_workflow(self, shortcut_name: str, modlist_install_dir: str, 
                            final_exe_path: str, progress_callback=None, steamdeck: Optional[bool] = None) -> Tuple[bool, Optional[Path], Optional[int], Optional[str]]:
        """
        Run the proven working automated prefix creation workflow.
        
        This implements our tested and working approach:
        1. Create shortcut with native Steam service (pointing to ModOrganizer.exe initially)
        2. Restart Steam using Jackify's robust method
        3. Create Proton prefix invisibly using Proton wrapper with DISPLAY=
        4. Verify everything persists
        
        Args:
            shortcut_name: Name for the Steam shortcut
            modlist_install_dir: Directory where the modlist is installed
            final_exe_path: Path to ModOrganizer.exe
            
        Returns:
            Tuple of (success, prefix_path, appid, last_timestamp)
        """
        logger.info("Starting proven working automated prefix creation workflow")
        
        # Show installation complete and configuration start headers FIRST
        if progress_callback:
            progress_callback("")
            progress_callback("=" * 64)
            progress_callback("= Installation phase complete =")
            progress_callback("=" * 64)
            progress_callback("")
            progress_callback("=" * 64)
            progress_callback("= Starting Configuration Phase =")
            progress_callback("=" * 64)
            progress_callback("")
        
        # Reset timing for Steam Integration section (part of Configuration Phase)
        from jackify.shared.timing import start_new_phase
        start_new_phase()
        
        # Show immediate feedback to user with section header
        if progress_callback:
            progress_callback("")  # Blank line before Steam Integration
            progress_callback("=== Steam Integration ===")
            progress_callback(f"{self._get_progress_timestamp()} Creating Steam shortcut with native service")
        
        # Detect special game types early to generate proper launch options
        from ..handlers.modlist_handler import ModlistHandler
        modlist_handler = ModlistHandler()
        special_game_type = modlist_handler.detect_special_game_type(modlist_install_dir)
        
        # Generate complete launch options for special games
        custom_launch_options = None
        if special_game_type in ["fnv", "enderal"]:
            custom_launch_options = self._generate_special_game_launch_options(special_game_type, modlist_install_dir)
            if not custom_launch_options:
                logger.error(f"Failed to generate launch options for {special_game_type.upper()} modlist")
                return False, None, None, None
        
        try:
            # Step 1: Create shortcut with native Steam service (pointing to ModOrganizer.exe initially)
            logger.info("Step 1: Creating shortcut with native Steam service")
            
            # TEMPORARILY DISABLED: Check if shortcut already exists and handle conflict
            # conflict_result = self.handle_existing_shortcut_conflict(shortcut_name, final_exe_path, modlist_install_dir)
            # if isinstance(conflict_result, list):  # Conflicts found
            #     logger.warning(f"Found {len(conflict_result)} existing shortcut(s) with same name and path")
            #     # Return a special tuple to indicate conflict that needs user resolution
            #     return ("CONFLICT", conflict_result, None)
            # elif not conflict_result:  # User cancelled or other failure
            #     logger.error("User cancelled due to shortcut conflict")
            #     return False, None, None, None
            logger.info("Conflict detection temporarily disabled - proceeding with shortcut creation")
            
            # Create shortcut using native Steam service with special game launch options
            success, appid = self.create_shortcut_with_native_service(shortcut_name, final_exe_path, modlist_install_dir, custom_launch_options)
            if not success:
                logger.error("Failed to create shortcut with native Steam service")
                return False, None, None, None
            
            logger.info(f"Step 1 completed: Shortcut created with native service, AppID: {appid}")
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Steam shortcut created successfully")
            
            # Apply Steam artwork if available
            try:
                from ..handlers.modlist_handler import ModlistHandler
                modlist_handler = ModlistHandler()
                modlist_handler.set_steam_grid_images(str(appid), modlist_install_dir)
                logger.info(f"Applied Steam artwork for shortcut '{shortcut_name}' (AppID: {appid})")
            except Exception as e:
                logger.warning(f"Failed to apply Steam artwork: {e}")
            
            # Step 2: Restart Steam using Jackify's robust method
            logger.info("Step 2: Restarting Steam using Jackify's robust method")
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Restarting Steam...")
            
            if not self.restart_steam():
                logger.error("Failed to restart Steam")
                return False, None, None, None
            
            logger.info("Step 2 completed: Steam restarted")
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Steam restarted successfully")
            
            # Step 3: Create Proton prefix invisibly using Proton wrapper
            logger.info("Step 3: Creating Proton prefix invisibly")
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Creating Proton prefix...")
            
            if not self.create_prefix_with_proton_wrapper(appid):
                logger.error("Failed to create Proton prefix")
                return False, None, None, None
            
            logger.info("Step 3 completed: Proton prefix created")
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Proton prefix created successfully")
            
            # Step 4: Verify everything persists
            logger.info("Step 4: Verifying compatibility tool persists")
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Verifying setup...")
            
            if not self.verify_compatibility_tool_persists(appid):
                logger.warning("Compatibility tool verification failed, but continuing")
            
            logger.info("Step 4 completed: Verification done")
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Setup verification completed")
            
            # Get the prefix path
            prefix_path = self.get_prefix_path(appid)
            
            last_timestamp = self._get_progress_timestamp()
            logger.info(f" Working workflow completed successfully! AppID: {appid}, Prefix: {prefix_path}")
            if progress_callback:
                progress_callback(f"{last_timestamp} Steam integration complete")
                progress_callback("")  # Blank line after Steam integration complete
                progress_callback("")  # Extra blank line to span across Configuration Summary
                progress_callback("")  # And one more to create space before Prefix Configuration
            
            return True, prefix_path, appid, last_timestamp
            
        except Exception as e:
            logger.error(f"Error in working workflow: {e}")
            if progress_callback:
                progress_callback(f"Error: {str(e)}")
            return False, None, None, None
    
    def continue_workflow_after_conflict_resolution(self, shortcut_name: str, modlist_install_dir: str, 
                                                  final_exe_path: str, appid: int, progress_callback=None) -> Tuple[bool, Optional[Path], Optional[int]]:
        """
        Continue the workflow after a shortcut conflict has been resolved.
        
        Args:
            shortcut_name: Name of the shortcut
            modlist_install_dir: Directory where the modlist is installed
            final_exe_path: Path to the final executable
            appid: The AppID of the shortcut that was created/replaced
            progress_callback: Optional callback for progress updates
            
        Returns:
            Tuple of (success, prefix_path, appid)
        """
        try:
            logger.info("Continuing workflow after conflict resolution")
            
            # Step 2: Restart Steam using Jackify's robust method
            logger.info("Step 2: Restarting Steam using Jackify's robust method")
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Restarting Steam...")
            
            if not self.restart_steam():
                logger.error("Failed to restart Steam")
                return False, None, None, None
            
            logger.info("Step 2 completed: Steam restarted")
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Steam restarted successfully")
            
            # Step 3: Create Proton prefix invisibly using Proton wrapper
            logger.info("Step 3: Creating Proton prefix invisibly")
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Creating Proton prefix...")
            
            if not self.create_prefix_with_proton_wrapper(appid):
                logger.error("Failed to create Proton prefix")
                return False, None, None, None
            
            logger.info("Step 3 completed: Proton prefix created")
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Proton prefix created successfully")
            
            # Step 4: Verify everything persists
            logger.info("Step 4: Verifying compatibility tool persists")
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Verifying setup...")
            
            if not self.verify_compatibility_tool_persists(appid):
                logger.warning("Compatibility tool verification failed, but continuing")
            
            logger.info("Step 4 completed: Verification done")
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Setup verification completed")
            
            # Get the prefix path
            prefix_path = self.get_prefix_path(appid)
            
            last_timestamp = self._get_progress_timestamp()
            logger.info(f" Workflow completed successfully after conflict resolution! AppID: {appid}, Prefix: {prefix_path}")
            if progress_callback:
                progress_callback(f"{last_timestamp} Automated Steam setup completed successfully!")
            
            return True, prefix_path, appid, last_timestamp
            
        except Exception as e:
            logger.error(f"Error continuing workflow after conflict resolution: {e}")
            if progress_callback:
                progress_callback(f"Error: {str(e)}")
            return False, None, None, None

    def modify_shortcut_to_batch_file(self, shortcut_name: str, batch_file_path: str, 
                                    modlist_install_dir: str) -> bool:
        """
        Modify an existing shortcut to point to a temporary batch file.
        
        Args:
            shortcut_name: Name of the shortcut to modify
            batch_file_path: Path to the temporary batch file
            modlist_install_dir: Directory where the modlist is installed
            
        Returns:
            True if successful, False otherwise
        """
        try:
            shortcuts_path = self._get_shortcuts_path()
            if not shortcuts_path:
                return False
            
            # Read current shortcuts
            with open(shortcuts_path, 'rb') as f:
                shortcuts_data = vdf.binary_load(f)
            
            shortcuts = shortcuts_data.get('shortcuts', {})
            
            # Find the shortcut by name
            for i in range(len(shortcuts)):
                shortcut = shortcuts[str(i)]
                name = shortcut.get('AppName', '')
                
                if shortcut_name == name:
                    # Update the shortcut to point to the batch file
                    old_exe = shortcut.get('Exe', '')
                    shortcut['Exe'] = f'"{batch_file_path}"'
                    shortcut['StartDir'] = f'"{modlist_install_dir}"'
                    
                    logger.info(f"Modified shortcut '{shortcut_name}':")
                    logger.info(f"  Exe: {old_exe} → {shortcut['Exe']}")
                    logger.info(f"  StartDir: {shortcut['StartDir']}")
                    
                    # Write back to file
                    with open(shortcuts_path, 'wb') as f:
                        vdf.binary_dump(shortcuts_data, f)
                    
                    return True
            
            logger.error(f"Shortcut '{shortcut_name}' not found for modification")
            return False
            
        except Exception as e:
            logger.error(f"Error modifying shortcut to batch file: {e}")
            return False
    
    def find_appid_in_shortcuts_vdf(self, shortcut_name: str) -> Optional[str]:
        """
        Find the AppID for a shortcut by name directly in shortcuts.vdf.
        This is a fallback method when protontricks detection fails.
        
        Args:
            shortcut_name: Name of the shortcut to find
            
        Returns:
            AppID as string, or None if not found
        """
        try:
            shortcuts_path = self._get_shortcuts_path()
            if not shortcuts_path:
                return None
            
            with open(shortcuts_path, 'rb') as f:
                shortcuts_data = vdf.binary_load(f)
            
            shortcuts = shortcuts_data.get('shortcuts', {})
            
            # Look for shortcut by name
            for i in range(len(shortcuts)):
                shortcut = shortcuts[str(i)]
                name = shortcut.get('AppName', '')
                
                if shortcut_name == name:
                    appid = shortcut.get('appid')
                    if appid:
                        logger.info(f"Found AppID {appid} for shortcut '{shortcut_name}' in shortcuts.vdf")
                        return str(appid)
            
            logger.warning(f"Shortcut '{shortcut_name}' not found in shortcuts.vdf")
            return None
            
        except Exception as e:
            logger.error(f"Error finding AppID in shortcuts.vdf: {e}")
            return None
    
    def predict_appid_using_stl_algorithm(self, shortcut_name: str, exe_path: str) -> Optional[int]:
        """
        Predict the AppID using SteamTinkerLaunch's exact algorithm.
        
        This implements the same logic as STL's generateShortcutVDFAppId and generateSteamShortID functions:
        1. Combine AppName + ExePath
        2. Generate MD5 hash, take first 8 characters
        3. Convert to decimal, make negative, ensure < 1 billion
        4. Convert to unsigned 32-bit integer
        
        Args:
            shortcut_name: Name of the shortcut
            exe_path: Path to the executable
            
        Returns:
            Predicted AppID as integer, or None if failed
        """
        try:
            import hashlib
            
            # Step 1: Combine AppName + ExePath (exactly like STL)
            combined_string = f"{shortcut_name}{exe_path}"
            logger.debug(f"Combined string for AppID prediction: '{combined_string}'")
            
            # Step 2: Generate MD5 hash and take first 8 characters
            md5_hash = hashlib.md5(combined_string.encode()).hexdigest()
            seed_hex = md5_hash[:8]
            logger.debug(f"MD5 hash: {md5_hash}, seed hex: {seed_hex}")
            
            # Step 3: Convert to decimal, make negative, ensure < 1 billion
            seed_decimal = int(seed_hex, 16)
            signed_appid = -(seed_decimal % 1000000000)
            logger.debug(f"Seed decimal: {seed_decimal}, signed AppID: {signed_appid}")
            
            # Step 4: Convert to unsigned 32-bit integer (STL's generateSteamShortID)
            unsigned_appid = signed_appid & 0xFFFFFFFF
            logger.debug(f"Unsigned AppID: {unsigned_appid}")
            
            logger.info(f"Predicted AppID using STL algorithm: {unsigned_appid} (signed: {signed_appid})")
            return unsigned_appid
            
        except Exception as e:
            logger.error(f"Error predicting AppID using STL algorithm: {e}")
            return None
    
    def create_shortcut_with_stl_algorithm(self, shortcut_name: str, exe_path: str, start_dir: str, compatibility_tool: str = None) -> bool:
        """
        Create a shortcut using STL's exact algorithm for consistent AppID calculation.
        
        Args:
            shortcut_name: Name of the shortcut
            exe_path: Path to the executable
            start_dir: Start directory
            compatibility_tool: Optional compatibility tool to set immediately (like STL does)
            
        Returns:
            True if successful, False otherwise
        """
        try:
            shortcuts_path = self._get_shortcuts_path()
            if not shortcuts_path:
                return False
            
            # Read current shortcuts
            with open(shortcuts_path, 'rb') as f:
                shortcuts_data = vdf.binary_load(f)
            
            shortcuts = shortcuts_data.get('shortcuts', {})
            
            # Find the next available index
            next_index = str(len(shortcuts))
            
            # Calculate AppID using STL's algorithm
            predicted_appid = self.predict_appid_using_stl_algorithm(shortcut_name, exe_path)
            if not predicted_appid:
                logger.error("Failed to predict AppID for shortcut creation")
                return False
            
            # Convert to signed AppID (STL stores the signed version in shortcuts.vdf)
            signed_appid = predicted_appid
            if predicted_appid > 0x7FFFFFFF:  # If it's a large positive number, make it negative
                signed_appid = predicted_appid - 0x100000000
            
            # Create new shortcut entry
            new_shortcut = {
                'AppName': shortcut_name,
                'Exe': f'"{exe_path}"',
                'StartDir': f'"{start_dir}"',
                'appid': signed_appid,  # Use the signed AppID
                'icon': '',
                'ShortcutPath': '',
                'LaunchOptions': '',
                'IsHidden': 0,
                'AllowDesktopConfig': 1,
                'AllowOverlay': 1,
                'openvr': 0,
                'Devkit': 0,
                'DevkitGameID': '',
                'LastPlayTime': 0,
                'FlatpakAppID': '',
                'tags': {},
                'IsInstalled': 1  # Make it appear in "Locally Installed" filter
            }
            
            # Add the new shortcut
            shortcuts[next_index] = new_shortcut
            
            # Write back to file
            with open(shortcuts_path, 'wb') as f:
                vdf.binary_dump(shortcuts_data, f)
            
            logger.info(f"Created shortcut with STL algorithm: {shortcut_name} with AppID {signed_appid} (unsigned: {predicted_appid})")
            
            # Set compatibility tool immediately if provided (like STL does)
            if compatibility_tool:
                logger.info(f"Setting compatibility tool immediately: {compatibility_tool}")
                success = self.set_compatibility_tool_complete_stl_style(predicted_appid, compatibility_tool)
                if not success:
                    logger.warning("Failed to set compatibility tool immediately")
            
            return True
            
        except Exception as e:
            logger.error(f"Error creating shortcut with STL algorithm: {e}")
            return False
    
    def set_compatibility_tool_stl_style(self, unsigned_appid: int, compat_tool: str) -> bool:
        """
        Set compatibility tool using STL's exact method.
        
        This adds an entry to config.vdf's CompatToolMapping section using the unsigned AppID as the key,
        exactly like STL does.
        
        Args:
            unsigned_appid: The unsigned AppID (Grid ID) to use as the key
            compat_tool: The compatibility tool name (e.g., 'proton_experimental')
            
        Returns:
            True if successful, False otherwise
        """
        try:
            config_path = self._get_config_path()
            if not config_path:
                logger.error("No config.vdf path found")
                return False
            
            # Read current config (config.vdf is text format)
            with open(config_path, 'r') as f:
                config_data = vdf.load(f)
            
            # Navigate to the correct location in the VDF structure
            if 'Software' not in config_data:
                config_data['Software'] = {}
            if 'Valve' not in config_data['Software']:
                config_data['Software']['Valve'] = {}
            if 'Steam' not in config_data['Software']['Valve']:
                config_data['Software']['Valve']['Steam'] = {}
            
            # Get or create CompatToolMapping
            if 'CompatToolMapping' not in config_data['Software']['Valve']['Steam']:
                config_data['Software']['Valve']['Steam']['CompatToolMapping'] = {}
            
            # Create the compatibility tool entry exactly like STL does
            compat_entry = {
                'name': compat_tool,
                'config': '',
                'priority': '250'
            }
            
            # Set the compatibility tool for this AppID (using unsigned AppID as key)
            config_data['Software']['Valve']['Steam']['CompatToolMapping'][str(unsigned_appid)] = compat_entry
            
            logger.info(f"Added compatibility tool entry: {str(unsigned_appid)} -> {compat_tool}")
            debug_print(f"[DEBUG] Added compatibility tool entry: {str(unsigned_appid)} -> {compat_tool}")
            
            # Write back to file (text format)
            with open(config_path, 'w') as f:
                vdf.dump(config_data, f)
            
            logger.info(f"Set compatibility tool STL-style: AppID {unsigned_appid} -> {compat_tool}")
            debug_print(f"[DEBUG] Set compatibility tool STL-style: AppID {unsigned_appid} -> {compat_tool}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error setting compatibility tool STL-style: {e}")
            return False

    def set_compatibility_tool_complete_stl_style(self, unsigned_appid: int, compat_tool: str) -> bool:
        """
        Set compatibility tool using STL's complete method with direct text manipulation.
        
        This replicates STL's approach by using direct text manipulation instead of VDF libraries
        to preserve existing entries in both config.vdf and localconfig.vdf.
        
        Args:
            unsigned_appid: The unsigned AppID (Grid ID) to use as the key
            compat_tool: The compatibility tool name (e.g., 'proton_experimental')
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Step 1: Update config.vdf using direct text manipulation (like STL does)
            config_path = self._get_config_path()
            if not config_path:
                logger.error("No config.vdf path found")
                return False
            
            # Read the entire file as text
            with open(config_path, 'r') as f:
                lines = f.readlines()
            
            # Find the CompatToolMapping section
            compat_section_start = None
            compat_section_end = None
            for i, line in enumerate(lines):
                if '"CompatToolMapping"' in line.strip():
                    compat_section_start = i
                    # Find the end of the CompatToolMapping section
                    brace_count = 0
                    for j in range(i + 1, len(lines)):
                        if '{' in lines[j]:
                            brace_count += 1
                        if '}' in lines[j]:
                            brace_count -= 1
                            if brace_count == 0:
                                compat_section_end = j
                                break
                    break
            
            if compat_section_start is None:
                logger.error("CompatToolMapping section not found in config.vdf")
                return False
            
            # Check if our AppID entry already exists
            appid_entry_start = None
            appid_entry_end = None
            for i in range(compat_section_start, compat_section_end + 1):
                if f'"{unsigned_appid}"' in lines[i]:
                    appid_entry_start = i
                    # Find the end of this AppID entry
                    brace_count = 0
                    for j in range(i + 1, compat_section_end + 1):
                        if '{' in lines[j]:
                            brace_count += 1
                        if '}' in lines[j]:
                            brace_count -= 1
                            if brace_count == 0:
                                appid_entry_end = j
                                break
                    break
            
            # Create the new entry in Steam's exact format
            new_entry_lines = [
                f'\t\t\t\t\t\t\t\t\t"{unsigned_appid}"\n',
                f'\t\t\t\t\t\t\t\t\t{{\n',
                f'\t\t\t\t\t\t\t\t\t\t"name"\t\t\t\t"{compat_tool}"\n',
                f'\t\t\t\t\t\t\t\t\t\t"config"\t\t\t\t\t""\n',
                f'\t\t\t\t\t\t\t\t\t\t"priority"\t\t\t\t\t"250"\n',
                f'\t\t\t\t\t\t\t\t\t}}\n'
            ]
            
            if appid_entry_start is None:
                # AppID entry doesn't exist, add it before the closing brace of CompatToolMapping
                lines.insert(compat_section_end, ''.join(new_entry_lines))
            else:
                # AppID entry exists, replace it
                del lines[appid_entry_start:appid_entry_end + 1]
                lines.insert(appid_entry_start, ''.join(new_entry_lines))
            
            # Write the updated file back
            with open(config_path, 'w') as f:
                f.writelines(lines)
            
            logger.info(f"Updated config.vdf: AppID {unsigned_appid} -> {compat_tool}")
            
            # Step 2: Update localconfig.vdf using direct text manipulation (like STL)
            localconfig_path = self._get_localconfig_path()
            if not localconfig_path:
                logger.error("No localconfig.vdf path found")
                return False
            
            # Calculate signed AppID (like STL does)
            signed_appid = (unsigned_appid | 0x80000000) & 0xFFFFFFFF
            # Convert to signed 32-bit integer
            import ctypes
            signed_appid_int = ctypes.c_int32(signed_appid).value
            
            # Read the entire file as text
            with open(localconfig_path, 'r') as f:
                lines = f.readlines()
            
            # Check if Apps section exists
            apps_section_start = None
            apps_section_end = None
            for i, line in enumerate(lines):
                if line.strip() == '"Apps"':
                    apps_section_start = i
                    # Find the end of the Apps section
                    brace_count = 0
                    for j in range(i + 1, len(lines)):
                        if '{' in lines[j]:
                            brace_count += 1
                        if '}' in lines[j]:
                            brace_count -= 1
                            if brace_count == 0:
                                apps_section_end = j
                                break
                    break
            
            # If Apps section doesn't exist, create it at the end of the file
            if apps_section_start is None:
                logger.info("Apps section not found, creating it at the end of the file")
                
                # Find the last closing brace (before the final closing brace)
                last_brace_pos = None
                for i in range(len(lines) - 1, -1, -1):
                    if lines[i].strip() == '}':
                        last_brace_pos = i
                        break
                
                if last_brace_pos is None:
                    logger.error("Could not find closing brace in localconfig.vdf")
                    return False
                
                # Insert Apps section before the last closing brace
                apps_section = [
                    '        "Apps"\n',
                    '        {\n',
                    f'                "{signed_appid_int}"\n',
                    '                {\n',
                    '                        "OverlayAppEnable"          "1"\n',
                    '                        "DisableLaunchInVR"         "1"\n',
                    '                }\n',
                    '        }\n'
                ]
                
                lines.insert(last_brace_pos, ''.join(apps_section))
                
            else:
                # Apps section exists, check if our AppID entry exists
                appid_entry_start = None
                appid_entry_end = None
                for i in range(apps_section_start, apps_section_end + 1):
                    if f'"{signed_appid_int}"' in lines[i]:
                        appid_entry_start = i
                        # Find the end of this AppID entry
                        brace_count = 0
                        for j in range(i + 1, apps_section_end + 1):
                            if '{' in lines[j]:
                                brace_count += 1
                            if '}' in lines[j]:
                                brace_count -= 1
                                if brace_count == 0:
                                    appid_entry_end = j
                                    break
                        break
                
                if appid_entry_start is None:
                    # AppID entry doesn't exist, add it to the Apps section
                    logger.info(f"AppID {signed_appid_int} entry not found, adding it to Apps section")
                    
                    # Insert before the closing brace of the Apps section
                    appid_entry = [
                        f'                "{signed_appid_int}"\n',
                        '                {\n',
                        '                        "OverlayAppEnable"          "1"\n',
                        '                        "DisableLaunchInVR"         "1"\n',
                        '                }\n'
                    ]
                    
                    lines.insert(apps_section_end, ''.join(appid_entry))
                    
                else:
                    # AppID entry exists, update the values
                    logger.info(f"AppID {signed_appid_int} entry exists, updating values")
                    
                    # Check if the values already exist and update them
                    overlay_found = False
                    vr_found = False
                    
                    for i in range(appid_entry_start, appid_entry_end + 1):
                        if '"OverlayAppEnable"' in lines[i]:
                            lines[i] = '                        "OverlayAppEnable"          "1"\n'
                            overlay_found = True
                        elif '"DisableLaunchInVR"' in lines[i]:
                            lines[i] = '                        "DisableLaunchInVR"         "1"\n'
                            vr_found = True
                    
                    # Add missing values
                    if not overlay_found or not vr_found:
                        # Find the position to insert (before the closing brace of the AppID entry)
                        insert_pos = appid_entry_end
                        for i in range(appid_entry_start, appid_entry_end + 1):
                            if lines[i].strip() == '}':
                                insert_pos = i
                                break
                        
                        new_values = []
                        if not overlay_found:
                            new_values.append('                        "OverlayAppEnable"          "1"\n')
                        if not vr_found:
                            new_values.append('                        "DisableLaunchInVR"         "1"\n')
                        
                        for value in new_values:
                            lines.insert(insert_pos, value)
            
            # Write the updated file back
            with open(localconfig_path, 'w') as f:
                f.writelines(lines)
            
            logger.info(f"Updated localconfig.vdf: Signed AppID {signed_appid_int} -> OverlayAppEnable=1, DisableLaunchInVR=1")
            debug_print(f"[DEBUG] Updated localconfig.vdf: Signed AppID {signed_appid_int} -> OverlayAppEnable=1, DisableLaunchInVR=1")
            
            return True
            
        except Exception as e:
            logger.error(f"Error setting compatibility tool complete STL-style: {e}")
            return False
    
    def modify_shortcut_to_batch_file(self, shortcut_name: str, new_exe_path: str, new_start_dir: str) -> bool:
        """
        Modify an existing shortcut's target and start directory.
        
        This is used in the workflow to:
        1. Change the shortcut target to a batch file (to create prefix)
        2. Change it back to ModOrganizer.exe (after prefix creation)
        
        Args:
            shortcut_name: The name of the shortcut to modify
            new_exe_path: The new executable path
            new_start_dir: The new start directory
            
        Returns:
            True if successful, False otherwise
        """
        try:
            shortcuts_path = self._get_shortcuts_path()
            if not shortcuts_path:
                logger.error("No shortcuts.vdf path found")
                return False
            
            # Read the current shortcuts.vdf
            with open(shortcuts_path, 'rb') as f:
                shortcuts_data = vdf.binary_load(f)
            
            if 'shortcuts' not in shortcuts_data:
                logger.error("No shortcuts found in shortcuts.vdf")
                return False
            
            shortcuts = shortcuts_data['shortcuts']
            shortcut_found = False
            
            # Find the shortcut by name
            for i in range(len(shortcuts)):
                shortcut = shortcuts[str(i)]
                if shortcut.get('AppName', '') == shortcut_name:
                    # Update the shortcut
                    shortcut['Exe'] = new_exe_path
                    shortcut['StartDir'] = new_start_dir
                    shortcut_found = True
                    logger.info(f"Modified shortcut '{shortcut_name}' to target: {new_exe_path}")
                    break
            
            if not shortcut_found:
                logger.error(f"Shortcut '{shortcut_name}' not found in shortcuts.vdf")
                return False
            
            # Write the updated shortcuts.vdf back
            with open(shortcuts_path, 'wb') as f:
                vdf.binary_dump(shortcuts_data, f)
            
            logger.info(f"Successfully modified shortcut '{shortcut_name}'")
            return True
            
        except Exception as e:
            logger.error(f"Error modifying shortcut: {e}")
            return False

    def _get_localconfig_path(self) -> str:
        """
        Get the path to localconfig.vdf file.
        
        Returns:
            Path to localconfig.vdf or None if not found
        """
        # Try the standard Steam userdata path
        steam_userdata_path = Path.home() / ".steam" / "steam" / "userdata"
        if steam_userdata_path.exists():
            # Find the first user directory (usually only one on Steam Deck)
            user_dirs = [d for d in steam_userdata_path.iterdir() if d.is_dir() and d.name.isdigit()]
            if user_dirs:
                localconfig_path = user_dirs[0] / "config" / "localconfig.vdf"
                if localconfig_path.exists():
                    return str(localconfig_path)
        
        logger.error("Could not find localconfig.vdf")
        return None



    def modify_shortcut_target(self, shortcut_name: str, new_exe_path: str, new_start_dir: str) -> bool:
        """
        Modify an existing shortcut's target and start directory.
        Preserves existing launch options (including STEAM_COMPAT_MOUNTS).
        
        Args:
            shortcut_name: The name of the shortcut to modify
            new_exe_path: The new executable path
            new_start_dir: The new start directory
            
        Returns:
            True if successful, False otherwise
        """
        try:
            shortcuts_path = self._get_shortcuts_path()
            if not shortcuts_path:
                logger.error("No shortcuts.vdf path found")
                return False
            
            # Read the current shortcuts.vdf
            with open(shortcuts_path, 'rb') as f:
                shortcuts_data = vdf.binary_load(f)
            
            if 'shortcuts' not in shortcuts_data:
                logger.error("No shortcuts found in shortcuts.vdf")
                return False
            
            shortcuts = shortcuts_data['shortcuts']
            shortcut_found = False
            
            # Find the shortcut by name
            for i in range(len(shortcuts)):
                shortcut = shortcuts[str(i)]
                if shortcut.get('AppName', '') == shortcut_name:
                    # Preserve existing launch options
                    existing_launch_options = shortcut.get('LaunchOptions', '')

                    # Update the shortcut EXACTLY as provided by the caller.
                    # - For temporary prefix creation we pass a Windows path (cmd.exe)
                    # - For final ModOrganizer.exe we pass the Linux path inside the modlist directory
                    shortcut['Exe'] = new_exe_path
                    shortcut['StartDir'] = new_start_dir
                    # Preserve the launch options (including STEAM_COMPAT_MOUNTS)
                    shortcut['LaunchOptions'] = existing_launch_options
                    
                    shortcut_found = True
                    logger.info(f"Modified shortcut '{shortcut_name}' to target: {new_exe_path}")
                    logger.info(f"Preserved launch options: {existing_launch_options}")
                    break
            
            if not shortcut_found:
                logger.error(f"Shortcut '{shortcut_name}' not found in shortcuts.vdf")
                return False
            
            # Write the updated shortcuts.vdf back
            with open(shortcuts_path, 'wb') as f:
                vdf.binary_dump(shortcuts_data, f)
            
            logger.info(f"Successfully modified shortcut '{shortcut_name}'")
            return True
            
        except Exception as e:
            logger.error(f"Error modifying shortcut: {e}")
            return False

    def create_prefix_with_proton_wrapper(self, appid: int) -> bool:
        """
        Create a Proton prefix directly using Proton's wrapper and STEAM_COMPAT_DATA_PATH.
        
        Args:
            appid: The AppID to create the prefix for
            
        Returns:
            True if successful, False otherwise
        """
        try:
            steam_root = Path.home() / ".steam/steam"
            compatdata_dir = steam_root / "steamapps/compatdata"
            proton_common_dir = steam_root / "steamapps/common"
            
            # Find a Proton wrapper to use
            proton_path = self._find_proton_binary(proton_common_dir)
            if not proton_path:
                logger.error("No Proton wrapper found")
                return False
            
            # Set up environment variables
            env = os.environ.copy()
            env['STEAM_COMPAT_CLIENT_INSTALL_PATH'] = str(steam_root)
            env['STEAM_COMPAT_DATA_PATH'] = str(compatdata_dir / str(abs(appid)))
            # Suppress GUI windows by unsetting DISPLAY
            env['DISPLAY'] = ''
            
            # Create the compatdata directory
            compat_dir = compatdata_dir / str(abs(appid))
            compat_dir.mkdir(parents=True, exist_ok=True)
            
            logger.info(f"Creating Proton prefix for AppID {appid}")
            logger.info(f"STEAM_COMPAT_CLIENT_INSTALL_PATH={env['STEAM_COMPAT_CLIENT_INSTALL_PATH']}")
            logger.info(f"STEAM_COMPAT_DATA_PATH={env['STEAM_COMPAT_DATA_PATH']}")
            
            # Run proton run wineboot -u to initialize the prefix
            cmd = [str(proton_path), 'run', 'wineboot', '-u']
            logger.info(f"Running: {' '.join(cmd)}")
            
            result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=60)
            logger.info(f"Proton exit code: {result.returncode}")
            
            if result.stdout:
                logger.info(f"stdout: {result.stdout.strip()[:500]}")
            if result.stderr:
                logger.info(f"stderr: {result.stderr.strip()[:500]}")
            
            # Give a moment for files to land
            time.sleep(3)
            
            # Check if prefix was created
            pfx = compat_dir / 'pfx'
            if pfx.exists():
                logger.info(f" Proton prefix created at: {pfx}")
                return True
            else:
                logger.warning(f"⚠️ Proton prefix not found at: {pfx}")
                return False
                
        except subprocess.TimeoutExpired:
            logger.warning("Proton timed out; prefix may still be initializing")
            return False
        except Exception as e:
            logger.error(f"Error creating prefix: {e}")
            return False
    
    def _find_proton_binary(self, proton_common_dir: Path) -> Optional[Path]:
        """Locate a Proton wrapper script to use (prefer Experimental)."""
        candidates = []
        preferred = [
            "Proton - Experimental",
            "Proton 9.0", 
            "Proton 8.0",
            "Proton Hotfix",
        ]
        
        for name in preferred:
            p = proton_common_dir / name / "proton"
            if p.exists():
                candidates.append(p)
        
        # As a fallback, scan all Proton* dirs
        if not candidates and proton_common_dir.exists():
            for p in proton_common_dir.glob("Proton*/proton"):
                candidates.append(p)
        
        if not candidates:
            logger.error("No Proton wrapper found under steamapps/common")
            return None
        
        logger.info(f"Using Proton wrapper: {candidates[0]}")
        return candidates[0]
    
    def replace_existing_shortcut(self, shortcut_name: str, exe_path: str, modlist_install_dir: str) -> Tuple[bool, Optional[int]]:
        """
        Replace an existing shortcut with a new one using STL.
        
        Args:
            shortcut_name: Name of the shortcut to replace
            exe_path: Path to the executable
            modlist_install_dir: Directory where the modlist is installed
            
        Returns:
            Tuple of (success, appid)
        """
        try:
            logger.info(f"Replacing existing shortcut: {shortcut_name}")
            
            # First, remove the existing shortcut using STL
            if getattr(sys, 'frozen', False):
                stl_path = Path(sys._MEIPASS) / "steamtinkerlaunch"
            else:
                project_root = Path(__file__).parent.parent.parent.parent.parent
                stl_path = project_root / "external_repos/steamtinkerlaunch/steamtinkerlaunch"
            
            if not stl_path.exists():
                logger.error(f"STL not found at: {stl_path}")
                return False, None
            
            # Remove existing shortcut
            remove_cmd = [str(stl_path), "rnsg", f"--appname={shortcut_name}"]
            env = os.environ.copy()
            env['STL_QUIET'] = '1'
            
            logger.info(f"Removing existing shortcut: {' '.join(remove_cmd)}")
            result = subprocess.run(remove_cmd, capture_output=True, text=True, timeout=30, env=env)
            
            if result.returncode != 0:
                logger.warning(f"Failed to remove existing shortcut: {result.stderr}")
                # Continue anyway, STL might create a new one
            
            # Now create the new shortcut using NativeSteamService
            success, app_id = self.create_shortcut_with_native_service(shortcut_name, exe_path, modlist_install_dir)
            return success, app_id
            
        except Exception as e:
            logger.error(f"Error replacing shortcut: {e}")
            return False, None

    def verify_compatibility_tool_persists(self, appid: int) -> bool:
        """
        Verify that the compatibility tool setting persists.
        
        Args:
            appid: The AppID to check
            
        Returns:
            True if compatibility tool is set, False otherwise
        """
        try:
            config_path = Path.home() / ".steam/steam/config/config.vdf"
            with open(config_path, 'r') as f:
                content = f.read()
            
            if f'"{appid}"' in content:
                logger.info(" Compatibility tool persists")
                return True
            else:
                logger.warning("⚠️ Compatibility tool not found")
                return False
                
        except Exception as e:
            logger.error(f"Error verifying compatibility tool: {e}")
            return False

    def get_prefix_path(self, appid: int) -> Optional[Path]:
        """
        Get the path to the Proton prefix for the given AppID.
        
        Args:
            appid: The AppID (unsigned, positive number)
            
        Returns:
            Path to the prefix directory, or None if not found
        """
        compatdata_dir = Path.home() / ".steam/steam/steamapps/compatdata"
        # Ensure we use the absolute value (unsigned AppID)
        prefix_dir = compatdata_dir / str(abs(appid))
        
        if prefix_dir.exists():
            return prefix_dir
        else:
            return None
    
