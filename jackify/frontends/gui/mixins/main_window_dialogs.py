"""
Main window dialogs and cleanup mixin.
Settings, About, open URL, cleanup_processes, closeEvent.
"""

import logging
import os
import subprocess
import warnings

logger = logging.getLogger(__name__)

from jackify.frontends.gui.dialogs.settings_dialog import SettingsDialog


class MainWindowDialogsMixin:
    """Mixin for settings/about dialogs, open URL, and cleanup."""
    def _stop_qthread(self, thread, thread_name: str, cooperative_timeout_ms: int = 5000):
        """Stop a QThread robustly to avoid teardown crashes on app exit."""
        if thread is None:
            return None
        try:
            if not thread.isRunning():
                return None
        except RuntimeError:
            return None

        # Disconnect all signals before stopping to prevent callbacks to a dying widget.
        # disconnect() with no receivers connected raises via Python's warnings module
        # (not as a catchable exception), so it must be suppressed rather than try/excepted.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            try:
                thread.finished.disconnect()
            except Exception:
                pass
            for _sig in ("update_available", "no_update", "check_failed", "cache_ready", "progress_update"):
                try:
                    getattr(thread, _sig).disconnect()
                except Exception:
                    pass

        try:
            thread.requestInterruption()
        except Exception:
            pass

        try:
            thread.quit()
        except Exception:
            pass

        try:
            if thread.wait(cooperative_timeout_ms):
                return None
        except Exception:
            pass

        try:
            if not thread.wait(10000):
                logger.warning("%s still running during shutdown", thread_name)
        except Exception:
            pass
        return None

    def open_settings_dialog(self):
        try:
            if self._settings_dialog is not None:
                try:
                    if self._settings_dialog.isVisible():
                        self._settings_dialog.raise_()
                        self._settings_dialog.activateWindow()
                        return
                    else:
                        self._settings_dialog = None
                except RuntimeError:
                    self._settings_dialog = None
            dlg = SettingsDialog(self)
            self._settings_dialog = dlg

            def on_dialog_finished():
                self._settings_dialog = None
            dlg.finished.connect(on_dialog_finished)
            dlg.exec()
        except Exception as e:
            logger.error(f"Exception in open_settings_dialog: {e}", exc_info=True)
            self._settings_dialog = None

    def open_about_dialog(self):
        try:
            from jackify.frontends.gui.dialogs.about_dialog import AboutDialog
            if self._about_dialog is not None:
                try:
                    if self._about_dialog.isVisible():
                        self._about_dialog.raise_()
                        self._about_dialog.activateWindow()
                        return
                    else:
                        self._about_dialog = None
                except RuntimeError:
                    self._about_dialog = None
            dlg = AboutDialog(self.system_info, self)
            self._about_dialog = dlg

            def on_dialog_finished():
                self._about_dialog = None
            dlg.finished.connect(on_dialog_finished)
            dlg.exec()
        except Exception as e:
            logger.error(f"Exception in open_about_dialog: {e}", exc_info=True)
            self._about_dialog = None

    def _open_url(self, url: str):
        env = os.environ.copy()
        appimage_vars = [
            'LD_LIBRARY_PATH', 'PYTHONPATH', 'PYTHONHOME',
            'QT_PLUGIN_PATH', 'QML2_IMPORT_PATH',
        ]
        if 'APPIMAGE' in env or 'APPDIR' in env:
            for var in appimage_vars:
                env.pop(var, None)
        subprocess.Popen(
            ['xdg-open', url],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )

    def _on_nxm_url_received(self, url: str) -> None:
        """Handle an incoming nxm:// URL from the IPC server or initial launch."""
        try:
            from jackify.backend.services.nxm_url import parse_nxm_url
            from jackify.backend.services import nxm_session
            from jackify.tools.verify_install import discover_installed_modlists
            from jackify.frontends.gui.dialogs.nxm_download_dialog import NxmDownloadDialog

            nxm = parse_nxm_url(url)
            modlists = discover_installed_modlists()
            if not modlists:
                from jackify.frontends.gui.dialogs.nxm_download_dialog import show_no_modlists_error
                show_no_modlists_error()
                return

            # Prefer the actively running MO2 instance; fall back to session memory.
            auto_start = nxm_session.detect_active_mo2_modlist(modlists)
            if auto_start is None:
                remembered = nxm_session.get_remembered_modlist()
                if remembered:
                    auto_start = next((m for m in modlists if m["name"] == remembered), None)

            dlg = NxmDownloadDialog(nxm, modlists, parent=self, auto_start_modlist=auto_start)
            dlg.show()
            dlg.raise_()
            dlg.activateWindow()
        except Exception as e:
            logger.warning("Failed to handle NXM URL %r: %s", url, e)

    def cleanup_processes(self):
        try:
            if hasattr(self, '_nxm_ipc_server') and self._nxm_ipc_server is not None:
                self._nxm_ipc_server.stop()
            if hasattr(self, '_update_thread') and self._update_thread is not None:
                self._update_thread = self._stop_qthread(self._update_thread, "_update_thread")
            if hasattr(self, '_gallery_cache_preload_thread') and self._gallery_cache_preload_thread is not None:
                self._gallery_cache_preload_thread = self._stop_qthread(
                    self._gallery_cache_preload_thread,
                    "_gallery_cache_preload_thread",
                )
            for service in self.gui_services.values():
                if hasattr(service, 'cleanup'):
                    service.cleanup()
            screens = [
                getattr(self, 'modlist_tasks_screen', None),
                getattr(self, 'additional_tasks_screen', None),
                getattr(self, 'install_modlist_screen', None),
                getattr(self, 'install_ttw_screen', None),
                getattr(self, 'configure_new_modlist_screen', None),
                getattr(self, 'wabbajack_installer_screen', None),
                getattr(self, 'configure_existing_modlist_screen', None),
                getattr(self, 'install_mo2_screen', None),
            ]
            for screen in screens:
                if screen is None:
                    continue
                if hasattr(screen, 'cleanup_processes'):
                    screen.cleanup_processes()
                elif hasattr(screen, 'cleanup'):
                    screen.cleanup()
            try:
                from jackify.backend.handlers.subprocess_utils import kill_all_registered_process_groups
                kill_all_registered_process_groups()
            except Exception:
                pass
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

    def closeEvent(self, event):
        self._save_geometry_on_quit()
        self.cleanup_processes()
        event.accept()
