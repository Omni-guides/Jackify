"""Execution workflow methods for InstallModlistScreen (Mixin)."""

from pathlib import Path
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QProgressBar, QMessageBox
import logging
import os

from .install_modlist_installer_thread import InstallerThread
from jackify.backend.services.steam_restart_service import ensure_flatpak_steam_filesystem_access
from jackify.backend.models.game_types import GAME_DISPLAY_NAMES, GAME_NAME_TO_TYPE
from jackify.shared.errors import install_dir_create_failed

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
            install_dir = self.install_dir_edit.text().strip()
            downloads_dir = self.downloads_dir_edit.text().strip()

            if self._session_engine_id() == "clf3" and not self._ensure_clf3_installed():
                self.progress_indicator.reset()
                self._enable_controls_after_operation()
                return

            tab_index = self.source_tabs.currentIndex()
            install_mode = 'online'
            if tab_index == 1:  # .wabbajack File tab
                modlist = self.file_edit.text().strip()
                if not modlist or not os.path.isfile(modlist) or not modlist.endswith('.wabbajack'):
                    self._abort_with_message(
                        "warning",
                        "Invalid Modlist",
                        "Please select a valid .wabbajack file."
                    )
                    return
                install_mode = 'file'
            else:
                # For online modlists, ALWAYS use machine_url from selected_modlist_info
                # Button text is now the display name (title), NOT the machine URL
                if not hasattr(self, 'selected_modlist_info') or not self.selected_modlist_info:
                    self._abort_with_message(
                        "warning",
                        "Invalid Modlist",
                        "Modlist information is missing. Please select the modlist again from the gallery."
                    )
                    return
                
                machine_url = self.selected_modlist_info.get('machine_url')
                if not machine_url:
                    self._abort_with_message(
                        "warning",
                        "Invalid Modlist",
                        "Modlist information is incomplete. Please select the modlist again from the gallery."
                    )
                    return
                
                # CRITICAL: Use machine_url, NOT button text
                modlist = machine_url

                if self._session_engine_id() == "clf3":
                    download_url = self.selected_modlist_info.get('download_url')
                    if not download_url:
                        self._abort_with_message(
                            "warning",
                            "Download URL Unavailable",
                            "Could not determine the download URL for this modlist.\n\n"
                            "Use the '.wabbajack File' tab to select a local file instead."
                        )
                        return
                    from jackify.shared.paths import get_jackify_downloads_dir
                    list_id = machine_url.split('/')[-1] if '/' in machine_url else machine_url
                    wabbajack_local = str(get_jackify_downloads_dir() / f"{list_id}.wabbajack")
                    modlist = wabbajack_local
                    self._clf3_cdn_url = download_url

            # Get authentication token (OAuth or API key) with automatic refresh
            api_key, oauth_info = self.auth_service.get_auth_for_engine()
            if not api_key:
                self._abort_with_message(
                    "warning",
                    "Authorisation Required",
                    "Please authorise with Nexus Mods before installing modlists.\n\n"
                    "Click the 'Authorise' button above to log in with OAuth,\n"
                    "or configure an API key in Settings.",
                    safety_level="medium"
                )
                return

            # Log authentication status at install start (Issue #111 diagnostics)
            auth_method = self.auth_service.get_auth_method()
            logger.info("=" * 60)
            logger.info("Authentication Status at Install Start")
            logger.info(f"Method: {auth_method or 'UNKNOWN'}")
            logger.info(f"Token length: {len(api_key)} chars")

            if auth_method == 'oauth':
                token_handler = self.auth_service.token_handler
                token_info = token_handler.get_token_info()
                if 'expires_in_minutes' in token_info:
                    logger.info(f"OAuth expires in: {token_info['expires_in_minutes']:.1f} minutes")
                if token_info.get('refresh_token_likely_expired'):
                    logger.warning(f"OAuth refresh token age: {token_info['refresh_token_age_days']:.1f} days (may need re-auth)")
            logger.info("=" * 60)

            modlist_name = self.modlist_name_edit.text().strip()
            missing_fields = []
            if not modlist_name:
                missing_fields.append("Modlist Name")
            if not install_dir:
                missing_fields.append("Install Directory")
            if not downloads_dir:
                missing_fields.append("Downloads Directory")
            if missing_fields:
                self._abort_with_message(
                    "warning",
                    "Missing Required Fields",
                    "Please fill in all required fields before starting the install:\n- " + "\n- ".join(missing_fields)
                )
                return
            from jackify.backend.handlers.validation_handler import ValidationHandler
            validation_handler = ValidationHandler()
            is_safe, reason = validation_handler.is_safe_install_directory(Path(install_dir))
            if not is_safe:
                from jackify.frontends.gui.dialogs.warning_dialog import WarningDialog
                dlg = WarningDialog(reason, parent=self)
                result = dlg.exec()
                if not result or not dlg.confirmed:
                    self._abort_install_validation()
                    return
            if not os.path.isdir(install_dir):
                from ..services.message_service import MessageService
                create = MessageService.question(self, "Create Directory?",
                    f"The install directory does not exist:\n{install_dir}\n\nWould you like to create it?",
                    critical=False  # Non-critical, won't steal focus
                )
                if create == QMessageBox.Yes:
                    try:
                        os.makedirs(install_dir, exist_ok=True)
                    except Exception as e:
                        MessageService.show_error(self, install_dir_create_failed(install_dir, str(e)))
                        self._abort_install_validation()
                        return
                else:
                    self._abort_install_validation()
                    return
            if not os.path.isdir(downloads_dir):
                from ..services.message_service import MessageService
                create = MessageService.question(self, "Create Directory?",
                    f"The downloads directory does not exist:\n{downloads_dir}\n\nWould you like to create it?",
                    critical=False  # Non-critical, won't steal focus
                )
                if create == QMessageBox.Yes:
                    try:
                        os.makedirs(downloads_dir, exist_ok=True)
                    except Exception as e:
                        MessageService.show_error(self, install_dir_create_failed(downloads_dir, str(e)))
                        self._abort_install_validation()
                        return
                else:
                    self._abort_install_validation()
                    return

            # Handle resolution saving
            resolution = self.resolution_combo.currentText()
            if resolution and resolution != "Leave unchanged":
                raw_resolution = resolution.split(" (")[0] if " (" in resolution else resolution
                self._current_resolution = raw_resolution
                success = self.resolution_service.save_resolution(resolution)
                if success:
                    logger.debug(f"Resolution saved successfully: {resolution}")
                else:
                    logger.debug("Failed to save resolution")
            else:
                # Clear saved resolution if "Leave unchanged" is selected
                if self.resolution_service.has_saved_resolution():
                    self.resolution_service.clear_saved_resolution()
                    logger.debug("Saved resolution cleared")
            
            ensure_flatpak_steam_filesystem_access(Path(install_dir))

            # Handle parent directory saving
            self._save_parent_directories(install_dir, downloads_dir)
            
            # Detect game type and check support
            game_type = None
            game_name = None
            
            readme_url = None
            if install_mode == 'file':
                # Parse .wabbajack file to get game type
                wabbajack_path = Path(modlist)
                readme_url = self.wabbajack_parser.parse_wabbajack_readme(wabbajack_path)
                result = self.wabbajack_parser.parse_wabbajack_game_type(wabbajack_path)
                if result:
                    if isinstance(result, tuple):
                        game_type, raw_game_type = result
                        if game_type == 'unknown' and raw_game_type:
                            game_name = raw_game_type
                        else:
                            game_name = GAME_DISPLAY_NAMES.get(game_type, game_type)
                    else:
                        game_type = result
                        game_name = GAME_DISPLAY_NAMES.get(game_type, game_type)
            else:
                # For online modlists, try to get game type from selected modlist
                if hasattr(self, 'selected_modlist_info') and self.selected_modlist_info:
                    readme_url = self.selected_modlist_info.get('readme_url')
                    game_name = self.selected_modlist_info.get('game', '')
                    logger.debug(f"Detected game_name from selected_modlist_info: '{game_name}'")
                    game_type = GAME_NAME_TO_TYPE.get(game_name.lower())
                    logger.debug(f"Mapped game_name '{game_name}' to game_type: '{game_type}'")
                    if not game_type:
                        game_type = 'unknown'
                        logger.debug(f"Game type not found in mapping, setting to 'unknown'")
                else:
                    logger.debug(f"No selected_modlist_info found")
                    game_type = 'unknown'
            
            # Store game type and name for later use
            self._current_game_type = game_type
            self._current_game_name = game_name
            
            # Check if game is supported
            logger.debug(f"Checking if game_type '{game_type}' is supported")
            logger.debug(f"game_type='{game_type}', game_name='{game_name}'")
            is_supported = self.wabbajack_parser.is_supported_game(game_type) if game_type else False
            logger.debug(f"is_supported_game('{game_type}') returned: {is_supported}")
            
            if game_type and not is_supported:
                logger.debug(f"Game '{game_type}' is not supported, showing dialog")
                from ..widgets.unsupported_game_dialog import UnsupportedGameDialog
                dialog = UnsupportedGameDialog(self, game_name)
                if not dialog.show_dialog(self, game_name):
                    self._abort_install_validation()
                    return
            elif game_type in ('skyrimvr', 'fallout4vr'):
                from ..widgets.unsupported_game_dialog import UnsupportedGameDialog
                if not UnsupportedGameDialog.show_dialog(self, game_name, vr_warning=True):
                    self._abort_install_validation()
                    return
            
            self.console.clear()
            self.process_monitor.clear()

            # Collapse Show Details if it was left open by the previous run.
            if self.show_details_checkbox.isChecked():
                self.show_details_checkbox.blockSignals(True)
                self.show_details_checkbox.setChecked(False)
                self.show_details_checkbox.blockSignals(False)
                from PySide6.QtCore import Qt as _Qt
                self._toggle_console_visibility(_Qt.Unchecked)

            # R&D: Reset progress indicator for new installation
            self.progress_indicator.reset()
            self.progress_state_manager.reset()
            self.file_progress_list.clear()
            self.file_progress_list.start_cpu_tracking()  # Start tracking CPU during installation
            self._is_update_install = False
            self._existing_shortcut_appid = None
            self._premium_notice_shown = False
            self._stalled_download_start_time = None
            self._stalled_download_notified = False
            self._stalled_data_snapshot = 0
            self._token_error_notified = False  # Reset token error notification
            self._premium_failure_active = False
            self._installation_cancelled = False
            self._non_premium_gate_enabled = False
            self._non_premium_info_acknowledged = False
            self._pending_manual_download_events = None
            self._post_install_active = False
            self._post_install_current_step = 0
            # Activity tab is always visible (tabs handle visibility automatically)
            
            # Update button states for installation
            self.start_btn.setEnabled(False)
            self.cancel_btn.setVisible(False)
            self.cancel_install_btn.setVisible(True)

            # Detect update-vs-new workflow before starting engine install.
            from jackify.backend.utils.modlist_meta import JACKIFY_META_FILE
            install_real = os.path.realpath(install_dir)
            meta_exists = (Path(install_real) / JACKIFY_META_FILE).exists()
            existing_appid = self._find_existing_shortcut_appid(modlist_name, install_real)
            if meta_exists and existing_appid:
                eligible, update_meta = self._evaluate_update_candidate(
                    modlist_name,
                    install_real,
                    install_mode,
                    existing_appid,
                )
                if not eligible:
                    logger.info(
                        "Update mode not offered | reason=%s requested_name=%s installed_name=%s",
                        update_meta.get("reason"),
                        modlist_name,
                        update_meta.get("installed_name"),
                    )
                else:
                    logger.info(
                        "Update mode candidate | version_relation=%s requested_version=%s installed_version=%s",
                        update_meta.get("version_relation"),
                        update_meta.get("requested_version"),
                        update_meta.get("installed_version"),
                    )
                    decision = self._prompt_update_or_new_install(modlist_name, install_real, update_meta)
                    if decision == "cancel":
                        self._abort_install_validation()
                        return
                    if decision == "new":
                        from ..services.message_service import MessageService

                        MessageService.warning(
                            self,
                            "Shortcut Name Already Exists",
                            "A Steam shortcut with this name already points to this install directory.\n\n"
                            "For a new install, choose a different Modlist Name before starting.",
                            safety_level="medium",
                        )
                        self._abort_install_validation()
                        return
                    # update
                    self._is_update_install = True
                    self._existing_shortcut_appid = existing_appid
                    self._safe_append_text(
                        f"Update mode selected. Reusing existing Steam shortcut AppID {existing_appid}."
                    )
                    self._record_pre_update_ini_snapshot(install_real)
            
            # CRITICAL: Final safety check - ensure online modlists use machine_url
            # CLF3 is exempt: it uses a pre-resolved local .wabbajack path, not machine_url
            if install_mode == 'online' and self._session_engine_id() != "clf3":
                if hasattr(self, 'selected_modlist_info') and self.selected_modlist_info:
                    expected_machine_url = self.selected_modlist_info.get('machine_url')
                    if expected_machine_url:
                        modlist = expected_machine_url  # Force use machine_url
                    else:
                        self._abort_with_message(
                            "critical",
                            "Installation Error",
                            "Cannot determine modlist machine URL. Please select the modlist again."
                        )
                        return
                else:
                    self._abort_with_message(
                        "critical",
                        "Installation Error",
                        "Modlist information is missing. Please select the modlist again from the gallery."
                    )
                    return
            
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
        self.install_thread.progress_updated.connect(self.on_progress_updated)  # R&D: Connect progress update
        self.install_thread.installation_finished.connect(self.on_installation_finished)
        self.install_thread.premium_required_detected.connect(self.on_premium_required_detected)
        self.install_thread.non_premium_detected.connect(self.on_non_premium_detected)
        self.install_thread.manual_download_list_received.connect(self.on_manual_download_list_received)
        # R&D: Pass progress state manager to thread
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
