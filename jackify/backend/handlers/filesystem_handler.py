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
import subprocess # Needed for running sudo commands
import pwd # To get user name
import grp # To get group name
import requests # Import requests
import vdf # Import VDF library at the top level
from jackify.shared.colors import COLOR_PROMPT, COLOR_RESET

# Initialize logger for the module
logger = logging.getLogger(__name__)

class FileSystemHandler:
    def __init__(self):
        # Keep instance logger if needed, but static methods use module logger
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
            return Path(path) # Return original path as Path object on error
        
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
            # For directories, check write on parent; for files, check write on file itself
            if path.is_dir():
                if not os.access(path, os.W_OK):
                    logger.warning(f"Validation failed: No write access to directory - {path}")
                    return False
            elif path.is_file():
                # Check write access to the parent directory for file creation/modification
                if not os.access(path.parent, os.W_OK):
                    logger.warning(f"Validation failed: No write access to parent dir of file - {path.parent}")
                    return False
            return True # Passed existence and access checks
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
    def set_permissions(path: Path, permissions: int = 0o755, recursive: bool = True) -> bool:
        """Set file or directory permissions (non-sudo)."""
        try:
            if not path.exists():
                logger.error(f"Cannot set permissions: Path does not exist - {path}")
                return False
            
            if recursive and path.is_dir():
                for root, dirs, files in os.walk(path):
                    try:
                        os.chmod(root, 0o755) # Dirs typically 755
                    except Exception as dir_e:
                        logger.warning(f"Failed to chmod dir {root}: {dir_e}")
                    for file in files:
                        try:
                            os.chmod(os.path.join(root, file), 0o644) # Files typically 644
                        except Exception as file_e:
                            logger.warning(f"Failed to chmod file {os.path.join(root, file)}: {file_e}")
            elif path.is_file():
                os.chmod(path, 0o644 if permissions == 0o755 else permissions) # Default file perms 644
            elif path.is_dir():
                os.chmod(path, permissions) # Set specific perm for top-level dir if not recursive
            logger.debug(f"Set permissions for {path} (recursive={recursive})")
            return True
        except Exception as e:
            logger.error(f"Failed to set permissions for {path}: {e}")
            return False
        
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

            # Less reliable: Check mount point info (can be slow/complex)
            # try:
            #      # ... (logic using /proc/mounts or df command) ...
            # except Exception as mount_e:
            #      logger.warning(f"Could not reliably check mount point for {path}: {mount_e}")

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
            
            shutil.move(str(source), str(destination)) # shutil.move needs strings
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
            
            # shutil.copytree needs destination to NOT exist unless dirs_exist_ok=True (Py 3.8+)
            # Ensure parent exists
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

    @staticmethod
    def blank_downloads_dir(modlist_ini: Path) -> bool:
        """Blanks the download_directory line in ModOrganizer.ini."""
        logger.info(f"Blanking download_directory in {modlist_ini}...")
        try:
            content = modlist_ini.read_text().splitlines()
            new_content = []
            found = False
            for line in content:
                if line.strip().startswith("download_directory="):
                    new_content.append("download_directory=")
                    found = True
                else:
                    new_content.append(line)
            
            if found:
                modlist_ini.write_text("\n".join(new_content) + "\n")
                logger.debug("download_directory line blanked.")
            else:
                logger.warning("download_directory line not found.")
                # Consider if we should add it blank?
            
            return True
        except Exception as e:
            logger.error(f"Failed to blank download_directory in {modlist_ini}: {e}")
            return False

    @staticmethod
    def copy_file(src: Path, dst: Path, overwrite: bool = False) -> bool:
        """Copy a single file."""
        try:
            if not src.is_file():
                logger.error(f"Copy failed: Source is not a file - {src}")
                return False
            if dst.exists() and not overwrite:
                logger.warning(f"Copy skipped: Destination exists and overwrite=False - {dst}")
                return False # Or True, depending on desired behavior for skip
            
            FileSystemHandler.ensure_directory(dst.parent)
            shutil.copy2(src, dst)
            logger.debug(f"Copied file {src} to {dst}")
            return True
        except Exception as e:
            logger.error(f"Failed to copy file {src} to {dst}: {e}")
            return False

    @staticmethod
    def move_file(src: Path, dst: Path, overwrite: bool = False) -> bool:
        """Move a single file."""
        try:
            if not src.is_file():
                logger.error(f"Move failed: Source is not a file - {src}")
                return False
            if dst.exists() and not overwrite:
                logger.warning(f"Move skipped: Destination exists and overwrite=False - {dst}")
                return False
            
            FileSystemHandler.ensure_directory(dst.parent)
            shutil.move(str(src), str(dst)) # shutil.move needs strings
            # Create backup with timestamp
            timestamp = os.path.getmtime(modlist_ini)
            backup_path = modlist_ini.with_suffix(f'.{timestamp:.0f}.bak')
            
            # Copy file to backup
            shutil.copy2(modlist_ini, backup_path)
            
            # Copy game path to backup path
            with open(modlist_ini, 'r') as f:
                lines = f.readlines()
            
            game_path_line = None
            for line in lines:
                if line.startswith('gamePath'):
                    game_path_line = line
                    break
            
            if game_path_line:
                # Create backup path entry
                backup_path_line = game_path_line.replace('gamePath', 'backupPath')
                
                # Append to file if not already present
                with open(modlist_ini, 'a') as f:
                    f.write(backup_path_line)
                
                self.logger.debug(f"Backed up ModOrganizer.ini and created backupPath entry")
                return True
            else:
                self.logger.error("No gamePath found in ModOrganizer.ini")
                return False
            
        except Exception as e:
            self.logger.error(f"Error backing up ModOrganizer.ini: {e}")
            return False
    
    def blank_downloads_dir(self, modlist_ini: Path) -> bool:
        """
        Blank or reset the MO2 Downloads Directory
        Returns True on success, False on failure
        """
        try:
            self.logger.info("Editing download_directory...")
            
            # Read the file
            with open(modlist_ini, 'r') as f:
                content = f.read()
            
            # Replace the download_directory line
            modified_content = re.sub(r'download_directory[^\n]*', 'download_directory =', content)
            
            # Write back to the file
            with open(modlist_ini, 'w') as f:
                f.write(modified_content)
            
            self.logger.debug("Download directory cleared successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"Error blanking downloads directory: {e}")
            return False

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
    
    def create_required_dirs(self, game_name: str, appid: str) -> bool:
        """
        Create required directories for a game modlist
        
        Args:
            game_name: Name of the game (e.g., skyrimse, fallout4)
            appid: Steam AppID of the modlist
            
        Returns:
            bool: True if directories were created successfully, False otherwise
        """
        try:
            # Define base paths
            home_dir = os.path.expanduser("~")
            game_dirs = {
                # Common directories needed across all games
                "common": [
                    os.path.join(home_dir, ".local", "share", "Steam", "steamapps", "compatdata", appid, "pfx"),
                    os.path.join(home_dir, ".steam", "steam", "steamapps", "compatdata", appid, "pfx")
                ],
                # Game-specific directories
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
            
            # Create common directories
            for dir_path in game_dirs["common"]:
                if dir_path and os.path.exists(os.path.dirname(dir_path)):
                    os.makedirs(dir_path, exist_ok=True)
                    self.logger.debug(f"Created directory: {dir_path}")
            
            # Create game-specific directories
            if game_name in game_dirs:
                for dir_path in game_dirs[game_name]:
                    os.makedirs(dir_path, exist_ok=True)
                    self.logger.debug(f"Created game-specific directory: {dir_path}")
            
            return True
        except Exception as e:
            self.logger.error(f"Error creating required directories: {e}")
            return False

    @staticmethod
    def all_owned_by_user(path: Path) -> bool:
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
    def set_ownership_and_permissions_sudo(path: Path, status_callback=None) -> bool:
        """Change ownership and permissions using sudo (robust, with timeout and re-prompt)."""
        if not path.exists():
            logger.error(f"Path does not exist: {path}")
            return False
        # Check if all files/dirs are already owned by the user
        if FileSystemHandler.all_owned_by_user(path):
            logger.info(f"All files in {path} are already owned by the current user. Skipping sudo chown/chmod.")
            return True
        try:
            user_name = pwd.getpwuid(os.geteuid()).pw_name
            group_name = grp.getgrgid(os.geteuid()).gr_name
        except KeyError:
            logger.error("Could not determine current user or group name.")
            return False

        log_msg = f"Applying ownership/permissions for {path} (user: {user_name}, group: {group_name}) via sudo."
        logger.info(log_msg)
        if status_callback:
            status_callback(f"Setting ownership/permissions for {os.path.basename(str(path))}...")
        else:
            print(f'\n{COLOR_PROMPT}Adjusting permissions for {path} (may require sudo password)...{COLOR_RESET}')

        def run_sudo_with_retries(cmd, desc, max_retries=3, timeout=300):
            for attempt in range(max_retries):
                try:
                    logger.info(f"Running sudo command (attempt {attempt+1}/{max_retries}): {' '.join(cmd)}")
                    result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=timeout)
                    if result.returncode == 0:
                        return True
                    else:
                        logger.error(f"sudo {desc} failed. Error: {result.stderr.strip()}")
                        print(f"Error: Failed to {desc}. Check logs.")
                        return False
                except subprocess.TimeoutExpired:
                    logger.error(f"sudo {desc} timed out (attempt {attempt+1}/{max_retries}).")
                    print(f"\nSudo prompt timed out after {timeout} seconds. Please try again.")
                    # Flush input if possible, then retry
            print(f"Failed to {desc} after {max_retries} attempts. Aborting.")
            return False

        # Run chown with retries
        chown_command = ['sudo', 'chown', '-R', f'{user_name}:{group_name}', str(path)]
        if not run_sudo_with_retries(chown_command, "change ownership"):
            return False
        print()
        # Run chmod with retries
        chmod_command = ['sudo', 'chmod', '-R', '755', str(path)]
        if not run_sudo_with_retries(chmod_command, "set permissions"):
            return False
        print()
        logger.info("Permissions set successfully.")
        return True

    def download_file(self, url: str, destination_path: Path, overwrite: bool = False, quiet: bool = False) -> bool:
        """Downloads a file from a URL to a destination path."""
        self.logger.info(f"Downloading {url} to {destination_path}...")
        
        if not overwrite and destination_path.exists():
            self.logger.info(f"File already exists, skipping download: {destination_path}")
            # Only print if not quiet
            if not quiet:
                print(f"File {destination_path.name} already exists, skipping download.")
            return True # Consider existing file as success
            
        try:
            # Ensure destination directory exists
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Perform the download with streaming
            with requests.get(url, stream=True, timeout=300, verify=True) as r:
                r.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
                with open(destination_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
                        
            self.logger.info("Download complete.")
            # Only print if not quiet
            if not quiet:
                print("Download complete.")
            return True
            
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Download failed: {e}")
            print(f"Error: Download failed for {url}. Check network connection and URL.")
            # Clean up potentially incomplete file
            if destination_path.exists():
                try: destination_path.unlink() 
                except OSError: pass
            return False
        except Exception as e:
            self.logger.error(f"Error during download or file writing: {e}", exc_info=True)
            print("Error: An unexpected error occurred during download.")
             # Clean up potentially incomplete file
            if destination_path.exists():
                try: destination_path.unlink() 
                except OSError: pass
            return False 

    @staticmethod
    def find_steam_library() -> Optional[Path]:
        """
        Find the Steam library containing game installations, prioritizing vdf.
        
        Returns:
            Optional[Path]: Path object to the Steam library's steamapps/common dir, or None if not found
        """
        logger.info("Detecting Steam library location...")
        
        # Try finding libraryfolders.vdf in common Steam paths
        possible_vdf_paths = [
            Path.home() / ".steam/steam/config/libraryfolders.vdf",
            Path.home() / ".local/share/Steam/config/libraryfolders.vdf",
            Path.home() / ".steam/root/config/libraryfolders.vdf"
        ]
        
        libraryfolders_vdf_path: Optional[Path] = None
        for path_obj in possible_vdf_paths:
            # Explicitly ensure path_obj is Path before checking is_file
            current_path = Path(path_obj)
            if current_path.is_file():
                libraryfolders_vdf_path = current_path # Assign the confirmed Path object
                logger.debug(f"Found libraryfolders.vdf at: {libraryfolders_vdf_path}")
                break
        
        # Check AFTER loop - libraryfolders_vdf_path is now definitely Path or None
        if not libraryfolders_vdf_path:
            logger.warning("libraryfolders.vdf not found...")
            # Proceed to default check below if vdf not found
        else:
            # Parse the VDF file to extract library paths
            try:
                # Try importing vdf here if not done globally
                with open(libraryfolders_vdf_path, 'r') as f:
                    data = vdf.load(f)
                
                # Look for library folders (indices are strings '0', '1', etc.)
                libraries = data.get('libraryfolders', {}) 
                
                for key in libraries:
                     if isinstance(libraries[key], dict) and 'path' in libraries[key]:
                        lib_path_str = libraries[key]['path']
                        if lib_path_str:
                             # Check if this library path is valid
                             potential_lib_path = Path(lib_path_str) / "steamapps/common"
                             if potential_lib_path.is_dir():
                                logger.info(f"Using Steam library path from vdf: {potential_lib_path}")
                                return potential_lib_path # Return first valid Path object found
                
                logger.warning("No valid library paths found within libraryfolders.vdf.")
                # Proceed to default check below if vdf parsing fails to find a valid path

            except ImportError:
                logger.error("Python 'vdf' library not found. Cannot parse libraryfolders.vdf.")
                # Proceed to default check below
            except Exception as e:
                logger.error(f"Error parsing libraryfolders.vdf: {e}")
                # Proceed to default check below

        # Fallback: Check default location if VDF parsing didn't yield a result
        default_path = Path.home() / ".steam/steam/steamapps/common"
        if default_path.is_dir():
            logger.warning(f"Using default Steam library path: {default_path}")
            return default_path 
        
        logger.error("No valid Steam library found via vdf or at default location.")
        return None

    @staticmethod
    def find_compat_data(appid: str) -> Optional[Path]:
        """Find the compatdata directory for a given AppID."""
        if not appid or not appid.isdigit():
            logger.error(f"Invalid AppID provided for compatdata search: {appid}")
            return None

        logger.debug(f"Searching for compatdata directory for AppID: {appid}")
        
        # Standard Steam locations
        possible_bases = [
            Path.home() / ".steam/steam/steamapps/compatdata",
            Path.home() / ".local/share/Steam/steamapps/compatdata",
        ]
        
        # Try to get library path from vdf to check there too
        # Use type hint for clarity
        steam_lib_common_path: Optional[Path] = FileSystemHandler.find_steam_library() 
        if steam_lib_common_path:
            # find_steam_library returns steamapps/common, go up two levels for library root
            library_root = steam_lib_common_path.parent.parent 
            vdf_compat_path = library_root / "steamapps/compatdata"
            if vdf_compat_path.is_dir() and vdf_compat_path not in possible_bases:
                possible_bases.insert(0, vdf_compat_path) # Prioritize library path from vdf

        for base_path in possible_bases:
            if not base_path.is_dir():
                logger.debug(f"Compatdata base path does not exist or is not a directory: {base_path}")
                continue
                
            potential_path = base_path / appid
            if potential_path.is_dir():
                logger.info(f"Found compatdata directory: {potential_path}")
                return potential_path # Return Path object
            else:
                logger.debug(f"Compatdata for {appid} not found in {base_path}")

        logger.warning(f"Compatdata directory for AppID {appid} not found in standard or detected library locations.")
        return None

    @staticmethod
    def find_steam_config_vdf() -> Optional[Path]:
        """Finds the active Steam config.vdf file."""
        logger.debug("Searching for Steam config.vdf...")
        possible_steam_paths = [
            Path.home() / ".steam/steam",
            Path.home() / ".local/share/Steam",
            Path.home() / ".steam/root"
        ]
        for steam_path in possible_steam_paths:
            potential_path = steam_path / "config/config.vdf"
            if potential_path.is_file():
                logger.info(f"Found config.vdf at: {potential_path}")
                return potential_path # Return Path object

        logger.warning("Could not locate Steam's config.vdf file in standard locations.")
        return None

    # ... (rest of the class) ... 