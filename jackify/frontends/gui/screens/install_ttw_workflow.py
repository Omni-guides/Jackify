"""TTW installation workflow methods for InstallTTWScreen (Mixin)."""
from pathlib import Path
from PySide6.QtCore import QTimer, Qt, QProcess
from PySide6.QtWidgets import QMessageBox, QApplication
from PySide6.QtGui import QTextCursor
import logging
import os
import time
import traceback

from jackify.frontends.gui.services.message_service import MessageService
from jackify.shared.errors import install_dir_create_failed, wabbajack_install_failed
from jackify.backend.handlers.validation_handler import ValidationHandler
from jackify.frontends.gui.dialogs.warning_dialog import WarningDialog
from ..shared_theme import JACKIFY_COLOR_BLUE

logger = logging.getLogger(__name__)


class TTWWorkflowMixin:
    """Mixin providing installation workflow methods for InstallTTWScreen."""

    def validate_and_start_install(self):
        import time
        self._install_workflow_start_time = time.time()

        self.config_handler.reload_config()
        logger.debug("Reloaded config from disk")

        if not self._check_ttw_requirements():
            return

        if not self._check_protontricks():
            return

        self._disable_controls_during_operation()

        try:
            mpi_path = self.file_edit.text().strip()
            if not mpi_path or not os.path.isfile(mpi_path) or not mpi_path.endswith('.mpi'):
                MessageService.warning(self, "Invalid TTW File", "Please select a valid TTW .mpi file.")
                self._enable_controls_after_operation()
                return
            install_dir = self.install_dir_edit.text().strip()

            missing_fields = []
            if not install_dir:
                missing_fields.append("Install Directory")
            if missing_fields:
                MessageService.warning(self, "Missing Required Fields", f"Please fill in all required fields before starting the install:\n- " + "\n- ".join(missing_fields))
                self._enable_controls_after_operation()
                return

            mpi_path = os.path.realpath(mpi_path)
            install_dir = os.path.realpath(install_dir)
            validation_handler = ValidationHandler()
            install_dir_path = Path(install_dir)

            if validation_handler.is_dangerous_directory(install_dir_path):
                dlg = WarningDialog(
                    f"The directory '{install_dir}' is a system or user root and cannot be used for TTW installation.",
                    parent=self
                )
                if not dlg.exec() or not dlg.confirmed:
                    self._enable_controls_after_operation()
                    return

            if install_dir_path.exists() and install_dir_path.is_dir():
                try:
                    has_files = any(install_dir_path.iterdir())
                    if has_files:
                        dlg = WarningDialog(
                            f"The TTW output directory already exists and contains files:\n{install_dir}\n\n"
                            f"All files in this directory will be deleted before installation.\n\n"
                            f"This action cannot be undone.",
                            parent=self
                        )
                        if not dlg.exec() or not dlg.confirmed:
                            self._enable_controls_after_operation()
                            return

                        import shutil
                        try:
                            for item in install_dir_path.iterdir():
                                if item.is_dir():
                                    shutil.rmtree(item)
                                else:
                                    item.unlink()
                            logger.debug(f"Deleted all contents of {install_dir}")
                        except Exception as e:
                            MessageService.show_error(self, install_dir_create_failed(str(install_dir), str(e)))
                            self._enable_controls_after_operation()
                            return
                except Exception as e:
                    logger.debug(f"Error checking directory contents: {e}")

            if not os.path.isdir(install_dir):
                create = MessageService.question(self, "Create Directory?",
                    f"The install directory does not exist:\n{install_dir}\n\nWould you like to create it?",
                    critical=False
                )
                if create == QMessageBox.Yes:
                    try:
                        os.makedirs(install_dir, exist_ok=True)
                    except Exception as e:
                        MessageService.show_error(self, install_dir_create_failed(install_dir, str(e)))
                        self._enable_controls_after_operation()
                        return
                else:
                    self._enable_controls_after_operation()
                    return

            self.console.clear()
            self.process_monitor.clear()

            self.start_btn.setEnabled(False)
            self.cancel_btn.setVisible(False)
            self.cancel_install_btn.setVisible(True)

            logger.debug(f"Calling run_ttw_installer with mpi_path={mpi_path}, install_dir={install_dir}")
            self.run_ttw_installer(mpi_path, install_dir)
        except Exception as e:
            self._enable_controls_after_operation()
            self.cancel_btn.setVisible(True)
            self.cancel_install_btn.setVisible(False)

    def run_ttw_installer(self, mpi_path, install_dir):
        logger.debug("run_ttw_installer called - USING THREADED BACKEND WRAPPER")

        self.config_handler._load_config()

        from jackify.backend.handlers.logging_handler import LoggingHandler
        log_handler = LoggingHandler()
        log_handler.rotate_log_file_per_run(Path(self.modlist_log_path), backup_count=5)

        self.console.clear()
        self._safe_append_text("Starting TTW installation...")

        self.file_progress_list.clear()
        self._update_ttw_phase("Initialising TTW installation", 0, 0, 0)
        QApplication.processEvents()

        self.status_banner.setVisible(True)
        self.status_banner.setText("Initialising TTW installation...")
        self.show_details_checkbox.setVisible(True)

        self.status_banner.setStyleSheet(f"""
            background-color: #2a2a2a;
            color: {JACKIFY_COLOR_BLUE};
            padding: 8px;
            border-radius: 4px;
            font-weight: bold;
            font-size: 13px;
        """)

        self.ttw_start_time = time.time()

        self.ttw_elapsed_timer = QTimer()
        self.ttw_elapsed_timer.timeout.connect(self._update_ttw_elapsed_time)
        self.ttw_elapsed_timer.start(1000)

        self.start_btn.setEnabled(False)
        self.cancel_btn.setVisible(False)
        self.cancel_install_btn.setVisible(True)

        from .install_ttw_thread import TTWInstallationThread
        self.install_thread = TTWInstallationThread(mpi_path, install_dir)
        self.install_thread.output_batch_received.connect(self.on_installation_output_batch, Qt.QueuedConnection)
        self.install_thread.progress_received.connect(self.on_installation_progress, Qt.QueuedConnection)
        self.install_thread.installation_finished.connect(self.on_installation_finished, Qt.QueuedConnection)

        self.install_thread.start()
        QApplication.processEvents()

    def on_installation_finished(self, success, message):
        """Handle installation completion."""
        logger.debug(f"on_installation_finished called with success={success}, message={message}")

        if hasattr(self, 'ttw_elapsed_timer'):
            self.ttw_elapsed_timer.stop()

        if success:
            elapsed = int(time.time() - self.ttw_start_time) if hasattr(self, 'ttw_start_time') else 0
            minutes = elapsed // 60
            seconds = elapsed % 60
            self.status_banner.setText(f"Installation completed successfully! Total time: {minutes}m {seconds}s")
            self.status_banner.setStyleSheet("""
                background-color: #1a3040;
                color: #3fd0ea;
                padding: 8px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 13px;
            """)
            self._safe_append_text(f"\nSuccess: {message}")
            self.process_finished(0, QProcess.NormalExit)
        else:
            self.status_banner.setText(f"Installation failed: {message}")
            self.status_banner.setStyleSheet("""
                background-color: #4d1a1a;
                color: #f44336;
                padding: 8px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 13px;
            """)
            self._safe_append_text(f"\nError: {message}")
            if getattr(self, '_ttw_unclean_game_dir_detected', False):
                self._safe_append_text(
                    "\nLikely cause: Your Fallout New Vegas game directory is not clean vanilla.\n"
                    "TTW requires an unmodified FNV installation to patch correctly.\n"
                    "If you have previously installed an FNV modlist that modifies the game directory,\n"
                    "verify or reinstall FNV via Steam to restore vanilla files, then try again."
                )
            self._last_install_message = message
            self.process_finished(1, QProcess.CrashExit)

    def process_finished(self, exit_code, exit_status):
        logger.debug(f"process_finished called with exit_code={exit_code}, exit_status={exit_status}")
        self.start_btn.setEnabled(True)
        self.cancel_btn.setVisible(True)
        self.cancel_install_btn.setVisible(False)
        logger.debug("Button states reset in process_finished")

        if exit_code == 0:
            self._safe_append_text("\nTTW installation completed successfully!")
            self._safe_append_text("The merged TTW files have been created in the output directory.")

            if self._integration_mode:
                self._safe_append_text("\nIntegrating TTW into modlist...")
                self._perform_modlist_integration()
            else:
                reply = MessageService.question(
                    self, "TTW Installation Complete!",
                    "Tale of Two Wastelands installation completed successfully!\n\n"
                    f"Output location: {self.install_dir_edit.text()}\n\n"
                    "Would you like to create a zipped mod archive for MO2?\n"
                    "This will package the TTW files for easy installation into Mod Organizer 2.",
                    critical=False,
                    safety_level="medium",
                )

                if reply == QMessageBox.Yes:
                    self._create_ttw_mod_archive()
                else:
                    MessageService.information(
                        self, "Installation Complete",
                        "TTW installation complete!\n\n"
                        "You can manually use the TTW files from the output directory.",
                        safety_level="medium"
                    )
        else:
            last_output = self.console.toPlainText()
            failure_msg = (getattr(self, '_last_install_message', '') or "").strip()
            if "cancelled by user" in last_output.lower() or "cancelled by user" in failure_msg.lower():
                MessageService.information(self, "Installation Cancelled", "The installation was cancelled by the user.", safety_level="low")
            else:
                user_summary = failure_msg or "TTW installation failed. Review recent console output for the failing step."
                MessageService.show_error(self, wabbajack_install_failed(user_summary))
                self._safe_append_text(f"\nInstall failed: {user_summary}")
        self.console.moveCursor(QTextCursor.End)
