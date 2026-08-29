"""Dialog management for ConfigureNewModlistScreen (Mixin)."""
import os
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QHBoxLayout, QFileDialog, QMessageBox, QApplication, QListWidget, QListWidgetItem
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QTextCursor
from pathlib import Path

import subprocess
from jackify.frontends.gui.dialogs.existing_setup_dialog import prompt_existing_setup_dialog
from jackify.frontends.gui.services.message_service import MessageService
from jackify.shared.errors import manual_steps_incomplete
import logging

logger = logging.getLogger(__name__)
class ModlistFetchThread(QThread):
    result = Signal(list, str)
    def __init__(self, cli_path, game_type, project_root, log_path, mode='list-modlists', modlist_name=None, install_dir=None, download_dir=None):
        super().__init__()
        self.cli_path = cli_path
        self.game_type = game_type
        self.project_root = project_root
        self.log_path = log_path
        self.mode = mode
        self.modlist_name = modlist_name
        self.install_dir = install_dir
        self.download_dir = download_dir
    def run(self):
        # Use safe Python executable to prevent AppImage recursive spawning
        from jackify.backend.handlers.subprocess_utils import get_safe_python_executable
        python_exe = get_safe_python_executable()
        
        if self.mode == 'list-modlists':
            cmd = [python_exe, self.cli_path, '--install-modlist', '--list-modlists', '--game-type', self.game_type]
        elif self.mode == 'install':
            cmd = [python_exe, self.cli_path, '--install-modlist', '--install', '--modlist-name', self.modlist_name, '--install-dir', self.install_dir, '--download-dir', self.download_dir, '--game-type', self.game_type]
        else:
            self.result.emit([], '[ModlistFetchThread] Unknown mode')
            return
        try:
            with open(self.log_path, 'a') as logf:
                logf.write(f"\n[Modlist Fetch CMD] {cmd}\n")
                # Use clean subprocess environment to prevent AppImage variable inheritance
                from jackify.backend.handlers.subprocess_utils import get_clean_subprocess_env
                env = get_clean_subprocess_env()
                proc = subprocess.Popen(cmd, cwd=self.project_root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
                stdout, stderr = proc.communicate()
                logf.write(f"[stdout]\n{stdout}\n[stderr]\n{stderr}\n")
                if proc.returncode == 0:
                    modlist_ids = [line.strip() for line in stdout.splitlines() if line.strip()]
                    self.result.emit(modlist_ids, '')
                else:
                    self.result.emit([], stderr)
        except Exception as e:
            self.result.emit([], str(e))

class SelectionDialog(QDialog):
    def __init__(self, title, items, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(350)
        self.setMinimumHeight(300)
        layout = QVBoxLayout(self)
        self.list_widget = QListWidget()
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        from PySide6.QtWidgets import QSizePolicy
        self.list_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        for item in items:
            QListWidgetItem(item, self.list_widget)
        layout.addWidget(self.list_widget)
        self.selected_item = None
        self.list_widget.itemClicked.connect(self.on_item_clicked)
    def on_item_clicked(self, item):
        self.selected_item = item.text()
        self.accept()

class ConfigureNewModlistDialogsMixin:
    """Mixin providing dialog management for ConfigureNewModlistScreen."""

    def _restore_controls_after_shortcut_dialog_abort(self):
        """Return Configure New to an editable state when shortcut resolution is aborted."""
        try:
            self._enable_controls_after_operation()
        except Exception:
            pass

    def hideEvent(self, event):
        if getattr(self, '_playbook_controller', None) is not None:
            try:
                self._playbook_controller.cleanup()
            except Exception:
                pass
        super().hideEvent(event)

    def cleanup_processes(self):
        if getattr(self, '_playbook_controller', None) is not None:
            try:
                self._playbook_controller.cleanup()
                self._playbook_controller = None
            except Exception:
                pass
        self._stop_focus_reclaim()
        if hasattr(self, 'file_progress_list'):
            self.file_progress_list.stop_cpu_tracking()

    def show_shortcut_conflict_dialog(self, conflicts):
        """Show dialog to reuse an existing shortcut or choose a new name."""
        conflict_names = [c['name'] for c in conflicts]
        existing_name = conflict_names[0]

        modlist_name = self.modlist_name_edit.text().strip()
        install_dir = os.path.dirname(self.install_dir_edit.text().strip()) if self.install_dir_edit.text().strip().endswith('ModOrganizer.exe') else self.install_dir_edit.text().strip()

        action, new_name = prompt_existing_setup_dialog(
            self,
            window_title="Existing Modlist Setup Detected",
            heading="Modlist Update or New Install",
            body=(
                "Jackify detected an existing Steam shortcut for this setup.\n\n"
                "If you are updating an existing modlist or reconfiguring it, choose "
                "'Use Existing Setup'. If you want a separate Steam entry, enter a different "
                "name and choose 'Create New Shortcut'."
            ),
            existing_name=existing_name,
            requested_name=modlist_name,
            install_dir=install_dir,
            field_label="New shortcut name",
            reuse_label="Use Existing Setup",
            new_label="Create New Shortcut",
            cancel_label="Cancel",
        )

        # Connect signals
        if action == "new":
            if new_name and new_name != modlist_name:
                self.retry_automated_workflow_with_new_name(new_name)
            elif new_name == modlist_name:
                MessageService.warning(self, "Same Name", "Please enter a different name to resolve the conflict.")
                self._restore_controls_after_shortcut_dialog_abort()
            else:
                MessageService.warning(self, "Invalid Name", "Please enter a valid shortcut name.")
                self._restore_controls_after_shortcut_dialog_abort()
        elif action == "reuse":
            existing_appid = conflicts[0].get('appid')
            if not existing_appid:
                MessageService.warning(
                    self,
                    "Existing Setup Not Found",
                    "Jackify could not determine the Steam AppID for the existing shortcut.",
                )
                self._restore_controls_after_shortcut_dialog_abort()
                return
            self._safe_append_text(f"Reusing existing Steam shortcut '{existing_name}'.")
            try:
                from jackify.backend.handlers.modlist_handler import ModlistHandler
                _game_type = self._detect_game_type_from_mo2_ini(install_dir)
                ModlistHandler().set_steam_grid_images(str(existing_appid), install_dir, game_type=_game_type)
            except Exception as _e:
                logger.warning("Failed to apply Steam artwork on shortcut reuse: %s", _e)

            # A shortcut can outlive its prefix (manual deletion, a stale AppID from before
            # reconciliation existed) - "reuse" must not assume the prefix is still there,
            # or configuration fails immediately trying to resolve a WINEPREFIX that isn't.
            from jackify.backend.services.native_steam_operations_service import NativeSteamOperationsService
            has_prefix = NativeSteamOperationsService().get_wine_prefix_path(
                str(existing_appid), log_missing=False
            )
            if has_prefix:
                self.continue_configuration_after_automated_prefix(
                    str(existing_appid),
                    existing_name,
                    install_dir,
                    None,
                )
            else:
                self._safe_append_text(
                    "Existing shortcut has no Proton prefix - recreating it before configuring."
                )
                mo2_exe_path = os.path.realpath(self.install_dir_edit.text().strip())
                self._repair_missing_prefix_then_configure(
                    existing_name, install_dir, mo2_exe_path, int(existing_appid)
                )
        else:
            self._safe_append_text("Shortcut creation cancelled by user")
            self._restore_controls_after_shortcut_dialog_abort()

    def _repair_missing_prefix_then_configure(self, shortcut_name, install_dir, mo2_exe_path, appid):
        """Recreate the Proton prefix for an existing shortcut whose prefix is gone.

        Mirrors the CLI's replace/reuse path (modlist_operations_configuration_cli.py):
        shut Steam down, then continue_workflow_after_conflict_resolution() restarts it
        and creates the prefix for the (already-existing) shortcut's AppID.
        """
        class _PrefixRepairThread(QThread):
            progress_update = Signal(str)
            repair_complete = Signal(object)
            error_occurred = Signal(object)

            def __init__(self, shortcut_name, install_dir, mo2_exe_path, appid):
                super().__init__()
                self.shortcut_name = shortcut_name
                self.install_dir = install_dir
                self.mo2_exe_path = mo2_exe_path
                self.appid = appid

            def run(self):
                try:
                    from jackify.backend.services.automated_prefix_service import AutomatedPrefixService
                    from jackify.backend.services.steam_restart_service import shutdown_steam

                    def progress_callback(message):
                        self.progress_update.emit(message)

                    progress_callback("Shutting down Steam...")
                    if not shutdown_steam():
                        logger.warning("Steam shutdown returned False, continuing anyway")

                    result = AutomatedPrefixService().continue_workflow_after_conflict_resolution(
                        self.shortcut_name, self.install_dir, self.mo2_exe_path, self.appid, progress_callback
                    )
                    self.repair_complete.emit(result)
                except Exception as e:
                    from jackify.shared.errors import JackifyError, prefix_creation_failed
                    if not isinstance(e, JackifyError):
                        e = prefix_creation_failed(str(e))
                    self.error_occurred.emit(e)

        def _on_complete(result):
            success = bool(result and result[0])
            if success:
                _, prefix_path, result_appid, last_timestamp = result
                self._safe_append_text("Proton prefix recreated successfully.")
                self.continue_configuration_after_automated_prefix(
                    str(result_appid), shortcut_name, install_dir, last_timestamp
                )
            else:
                self._safe_append_text("Failed to recreate the Proton prefix for the existing shortcut.")
                MessageService.warning(
                    self,
                    "Prefix Recreation Failed",
                    "Jackify could not recreate the Proton prefix for the existing Steam shortcut. "
                    "Check the log for details.",
                )
                self._restore_controls_after_shortcut_dialog_abort()
            self._prefix_repair_thread = None

        def _on_error(error):
            from jackify.shared.errors import JackifyError, classify_exception
            if not isinstance(error, JackifyError):
                error = classify_exception(str(error))
            logger.error("Prefix repair failed: %s", error.message)
            self._safe_append_text(f"[FAILED] {error.message}")
            MessageService.show_error(self, error)
            self._restore_controls_after_shortcut_dialog_abort()
            self._prefix_repair_thread = None

        self._prefix_repair_thread = _PrefixRepairThread(shortcut_name, install_dir, mo2_exe_path, appid)
        self._prefix_repair_thread.progress_update.connect(self._safe_append_text)
        self._prefix_repair_thread.repair_complete.connect(_on_complete)
        self._prefix_repair_thread.error_occurred.connect(_on_error)
        self._prefix_repair_thread.start()

    def retry_automated_workflow_with_new_name(self, new_name):
        """Retry the automated workflow with a new shortcut name"""
        # Update the modlist name field temporarily
        original_name = self.modlist_name_edit.text()
        self.modlist_name_edit.setText(new_name)
        
        # Restart the automated workflow
        self._safe_append_text(f"Retrying with new shortcut name: '{new_name}'")
        self._start_automated_prefix_workflow(new_name, os.path.dirname(self.install_dir_edit.text().strip()) if self.install_dir_edit.text().strip().endswith('ModOrganizer.exe') else self.install_dir_edit.text().strip(), self.install_dir_edit.text().strip(), self.resolution_combo.currentText())

    def handle_validation_failure(self, missing_text):
        """Handle manual steps validation failure with retry logic"""
        self._manual_steps_retry_count += 1
        
        if self._manual_steps_retry_count < 3:
            # Show retry dialog
            MessageService.show_error(self, manual_steps_incomplete())
            # Show manual steps dialog again
            extra_warning = ""
            if self._manual_steps_retry_count >= 2:
                extra_warning = "<br><b style='color:#f33'>It looks like you have not completed the manual steps yet. Please try again.</b>"
            self.show_manual_steps_dialog(extra_warning)
        else:
            # Max retries reached
            MessageService.show_error(self, manual_steps_incomplete())
            self.on_configuration_complete(False, "Manual steps validation failed after multiple attempts", self.modlist_name_edit.text().strip())

    def show_next_steps_dialog(self, message):
        dlg = QDialog(self)
        dlg.setWindowTitle("Next Steps")
        dlg.setModal(True)
        layout = QVBoxLayout(dlg)
        label = QLabel(message)
        label.setWordWrap(True)
        layout.addWidget(label)
        btn_row = QHBoxLayout()
        btn_return = QPushButton("Return")
        btn_exit = QPushButton("Exit")
        btn_row.addWidget(btn_return)
        btn_row.addWidget(btn_exit)
        layout.addLayout(btn_row)
        def on_return():
            dlg.accept()
            if self.stacked_widget:
                self.stacked_widget.setCurrentIndex(0)
        def on_exit():
            QApplication.quit()
        btn_return.clicked.connect(on_return)
        btn_exit.clicked.connect(on_exit)
        dlg.exec()
