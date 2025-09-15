"""
Update notification and download dialog for Jackify.

This dialog handles notifying users about available updates and
managing the download/installation process.
"""

import logging
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QTextEdit, QProgressBar, QGroupBox, QCheckBox
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QPixmap, QFont

from ....backend.services.update_service import UpdateService, UpdateInfo


logger = logging.getLogger(__name__)


class UpdateDownloadThread(QThread):
    """Background thread for downloading updates."""
    
    progress_updated = Signal(int, int)  # downloaded, total
    download_finished = Signal(object)   # Path or None
    
    def __init__(self, update_service: UpdateService, update_info: UpdateInfo):
        super().__init__()
        self.update_service = update_service
        self.update_info = update_info
        self.downloaded_path = None
    
    def run(self):
        """Download the update in background."""
        try:
            def progress_callback(downloaded: int, total: int):
                self.progress_updated.emit(downloaded, total)
            
            self.downloaded_path = self.update_service.download_update(
                self.update_info, progress_callback
            )
            
            self.download_finished.emit(self.downloaded_path)
            
        except Exception as e:
            logger.error(f"Error in download thread: {e}")
            self.download_finished.emit(None)


class UpdateDialog(QDialog):
    """Dialog for notifying users about updates and handling downloads."""
    
    def __init__(self, update_info: UpdateInfo, update_service: UpdateService, parent=None):
        super().__init__(parent)
        self.update_info = update_info
        self.update_service = update_service
        self.downloaded_path = None
        self.download_thread = None
        
        self.setup_ui()
        self.setup_connections()
        
    def setup_ui(self):
        """Set up the dialog UI."""
        self.setWindowTitle("Jackify Update Available")
        self.setModal(True)
        self.setMinimumSize(500, 400)
        self.setMaximumSize(600, 600)
        
        layout = QVBoxLayout(self)
        
        # Header
        header_layout = QHBoxLayout()
        
        # Update icon (if available)
        icon_label = QLabel()
        icon_label.setText("^")  # Update arrow symbol
        icon_label.setStyleSheet("font-size: 24px; color: #3fd0ea; font-weight: bold;")
        header_layout.addWidget(icon_label)
        
        # Update title
        title_layout = QVBoxLayout()
        title_label = QLabel(f"Update Available: v{self.update_info.version}")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setStyleSheet("color: #3fd0ea;")
        title_layout.addWidget(title_label)
        
        subtitle_label = QLabel(f"Current version: v{self.update_service.current_version}")
        subtitle_label.setStyleSheet("color: #666;")
        title_layout.addWidget(subtitle_label)
        
        header_layout.addLayout(title_layout)
        header_layout.addStretch()
        
        layout.addLayout(header_layout)
        
        # File size info
        if self.update_info.file_size:
            size_mb = self.update_info.file_size / (1024 * 1024)
            update_type = "Delta update" if self.update_info.is_delta_update else "Full update"
            size_label = QLabel(f"{update_type} - Download size: {size_mb:.1f} MB")
            size_label.setStyleSheet("color: #666; margin-bottom: 10px;")
            layout.addWidget(size_label)
        
        # Changelog group
        changelog_group = QGroupBox("What's New")
        changelog_layout = QVBoxLayout(changelog_group)
        
        self.changelog_text = QTextEdit()
        self.changelog_text.setPlainText(self.update_info.changelog or "No changelog available.")
        self.changelog_text.setMaximumHeight(150)
        self.changelog_text.setReadOnly(True)
        changelog_layout.addWidget(self.changelog_text)
        
        layout.addWidget(changelog_group)
        
        # Progress section (initially hidden)
        self.progress_group = QGroupBox("Download Progress")
        progress_layout = QVBoxLayout(self.progress_group)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        progress_layout.addWidget(self.progress_bar)
        
        self.progress_label = QLabel("Preparing download...")
        self.progress_label.setVisible(False)
        progress_layout.addWidget(self.progress_label)
        
        layout.addWidget(self.progress_group)
        self.progress_group.setVisible(False)
        
        # Options
        options_group = QGroupBox("Update Options")
        options_layout = QVBoxLayout(options_group)
        
        self.auto_restart_checkbox = QCheckBox("Automatically restart Jackify after update")
        self.auto_restart_checkbox.setChecked(True)
        options_layout.addWidget(self.auto_restart_checkbox)
        
        layout.addWidget(options_group)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.later_button = QPushButton("Remind Me Later")
        self.later_button.clicked.connect(self.remind_later)
        button_layout.addWidget(self.later_button)
        
        self.skip_button = QPushButton("Skip This Version")
        self.skip_button.clicked.connect(self.skip_version)
        button_layout.addWidget(self.skip_button)
        
        button_layout.addStretch()
        
        self.download_button = QPushButton("Download && Install Update")
        self.download_button.setDefault(True)
        self.download_button.clicked.connect(self.start_download)
        button_layout.addWidget(self.download_button)
        
        self.install_button = QPushButton("Install && Restart")
        self.install_button.setVisible(False)
        self.install_button.clicked.connect(self.install_update)
        self.install_button.setStyleSheet("""
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
        """)
        button_layout.addWidget(self.install_button)
        
        layout.addLayout(button_layout)
        
        # Style the download button to match Jackify theme (dark with blue text)
        self.download_button.setStyleSheet("""
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
        """)
    
    def setup_connections(self):
        """Set up signal connections."""
        pass
    
    def start_download(self):
        """Start downloading the update."""
        if not self.update_service.can_update():
            self.show_error("Update not possible", 
                          "Cannot update: not running as AppImage or insufficient permissions.")
            return
        
        # Show progress UI
        self.progress_group.setVisible(True)
        self.progress_bar.setVisible(True)
        self.progress_label.setVisible(True)
        self.progress_label.setText("Starting download...")
        
        # Disable buttons during download
        self.download_button.setEnabled(False)
        self.later_button.setEnabled(False)
        self.skip_button.setEnabled(False)
        
        # Start download thread
        self.download_thread = UpdateDownloadThread(self.update_service, self.update_info)
        self.download_thread.progress_updated.connect(self.update_progress)
        self.download_thread.download_finished.connect(self.download_completed)
        self.download_thread.start()
    
    def update_progress(self, downloaded: int, total: int):
        """Update download progress."""
        if total > 0:
            percentage = int((downloaded / total) * 100)
            self.progress_bar.setValue(percentage)
            
            downloaded_mb = downloaded / (1024 * 1024)
            total_mb = total / (1024 * 1024)
            
            self.progress_label.setText(f"Downloaded {downloaded_mb:.1f} MB of {total_mb:.1f} MB ({percentage}%)")
        else:
            self.progress_label.setText(f"Downloaded {downloaded / (1024 * 1024):.1f} MB...")
    
    def download_completed(self, downloaded_path: Optional[Path]):
        """Handle download completion."""
        if downloaded_path:
            self.downloaded_path = downloaded_path
            self.progress_label.setText("Download completed successfully!")
            self.progress_bar.setValue(100)
            
            # Show install button
            self.download_button.setVisible(False)
            self.install_button.setVisible(True)
            
            # Re-enable other buttons
            self.later_button.setEnabled(True)
            self.skip_button.setEnabled(True)
            
        else:
            self.show_error("Download Failed", "Failed to download the update. Please try again later.")
            
            # Reset UI
            self.progress_group.setVisible(False)
            self.download_button.setEnabled(True)
            self.later_button.setEnabled(True)
            self.skip_button.setEnabled(True)
    
    def install_update(self):
        """Install the downloaded update."""
        if not self.downloaded_path:
            self.show_error("No Download", "No update has been downloaded.")
            return
        
        self.progress_label.setText("Installing update...")
        
        if self.update_service.apply_update(self.downloaded_path):
            self.progress_label.setText("Update applied successfully! Jackify will restart...")
            
            # Close dialog and exit application (update helper will restart)
            self.accept()
            
            # The update helper script will handle the restart
            import sys
            sys.exit(0)
            
        else:
            self.show_error("Installation Failed", "Failed to apply the update. Please try again.")
    
    def remind_later(self):
        """Close dialog and remind later."""
        self.reject()
    
    def skip_version(self):
        """Skip this version and save preference."""
        try:
            # Save the skipped version to config
            from jackify.backend.handlers.config_handler import ConfigHandler
            config_handler = ConfigHandler()
            
            # Get current skipped versions
            skipped_versions = config_handler.get('skipped_versions', [])
            
            # Add this version to skipped list
            if self.update_info.version not in skipped_versions:
                skipped_versions.append(self.update_info.version)
                config_handler.set('skipped_versions', skipped_versions)
                config_handler.save()
                
            logger.info(f"Skipped version {self.update_info.version}")
            
        except Exception as e:
            logger.error(f"Error saving skip preference: {e}")
        
        self.reject()
    
    def show_error(self, title: str, message: str):
        """Show error message to user."""
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.warning(self, title, message)
    
    def closeEvent(self, event):
        """Handle dialog close event."""
        if self.download_thread and self.download_thread.isRunning():
            # Cancel download if in progress
            self.download_thread.terminate()
            self.download_thread.wait()
        
        event.accept()