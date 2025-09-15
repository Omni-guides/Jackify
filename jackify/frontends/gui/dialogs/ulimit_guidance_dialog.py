#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ulimit Guidance Dialog

Provides guidance for manually increasing file descriptor limits when automatic
increase fails. Offers distribution-specific instructions and commands.
"""

import logging
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QTextEdit, QGroupBox, QTabWidget, QWidget, QScrollArea,
    QFrame, QSizePolicy
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QIcon

logger = logging.getLogger(__name__)


class UlimitGuidanceDialog(QDialog):
    """Dialog to provide manual ulimit increase guidance when automatic methods fail"""
    
    def __init__(self, resource_manager=None, parent=None):
        super().__init__(parent)
        self.resource_manager = resource_manager
        self.setWindowTitle("File Descriptor Limit Guidance")
        self.setModal(True)
        self.setMinimumSize(800, 600)
        self.resize(900, 700)
        
        # Get current status and instructions
        if self.resource_manager:
            self.status = self.resource_manager.get_limit_status()
            self.instructions = self.resource_manager.get_manual_increase_instructions()
        else:
            # Fallback if no resource manager provided
            from jackify.backend.services.resource_manager import ResourceManager
            temp_manager = ResourceManager()
            self.status = temp_manager.get_limit_status()
            self.instructions = temp_manager.get_manual_increase_instructions()
        
        self._setup_ui()
        
        # Auto-refresh status every few seconds
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self._refresh_status)
        self.refresh_timer.start(3000)  # Refresh every 3 seconds
    
    def _setup_ui(self):
        """Set up the user interface"""
        layout = QVBoxLayout()
        self.setLayout(layout)
        
        # Title and current status
        self._create_header(layout)
        
        # Main content with tabs
        self._create_content_tabs(layout)
        
        # Action buttons
        self._create_action_buttons(layout)
        
        # Apply styling
        self._apply_styling()
    
    def _create_header(self, layout):
        """Create header with current status"""
        header_frame = QFrame()
        header_frame.setFrameStyle(QFrame.StyledPanel)
        header_layout = QVBoxLayout()
        header_frame.setLayout(header_layout)
        
        # Title
        title_label = QLabel("File Descriptor Limit Configuration")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignCenter)
        header_layout.addWidget(title_label)
        
        # Status information
        self._create_status_section(header_layout)
        
        layout.addWidget(header_frame)
    
    def _create_status_section(self, layout):
        """Create current status display"""
        status_layout = QHBoxLayout()
        
        # Current limits
        current_label = QLabel(f"Current Limit: {self.status['current_soft']}")
        target_label = QLabel(f"Target Limit: {self.status['target_limit']}")
        max_label = QLabel(f"Maximum Possible: {self.status['max_possible']}")
        
        # Status indicator
        if self.status['target_achieved']:
            status_text = "✓ Optimal"
            status_color = "#4caf50"  # Green
        elif self.status['can_increase']:
            status_text = "Can Improve"
            status_color = "#ff9800"  # Orange
        else:
            status_text = "✗ Needs Manual Fix"
            status_color = "#f44336"  # Red
        
        self.status_label = QLabel(f"Status: {status_text}")
        self.status_label.setStyleSheet(f"color: {status_color}; font-weight: bold;")
        
        status_layout.addWidget(current_label)
        status_layout.addWidget(target_label)
        status_layout.addWidget(max_label)
        status_layout.addStretch()
        status_layout.addWidget(self.status_label)
        
        layout.addLayout(status_layout)
    
    def _create_content_tabs(self, layout):
        """Create tabbed content with different guidance types"""
        self.tab_widget = QTabWidget()
        
        # Quick Fix tab
        self._create_quick_fix_tab()
        
        # Permanent Fix tab
        self._create_permanent_fix_tab()
        
        # Troubleshooting tab
        self._create_troubleshooting_tab()
        
        layout.addWidget(self.tab_widget)
    
    def _create_quick_fix_tab(self):
        """Create quick/temporary fix tab"""
        widget = QWidget()
        layout = QVBoxLayout()
        widget.setLayout(layout)
        
        # Explanation
        explanation = QLabel(
            "Quick fixes apply only to the current terminal session. "
            "You'll need to run these commands each time you start Jackify from a new terminal."
        )
        explanation.setWordWrap(True)
        explanation.setStyleSheet("color: #666; font-style: italic; margin-bottom: 10px;")
        layout.addWidget(explanation)
        
        # Commands group
        commands_group = QGroupBox("Commands to Run")
        commands_layout = QVBoxLayout()
        commands_group.setLayout(commands_layout)
        
        # Command text
        if 'temporary' in self.instructions['methods']:
            temp_method = self.instructions['methods']['temporary']
            
            commands_text = QTextEdit()
            commands_text.setPlainText('\n'.join(temp_method['commands']))
            commands_text.setMaximumHeight(120)
            commands_text.setFont(QFont("monospace"))
            commands_layout.addWidget(commands_text)
            
            # Note
            if 'note' in temp_method:
                note_label = QLabel(f"Note: {temp_method['note']}")
                note_label.setWordWrap(True)
                note_label.setStyleSheet("color: #666; font-style: italic;")
                commands_layout.addWidget(note_label)
        
        layout.addWidget(commands_group)
        
        # Current session test
        test_group = QGroupBox("Test Current Session")
        test_layout = QVBoxLayout()
        test_group.setLayout(test_layout)
        
        test_label = QLabel("You can test if the commands worked by running:")
        test_layout.addWidget(test_label)
        
        test_command = QTextEdit()
        test_command.setPlainText("ulimit -n")
        test_command.setMaximumHeight(40)
        test_command.setFont(QFont("monospace"))
        test_layout.addWidget(test_command)
        
        expected_label = QLabel(f"Expected result: {self.instructions['target_limit']} or higher")
        expected_label.setStyleSheet("color: #666;")
        test_layout.addWidget(expected_label)
        
        layout.addWidget(test_group)
        
        layout.addStretch()
        
        self.tab_widget.addTab(widget, "Quick Fix")
    
    def _create_permanent_fix_tab(self):
        """Create permanent fix tab"""
        widget = QWidget()
        layout = QVBoxLayout()
        widget.setLayout(layout)
        
        # Explanation
        explanation = QLabel(
            "Permanent fixes modify system configuration files and require administrator privileges. "
            "Changes take effect after logout/login or system reboot."
        )
        explanation.setWordWrap(True)
        explanation.setStyleSheet("color: #666; font-style: italic; margin-bottom: 10px;")
        layout.addWidget(explanation)
        
        # Distribution detection
        distro_label = QLabel(f"Detected Distribution: {self.instructions['distribution'].title()}")
        distro_label.setStyleSheet("font-weight: bold; color: #333;")
        layout.addWidget(distro_label)
        
        # Commands group
        commands_group = QGroupBox("System Configuration Commands")
        commands_layout = QVBoxLayout()
        commands_group.setLayout(commands_layout)
        
        # Warning
        warning_label = QLabel(
            "WARNING: These commands require root/sudo privileges and modify system files. "
            "Make sure you understand what each command does before running it."
        )
        warning_label.setWordWrap(True)
        warning_label.setStyleSheet("background-color: #fff3cd; border: 1px solid #ffeaa7; padding: 8px; border-radius: 4px; color: #856404;")
        commands_layout.addWidget(warning_label)
        
        # Command text
        if 'permanent' in self.instructions['methods']:
            perm_method = self.instructions['methods']['permanent']
            
            commands_text = QTextEdit()
            commands_text.setPlainText('\n'.join(perm_method['commands']))
            commands_text.setMinimumHeight(200)
            commands_text.setFont(QFont("monospace"))
            commands_layout.addWidget(commands_text)
            
            # Note
            if 'note' in perm_method:
                note_label = QLabel(f"Note: {perm_method['note']}")
                note_label.setWordWrap(True)
                note_label.setStyleSheet("color: #666; font-style: italic;")
                commands_layout.addWidget(note_label)
        
        layout.addWidget(commands_group)
        
        # Verification group
        verify_group = QGroupBox("Verification After Reboot/Re-login")
        verify_layout = QVBoxLayout()
        verify_group.setLayout(verify_layout)
        
        verify_label = QLabel("After rebooting or logging out and back in, verify the change:")
        verify_layout.addWidget(verify_label)
        
        verify_command = QTextEdit()
        verify_command.setPlainText("ulimit -n")
        verify_command.setMaximumHeight(40)
        verify_command.setFont(QFont("monospace"))
        verify_layout.addWidget(verify_command)
        
        expected_label = QLabel(f"Expected result: {self.instructions['target_limit']} or higher")
        expected_label.setStyleSheet("color: #666;")
        verify_layout.addWidget(expected_label)
        
        layout.addWidget(verify_group)
        
        layout.addStretch()
        
        self.tab_widget.addTab(widget, "Permanent Fix")
    
    def _create_troubleshooting_tab(self):
        """Create troubleshooting tab"""
        widget = QWidget()
        layout = QVBoxLayout()
        widget.setLayout(layout)
        
        # Create scrollable area for troubleshooting content
        scroll = QScrollArea()
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout()
        scroll_widget.setLayout(scroll_layout)
        
        # Common issues
        issues_group = QGroupBox("Common Issues and Solutions")
        issues_layout = QVBoxLayout()
        issues_group.setLayout(issues_layout)
        
        issues_text = """
<b>Issue:</b> "Operation not permitted" when trying to increase limits<br>
<b>Solution:</b> You may need root privileges or the hard limit may be too low. Try the permanent fix method.

<b>Issue:</b> Changes don't persist after closing terminal<br>
<b>Solution:</b> Use the permanent fix method to modify system configuration files.

<b>Issue:</b> Still getting "too many open files" errors after increasing limits<br>
<b>Solution:</b> Some applications may need to be restarted to pick up the new limits. Try restarting Jackify.

<b>Issue:</b> Can't increase above a certain number<br>
<b>Solution:</b> The hard limit may be set by system administrator or systemd. Check systemd service limits if applicable.
        """
        
        issues_label = QLabel(issues_text)
        issues_label.setWordWrap(True)
        issues_label.setTextFormat(Qt.RichText)
        issues_layout.addWidget(issues_label)
        
        scroll_layout.addWidget(issues_group)
        
        # System information
        sysinfo_group = QGroupBox("System Information")
        sysinfo_layout = QVBoxLayout()
        sysinfo_group.setLayout(sysinfo_layout)
        
        sysinfo_text = f"""
<b>Current Soft Limit:</b> {self.status['current_soft']}<br>
<b>Current Hard Limit:</b> {self.status['current_hard']}<br>
<b>Target Limit:</b> {self.status['target_limit']}<br>
<b>Detected Distribution:</b> {self.instructions['distribution']}<br>
<b>Can Increase Automatically:</b> {"Yes" if self.status['can_increase'] else "No"}<br>
<b>Target Achieved:</b> {"Yes" if self.status['target_achieved'] else "No"}
        """
        
        sysinfo_label = QLabel(sysinfo_text)
        sysinfo_label.setWordWrap(True)
        sysinfo_label.setTextFormat(Qt.RichText)
        sysinfo_label.setFont(QFont("monospace", 9))
        sysinfo_layout.addWidget(sysinfo_label)
        
        scroll_layout.addWidget(sysinfo_group)
        
        # Additional resources
        resources_group = QGroupBox("Additional Resources")
        resources_layout = QVBoxLayout()
        resources_group.setLayout(resources_layout)
        
        resources_text = """
<b>For more help:</b><br>
• Check your distribution's documentation for ulimit configuration<br>
• Search for "increase file descriptor limit [your_distribution]"<br>
• Consider asking on your distribution's support forums<br>
• Jackify documentation and issue tracker on GitHub
        """
        
        resources_label = QLabel(resources_text)
        resources_label.setWordWrap(True)
        resources_label.setTextFormat(Qt.RichText)
        resources_layout.addWidget(resources_label)
        
        scroll_layout.addWidget(resources_group)
        
        scroll_layout.addStretch()
        
        scroll.setWidget(scroll_widget)
        scroll.setWidgetResizable(True)
        layout.addWidget(scroll)
        
        self.tab_widget.addTab(widget, "Troubleshooting")
    
    def _create_action_buttons(self, layout):
        """Create action buttons"""
        button_layout = QHBoxLayout()
        
        # Try Again button
        self.try_again_btn = QPushButton("Try Automatic Fix Again")
        self.try_again_btn.clicked.connect(self._try_automatic_fix)
        self.try_again_btn.setEnabled(self.status['can_increase'] and not self.status['target_achieved'])
        
        # Refresh Status button
        refresh_btn = QPushButton("Refresh Status")
        refresh_btn.clicked.connect(self._refresh_status)
        
        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        close_btn.setDefault(True)
        
        button_layout.addWidget(self.try_again_btn)
        button_layout.addWidget(refresh_btn)
        button_layout.addStretch()
        button_layout.addWidget(close_btn)
        
        layout.addLayout(button_layout)
    
    def _apply_styling(self):
        """Apply dialog styling"""
        self.setStyleSheet("""
            QDialog {
                background-color: #f5f5f5;
            }
            QGroupBox {
                font-weight: bold;
                border: 2px solid #cccccc;
                border-radius: 5px;
                margin-top: 1ex;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
            QTextEdit {
                background-color: #ffffff;
                border: 1px solid #cccccc;
                border-radius: 3px;
                padding: 5px;
            }
            QPushButton {
                background-color: #007acc;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #005a9e;
            }
            QPushButton:pressed {
                background-color: #004175;
            }
            QPushButton:disabled {
                background-color: #cccccc;
                color: #666666;
            }
        """)
    
    def _try_automatic_fix(self):
        """Try automatic fix again"""
        if self.resource_manager:
            success = self.resource_manager.apply_recommended_limits()
            if success:
                self._refresh_status()
                from jackify.frontends.gui.services.message_service import MessageService
                MessageService.information(
                    self, 
                    "Success", 
                    "File descriptor limits have been increased successfully!",
                    safety_level="low"
                )
            else:
                from jackify.frontends.gui.services.message_service import MessageService
                MessageService.warning(
                    self,
                    "Fix Failed",
                    "Automatic fix failed. Please try the manual methods shown in the tabs above.",
                    safety_level="medium"
                )
    
    def _refresh_status(self):
        """Refresh current status display"""
        try:
            if self.resource_manager:
                self.status = self.resource_manager.get_limit_status()
            else:
                from jackify.backend.services.resource_manager import ResourceManager
                temp_manager = ResourceManager()
                self.status = temp_manager.get_limit_status()
            
            # Update status display in header
            header_frame = self.layout().itemAt(0).widget()
            if header_frame:
                # Find and update status section
                header_layout = header_frame.layout()
                status_layout = header_layout.itemAt(1).layout()
                
                # Update individual labels
                status_layout.itemAt(0).widget().setText(f"Current Limit: {self.status['current_soft']}")
                status_layout.itemAt(1).widget().setText(f"Target Limit: {self.status['target_limit']}")
                status_layout.itemAt(2).widget().setText(f"Maximum Possible: {self.status['max_possible']}")
                
                # Update status indicator
                if self.status['target_achieved']:
                    status_text = "✓ Optimal"
                    status_color = "#4caf50"  # Green
                elif self.status['can_increase']:
                    status_text = "Can Improve"
                    status_color = "#ff9800"  # Orange
                else:
                    status_text = "✗ Needs Manual Fix"
                    status_color = "#f44336"  # Red
                
                self.status_label.setText(f"Status: {status_text}")
                self.status_label.setStyleSheet(f"color: {status_color}; font-weight: bold;")
            
            # Update try again button
            self.try_again_btn.setEnabled(self.status['can_increase'] and not self.status['target_achieved'])
            
        except Exception as e:
            logger.warning(f"Error refreshing status: {e}")
    
    def closeEvent(self, event):
        """Handle dialog close event"""
        if hasattr(self, 'refresh_timer'):
            self.refresh_timer.stop()
        event.accept()


# Convenience function for easy use
def show_ulimit_guidance(parent=None, resource_manager=None):
    """
    Show the ulimit guidance dialog
    
    Args:
        parent: Parent widget for the dialog
        resource_manager: Optional ResourceManager instance
        
    Returns:
        Dialog result (QDialog.Accepted or QDialog.Rejected)
    """
    dialog = UlimitGuidanceDialog(resource_manager, parent)
    return dialog.exec()


if __name__ == "__main__":
    # Test the dialog
    import sys
    from PySide6.QtWidgets import QApplication
    
    app = QApplication(sys.argv)
    
    # Create and show dialog
    result = show_ulimit_guidance()
    
    sys.exit(result)