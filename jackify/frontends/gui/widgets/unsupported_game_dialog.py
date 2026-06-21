"""
Unsupported Game Dialog Widget

This module provides a popup dialog to warn users when they're about to install
a modlist for a game that doesn't support automated post-install configuration.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QTextEdit, QFrame
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QPixmap, QIcon


class UnsupportedGameDialog(QDialog):
    """
    Dialog to warn users about unsupported games for post-install configuration.
    
    This dialog informs users that while any modlist can be downloaded with Jackify,
    only certain games support automated post-install configuration.
    """
    
    # Signal emitted when user clicks OK to continue
    continue_installation = Signal()
    
    def __init__(self, parent=None, game_name: str = None, vr_warning: bool = False):
        super().__init__(parent)
        self.game_name = game_name
        self.vr_warning = vr_warning
        self.setup_ui()
        self.setup_connections()

    def setup_ui(self):
        """Set up the dialog UI."""
        self.setWindowTitle("VR Platform Notice" if self.vr_warning else "Game Support Notice")
        self.setModal(True)
        self.setFixedSize(500, 500)
        
        # Main layout
        layout = QVBoxLayout()
        layout.setSpacing(20)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Icon and title (smaller, less vertical space)
        title_layout = QHBoxLayout()
        icon_label = QLabel("!")
        icon_label.setFont(QFont("Arial", 18, QFont.Weight.Bold))
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setFixedSize(32, 32)
        icon_label.setStyleSheet("color: #f0c040;")
        title_layout.addWidget(icon_label)
        title_label = QLabel("<b>VR Platform Notice</b>" if self.vr_warning else "<b>Game Support Notice</b>")
        title_label.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        title_label.setStyleSheet("color: #3fd0ea;")
        title_layout.addWidget(title_label)
        title_layout.addStretch()
        layout.addLayout(title_layout)
        # Reduce space after title
        layout.addSpacing(4)
        # Separator line
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        separator.setStyleSheet("background: #444; max-height: 1px;")
        layout.addWidget(separator)
        # Reduce space after separator
        layout.addSpacing(4)
        # Message text
        message_text = QTextEdit()
        message_text.setReadOnly(True)
        message_text.setMaximumHeight(340)
        message_text.setStyleSheet("""
            QTextEdit {
                background-color: #23272e;
                color: #e0e0e0;
                border: 1px solid #444;
                border-radius: 6px;
                padding: 12px;
                font-size: 12px;
                font-family: 'Segoe UI', Arial, sans-serif;
            }
        """)
        
        # Create the message content
        if self.vr_warning:
            game_label = self.game_name or "a VR modlist"
            message = f"""<p><strong>You are about to install {game_label}.</strong></p>

<p>Jackify will handle the download, Wine prefix setup, and Steam shortcut creation as normal. However, getting VR modlists running on Linux involves platform dependencies that are outside Jackify's control:</p>

<ul>
<li>SteamVR must be installed and working with your headset before launching</li>
<li>Your VR runtime (SteamVR, ALVR, WiVRn, etc.) must be configured separately</li>
<li>Some modlists may require additional manual steps documented by the list author</li>
</ul>

<p>Jackify's VR support is <strong>best effort</strong>. The install and configuration will proceed normally, but whether the modlist runs correctly depends heavily on your VR platform setup.</p>

<p><strong>Always consult your modlist's installation guide</strong> for any additional manual steps required after Jackify completes.</p>

<p>Click <strong>Continue</strong> to proceed, or <strong>Cancel</strong> to go back.</p>"""
        elif self.game_name:
            message = f"""<p><strong>You are about to install a modlist for <em>{self.game_name}</em>.</strong></p>

<p>While any modlist can be downloaded with Jackify, the post-install configuration can only be automatically applied to:</p>

<ul>
<li><strong>Skyrim Special Edition</strong></li>
<li><strong>Fallout 4</strong></li>
<li><strong>Fallout New Vegas</strong></li>
<li><strong>Oblivion</strong></li>
<li><strong>Starfield</strong></li>
<li><strong>Oblivion Remastered</strong></li>
<li><strong>Enderal</strong></li>
</ul>

<p>For unsupported games, you will need to manually configure Steam shortcuts and other post-install steps.</p>

<p><em>We are working to add more automated support in future releases!</em></p>

<p>Click <strong>Continue</strong> to proceed with the modlist installation, or <strong>Cancel</strong> to go back.</p>"""
        else:
            message = f"""<p><strong>You are about to install a modlist for an unsupported game.</strong></p>

<p>While any modlist can be downloaded with Jackify, the post-install configuration can only be automatically applied to:</p>

<ul>
<li><strong>Skyrim Special Edition</strong></li>
<li><strong>Fallout 4</strong></li>
<li><strong>Fallout New Vegas</strong></li>
<li><strong>Oblivion</strong></li>
<li><strong>Starfield</strong></li>
<li><strong>Oblivion Remastered</strong></li>
<li><strong>Enderal</strong></li>
</ul>

<p>For unsupported games, you will need to manually configure Steam shortcuts and other post-install steps.</p>

<p><em>We are working to add more automated support in future releases!</em></p>

<p>Click <strong>Continue</strong> to proceed with the modlist installation, or <strong>Cancel</strong> to go back.</p>"""
        
        message_text.setHtml(message)
        layout.addWidget(message_text)
        
        # Button layout (Continue left, Cancel right)
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        continue_button = QPushButton("Continue")
        continue_button.setFixedSize(100, 35)
        continue_button.setDefault(True)
        continue_button.setStyleSheet("""
            QPushButton {
                background-color: #3fd0ea;
                color: #23272e;
                border: none;
                border-radius: 5px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2bb8d6;
            }
            QPushButton:pressed {
                background-color: #1a7e99;
            }
        """)
        button_layout.addWidget(continue_button)
        cancel_button = QPushButton("Cancel")
        cancel_button.setFixedSize(100, 35)
        cancel_button.setStyleSheet("""
            QPushButton {
                background-color: #6c757d;
                color: white;
                border: none;
                border-radius: 5px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #5a6268;
            }
            QPushButton:pressed {
                background-color: #545b62;
            }
        """)
        button_layout.addWidget(cancel_button)
        layout.addLayout(button_layout)
        self.setLayout(layout)
        self.cancel_button = cancel_button
        self.continue_button = continue_button
        self.setStyleSheet("""
            QDialog {
                background-color: #23272e;
                color: #e0e0e0;
            }
            QLabel {
                color: #e0e0e0;
            }
        """)
    
    def setup_connections(self):
        """Set up signal connections."""
        self.cancel_button.clicked.connect(self.reject)
        self.continue_button.clicked.connect(self.accept)
        self.accepted.connect(self.continue_installation.emit)
    
    @staticmethod
    def show_dialog(parent=None, game_name: str = None, vr_warning: bool = False) -> bool:
        """
        Show the dialog and return the user's choice.

        Args:
            parent: Parent widget
            game_name: Name of the game (optional)
            vr_warning: Show VR best-effort warning instead of unsupported game notice

        Returns:
            True if user clicked Continue, False if Cancel
        """
        dialog = UnsupportedGameDialog(parent, game_name, vr_warning=vr_warning)
        result = dialog.exec()
        return result == QDialog.DialogCode.Accepted 