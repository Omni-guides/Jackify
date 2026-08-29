"""
Warning Dialog

Custom warning dialog for destructive actions (e.g., deleting directory contents).
Matches Jackify theming and requires explicit user confirmation.
"""

from pathlib import Path
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QFrame, QSizePolicy
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
        # Sized to the message rather than fixed - a clipped destructive warning is the one
        # thing this dialog must never do
        self.setMinimumWidth(500)
        self.setMaximumWidth(560)
        self.confirmed = False
        self._failed_attempts = 0
        self._max_attempts = 3
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
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(10)
        card_layout.setContentsMargins(28, 20, 28, 22)
        card.setStyleSheet(
            "QFrame#warningCard { "
            "  background: #2d2323; "
            "  border-radius: 12px; "
            "  border: 2px solid #f0c040; "
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
            "  color: #f0c040; "
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
            "  color: #f0c040; "
            "  margin-bottom: 2px; "
            "}"
        )
        card_layout.addWidget(title_label)

        message_text = QLabel(warning_message)
        message_text.setWordWrap(True)
        message_text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        message_text.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        message_text.setStyleSheet(
            "QLabel { "
            "  font-size: 15px; "
            "  color: #e0e0e0; "
            "  background: transparent; "
            "  border: none; "
            "  padding: 4px 6px 10px 6px; "
            "}"
        )
        card_layout.addWidget(message_text)

        # Confirmation entry
        self.confirm_label = QLabel("Type 'DELETE' to confirm (all caps):")
        self.confirm_label.setAlignment(Qt.AlignCenter)
        self.confirm_label.setStyleSheet(
            "QLabel { "
            "  font-size: 13px; "
            "  color: #f0c040; "
            "  margin-bottom: 2px; "
            "}"
        )
        card_layout.addWidget(self.confirm_label)

        self.confirm_edit = QLineEdit()
        self.confirm_edit.setAlignment(Qt.AlignCenter)
        self.confirm_edit.setPlaceholderText("DELETE")
        self._default_lineedit_style = (
            "QLineEdit { "
            "  font-size: 15px; "
            "  border: 1px solid #f0c040; "
            "  border-radius: 6px; "
            "  padding: 6px; "
            "  background: #23272e; "
            "  color: #e0e0e0; "
            "}"
        )
        self.confirm_edit.setStyleSheet(self._default_lineedit_style)
        self.confirm_edit.textChanged.connect(self._on_text_changed)
        self.confirm_edit.returnPressed.connect(self._on_confirm)  # Handle Enter key
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
            "  background-color: #4a5568; "
            "  color: white; "
            "  border: none; "
            "  border-radius: 4px; "
            "  font-weight: bold; "
            "  padding: 8px 16px; "
            "} "
            "QPushButton:hover { "
            "  background-color: #5a6578; "
            "} "
            "QPushButton:pressed { "
            "  background-color: #3fd0ea; "
            "}"
        )
        button_layout.addWidget(cancel_btn)

        confirm_btn = QPushButton("Proceed")
        confirm_btn.setFixedSize(120, 36)
        confirm_btn.clicked.connect(self._on_confirm)
        confirm_btn.setStyleSheet(
            "QPushButton { "
            "  background-color: #8b2020; "
            "  color: white; "
            "  border: none; "
            "  border-radius: 4px; "
            "  font-weight: bold; "
            "  padding: 8px 16px; "
            "} "
            "QPushButton:hover { "
            "  background-color: #a02828; "
            "} "
            "QPushButton:pressed { "
            "  background-color: #7a1a1a; "
            "}"
        )
        button_layout.addWidget(confirm_btn)
        button_layout.addStretch()
        card_layout.addLayout(button_layout)

        layout.addStretch()
        layout.addWidget(card, alignment=Qt.AlignCenter)
        layout.addStretch()

    def _on_text_changed(self):
        """Reset error styling when user starts typing again."""
        # Only reset if currently showing error state (darker background)
        if "#3b2323" in self.confirm_edit.styleSheet():
            self.confirm_edit.setStyleSheet(self._default_lineedit_style)
            self.confirm_edit.setPlaceholderText("DELETE")

            # Reset label but keep attempt counter if attempts were made
            if self._failed_attempts > 0:
                remaining = self._max_attempts - self._failed_attempts
                self.confirm_label.setText(f"Type 'DELETE' to confirm (all caps) - {remaining} attempt(s) remaining:")
            else:
                self.confirm_label.setText("Type 'DELETE' to confirm (all caps):")

            self.confirm_label.setStyleSheet(
                "QLabel { "
                "  font-size: 13px; "
                "  color: #f0c040; "
                "  margin-bottom: 2px; "
                "}"
            )

    def _on_confirm(self):
        entered_text = self.confirm_edit.text().strip()

        if entered_text == "DELETE":
            # Correct - proceed
            self.confirmed = True
            self.accept()
        else:
            # Wrong text entered
            self._failed_attempts += 1

            if self._failed_attempts >= self._max_attempts:
                # Too many failed attempts - cancel automatically
                self.confirmed = False
                self.reject()
                return

            # Still have attempts remaining - clear field and show error feedback
            self.confirm_edit.clear()

            # Update label to show remaining attempts
            remaining = self._max_attempts - self._failed_attempts
            self.confirm_label.setText(f"Wrong! Type 'DELETE' exactly (all caps) - {remaining} attempt(s) remaining:")
            self.confirm_label.setStyleSheet(
                "QLabel { "
                "  font-size: 13px; "
                "  color: #e05050; "
                "  margin-bottom: 2px; "
                "  font-weight: bold; "
                "}"
            )

            # Show error state in text field
            self.confirm_edit.setPlaceholderText(f"Type DELETE ({remaining} attempts left)")
            self.confirm_edit.setStyleSheet(
                "QLineEdit { "
                "  font-size: 15px; "
                "  border: 2px solid #8b2020; "
                "  border-radius: 6px; "
                "  padding: 6px; "
                "  background: #3b2323; "
                "  color: #e0e0e0; "
                "}"
            ) 