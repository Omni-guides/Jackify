"""Line processing methods for ProgressStateManager (Mixin)."""

import logging
import time
from typing import TYPE_CHECKING

from jackify.shared.progress_models import (
    InstallationPhase,
    InstallationProgress,
    FileProgress,
    OperationType,
)

if TYPE_CHECKING:
    from jackify.backend.handlers.progress_parser import ParsedLine

logger = logging.getLogger(__name__)


class ProgressStateProcessingMixin:
    """Mixin providing line processing methods."""

    def process_line(self, line: str) -> bool:
        """
        Process a line of output and update state.

        Returns:
            True if state was updated, False otherwise
        """
        parsed = self.parser.parse_line(line)

        if not parsed.has_progress:
            return False

        updated = False

        phase_changed = False
        if parsed.phase and parsed.phase != self.state.phase:
            previous_phase = self.state.phase

            if previous_phase == InstallationPhase.DOWNLOAD:
                self._download_files_seen = {}
                self._download_total_bytes = 0
                self._download_processed_bytes = 0

            if previous_phase == InstallationPhase.VALIDATE and not parsed.data_info:
                if self.state.data_total > 0:
                    self.state.data_processed = 0
                    self.state.data_total = 0
                    updated = True

            if previous_phase == InstallationPhase.VALIDATE:
                if self.state.phase_name and 'validat' in self.state.phase_name.lower():
                    self.state.phase_name = ""
                    updated = True

            phase_changed = True
            self._previous_phase = self.state.phase
            self.state.phase = parsed.phase
            updated = True
        elif parsed.phase:
            self.state.phase = parsed.phase
            updated = True

        if parsed.phase_name:
            self.state.phase_name = parsed.phase_name
            updated = True
        elif phase_changed:
            if self.state.phase_name and self.state.phase != InstallationPhase.VALIDATE:
                self.state.phase_name = ""
                updated = True

        if self.state.phase == InstallationPhase.DOWNLOAD:
            if self.state.phase_name and 'validat' in self.state.phase_name.lower():
                self.state.phase_name = ""
                updated = True

        if parsed.overall_percent is not None:
            self.state.overall_percent = parsed.overall_percent
            updated = True

        if parsed.step_info:
            self.state.phase_step, self.state.phase_max_steps = parsed.step_info
            updated = True

        if parsed.data_info:
            new_processed, new_total = parsed.data_info
            self.state.data_processed = new_processed
            if self.state.phase == InstallationPhase.DOWNLOAD and self._download_total_bytes > 0:
                # The engine only reports remaining bytes during download; the parser
                # extrapolates a total from it and that estimate drifts both up and
                # down line to line as archive sizes vary. Prefer the total already
                # accumulated from real per-file sizes below once it's available.
                self.state.data_total = self._download_total_bytes
            else:
                self.state.data_total = new_total
            if self.state.data_total > 0 and self.state.overall_percent == 0.0:
                self.state.overall_percent = (self.state.data_processed / self.state.data_total) * 100.0
            updated = True

        if parsed.file_counter:
            self.state.phase_step, self.state.phase_max_steps = parsed.file_counter
            updated = True

        if parsed.file_progress:
            if hasattr(parsed.file_progress, '_texture_counter'):
                tex_current, tex_total = parsed.file_progress._texture_counter
                self.state.texture_conversion_current = tex_current
                self.state.texture_conversion_total = tex_total
                updated = True

            if hasattr(parsed.file_progress, '_bsa_counter'):
                bsa_current, bsa_total = parsed.file_progress._bsa_counter
                self.state.bsa_building_current = bsa_current
                self.state.bsa_building_total = bsa_total
                updated = True

            if hasattr(parsed.file_progress, '_hidden') and parsed.file_progress._hidden:
                return updated

            if parsed.file_progress.filename.lower().endswith('.wabbajack'):
                self._wabbajack_entry_name = parsed.file_progress.filename
                self._remove_synthetic_wabbajack()
                self._has_real_wabbajack = True
            else:
                if parsed.file_progress.operation == OperationType.DOWNLOAD:
                    self._remove_all_wabbajack_entries()
                    self._has_real_wabbajack = True

            if self.state.phase == InstallationPhase.DOWNLOAD and parsed.file_progress.operation == OperationType.DOWNLOAD:
                filename = parsed.file_progress.filename
                total_size = parsed.file_progress.total_size or 0
                current_size = parsed.file_progress.current_size or 0

                if filename not in self._download_files_seen:
                    if total_size > 0:
                        self._download_total_bytes += total_size
                        self._download_files_seen[filename] = (total_size, current_size)
                        self._download_processed_bytes += current_size
                else:
                    old_total, old_current = self._download_files_seen[filename]
                    if total_size > old_total:
                        self._download_total_bytes += (total_size - old_total)
                    if current_size > old_current:
                        self._download_processed_bytes += (current_size - old_current)
                    self._download_files_seen[filename] = (max(old_total, total_size), current_size)

                if self.state.data_total == 0 and self._download_total_bytes > 0:
                    self.state.data_total = self._download_total_bytes
                    self.state.data_processed = self._download_processed_bytes
                    updated = True

            self._augment_file_metrics(parsed.file_progress)
            existing_file = None
            for f in self.state.active_files:
                if f.filename == parsed.file_progress.filename:
                    existing_file = f
                    break

            if parsed.file_progress.percent >= 100.0 and not existing_file:
                updated = True
            elif parsed.file_progress.percent >= 100.0:
                parsed.file_progress.percent = 100.0
                parsed.file_progress.last_update = time.time()
                self.state.add_file(parsed.file_progress)
                updated = True
            else:
                self.state.add_file(parsed.file_progress)
                updated = True
        elif parsed.data_info:
            phase_name_lower = (parsed.phase_name or "").lower()
            message_lower = (parsed.message or "").lower()
            is_archive_phase = (
                'mod archives' in phase_name_lower or
                'downloading mod archives' in message_lower or
                (parsed.phase == InstallationPhase.DOWNLOAD and self._has_real_download_activity())
            )

            if is_archive_phase:
                self._remove_all_wabbajack_entries()
                self._has_real_wabbajack = True

            if not getattr(self, '_has_real_wabbajack', False):
                if self._maybe_add_wabbajack_progress(parsed):
                    updated = True

        if parsed.completed_filename:
            if not self.parser.should_display_file(parsed.completed_filename):
                parsed.completed_filename = None

        if parsed.completed_filename:
            if self.state.phase == InstallationPhase.DOWNLOAD:
                filename = parsed.completed_filename
                if filename in self._download_files_seen:
                    old_total, old_current = self._download_files_seen[filename]
                    if old_current < old_total:
                        self._download_processed_bytes += (old_total - old_current)
                        self._download_files_seen[filename] = (old_total, old_total)
                    if self.state.data_total == 0 and self._download_total_bytes > 0:
                        self.state.data_total = self._download_total_bytes
                        self.state.data_processed = self._download_processed_bytes
                        updated = True

            found_existing = False
            for file_prog in self.state.active_files:
                filename_match = (
                    file_prog.filename == parsed.completed_filename or
                    file_prog.filename.endswith(parsed.completed_filename) or
                    parsed.completed_filename in file_prog.filename
                )
                if filename_match:
                    file_prog.percent = 100.0
                    file_prog.last_update = time.time()
                    updated = True
                    found_existing = True
                    break

            if not found_existing:
                operation = OperationType.DOWNLOAD
                if parsed.file_progress:
                    operation = parsed.file_progress.operation

                completed_file = FileProgress(
                    filename=parsed.completed_filename,
                    operation=operation,
                    percent=100.0,
                    current_size=0,
                    total_size=0
                )
                completed_file.last_update = time.time()
                self.state.add_file(completed_file)
                updated = True

        if parsed.speed_info:
            operation, speed = parsed.speed_info
            self.state.update_speed(operation, speed)
            updated = True

        if parsed.message:
            self.state.message = parsed.message

        if updated:
            self.state.timestamp = time.time()

        if updated:
            self.state.remove_completed_files()

        return updated
