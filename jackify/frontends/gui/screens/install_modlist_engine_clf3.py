"""
CLF3 engine support for InstallerThread: modlist fetch, environment, stderr forwarding and
the stdout/heartbeat loops. Everything CLF3-specific lives here so it can be removed as a unit.
"""

import logging
import os
import re
import threading
import time as _time
from typing import Optional

from jackify.backend.utils.engine_error_parser import parse_engine_error_line

logger = logging.getLogger(__name__)


class Clf3InstallerMixin:
    """CLF3 behaviour for InstallerThread."""

    _clf3_parser = None
    _clf3_last_activity = None
    _clf3_stderr_fh = None
    _clf3_last_phase: str = ''
    _clf3_manual_parser = None

    # CLF3 tracing line patterns (after ANSI stripping, from tracing_subscriber::fmt default format)
    _CLF3_TRACING_INFO_RE = re.compile(
        r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z\s+(INFO|DEBUG|TRACE)\s+'
    )
    _CLF3_TRACING_WARN_RE = re.compile(
        r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z\s+(WARN|ERROR)\s+\S+:\s+(.*)'
    )
    _CLF3_PHASE_HEADER_RE = re.compile(r'^=== .+ ===$')
    _CLF3_ANSI_RE = re.compile(r'\x1b\[[0-9;?]*[ -/]*[@-~]')

    def _clf3_resolve_game_dir(self) -> Optional[str]:
        from jackify.backend.services.engine_invoker import resolve_game_location
        location = resolve_game_location(self.game_type)
        if not location:
            logger.warning("CLF3: could not resolve game directory for game_type=%s", self.game_type)
            return None
        game_dir, game_store = location
        if game_store != 'steam':
            store_label = {'gog': 'GOG', 'epic': 'Epic Games'}.get(game_store, game_store)
            self.output_received.emit(
                f"[WARN] Game detected from {store_label}, not Steam. "
                "Most Wabbajack modlists require the Steam version. "
                "If the install fails with hash errors, a store version mismatch is likely the cause.\n"
            )
        return game_dir

    def _clf3_fetch_modlist(self, engine_path: str) -> bool:
        """Download the .wabbajack via CLF3 when only a CDN URL is known. False means finished was emitted."""
        if not self.clf3_cdn_url or os.path.isfile(self.modlist):
            return True
        self.output_received.emit("Downloading modlist file via CLF3...\n")
        import subprocess as _sp
        from jackify.backend.handlers.subprocess_utils import get_clean_subprocess_env
        fetch_cmd = [engine_path, "fetch", self.clf3_cdn_url, "--output", self.modlist]
        logger.debug("CLF3 fetch command: %s", " ".join(fetch_cmd))
        fetch_env = get_clean_subprocess_env({})
        fetch_cwd = os.path.dirname(self.modlist) or os.path.expanduser("~")
        os.makedirs(fetch_cwd, exist_ok=True)
        fetch_result = _sp.run(fetch_cmd, capture_output=True, text=True, env=fetch_env, cwd=fetch_cwd)
        if fetch_result.returncode != 0:
            err = fetch_result.stderr.strip() or fetch_result.stdout.strip() or "unknown error"
            self.installation_finished.emit(False, f"Failed to download modlist file:\n\n{err}")
            return False
        self.output_received.emit("Modlist file ready.\n")
        return True

    def _clf3_env_vars(self) -> dict:
        return {'NEXUS_OAUTH_TOKEN': self.api_key}

    def _clf3_start_session(self) -> None:
        from jackify.backend.handlers.progress_parser_clf3 import CLF3ProgressStateManager
        from jackify.backend.handlers.clf3_manual_downloads import Clf3ManualListParser
        self._clf3_parser = CLF3ProgressStateManager()
        self._clf3_manual_parser = Clf3ManualListParser()
        self._clf3_last_activity = [_time.monotonic()]

    def _clf3_run_output_loops(self) -> None:
        heartbeat_stop = threading.Event()
        heartbeat_thread = threading.Thread(
            target=self._run_clf3_heartbeat,
            args=(self._clf3_last_activity, heartbeat_stop),
            daemon=True,
        )
        heartbeat_thread.start()
        self._run_clf3_stdout_loop(self._clf3_last_activity)
        heartbeat_stop.set()
        heartbeat_thread.join(timeout=2.0)

    def _clf3_open_stderr_log(self) -> None:
        self._clf3_last_phase = ''
        if self._clf3_parser is not None and os.environ.get("JACKIFY_CLF3_VERBOSE"):
            self._clf3_stderr_fh = open("/tmp/clf3_stderr.log", "w", encoding="utf-8")

    def _clf3_close_stderr_log(self) -> None:
        if self._clf3_stderr_fh:
            self._clf3_stderr_fh.close()
            self._clf3_stderr_fh = None
            logger.info("CLF3 stderr log written to /tmp/clf3_stderr.log")

    def _clf3_forward_stderr_line(self, line: str) -> bool:
        """CLF3: JSON events are on stdout; human-readable detail and tracing go to stderr.

        Forwards phase headers and log() messages to Show Details. Verbose INFO/DEBUG/TRACE
        tracing is dropped; WARN/ERROR is shown stripped. Returns True when the line was handled.
        """
        if self._clf3_parser is None:
            return False
        if self._clf3_stderr_fh:
            self._clf3_stderr_fh.write(line + "\n")
            self._clf3_stderr_fh.flush()
        clean = self._CLF3_ANSI_RE.sub('', line)
        if self._clf3_manual_parser is not None:
            self._clf3_manual_parser.feed(clean)
        error = parse_engine_error_line(clean)
        if error and self.last_error is None:
            self.last_error = error
        warn_m = self._CLF3_TRACING_WARN_RE.match(clean)
        if warn_m:
            self.output_received.emit(f"[WARN] {warn_m.group(2)}\n")
        elif not self._CLF3_TRACING_INFO_RE.match(clean):
            if self._CLF3_PHASE_HEADER_RE.match(clean):
                if clean != self._clf3_last_phase:
                    self._clf3_last_phase = clean
                    self.output_received.emit(clean + '\n')
            else:
                self.output_received.emit(clean + '\n')
        if self._clf3_last_activity is not None:
            self._clf3_last_activity[0] = _time.monotonic()
        return True

    def _clf3_manual_events(self) -> list:
        """Manual download dialog events built from the parsed CLF3 listing."""
        from jackify.backend.handlers.wabbajack_cli_manual_downloads import (
            ManualItem, build_manual_events, find_wabbajack_file, load_archives,
        )
        items = [
            ManualItem(i.name, i.size_text.replace('iB', 'B'), '', i.url, i.note)
            for i in self._clf3_manual_parser.items
        ]
        archives = load_archives(find_wabbajack_file(self.modlist, self.downloads_dir))
        return build_manual_events(items, archives)

    def _clf3_handle_manual_downloads(self, returncode: int, cmd: list, env: dict) -> int:
        """Show CLF3's manual download listing in the download manager and re-run on continue.

        CLF3 exits 0 after printing the list and has no way to wait, so Jackify holds here
        until the files are in the downloads folder, then runs the same command again.
        """
        from jackify.backend.handlers.subprocess_utils import ProcessManager
        while (returncode == 0 and not self.cancelled and self._clf3_manual_parser is not None
               and self._clf3_manual_parser.items):
            self._clf3_continue = threading.Event()
            self._wjcli_waiting = True
            self._wjcli_continue = self._clf3_continue
            self.manual_download_list_received.emit(self._clf3_manual_events())
            self._clf3_continue.wait()
            self._wjcli_waiting = False
            if self.cancelled:
                break
            self._clf3_start_session()
            self.process_manager = ProcessManager(cmd, env=env, text=False, separate_stderr=True, enable_stdin=True)
            stderr_thread = threading.Thread(target=self._read_stderr, daemon=True)
            stderr_thread.start()
            self._clf3_run_output_loops()
            stderr_thread.join(timeout=5)
            returncode = self.process_manager.wait()
        return returncode

    def _clf3_apply_manual_downloads(self, returncode: int) -> int:
        """CLF3 exits 0 after listing files it cannot fetch; treat that as an incomplete install."""
        parser = self._clf3_manual_parser
        if returncode != 0 or self.cancelled or parser is None or not parser.found:
            return returncode
        from jackify.backend.handlers.clf3_manual_downloads import format_manual_summary
        from jackify.shared.errors import manual_downloads_required
        logger.warning("CLF3 stopped with %d manual download(s) outstanding", parser.expected_count or len(parser.items))
        if self.last_error is None:
            self.last_error = manual_downloads_required(
                format_manual_summary(parser, max_items=8), parser.downloads_dir
            )
        return 1

    def _run_clf3_heartbeat(self, last_activity: list, stop: threading.Event) -> None:
        """Emit periodic 'finalising' updates to Show Details when stdout goes silent.

        Fires once when silence exceeds THRESHOLD, then repeats every REPEAT seconds
        of continued silence - so extended waits remain visible to the user.
        Samples /proc/<pid>/io to show write throughput, giving the user concrete
        evidence that extraction is progressing even when CLF3 emits no output.
        Resets when real output arrives so a new silence period can trigger it again.
        """
        import copy
        import time as _time
        THRESHOLD = 8.0
        INTERVAL = 5.0
        REPEAT = 30.0
        last_heartbeat_at = [0.0]
        while not stop.wait(INTERVAL):
            proc = self.process_manager.proc if self.process_manager else None
            if not proc or proc.poll() is not None:
                break
            now = _time.monotonic()
            elapsed_since_activity = now - last_activity[0]
            if elapsed_since_activity < THRESHOLD:
                continue
            # Allow first fire when silence starts; then only re-fire every REPEAT seconds.
            already_fired = last_heartbeat_at[0] >= last_activity[0]
            if already_fired and (now - last_heartbeat_at[0]) < REPEAT:
                continue
            clf3_parser = getattr(self, '_clf3_parser', None)
            phase = (clf3_parser.get_state().phase_name if clf3_parser else None) or 'Working'
            wait_secs = int(elapsed_since_activity)
            # Sample write_bytes to show active extraction throughput.
            # The N/N dispatch counter fires when all archives are handed to worker threads;
            # the workers themselves continue decompressing in parallel after that point.
            # /proc/<pid>/io write_bytes confirms real I/O is happening.
            if not already_fired:
                total = clf3_parser.get_state().phase_max_steps if clf3_parser else 0
                archive_str = f"{total} archives" if total else "archives"
                self.output_received.emit(f"[Decompressing {archive_str}: workers running...]\n")
            if clf3_parser:
                from jackify.shared.progress_models import InstallationPhase
                current = clf3_parser.get_state()
                heartbeat_state = copy.copy(current)
                heartbeat_state.phase = InstallationPhase.FINALIZE
                heartbeat_state.phase_name = "Decompressing"
                heartbeat_state.phase_step = 0
                heartbeat_state.phase_max_steps = 0
                heartbeat_state.overall_percent = 99.0
                heartbeat_state.message = "Decompressing archives..."
                self.progress_updated.emit(heartbeat_state)
            last_heartbeat_at[0] = now

    def _run_clf3_stdout_loop(self, last_activity: list) -> None:
        """Read CLF3 stdout line-by-line and forward to Show Details.

        JSON progress events (keyed on "type") and plain human-readable text both arrive
        on stdout. Manual download events (keyed on "event") also appear on stdout.

        Extraction dispatch counters ("Extracting: N/M") are dropped - named per-archive
        completion lines already cover this information.
        Directive counters ("Processing: N/M") are buffered; only the final value is
        emitted when the next non-counter line arrives, avoiding a 1315-line flood.
        """
        import time as _time
        _COUNTER_LINE_RE = re.compile(r'^(?:Extracting|Building BSA|DDS Transform): \d+/\d+$')
        _PROCESSING_RE = re.compile(r'^Processing: \d+/\d+$')
        _PHASE_HEADER_RE = re.compile(r'^=== .+ ===$')
        _buffered_processing = None
        _last_phase_header: str = ''
        ansi_escape = re.compile(rb'\x1b\[[0-9;?]*[ -/]*[@-~]')
        for raw in self.process_manager.proc.stdout:
            if self.cancelled:
                self.cancel()
                break
            decoded = ansi_escape.sub(b'', raw).decode('utf-8', errors='replace').rstrip('\r\n')
            stripped = decoded.strip()
            if not stripped:
                continue
            last_activity[0] = _time.monotonic()
            self._remember_stdout_line(decoded)
            if self._handle_engine_event(decoded):
                continue
            if stripped.startswith('{'):
                clf3_parser = getattr(self, '_clf3_parser', None)
                if clf3_parser and clf3_parser.process_line(stripped):
                    state = clf3_parser.get_state()
                    self.progress_updated.emit(state)
                    msg = state.message
                    if msg.startswith('Extracting ') and '(' in msg and state.phase_name == "Extracting":
                        # Relabel as "Queuing" - the N/M counter tracks archive dispatch
                        # to worker threads, not completion of decompression.
                        self.output_received.emit(msg.replace('Extracting ', 'Queuing ', 1) + '\n')
                continue
            if self._clf3_manual_parser is not None:
                self._clf3_manual_parser.feed(stripped)
            if _COUNTER_LINE_RE.match(stripped):
                continue
            if _PROCESSING_RE.match(stripped):
                _buffered_processing = stripped
                continue
            if _buffered_processing is not None:
                self.output_received.emit(_buffered_processing + '\n')
                _buffered_processing = None
            if _PHASE_HEADER_RE.match(stripped):
                if stripped == _last_phase_header:
                    continue
                _last_phase_header = stripped
            self.output_received.emit(decoded + '\n')
        if _buffered_processing is not None:
            self.output_received.emit(_buffered_processing + '\n')
