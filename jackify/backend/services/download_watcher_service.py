"""
Watches a directory for newly downloaded files and matches them against a
list of pending manual download items by lax filename comparison.
"""

import re
import time
import logging
from dataclasses import dataclass, field
from pathlib import Path
from threading import Thread, Event, Lock
from typing import Callable, Optional

from jackify.backend.services.file_validator_service import (
    _XXH64Fallback, _hash_matches_expected, xxhash,
)

logger = logging.getLogger(__name__)


def _as_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def normalize_download_name(name: str) -> str:
    """
    Lax comparison form for matching a browser-saved file against engine metadata.

    Nexus filenames can legitimately begin with dots or spaces, which browsers and
    file managers silently drop when saving. Engine metadata also sometimes carries
    a leading numeric prefix (e.g. "1_filename.zip") that the saved file lacks.
    Applied to both sides of a comparison; hash validation remains the real gate.
    """
    normalized = re.sub(r'^[.\s]+', '', (name or "").lower())
    return re.sub(r'^\d+_', '', normalized)


@dataclass
class WatcherConfig:
    watch_directory: Path
    watch_recursive: bool = False
    debounce_seconds: float = 2.0
    additional_dirs: list = field(default_factory=list)


class DownloadWatcherService:
    """
    Monitors a directory for files that match pending download items.

    Caller sets pending_items (list of dicts with at least 'file_name') and
    registers an on_candidate callback that receives (Path, dict) when a
    potential match is detected (after debounce, before hash validation).

    Detection strategy: every scan checks every non-temp file against pending
    items. Files currently being debounced are skipped to avoid duplicate
    threads. When debounce completes (pass or fail), the path is cleared from
    the in-flight set so the next scan can re-detect it if still pending.
    """

    def __init__(self, config: WatcherConfig, on_candidate: Callable[[Path, dict], None]):
        self._config = config
        self._on_candidate = on_candidate
        self._pending_items: list[dict] = []
        self._pending_exact: list[tuple[str, dict]] = []
        self._stop_event = Event()
        self._thread: Optional[Thread] = None
        self._debouncing: set[Path] = set()
        self._debouncing_lock = Lock()
        # (path, size, mtime) -> hash, so a file is hashed once rather than every scan
        self._hash_cache: dict = {}

    def set_pending_items(self, items: list[dict]) -> None:
        """Replace the pending items list. Thread-safe for simple list swap."""
        self._pending_items = list(items)
        self._pending_exact = [
            (str(item.get('file_name', '')).lower(), item)
            for item in self._pending_items
            if item.get('file_name')
        ]

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = Thread(target=self._watch_loop, daemon=True, name='DownloadWatcher')
        self._thread.start()
        logger.debug(f"Download watcher started on: {self._config.watch_directory}")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.debug("Download watcher stopped")

    def _all_watch_dirs(self) -> list[Path]:
        dirs = [self._config.watch_directory]
        dirs.extend(self._config.additional_dirs)
        return [d for d in dirs if d.is_dir()]

    def _scan(self) -> None:
        for watch_dir in self._all_watch_dirs():
            try:
                entries = list(watch_dir.iterdir()) if not self._config.watch_recursive else \
                    [p for p in watch_dir.rglob('*') if p.is_file()]
                for path in entries:
                    if not path.is_file():
                        continue
                    if path.suffix in ('.part', '.crdownload', '.tmp'):
                        continue
                    with self._debouncing_lock:
                        if path in self._debouncing:
                            continue
                    self._check_candidate(path)
            except OSError as e:
                logger.debug(f"Watcher scan error on {watch_dir}: {e}")

    def _check_candidate(self, path: Path) -> None:
        candidate_name = path.name.lower()
        # Exact filename match (case-insensitive).
        for expected_name, item in self._pending_exact:
            if expected_name == candidate_name:
                logger.debug(f"Candidate exact match: {path.name}")
                self._debounce_and_emit(path, item)
                return
        candidate_normalized = normalize_download_name(candidate_name)
        for expected_name, item in self._pending_exact:
            if normalize_download_name(expected_name) == candidate_normalized:
                logger.debug(f"Candidate normalized match: {path.name} -> {expected_name}")
                self._debounce_and_emit(path, item)
                return

        item = self._match_by_content(path)
        if item is not None:
            logger.info(
                "Candidate content match: %s -> %s (filename differs)",
                path.name, item.get('file_name'),
            )
            self._debounce_and_emit(path, item)

    def match_by_content(self, path: Path) -> Optional[dict]:
        """Public entry point for callers outside the live scan loop (e.g. the
        manager's startup precheck / Scan Now button) that need the same
        hash+size fallback the passive watcher already applies."""
        return self._match_by_content(path)

    def _match_by_content(self, path: Path) -> Optional[dict]:
        """Match on hash when the filename does not match any pending item.

        Nexus has changed its archive filename format more than once, and browsers alter names
        while saving, so a correct archive can arrive under a name no normalisation rule can
        map back. Size is checked first because it is a stat() - only an exact size match is
        worth hashing.
        """
        try:
            size = path.stat().st_size
        except OSError:
            return None
        if size <= 0:
            return None

        candidates = [
            item for item in self._pending_items
            if str(item.get('expected_hash', '')).strip()
            and _as_int(item.get('expected_size')) == size
        ]
        if not candidates:
            return None

        key = (str(path), size, self._mtime(path))
        computed = self._hash_cache.get(key)
        if computed is None:
            computed = self._hash_file(path)
            if computed is None:
                return None
            self._hash_cache[key] = computed

        for item in candidates:
            if _hash_matches_expected(computed, str(item.get('expected_hash', ''))):
                return item
        return None

    @staticmethod
    def _mtime(path: Path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0

    @staticmethod
    def _hash_file(path: Path) -> Optional[str]:
        try:
            h = xxhash.xxh64() if xxhash else _XXH64Fallback()
            with open(path, 'rb') as f:
                while True:
                    chunk = f.read(1024 * 1024)
                    if not chunk:
                        break
                    h.update(chunk)
            return h.hexdigest().lower()
        except OSError as e:
            logger.debug("Content match hashing failed for %s: %s", path, e)
            return None

    def _debounce_and_emit(self, path: Path, item: dict) -> None:
        with self._debouncing_lock:
            self._debouncing.add(path)

        expected_size = 0
        try:
            expected_size = int(item.get('expected_size', 0) or 0)
        except (TypeError, ValueError):
            expected_size = 0

        def _wait_and_emit():
            became_stable = False
            try:
                prev_size = -1
                stable_count = 0
                needed = max(1, int(self._config.debounce_seconds / 0.5))
                for _ in range(needed * 4):
                    if self._stop_event.is_set():
                        return
                    time.sleep(0.5)
                    try:
                        size = path.stat().st_size
                    except OSError:
                        return
                    # A slow/in-progress download can hold a constant size for the
                    # debounce window (initial throttle, network stall) and look
                    # stable while still incomplete. Validating it prematurely fails
                    # the hash, reverts the item to pending, and triggers a duplicate
                    # browser tab. Hold off until the file reaches its known size.
                    if expected_size > 0 and size != expected_size:
                        stable_count = 0
                        prev_size = size
                        continue
                    if size == prev_size:
                        stable_count += 1
                        if stable_count >= needed:
                            became_stable = True
                            break
                    else:
                        stable_count = 0
                    prev_size = size
                # Only validate if the file stopped growing. If still downloading,
                # release the debounce lock so the next scan can retry once it finishes.
                if became_stable and path.exists():
                    self._on_candidate(path, item)
                    # Path stays in _debouncing until release_path() is called by the
                    # manager after validation completes, preventing repeated re-fires.
            finally:
                if not became_stable:
                    with self._debouncing_lock:
                        self._debouncing.discard(path)

        Thread(target=_wait_and_emit, daemon=True, name=f'Debounce-{path.name[:20]}').start()

    def release_path(self, path: Path) -> None:
        """Allow the watcher to re-detect a path after validation completes."""
        with self._debouncing_lock:
            self._debouncing.discard(path)

    def _watch_loop(self) -> None:
        while not self._stop_event.is_set():
            self._scan()
            self._stop_event.wait(timeout=1.0)
