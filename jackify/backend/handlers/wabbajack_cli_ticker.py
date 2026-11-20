"""Once-a-second refresh of wabbajack-cli progress between the CLI's own updates."""
import logging
import threading
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

POLL_SECONDS = 1.0


def fetched_bytes(download_dir: str, file_name: str) -> int:
    """Size of the modlist file, including any partial-download sibling, in download_dir."""
    total = 0
    try:
        for path in Path(download_dir).glob(f"{file_name}*"):
            if path.is_file():
                total += path.stat().st_size
    except OSError as e:
        logger.debug("Could not size modlist file in %s: %s", download_dir, e)
    return total


class ProgressTicker:
    """Keeps the display moving while the CLI is quiet.

    Covers the .wabbajack fetch (no progress lines at all) and per-file download rows
    (reported every few seconds).
    """

    def __init__(self, parser, download_dir: str, emit: Callable[[object], None]):
        self._parser = parser
        self._download_dir = download_dir
        self._emit = emit
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.wait(POLL_SECONDS):
            changed = False
            name = self._parser.modlist_fetch
            if name:
                size = fetched_bytes(self._download_dir, name)
                changed = self._parser.note_modlist_fetch_bytes(size)
            changed = self._parser.tick() or changed
            if changed:
                self._emit(self._parser.get_state())
