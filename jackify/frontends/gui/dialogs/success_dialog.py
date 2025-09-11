"""
Success Dialog

Celebration dialog shown when workflows complete successfully.
Features trophy icon, personalized messaging, and time tracking.
"""

import logging
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QWidget, 
    QSpacerItem, QSizePolicy, QFrame, QApplication
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap, QIcon, QFont

logger = logging.getLogger(__name__)


class SuccessDialog(QDialog):
    """
    Celebration dialog shown when workflows complete successfully.
    
    Features:
    - Trophy icon
    - Personalized success message
    - Time taken display
    - Next steps guidance
    - Return and Exit buttons
    """
    
    def __init__(self, modlist_name: str, workflow_type: str, time_taken: str, game_name: str = None, parent=None):
        super().__init__(parent)
        self.modlist_name = modlist_name
        self.workflow_type = workflow_type
        self.time_taken = time_taken
        self.game_name = game_name
        self.setWindowTitle("Success!")
        self.setWindowModality(Qt.NonModal)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setFixedSize(500, 420)
        self.setWindowFlag(Qt.WindowDoesNotAcceptFocus, True)
        self.setStyleSheet("QDialog { background: #181818; color: #fff; border-radius: 12px; }" )
        layout = QVBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)

        # --- Card background for content ---
        card = QFrame(self)
        card.setObjectName("successCard")
        card.setFrameShape(QFrame.StyledPanel)
        card.setFrameShadow(QFrame.Raised)
        card.setFixedWidth(440)
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(12)
        card_layout.setContentsMargins(28, 28, 28, 28)
        card.setStyleSheet(
            "QFrame#successCard { "
            "  background: #23272e; "
            "  border-radius: 12px; "
            "  border: 1px solid #353a40; "
            "}"
        )
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # Trophy icon (smaller, more subtle)
        trophy_label = QLabel()
        trophy_label.setAlignment(Qt.AlignCenter)
        trophy_icon_path = Path(__file__).parent.parent.parent.parent.parent / "Files" / "trophy.png"
        if trophy_icon_path.exists():
            pixmap = QPixmap(str(trophy_icon_path)).scaled(36, 36, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            trophy_label.setPixmap(pixmap)
        else:
            trophy_label.setText("✓")
            trophy_label.setStyleSheet(
                "QLabel { "
                "  font-size: 28px; "
                "  margin-bottom: 4px; "
                "}"
            )
        card_layout.addWidget(trophy_label)

        # Success title (less saturated green)
        title_label = QLabel("Success!")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet(
            "QLabel { "
            "  font-size: 22px; "
            "  font-weight: 600; "
            "  color: #2ecc71; "
            "  margin-bottom: 2px; "
            "}"
        )
        card_layout.addWidget(title_label)

        # Personalized success message (modlist name in Jackify Blue, but less bold)
        message_text = self._build_success_message()
        modlist_name_html = f'<span style="color:#3fb7d6; font-size:17px; font-weight:500;">{self.modlist_name}</span>'
        if self.workflow_type == "install":
            message_html = f"<span style='font-size:15px;'>{modlist_name_html} installed successfully!</span>"
        else:
            message_html = message_text
        message_label = QLabel(message_html)
        message_label.setAlignment(Qt.AlignCenter)
        message_label.setWordWrap(True)
        message_label.setStyleSheet(
            "QLabel { "
            "  font-size: 15px; "
            "  color: #e0e0e0; "
            "  line-height: 1.3; "
            "  margin-bottom: 6px; "
            "  max-width: 400px; "
            "  min-width: 200px; "
            "  word-wrap: break-word; "
            "}"
        )
        message_label.setTextFormat(Qt.RichText)
        card_layout.addWidget(message_label)

        # Time taken
        time_label = QLabel(f"Completed in {self.time_taken}")
        time_label.setAlignment(Qt.AlignCenter)
        time_label.setStyleSheet(
            "QLabel { "
            "  font-size: 12px; "
            "  color: #b0b0b0; "
            "  font-style: italic; "
            "  margin-bottom: 10px; "
            "}"
        )
        card_layout.addWidget(time_label)

        # Next steps guidance
        next_steps_text = self._build_next_steps()
        next_steps_label = QLabel(next_steps_text)
        next_steps_label.setAlignment(Qt.AlignCenter)
        next_steps_label.setWordWrap(True)
        next_steps_label.setStyleSheet(
            "QLabel { "
            "  font-size: 13px; "
            "  color: #b0b0b0; "
            "  line-height: 1.2; "
            "  padding: 6px; "
            "  background-color: transparent; "
            "  border-radius: 6px; "
            "  border: none; "
            "}"
        )
        card_layout.addWidget(next_steps_label)

        # Subtle Ko-Fi support link
        kofi_label = QLabel('<a href="https://ko-fi.com/omni1" style="color:#72A5F2; text-decoration:none;">Enjoying Jackify? Support development ♥</a>')
        kofi_label.setAlignment(Qt.AlignCenter)
        kofi_label.setStyleSheet(
            "QLabel { "
            "  color: #72A5F2; "
            "  font-size: 11px; "
            "  margin-top: 8px; "
            "  padding: 4px; "
            "  background-color: transparent; "
            "}"
        )
        kofi_label.setTextInteractionFlags(Qt.TextBrowserInteraction)
        kofi_label.setOpenExternalLinks(True)
        card_layout.addWidget(kofi_label)

        layout.addStretch()
        layout.addWidget(card, alignment=Qt.AlignCenter)
        layout.addStretch()

        # Action buttons
        btn_row = QHBoxLayout()
        self.return_btn = QPushButton("Return")
        self.exit_btn = QPushButton("Exit")
        btn_row.addWidget(self.return_btn)
        btn_row.addWidget(self.exit_btn)
        layout.addLayout(btn_row)
        # Now set up the timer/countdown logic AFTER buttons are created
        self.return_btn.setEnabled(False)
        self.exit_btn.setEnabled(False)
        self._countdown = 3
        self._orig_return_text = self.return_btn.text()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_countdown)
        self._update_countdown()
        self._timer.start(1000)
        self.return_btn.clicked.connect(self.accept)
        self.exit_btn.clicked.connect(QApplication.quit)

        # Set the Wabbajack icon if available
        self._set_dialog_icon()
        
        logger.info(f"SuccessDialog created for {workflow_type}: {modlist_name} (completed in {time_taken})")
    
    def _set_dialog_icon(self):
        """Set the dialog icon to Wabbajack icon if available"""
        try:
            # Try to use the same icon as the main application
            icon_path = Path(__file__).parent.parent.parent.parent.parent / "Files" / "wabbajack-icon.png"
            if icon_path.exists():
                icon = QIcon(str(icon_path))
                self.setWindowIcon(icon)
        except Exception as e:
            logger.debug(f"Could not set dialog icon: {e}")
    
    def _setup_ui(self):
        """Set up the dialog user interface"""
        pass # This method is no longer needed as __init__ handles UI setup
    
    def _setup_buttons(self, layout):
        """Set up the action buttons"""
        pass # This method is no longer needed as __init__ handles button setup
    
    def _build_success_message(self) -> str:
        """
        Build the personalized success message based on workflow type.
        
        Returns:
            Formatted success message string
        """
        workflow_messages = {
            "install": f"{self.modlist_name} installed successfully!",
            "configure_new": f"{self.modlist_name} configured successfully!",
            "configure_existing": f"{self.modlist_name} configuration updated successfully!",
            "tuxborn": f"Tuxborn installation completed successfully!",
        }
        
        return workflow_messages.get(self.workflow_type, f"{self.modlist_name} completed successfully!")
    
    def _build_next_steps(self) -> str:
        """
        Build the next steps guidance based on workflow type.
        
        Returns:
            Formatted next steps string
        """
        game_display = self.game_name or self.modlist_name
        if self.workflow_type == "tuxborn":
            return f"You can now launch Tuxborn from Steam and enjoy your modded {game_display} experience!"
        else:
            return f"You can now launch {self.modlist_name} from Steam and enjoy your modded {game_display} experience!" 

    def _update_countdown(self):
        if self._countdown > 0:
            self.return_btn.setText(f"{self._orig_return_text} ({self._countdown}s)")
            self.return_btn.setEnabled(False)
            self.exit_btn.setEnabled(False)
            self._countdown -= 1
        else:
            self.return_btn.setText(self._orig_return_text)
            self.return_btn.setEnabled(True)
            self.exit_btn.setEnabled(True)
            self._timer.stop() 