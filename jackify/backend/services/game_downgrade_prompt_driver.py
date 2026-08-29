"""Drives jackify-game-downgrader's interactive stdin/stdout over plain pipes.

steamcmd (invoked by the downgrader as a child process) reads the account password and
Steam Guard code from its inherited stdin, but that never requires a real tty: echo suppression
is a terminal-driver feature with no equivalent over a plain pipe, and the downgrader's own
confirmation/close-game gates already fall back to input() when stdin isn't a tty. So this
drives the whole flow over ordinary pipes, matching known prompt text against the GUI's own
native dialogs instead of a human typing into a terminal.

None of the prompts here ever end in a newline (input()'s own prompt text doesn't print one,
and steamcmd's C-style prompts don't either), so a naive line-based read would block forever
waiting for a newline that never arrives. This reads raw bytes with a short select() timeout
instead, exactly like the downgrader's own steamcmd.py handles its nested steamcmd subprocess.

Security: this module must never log raw captured output, only the prompt *kind* it matched
(see KNOWN_PROMPTS) - a captured line could contain account details in an unexpected steamcmd
error message. Passwords/codes the user enters live only as local variables for the moment it
takes to write them to the child's stdin.
"""

from __future__ import annotations

import logging
import os
import queue
import re
import select
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

from PySide6.QtCore import QThread, Signal

from jackify.backend.handlers.subprocess_utils import ProcessManager, get_clean_subprocess_env
from jackify.backend.services.steam_restart_service import shutdown_steam, start_steam_and_wait

logger = logging.getLogger(__name__)

IDLE_FLUSH_SECONDS = 0.3
GENERIC_FALLBACK_SECONDS = 20.0
POLL_INTERVAL_SECONDS = 0.2


@dataclass(frozen=True)
class PromptRule:
    kind: str
    substrings: tuple
    auto_reply: Optional[str] = None  # sent immediately, no UI involved


REQUIRES_CLOSED_RE = re.compile(r"requires (.+?) to be closed")

# Printed by cli.py right before it starts copying downgraded files into place (real,
# non-dry-run downgrades only) - once this has been seen, a failure past this point may have
# left the install in a half-swapped state worth mentioning the 'restore' command for.
REAL_CHANGES_MARKER = "Backing up the current install and copying downgraded files in"

# The downgrader draws its own single-line depot-transfer spinner by writing
# "\r\x1b[K<text>" repeatedly (a real-terminal overlay, see steamcmd.py's _run_with_spinner) -
# over a plain pipe that just means dozens of \r-separated frames with no newline between them.
ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
DEPOT_PROGRESS_RE = re.compile(r"depot (\d+): (\d+)% \((\d+)/(\d+) MB\)")


def _strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)

KNOWN_PROMPTS = (
    PromptRule("proceed", ("Proceed? [y/N]",), auto_reply="y"),
    # Only ever appears when the GUI's own backup checkbox was left checked (unchecking it
    # sends --no-backup, which skips this prompt entirely at the source) - the checkbox was
    # already the real decision, so this is just a mechanical yes, not a second ask.
    PromptRule("create_backup", ("Create a full game backup?",), auto_reply="y"),
    # Must come before the generic press_any_key rule below - this is the
    # "close Steam/the game first" gate, which needs a status update, not a
    # silent instant reply (see _handle_match).
    PromptRule("requires_closed", ("to be closed. Please fully exit",)),
    PromptRule("press_any_key", ("press any key to continue",), auto_reply=""),
    PromptRule("username", ("Steam username (for steamcmd login):",)),
    PromptRule("password", ("password:",)),
    PromptRule("guard_code", ("Steam Guard code:",)),
    PromptRule("guard_mobile", ("Steam Guard mobile authenticator",)),
)


class GameDowngradePromptDriver(QThread):
    """Runs the downgrader as a child process and drives its prompts.

    Emits Qt signals for anything the UI needs to show; for prompts that need a typed answer,
    the caller must call provide_answer() (or provide_login() for the combined username/
    password prompt) from any thread once the user has answered - this thread blocks on an
    internal queue until it arrives.
    """

    log_line = Signal(str)
    phase_status = Signal(str)
    need_login = Signal()
    need_password = Signal()
    need_guard_code = Signal()
    waiting_for_phone_approval = Signal(bool)
    waiting_for_process_close = Signal(str)
    depot_progress = Signal(str, int, int, int)  # depot_id, percent, done_mb, total_mb
    need_generic_input = Signal(str)
    finished = Signal(int, bool)  # returncode, real_changes_started

    def __init__(self, binary_path: str, python3_path: str, args: list, cwd: str = None,
                 system_info=None):
        super().__init__()
        self._cmd = [python3_path, binary_path, *args]
        self._cwd = cwd
        self._system_info = system_info
        self._answer_queue: "queue.Queue[str]" = queue.Queue()
        self._login_queue: "queue.Queue[tuple]" = queue.Queue()
        self._cached_password: Optional[str] = None
        self._pm: Optional[ProcessManager] = None
        self._cancel_requested = threading.Event()
        self._last_close_label: Optional[str] = None
        self._steam_was_shut_down = False
        self._last_depot_progress: Optional[tuple] = None
        self._awaiting_phone_approval = False
        self._awaiting_process_close = False
        self._real_changes_started = False

    def provide_answer(self, text: str) -> None:
        """Called from the UI thread once the user has answered a prompt."""
        self._answer_queue.put(text)

    def provide_login(self, username: str, password: str) -> None:
        """Called from the UI thread once the user has answered the combined login dialog."""
        self._login_queue.put((username, password))

    def cancel(self) -> None:
        self._cancel_requested.set()
        self._answer_queue.put("")  # unblock a pending wait for input
        self._login_queue.put(("", ""))
        if self._pm:
            self._pm.cancel()

    def run(self) -> None:
        # The downgrader refuses to run while Steam is open (it needs exclusive access to the
        # game's files) - Jackify already has a hardened shutdown/restart path for exactly this
        # situation (used before writing shortcuts.vdf etc.), so drive it here instead of making
        # the user go close Steam by hand. No separate "Closing Steam..." announcement here -
        # the confirmation dialog already explained why, and shutdown_steam()'s own progress
        # callback (wired straight to log_line, which also drives the banner) narrates it.
        try:
            steam_closed = shutdown_steam(progress_callback=self.log_line.emit, system_info=self._system_info)
        except Exception as e:
            logger.warning("Steam shutdown failed: %s", e)
            steam_closed = False
        if not steam_closed:
            self.log_line.emit("Could not automatically close Steam. Close it manually and try again.")
            self.finished.emit(-1, False)
            return
        self._steam_was_shut_down = True

        self.phase_status.emit("Running...")
        returncode = -1
        try:
            # Everything from process construction onward is inside this try/finally -
            # if ProcessManager() itself fails to spawn, finished must still be emitted or
            # the screen is stuck permanently in "running" chrome with no driver to cancel.
            env = get_clean_subprocess_env({"PYTHONUNBUFFERED": "1"})
            self._pm = ProcessManager(self._cmd, env=env, cwd=self._cwd, enable_stdin=True)
            stdout = self._pm.proc.stdout
            fd = stdout.fileno()

            pending = b""
            last_activity = time.monotonic()

            while not self._cancel_requested.is_set():
                if self._pm.proc.poll() is not None:
                    break
                try:
                    ready, _, _ = select.select([fd], [], [], POLL_INTERVAL_SECONDS)
                except (OSError, ValueError):
                    break

                if ready:
                    try:
                        chunk = os.read(fd, 4096)
                    except OSError:
                        break
                    if not chunk:
                        break
                    pending += chunk
                    pending = self._consume_overlay_frames(pending)
                    pending = self._drain_lines(pending)
                    # Reset AFTER processing, not before: _handle_match can block for a long
                    # time on a modal dialog (e.g. typing a Steam Guard code fetched from a
                    # phone) - if reset first, that wait alone could exceed
                    # GENERIC_FALLBACK_SECONDS and pop a spurious "waiting for input" dialog
                    # the instant the real one closes.
                    last_activity = time.monotonic()
                    continue

                idle = time.monotonic() - last_activity
                if pending and idle >= IDLE_FLUSH_SECONDS:
                    matched = self._try_match(pending)
                    if matched:
                        text = pending.decode(errors="replace")
                        pending = b""
                        self._handle_match(matched, text)
                        last_activity = time.monotonic()
                    elif idle >= GENERIC_FALLBACK_SECONDS:
                        # An unrecognized prompt sitting unflushed for a long time - surface
                        # whatever text we have instead of looping on it forever with no
                        # timeout (a prompt whose exact wording we don't know about must not
                        # be a silent permanent hang).
                        text = _strip_ansi(pending.decode(errors="replace")).strip()
                        pending = b""
                        if text:
                            self.log_line.emit(text)
                        self.need_generic_input.emit("The downgrader appears to be waiting for input.")
                        reply = self._answer_queue.get()
                        if not self._cancel_requested.is_set():
                            self._pm.write_stdin(reply)
                        last_activity = time.monotonic()
                elif not pending and idle >= GENERIC_FALLBACK_SECONDS:
                    self.need_generic_input.emit("The downgrader appears to be waiting for input.")
                    reply = self._answer_queue.get()
                    if not self._cancel_requested.is_set():
                        self._pm.write_stdin(reply)
                    last_activity = time.monotonic()
            returncode = self._pm.wait() if self._pm.is_running() else (self._pm.proc.returncode or 0)
        except Exception as e:
            logger.error("Game downgrade driver failed: %s", e)
            self.log_line.emit(f"Unexpected error running the downgrader: {e}")
        finally:
            self._restart_steam()
            self.finished.emit(returncode if returncode is not None else -1, self._real_changes_started)

    def _restart_steam(self) -> None:
        if not self._steam_was_shut_down:
            return
        self.phase_status.emit("Restarting Steam...")
        try:
            is_steam_deck = getattr(self._system_info, "is_steamdeck", None)
            is_flatpak = getattr(self._system_info, "is_flatpak_steam", None)
            # start_steam_and_wait(), not the bare start_steam() - that one returns as soon as
            # steamwebhelper is merely detected (~5s after launch), well before Steam is
            # actually usable, which let this driver report "finished" and restart-complete
            # before the user's Steam window was really back.
            if not start_steam_and_wait(
                is_steamdeck_flag=is_steam_deck, is_flatpak_flag=is_flatpak,
                progress_callback=self.log_line.emit,
            ):
                self.log_line.emit("Steam did not restart automatically - start it manually.")
        except Exception as e:
            logger.warning("Steam restart failed: %s", e)
            self.log_line.emit("Steam did not restart automatically - start it manually.")

    def _consume_overlay_frames(self, pending: bytes) -> bytes:
        """Drop stale \\r-redraw spinner frames, keeping only whatever comes after the last
        \\r in this chunk (which may itself be a real newline-terminated line, e.g. the
        "clear the overlay" \\r immediately preceding a depot's completion print()).

        steamcmd draws its own \\r-based connecting/login spinners independently of the
        downgrader's depot-progress overlay, and real content - a prompt (Steam Guard mobile
        approval, a password retry) or a complete newline-terminated line (e.g. "\\r\\x1b[K"
        clearing the overlay immediately followed by "Depot download complete\\n...") - can
        arrive glued to one of those spinner frames in the same read() chunk. A frame is only
        genuinely disposable once any real lines inside it have been drained out via
        _drain_lines and whatever single-line prompt text is left has been checked against
        KNOWN_PROMPTS - two regressions already found from skipping either step (2026-08-22:
        "check your phone" never appeared because a bare prompt-check wasn't enough; a
        depot-completion line landing mid-frame was silently dropped entirely)."""
        if b"\r" not in pending:
            return pending
        *frames, remainder = pending.split(b"\r")
        for frame in frames:
            if not frame:
                continue
            frame = self._drain_lines(frame)
            text = _strip_ansi(frame.decode(errors="replace")).strip()
            if not text:
                continue
            matched = self._try_match(text)
            if matched:
                self._handle_match(matched, text)
                continue
            self._maybe_emit_depot_progress(text)
        return remainder

    def _maybe_emit_depot_progress(self, text: str) -> None:
        match = DEPOT_PROGRESS_RE.search(text)
        if not match:
            return
        depot_id, percent, done_mb, total_mb = match.groups()
        percent, done_mb, total_mb = int(percent), int(done_mb), int(total_mb)
        # The tool's own on-disk size poll can keep creeping past its reported total for a
        # while after a depot is functionally done (before steamcmd prints its real
        # completion line) - clamp before deduping, not after, or a run of genuinely-different
        # raw values that all display identically ("100% (4663/4663 MB)") floods the log with
        # dozens of visually-duplicate lines.
        done_mb = min(done_mb, total_mb) if total_mb else done_mb
        key = (depot_id, percent, done_mb)
        if key == self._last_depot_progress:
            return
        self._last_depot_progress = key
        self._clear_phone_wait()
        self._clear_process_close_wait()
        self.depot_progress.emit(depot_id, percent, done_mb, total_mb)

    def _clear_phone_wait(self) -> None:
        if self._awaiting_phone_approval:
            self._awaiting_phone_approval = False
            self.waiting_for_phone_approval.emit(False)

    def _clear_process_close_wait(self) -> None:
        if self._awaiting_process_close:
            self._awaiting_process_close = False
            self._last_close_label = None
            self.waiting_for_process_close.emit("")  # empty label = resolved

    def _drain_lines(self, pending: bytes) -> bytes:
        while b"\n" in pending:
            line, pending = pending.split(b"\n", 1)
            text = _strip_ansi(line.decode(errors="replace"))
            matched = self._try_match(text)
            if matched:
                self._handle_match(matched, text)
            else:
                stripped = text.strip()
                if stripped:
                    self._clear_phone_wait()
                    self._clear_process_close_wait()
                    if REAL_CHANGES_MARKER in stripped:
                        self._real_changes_started = True
                        self.phase_status.emit("Copying downgraded files...")
                    self.log_line.emit(stripped)
        return pending

    def _try_match(self, buf: bytes | str) -> Optional[PromptRule]:
        text = buf.decode(errors="replace") if isinstance(buf, bytes) else buf
        for rule in KNOWN_PROMPTS:
            if any(s in text for s in rule.substrings):
                return rule
        return None

    def _handle_match(self, rule: PromptRule, text: str) -> None:
        logger.debug("Game downgrader: matched %s prompt", rule.kind)

        if rule.kind == "requires_closed":
            match = REQUIRES_CLOSED_RE.search(text)
            label = match.group(1) if match else "the required process"
            if label != self._last_close_label:
                self._last_close_label = label
                self._awaiting_process_close = True
                self.waiting_for_process_close.emit(label)
            # The downgrader re-checks and reprints this every loop iteration - throttle our
            # reply so we're not hammering it (and its own `pgrep`) many times a second while
            # genuinely waiting for the user to go close something.
            for _ in range(10):
                if self._cancel_requested.is_set():
                    return
                time.sleep(0.1)
            self._pm.write_stdin("")
            return

        if rule.auto_reply is not None:
            self._pm.write_stdin(rule.auto_reply)
            return

        if rule.kind == "username":
            # Ask for username and password together here (the earlier of the two prompts),
            # so the user isn't asked twice - the password is cached and auto-supplied when
            # steamcmd's own separate "password:" prompt arrives below.
            self.need_login.emit()
            username, password = self._login_queue.get()
            if self._cancel_requested.is_set():
                return
            self._cached_password = password
            self._pm.write_stdin(username)
            return

        if rule.kind == "guard_mobile":
            self._awaiting_phone_approval = True
            self.waiting_for_phone_approval.emit(True)
            return

        if rule.kind == "password":
            if self._cached_password is not None:
                password, self._cached_password = self._cached_password, None
                self._pm.write_stdin(password)
                del password
                return
            self.need_password.emit()
        elif rule.kind == "guard_code":
            self._clear_phone_wait()
            self.need_guard_code.emit()
        else:
            return

        answer = self._answer_queue.get()
        if not self._cancel_requested.is_set():
            self._pm.write_stdin(answer)
        del answer
