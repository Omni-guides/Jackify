"""Workflow management for ConfigureExistingModlistScreen (Mixin)."""
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QMessageBox
import os
import time
import logging
from pathlib import Path

from jackify.shared.resolution_utils import get_resolution_fallback
from jackify.shared.errors import configuration_failed

logger = logging.getLogger(__name__)

class ConfigureExistingModlistWorkflowMixin:
    """Mixin providing workflow management for ConfigureExistingModlistScreen."""

    def _detect_game_type_from_mo2_ini(self, install_dir: str) -> str:
        """Detect game type for the verifier from ModOrganizer.ini."""
        try:
            from jackify.backend.handlers.modlist_handler import ModlistHandler
            special = ModlistHandler().detect_special_game_type(install_dir)
            if special:
                return special
        except Exception as e:
            logger.warning("Special game type detection failed: %s", e)

        # detect_special_game_type only covers non-default games; read gameName= directly
        try:
            from pathlib import Path
            mo2_ini = Path(install_dir) / "ModOrganizer.ini"
            if mo2_ini.exists():
                for raw_line in mo2_ini.read_text(errors='ignore').splitlines():
                    line = raw_line.strip().lower()
                    if line.startswith("gamename="):
                        val = line[len("gamename="):]
                        if "fallout 4" in val:
                            return "fallout4"
                        if "skyrim" in val:
                            return "skyrim"
        except Exception as e:
            logger.warning("ModOrganizer.ini gameName read failed: %s", e)

        logger.warning("Could not determine game type for %s, verifier will run generic checks only", install_dir)
        return 'unknown'

    def validate_and_start_configure(self):
        # Reload config to pick up any settings changes made in Settings dialog
        self.config_handler.reload_config()

        # Rotate log file at start of each workflow run (keep 5 backups)
        from jackify.backend.handlers.logging_handler import LoggingHandler
        from pathlib import Path
        log_handler = LoggingHandler()
        log_handler.rotate_log_file_per_run(Path(self.modlist_log_path), backup_count=5)

        # Initialize progress indicator
        self.progress_indicator.set_status("Preparing to configure...", 0)

        # Start CPU tracking
        self.file_progress_list.start_cpu_tracking()

        # Disable controls during configuration
        self._disable_controls_during_operation()
        
        # Get selected shortcut
        idx = self.shortcut_combo.currentIndex() - 1  # Account for 'Please Select...'
        from jackify.frontends.gui.services.message_service import MessageService
        if idx < 0 or idx >= len(self.shortcut_map):
            MessageService.critical(self, "No Shortcut Selected", "Please select a ModOrganizer.exe Steam shortcut to configure.", safety_level="medium")
            self._enable_controls_after_operation()
            return
        shortcut = self.shortcut_map[idx]
        modlist_name = shortcut.get('AppName', shortcut.get('appname', ''))
        install_dir = shortcut.get('StartDir', shortcut.get('startdir', ''))
        if not modlist_name or not install_dir:
            MessageService.critical(self, "Invalid Shortcut", "The selected shortcut is missing required information.", safety_level="medium")
            self._enable_controls_after_operation()
            return
        raw_appid = shortcut.get('AppID', shortcut.get('appid', ''))
        self._current_appid = str(raw_appid) if raw_appid != '' else ''
        resolution = self.resolution_combo.currentText()
        # Handle resolution saving
        if resolution and resolution != "Leave unchanged":
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
        # Start the workflow (no shortcut creation needed)
        self.start_workflow(modlist_name, install_dir, resolution)

    def start_workflow(self, modlist_name, install_dir, resolution):
        """Start the configuration workflow using backend service directly"""
        # CRITICAL: Reload config from disk to pick up any settings changes from Settings dialog
        # Refresh Proton version and winetricks settings
        self.config_handler._load_config()

        # Store install_dir for later use in on_configuration_complete
        self._current_install_dir = install_dir

        try:
            # Start time tracking
            self._workflow_start_time = time.time()

            from jackify import __version__ as jackify_version
            self._safe_append_text(f"Jackify v{jackify_version}")
            self._safe_append_text("[Jackify] Starting post-install configuration...")
            
            # Create configuration thread using backend service
            from PySide6.QtCore import QThread, Signal
            from jackify.backend.models.configuration import SystemInfo
            from jackify.backend.services.platform_detection_service import PlatformDetectionService
            
            # Capture parent's method and create system_info
            detect_game_type_func = self._detect_game_type_from_mo2_ini
            platform_service = PlatformDetectionService.get_instance()
            parent_system_info = SystemInfo(is_steamdeck=platform_service.is_steamdeck)
            
            class ConfigurationThread(QThread):
                progress_update = Signal(str)
                configuration_complete = Signal(bool, str, str, bool)
                error_occurred = Signal(str)
                steam_restart_needed = Signal(str, str, str)  # app_name, exe_path, dl_path
                
                def __init__(self, modlist_name, install_dir, resolution, system_info, detect_func):
                    super().__init__()
                    self.modlist_name = modlist_name
                    self.install_dir = install_dir
                    self.resolution = resolution
                    self.system_info = system_info
                    self.detect_game_type = detect_func
                    
                def run(self):
                    try:
                        from jackify.backend.services.modlist_service import ModlistService
                        from jackify.backend.models.modlist import ModlistContext
                        from pathlib import Path
                        import os
                        
                        # Initialize backend service
                        modlist_service = ModlistService(self.system_info)
                        
                        # Detect game type from ModOrganizer.ini using captured function
                        detected_game_type = self.detect_game_type(self.install_dir)
                        
                        # Create modlist context for existing modlist configuration
                        mo2_exe_path = os.path.join(self.install_dir, "ModOrganizer.exe")
                        from jackify.backend.services.nxm_downloader import resolve_mo2_download_dir
                        modlist_context = ModlistContext(
                            name=self.modlist_name,
                            install_dir=Path(self.install_dir),
                            download_dir=resolve_mo2_download_dir(Path(self.install_dir)),
                            game_type=detected_game_type,
                            nexus_api_key='',  # Not needed for configuration-only
                            modlist_value='',  # Not needed for existing modlist
                            modlist_source='existing',
                            skip_confirmation=True
                        )
                        
                        # For existing modlists, add resolution if specified
                        if self.resolution != "Leave unchanged":
                            modlist_context.resolution = self.resolution.split()[0]
                        # If "Leave unchanged" selected, resolution stays None
                        
                        # Define callbacks
                        def progress_callback(message):
                            self.progress_update.emit(message)

                        # Store completion args rather than emitting immediately so we can
                        # emit steam_restart_needed first when a restart is required.
                        completion_args = [None]

                        def completion_callback(success, message, modlist_name, enb_detected=False):
                            completion_args[0] = (success, message, modlist_name, enb_detected)

                        self.progress_update.emit("Starting existing modlist configuration...")
                        success = modlist_service.configure_modlist_post_steam(
                            context=modlist_context,
                            progress_callback=progress_callback,
                            completion_callback=completion_callback
                        )

                        if getattr(modlist_context, 'steam_restart_needed', False):
                            self.steam_restart_needed.emit(
                                getattr(modlist_context, 'mounts_app_name', ''),
                                getattr(modlist_context, 'mounts_exe_path', ''),
                                getattr(modlist_context, 'mounts_dl_path', ''),
                            )

                        if completion_args[0] is not None:
                            self.configuration_complete.emit(*completion_args[0])

                        if not success:
                            self.error_occurred.emit(
                                "Configuration did not complete successfully. "
                                "Review the latest workflow output above for the failing step."
                            )
                            
                    except Exception as e:
                        import traceback
                        error_msg = f"Configuration error: {e}\n{traceback.format_exc()}"
                        self.error_occurred.emit(error_msg)
            
            # Create and start the configuration thread
            self.config_thread = ConfigurationThread(modlist_name, install_dir, resolution, parent_system_info, detect_game_type_func)
            self.config_thread.progress_update.connect(self._handle_progress_update)
            self.config_thread.configuration_complete.connect(self.on_configuration_complete)
            self.config_thread.error_occurred.connect(self.on_configuration_error)
            self.config_thread.steam_restart_needed.connect(self._on_steam_restart_needed)  # (app_name, exe_path, dl_path)
            self.config_thread.start()
            
        except Exception as e:
            self._safe_append_text(f"[ERROR] Failed to start configuration: {e}")
            MessageService.show_error(self, configuration_failed(str(e)))

    def _on_steam_restart_needed(self, app_name: str, exe_path: str, dl_path: str):
        """Prompt before stopping Steam to write a deferred STEAM_COMPAT_MOUNTS update.

        Receives the shortcut identity and path from the signal so it can call
        ensure_mounts_in_steam_compat on the GUI's ShortcutHandler (not the backend's).

        Sets _awaiting_steam_restart before showing the dialog so that
        on_configuration_complete (fired by the nested event loop during exec())
        defers the success/ENB dialogs until after this handler finishes.
        """
        from PySide6.QtWidgets import QMessageBox
        from jackify.frontends.gui.services.message_service import MessageService
        self._awaiting_steam_restart = True
        try:
            reply = MessageService.question(
                self,
                "Restart Steam?",
                "The download directory mount needs to be added to STEAM_COMPAT_MOUNTS for this "
                "modlist. Steam must be stopped to write this change safely.\n\n"
                "Any running game will be closed. Do you want Jackify to restart Steam now?",
                safety_level="medium",
            )
            if reply == QMessageBox.No:
                logger.info("User declined Steam restart; STEAM_COMPAT_MOUNTS update skipped")
            else:
                try:
                    from jackify.backend.services.steam_restart_service import shutdown_steam, start_steam
                    shutdown_steam()
                    self.shortcut_handler.ensure_mounts_in_steam_compat(app_name, exe_path, dl_path)
                    start_steam()
                except Exception as e:
                    logger.warning("Steam restart/mounts update failed: %s", e)
        finally:
            self._awaiting_steam_restart = False
            if hasattr(self, '_deferred_completion_args') and self._deferred_completion_args is not None:
                args = self._deferred_completion_args
                self._deferred_completion_args = None
                from PySide6.QtCore import QTimer
                QTimer.singleShot(0, lambda: self.on_configuration_complete(*args))

    def _check_and_run_vnv_automation(self, modlist_name: str, install_dir: str) -> bool:
        """Check if VNV automation should run and start it if applicable.

        Returns:
            True if VNV automation is starting (caller should defer success dialog)
            False if no VNV needed (show success dialog immediately)
        """
        from ..services.vnv_automation_controller import VNVAutomationController

        self._vnv_controller = VNVAutomationController()
        return self._vnv_controller.attempt(
            parent=self,
            modlist_name=modlist_name,
            install_dir=install_dir,
            on_progress=self._safe_append_text,
            on_complete=self._on_vnv_complete,
            begin_feedback=self._begin_post_install_feedback,
            handle_feedback=self._handle_post_install_progress,
        )

    def _on_vnv_complete(self, success: bool, error: str):
        """Handle VNV automation completion and show deferred success dialog."""
        self._end_post_install_feedback(not bool(error))
        if not success and error:
            from ..services.message_service import MessageService
            MessageService.warning(
                self,
                "VNV Automation Failed",
                f"VNV post-install automation encountered an error:\n\n{error}\n\n"
                "You can complete these steps manually by following the guide at:\n"
                "https://vivanewvegas.moddinglinked.com/wabbajack.html"
            )
        elif success:
            self._safe_append_text("VNV post-install automation completed successfully.")

        if hasattr(self, '_pending_success_dialog_params'):
            params = self._pending_success_dialog_params
            del self._pending_success_dialog_params
            self._run_verifier_then_show_success(
                install_dir=params.get('install_dir', ''),
                game_type=params.get('game_type', 'unknown'),
                appid=params.get('appid', ''),
                success_params={
                    'modlist_name': params['modlist_name'],
                    'workflow_type': params['workflow_type'],
                    'time_taken': params['time_taken'],
                    'game_name': params.get('game_name'),
                    'enb_detected': params.get('enb_detected', False),
                },
            )

    def _check_and_run_mew_automation(self, modlist_name: str, install_dir: str) -> bool:
        """Check if MEW automation should run and start it if applicable.

        Returns:
            True if MEW automation is starting (caller should defer success dialog)
            False if no MEW needed (show success dialog immediately)
        """
        from ..services.mew_automation_controller import MEWAutomationController

        self._mew_controller = MEWAutomationController()
        return self._mew_controller.attempt(
            parent=self,
            modlist_name=modlist_name,
            install_dir=install_dir,
            appid=getattr(self, '_current_appid', None),
            on_progress=self._safe_append_text,
            on_complete=self._on_mew_complete,
            begin_feedback=self._begin_post_install_feedback,
            handle_feedback=self._handle_post_install_progress,
        )

    def _on_mew_complete(self, success: bool, error: str):
        """Handle MEW automation completion and show deferred success dialog."""
        self._end_post_install_feedback(not bool(error))
        if not success and error:
            from ..services.message_service import MessageService
            MessageService.warning(
                self,
                "MEW Automation Failed",
                f"MEW post-install automation encountered an error:\n\n{error}\n\n"
                "You can complete these steps manually by following the guide at:\n"
                "https://mojaveexpressguide.com/docs/Installation"
            )
        elif success:
            self._safe_append_text("MEW post-install automation completed successfully.")

        if hasattr(self, '_pending_success_dialog_params'):
            params = self._pending_success_dialog_params
            del self._pending_success_dialog_params
            self._run_verifier_then_show_success(
                install_dir=params.get('install_dir', ''),
                game_type=params.get('game_type', 'unknown'),
                appid=params.get('appid', ''),
                success_params={
                    'modlist_name': params['modlist_name'],
                    'workflow_type': params['workflow_type'],
                    'time_taken': params['time_taken'],
                    'game_name': params.get('game_name'),
                    'enb_detected': params.get('enb_detected', False),
                },
            )

    def show_manual_steps_dialog(self, extra_warning=""):
        modlist_name = self.shortcut_combo.currentText().split('(')[0].strip() or "your modlist"
        msg = (
            f"<b>Manual Proton Setup Required for <span style='color:#3fd0ea'>{modlist_name}</span></b><br>"
            "After Steam restarts, complete the following steps in Steam:<br>"
            f"1. Locate the '<b>{modlist_name}</b>' entry in your Steam Library<br>"
            "2. Right-click and select 'Properties'<br>"
            "3. Switch to the 'Compatibility' tab<br>"
            "4. Check the box labeled 'Force the use of a specific Steam Play compatibility tool'<br>"
            "5. Select 'Proton - Experimental' from the dropdown menu<br>"
            "6. Close the Properties window<br>"
            f"7. Launch '<b>{modlist_name}</b>' from your Steam Library<br>"
            "8. Wait for Wabbajack to download its files and fully load<br>"
            "9. Once Wabbajack has fully loaded, CLOSE IT completely and return here<br>"
            "<br>Once you have completed ALL the steps above, click OK to continue."
            f"{extra_warning}"
        )
        reply = MessageService.question(self, "Manual Steps Required", msg, safety_level="medium")
        if reply == QMessageBox.Yes:
            if self.config_process and self.config_process.state() == QProcess.Running:
                self.config_process.write(b'\n')
                self.config_process.waitForBytesWritten(1000)
            self._config_prompt_state = None
            self._manual_steps_buffer = []
        else:
            # User clicked Cancel or closed the dialog - cancel the workflow
            self._safe_append_text("\nManual steps cancelled by user. Workflow stopped.")
            # Terminate the configuration process
            if self.config_process and self.config_process.state() == QProcess.Running:
                self.config_process.terminate()
                self.config_process.waitForFinished(2000)
            # Re-enable all controls
            self._enable_controls_after_operation()
            self.cancel_btn.setVisible(True)

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
                self.stacked_widget.setCurrentIndex(0)
        def on_exit():
            QApplication.quit()
        btn_return.clicked.connect(on_return)
        btn_exit.clicked.connect(on_exit)
        dlg.exec()

    def refresh_modlist_list(self):
        """Refresh the modlist dropdown by re-detecting ModOrganizer.exe shortcuts (async)"""
        # Use async loading to avoid blocking UI
        self._shortcuts_loaded = False  # Allow reload
        self._load_shortcuts_async() 

    def _calculate_time_taken(self) -> str:
        """Calculate and format the time taken for the workflow"""
        if self._workflow_start_time is None:
            return "unknown time"
        
        elapsed_seconds = time.time() - self._workflow_start_time
        elapsed_minutes = int(elapsed_seconds // 60)
        elapsed_seconds_remainder = int(elapsed_seconds % 60)
        
        if elapsed_minutes > 0:
            if elapsed_minutes == 1:
                return f"{elapsed_minutes} minute {elapsed_seconds_remainder} seconds"
            else:
                return f"{elapsed_minutes} minutes {elapsed_seconds_remainder} seconds"
        else:
            return f"{elapsed_seconds_remainder} seconds"
