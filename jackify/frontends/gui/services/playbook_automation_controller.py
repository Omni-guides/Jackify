"""
Generic GUI controller for the Modlist Playbook System - replaces `vnv_automation_controller.py`
and `mew_automation_controller.py`, which are near-duplicate ~400-line classes doing the same
confirm -> worker -> manual-download-fallback dance for their own hardcoded services. Any current
or future playbook gets the same treatment here: `find_matching_playbooks()` first (safe, no
consent needed) so the caller only invokes this when there is something to do, then a
`MessageService.question()` dialog built from `build_confirmation_text()` (same wording as the
old services' `get_automation_description()`), then a worker thread running `run_hook()` with
consent already granted, with the same sequential manual-download-dialog-then-retry pattern the
CLI side uses (`playbook_automation.py`), reusing the existing `ManualDownloadDialog`/
`ManualDownloadManager` classes exactly as VNV/MEW do today.
"""
import logging
import warnings
from pathlib import Path
from typing import Callable, List, Optional

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import QMessageBox, QWidget

from jackify.backend.services.playbook.catalog import asset_cache_dir
from jackify.backend.services.playbook.registry import MatchIdentity, PlaybookRegistry
from jackify.backend.services.playbook.runtime import HookRunResult, build_confirmation_text, is_heavy, run_hook
from jackify.backend.services.playbook.steps.base import StepContext

logger = logging.getLogger(__name__)

# Same rationale as vnv_automation_controller.py: a worker may still be running a long operation
# when the screen is torn down, so park it here rather than let GC destroy a running QThread.
_ORPHANED_WORKERS: set = set()


class _PlaybookWorker(QThread):
    """Runs run_hook() with consent already granted - the confirmation dialog already happened
    on the main thread before this worker is started."""
    progress_update = Signal(str)
    completed = Signal(object)  # List[HookRunResult]

    def __init__(self, hook, registry, identity, step_ctx, install_key):
        super().__init__()
        self._hook = hook
        self._registry = registry
        self._identity = identity
        self._step_ctx = step_ctx
        self._install_key = install_key

    def run(self):
        try:
            self.progress_update.emit(f"Running {self._hook} fixes...")
            # Signal emission is thread-safe in Qt - safe to hand straight to steps as their
            # progress sink so live subprocess output (e.g. BSA decompressor percent) reaches
            # the GUI in real time rather than only at the end.
            self._step_ctx.log = self.progress_update.emit
            results = run_hook(
                self._hook, self._registry, self._identity, self._step_ctx, self._install_key,
                consent_callback=lambda pb: True,
            )
            self.completed.emit(results)
        except Exception as e:
            logger.error("Playbook worker failed: %s", e, exc_info=True)
            self.completed.emit([])


class PlaybookAutomationController(QObject):
    """
    Single entry point for playbook automation across all GUI workflows.

    Usage in a screen, after its background config/install thread has finished (never from
    inside that thread - see hook_wiring.py's `defer_playbooks` docstring):

        controller = PlaybookAutomationController()
        if controller.attempt(
            parent=self, hook="post_configure", identity=identity, step_ctx=step_ctx,
            install_key=install_key, on_progress=self._safe_append_text,
            on_complete=lambda success, error: self._on_playbook_done(success, error),
        ):
            return  # running, defer success dialog
        # nothing to do, show success dialog now
    """

    _worker_start_requested = Signal()

    def __init__(self):
        super().__init__()
        self._worker: Optional[_PlaybookWorker] = None
        self._manual_manager = None
        self._manual_dialog = None
        self._pending_worker_start: Optional[Callable] = None
        self._on_progress_cb: Optional[Callable] = None
        self._on_complete_cb: Optional[Callable] = None
        self._on_offer_flow_cb: Optional[Callable[[str], None]] = None
        self._handle_feedback_cb: Optional[Callable[[str], None]] = None
        self._worker_start_requested.connect(self._dispatch_worker_start)
        # Populated by the most recent attempt() run - callers read this after on_complete
        # fires to surface step failures in the end-of-install verification report.
        self.last_failure_notices: List[str] = []

    def attempt(
        self,
        parent: QWidget,
        hook: str,
        registry: PlaybookRegistry,
        identity: MatchIdentity,
        step_ctx: StepContext,
        install_key: str,
        on_progress: Callable[[str], None],
        on_complete: Callable[[bool, str], None],
        on_offer_flow: Optional[Callable[[str], None]] = None,
        begin_feedback: Optional[Callable[[], None]] = None,
        handle_feedback: Optional[Callable[[str], None]] = None,
    ) -> bool:
        """
        Check for matching playbooks and start automation if the user consents.

        Returns:
            True if a heavy playbook is running (caller should defer its success dialog)
            False if nothing needed consent (light playbooks already applied silently, or
                nothing matched, or the user declined)
        """
        from jackify.backend.services.playbook.runtime import find_matching_playbooks

        self.last_failure_notices = []
        try:
            matches = find_matching_playbooks(hook, registry, identity, step_ctx)
        except Exception as e:
            logger.error("Playbook matching failed: %s", e, exc_info=True)
            return False
        if not matches:
            return False

        heavy = [pb for pb in matches if is_heavy(pb)]
        if not heavy:
            # Only light playbooks matched - apply them now, silently, no dialog needed.
            try:
                results = run_hook(hook, registry, identity, step_ctx, install_key, consent_callback=lambda pb: True)
                for result in results:
                    self.last_failure_notices.extend(result.failure_notices)
            except Exception as e:
                logger.error("Playbook auto-apply failed: %s", e, exc_info=True)
            return False

        from .message_service import MessageService

        for playbook in heavy:
            playbook_hook = playbook.hook or "post_configure"
            steps_for_hook = [s for s in playbook.steps if (s.hook or playbook_hook) == hook]
            reply = MessageService.question(
                parent, playbook.display_name, build_confirmation_text(playbook, steps_for_hook),
                critical=False, safety_level="medium",
            )
            if reply != QMessageBox.Yes:
                on_progress(f"{playbook.display_name} skipped by user")
                continue

            self._on_progress_cb = on_progress
            self._on_complete_cb = on_complete
            self._on_offer_flow_cb = on_offer_flow
            self._handle_feedback_cb = handle_feedback
            if begin_feedback:
                begin_feedback()
            self._start_worker(parent, hook, registry, identity, step_ctx, install_key)
            return True

        return False

    def _dispatch_worker_start(self):
        if self._pending_worker_start:
            fn = self._pending_worker_start
            self._pending_worker_start = None
            fn()

    def _start_worker(self, parent, hook, registry, identity, step_ctx, install_key):
        self._worker = _PlaybookWorker(hook, registry, identity, step_ctx, install_key)
        self._worker.progress_update.connect(self._on_worker_progress)
        self._worker.completed.connect(
            lambda results: self._on_worker_done(parent, hook, registry, identity, step_ctx, install_key, results)
        )
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.start()

    @Slot(str)
    def _on_worker_progress(self, message: str):
        if self._on_progress_cb:
            self._on_progress_cb(message)
        if self._handle_feedback_cb:
            self._handle_feedback_cb(message)

    def _on_worker_done(self, parent, hook, registry, identity, step_ctx, install_key, results: List[HookRunResult]):
        self._worker = None
        manual_downloads = [item for r in results for item in r.manual_downloads]
        if manual_downloads:
            self._show_manual_download_dialog(
                parent, manual_downloads[0], hook, registry, identity, step_ctx, install_key,
            )
            return

        for result in results:
            for flow in result.offered_flows:
                if self._on_offer_flow_cb:
                    self._on_offer_flow_cb(flow)
            self.last_failure_notices.extend(result.failure_notices)
            for notice in result.failure_notices:
                if self._on_progress_cb:
                    self._on_progress_cb(f"Playbook step issue: {notice}")

        self._finish(True, "")

    def _show_manual_download_dialog(self, parent, item, hook, registry, identity, step_ctx, install_key):
        """One tool's manual-download fallback (sequential, per the accepted v0.8 UX decision -
        no combined pre-flight scan across every tool a playbook might need)."""
        metadata = item.get("manual_download_metadata")
        tool_id = item.get("tool_id")
        if not metadata or not tool_id:
            static = item.get("manual_download")
            if static is not None and self._on_progress_cb:
                self._on_progress_cb(f"{item.get('tool_display_name', 'Tool')}: {static.instructions}")
            self._finish(False, "")
            return

        from jackify.backend.services.manual_download_manager import ManualDownloadManager
        from jackify.frontends.gui.dialogs.manual_download_dialog import ManualDownloadDialog
        from jackify.backend.handlers.config_handler import ConfigHandler

        cache_dir = asset_cache_dir(tool_id)
        cfg_watch = ConfigHandler().get("manual_download_watch_directory", None)
        watch_dir = None
        if cfg_watch:
            p = Path(str(cfg_watch)).expanduser()
            if p.is_dir():
                watch_dir = p
        if watch_dir is None:
            import os
            xdg = os.environ.get('XDG_DOWNLOAD_DIR', '')
            xdg_path = Path(xdg).expanduser() if xdg else None
            watch_dir = xdg_path if (xdg_path and xdg_path.is_dir()) else Path.home() / 'Downloads'

        state = {"done": False}

        def _on_all_done(_completed, _skipped):
            self._pending_worker_start = lambda: self._retry_after_manual_download(
                state, parent, hook, registry, identity, step_ctx, install_key,
            )
            self._worker_start_requested.emit()

        manager = ManualDownloadManager(
            modlist_download_dir=cache_dir, watch_directory=watch_dir,
            concurrent_limit=1, on_all_done=_on_all_done,
        )
        self._manual_manager = manager
        manager.load_items([metadata], loop_iteration=1)

        dialog = ManualDownloadDialog(
            manager=manager, modlist_name=f"{item.get('tool_display_name', 'Tool')} Download",
            watch_directory=watch_dir, concurrent_limit=1, parent=parent,
        )
        self._manual_dialog = dialog
        dialog.load_items(manager.items)
        dialog.finished.connect(lambda _result: self._cancel_manual_download_flow(state))
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _cancel_manual_download_flow(self, state: dict) -> None:
        if state["done"]:
            return
        state["done"] = True
        self._stop_manual_download_flow()
        self._finish(False, "")

    def _retry_after_manual_download(self, state, parent, hook, registry, identity, step_ctx, install_key) -> None:
        if state["done"]:
            return
        state["done"] = True
        self._stop_manual_download_flow()
        self._start_worker(parent, hook, registry, identity, step_ctx, install_key)

    def _stop_manual_download_flow(self) -> None:
        dialog = self._manual_dialog
        manager = self._manual_manager
        self._manual_dialog = None
        self._manual_manager = None
        if dialog is not None:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                try:
                    dialog.finished.disconnect()
                except Exception:
                    pass
            try:
                dialog.close()
            except Exception:
                pass
        if manager is not None:
            try:
                manager.stop()
            except Exception:
                pass

    def _finish(self, success: bool, error: str) -> None:
        cb = self._on_complete_cb
        self._on_complete_cb = None
        self._on_progress_cb = None
        self._on_offer_flow_cb = None
        self._handle_feedback_cb = None
        if cb:
            cb(success, error)

    def cleanup(self):
        """Stop worker if running. Call from screen cleanup/hideEvent."""
        self._on_complete_cb = None
        self._on_progress_cb = None
        self._on_offer_flow_cb = None
        self._handle_feedback_cb = None
        self._pending_worker_start = None
        self._stop_manual_download_flow()
        if self._worker and self._worker.isRunning():
            worker = self._worker
            _ORPHANED_WORKERS.add(worker)
            worker.finished.connect(lambda w=worker: _ORPHANED_WORKERS.discard(w))
        self._worker = None
