"""
FileSystemHandler module for managing file system operations.
This module handles path normalization, validation, and file operations.
"""

import os
import shutil
import logging
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from datetime import datetime
import re
import time
import subprocess
import pwd
import grp
from jackify.shared.colors import COLOR_PROMPT, COLOR_RESET

from .filesystem_handler_download import FilesystemDownloadMixin
from .filesystem_handler_ownership import FilesystemOwnershipMixin
from .filesystem_handler_steam import FilesystemSteamMixin
from .filesystem_handler_first_launch import FilesystemFirstLaunchMixin

logger = logging.getLogger(__name__)

class FileSystemHandler(
    FilesystemDownloadMixin, FilesystemOwnershipMixin, FilesystemSteamMixin, FilesystemFirstLaunchMixin
):
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
    @staticmethod
    def normalize_path(path: str) -> Path:
        """Normalize a path string to a Path object."""
        try:
            if path.startswith('~'):
                path = os.path.expanduser(path)
            path = os.path.abspath(path)
            return Path(path)
        except Exception as e:
            logger.error(f"Failed to normalize path {path}: {e}")
            return Path(path)
        
    @staticmethod
    def validate_path(path: Path) -> bool:
        """Validate if a path exists and is accessible."""
        try:
            if not path.exists():
                logger.warning(f"Validation failed: Path does not exist - {path}")
                return False
            # Check read access
            if not os.access(path, os.R_OK):
                logger.warning(f"Validation failed: No read access - {path}")
                return False
            # Check write access (important for many operations)
            if path.is_dir():
                if not os.access(path, os.W_OK):
                    logger.warning(f"Validation failed: No write access to directory - {path}")
                    return False
            elif path.is_file():
                # Check write access to the parent directory for file creation/modification
                if not os.access(path.parent, os.W_OK):
                    logger.warning(f"Validation failed: No write access to parent dir of file - {path.parent}")
                    return False
            return True
        except Exception as e:
            logger.error(f"Failed to validate path {path}: {e}")
            return False
        
    @staticmethod
    def ensure_directory(path: Path) -> bool:
        """Ensure a directory exists, create if it doesn't."""
        try:
            path.mkdir(parents=True, exist_ok=True)
            logger.debug(f"Ensured directory exists: {path}")
            return True
        except Exception as e:
            logger.error(f"Failed to ensure directory {path}: {e}")
            return False
        
    @staticmethod
    def backup_file(file_path: Path, backup_dir: Optional[Path] = None) -> Optional[Path]:
        """Create a backup of a file with timestamp."""
        try:
            if not file_path.is_file():
                logger.error(f"Backup failed: Source is not a file - {file_path}")
                return None
            
            if backup_dir is None:
                backup_dir = file_path.parent / "backups"
            
            FileSystemHandler.ensure_directory(backup_dir)
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = backup_dir / f"{file_path.stem}_{timestamp}{file_path.suffix}"
            
            shutil.copy2(file_path, backup_path)
            logger.info(f"File backed up to: {backup_path}")
            return backup_path
        except Exception as e:
            logger.error(f"Failed to backup file {file_path}: {e}")
            return None
        
    @staticmethod
    def restore_backup(backup_path: Path, target_path: Path) -> bool:
        """Restore a file from backup, backing up the current target first."""
        try:
            if not backup_path.is_file():
                logger.error(f"Restore failed: Backup source is not a file - {backup_path}")
                return False
            
            if target_path.exists():
                logger.warning(f"Target file exists, creating backup before restore: {target_path}")
                FileSystemHandler.backup_file(target_path)
            
            # Ensure target directory exists
            FileSystemHandler.ensure_directory(target_path.parent)
            
            shutil.copy2(backup_path, target_path)
            logger.info(f"Restored {backup_path} to {target_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to restore backup {backup_path} to {target_path}: {e}")
            return False
        
    @staticmethod
    def find_latest_backup(original_file_path: Path) -> Optional[Path]:
        """Finds the most recent backup file for a given original file path."""
        if not original_file_path.exists():
            logger.warning(f"Cannot find backups for non-existent file: {original_file_path}")
            return None

        backup_dir = original_file_path.parent / "backups"
        if not backup_dir.is_dir():
            logger.debug(f"Backup directory not found: {backup_dir}")
            return None

        file_stem = original_file_path.stem
        file_suffix = original_file_path.suffix
        
        # Look for timestamped backups first (e.g., shortcuts_20230101_120000.vdf)
        # Adjusted glob pattern to match the format used in backup_file
        timestamp_pattern = f"{file_stem}_*_*{file_suffix}"
        timestamped_backups = list(backup_dir.glob(timestamp_pattern))
        
        latest_backup_path = None
        latest_timestamp = 0

        if timestamped_backups:
            logger.debug(f"Found potential timestamped backups: {timestamped_backups}")
            for backup_path in timestamped_backups:
                # Extract timestamp from filename (e.g., stem_YYYYMMDD_HHMMSS.suffix)
                try:
                    name_parts = backup_path.stem.split('_')
                    if len(name_parts) >= 3:
                        # Combine date and time parts for parsing
                        timestamp_str = f"{name_parts[-2]}_{name_parts[-1]}"
                        backup_time = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S").timestamp()
                        if backup_time > latest_timestamp:
                            latest_timestamp = backup_time
                            latest_backup_path = backup_path
                    else:
                        logger.warning(f"Could not parse timestamp from backup filename: {backup_path.name}")
                except (ValueError, IndexError) as e:
                    logger.warning(f"Error parsing timestamp from {backup_path.name}: {e}")
            
            if latest_backup_path:
                logger.info(f"Latest timestamped backup found: {latest_backup_path}")
                return latest_backup_path

        # If no timestamped backup found, check for simple .bak file
        simple_backup_path = backup_dir / f"{original_file_path.name}.bak"
        # Correction: Simple backup might be in the *same* directory, not backup_dir
        simple_backup_path_alt = original_file_path.with_suffix(f"{file_suffix}.bak")
        
        if simple_backup_path_alt.is_file():
             logger.info(f"Found simple backup file: {simple_backup_path_alt}")
             return simple_backup_path_alt
        elif simple_backup_path.is_file(): # Check in backup dir as fallback
             logger.info(f"Found simple backup file in backup dir: {simple_backup_path}")
             return simple_backup_path

        logger.warning(f"No suitable backup found for {original_file_path} in {backup_dir} or adjacent.")
        return None
        
    @staticmethod
    def get_permissions(path: Path) -> Optional[int]:
        """Get file or directory permissions (last 3 octal digits)."""
        try:
            return os.stat(path).st_mode & 0o777
        except Exception as e:
            logger.error(f"Failed to get permissions for {path}: {e}")
            return None
        
    @staticmethod
    def is_sd_card(path: Path) -> bool:
        """Check if a path likely resides on an SD card based on common mount points."""
        try:
            # Get the absolute path to resolve symlinks etc.
            abs_path_str = str(path.resolve())
            
            # Common SD card mount patterns/devices on Linux/Steam Deck
            sd_patterns = [
                "/run/media/mmcblk",
                "/media/mmcblk",
                "/dev/mmcblk"
            ]

            # Check if path starts with known mount points
            for pattern in sd_patterns:
                if abs_path_str.startswith(pattern):
                    logger.debug(f"Path {path} matches SD card pattern: {pattern}")
                    return True

            logger.debug(f"Path {path} does not appear to be on a standard SD card mount.")
            return False
            
        except Exception as e:
            logger.error(f"Error checking if path is on SD card: {e}")
            return False # Default to False on error
        
    @staticmethod
    def get_directory_size(path: Path) -> Optional[int]:
        """Get the total size of a directory in bytes."""
        try:
            total_size = 0
            for entry in os.scandir(path):
                if entry.is_dir(follow_symlinks=False):
                    total_size += FileSystemHandler.get_directory_size(Path(entry.path)) or 0
                elif entry.is_file(follow_symlinks=False):
                    total_size += entry.stat().st_size
            return total_size
        except Exception as e:
            logger.error(f"Failed to get directory size for {path}: {e}")
            return None
        
    @staticmethod
    def cleanup_directory(path: Path, age_days: int) -> bool:
        """Delete files in a directory older than age_days."""
        try:
            if not path.is_dir():
                logger.error(f"Cleanup failed: Not a directory - {path}")
                return False
            
            current_time = time.time()
            age_seconds = age_days * 86400
            deleted_count = 0
            
            for item in path.iterdir():
                if item.is_file():
                    try:
                        file_age = current_time - item.stat().st_mtime
                        if file_age > age_seconds:
                            item.unlink()
                            logger.debug(f"Deleted old file: {item}")
                            deleted_count += 1
                    except Exception as item_e:
                        logger.warning(f"Could not process/delete file {item}: {item_e}")
            
            logger.info(f"Cleanup complete for {path}. Deleted {deleted_count} files older than {age_days} days.")
            return True
        except Exception as e:
            logger.error(f"Failed to clean up directory {path}: {e}")
            return False
        
    @staticmethod
    def move_directory(source: Path, destination: Path) -> bool:
        """Move a directory and its contents."""
        try:
            if not source.is_dir():
                logger.error(f"Move failed: Source is not a directory - {source}")
                return False
            
            FileSystemHandler.ensure_directory(destination.parent)
            
            shutil.move(str(source), str(destination))
            logger.info(f"Moved directory {source} to {destination}")
            return True
        except Exception as e:
            logger.error(f"Failed to move directory {source} to {destination}: {e}")
            return False
        
    @staticmethod
    def copy_directory(source: Path, destination: Path, dirs_exist_ok=True) -> bool:
        """Copy a directory and its contents."""
        try:
            if not source.is_dir():
                logger.error(f"Copy failed: Source is not a directory - {source}")
                return False
            
            FileSystemHandler.ensure_directory(destination.parent)

            shutil.copytree(source, destination, dirs_exist_ok=dirs_exist_ok) 
            logger.info(f"Copied directory {source} to {destination}")
            return True
        except Exception as e:
            logger.error(f"Failed to copy directory {source} to {destination}: {e}")
            return False
        
    @staticmethod
    def list_directory(path: Path, pattern: Optional[str] = None) -> List[Path]:
        """List contents of a directory, optionally filtering by pattern."""
        try:
            if not path.is_dir():
                logger.error(f"Cannot list: Not a directory - {path}")
                return []
            
            if pattern:
                return list(path.glob(pattern))
            else:
                return list(path.iterdir())
        except Exception as e:
            logger.error(f"Failed to list directory {path}: {e}")
            return []
        
    @staticmethod
    def backup_modorganizer(modlist_ini: Path) -> bool:
        """Backs up ModOrganizer.ini and adds a backupPath entry."""
        logger.info(f"Backing up {modlist_ini}...")
        backup_path = FileSystemHandler.backup_file(modlist_ini)
        if not backup_path:
            return False
        
        try:
            # Add backupPath entry (read, find gamePath, duplicate/rename, write)
            content = modlist_ini.read_text().splitlines()
            new_content = []
            gamepath_line = None
            backupath_exists = False
            
            for line in content:
                new_content.append(line)
                if line.strip().startswith("gamePath="):
                    gamepath_line = line
                if line.strip().startswith("backupPath="):
                    backupath_exists = True
            
            if gamepath_line and not backupath_exists:
                backupath_line = gamepath_line.replace("gamePath=", "backupPath=", 1)
                # Find the index of gamepath_line to insert backupath after it
                try:
                    gamepath_index = new_content.index(gamepath_line)
                    new_content.insert(gamepath_index + 1, backupath_line)
                    logger.debug("Added backupPath entry to ModOrganizer.ini")
                except ValueError:
                    logger.warning("Could not find gamePath line index to insert backupPath.")
                    new_content.append(backupath_line) # Append at end as fallback
                
                modlist_ini.write_text("\n".join(new_content) + "\n")
            elif backupath_exists:
                logger.debug("backupPath already exists in ModOrganizer.ini")
            else:
                logger.warning("gamePath not found, cannot add backupPath entry.")

            return True
        except Exception as e:
            logger.error(f"Failed to add backupPath entry to {modlist_ini}: {e}")
            return False # Backup succeeded, but adding entry failed

    def copy_file(self, src: Path, dst: Path, overwrite: bool = False) -> bool:
        """
        Copy a file from source to destination.
        
        Args:
            src: Source file path
            dst: Destination file path
            overwrite: Whether to overwrite existing file
            
        Returns:
            bool: True if file was copied successfully, False otherwise
        """
        try:
            if not overwrite and os.path.exists(dst):
                self.logger.info(f"Destination file already exists: {dst}")
                return False
            
            shutil.copy2(src, dst)
            return True
        except Exception as e:
            self.logger.error(f"Error copying file: {e}")
            return False
    
    def move_file(self, src: Path, dst: Path, overwrite: bool = False) -> bool:
        """
        Move a file from source to destination.
        
        Args:
            src: Source file path
            dst: Destination file path
            overwrite: Whether to overwrite existing file
            
        Returns:
            bool: True if file was moved successfully, False otherwise
        """
        try:
            if not overwrite and os.path.exists(dst):
                self.logger.info(f"Destination file already exists: {dst}")
                return False
            
            shutil.move(src, dst)
            return True
        except Exception as e:
            self.logger.error(f"Error moving file: {e}")
            return False
    
    def delete_file(self, path: Path) -> bool:
        """
        Delete a file.
        
        Args:
            path: Path to the file to delete
            
        Returns:
            bool: True if file was deleted successfully, False otherwise
        """
        try:
            if os.path.exists(path):
                os.remove(path)
                return True
            return False
        except Exception as e:
            self.logger.error(f"Error deleting file: {e}")
            return False
    
    def delete_directory(self, path: Path, recursive: bool = True) -> bool:
        """
        Delete a directory.
        
        Args:
            path: Path to the directory to delete
            recursive: Whether to delete directory recursively
            
        Returns:
            bool: True if directory was deleted successfully, False otherwise
        """
        try:
            if os.path.exists(path):
                if recursive:
                    shutil.rmtree(path)
                else:
                    os.rmdir(path)
                return True
            return False
        except Exception as e:
            self.logger.error(f"Error deleting directory: {e}")
            return False
    
    def create_required_dirs(self, game_name: str, appid: str, modlist_dir: Optional[str] = None) -> bool:
        """
        Create required directories for a game modlist

        This includes both Linux home directories and Wine prefix directories.
        Creating the Wine prefix Documents directories is critical for USVFS
        to work properly on first launch - USVFS needs the target directory
        to exist before it can virtualize profile INI files.

        Args:
            game_name: Name of the game (e.g., skyrimse, fallout4)
            appid: Steam AppID of the modlist
            modlist_dir: Modlist install directory, used to seed the MO2 profile's own
                INI files for games whose plugin has no bundled default-ini fallback
        Returns:
            bool: True if directories were created successfully, False otherwise
        """
        try:
            # Define base paths
            home_dir = os.path.expanduser("~")
            
            # Game-specific Documents directory names (for both Linux home and Wine prefix)
            game_docs_dirs = {
                "skyrimse": "Skyrim Special Edition",
                "skyrimvr": "Skyrim VR",
                "fallout4": "Fallout4",
                "fallout4vr": "Fallout4VR",
                "falloutnv": "FalloutNV",
                "oblivion": "Oblivion",
                "oblivion_remastered": "Oblivion Remastered",
                "enderal": "Enderal Special Edition",
                "enderalse": "Enderal Special Edition",
                "starfield": "Starfield",
            }
            
            game_dirs = {
                # Common directories needed across all games
                "common": [
                    os.path.join(home_dir, ".local", "share", "Steam", "steamapps", "compatdata", appid, "pfx"),
                    os.path.join(home_dir, ".steam", "steam", "steamapps", "compatdata", appid, "pfx")
                ],
                # Game-specific directories in Linux home (legacy, may not be needed)
                "skyrimse": [
                    os.path.join(home_dir, "Documents", "My Games", "Skyrim Special Edition"),
                ],
                "fallout4": [
                    os.path.join(home_dir, "Documents", "My Games", "Fallout4"),
                ],
                "falloutnv": [
                    os.path.join(home_dir, "Documents", "My Games", "FalloutNV"),
                ],
                "oblivion": [
                    os.path.join(home_dir, "Documents", "My Games", "Oblivion"),
                ]
            }
            
            # Create common directories (compatdata pfx paths)
            for dir_path in game_dirs["common"]:
                if dir_path and os.path.exists(os.path.dirname(dir_path)):
                    os.makedirs(dir_path, exist_ok=True)
                    self.logger.debug(f"Created directory: {dir_path}")
            
            # Create game-specific directories in Linux home (legacy support)
            if game_name in game_dirs:
                for dir_path in game_dirs[game_name]:
                    os.makedirs(dir_path, exist_ok=True)
                    self.logger.debug(f"Created game-specific directory: {dir_path}")
            
            # CP2077 and BG3 use AppData/Local only (no My Games)
            appdata_only_dirs = {
                "cp2077": os.path.join("CD Projekt Red", "Cyberpunk 2077"),
                "bg3": os.path.join("Larian Studios", "Baldur's Gate 3"),
            }

            # CRITICAL: Create game-specific directories in Wine prefix
            # Required for USVFS to virtualize profile INIs on first launch
            from ..handlers.path_handler import PathHandler
            path_handler = PathHandler()
            compatdata_path = path_handler.find_compat_data(appid)

            if compatdata_path:
                prefix_user = os.path.join(
                    str(compatdata_path), "pfx", "drive_c", "users", "steamuser"
                )

                if game_name in appdata_only_dirs:
                    appdata_path = os.path.join(
                        prefix_user, "AppData", "Local", appdata_only_dirs[game_name]
                    )
                    try:
                        os.makedirs(appdata_path, exist_ok=True)
                        self.logger.info(f"Created Wine prefix AppData/Local directory: {appdata_path}")
                    except Exception as e:
                        self.logger.warning(f"Could not create AppData/Local directory {appdata_path}: {e}")

                elif game_name in game_docs_dirs:
                    docs_dir_name = game_docs_dirs[game_name]
                    wine_docs_path = os.path.join(
                        prefix_user, "Documents", "My Games", docs_dir_name
                    )
                    try:
                        os.makedirs(wine_docs_path, exist_ok=True)
                        self.logger.info(f"Created Wine prefix Documents directory: {wine_docs_path}")
                    except Exception as e:
                        self.logger.warning(f"Could not create Wine prefix Documents directory {wine_docs_path}: {e}")

                    if game_name == "skyrimse":
                        self._seed_skyrim_first_launch_files(prefix_user, docs_dir_name)
                    elif game_name == "fallout4":
                        self._seed_fo4_first_launch_files(prefix_user, docs_dir_name)
                    elif game_name == "skyrimvr":
                        self._seed_skyrimvr_first_launch_files(prefix_user, docs_dir_name)
                    elif game_name == "fallout4vr":
                        self._seed_fallout4vr_first_launch_files(prefix_user, docs_dir_name)
                    elif game_name == "starfield":
                        self._seed_starfield_first_launch_files(prefix_user, docs_dir_name, modlist_dir)
            else:
                self.logger.warning(f"Could not find compatdata path for AppID {appid}, skipping Wine prefix directory creation")
            
            return True
        except Exception as e:
            self.logger.error(f"Error creating required directories: {e}")
            return False

