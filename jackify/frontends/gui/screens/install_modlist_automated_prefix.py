"""Automated prefix workflow handlers for InstallModlistScreen (Mixin)."""
from PySide6.QtCore import QThread, Signal, Qt, QTimer
from PySide6.QtWidgets import QProgressDialog, QMainWindow
from jackify.frontends.gui.services.message_service import MessageService
from jackify.backend.services.automated_prefix_service import AutomatedPrefixService
from pathlib import Path
import traceback
import threading
import subprocess
import time
import os
import logging

logger = logging.getLogger(__name__)
class AutomatedPrefixHandlersMixin:
    """Mixin providing automated prefix workflow event handlers for InstallModlistScreen."""

    def start_automated_prefix_workflow(self):
        """Start the automated prefix creation workflow"""
        # Reload config from disk to pick up any settings changes from Settings dialog
        # Refresh Proton version and winetricks settings
        self.config_handler._load_config()

        # Ensure _current_resolution is always set before starting workflow
        if not hasattr(self, '_current_resolution') or self._current_resolution is None:
            resolution = self.resolution_combo.currentText() if hasattr(self, 'resolution_combo') else None
            # Extract resolution properly (e.g., "1280x800" from "1280x800 (Steam Deck)")
            if resolution and resolution != "Leave unchanged":
                if " (" in resolution:
                    self._current_resolution = resolution.split(" (")[0]
                else:
                    self._current_resolution = resolution
            else:
                self._current_resolution = None

        try:
            # Disable controls during installation
            self._disable_controls_during_operation()
            modlist_name = self.modlist_name_edit.text().strip()
            install_dir = os.path.realpath(self.install_dir_edit.text().strip())
            final_exe_path = os.path.join(install_dir, "ModOrganizer.exe")
            
            if not os.path.exists(final_exe_path):
                # Check if this is Somnium specifically (uses files/ subdirectory)
                modlist_name_lower = modlist_name.lower()
                if "somnium" in modlist_name_lower:
                    somnium_exe_path = os.path.join(install_dir, "files", "ModOrganizer.exe")
                    if os.path.exists(somnium_exe_path):
                        final_exe_path = somnium_exe_path
                        self._safe_append_text(f"Detected Somnium modlist - will proceed with automated setup")
                        # Show Somnium guidance popup after automated workflow completes
                        self._show_somnium_guidance = True
                        self._somnium_install_dir = install_dir
                    else:
                        self._safe_append_text(f"ERROR: Somnium ModOrganizer.exe not found at {somnium_exe_path}")
                        MessageService.critical(self, "Somnium ModOrganizer.exe Not Found", 
                            f"Expected Somnium ModOrganizer.exe not found at:\n{somnium_exe_path}\n\nCannot proceed with automated setup.")
                        return
                else:
                    self._safe_append_text(f"ERROR: ModOrganizer.exe not found at {final_exe_path}")
                    MessageService.critical(self, "ModOrganizer.exe Not Found", 
                        f"ModOrganizer.exe not found at:\n{final_exe_path}\n\nCannot proceed with automated setup.")
                    return
            
            self._begin_post_install_feedback()

            # Run automated prefix creation in separate thread
            class AutomatedPrefixThread(QThread):
                finished = Signal(bool, str, str, str)  # success, prefix_path, appid (as string), last_timestamp
                progress = Signal(str)  # progress messages
                error = Signal(object)  # error (JackifyError or str)
                show_progress_dialog = Signal(str)  # show progress dialog with message
                hide_progress_dialog = Signal()  # hide progress dialog
                conflict_detected = Signal(list)  # conflicts list
                
                def __init__(self, modlist_name, install_dir, final_exe_path, downloads_dir=None):
                    super().__init__()
                    self.modlist_name = modlist_name
                    self.install_dir = install_dir
                    self.final_exe_path = final_exe_path
                    self.downloads_dir = downloads_dir

                def run(self):
                    try:
                        def progress_callback(message):
                            self.progress.emit(message)
                            # Show progress dialog during Steam restart
                            if "Steam restarted successfully" in message:
                                self.hide_progress_dialog.emit()
                            elif "Restarting Steam..." in message:
                                self.show_progress_dialog.emit("Restarting Steam...")
                        
                        prefix_service = AutomatedPrefixService()
                        # Determine Steam Deck once and pass through the workflow
                        try:
                            _is_steamdeck = False
                            if os.path.exists('/etc/os-release'):
                                with open('/etc/os-release') as f:
                                    if 'steamdeck' in f.read().lower():
                                        _is_steamdeck = True
                        except Exception:
                            _is_steamdeck = False
                        result = prefix_service.run_working_workflow(
                            self.modlist_name, self.install_dir, self.final_exe_path, progress_callback,
                            steamdeck=_is_steamdeck, download_dir=self.downloads_dir
                        )
                        
                        # Handle the result - check for conflicts
                        if isinstance(result, tuple) and len(result) == 4:
                            if result[0] == "CONFLICT":
                                # Conflict detected - emit signal to main GUI
                                conflicts = result[1]
                                self.hide_progress_dialog.emit()
                                self.conflict_detected.emit(conflicts)
                                return
                            else:
                                # Normal result with timestamp
                                success, prefix_path, new_appid, last_timestamp = result
                        elif isinstance(result, tuple) and len(result) == 3:
                            # Fallback for old format (backward compatibility)
                            if result[0] == "CONFLICT":
                                # Conflict detected - emit signal to main GUI
                                conflicts = result[1]
                                self.hide_progress_dialog.emit()
                                self.conflict_detected.emit(conflicts)
                                return
                            else:
                                # Normal result (old format)
                                success, prefix_path, new_appid = result
                                last_timestamp = None
                        else:
                            # Handle non-tuple result
                            success = result
                            prefix_path = ""
                            new_appid = "0"
                            last_timestamp = None
                        
                        # Ensure progress dialog is hidden when workflow completes
                        self.hide_progress_dialog.emit()
                        self.finished.emit(success, prefix_path or "", str(new_appid) if new_appid else "0", last_timestamp)
                        
                    except Exception as e:
                        # Ensure progress dialog is hidden on error
                        self.hide_progress_dialog.emit()
                        from jackify.shared.errors import JackifyError, prefix_creation_failed
                        if not isinstance(e, JackifyError):
                            e = prefix_creation_failed(str(e))
                        self.error.emit(e)
            
            # Create and start thread (pass downloads_dir for STEAM_COMPAT_MOUNTS)
            _dl_raw = self.downloads_dir_edit.text().strip() if getattr(self, 'downloads_dir_edit', None) else None
            downloads_dir = os.path.realpath(_dl_raw) if _dl_raw else None
            self.prefix_thread = AutomatedPrefixThread(modlist_name, install_dir, final_exe_path, downloads_dir)
            self.prefix_thread.finished.connect(self.on_automated_prefix_finished)
            self.prefix_thread.error.connect(self.on_automated_prefix_error)
            self.prefix_thread.progress.connect(self.on_automated_prefix_progress)
            self.prefix_thread.show_progress_dialog.connect(self.show_steam_restart_progress)
            self.prefix_thread.hide_progress_dialog.connect(self.hide_steam_restart_progress)
            self.prefix_thread.conflict_detected.connect(self.show_shortcut_conflict_dialog)
            self.prefix_thread.start()
            
        except Exception as e:
            logger.debug(f"Exception in start_automated_prefix_workflow: {e}")
            self._safe_append_text(f"ERROR: Failed to start automated workflow: {e}")
            self._enable_controls_after_operation()
            self.cancel_btn.setVisible(True)
            self.cancel_install_btn.setVisible(False)

    def on_automated_prefix_finished(self, success, prefix_path, new_appid_str, last_timestamp=None):
        """Handle completion of automated prefix creation"""
        try:
            if success:
                logger.debug(f"SUCCESS: Automated prefix creation completed!")
                logger.debug(f"Prefix created at: {prefix_path}")
                if new_appid_str and new_appid_str != "0":
                    logger.debug(f"AppID: {new_appid_str}")
                
                # Convert string AppID back to integer for configuration
                new_appid = int(new_appid_str) if new_appid_str and new_appid_str != "0" else None
                
                # Continue with configuration using the new AppID and timestamp
                modlist_name = self.modlist_name_edit.text().strip()
                install_dir = os.path.realpath(self.install_dir_edit.text().strip())
                self.continue_configuration_after_automated_prefix(new_appid, modlist_name, install_dir, last_timestamp)
            else:
                error_reason = last_timestamp or "Unknown error"
                self._safe_append_text(f"ERROR: Automated prefix creation failed: {error_reason}")
                from jackify.shared.errors import prefix_creation_failed
                MessageService.show_error(self, prefix_creation_failed(str(error_reason)))
                # Re-enable controls on failure
                self._enable_controls_after_operation()
                self._end_post_install_feedback(success=False)
        finally:
            # Always ensure controls are re-enabled when workflow truly completes
            pass

    def on_automated_prefix_error(self, error):
        """Handle error in automated prefix creation"""
        from jackify.shared.errors import JackifyError, classify_exception
        if not isinstance(error, JackifyError):
            error = classify_exception(str(error))
        logger.error(f"Automated prefix error: {error.message}")
        self._safe_append_text(f"[FAILED] {error.message}")
        MessageService.show_error(self, error)
        self._enable_controls_after_operation()
        self._end_post_install_feedback(success=False)

    def on_automated_prefix_progress(self, progress_msg):
        """Handle progress updates from automated prefix creation"""
        self._safe_append_text(progress_msg)
        self._handle_post_install_progress(progress_msg)

