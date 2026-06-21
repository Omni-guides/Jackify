#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MO2 INI and path formatting mixin for PathHandler.
Extracted from path_handler for file-size and domain separation.
"""

import os
import re
import shutil
import logging
from pathlib import Path
from typing import Optional, List
from datetime import datetime

from .wine_utils import WineUtils

logger = logging.getLogger(__name__)

TARGET_EXECUTABLES_LOWER = [
    "skse64_loader.exe", "f4se_loader.exe", "nvse_loader.exe", "obse_loader.exe",
    "sfse_loader.exe", "obse64_loader.exe", "falloutnv.exe"
]
STOCK_GAME_FOLDERS = [
    "Stock Game", "StockGame", "STOCK GAME", "Stock Game Folder",
    "Game Root", "Stock Folder", "Skyrim Stock", "root/Skyrim Special Edition",
]

class PathHandlerMO2Mixin:
    """Mixin providing ModOrganizer.ini path updates and formatting."""

    @staticmethod
    def _desired_home_basis_from_modlist_dir(modlist_dir_path: Path) -> Optional[str]:
        """
        Determine desired Linux home-path basis from modlist install directory.

        Returns:
            "/var/home" when modlist dir is under /var/home,
            "/home" when modlist dir is under /home,
            None otherwise.
        """
        try:
            posix = modlist_dir_path.as_posix()
        except Exception:
            posix = str(modlist_dir_path).replace("\\", "/")
        if posix.startswith("/var/home/"):
            return "/var/home"
        if posix.startswith("/home/"):
            return "/home"
        return None

    @staticmethod
    def _rewrite_z_home_basis_in_line(line: str, desired_home_basis: str) -> str:
        """
        Rewrite only Z:-drive /home -> /var/home path basis in a single INI line.

        Preserves slash style (forward or backslash), and leaves D: paths untouched.
        """
        if desired_home_basis == "/var/home":
            # Z:/home/... -> Z:/var/home/...
            # Z:\\home\\... -> Z:\\var\\home\\...
            return re.sub(r'([Zz]:[/\\]+)home([/\\]+)', r'\1var\2home\2', line)
        return line

    def align_home_path_basis(self, modlist_ini_path: Path, modlist_dir_path: Path, modlist_sdcard: bool) -> bool:
        """
        Align gamePath/binary/workingDirectory home-path basis to modlist_dir_path.

        This is a targeted post-processing step for Z: paths only:
        - If install path is /var/home/... then rewrite Z:/home/... to Z:/var/home/...
        - Otherwise do nothing.
        """
        if modlist_sdcard:
            return True
        desired_home_basis = self._desired_home_basis_from_modlist_dir(modlist_dir_path)
        # This alignment pass is intentionally one-way:
        # only promote Z:/home -> Z:/var/home when install dir uses /var/home.
        if desired_home_basis != "/var/home":
            return True
        if not modlist_ini_path.is_file():
            logger.error(f"INI file {modlist_ini_path} does not exist for home-basis alignment")
            return False
        try:
            with open(modlist_ini_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            changed = 0
            for i, line in enumerate(lines):
                stripped = line.strip()
                if not (
                    re.match(r'^\s*gamepath\s*=.*$', stripped, re.IGNORECASE)
                    or re.match(r'^(\d+)(\\+)\s*binary\s*=.*$', stripped, re.IGNORECASE)
                    or re.match(r'^(\d+)(\\+)\s*workingDirectory\s*=.*$', stripped, re.IGNORECASE)
                ):
                    continue
                rewritten = self._rewrite_z_home_basis_in_line(line, desired_home_basis)
                if rewritten != line:
                    lines[i] = rewritten
                    changed += 1

            if changed > 0:
                with open(modlist_ini_path, 'w', encoding='utf-8') as f:
                    f.writelines(lines)
                logger.info(
                    "Aligned ModOrganizer.ini home-path basis to %s for %d line(s): %s",
                    desired_home_basis,
                    changed,
                    modlist_ini_path,
                )
            else:
                logger.debug(
                    "No home-path basis alignment needed for %s (target %s)",
                    modlist_ini_path,
                    desired_home_basis,
                )
            return True
        except Exception as e:
            logger.error(f"Error aligning home path basis in {modlist_ini_path}: {e}")
            return False

    @staticmethod
    def _strip_sdcard_path_prefix(path_obj: Path) -> str:
        """Removes SD card mount prefix. Returns path as POSIX-style string."""
        path_str = path_obj.as_posix()
        stripped_path = WineUtils._strip_sdcard_path(path_str)
        if stripped_path != path_str:
            return stripped_path.lstrip('/') if stripped_path != '/' else '.'
        return path_str

    @classmethod
    def update_mo2_ini_paths(
        cls,
        modlist_ini_path: Path,
        modlist_dir_path: Path,
        modlist_sdcard: bool,
        steam_library_common_path: Optional[Path] = None,
        basegame_dir_name: Optional[str] = None,
        basegame_sdcard: bool = False
    ) -> bool:
        """Update gamePath, binary, and workingDirectory in ModOrganizer.ini."""
        logger.info(f"[DEBUG] update_mo2_ini_paths called with: modlist_ini_path={modlist_ini_path}, modlist_dir_path={modlist_dir_path}, modlist_sdcard={modlist_sdcard}, steam_library_common_path={steam_library_common_path}, basegame_dir_name={basegame_dir_name}, basegame_sdcard={basegame_sdcard}")
        if not modlist_ini_path.is_file():
            logger.error(f"ModOrganizer.ini not found at specified path: {modlist_ini_path}")
            try:
                logger.warning("Creating minimal ModOrganizer.ini with [General] section.")
                with open(modlist_ini_path, 'w', encoding='utf-8') as f:
                    f.write('[General]\n')
            except Exception as e:
                logger.critical(f"Failed to create minimal ModOrganizer.ini: {e}")
                return False
        if not modlist_dir_path.is_dir():
            logger.error(f"Modlist directory not found or not a directory: {modlist_dir_path}")
        all_steam_libraries = cls.get_all_steam_library_paths()
        logger.info(f"[DEBUG] Detected Steam libraries: {all_steam_libraries}")
        import sys
        if hasattr(sys, 'argv') and any(arg in ('--debug', '-d') for arg in sys.argv):
            logger.debug(f"Detected Steam libraries: {all_steam_libraries}")
        GAME_DIR_NAMES = {
            "Skyrim Special Edition": "Skyrim Special Edition",
            "Fallout 4": "Fallout 4",
            "Fallout New Vegas": "Fallout New Vegas",
            "Oblivion": "Oblivion"
        }
        canonical_name = GAME_DIR_NAMES.get(basegame_dir_name, basegame_dir_name) if basegame_dir_name else None
        gamepath_target_dir = None
        gamepath_target_is_sdcard = modlist_sdcard
        checked_candidates = []
        if canonical_name:
            for lib in all_steam_libraries:
                candidate = lib / "steamapps" / "common" / canonical_name
                checked_candidates.append(str(candidate))
                logger.info(f"[DEBUG] Checking for vanilla game directory: {candidate}")
                if candidate.is_dir():
                    gamepath_target_dir = candidate
                    logger.info(f"Found vanilla game directory: {candidate}")
                    break
        if not gamepath_target_dir:
            logger.error(f"Could not find vanilla game directory '{canonical_name}' in any Steam library. Checked: {checked_candidates}")
            print("\nCould not automatically detect a Stock Game or vanilla game directory.")
            print("Please enter the full path to your vanilla game directory (e.g., /path/to/Skyrim Special Edition):")
            while True:
                user_input = input("Game directory path: ").strip()
                user_path = Path(user_input)
                logger.info(f"[DEBUG] User entered: {user_input}")
                if user_path.is_dir():
                    exe_candidates = list(user_path.glob('*.exe'))
                    logger.info(f"[DEBUG] .exe files in user path: {exe_candidates}")
                    if exe_candidates:
                        gamepath_target_dir = user_path
                        logger.info(f"User provided valid vanilla game directory: {gamepath_target_dir}")
                        break
                    print("Directory exists but does not appear to contain the game executable. Please check and try again.")
                    logger.warning("User path exists but no .exe files found.")
                else:
                    print("Directory not found. Please enter a valid path.")
                    logger.warning("User path does not exist.")
        if not gamepath_target_dir:
            logger.critical("[FATAL] Could not determine a valid target directory for gamePath. Check configuration and paths. Aborting update.")
            return False
        logger.debug(f"Determined gamePath target directory: {gamepath_target_dir}")
        logger.debug(f"gamePath target is on SD card: {gamepath_target_is_sdcard}")
        try:
            logger.debug(f"Reading original INI file: {modlist_ini_path}")
            with open(modlist_ini_path, 'r', encoding='utf-8', errors='ignore') as f:
                original_lines = f.readlines()
            gamepath_line_num = -1
            general_section_line = -1
            for i, line in enumerate(original_lines):
                if re.match(r'^\s*\[General\]\s*$', line, re.IGNORECASE):
                    general_section_line = i
                if re.match(r'^\s*gamepath\s*=\s*', line, re.IGNORECASE):
                    gamepath_line_num = i
                    break
            processed_str = PathHandlerMO2Mixin._strip_sdcard_path_prefix(gamepath_target_dir)
            windows_style_single = processed_str.replace('/', '\\')
            gamepath_drive_letter = "D:" if gamepath_target_is_sdcard else "Z:"
            formatted_gamepath = PathHandlerMO2Mixin._format_gamepath_for_mo2(f'{gamepath_drive_letter}{windows_style_single}')
            new_gamepath_line = f'gamePath = @ByteArray({formatted_gamepath})\n'
            if gamepath_line_num != -1:
                logger.info(f"Updating existing gamePath line: {original_lines[gamepath_line_num].strip()} -> {new_gamepath_line.strip()}")
                original_lines[gamepath_line_num] = new_gamepath_line
            else:
                insert_at = general_section_line + 1 if general_section_line != -1 else 0
                logger.info(f"Adding missing gamePath line at line {insert_at+1}: {new_gamepath_line.strip()}")
                original_lines.insert(insert_at, new_gamepath_line)
            TARGET_EXEC_LOWER = [
                "skse64_loader.exe", "f4se_loader.exe", "nvse_loader.exe", "obse_loader.exe", "falloutnv.exe"
            ]
            in_custom_exec = False
            for i, line in enumerate(original_lines):
                if re.match(r'^\s*\[customExecutables\]\s*$', line, re.IGNORECASE):
                    in_custom_exec = True
                    continue
                if in_custom_exec and re.match(r'^\s*\[.*\]\s*$', line):
                    in_custom_exec = False
                if in_custom_exec:
                    m = re.match(r'^(\d+)\\binary\s*=\s*(.*)$', line.strip(), re.IGNORECASE)
                    if m:
                        idx, old_path = m.group(1), m.group(2)
                        exe_name = os.path.basename(old_path).lower()
                        if exe_name in TARGET_EXEC_LOWER:
                            new_path = f'{gamepath_drive_letter}/{PathHandlerMO2Mixin._strip_sdcard_path_prefix(gamepath_target_dir)}/{exe_name}'
                            new_path = PathHandlerMO2Mixin._format_binary_for_mo2(new_path)
                            logger.info(f"Updating binary for entry {idx}: {old_path} -> {new_path}")
                            original_lines[i] = f'{idx}\\binary = {new_path}\n'
                    m_wd = re.match(r'^(\d+)\\workingDirectory\s*=\s*(.*)$', line.strip(), re.IGNORECASE)
                    if m_wd:
                        idx, old_wd = m_wd.group(1), m_wd.group(2)
                        new_wd = f'{gamepath_drive_letter}{windows_style_single}'
                        new_wd = PathHandlerMO2Mixin._format_workingdir_for_mo2(new_wd)
                        logger.info(f"Updating workingDirectory for entry {idx}: {old_wd} -> {new_wd}")
                        original_lines[i] = f'{idx}\\workingDirectory = {new_wd}\n'
            backup_path = modlist_ini_path.with_suffix(f".{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak")
            try:
                shutil.copy2(modlist_ini_path, backup_path)
                logger.info(f"Backed up original INI to: {backup_path}")
            except Exception as bak_err:
                logger.error(f"Failed to backup original INI file: {bak_err}")
                return False
            try:
                with open(modlist_ini_path, 'w', encoding='utf-8') as f:
                    f.writelines(original_lines)
                logger.info(f"Successfully wrote updated paths to {modlist_ini_path}")
                return True
            except Exception as write_err:
                logger.error(f"Failed to write updated INI file {modlist_ini_path}: {write_err}", exc_info=True)
                logger.error("Attempting to restore from backup...")
                try:
                    shutil.move(backup_path, modlist_ini_path)
                    logger.info("Successfully restored original INI from backup.")
                except Exception as restore_err:
                    logger.critical(f"CRITICAL FAILURE: Could not write new INI and failed to restore backup {backup_path}. Manual intervention required at {modlist_ini_path}! Error: {restore_err}")
                return False
        except Exception as e:
            logger.error(f"An unexpected error occurred during INI path update: {e}", exc_info=True)
            return False

    @staticmethod
    def edit_resolution(modlist_ini, resolution) -> bool:
        """Edit resolution settings in ModOrganizer.ini. resolution format: '1920x1080'."""
        try:
            logger.info(f"Editing resolution settings to {resolution}...")
            width, height = resolution.split('x')
            with open(modlist_ini, 'r') as f:
                content = f.read()
            content = re.sub(r'^width\s*=\s*\d+$', f'width = {width}', content, flags=re.MULTILINE)
            content = re.sub(r'^height\s*=\s*\d+$', f'height = {height}', content, flags=re.MULTILINE)
            with open(modlist_ini, 'w') as f:
                f.write(content)
            logger.info("Resolution settings edited successfully")
            return True
        except Exception as e:
            logger.error(f"Error editing resolution settings: {e}")
            return False

    def replace_gamepath(self, modlist_ini_path: Path, new_game_path: Path, modlist_sdcard: bool = False) -> bool:
        """Updates the gamePath value in ModOrganizer.ini to the specified path."""
        logger.info(f"Replacing gamePath in {modlist_ini_path} with {new_game_path}")
        if not modlist_ini_path.is_file():
            logger.error(f"ModOrganizer.ini not found at: {modlist_ini_path}")
            return False
        try:
            with open(modlist_ini_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            drive_letter = "D:\\\\" if modlist_sdcard else "Z:\\\\"
            processed_path = self._strip_sdcard_path_prefix(new_game_path)
            windows_style = processed_path.replace('/', '\\')
            windows_style_double = windows_style.replace('\\', '\\\\')
            new_gamepath_line = f'gamePath=@ByteArray({drive_letter}{windows_style_double})\n'
            gamepath_found = False
            for i, line in enumerate(lines):
                if re.match(r'^\s*gamepath\s*=.*$', line, re.IGNORECASE):
                    lines[i] = new_gamepath_line
                    gamepath_found = True
                    break
            if not gamepath_found:
                logger.error("gamePath line not found in ModOrganizer.ini. Aborting.")
                return False
            with open(modlist_ini_path, 'w', encoding='utf-8') as f:
                f.writelines(lines)
            logger.info("gamePath updated successfully")
            return True
        except Exception as e:
            logger.error(f"Error replacing gamePath: {e}")
            return False

    def edit_binary_working_paths(self, modlist_ini_path: Path, modlist_dir_path: Path, modlist_sdcard: bool,
                                  steam_libraries: Optional[List[Path]] = None,
                                  compat_data_path: Optional[Path] = None) -> bool:
        """Update all binary paths and working directories in ModOrganizer.ini. Critical, regression-prone."""
        try:
            logger.debug(f"Updating binary paths and working directories in {modlist_ini_path} to use root: {modlist_dir_path}")
            if not modlist_ini_path.is_file():
                logger.error(f"INI file {modlist_ini_path} does not exist")
                return False
            with open(modlist_ini_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            existing_game_path = None
            gamepath_drive_letter = None
            gamepath_line_index = -1
            for i, line in enumerate(lines):
                if re.match(r'^\s*gamepath\s*=.*@ByteArray\(([^)]+)\)', line, re.IGNORECASE):
                    match = re.search(r'@ByteArray\(([^)]+)\)', line)
                    if match:
                        raw_path = match.group(1)
                        gamepath_line_index = i
                        if raw_path.startswith('Z:'):
                            gamepath_drive_letter = 'Z:'
                        elif raw_path.startswith('D:'):
                            gamepath_drive_letter = 'D:'
                        if raw_path.startswith(('Z:', 'D:')):
                            linux_path = raw_path[2:].replace('\\\\', '/').replace('\\', '/')
                            existing_game_path = linux_path
                            logger.debug(f"Extracted existing gamePath: {existing_game_path}, drive letter: {gamepath_drive_letter}")
                        break
            if modlist_sdcard and existing_game_path and existing_game_path.startswith('/run/media') and gamepath_line_index != -1:
                stripped_path = None
                if compat_data_path:
                    dosdevices_d = compat_data_path / "pfx" / "dosdevices" / "d:"
                    if dosdevices_d.exists():
                        try:
                            d_target = os.readlink(str(dosdevices_d))
                            d_mount = Path(d_target).as_posix().rstrip('/')
                            if existing_game_path.startswith(d_mount):
                                stripped_path = existing_game_path[len(d_mount):]
                                logger.debug(f"Resolved SD card D: mount via dosdevices: {d_mount}")
                        except Exception as e:
                            logger.warning(f"Could not read dosdevices/d: symlink: {e}")
                if stripped_path is None:
                    # Strip the /run/media/deck/<volume> prefix to get the relative path
                    sdcard_pattern = r'^/run/media/[^/]+/[^/]+(.+)$'
                    m = re.match(sdcard_pattern, existing_game_path)
                    if m:
                        stripped_path = m.group(1)
                    else:
                        logger.warning(f"Could not strip SD card prefix from gamePath (no dosdevices symlink available): {existing_game_path}")
                if stripped_path is not None:
                    windows_path = stripped_path.lstrip('/').replace('/', '\\\\')
                    new_gamepath_value = f"D:\\\\{windows_path}"
                    new_gamepath_line = f"gamePath = @ByteArray({new_gamepath_value})\n"
                    logger.info(f"Updating gamePath for SD card: {lines[gamepath_line_index].strip()} -> {new_gamepath_line.strip()}")
                    lines[gamepath_line_index] = new_gamepath_line
            game_path_updated = False
            binary_paths_updated = 0
            working_dirs_updated = 0
            binary_lines = []
            working_dir_lines = []
            for i, line in enumerate(lines):
                stripped = line.strip()
                binary_match = re.match(r'^(\d+)(\\+)\s*binary\s*=.*$', stripped, re.IGNORECASE)
                if binary_match:
                    binary_lines.append((i, stripped, binary_match.group(1), binary_match.group(2)))
                wd_match = re.match(r'^(\d+)(\\+)\s*workingDirectory\s*=.*$', stripped, re.IGNORECASE)
                if wd_match:
                    working_dir_lines.append((i, stripped, wd_match.group(1), wd_match.group(2)))
            binary_paths_by_index = {}
            if existing_game_path and '/steamapps/common/' in existing_game_path:
                steamapps_index = existing_game_path.find('/steamapps/common/')
                steam_lib_root = existing_game_path[:steamapps_index]
                steam_libraries = [Path(steam_lib_root)]
                logger.info(f"Using Steam library from existing gamePath: {steam_lib_root}")
            elif steam_libraries is None or not steam_libraries:
                steam_libraries = self.get_all_steam_library_paths()
                logger.debug(f"Fallback to detected Steam libraries: {steam_libraries}")
            for i, line, index, backslash_style in binary_lines:
                parts = line.split('=', 1)
                if len(parts) != 2:
                    logger.error(f"Malformed binary line: {line}")
                    continue
                key_part, value_part = parts
                cleaned_value = PathHandlerMO2Mixin._clean_malformed_binary_path(value_part)
                exe_name = os.path.basename(cleaned_value).lower()
                if exe_name not in TARGET_EXECUTABLES_LOWER:
                    logger.debug(f"Skipping non-target executable: {exe_name}")
                    continue
                rel_path = None
                if 'steamapps' in cleaned_value:
                    if not gamepath_drive_letter:
                        logger.warning("Vanilla game path detected but gamePath drive letter not found. Skipping binary path update.")
                        continue
                    is_malformed = '"' in cleaned_value or cleaned_value != value_part.strip().strip('"')
                    idx = cleaned_value.index('steamapps')
                    subpath = cleaned_value[idx:].lstrip('/')
                    correct_steam_lib = None
                    for lib in steam_libraries:
                        if len(subpath.split('/')) > 3 and (lib / subpath.split('/')[2] / subpath.split('/')[3]).exists():
                            correct_steam_lib = lib
                            break
                    if not correct_steam_lib and steam_libraries:
                        correct_steam_lib = steam_libraries[0]
                    if correct_steam_lib:
                        drive_prefix = gamepath_drive_letter
                        if is_malformed:
                            logger.info(f"Fixing malformed binary path for {exe_name}: {value_part.strip()}")
                        new_binary_path = f"{drive_prefix}/{correct_steam_lib}/{subpath}".replace('\\', '/').replace('//', '/')
                    else:
                        logger.error("Could not determine correct Steam library for vanilla game path.")
                        continue
                else:
                    drive_prefix = "D:" if modlist_sdcard else "Z:"
                    found_stock = None
                    for folder in STOCK_GAME_FOLDERS:
                        folder_pattern = f"/{folder}"
                        if folder_pattern in cleaned_value:
                            idx = cleaned_value.index(folder_pattern)
                            rel_path = cleaned_value[idx:].lstrip('/')
                            found_stock = folder
                            break
                    if not rel_path:
                        if "/mods/" in cleaned_value:
                            idx = cleaned_value.index("/mods/")
                            rel_path = cleaned_value[idx:].lstrip('/')
                        elif existing_game_path:
                            rel_path = None
                            game_path_base = existing_game_path
                        else:
                            rel_path = exe_name
                    if rel_path is not None:
                        processed_modlist_path = self._strip_sdcard_path_prefix(modlist_dir_path) if modlist_sdcard else str(modlist_dir_path)
                        new_binary_path = f"{drive_prefix}/{processed_modlist_path}/{rel_path}".replace('\\', '/').replace('//', '/')
                    else:
                        new_binary_path = f"{drive_prefix}/{game_path_base}/{exe_name}".replace('\\', '/').replace('//', '/')
                formatted_binary_path = PathHandlerMO2Mixin._format_binary_for_mo2(new_binary_path)
                if '"' in formatted_binary_path:
                    formatted_binary_path = formatted_binary_path.replace('"', '')
                new_binary_line = f"{index}{backslash_style}binary = {formatted_binary_path}"
                logger.info(f"Updating binary path: {line.strip()} -> {new_binary_line}")
                original_line = lines[i]
                lines[i] = new_binary_line + '\n'
                binary_paths_updated += 1
                binary_paths_by_index[index] = formatted_binary_path
            for j, wd_line, index, backslash_style in working_dir_lines:
                if index in binary_paths_by_index:
                    binary_path = binary_paths_by_index[index]
                    wd_path = os.path.dirname(binary_path)
                    drive_prefix = "D:" if binary_path.startswith("D:") else "Z:" if binary_path.startswith("Z:") else ("D:" if modlist_sdcard else "Z:")
                    if wd_path.startswith("D:") or wd_path.startswith("Z:"):
                        wd_path = wd_path[2:]
                    wd_path = drive_prefix + wd_path
                    formatted_wd_path = PathHandlerMO2Mixin._format_workingdir_for_mo2(wd_path)
                    key_part = f"{index}{backslash_style}workingDirectory"
                    new_wd_line = f"{key_part} = {formatted_wd_path}"
                    logger.debug(f"Updating working directory: {wd_line.strip()} -> {new_wd_line}")
                    original_wd_line = lines[j]
                    lines[j] = new_wd_line + '\n'
                    working_dirs_updated += 1
            with open(modlist_ini_path, 'w', encoding='utf-8') as f:
                f.writelines(lines)
            logger.info(f"edit_binary_working_paths completed: Game path updated: {game_path_updated}, Binary paths updated: {binary_paths_updated}, Working directories updated: {working_dirs_updated}")
            return True
        except Exception as e:
            logger.error(f"Error updating binary paths in {modlist_ini_path}: {str(e)}")
            return False

    def _format_path_for_mo2(self, path: str) -> str:
        """Format a path for MO2's ModOrganizer.ini file (working directories)."""
        formatted = path.replace('/', '\\')
        if not re.match(r'^[A-Za-z]:', formatted):
            formatted = 'D:' + formatted
        formatted = formatted.replace('\\', '\\\\')
        return formatted

    def _format_binary_path_for_mo2(self, path_str) -> str:
        """Format a binary path for MO2 config file. Binary paths need forward slashes."""
        return path_str.replace('\\', '/')

    def _format_working_dir_for_mo2(self, path_str) -> str:
        """Format a working directory path for MO2 config file. Ensures double backslashes."""
        path = path_str.replace('/', '\\')
        path = path.replace('\\', '\\\\')
        path = re.sub(r'^([A-Z]:)\\\\+', r'\1\\\\', path)
        return path

    @staticmethod
    def _format_gamepath_for_mo2(path: str) -> str:
        path = path.replace('/', '\\')
        path = re.sub(r'\\+', r'\\', path)
        path = re.sub(r'^([A-Z]:)\\+', r'\1\\', path)
        return path

    @staticmethod
    def _clean_malformed_binary_path(value_part: str) -> str:
        """Clean up malformed binary paths from engine (e.g., quotes in wrong places)."""
        cleaned = value_part.strip()
        if cleaned.startswith('"') and '"' in cleaned[1:]:
            quote_end = cleaned.find('"', 1)
            if quote_end > 0:
                after_quote = cleaned[quote_end + 1:].strip()
                if after_quote.startswith('/') or after_quote:
                    path_part = cleaned[1:quote_end]
                    remaining = after_quote.lstrip('/')
                    cleaned = f"{path_part}/{remaining}" if remaining else path_part
                    logger.info(f"Cleaned malformed binary path: {value_part} -> {cleaned}")
        cleaned = cleaned.strip('"')
        cleaned = cleaned.replace('\\', '/')
        return cleaned

    @staticmethod
    def _format_binary_for_mo2(path: str) -> str:
        path = path.replace('\\', '/')
        path = re.sub(r'^([A-Z]:)//+', r'\1/', path)
        return path

    @staticmethod
    def _format_workingdir_for_mo2(path: str) -> str:
        path = path.replace('/', '\\')
        path = path.replace('\\', '\\\\')
        path = re.sub(r'^([A-Z]:)\\\\+', r'\1\\\\', path)
        return path

    def set_download_directory(self, modlist_ini_path: Path, download_dir_linux_path, modlist_sdcard: bool) -> bool:
        """
        Set download_directory in ModOrganizer.ini to the correct Wine path (Z: or D: for SD card).
        Replaces ALL occurrences of the key throughout the file - MO2 reads the last one, and
        duplicate [General] sections from Wabbajack installs are common.
        """
        if not modlist_ini_path.is_file() or not download_dir_linux_path:
            return False
        try:
            path_obj = Path(download_dir_linux_path)
            if modlist_sdcard:
                drive = "D:"
                path_part = self._strip_sdcard_path_prefix(path_obj)
                if path_part.startswith('/'):
                    path_part = path_part[1:]
                path_part = path_part.replace('/', '\\')
            else:
                drive = "Z:"
                path_part = str(path_obj).replace('/', '\\').lstrip('\\')
            wine_path = drive + "\\" + path_part
            formatted = PathHandlerMO2Mixin._format_workingdir_for_mo2(wine_path)
            with open(modlist_ini_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            new_line = f"download_directory = {formatted}\n"
            replaced = [i for i, l in enumerate(lines) if re.match(r'^\s*download_directory\s*=', l, re.IGNORECASE)]
            if replaced:
                for i in replaced:
                    lines[i] = new_line
            else:
                # No existing entry - insert after [General]
                insert_idx = next((i for i, l in enumerate(lines) if re.match(r'^\s*\[General\]', l, re.I)), -1)
                if insert_idx >= 0:
                    insert_idx += 1
                    while insert_idx < len(lines) and not re.match(r'^\s*\[', lines[insert_idx]):
                        insert_idx += 1
                    lines.insert(insert_idx, new_line)
                else:
                    lines.append("[General]\n")
                    lines.append(new_line)
            with open(modlist_ini_path, 'w', encoding='utf-8') as f:
                f.writelines(lines)
            logger.info(f"Set download_directory in ModOrganizer.ini to {formatted} ({len(replaced)} occurrence(s))")
            return True
        except Exception as e:
            logger.error(f"Error setting download_directory in {modlist_ini_path}: {e}")
            return False

    def get_download_directory_linux_path(self, modlist_ini_path: Path) -> Optional[str]:
        """
        Read the first valid download_directory value from ModOrganizer.ini and convert to a Linux path.
        Returns None if no valid Z: or D: path is found.
        """
        if not modlist_ini_path.is_file():
            return None
        try:
            with open(modlist_ini_path, 'r', encoding='utf-8-sig') as f:
                lines = f.readlines()
        except UnicodeDecodeError:
            try:
                with open(modlist_ini_path, 'r', encoding='latin-1') as f:
                    lines = f.readlines()
            except Exception:
                return None
        except Exception:
            return None
        for line in lines:
            m = re.match(r'^\s*download_directory\s*=\s*(.+)$', line, re.IGNORECASE)
            if not m:
                continue
            raw = m.group(1).strip()
            ba = re.match(r'@ByteArray\((.+)\)$', raw)
            if ba:
                raw = ba.group(1).strip()
            # Engine's RemapMO2File writes a raw Linux path directly
            if raw.startswith('/'):
                return raw
            # Expect Z:\\path\\... or D:\\path\\... (MO2 doubles backslashes in the file)
            drive_m = re.match(r'^([ZzDd]):(.+)$', raw)
            if not drive_m:
                continue
            drive, rest = drive_m.group(1).upper(), drive_m.group(2)
            # Collapse doubled backslashes back to single separators
            rest = re.sub(r'\\\\', '/', rest).replace('\\', '/')
            if drive == 'Z':
                return '/' + rest.lstrip('/')
            # D: (SD card) - return as-is with leading slash; caller handles sdcard prefix
            return '/' + rest.lstrip('/')
        return None
