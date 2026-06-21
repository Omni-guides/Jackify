"""
CLF3 Progress Parser

Parses CLF3 --jackify stdout into InstallationProgress state.
Each line is a JSON object with a "type" field matching ProgressEvent variants.
"""
import json
import logging
import re

from jackify.shared.progress_models import InstallationPhase, InstallationProgress, FileProgress, OperationType

_COUNTER_RE = re.compile(r'\((\d+)/(\d+)\)\s*$')

logger = logging.getLogger(__name__)

_PHASE_MAP = {
    "Downloading": InstallationPhase.DOWNLOAD,
    "Validating": InstallationPhase.VALIDATE,
    "Installing": InstallationPhase.INSTALL,
    "Extracting": InstallationPhase.INSTALL,
    "BSA Build": InstallationPhase.INSTALL,
    "DDS Transform": InstallationPhase.INSTALL,
    "Finalizing": InstallationPhase.FINALIZE,
    "Cleanup": InstallationPhase.FINALIZE,
}


class CLF3ProgressStateManager:
    """
    Parses CLF3 --progress-json stdout and maintains InstallationProgress state.
    Implements the same process_line / get_state interface as ProgressStateManager.
    """

    def __init__(self):
        self.state = InstallationProgress()
        self.state.phase = InstallationPhase.INITIALIZATION
        self.state.phase_name = "Starting"
        self._total_archives: int = 0
        self._completed_archives: int = 0
        self._total_directives: int = 0
        self._completed_directives: int = 0
        # True once a real DownloadProgress event fires; distinguishes verify-only runs
        self._seen_actual_download: bool = False
        # name -> (downloaded, total, speed)
        self._active_downloads: dict = {}

    def get_state(self) -> InstallationProgress:
        return self.state

    def reset(self) -> None:
        self.__init__()

    def process_line(self, line: str) -> bool:
        stripped = line.strip()
        if not stripped:
            return False
        if not stripped.startswith('{'):
            idx = stripped.find('{')
            if idx < 0:
                return False
            stripped = stripped[idx:]
        try:
            obj = json.loads(stripped)
        except (json.JSONDecodeError, ValueError):
            return False

        event_type = obj.get('type')
        if not event_type:
            return False

        handler = _HANDLERS.get(event_type)
        if handler:
            return handler(self, obj)
        return False

    # -- event handlers --

    def _on_download_progress(self, obj: dict) -> bool:
        name = obj.get('name', '')
        downloaded = obj.get('downloaded', 0)
        total = obj.get('total', 0)
        speed = obj.get('speed', 0.0)
        self._active_downloads[name] = (downloaded, total, speed)

        self._seen_actual_download = True

        # Preserve "Downloading + Extracting" phase_name if concurrent mode is already active.
        in_concurrent = (
            self._total_archives > 0 and
            self._completed_archives > self._total_archives
        )
        if self.state.phase != InstallationPhase.DOWNLOAD:
            self.state.phase = InstallationPhase.DOWNLOAD
            self.state.phase_name = "Downloading + Extracting" if in_concurrent else "Downloading"
        elif self.state.phase_name not in ("Downloading", "Downloading + Extracting"):
            self.state.phase_name = "Downloading"

        # Rebuild active_files from current download map
        active_files = []
        for dl_name, (dl_downloaded, dl_total, dl_speed) in self._active_downloads.items():
            pct = (dl_downloaded / dl_total * 100.0) if dl_total > 0 else 0.0
            active_files.append(FileProgress(
                filename=dl_name,
                operation=OperationType.DOWNLOAD,
                percent=pct,
                current_size=dl_downloaded,
                total_size=dl_total,
                speed=dl_speed,
            ))
        self.state.active_files = active_files

        total_speed = sum(v[2] for v in self._active_downloads.values())
        speed_mb = total_speed / 1_048_576
        self.state.message = f"Downloading {len(active_files)} file(s) | {speed_mb:.1f} MB/s"

        if self._total_archives > 0:
            if in_concurrent:
                effective_max = self._total_archives * 2
                self.state.phase_step = self._completed_archives
                self.state.phase_max_steps = effective_max
                self.state.overall_percent = min(self._completed_archives / effective_max * 50.0, 50.0)
            else:
                self.state.phase_step = self._completed_archives
                self.state.phase_max_steps = self._total_archives
                self.state.overall_percent = min(self._completed_archives / self._total_archives * 50.0, 50.0)
        return True

    def _on_download_complete(self, obj: dict) -> bool:
        name = obj.get('name', '')
        self._active_downloads.pop(name, None)
        self.state.active_files = [f for f in self.state.active_files if f.filename != name]
        return True

    def _on_archive_complete(self, obj: dict) -> bool:
        index = obj.get('index', 0)
        total = obj.get('total', 0)
        if total:
            self._total_archives = total
        actual_total = total or self._total_archives
        self._completed_archives = index

        # CLF3 emits a single cumulative ArchiveComplete counter spanning both download
        # and extraction when running concurrently. index > actual_total means extraction
        # events are being counted on top of the download events.
        if actual_total > 0 and index > actual_total:
            extracted = index - actual_total
            effective_max = actual_total * 2
            self.state.phase_step = index
            self.state.phase_max_steps = effective_max
            self.state.overall_percent = min(index / effective_max * 50.0, 50.0)
            self.state.phase_name = "Downloading + Extracting"
            self.state.message = f"Downloaded: {actual_total}/{actual_total} | Extracting: {extracted}/{actual_total}"
        elif not self._seen_actual_download and self.state.phase in (InstallationPhase.DOWNLOAD, InstallationPhase.VALIDATE):
            self.state.phase_step = index
            self.state.phase_max_steps = actual_total
            if actual_total > 0:
                self.state.overall_percent = min(index / actual_total * 50.0, 50.0)
            self.state.phase_name = "Verifying Archives"
            self.state.message = f"Verifying: {index}/{actual_total}"
        else:
            self.state.phase_step = index
            self.state.phase_max_steps = actual_total
            phase_name = self.state.phase_name or ""
            phase_lower = phase_name.lower()
            if "bsa" in phase_lower:
                self.state.message = f"Building BSA: {index}/{actual_total}"
            elif "dds" in phase_lower or "transform" in phase_lower:
                self.state.message = f"Converting textures: {index}/{actual_total}"
            elif "extract" in phase_lower:
                if actual_total > 0:
                    self.state.overall_percent = min(index / actual_total * 50.0, 50.0)
                self.state.message = f"Extracting: {index}/{actual_total}"
            else:
                if actual_total > 0:
                    self.state.overall_percent = min(index / actual_total * 50.0, 50.0)
                self.state.message = f"Downloaded: {index}/{actual_total}"
        return True

    def _on_download_skipped(self, obj: dict) -> bool:
        count = obj.get('count', 0)
        # ArchiveComplete tracks the authoritative cumulative index; don't double-count here
        self.state.message = f"Skipped {count} already-downloaded archive(s)"
        return True

    def _on_phase_change(self, obj: dict) -> bool:
        phase_label = obj.get('phase', '')
        phase = InstallationPhase.UNKNOWN
        for key, val in _PHASE_MAP.items():
            if key.lower() in phase_label.lower():
                phase = val
                break
        self.state.phase = phase
        # Default DOWNLOAD phase to "Verifying"; _on_download_progress flips it
        # to "Downloading" the first time an actual download event arrives.
        if phase == InstallationPhase.DOWNLOAD:
            self.state.phase_name = "Verifying"
            self.state.message = "Verifying"
        else:
            self.state.phase_name = phase_label
            self.state.message = phase_label
        self.state.phase_step = 0
        self.state.phase_max_steps = 0
        self.state.active_files = []
        self._active_downloads.clear()
        self._seen_actual_download = False
        logger.debug("CLF3 phase: %s -> %s", phase_label, phase)
        return True

    def _on_directive_complete(self, obj: dict) -> bool:
        index = obj.get('index', 0)
        total = obj.get('total', 0)
        if total:
            self._total_directives = total
        self._completed_directives = index
        self.state.phase_step = index
        self.state.phase_max_steps = total or self._total_directives
        if total > 0:
            self.state.overall_percent = 50.0 + min(index / total * 50.0, 50.0)
        effective_total = total or self._total_directives
        phase_lower = (self.state.phase_name or "").lower()
        if "bsa" in phase_lower:
            self.state.message = f"Building BSA: {index}/{effective_total}"
        elif "dds" in phase_lower or "transform" in phase_lower:
            self.state.message = f"Converting textures: {index}/{effective_total}"
        else:
            self.state.message = f"Installing: {index}/{effective_total} files"
        return True

    def _on_directive_phase_started(self, obj: dict) -> bool:
        directive_type = obj.get('directive_type', '')
        total = obj.get('total', 0)
        if total:
            self._total_directives = total
        self.state.message = f"Processing {directive_type} ({total} files)"
        if self.state.phase not in (InstallationPhase.INSTALL, InstallationPhase.FINALIZE):
            self.state.phase = InstallationPhase.INSTALL
            self.state.phase_name = "Installing"
        return True

    def _on_status(self, obj: dict) -> bool:
        message = obj.get('message', '')
        if not message:
            return False
        self.state.message = message
        m = _COUNTER_RE.search(message)
        if m:
            step = int(m.group(1))
            total = int(m.group(2))
            self.state.phase_step = step
            self.state.phase_max_steps = total
            if total > 0:
                # Streaming extraction emits "Extracting <name> (N/total)" Status messages
                # instead of phase_start+overall_inc. Detect these and drive 50-100% progress.
                # Only transition to INSTALL when no downloads are active; during concurrent
                # download+extract we stay in DOWNLOAD phase and track 0-50%.
                if message.startswith("Extracting ") and not self._active_downloads:
                    self.state.phase = InstallationPhase.INSTALL
                    self.state.phase_name = "Extracting"
                    self.state.overall_percent = 50.0 + min(step / total * 50.0, 50.0)
                elif self.state.phase == InstallationPhase.INSTALL:
                    self.state.overall_percent = 50.0 + min(step / total * 50.0, 50.0)
                else:
                    self.state.overall_percent = min(step / total * 50.0, 50.0)
        return True


_HANDLERS = {
    'DownloadProgress': CLF3ProgressStateManager._on_download_progress,
    'DownloadComplete': CLF3ProgressStateManager._on_download_complete,
    'ArchiveComplete': CLF3ProgressStateManager._on_archive_complete,
    'DownloadSkipped': CLF3ProgressStateManager._on_download_skipped,
    'PhaseChange': CLF3ProgressStateManager._on_phase_change,
    'DirectiveComplete': CLF3ProgressStateManager._on_directive_complete,
    'DirectivePhaseStarted': CLF3ProgressStateManager._on_directive_phase_started,
    'Status': CLF3ProgressStateManager._on_status,
}
