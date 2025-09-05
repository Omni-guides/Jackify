"""
Warning Dialog

Custom warning dialog for destructive actions (e.g., deleting directory contents).
Matches Jackify theming and requires explicit user confirmation.
"""

from pathlib import Path
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QFrame, QSizePolicy, QTextEdit
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QIcon, QFont
from .. import shared_theme

class WarningDialog(QDialog):
    """
    Jackify-themed warning dialog for dangerous/destructive actions.
    Requires user to type 'DELETE' to confirm.
    """
    def __init__(self, warning_message: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Warning!")
        self.setModal(True)
        # Increased height for better text display, scalable for 800p screens
        self.setFixedSize(500, 440)
        self.confirmed = False
        self._setup_ui(warning_message)

    def _setup_ui(self, warning_message):
        layout = QVBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)

        # Card background
        card = QFrame(self)
        card.setObjectName("warningCard")
        card.setFrameShape(QFrame.StyledPanel)
        card.setFrameShadow(QFrame.Raised)
        card.setMinimumWidth(440)
        card.setMinimumHeight(320)
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(16)
        card_layout.setContentsMargins(28, 28, 28, 28)
        card.setStyleSheet(
            "QFrame#warningCard { "
            "  background: #2d2323; "
            "  border-radius: 12px; "
            "  border: 2px solid #e67e22; "
            "}"
        )

        # Warning icon
        icon_label = QLabel()
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setText("!")
        icon_label.setStyleSheet(
            "QLabel { "
            "  font-size: 36px; "
            "  font-weight: bold; "
            "  color: #e67e22; "
            "  margin-bottom: 4px; "
            "}"
        )
        card_layout.addWidget(icon_label)

        # Warning title
        title_label = QLabel("Potentially Destructive Action!")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet(
            "QLabel { "
            "  font-size: 20px; "
            "  font-weight: 600; "
            "  color: #e67e22; "
            "  margin-bottom: 2px; "
            "}"
        )
        card_layout.addWidget(title_label)

        # Warning message (use a scrollable text area for long messages)
        message_text = QTextEdit()
        message_text.setReadOnly(True)
        message_text.setPlainText(warning_message)
        message_text.setMinimumHeight(80)
        message_text.setMaximumHeight(160)
        message_text.setStyleSheet(
            "QTextEdit { "
            "  font-size: 15px; "
            "  color: #e0e0e0; "
            "  background: transparent; "
            "  border: none; "
            "  line-height: 1.3; "
            "  margin-bottom: 6px; "
            "  max-width: 400px; "
            "  min-width: 200px; "
            "}"
        )
        card_layout.addWidget(message_text)

        # Confirmation entry
        confirm_label = QLabel("Type 'DELETE' to confirm:")
        confirm_label.setAlignment(Qt.AlignCenter)
        confirm_label.setStyleSheet(
            "QLabel { "
            "  font-size: 13px; "
            "  color: #e67e22; "
            "  margin-bottom: 2px; "
            "}"
        )
        card_layout.addWidget(confirm_label)

        self.confirm_edit = QLineEdit()
        self.confirm_edit.setAlignment(Qt.AlignCenter)
        self.confirm_edit.setPlaceholderText("DELETE")
        self.confirm_edit.setStyleSheet(
            "QLineEdit { "
            "  font-size: 15px; "
            "  border: 1px solid #e67e22; "
            "  border-radius: 6px; "
            "  padding: 6px; "
            "  background: #23272e; "
            "  color: #e67e22; "
            "}"
        )
        card_layout.addWidget(self.confirm_edit)

        # Action buttons
        button_layout = QHBoxLayout()
        button_layout.setSpacing(12)
        button_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedSize(120, 36)
        cancel_btn.clicked.connect(self.reject)
        cancel_btn.setStyleSheet(
            "QPushButton { "
            "  background-color: #95a5a6; "
            "  color: white; "
            "  border: none; "
            "  border-radius: 4px; "
            "  font-weight: bold; "
            "  padding: 8px 16px; "
            "} "
            "QPushButton:hover { "
            "  background-color: #7f8c8d; "
            "} "
            "QPushButton:pressed { "
            "  background-color: #6c7b7d; "
            "}"
        )
        button_layout.addWidget(cancel_btn)

        confirm_btn = QPushButton("Proceed")
        confirm_btn.setFixedSize(120, 36)
        confirm_btn.clicked.connect(self._on_confirm)
        confirm_btn.setStyleSheet(
            "QPushButton { "
            "  background-color: #e67e22; "
            "  color: white; "
            "  border: none; "
            "  border-radius: 4px; "
            "  font-weight: bold; "
            "  padding: 8px 16px; "
            "} "
            "QPushButton:hover { "
            "  background-color: #d35400; "
            "} "
            "QPushButton:pressed { "
            "  background-color: #b34700; "
            "}"
        )
        button_layout.addWidget(confirm_btn)
        button_layout.addStretch()
        card_layout.addLayout(button_layout)

        layout.addStretch()
        layout.addWidget(card, alignment=Qt.AlignCenter)
        layout.addStretch()

    def _on_confirm(self):
        if self.confirm_edit.text().strip().upper() == "DELETE":
            self.confirmed = True
            self.accept()
        else:
            self.confirm_edit.setText("")
            self.confirm_edit.setPlaceholderText("Type DELETE to confirm")
            self.confirm_edit.setStyleSheet(self.confirm_edit.styleSheet() + "QLineEdit { background: #3b2323; }") 