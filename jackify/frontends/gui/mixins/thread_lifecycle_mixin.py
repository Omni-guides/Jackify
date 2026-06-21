"""
Safe QThread teardown mixin for workflow screens.

PySide6 segfaults if a QThread emits a signal to a C++ Qt object that has
already been deleted (e.g. because the user navigated away). The fix is to
disconnect all signals from a thread before the owning screen can be destroyed,
then let the thread finish naturally rather than calling terminate().

Usage:
    class MyScreen(ThreadLifecycleMixin, QWidget):
        def hideEvent(self, event):
            super().hideEvent(event)
            self.my_thread = self._park_thread(
                self.my_thread, ["finished_signal", "progress_update"]
            )

        def cleanup_processes(self):
            self._park_all_threads()
"""

import logging
import warnings
from typing import List, Optional

logger = logging.getLogger(__name__)

# Module-level registry keeps references to parked threads alive independent
# of screen widget lifetime. Screens are destroyed on navigation; without this,
# _parked_threads on self evaporates and the GC destroys still-running threads,
# triggering Qt's "QThread: Destroyed while thread is still running" abort.
_PARKED_THREAD_REGISTRY: set = set()


class ThreadLifecycleMixin:
    """Mixin providing safe QThread signal-disconnect parking for screen widgets."""

    def _park_thread(self, thread, signal_names: Optional[List[str]] = None):
        """Disconnect a thread from this screen and let it finish on its own.

        Disconnects the named signals so no callbacks fire on this (potentially
        dying) widget. Keeps a reference in _parked_threads so the thread is
        not garbage-collected before it finishes.

        Returns None so callers can do: self.thread = self._park_thread(self.thread, [...])
        """
        if thread is None:
            return None

        for name in (signal_names or []):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                try:
                    getattr(thread, name).disconnect()
                except Exception:
                    pass

        # Register in the module-level set so the reference survives screen destruction.
        # Remove from registry when the thread finishes so it can be GC'd cleanly.
        _PARKED_THREAD_REGISTRY.add(thread)
        try:
            thread.finished.connect(lambda t=thread: _PARKED_THREAD_REGISTRY.discard(t))
        except Exception:
            pass
        return None

    def hideEvent(self, event):
        """Park all running threads when the screen is hidden/navigated away from."""
        try:
            super().hideEvent(event)
        except Exception:
            pass
        self._park_all_threads()

    def _kill_prefix_wine_processes(self, appid: str = '') -> None:
        """Kill wine/winetricks subprocesses on user-initiated cancel.

        Called before parking threads so the blocked subprocess.run() calls inside
        the thread actually return rather than running until completion.
        """
        import os
        import subprocess
        for pattern in ('winetricks', 'protontricks'):
            subprocess.run(['pkill', '-9', '-f', pattern], capture_output=True)
        if not appid:
            return
        try:
            from jackify.backend.handlers.path_handler import PathHandler
            from jackify.backend.handlers.winetricks_handler import WinetricksHandler
            compat = PathHandler.find_compat_data(str(appid))
            if not compat:
                return
            pfx = str(compat / 'pfx')
            wine_bin = WinetricksHandler()._get_wine_binary_for_prefix(pfx)
            if not wine_bin:
                return
            wineserver = os.path.join(os.path.dirname(wine_bin), 'wineserver')
            if os.path.isfile(wineserver):
                subprocess.run([wineserver, '-k'],
                               env={**os.environ, 'WINEPREFIX': pfx},
                               timeout=5, capture_output=True)
        except Exception:
            pass

    def _park_all_threads(self):
        """Park every running QThread attribute found on this instance.

        Inspects instance variables, disconnects common signal names from any
        running QThread, and parks them. Used in cleanup_processes() / closeEvent().
        """
        from PySide6.QtCore import QThread

        _common_signals = (
            "finished_signal",
            "progress_update",
            "workflow_complete",
            "configuration_complete",
            "error_occurred",
            "status_update",
            "finished",
        )

        for attr_name, value in list(vars(self).items()):
            try:
                if not isinstance(value, QThread):
                    continue
                if not value.isRunning():
                    continue
                signal_names = [s for s in _common_signals if hasattr(value, s)]
                setattr(self, attr_name, self._park_thread(value, signal_names))
            except Exception:
                pass
