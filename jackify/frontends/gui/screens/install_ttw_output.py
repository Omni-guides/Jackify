"""TTW output processing mixin for InstallTTWScreen."""
import re
import time

from ..utils import strip_ansi_control_codes


class TTWOutputMixin:
    """Mixin providing output and progress signal handlers for InstallTTWScreen."""

    def on_installation_output_batch(self, messages):
        """Handle batched output from TTW_Linux_Installer (pre-cleaned in worker thread)."""
        if not hasattr(self, '_ttw_seen_lines'):
            self._ttw_seen_lines = set()
            self._ttw_current_phase = None
            self._ttw_last_activity_update = 0
            self._ttw_bsa_total = 0
            self._ttw_bsa_done = 0
            self.ttw_start_time = time.time()

        lines_to_display = []
        html_fragments = []
        show_details_due_to_error = False
        bsa_progress_changed = False

        for cleaned in messages:
            if not cleaned:
                continue

            lower_cleaned = cleaned.lower()

            try:
                if not self._ttw_bsa_total:
                    bsa_total_match = re.search(r'(\d+)\s+output BSAs', cleaned)
                    if bsa_total_match:
                        self._ttw_bsa_total = int(bsa_total_match.group(1))
                        bsa_progress_changed = True

                if 'loading manifest:' in lower_cleaned:
                    self._ttw_current_phase = "Loading manifest"
            except Exception:
                pass

            is_error = 'error:' in lower_cleaned and 'succeeded' not in lower_cleaned and '0 failed' not in lower_cleaned
            is_warning = 'warning:' in lower_cleaned
            is_bsa_progress = cleaned.startswith('[BSA]')
            is_bsa_done = is_bsa_progress and ('... ok' in lower_cleaned or '... failed' in lower_cleaned)
            if is_bsa_done:
                self._ttw_bsa_done += 1
                bsa_progress_changed = True
            is_milestone = is_bsa_progress or any(
                kw in lower_cleaned for kw in ['===', 'complete', 'finished', 'validation', 'configuration valid']
            )
            is_file_op = not is_bsa_progress and any(
                ext in lower_cleaned for ext in ['.ogg', '.mp3', '.bsa', '.dds', '.nif', '.kf', '.hkx']
            )
            is_noise = cleaned.strip().upper() in ['OK', 'OK.', 'OK!', 'DONE', 'DONE.', 'SUCCESS', 'SUCCESS.']

            if is_error and 'cannot get directory path for location type' in lower_cleaned:
                self._ttw_unclean_game_dir_detected = True

            should_show = (is_error or is_warning or is_milestone) or (self.show_details_checkbox.isChecked() and not is_file_op and not is_noise)

            if should_show:
                if is_error or is_warning:
                    color = '#f44336' if is_error else '#ff9800'
                    prefix = "WARNING: " if is_warning else "ERROR: "
                    escaped = (prefix + cleaned).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                    html_fragments.append(f'<span style="color: {color};">{escaped}</span>')
                    show_details_due_to_error = True
                else:
                    lines_to_display.append(cleaned)

        if bsa_progress_changed and self._ttw_bsa_total:
            current_time = time.time()
            if (current_time - self._ttw_last_activity_update) >= 0.3:
                percent = int(self._ttw_bsa_done / self._ttw_bsa_total * 100)
                self._update_ttw_phase("Building archives", self._ttw_bsa_done, self._ttw_bsa_total, percent)
                self._ttw_last_activity_update = current_time

        if html_fragments or lines_to_display:
            try:
                if html_fragments:
                    self.console.insertHtml('<br>'.join(html_fragments) + '<br>')
                if lines_to_display:
                    self.console.append('\n'.join(lines_to_display))
                if show_details_due_to_error and not self.show_details_checkbox.isChecked():
                    self.show_details_checkbox.setChecked(True)
            except Exception:
                pass

    def on_installation_output(self, message):
        """Single-message output handler (not currently wired to the batch thread)."""
        if not hasattr(self, '_ttw_seen_lines'):
            self._ttw_seen_lines = set()
            self._ttw_last_extraction_progress = 0
            self._ttw_last_file_operation_time = 0
            self._ttw_file_operation_count = 0
            self._ttw_current_phase = None
            self._ttw_last_progress_line = None
            self._ttw_progress_line_text = None

        if message.strip().startswith('[Jackify]'):
            self._write_to_log_file(message)
            return

        cleaned = strip_ansi_control_codes(message).strip()

        filtered_chars = []
        for char in cleaned:
            code = ord(char)
            is_emoji = (
                (0x1F300 <= code <= 0x1F9FF) or
                (0x1F600 <= code <= 0x1F64F) or
                (0x2600 <= code <= 0x26FF) or
                (0x2700 <= code <= 0x27BF)
            )
            if not is_emoji:
                filtered_chars.append(char)
        cleaned = ''.join(filtered_chars).strip()

        if not cleaned:
            return

        if not hasattr(self, 'ttw_start_time'):
            self.ttw_start_time = time.time()

        lower_cleaned = cleaned.lower()

        try:
            self._write_to_log_file(cleaned)
        except Exception:
            pass

        try:
            progress_match = re.search(r'Progress:\s*(\d+)%', cleaned)
            if progress_match:
                percent = int(progress_match.group(1))
                self._update_ttw_activity(percent, 100, percent)

            if 'loading manifest:' in lower_cleaned:
                self._ttw_current_phase = "Loading manifest"
        except Exception:
            pass

        is_error = 'error:' in lower_cleaned and 'succeeded' not in lower_cleaned and '0 failed' not in lower_cleaned
        is_warning = 'warning:' in lower_cleaned
        is_milestone = any(kw in lower_cleaned for kw in ['===', 'complete', 'finished', 'validation', 'configuration valid'])
        is_file_op = any(ext in lower_cleaned for ext in ['.ogg', '.mp3', '.bsa', '.dds', '.nif', '.kf', '.hkx'])
        is_noise = cleaned.strip().upper() in ['OK', 'OK.', 'OK!', 'DONE', 'DONE.', 'SUCCESS', 'SUCCESS.']

        should_show = (is_error or is_warning or is_milestone) or (self.show_details_checkbox.isChecked() and not is_file_op and not is_noise)

        if should_show:
            try:
                if is_error or is_warning:
                    color = '#f44336' if is_error else '#ff9800'
                    prefix = "WARNING: " if is_warning else "ERROR: "
                    escaped = (prefix + cleaned).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                    html = f'<span style="color: {color};">{escaped}</span><br>'
                    self.console.insertHtml(html)
                    if not self.show_details_checkbox.isChecked():
                        self.show_details_checkbox.setChecked(True)
                else:
                    self.console.append(cleaned)
            except Exception:
                pass

    def on_installation_progress(self, progress_message):
        """Replace the last console line for in-place progress updates."""
        from PySide6.QtGui import QTextCursor
        cursor = self.console.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.movePosition(QTextCursor.StartOfLine, QTextCursor.KeepAnchor)
        cursor.removeSelectedText()
        cursor.insertText(progress_message)
