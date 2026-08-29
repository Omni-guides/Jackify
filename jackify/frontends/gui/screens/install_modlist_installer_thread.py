"""
InstallerThread: QThread subclass for running jackify-engine install.
Signals are defined at class level (required for Qt signal/slot).
"""

import json
import os
import re
import threading
from typing import Optional

from PySide6.QtCore import QThread, Signal
import logging

from jackify.backend.utils.engine_error_parser import parse_engine_error_line, error_from_exit_code, nexus_url_from_error_line
from jackify.backend.utils.cc_content_detector import is_cc_content_error, extract_cc_filename, is_creation_kit_missing_error
from jackify.shared.errors import JackifyError, cc_content_missing, creation_kit_missing
from jackify.shared.progress_models import InstallationPhase


logger = logging.getLogger(__name__)
class InstallerThread(QThread):
    """Runs jackify-engine install in a background thread. Signals at class level."""

    output_received = Signal(str)
    progress_received = Signal(str)
    progress_updated = Signal(object)
    installation_finished = Signal(bool, str)
    premium_required_detected = Signal(str)
    # Emitted when engine outputs a full batch of manual download items.
    # Payload: list of dicts with keys: file_name, nexus_url/download_url/url,
    #          expected_size, mod_name, mod_id, file_id, index, total, loop_iteration
    manual_download_list_received = Signal(list)
    manual_download_phase_complete = Signal()
    non_premium_detected = Signal()

    def __init__(self, modlist, install_dir, downloads_dir, api_key, modlist_name,
                 install_mode='online', progress_state_manager=None, auth_service=None,
                 oauth_info=None, game_type=None, clf3_cdn_url=None, engine_id=None):
        super().__init__()
        self.modlist = modlist
        self.install_dir = install_dir
        self.downloads_dir = downloads_dir
        self.api_key = api_key
        self.modlist_name = modlist_name
        self.game_type = game_type
        self.install_mode = install_mode
        self.clf3_cdn_url = clf3_cdn_url
        self.engine_id = engine_id
        self.cancelled = False
        self.process_manager = None
        self.progress_state_manager = progress_state_manager
        self.auth_service = auth_service
        self.oauth_info = oauth_info
        self._premium_signal_sent = False
        self._non_premium_info_sent = False
        self._engine_output_buffer = []
        self._buffer_size = 10
        self.last_error: Optional[JackifyError] = None
        self._raw_stderr_lines: list = []  # bounded ring buffer for non-JSON stderr
        self._raw_stdout_lines: list = []  # bounded ring buffer for non-JSON stdout
        self._pending_manual_downloads: list = []  # accumulates items until list_complete
        self._resource_limit_hint: Optional[str] = None
        self._install_progress_started = False  # True once any [FILE_PROGRESS] output seen
        self._last_error_raw_context: dict = {}  # raw context dict from structured engine errors

    @staticmethod
    def _is_generic_failure_text(message: Optional[str]) -> bool:
        text = (message or "").strip().lower()
        if not text:
            return True
        generic_markers = (
            "did not complete successfully",
            "unknown failure",
            "an install engine error occurred",
            "installation failed due to an engine error",
        )
        return any(marker in text for marker in generic_markers)

    def cancel(self):
        self.cancelled = True
        if self.process_manager:
            self.process_manager.cancel()

    def send_continue(self):
        """Send the continue command to the engine after manual downloads are ready."""
        if self.process_manager:
            sent = self.process_manager.write_stdin('{"command":"continue"}')
            if sent:
                logger.info("[MDL-1014] Manual download continue command accepted by process stdin")
            else:
                logger.error("[MDL-9010] Failed to send continue command to engine (stdin unavailable or process exited)")

    def _handle_engine_event(self, line: str) -> bool:
        """
        Try to parse a stdout line as an engine workflow event.
        Returns True if the line was an event (caller should not emit it as output).
        """
        stripped = line.strip()
        if not stripped.startswith('{'):
            return False
        try:
            obj = json.loads(stripped)
        except (json.JSONDecodeError, ValueError):
            return False

        event = obj.get('event')
        if not event:
            return False

        if event == 'manual_download_required':
            self._pending_manual_downloads.append(obj)
            return True

        if event == 'manual_download_list_complete':
            loop_iter = obj.get('loop_iteration', 1)
            items = list(self._pending_manual_downloads)
            self._pending_manual_downloads.clear()
            for item in items:
                item['loop_iteration'] = loop_iter
            if items:
                logger.info(f"[MDL-1000] Engine manual download list complete | loop_iteration={loop_iter} items={len(items)}")
                self.manual_download_list_received.emit(items)
            return True

        if event == 'manual_download_phase_complete':
            logger.info("[MDL-1015] Engine reported manual download phase complete")
            self.manual_download_phase_complete.emit()
            return True

        return False

    # CLF3 tracing line patterns (after ANSI stripping, from tracing_subscriber::fmt default format)
    _CLF3_TRACING_INFO_RE = re.compile(
        r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z\s+(INFO|DEBUG|TRACE)\s+'
    )
    _CLF3_TRACING_WARN_RE = re.compile(
        r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z\s+(WARN|ERROR)\s+\S+:\s+(.*)'
    )
    _CLF3_PHASE_HEADER_RE = re.compile(r'^=== .+ ===$')
    _CLF3_ANSI_RE = re.compile(r'\x1b\[[0-9;?]*[ -/]*[@-~]')

    def _read_stderr(self):
        import time as _time
        _stderr_log = os.environ.get("JACKIFY_CLF3_VERBOSE")
        _stderr_fh = open("/tmp/clf3_stderr.log", "w", encoding="utf-8") if _stderr_log else None
        _last_clf3_phase: str = ''
        try:
            for raw in self.process_manager.proc.stderr:
                line = raw.decode('utf-8', errors='replace').strip()
                if not line:
                    continue
                logger.debug(f"Engine stderr: {line}")
                if _stderr_fh:
                    _stderr_fh.write(line + "\n")
                    _stderr_fh.flush()
                self._raw_stderr_lines.append(line)
                if len(self._raw_stderr_lines) > 40:
                    self._raw_stderr_lines.pop(0)

                # CLF3: JSON events are on stdout; human-readable detail and tracing go to stderr.
                # Forward phase headers and log() messages to Show Details.
                # Verbose INFO/DEBUG/TRACE tracing is dropped; WARN/ERROR is shown stripped.
                clf3_parser = getattr(self, '_clf3_parser', None)
                if clf3_parser is not None:
                    clean = self._CLF3_ANSI_RE.sub('', line)
                    error = parse_engine_error_line(clean)
                    if error and self.last_error is None:
                        self.last_error = error
                    warn_m = self._CLF3_TRACING_WARN_RE.match(clean)
                    if warn_m:
                        self.output_received.emit(f"[WARN] {warn_m.group(2)}\n")
                    elif not self._CLF3_TRACING_INFO_RE.match(clean):
                        if self._CLF3_PHASE_HEADER_RE.match(clean):
                            if clean != _last_clf3_phase:
                                _last_clf3_phase = clean
                                self.output_received.emit(clean + '\n')
                        else:
                            self.output_received.emit(clean + '\n')
                    _act = getattr(self, '_clf3_last_activity', None)
                    if _act is not None:
                        _act[0] = _time.monotonic()
                    continue

                error = parse_engine_error_line(line)
                if error and self.last_error is None:
                    self.last_error = error
                    try:
                        obj = json.loads(line)
                        if obj.get("type") == "disk_full":
                            self._last_error_raw_context = obj.get("context") or {}
                    except (json.JSONDecodeError, ValueError):
                        pass
                else:
                    if self.last_error is None and is_cc_content_error(line):
                        self.last_error = cc_content_missing(extract_cc_filename(line) or "")
                    if self.last_error is None and is_creation_kit_missing_error(line):
                        self.last_error = creation_kit_missing(self.game_type)
        except Exception as e:
            logger.debug(f"Stderr reader error: {e}")
        finally:
            if _stderr_fh:
                _stderr_fh.close()
                logger.info("CLF3 stderr log written to /tmp/clf3_stderr.log")

    def _is_download_phase(self) -> bool:
        """True while the engine is downloading, per the structured progress parser.

        [FILE_PROGRESS] per-file console text (filename/percent/speed) is only
        useful during downloads, where per-file speed is the whole point. During
        hashing/extract/install it fires once per file with no throttling on the
        engine side, flooding Show Details with a filename flash for every one of
        tens of thousands of files. The Activity panel's counters are unaffected
        either way - they come from progress_state, parsed unconditionally above.
        """
        if not self.progress_state_manager:
            return False
        try:
            return self.progress_state_manager.get_state().phase == InstallationPhase.DOWNLOAD
        except Exception:
            return False

    def _remember_stdout_line(self, line: str) -> None:
        """Keep a bounded tail of meaningful stdout lines for failure diagnostics."""
        cleaned = (line or "").strip()
        if not cleaned:
            return
        if cleaned.startswith("{"):
            return
        if cleaned.startswith("Installing files ") or cleaned.startswith("Extracting files "):
            return
        self._raw_stdout_lines.append(cleaned)
        if len(self._raw_stdout_lines) > 60:
            self._raw_stdout_lines.pop(0)

    def _extract_root_cause_line(self) -> Optional[str]:
        """Extract the most actionable error line from stderr/stdout tails."""
        combined = list(reversed(self._raw_stderr_lines)) + list(reversed(self._raw_stdout_lines))
        if not combined:
            return None

        ignore_fragments = (
            "installation failed",
            "install failed",
            "exit code",
            "building bsa",
            "generating debug caches",
        )
        priority_fragments = (
            "too many open files",
            "file descriptor",
            "resource temporarily unavailable",
            "cannot increase file descriptor limit",
            "permission denied",
            "no space left on device",
            "traceback",
            "fatal",
            "exception",
            "error",
            "failed",
            "could not",
            "unable to",
        )

        for raw in combined:
            lowered = raw.lower()
            if any(fragment in lowered for fragment in ignore_fragments):
                continue
            if any(fragment in lowered for fragment in priority_fragments):
                return raw

        for raw in combined:
            lowered = raw.lower()
            if any(fragment in lowered for fragment in ignore_fragments):
                continue
            return raw

        return None

    def _build_failure_message(self, returncode: int) -> str:
        """Build a user-facing failure message with the best available root cause."""
        root_cause = self._extract_root_cause_line()
        if root_cause:
            nexus_url = nexus_url_from_error_line(root_cause)
            if nexus_url:
                root_cause = f"{root_cause}\nMod page: {nexus_url}"
            if self._resource_limit_hint and "file descriptor" not in root_cause.lower():
                return f"{root_cause}\n\nPossible contributing issue: {self._resource_limit_hint}"
            return root_cause

        recent_lines = []
        for line in list(reversed(self._raw_stderr_lines)) + list(reversed(self._raw_stdout_lines)):
            cleaned = (line or "").strip()
            if not cleaned:
                continue
            lowered = cleaned.lower()
            if (
                "install failed" in lowered
                or "installation failed" in lowered
                or "exit code" in lowered
                or "building bsa" in lowered
                or "generating debug caches" in lowered
            ):
                continue
            if cleaned not in recent_lines:
                recent_lines.append(cleaned)
            if len(recent_lines) >= 3:
                break

        if recent_lines:
            recent_block = "\n- ".join(recent_lines)
            return (
                "Install engine reported errors.\n\n"
                f"Most recent engine output:\n- {recent_block}"
            )

        if self._resource_limit_hint:
            return self._resource_limit_hint

        return (
            "Install failed, but the engine did not provide a specific error line."
        )

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

    def run(self):
        try:
            from jackify.backend.services.engine_invoker import (
                get_active_engine_id, get_engine_path, build_install_command,
                resolve_game_dir, resolve_game_location,
            )
            from jackify.backend.handlers.config_handler import ConfigHandler
            config_handler = ConfigHandler()

            engine_id = self.engine_id if self.engine_id else get_active_engine_id()
            engine_path = get_engine_path(engine_id)
            if not engine_path or not os.path.exists(engine_path):
                error_msg = f"Engine not found: {engine_id} ({engine_path or 'path unknown'})"
                logger.error(error_msg)
                self.installation_finished.emit(False, error_msg)
                return
            if not os.access(engine_path, os.X_OK):
                error_msg = f"Engine is not executable: {engine_path}"
                logger.error(error_msg)
                self.installation_finished.emit(False, error_msg)
                return

            logger.debug(f"Using engine {engine_id} at: {engine_path}")

            debug_mode = config_handler.get('debug_mode', False)
            game_dir = None
            clf3_mode = (engine_id == "clf3")
            if clf3_mode:
                location = resolve_game_location(self.game_type)
                if location:
                    game_dir, game_store = location
                    if game_store != 'steam':
                        store_label = {'gog': 'GOG', 'epic': 'Epic Games'}.get(game_store, game_store)
                        self.output_received.emit(
                            f"[WARN] Game detected from {store_label}, not Steam. "
                            "Most Wabbajack modlists require the Steam version. "
                            "If the install fails with hash errors, a store version mismatch is likely the cause.\n"
                        )
                else:
                    logger.warning("CLF3: could not resolve game directory for game_type=%s", self.game_type)

            if clf3_mode and self.clf3_cdn_url and not os.path.isfile(self.modlist):
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
                    return
                self.output_received.emit("Modlist file ready.\n")

            cmd = build_install_command(
                engine_id=engine_id,
                engine_path=engine_path,
                wabbajack=self.modlist,
                install_dir=self.install_dir,
                downloads_dir=self.downloads_dir,
                game_dir=game_dir,
                install_mode=self.install_mode,
                debug=debug_mode,
            )
            logger.debug(f"FULL Engine command: {' '.join(cmd)}")
            logger.debug(f"modlist value being passed: '{self.modlist}'")
            from jackify.backend.handlers.subprocess_utils import get_clean_subprocess_env
            writeback_path = str(self.auth_service.get_token_writeback_path()) if self.auth_service else None
            if clf3_mode:
                env_vars = {'NEXUS_OAUTH_TOKEN': self.api_key}
            else:
                env_vars = {'NEXUS_API_KEY': self.api_key}
                if self.oauth_info:
                    env_vars['NEXUS_OAUTH_INFO'] = self.oauth_info
                    from jackify.backend.services.nexus_oauth_service import NexusOAuthService
                    env_vars['NEXUS_OAUTH_CLIENT_ID'] = NexusOAuthService.CLIENT_ID
                if writeback_path:
                    env_vars['JACKIFY_TOKEN_WRITEBACK'] = writeback_path
                env_vars['DOTNET_SYSTEM_GLOBALIZATION_INVARIANT'] = "1"
            env = get_clean_subprocess_env(env_vars)

            # Install-time resource preflight: keep this visible in workflow output so
            # users/support see hard-limit constraints even without debug logging.
            try:
                from jackify.backend.services.resource_manager import ResourceManager
                resource_manager = ResourceManager()
                status = resource_manager.get_limit_status()
                if status.get('current_hard', 0) < status.get('target_limit', 0):
                    self._resource_limit_hint = (
                        f"File descriptor hard limit is {status['current_hard']} "
                        f"(target {status['target_limit']}); this can cause install failures. "
                        "Increase ulimit and retry."
                    )
                    self.output_received.emit(f"[WARN] {self._resource_limit_hint}\n")
            except Exception as e:
                logger.debug(f"Resource preflight check failed: {e}")

            from jackify.backend.handlers.subprocess_utils import ProcessManager
            if clf3_mode:
                import time as _time
                from jackify.backend.handlers.progress_parser_clf3 import CLF3ProgressStateManager
                self._clf3_parser = CLF3ProgressStateManager()
                self._clf3_last_activity = [_time.monotonic()]
            else:
                self._clf3_parser = None
            self.process_manager = ProcessManager(cmd, env=env, text=False, separate_stderr=True, enable_stdin=True)
            stderr_thread = threading.Thread(target=self._read_stderr, daemon=True)
            stderr_thread.start()

            if clf3_mode:
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
            else:
                ansi_escape = re.compile(rb'\x1b\[[0-9;?]*[ -/]*[@-~]')
                buffer = b''
                last_was_blank = False
                while True:
                    if self.cancelled:
                        self.cancel()
                        break
                    char = self.process_manager.read_stdout_char()
                    if not char:
                        break
                    buffer += char
                    while b'\n' in buffer or b'\r' in buffer:
                        if b'\r' in buffer and (buffer.index(b'\r') < buffer.index(b'\n') if b'\n' in buffer else True):
                            line, buffer = buffer.split(b'\r', 1)
                            line = ansi_escape.sub(b'', line)
                            decoded = line.decode('utf-8', errors='replace')
                            config_handler = ConfigHandler()
                            debug_mode = config_handler.get('debug_mode', False)
                            from jackify.backend.utils.nexus_premium_detector import is_non_premium_indicator
                            is_premium_error, matched_pattern = is_non_premium_indicator(decoded)
                            if not self._premium_signal_sent and is_premium_error:
                                self._premium_signal_sent = True
                                logger.warning("=" * 80)
                                logger.warning("PREMIUM DETECTION TRIGGERED - DIAGNOSTIC DUMP (Issue #111)")
                                logger.warning("=" * 80)
                                logger.warning(f"Matched pattern: '{matched_pattern}'")
                                logger.warning(f"Triggering line: '{decoded.strip()}'")
                                logger.warning("AUTHENTICATION DIAGNOSTICS:")
                                logger.warning(f"  Auth value present: {'YES' if self.api_key else 'NO'}")
                                if self.api_key:
                                    logger.warning(f"  Auth value length: {len(self.api_key)} chars")
                                    auth_method = self.auth_service.get_auth_method() if self.auth_service else None
                                    logger.warning(f"  Auth method: {auth_method or 'UNKNOWN'}")
                                    if auth_method == 'oauth' and self.auth_service:
                                        token_handler = self.auth_service.token_handler
                                        token_info = token_handler.get_token_info()
                                        logger.warning("  OAuth Token Status:")
                                        logger.warning(f"    Has token file: {token_info.get('has_token', False)}")
                                        logger.warning(f"    Has refresh token: {token_info.get('has_refresh_token', False)}")
                                        if 'expires_in_minutes' in token_info:
                                            logger.warning(f"    Expires in: {token_info['expires_in_minutes']:.1f} minutes")
                                        if 'refresh_token_age_days' in token_info:
                                            logger.warning(f"    Refresh token age: {token_info['refresh_token_age_days']:.1f} days")
                                        if token_info.get('error'):
                                            logger.warning(f"    Error: {token_info['error']}")
                                logger.warning("Previous engine output (last 10 lines):")
                                for i, buffered_line in enumerate(self._engine_output_buffer, 1):
                                    logger.warning(f"  -{len(self._engine_output_buffer) - i + 1}: {buffered_line}")
                                logger.warning("If user HAS Premium, this is a FALSE POSITIVE")
                                logger.warning("=" * 80)
                                self.premium_required_detected.emit(decoded.strip() or "Nexus Premium required")
                            self._engine_output_buffer.append(decoded.strip())
                            if len(self._engine_output_buffer) > self._buffer_size:
                                self._engine_output_buffer.pop(0)
                            if self.last_error is None and is_cc_content_error(decoded):
                                self.last_error = cc_content_missing(extract_cc_filename(decoded) or "")
                            if self.last_error is None and is_creation_kit_missing_error(decoded):
                                self.last_error = creation_kit_missing(self.game_type)
                            if self.progress_state_manager:
                                updated = self.progress_state_manager.process_line(decoded)
                                if updated:
                                    progress_state = self.progress_state_manager.get_state()
                                    if progress_state.active_files and debug_mode:
                                        logger.debug(f"Parser detected {len(progress_state.active_files)} active files from line: {decoded[:80]}")
                                    self.progress_updated.emit(progress_state)
                            if '[FILE_PROGRESS]' in decoded:
                                self._install_progress_started = True
                                parts = decoded.split('[FILE_PROGRESS]', 1)
                                if parts[0].strip():
                                    self.progress_received.emit(parts[0].rstrip())
                                if self._is_download_phase():
                                    tail = parts[1].strip() if len(parts) > 1 else ''
                                    if tail:
                                        self.progress_received.emit(tail + '\r')
                            else:
                                self.progress_received.emit(decoded + '\r')
                        elif b'\n' in buffer:
                            line, buffer = buffer.split(b'\n', 1)
                            line = ansi_escape.sub(b'', line)
                            decoded = line.decode('utf-8', errors='replace')
                            from jackify.backend.utils.nexus_premium_detector import is_non_premium_indicator
                            is_premium_error, matched_pattern = (False, None) if decoded.strip().startswith('{') else is_non_premium_indicator(decoded)
                            if not self._premium_signal_sent and is_premium_error:
                                self._premium_signal_sent = True
                                logger.warning("=" * 80)
                                logger.warning("PREMIUM DETECTION TRIGGERED - DIAGNOSTIC DUMP (Issue #111)")
                                logger.warning("=" * 80)
                                logger.warning(f"Matched pattern: '{matched_pattern}'")
                                logger.warning(f"Triggering line: '{decoded.strip()}'")
                                logger.warning("AUTHENTICATION DIAGNOSTICS:")
                                logger.warning(f"  Auth value present: {'YES' if self.api_key else 'NO'}")
                                if self.api_key:
                                    logger.warning(f"  Auth value length: {len(self.api_key)} chars")
                                    auth_method = self.auth_service.get_auth_method() if self.auth_service else None
                                    logger.warning(f"  Auth method: {auth_method or 'UNKNOWN'}")
                                    if auth_method == 'oauth' and self.auth_service:
                                        token_handler = self.auth_service.token_handler
                                        token_info = token_handler.get_token_info()
                                        logger.warning("  OAuth Token Status:")
                                        logger.warning(f"    Has token file: {token_info.get('has_token', False)}")
                                        logger.warning(f"    Has refresh token: {token_info.get('has_refresh_token', False)}")
                                        if 'expires_in_minutes' in token_info:
                                            logger.warning(f"    Expires in: {token_info['expires_in_minutes']:.1f} minutes")
                                        if 'refresh_token_age_days' in token_info:
                                            logger.warning(f"    Refresh token age: {token_info['refresh_token_age_days']:.1f} days")
                                        if token_info.get('error'):
                                            logger.warning(f"    Error: {token_info['error']}")
                                logger.warning("Previous engine output (last 10 lines):")
                                for i, buffered_line in enumerate(self._engine_output_buffer, 1):
                                    logger.warning(f"  -{len(self._engine_output_buffer) - i + 1}: {buffered_line}")
                                logger.warning("If user HAS Premium, this is a FALSE POSITIVE")
                                logger.warning("=" * 80)
                                self.premium_required_detected.emit(decoded.strip() or "Nexus Premium required")
                            if not self._non_premium_info_sent and 'non-premium' in decoded.lower() and 'routing' in decoded.lower():
                                self._non_premium_info_sent = True
                                self.non_premium_detected.emit()
                            self._engine_output_buffer.append(decoded.strip())
                            if len(self._engine_output_buffer) > self._buffer_size:
                                self._engine_output_buffer.pop(0)
                            if self.last_error is None and is_cc_content_error(decoded):
                                self.last_error = cc_content_missing(extract_cc_filename(decoded) or "")
                            if self.last_error is None and is_creation_kit_missing_error(decoded):
                                self.last_error = creation_kit_missing(self.game_type)
                            config_handler = ConfigHandler()
                            debug_mode = config_handler.get('debug_mode', False)
                            if self.progress_state_manager:
                                updated = self.progress_state_manager.process_line(decoded)
                                if updated:
                                    progress_state = self.progress_state_manager.get_state()
                                    if progress_state.active_files and debug_mode:
                                        logger.debug(f"Parser detected {len(progress_state.active_files)} active files from line: {decoded[:80]}")
                                    self.progress_updated.emit(progress_state)
                            if self._handle_engine_event(decoded):
                                last_was_blank = False
                                continue
                            self._remember_stdout_line(decoded)
                            if '[FILE_PROGRESS]' in decoded:
                                self._install_progress_started = True
                                parts = decoded.split('[FILE_PROGRESS]', 1)
                                if parts[0].strip():
                                    self.output_received.emit(parts[0].rstrip())
                                if self._is_download_phase():
                                    tail = parts[1].strip() if len(parts) > 1 else ''
                                    if tail:
                                        self.output_received.emit(tail + '\r')
                                last_was_blank = False
                                continue
                            if decoded.strip() == '':
                                if not last_was_blank:
                                    self.output_received.emit('\n')
                                last_was_blank = True
                            else:
                                self.output_received.emit(decoded + '\n')
                                last_was_blank = False
                if buffer:
                    line = ansi_escape.sub(b'', buffer)
                    decoded = line.decode('utf-8', errors='replace')
                    if '[FILE_PROGRESS]' in decoded:
                        parts = decoded.split('[FILE_PROGRESS]', 1)
                        if parts[0].strip():
                            self.output_received.emit(parts[0].rstrip())
                        if self._is_download_phase():
                            tail = parts[1].strip() if len(parts) > 1 else ''
                            if tail:
                                self.output_received.emit(tail + '\r')
                    else:
                        self._remember_stdout_line(decoded)
                        self.output_received.emit(decoded)
            stderr_thread.join(timeout=5)
            returncode = self.process_manager.wait()
            if writeback_path and self.auth_service and not clf3_mode:
                self.auth_service.apply_token_writeback(writeback_path)
            if self.process_manager.proc and self.process_manager.proc.stdout:
                try:
                    remaining = self.process_manager.proc.stdout.read()
                    if remaining:
                        decoded_remaining = remaining.decode('utf-8', errors='replace')
                        if decoded_remaining.strip():
                            logger.debug(f"Remaining output after process exit: {decoded_remaining[:500]}")
                            if '[FILE_PROGRESS]' in decoded_remaining:
                                parts = decoded_remaining.split('[FILE_PROGRESS]', 1)
                                if parts[0].strip():
                                    self.output_received.emit(parts[0].rstrip())
                            else:
                                self.output_received.emit(decoded_remaining)
                except Exception as e:
                    logger.debug(f"Error reading remaining output: {e}")
            if returncode != 0 and not self.cancelled and self.last_error is None:
                stderr_tail = self._raw_stderr_lines[-10:] if self._raw_stderr_lines else []
                stdout_tail = self._raw_stdout_lines[-10:] if self._raw_stdout_lines else []
                combined_tail = stderr_tail + stdout_tail
                tail_text = "\n".join(combined_tail)
                detail = f"Exit code {returncode}.\n\nEngine output:\n{tail_text}" if tail_text else f"Exit code {returncode}."
                fallback = error_from_exit_code(
                    returncode,
                    detail,
                    context={
                        "exit_code": returncode,
                        "stderr_tail_lines": len(stderr_tail),
                        "stdout_tail_lines": len(stdout_tail),
                    },
                )
                if fallback:
                    self.last_error = fallback

            if self.cancelled:
                self.installation_finished.emit(False, "Installation cancelled by user")
            elif returncode == 0:
                self.installation_finished.emit(True, "Installation completed successfully")
            else:
                if self.last_error:
                    error_msg = self.last_error.message or ""
                    if self._is_generic_failure_text(error_msg):
                        error_msg = self._build_failure_message(returncode)
                        self.last_error.message = error_msg
                else:
                    error_msg = self._build_failure_message(returncode)
                logger.error(f"Engine install failed | exit_code={returncode} summary={error_msg}")
                self.installation_finished.emit(False, error_msg)
        except Exception as e:
            self.installation_finished.emit(False, f"Installation error: {str(e)}")
        finally:
            if self.cancelled and self.process_manager:
                self.process_manager.cancel()
