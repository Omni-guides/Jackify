from __future__ import annotations

"""Public API methods for ManualDownloadManager."""

import json
from typing import Optional


class ManualDownloadManagerApiMixin:
    """Mixin containing public manager API methods and status properties."""
    def load_items(self, events: list[dict], loop_iteration: int = 1) -> None:
        """
        Merge a new batch of engine events into the existing item list.

        On loop_iteration > 1, engine only emits still-missing files. Items NOT
        in the new batch that were pending are confirmed present by the engine
        (they passed its rescan) and are marked complete. Genuinely new items
        (edge case) are appended. active_tabs resets so the sliding window
        opens fresh tabs for the remaining items.
        """
        with self._lock:
            existing_map = {item.file_name: item for item in self._items}
            new_batch_names = {evt.get('file_name', '') for evt in events}

            # Items the engine confirmed are now present (not in new batch, were pending)
            for item in self._items:
                if item.file_name not in new_batch_names and item.status not in ('complete', 'deferred', 'skipped', 'error'):
                    item.status = 'complete'
                    item.needs_user_retry = False

            # Recheck loop: clear temporary defer state for still-missing files so they can
            # re-enter active browser rotation in the new iteration.
            if loop_iteration > 1:
                for item in self._items:
                    if item.file_name in new_batch_names and item.status in ('deferred', 'skipped'):
                        item.status = 'pending'
                        item.needs_user_retry = False
                        item.error_message = None

            # Add items genuinely not seen before (first iteration, or edge case)
            for evt in events:
                name = evt.get('file_name', '')
                if name not in existing_map:
                    # Local import avoids module-load circular dependency with manager class.
                    from jackify.backend.services.manual_download_manager import DownloadItem

                    new_item = DownloadItem.from_event(evt, loop_iteration)
                    self._items.append(new_item)
                    if not new_item.nexus_url:
                        self._diag(
                            "MDL-9012",
                            "Engine manual-download event missing required nexus_url",
                            level="error",
                            file_name=new_item.file_name or "missing",
                            loop_iteration=loop_iteration,
                            mod_id=new_item.mod_id,
                            file_id=new_item.file_id,
                        )

            self._active_tabs = 0
            total = len(self._items)
            pending = sum(1 for i in self._items if i.status == 'pending')
            complete = sum(1 for i in self._items if i.status == 'complete')
            skipped = sum(1 for i in self._items if i.status == 'skipped')
            sample_pending = [i.file_name for i in self._items if i.status == 'pending'][:5]
        self._refresh_watcher_pending_items()
        self._diag(
            "MDL-1001",
            "Manual download batch loaded",
            loop_iteration=loop_iteration,
            batch_size=len(events),
            total_items=total,
            pending=pending,
            complete=complete,
            skipped=skipped,
            pending_sample=json.dumps(sample_pending, ensure_ascii=True),
        )

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
        self._diag(
            "MDL-1002",
            "Manual download watcher started",
            watch_dir=str(self._watch_dir),
            downloads_dir=str(self._dl_dir),
            concurrent_limit=self._limit,
        )
        self._watcher.start()
        matched = self._ingest_existing_files()
        with self._lock:
            self._startup_precheck_pending = matched
        if matched:
            self._diag("MDL-1003", "Pre-existing archives detected", matched=matched)
            self._diag("MDL-1016", "Deferring tab opening until precheck validation completes", pending_precheck=matched)
        else:
            self._open_next_tabs()

    def stop(self) -> None:
        self._watcher.stop()
        self._validator.shutdown()
        with self._lock:
            self._started = False
            self._startup_precheck_pending = 0
        self._diag("MDL-1009", "Manual download manager stopped")

    def pause(self) -> None:
        with self._lock:
            self._paused = True

    def resume(self) -> None:
        with self._lock:
            self._paused = False
        self._diag("MDL-1008", "Manual download resumed")
        # Explicit user start/resume must open tabs even if startup precheck
        # bookkeeping is still in-flight.
        self._open_next_tabs(force_user_start=True)

    def skip_item(self, file_name: str) -> None:
        item_to_notify: Optional[DownloadItem] = None
        with self._lock:
            for item in self._items:
                if item.file_name == file_name and item.status not in ('complete',):
                    # Only free the browser slot if this item actually held one.
                    # 'pending' items have no slot; 'validating' items still hold
                    # the slot counted when they entered 'browser_opened'.
                    had_slot = item.status in ('browser_opened', 'validating')
                    item.status = 'deferred'
                    if had_slot and self._active_tabs > 0:
                        self._active_tabs -= 1
                    item_to_notify = item
                    break
        if item_to_notify is not None:
            self._notify(item_to_notify)
        self._open_next_tabs()
        self._check_all_done()

    def force_rescan(self) -> None:
        """Re-ingest existing files immediately (Scan Now button)."""
        self._diag("MDL-1026", "Force rescan requested by user")
        self._ingest_existing_files()

    def set_concurrent_limit(self, limit: int) -> None:
        with self._lock:
            self._limit = max(1, min(5, limit))
            applied = self._limit
            started = self._started
        self._diag("MDL-1006", "Manual download concurrency updated", concurrent_limit=applied)
        if started:
            self._open_next_tabs()

    @property
    def items(self) -> list[DownloadItem]:
        with self._lock:
            return list(self._items)

    @property
    def pending_count(self) -> int:
        with self._lock:
            return sum(1 for i in self._items if i.status == 'pending')

    @property
    def complete_count(self) -> int:
        with self._lock:
            return sum(1 for i in self._items if i.status == 'complete')

    @property
    def skipped_count(self) -> int:
        with self._lock:
            return sum(1 for i in self._items if i.status in ('deferred', 'skipped'))
