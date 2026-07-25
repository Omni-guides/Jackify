"""
Game Proton Warning Dialog

Shown to recommend a Proton version for the modlist's game type, mirroring
enb_proton_dialog.py's structure and behavior.
"""

import logging
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSizePolicy, QFrame
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon

logger = logging.getLogger(__name__)


class GameProtonWarningDialog(QDialog):
    """Dialog recommending a Proton version for the modlist's game."""

    def __init__(self, modlist_name: str, warning: dict, game_label: str, parent=None):
        super().__init__(parent)
        self.modlist_name = modlist_name
        self.setWindowTitle("Recommended Proton Version")
        self.setWindowModality(Qt.ApplicationModal)
        self.setFixedSize(600, 420)
        self.setStyleSheet("QDialog { background: #181818; color: #fff; border-radius: 12px; }")

        layout = QVBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(30, 30, 30, 30)

        card = QFrame(self)
        card.setObjectName("gameProtonCard")
        card.setFrameShape(QFrame.StyledPanel)
        card.setFrameShadow(QFrame.Raised)
        card.setFixedWidth(540)
        card.setMinimumHeight(280)
        card.setMaximumHeight(16777215)
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(16)
        card_layout.setContentsMargins(28, 28, 28, 28)
        card.setStyleSheet(
            "QFrame#gameProtonCard { "
            "  background: #23272e; "
            "  border-radius: 12px; "
            "  border: 2px solid #3fb7d6;"
            "}"
        )
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.MinimumExpanding)

        title_label = QLabel("Recommended Proton Version")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet(
            "QLabel { font-size: 24px; font-weight: 700; color: #3fb7d6; margin-bottom: 4px; }"
        )
        card_layout.addWidget(title_label)

        warning_label = QLabel(
            f"The following Proton versions are recommended for {game_label}:"
        )
        warning_label.setAlignment(Qt.AlignCenter)
        warning_label.setWordWrap(True)
        warning_label.setStyleSheet(
            "QLabel { font-size: 14px; color: #e0e0e0; line-height: 1.5; margin-bottom: 12px; padding: 8px; }"
        )
        card_layout.addWidget(warning_label)

        recommended = warning.get("recommended", [])
        recommended_html = "<br/>".join(f"- <b style='color: #3fd0ea;'>{v}</b>" for v in recommended)
        details_text = (
            "<div style='text-align: left; padding: 12px; background: #1a1d23; border-radius: 8px; margin: 8px 0;'>"
            "<div style='font-size: 13px; color: #b0b0b0; margin-bottom: 8px;'><b style='color: #fff;'>(In order of recommendation)</b></div>"
            f"<div style='font-size: 14px; color: #fff; line-height: 1.8;'>{recommended_html}</div>"
            "</div>"
        )
        details_label = QLabel(details_text)
        details_label.setAlignment(Qt.AlignLeft)
        details_label.setWordWrap(True)
        details_label.setStyleSheet(
            "QLabel { font-size: 14px; color: #e0e0e0; line-height: 1.6; margin: 8px 0; }"
        )
        details_label.setTextFormat(Qt.RichText)
        card_layout.addWidget(details_label)

        layout.addStretch()
        layout.addWidget(card, alignment=Qt.AlignCenter)
        layout.addSpacing(20)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.ok_btn = QPushButton("I Understand (3s)")
        self.ok_btn.setEnabled(False)
        self.ok_btn.setStyleSheet(
            "QPushButton { background: #3fb7d6; color: #fff; border: none; border-radius: 6px; "
            "padding: 10px 24px; font-size: 14px; font-weight: 600; }"
            "QPushButton:hover { background: #35a5c2; }"
            "QPushButton:pressed { background: #2d8fa8; }"
            "QPushButton:disabled { background: #555; color: #aaa; }"
        )
        self.ok_btn.clicked.connect(self.accept)
        btn_row.addWidget(self.ok_btn)

        self._protect_countdown = 3
        self._protect_timer = QTimer(self)
        self._protect_timer.setInterval(1000)
        self._protect_timer.timeout.connect(self._on_protect_tick)
        self._protect_timer.start()
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._set_dialog_icon()

        logger.info(f"GameProtonWarningDialog created for modlist: {modlist_name}")

    def _on_protect_tick(self):
        self._protect_countdown -= 1
        if self._protect_countdown > 0:
            self.ok_btn.setText(f"I Understand ({self._protect_countdown}s)")
        else:
            self._protect_timer.stop()
            self.ok_btn.setText("I Understand")
            self.ok_btn.setEnabled(True)

    def _set_dialog_icon(self):
        try:
            icon_path = Path(__file__).parent.parent.parent.parent.parent / "Files" / "wabbajack-icon.png"
            if icon_path.exists():
                icon = QIcon(str(icon_path))
                self.setWindowIcon(icon)
        except Exception as e:
            logger.debug(f"Could not set dialog icon: {e}")
