"""
CLI manual download flow.

Handles the interactive terminal experience when the engine emits a batch of
files requiring manual download. Uses the same backend services as the GUI path
(ManualDownloadManager, DownloadWatcherService, FileValidatorService) but
outputs status to the terminal and reads simple keyboard commands.
"""

import os
import sys
import queue
import shutil
import threading
import logging
import time
from pathlib import Path
from typing import Callable, Optional

from jackify.backend.services.manual_download_manager import ManualDownloadManager, DownloadItem
from jackify.backend.services.download_watcher_service import WatcherConfig
from jackify.backend.handlers.config_handler import ConfigHandler

logger = logging.getLogger(__name__)

def _fmt_size(n: int) -> str:
    if n <= 0:
        return ''
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


class CliManualDownloadFlow:
    """
    Blocking CLI flow for manual downloads. Returns when all items are done
    (complete or skipped) and the continue command has been written to the
    engine's stdin pipe.
    """

    def __init__(
        self,
        items: list[dict],
        loop_iteration: int,
        download_dir: Path,
        stdin_write: Callable[[str], bool],
        output_callback: Optional[Callable[[str], None]] = None,
        concurrent_limit: int = 2,
    ):
        self._stdin_write = stdin_write
        self._output = output_callback or print
        self._done_event = threading.Event()
        self._config_handler = ConfigHandler()
        self._command_queue: queue.Queue[str] = queue.Queue()
        self._last_rendered_snapshot: Optional[str] = None
        self._last_render_time = 0.0
        self._completed_successfully = False
        self._interactive_tty = bool(getattr(sys.__stdout__, "isatty", lambda: False)())
        self._terminal = sys.__stdout__ if self._interactive_tty else None
        self._screen_lines = 0
        self._status_dirty = True
        self._notices: list[str] = []
        self._startup_render_blocked = False

        configured_watch = self._config_handler.get("manual_download_watch_directory", None)
        watch_dir = None
        if configured_watch:
            cfg_path = Path(str(configured_watch)).expanduser()
            if cfg_path.is_dir():
                watch_dir = cfg_path
        if watch_dir is None:
            xdg_dl = os.environ.get('XDG_DOWNLOAD_DIR', '')
            watch_dir = Path(xdg_dl) if (xdg_dl and Path(xdg_dl).is_dir()) else Path.home() / 'Downloads'

        self._manager = ManualDownloadManager(
            modlist_download_dir=download_dir,
            watch_directory=watch_dir,
            concurrent_limit=concurrent_limit,
            on_item_updated=self._on_item_updated,
            on_send_continue=self._on_all_done,
            on_all_done=self._on_all_done_counts,
        )
        self._manager.load_items(items, loop_iteration)
        self._total = len(self._manager.items)
        self._watch_dir = watch_dir

    def run(self) -> bool:
        """Block until all items are complete/skipped and continue is sent."""
        if not self._confirm_start():
            self._output("Manual download phase cancelled.")
            return False
        self._startup_render_blocked = True
        try:
            self._manager.start()
        finally:
            self._startup_render_blocked = False
        self._render_status(force=True)
        if sys.stdin.isatty():
            threading.Thread(target=self._read_commands, daemon=True).start()
        else:
            self._output("[interactive commands unavailable: non-interactive stdin]")

        while not self._done_event.is_set():
            self._handle_pending_commands()
            self._render_status()
            self._done_event.wait(timeout=0.25)

        self._manager.stop()
        return self._completed_successfully

    def _on_item_updated(self, item: DownloadItem) -> None:
        status = {
            'browser_opened': 'browser opened',
            'validating':     'validating...',
            'complete':       '[OK]',
            'deferred':       '[deferred]',
            'skipped':        '[skipped]',
            'error':          '[error]',
        }.get(item.status, item.status)
        if not self._interactive_tty or item.status in ('error',):
            self._output(f"  {status:>14}  {item.file_name}")
        if item.error_message:
            self._emit_notice(f"reason: {item.error_message}")
        self._status_dirty = True
        if self._startup_render_blocked or self._interactive_tty:
            return
        self._render_status(force=True)

    def _on_all_done_counts(self, completed: int, skipped: int) -> None:
        self._completed_successfully = completed == self._total and skipped == 0
        self._emit_notice(f"All downloads done: {completed} complete, {skipped} skipped")
        self._emit_notice("Signalling engine to continue...")

    def _on_all_done(self) -> None:
        self._stdin_write('{"command":"continue"}')
        self._done_event.set()

    def _retry_deferred(self) -> None:
        retried = 0
        with self._manager._lock:
            for item in self._manager._items:
                if item.status in ('deferred', 'skipped'):
                    item.status = 'pending'
                    item.needs_user_retry = False
                    item.error_message = None
                    retried += 1
        if retried == 0:
            self._emit_notice("[no deferred items to retry]")
            return
        self._emit_notice(f"[retried {retried} deferred item(s)]")
        self._manager._open_next_tabs()

    def _set_watch_folder(self, raw: str) -> None:
        candidate = Path(raw).expanduser()
        if not candidate.is_dir():
            self._emit_notice(f"[invalid directory: {candidate}]")
            return
        self._watch_dir = candidate
        self._manager._watch_dir = candidate
        self._manager._watcher._config.watch_directory = candidate
        # Force a fresh scan baseline for the newly-selected directory.
        self._manager._watcher._known = {}
        try:
            self._config_handler.set("manual_download_watch_directory", str(candidate))
            self._config_handler.save_config()
        except Exception:
            logger.debug("Could not persist manual_download_watch_directory", exc_info=True)
        self._emit_notice(f"[watch folder set to {candidate}]")
        self._status_dirty = True
        self._render_status(force=True)

    def _set_concurrency(self, raw: str) -> None:
        try:
            value = int(raw)
        except ValueError:
            self._emit_notice(f"[invalid number: {raw}]")
            return
        value = max(1, min(5, value))
        self._manager.set_concurrent_limit(value)
        try:
            self._config_handler.set("manual_download_concurrent_limit", value)
            self._config_handler.save_config()
        except Exception:
            logger.debug("Could not persist manual_download_concurrent_limit", exc_info=True)
        self._emit_notice(f"[concurrency set to {value}]")
        self._status_dirty = True
        self._render_status(force=True)

    def _read_commands(self) -> None:
        while not self._done_event.is_set():
            try:
                line = sys.stdin.readline()
            except Exception:
                return
            if not line:
                return
            self._command_queue.put(line.strip())

    def _handle_pending_commands(self) -> None:
        while True:
            try:
                command = self._command_queue.get_nowait()
            except queue.Empty:
                return
            if not command:
                continue
            if self._handle_command(command):
                return

    def _handle_command(self, command: str) -> bool:
        parts = command.split(maxsplit=1)
        action = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if action == 'help':
            self._print_help()
        elif action in ('list', 'ls', 'status'):
            self._render_status(force=True)
        elif action == 'open':
            self._open_item(arg)
        elif action in ('defer', 'skip'):
            self._defer_item(arg)
        elif action == 'retry':
            self._retry_deferred()
        elif action == 'watch':
            if not arg:
                self._emit_notice(f"[watch folder: {self._watch_dir}]")
            else:
                self._set_watch_folder(arg)
        elif action == 'pause':
            self._manager.pause()
            self._emit_notice("[paused]")
        elif action == 'resume':
            self._manager.resume()
            self._emit_notice("[resumed]")
        elif action in ('concurrency', 'tabs'):
            if not arg:
                self._emit_notice(f"[concurrency: {self._manager._limit}]")
            else:
                self._set_concurrency(arg)
        elif action in ('quit', 'exit'):
            self._emit_notice("Stopping - downloaded files are preserved for resume.")
            self._manager.stop()
            self._done_event.set()
            return True
        else:
            self._emit_notice(f"[unknown command: {command}]")
            self._print_help()
        return False

    def _print_help(self) -> None:
        self._output("")
        self._output("Commands:")
        self._output("  list                 Show current status")
        self._output("  open <index>         Re-open a file in the browser")
        self._output("  defer <index>        Defer an active file")
        self._output("  retry                Retry all deferred files")
        self._output("  watch <path>         Change watched download folder")
        self._output("  pause | resume       Pause or resume auto-open")
        self._output("  concurrency <1-5>    Set concurrent browser tabs")
        self._output("  quit                 Stop and preserve progress")
        self._output("")

    def _render_status(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and not self._status_dirty and (now - self._last_render_time) < 2.0:
            return
        with self._manager._lock:
            items = list(self._manager._items)
            complete = sum(1 for item in items if item.status == 'complete')
            deferred = sum(1 for item in items if item.status in ('deferred', 'skipped'))
            active = sum(1 for item in items if item.status == 'browser_opened')
            validating = sum(1 for item in items if item.status == 'validating')
            pending = sum(1 for item in items if item.status == 'pending')
            paused = self._manager._paused
        remaining = self._total - complete - deferred
        snapshot = (
            f"Watch: {self._watch_dir} | Complete: {complete}/{self._total} | "
            f"Active: {active} | Validating: {validating} | Pending: {pending} | "
            f"Deferred: {deferred} | Remaining: {remaining} | "
            f"Tabs: {self._manager._limit} | {'Paused' if paused else 'Running'}"
        )
        if not force and snapshot == self._last_rendered_snapshot:
            return
        self._last_rendered_snapshot = snapshot
        self._last_render_time = now
        self._status_dirty = False
        recheck_note = None
        if self._manager._items:
            first = self._manager._items[0]
            if first.loop_iteration > 1:
                recheck_note = f"Recheck {first.loop_iteration} - still missing: {self._total}"
        lines = [
            "",
            *self._boxed_lines(
                "Jackify CLI Download Manager",
                [
                    f"Files required: {self._total}",
                    f"Concurrent browser tabs: {self._manager._limit}",
                    f"Watching: {self._watch_dir}",
                    *( [recheck_note] if recheck_note else [] ),
                ],
            ),
            *self._boxed_lines(
                "Action Required",
                [
                    "Check your browser now.",
                    "Jackify may have opened Nexus download pages in the background.",
                    "Type `help` at any time for available commands.",
                ],
            ),
            *self._boxed_lines("Status", [snapshot]),
            *self._boxed_lines(
                "Downloads",
                [self._format_table_header(), *[self._format_item(item) for item in self._visible_items(items)]],
            ),
            *self._boxed_lines(
                "Commands",
                ["help | list | open <index> | defer <index> | retry | watch <path> | pause | resume | concurrency <1-5> | quit"],
            ),
            *self._boxed_lines("Notices", self._notices[-3:] or ["None"]),
            "",
        ]
        if self._interactive_tty and self._terminal is not None:
            self._redraw_terminal(lines)
        else:
            for line in lines:
                self._output(line)

    def _visible_items(self, items: list[DownloadItem]) -> list[DownloadItem]:
        priority = {'browser_opened': 0, 'validating': 1, 'pending': 2, 'deferred': 3, 'skipped': 4, 'error': 5, 'complete': 6}
        return sorted(items, key=lambda item: (priority.get(item.status, 9), item.index))[:14]

    def _format_item(self, item: DownloadItem) -> str:
        status = {
            'browser_opened': 'OPEN ',
            'validating': 'CHECK',
            'pending': 'WAIT ',
            'deferred': 'DEFER',
            'skipped': 'SKIP ',
            'error': 'ERROR',
            'complete': 'DONE ',
        }.get(item.status, item.status[:5].upper())
        size = _fmt_size(item.expected_size).rjust(7) if item.expected_size else ' ' * 7
        mod_name = self._truncate(item.mod_name or "", 24).ljust(24)
        file_name = self._truncate(item.file_name, 32).ljust(32)
        return f"{item.index:>3}/{item.total:<3}  {status}  {size}  {mod_name}  {file_name}"

    def _find_item(self, raw: str) -> Optional[DownloadItem]:
        if not raw:
            self._emit_notice("[missing item index]")
            return None
        if raw.isdigit():
            target_index = int(raw)
            for item in self._manager.items:
                if item.index == target_index:
                    return item
        low = raw.lower()
        for item in self._manager.items:
            if item.file_name.lower() == low:
                return item
        self._emit_notice(f"[item not found: {raw}]")
        return None

    def _open_item(self, raw: str) -> None:
        item = self._find_item(raw)
        if not item:
            return
        if self._manager.reopen_item(item.file_name):
            self._emit_notice(f"[opened] {item.file_name}")
        else:
            self._emit_notice(f"[could not open] {item.file_name}")

    def _defer_item(self, raw: str) -> None:
        item = self._find_item(raw)
        if not item:
            return
        if item.status not in ('browser_opened', 'pending', 'error'):
            self._emit_notice(f"[cannot defer item in state: {item.status}]")
            return
        self._manager.skip_item(item.file_name)
        self._emit_notice(f"[deferred] {item.file_name}")
        self._status_dirty = True

    def _confirm_start(self) -> bool:
        self._output("")
        for line in self._boxed_lines(
            "Non-Premium Manual Download Flow",
            [
                "Jackify detected that manual Nexus downloads are required.",
                "It will open Nexus pages in your browser, watch your download folder,",
                "validate files automatically, and resume once everything is present.",
                "",
                "Key commands:",
                "concurrency 1-5  Change simultaneous browser tabs",
                "defer <index>    Skip an item for now",
                "retry            Reopen deferred items",
                "watch <path>     Change monitored download folder",
            ],
        ):
            self._output(line)
        if not sys.stdin.isatty():
            return True
        self._output("Continue? [Y/n]: ")
        try:
            response = (sys.stdin.readline() or "").strip().lower()
        except Exception:
            return False
        return response in ("", "y", "yes")

    def _redraw_terminal(self, lines: list[str]) -> None:
        if self._terminal is None:
            return
        terminal_width = self._terminal_columns()
        if self._screen_lines:
            self._terminal.write(f"\x1b[{self._screen_lines}F")
        self._terminal.write("\x1b[J")
        for line in lines:
            self._terminal.write(line[: max(1, terminal_width - 1)] + "\n")
        self._terminal.flush()
        self._screen_lines = len(lines)

    @staticmethod
    def _truncate(value: str, width: int) -> str:
        if len(value) <= width:
            return value
        if width <= 3:
            return value[:width]
        return value[: width - 3] + "..."

    @staticmethod
    def _format_table_header() -> str:
        return "Idx     State    Size     Mod                       File"

    def _boxed_lines(self, title: str, rows: list[str], width: Optional[int] = None) -> list[str]:
        width = width or max(60, min(100, self._terminal_columns() - 2))
        inner_width = max(20, width - 4)
        top = "+" + "-" * (width - 2) + "+"
        rendered = [top, f"| {self._truncate(title, inner_width).ljust(inner_width)} |"]
        if rows:
            rendered.append("|" + "-" * (width - 2) + "|")
            for row in rows:
                rendered.append(f"| {self._truncate(row, inner_width).ljust(inner_width)} |")
        rendered.append(top)
        return rendered

    def _terminal_columns(self) -> int:
        return shutil.get_terminal_size(fallback=(100, 24)).columns

    def _emit_notice(self, message: str) -> None:
        if self._interactive_tty:
            self._notices.append(message)
            self._status_dirty = True
            return
        self._output(message)

def run_cli_manual_download_phase(
    events: list[dict],
    loop_iteration: int,
    download_dir: Path,
    stdin_write: Callable[[str], bool],
    output_callback: Optional[Callable[[str], None]] = None,
    concurrent_limit: int = 2,
) -> bool:
    """
    Entry point called from modlist_operations_configuration_cli when the engine emits
    a manual_download_list_complete event. Blocks until done.
    """
    flow = CliManualDownloadFlow(
        items=events,
        loop_iteration=loop_iteration,
        download_dir=download_dir,
        stdin_write=stdin_write,
        output_callback=output_callback,
        concurrent_limit=concurrent_limit,
    )
    return flow.run()
