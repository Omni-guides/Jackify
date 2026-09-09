"""Small self-contained widgets used by modlist_properties_dialog.py."""
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import QLabel, QSizePolicy


class BannerLabel(QLabel):
    """Banner that re-crops on its own resize - the dialog's resizeEvent fires before the
    layout has resized this label, so cropping from there uses a stale width."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._source: Optional[QPixmap] = None

    def set_source(self, pixmap: Optional[QPixmap]):
        self._source = pixmap
        self._rescale()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._rescale()

    def _rescale(self):
        if self._source is None or self._source.isNull():
            return
        target = self.size()
        if target.width() <= 0 or target.height() <= 0:
            return
        scaled = self._source.scaled(
            target, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
        )
        x = max(0, (scaled.width() - target.width()) // 2)
        y = max(0, (scaled.height() - target.height()) // 2)
        cropped = scaled.copy(x, y, target.width(), target.height())

        # A center-crop against the dialog's flush top edge (no titlebar gap) reads as an
        # abrupt cut, especially when the source art has content near its own top edge - a
        # short fade into black eases the transition without a hard line.
        fade_height = min(40, target.height())
        if fade_height > 0:
            painter = QPainter(cropped)
            gradient = QLinearGradient(0, 0, 0, fade_height)
            gradient.setColorAt(0.0, QColor(0, 0, 0, 140))
            gradient.setColorAt(1.0, QColor(0, 0, 0, 0))
            painter.fillRect(0, 0, target.width(), fade_height, gradient)
            painter.end()

        self.setPixmap(cropped)


class ElidedValueLabel(QLabel):
    """Single-line detail value: elided to fit, full text on hover, click to copy.

    Never wraps - a wrapped path makes the row height depend on path length and dialog width,
    which clipped the grid. Elides in the middle to keep the drive root and the folder name.
    """
    clicked = Signal()

    def __init__(self, text: str, copy_text: Optional[str] = None, parent=None):
        super().__init__(parent)
        self._full_text = text
        # Hover shows what a click will copy
        self.setToolTip(copy_text if copy_text is not None else text)
        self.setCursor(Qt.PointingHandCursor)
        # Ignored width, or a long path widens the dialog instead of eliding
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.setFixedHeight(self.fontMetrics().height() + 2)
        self._apply_elide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_elide()

    def _apply_elide(self):
        elided = self.fontMetrics().elidedText(self._full_text, Qt.ElideMiddle, max(0, self.width()))
        if elided != self.text():
            super().setText(elided)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)
