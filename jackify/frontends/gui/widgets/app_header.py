"""
Persistent app header: logo banner, tab navigation, separator.

Owned by the main window (main_window_ui.py), sitting above the stacked widget. This whole
block stays identical across the Modlists / Additional Tasks / Tools Hub destinations - only
the body underneath (the current screen) changes. See modlist_dashboard_tabs.py for the tab
bar itself.
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from jackify.frontends.gui.screens.modlist_dashboard_tabs import DashboardTabBar
from jackify.frontends.gui.shared_theme import BANNER_PATH, COLOR_SEPARATOR

_BANNER_HEIGHT = 44


class AppHeader(QWidget):
    """Logo banner + tab bar + separator, shown together above whichever of the three tabbed
    screens is current, hidden on deeper workflow screens reached from within them."""

    def __init__(self, stacked_widget, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.setSpacing(0)

        banner = QLabel()
        banner.setAlignment(Qt.AlignHCenter)
        pixmap = QPixmap(BANNER_PATH)
        if not pixmap.isNull():
            # Scale at the screen's real device pixel ratio, not just the logical height - a
            # pixmap scaled for 1x and handed to Qt without setDevicePixelRatio() gets
            # stretched again to fill a HiDPI/fractionally-scaled screen, reading as a very
            # slight softness/squash rather than a sharp logo.
            screen = QApplication.primaryScreen()
            dpr = screen.devicePixelRatio() if screen else 1.0
            scaled = pixmap.scaledToHeight(round(_BANNER_HEIGHT * dpr), Qt.SmoothTransformation)
            scaled.setDevicePixelRatio(dpr)
            banner.setPixmap(scaled)
        layout.addWidget(banner)

        layout.addSpacing(6)

        self.tab_bar = DashboardTabBar(stacked_widget)
        layout.addWidget(self.tab_bar)

        layout.addSpacing(8)

        sep = QLabel()
        sep.setFixedHeight(2)
        sep.setStyleSheet(f"background: {COLOR_SEPARATOR};")
        layout.addWidget(sep)

    def add_action_widget(self, widget, tab_index: int) -> None:
        self.tab_bar.add_action_widget(widget, tab_index)

    def set_active(self, index: int) -> None:
        self.tab_bar.set_active(index)

    def set_needs_attention(self, index: int, needs_attention: bool) -> None:
        self.tab_bar.set_needs_attention(index, needs_attention)

    @staticmethod
    def is_tabbed_index(index: int) -> bool:
        return DashboardTabBar.is_tabbed_index(index)
