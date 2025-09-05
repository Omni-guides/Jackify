"""
Protontricks Error Dialog

Dialog shown when protontricks is not found, with options to install via Flatpak or get native installation guidance.
"""

from pathlib import Path
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QSizePolicy, QTextEdit, QProgressBar
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QPixmap, QIcon, QFont
from .. import shared_theme


class FlatpakInstallThread(QThread):
    """Thread for installing Flatpak protontricks"""
    finished = Signal(bool, str)  # success, message
    
    def __init__(self, detection_service):
        super().__init__()
        self.detection_service = detection_service
    
    def run(self):
        success, message = self.detection_service.install_flatpak_protontricks()
        self.finished.emit(success, message)


class ProtontricksErrorDialog(QDialog):
    """
    Dialog shown when protontricks is not found
    Provides options to install via Flatpak or get native installation guidance
    """
    
    def __init__(self, detection_service, parent=None):
        super().__init__(parent)
        self.detection_service = detection_service
        self.setWindowTitle("Protontricks Required")
        self.setModal(True)
        self.setFixedSize(550, 520)
        self.install_thread = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)

        # Card background
        card = QFrame(self)
        card.setObjectName("protontricksCard")
        card.setFrameShape(QFrame.StyledPanel)
        card.setFrameShadow(QFrame.Raised)
        card.setMinimumWidth(500)
        card.setMinimumHeight(400)
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(16)
        card_layout.setContentsMargins(28, 28, 28, 28)
        card.setStyleSheet(
            "QFrame#protontricksCard { "
            "  background: #2d2323; "
            "  border-radius: 12px; "
            "  border: 2px solid #e74c3c; "
            "}"
        )

        # Error icon
        icon_label = QLabel()
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setText("!")
        icon_label.setStyleSheet(
            "QLabel { "
            "  font-size: 36px; "
            "  font-weight: bold; "
            "  color: #e74c3c; "
            "  margin-bottom: 4px; "
            "}"
        )
        card_layout.addWidget(icon_label)

        # Error title
        title_label = QLabel("Protontricks Not Found")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet(
            "QLabel { "
            "  font-size: 20px; "
            "  font-weight: 600; "
            "  color: #e74c3c; "
            "  margin-bottom: 2px; "
            "}"
        )
        card_layout.addWidget(title_label)

        # Error message
        message_text = QTextEdit()
        message_text.setReadOnly(True)
        message_text.setPlainText(
            "Protontricks is required for Jackify to function properly. "
            "It manages Wine prefixes for Steam games and is essential for modlist installation and configuration.\n\n"
            "Choose an installation method below:"
        )
        message_text.setMinimumHeight(100)
        message_text.setMaximumHeight(120)
        message_text.setStyleSheet(
            "QTextEdit { "
            "  font-size: 15px; "
            "  color: #e0e0e0; "
            "  background: transparent; "
            "  border: none; "
            "  line-height: 1.3; "
            "  margin-bottom: 6px; "
            "}"
        )
        card_layout.addWidget(message_text)

        # Progress bar (initially hidden)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setStyleSheet(
            "QProgressBar { "
            "  border: 1px solid #555; "
            "  border-radius: 4px; "
            "  background: #23272e; "
            "  text-align: center; "
            "} "
            "QProgressBar::chunk { "
            "  background-color: #4fc3f7; "
            "  border-radius: 3px; "
            "}"
        )
        card_layout.addWidget(self.progress_bar)

        # Status label (initially hidden)
        self.status_label = QLabel()
        self.status_label.setVisible(False)
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet(
            "QLabel { "
            "  font-size: 14px; "
            "  color: #4fc3f7; "
            "  margin: 8px 0; "
            "}"
        )
        card_layout.addWidget(self.status_label)

        # Button layout
        button_layout = QVBoxLayout()
        button_layout.setSpacing(12)

        # Flatpak install button
        self.flatpak_btn = QPushButton("Install via Flatpak (Recommended)")
        self.flatpak_btn.setFixedHeight(40)
        self.flatpak_btn.clicked.connect(self._install_flatpak)
        self.flatpak_btn.setStyleSheet(
            "QPushButton { "
            "  background-color: #4fc3f7; "
            "  color: white; "
            "  border: none; "
            "  border-radius: 6px; "
            "  font-weight: bold; "
            "  font-size: 14px; "
            "  padding: 8px 16px; "
            "} "
            "QPushButton:hover { "
            "  background-color: #3498db; "
            "} "
            "QPushButton:pressed { "
            "  background-color: #2980b9; "
            "} "
            "QPushButton:disabled { "
            "  background-color: #555; "
            "  color: #888; "
            "}"
        )
        button_layout.addWidget(self.flatpak_btn)

        # Native install guidance button
        self.native_btn = QPushButton("Show Native Installation Instructions")
        self.native_btn.setFixedHeight(40)
        self.native_btn.clicked.connect(self._show_native_guidance)
        self.native_btn.setStyleSheet(
            "QPushButton { "
            "  background-color: #95a5a6; "
            "  color: white; "
            "  border: none; "
            "  border-radius: 6px; "
            "  font-weight: bold; "
            "  font-size: 14px; "
            "  padding: 8px 16px; "
            "} "
            "QPushButton:hover { "
            "  background-color: #7f8c8d; "
            "} "
            "QPushButton:pressed { "
            "  background-color: #6c7b7d; "
            "}"
        )
        button_layout.addWidget(self.native_btn)

        card_layout.addLayout(button_layout)

        # Bottom button layout
        bottom_layout = QHBoxLayout()
        bottom_layout.setSpacing(12)

        # Re-detect button
        self.redetect_btn = QPushButton("Re-detect")
        self.redetect_btn.setFixedSize(120, 36)
        self.redetect_btn.clicked.connect(self._redetect)
        self.redetect_btn.setStyleSheet(
            "QPushButton { "
            "  background-color: #27ae60; "
            "  color: white; "
            "  border: none; "
            "  border-radius: 4px; "
            "  font-weight: bold; "
            "  padding: 8px 16px; "
            "} "
            "QPushButton:hover { "
            "  background-color: #229954; "
            "} "
            "QPushButton:pressed { "
            "  background-color: #1e8449; "
            "}"
        )
        bottom_layout.addWidget(self.redetect_btn)

        bottom_layout.addStretch()

        # Exit button
        exit_btn = QPushButton("Exit Jackify")
        exit_btn.setFixedSize(120, 36)
        exit_btn.clicked.connect(self._exit_app)
        exit_btn.setStyleSheet(
            "QPushButton { "
            "  background-color: #e74c3c; "
            "  color: white; "
            "  border: none; "
            "  border-radius: 4px; "
            "  font-weight: bold; "
            "  padding: 8px 16px; "
            "} "
            "QPushButton:hover { "
            "  background-color: #c0392b; "
            "} "
            "QPushButton:pressed { "
            "  background-color: #a93226; "
            "}"
        )
        bottom_layout.addWidget(exit_btn)

        card_layout.addLayout(bottom_layout)

        layout.addStretch()
        layout.addWidget(card, alignment=Qt.AlignCenter)
        layout.addStretch()

    def _install_flatpak(self):
        """Install protontricks via Flatpak"""
        # Disable buttons during installation
        self.flatpak_btn.setEnabled(False)
        self.native_btn.setEnabled(False)
        self.redetect_btn.setEnabled(False)
        
        # Show progress
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminate progress
        self.status_label.setVisible(True)
        self.status_label.setText("Installing Flatpak protontricks...")
        
        # Start installation thread
        self.install_thread = FlatpakInstallThread(self.detection_service)
        self.install_thread.finished.connect(self._on_install_finished)
        self.install_thread.start()

    def _on_install_finished(self, success, message):
        """Handle installation completion"""
        # Hide progress
        self.progress_bar.setVisible(False)
        
        # Re-enable buttons
        self.flatpak_btn.setEnabled(True)
        self.native_btn.setEnabled(True)
        self.redetect_btn.setEnabled(True)
        
        if success:
            self.status_label.setText("✓ Installation successful!")
            self.status_label.setStyleSheet("QLabel { color: #27ae60; font-size: 14px; margin: 8px 0; }")
            # Auto-redetect after successful installation
            self._redetect()
        else:
            self.status_label.setText(f"✗ Installation failed: {message}")
            self.status_label.setStyleSheet("QLabel { color: #e74c3c; font-size: 14px; margin: 8px 0; }")

    def _show_native_guidance(self):
        """Show native installation guidance"""
        from ..services.message_service import MessageService
        guidance = self.detection_service.get_installation_guidance()
        MessageService.information(self, "Native Installation", guidance, safety_level="low")

    def _redetect(self):
        """Re-detect protontricks"""
        self.detection_service.clear_cache()
        is_installed, installation_type, details = self.detection_service.detect_protontricks(use_cache=False)
        
        if is_installed:
            self.status_label.setText("✓ Protontricks found!")
            self.status_label.setStyleSheet("QLabel { color: #27ae60; font-size: 14px; margin: 8px 0; }")
            self.status_label.setVisible(True)
            self.accept()  # Close dialog successfully
        else:
            self.status_label.setText("✗ Protontricks still not found")
            self.status_label.setStyleSheet("QLabel { color: #e74c3c; font-size: 14px; margin: 8px 0; }")
            self.status_label.setVisible(True)

    def _exit_app(self):
        """Exit the application"""
        self.reject()
        import sys
        sys.exit(1)

    def closeEvent(self, event):
        """Handle dialog close event"""
        if self.install_thread and self.install_thread.isRunning():
            self.install_thread.terminate()
            self.install_thread.wait()
        event.accept()