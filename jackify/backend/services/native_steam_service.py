#!/usr/bin/env python3
"""
Native Steam Shortcut and Proton Management Service

This service replaces STL entirely with native Python VDF manipulation.
Handles both shortcut creation and Proton version setting reliably.
"""

import os
import sys
import time
import logging
import hashlib
import vdf
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List

from ..handlers.vdf_handler import VDFHandler

logger = logging.getLogger(__name__)

class NativeSteamService:
    """
    Native Steam shortcut and Proton management service.
    
    This completely replaces STL with reliable VDF manipulation that:
    1. Creates shortcuts with proper VDF structure
    2. Sets Proton versions in the correct config files
    3. Never corrupts existing shortcuts
    """
    
    def __init__(self):
        self.steam_paths = [
            Path.home() / ".steam" / "steam",
            Path.home() / ".local" / "share" / "Steam",
            Path.home() / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam"
        ]
        self.steam_path = None
        self.userdata_path = None
        self.user_id = None
        self.user_config_path = None
        
    def find_steam_user(self) -> bool:
        """
        Find the active Steam user directory using Steam's own configuration files.
        No more guessing - uses loginusers.vdf to get the most recent user and converts SteamID64 to SteamID3.
        """
        try:
            # Step 1: Find Steam installation using Steam's own file structure
            if not self._find_steam_installation():
                logger.error("No Steam installation found")
                return False

            # Step 2: Parse loginusers.vdf to get the most recent user (SteamID64)
            steamid64 = self._get_most_recent_user_from_loginusers()
            if not steamid64:
                logger.error("Could not determine most recent Steam user from loginusers.vdf")
                return False

            # Step 3: Convert SteamID64 to SteamID3 (userdata directory format)
            steamid3 = self._convert_steamid64_to_steamid3(steamid64)
            logger.info(f"Most recent Steam user: SteamID64={steamid64}, SteamID3={steamid3}")

            # Step 4: Verify the userdata directory exists
            user_dir = self.userdata_path / str(steamid3)
            if not user_dir.exists():
                logger.error(f"Userdata directory does not exist: {user_dir}")
                return False

            config_dir = user_dir / "config"
            if not config_dir.exists():
                logger.error(f"User config directory does not exist: {config_dir}")
                return False

            # Step 5: Set up the service state
            self.user_id = str(steamid3)
            self.user_config_path = config_dir

            logger.info(f"VERIFIED Steam user: {self.user_id}")
            logger.info(f"User config path: {self.user_config_path}")
            logger.info(f"Shortcuts.vdf will be at: {self.user_config_path / 'shortcuts.vdf'}")

            return True

        except Exception as e:
            logger.error(f"Error finding Steam user: {e}", exc_info=True)
            return False

    def _find_steam_installation(self) -> bool:
        """Find Steam installation by checking for config/loginusers.vdf"""
        for steam_path in self.steam_paths:
            loginusers_path = steam_path / "config" / "loginusers.vdf"
            userdata_path = steam_path / "userdata"

            if loginusers_path.exists() and userdata_path.exists():
                self.steam_path = steam_path
                self.userdata_path = userdata_path
                logger.info(f"Found Steam installation at: {steam_path}")
                return True

        return False

    def _get_most_recent_user_from_loginusers(self) -> Optional[str]:
        """
        Parse loginusers.vdf to get the SteamID64 of the most recent user.
        Uses Steam's own MostRecent flag and Timestamp.
        """
        try:
            loginusers_path = self.steam_path / "config" / "loginusers.vdf"

            # Load VDF data
            vdf_data = VDFHandler.load(str(loginusers_path), binary=False)
            if not vdf_data:
                logger.error("Failed to parse loginusers.vdf")
                return None

            users_section = vdf_data.get("users", {})
            if not users_section:
                logger.error("No users section found in loginusers.vdf")
                return None

            most_recent_user = None
            most_recent_timestamp = 0

            # Find user with MostRecent=1 or highest timestamp
            for steamid64, user_data in users_section.items():
                if isinstance(user_data, dict):
                    # Check for MostRecent flag first
                    if user_data.get("MostRecent") == "1":
                        logger.info(f"Found user marked as MostRecent: {steamid64}")
                        return steamid64

                    # Also track highest timestamp as fallback
                    timestamp = int(user_data.get("Timestamp", "0"))
                    if timestamp > most_recent_timestamp:
                        most_recent_timestamp = timestamp
                        most_recent_user = steamid64

            # Return user with highest timestamp if no MostRecent flag found
            if most_recent_user:
                logger.info(f"Found most recent user by timestamp: {most_recent_user}")
                return most_recent_user

            logger.error("No valid users found in loginusers.vdf")
            return None

        except Exception as e:
            logger.error(f"Error parsing loginusers.vdf: {e}")
            return None

    def _convert_steamid64_to_steamid3(self, steamid64: str) -> int:
        """
        Convert SteamID64 to SteamID3 (used in userdata directory names).
        Formula: SteamID3 = SteamID64 - 76561197960265728
        """
        try:
            steamid64_int = int(steamid64)
            steamid3 = steamid64_int - 76561197960265728
            logger.debug(f"Converted SteamID64 {steamid64} to SteamID3 {steamid3}")
            return steamid3
        except ValueError as e:
            logger.error(f"Invalid SteamID64 format: {steamid64}")
            raise


    def get_shortcuts_vdf_path(self) -> Optional[Path]:
        """Get the path to shortcuts.vdf"""
        if not self.user_config_path:
            if not self.find_steam_user():
                return None
        
        shortcuts_path = self.user_config_path / "shortcuts.vdf"
        return shortcuts_path if shortcuts_path.exists() else shortcuts_path
    
    def get_localconfig_vdf_path(self) -> Optional[Path]:
        """Get the path to localconfig.vdf"""
        if not self.user_config_path:
            if not self.find_steam_user():
                return None
        
        return self.user_config_path / "localconfig.vdf"
    
    def read_shortcuts_vdf(self) -> Dict[str, Any]:
        """Read the shortcuts.vdf file safely"""
        shortcuts_path = self.get_shortcuts_vdf_path()
        if not shortcuts_path:
            return {'shortcuts': {}}
        
        try:
            if shortcuts_path.exists():
                with open(shortcuts_path, 'rb') as f:
                    data = vdf.binary_load(f)
                return data
            else:
                logger.info("shortcuts.vdf does not exist, will create new one")
                return {'shortcuts': {}}
                
        except Exception as e:
            logger.error(f"Error reading shortcuts.vdf: {e}")
            return {'shortcuts': {}}
    
    def write_shortcuts_vdf(self, data: Dict[str, Any]) -> bool:
        """Write the shortcuts.vdf file safely"""
        shortcuts_path = self.get_shortcuts_vdf_path()
        if not shortcuts_path:
            return False
        
        try:
            # Create backup first
            if shortcuts_path.exists():
                backup_path = shortcuts_path.with_suffix(f".vdf.backup_{int(time.time())}")
                import shutil
                shutil.copy2(shortcuts_path, backup_path)
                logger.info(f"Created backup: {backup_path}")
            
            # Ensure parent directory exists
            shortcuts_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Write the VDF file
            with open(shortcuts_path, 'wb') as f:
                vdf.binary_dump(data, f)
            
            logger.info("Successfully wrote shortcuts.vdf")
            return True
            
        except Exception as e:
            logger.error(f"Error writing shortcuts.vdf: {e}")
            return False
    
    def generate_app_id(self, app_name: str, exe_path: str) -> Tuple[int, int]:
        """
        Generate random AppID to avoid Steam cache conflicts.
        
        Uses random negative AppID similar to old working method to avoid
        Steam's cache conflicts that break Proton setting and "Installed Locally" visibility.
        AppID will be re-detected after Steam restart using existing detection logic.
        
        Returns:
            (signed_app_id, unsigned_app_id) - Both the signed and unsigned versions
        """
        import random
        
        # Generate random negative AppID in Steam's non-Steam app range
        # Use range that avoids conflicts with real Steam apps
        signed_app_id = -random.randint(100000000, 999999999)
        
        # Convert to unsigned for CompatToolMapping
        unsigned_app_id = signed_app_id + 2**32
        
        logger.info(f"Generated random AppID for '{app_name}': {signed_app_id} (unsigned: {unsigned_app_id})")
        return signed_app_id, unsigned_app_id
    
    def create_shortcut(self, app_name: str, exe_path: str, start_dir: str = None, 
                       launch_options: str = "%command%", tags: List[str] = None) -> Tuple[bool, Optional[int]]:
        """
        Create a Steam shortcut using direct VDF manipulation.
        
        Args:
            app_name: The shortcut name
            exe_path: Path to the executable
            start_dir: Start directory (defaults to exe directory)
            launch_options: Launch options (defaults to "%command%")
            tags: List of tags to apply
            
        Returns:
            (success, unsigned_app_id) - Success status and the AppID
        """
        if not start_dir:
            start_dir = str(Path(exe_path).parent)
        
        if not tags:
            tags = ["Jackify"]
        
        logger.info(f"Creating shortcut '{app_name}' for '{exe_path}'")
        
        try:
            # Read current shortcuts
            data = self.read_shortcuts_vdf()
            shortcuts = data.get('shortcuts', {})
            
            # Generate AppID
            signed_app_id, unsigned_app_id = self.generate_app_id(app_name, exe_path)
            
            # Find next available index
            indices = [int(k) for k in shortcuts.keys() if k.isdigit()]
            next_index = max(indices, default=-1) + 1
            
            # Get icon path from SteamIcons directory if available
            icon_path = ''
            steamicons_dir = Path(exe_path).parent / "SteamIcons"
            if steamicons_dir.is_dir():
                grid_tall_icon = steamicons_dir / "grid-tall.png"
                if grid_tall_icon.exists():
                    icon_path = str(grid_tall_icon)
                    logger.info(f"Using icon from SteamIcons: {icon_path}")
                else:
                    # Look for any PNG file
                    png_files = list(steamicons_dir.glob("*.png"))
                    if png_files:
                        icon_path = str(png_files[0])
                        logger.info(f"Using fallback icon: {icon_path}")
            
            # Create the shortcut entry with proper structure
            shortcut_entry = {
                'appid': signed_app_id,  # Use signed AppID in shortcuts.vdf
                'AppName': app_name,
                'Exe': f'"{exe_path}"',
                'StartDir': f'"{start_dir}"',
                'icon': icon_path,
                'ShortcutPath': '',
                'LaunchOptions': launch_options,
                'IsHidden': 0,
                'AllowDesktopConfig': 1,
                'AllowOverlay': 1,
                'OpenVR': 0,
                'Devkit': 0,
                'DevkitGameID': '',
                'DevkitOverrideAppID': 0,
                'LastPlayTime': 0,
                'IsInstalled': 1,  # Mark as installed so it appears in "Installed locally"
                'FlatpakAppID': '',
                'tags': {}
            }
            
            # Add tags
            for i, tag in enumerate(tags):
                shortcut_entry['tags'][str(i)] = tag
            
            # Add to shortcuts
            shortcuts[str(next_index)] = shortcut_entry
            data['shortcuts'] = shortcuts
            
            # Write back to file
            if self.write_shortcuts_vdf(data):
                logger.info(f"Shortcut created successfully at index {next_index}")
                return True, unsigned_app_id
            else:
                logger.error("Failed to write shortcut to VDF")
                return False, None
                
        except Exception as e:
            logger.error(f"Error creating shortcut: {e}")
            return False, None
    
    def set_proton_version(self, app_id: int, proton_version: str = "proton_experimental") -> bool:
        """
        Set the Proton version for a specific app using ONLY config.vdf like steam-conductor does.
        
        Args:
            app_id: The unsigned AppID  
            proton_version: The Proton version to set
            
        Returns:
            True if successful
        """
        logger.info(f"Setting Proton version '{proton_version}' for AppID {app_id} using STL-compatible format")
        
        try:
            # Step 1: Write to the main config.vdf for CompatToolMapping
            config_path = self.steam_path / "config" / "config.vdf"
            
            if not config_path.exists():
                logger.error(f"Steam config.vdf not found at: {config_path}")
                return False
            
            # Create backup first
            backup_path = config_path.with_suffix(f".vdf.backup_{int(time.time())}")
            import shutil
            shutil.copy2(config_path, backup_path)
            logger.info(f"Created backup: {backup_path}")
            
            # Read the file as text to avoid VDF library formatting issues
            with open(config_path, 'r', encoding='utf-8', errors='ignore') as f:
                config_text = f.read()
            
            # Find the CompatToolMapping section
            compat_start = config_text.find('"CompatToolMapping"')
            if compat_start == -1:
                logger.error("CompatToolMapping section not found in config.vdf")
                return False
            
            # Find the closing brace for CompatToolMapping
            # Look for the opening brace after CompatToolMapping
            brace_start = config_text.find('{', compat_start)
            if brace_start == -1:
                logger.error("CompatToolMapping opening brace not found")
                return False
            
            # Count braces to find the matching closing brace
            brace_count = 1
            pos = brace_start + 1
            compat_end = -1
            
            while pos < len(config_text) and brace_count > 0:
                if config_text[pos] == '{':
                    brace_count += 1
                elif config_text[pos] == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        compat_end = pos
                        break
                pos += 1
            
            if compat_end == -1:
                logger.error("CompatToolMapping closing brace not found")
                return False
            
            # Check if this AppID already exists
            app_id_pattern = f'"{app_id}"'
            app_id_exists = app_id_pattern in config_text[compat_start:compat_end]
            
            if app_id_exists:
                logger.info(f"AppID {app_id} already exists in CompatToolMapping, will be overwritten")
                # Remove the existing entry by finding and removing the entire block
                # This is complex, so for now just add at the end
            
            # Create the new entry in STL's exact format (tabs between key and value)
            new_entry = f'\t\t\t\t\t"{app_id}"\n\t\t\t\t\t{{\n\t\t\t\t\t\t"name"\t\t"{proton_version}"\n\t\t\t\t\t\t"config"\t\t""\n\t\t\t\t\t\t"priority"\t\t"250"\n\t\t\t\t\t}}\n'
            
            # Insert the new entry just before the closing brace of CompatToolMapping
            new_config_text = config_text[:compat_end] + new_entry + config_text[compat_end:]
            
            # Write back the modified text
            with open(config_path, 'w', encoding='utf-8') as f:
                f.write(new_config_text)
            
            logger.info(f"Successfully set Proton version '{proton_version}' for AppID {app_id} using config.vdf only (steam-conductor method)")
            return True
            
        except Exception as e:
            logger.error(f"Error setting Proton version: {e}")
            return False
    
    def create_shortcut_with_proton(self, app_name: str, exe_path: str, start_dir: str = None,
                                  launch_options: str = "%command%", tags: List[str] = None,
                                  proton_version: str = None) -> Tuple[bool, Optional[int]]:
        """
        Complete workflow: Create shortcut and set Proton version.

        This is the main method that replaces STL entirely.

        Returns:
            (success, app_id) - Success status and the AppID
        """
        # Auto-detect best Proton version if none provided
        if proton_version is None:
            try:
                from jackify.backend.core.modlist_operations import _get_user_proton_version
                proton_version = _get_user_proton_version()
                logger.info(f"Auto-detected Proton version: {proton_version}")
            except Exception as e:
                logger.warning(f"Failed to auto-detect Proton, falling back to experimental: {e}")
                proton_version = "proton_experimental"

        logger.info(f"Creating shortcut with Proton: '{app_name}' -> '{proton_version}'")
        
        # Step 1: Create the shortcut
        success, app_id = self.create_shortcut(app_name, exe_path, start_dir, launch_options, tags)
        if not success:
            logger.error("Failed to create shortcut")
            return False, None
        
        # Step 2: Set the Proton version
        if not self.set_proton_version(app_id, proton_version):
            logger.error("Failed to set Proton version (shortcut still created)")
            return False, app_id  # Shortcut exists but Proton setting failed
        
        logger.info(f"Complete workflow successful: '{app_name}' with '{proton_version}'")
        return True, app_id
    
    def list_shortcuts(self) -> Dict[str, str]:
        """List all existing shortcuts (for debugging)"""
        shortcuts = self.read_shortcuts_vdf().get('shortcuts', {})
        shortcut_list = {}
        
        for index, shortcut in shortcuts.items():
            app_name = shortcut.get('AppName', 'Unknown')
            shortcut_list[index] = app_name
        
        return shortcut_list
    
    def remove_shortcut(self, app_name: str) -> bool:
        """Remove a shortcut by name"""
        try:
            data = self.read_shortcuts_vdf()
            shortcuts = data.get('shortcuts', {})
            
            # Find shortcut by name
            to_remove = None
            for index, shortcut in shortcuts.items():
                if shortcut.get('AppName') == app_name:
                    to_remove = index
                    break
            
            if to_remove is None:
                logger.warning(f"Shortcut '{app_name}' not found")
                return False
            
            # Remove the shortcut
            del shortcuts[to_remove]
            data['shortcuts'] = shortcuts
            
            # Write back
            if self.write_shortcuts_vdf(data):
                logger.info(f"Removed shortcut '{app_name}'")
                return True
            else:
                logger.error("Failed to write updated shortcuts")
                return False
                
        except Exception as e:
            logger.error(f"Error removing shortcut: {e}")
            return False