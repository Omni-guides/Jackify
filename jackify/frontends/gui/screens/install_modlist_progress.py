"""Progress and installation event handlers for InstallModlistScreen (Mixin)."""
from PySide6.QtCore import QProcess, QTimer
from PySide6.QtWidgets import QMessageBox
from PySide6.QtGui import QTextCursor
from jackify.frontends.gui.services.message_service import MessageService
from jackify.shared.errors import wabbajack_install_failed
from jackify.shared.progress_models import InstallationPhase, OperationType, InstallationProgress, FileProgress
from jackify.backend.utils.nexus_premium_detector import is_non_premium_indicator
import time
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)
class ProgressHandlersMixin:
    """Mixin providing progress tracking and installation event handlers for InstallModlistScreen."""

    def on_installation_progress(self, progress_message):
        """
        Handle progress messages from installation thread.

        NOTE: This is called for MOST engine output, not just progress lines!
        The name is misleading - it's actually the main output path.
        """
        # Always write output to console buffer (same as on_installation_output)
        self._safe_append_text(progress_message)

    def on_premium_required_detected(self, engine_line: str):
        """Handle detection of Nexus Premium requirement."""
        if self._premium_notice_shown:
            return

        self._premium_notice_shown = True
        self._premium_failure_active = True

        user_message = (
            "Nexus Mods rejected the automated download because this account is not Premium. "
            "Jackify currently requires a Nexus Premium membership for automated installs, "
            "and non-premium support is still planned."
        )

        if engine_line:
            logger.warning(f"Nexus Premium required, engine message: {engine_line}")
            self._safe_append_text(f"[Jackify] Engine message: {engine_line}")
        logger.warning("Nexus Premium required for this modlist install")
        self._safe_append_text("[Jackify] Jackify detected that Nexus Premium is required for this modlist install.")

        MessageService.critical(
            self,
            "Nexus Premium Required",
            f"{user_message}\n\nDetected engine output:\n{engine_line or 'Buy Nexus Premium to automate this process.'}",
            safety_level="medium"
        )

        if hasattr(self, 'install_thread') and self.install_thread:
            self.install_thread.cancel()

    def on_non_premium_detected(self):
        """Gate the manual-download dialog until non-premium info has been acknowledged."""
        self._non_premium_gate_enabled = True
        self._non_premium_info_acknowledged = False
        logger.info("[MDL-1002] Non-premium flow detected; info dialog will show when manual downloads arrive")

    def _show_non_premium_info_dialog(self):
        """Show the non-premium information dialog. Blocks (nested event loop) until user clicks OK.

        Called from on_manual_download_list_received, so it only appears when files actually
        need manual downloading. The engine is paused waiting for a continue signal at that
        point, so process_finished will not fire and close the dialog prematurely.
        """
        from PySide6.QtCore import Qt
        if getattr(self, '_non_premium_info_dlg', None) is not None:
            return
        if getattr(self, '_non_premium_info_acknowledged', False):
            return

        box = QMessageBox(self)
        box.setWindowTitle("Non-Premium Account Detected")
        box.setIcon(QMessageBox.Information)
        box.setWindowModality(Qt.WindowModal)
        box.setTextFormat(Qt.RichText)
        box.setText(
            "<b>Jackify has detected that your Nexus account does not have Premium.</b>"
            "<br><br>"
            "The install will proceed in the following stages:"
            "<ol>"
            "<li>Automatically download any mods available from non-Nexus sources</li>"
            "<li>After you click OK here, open a manual download dialog listing all remaining manual archives</li>"
            "</ol>"
            "When your browser opens a Nexus page, click <b>\"Slow Download\"</b>."
            " For non-Nexus manual links, follow the site instructions shown in the page.<br><br>"
            "<b>Watch folder:</b> Jackify watches the folder shown in that dialog for newly downloaded files. "
            "Files detected there are validated and moved automatically into your modlist downloads folder - "
            "you do not need to move files manually. If your browser saves to a different location, "
            "please set the Watch Folder to that directory before starting the download of mod archives."
        )
        box.setStandardButtons(QMessageBox.Ok)
        self._non_premium_info_dlg = box
        box.exec()
        self._non_premium_info_dlg = None
        self._non_premium_info_acknowledged = True
        logger.info("[MDL-1003] Non-premium information dialog acknowledged by user")

    def on_progress_updated(self, progress_state):
        """R&D: Handle structured progress updates from parser"""
        # Calculate proper overall progress during BSA building
        # During BSA building, file installation is at 100% but BSAs are still being built
        # Override overall_percent to show BSA building progress instead
        if progress_state.bsa_building_total > 0 and progress_state.bsa_building_current > 0:
            bsa_percent = (progress_state.bsa_building_current / progress_state.bsa_building_total) * 100.0
            progress_state.overall_percent = min(99.0, bsa_percent)  # Cap at 99% until fully complete

        # Detect stalled downloads (0.0MB/s for extended period)
        # Catch silent token refresh failures or network issues
        # IMPORTANT: Only check during DOWNLOAD phase, not during VALIDATE phase
        # Validation checks existing files and shows 0.0MB/s, which is expected behavior
        if progress_state.phase == InstallationPhase.DOWNLOAD:
            speed_display = progress_state.get_overall_speed_display()
            # Check if speed is 0 or very low (< 0.1MB/s) for more than 2 minutes
            # Only trigger if we're actually in download phase (not validation)
            is_stalled = not speed_display or speed_display == "0.0B/s" or \
                        (speed_display and any(x in speed_display.lower() for x in ['0.0mb/s', '0.0kb/s', '0b/s']))
            
            # Additional check: Only consider it stalled if we have active download files
            # If no files are being downloaded, it might just be between downloads
            has_active_downloads = any(
                f.operation == OperationType.DOWNLOAD and not f.is_complete 
                for f in progress_state.active_files
            )
            
            if is_stalled and has_active_downloads:
                if self._stalled_download_start_time is None:
                    self._stalled_download_start_time = time.time()
                    self._stalled_data_snapshot = progress_state.data_processed
                elif progress_state.data_processed > self._stalled_data_snapshot:
                    # Bytes are advancing despite 0 speed readout - engine reporting lag, not a real stall
                    self._stalled_download_start_time = time.time()
                    self._stalled_data_snapshot = progress_state.data_processed
                else:
                    stalled_duration = time.time() - self._stalled_download_start_time
                    # Warn after 2 minutes of stalled downloads
                    if stalled_duration > 120 and not self._stalled_download_notified:
                        self._stalled_download_notified = True
                        logger.warning("Downloads stalled (0.0MB/s for 2+ minutes)")
                        MessageService.warning(
                            self,
                            "Download Stalled",
                            (
                                "Downloads have been stalled (0.0MB/s) for over 2 minutes.\n\n"
                                "Possible causes:\n"
                                "• OAuth token expired and refresh failed\n"
                                "• Network connectivity issues\n"
                                "• Nexus Mods server issues\n\n"
                                "Please check the console output (Show Details) for error messages.\n"
                                "If authentication failed, you may need to re-authorize in Settings."
                            ),
                            safety_level="low"
                        )
                        # Force console to be visible
                        if not self.show_details_checkbox.isChecked():
                            self.show_details_checkbox.setChecked(True)
                        # Add warning to console
                        self._safe_append_text(
                            "\n[Jackify] WARNING: Downloads have stalled (0.0MB/s for 2+ minutes)\n"
                            "[Jackify] This may indicate an authentication or network issue.\n"
                            "[Jackify] Check the console above for error messages.\n"
                        )
            else:
                # Downloads are active - reset stall timer
                self._stalled_download_start_time = None
                self._stalled_download_notified = False
                self._stalled_data_snapshot = 0

        # Update progress indicator widget
        self.progress_indicator.update_progress(progress_state)
        
        # Only show file progress list if console is not visible (mutually exclusive)
        console_visible = self.show_details_checkbox.isChecked()
        
        # Determine phase display name up front (short/stable label)
        phase_label = progress_state.get_phase_label()
        
        # During installation or extraction phase, show summary counter instead of individual files
        # Avoid cluttering UI with completed files
        is_installation_phase = (
            progress_state.phase == InstallationPhase.INSTALL or
            (progress_state.phase_name and 'install' in progress_state.phase_name.lower())
        )
        is_extraction_phase = (
            progress_state.phase == InstallationPhase.EXTRACT or
            (progress_state.phase_name and (
                'extract' in progress_state.phase_name.lower()
                or 'queu' in progress_state.phase_name.lower()
                or 'decompress' in progress_state.phase_name.lower()
            ))
        )
        
        # Detect BSA building phase - check multiple indicators
        is_bsa_building = False
        
        # Check phase name for BSA indicators
        if progress_state.phase_name:
            phase_lower = progress_state.phase_name.lower()
            if 'bsa' in phase_lower or ('building' in phase_lower and progress_state.phase == InstallationPhase.INSTALL):
                is_bsa_building = True
        
        # Check message/status text for BSA building indicators
        if not is_bsa_building and progress_state.message:
            msg_lower = progress_state.message.lower()
            if ('building' in msg_lower or 'writing' in msg_lower or 'verifying' in msg_lower) and '.bsa' in msg_lower:
                is_bsa_building = True
        
        # Check if we have BSA files being processed (even if they're at 100%, they indicate BSA phase)
        if not is_bsa_building and progress_state.active_files:
            bsa_files = [f for f in progress_state.active_files if f.filename.lower().endswith('.bsa')]
            if len(bsa_files) > 0:
                # If we have any BSA files and we're in INSTALL phase, likely BSA building
                if progress_state.phase == InstallationPhase.INSTALL:
                    is_bsa_building = True
        
        # Also check display text for BSA mentions (fallback)
        if not is_bsa_building:
            display_lower = progress_state.display_text.lower()
            if 'bsa' in display_lower and progress_state.phase == InstallationPhase.INSTALL:
                is_bsa_building = True
        
        now_mono = time.monotonic()
        if is_bsa_building:
            self._bsa_hold_deadline = now_mono + 1.5
        elif now_mono < self._bsa_hold_deadline:
            is_bsa_building = True
        else:
            self._bsa_hold_deadline = now_mono

        if is_installation_phase:
            self._stop_clf3_decompress_pulse()
            current_step = progress_state.phase_step
            phase_lower = (progress_state.phase_name or "").lower()

            if "bsa" in phase_lower:
                step_label = f"Building BSA: {current_step}/{progress_state.phase_max_steps}"
            elif "dds" in phase_lower or "texture" in phase_lower:
                step_label = f"Converting Textures: {current_step}/{progress_state.phase_max_steps}"
            elif "extract" in phase_lower or "queu" in phase_lower:
                step_label = f"Queuing Archives: {current_step}/{progress_state.phase_max_steps}"
            else:
                step_label = f"Installing Files: {current_step}/{progress_state.phase_max_steps}"

            display_items = []

            if current_step > 0 or progress_state.phase_max_steps > 0:
                install_line = FileProgress(
                    filename=step_label,
                    operation=OperationType.INSTALL,
                    percent=0.0,
                    speed=-1.0
                )
                install_line._no_progress_bar = True
                display_items.append(install_line)

            # Lines 2+: Show converting textures and BSA files
            # Extract and categorize active files
            for f in progress_state.active_files:
                if f.operation == OperationType.INSTALL:
                    if f.filename.lower().endswith('.bsa') or f.filename.lower().endswith('.ba2'):
                        # BSA: filename.bsa (42/89) - Use state-level BSA counter
                        if progress_state.bsa_building_total > 0:
                            display_filename = f"BSA: {f.filename} ({progress_state.bsa_building_current}/{progress_state.bsa_building_total})"
                        else:
                            display_filename = f"BSA: {f.filename}"

                        display_file = FileProgress(
                            filename=display_filename,
                            operation=f.operation,
                            percent=f.percent,
                            current_size=0,  # Don't show size
                            total_size=0,
                            speed=-1.0  # No speed
                        )
                        display_items.append(display_file)
                        if len(display_items) >= 4:  # Max 1 install line + 3 operations
                            break
                    elif f.filename.lower().endswith(('.dds', '.png', '.tga', '.bmp')):
                        # Converting Texture: filename.dds (234/1078)
                        # Use state-level texture counter (more reliable than file-level)
                        if progress_state.texture_conversion_total > 0:
                            display_filename = f"Converting Texture: {f.filename} ({progress_state.texture_conversion_current}/{progress_state.texture_conversion_total})"
                        else:
                            # No texture counter available, just show filename
                            display_filename = f"Converting Texture: {f.filename}"

                        display_file = FileProgress(
                            filename=display_filename,
                            operation=f.operation,
                            percent=f.percent,
                            current_size=0,  # Don't show size
                            total_size=0,
                            speed=-1.0  # No speed
                        )
                        display_items.append(display_file)
                        if len(display_items) >= 4:  # Max 1 install line + 3 operations
                            break

            # Update target state (render loop handles smooth display)
            # Explicitly pass None for summary_info to clear any stale summary data
            if display_items:
                self.file_progress_list.update_files(display_items, current_phase=phase_label or "Installing", summary_info=None)
            return
        elif is_extraction_phase:
            phase_lower = (progress_state.phase_name or "").lower()
            if 'decompress' in phase_lower:
                label = progress_state.message or "Decompressing archives..."
                self._clf3_decompress_label = label
                if not getattr(self, '_clf3_decompress_timer', None):
                    self._start_clf3_decompress_pulse(label)
            else:
                self._stop_clf3_decompress_pulse()
                current_step = progress_state.phase_step
                summary_info = {
                    'current_step': current_step,
                    'max_steps': progress_state.phase_max_steps,
                }
                phase_display_name = phase_label or "Queuing Archives"
                self.file_progress_list.update_files([], current_phase=phase_display_name, summary_info=summary_info)
            return
        elif progress_state.active_files:
            self._stop_clf3_decompress_pulse()
            # Pass phase label to update header (e.g., "[Activity - Downloading]")
            # Explicitly clear summary_info when showing file list
            try:
                self.file_progress_list.update_files(progress_state.active_files, current_phase=phase_label, summary_info=None)
            except RuntimeError as e:
                # Widget was deleted - ignore to prevent coredump
                if "already deleted" in str(e):
                    return
                raise
            except Exception as e:
                # Catch any other exceptions to prevent coredump
                import logging
                logging.getLogger(__name__).error(f"Error updating file progress list: {e}", exc_info=True)
        else:
            self._stop_clf3_decompress_pulse()
            # When there are no active files but phase progress counters are set (CLF3 streaming
            # pipeline: extraction runs inside the Downloading phase with no per-file events),
            # show a summary widget so the Activity tab is not blank.
            summary_info = None
            if progress_state.phase_step > 0 or progress_state.phase_max_steps > 0:
                summary_info = {
                    'current_step': progress_state.phase_step,
                    'max_steps': progress_state.phase_max_steps,
                }
            try:
                self.file_progress_list.update_files([], current_phase=phase_label, summary_info=summary_info)
            except RuntimeError as e:
                if "already deleted" in str(e):
                    return
                raise
            except Exception as e:
                logger.error(f"Error updating file progress list: {e}", exc_info=True)

    def _start_clf3_decompress_pulse(self, label: str = "Decompressing archives..."):
        self._clf3_decompress_label = label
        if not getattr(self, '_clf3_decompress_timer', None):
            self._clf3_decompress_timer = QTimer(self)
            self._clf3_decompress_timer.timeout.connect(self._clf3_decompress_heartbeat)
        self._clf3_decompress_timer.start(250)

    def _clf3_decompress_heartbeat(self):
        label = getattr(self, '_clf3_decompress_label', "Decompressing archives...")
        self.file_progress_list.update_or_add_item("__clf3_decompress__", label, 0.0)

    def _stop_clf3_decompress_pulse(self):
        timer = getattr(self, '_clf3_decompress_timer', None)
        if timer:
            timer.stop()
            self._clf3_decompress_timer = None
        self._clf3_decompress_label = None

    def _record_install_failure(self, failure_reason: str) -> None:
        """JackifyDB failure record - isolated try/except since a data-collection call must
        never affect the (already failing) install flow."""
        try:
            thread = getattr(self, 'install_thread', None)
            from jackify import __version__ as _jackify_version
            from jackify.backend.services.jackify_db import gather_environment_fields, record_event
            event = "update_completed" if getattr(self, "_is_update_install", False) else "install_completed"
            record_event(
                event, "failure",
                game_type=getattr(self, '_current_game_type', None),
                install_mode=getattr(thread, 'install_mode', 'online') if thread else None,
                jackify_version=_jackify_version, failure_phase="install",
                failure_reason=failure_reason,
                **gather_environment_fields(),
            )
        except Exception as e:
            logger.debug(f"JackifyDB failure record skipped: {e}")

    def on_installation_finished(self, success, message):
        """Handle installation completion"""
        self._stop_clf3_decompress_pulse()
        logger.debug(f"on_installation_finished called with success={success}, message={message}")
        # installation_finished is emitted from inside run() via a queued connection,
        # so run() may still be executing its finally block when this slot fires.
        # Destroying the thread object while run() is still on the stack causes
        # "QThread: Destroyed while thread is still running" / SIGABRT.
        thread = getattr(self, 'install_thread', None)
        if thread and thread.isRunning():
            thread.wait(3000)
        self.progress_state_manager.reset()
        # Clear file list but keep CPU tracking running for configuration phase
        self.file_progress_list.list_widget.clear()
        self.file_progress_list._file_items.clear()
        self.file_progress_list._summary_widget = None
        self.file_progress_list._transition_label = None
        self.file_progress_list._last_phase = None
        
        if success:
            # Update progress indicator with completion
            final_state = InstallationProgress(
                phase=InstallationPhase.FINALIZE,
                phase_name="Installation Complete",
                overall_percent=100.0
            )
            self.progress_indicator.update_progress(final_state)

            try:
                from jackify.backend.utils.modlist_meta import write_modlist_meta
                thread = getattr(self, 'install_thread', None)
                if thread and getattr(thread, 'install_dir', None) and getattr(thread, 'modlist_name', None):
                    modlist_version = None
                    machine_url = None
                    gallery_image_path = None
                    if getattr(thread, 'install_mode', 'online') == 'online':
                        info = getattr(self, 'selected_modlist_info', None) or {}
                        modlist_version = info.get('version')
                        machine_url = info.get('machine_url')
                        gallery_image_path = info.get('gallery_image_path')
                        if not modlist_version:
                            logger.warning(
                                "No version in selected_modlist_info for %r at install "
                                "completion (keys present: %s) - Dashboard will show Unknown "
                                "Version for this install.",
                                thread.modlist_name, list(info.keys()),
                            )
                    else:
                        # File-mode install: thread.modlist is the exact local .wabbajack path
                        # the user selected, so its own declared Version is ground truth -
                        # unlike a gallery lookup, which only ever knows the current public
                        # release, not what this specific archive was actually built from.
                        wabbajack_path = getattr(thread, 'modlist', None)
                        if wabbajack_path and str(wabbajack_path).endswith('.wabbajack') and os.path.isfile(wabbajack_path):
                            from jackify.backend.handlers.wabbajack_parser import WabbajackParser
                            modlist_version = WabbajackParser().parse_wabbajack_version(Path(wabbajack_path))
                    write_modlist_meta(
                        thread.install_dir,
                        thread.modlist_name,
                        getattr(self, '_current_game_type', None),
                        install_mode=getattr(thread, 'install_mode', 'online'),
                        modlist_version=modlist_version,
                    )
                    from jackify.backend.services.install_registry import register_install, compute_install_id
                    import datetime as _datetime
                    from jackify import __version__ as _jackify_version_for_registry
                    register_install(
                        thread.install_dir,
                        thread.modlist_name,
                        game_type=getattr(self, '_current_game_type', None),
                        installed_version=modlist_version,
                        machine_url=machine_url,
                        install_date=_datetime.datetime.now().isoformat(timespec="seconds"),
                        jackify_version=_jackify_version_for_registry,
                    )
                    if gallery_image_path:
                        try:
                            from jackify.backend.services.dashboard_images import save_image_from_path
                            save_image_from_path(compute_install_id(thread.install_dir), gallery_image_path)
                        except Exception as _img_err:
                            logger.debug(f"Dashboard image save skipped: {_img_err}")
                    from jackify import __version__ as _jackify_version
                    from jackify.backend.services.jackify_db import gather_environment_fields, record_event
                    event = "update_completed" if getattr(self, "_is_update_install", False) else "install_completed"
                    record_event(
                        event, "success",
                        modlist_name=thread.modlist_name, modlist_version=modlist_version,
                        game_type=getattr(self, '_current_game_type', None),
                        install_mode=getattr(thread, 'install_mode', 'online'),
                        jackify_version=_jackify_version,
                        **gather_environment_fields(),
                    )
            except Exception as _meta_err:
                logger.debug(f"Modlist meta write skipped: {_meta_err}")

            try:
                from jackify.backend.utils.clf3_postinstall import inject_mo2_download_dir
                if thread and getattr(thread, 'install_dir', None) and getattr(thread, 'downloads_dir', None):
                    inject_mo2_download_dir(thread.install_dir, thread.downloads_dir)
            except Exception as _ini_err:
                logger.debug(f"MO2 INI download_directory injection skipped: {_ini_err}")

            logger.info(f"Installation succeeded: {message}")
            if self.show_details_checkbox.isChecked():
                self._safe_append_text(f"\nSuccess: {message}")
            self.process_finished(0, QProcess.NormalExit)  # Simulate successful completion
        else:
            # Reset to initial state on failure
            self.progress_indicator.reset()
            cancellation_detected = (
                (isinstance(message, str) and "cancelled by user" in message.lower())
                or bool(getattr(self, '_cancellation_requested', False))
            )
            if cancellation_detected:
                self._installation_cancelled = True
                logger.info("Installation cancelled by user")
                if self.show_details_checkbox.isChecked():
                    self._safe_append_text("\nInstallation cancelled by user.")
                self._record_install_failure("user_cancelled")
                # Use a distinct non-success code and let process_finished route this
                # through the cancellation UX path (not failure path).
                self.process_finished(130, QProcess.NormalExit)
                return

            if self._premium_failure_active:
                message = "Installation stopped because Nexus Premium is required for automated downloads."

            if not self._premium_failure_active:
                engine_error = getattr(self.install_thread, 'last_error', None)
                if engine_error:
                    self._engine_error = engine_error
                self._failure_message = message

            logger.error(f"Installation failed: {message}")
            if self.show_details_checkbox.isChecked():
                self._safe_append_text(f"\nError: {message}")
            if self._premium_failure_active:
                failure_reason = "download_failed"
            elif getattr(self.install_thread, 'last_error', None):
                failure_reason = "engine_crash"
            else:
                failure_reason = "unknown"
            self._record_install_failure(failure_reason)
            self.process_finished(1, QProcess.CrashExit)  # Simulate error

    def process_finished(self, exit_code, exit_status):
        logger.debug(f"process_finished called with exit_code={exit_code}, exit_status={exit_status}")
        # Reset button states
        self.start_btn.setEnabled(True)
        self.cancel_btn.setVisible(True)
        self.cancel_install_btn.setVisible(False)
        logger.debug("Button states reset in process_finished")

        # Stop manual download manager if it is still running (e.g. install failed mid-phase)
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
        

        if exit_code == 0:
            if getattr(self, "_is_update_install", False):
                try:
                    install_dir = os.path.realpath(self.install_dir_edit.text().strip())
                    self._record_post_engine_ini_snapshot_and_diff(install_dir)
                except Exception as e:
                    logger.warning("Update mode: failed post-engine MO2 snapshot/diff: %s", e)
            # Check if this was an unsupported game
            game_type = getattr(self, '_current_game_type', None)
            game_name = getattr(self, '_current_game_name', None)
            
            if game_type and not self.wabbajack_parser.is_supported_game(game_type):
                # Show success message for unsupported games without post-install configuration
                MessageService.information(
                    self, "Modlist Install Complete!",
                    f"Modlist installation completed successfully!\n\n"
                    f"Note: Post-install configuration was skipped for unsupported game type: {game_name or game_type}\n\n"
                    f"You will need to manually configure Steam shortcuts and other post-install steps."
                )
                logger.warning(f"Post-install configuration skipped for unsupported game: {game_name or game_type}")
                self._safe_append_text(f"\nModlist installation completed successfully.")
                self._safe_append_text(f"\nWarning: Post-install configuration skipped for unsupported game: {game_name or game_type}")
            else:
                # Check if auto-restart is enabled
                auto_restart_enabled = hasattr(self, 'auto_restart_checkbox') and self.auto_restart_checkbox.isChecked()
                
                if auto_restart_enabled:
                    # Auto-accept Steam restart - proceed without dialog
                    logger.info("Auto-accepting Steam restart (unattended mode enabled)")
                    reply = QMessageBox.Yes  # Simulate user clicking Yes
                else:
                    # Show the normal install complete dialog for supported games
                    from jackify.shared.messages import STEAM_RESTART_WARNING
                    reply = MessageService.question(
                        self, "Modlist Install Complete!",
                        f"Modlist install complete!\n\nWould you like to add this modlist to Steam and configure it now? {STEAM_RESTART_WARNING}",
                        critical=False,  # Non-critical, won't steal focus
                        safety_level="medium",
                    )
                
                if reply == QMessageBox.Yes:
                    if getattr(self, "_is_update_install", False) and getattr(self, "_existing_shortcut_appid", None):
                        # Update workflow: reuse existing shortcut and skip shortcut creation/restart path.
                        modlist_name = self.modlist_name_edit.text().strip()
                        install_dir = os.path.realpath(self.install_dir_edit.text().strip())
                        self._safe_append_text(
                            f"Update mode: reusing existing Steam shortcut AppID {self._existing_shortcut_appid}."
                        )
                        try:
                            from jackify.backend.handlers.modlist_handler import ModlistHandler
                            _game_type = self._detect_game_type_from_mo2_ini(install_dir)
                            ModlistHandler().set_steam_grid_images(
                                str(self._existing_shortcut_appid), install_dir, game_type=_game_type
                            )
                        except Exception as _e:
                            logger.warning("Failed to apply Steam artwork on update install: %s", _e)
                        self.continue_configuration_after_automated_prefix(
                            self._existing_shortcut_appid,
                            modlist_name,
                            install_dir,
                            None,
                        )
                    else:
                        # New install workflow: create shortcut and run automated prefix flow.
                        self.start_automated_prefix_workflow()
                else:
                    # User selected "No" - show completion message and keep GUI open
                    self._safe_append_text("\nModlist installation completed successfully!")
                    self._safe_append_text("Note: You can manually configure Steam integration later if needed.")
                    MessageService.information(
                        self, "Installation Complete", 
                        "Modlist installation completed successfully!\n\n"
                        "The modlist has been installed but Steam integration was skipped.\n"
                        "You can manually add the modlist to Steam later if desired.",
                        safety_level="medium"
                    )
                    # Re-enable controls since operation is complete
                    self._enable_controls_after_operation()
        else:
            # Check for user cancellation first - check message parameter first, then console
            if self._premium_failure_active:
                MessageService.warning(
                    self,
                    "Nexus Premium Required",
                    "Jackify stopped the installation because Nexus Mods reported that this account is not Premium.\n\n"
                    "Automatic installs currently require Nexus Premium. Non-premium support is planned.",
                    safety_level="medium"
                )
                logger.warning("Install stopped: Nexus Premium required")
                self._safe_append_text("\nInstall stopped: Nexus Premium required.")
                self._premium_failure_active = False
            elif getattr(self, '_installation_cancelled', False):
                MessageService.information(self, "Installation Cancelled", "The installation was cancelled by the user.", safety_level="low")
                self._installation_cancelled = False
                self._cancellation_requested = False
            elif hasattr(self, '_cancellation_requested') and self._cancellation_requested:
                # User explicitly cancelled via cancel button
                MessageService.information(self, "Installation Cancelled", "The installation was cancelled by the user.", safety_level="low")
                self._cancellation_requested = False
            else:
                # Check console as fallback
                last_output = self.console.toPlainText()
                if "cancelled by user" in last_output.lower():
                    MessageService.information(self, "Installation Cancelled", "The installation was cancelled by the user.", safety_level="low")
                else:
                    engine_error = getattr(self, '_engine_error', None)
                    if engine_error:
                        self._engine_error = None
                        logger.error(
                            "Install failed | exit_code=%s error=%s",
                            exit_code,
                            engine_error.message,
                        )
                        MessageService.show_error(self, engine_error)
                        self._safe_append_text(f"\nInstall failed: {engine_error.message}")
                    else:
                        failure_msg = (
                            getattr(self, '_failure_message', None)
                            or "Install failed, but no specific error details were captured from engine output."
                        )
                        self._failure_message = None
                        logger.error(
                            "Install failed | exit_code=%s summary=%s",
                            exit_code,
                            failure_msg,
                        )
                        MessageService.show_error(
                            self,
                            wabbajack_install_failed(
                                failure_msg,
                                context={
                                    "operation": "install_modlist",
                                    "step": "engine_install",
                                    "exit_code": exit_code,
                                    "modlist_name": self.modlist_name_edit.text().strip(),
                                    "install_dir": self.install_dir_edit.text().strip(),
                                },
                            ),
                        )
                        self._safe_append_text(f"\nInstall failed: {failure_msg}")
        self.console.moveCursor(QTextCursor.End)
