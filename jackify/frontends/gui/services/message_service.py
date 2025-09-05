"""
Non-Focus-Stealing Message Service for Jackify
Provides message boxes that don't steal focus from the current application
"""

import random
import string
from typing import Optional
from PySide6.QtWidgets import QMessageBox, QWidget, QLineEdit, QLabel, QVBoxLayout, QHBoxLayout, QCheckBox
from PySide6.QtCore import Qt, QTimer


class NonFocusMessageBox(QMessageBox):
    """Custom QMessageBox that prevents focus stealing"""
    
    def __init__(self, parent=None, critical=False, safety_level="low"):
        super().__init__(parent)
        self.safety_level = safety_level
        self._setup_no_focus_attributes(critical, safety_level)
    
    def _setup_no_focus_attributes(self, critical, safety_level):
        """Configure the message box to not steal focus"""
        # Set modality based on criticality and safety level
        if critical or safety_level == "high":
            self.setWindowModality(Qt.ApplicationModal)
        elif safety_level == "medium":
            self.setWindowModality(Qt.NonModal)
        else:
            self.setWindowModality(Qt.NonModal)
        
        # Prevent focus stealing
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setWindowFlags(
            self.windowFlags() | 
            Qt.WindowStaysOnTopHint |
            Qt.WindowDoesNotAcceptFocus
        )
        
        # Set focus policy to prevent taking focus
        self.setFocusPolicy(Qt.NoFocus)
        
        # Make sure child widgets don't steal focus either
        for child in self.findChildren(QWidget):
            child.setFocusPolicy(Qt.NoFocus)
    
    def showEvent(self, event):
        """Override to ensure no focus stealing on show"""
        super().showEvent(event)
        # Ensure we don't steal focus
        self.activateWindow()
        self.raise_()


class SafeMessageBox(NonFocusMessageBox):
    """Enhanced message box with safety features"""
    
    def __init__(self, parent=None, safety_level="low"):
        super().__init__(parent, critical=(safety_level == "high"), safety_level=safety_level)
        self.safety_level = safety_level
        self.countdown_remaining = 0
        self.confirmation_code = None
        self.countdown_timer = None
        self.code_input = None
        self.understanding_checkbox = None
        
    def setup_safety_features(self, title: str, message: str, 
                             danger_action: str = "OK",
                             safe_action: str = "Cancel",
                             is_question: bool = False):
        self.setWindowTitle(title)
        self.setText(message)
        if self.safety_level == "high":
            self.setIcon(QMessageBox.Warning)
            self._setup_high_safety(danger_action, safe_action)
        elif self.safety_level == "medium":
            self.setIcon(QMessageBox.Information)
            self._setup_medium_safety(danger_action, safe_action)
        else:
            self.setIcon(QMessageBox.Information)
            self._setup_low_safety(danger_action, safe_action)
        # --- Fix: For question dialogs, set proceed/cancel button return values, but do NOT call setStandardButtons ---
        if is_question and hasattr(self, 'proceed_btn'):
            self.proceed_btn.setText(danger_action)
            self.proceed_btn.setProperty('role', QMessageBox.YesRole)
            self.proceed_btn.clicked.disconnect()
            self.proceed_btn.clicked.connect(lambda: self.done(QMessageBox.Yes))
            self.cancel_btn.setText(safe_action)
            self.cancel_btn.setProperty('role', QMessageBox.NoRole)
            self.cancel_btn.clicked.disconnect()
            self.cancel_btn.clicked.connect(lambda: self.done(QMessageBox.No))
    
    def _setup_high_safety(self, danger_action: str, safe_action: str):
        """High safety: requires typing confirmation code"""
        # Generate random confirmation code
        self.confirmation_code = ''.join(random.choices(string.ascii_uppercase, k=6))
        
        # Create custom buttons
        self.proceed_btn = self.addButton(danger_action, QMessageBox.AcceptRole)
        self.cancel_btn = self.addButton(safe_action, QMessageBox.RejectRole)
        
        # Make cancel the default (Enter key)
        self.setDefaultButton(self.cancel_btn)
        
        # Initially disable proceed button
        self.proceed_btn.setEnabled(False)
        
        # Add confirmation code input
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        instruction = QLabel(f"Type '{self.confirmation_code}' to confirm:")
        instruction.setStyleSheet("font-weight: bold; color: red;")
        layout.addWidget(instruction)
        
        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText("Enter confirmation code...")
        self.code_input.textChanged.connect(self._check_code_input)
        layout.addWidget(self.code_input)
        
        self.layout().addWidget(widget, 1, 0, 1, self.layout().columnCount())
        
        # Start countdown
        self._start_countdown(3)
    
    def _setup_medium_safety(self, danger_action: str, safe_action: str):
        """Medium safety: requires wait period"""
        # Create custom buttons
        self.proceed_btn = self.addButton(danger_action, QMessageBox.AcceptRole)
        self.cancel_btn = self.addButton(safe_action, QMessageBox.RejectRole)
        
        # Make cancel the default (Enter key)
        self.setDefaultButton(self.cancel_btn)
        
        # Initially disable proceed button
        self.proceed_btn.setEnabled(False)
        
        # Start countdown
        self._start_countdown(3)
    
    def _setup_low_safety(self, danger_action: str, safe_action: str):
        """Low safety: no additional features needed"""
        # Create standard buttons
        self.proceed_btn = self.addButton(danger_action, QMessageBox.AcceptRole)
        self.cancel_btn = self.addButton(safe_action, QMessageBox.RejectRole)
        
        # Make proceed the default for low safety
        self.setDefaultButton(self.proceed_btn)
    
    def _start_countdown(self, seconds: int):
        self.countdown_timer = QTimer()
        self.countdown_timer.timeout.connect(self._update_countdown)
        self.countdown_remaining = seconds
        self._update_countdown()
        self.countdown_timer.start(1000)  # Update every second

    def _update_countdown(self):
        if self.countdown_remaining > 0:
            if hasattr(self, 'proceed_btn'):
                if self.safety_level == "high":
                    self.proceed_btn.setText(f"Please wait {self.countdown_remaining}s...")
                else:
                    self.proceed_btn.setText(f"OK ({self.countdown_remaining}s)")
                self.proceed_btn.setEnabled(False)
            if hasattr(self, 'cancel_btn'):
                self.cancel_btn.setEnabled(False)
            self.countdown_remaining -= 1
        else:
            self.countdown_timer.stop()
            if hasattr(self, 'proceed_btn'):
                if self.safety_level == "high":
                    self.proceed_btn.setText("Proceed")
                else:
                    self.proceed_btn.setText("OK")
                self.proceed_btn.setEnabled(True)
            if hasattr(self, 'cancel_btn'):
                self.cancel_btn.setEnabled(True)
            self._check_all_requirements()
    
    def _check_code_input(self):
        """Check if typed code matches"""
        if self.countdown_remaining <= 0:
            self._check_all_requirements()
    
    def _check_all_requirements(self):
        """Check if all requirements are met"""
        can_proceed = self.countdown_remaining <= 0
        
        if self.safety_level == "high":
            can_proceed = can_proceed and (
                self.code_input.text().upper() == self.confirmation_code
            )
        
        self.proceed_btn.setEnabled(can_proceed)


class MessageService:
    """Service class for creating non-focus-stealing message boxes"""
    
    @staticmethod
    def _create_base_message_box(parent: Optional[QWidget] = None, critical: bool = False, safety_level: str = "low") -> NonFocusMessageBox:
        """Create a base message box with no focus stealing"""
        if safety_level in ["medium", "high"]:
            return SafeMessageBox(parent, safety_level)
        else:
            return NonFocusMessageBox(parent, critical)
    
    @staticmethod
    def information(parent: Optional[QWidget] = None, 
                   title: str = "Information",
                   message: str = "",
                   buttons: QMessageBox.StandardButtons = QMessageBox.Ok,
                   default_button: QMessageBox.StandardButton = QMessageBox.Ok,
                   critical: bool = False,
                   safety_level: str = "low") -> int:
        """Show information message without stealing focus"""
        if safety_level in ["medium", "high"]:
            msg_box = SafeMessageBox(parent, safety_level)
            msg_box.setup_safety_features(title, message, "OK", "Cancel")
        else:
            msg_box = MessageService._create_base_message_box(parent, critical, safety_level)
            msg_box.setIcon(QMessageBox.Information)
            msg_box.setWindowTitle(title)
            msg_box.setText(message)
            msg_box.setStandardButtons(buttons)
            msg_box.setDefaultButton(default_button)
        
        return msg_box.exec()
    
    @staticmethod
    def warning(parent: Optional[QWidget] = None,
                title: str = "Warning",
                message: str = "",
                buttons: QMessageBox.StandardButtons = QMessageBox.Ok,
                default_button: QMessageBox.StandardButton = QMessageBox.Ok,
                critical: bool = False,
                safety_level: str = "low") -> int:
        """Show warning message without stealing focus"""
        if safety_level in ["medium", "high"]:
            msg_box = SafeMessageBox(parent, safety_level)
            msg_box.setup_safety_features(title, message, "OK", "Cancel")
        else:
            msg_box = MessageService._create_base_message_box(parent, critical, safety_level)
            msg_box.setIcon(QMessageBox.Warning)
            msg_box.setWindowTitle(title)
            msg_box.setText(message)
            msg_box.setStandardButtons(buttons)
            msg_box.setDefaultButton(default_button)
        
        return msg_box.exec()
    
    @staticmethod
    def critical(parent: Optional[QWidget] = None,
                 title: str = "Critical Error",
                 message: str = "",
                 buttons: QMessageBox.StandardButtons = QMessageBox.Ok,
                 default_button: QMessageBox.StandardButton = QMessageBox.Ok,
                 safety_level: str = "medium") -> int:
        """Show critical error message (always requires attention)"""
        msg_box = MessageService._create_base_message_box(parent, critical=True, safety_level=safety_level)
        msg_box.setIcon(QMessageBox.Critical)
        msg_box.setWindowTitle(title)
        msg_box.setText(message)
        msg_box.setStandardButtons(buttons)
        msg_box.setDefaultButton(default_button)
        return msg_box.exec()
    
    @staticmethod
    def question(parent: Optional[QWidget] = None,
                 title: str = "Question",
                 message: str = "",
                 buttons: QMessageBox.StandardButtons = QMessageBox.Yes | QMessageBox.No,
                 default_button: QMessageBox.StandardButton = QMessageBox.No,
                 critical: bool = False,
                 safety_level: str = "low") -> int:
        """Show question dialog without stealing focus"""
        if safety_level in ["medium", "high"]:
            msg_box = SafeMessageBox(parent, safety_level)
            msg_box.setup_safety_features(title, message, "Yes", "No", is_question=True)
        else:
            msg_box = MessageService._create_base_message_box(parent, critical, safety_level)
            msg_box.setIcon(QMessageBox.Question)
            msg_box.setWindowTitle(title)
            msg_box.setText(message)
            msg_box.setStandardButtons(buttons)
            msg_box.setDefaultButton(default_button)
        
        return msg_box.exec() 