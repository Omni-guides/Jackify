from __future__ import annotations

"""Internal runtime methods for ManualDownloadManager."""

import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Optional

from jackify.backend.services.download_watcher_service import normalize_download_name
from jackify.backend.services.file_validator_service import ValidationResult

logger = logging.getLogger(__name__)


class ManualDownloadManagerRuntimeMixin:
    """Mixin containing browser/watcher/validation runtime methods."""
    def _open_next_tabs(self, force_user_start: bool = False) -> None:
        to_open = []
        to_notify = []
        with self._lock:
            if not self._started or self._paused:
                return
            if self._startup_precheck_pending > 0 and not force_user_start:
                return
            while self._active_tabs < self._limit:
                item = self._next_pending(include_retry=force_user_start)
                if item is None:
                    break
                if force_user_start and item.needs_user_retry:
                    item.needs_user_retry = False
                    item.error_message = None
                item.status = 'browser_opened'
                self._active_tabs += 1
                to_notify.append(item)
                to_open.append(item)
            active_tabs = self._active_tabs
            pending_left = sum(1 for i in self._items if i.status == 'pending')
        if to_open:
            self._diag(
                "MDL-1010",
                "Opening next manual download tab window",
                opening_count=len(to_open),
                active_tabs=active_tabs,
                pending_after_schedule=pending_left,
            )
        # Notify outside the lock to prevent GUI callbacks from re-entering manager state.
        for item in to_notify:
            self._notify(item)
        # Open browser tabs outside the lock so Popen/fork doesn't stall lock holders
        for item in to_open:
            opened, error_message = self._open_browser(item)
            if opened:
                continue
            item_to_notify: Optional[DownloadItem] = None
            with self._lock:
                # Revert failed launch so the row does not falsely remain "Browser Opened".
                current = self._item_by_name(item.file_name)
                if current and current.status == 'browser_opened':
                    current.status = 'pending'
                    if self._active_tabs > 0:
                        self._active_tabs -= 1
                    current.error_message = error_message
                    if error_message and "No URL available" in error_message:
                        current.needs_user_retry = True
                    item_to_notify = current
            if item_to_notify is not None:
                self._notify(item_to_notify)
            self._diag(
                "MDL-9001",
                "Automatic browser launch failed for manual download item",
                level="warning",
                file_name=item.file_name,
                reason=error_message or "unknown launcher failure",
            )

    def _next_pending(self, include_retry: bool = False) -> Optional[DownloadItem]:
        for item in self._items:
            if item.status != 'pending':
                continue
            if item.needs_user_retry and not include_retry:
                continue
            return item
        return None

    _BROWSER_OPEN_COOLDOWN = 30.0  # seconds before the same file's URL may be re-opened

    def _open_browser(self, item: DownloadItem) -> tuple[bool, Optional[str]]:
        url = item.nexus_url
        if not url:
            msg = "No URL available for manual download item"
            logger.warning(f"{msg}: {item.file_name}")
            return False, msg

        now = time.monotonic()
        last = self._last_browser_open.get(item.file_name, 0.0)
        if now - last < self._BROWSER_OPEN_COOLDOWN:
            remaining = int(self._BROWSER_OPEN_COOLDOWN - (now - last))
            logger.warning(
                f"Suppressed duplicate browser open for {item.file_name} "
                f"(cooldown: {remaining}s remaining)"
            )
            return True, None

        # Linux desktop launch fallbacks. xdg-open should cover most environments,
        # but keep alternates for distributions where handlers differ.
        launch_cmds = (
            ['xdg-open', url],
            ['gio', 'open', url],
            ['sensible-browser', url],
        )

        # Strip AppImage library path overrides before launching external processes.
        # Inheriting LD_LIBRARY_PATH causes xdg-open/kde-open to load bundled Qt
        # libs, which produces symbol version mismatches on distributions that ship
        # a different Qt version than the one bundled in the AppImage.
        clean_env = os.environ.copy()
        for var in ('LD_LIBRARY_PATH', 'LD_PRELOAD'):
            clean_env.pop(var, None)

        launch_errors: list[str] = []
        for cmd in launch_cmds:
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    start_new_session=True,
                    env=clean_env,
                )
            except OSError as e:
                launch_errors.append(f"{cmd[0]} not available: {e}")
                continue

            try:
                rc = proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                # Launcher still running after handoff window; treat as success.
                self._last_browser_open[item.file_name] = time.monotonic()
                logger.debug(f"Opened browser for: {item.file_name} via {cmd[0]}")
                return True, None

            if rc == 0:
                self._last_browser_open[item.file_name] = time.monotonic()
                logger.debug(f"Opened browser for: {item.file_name} via {cmd[0]}")
                return True, None

            stderr_tail = ""
            try:
                stderr_tail = (proc.stderr.read() or b"").decode("utf-8", errors="replace").strip()
            except Exception:
                stderr_tail = ""
            launch_errors.append(f"{cmd[0]} exited {rc}{(': ' + stderr_tail) if stderr_tail else ''}")

        msg = f"Could not open browser automatically for {item.file_name}"
        logger.error(f"{msg}. Launch attempts: {' | '.join(launch_errors)}")
        return False, msg

    def _on_candidate(self, path: Path, hint: dict, from_startup_precheck: bool = False) -> bool:
        """Called by watcher after debounce when a potential match is found."""
        file_name = hint.get('file_name', '')
        item_to_notify: Optional[DownloadItem] = None
        reject_reason = ""
        had_browser_slot = False
        with self._lock:
            item = self._item_by_name(file_name)
            if item is None:
                reject_reason = "unknown_item"
            elif item.status in ('complete', 'skipped', 'deferred'):
                reject_reason = f"terminal_status:{item.status}"
            elif item.status == 'validating':
                reject_reason = "already_validating"
            if reject_reason:
                self._diag(
                    "MDL-1022",
                    "Candidate ignored",
                    file_name=file_name or "missing",
                    source_path=str(path),
                    from_precheck=from_startup_precheck,
                    reason=reject_reason,
                )
                return False
            had_browser_slot = item.status == 'browser_opened'
            item.status = 'validating'
            item_to_notify = item

        if item_to_notify is not None:
            self._notify(item_to_notify)
        self._diag(
            "MDL-1020",
            "Candidate queued for validation",
            file_name=file_name or "missing",
            source_path=str(path),
            from_precheck=from_startup_precheck,
        )

        # Pass the engine's canonical filename as dest_name so that if the browser
        # stripped a leading dot, the file is renamed correctly on move.
        canonical_name = hint.get('file_name') or None
        dest_name = canonical_name if canonical_name and canonical_name != path.name else None
        self._validator.validate_async(
            file_path=path,
            expected_hash=hint.get('expected_hash', ''),
            modlist_download_dir=self._dl_dir,
            on_result=lambda result, dest: self._on_validation_result(
                file_name,
                result,
                dest,
                from_startup_precheck=from_startup_precheck,
                had_browser_slot=had_browser_slot,
            ),
            dest_name=dest_name,
        )
        return True

    def _on_validation_result(
        self,
        file_name: str,
        result: ValidationResult,
        dest: Optional[Path],
        from_startup_precheck: bool = False,
        had_browser_slot: bool = False,
    ) -> None:
        item_to_notify: Optional[DownloadItem] = None
        validation_failed = False
        completed_now = False
        precheck_ready = False
        expected_hash = ""
        mod_id = 0
        file_id = 0
        source_path = str(result.file_path) if getattr(result, "file_path", None) else ""
        computed_hash = (result.computed_hash or "").lower() if result.computed_hash else ""
        with self._lock:
            item = self._item_by_name(file_name)
            if item is None:
                return
            expected_hash = (item.expected_hash or "").lower()
            mod_id = item.mod_id
            file_id = item.file_id
            if result.matches and dest:
                item.status = 'complete'
                item.local_path = str(dest)
                item.needs_user_retry = False
                if had_browser_slot and self._active_tabs > 0:
                    self._active_tabs -= 1
                item_to_notify = item
                completed_now = True
            else:
                msg = result.error or f"Hash mismatch (got {result.computed_hash})"
                # If the user deferred this item while validation was in-flight,
                # skip_item already decremented _active_tabs and set status='deferred'.
                # Preserve the defer; don't double-decrement or re-open a browser tab.
                if item.status == 'deferred':
                    item_to_notify = item
                    validation_failed = True
                else:
                    # Revert to pending so the sliding window can re-open a browser tab.
                    item.status = 'pending'
                    item.error_message = msg
                    logger.warning(f"Validation failed for {file_name}: {msg}")
                    if had_browser_slot and self._active_tabs > 0:
                        self._active_tabs -= 1
                    item_to_notify = item
                    validation_failed = True
            if from_startup_precheck and self._startup_precheck_pending > 0:
                self._startup_precheck_pending -= 1
                precheck_ready = self._startup_precheck_pending == 0

        if item_to_notify is not None:
            self._notify(item_to_notify)
        if result.file_path:
            self._watcher.release_path(result.file_path)
        if completed_now:
            self._diag(
                "MDL-1021",
                "Archive validated and accepted",
                file_name=file_name,
                source_path=source_path or "missing",
                destination_path=str(dest) if dest else "missing",
                expected_hash=expected_hash or "missing",
                computed_hash=computed_hash or "missing",
                from_precheck=from_startup_precheck,
                mod_id=mod_id,
                file_id=file_id,
            )
            self._maybe_log_progress_summary()
        if precheck_ready:
            self._diag("MDL-1017", "Startup precheck validation complete; opening tabs")
            self._open_next_tabs()
        if validation_failed:
            self._refresh_watcher_pending_items()
            if not from_startup_precheck:
                self._open_next_tabs()
            self._diag(
                "MDL-9002",
                "Archive validation failed",
                level="warning",
                file_name=file_name,
                expected_hash=expected_hash or "missing",
                computed_hash=computed_hash or "missing",
                source_path=source_path or "missing",
                mod_id=mod_id,
                file_id=file_id,
                from_precheck=from_startup_precheck,
                reason=result.error or "hash mismatch",
            )
            return

        # Update watcher pending list (remove completed item, keep other in-flight items).
        self._refresh_watcher_pending_items()
        if not from_startup_precheck:
            self._open_next_tabs()
        self._check_all_done()

    def _check_all_done(self) -> None:
        with self._lock:
            remaining = [i for i in self._items if i.status not in ('complete', 'deferred', 'skipped', 'error')]
            if remaining:
                return
            completed = sum(1 for i in self._items if i.status == 'complete')
            skipped = sum(1 for i in self._items if i.status in ('deferred', 'skipped'))

        self._diag("MDL-1011", "Manual download phase completed", completed=completed, skipped=skipped)
        if self._on_all_done:
            self._on_all_done(completed, skipped)
        if self._on_send_continue:
            self._diag("MDL-1012", "Sending continue command to engine")
            self._on_send_continue()

    def _item_by_name(self, file_name: str) -> Optional[DownloadItem]:
        for item in self._items:
            if item.file_name == file_name:
                return item
        return None

    def _refresh_watcher_pending_items(self) -> None:
        """Keep watcher tracking all non-terminal items, not only pure 'pending' ones."""
        with self._lock:
            pending_items = [
                {'file_name': i.file_name, 'expected_hash': i.expected_hash, 'expected_size': i.expected_size}
                for i in self._items
                if i.status not in ('complete', 'error')
            ]
            pending_count = len(pending_items)
            sample_pending = [i['file_name'] for i in pending_items[:5]]
        self._watcher.set_pending_items(pending_items)
        self._diag(
            "MDL-1019",
            "Watcher pending list refreshed",
            pending_count=pending_count,
            pending_sample=json.dumps(sample_pending, ensure_ascii=True),
        )

    def _ingest_existing_files(self) -> int:
        """
        Pre-check watch/modlist directories for already-present archives so users
        do not need to re-download files that already exist.
        """
        dirs: list[Path] = []
        if self._watch_dir.is_dir():
            dirs.append(self._watch_dir)
        if self._dl_dir.is_dir() and self._dl_dir != self._watch_dir:
            dirs.append(self._dl_dir)
        if not dirs:
            return 0

        existing_files: list[Path] = []
        for d in dirs:
            try:
                for p in d.iterdir():
                    if p.is_file() and p.suffix not in ('.part', '.crdownload', '.tmp'):
                        existing_files.append(p)
            except OSError as e:
                logger.warning(f"[MDL-9021] Precheck scan error: dir={d} reason={e}")
                continue

        if not existing_files:
            self._diag("MDL-1023", "Startup precheck found no candidate files", scan_dirs=len(dirs))
            return 0

        exact_map: dict[str, Path] = {}
        normalized_map: dict[str, Path] = {}
        for p in existing_files:
            exact_map.setdefault(p.name.lower(), p)
            normalized_map.setdefault(normalize_download_name(p.name), p)

        with self._lock:
            targets = [
                {'file_name': i.file_name, 'expected_hash': i.expected_hash, 'expected_size': i.expected_size}
                for i in self._items
                if i.status not in ('complete', 'error')
            ]

        self._diag(
            "MDL-1024",
            "Startup precheck scan summary",
            scan_dirs=len(dirs),
            discovered_files=len(existing_files),
            pending_targets=len(targets),
            discovered_sample=json.dumps([p.name for p in existing_files[:5]], ensure_ascii=True),
            target_sample=json.dumps([t.get('file_name', '') for t in targets[:5]], ensure_ascii=True),
        )

        matched = 0
        used_paths: set[Path] = set()
        for hint in targets:
            name = hint['file_name']
            exact = exact_map.get(name.lower())
            if exact is None:
                exact = normalized_map.get(normalize_download_name(name))
            if exact is None or exact in used_paths:
                continue
            used_paths.add(exact)
            if self._on_candidate(exact, hint, from_startup_precheck=True):
                matched += 1

        if matched:
            logger.info(f"[MDL-1025] Startup precheck queued {matched} archive(s) for validation")
        else:
            self._diag("MDL-1025", "Startup precheck found zero exact filename matches")
        return matched

    def reopen_item(self, file_name: str) -> bool:
        """Re-open a specific item's URL (e.g. if user closed browser tab accidentally)."""
        notify_item: Optional[DownloadItem] = None
        with self._lock:
            item = self._item_by_name(file_name)
            if item is None:
                return False
            if item.status in ('complete', 'skipped'):
                return False
            if item.status != 'browser_opened':
                item.status = 'browser_opened'
                item.needs_user_retry = False
                self._active_tabs += 1
                notify_item = item
        if notify_item is not None:
            self._notify(notify_item)

        if item is None:
            return False
        opened, error = self._open_browser(item)
        if not opened:
            revert_item: Optional[DownloadItem] = None
            with self._lock:
                current = self._item_by_name(file_name)
                if current is not None and current.status == 'browser_opened':
                    current.status = 'pending'
                    current.needs_user_retry = True
                    if self._active_tabs > 0:
                        self._active_tabs -= 1
                    revert_item = current
            if revert_item is not None:
                self._notify(revert_item)
            self._diag(
                "MDL-9011",
                "Manual reopen failed",
                level="warning",
                file_name=file_name,
                reason=error or "unknown launcher failure",
            )
            return False
        self._diag("MDL-1018", "Manual item URL re-opened by user", file_name=file_name)
        return True

    def _maybe_log_progress_summary(self) -> None:
        with self._lock:
            complete = sum(1 for i in self._items if i.status == 'complete')
            skipped = sum(1 for i in self._items if i.status in ('deferred', 'skipped'))
            pending = sum(1 for i in self._items if i.status == 'pending')
            validating = sum(1 for i in self._items if i.status == 'validating')
            opened = sum(1 for i in self._items if i.status == 'browser_opened')
            total = len(self._items)
        if complete == self._last_progress_log_completed:
            return
        if complete in (1, total) or complete % 10 == 0:
            self._last_progress_log_completed = complete
            self._diag(
                "MDL-1013",
                "Manual download progress summary",
                total=total,
                complete=complete,
                browser_opened=opened,
                validating=validating,
                pending=pending,
                skipped=skipped,
                needs_retry=sum(1 for i in self._items if i.needs_user_retry),
            )

    def _diag(self, code: str, message: str, level: str = "info", **ctx) -> None:
        details = " ".join(f"{k}={v}" for k, v in ctx.items())
        text = f"[{code}] run={self._run_id} {message}"
        if details:
            text = f"{text} | {details}"
        if level == "warning":
            logger.warning(text)
        elif level == "error":
            logger.error(text)
        else:
            logger.info(text)

    def _notify(self, item: DownloadItem) -> None:
        if self._on_item_updated:
            try:
                self._on_item_updated(item)
            except Exception as e:
                logger.debug(f"on_item_updated callback error: {e}")
