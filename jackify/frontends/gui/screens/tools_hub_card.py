"""
Tools Hub card widget.

Per-tool card showing status badge, version, and action buttons.
Engines show Set Active / Active badge; tools with can_launch show Launch.
"""

import logging
from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel,
    QMenu, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from jackify.backend.services.tool_registry import ToolRegistry, ToolStatus, set_active_engine_id
from jackify.frontends.gui.services.message_service import MessageService, open_url
from jackify.frontends.gui.shared_theme import JACKIFY_COLOR_BLUE

logger = logging.getLogger(__name__)

_C_INSTALL    = "#1a5fa8"
_C_UPDATE     = "#4a5568"
_C_LAUNCH     = "#1a5fa8"
_C_SET_ACTIVE = "#4a5568"
_C_BACK       = "#4a5568"
_C_DISABLED   = "#333"

_STYLE_BTN_INVISIBLE = (
    "QPushButton { background: transparent; border: none; color: transparent; "
    "font-size: 11px; font-weight: bold; padding: 4px 8px; min-width: 90px; }"
    "QPushButton:hover { background: transparent; }"
)

_BADGE_NOT_INSTALLED = ("#555", "#ccc")
_BADGE_UP_TO_DATE    = ("#1a3545", "#5fb8c8")
_BADGE_UPDATE_AVAIL  = ("#5a3d00", "#f0c040")
_BADGE_ACTIVE        = ("#0e3d5a", JACKIFY_COLOR_BLUE)


def btn_style(colour: str, disabled: bool = False, width: int = 90) -> str:
    bg = _C_DISABLED if disabled else colour
    hover = "#444" if disabled else colour
    return (
        f"QPushButton {{ background-color: {bg}; color: {'#666' if disabled else 'white'}; "
        f"border: none; border-radius: 4px; font-size: 11px; font-weight: bold; "
        f"padding: 4px 8px; min-width: {width}px; }}"
        f"QPushButton:hover {{ background-color: {hover}; }}"
    )


def section_header(text: str) -> QLabel:
    lbl = QLabel(text.upper())
    lbl.setStyleSheet(
        "color: #777; font-size: 10px; font-weight: bold; letter-spacing: 1px; "
        "background: transparent; border: none; padding: 0;"
    )
    return lbl


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
            "QFrame { background-color: #2a2a2a; border: 1px solid #3a3a3a; border-radius: 6px; }"
        )
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        outer = QHBoxLayout()
        outer.setContentsMargins(14, 7, 14, 7)
        outer.setSpacing(12)

        info_col = QVBoxLayout()
        info_col.setSpacing(2)
        url = status.definition.upstream_url
        if url:
            name_html = (
                f'<a href="{url}" style="color: #e0e0e0; text-decoration: none; font-weight: bold;">'
                f'{status.definition.display_name}</a>'
            )
        else:
            name_html = f"<b>{status.definition.display_name}</b>"
        self._name_label = QLabel(name_html)
        self._name_label.setTextFormat(Qt.RichText)
        self._name_label.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self._name_label.linkActivated.connect(self._open_url)
        self._name_label.setStyleSheet("color: #e0e0e0; font-size: 13px; background: transparent; border: none;")
        info_col.addWidget(self._name_label)
        desc_label = QLabel(status.definition.description)
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("color: #888; font-size: 11px; background: transparent; border: none;")
        info_col.addWidget(desc_label)
        info_w = QWidget()
        info_w.setLayout(info_col)
        info_w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        info_w.setStyleSheet("background: transparent; border: none;")
        outer.addWidget(info_w, stretch=3)

        centre_col = QVBoxLayout()
        centre_col.setSpacing(4)
        centre_col.setAlignment(Qt.AlignCenter)
        self._badge = QLabel()
        self._badge.setAlignment(Qt.AlignCenter)
        self._badge.setFixedWidth(140)
        self._badge.setStyleSheet("border-radius: 3px; padding: 2px 6px; font-size: 11px; font-weight: bold;")
        centre_col.addWidget(self._badge, alignment=Qt.AlignCenter)
        self._version_label = QLabel()
        self._version_label.setAlignment(Qt.AlignCenter)
        self._version_label.setStyleSheet("color: #777; font-size: 10px; background: transparent; border: none;")
        centre_col.addWidget(self._version_label, alignment=Qt.AlignCenter)
        centre_w = QWidget()
        centre_w.setLayout(centre_col)
        centre_w.setFixedWidth(160)
        centre_w.setStyleSheet("background: transparent; border: none;")
        outer.addWidget(centre_w)

        btn_col = QVBoxLayout()
        btn_col.setSpacing(3)
        btn_col.setAlignment(Qt.AlignCenter)
        self._btn_primary = QPushButton()
        self._btn_primary.setFixedWidth(100)
        self._btn_primary.clicked.connect(self._on_primary)
        btn_col.addWidget(self._btn_primary)
        self._btn_update = QPushButton("Update")
        self._btn_update.setFixedWidth(100)
        self._btn_update.clicked.connect(lambda: self.action_requested.emit(self._tool_id, "update"))
        btn_col.addWidget(self._btn_update)
        self._btn_more = QPushButton("...")
        self._btn_more.setFixedWidth(100)
        self._btn_more.setStyleSheet(btn_style(_C_BACK))
        self._btn_more.clicked.connect(self._on_more)
        btn_col.addWidget(self._btn_more)
        btn_w = QWidget()
        btn_w.setLayout(btn_col)
        btn_w.setFixedWidth(120)
        btn_w.setStyleSheet("background: transparent; border: none;")
        outer.addWidget(btn_w)

        self.setLayout(outer)
        self._refresh_ui()

    def _refresh_ui(self):
        defn = self._status.definition
        installed = self._status.installed
        update_avail = self._status.update_available
        is_active = defn.is_engine and self._active_engine_id == self._tool_id

        if self._busy:
            self._badge.setText("Working...")
            self._badge.setStyleSheet(
                "background-color: #555; color: #ccc; border-radius: 3px; "
                "padding: 2px 6px; font-size: 11px; font-weight: bold; border: none;"
            )
            self._btn_primary.setText(self._busy_label or "Working...")
            self._btn_primary.setEnabled(False)
            self._btn_primary.setVisible(True)
            self._btn_update.setStyleSheet(
                _STYLE_BTN_INVISIBLE
            )
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
            f"padding: 2px 6px; font-size: 11px; font-weight: bold; border: none;"
        )

        iv = self._status.installed_version or "-"
        lv = self._status.latest_version or "checking..."
        self._version_label.setText(f"Installed: {iv}\nLatest: {lv}")

        if not installed:
            self._btn_primary.setText("Install")
            self._btn_primary.setStyleSheet(btn_style(_C_INSTALL))
            self._btn_primary.setEnabled(not self._busy)
            self._btn_primary.setVisible(True)
        elif defn.is_engine:
            if is_active:
                self._btn_primary.setText("Active")
                self._btn_primary.setStyleSheet(btn_style(_C_DISABLED, disabled=True))
                self._btn_primary.setEnabled(False)
            else:
                self._btn_primary.setText("Set Active")
                self._btn_primary.setStyleSheet(btn_style(_C_SET_ACTIVE))
                self._btn_primary.setEnabled(not self._busy)
            self._btn_primary.setVisible(True)
        elif defn.can_launch:
            self._btn_primary.setText("Launch")
            self._btn_primary.setStyleSheet(btn_style(_C_LAUNCH))
            self._btn_primary.setEnabled(not self._busy)
            self._btn_primary.setVisible(True)
        else:
            self._btn_primary.setVisible(False)

        if installed and update_avail and not self._busy:
            self._btn_update.setStyleSheet(btn_style(_C_UPDATE))
            self._btn_update.setEnabled(True)
        else:
            self._btn_update.setStyleSheet(
                _STYLE_BTN_INVISIBLE
            )
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
        cancel_btn.setStyleSheet(btn_style(_C_BACK))
        cancel_btn.setDefault(True)
        cancel_btn.clicked.connect(dlg.reject)
        btn_row.addWidget(cancel_btn)
        uninstall_btn = QPushButton("Uninstall")
        uninstall_btn.setFixedSize(90, 30)
        uninstall_btn.setStyleSheet(btn_style("#8b2020"))
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
