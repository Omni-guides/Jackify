"""
Wabbajack CLI Progress Parser

Parses upstream wabbajack-cli install output into InstallationProgress state.
Lines look like "HH:MM:SS.mmm [LEVEL] text"; progress arrives as plain text
(preflight check lines, "[NN%] status" install lines, "[Downloading] file: X of Y").
"""
import logging
import re
import time
from typing import List, Optional

from jackify.backend.handlers.wabbajack_cli_manual_downloads import ManualBlockParser
from jackify.shared.progress_models import (
    FileProgress,
    InstallationPhase,
    InstallationProgress,
    OperationType,
)

logger = logging.getLogger(__name__)

_LINE_RE = re.compile(r'^\d+:\d{2}:\d{2}(?:\.\d+)?\s+\[(\w+)\]\s?(.*)$')
_CHECK_STATE_RE = re.compile(r'^\[(Running|Passed|Failed)\]\s+([^:]+):\s*(.*)$')
_CHECK_PROGRESS_RE = re.compile(r'^([A-Za-z][A-Za-z ]*): (.*?) \((\d+)%(?:, (.*))?\)$')
_INSTALL_RE = re.compile(r'^\[\s*(\d+)%\]\s*(?:\[(\d+)/(\d+)\]\s*)?(.*)$')
_FILES_RE = re.compile(r'\(([\d,]+)/([\d,]+) files(?:, ([\d.]+\s?[A-Za-z]*)/([\d.]+\s?[A-Za-z]*))?\)')
_COUNTER_RE = re.compile(r'\(([\d,]+)/([\d,]+)\)\s*$')
_DOWNLOADING_RE = re.compile(r'^\[Downloading\]\s+(.+?): ([\d.]+\s?[A-Za-z]*) of ([\d.]+\s?[A-Za-z]*)$')
_LIST_FETCH_RE = re.compile(r'^Downloading ([^/\s]+)/([^/]+)$')
_DOWNLOADED_RE = re.compile(r'^\[Downloaded\]\s+(.+?):')
_SIZE_RE = re.compile(r'^([\d.]+)\s?([KMGT]?B)(?:/s)?$', re.IGNORECASE)
_UNITS = {'B': 1, 'KB': 1024, 'MB': 1024 ** 2, 'GB': 1024 ** 3, 'TB': 1024 ** 4}

_KNOWN_FAILURE_PREFIXES = ("Couldn't find list", "Unhandled exception:")
_GAME_MISSING_RE = re.compile(r"^Game installed: (.+?) is not installed")
_GAME_VERSION_RE = re.compile(
    r"^Game files: \d+ game files don't match \(built against ([\w.]+); you have ([\w.]+)\)"
)
_FILE_MISMATCH_SUFFIX = ": Does not match the version this list was built against"
_TO_DOWNLOAD_RE = re.compile(r'(\d+) to download \(([\d.]+\s?[A-Za-z]+)\)')
_ACCESS_DENIED_RE = re.compile(r"UnauthorizedAccessException: Access to the path '([^']+)' is denied")
_ERROR_LEVELS = {'ERROR', 'CRITICAL', 'CRIT', 'FATAL'}
_IGNORED_LEVELS = {'DEBUG', 'TRACE'}
_SUBTASKS = (
    (re.compile(r'^Writing inline files$'), "Writing inline files"),
    (re.compile(r'^Writing Metas$'), "Writing meta files"),
    (re.compile(r'^Generating debug caches$'), "Generating debug caches"),
)
_MAX_EXTRAPOLATION_SECONDS = 6.0
_RATE_SMOOTHING = 0.5


def parse_size(text: str) -> int:
    """Convert "9.5MB" or "6.8GB/s" to bytes. Returns 0 when unparseable."""
    m = _SIZE_RE.match(text.strip())
    if not m:
        return 0
    return int(float(m.group(1)) * _UNITS[m.group(2).upper()])


def _to_int(text: str) -> int:
    return int(text.replace(',', ''))


class WabbajackCliProgressStateManager:
    """
    Maintains InstallationProgress from wabbajack-cli output.
    Implements the same process_line / get_state interface as ProgressStateManager.
    """

    def __init__(self):
        self.state = InstallationProgress()
        self.state.phase = InstallationPhase.INITIALIZATION
        self.state.phase_name = "Starting"
        self.state.message_is_curated = True
        self.failed_checks: List[str] = []
        self.error_lines: List[str] = []
        self.preflight_stopped: bool = False
        self.finished: bool = False
        self._active_downloads: dict = {}
        self._download_total: int = 0
        self.modlist_fetch: Optional[str] = None
        self.manual = ManualBlockParser()

    def get_state(self) -> InstallationProgress:
        return self.state

    def reset(self) -> None:
        self.__init__()

    def get_failure_summary(self) -> Optional[str]:
        """Best user-facing reason for a failed run, or None if nothing failed."""
        if self.manual.items:
            return f"{len(self.manual.items)} files must be downloaded manually."
        if self.failed_checks:
            return "; ".join(self._plain_failure(c) for c in self._collapse_game_checks())
        if self.error_lines:
            return self._plain_failure(self.error_lines[-1])
        return None

    def _collapse_game_checks(self) -> List[str]:
        """Replace the game checks' per-file listing and Wabbajack-login advice with one sentence."""
        out: List[str] = []
        for check in self.failed_checks:
            missing = _GAME_MISSING_RE.match(check)
            version = _GAME_VERSION_RE.match(check)
            if missing:
                out.append(f"{missing.group(1)} was not found. Install it through Steam, "
                           "run it once, and try again.")
            elif version:
                out.append(f"Your game version ({version.group(2)}) does not match the version this "
                           f"modlist was built against ({version.group(1)}). Change the game to "
                           "that version and try again.")
            elif not check.endswith(_FILE_MISMATCH_SUFFIX):
                out.append(check)
        return out

    @staticmethod
    def _plain_failure(text: str) -> str:
        """Replace raw .NET exception text with something a user can act on."""
        denied = _ACCESS_DENIED_RE.search(text)
        if denied:
            return (f"Jackify cannot write to {denied.group(1)}. "
                    "Check that the folder exists and that you have permission to write to it.")
        if text.startswith('Nexus Mods login') and 'JSON' in text:
            return ("Jackify could not give the installer a Nexus Mods login. "
                    "Log in to Nexus Mods again in Jackify and retry.")
        return text

    def process_line(self, line: str) -> bool:
        stripped = line.strip()
        if not stripped:
            return False
        if self.manual.consume(stripped):
            return False
        level = 'INFO'
        text = stripped
        m = _LINE_RE.match(stripped)
        if m:
            level, text = m.group(1).upper(), m.group(2).strip()
        if level in _IGNORED_LEVELS:
            return False
        if text.startswith('Preflight stopped'):
            self.preflight_stopped = True
            return False
        if level in _ERROR_LEVELS:
            # Failed checks are logged again at ERROR level, followed by stack traces
            if _CHECK_STATE_RE.match(text) or text in self.error_lines or 'TaskCanceledException' in text:
                return False
            self.error_lines.append(text)
            self.state.message = text
            return True

        if text.startswith(_KNOWN_FAILURE_PREFIXES):
            self.error_lines.append(text)
            self.state.message = text
            return True

        for handler in (
            self._on_list_fetch,
            self._on_check_state,
            self._on_downloading,
            self._on_downloaded,
            self._on_install_status,
            self._on_check_progress,
            self._on_next_step,
            self._on_subtask,
        ):
            if handler(text):
                return True
        return False

    def _begin_phase(self, phase: InstallationPhase, name: str) -> None:
        """Switch phase, dropping counters and speed that belong to the previous one.

        Download byte totals and speed would otherwise stay on screen, and drive the bar,
        through every later phase.
        """
        if name == self.state.phase_name and phase == self.state.phase:
            return
        previous_phase = self.state.phase
        self.modlist_fetch = None
        self.state.speeds.clear()
        self.state.speed_timestamps.clear()
        self.state.phase = phase
        self.state.phase_name = name
        self.state.phase_step = 0
        self.state.phase_max_steps = 0
        self.state.stage_index = 0
        self.state.stage_total = 0
        self.state.data_processed = 0
        self.state.data_total = 0
        self.state.install_bytes_tracked = False
        if not (phase == previous_phase == InstallationPhase.INSTALL):
            self.state.overall_percent = 0.0
        self.state.bsa_building_current = 0
        self.state.bsa_building_total = 0

    def _on_list_fetch(self, text: str) -> bool:
        m = _LIST_FETCH_RE.match(text)
        if not m or self.state.phase != InstallationPhase.INITIALIZATION:
            return False
        self._begin_phase(InstallationPhase.DOWNLOAD, "Downloading modlist file")
        self.modlist_fetch = f"{m.group(1)}_@@_{m.group(2)}.wabbajack"
        self.state.message = "Downloading modlist file"
        return True

    def note_modlist_fetch_bytes(self, size: int) -> bool:
        """Record bytes of the .wabbajack file on disk. Returns True when the display changed."""
        if not self.modlist_fetch or size <= 0 or size == self.state.data_processed:
            return False
        self.state.data_processed = size
        self.state.active_files = [FileProgress(
            filename=self.modlist_fetch.replace("_@@_", "/").rsplit(".wabbajack", 1)[0],
            operation=OperationType.DOWNLOAD,
            percent=0.0,
            current_size=size,
            total_size=0,
        )]
        return True

    def _on_check_state(self, text: str) -> bool:
        m = _CHECK_STATE_RE.match(text)
        if not m:
            return False
        state, title, detail = m.groups()
        if state == 'Failed':
            self.failed_checks.append(f"{title}: {detail}".strip().rstrip(':'))
            self.state.message = f"Check failed - {title}"
        elif state == 'Running':
            self._begin_phase(InstallationPhase.VALIDATE, "Preflight")
            self.state.message = f"Checking: {title}"
        else:
            self.state.message = f"{title}: {detail}" if detail else title
            planned = _TO_DOWNLOAD_RE.search(detail)
            if planned:
                self._download_total = parse_size(planned.group(2))
        return True

    def _on_check_progress(self, text: str) -> bool:
        m = _CHECK_PROGRESS_RE.match(text)
        if not m:
            return False
        title, detail, pct, extras = m.group(1), m.group(2), int(m.group(3)), m.group(4)
        is_download = title.lower().startswith('automated downloads')
        if is_download:
            self._begin_phase(InstallationPhase.DOWNLOAD, "Downloading")
            if self.state.data_total == 0:
                self.state.data_total = self._download_total
        else:
            self._begin_phase(InstallationPhase.VALIDATE, "Preflight")
        self.state.message = f"{title}: {detail}"
        self.state.overall_percent = float(pct)
        counter = re.match(r'(\d+) of (\d+)', detail)
        if counter:
            self.state.phase_step = int(counter.group(1))
            self.state.phase_max_steps = int(counter.group(2))
        for part in (extras or '').split(', '):
            if not part:
                continue
            if ' of ' in part:
                done, total = part.split(' of ', 1)
                self.state.data_processed = parse_size(done)
                self.state.data_total = parse_size(total)
            elif part.endswith('/s'):
                speed = parse_size(part)
                if speed:
                    self.state.update_speed('download' if is_download else 'validate', speed)
        return True

    def _on_install_status(self, text: str) -> bool:
        m = _INSTALL_RE.match(text)
        if not m:
            return False
        pct = int(m.group(1))
        status = m.group(4).strip()

        if status == 'Finished':
            self.finished = True
            self._begin_phase(InstallationPhase.FINALIZE, "Finished")
            self.state.overall_percent = float(pct)
            self.state.message = "Finished"
            self.state.active_files = []
            return True

        title = _FILES_RE.sub('', status).strip()
        title = _COUNTER_RE.sub('', title).strip()
        self._begin_phase(self._phase_for(title), title)
        self.state.overall_percent = float(pct)
        if m.group(2):
            self.state.stage_index = int(m.group(2))
            self.state.stage_total = int(m.group(3))
        self.state.message = status

        files = _FILES_RE.search(status)
        if files:
            self.state.install_bytes_tracked = files.group(3) is not None
            if files.group(3):
                self.state.data_processed = parse_size(files.group(3))
                self.state.data_total = parse_size(files.group(4))
            self.state.phase_step = _to_int(files.group(1))
            self.state.phase_max_steps = _to_int(files.group(2))
            self.state.message = f"Installing: {files.group(1)}/{files.group(2)} files"
        else:
            counter = _COUNTER_RE.search(status)
            if counter:
                current, total = _to_int(counter.group(1)), _to_int(counter.group(2))
                if 'BSA' in title:
                    self.state.bsa_building_current = current
                    self.state.bsa_building_total = total
                else:
                    self.state.phase_step = current
                    self.state.phase_max_steps = total
        return True

    def _on_downloading(self, text: str) -> bool:
        m = _DOWNLOADING_RE.match(text)
        if not m:
            return False
        name, done, total = m.group(1), parse_size(m.group(2)), parse_size(m.group(3))
        now = time.monotonic()
        rate = 0.0
        previous = self._active_downloads.get(name)
        if previous and now > previous[2] and done >= previous[0]:
            observed = (done - previous[0]) / (now - previous[2])
            rate = observed if previous[3] <= 0 else (
                _RATE_SMOOTHING * observed + (1 - _RATE_SMOOTHING) * previous[3])
        self._active_downloads[name] = (done, total, now, rate)
        self._sync_active_files()
        return True

    def _on_downloaded(self, text: str) -> bool:
        m = _DOWNLOADED_RE.match(text)
        if not m:
            return False
        self._active_downloads.pop(m.group(1), None)
        self._sync_active_files()
        return True

    def _on_next_step(self, text: str) -> bool:
        if not text.startswith('Next Step:'):
            return False
        step = text[len('Next Step:'):].strip()
        self._begin_phase(self._phase_for(step), step)
        self.state.message = step
        return True

    def _on_subtask(self, text: str) -> bool:
        """Name the work the CLI is doing between step headers, so the banner does not sit on a
        stale file counter while it writes metas and inline files."""
        if self.state.phase != InstallationPhase.INSTALL:
            return False
        for pattern, label in _SUBTASKS:
            if pattern.match(text):
                self.state.phase_name = label
                self.state.message = label
                self.state.phase_step = 0
                self.state.phase_max_steps = 0
                self.state.stage_index = 0
                self.state.stage_total = 0
                self.state.data_processed = 0
                self.state.data_total = 0
                self.state.install_bytes_tracked = False
                return True
        return False

    def _sync_active_files(self) -> None:
        """Rebuild the download rows. Between CLI updates a row advances at its last measured
        rate, never past 99% of its size and never for longer than the CLI's usual gap."""
        now = time.monotonic()
        files = []
        for name, (done, total, seen, rate) in self._active_downloads.items():
            shown = done
            if rate > 0:
                shown += int(rate * min(now - seen, _MAX_EXTRAPOLATION_SECONDS))
                if total > 0:
                    shown = min(shown, int(total * 0.99))
                shown = max(shown, done)
            files.append(FileProgress(
                filename=name,
                operation=OperationType.DOWNLOAD,
                percent=(shown / total * 100.0) if total > 0 else 0.0,
                current_size=shown,
                total_size=total,
            ))
        self.state.active_files = files

    def tick(self) -> bool:
        """Advance download rows between CLI updates. Returns True when a row moved."""
        if not any(rate > 0 for *_, rate in self._active_downloads.values()):
            return False
        self._sync_active_files()
        return True

    @staticmethod
    def _phase_for(title: str) -> InstallationPhase:
        lowered = title.lower()
        if 'extracting' in lowered:
            return InstallationPhase.EXTRACT
        if 'hashing' in lowered or 'unmodified' in lowered or 'validat' in lowered:
            return InstallationPhase.VALIDATE
        if 'configuring' in lowered or 'priming' in lowered or 'folder structure' in lowered:
            return InstallationPhase.INITIALIZATION
        return InstallationPhase.INSTALL
