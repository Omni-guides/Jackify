"""
Shared VNV post-install automation controller for all GUI workflows.

Handles VNV detection, user confirmation, premium/non-premium download paths,
worker thread management, and completion callbacks.
"""

import logging
import warnings
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QThread, Signal, Slot, QObject
from PySide6.QtWidgets import QMessageBox, QWidget

logger = logging.getLogger(__name__)

# Keep references to orphaned workers alive until they finish naturally.
# If cleanup() is called while a long-running worker (e.g. BSA decompression)
# is still going, dropping self._worker would let GC destroy a running QThread.
_ORPHANED_WORKERS: set = set()


class _VNVWorker(QThread):
    """Background thread for VNV automation."""
    progress_update = Signal(str)
    completed = Signal(bool, str)  # (success, error_message)

    def __init__(self, modlist_name, install_path, game_root, ttw_installer_path):
        super().__init__()
        self._modlist_name = modlist_name
        self._install_path = install_path
        self._game_root = game_root
        self._ttw_installer_path = ttw_installer_path

    def run(self):
        try:
            from jackify.backend.services.vnv_integration_helper import run_vnv_automation_if_applicable
            automation_ran, error = run_vnv_automation_if_applicable(
                modlist_name=self._modlist_name,
                modlist_install_location=self._install_path,
                game_root=self._game_root,
                ttw_installer_path=self._ttw_installer_path,
                progress_callback=self.progress_update.emit,
                manual_file_callback=None,
                confirmation_callback=lambda desc: True,
            )
            self.completed.emit(error is None, error or "")
        except Exception as e:
            import traceback
            self.completed.emit(False, f"{e}\n{traceback.format_exc()}")


class VNVAutomationController(QObject):
    """
    Single entry point for VNV post-install automation across all GUI workflows.

    Usage in any screen's on_configuration_complete:

        from ..services.vnv_automation_controller import VNVAutomationController
        controller = VNVAutomationController()
        if controller.attempt(
            parent=self,
            modlist_name=modlist_name,
            install_dir=install_dir,
            on_progress=self._safe_append_text,
            on_complete=lambda success, error: self._on_vnv_done(success, error),
        ):
            # VNV is running, defer success dialog
            return
        # No VNV, show success dialog now
    """

    # Emitted from the watcher background thread; delivered on main thread
    # via auto-queued connection because this object lives on the main thread.
    _worker_start_requested = Signal()

    def __init__(self):
        super().__init__()
        self._worker: Optional[_VNVWorker] = None
        self._manual_manager = None
        self._manual_dialog = None
        self._pending_worker_start: Optional[Callable] = None
        self._on_progress_cb: Optional[Callable] = None
        self._on_complete_cb: Optional[Callable] = None
        self._handle_feedback_cb: Optional[Callable] = None
        self._worker_start_requested.connect(self._dispatch_worker_start)

    def attempt(
        self,
        parent: QWidget,
        modlist_name: str,
        install_dir: str,
        on_progress: Callable[[str], None],
        on_complete: Callable[[bool, str], None],
        begin_feedback: Optional[Callable[[], None]] = None,
        handle_feedback: Optional[Callable[[str], None]] = None,
    ) -> bool:
        """Check for VNV eligibility and start automation if applicable.

        Args:
            parent: Parent QWidget for dialogs
            modlist_name: Name of the modlist
            install_dir: Installation directory path
            on_progress: Called with progress text messages
            on_complete: Called with (success, error_message) when done
            begin_feedback: Optional - start post-install progress UI
            handle_feedback: Optional - update post-install progress UI

        Returns:
            True if VNV automation is starting (caller should defer success dialog)
            False if no VNV needed (caller should show success dialog immediately)
        """
        try:
            from jackify.backend.services.vnv_integration_helper import should_offer_vnv_automation
            from jackify.backend.handlers.path_handler import PathHandler
            from jackify.backend.services.vnv_post_install_service import VNVPostInstallService
            from jackify.backend.services.automated_prefix_service import AutomatedPrefixService

            install_path = Path(install_dir)

            if not should_offer_vnv_automation(modlist_name, install_path):
                return False

            game_paths = PathHandler().find_vanilla_game_paths()
            game_root = game_paths.get('Fallout New Vegas')
            if not game_root:
                logger.debug("VNV automation skipped - FNV game root not found")
                on_progress("VNV automation skipped: Fallout New Vegas path not found")
                return False

            # Check completion status
            vnv_service = VNVPostInstallService(
                modlist_install_location=install_path,
                game_root=game_root,
                ttw_installer_path=AutomatedPrefixService.get_ttw_installer_path(),
            )
            completed = vnv_service.check_already_completed()
            if completed['root_mods'] and completed['4gb_patch'] and completed['bsa_decompressed']:
                logger.info("VNV automation steps already completed")
                return False

            # Confirmation dialog
            from .message_service import MessageService
            reply = MessageService.question(
                parent,
                "VNV Post-Install Automation",
                vnv_service.get_automation_description(),
                critical=False,
                safety_level="medium",
            )
            if reply != QMessageBox.Yes:
                logger.info("User declined VNV automation")
                on_progress("VNV automation skipped by user")
                return False

            ttw_installer_path = AutomatedPrefixService.get_ttw_installer_path()

            # Non-premium path: route 4GB patcher through ManualDownloadManager
            from jackify.backend.services.nexus_auth_service import NexusAuthService
            from jackify.backend.services.nexus_premium_service import NexusPremiumService

            auth_svc = NexusAuthService()
            token = auth_svc.get_auth_token()
            is_premium = False
            if token:
                is_premium, _ = NexusPremiumService().check_premium_status(
                    token, is_oauth=(auth_svc.get_auth_method() == "oauth")
                )

            if not is_premium:
                has_4gb_cache = vnv_service._find_cached_4gb_patcher() is not None
                has_bsa_cache = (
                    vnv_service._find_cached_bsa_mpi() is not None or
                    vnv_service._find_cached_bsa_package() is not None
                )
                if has_4gb_cache and has_bsa_cache:
                    logger.debug("VNV non-premium: required VNV tools already cached, proceeding to worker")
                else:
                    tool_events = vnv_service.get_manual_download_items(include_bsa=not has_bsa_cache)
                    logger.debug("VNV non-premium: tool_events=%d, cache_dir=%s", len(tool_events), vnv_service.cache_dir)
                    if tool_events:
                        if begin_feedback:
                            begin_feedback()
                        self._show_tool_download_dialog(
                            parent, tool_events, vnv_service.cache_dir,
                            modlist_name, install_path, game_root, ttw_installer_path,
                            on_progress, on_complete, handle_feedback,
                        )
                        return True
                    else:
                        # Nexus API unavailable - can't auto-track the download.
                        # Open the mod page so the user can get it manually and inform
                        # them where to place it so the worker finds it next time.
                        logger.warning("VNV non-premium: Nexus API query failed, cannot open download manager")
                        try:
                            import subprocess
                            import os
                            _strip = {"LD_LIBRARY_PATH", "LD_PRELOAD", "QT_PLUGIN_PATH", "QML2_IMPORT_PATH", "PYTHONPATH", "PYTHONHOME"}
                            clean_env = {k: v for k, v in os.environ.items() if k not in _strip}
                            subprocess.Popen(['xdg-open', 'https://www.nexusmods.com/newvegas/mods/62552?tab=files'], env=clean_env, start_new_session=True)
                        except Exception:
                            pass
                        from .message_service import MessageService
                        MessageService.information(
                            parent,
                            "VNV Tools - Manual Download Required",
                            "Jackify could not query the Nexus download URL(s) (check your Nexus login in Settings).\n\n"
                            "Your modlist has been installed successfully.\n\n"
                            "To complete VNV post-install setup, please:\n"
                            "1. Download the '4GB Patcher (Linux/Proton)' from:\n"
                            "   nexusmods.com/newvegas/mods/62552\n\n"
                            "2. Download the BSA Decompressor package from:\n"
                            "   nexusmods.com/newvegas/mods/65854\n\n"
                            f"3. Place the archive(s) in:\n   {vnv_service.cache_dir}\n\n"
                            "4. Re-configure the modlist - Jackify will detect the files automatically.",
                        )
                        return False

            # Premium or all tools already cached - start worker directly
            if begin_feedback:
                begin_feedback()
            self._start_worker(
                parent, modlist_name, install_path, game_root,
                ttw_installer_path, on_progress, on_complete, handle_feedback,
            )
            return True

        except Exception as e:
            logger.error("Failed to start VNV automation: %s", e)
            import traceback
            logger.error("Traceback: %s", traceback.format_exc())
            return False

    def _dispatch_worker_start(self):
        """Slot - always runs on the main thread due to queued signal delivery."""
        if self._pending_worker_start:
            fn = self._pending_worker_start
            self._pending_worker_start = None
            fn()

    def _show_tool_download_dialog(
        self, parent, tool_events, cache_dir,
        modlist_name, install_path, game_root, ttw_installer_path,
        on_progress, on_complete, handle_feedback,
    ):
        """Show ManualDownloadDialog for VNV tools that need manual download."""
        from jackify.backend.services.manual_download_manager import ManualDownloadManager
        from jackify.frontends.gui.dialogs.manual_download_dialog import ManualDownloadDialog
        from jackify.backend.handlers.config_handler import ConfigHandler

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

        def _on_all_done(_completed, _skipped):
            # _check_all_done() runs in the watcher background thread (Python
            # threading.Thread - no Qt event loop).  QTimer.singleShot is
            # unreliable from non-Qt threads.  Instead, emit a signal: because
            # VNVAutomationController was created on the main thread, Qt uses a
            # queued connection automatically and delivers the slot on the main thread.
            self._pending_worker_start = lambda: self._finish_manual_download_flow(
                state,
                parent,
                modlist_name,
                install_path,
                game_root,
                ttw_installer_path,
                on_progress,
                on_complete,
                handle_feedback,
            )
            self._worker_start_requested.emit()

        state = {"done": False}

        manager = ManualDownloadManager(
            modlist_download_dir=cache_dir,
            watch_directory=watch_dir,
            concurrent_limit=2,
            on_all_done=_on_all_done,
        )
        self._manual_manager = manager
        manager.load_items(tool_events, loop_iteration=1)

        dialog = ManualDownloadDialog(
            manager=manager,
            modlist_name="VNV Post-Install Tools",
            watch_directory=watch_dir,
            concurrent_limit=2,
            parent=parent,
        )
        self._manual_dialog = dialog
        dialog.load_items(manager.items)
        dialog.finished.connect(lambda _result: self._cancel_manual_download_flow(on_complete, state))
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _cancel_manual_download_flow(self, on_complete, state: dict) -> None:
        if state["done"]:
            return
        state["done"] = True
        self._stop_manual_download_flow()
        on_complete(False, "")

    def _finish_manual_download_flow(
        self,
        state: dict,
        parent,
        modlist_name,
        install_path,
        game_root,
        ttw_installer_path,
        on_progress,
        on_complete,
        handle_feedback,
    ) -> None:
        if state["done"]:
            return
        state["done"] = True
        self._stop_manual_download_flow()
        self._start_worker(
            parent,
            modlist_name,
            install_path,
            game_root,
            ttw_installer_path,
            on_progress,
            on_complete,
            handle_feedback,
        )

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

    def _start_worker(
        self, parent, modlist_name, install_path, game_root,
        ttw_installer_path, on_progress, on_complete, handle_feedback,
    ):
        """Create and start VNV worker thread.

        Signals are connected to @Slot methods on this QObject (main thread).
        Because VNVAutomationController lives on the main thread, Qt automatically
        uses queued connections for signals emitted from the worker thread,
        guaranteeing that _on_worker_progress and _on_worker_done execute on
        the main thread regardless of which thread the worker emits from.
        """
        self._on_progress_cb = on_progress
        self._on_complete_cb = on_complete
        self._handle_feedback_cb = handle_feedback

        self._worker = _VNVWorker(
            modlist_name, install_path, game_root, ttw_installer_path,
        )
        self._worker.progress_update.connect(self._on_worker_progress)
        self._worker.completed.connect(self._on_worker_done)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.start()

    @Slot(str)
    def _on_worker_progress(self, message: str):
        if self._on_progress_cb:
            self._on_progress_cb(message)
        if self._handle_feedback_cb:
            self._handle_feedback_cb(message)

    @Slot(bool, str)
    def _on_worker_done(self, success: bool, error: str):
        self._worker = None
        cb = self._on_complete_cb
        self._on_complete_cb = None
        self._on_progress_cb = None
        self._handle_feedback_cb = None
        if cb:
            cb(success, error)

    def cleanup(self):
        """Stop worker if running. Call from screen cleanup/hideEvent."""
        self._on_complete_cb = None
        self._on_progress_cb = None
        self._handle_feedback_cb = None
        self._pending_worker_start = None
        self._stop_manual_download_flow()
        if self._worker and self._worker.isRunning():
            # Worker may still be running a long operation (BSA decompression etc).
            # Park it in the global set so the reference outlives this controller.
            worker = self._worker
            _ORPHANED_WORKERS.add(worker)
            worker.finished.connect(lambda w=worker: _ORPHANED_WORKERS.discard(w))
        self._worker = None
