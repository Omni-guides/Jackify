"""Shared mixin for reclaiming window focus after Steam restart."""
import logging
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication

logger = logging.getLogger(__name__)

STEAM_RESTART_SENTINEL = "[Jackify] Steam restart complete"


class FocusReclaimMixin:
    """Mixin providing post-Steam-restart focus reclaim for any screen.

    Usage: inherit this mixin and call _start_focus_reclaim_retries() when
    Steam restart is detected. Detection is typically done by checking
    progress messages for STEAM_RESTART_SENTINEL.
    """

    def _stop_focus_reclaim(self):
        pass  # No timer to stop - single-shot, no state

    def _start_focus_reclaim_retries(self):
        QTimer.singleShot(500, self._focus_reclaim_tick)

    def _focus_reclaim_tick(self):
        try:
            win = self.window()
            if win is None:
                return
            # raise_/activateWindow work on X11 and are silently ignored on Wayland, which
            # forbids self-activation. alert() is the one route the compositor honours there -
            # it marks the window as demanding attention so the taskbar entry highlights.
            win.raise_()
            win.activateWindow()
            win.setWindowState(win.windowState() & ~Qt.WindowMinimized | Qt.WindowActive)
            app = QApplication.instance()
            if app is not None:
                app.alert(win, 0)
        except Exception as e:
            logger.debug(f"Focus reclaim attempt failed: {e}")
