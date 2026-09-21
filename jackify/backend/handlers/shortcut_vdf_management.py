"""VDF backup/restore and modification methods for ShortcutHandler (Mixin)."""
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path

import glob
import vdf

from .vdf_handler import VDFHandler

logger = logging.getLogger(__name__)


class ShortcutVDFManagementMixin:
    """Mixin providing VDF file management methods."""

    def _check_and_restore_shortcuts_vdf(self):
        """
        Check if shortcuts.vdf exists and restore from backup if missing.
        Returns:
            bool: True if file exists or was restored, False if unable to restore
        """
        shortcuts_files = []
        for user_dir in os.listdir(self.shortcuts_path):
            shortcuts_file = os.path.join(self.shortcuts_path, user_dir, "config", "shortcuts.vdf")
            if os.path.dirname(shortcuts_file):
                shortcuts_files.append(shortcuts_file)

        missing_files = []
        for file_path in shortcuts_files:
            if not os.path.exists(file_path):
                self.logger.warning(f"shortcuts.vdf is missing at: {file_path}")
                missing_files.append(file_path)

        if not missing_files:
            self.logger.debug("All shortcuts.vdf files are present")
            return True

        restored = 0
        for file_path in missing_files:
            backup_files = sorted(glob.glob(f"{file_path}.*.bak"), reverse=True)
            if backup_files:
                try:
                    shutil.copy2(backup_files[0], file_path)
                    self.logger.info(f"Restored {file_path} from {backup_files[0]}")
                    restored += 1
                    continue
                except Exception as e:
                    self.logger.error(f"Failed to restore from timestamped backup: {e}")

            simple_backup = f"{file_path}.bak"
            if os.path.exists(simple_backup):
                try:
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
            backup_path = f"{shortcuts_file}.{int(time.time())}.bak"
            shutil.copy2(shortcuts_file, backup_path)
            self.logger.info(f"Created backup before direct modification: {backup_path}")

            if not os.path.exists(shortcuts_file) or os.path.getsize(shortcuts_file) == 0:
                with open(shortcuts_file, 'wb') as f:
                    f.write(b'\x00shortcuts\x00\x08\x08')
                self.logger.info(f"Created new shortcuts.vdf file at {shortcuts_file}")

            try:
                import sys
                import importlib.util

                steam_vdf_spec = importlib.util.find_spec("steam_vdf")

                if steam_vdf_spec is None:
                    from jackify.backend.handlers.subprocess_utils import get_safe_python_executable
                    python_exe = get_safe_python_executable()
                    subprocess.check_call([python_exe, "-m", "pip", "install", "steam-vdf", "--user"])
                    time.sleep(1)

                import vdf as steam_vdf

                with open(shortcuts_file, 'rb') as f:
                    shortcuts_data = steam_vdf.load(f)

                max_id = -1
                if 'shortcuts' in shortcuts_data:
                    for id_str in shortcuts_data['shortcuts']:
                        try:
                            id_num = int(id_str)
                            if id_num > max_id:
                                max_id = id_num
                        except ValueError:
                            pass

                new_id = max_id + 1

                if 'shortcuts' not in shortcuts_data:
                    shortcuts_data['shortcuts'] = {}

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

                with open(shortcuts_file, 'wb') as f:
                    steam_vdf.dump(shortcuts_data, f)

                self.logger.info(f"Added shortcut for {modlist_name} using steam-vdf library")
                return True

            except Exception as e:
                self.logger.warning(f"Failed to use steam-vdf library: {e}")

                self.logger.info("Falling back to VDFHandler for shortcuts.vdf modification")
                shortcuts_data = VDFHandler.load(shortcuts_file, binary=True)

                if not shortcuts_data:
                    shortcuts_data = {'shortcuts': {}}

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

                if 'shortcuts' not in shortcuts_data:
                    shortcuts_data['shortcuts'] = {}
                shortcuts_data['shortcuts'][str(new_id)] = new_entry

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
            tags = []

        # A parse/access failure on an existing file must abort, not fall back to an
        # empty dict - that fallback is what let this method silently overwrite a
        # user's real shortcuts.vdf with a blank one plus the new entry.
        data = {'shortcuts': {}}

        if os.path.exists(shortcuts_file):
            try:
                with open(shortcuts_file, 'rb') as f:
                    file_data = f.read()
            except Exception as e:
                self.logger.error(f"Error accessing shortcuts.vdf, aborting to avoid data loss: {e}")
                return False, None

            if file_data:
                try:
                    data = vdf.binary_loads(file_data)
                except Exception as e:
                    self.logger.error(f"Could not parse existing shortcuts.vdf, aborting to avoid data loss: {e}")
                    return False, None
                if 'shortcuts' not in data:
                    data['shortcuts'] = {}
        else:
            self.logger.info(f"shortcuts.vdf not found at {shortcuts_file}. A new file will be created.")

        if 'shortcuts' not in data:
            data['shortcuts'] = {}

        next_index = 0
        if data.get('shortcuts'):
            shortcut_indices = [int(k) for k in data['shortcuts'].keys() if k.isdigit()]
            if shortcut_indices:
                next_index = max(shortcut_indices) + 1

        new_shortcut = {
            'AppName': app_name,
            'Exe': f'"{exe_path}"',
            'StartDir': f'"{start_dir}"',
            'icon': icon_path,
            'ShortcutPath': "",
            'LaunchOptions': launch_options,
            'IsHidden': 0,
            'AllowDesktopConfig': 1,
            'AllowOverlay': 1,
            'OpenVR': 0,
            'Devkit': 0,
            'DevkitGameID': '',
            'DevkitOverrideAppID': 0,
            'LastPlayTime': 0,
            'FlatpakAppID': '',
            'IsInstalled': 1,
        }

        if tags:
            new_shortcut['tags'] = {str(i): tag for i, tag in enumerate(tags)}

        app_id = (0x80000000 + int(next_index)) % (2**32)

        if app_id > 0x7FFFFFFF:
            app_id = app_id - 0x100000000

        new_shortcut['appid'] = app_id

        data['shortcuts'][str(next_index)] = new_shortcut
        self.logger.info(f"Adding shortcut '{app_name}' at index {next_index}")

        try:
            temp_file = f"{shortcuts_file}.temp"
            with open(temp_file, 'wb') as f:
                vdf_data = vdf.binary_dumps(data)
                f.write(vdf_data)

            shutil.move(temp_file, shortcuts_file)

            self.logger.info(f"Successfully updated shortcuts.vdf! AppID: {app_id}")
            return True, app_id
        except Exception as e:
            self.logger.error(f"Error: Failed to write updated shortcuts.vdf: {e}")
            return False, None

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

            safe_backup = getattr(self, '_safe_shortcuts_backup', None)
            if safe_backup and os.path.exists(safe_backup):
                try:
                    shutil.copy2(safe_backup, shortcuts_file)
                    self.logger.info(f"Restored shortcuts.vdf from pre-restart backup")
                    return
                except Exception as e:
                    self.logger.error(f"Failed to restore from pre-restart backup: {e}")

            backup = getattr(self, '_last_shortcuts_backup', None)
            if backup and os.path.exists(backup):
                try:
                    shutil.copy2(backup, shortcuts_file)
                    self.logger.info(f"Restored shortcuts.vdf from regular backup")
                except Exception as e:
                    self.logger.error(f"Failed to restore from backup: {e}")
                    self.logger.warning("shortcuts.vdf restore failed - shortcut may need to be recreated")
        else:
            self.logger.info(f"shortcuts.vdf verified intact after restart")
