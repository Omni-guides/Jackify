"""
Orchestrates the manual download workflow:
- Maintains queue of pending items
- Opens browser tabs (sliding window, N concurrent)
- Coordinates directory watcher and file validator
- Sends continue command to engine when all items are done
"""

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, Optional

from jackify.backend.services.download_watcher_service import DownloadWatcherService, WatcherConfig
from jackify.backend.services.file_validator_service import FileValidatorService
from jackify.backend.services.manual_download_manager_api_mixin import ManualDownloadManagerApiMixin
from jackify.backend.services.manual_download_manager_runtime_mixin import ManualDownloadManagerRuntimeMixin

logger = logging.getLogger(__name__)

STATUS = Literal["pending", "browser_opened", "validating", "complete", "deferred", "skipped", "error"]

def _get_state_file() -> Path:
    from jackify.shared.paths import get_jackify_data_dir
    return get_jackify_data_dir() / 'manual_download_state.json'


@dataclass
class DownloadItem:
    file_name: str
    nexus_url: str
    expected_hash: str
    expected_size: int
    mod_name: str
    mod_id: int = 0
    file_id: int = 0
    index: int = 0
    total: int = 0
    loop_iteration: int = 1
    status: STATUS = "pending"
    local_path: Optional[str] = None
    error_message: Optional[str] = None
    needs_user_retry: bool = False

    @classmethod
    def from_event(cls, evt: dict, loop_iteration: int = 1) -> 'DownloadItem':
        # Engine historically emitted `nexus_url`, but manual-only/external sources
        # may arrive as generic URL fields depending on engine version.
        source_url = (
            evt.get('nexus_url')
            or evt.get('download_url')
            or evt.get('manual_url')
            or evt.get('url')
            or ''
        )
        item = cls(
            file_name=evt.get('file_name', ''),
            nexus_url=source_url,
            expected_hash=evt.get('expected_hash', ''),
            expected_size=evt.get('expected_size', 0),
            mod_name=evt.get('mod_name', evt.get('file_name', '')),
            mod_id=evt.get('mod_id', 0),
            file_id=evt.get('file_id', 0),
            index=evt.get('index', 0),
            total=evt.get('total', 0),
            loop_iteration=loop_iteration,
        )
        if not item.nexus_url:
            # Engine contract says nexus_url should be present and non-empty.
            # If missing, keep this item out of auto-open rotation and require
            # explicit user attention/manual recovery.
            item.needs_user_retry = True
            item.error_message = "Malformed manual_download_required event: missing nexus_url"
        return item


class ManualDownloadManager(ManualDownloadManagerApiMixin, ManualDownloadManagerRuntimeMixin):
    """
    Manages the full manual download workflow for one engine session.

    Usage:
        manager = ManualDownloadManager(
            modlist_download_dir=Path(...),
            watch_directory=Path(...),
            concurrent_limit=2,
            on_item_updated=my_callback,
            on_send_continue=installer_thread.send_continue,
        )
        manager.load_items(event_list, loop_iteration=1)
        manager.start()
        # ... user downloads files ...
        # manager sends continue automatically when all done
        manager.stop()
    """

    def __init__(
        self,
        modlist_download_dir: Path,
        watch_directory: Path,
        concurrent_limit: int = 2,
        on_item_updated: Optional[Callable[[DownloadItem], None]] = None,
        on_send_continue: Optional[Callable[[], None]] = None,
        on_all_done: Optional[Callable[[int, int], None]] = None,
    ):
        self._dl_dir = modlist_download_dir
        self._watch_dir = watch_directory
        self._limit = max(1, min(5, concurrent_limit))
        self._on_item_updated = on_item_updated
        self._on_send_continue = on_send_continue
        self._on_all_done = on_all_done

        self._items: list[DownloadItem] = []
        self._lock = threading.Lock()
        self._active_tabs = 0
        self._paused = False
        self._started = False
        self._startup_precheck_pending = 0
        self._run_id = f"mdl-{int(time.time())}-{id(self) % 10000}"
        self._last_progress_log_completed = -1
        self._last_browser_open: dict[str, float] = {}  # file_name -> monotonic timestamp

        additional = [modlist_download_dir] if modlist_download_dir != watch_directory else []
        config = WatcherConfig(watch_directory=watch_directory, additional_dirs=additional)
        self._watcher = DownloadWatcherService(config, self._on_candidate)
        self._validator = FileValidatorService(max_workers=2)
