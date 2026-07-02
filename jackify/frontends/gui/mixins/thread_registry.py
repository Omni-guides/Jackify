"""
Application-wide QThread registry.

All managed threads are registered here. On app exit `drain_all_threads` disconnects
signals, requests cancellation, and waits for each thread so no QThread outlives its
Python wrapper or fires signals into destroyed widgets.

Usage in threads that are not owned by a ThreadLifecycleMixin widget (e.g. orphaned
workers) call `register_managed_thread` directly. ThreadLifecycleMixin calls it
automatically inside `_park_thread`.
"""

import logging
import warnings

logger = logging.getLogger(__name__)

# Central set of live managed threads. Python objects are kept alive here until their
# QThread.finished signal fires, preventing GC from destroying running threads.
_MANAGED_THREADS: set = set()

# Common signal names to disconnect during drain / park.
_COMMON_SIGNAL_NAMES = (
    "finished",
    "finished_signal",
    "progress_update",
    "workflow_complete",
    "configuration_complete",
    "error_occurred",
    "status_update",
    "output_received",
    "progress_received",
    "installation_finished",
    "cache_ready",
    "update_available",
    "no_update",
    "check_failed",
    "completed",
    "done",
    "name_ready",
    "progress",
)


def register_managed_thread(thread) -> None:
    """Add a QThread to the global registry and auto-remove it when it finishes.

    Safe to call multiple times on the same thread.
    """
    if thread is None:
        return
    _MANAGED_THREADS.add(thread)
    try:
        thread.finished.connect(lambda t=thread: _MANAGED_THREADS.discard(t))
    except Exception:
        pass


def drain_all_threads(timeout_ms: int = 8000) -> None:
    """Disconnect signals, request cancellation, and wait for every registered thread.

    Called on `QApplication.aboutToQuit` and from the emergency cleanup handler.
    Does not call terminate() - threads are given `timeout_ms` to finish gracefully.
    If a thread does not exit in time, a warning is logged and we move on.
    """
    snapshot = list(_MANAGED_THREADS)
    if not snapshot:
        return

    logger.debug("Draining %d managed thread(s)", len(snapshot))
    for thread in snapshot:
        try:
            if not thread.isRunning():
                _MANAGED_THREADS.discard(thread)
                continue
        except RuntimeError:
            _MANAGED_THREADS.discard(thread)
            continue

        # Disconnect all known signals so no callbacks fire into destroyed widgets.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            for name in _COMMON_SIGNAL_NAMES:
                try:
                    getattr(thread, name).disconnect()
                except Exception:
                    pass

        # Signal cancellation where supported.
        if hasattr(thread, "cancel"):
            try:
                thread.cancel()
            except Exception:
                pass
        try:
            thread.requestInterruption()
        except Exception:
            pass
        try:
            thread.quit()
        except Exception:
            pass

        try:
            if not thread.wait(timeout_ms):
                logger.warning(
                    "Thread %s did not stop within %dms during drain",
                    thread.__class__.__name__,
                    timeout_ms,
                )
        except Exception:
            pass

        try:
            thread.deleteLater()
        except Exception:
            pass

        _MANAGED_THREADS.discard(thread)

    logger.debug("Thread drain complete")
