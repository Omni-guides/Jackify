"""Modlist integration workflow for InstallTTWScreen (Mixin)."""
from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import QProgressDialog, QApplication
from jackify.frontends.gui.services.message_service import MessageService
from pathlib import Path
import traceback
import os
import json
import shutil
import re
import logging

logger = logging.getLogger(__name__)
class TTWIntegrationMixin:
    """Mixin providing modlist integration workflow for InstallTTWScreen."""

    def set_modlist_integration_mode(self, modlist_name: str, install_dir: str):
        """Set the screen to modlist integration mode

        This mode is activated when TTW needs to be installed and integrated
        into an existing modlist. In this mode, after TTW installation completes,
        the TTW output will be automatically integrated into the modlist.

        Args:
            modlist_name: Name of the modlist to integrate TTW into
            install_dir: Installation directory of the modlist
        """
        self._integration_mode = True
        self._integration_modlist_name = modlist_name
        self._integration_install_dir = install_dir

        # Pre-populate output dir to install TTW directly into the modlist mods folder,
        # avoiding the wasteful copy step during integration.
        ttw_target = Path(install_dir) / "mods" / "[NoDelete] Tale of Two Wastelands"
        self.install_dir_edit.setText(str(ttw_target))

        # Reset saved geometry so showEvent can properly collapse from current window size
        self._saved_geometry = None
        self._saved_min_size = None

        logger.debug(f"TTW screen set to integration mode for modlist: {modlist_name}")
        logger.debug(f"TTW output pre-populated to: {ttw_target}")

    def _perform_modlist_integration(self):
        """Integrate TTW into the modlist automatically

        This is called when in integration mode. It will:
        1. Copy TTW output to modlist's mods folder
        2. Update modlist.txt for all profiles
        3. Update plugins.txt with TTW ESMs in correct order
        4. Emit integration_complete signal
        """
        try:
            from pathlib import Path
            import re
            from PySide6.QtCore import QThread, Signal

            # Get TTW output directory
            ttw_output_dir = Path(self.install_dir_edit.text())
            if not ttw_output_dir.exists():
                error_msg = f"TTW output directory not found: {ttw_output_dir}"
                self._safe_append_text(f"\nError: {error_msg}")
                self.integration_complete.emit(False, "")
                return

            # Extract version from .mpi filename
            mpi_path = self.file_edit.text().strip()
            ttw_version = ""
            if mpi_path:
                mpi_filename = Path(mpi_path).stem
                version_match = re.search(r'v?(\d+\.\d+(?:\.\d+)?)', mpi_filename, re.IGNORECASE)
                if version_match:
                    ttw_version = version_match.group(1)

            # If TTW was installed directly into the modlist mods dir (integration mode
            # pre-populate), rename to the versioned folder name and skip the copy step.
            skip_copy = False
            mods_dir = Path(self._integration_install_dir) / "mods"
            if ttw_output_dir.parent == mods_dir:
                versioned_name = f"[NoDelete] Tale of Two Wastelands {ttw_version}".strip() if ttw_version else "[NoDelete] Tale of Two Wastelands"
                versioned_path = mods_dir / versioned_name
                if ttw_output_dir != versioned_path and ttw_output_dir.exists():
                    logger.debug(f"Renaming TTW output: {ttw_output_dir.name} -> {versioned_name}")
                    ttw_output_dir.rename(versioned_path)
                    ttw_output_dir = versioned_path
                skip_copy = True
                logger.debug("TTW already in mods dir - skipping copy step")

            # Create background thread for integration
            class IntegrationThread(QThread):
                finished = Signal(bool, str)  # success, ttw_version
                progress = Signal(str)  # progress message

                def __init__(self, ttw_output_path, modlist_install_dir, ttw_version, skip_copy):
                    super().__init__()
                    self.ttw_output_path = ttw_output_path
                    self.modlist_install_dir = modlist_install_dir
                    self.ttw_version = ttw_version
                    self.skip_copy = skip_copy

                def run(self):
                    try:
                        from jackify.backend.handlers.ttw_installer_handler import TTWInstallerHandler

                        self.progress.emit("Integrating TTW into modlist...")
                        success = TTWInstallerHandler.integrate_ttw_into_modlist(
                            ttw_output_path=self.ttw_output_path,
                            modlist_install_dir=self.modlist_install_dir,
                            ttw_version=self.ttw_version,
                            skip_copy=self.skip_copy,
                        )
                        self.finished.emit(success, self.ttw_version)
                    except Exception as e:
                        logger.debug(f"ERROR: Integration thread failed: {e}")
                        import traceback
                        traceback.print_exc()
                        self.finished.emit(False, self.ttw_version)

            # Show progress message
            self._safe_append_text("\nIntegrating TTW into modlist (this may take a few minutes)...")

            # Update status banner (only in integration mode - visible when collapsed)
            if self._integration_mode:
                self.status_banner.setText("Integrating TTW into modlist (this may take a few minutes)...")
                self.status_banner.setStyleSheet(f"""
                    QLabel {{
                        background-color: #FFA500;
                        color: white;
                        font-weight: bold;
                        padding: 8px;
                        border-radius: 5px;
                    }}
                """)

            # Create progress dialog for integration
            progress_dialog = QProgressDialog(
                f"Integrating TTW {ttw_version} into modlist...\n\n"
                "This involves copying several GB of files and may take a few minutes.\n"
                "Please wait...",
                None,  # No cancel button
                0, 0,  # Indeterminate progress
                self
            )
            progress_dialog.setWindowTitle("Integrating TTW")
            progress_dialog.setMinimumDuration(0)  # Show immediately
            progress_dialog.setWindowModality(Qt.ApplicationModal)
            progress_dialog.setCancelButton(None)
            progress_dialog.show()
            QApplication.processEvents()

            # Store reference to close later
            self._integration_progress_dialog = progress_dialog

            # Create and start integration thread
            self.integration_thread = IntegrationThread(
                ttw_output_dir,
                Path(self._integration_install_dir),
                ttw_version,
                skip_copy,
            )
            self.integration_thread.progress.connect(self._safe_append_text)
            self.integration_thread.finished.connect(self._on_integration_thread_finished)
            self.integration_thread.start()

        except Exception as e:
            # Close progress dialog if it exists
            if hasattr(self, '_integration_progress_dialog'):
                self._integration_progress_dialog.close()
                delattr(self, '_integration_progress_dialog')

            error_msg = f"Integration error: {str(e)}"
            self._safe_append_text(f"\nError: {error_msg}")
            logger.debug(f"ERROR: {error_msg}")
            import traceback
            traceback.print_exc()
            self.integration_complete.emit(False, "")

    def _on_integration_thread_finished(self, success: bool, ttw_version: str):
        """Handle completion of integration thread"""
        try:
            # Close progress dialog
            if hasattr(self, '_integration_progress_dialog'):
                self._integration_progress_dialog.close()
                delattr(self, '_integration_progress_dialog')

            if success:
                self._safe_append_text("\nTTW integration completed successfully!")

                # Update status banner (only in integration mode)
                if self._integration_mode:
                    self.status_banner.setText("TTW integration completed successfully!")
                    self.status_banner.setStyleSheet(f"""
                        QLabel {{
                            background-color: #1a3040;
                            color: white;
                            font-weight: bold;
                            padding: 8px;
                            border-radius: 5px;
                        }}
                    """)

                MessageService.information(
                    self, "Integration Complete",
                    f"TTW {ttw_version} has been successfully integrated into {self._integration_modlist_name}!",
                    safety_level="medium"
                )
                self.integration_complete.emit(True, ttw_version)
            else:
                self._safe_append_text("\nTTW integration failed!")

                # Update status banner (only in integration mode)
                if self._integration_mode:
                    self.status_banner.setText("TTW integration failed!")
                    self.status_banner.setStyleSheet(f"""
                        QLabel {{
                            background-color: #dc3545;
                            color: white;
                            font-weight: bold;
                            padding: 8px;
                            border-radius: 5px;
                        }}
                    """)

                MessageService.critical(
                    self, "Integration Failed",
                    "Failed to integrate TTW into the modlist. Check the log for details."
                )
                self.integration_complete.emit(False, ttw_version)
        except Exception as e:
            logger.debug(f"ERROR: Failed to handle integration completion: {e}")
            self.integration_complete.emit(False, ttw_version)

    def _create_ttw_mod_archive(self, automated=False):
        """Create a zipped mod archive of TTW output for MO2 installation.

        Args:
            automated: If True, runs silently without user prompts (for automation)
        """
        try:
            from pathlib import Path
            import re
            from PySide6.QtCore import QThread, Signal

            output_dir = Path(self.install_dir_edit.text())
            if not output_dir.exists():
                if not automated:
                    MessageService.warning(self, "Output Directory Not Found",
                                         f"Output directory does not exist:\n{output_dir}")
                return False

            # Extract version from .mpi filename (e.g., "TTW v3.4.mpi" -> "3.4")
            mpi_path = self.file_edit.text().strip()
            version_suffix = ""
            if mpi_path:
                mpi_filename = Path(mpi_path).stem
                version_match = re.search(r'v?(\d+\.\d+(?:\.\d+)?)', mpi_filename, re.IGNORECASE)
                if version_match:
                    version_suffix = f" {version_match.group(1)}"

            # Create archive filename
            archive_name = f"[NoDelete] Tale of Two Wastelands{version_suffix}"
            archive_path = output_dir.parent / archive_name

            # Create background thread for zip creation
            class ZipCreationThread(QThread):
                finished = Signal(bool, str)  # success, result_message

                def __init__(self, output_dir, archive_path):
                    super().__init__()
                    self.output_dir = output_dir
                    self.archive_path = archive_path

                def run(self):
                    try:
                        import shutil
                        final_archive = shutil.make_archive(
                            str(self.archive_path),
                            'zip',
                            str(self.output_dir)
                        )
                        self.finished.emit(True, str(final_archive))
                    except Exception as e:
                        self.finished.emit(False, str(e))

            # Create progress dialog (non-modal so UI stays responsive)
            progress_dialog = QProgressDialog(
                f"Creating mod archive: {archive_name}.zip\n\n"
                "This may take several minutes depending on installation size...",
                "Cancel",
                0, 0,  # 0,0 = indeterminate progress bar
                self
            )
            progress_dialog.setWindowTitle("Creating Archive")
            progress_dialog.setMinimumDuration(0)  # Show immediately
            progress_dialog.setWindowModality(Qt.ApplicationModal)
            progress_dialog.setCancelButton(None)  # Cannot cancel zip operation safely
            progress_dialog.show()
            QApplication.processEvents()

            # Create and start thread
            zip_thread = ZipCreationThread(output_dir, archive_path)

            def on_zip_finished(success, result):
                progress_dialog.close()
                if success:
                    final_archive = result
                    if not automated:
                        self._safe_append_text(f"\nArchive created successfully: {Path(final_archive).name}")
                        MessageService.information(
                            self, "Archive Created",
                            f"TTW mod archive created successfully!\n\n"
                            f"Location: {final_archive}\n\n"
                            f"You can now install this archive as a mod in MO2.",
                            safety_level="medium"
                        )
                else:
                    error_msg = f"Failed to create mod archive: {result}"
                    if not automated:
                        self._safe_append_text(f"\nError: {error_msg}")
                        MessageService.critical(self, "Archive Creation Failed", error_msg)

            zip_thread.finished.connect(on_zip_finished)
            zip_thread.start()

            # Keep reference to prevent garbage collection
            self._zip_thread = zip_thread

            return True

        except Exception as e:
            error_msg = f"Failed to create mod archive: {str(e)}"
            if not automated:
                self._safe_append_text(f"\nError: {error_msg}")
                MessageService.critical(self, "Archive Creation Failed", error_msg)
            return False

