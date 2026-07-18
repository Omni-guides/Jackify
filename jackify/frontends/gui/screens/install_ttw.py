
"""
InstallModlistScreen for Jackify GUI
"""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QComboBox, QHBoxLayout, QLineEdit, QPushButton, QGridLayout, QFileDialog, QTextEdit, QSizePolicy, QTabWidget, QDialog, QMessageBox, QProgressDialog, QApplication, QCheckBox, QStyledItemDelegate, QStyle, QFrame
from PySide6.QtCore import Qt, QSize, QThread, Signal, QTimer, QProcess, QMetaObject, QUrl
from PySide6.QtGui import QPixmap, QTextCursor, QPainter, QFont
from ..shared_theme import JACKIFY_COLOR_BLUE, DEBUG_BORDERS
from ..utils import ansi_to_html, strip_ansi_control_codes, set_responsive_minimum, _get_sidebar_urls
from ..widgets.unsupported_game_dialog import UnsupportedGameDialog
from jackify.frontends.gui.widgets.file_progress_list import FileProgressList
import os
import subprocess
import sys
import threading
from jackify.backend.handlers.shortcut_handler import ShortcutHandler
from jackify.backend.handlers.wabbajack_parser import WabbajackParser
import traceback
from jackify.backend.core.modlist_operations import get_jackify_engine_path
import signal
import re
import time
from jackify.backend.handlers.subprocess_utils import ProcessManager
from jackify.backend.handlers.config_handler import ConfigHandler
from ..dialogs import SuccessDialog
from jackify.backend.handlers.validation_handler import ValidationHandler
from jackify.frontends.gui.dialogs.warning_dialog import WarningDialog
from jackify.frontends.gui.services.message_service import MessageService
from jackify.shared.errors import manual_steps_incomplete
import logging
logger = logging.getLogger(__name__)
from .install_ttw_ui_setup import TTWUISetupMixin
from .install_ttw_integration import TTWIntegrationMixin
from .install_ttw_requirements import TTWRequirementsMixin
from .install_ttw_lifecycle import TTWLifecycleMixin
from .install_ttw_workflow import TTWWorkflowMixin
from .install_ttw_output import TTWOutputMixin
from .install_ttw_ui import TTWUIMixin
from .screen_back_mixin import ScreenBackMixin
from jackify.frontends.gui.mixins.thread_lifecycle_mixin import ThreadLifecycleMixin

class ModlistFetchThread(QThread):
    result = Signal(list, str)
    def __init__(self, game_type, log_path, mode='list-modlists'):
        super().__init__()
        self.game_type = game_type
        self.log_path = log_path
        self.mode = mode
    
    def run(self):
        try:
            # Use proper backend service - NOT the misnamed CLI class
            from jackify.backend.services.modlist_service import ModlistService
            from jackify.backend.models.configuration import SystemInfo
            
            # Initialize backend service
            # Detect if we're on Steam Deck
            is_steamdeck = False
            try:
                if os.path.exists('/etc/os-release'):
                    with open('/etc/os-release') as f:
                        if 'steamdeck' in f.read().lower():
                            is_steamdeck = True
            except Exception:
                pass
            
            system_info = SystemInfo(is_steamdeck=is_steamdeck)
            modlist_service = ModlistService(system_info)
            
            # Get modlists using proper backend service
            modlist_infos = modlist_service.list_modlists(game_type=self.game_type)
            
            # Return full modlist objects instead of just IDs to preserve enhanced metadata
            self.result.emit(modlist_infos, '')
            
        except Exception as e:
            error_msg = f"Backend service error: {str(e)}"
            # Don't write to log file before workflow starts - just return error
            self.result.emit([], error_msg)

class InstallTTWScreen(ThreadLifecycleMixin, ScreenBackMixin, TTWUISetupMixin, TTWIntegrationMixin, TTWRequirementsMixin, TTWLifecycleMixin, QWidget, TTWWorkflowMixin, TTWOutputMixin, TTWUIMixin):
    resize_request = Signal(str)
    integration_complete = Signal(bool, str)  # Signal for modlist integration completion (success, ttw_version)
    
    def _collect_actionable_controls(self):
        """Collect all actionable controls that should be disabled during operations (except Cancel)"""
        self._actionable_controls = [
            # Main action button
            self.start_btn,
            # File selection
            self.file_edit,
            self.file_btn,
            # Install directory
            self.install_dir_edit,
            self.browse_install_btn,
        ]

    def _disable_controls_during_operation(self):
        """Disable all actionable controls during install/configure operations (except Cancel)"""
        for control in self._actionable_controls:
            if control:
                control.setEnabled(False)

    def _enable_controls_after_operation(self):
        """Re-enable all actionable controls after install/configure operations complete"""
        for control in self._actionable_controls:
            if control:
                control.setEnabled(True)

    def refresh_paths(self):
        """Refresh cached paths when config changes."""
        from jackify.shared.paths import get_jackify_logs_dir
        self.modlist_log_path = get_jackify_logs_dir() / 'TTW_Install_workflow.log'
        os.makedirs(os.path.dirname(self.modlist_log_path), exist_ok=True)

    def _open_url_safe(self, url):
        """Safely open URL via subprocess to avoid Qt library clashes inside the AppImage runtime"""
        import subprocess
        import os
        _strip = {"LD_LIBRARY_PATH", "LD_PRELOAD", "QT_PLUGIN_PATH", "QML2_IMPORT_PATH", "PYTHONPATH", "PYTHONHOME"}
        clean_env = {k: v for k, v in os.environ.items() if k not in _strip}
        try:
            subprocess.Popen(['xdg-open', url], env=clean_env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        except Exception as e:
            logger.warning(f"Could not open URL {url}: {e}")

    def _load_saved_parent_directories(self):
        """No-op: do not pre-populate install/download directories from saved values."""
        pass

    def _update_directory_suggestions(self, modlist_name):
        """Update directory suggestions based on modlist name"""
        try:
            if not modlist_name:
                return
                
            # Update install directory suggestion with modlist name
            saved_install_parent = self.config_handler.get_default_install_parent_dir()
            if saved_install_parent:
                suggested_install_dir = os.path.join(saved_install_parent, modlist_name)
                self.install_dir_edit.setText(suggested_install_dir)
                logger.debug(f"Updated install directory suggestion: {suggested_install_dir}")
            
            # Update download directory suggestion
            saved_download_parent = self.config_handler.get_default_download_parent_dir()
            if saved_download_parent:
                suggested_download_dir = os.path.join(saved_download_parent, "Downloads")
                logger.debug(f"Updated download directory suggestion: {suggested_download_dir}")
                
        except Exception as e:
            logger.debug(f"Error updating directory suggestions: {e}")
    
    def _save_parent_directories(self, install_dir, downloads_dir):
        """Removed automatic saving - user should set defaults in settings"""
        pass

    def browse_wabbajack_file(self):
        start_path = self.file_edit.text() if self.file_edit.text() else os.path.expanduser("~")
        dialog = QFileDialog(self, "Select TTW .mpi File")
        dialog.setFileMode(QFileDialog.ExistingFile)
        dialog.setNameFilter("MPI Files (*.mpi);;All Files (*)")
        dialog.setDirectory(start_path)
        dialog.setOption(QFileDialog.DontUseNativeDialog, True)
        dialog.setSidebarUrls(_get_sidebar_urls())
        if dialog.exec() == QDialog.Accepted:
            files = dialog.selectedFiles()
            if files:
                self.file_edit.setText(files[0])

    def browse_install_dir(self):
        dialog = QFileDialog(self, "Select Install Directory")
        dialog.setFileMode(QFileDialog.Directory)
        dialog.setOption(QFileDialog.ShowDirsOnly, True)
        dialog.setOption(QFileDialog.DontUseNativeDialog, True)
        dialog.setSidebarUrls(_get_sidebar_urls())
        if self.install_dir_edit.text():
            dialog.setDirectory(self.install_dir_edit.text())
        if dialog.exec() == QDialog.Accepted:
            dirs = dialog.selectedFiles()
            if dirs:
                self.install_dir_edit.setText(dirs[0])

    def update_top_panel(self):
        try:
            result = subprocess.run([
                "ps", "-eo", "pcpu,pmem,comm,args"
            ], stdout=subprocess.PIPE, text=True, timeout=2)
            lines = result.stdout.splitlines()
            header = "CPU%\tMEM%\tCOMMAND"
            filtered = [header]
            process_rows = []
            for line in lines[1:]:
                line_lower = line.lower()
                if (
                    ("jackify-engine" in line_lower or "7zz" in line_lower or "texconv" in line_lower or
                     "wine" in line_lower or "wine64" in line_lower or "protontricks" in line_lower or
                     "ttw_linux" in line_lower)
                    and "jackify-gui.py" not in line_lower
                ):
                    cols = line.strip().split(None, 3)
                    if len(cols) >= 3:
                        process_rows.append(cols)
            process_rows.sort(key=lambda x: float(x[0]), reverse=True)
            for cols in process_rows:
                filtered.append('\t'.join(cols))
            if len(filtered) == 1:
                filtered.append("[No Jackify-related processes found]")
            self.process_monitor.setPlainText('\n'.join(filtered))
        except Exception as e:
            self.process_monitor.setPlainText(f"[process info unavailable: {e}]")

    def _check_protontricks(self):
        """Check if protontricks is available before critical operations"""
        try:
            if self.protontricks_service.is_bundled_mode():
                return True

            is_installed, installation_type, details = self.protontricks_service.detect_protontricks()
            
            if not is_installed:
                # Show protontricks error dialog
                from jackify.frontends.gui.dialogs.protontricks_error_dialog import ProtontricksErrorDialog
                dialog = ProtontricksErrorDialog(self.protontricks_service, self)
                result = dialog.exec()
                
                if result == QDialog.Rejected:
                    return False
                
                # Re-check after dialog
                is_installed, _, _ = self.protontricks_service.detect_protontricks(use_cache=False)
                return is_installed
            
            return True
            
        except Exception as e:
            logger.error(f"Error checking protontricks: {e}")
            MessageService.warning(self, "Protontricks Check Failed",
                                 f"Unable to verify protontricks installation: {e}\n\n"
                                 "Continuing anyway, but some features may not work correctly.")
            return True  # Continue anyway

    def _write_to_log_file(self, message):
        """Write message to workflow log file with timestamp."""
        try:
            import re
            from datetime import datetime
            clean = re.sub(r'<[^>]+>', '', str(message))
            if not clean.strip():
                return
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            with open(self.modlist_log_path, 'a', encoding='utf-8') as f:
                for line in clean.splitlines():
                    stripped = line.rstrip()
                    if stripped:
                        f.write(f"[{timestamp}] {stripped}\n")
        except Exception:
            pass

    def handle_validation_failure(self, missing_text):
        """Handle failed validation with retry logic"""
        self._manual_steps_retry_count += 1
        
        if self._manual_steps_retry_count < 3:
            # Show retry dialog with increasingly detailed guidance
            retry_guidance = ""
            if self._manual_steps_retry_count == 1:
                retry_guidance = "\n\nTip: Make sure Steam is fully restarted before trying again."
            elif self._manual_steps_retry_count == 2:
                retry_guidance = "\n\nTip: If using Flatpak Steam, ensure compatdata is being created in the correct location."
            
            MessageService.show_error(self, manual_steps_incomplete())
            # Show manual steps dialog again
            extra_warning = ""
            if self._manual_steps_retry_count >= 2:
                extra_warning = "<br><b style='color:#f33'>It looks like you have not completed the manual steps yet. Please try again.</b>"
            self.show_manual_steps_dialog(extra_warning)
        else:
            # Max retries reached
            MessageService.show_error(self, manual_steps_incomplete())
            self.on_configuration_complete(False, "Manual steps validation failed after multiple attempts", self._current_modlist_name)

    def show_next_steps_dialog(self, message):
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QHBoxLayout, QApplication
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
                self.stacked_widget.setCurrentIndex(0)  # Main menu
        def on_exit():
            QApplication.quit()
        btn_return.clicked.connect(on_return)
        btn_exit.clicked.connect(on_exit)
        dlg.exec()

    def cleanup_processes(self):
        if hasattr(self, 'install_thread') and self.install_thread:
            try:
                if self.install_thread.isRunning():
                    self.install_thread.cancel()
            except Exception:
                pass
    
    def cancel_installation(self):
        """Cancel the currently running installation"""
        reply = MessageService.question(
            self, "Cancel Installation",
            "Are you sure you want to cancel the installation?",
            critical=False,  # Non-critical, won't steal focus
            safety_level="medium",
        )

        if reply == QMessageBox.Yes:
            self._safe_append_text("\nCancelling installation...")

            # Stop the elapsed timer if running
            if hasattr(self, 'ttw_elapsed_timer') and self.ttw_elapsed_timer.isActive():
                self.ttw_elapsed_timer.stop()

            # Update status banner
            if hasattr(self, 'status_banner'):
                self.status_banner.setText("Installation cancelled by user")
                self.status_banner.setStyleSheet(f"""
                    background-color: #4d3d1a;
                    color: #FFA500;
                    padding: 8px;
                    border-radius: 4px;
                    font-weight: bold;
                    font-size: 13px;
                """)

            # Send process-group kill first so the subprocess tree dies before we
            # disconnect signals or wait on the thread.
            if hasattr(self, 'install_thread') and self.install_thread:
                try:
                    self.install_thread.cancel()
                except Exception:
                    pass

            # Park threads (disconnects signals so no callbacks fire on the dying widget).
            self._park_all_threads()

            # Wait up to 5 s for the thread to exit after the kill signal.
            if hasattr(self, 'install_thread') and self.install_thread:
                try:
                    self.install_thread.wait(5000)
                except Exception:
                    pass
                self.install_thread = None

            # Cleanup any remaining processes
            self.cleanup_processes()
            
            # Reset button states and re-enable all controls
            self._enable_controls_after_operation()
            self.cancel_btn.setVisible(True)
            self.cancel_install_btn.setVisible(False)
            
            # Collapse window if "Show Details" is checked
            if hasattr(self, 'show_details_checkbox') and self.show_details_checkbox.isChecked():
                self.resize_request.emit('collapse')
                self.show_details_checkbox.blockSignals(True)
                self.show_details_checkbox.setChecked(False)
                self.show_details_checkbox.blockSignals(False)
            
            self._safe_append_text("Installation cancelled by user.")

    def _show_somnium_post_install_guidance(self):
        """Show guidance popup for Somnium post-installation steps"""
        from ..services.message_service import MessageService
        
        guidance_text = f"""<b>Somnium Post-Installation Required</b><br><br>
Due to Somnium's non-standard folder structure, you need to manually update the binary paths in ModOrganizer:<br><br>
<b>1.</b> Launch the Steam shortcut created for Somnium<br>
<b>2.</b> In ModOrganizer, go to Settings → Executables<br>
<b>3.</b> For each executable entry (SKSE64, etc.), update the binary path to point to:<br>
<code>{self._somnium_install_dir}/files/root/Enderal Special Edition/skse64_loader.exe</code><br><br>
<b>Note:</b> Full Somnium support will be added in a future Jackify update.<br><br>
<i>You can also refer to the Somnium installation guide at:<br>
https://wiki.scenicroute.games/Somnium/1_Installation.html</i>"""
        
        MessageService.information(self, "Somnium Setup Required", guidance_text)
        
        # Reset the guidance flag
        self._show_somnium_guidance = False
        self._somnium_install_dir = None

    def cancel_and_cleanup(self):
        """Handle Cancel button - clean up processes and go back"""
        self.collapse_show_details_before_leave()
        self.go_back()
        QTimer.singleShot(0, self.cleanup_processes)
    
    def reset_screen_to_defaults(self):
        """Reset the screen to default state when navigating back from main menu"""
        # Clear integration mode first - a caller (e.g. the Begin Again automated TTW
        # trigger) sets it again immediately after this runs, via set_modlist_integration_mode.
        # Without this reset it stays True forever once set, so a later standalone TTW
        # install would silently try to integrate into a stale modlist from a prior run.
        self._integration_mode = False
        self.file_edit.setText("")
        self.install_dir_edit.setText(self.config_handler.get_modlist_install_base_dir())
        self.console.clear()
        self.process_monitor.clear()
        self.status_banner.setText("Ready to install")
        self.status_banner.setStyleSheet(f"""
            background-color: #2a2a2a;
            color: {JACKIFY_COLOR_BLUE};
            padding: 6px 8px;
            border-radius: 4px;
            font-weight: bold;
            font-size: 13px;
        """)

        # Re-enable controls (in case they were disabled from previous errors)
        self._enable_controls_after_operation()

        # Check requirements when screen is actually shown (not on app startup)
        self.check_requirements()

 
