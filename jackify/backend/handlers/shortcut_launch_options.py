"""Launch options and icon methods for ShortcutHandler (Mixin)."""
import logging
import os
import shutil
import time
import vdf

logger = logging.getLogger(__name__)


class ShortcutLaunchOptionsMixin:
    """Mixin providing launch options and icon methods."""

    def get_shortcut_launch_options(self, app_name: str, exe_path: str) -> 'Optional[str]':
        """Return current LaunchOptions for a shortcut, or None if the shortcut is not found."""
        shortcuts_file = self.path_handler._find_shortcuts_vdf()
        if not shortcuts_file or not os.path.exists(shortcuts_file):
            return None
        try:
            with open(shortcuts_file, 'rb') as f:
                data = vdf.binary_loads(f.read())
        except Exception as e:
            self.logger.debug(f"Could not read shortcuts.vdf: {e}")
            return None

        def _norm(p: str) -> str:
            try:
                return os.path.normpath(os.path.abspath(p.strip().strip('"'))).lower()
            except Exception:
                return p.strip().strip('"').lower()

        exe_norm = _norm(exe_path)
        for shortcut_data in data.get('shortcuts', {}).values():
            if (shortcut_data.get('AppName', '').strip() == app_name and
                    _norm(shortcut_data.get('Exe', '')) == exe_norm):
                return shortcut_data.get('LaunchOptions', '')
        return None

    def ensure_mounts_in_steam_compat(self, app_name: str, exe_path: str, *paths: str) -> str:
        """Add mountpoints of any supplied paths to STEAM_COMPAT_MOUNTS if not already present.

        Reads existing launch options and appends only what is missing - never overwrites
        unrelated options. Adds the top-level directory of each path so Proton's container
        can bind-mount the subtree into the prefix.

        When Steam is running, the write is deferred: returns "steam_running" so the caller
        can stop Steam first, call apply_pending_mounts_update(), then restart Steam.

        Returns:
            "unchanged"     - mounts already correct, no action needed
            "updated"       - Steam was not running; write succeeded
            "steam_running" - changes needed but deferred; call apply_pending_mounts_update()
                              after stopping Steam
            "failed"        - shortcut not found or write error
        """
        import re
        from pathlib import Path as _Path

        def _is_covered(path: str, mounts: list) -> bool:
            """Return True if path is already reachable via an existing mount entry.

            A path is covered if an existing mount entry is equal to it or is a
            parent of it. Root '/' is excluded as a catch-all.
            """
            p = _Path(path)
            for mount in mounts:
                if mount == '/':
                    continue
                try:
                    p.relative_to(mount)
                    return True
                except ValueError:
                    pass
            return False

        current = self.get_shortcut_launch_options(app_name, exe_path)
        if current is None:
            self.logger.warning(f"Shortcut '{app_name}' not found in shortcuts.vdf; cannot update STEAM_COMPAT_MOUNTS")
            return "failed"

        compat_re = re.compile(r'STEAM_COMPAT_MOUNTS="([^"]*)"')
        m = compat_re.search(current)
        existing = [p for p in m.group(1).split(':') if p] if m else []

        mounts_to_add = []
        for p in paths:
            if not p:
                continue
            if not _is_covered(p, existing) and p not in mounts_to_add:
                mounts_to_add.append(p)

        if not mounts_to_add:
            self.logger.debug(f"STEAM_COMPAT_MOUNTS for '{app_name}' already covers required paths")
            return "unchanged"

        if m:
            updated_val = ':'.join(existing + mounts_to_add)
            updated = compat_re.sub(f'STEAM_COMPAT_MOUNTS="{updated_val}"', current)
        else:
            val = ':'.join(mounts_to_add)
            prefix = f'STEAM_COMPAT_MOUNTS="{val}"'
            updated = f'{prefix} {current}' if current.strip() else f'{prefix} %command%'

        self.logger.info(f"STEAM_COMPAT_MOUNTS update needed for '{app_name}': adding {mounts_to_add}")

        try:
            from jackify.backend.services.steam_restart_service import get_steam_processes
            steam_running = bool(get_steam_processes())
        except Exception:
            steam_running = False

        if steam_running:
            # Defer the write - Steam holds shortcuts.vdf in memory and would clobber it.
            # Store the pending options so the GUI can stop Steam, apply, then restart.
            self._pending_mounts_app_name = app_name
            self._pending_mounts_exe_path = exe_path
            self._pending_mounts_options = updated
            return "steam_running"

        success = self.update_shortcut_launch_options(app_name, exe_path, updated)
        return "updated" if success else "failed"

    def apply_pending_mounts_update(self) -> bool:
        """Write a deferred STEAM_COMPAT_MOUNTS update. Call only after Steam has stopped."""
        app_name = getattr(self, '_pending_mounts_app_name', None)
        exe_path = getattr(self, '_pending_mounts_exe_path', None)
        options = getattr(self, '_pending_mounts_options', None)
        if not (app_name and exe_path and options):
            self.logger.warning("apply_pending_mounts_update called with no pending update")
            return False
        self._pending_mounts_app_name = None
        self._pending_mounts_exe_path = None
        self._pending_mounts_options = None
        return self.update_shortcut_launch_options(app_name, exe_path, options)

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

        shortcuts_file = self.path_handler._find_shortcuts_vdf()
        if not shortcuts_file:
            self.logger.error("Could not find shortcuts.vdf to update.")
            return False

        data = {'shortcuts': {}}
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

        def _normalize_path(p: str) -> str:
            try:
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
            for index, shortcut_data in data.get('shortcuts', {}).items():
                shortcut_name = shortcut_data.get('AppName', '')
                shortcut_exe = shortcut_data.get('Exe', '')
                self.logger.error(f"Found shortcut: AppName='{shortcut_name}', Exe='{shortcut_exe}' -> norm='{_normalize_path(shortcut_exe)}'")
            return False

        if target_index in data['shortcuts']:
            self.logger.info(f"Found shortcut at index {target_index}. Updating LaunchOptions...")
            data['shortcuts'][target_index]['LaunchOptions'] = new_launch_options
        else:
            self.logger.error(f"Target index {target_index} not found in shortcuts dictionary after identification.")
            return False

        try:
            temp_file = f"{shortcuts_file}.temp"
            with open(temp_file, 'wb') as f:
                vdf_data = vdf.binary_dumps(data)
                f.write(vdf_data)

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
        abs_path = os.path.abspath(mo2_exe_path)
        z_path = f"Z:{abs_path}"
        win_path = z_path.replace('/', '\\')
        win_path = win_path.replace('\\', '\\\\')
        content = (
            "[handlers]\n"
            "size=1\n"
            "1\\games=\"skyrimse,skyrim,fallout4,falloutnv,fallout3,oblivion,enderal,starfield\"\n"
            f"1\\executable={win_path}\n"
            "1\\arguments=\n"
        )
        with open(ini_path, "w") as f:
            f.write(content)
        self.logger.info(f"[SUCCESS] nxmhandler.ini written to {ini_path}")
