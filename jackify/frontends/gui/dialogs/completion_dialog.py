"""
Completion Dialog

Custom completion dialog that shows the same detailed completion message
as the CLI frontend, formatted for GUI display.
"""

import logging
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit,
    QWidget, QSpacerItem, QSizePolicy
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QIcon

logger = logging.getLogger(__name__)


class NextStepsDialog(QDialog):
    """
    Custom completion dialog showing detailed next steps after modlist configuration.
    
    Displays the same information as the CLI completion message but in a proper GUI format.
    """
    
    def __init__(self, modlist_name: str, parent=None):
        """
        Initialize the Next Steps dialog.
        
        Args:
            modlist_name: Name of the configured modlist
            parent: Parent widget
        """
        super().__init__(parent)
        self.modlist_name = modlist_name
        self.setWindowTitle("Next Steps")
        self.setModal(True)
        self.setFixedSize(600, 400)
        
        # Set the Wabbajack icon if available
        self._set_dialog_icon()
        
        self._setup_ui()
        
        logger.info(f"NextStepsDialog created for modlist: {modlist_name}")
    
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
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Header with icon and title
        self._setup_header(layout)
        
        # Main content area
        self._setup_content(layout)
        
        # Action buttons
        self._setup_buttons(layout)
    
    def _setup_header(self, layout):
        """Set up the dialog header with title"""
        header_layout = QHBoxLayout()
        
        # Title
        title_label = QLabel("Next Steps:")
        title_label.setStyleSheet(
            "QLabel { "
            "  font-size: 18px; "
            "  font-weight: bold; "
            "  color: #2c3e50; "
            "  margin-bottom: 10px; "
            "}"
        )
        header_layout.addWidget(title_label)
        
        # Add some space
        header_layout.addStretch()
        
        layout.addLayout(header_layout)
    
    def _setup_content(self, layout):
        """Set up the main content area with next steps"""
        # Create content area
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setSpacing(12)
        
        # Add the detailed next steps text (matching CLI completion message)
        steps_text = self._build_completion_text()
        
        content_text = QTextEdit()
        content_text.setPlainText(steps_text)
        content_text.setReadOnly(True)
        content_text.setStyleSheet(
            "QTextEdit { "
            "  background-color: #f8f9fa; "
            "  border: 1px solid #dee2e6; "
            "  border-radius: 6px; "
            "  padding: 12px; "
            "  font-family: 'Segoe UI', Arial, sans-serif; "
            "  font-size: 12px; "
            "  line-height: 1.5; "
            "}"
        )
        content_layout.addWidget(content_text)
        
        layout.addWidget(content_widget)
    
    def _setup_buttons(self, layout):
        """Set up the action buttons"""
        button_layout = QHBoxLayout()
        button_layout.setSpacing(12)
        
        # Add stretch to center buttons
        button_layout.addStretch()
        
        # Return button (goes back to menu)
        return_btn = QPushButton("Return")
        return_btn.setFixedSize(100, 35)
        return_btn.clicked.connect(self.accept)  # This will close dialog and return to menu
        return_btn.setStyleSheet(
            "QPushButton { "
            "  background-color: #3498db; "
            "  color: white; "
            "  border: none; "
            "  border-radius: 4px; "
            "  font-weight: bold; "
            "  padding: 8px 16px; "
            "} "
            "QPushButton:hover { "
            "  background-color: #2980b9; "
            "} "
            "QPushButton:pressed { "
            "  background-color: #21618c; "
            "}"
        )
        button_layout.addWidget(return_btn)
        
        button_layout.addSpacing(10)
        
        # Exit button (closes the application)
        exit_btn = QPushButton("Exit")
        exit_btn.setFixedSize(100, 35)
        exit_btn.clicked.connect(self.reject)  # This will close dialog and potentially exit app
        exit_btn.setStyleSheet(
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
        button_layout.addWidget(exit_btn)
        
        button_layout.addStretch()
        
        layout.addLayout(button_layout)
    
    def _build_completion_text(self) -> str:
        """
        Build the completion text matching the CLI version from menu_handler.py.
        
        Returns:
            Formatted completion text string
        """
        # Match the CLI completion text from menu_handler.py lines 627-631
        completion_text = f"""✓ Configuration completed successfully!

Modlist Install and Configuration complete!:

  • You should now be able to Launch '{self.modlist_name}' through Steam.
  • Congratulations and enjoy the game!

Detailed log available at: ~/Jackify/logs/Configure_New_Modlist_workflow.log"""
        
        return completion_text 