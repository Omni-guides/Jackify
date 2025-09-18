#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Resolution Handler Module
Handles setting resolution in various INI files
"""

import os
import re
import glob
import logging
import subprocess
from pathlib import Path
from typing import Optional, List, Dict
# Import colors from the new central location
from .ui_colors import COLOR_PROMPT, COLOR_RESET, COLOR_ERROR, COLOR_INFO

# Initialize logger
logger = logging.getLogger(__name__)


class ResolutionHandler:
    """
    Handles resolution selection and configuration for games
    """
    
    def __init__(self, modlist_dir=None, game_var=None, resolution=None):
        self.modlist_dir = modlist_dir
        self.game_var = game_var  # Short version (e.g., "Skyrim")
        self.game_var_full = None  # Full version (e.g., "Skyrim Special Edition")
        self.resolution = resolution
        # Add logger initialization
        self.logger = logging.getLogger(__name__)
        
        # Set the full game name based on the short version
        if self.game_var:
            game_lookup = {
                "Skyrim": "Skyrim Special Edition",
                "Fallout": "Fallout 4",
                "Fallout 4": "Fallout 4",
                "Fallout New Vegas": "Fallout New Vegas",
                "FNV": "Fallout New Vegas",
                "Oblivion": "Oblivion"
            }
            self.game_var_full = game_lookup.get(self.game_var, self.game_var)
    
    def set_resolution(self, resolution):
        """
        Set the target resolution, e.g. "1280x800"
        """
        self.resolution = resolution
        logger.debug(f"Resolution set to: {self.resolution}")
        return True
    
    def get_resolution_components(self):
        """
        Split resolution into width and height components
        """
        if not self.resolution:
            logger.error("Resolution not set")
            return None, None
            
        try:
            width, height = self.resolution.split('x')
            return width, height
        except ValueError:
            logger.error(f"Invalid resolution format: {self.resolution}")
            return None, None
    
    def detect_steamdeck_resolution(self):
        """
        Set resolution to Steam Deck native if on a Steam Deck
        """
        try:
            if os.path.exists("/etc/os-release"):
                with open("/etc/os-release", "r") as f:
                    if "steamdeck" in f.read():
                        self.resolution = "1280x800"
                        logger.debug("Steam Deck detected, setting resolution to 1280x800")
                        return True
            
            return False
        except Exception as e:
            logger.error(f"Error detecting Steam Deck resolution: {e}")
            return False
    
    def select_resolution(self, steamdeck=False) -> Optional[str]:
        """
        Ask the user if they want to set resolution, then prompt and validate.
        Returns the selected resolution string (e.g., "1920x1080") or None if skipped/cancelled.
        """
        if steamdeck:
            logger.info("Steam Deck detected - Setting resolution to 1280x800")
            return "1280x800"
        
        # Ask user if they want to set resolution
        response = input(f"{COLOR_PROMPT}Do you wish to set the display resolution now? (y/N): {COLOR_RESET}").lower()
        
        if response == 'y':
            while True:
                user_res = input(f"{COLOR_PROMPT}Enter desired resolution (e.g., 1920x1080): {COLOR_RESET}").strip()
                if self._validate_resolution_format(user_res):
                    # Optional: Add confirmation step here if desired
                    # confirm = input(f"{COLOR_PROMPT}Use resolution {user_res}? (Y/n): {COLOR_RESET}").lower()
                    # if confirm != 'n':
                    #     return user_res
                    return user_res # Return validated resolution
                else:
                    print(f"{COLOR_ERROR}Invalid format. Please use format WxH (e.g., 1920x1080){COLOR_RESET}")
        else:
            self.logger.info("Resolution setup skipped by user.")
            return None
    
    def _validate_resolution_format(self, resolution: str) -> bool:
        """Validates the resolution format WxH (e.g., 1920x1080)."""
        if not resolution:
            return False
        # Simple regex to match one or more digits, 'x', one or more digits
        if re.match(r"^[0-9]+x[0-9]+$", resolution):
            self.logger.debug(f"Resolution format validated: {resolution}")
            return True
        else:
            self.logger.warning(f"Invalid resolution format provided: {resolution}")
            return False
    
    @staticmethod
    def get_available_resolutions() -> List[str]:
        """Gets available display resolutions using xrandr."""
        resolutions = []
        try:
            result = subprocess.run(["xrandr"], capture_output=True, text=True, check=True)
            # Regex to find lines like '   1920x1080     59.96*+'
            matches = re.finditer(r"^\s*(\d+x\d+)\s", result.stdout, re.MULTILINE)
            for match in matches:
                res = match.group(1)
                if res not in resolutions:
                    resolutions.append(res)
            # Add common resolutions if xrandr fails or doesn't list them
            common_res = ["1280x720", "1280x800", "1920x1080", "1920x1200", "2560x1440"]
            for res in common_res:
                 if res not in resolutions:
                      resolutions.append(res)
            resolutions.sort(key=lambda r: tuple(map(int, r.split('x'))))
            logger.debug(f"Detected resolutions: {resolutions}")
            return resolutions
        except (FileNotFoundError, subprocess.CalledProcessError, Exception) as e:
            logger.warning(f"Could not detect resolutions via xrandr: {e}. Falling back to common list.")
            # Fallback to a common list if xrandr is not available or fails
            return ["1280x720", "1280x800", "1920x1080", "1920x1200", "2560x1440"]
            
    @staticmethod
    def update_ini_resolution(modlist_dir: str, game_var: str, set_res: str, vanilla_game_dir: str = None) -> bool:
        """
        Updates the resolution in relevant INI files for the specified game.

        Args:
            modlist_dir (str): Path to the modlist directory.
            game_var (str): The game identifier (e.g., "Skyrim Special Edition", "Fallout 4").
            set_res (str): The desired resolution (e.g., "1920x1080").
            vanilla_game_dir (str): Optional path to vanilla game directory for fallback.

        Returns:
            bool: True if successful or not applicable, False on error.
        """
        logger.info(f"Attempting to set resolution to {set_res} for {game_var} in {modlist_dir}")
        
        try:
            isize_w, isize_h = set_res.split('x')
            modlist_path = Path(modlist_dir)
            success_count = 0
            files_processed = 0

            # 1. Handle SSEDisplayTweaks.ini (Skyrim SE only)
            if game_var == "Skyrim Special Edition":
                logger.debug("Processing SSEDisplayTweaks.ini...")
                sse_tweaks_files = list(modlist_path.rglob("SSEDisplayTweaks.ini"))
                if sse_tweaks_files:
                     for ini_file in sse_tweaks_files:
                        files_processed += 1
                        logger.debug(f"Updating {ini_file}")
                        if ResolutionHandler._modify_sse_tweaks(ini_file, set_res):
                            success_count += 1
                else:
                    logger.debug("No SSEDisplayTweaks.ini found, skipping.")

            # 1.5. Handle HighFPSPhysicsFix.ini (Fallout 4 only)
            elif game_var == "Fallout 4":
                logger.debug("Processing HighFPSPhysicsFix.ini...")
                highfps_files = list(modlist_path.rglob("HighFPSPhysicsFix.ini"))
                if highfps_files:
                     for ini_file in highfps_files:
                        files_processed += 1
                        logger.debug(f"Updating {ini_file}")
                        if ResolutionHandler._modify_highfps_physics_fix(ini_file, set_res):
                            success_count += 1
                else:
                    logger.debug("No HighFPSPhysicsFix.ini found, skipping.")

            # 2. Handle game-specific Prefs/INI files
            prefs_filenames = []
            if game_var == "Skyrim Special Edition":
                prefs_filenames = ["skyrimprefs.ini"]
            elif game_var == "Fallout 4":
                prefs_filenames = ["Fallout4Prefs.ini"]
            elif game_var == "Fallout New Vegas":
                prefs_filenames = ["falloutprefs.ini"]
            elif game_var == "Oblivion":
                prefs_filenames = ["Oblivion.ini"]
            else:
                logger.warning(f"Resolution setting not implemented for game: {game_var}")
                return True # Not an error, just not applicable
            
            logger.debug(f"Processing {prefs_filenames}...")
            prefs_files_found = []
            # Search entire modlist directory recursively for all target files
            logger.debug(f"Searching entire modlist directory for: {prefs_filenames}")
            for fname in prefs_filenames:
                found_files = list(modlist_path.rglob(fname))
                prefs_files_found.extend(found_files)
                if found_files:
                    logger.debug(f"Found {len(found_files)} {fname} files: {[str(f) for f in found_files]}")
            
            if not prefs_files_found:
                logger.warning(f"No preference files ({prefs_filenames}) found in modlist directory.")
                
                # Fallback: Try vanilla game directory if provided
                if vanilla_game_dir:
                    logger.info(f"Attempting fallback to vanilla game directory: {vanilla_game_dir}")
                    vanilla_path = Path(vanilla_game_dir)
                    for fname in prefs_filenames:
                        vanilla_files = list(vanilla_path.rglob(fname))
                        prefs_files_found.extend(vanilla_files)
                        if vanilla_files:
                            logger.info(f"Found {len(vanilla_files)} {fname} files in vanilla game directory")
                
                if not prefs_files_found:
                    logger.warning("No preference files found in modlist or vanilla game directory. Manual INI edit might be needed.")
                    return True 
            
            for ini_file in prefs_files_found:
                files_processed += 1
                logger.debug(f"Updating {ini_file}")
                if ResolutionHandler._modify_prefs_resolution(ini_file, isize_w, isize_h, game_var == "Oblivion"):
                     success_count += 1

            logger.info(f"Resolution update: processed {files_processed} files, {success_count} successfully updated.")
            # Return True even if some updates failed, as the overall process didn't halt
            return True

        except ValueError:
             logger.error(f"Invalid resolution format: {set_res}. Expected WxH (e.g., 1920x1080).")
             return False
        except Exception as e:
            logger.error(f"Error updating INI resolutions: {e}", exc_info=True)
            return False
            
    @staticmethod
    def _modify_sse_tweaks(ini_path: Path, resolution: str) -> bool:
        """Helper to modify SSEDisplayTweaks.ini"""
        try:
            with open(ini_path, 'r') as f:
                lines = f.readlines()
            
            new_lines = []
            modified = False
            for line in lines:
                stripped_line = line.strip()
                # Use regex for flexibility with spacing and comments
                if re.match(r'^\s*(#?)\s*Resolution\s*=.*$', stripped_line, re.IGNORECASE):
                    new_lines.append(f"Resolution={resolution}\n")
                    modified = True
                elif re.match(r'^\s*(#?)\s*Fullscreen\s*=.*$', stripped_line, re.IGNORECASE):
                    new_lines.append("Fullscreen=false\n")
                    modified = True
                elif re.match(r'^\s*(#?)\s*Borderless\s*=.*$', stripped_line, re.IGNORECASE):
                    new_lines.append("Borderless=true\n")
                    modified = True
                else:
                    new_lines.append(line)
            
            if modified:
                with open(ini_path, 'w') as f:
                    f.writelines(new_lines)
                logger.debug(f"Successfully modified {ini_path} for SSEDisplayTweaks")
            return True
        except Exception as e:
            logger.error(f"Failed to modify {ini_path}: {e}")
            return False

    @staticmethod
    def _modify_highfps_physics_fix(ini_path: Path, resolution: str) -> bool:
        """Helper to modify HighFPSPhysicsFix.ini for Fallout 4"""
        try:
            with open(ini_path, 'r') as f:
                lines = f.readlines()
            
            new_lines = []
            modified = False
            for line in lines:
                stripped_line = line.strip()
                # Look for Resolution line (commonly commented out by default)
                if re.match(r'^\s*(#?)\s*Resolution\s*=.*$', stripped_line, re.IGNORECASE):
                    new_lines.append(f"Resolution={resolution}\n")
                    modified = True
                else:
                    new_lines.append(line)
            
            if modified:
                with open(ini_path, 'w') as f:
                    f.writelines(new_lines)
                logger.debug(f"Successfully modified {ini_path} for HighFPSPhysicsFix")
            return True
        except Exception as e:
            logger.error(f"Failed to modify {ini_path}: {e}")
            return False

    @staticmethod
    def _modify_prefs_resolution(ini_path: Path, width: str, height: str, is_oblivion: bool) -> bool:
        """Helper to modify resolution in skyrimprefs.ini, Fallout4Prefs.ini, etc."""
        try:
            with open(ini_path, 'r') as f:
                lines = f.readlines()

            new_lines = []
            modified = False

            for line in lines:
                stripped_line = line.strip()
                if stripped_line.lower().startswith("isize w"):
                    # Preserve original spacing around equals sign
                    if " = " in stripped_line:
                        width_replace = f"iSize W = {width}\n"
                    else:
                        width_replace = f"iSize W={width}\n"
                    new_lines.append(width_replace)
                    modified = True
                elif stripped_line.lower().startswith("isize h"):
                    # Preserve original spacing around equals sign
                    if " = " in stripped_line:
                        height_replace = f"iSize H = {height}\n"
                    else:
                        height_replace = f"iSize H={height}\n"
                    new_lines.append(height_replace)
                    modified = True
                else:
                    new_lines.append(line)
            
            if modified:
                with open(ini_path, 'w') as f:
                    f.writelines(new_lines)
                logger.debug(f"Successfully modified {ini_path} for resolution")
            return True
        except Exception as e:
            logger.error(f"Failed to modify {ini_path}: {e}")
            return False
    
    def edit_resolution(self, modlist_dir, game_var, selected_resolution=None):
        """
        Edit resolution in INI files
        """
        if selected_resolution:
            logger.debug(f"Applying resolution: {selected_resolution}")
            return self.update_ini_resolution(modlist_dir, game_var, selected_resolution)
        else:
            logger.debug("Resolution setup skipped")
            return True
    
    def update_sse_display_tweaks(self):
        """
        Update SSEDisplayTweaks.ini with the chosen resolution
        Returns True on success, False on failure
        """
        if not self.modlist_dir or not self.game_var or not self.resolution:
            logger.error("Missing required parameters")
            return False
            
        if self.game_var != "Skyrim Special Edition":
            logger.debug(f"Not Skyrim, skipping SSEDisplayTweaks")
            return False
            
        try:
            # Find all SSEDisplayTweaks.ini files
            ini_files = glob.glob(f"{self.modlist_dir}/**/SSEDisplayTweaks.ini", recursive=True)
            
            if not ini_files:
                logger.debug("No SSEDisplayTweaks.ini files found")
                return False
                
            for ini_file in ini_files:
                # Read the file
                with open(ini_file, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.readlines()
                
                # Process and modify the content
                modified_content = []
                for line in content:
                    if line.strip().startswith("Resolution=") or line.strip().startswith("#Resolution="):
                        modified_content.append(f"Resolution={self.resolution}\n")
                    elif line.strip().startswith("Fullscreen=") or line.strip().startswith("#Fullscreen="):
                        modified_content.append(f"Fullscreen=false\n")
                    elif line.strip().startswith("Borderless=") or line.strip().startswith("#Borderless="):
                        modified_content.append(f"Borderless=true\n")
                    else:
                        modified_content.append(line)
                
                # Write the modified content back
                with open(ini_file, 'w', encoding='utf-8') as f:
                    f.writelines(modified_content)
                    
                logger.debug(f"Updated {ini_file} with Resolution={self.resolution}, Fullscreen=false, Borderless=true")
            
            return True
            
        except Exception as e:
            logger.error(f"Error updating SSEDisplayTweaks.ini: {e}")
            return False
    
    def update_game_prefs_ini(self):
        """
        Update game preference INI files with the chosen resolution
        Returns True on success, False on failure
        """
        if not self.modlist_dir or not self.game_var or not self.resolution:
            logger.error("Missing required parameters")
            return False
        
        try:
            # Get resolution components
            width, height = self.get_resolution_components()
            if not width or not height:
                return False
                
            # Define possible stock game folders to search
            stock_folders = [
                "profiles", "Stock Game", "Game Root", "STOCK GAME", 
                "Stock Game Folder", "Stock Folder", "Skyrim Stock"
            ]
            
            # Define the appropriate INI file based on game type
            ini_filename = None
            if self.game_var == "Skyrim Special Edition":
                ini_filename = "skyrimprefs.ini"
            elif self.game_var == "Fallout 4":
                ini_filename = "Fallout4Prefs.ini"
            elif self.game_var == "Fallout New Vegas":
                ini_filename = "falloutprefs.ini"
            elif self.game_var == "Oblivion":
                ini_filename = "Oblivion.ini"
            else:
                logger.error(f"Unsupported game: {self.game_var}")
                return False
                
            # Search for INI files in the appropriate directories
            ini_files = []
            for folder in stock_folders:
                path_pattern = os.path.join(self.modlist_dir, folder, f"**/{ini_filename}")
                ini_files.extend(glob.glob(path_pattern, recursive=True))
            
            if not ini_files:
                logger.warn(f"No {ini_filename} files found in specified directories")
                return False
                
            for ini_file in ini_files:
                # Read the file
                with open(ini_file, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.readlines()
                
                # Process and modify the content
                modified_content = []
                for line in content:
                    line_lower = line.lower()
                    if "isize w" in line_lower:
                        # Handle different formats (with = or space)
                        if "=" in line and not " = " in line:
                            modified_content.append(f"iSize W={width}\n")
                        else:
                            modified_content.append(f"iSize W = {width}\n")
                    elif "isize h" in line_lower:
                        # Handle different formats (with = or space)
                        if "=" in line and not " = " in line:
                            modified_content.append(f"iSize H={height}\n")
                        else:
                            modified_content.append(f"iSize H = {height}\n")
                    else:
                        modified_content.append(line)
                
                # Write the modified content back
                with open(ini_file, 'w', encoding='utf-8') as f:
                    f.writelines(modified_content)
                    
                logger.debug(f"Updated {ini_file} with iSize W={width}, iSize H={height}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error updating game prefs INI: {e}")
            return False
    
    def update_all_resolution_settings(self):
        """
        Update all resolution-related settings in all relevant INI files
        Returns True if any files were updated, False if none were updated
        """
        if not self.resolution:
            logger.error("Resolution not set")
            return False
            
        success = False
        
        # Update SSEDisplayTweaks.ini if applicable
        sse_success = self.update_sse_display_tweaks()
        
        # Update game preferences INI
        prefs_success = self.update_game_prefs_ini()
        
        return sse_success or prefs_success 