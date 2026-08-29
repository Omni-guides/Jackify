"""
Tools Hub card widget.

Vertical card matching the Modlist Dashboard's card shape (icon tile on top, name/status
below, actions at the bottom) rather than the old full-width row - the same visual language
across both card grids, and no more wasted horizontal space per tool.
"""

import logging
import subprocess
from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel,
    QMenu, QPushButton, QSizePolicy, QVBoxLayout,
)

from jackify.backend.services.tool_icons import get_cached_icon_path
from jackify.backend.services.tool_registry import ToolRegistry, ToolStatus, set_active_engine_id
from jackify.frontends.gui.screens.modlist_dashboard_card import CARD_HEIGHT, CARD_WIDTH, IMAGE_HEIGHT, IMAGE_WIDTH
from jackify.frontends.gui.services.message_service import MessageService, open_url
from jackify.frontends.gui.shared_theme import (  # noqa: F401 - btn_style re-exported for callers
    JACKIFY_COLOR_BLUE, LOGO_PATH,
    COLOR_BTN_BACK as _C_BACK,
    COLOR_BTN_DISABLED as _C_DISABLED,
    COLOR_BTN_INSTALL as _C_INSTALL,
    COLOR_BTN_LAUNCH as _C_LAUNCH,
    COLOR_BTN_SET_ACTIVE as _C_SET_ACTIVE,
    COLOR_BTN_UPDATE as _C_UPDATE,
    btn_style,
)

_JACKIFY_ENGINE_TOOL_ID = "jackify-engine"

logger = logging.getLogger(__name__)

_STYLE_BTN_INVISIBLE = (
    "QPushButton { background: transparent; border: none; color: transparent; "
    "font-size: 11px; font-weight: bold; padding: 4px 8px; }"
    "QPushButton:hover { background: transparent; }"
)

_BADGE_NOT_INSTALLED = ("#555", "#ccc")
_BADGE_UP_TO_DATE    = ("#1a3545", "#5fb8c8")
_BADGE_UPDATE_AVAIL  = ("#5a3d00", "#f0c040")
_BADGE_ACTIVE        = ("#0e3d5a", JACKIFY_COLOR_BLUE)

_TILE_ENGINE = "#2e4a63"
_TILE_TOOL = "#3d3d45"


def section_header(text: str) -> QLabel:
    lbl = QLabel(text.upper())
    lbl.setStyleSheet(
        "color: #777; font-size: 10px; font-weight: bold; letter-spacing: 1px; "
        "background: transparent; border: none; padding: 0;"
    )
    return lbl


def _initials(display_name: str) -> str:
    words = [w for w in display_name.replace("-", " ").split() if w]
    if not words:
        return "?"
    if len(words) == 1:
        return words[0][:3].upper()
    return "".join(w[0] for w in words[:3]).upper()


class ToolCard(QFrame):
    action_requested = Signal(str, str)   # tool_id, action
    engine_activated = Signal(str)        # tool_id

    def __init__(self, status: ToolStatus, active_engine_id: str, parent=None):
        super().__init__(parent)
        self._tool_id = status.definition.tool_id
        self._status = status
        self._active_engine_id = active_engine_id
        self._busy = False
        self._busy_label: Optional[str] = None

        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet(
            "ToolCard { background-color: #2a2a2a; border: 1px solid #3a3a3a; border-radius: 6px; } "
            "ToolCard:hover { background-color: #333333; border: 1px solid #5a9fd6; }"
        )
        self.setFixedSize(CARD_WIDTH, CARD_HEIGHT)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        outer = QVBoxLayout()
        outer.setContentsMargins(10, 8, 10, 6)
        outer.setSpacing(3)

        defn = status.definition
        self._tile_label = QLabel()
        self._tile_label.setFixedSize(IMAGE_WIDTH, IMAGE_HEIGHT)
        self._tile_label.setAlignment(Qt.AlignCenter)
        self._tile_label.setStyleSheet("background: #1c1c1c; border-radius: 4px; border: none;")
        self._load_tile_image()
        outer.addWidget(self._tile_label, alignment=Qt.AlignHCenter)

        name_font = QFont("Sans", 11, QFont.Bold)
        url = defn.upstream_url
        if url:
            name_html = (
                f'<a href="{url}" style="color: {JACKIFY_COLOR_BLUE}; text-decoration: none;">'
                f'{defn.display_name}</a>'
            )
        else:
            name_html = f'<span style="color: {JACKIFY_COLOR_BLUE};">{defn.display_name}</span>'
        self._name_label = QLabel(name_html)
        self._name_label.setFont(name_font)
        self._name_label.setTextFormat(Qt.RichText)
        self._name_label.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self._name_label.setOpenExternalLinks(False)
        self._name_label.linkActivated.connect(self._open_url)
        self._name_label.setStyleSheet("background: transparent; border: none;")
        self._name_label.setFixedHeight(18)
        outer.addWidget(self._name_label)

        desc_font = QFont("Sans", 9)
        elided_desc = QFontMetrics(desc_font).elidedText(defn.description, Qt.ElideRight, CARD_WIDTH - 20)
        desc_label = QLabel(elided_desc)
        desc_label.setFont(desc_font)
        desc_label.setStyleSheet("color: #888; background: transparent; border: none;")
        desc_label.setFixedHeight(14)
        if elided_desc != defn.description:
            desc_label.setToolTip(defn.description)
        outer.addWidget(desc_label)

        badge_row = QHBoxLayout()
        badge_row.setSpacing(6)
        self._badge = QLabel()
        self._badge.setStyleSheet("border-radius: 3px; padding: 2px 6px; font-size: 10px; font-weight: bold;")
        badge_row.addWidget(self._badge)
        badge_row.addStretch(1)
        self._version_label = QLabel()
        self._version_label.setStyleSheet("color: #777; font-size: 10px; background: transparent; border: none;")
        self._version_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        badge_row.addWidget(self._version_label)
        outer.addLayout(badge_row)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)
        self._btn_primary = QPushButton()
        self._btn_primary.setFixedHeight(24)
        self._btn_primary.clicked.connect(self._on_primary)
        btn_row.addWidget(self._btn_primary, stretch=2)
        self._btn_update = QPushButton("Update")
        self._btn_update.setFixedHeight(24)
        self._btn_update.clicked.connect(lambda: self.action_requested.emit(self._tool_id, "update"))
        btn_row.addWidget(self._btn_update, stretch=2)
        self._btn_more = QPushButton("...")
        self._btn_more.setFixedHeight(24)
        self._btn_more.setStyleSheet(btn_style(_C_BACK, width=30))
        self._btn_more.clicked.connect(self._on_more)
        btn_row.addWidget(self._btn_more, stretch=1)
        outer.addLayout(btn_row)

        self.setLayout(outer)
        self._refresh_ui()

    def _load_tile_image(self) -> None:
        # Fetched GitHub-owner avatars only make sense for engines (few, well-known repos) -
        # for the wider tools list they were often unrelated/low-quality images, so those
        # keep the colour-tile placeholder instead. jackify-engine uses the bundled Jackify
        # logo directly rather than a fetched avatar.
        if self._tool_id == _JACKIFY_ENGINE_TOOL_ID:
            pixmap = QPixmap(LOGO_PATH)
            if not pixmap.isNull():
                self._set_tile_pixmap(pixmap)
                return
        if self._status.definition.is_engine:
            cached = get_cached_icon_path(self._tool_id)
            if cached:
                pixmap = QPixmap(str(cached))
                if not pixmap.isNull():
                    self._set_tile_pixmap(pixmap)
                    return
        self._tile_label.setPixmap(self._placeholder_pixmap())

    def set_icon_pixmap(self, path) -> None:
        """Called once a background fetch has cached a real icon for this tool - engines only,
        see _load_tile_image."""
        if not self._status.definition.is_engine:
            return
        pixmap = QPixmap(str(path))
        if not pixmap.isNull():
            self._set_tile_pixmap(pixmap)

    def _set_tile_pixmap(self, pixmap: QPixmap) -> None:
        size = self._tile_label.size()
        # Fetched avatars/logos are square-ish, not the same aspect ratio as the tile - fit
        # within it (letterboxed on the dark tile background) rather than cropping or
        # stretching a face/logo out of shape.
        scaled = pixmap.scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._tile_label.setPixmap(scaled)

    def _placeholder_pixmap(self) -> QPixmap:
        base = QColor(_TILE_ENGINE if self._status.definition.is_engine else _TILE_TOOL)
        size = self._tile_label.size()
        pixmap = QPixmap(size)
        painter = QPainter(pixmap)
        gradient = QLinearGradient(0, 0, size.width(), size.height())
        gradient.setColorAt(0.0, base.lighter(130))
        gradient.setColorAt(1.0, base.darker(140))
        painter.fillRect(pixmap.rect(), gradient)
        painter.setPen(QColor(255, 255, 255, 210))
        font = QFont()
        font.setBold(True)
        font.setPointSize(22)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignCenter, _initials(self._status.definition.display_name))
        painter.end()
        return pixmap

    def _refresh_ui(self):
        defn = self._status.definition
        installed = self._status.installed
        update_avail = self._status.update_available
        is_active = defn.is_engine and self._active_engine_id == self._tool_id

        if self._busy:
            self._badge.setText("Working...")
            self._badge.setStyleSheet(
                "background-color: #555; color: #ccc; border-radius: 3px; "
                "padding: 2px 6px; font-size: 10px; font-weight: bold; border: none;"
            )
            self._btn_primary.setText(self._busy_label or "Working...")
            self._btn_primary.setEnabled(False)
            self._btn_primary.setVisible(True)
            self._btn_update.setStyleSheet(_STYLE_BTN_INVISIBLE)
            self._btn_update.setEnabled(False)
            self._btn_more.setEnabled(False)
            return

        if defn.is_engine and is_active:
            bg, fg, badge_text = *_BADGE_ACTIVE, "Active Engine"
        elif not installed:
            bg, fg, badge_text = *_BADGE_NOT_INSTALLED, "Not Installed"
        elif update_avail:
            bg, fg, badge_text = *_BADGE_UPDATE_AVAIL, "Update Available"
        else:
            bg, fg, badge_text = *_BADGE_UP_TO_DATE, "Installed"
        self._badge.setText(badge_text)
        self._badge.setStyleSheet(
            f"background-color: {bg}; color: {fg}; border-radius: 3px; "
            f"padding: 2px 6px; font-size: 10px; font-weight: bold; border: none;"
        )

        iv = self._status.installed_version or "-"
        lv = self._status.latest_version or "checking..."
        self._version_label.setText(f"{iv} / {lv}")
        self._version_label.setToolTip(f"Installed: {iv}\nLatest: {lv}")

        if not installed:
            self._btn_primary.setText("Install")
            self._btn_primary.setStyleSheet(btn_style(_C_INSTALL, width=70))
            self._btn_primary.setEnabled(not self._busy)
            self._btn_primary.setVisible(True)
        elif defn.is_engine:
            if is_active:
                self._btn_primary.setText("Active")
                self._btn_primary.setStyleSheet(btn_style(_C_DISABLED, disabled=True, width=70))
                self._btn_primary.setEnabled(False)
            else:
                self._btn_primary.setText("Set Active")
                self._btn_primary.setStyleSheet(btn_style(_C_SET_ACTIVE, width=70))
                self._btn_primary.setEnabled(not self._busy)
            self._btn_primary.setVisible(True)
        elif defn.can_launch:
            self._btn_primary.setText("Launch")
            self._btn_primary.setStyleSheet(btn_style(_C_LAUNCH, width=70))
            self._btn_primary.setEnabled(not self._busy)
            self._btn_primary.setVisible(True)
        else:
            self._btn_primary.setVisible(False)

        if installed and update_avail and not self._busy:
            self._btn_update.setStyleSheet(btn_style(_C_UPDATE, width=70))
            self._btn_update.setEnabled(True)
        else:
            self._btn_update.setStyleSheet(_STYLE_BTN_INVISIBLE)
            self._btn_update.setEnabled(False)
        self._btn_more.setEnabled(not self._busy)

    def set_latest_version(self, tag: str) -> bool:
        self._status.latest_version = tag
        if self._status.installed and self._status.installed_version and tag != "unknown":
            self._status.update_available = tag.lstrip("v") != self._status.installed_version.lstrip("v")
        self._refresh_ui()
        return self._status.update_available

    def set_active_engine(self, active_id: str):
        self._active_engine_id = active_id
        self._refresh_ui()

    def set_busy(self, busy: bool, label: Optional[str] = None):
        self._busy = busy
        self._busy_label = label if busy else None
        self._refresh_ui()

    def mark_installed(self, version: str):
        self._status.installed = True
        self._status.installed_version = version
        self._status.update_available = False
        self._busy = False
        self._busy_label = None
        self._refresh_ui()

    def mark_uninstalled(self):
        self._status.installed = False
        self._status.installed_version = None
        self._status.update_available = False
        self._busy = False
        self._busy_label = None
        self._refresh_ui()

    def _prompt_uninstall(self, display_name: str):
        dlg = QDialog(self.window())
        dlg.setWindowTitle("Uninstall Tool")
        dlg.setWindowModality(Qt.ApplicationModal)
        dlg.setAttribute(Qt.WA_DeleteOnClose)
        dlg.setMinimumWidth(340)
        dlg.setStyleSheet(
            "QDialog { background-color: #232323; color: #e0e0e0; }"
            "QLabel  { color: #e0e0e0; font-size: 13px; background: transparent; border: none; }"
        )
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(16)
        msg = QLabel(f"Uninstall <b>{display_name}</b>?<br><br>This will delete the installed files.")
        msg.setTextFormat(Qt.RichText)
        msg.setWordWrap(True)
        layout.addWidget(msg)
        sep = QLabel()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: #3a3a3a; border: none;")
        layout.addWidget(sep)
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedSize(90, 30)
        cancel_btn.setStyleSheet(btn_style(_C_BACK, width=90))
        cancel_btn.setDefault(True)
        cancel_btn.clicked.connect(dlg.reject)
        btn_row.addWidget(cancel_btn)
        uninstall_btn = QPushButton("Uninstall")
        uninstall_btn.setFixedSize(90, 30)
        uninstall_btn.setStyleSheet(btn_style("#8b2020", width=90))
        uninstall_btn.clicked.connect(dlg.accept)
        btn_row.addWidget(uninstall_btn)
        layout.addLayout(btn_row)
        if dlg.exec() == QDialog.Accepted:
            self.action_requested.emit(self._tool_id, "uninstall")

    def _on_primary(self):
        defn = self._status.definition
        if not self._status.installed:
            self.action_requested.emit(self._tool_id, "install")
        elif defn.is_engine:
            try:
                set_active_engine_id(self._tool_id)
                self.engine_activated.emit(self._tool_id)
            except Exception as e:
                MessageService.warning(self, "Error", str(e))
        elif defn.can_launch:
            if self._tool_id == "ttw_installer":
                self.action_requested.emit(self._tool_id, "launch_jackify_ui")
            else:
                self._launch()

    def _open_url(self, url: str):
        open_url(url)

    def _launch(self):
        binary = ToolRegistry().get_binary_path(self._tool_id)
        if not binary:
            MessageService.warning(
                self, "Not Found",
                f"No executable found for {self._status.definition.display_name}. Try reinstalling it."
            )
            return
        try:
            subprocess.Popen(
                [str(binary)], start_new_session=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            MessageService.warning(self, "Launch Failed", str(e))

    def _on_more(self):
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background-color: #2a2a2a; color: #e0e0e0; border: 1px solid #444; }"
            "QMenu::item:selected { background-color: #3a3a3a; }"
            "QMenu::item:disabled { color: #555; }"
        )
        defn = self._status.definition
        upstream_action = menu.addAction("Open Website")
        upstream_action.setEnabled(bool(defn.upstream_url))
        menu.addSeparator()
        downgrade_action = menu.addAction("Change Version")
        downgrade_action.setEnabled(self._status.can_downgrade and not self._busy)
        uninstall_action = menu.addAction("Uninstall")
        uninstall_action.setEnabled(defn.can_uninstall and self._status.installed and not self._busy)

        chosen = menu.exec(self._btn_more.mapToGlobal(self._btn_more.rect().bottomLeft()))
        if chosen == upstream_action and defn.upstream_url:
            self._open_url(defn.upstream_url)
        elif chosen == downgrade_action and downgrade_action.isEnabled():
            self.action_requested.emit(self._tool_id, "downgrade")
        elif chosen == uninstall_action and uninstall_action.isEnabled():
            QTimer.singleShot(0, lambda: self._prompt_uninstall(defn.display_name))
