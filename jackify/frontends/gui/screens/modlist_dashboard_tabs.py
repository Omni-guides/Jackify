"""
Persistent top-level tab bar: Modlists / Additional Tasks / Tools Hub.

Owned by the main window (main_window_ui.py), sitting above the stacked widget rather than
inside any one screen, so switching between these three destinations keeps the tab row in
place and only the body below it changes - it should not read as a full screen navigation.

The index values below are coupled to the screen-factory index scheme defined in
main_window_ui.py (Additional Tasks=3, Tools Hub=10, Modlist Dashboard=12).
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from jackify.frontends.gui.shared_theme import (
    COLOR_TAB_ACTIVE_BG, COLOR_TAB_HOVER_BG, COLOR_TAB_INACTIVE_TEXT, JACKIFY_COLOR_BLUE,
)

TAB_TARGETS = [
    ("Modlists", 12),
    ("Additional Tasks", 3),
    ("Tools Hub", 10),
]

_TAB_DESCRIPTIONS = {
    12: "Install, launch, and manage your modlists",
    3: "Verifier, diagnostics, Wabbajack installer, and other one-off tools",
    10: "Manage the install engine and third-party tools",
}

_ATTENTION_COLOR = "#f0c040"
_ATTENTION_DOT_SIZE = 8


def _tab_style(active: bool) -> str:
    if active:
        return (
            f"QPushButton {{ background-color: {COLOR_TAB_ACTIVE_BG}; color: {JACKIFY_COLOR_BLUE}; "
            f"border: none; border-bottom: 2px solid {JACKIFY_COLOR_BLUE}; "
            f"border-top-left-radius: 6px; border-top-right-radius: 6px; "
            f"font-size: 13px; font-weight: bold; padding: 6px 18px; }}"
        )
    return (
        f"QPushButton {{ background-color: transparent; color: {COLOR_TAB_INACTIVE_TEXT}; "
        f"border: none; border-bottom: 2px solid transparent; "
        f"border-top-left-radius: 6px; border-top-right-radius: 6px; "
        f"font-size: 13px; font-weight: bold; padding: 6px 18px; }}"
        f"QPushButton:hover {{ background-color: {COLOR_TAB_HOVER_BG}; color: {JACKIFY_COLOR_BLUE}; }}"
    )


class _TabButton(QPushButton):
    """A tab button that can show a small corner dot rather than changing its own color -
    a visible "something needs attention here" cue subtle enough not to look like an error
    or read as the tab itself having changed state (VS Code's Extensions icon does the same
    for pending updates)."""

    def __init__(self, label: str, parent=None):
        super().__init__(label, parent)
        self._attention = False

    def set_attention(self, needs_attention: bool) -> None:
        if self._attention != needs_attention:
            self._attention = needs_attention
            self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._attention:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(_ATTENTION_COLOR))
        rect = self.rect()
        painter.drawEllipse(
            rect.right() - _ATTENTION_DOT_SIZE - 6, rect.top() + 5,
            _ATTENTION_DOT_SIZE, _ATTENTION_DOT_SIZE,
        )
        painter.end()


class DashboardTabBar(QWidget):
    """Highlights whichever of Modlists / Additional Tasks / Tools Hub is current and
    switches the shared stacked widget when a tab is clicked. A tab can also be flagged as
    needing attention (e.g. Tools Hub when an update is available) - shown as a small corner
    dot rather than changing the tab's own color, see _TabButton."""

    def __init__(self, stacked_widget, parent=None):
        super().__init__(parent)
        self._stacked_widget = stacked_widget
        self._buttons = {}
        self._active_index = TAB_TARGETS[0][1]
        self._attention = set()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(30, 4, 30, 0)
        layout.setSpacing(4)
        for label, index in TAB_TARGETS:
            btn = _TabButton(label)
            btn.setFixedHeight(30)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, i=index: self._stacked_widget.setCurrentIndex(i))
            layout.addWidget(btn)
            self._buttons[index] = btn
        layout.addStretch(1)

        # Right-aligned slot for tab-specific action widgets (Dashboard's "Check for Updates",
        # Tools Hub's "Update All") - each shown only while its own tab is active, everything
        # else about this row stays constant across tabs.
        self.action_slot = QWidget()
        slot_layout = QHBoxLayout(self.action_slot)
        slot_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.action_slot)
        self._action_widgets = []  # [(tab_index, widget), ...]

        self.set_active(self._active_index)

    def add_action_widget(self, widget, tab_index: int) -> None:
        self.action_slot.layout().addWidget(widget)
        self._action_widgets.append((tab_index, widget))
        widget.setVisible(tab_index == self._active_index)

    def set_active(self, current_index: int) -> None:
        self._active_index = current_index
        for tab_index, widget in self._action_widgets:
            widget.setVisible(tab_index == current_index)
        for index in self._buttons:
            self._restyle(index)

    def set_needs_attention(self, index: int, needs_attention: bool) -> None:
        if needs_attention:
            self._attention.add(index)
        else:
            self._attention.discard(index)
        self._restyle(index)

    def _restyle(self, index: int) -> None:
        btn = self._buttons.get(index)
        if btn is None:
            return
        attention = index in self._attention
        btn.setStyleSheet(_tab_style(active=index == self._active_index))
        btn.set_attention(attention)
        base = _TAB_DESCRIPTIONS.get(index, "")
        btn.setToolTip(f"{base}\n\nUpdate available" if attention else base)

    @staticmethod
    def is_tabbed_index(index: int) -> bool:
        return any(index == target for _, target in TAB_TARGETS)
