"""
Migrated Modlist Tasks Screen

This is a migrated version of the original modlist tasks menu that uses backend services
directly instead of subprocess calls to jackify-cli.py.

Key changes:
- Uses backend services directly instead of subprocess.Popen()
- Direct backend service integration
- Maintains same UI and workflow
- Improved error handling and progress reporting
"""

import os
import sys
import logging
from pathlib import Path
from typing import List, Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QGridLayout, QSizePolicy, QApplication, QFrame, QMessageBox
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QFont, QPalette, QColor, QPixmap

# Import our GUI services
from jackify.backend.models.configuration import SystemInfo
from ..shared_theme import JACKIFY_COLOR_BLUE

# Constants
DEBUG_BORDERS = False

logger = logging.getLogger(__name__)


class ModlistTasksScreen(QWidget):
    """
    Migrated Modlist Tasks screen that uses backend services directly.
    
    This replaces the original ModlistTasksMenu's subprocess calls with
    direct navigation to existing automated workflows.
    """
    
    def __init__(self, stacked_widget=None, main_menu_index=0, system_info: Optional[SystemInfo] = None, dev_mode=False):
        super().__init__()
        logger.info("ModlistTasksScreen initializing (migrated version)")
        
        self.stacked_widget = stacked_widget
        self.main_menu_index = main_menu_index
        self.debug = DEBUG_BORDERS
        self.dev_mode = dev_mode
        
        # Initialize backend services
        if system_info is None:
            system_info = SystemInfo(is_steamdeck=self._is_steamdeck())
        self.system_info = system_info
        
        # Setup UI
        self._setup_ui()
        
        logger.info("ModlistTasksScreen initialized (migrated version)")
    
    def _is_steamdeck(self) -> bool:
        """Check if running on Steam Deck"""
        try:
            if os.path.exists("/etc/os-release"):
                with open("/etc/os-release", "r") as f:
                    content = f.read()
                    if "steamdeck" in content:
                        return True
            return False
        except Exception:
            return False
    
    def _setup_ui(self):
        """Set up the user interface"""
        main_layout = QVBoxLayout(self)
        main_layout.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        main_layout.setContentsMargins(50, 50, 50, 50)
        
        if self.debug:
            self.setStyleSheet("border: 2px solid green;")
        
        # Header section
        self._setup_header(main_layout)
        
        # Menu buttons section
        self._setup_menu_buttons(main_layout)
        
        # Bottom navigation
        self._setup_navigation(main_layout)
    
    def _setup_header(self, layout):
        """Set up the header section"""
        header_layout = QVBoxLayout()
        header_layout.setSpacing(2)
        
        # Title
        title = QLabel("<b>Modlist Tasks</b>")
        title.setStyleSheet(f"font-size: 24px; color: {JACKIFY_COLOR_BLUE};")
        title.setAlignment(Qt.AlignHCenter)
        header_layout.addWidget(title)

        # Add a spacer to match main menu vertical spacing
        header_layout.addSpacing(16)
        
        # Description  
        desc = QLabel(
            "Manage your modlists with native Linux tools. Choose "
            "from the options below to install or configure modlists.<br>&nbsp;"
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #ccc;")
        desc.setAlignment(Qt.AlignHCenter)
        header_layout.addWidget(desc)
        
        header_layout.addSpacing(24)
        
        # Separator
        sep = QLabel()
        sep.setFixedHeight(2)
        sep.setStyleSheet("background: #fff;")
        header_layout.addWidget(sep)
        
        header_layout.addSpacing(16)
        layout.addLayout(header_layout)
    
    def _setup_menu_buttons(self, layout):
        """Set up the menu buttons section"""
        # Menu options
        MENU_ITEMS = [
            ("Install a Modlist (Automated)", "install_modlist", "Download and install modlists automatically"),
            ("Configure New Modlist (Post-Download)", "configure_new_modlist", "Configure a newly downloaded modlist"),
            ("Configure Existing Modlist (In Steam)", "configure_existing_modlist", "Reconfigure an existing Steam modlist"),
        ]
        if self.dev_mode:
            MENU_ITEMS.append(("Install Wabbajack Application", "install_wabbajack", "Set up the Wabbajack application"))
        MENU_ITEMS.append(("Return to Main Menu", "return_main_menu", "Go back to the main menu"))
        
        # Create grid layout for buttons
        button_grid = QGridLayout()
        button_grid.setSpacing(16)
        button_grid.setAlignment(Qt.AlignHCenter)
        
        button_width = 400
        button_height = 50
        
        for i, (label, action_id, description) in enumerate(MENU_ITEMS):
            # Create button
            btn = QPushButton(label)
            btn.setFixedSize(button_width, button_height)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: #4a5568;
                    color: white;
                    border: none;
                    border-radius: 8px;
                    font-size: 14px;
                    font-weight: bold;
                    text-align: center;
                }}
                QPushButton:hover {{
                    background-color: #5a6578;
                }}
                QPushButton:pressed {{
                    background-color: {JACKIFY_COLOR_BLUE};
                }}
            """)
            btn.clicked.connect(lambda checked, a=action_id: self.menu_action(a))
            
            # Create description label
            desc_label = QLabel(description)
            desc_label.setAlignment(Qt.AlignHCenter)
            desc_label.setStyleSheet("color: #999; font-size: 12px;")
            desc_label.setWordWrap(True)
            desc_label.setFixedWidth(button_width)
            
            # Add to grid
            button_grid.addWidget(btn, i * 2, 0, Qt.AlignHCenter)
            button_grid.addWidget(desc_label, i * 2 + 1, 0, Qt.AlignHCenter)
        
        layout.addLayout(button_grid)
    
    def _setup_navigation(self, layout):
        """Set up the navigation section"""
        # Remove the bottom navigation bar entirely (no gray Back to Main Menu button)
        pass
    
    def menu_action(self, action_id):
        """Handle menu button clicks"""
        logger.info(f"Modlist tasks menu action: {action_id}")
        
        if not self.stacked_widget:
            return
        
        # Navigate to different screens based on action
        if action_id == "return_main_menu":
            self.stacked_widget.setCurrentIndex(0)
        elif action_id == "install_modlist":
            self.stacked_widget.setCurrentIndex(4)
        elif action_id == "configure_new_modlist":
            self.stacked_widget.setCurrentIndex(5)
        elif action_id == "configure_existing_modlist":
            self.stacked_widget.setCurrentIndex(6)
    
    def go_back(self):
        """Return to main menu"""
        if self.stacked_widget:
            self.stacked_widget.setCurrentIndex(self.main_menu_index)
    
    def cleanup(self):
        """Clean up resources when the screen is closed"""
        pass 