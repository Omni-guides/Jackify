#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Wine Utilities Module
Handles wine-related operations and utilities
"""

import os
import re
import subprocess
import logging
import shutil
import time
from pathlib import Path
import glob
from typing import Optional, Tuple, List, Dict
from .subprocess_utils import get_clean_subprocess_env

# Initialize logger
logger = logging.getLogger(__name__)


class WineUtils:
    """
    Utilities for wine-related operations
    """
    
    @staticmethod
    def cleanup_wine_processes():
        """
        Clean up wine processes
        Returns True on success, False on failure
        """
        try:
            # Find and kill processes containing various process names
            processes = subprocess.run(
                "pgrep -f 'win7|win10|ShowDotFiles|protontricks'", 
                shell=True, 
                capture_output=True, 
                text=True,
                env=get_clean_subprocess_env()
            ).stdout.strip()
            
            if processes:
                for pid in processes.split("\n"):
                    try:
                        subprocess.run(f"kill -9 {pid}", shell=True, check=True, env=get_clean_subprocess_env())
                    except subprocess.CalledProcessError:
                        logger.warning(f"Failed to kill process {pid}")
                logger.debug("Processes killed successfully")
            else:
                logger.debug("No matching processes found")
                
            # Kill winetricks processes
            subprocess.run("pkill -9 winetricks", shell=True, env=get_clean_subprocess_env())
            return True
        except Exception as e:
            logger.error(f"Failed to cleanup wine processes: {e}")
            return False
    
    @staticmethod
    def edit_binary_working_paths(modlist_ini, modlist_dir, modlist_sdcard, steam_library, basegame_sdcard):
        """
        Edit binary and working directory paths in ModOrganizer.ini
        Returns True on success, False on failure
        """
        if not os.path.isfile(modlist_ini):
            logger.error(f"ModOrganizer.ini not found at {modlist_ini}")
            return False
            
        try:
            # Read the file
            with open(modlist_ini, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.readlines()
                
            modified_content = []
            found_skse = False
            
            # First pass to identify SKSE/F4SE launcher entries
            skse_lines = []
            for i, line in enumerate(content):
                if re.search(r'skse64_loader\.exe|f4se_loader\.exe', line):
                    skse_lines.append((i, line))
                    found_skse = True
            
            if not found_skse:
                logger.debug("No SKSE/F4SE launcher entries found")
                return False
                
            # Process each SKSE/F4SE entry
            for line_num, orig_line in skse_lines:
                # Split the line into key and value
                if '=' not in orig_line:
                    continue
                    
                binary_num, skse_loc = orig_line.split('=', 1)
                
                # Set drive letter based on whether using SD card
                if modlist_sdcard:
                    drive_letter = " = D:"
                else:
                    drive_letter = " = Z:"
                
                # Determine the working directory key
                just_num = binary_num.split('\\')[0]
                bin_path_start = binary_num.strip().replace('\\', '\\\\')
                path_start = f"{just_num}\\\\workingDirectory".replace('\\', '\\\\')
                
                # Process the path based on its type
                if "mods" in orig_line:
                    # mods path type
                    if modlist_sdcard:
                        path_middle = WineUtils._strip_sdcard_path(modlist_dir)
                    else:
                        path_middle = modlist_dir
                    
                    path_end = re.sub(r'.*/mods', '/mods', skse_loc.split('/')[0])
                    bin_path_end = re.sub(r'.*/mods', '/mods', skse_loc)
                    
                elif any(term in orig_line for term in ["Stock Game", "Game Root", "STOCK GAME", "Stock Game Folder", "Stock Folder", "Skyrim Stock", "root/Skyrim Special Edition"]):
                    # Stock Game or Game Root type
                    if modlist_sdcard:
                        path_middle = WineUtils._strip_sdcard_path(modlist_dir)
                    else:
                        path_middle = modlist_dir
                    
                    # Determine the specific stock folder type
                    if "Stock Game" in orig_line:
                        dir_type = "stockgame"
                        path_end = re.sub(r'.*/Stock Game', '/Stock Game', os.path.dirname(skse_loc))
                        bin_path_end = re.sub(r'.*/Stock Game', '/Stock Game', skse_loc)
                    elif "Game Root" in orig_line:
                        dir_type = "gameroot"
                        path_end = re.sub(r'.*/Game Root', '/Game Root', os.path.dirname(skse_loc))
                        bin_path_end = re.sub(r'.*/Game Root', '/Game Root', skse_loc)
                    elif "STOCK GAME" in orig_line:
                        dir_type = "STOCKGAME"
                        path_end = re.sub(r'.*/STOCK GAME', '/STOCK GAME', os.path.dirname(skse_loc))
                        bin_path_end = re.sub(r'.*/STOCK GAME', '/STOCK GAME', skse_loc)
                    elif "Stock Folder" in orig_line:
                        dir_type = "stockfolder"
                        path_end = re.sub(r'.*/Stock Folder', '/Stock Folder', os.path.dirname(skse_loc))
                        bin_path_end = re.sub(r'.*/Stock Folder', '/Stock Folder', skse_loc)
                    elif "Skyrim Stock" in orig_line:
                        dir_type = "skyrimstock"
                        path_end = re.sub(r'.*/Skyrim Stock', '/Skyrim Stock', os.path.dirname(skse_loc))
                        bin_path_end = re.sub(r'.*/Skyrim Stock', '/Skyrim Stock', skse_loc)
                    elif "Stock Game Folder" in orig_line:
                        dir_type = "stockgamefolder"
                        path_end = re.sub(r'.*/Stock Game Folder', '/Stock Game Folder', skse_loc)
                        bin_path_end = path_end
                    elif "root/Skyrim Special Edition" in orig_line:
                        dir_type = "rootskyrimse"
                        path_end = '/' + skse_loc.lstrip()
                        bin_path_end = path_end
                    else:
                        logger.error(f"Unknown stock game type in line: {orig_line}")
                        continue
                        
                elif "steamapps" in orig_line:
                    # Steam apps path type
                    if basegame_sdcard:
                        path_middle = WineUtils._strip_sdcard_path(steam_library)
                        drive_letter = " = D:"
                    else:
                        path_middle = steam_library.split('steamapps')[0]
                    
                    path_end = re.sub(r'.*/steamapps', '/steamapps', os.path.dirname(skse_loc))
                    bin_path_end = re.sub(r'.*/steamapps', '/steamapps', skse_loc)
                    
                else:
                    logger.warning(f"No matching pattern found in the path: {orig_line}")
                    continue
                
                # Combine paths
                full_bin_path = f"{bin_path_start}{drive_letter}{path_middle}{bin_path_end}"
                full_path = f"{path_start}{drive_letter}{path_middle}{path_end}"
                
                # Replace forward slashes with double backslashes for Windows paths
                new_path = full_path.replace('/', '\\\\')
                
                # Update the content with new paths
                for i, line in enumerate(content):
                    if line.startswith(bin_path_start):
                        content[i] = f"{full_bin_path}\n"
                    elif line.startswith(path_start):
                        content[i] = f"{new_path}\n"
            
            # Write back the modified content
            with open(modlist_ini, 'w', encoding='utf-8') as f:
                f.writelines(content)
                
            logger.debug("Updated binary and working directory paths successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error editing binary working paths: {e}")
            return False
    
    @staticmethod
    def _get_sd_card_mounts():
        """
        Dynamically detect all current SD card mount points
        Returns list of mount point paths
        """
        try:
            import subprocess
            result = subprocess.run(['df', '-h'], capture_output=True, text=True, timeout=5)
            sd_mounts = []
            for line in result.stdout.split('\n'):
                # Look for common SD card mount patterns
                if '/run/media' in line or ('/mnt' in line and 'sdcard' in line.lower()):
                    parts = line.split()
                    if len(parts) >= 6:  # df output has 6+ columns
                        mount_point = parts[-1]  # Last column is mount point
                        if mount_point.startswith(('/run/media', '/mnt')):
                            sd_mounts.append(mount_point)
            return sd_mounts
        except Exception:
            # Fallback to common patterns if df fails
            return ['/run/media/mmcblk0p1', '/run/media/deck']

    @staticmethod
    def _strip_sdcard_path(path):
        """
        Strip any detected SD card mount prefix from paths
        Handles both /run/media/mmcblk0p1 and /run/media/deck/UUID patterns
        """
        sd_mounts = WineUtils._get_sd_card_mounts()

        for mount in sd_mounts:
            if path.startswith(mount):
                # Strip the mount prefix and ensure proper leading slash
                relative_path = path[len(mount):].lstrip('/')
                return "/" + relative_path if relative_path else "/"

        return path
    
    @staticmethod
    def all_owned_by_user(path):
        """
        Returns True if all files and directories under 'path' are owned by the current user.
        """
        uid = os.getuid()
        gid = os.getgid()
        for root, dirs, files in os.walk(path):
            for name in dirs + files:
                full_path = os.path.join(root, name)
                try:
                    stat = os.stat(full_path)
                    if stat.st_uid != uid or stat.st_gid != gid:
                        return False
                except Exception:
                    return False
        return True

    @staticmethod
    def chown_chmod_modlist_dir(modlist_dir):
        """
        Change ownership and permissions of modlist directory
        Returns True on success, False on failure
        """
        if WineUtils.all_owned_by_user(modlist_dir):
            logger.info(f"All files in {modlist_dir} are already owned by the current user. Skipping sudo chown/chmod.")
            return True
        logger.warn("Changing Ownership and Permissions of modlist directory (may require sudo password)")
        
        try:
            user = subprocess.run("whoami", shell=True, capture_output=True, text=True).stdout.strip()
            group = subprocess.run("id -gn", shell=True, capture_output=True, text=True).stdout.strip()
            
            logger.debug(f"User is {user} and Group is {group}")
            
            # Change ownership
            result1 = subprocess.run(
                f"sudo chown -R {user}:{group} \"{modlist_dir}\"",
                shell=True,
                capture_output=True,
                text=True
            )
            
            # Change permissions
            result2 = subprocess.run(
                f"sudo chmod -R 755 \"{modlist_dir}\"",
                shell=True,
                capture_output=True,
                text=True
            )
            
            if result1.returncode != 0 or result2.returncode != 0:
                logger.error("Failed to change ownership/permissions")
                logger.error(f"chown output: {result1.stderr}")
                logger.error(f"chmod output: {result2.stderr}")
                return False
                
            return True
            
        except Exception as e:
            logger.error(f"Error changing ownership and permissions: {e}")
            return False
    
    @staticmethod
    def create_dxvk_file(modlist_dir, modlist_sdcard, steam_library, basegame_sdcard, game_var_full):
        """
        Create DXVK file in the modlist directory
        """
        try:
            # Construct the path to the game directory
            game_dir = os.path.join(steam_library, game_var_full)
            
            # Create the DXVK file
            dxvk_file = os.path.join(modlist_dir, "DXVK")
            with open(dxvk_file, 'w') as f:
                f.write(game_dir)
            
            logger.debug(f"Created DXVK file at {dxvk_file} pointing to {game_dir}")
            return True
        except Exception as e:
            logger.error(f"Error creating DXVK file: {e}")
            return False
    
    @staticmethod
    def small_additional_tasks(modlist_dir, compat_data_path):
        """
        Perform small additional tasks like deleting unsupported plugins
        Returns True on success, False on failure
        """
        try:
            # Delete MO2 plugins that don't work via Proton
            file_to_delete = os.path.join(modlist_dir, "plugins/FixGameRegKey.py")
            if os.path.exists(file_to_delete):
                os.remove(file_to_delete)
                logger.debug(f"File deleted: {file_to_delete}")
            
            # Download Font to support Bethini
            if compat_data_path and os.path.isdir(compat_data_path):
                font_path = os.path.join(compat_data_path, "pfx/drive_c/windows/Fonts/seguisym.ttf")
                font_dir = os.path.dirname(font_path)
                
                # Ensure the directory exists
                os.makedirs(font_dir, exist_ok=True)
                
                # Download the font
                font_url = "https://github.com/mrbvrz/segoe-ui-linux/raw/refs/heads/master/font/seguisym.ttf"
                subprocess.run(
                    f"wget {font_url} -q -nc -O \"{font_path}\"",
                    shell=True,
                    check=True
                )
                logger.debug(f"Downloaded font to: {font_path}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error performing additional tasks: {e}")
            return False
    
    @staticmethod
    def modlist_specific_steps(modlist, appid):
        """
        Perform modlist-specific steps
        Returns True on success, False on failure
        """
        try:
            # Define modlist-specific configurations
            modlist_configs = {
                "wildlander": ["dotnet48", "dotnet472", "vcrun2019"],
                "septimus|sigernacollection|licentia|aldrnari|phoenix": ["dotnet48", "dotnet472"],
                "masterstroke": ["dotnet48", "dotnet472"],
                "diablo": ["dotnet48", "dotnet472"],
                "living_skyrim": ["dotnet48", "dotnet472", "dotnet462"],
                "nolvus": ["dotnet8"]
            }
            
            modlist_lower = modlist.lower().replace(" ", "")
            
            # Check for wildlander special case
            if "wildlander" in modlist_lower:
                logger.info(f"Running steps specific to {modlist}. This can take some time, be patient!")
                # Implementation for wildlander-specific steps
                return True
                
            # Check for other modlists
            for pattern, components in modlist_configs.items():
                if re.search(pattern.replace("|", "|.*"), modlist_lower):
                    logger.info(f"Running steps specific to {modlist}. This can take some time, be patient!")
                    
                    # Install components
                    for component in components:
                        if component == "dotnet8":
                            # Special handling for .NET 8
                            logger.info("Downloading .NET 8 Runtime")
                            # Implementation for .NET 8 installation
                            pass
                        else:
                            # Standard component installation
                            logger.info(f"Installing {component}...")
                            # Implementation for standard component installation
                            pass
                    
                    # Set Windows 10 prefix
                    # Implementation for setting Windows 10 prefix
                    
                    return True
            
            # No specific steps for this modlist
            logger.debug(f"No specific steps needed for {modlist}")
            return True
            
        except Exception as e:
            logger.error(f"Error performing modlist-specific steps: {e}")
            return False
    
    @staticmethod
    def fnv_launch_options(game_var, compat_data_path, modlist):
        """
        Set up Fallout New Vegas launch options
        Returns True on success, False on failure
        """
        if game_var != "Fallout New Vegas":
            return True
            
        try:
            appid_to_check = "22380"  # Fallout New Vegas AppID
            
            for path in [
                os.path.expanduser("~/.local/share/Steam/steamapps/compatdata"),
                os.path.expanduser("~/.steam/steam/steamapps/compatdata"),
                os.path.expanduser("~/.steam/root/steamapps/compatdata")
            ]:
                compat_path = os.path.join(path, appid_to_check)
                if os.path.exists(compat_path):
                    logger.warning(f"\nFor {modlist}, please add the following line to the Launch Options in Steam for your '{modlist}' entry:")
                    logger.info(f"\nSTEAM_COMPAT_DATA_PATH=\"{compat_path}\" %command%")
                    logger.warning("\nThis is essential for the modlist to load correctly.")
                    return True
                    
            logger.error("Could not determine the compatdata path for Fallout New Vegas")
            return False
            
        except Exception as e:
            logger.error(f"Error setting FNV launch options: {e}")
            return False
    
    @staticmethod
    def get_proton_version(compat_data_path):
        """
        Detect the Proton version used by a Steam game/shortcut
        
        Args:
            compat_data_path (str): Path to the compatibility data directory
            
        Returns:
            str: Detected Proton version or 'Unknown' if not found
        """
        logger.info("Detecting Proton version...")
        
        # Validate the compatdata path exists
        if not os.path.isdir(compat_data_path):
            logger.warning(f"Compatdata directory not found at '{compat_data_path}'")
            return "Unknown"
            
        # First try to get Proton version from the registry
        system_reg_path = os.path.join(compat_data_path, "pfx", "system.reg")
        if os.path.isfile(system_reg_path):
            try:
                with open(system_reg_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                    
                # Use regex to find SteamClientProtonVersion entry
                match = re.search(r'"SteamClientProtonVersion"="([^"]+)"', content)
                if match:
                    version = match.group(1).strip()
                    # Keep GE versions as is, otherwise prefix with "Proton"
                    if "GE" in version:
                        proton_ver = version
                    else:
                        proton_ver = f"Proton {version}"
                        
                    logger.debug(f"Detected Proton version from registry: {proton_ver}")
                    return proton_ver
            except Exception as e:
                logger.debug(f"Error reading system.reg: {e}")
                
        # Fallback to config_info if registry method fails
        config_info_path = os.path.join(compat_data_path, "config_info")
        if os.path.isfile(config_info_path):
            try:
                with open(config_info_path, "r") as f:
                    config_ver = f.readline().strip()
                    
                if config_ver:
                    # Keep GE versions as is, otherwise prefix with "Proton"
                    if "GE" in config_ver:
                        proton_ver = config_ver
                    else:
                        proton_ver = f"Proton {config_ver}"
                        
                    logger.debug(f"Detected Proton version from config_info: {proton_ver}")
                    return proton_ver
            except Exception as e:
                logger.debug(f"Error reading config_info: {e}")
                
        logger.warning("Could not detect Proton version")
        return "Unknown"
    
    @staticmethod
    def update_executables(modlist_ini, modlist_dir, modlist_sdcard, steam_library, basegame_sdcard):
        """
        Update executable paths in ModOrganizer.ini
        """
        logger.info("Updating executable paths in ModOrganizer.ini...")
        
        try:
            # Find SKSE or F4SE loader entries
            with open(modlist_ini, 'r') as f:
                lines = f.readlines()
            
            # Process each line
            for i, line in enumerate(lines):
                if "skse64_loader.exe" in line or "f4se_loader.exe" in line:
                    # Extract the binary path
                    binary_path = line.strip().split('=', 1)[1] if '=' in line else ""
                    
                    # Determine drive letter
                    drive_letter = "D:" if modlist_sdcard else "Z:"
                    
                    # Extract binary number
                    binary_num = line.strip().split('=', 1)[0] if '=' in line else ""
                    
                    # Find the equivalent workingDirectory
                    justnum = binary_num.split('\\')[0] if '\\' in binary_num else binary_num
                    bin_path_start = binary_num.replace('\\', '\\\\')
                    path_start = f"{justnum}\\workingDirectory".replace('\\', '\\\\')
                    
                    # Determine path type and construct new paths
                    if "mods" in binary_path:
                        # mods path type found
                        if modlist_sdcard:
                            path_middle = WineUtils._strip_sdcard_path(modlist_dir)
                        else:
                            path_middle = modlist_dir
                        
                        path_end = '/' + '/'.join(binary_path.split('/mods/', 1)[1].split('/')[:-1]) if '/mods/' in binary_path else ""
                        bin_path_end = '/' + '/'.join(binary_path.split('/mods/', 1)[1].split('/')) if '/mods/' in binary_path else ""
                    
                    elif any(x in binary_path for x in ["Stock Game", "Game Root", "STOCK GAME", "Stock Game Folder", "Stock Folder", "Skyrim Stock", "root/Skyrim Special Edition"]):
                        # Stock/Game Root found
                        if modlist_sdcard:
                            path_middle = WineUtils._strip_sdcard_path(modlist_dir)
                        else:
                            path_middle = modlist_dir
                        
                        # Determine directory type
                        if "Stock Game" in binary_path:
                            dir_type = "stockgame"
                            path_end = '/' + '/'.join(binary_path.split('/Stock Game/', 1)[1].split('/')[:-1]) if '/Stock Game/' in binary_path else ""
                            bin_path_end = '/' + '/'.join(binary_path.split('/Stock Game/', 1)[1].split('/')) if '/Stock Game/' in binary_path else ""
                        elif "Game Root" in binary_path:
                            dir_type = "gameroot"
                            path_end = '/' + '/'.join(binary_path.split('/Game Root/', 1)[1].split('/')[:-1]) if '/Game Root/' in binary_path else ""
                            bin_path_end = '/' + '/'.join(binary_path.split('/Game Root/', 1)[1].split('/')) if '/Game Root/' in binary_path else ""
                        elif "STOCK GAME" in binary_path:
                            dir_type = "STOCKGAME"
                            path_end = '/' + '/'.join(binary_path.split('/STOCK GAME/', 1)[1].split('/')[:-1]) if '/STOCK GAME/' in binary_path else ""
                            bin_path_end = '/' + '/'.join(binary_path.split('/STOCK GAME/', 1)[1].split('/')) if '/STOCK GAME/' in binary_path else ""
                        elif "Stock Folder" in binary_path:
                            dir_type = "stockfolder"
                            path_end = '/' + '/'.join(binary_path.split('/Stock Folder/', 1)[1].split('/')[:-1]) if '/Stock Folder/' in binary_path else ""
                            bin_path_end = '/' + '/'.join(binary_path.split('/Stock Folder/', 1)[1].split('/')) if '/Stock Folder/' in binary_path else ""
                        elif "Skyrim Stock" in binary_path:
                            dir_type = "skyrimstock"
                            path_end = '/' + '/'.join(binary_path.split('/Skyrim Stock/', 1)[1].split('/')[:-1]) if '/Skyrim Stock/' in binary_path else ""
                            bin_path_end = '/' + '/'.join(binary_path.split('/Skyrim Stock/', 1)[1].split('/')) if '/Skyrim Stock/' in binary_path else ""
                        elif "Stock Game Folder" in binary_path:
                            dir_type = "stockgamefolder"
                            path_end = '/' + '/'.join(binary_path.split('/Stock Game Folder/', 1)[1].split('/')) if '/Stock Game Folder/' in binary_path else ""
                        elif "root/Skyrim Special Edition" in binary_path:
                            dir_type = "rootskyrimse"
                            path_end = '/' + binary_path.split('root/Skyrim Special Edition', 1)[1] if 'root/Skyrim Special Edition' in binary_path else ""
                            bin_path_end = '/' + binary_path.split('root/Skyrim Special Edition', 1)[1] if 'root/Skyrim Special Edition' in binary_path else ""
                    
                    elif "steamapps" in binary_path:
                        # Steamapps found
                        if basegame_sdcard:
                            path_middle = WineUtils._strip_sdcard_path(steam_library)
                            drive_letter = "D:"
                        else:
                            path_middle = steam_library.split('steamapps', 1)[0] if 'steamapps' in steam_library else steam_library
                        
                        path_end = '/' + '/'.join(binary_path.split('/steamapps/', 1)[1].split('/')[:-1]) if '/steamapps/' in binary_path else ""
                        bin_path_end = '/' + '/'.join(binary_path.split('/steamapps/', 1)[1].split('/')) if '/steamapps/' in binary_path else ""
                    
                    else:
                        logger.warning(f"No matching pattern found in the path: {binary_path}")
                        continue
                    
                    # Combine paths
                    full_bin_path = f"{bin_path_start}={drive_letter}{path_middle}{bin_path_end}"
                    full_path = f"{path_start}={drive_letter}{path_middle}{path_end}"
                    
                    # Replace forward slashes with double backslashes
                    new_path = full_path.replace('/', '\\\\')
                    
                    # Update the lines
                    lines[i] = f"{full_bin_path}\n"
                    
                    # Find and update the workingDirectory line
                    for j, working_line in enumerate(lines):
                        if working_line.startswith(path_start):
                            lines[j] = f"{new_path}\n"
                            break
            
            # Write the updated content back to the file
            with open(modlist_ini, 'w') as f:
                f.writelines(lines)
            
            logger.info("Executable paths updated successfully")
            return True
        except Exception as e:
            logger.error(f"Error updating executable paths: {e}")
            return False
    
    @staticmethod
    def find_proton_binary(proton_version: str):
        """
        Find the full path to the Proton binary given a version string (e.g., 'Proton 8.0', 'GE-Proton8-15').
        Searches standard Steam library locations.
        Returns the path to the 'files/bin/wine' executable, or None if not found.
        """
        # Clean up the version string for directory matching
        version_patterns = [proton_version, proton_version.replace(' ', '_'), proton_version.replace(' ', '')]

        # Get actual Steam library paths from libraryfolders.vdf (smart detection)
        steam_common_paths = []
        compatibility_paths = []

        try:
            from .path_handler import PathHandler
            # Get root Steam library paths (without /steamapps/common suffix)
            root_steam_libs = PathHandler.get_all_steam_library_paths()
            for lib_path in root_steam_libs:
                lib = Path(lib_path)
                if lib.exists():
                    # Valve Proton: {library}/steamapps/common
                    common_path = lib / "steamapps/common"
                    if common_path.exists():
                        steam_common_paths.append(common_path)
                    # GE-Proton: same Steam installation root + compatibilitytools.d
                    compatibility_paths.append(lib / "compatibilitytools.d")
        except Exception as e:
            logger.warning(f"Could not detect Steam libraries from libraryfolders.vdf: {e}")

        # Fallback locations if dynamic detection fails
        if not steam_common_paths:
            steam_common_paths = [
                Path.home() / ".steam/steam/steamapps/common",
                Path.home() / ".local/share/Steam/steamapps/common",
                Path.home() / ".steam/root/steamapps/common"
            ]

        if not compatibility_paths:
            compatibility_paths = [
                Path.home() / ".steam/steam/compatibilitytools.d",
                Path.home() / ".local/share/Steam/compatibilitytools.d"
            ]

        # Add standard compatibility tool locations (covers edge cases like Flatpak)
        compatibility_paths.extend([
            Path.home() / ".steam/root/compatibilitytools.d",
            Path.home() / ".var/app/com.valvesoftware.Steam/.local/share/Steam/compatibilitytools.d"
        ])
        # Special handling for Proton 9: try all possible directory names
        if proton_version.strip().startswith("Proton 9"):
            proton9_candidates = ["Proton 9.0", "Proton 9.0 (Beta)"]
            for base_path in steam_common_paths:
                for name in proton9_candidates:
                    candidate = base_path / name / "files/bin/wine"
                    if candidate.is_file():
                        return str(candidate)
                # Fallback: any Proton 9* directory
                for subdir in base_path.glob("Proton 9*"):
                    wine_bin = subdir / "files/bin/wine"
                    if wine_bin.is_file():
                        return str(wine_bin)
        # General case: try version patterns in both steamapps and compatibilitytools.d
        all_paths = steam_common_paths + compatibility_paths
        for base_path in all_paths:
            if not base_path.is_dir():
                continue
            for pattern in version_patterns:
                # Try direct match for Proton directory
                proton_dir = base_path / pattern
                wine_bin = proton_dir / "files/bin/wine"
                if wine_bin.is_file():
                    return str(wine_bin)
                # Try glob for GE/other variants
                for subdir in base_path.glob(f"*{pattern}*"):
                    wine_bin = subdir / "files/bin/wine"
                    if wine_bin.is_file():
                        return str(wine_bin)
        # Fallback: Try user's configured Proton version
        try:
            from .config_handler import ConfigHandler
            config = ConfigHandler()
            fallback_path = config.get_proton_path()
            if fallback_path != 'auto':
                fallback_wine_bin = Path(fallback_path) / "files/bin/wine"
                if fallback_wine_bin.is_file():
                    logger.warning(f"Requested Proton version '{proton_version}' not found. Falling back to user's configured version.")
                    return str(fallback_wine_bin)
        except Exception:
            pass

        # Final fallback: Try 'Proton - Experimental' if present
        for base_path in steam_common_paths:
            wine_bin = base_path / "Proton - Experimental" / "files/bin/wine"
            if wine_bin.is_file():
                logger.warning(f"Requested Proton version '{proton_version}' not found. Falling back to 'Proton - Experimental'.")
                return str(wine_bin)
        return None
    
    @staticmethod
    def get_proton_paths(appid: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Get the Proton paths for a given AppID.
        
        Args:
            appid (str): The Steam AppID to get paths for
            
        Returns:
            tuple: (compatdata_path, proton_path, wine_bin) or (None, None, None) if not found
        """
        logger.info(f"Getting Proton paths for AppID {appid}")
        
        # Find compatdata path
        possible_compat_bases = [
            Path.home() / ".steam/steam/steamapps/compatdata",
            Path.home() / ".local/share/Steam/steamapps/compatdata"
        ]
        
        compatdata_path = None
        for base_path in possible_compat_bases:
            potential_compat_path = base_path / appid
            if potential_compat_path.is_dir():
                compatdata_path = str(potential_compat_path)
                logger.debug(f"Found compatdata directory: {compatdata_path}")
                break
                
        if not compatdata_path:
            logger.error(f"Could not find compatdata directory for AppID {appid}")
            return None, None, None
            
        # Get Proton version
        proton_version = WineUtils.get_proton_version(compatdata_path)
        if proton_version == "Unknown":
            logger.error(f"Could not determine Proton version for AppID {appid}")
            return None, None, None
            
        # Find Proton binary
        wine_bin = WineUtils.find_proton_binary(proton_version)
        if not wine_bin:
            logger.error(f"Could not find Proton binary for version {proton_version}")
            return None, None, None
            
        # Get Proton path (parent of wine binary)
        proton_path = str(Path(wine_bin).parent.parent)
        logger.debug(f"Found Proton path: {proton_path}")
        
        return compatdata_path, proton_path, wine_bin 
    
    @staticmethod
    def get_steam_library_paths() -> List[Path]:
        """
        Get all Steam library paths from libraryfolders.vdf (handles Flatpak, custom locations, etc.).

        Returns:
            List of Path objects for Steam library directories
        """
        try:
            from .path_handler import PathHandler
            # Use existing PathHandler that reads libraryfolders.vdf
            library_paths = PathHandler.get_all_steam_library_paths()
            # Convert to steamapps/common paths for Proton scanning
            steam_common_paths = []
            for lib_path in library_paths:
                common_path = lib_path / "steamapps" / "common"
                if common_path.exists():
                    steam_common_paths.append(common_path)
            logger.debug(f"Found Steam library paths: {steam_common_paths}")
            return steam_common_paths
        except Exception as e:
            logger.warning(f"Failed to get Steam library paths from libraryfolders.vdf: {e}")
            # Fallback to hardcoded paths if PathHandler fails
            fallback_paths = [
                Path.home() / ".steam/steam/steamapps/common",
                Path.home() / ".local/share/Steam/steamapps/common",
                Path.home() / ".steam/root/steamapps/common"
            ]
            return [path for path in fallback_paths if path.exists()]

    @staticmethod
    def get_compatibility_tool_paths() -> List[Path]:
        """
        Get all compatibility tool paths for GE-Proton and other custom Proton versions.

        Returns:
            List of Path objects for compatibility tool directories
        """
        compat_paths = [
            Path.home() / ".steam/steam/compatibilitytools.d",
            Path.home() / ".local/share/Steam/compatibilitytools.d"
        ]

        # Return only existing paths
        return [path for path in compat_paths if path.exists()]

    @staticmethod
    def scan_ge_proton_versions() -> List[Dict[str, any]]:
        """
        Scan for available GE-Proton versions in compatibilitytools.d directories.

        Returns:
            List of dicts with version info, sorted by priority (newest first)
        """
        logger.info("Scanning for available GE-Proton versions...")

        found_versions = []
        compat_paths = WineUtils.get_compatibility_tool_paths()

        if not compat_paths:
            logger.warning("No compatibility tool paths found")
            return []

        for compat_path in compat_paths:
            logger.debug(f"Scanning compatibility tools: {compat_path}")

            try:
                # Look for GE-Proton directories
                for proton_dir in compat_path.iterdir():
                    if not proton_dir.is_dir():
                        continue

                    dir_name = proton_dir.name
                    if not dir_name.startswith("GE-Proton"):
                        continue

                    # Check for wine binary
                    wine_bin = proton_dir / "files" / "bin" / "wine"
                    if not wine_bin.exists() or not wine_bin.is_file():
                        logger.debug(f"Skipping {dir_name} - no wine binary found")
                        continue

                    # Parse version from directory name (e.g., "GE-Proton10-16")
                    version_match = re.match(r'GE-Proton(\d+)-(\d+)', dir_name)
                    if version_match:
                        major_ver = int(version_match.group(1))
                        minor_ver = int(version_match.group(2))

                        # Calculate priority: GE-Proton gets highest priority
                        # Priority format: 200 (base) + major*10 + minor (e.g., 200 + 100 + 16 = 316)
                        priority = 200 + (major_ver * 10) + minor_ver

                        found_versions.append({
                            'name': dir_name,
                            'path': proton_dir,
                            'wine_bin': wine_bin,
                            'priority': priority,
                            'major_version': major_ver,
                            'minor_version': minor_ver,
                            'type': 'GE-Proton'
                        })
                        logger.debug(f"Found {dir_name} at {proton_dir} (priority: {priority})")
                    else:
                        logger.debug(f"Skipping {dir_name} - unknown GE-Proton version format")

            except Exception as e:
                logger.warning(f"Error scanning {compat_path}: {e}")

        # Sort by priority (highest first, so newest GE-Proton versions come first)
        found_versions.sort(key=lambda x: x['priority'], reverse=True)

        logger.info(f"Found {len(found_versions)} GE-Proton version(s)")
        return found_versions

    @staticmethod
    def scan_valve_proton_versions() -> List[Dict[str, any]]:
        """
        Scan for available Valve Proton versions with fallback priority.
        
        Returns:
            List of dicts with version info, sorted by priority (best first)
        """
        logger.info("Scanning for available Valve Proton versions...")
        
        found_versions = []
        steam_libs = WineUtils.get_steam_library_paths()
        
        if not steam_libs:
            logger.warning("No Steam library paths found")
            return []
        
        # Priority order for Valve Proton versions
        # Note: GE-Proton uses 200+ range, so Valve Proton gets 100+ range
        preferred_versions = [
            ("Proton - Experimental", 150),  # Higher priority than regular Valve Proton
            ("Proton 10.0", 140),
            ("Proton 9.0", 130),
            ("Proton 9.0 (Beta)", 125)
        ]
        
        for steam_path in steam_libs:
            logger.debug(f"Scanning Steam library: {steam_path}")
            
            for version_name, priority in preferred_versions:
                proton_path = steam_path / version_name
                wine_bin = proton_path / "files" / "bin" / "wine"
                
                if wine_bin.exists() and wine_bin.is_file():
                    found_versions.append({
                        'name': version_name,
                        'path': proton_path,
                        'wine_bin': wine_bin,
                        'priority': priority,
                        'type': 'Valve-Proton'
                    })
                    logger.debug(f"Found {version_name} at {proton_path}")
        
        # Sort by priority (highest first)
        found_versions.sort(key=lambda x: x['priority'], reverse=True)
        
        # Remove duplicates while preserving order
        unique_versions = []
        seen_names = set()
        for version in found_versions:
            if version['name'] not in seen_names:
                unique_versions.append(version)
                seen_names.add(version['name'])
        
        logger.info(f"Found {len(unique_versions)} unique Valve Proton version(s)")
        return unique_versions

    @staticmethod
    def scan_all_proton_versions() -> List[Dict[str, any]]:
        """
        Scan for all available Proton versions (GE-Proton + Valve Proton) with unified priority.

        Priority Chain (highest to lowest):
        1. GE-Proton10-16+ (priority 316+)
        2. GE-Proton10-* (priority 200+)
        3. Proton - Experimental (priority 150)
        4. Proton 10.0 (priority 140)
        5. Proton 9.0 (priority 130)
        6. Proton 9.0 (Beta) (priority 125)

        Returns:
            List of dicts with version info, sorted by priority (best first)
        """
        logger.info("Scanning for all available Proton versions...")

        all_versions = []

        # Scan GE-Proton versions (highest priority)
        ge_versions = WineUtils.scan_ge_proton_versions()
        all_versions.extend(ge_versions)

        # Scan Valve Proton versions
        valve_versions = WineUtils.scan_valve_proton_versions()
        all_versions.extend(valve_versions)

        # Sort by priority (highest first)
        all_versions.sort(key=lambda x: x['priority'], reverse=True)

        # Remove duplicates while preserving order
        unique_versions = []
        seen_names = set()
        for version in all_versions:
            if version['name'] not in seen_names:
                unique_versions.append(version)
                seen_names.add(version['name'])

        if unique_versions:
            logger.info(f"Found {len(unique_versions)} total Proton version(s)")
            logger.info(f"Best available: {unique_versions[0]['name']} ({unique_versions[0]['type']})")
        else:
            logger.warning("No Proton versions found")

        return unique_versions

    @staticmethod
    def select_best_proton() -> Optional[Dict[str, any]]:
        """
        Select the best available Proton version (GE-Proton or Valve Proton) using unified precedence.

        Returns:
            Dict with version info for the best Proton, or None if none found
        """
        available_versions = WineUtils.scan_all_proton_versions()

        if not available_versions:
            logger.warning("No compatible Proton versions found")
            return None

        # Return the highest priority version (first in sorted list)
        best_version = available_versions[0]
        logger.info(f"Selected best Proton version: {best_version['name']} ({best_version['type']})")
        return best_version

    @staticmethod
    def select_best_valve_proton() -> Optional[Dict[str, any]]:
        """
        Select the best available Valve Proton version using fallback precedence.
        Note: This method is kept for backward compatibility. Consider using select_best_proton() instead.

        Returns:
            Dict with version info for the best Proton, or None if none found
        """
        available_versions = WineUtils.scan_valve_proton_versions()

        if not available_versions:
            logger.warning("No compatible Valve Proton versions found")
            return None

        # Return the highest priority version (first in sorted list)
        best_version = available_versions[0]
        logger.info(f"Selected Valve Proton version: {best_version['name']}")
        return best_version
    
    @staticmethod
    def check_proton_requirements() -> Tuple[bool, str, Optional[Dict[str, any]]]:
        """
        Check if compatible Proton version is available for workflows.

        Returns:
            tuple: (requirements_met, status_message, proton_info)
            - requirements_met: True if compatible Proton found
            - status_message: Human-readable status for display to user
            - proton_info: Dict with Proton details if found, None otherwise
        """
        logger.info("Checking Proton requirements for workflow...")

        # Scan for available Proton versions (includes GE-Proton + Valve Proton)
        best_proton = WineUtils.select_best_proton()

        if best_proton:
            # Compatible Proton found
            proton_type = best_proton.get('type', 'Unknown')
            status_msg = f"✓ Using {best_proton['name']} ({proton_type}) for this workflow"
            logger.info(f"Proton requirements satisfied: {best_proton['name']} ({proton_type})")
            return True, status_msg, best_proton
        else:
            # No compatible Proton found
            status_msg = "✗ No compatible Proton version found (GE-Proton 10+, Proton 9+, 10, or Experimental required)"
            logger.warning("Proton requirements not met - no compatible version found")
            return False, status_msg, None 