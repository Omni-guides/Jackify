"""
InstallModlistScreen for Jackify GUI
"""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QComboBox, QHBoxLayout, QLineEdit, QPushButton, QGridLayout, QFileDialog, QTextEdit, QSizePolicy, QTabWidget, QDialog, QListWidget, QListWidgetItem, QMessageBox, QProgressDialog, QApplication, QCheckBox, QStyledItemDelegate, QStyle, QTableWidget, QTableWidgetItem, QHeaderView, QMainWindow
from PySide6.QtCore import Qt, QSize, QThread, Signal, QTimer, QProcess, QMetaObject, QUrl
from PySide6.QtGui import QPixmap, QTextCursor, QColor, QPainter, QFont
from ..shared_theme import JACKIFY_COLOR_BLUE, DEBUG_BORDERS
from ..utils import ansi_to_html, set_responsive_minimum
from ..widgets.unsupported_game_dialog import UnsupportedGameDialog
import os
import subprocess
import sys
import threading
from typing import Optional
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
from jackify.backend.utils.nexus_premium_detector import is_non_premium_indicator
# R&D: Progress reporting components
from jackify.backend.handlers.progress_parser import ProgressStateManager
from jackify.frontends.gui.widgets.progress_indicator import OverallProgressIndicator
from jackify.frontends.gui.widgets.file_progress_list import FileProgressList
from jackify.shared.progress_models import InstallationPhase, InstallationProgress, OperationType, FileProgress
from jackify.shared.errors import manual_steps_incomplete
# Modlist gallery (imported at module level to avoid import delay when opening dialog)
from jackify.frontends.gui.screens.modlist_gallery import ModlistGalleryDialog
import logging
logger = logging.getLogger(__name__)
from .install_modlist_dialogs import ModlistFetchThread, SelectionDialog
from .install_modlist_ui_setup import InstallModlistUISetupMixin
from .install_modlist_console import ConsoleOutputMixin
from .install_modlist_progress import ProgressHandlersMixin
from .install_modlist_postinstall import PostInstallFeedbackMixin
from .install_modlist_automated_prefix import AutomatedPrefixHandlersMixin
from .install_modlist_configuration import ConfigurationPhaseMixin
from .install_modlist_ttw import TTWIntegrationMixin
from .install_modlist_vnv import VNVAutomationMixin
from .install_modlist_workflow import InstallWorkflowMixin
from .install_modlist_nexus import NexusAuthMixin
from .install_modlist_selection import ModlistSelectionMixin
from .screen_back_mixin import ScreenBackMixin
from .install_verifier_mixin import InstallVerifierMixin
from jackify.frontends.gui.mixins.thread_lifecycle_mixin import ThreadLifecycleMixin

class InstallModlistScreen(ThreadLifecycleMixin, ScreenBackMixin, InstallVerifierMixin, InstallModlistUISetupMixin, ConsoleOutputMixin, ProgressHandlersMixin, PostInstallFeedbackMixin, AutomatedPrefixHandlersMixin, ConfigurationPhaseMixin, QWidget, TTWIntegrationMixin, VNVAutomationMixin, InstallWorkflowMixin, NexusAuthMixin, ModlistSelectionMixin):
    resize_request = Signal(str)  # Signal for expand/collapse like TTW screen
    def _collect_actionable_controls(self):
        """Collect all actionable controls that should be disabled during operations (except Cancel)"""
        self._actionable_controls = [
            # Main action button
            self.start_btn,
            # Game/modlist selection
            self.game_type_btn,
            self.modlist_btn,
            # Source tabs (entire tab widget)
            self.source_tabs,
            # Form fields
            self.modlist_name_edit,
            self.install_dir_edit,
            self.downloads_dir_edit,
            self.file_edit,
            # Browse buttons
            self.browse_install_btn,
            self.browse_downloads_btn,
            self.file_btn,
            # Resolution controls
            self.resolution_combo,
            # Nexus login button
            self.nexus_login_btn,
            # Checkboxes
            self.auto_restart_checkbox,
            self.engine_checkbox,
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

    def _abort_install_validation(self):
        """Reset UI state when validation is aborted early."""
        self._enable_controls_after_operation()
        self.cancel_btn.setVisible(True)
        self.cancel_install_btn.setVisible(False)
        self.progress_indicator.reset()
        self.process_monitor.clear()

    def _abort_with_message(self, level: str, title: str, message: str, **kwargs):
        """Show a message and abort the validation workflow."""
        messenger = getattr(MessageService, level, MessageService.warning)
        messenger(self, title, message, **kwargs)
        self._abort_install_validation()

    def refresh_paths(self):
        """Refresh cached paths when config changes."""
        from jackify.shared.paths import get_jackify_logs_dir
        self.modlist_log_path = get_jackify_logs_dir() / 'Modlist_Install_workflow.log'
        os.makedirs(os.path.dirname(self.modlist_log_path), exist_ok=True)

    def _open_url_safe(self, url):
        import subprocess
        _strip = {"LD_LIBRARY_PATH", "LD_PRELOAD", "QT_PLUGIN_PATH", "QML2_IMPORT_PATH", "PYTHONPATH", "PYTHONHOME"}
        clean_env = {k: v for k, v in os.environ.items() if k not in _strip}
        try:
            subprocess.Popen(['xdg-open', url], env=clean_env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        except Exception as e:
            logger.warning(f"Could not open URL {url}: {e}")

    def resizeEvent(self, event):
        """Handle window resize to prioritize form over console"""
        super().resizeEvent(event)
        self._adjust_console_for_form_priority()

    def _adjust_console_for_form_priority(self):
        """Console now dynamically fills available space with stretch=1, no manual calculation needed"""
        # The console automatically fills remaining space due to stretch=1 in the layout
        # Remove any fixed height constraints to allow natural stretching
        self.console.setMaximumHeight(16777215)  # Reset to default maximum
        self.console.setMinimumHeight(50)  # Keep minimum height for usability

    def showEvent(self, event):
        """Called when the widget becomes visible - ensure collapsed state"""
        super().showEvent(event)

        # Refresh Nexus auth status when screen becomes visible
        # Refresh auth status after OAuth from Settings
        self._update_nexus_status()

        # Do NOT load saved parent directories

        # Gallery cache preloads at app startup (see JackifyMainWindow.__init__)

        # Ensure initial collapsed layout each time this screen is opened (like TTW screen)
        try:
            from PySide6.QtCore import Qt as _Qt
            # Ensure checkbox is unchecked without emitting signals
            if self.show_details_checkbox.isChecked():
                self.show_details_checkbox.blockSignals(True)
                self.show_details_checkbox.setChecked(False)
                self.show_details_checkbox.blockSignals(False)
            
            # Force collapsed state
            self._toggle_console_visibility(_Qt.Unchecked)
            # Force the window to compact height
            main_window = self.window()
            if main_window:
                # Save original geometry once
                if self._saved_geometry is None:
                    self._saved_geometry = main_window.geometry()
                if self._saved_min_size is None:
                    self._saved_min_size = main_window.minimumSize()
                # Use Qt's standard approach: let layout size naturally, only set minimum
                # Allow manual resizing, prevent content cut-off
                from PySide6.QtCore import QTimer, QSize
                from PySide6.QtWidgets import QApplication
                
                def calculate_and_set_upper_section_height():
                    """Calculate and lock the upper section height based on left side only"""
                    try:
                        if hasattr(self, 'upper_section_widget') and self.upper_section_widget is not None:
                            # Only calculate if we haven't stored it yet
                            if not hasattr(self, '_upper_section_fixed_height') or self._upper_section_fixed_height is None:
                                # Calculate height based on LEFT side (user_config_widget) only
                                if hasattr(self, 'user_config_widget') and self.user_config_widget is not None:
                                    # Force layout updates to ensure everything is calculated
                                    self.user_config_widget.updateGeometry()
                                    self.user_config_widget.layout().update()
                                    self.updateGeometry()
                                    self.layout().update()
                                    QApplication.processEvents()
                                    # Get the natural height of the left side
                                    left_height = self.user_config_widget.sizeHint().height()
                                    # Add a small margin for spacing
                                    self._upper_section_fixed_height = left_height + 20
                                else:
                                    # Fallback: use sizeHint of upper section
                                    self.upper_section_widget.updateGeometry()
                                    self._upper_section_fixed_height = self.upper_section_widget.sizeHint().height()
                            # Lock the height - same in both modes
                            self.upper_section_widget.setMaximumHeight(self._upper_section_fixed_height)
                            self.upper_section_widget.setMinimumHeight(self._upper_section_fixed_height)
                    except Exception as e:
                        if self.debug:
                            logger.debug(f"Error calculating upper section height: {e}")
                
                # Calculate heights immediately after forcing layout update
                # Prevents visible layout shift
                self.updateGeometry()
                self.layout().update()
                QApplication.processEvents()
                
                # Calculate upper section height immediately
                calculate_and_set_upper_section_height()

                # Only set minimum size - DO NOT RESIZE
                from PySide6.QtCore import QSize
                # On Steam Deck, keep fullscreen; on other systems, set normal window state
                if not (hasattr(main_window, 'system_info') and main_window.system_info.is_steamdeck):
                    main_window.showNormal()
                main_window.setMaximumSize(QSize(16777215, 16777215))
                set_responsive_minimum(main_window, min_width=960, min_height=420)
                # DO NOT resize - let window stay at current size
        except Exception as e:
            logger.debug(f"showEvent exception: {e}")
    
    def _start_gallery_cache_preload(self):
        """DEPRECATED: Gallery cache preload now happens at app startup in JackifyMainWindow"""
        # Only start once per session
        if self._gallery_cache_preload_started:
            return

        self._gallery_cache_preload_started = True
        
        # Create background thread to preload gallery cache
        class GalleryCachePreloadThread(QThread):
            finished_signal = Signal(bool, str)  # success, message
            
            def run(self):
                try:
                    from jackify.backend.services.modlist_gallery_service import ModlistGalleryService
                    service = ModlistGalleryService()
                    
                    # Fetch with search index to build cache (this will take time but is invisible)
                    # Use force_refresh=False to allow using existing cache if it has mods
                    metadata = service.fetch_modlist_metadata(
                        include_validation=False,  # Skip validation for speed
                        include_search_index=True,  # Include mods for search
                        sort_by="title",
                        force_refresh=False  # Use cache if it has mods, otherwise fetch fresh
                    )
                    
                    if metadata:
                        # Check if we got mods
                        modlists_with_mods = sum(1 for m in metadata.modlists if hasattr(m, 'mods') and m.mods)
                        if modlists_with_mods > 0:
                            logger.debug(f"Gallery cache ready ({modlists_with_mods} modlists with mods)")
                        else:
                            # Cache didn't have mods, but we fetched fresh - should have mods now
                            logger.debug("Gallery cache updated")
                    else:
                        logger.debug("Failed to load gallery cache")
                        
                except Exception as e:
                    logger.debug(f"Gallery cache preload error: {str(e)}")
        
        # Start thread (non-blocking, invisible to user)
        self._gallery_cache_preload_thread = GalleryCachePreloadThread()
        # Don't connect finished signal - we don't need to do anything, just let it run
        self._gallery_cache_preload_thread.start()
        
        logger.debug("Started background gallery cache preload")

    def hideEvent(self, event):
        """Called when the widget is hidden. Do not clear main window constraints so collapse from go_back() sticks."""
        super().hideEvent(event)

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
                self.downloads_dir_edit.setText(suggested_download_dir)
                logger.debug(f"Updated download directory suggestion: {suggested_download_dir}")
                
        except Exception as e:
            logger.debug(f"Error updating directory suggestions: {e}")
    
    def _save_parent_directories(self, install_dir, downloads_dir):
        """Removed automatic saving - user should set defaults in settings"""
        pass

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
                     "hoolamike" in line_lower)
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

    def _on_show_details_toggled(self, checked: bool):
        """R&D: Toggle console visibility (reuse TTW pattern)"""
        from PySide6.QtCore import Qt as _Qt
        self._toggle_console_visibility(_Qt.Checked if checked else _Qt.Unchecked)
    
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

    def hideEvent(self, event):
        if getattr(self, '_vnv_controller', None) is not None:
            try:
                self._vnv_controller.cleanup()
            except Exception:
                pass
        super().hideEvent(event)

    def cleanup_processes(self):
        self._stop_clf3_decompress_pulse()

        fpl = getattr(self, 'file_progress_list', None)
        if fpl is not None:
            try:
                fpl.stop_cpu_tracking()
            except Exception:
                pass

        if getattr(self, '_vnv_controller', None) is not None:
            self._vnv_controller.cleanup()
            self._vnv_controller = None

        self._stop_focus_reclaim()

        # install_thread needs cancel() to kill the child subprocess, not just
        # signal disconnection. The extended wait gives the engine time to flush.
        thread = getattr(self, 'install_thread', None)
        if thread is not None:
            try:
                running = thread.isRunning()
            except RuntimeError:
                running = False
            if running:
                try:
                    thread.cancel()
                except Exception:
                    pass
                if not thread.wait(15000):
                    logger.warning("install_thread did not stop in 15s")
                    thread.wait(10000)
            self.install_thread = None
    
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

            # Set flag so we can detect cancellation reliably
            self._cancellation_requested = True

            try:
                # Clear Active Files window and update progress indicator
                if hasattr(self, 'file_progress_list'):
                    self.file_progress_list.clear()
                if hasattr(self, 'progress_indicator'):
                    self.progress_indicator.set_status("Cancelled", None)

                # Stop manual download manager and close dialog if active
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
                if getattr(self, '_non_premium_info_dlg', None) is not None:
                    try:
                        self._non_premium_info_dlg.close()
                    except Exception:
                        pass
                    self._non_premium_info_dlg = None
                self._non_premium_gate_enabled = False
                self._non_premium_info_acknowledged = False
                self._pending_manual_download_events = None

                # Cancel the installation thread if it exists
                try:
                    if hasattr(self, 'install_thread') and self.install_thread and self.install_thread.isRunning():
                        self.install_thread.cancel()
                        self.install_thread.wait(12000)  # Allow time for child processes (7zz) to die; no terminate() - pthread_cancel corrupts Python
                        if self.install_thread.isRunning():
                            logger.warning("WARNING: InstallationThread still running after 12s cancel wait; retrying")
                            self.install_thread.cancel()
                            self.install_thread.wait(5000)
                except RuntimeError:
                    self.install_thread = None

                # Park prefix/config threads - disconnect their signals and let them
                # finish naturally rather than terminating unsafely.
                if hasattr(self, 'prefix_thread') and self.prefix_thread:
                    self.prefix_thread = self._park_thread(
                        self.prefix_thread,
                        ["progress_update", "workflow_complete", "error_occurred"],
                    )
                if hasattr(self, 'config_thread') and self.config_thread:
                    _ctx = getattr(self, 'context', None)
                    _appid = str(
                        getattr(self, '_current_appid', '')
                        or ((_ctx.get('appid', '') if isinstance(_ctx, dict) else '') or '')
                    )
                    try:
                        self.config_thread.requestInterruption()
                    except Exception:
                        pass
                    self._kill_prefix_wine_processes(_appid)
                    self.config_thread = self._park_thread(
                        self.config_thread,
                        ["progress_update", "configuration_complete", "error_occurred"],
                    )

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

            except Exception as e:
                logger.debug(f"ERROR: Exception during cancellation cleanup: {e}")
                import traceback
                traceback.print_exc()

            finally:
                # Always write cancellation message to console so detection works
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
        self.cleanup_processes()
        self.collapse_show_details_before_leave()
        self.go_back()
    
    def reset_screen_to_defaults(self):
        """Reset the screen to default state when navigating back from main menu"""
        # Reset form fields
        self.modlist_btn.setText("Select Modlist")
        self.modlist_btn.setEnabled(False)
        self.file_edit.setText("")
        self.modlist_name_edit.setText("")
        self.install_dir_edit.setText(self.config_handler.get_modlist_install_base_dir())
        # Reset game type button
        self.game_type_btn.setText("Please Select...")

        # Clear console and process monitor
        self.console.clear()
        self.process_monitor.clear()

        # Reset tabs to first tab (Online)
        self.source_tabs.setCurrentIndex(0)

        # Reset resolution combo to saved config preference
        saved_resolution = self.resolution_service.get_saved_resolution()
        if saved_resolution:
            combo_items = [self.resolution_combo.itemText(i) for i in range(self.resolution_combo.count())]
            resolution_index = self.resolution_service.get_resolution_index(saved_resolution, combo_items)
            self.resolution_combo.setCurrentIndex(resolution_index)
        elif self.resolution_combo.count() > 0:
            self.resolution_combo.setCurrentIndex(0)  # Fallback to "Leave unchanged"

        # Re-enable controls (in case they were disabled from previous errors)
        self._enable_controls_after_operation()

 
