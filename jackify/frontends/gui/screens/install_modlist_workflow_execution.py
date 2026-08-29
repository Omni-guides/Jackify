"""Execution workflow methods for InstallModlistScreen (Mixin)."""

from pathlib import Path
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QProgressBar, QMessageBox
import logging
import os

from .install_modlist_installer_thread import InstallerThread

logger = logging.getLogger(__name__)


class InstallWorkflowExecutionMixin:
    """Mixin containing install-run and manual-download dialog execution methods."""

    def _session_engine_id(self) -> str:
        """Return the engine to use for this install based on the install screen checkbox."""
        return "clf3" if self.engine_checkbox.isChecked() else "jackify-engine"

    def _ensure_clf3_installed(self) -> bool:
        """
        If CLF3 is already installed, return True immediately.
        If not, show a download dialog and install it, returning True on success.
        """
        from jackify.backend.services.tool_registry import ToolRegistry
        status = ToolRegistry().get_status("clf3")
        if status and status.installed:
            return True

        reply = QMessageBox.question(
            self,
            "CLF3 Not Installed",
            "The experimental engine (CLF3) is not installed.\n\n"
            "Download and install it now to continue?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return False

        return self._download_clf3_with_dialog()

    def _download_clf3_with_dialog(self) -> bool:
        """Download CLF3 in a modal dialog with a pulsing progress bar. Returns True on success."""

        class _Clf3InstallThread(QThread):
            finished_signal = Signal(bool, str)

            def run(self):
                try:
                    ok, msg = ToolRegistry().install("clf3")
                    self.finished_signal.emit(ok, msg)
                except Exception as exc:
                    self.finished_signal.emit(False, str(exc))

        from jackify.backend.services.tool_registry import ToolRegistry
        from jackify.frontends.gui.shared_theme import JACKIFY_COLOR_BLUE

        dlg = QDialog(self)
        dlg.setWindowTitle("Installing CLF3")
        dlg.setModal(True)
        dlg.setMinimumWidth(360)
        layout = QVBoxLayout(dlg)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        label = QLabel("Downloading CLF3 (experimental engine)...")
        label.setStyleSheet("color: #ccc; font-size: 13px;")
        layout.addWidget(label)

        bar = QProgressBar()
        bar.setRange(0, 0)
        bar.setTextVisible(False)
        bar.setFixedHeight(6)
        bar.setStyleSheet(f"""
            QProgressBar {{ border: none; background-color: #333; border-radius: 3px; }}
            QProgressBar::chunk {{ background-color: {JACKIFY_COLOR_BLUE}; border-radius: 3px; }}
        """)
        layout.addWidget(bar)

        result = [False, ""]

        thread = _Clf3InstallThread()

        def on_done(ok: bool, msg: str):
            result[0] = ok
            result[1] = msg
            dlg.accept()

        thread.finished_signal.connect(on_done)
        thread.start()
        dlg.exec()
        thread.wait(5000)

        if not result[0]:
            QMessageBox.critical(
                self,
                "CLF3 Install Failed",
                f"Could not install CLF3:\n\n{result[1]}",
            )
            return False

        label.setText("CLF3 installed.")
        return True

    def validate_and_start_install(self):
        import time
        self._install_workflow_start_time = time.time()

        # Disable controls before processEvents to prevent double-click re-entry
        self._disable_controls_during_operation()

        # Immediately show "Initialising" status to provide feedback
        self.progress_indicator.set_status("Initialising...", 0)
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()

        # Reload config to pick up any settings changes made in Settings dialog
        self.config_handler.reload_config()

        # Check protontricks before proceeding
        if not self._check_protontricks():
            self.progress_indicator.reset()
            self._enable_controls_after_operation()
            return

        try:
            ctx = {}
            if not self._resolve_install_source(ctx):
                return
            if not self._authenticate_for_install(ctx):
                return
            if not self._validate_fields_and_dirs(ctx):
                return
            self._persist_resolution_and_dirs(ctx)
            if not self._detect_game(ctx):
                return
            self._reset_install_ui_state(ctx)
            if not self._check_update_mode(ctx):
                return

            modlist = ctx['modlist']
            install_dir = ctx['install_dir']
            downloads_dir = ctx['downloads_dir']
            install_mode = ctx['install_mode']
            api_key = ctx['api_key']
            oauth_info = ctx['oauth_info']
            readme_url = ctx.get('readme_url')

            if readme_url:
                import subprocess
                if "raw.githubusercontent.com" in readme_url:
                    readme_url = readme_url.replace("raw.githubusercontent.com", "github.com")
                    readme_url = readme_url.replace("/main/", "/blob/main/")
                    readme_url = readme_url.replace("/master/", "/blob/master/")
                logger.info("Opening modlist readme: %s", readme_url)
                _strip = {"LD_LIBRARY_PATH", "LD_PRELOAD", "QT_PLUGIN_PATH", "QML2_IMPORT_PATH", "PYTHONPATH", "PYTHONHOME"}
                clean_env = {k: v for k, v in os.environ.items() if k not in _strip}
                subprocess.Popen(["xdg-open", readme_url], env=clean_env, start_new_session=True)
                self._safe_append_text(
                    "Modlist readme opened in your browser. "
                    "Check it for any manual post-install steps before launching the game."
                )
            self._readme_url = readme_url or None

            logger.debug(f"Calling run_modlist_installer with modlist={modlist}, install_dir={install_dir}, downloads_dir={downloads_dir}, install_mode={install_mode}")
            self.run_modlist_installer(modlist, install_dir, downloads_dir, api_key, install_mode, oauth_info)
        except Exception as e:
            logger.error("Unexpected error in validate_and_start_install", exc_info=True)
            self._enable_controls_after_operation()
            self.cancel_btn.setVisible(True)
            self.cancel_install_btn.setVisible(False)
            from jackify.shared.paths import get_jackify_logs_dir
            from ..services.message_service import MessageService
            MessageService.critical(
                self,
                "Installation Error",
                f"Could not start the installation.\n\n{e}\n\n"
                f"Details were written to the Jackify log at:\n{get_jackify_logs_dir()}",
            )

    def run_modlist_installer(self, modlist, install_dir, downloads_dir, api_key, install_mode='online', oauth_info=None):
        
        # Rotate log file at start of each workflow run (keep 5 backups)
        from jackify.backend.handlers.logging_handler import LoggingHandler
        log_handler = LoggingHandler()
        log_handler.rotate_log_file_per_run(Path(self.modlist_log_path), backup_count=5)

        # Clear console for fresh installation output
        self.console.clear()
        from jackify import __version__ as jackify_version
        self._safe_append_text(f"Jackify v{jackify_version}")
        self._safe_append_text("Starting modlist installation with custom progress handling...")
        
        # Update UI state for installation
        self.start_btn.setEnabled(False)
        self.cancel_btn.setVisible(False)
        self.cancel_install_btn.setVisible(True)
        
        self._downloads_dir = downloads_dir
        self.install_thread = InstallerThread(
            modlist, install_dir, downloads_dir, api_key, self.modlist_name_edit.text().strip(), install_mode,
            progress_state_manager=self.progress_state_manager,
            auth_service=self.auth_service,
            oauth_info=oauth_info,
            game_type=getattr(self, '_current_game_type', None),
            clf3_cdn_url=getattr(self, '_clf3_cdn_url', None),
            engine_id=self._session_engine_id(),
        )
        self._clf3_cdn_url = None
        self._active_session_engine_id = self._session_engine_id()
        self.install_thread.output_received.connect(self.on_installation_output)
        self.install_thread.progress_received.connect(self.on_installation_progress)
        self.install_thread.progress_updated.connect(self.on_progress_updated)
        self.install_thread.installation_finished.connect(self.on_installation_finished)
        self.install_thread.premium_required_detected.connect(self.on_premium_required_detected)
        self.install_thread.non_premium_detected.connect(self.on_non_premium_detected)
        self.install_thread.manual_download_list_received.connect(self.on_manual_download_list_received)
        self.install_thread.progress_state_manager = self.progress_state_manager
        self.install_thread.finished.connect(self.install_thread.deleteLater)
        self.install_thread.start()

    def on_manual_download_list_received(self, events: list) -> None:
        """Show the manual download dialog when the engine emits a batch of missing files."""
        try:
            # Show non-premium info dialog synchronously before the file list.
            # The engine is paused waiting for a continue signal at this point,
            # so process_finished will not fire during exec() and close it prematurely.
            if getattr(self, '_non_premium_gate_enabled', False) and not getattr(self, '_non_premium_info_acknowledged', False):
                self._show_non_premium_info_dialog()
            logger.info(f"[MDL-1005] Showing manual download dialog for batch | items={len(events)}")
            self._show_manual_download_dialog(events)
        except Exception as exc:
            logger.error(f"Manual download dialog setup failed: {exc}", exc_info=True)
            self._safe_append_text(f"\n[ERROR] Manual download dialog failed to open: {exc}\n")

    def _flush_pending_manual_download_events(self) -> None:
        events = getattr(self, '_pending_manual_download_events', None)
        if not events:
            return
        self._pending_manual_download_events = None
        logger.info(f"[MDL-1007] Releasing queued manual download batch after acknowledgement | items={len(events)}")
        self._show_manual_download_dialog(events)

    def _show_manual_download_dialog(self, events: list) -> None:
        from pathlib import Path as _Path
        from jackify.backend.handlers.config_handler import ConfigHandler
        from jackify.backend.services.manual_download_manager import ManualDownloadManager
        from jackify.frontends.gui.dialogs.manual_download_dialog import ManualDownloadDialog

        cfg_watch = ConfigHandler().get("manual_download_watch_directory", None)
        watch_dir = None
        if cfg_watch:
            cfg_path = _Path(str(cfg_watch)).expanduser()
            if cfg_path.is_dir():
                watch_dir = cfg_path
        if watch_dir is None:
            xdg_dl = Path(os.environ.get('XDG_DOWNLOAD_DIR', '')) if os.environ.get('XDG_DOWNLOAD_DIR') else None
            watch_dir = xdg_dl if (xdg_dl and xdg_dl.is_dir()) else _Path.home() / 'Downloads'
        dl_dir = _Path(self._downloads_dir) if hasattr(self, '_downloads_dir') else watch_dir

        loop_iteration = events[0].get('loop_iteration', 1) if events else 1
        count = len(events)
        raw_limit = ConfigHandler().get('manual_download_concurrent_limit', 2)
        try:
            concurrent_limit = int(raw_limit)
        except (TypeError, ValueError):
            concurrent_limit = 2
        concurrent_limit = max(1, min(5, concurrent_limit))

        self._safe_append_text(
            f"\n[Manual Download Required] {count} file(s) need manual download "
            f"(rate limit, access error, or non-premium).\n"
            f"Opening download dialog - it will appear in front momentarily.\n"
        )
        logger.info(
            f"[MDL-1006] Manual download protocol initialized | count={count} "
            f"loop_iteration={loop_iteration} watch_dir={watch_dir} downloads_dir={dl_dir}"
        )

        # New install run: start with a fresh manager/dialog to avoid stale statuses from prior runs.
        if loop_iteration == 1:
            if getattr(self, '_manual_dl_manager', None) is not None:
                try:
                    self._manual_dl_manager.stop()
                except Exception:
                    pass
                self._manual_dl_manager = None
            if getattr(self, '_manual_dl_dialog', None) is not None:
                try:
                    self._manual_dl_dialog.close()
                except Exception:
                    pass
                self._manual_dl_dialog = None

        if not hasattr(self, '_manual_dl_manager') or self._manual_dl_manager is None:
            self._manual_dl_manager = ManualDownloadManager(
                modlist_download_dir=dl_dir,
                watch_directory=watch_dir,
                concurrent_limit=concurrent_limit,
                on_send_continue=self.install_thread.send_continue,
            )
            self._manual_dl_dialog = ManualDownloadDialog(
                manager=self._manual_dl_manager,
                modlist_name=self.modlist_name_edit.text().strip() if hasattr(self, 'modlist_name_edit') else '',
                watch_directory=watch_dir,
                concurrent_limit=concurrent_limit,
                parent=self,
            )

        self._manual_dl_manager.load_items(events, loop_iteration)
        self._manual_dl_dialog.load_items(self._manual_dl_manager.items)

        if not self._manual_dl_dialog.isVisible():
            self._manual_dl_dialog.show()
            self._manual_dl_dialog.raise_()
            self._manual_dl_dialog.activateWindow()
