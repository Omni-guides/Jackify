"""Shortcut discovery and AppID methods for ShortcutHandler (Mixin)."""
import logging
import os
import re
from pathlib import Path
from typing import List, Dict, Optional

from .vdf_handler import VDFHandler

logger = logging.getLogger(__name__)


class ShortcutDiscoveryMixin:
    """Mixin providing shortcut discovery and AppID resolution methods."""

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
        Find the current AppID for a given shortcut name and (optionally) executable path.

        Primary method: Read directly from shortcuts.vdf (reliable, no external dependencies)
        Fallback method: Use protontricks (if available)

        Args:
            shortcut_name (str): The name of the Steam shortcut.
            exe_path (Optional[str]): The path to the executable (for robust matching after Steam restart).

        Returns:
            Optional[str]: The found AppID string, or None if not found or error occurs.
        """
        self.logger.info(f"Attempting to find current AppID for shortcut: '{shortcut_name}' (exe_path: '{exe_path}')")

        try:
            appid = self.get_appid_from_vdf(shortcut_name, exe_path)
            if appid:
                self.logger.info(f"Successfully found AppID {appid} from shortcuts.vdf")
                return appid

            self.logger.info("AppID not found in shortcuts.vdf, trying protontricks as fallback...")
            from .protontricks_handler import ProtontricksHandler
            pt_handler = ProtontricksHandler(self.steamdeck)
            if not pt_handler.detect_protontricks():
                self.logger.warning("Protontricks not detected - cannot use as fallback")
                return None
            result = pt_handler.run_protontricks("-l")
            if not result or result.returncode != 0:
                self.logger.warning(f"Protontricks fallback failed: {result.stderr if result else 'No result'}")
                return None
            found_shortcuts = []
            for line in result.stdout.splitlines():
                m = re.search(r"Non-Steam shortcut:\s*(.*?)\s*\((\d+)\)$", line)
                if m:
                    pt_name = m.group(1).strip()
                    pt_appid = m.group(2)
                    found_shortcuts.append((pt_name, pt_appid))
            vdf_shortcuts = []
            shortcuts_vdf_path = self.shortcuts_path
            if shortcuts_vdf_path and os.path.isfile(shortcuts_vdf_path):
                try:
                    shortcuts_data = VDFHandler.load(shortcuts_vdf_path, binary=True)
                    if shortcuts_data and 'shortcuts' in shortcuts_data:
                        for idx, shortcut in shortcuts_data['shortcuts'].items():
                            app_name = shortcut.get('AppName', shortcut.get('appname', '')).strip()
                            exe = shortcut.get('Exe', shortcut.get('exe', '')).strip('"').strip()
                            vdf_shortcuts.append((app_name, exe, idx))
                except Exception as e:
                    self.logger.error(f"Error parsing shortcuts.vdf for exe path matching: {e}")
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

    def get_appid_from_vdf(self, shortcut_name: str, exe_path: Optional[str] = None) -> Optional[str]:
        """
        Get AppID directly from shortcuts.vdf by reading the file and matching shortcut name/exe.
        This is more reliable than using protontricks since it doesn't depend on external tools.

        Args:
            shortcut_name (str): The name of the Steam shortcut.
            exe_path (Optional[str]): The path to the executable for additional validation.

        Returns:
            Optional[str]: The AppID as a string, or None if not found.
        """
        self.logger.info(f"Looking up AppID from shortcuts.vdf for shortcut: '{shortcut_name}' (exe: '{exe_path}')")

        if not self.shortcuts_path or not os.path.isfile(self.shortcuts_path):
            self.logger.warning(f"Shortcuts.vdf not found at {self.shortcuts_path}")
            return None

        try:
            shortcuts_data = VDFHandler.load(self.shortcuts_path, binary=True)
            if not shortcuts_data or 'shortcuts' not in shortcuts_data:
                self.logger.warning("No shortcuts found in shortcuts.vdf")
                return None

            shortcut_name_clean = shortcut_name.strip().lower()

            for idx, shortcut in shortcuts_data['shortcuts'].items():
                name = shortcut.get('AppName', shortcut.get('appname', '')).strip()

                if name.lower() == shortcut_name_clean:
                    appid = shortcut.get('appid')

                    if appid:
                        if exe_path:
                            vdf_exe = shortcut.get('Exe', shortcut.get('exe', '')).strip('"').strip()
                            exe_path_norm = os.path.abspath(os.path.expanduser(exe_path)).lower()
                            vdf_exe_norm = os.path.abspath(os.path.expanduser(vdf_exe)).lower()

                            if vdf_exe_norm == exe_path_norm:
                                self.logger.info(f"Found AppID {appid} for shortcut '{name}' with matching exe '{vdf_exe}'")
                                return str(int(appid) & 0xFFFFFFFF)
                            else:
                                self.logger.debug(f"Found shortcut '{name}' but exe doesn't match: '{vdf_exe}' vs '{exe_path}'")
                                continue
                        else:
                            self.logger.info(f"Found AppID {appid} for shortcut '{name}' (no exe validation)")
                            return str(int(appid) & 0xFFFFFFFF)

            self.logger.debug(f"No matching shortcut found in shortcuts.vdf for '{shortcut_name}'")
            return None

        except Exception as e:
            self.logger.error(f"Error reading shortcuts.vdf: {e}")
            self.logger.exception("Traceback:")
            return None

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
            self.logger.info(f"No shortcuts.vdf file found at {self.shortcuts_path} - this is normal for new Steam installations")
            return []

        shortcuts_file = self.shortcuts_path
        try:
            shortcuts_data = VDFHandler.load(shortcuts_file, binary=True)
            if shortcuts_data is None or 'shortcuts' not in shortcuts_data:
                self.logger.warning(f"Could not load or parse data from {shortcuts_file}")
                return []

            for shortcut_id, shortcut in shortcuts_data['shortcuts'].items():
                if not isinstance(shortcut, dict):
                    self.logger.warning(f"Skipping invalid shortcut entry (not a dict) at index {shortcut_id} in {shortcuts_file}")
                    continue

                app_name = shortcut.get('AppName', shortcut.get('appname'))
                exe_path = shortcut.get('Exe', shortcut.get('exe', '')).strip('"')
                start_dir = shortcut.get('StartDir', shortcut.get('startdir', '')).strip('"')

                if app_name and start_dir and os.path.basename(exe_path) == executable_name:
                    is_valid = True
                    if executable_name == "ModOrganizer.exe":
                        if not (Path(start_dir) / 'ModOrganizer.ini').exists():
                            self.logger.warning(f"Found MO2 shortcut '{app_name}' but ModOrganizer.ini missing in '{start_dir}'")
                            is_valid = False

                    if is_valid:
                        matched_shortcuts.append({'name': app_name, 'path': start_dir})
                        self.logger.debug(f"Found '{executable_name}' shortcut in VDF: {app_name} -> {start_dir}")

        except Exception as e:
            self.logger.error(f"Error processing {shortcuts_file}: {e}")
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

        vdf_shortcuts = self._scan_shortcuts_for_executable(executable_name)
        if not vdf_shortcuts:
            self.logger.warning(f"No '{executable_name}' shortcuts found in VDF files.")

        pt_result = self.protontricks_handler.run_protontricks("-l")
        if not pt_result or pt_result.returncode != 0:
            self.logger.error(f"Protontricks failed to list applications: {pt_result.stderr if pt_result else 'No result'}")
            return []

        pt_shortcuts = {}
        for line in pt_result.stdout.splitlines():
            line = line.strip()
            if "Non-Steam shortcut:" in line:
                match = re.search(r"Non-Steam shortcut:\s*(.*?)\s*\((\d+)\)$", line)
                if match:
                    pt_name = match.group(1).strip()
                    pt_appid = match.group(2)
                    pt_shortcuts[pt_name] = pt_appid

        if not pt_shortcuts:
            self.logger.warning("No Non-Steam shortcuts listed by Protontricks.")
            return []

        final_list = []
        for vdf_shortcut in vdf_shortcuts:
            vdf_name = vdf_shortcut['name']
            if vdf_name in pt_shortcuts:
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

        if not self.shortcuts_path or not os.path.isfile(self.shortcuts_path):
            self.logger.info(f"No shortcuts.vdf file found at {self.shortcuts_path} - this is normal for new Steam installations")
            return []

        vdf_path = self.shortcuts_path
        try:
            self.logger.debug(f"Parsing shortcuts file: {vdf_path}")
            shortcuts_data = VDFHandler.load(vdf_path, binary=True)

            if not shortcuts_data or 'shortcuts' not in shortcuts_data:
                self.logger.warning(f"Shortcuts data is empty or invalid in {vdf_path}")
                return []

            shortcuts_dict = shortcuts_data.get('shortcuts', {})

            for index, shortcut_details in shortcuts_dict.items():
                if not isinstance(shortcut_details, dict):
                    self.logger.warning(f"Skipping invalid shortcut entry at index {index} in {vdf_path}")
                    continue

                exe_path = shortcut_details.get('Exe', shortcut_details.get('exe', '')).strip('"')
                app_name = shortcut_details.get('AppName', shortcut_details.get('appname', 'Unknown Shortcut'))

                if executable_name in os.path.basename(exe_path):
                    self.logger.info(f"Found matching shortcut '{app_name}' in {vdf_path}")
                    app_id = shortcut_details.get('appid', shortcut_details.get('AppID', shortcut_details.get('appId', None)))
                    start_dir = shortcut_details.get('StartDir', shortcut_details.get('startdir', '')).strip('"')

                    match = {
                        'AppName': app_name,
                        'Exe': exe_path,
                        'StartDir': start_dir,
                        'appid': app_id
                    }
                    matching_shortcuts.append(match)
                else:
                     self.logger.debug(f"Skipping shortcut '{app_name}': Exe path '{exe_path}' does not contain '{executable_name}'")

        except Exception as e:
            self.logger.error(f"Error processing shortcuts file {vdf_path}: {e}", exc_info=True)
            return []

        if not matching_shortcuts:
             self.logger.debug(f"No shortcuts found pointing to '{executable_name}' in {vdf_path}.")

        return matching_shortcuts
