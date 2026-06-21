"""
InstallModlistOutputMixin: handlers for InstallerThread signals.
on_installation_output, on_installation_progress, on_premium_required_detected, on_progress_updated.
"""

import time

from jackify.shared.progress_models import InstallationPhase, OperationType, FileProgress
import logging


logger = logging.getLogger(__name__)
class InstallModlistOutputMixin:
    """Mixin providing signal handlers for InstallerThread output/progress/premium/progress_updated."""

    def on_installation_output(self, message):
        """Handle regular output from installation thread."""
        if message.strip().startswith('[Jackify]'):
            self._write_to_log_file(message)
            return
        msg_lower = message.lower()
        if (
            'contains files with foreign characters' in msg_lower and
            'using proton 7z.exe for extraction' in msg_lower
        ):
            self._write_to_log_file(message)
            return
        token_error_keywords = [
            'token has expired', 'token expired', 'oauth token', 'authentication failed',
            'unauthorized', '401', '403', 'refresh token', 'authorization failed',
            'nexus.*premium.*required', 'premium.*required',
        ]
        is_token_error = any(keyword in msg_lower for keyword in token_error_keywords)
        if is_token_error:
            if not self._token_error_notified:
                self._token_error_notified = True
                from jackify.frontends.gui.services.message_service import MessageService
                engine_id = getattr(self, '_active_session_engine_id', None)
                if engine_id == 'clf3':
                    MessageService.critical(
                        self,
                        "CLF3 Authentication Error",
                        (
                            "CLF3 could not authenticate with Nexus Mods.\n\n"
                            "The CLF3 binary stores its own Nexus API key, which may have "
                            "expired or been revoked. Your Jackify OAuth is unaffected.\n\n"
                            "To fix: generate an API key at nexus.mods.com (account page), "
                            "then run in a terminal:\n\n"
                            "  clf3 set-api-key YOUR_KEY\n\n"
                            "OAuth support for CLF3 will be automatic after the next CLF3 release."
                        ),
                        safety_level="high"
                    )
                    guidance = (
                        "\n[Jackify] CLF3 auth failed. CLF3 uses its own saved Nexus API key "
                        "(not your Jackify OAuth). Run: clf3 set-api-key YOUR_KEY\n"
                    )
                else:
                    MessageService.critical(
                        self,
                        "Authentication Error",
                        (
                            "Nexus Mods authentication has failed. This may be due to:\n\n"
                            "• OAuth token expired and refresh failed\n"
                            "• Nexus Premium required for this modlist\n"
                            "• Network connectivity issues\n\n"
                            "Please check the console output (Show Details) for more information.\n"
                            "You may need to re-authorize in Settings."
                        ),
                        safety_level="high"
                    )
                    guidance = (
                        "\n[Jackify] CRITICAL: Authentication/Token Error Detected!\n"
                        "[Jackify] This may cause downloads to stop. Check the error message above.\n"
                        "[Jackify] If OAuth token expired, go to Settings and re-authorize.\n"
                    )
                self._safe_append_text(guidance)
                if not self.show_details_checkbox.isChecked():
                    self.show_details_checkbox.setChecked(True)
        if 'destination array was not long enough' in msg_lower or \
           ('argumentexception' in msg_lower and 'downloadmachineurl' in msg_lower):
            if not hasattr(self, '_array_error_notified'):
                self._array_error_notified = True
                guidance = (
                    "\n[Jackify] Engine Error Detected: Buffer size issue during .wabbajack download.\n"
                    "[Jackify] This is a known bug in jackify-engine 0.4.0.\n"
                    "[Jackify] Workaround: Delete any partial .wabbajack files in your downloads directory and try again.\n"
                )
                self._safe_append_text(guidance)
        self._safe_append_text(message)

    def on_installation_progress(self, progress_message):
        """Handle progress messages from installation thread (main output path)."""
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
            self._safe_append_text(f"[Jackify] Engine message: {engine_line}")
        self._safe_append_text("[Jackify] Jackify detected that Nexus Premium is required for this modlist install.")
        from jackify.frontends.gui.services.message_service import MessageService
        MessageService.critical(
            self,
            "Nexus Premium Required",
            f"{user_message}\n\nDetected engine output:\n{engine_line or 'Buy Nexus Premium to automate this process.'}",
            safety_level="medium"
        )
        if hasattr(self, 'install_thread') and self.install_thread:
            self.install_thread.cancel()

    def on_progress_updated(self, progress_state):
        """Handle structured progress updates from parser."""
        if progress_state.bsa_building_total > 0 and progress_state.bsa_building_current > 0:
            bsa_percent = (progress_state.bsa_building_current / progress_state.bsa_building_total) * 100.0
            progress_state.overall_percent = min(99.0, bsa_percent)
        if progress_state.phase == InstallationPhase.DOWNLOAD:
            speed_display = progress_state.get_overall_speed_display()
            is_stalled = not speed_display or speed_display == "0.0B/s" or \
                (speed_display and any(x in speed_display.lower() for x in ['0.0mb/s', '0.0kb/s', '0b/s']))
            has_active_downloads = any(
                f.operation == OperationType.DOWNLOAD and not f.is_complete
                for f in progress_state.active_files
            )
            if is_stalled and has_active_downloads:
                if self._stalled_download_start_time is None:
                    self._stalled_download_start_time = time.time()
                    self._stalled_data_snapshot = progress_state.data_processed
                elif progress_state.data_processed > self._stalled_data_snapshot:
                    self._stalled_download_start_time = time.time()
                    self._stalled_data_snapshot = progress_state.data_processed
                else:
                    stalled_duration = time.time() - self._stalled_download_start_time
                    if stalled_duration > 120 and not self._stalled_download_notified:
                        self._stalled_download_notified = True
                        from jackify.frontends.gui.services.message_service import MessageService
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
                        if not self.show_details_checkbox.isChecked():
                            self.show_details_checkbox.setChecked(True)
                        self._safe_append_text(
                            "\n[Jackify] WARNING: Downloads have stalled (0.0MB/s for 2+ minutes)\n"
                            "[Jackify] This may indicate an authentication or network issue.\n"
                            "[Jackify] Check the console above for error messages.\n"
                        )
            else:
                self._stalled_download_start_time = None
                self._stalled_download_notified = False
                self._stalled_data_snapshot = 0
        self.progress_indicator.update_progress(progress_state)
        phase_label = progress_state.get_phase_label()
        is_installation_phase = (
            progress_state.phase == InstallationPhase.INSTALL or
            (progress_state.phase_name and 'install' in progress_state.phase_name.lower())
        )
        is_extraction_phase = (
            progress_state.phase == InstallationPhase.EXTRACT or
            (progress_state.phase_name and 'extract' in progress_state.phase_name.lower())
        )
        is_bsa_building = False
        if progress_state.phase_name:
            phase_lower = progress_state.phase_name.lower()
            if 'bsa' in phase_lower or ('building' in phase_lower and progress_state.phase == InstallationPhase.INSTALL):
                is_bsa_building = True
        if not is_bsa_building and progress_state.message:
            msg_lower = progress_state.message.lower()
            if ('building' in msg_lower or 'writing' in msg_lower or 'verifying' in msg_lower) and '.bsa' in msg_lower:
                is_bsa_building = True
        if not is_bsa_building and progress_state.active_files:
            bsa_files = [f for f in progress_state.active_files if f.filename.lower().endswith('.bsa')]
            if bsa_files and progress_state.phase == InstallationPhase.INSTALL:
                is_bsa_building = True
        if not is_bsa_building:
            display_text = getattr(progress_state, 'display_text', None) or ''
            if 'bsa' in display_text.lower() and progress_state.phase == InstallationPhase.INSTALL:
                is_bsa_building = True
        now_mono = time.monotonic()
        if is_bsa_building:
            self._bsa_hold_deadline = now_mono + 1.5
        elif now_mono < self._bsa_hold_deadline:
            is_bsa_building = True
        else:
            self._bsa_hold_deadline = now_mono
        if is_installation_phase:
            current_step = progress_state.phase_step
            display_items = []
            if current_step > 0 or progress_state.phase_max_steps > 0:
                install_line = FileProgress(
                    filename=f"Installing Files: {current_step}/{progress_state.phase_max_steps}",
                    operation=OperationType.INSTALL, percent=0.0, speed=-1.0
                )
                install_line._no_progress_bar = True
                display_items.append(install_line)
            for f in progress_state.active_files:
                if f.operation == OperationType.INSTALL:
                    if f.filename.lower().endswith('.bsa') or f.filename.lower().endswith('.ba2'):
                        display_filename = f"BSA: {f.filename} ({progress_state.bsa_building_current}/{progress_state.bsa_building_total})" if progress_state.bsa_building_total > 0 else f"BSA: {f.filename}"
                        display_file = FileProgress(filename=display_filename, operation=f.operation, percent=f.percent, current_size=0, total_size=0, speed=-1.0)
                        display_items.append(display_file)
                        if len(display_items) >= 4:
                            break
                    elif f.filename.lower().endswith(('.dds', '.png', '.tga', '.bmp')):
                        display_filename = f"Converting Texture: {f.filename} ({progress_state.texture_conversion_current}/{progress_state.texture_conversion_total})" if progress_state.texture_conversion_total > 0 else f"Converting Texture: {f.filename}"
                        display_file = FileProgress(filename=display_filename, operation=f.operation, percent=f.percent, current_size=0, total_size=0, speed=-1.0)
                        display_items.append(display_file)
                        if len(display_items) >= 4:
                            break
            if display_items:
                self.file_progress_list.update_files(display_items, current_phase="Installing", summary_info=None)
            return
        if is_extraction_phase:
            current_step = progress_state.phase_step
            summary_info = {'current_step': current_step, 'max_steps': progress_state.phase_max_steps}
            phase_display_name = phase_label or "Extracting"
            self.file_progress_list.update_files([], current_phase=phase_display_name, summary_info=summary_info)
            return
        if progress_state.active_files:
            try:
                self.file_progress_list.update_files(progress_state.active_files, current_phase=phase_label, summary_info=None)
            except RuntimeError as e:
                if "already deleted" in str(e):
                    if getattr(self, 'debug', False):
                        logger.debug(f"Ignoring widget deletion error: {e}")
                    return
                raise
            except Exception as e:
                if getattr(self, 'debug', False):
                    logger.debug(f"Error updating file progress list: {e}")
                import logging
                logging.getLogger(__name__).error(f"Error updating file progress list: {e}", exc_info=True)
        else:
            try:
                self.file_progress_list.update_files([], current_phase=phase_label)
            except RuntimeError as e:
                if "already deleted" in str(e):
                    return
                raise
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Error updating file progress list: {e}", exc_info=True)
