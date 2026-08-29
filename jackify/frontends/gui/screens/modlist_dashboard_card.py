"""
Modlist Dashboard card widget.

Vertical, image-led card - the Gallery's own card shape (image on top, name/details below).
Management actions (Reconfigure, Change Artwork, Change Proton Version, Uninstall) live in the
Properties popout (modlist_properties_dialog.py), not as permanent buttons on the tile - clicking
the card opens Properties, matching how Steam's library grid keeps a tile's permanent chrome to
almost nothing. Launch is the one action that stays on the tile itself, as a small corner overlay
icon (Steam's own hover-play affordance), separate from the properties click.
"""
import logging
from typing import Optional

from PySide6.QtCore import QPointF, QRect, Qt, Signal
from PySide6.QtGui import (
    QColor, QFont, QFontMetrics, QLinearGradient, QMouseEvent, QPainter, QPixmap, QPolygonF,
)
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QMenu, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from jackify.backend.models.game_types import GAME_DISPLAY_NAMES, GAME_NAME_TO_TYPE
from jackify.backend.services.dashboard_images import (
    get_cached_image_path,
    get_modlist_specific_art_path,
    get_steam_grid_art_path,
)
from jackify.backend.services.dashboard_status import (
    STATUS_MISSING,
    STATUS_NOT_CONFIGURED,
    STATUS_READY,
    STATUS_UNKNOWN_VERSION,
    STATUS_UPDATE_AVAILABLE,
)
from jackify.backend.services.install_registry import InstallEntry
from ..shared_theme import JACKIFY_COLOR_BLUE, btn_style  # noqa: F401 - re-exported for callers

logger = logging.getLogger(__name__)

_BADGE_READY = ("#1a3545", "#5fb8c8", "Ready")
_BADGE_UPDATE_AVAILABLE = ("#5a3d00", "#f0c040", "Update Available")
_BADGE_NOT_CONFIGURED = ("#555", "#ccc", "Not Configured")
_BADGE_MISSING = ("#5a1a1a", "#e08080", "Missing")
_BADGE_UNKNOWN_VERSION = ("#3a3a3a", "#999", "Unknown Version")

_BADGES = {
    STATUS_READY: _BADGE_READY,
    STATUS_UPDATE_AVAILABLE: _BADGE_UPDATE_AVAILABLE,
    STATUS_NOT_CONFIGURED: _BADGE_NOT_CONFIGURED,
    STATUS_MISSING: _BADGE_MISSING,
    STATUS_UNKNOWN_VERSION: _BADGE_UNKNOWN_VERSION,
}

# Fallback thumbnail colour + abbreviation per game type, used when an install has no cached
# artwork (backfilled installs, or the gallery has no match) - not real box art, just enough to
# tell cards apart at a glance rather than a blank grey box.
_GAME_THUMB_STYLE = {
    'skyrim': ("#2e4a63", "SSE"),
    'skyrimvr': ("#2e4a63", "VR"),
    'fallout4': ("#3d5c3d", "F4"),
    'fallout4vr': ("#3d5c3d", "F4VR"),
    'falloutnv': ("#5c4a2e", "FNV"),
    'fallout3': ("#5c4a2e", "F3"),
    'oblivion': ("#4a3d5c", "OB"),
    'oblivion_remastered': ("#4a3d5c", "OBR"),
    'enderal': ("#5c2e3d", "END"),
    'starfield': ("#2e4a4a", "SF"),
    'bg3': ("#5c3d2e", "BG3"),
    'cp2077': ("#5c2e50", "CP"),
}
_GAME_THUMB_DEFAULT = ("#333333", "?")


CARD_WIDTH = 260
CARD_HEIGHT = 238
IMAGE_WIDTH = 240
IMAGE_HEIGHT = 135


class _LaunchButton(QPushButton):
    """
    Round play-button overlay that paints its own triangle rather than relying on a Unicode
    glyph ("▶") - font metrics vary enough per system/font that the glyph never sits visually
    centred in the circle, so it's drawn directly instead.
    """

    def __init__(self, enabled_style: bool, parent=None):
        super().__init__(parent)
        self._enabled_style = enabled_style

    def enterEvent(self, event):
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = self.rect()
        bg = QColor(26, 95, 168, 220) if self._enabled_style and self.underMouse() else \
            QColor(20, 20, 20, 190 if self._enabled_style else 120)
        painter.setPen(QColor(255, 255, 255, 60 if self._enabled_style else 30))
        painter.setBrush(bg)
        painter.drawEllipse(rect.adjusted(1, 1, -1, -1))

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255) if self._enabled_style else QColor("#777"))
        cx, cy = rect.center().x(), rect.center().y()
        size = rect.width() * 0.28
        triangle = [
            (cx - size * 0.5 + 1, cy - size),
            (cx - size * 0.5 + 1, cy + size),
            (cx + size, cy),
        ]
        painter.drawPolygon(QPolygonF([QPointF(x, y) for x, y in triangle]))
        painter.end()


class DashboardCard(QFrame):
    # install_id, action: properties/launch
    action_requested = Signal(str, str)

    def __init__(
        self, entry: InstallEntry, status: str, proton_version: Optional[str] = None,
        latest_version: Optional[str] = None, parent=None,
    ):
        super().__init__(parent)
        self._entry = entry
        self._status = status
        self._proton_version = proton_version

        self.setFrameShape(QFrame.StyledPanel)
        # A real size increase would reflow the grid (the exact bug just fixed for the version
        # row), so the hover cue is a brighter, thicker border instead - reads as the card
        # lifting slightly without touching layout.
        # Selector must be the class name, not "QFrame" - QLabel is itself a QFrame subclass,
        # so a bare "QFrame" rule cascades onto every label in the card, not just the card.
        self.setStyleSheet(
            "DashboardCard { background-color: #2a2a2a; border: 1px solid #3a3a3a; border-radius: 6px; } "
            "DashboardCard:hover { background-color: #333333; border: 1px solid #5a9fd6; }"
        )
        self.setFixedSize(CARD_WIDTH, CARD_HEIGHT)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)

        outer = QVBoxLayout()
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(6)

        self.thumb_label = QLabel(self)
        self.thumb_label.setFixedSize(IMAGE_WIDTH, IMAGE_HEIGHT)
        self.thumb_label.setAlignment(Qt.AlignCenter)
        self.thumb_label.setScaledContents(True)
        self.thumb_label.setStyleSheet("background: #1c1c1c; border-radius: 4px; border: none;")
        self._load_thumbnail()
        outer.addWidget(self.thumb_label, alignment=Qt.AlignHCenter)

        name_row = QHBoxLayout()
        name_row.setSpacing(6)
        name_label = QLabel()
        name_label.setWordWrap(False)
        name_font = QFont("Sans", 11, QFont.Bold)
        name_label.setFont(name_font)
        name_label.setStyleSheet(f"color: {JACKIFY_COLOR_BLUE}; background: transparent; border: none;")
        name_row.addWidget(name_label, stretch=1)

        # game_type is stored inconsistently across write paths - some already write the full
        # display name (e.g. "Fallout New Vegas"), others the short internal key (e.g.
        # "skyrim"); GAME_DISPLAY_NAMES only has entries for the latter, so a plain .get()
        # with itself as fallback normalises both without needing to detect which is which.
        game_display = GAME_DISPLAY_NAMES.get(entry.game_type, entry.game_type) if entry.game_type else None
        game_label = QLabel(game_display or "Unknown game")
        game_label.setStyleSheet("color: #888; font-size: 10px; background: transparent; border: none;")
        game_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        name_row.addWidget(game_label)
        outer.addLayout(name_row)

        # Long modlist names ("Mojave Express Wabbajack (MEW)") get clipped mid-word by the
        # QHBoxLayout sharing the row with the game-type label - elide with an ellipsis and
        # keep the full name as a tooltip instead of just letting it truncate silently.
        available_width = CARD_WIDTH - 20 - 6 - game_label.sizeHint().width()
        elided = QFontMetrics(name_font).elidedText(entry.modlist_name, Qt.ElideRight, max(available_width, 40))
        name_label.setText(elided)
        if elided != entry.modlist_name:
            name_label.setToolTip(entry.modlist_name)

        badge_row = QHBoxLayout()
        badge_row.setSpacing(6)
        bg, fg, text = _BADGES.get(status, _BADGE_UNKNOWN_VERSION)
        badge = QLabel(text)
        badge.setStyleSheet(
            f"background-color: {bg}; color: {fg}; border-radius: 3px; "
            f"padding: 2px 6px; font-size: 10px; font-weight: bold; border: none;"
        )
        badge.setFixedWidth(badge.sizeHint().width())
        badge_row.addWidget(badge)
        badge_row.addStretch(1)
        proton_label = QLabel(f"Proton: {proton_version or 'Unknown'}")
        proton_label.setStyleSheet("color: #777; font-size: 10px; background: transparent; border: none;")
        proton_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        badge_row.addWidget(proton_label)
        outer.addLayout(badge_row)

        # Own row rather than sharing badge_row - "Update Available" is wide enough on its
        # own to collide with anything crammed onto the same line next to it.
        # Always added, even when blank - conditionally adding this widget made cards with a
        # version line taller than cards without one, so grid rows lost their shared height and
        # cards no longer lined up.
        version_text = ""
        if status == STATUS_UPDATE_AVAILABLE and entry.installed_version and latest_version:
            version_text = f"v{entry.installed_version} -> v{latest_version}"
        elif status == STATUS_READY and entry.installed_version:
            version_text = f"v{entry.installed_version}"
        version_label = QLabel(version_text)
        version_label.setStyleSheet("color: #999; font-size: 10px; background: transparent; border: none;")
        outer.addWidget(version_label)

        self.setLayout(outer)

        # Launch overlay: a small icon button anchored to the thumbnail's bottom-right corner,
        # the one action that stays on the tile itself rather than moving into Properties -
        # clicking it must not also open Properties, so it's a real child widget (which
        # consumes the click) rather than a region checked inside mousePressEvent.
        has_appid = bool(entry.appid)
        can_launch = has_appid and status not in (STATUS_MISSING, STATUS_NOT_CONFIGURED)
        self.launch_btn = _LaunchButton(can_launch, self.thumb_label)
        self.launch_btn.setFixedSize(28, 28)
        self.launch_btn.setFlat(True)
        self.launch_btn.setStyleSheet("QPushButton { border: none; background: transparent; }")
        self.launch_btn.setToolTip("Launch" if has_appid else "No Steam AppID - configure this modlist first")
        self.launch_btn.setEnabled(can_launch)
        self.launch_btn.move(IMAGE_WIDTH - 28 - 6, IMAGE_HEIGHT - 28 - 6)
        self.launch_btn.clicked.connect(lambda: self.action_requested.emit(entry.install_id, "launch"))

    def _load_thumbnail(self):
        for source in (
            get_cached_image_path(self._entry.install_id),
            get_modlist_specific_art_path(self._entry.install_dir),
            get_steam_grid_art_path(self._entry.appid) if self._entry.appid else None,
        ):
            if source:
                pixmap = QPixmap(str(source))
                if not pixmap.isNull():
                    self.thumb_label.setPixmap(self._cropped_to_thumb(pixmap))
                    return

        self.thumb_label.setPixmap(self._game_placeholder_pixmap())

    def _cropped_to_thumb(self, pixmap: QPixmap) -> QPixmap:
        """Fill the thumbnail rect without stretching, cropping any excess."""
        size = self.thumb_label.size()
        return pixmap.scaled(size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)

    def _game_placeholder_pixmap(self) -> QPixmap:
        """Last-resort placeholder when there is no dashboard image, no appid, and no Steam
        grid art on disk yet (e.g. a not-yet-configured entry)."""
        raw = (self._entry.game_type or "").lower()
        game_key = raw if raw in _GAME_THUMB_STYLE else GAME_NAME_TO_TYPE.get(raw)
        colour, label = _GAME_THUMB_STYLE.get(game_key, _GAME_THUMB_DEFAULT)
        base = QColor(colour)

        size = self.thumb_label.size()
        pixmap = QPixmap(size)
        gradient_painter = QPainter(pixmap)
        gradient = QLinearGradient(0, 0, size.width(), size.height())
        gradient.setColorAt(0.0, base.lighter(130))
        gradient.setColorAt(1.0, base.darker(140))
        gradient_painter.fillRect(pixmap.rect(), gradient)
        gradient_painter.setPen(QColor(255, 255, 255, 210))
        font = QFont()
        font.setBold(True)
        font.setPointSize(20)
        gradient_painter.setFont(font)
        gradient_painter.drawText(pixmap.rect(), Qt.AlignCenter, label)
        gradient_painter.end()
        return pixmap

    def refresh_thumbnail(self):
        self._load_thumbnail()

    def mousePressEvent(self, event: QMouseEvent):
        # super() call must happen before emit(): the Properties dialog this signal opens
        # runs a nested event loop, and Remove from List can delete this very card (grid
        # rebuild) before that loop returns - leaving self a deleted C++ object afterward.
        super().mousePressEvent(event)
        if event.button() == Qt.LeftButton:
            self.action_requested.emit(self._entry.install_id, "properties")


class AddModlistCard(QFrame):
    """Tile that starts a new modlist. Sized like a real card so the grid stays even, and placed
    last so it does not shift the user's own modlists along by one."""
    install_requested = Signal()
    add_existing_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet(
            "QFrame { background-color: #2a2a2a; border: 1px dashed #4a4a4a; border-radius: 6px; }"
        )
        self.setFixedSize(CARD_WIDTH, CARD_HEIGHT)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)

        outer = QVBoxLayout()
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(6)

        plus = QLabel("+")
        plus.setFixedSize(IMAGE_WIDTH, IMAGE_HEIGHT)
        plus.setAlignment(Qt.AlignCenter)
        plus.setFont(QFont("Sans", 40, QFont.Light))
        plus.setStyleSheet(
            f"color: {JACKIFY_COLOR_BLUE}; background: #1c1c1c; border-radius: 4px; border: none;"
        )
        outer.addWidget(plus, alignment=Qt.AlignHCenter)

        title = QLabel("Add a Modlist")
        title.setFont(QFont("Sans", 11, QFont.Bold))
        title.setStyleSheet(f"color: {JACKIFY_COLOR_BLUE}; background: transparent; border: none;")
        outer.addWidget(title)

        subtitle = QLabel("Install a new one, or set up one you already have")
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: #888; font-size: 11px; background: transparent; border: none;")
        outer.addWidget(subtitle)

        outer.addStretch()
        self.setLayout(outer)

    def enterEvent(self, event):
        self.setStyleSheet(
            f"QFrame {{ background-color: #333333; border: 1px dashed {JACKIFY_COLOR_BLUE}; "
            f"border-radius: 6px; }}"
        )
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setStyleSheet(
            "QFrame { background-color: #2a2a2a; border: 1px dashed #4a4a4a; border-radius: 6px; }"
        )
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self._show_choice_menu(event)
        super().mousePressEvent(event)

    def _show_choice_menu(self, event: QMouseEvent):
        """Two-item menu at the cursor - a navigation branch, not a decision worth a window."""
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background-color: #2a2a2a; color: #ddd; border: 1px solid #4a4a4a; }"
            "QMenu::item { padding: 8px 20px; }"
            f"QMenu::item:selected {{ background-color: {JACKIFY_COLOR_BLUE}; color: white; }}"
        )
        install_action = menu.addAction("Install a New Modlist")
        install_action.setToolTip("Download and install a modlist from the gallery")
        existing_action = menu.addAction("Add an Existing Modlist")
        existing_action.setToolTip("Set up a modlist already on this system")

        chosen = menu.exec(event.globalPosition().toPoint())
        if chosen is install_action:
            self.install_requested.emit()
        elif chosen is existing_action:
            self.add_existing_requested.emit()
