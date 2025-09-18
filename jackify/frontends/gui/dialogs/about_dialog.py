"""
About dialog for Jackify.

This dialog displays system information, version details, and provides
access to update checking and external links.
"""

import logging
import os
import platform
import subprocess
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QGroupBox, QTextEdit, QApplication
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont, QClipboard

from ....backend.services.update_service import UpdateService
from ....backend.models.configuration import SystemInfo
from .... import __version__

logger = logging.getLogger(__name__)


class UpdateCheckThread(QThread):
    """Background thread for checking updates."""
    
    update_check_finished = Signal(object)  # UpdateInfo or None
    
    def __init__(self, update_service: UpdateService):
        super().__init__()
        self.update_service = update_service
    
    def run(self):
        """Check for updates in background."""
        try:
            update_info = self.update_service.check_for_updates()
            self.update_check_finished.emit(update_info)
        except Exception as e:
            logger.error(f"Error checking for updates: {e}")
            self.update_check_finished.emit(None)


class AboutDialog(QDialog):
    """About dialog showing system info and app details."""
    
    def __init__(self, system_info: SystemInfo, parent=None):
        super().__init__(parent)
        self.system_info = system_info
        self.update_service = UpdateService(__version__)
        self.update_check_thread = None
        
        self.setup_ui()
        self.setup_connections()
        
    def setup_ui(self):
        """Set up the dialog UI."""
        self.setWindowTitle("About Jackify")
        self.setModal(True)
        self.setFixedSize(520, 520)
        
        layout = QVBoxLayout(self)
        
        # Header
        header_layout = QVBoxLayout()
        
        # App icon/name
        title_label = QLabel("Jackify")
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("color: #3fd0ea; margin: 10px;")
        header_layout.addWidget(title_label)
        
        subtitle_label = QLabel(f"v{__version__}")
        subtitle_font = QFont()
        subtitle_font.setPointSize(12)
        subtitle_label.setFont(subtitle_font)
        subtitle_label.setAlignment(Qt.AlignCenter)
        subtitle_label.setStyleSheet("color: #666; margin-bottom: 10px;")
        header_layout.addWidget(subtitle_label)
        
        tagline_label = QLabel("Simplifying Wabbajack modlist installation and configuration on Linux")
        tagline_label.setAlignment(Qt.AlignCenter)
        tagline_label.setStyleSheet("color: #888; margin-bottom: 20px;")
        header_layout.addWidget(tagline_label)
        
        layout.addLayout(header_layout)
        
        # System Information Group
        system_group = QGroupBox("System Information")
        system_layout = QVBoxLayout(system_group)
        
        system_info_text = self._get_system_info_text()
        system_info_label = QLabel(system_info_text)
        system_info_label.setStyleSheet("font-family: monospace; font-size: 10pt; color: #ccc;")
        system_info_label.setWordWrap(True)
        system_layout.addWidget(system_info_label)
        
        layout.addWidget(system_group)
        
        # Jackify Information Group
        jackify_group = QGroupBox("Jackify Information")
        jackify_layout = QVBoxLayout(jackify_group)
        
        jackify_info_text = self._get_jackify_info_text()
        jackify_info_label = QLabel(jackify_info_text)
        jackify_info_label.setStyleSheet("font-family: monospace; font-size: 10pt; color: #ccc;")
        jackify_layout.addWidget(jackify_info_label)
        
        layout.addWidget(jackify_group)
        
        # Update status
        self.update_status_label = QLabel("")
        self.update_status_label.setStyleSheet("color: #666; font-size: 10pt; margin: 5px;")
        self.update_status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.update_status_label)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        # Update check button
        self.update_button = QPushButton("Check for Updates")
        self.update_button.clicked.connect(self.check_for_updates)
        self.update_button.setStyleSheet("""
            QPushButton {
                background-color: #23272e;
                color: #3fd0ea;
                font-weight: bold;
                padding: 8px 16px;
                border-radius: 4px;
                border: 2px solid #3fd0ea;
            }
            QPushButton:hover {
                background-color: #3fd0ea;
                color: #23272e;
            }
            QPushButton:pressed {
                background-color: #2bb8d6;
                color: #23272e;
            }
            QPushButton:disabled {
                background-color: #444;
                color: #666;
                border-color: #666;
            }
        """)
        button_layout.addWidget(self.update_button)
        
        button_layout.addStretch()
        
        # Copy Info button
        copy_button = QPushButton("Copy Info")
        copy_button.clicked.connect(self.copy_system_info)
        button_layout.addWidget(copy_button)
        
        # External links
        github_button = QPushButton("GitHub")
        github_button.clicked.connect(self.open_github)
        button_layout.addWidget(github_button)
        
        nexus_button = QPushButton("Nexus")
        nexus_button.clicked.connect(self.open_nexus)
        button_layout.addWidget(nexus_button)
        
        layout.addLayout(button_layout)
        
        # Close button
        close_layout = QHBoxLayout()
        close_layout.addStretch()
        close_button = QPushButton("Close")
        close_button.setDefault(True)
        close_button.clicked.connect(self.accept)
        close_layout.addWidget(close_button)
        layout.addLayout(close_layout)
        
    def setup_connections(self):
        """Set up signal connections."""
        pass
    
    def _get_system_info_text(self) -> str:
        """Get formatted system information."""
        try:
            # OS info
            os_info = self._get_os_info()
            kernel = platform.release()
            
            # Desktop environment
            desktop = self._get_desktop_environment()
            
            # Display server
            display_server = self._get_display_server()
            
            return f"• OS: {os_info}\n• Kernel: {kernel}\n• Desktop: {desktop}\n• Display: {display_server}"
            
        except Exception as e:
            logger.error(f"Error getting system info: {e}")
            return "• System info unavailable"
    
    def _get_jackify_info_text(self) -> str:
        """Get formatted Jackify information."""
        try:
            # Engine version
            engine_version = self._get_engine_version()
            
            # Python version
            python_version = platform.python_version()
            
            return f"• Engine: {engine_version}\n• Python: {python_version}"
            
        except Exception as e:
            logger.error(f"Error getting Jackify info: {e}")
            return "• Jackify info unavailable"
    
    def _get_os_info(self) -> str:
        """Get OS distribution name and version."""
        try:
            if os.path.exists("/etc/os-release"):
                with open("/etc/os-release", "r") as f:
                    lines = f.readlines()
                    pretty_name = None
                    name = None
                    version = None
                    
                    for line in lines:
                        line = line.strip()
                        if line.startswith("PRETTY_NAME="):
                            pretty_name = line.split("=", 1)[1].strip('"')
                        elif line.startswith("NAME="):
                            name = line.split("=", 1)[1].strip('"')
                        elif line.startswith("VERSION="):
                            version = line.split("=", 1)[1].strip('"')
                    
                    # Prefer PRETTY_NAME, fallback to NAME + VERSION
                    if pretty_name:
                        return pretty_name
                    elif name and version:
                        return f"{name} {version}"
                    elif name:
                        return name
            
            # Fallback to platform info
            return f"{platform.system()} {platform.release()}"
            
        except Exception as e:
            logger.error(f"Error getting OS info: {e}")
            return "Unknown Linux"
    
    def _get_desktop_environment(self) -> str:
        """Get desktop environment."""
        try:
            # Try XDG_CURRENT_DESKTOP first
            desktop = os.environ.get("XDG_CURRENT_DESKTOP")
            if desktop:
                return desktop
            
            # Fallback to DESKTOP_SESSION
            desktop = os.environ.get("DESKTOP_SESSION")
            if desktop:
                return desktop
            
            # Try detecting common DEs
            if os.environ.get("KDE_FULL_SESSION"):
                return "KDE"
            elif os.environ.get("GNOME_DESKTOP_SESSION_ID"):
                return "GNOME"
            elif os.environ.get("XFCE4_SESSION"):
                return "XFCE"
            
            return "Unknown"
            
        except Exception as e:
            logger.error(f"Error getting desktop environment: {e}")
            return "Unknown"
    
    def _get_display_server(self) -> str:
        """Get display server type (Wayland or X11)."""
        try:
            # Check XDG_SESSION_TYPE first
            session_type = os.environ.get("XDG_SESSION_TYPE")
            if session_type:
                return session_type.capitalize()
            
            # Check for Wayland display
            if os.environ.get("WAYLAND_DISPLAY"):
                return "Wayland"
            
            # Check for X11 display
            if os.environ.get("DISPLAY"):
                return "X11"
            
            return "Unknown"
            
        except Exception as e:
            logger.error(f"Error getting display server: {e}")
            return "Unknown"
    
    def _get_engine_version(self) -> str:
        """Get jackify-engine version."""
        try:
            # Try to execute jackify-engine --version  
            engine_path = Path(__file__).parent.parent.parent.parent / "engine" / "jackify-engine"
            if engine_path.exists():
                result = subprocess.run([str(engine_path), "--version"], 
                                      capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    version = result.stdout.strip()
                    # Extract just the version number (before the +commit hash)
                    if '+' in version:
                        version = version.split('+')[0]
                    return f"v{version}"
            
            return "Unknown"
            
        except Exception as e:
            logger.error(f"Error getting engine version: {e}")
            return "Unknown"
    
    def check_for_updates(self):
        """Check for updates in background."""
        if self.update_check_thread and self.update_check_thread.isRunning():
            return
        
        self.update_button.setEnabled(False)
        self.update_button.setText("Checking...")
        self.update_status_label.setText("Checking for updates...")
        
        self.update_check_thread = UpdateCheckThread(self.update_service)
        self.update_check_thread.update_check_finished.connect(self.update_check_finished)
        self.update_check_thread.start()
    
    def update_check_finished(self, update_info):
        """Handle update check completion."""
        self.update_button.setEnabled(True)
        self.update_button.setText("Check for Updates")
        
        if update_info:
            self.update_status_label.setText(f"Update available: v{update_info.version}")
            self.update_status_label.setStyleSheet("color: #3fd0ea; font-size: 10pt; margin: 5px;")
            
            # Show update dialog
            from .update_dialog import UpdateDialog
            update_dialog = UpdateDialog(update_info, self.update_service, self)
            update_dialog.exec()
        else:
            self.update_status_label.setText("You're running the latest version")
            self.update_status_label.setStyleSheet("color: #666; font-size: 10pt; margin: 5px;")
    
    def copy_system_info(self):
        """Copy system information to clipboard."""
        try:
            info_text = f"""Jackify v{__version__} (Engine {self._get_engine_version()})
OS: {self._get_os_info()} ({platform.release()})
Desktop: {self._get_desktop_environment()} ({self._get_display_server()})
Python: {platform.python_version()}"""
            
            clipboard = QApplication.clipboard()
            clipboard.setText(info_text)
            
            # Briefly update button text
            sender = self.sender()
            original_text = sender.text()
            sender.setText("Copied!")
            
            # Reset button text after delay
            from PySide6.QtCore import QTimer
            QTimer.singleShot(1000, lambda: sender.setText(original_text))
            
        except Exception as e:
            logger.error(f"Error copying system info: {e}")
    
    def open_github(self):
        """Open GitHub repository."""
        try:
            import webbrowser
            webbrowser.open("https://github.com/Omni-guides/Jackify")
        except Exception as e:
            logger.error(f"Error opening GitHub: {e}")
    
    def open_nexus(self):
        """Open Nexus Mods page."""
        try:
            import webbrowser
            webbrowser.open("https://www.nexusmods.com/site/mods/1427")
        except Exception as e:
            logger.error(f"Error opening Nexus: {e}")
    
    def closeEvent(self, event):
        """Handle dialog close event."""
        if self.update_check_thread and self.update_check_thread.isRunning():
            self.update_check_thread.terminate()
            self.update_check_thread.wait()
        
        event.accept()