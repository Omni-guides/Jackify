"""
Non-Focus-Stealing Message Service for Jackify
Provides message boxes that don't steal focus from the current application
"""

import logging
import os
import random
import string
import subprocess
import warnings
from typing import Optional

logger = logging.getLogger(__name__)


def open_url(url: str) -> None:
    """Open a URL in the system browser, safe to call from within an AppImage."""
    env = os.environ.copy()
    if "APPIMAGE" in env or "APPDIR" in env:
        for var in ("LD_LIBRARY_PATH", "PYTHONPATH", "PYTHONHOME", "QT_PLUGIN_PATH", "QML2_IMPORT_PATH"):
            env.pop(var, None)
    try:
        subprocess.Popen(
            ["xdg-open", url], env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as e:
        logger.warning("Failed to open URL %s: %s", url, e)
from PySide6.QtWidgets import (
    QMessageBox, QWidget, QLineEdit, QLabel, QVBoxLayout, QHBoxLayout,
    QCheckBox, QTextEdit, QPushButton, QDialog, QDialogButtonBox, QSizePolicy,
    QStyle,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont


class NonFocusMessageBox(QMessageBox):
    """Custom QMessageBox that prevents focus stealing"""
    
    def __init__(self, parent=None, critical=False, safety_level="low"):
        super().__init__(parent)
        self.safety_level = safety_level
        self._setup_no_focus_attributes(critical, safety_level)
    
    def _setup_no_focus_attributes(self, critical, safety_level):
        if critical or safety_level == "high":
            self.setWindowModality(Qt.ApplicationModal)
        else:
            self.setWindowModality(Qt.NonModal)

        self.setAttribute(Qt.WA_ShowWithoutActivating, True)


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
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
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

        self.proceed_btn = self.addButton(danger_action, QMessageBox.ActionRole)
        self.cancel_btn = self.addButton(safe_action, QMessageBox.ActionRole)
        self.setDefaultButton(self.cancel_btn)
        self.proceed_btn.setEnabled(False)

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
        self._danger_action_text = danger_action
        self.proceed_btn = self.addButton(danger_action, QMessageBox.ActionRole)
        self.cancel_btn = self.addButton(safe_action, QMessageBox.ActionRole)
        self.setDefaultButton(self.cancel_btn)
        self.proceed_btn.setEnabled(False)
        self._start_countdown(3)
    
    def _setup_low_safety(self, danger_action: str, safe_action: str):
        """Low safety: no additional features needed"""
        self.proceed_btn = self.addButton(danger_action, QMessageBox.ActionRole)
        self.cancel_btn = self.addButton(safe_action, QMessageBox.ActionRole)
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
                    action_label = getattr(self, "_danger_action_text", "OK")
                    self.proceed_btn.setText(f"{action_label} ({self.countdown_remaining}s)")
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
                    self.proceed_btn.setText(getattr(self, "_danger_action_text", "OK"))
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
            msg_box.setTextFormat(Qt.RichText)
            msg_box.setTextInteractionFlags(Qt.TextBrowserInteraction)
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
        """Show question dialog without stealing focus. Uses explicit button order for consistency."""
        if safety_level in ["medium", "high"]:
            msg_box = SafeMessageBox(parent, safety_level)
            msg_box.setup_safety_features(title, message, "Yes", "No", is_question=True)
        else:
            msg_box = MessageService._create_base_message_box(parent, critical, safety_level)
            msg_box.setIcon(QMessageBox.Question)
            msg_box.setWindowTitle(title)
            msg_box.setText(message)
            yes_btn = msg_box.addButton("Yes", QMessageBox.ActionRole)
            no_btn = msg_box.addButton("No", QMessageBox.ActionRole)
            if default_button == QMessageBox.No:
                msg_box.setDefaultButton(no_btn)
            else:
                msg_box.setDefaultButton(yes_btn)

        result = msg_box.exec()

        # For SafeMessageBox with is_question=True, return value is already set by done()
        if safety_level in ["medium", "high"]:
            return result

        # For non-SafeMessageBox, map clicked button to QMessageBox.Yes/No for compatibility
        clicked = msg_box.clickedButton()
        if clicked and clicked.text() == "Yes":
            return QMessageBox.Yes
        return QMessageBox.No

    @staticmethod
    def show_error(parent: Optional[QWidget], error) -> None:
        """Show a structured error dialog for a JackifyError.

        Displays title, plain-English message, optional "what to do" suggestion,
        and an optional collapsible technical detail pane.

        Args:
            parent: Parent widget (may be None).
            error:  A JackifyError instance (imported inside to preserve
                    backend/frontend separation).
        """
        from jackify.shared.errors import JackifyError

        if not isinstance(error, JackifyError):
            # Fallback for plain exceptions
            dialog = _ErrorDialog(parent, str(error), str(error), None, [], None)
            dialog.exec()
            return

        dialog = _ErrorDialog(
            parent,
            error.title,
            error.message,
            error.suggestion,
            getattr(error, 'solutions', []),
            error.technical,
        )
        dialog.exec()


class _ErrorDialog(QDialog):
    """Internal dialog used by MessageService.show_error()."""

    _DETAIL_HEIGHT = 140

    def __init__(self, parent, title: str, message: str,
                 suggestion: Optional[str], solutions, technical: Optional[str]):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowModality(Qt.ApplicationModal)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self._technical = technical
        self._detail_visible = False

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Icon + message row
        icon_label = QLabel()
        icon_label.setPixmap(
            self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxCritical).pixmap(32, 32)
        )
        icon_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        msg_label = QLabel(message)
        msg_label.setWordWrap(True)
        msg_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        top_row = QHBoxLayout()
        top_row.addWidget(icon_label)
        top_row.addWidget(msg_label, 1)
        layout.addLayout(top_row)

        # Suggestion row
        if suggestion:
            sug_label = QLabel(f"What to do: {suggestion}")
            sug_label.setWordWrap(True)
            sug_label.setStyleSheet("color: #aaaaaa; padding-left: 42px;")
            layout.addWidget(sug_label)

        # Numbered solutions list
        if solutions:
            steps_label = QLabel("Things to try:")
            steps_label.setStyleSheet("color: #cccccc; padding-left: 42px; font-weight: bold;")
            layout.addWidget(steps_label)
            for i, step in enumerate(solutions, start=1):
                step_label = QLabel(f"  {i}. {step}")
                step_label.setWordWrap(True)
                step_label.setStyleSheet("color: #aaaaaa; padding-left: 52px;")
                layout.addWidget(step_label)

        # Technical detail toggle
        if technical:
            self._toggle_btn = QPushButton("Show technical detail")
            self._toggle_btn.setCheckable(False)
            self._toggle_btn.setStyleSheet(
                "QPushButton { text-align: left; border: none; color: #888888; "
                "padding: 0; font-size: 11px; } "
                "QPushButton:hover { color: #cccccc; }"
            )
            self._toggle_btn.clicked.connect(self._toggle_detail)
            layout.addWidget(self._toggle_btn)

            self._detail_edit = QTextEdit()
            self._detail_edit.setReadOnly(True)
            self._detail_edit.setPlainText(technical)
            mono = QFont("Monospace")
            mono.setStyleHint(QFont.TypeWriter)
            self._detail_edit.setFont(mono)
            self._detail_edit.setStyleSheet(
                "background-color: #1a1a1a; color: #cccccc; "
                "border: 1px solid #333333; border-radius: 4px;"
            )
            self._detail_edit.setFixedHeight(self._DETAIL_HEIGHT)
            self._detail_edit.hide()
            layout.addWidget(self._detail_edit)

        # OK button - disabled for 3s to prevent accidental dismissal
        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

        self._ok_btn = buttons.button(QDialogButtonBox.Ok)
        self._ok_countdown = 3
        self._ok_btn.setEnabled(False)
        self._ok_btn.setText(f"OK ({self._ok_countdown}s)")
        self._ok_timer = QTimer(self)
        self._ok_timer.timeout.connect(self._tick_ok_countdown)
        self._ok_timer.start(1000)

        self.setMinimumWidth(440)
        self.adjustSize()

    def _tick_ok_countdown(self):
        self._ok_countdown -= 1
        if self._ok_countdown > 0:
            self._ok_btn.setText(f"OK ({self._ok_countdown}s)")
        else:
            self._ok_timer.stop()
            self._ok_btn.setText("OK")
            self._ok_btn.setEnabled(True)

    def _toggle_detail(self):
        self._detail_visible = not self._detail_visible
        if self._detail_visible:
            self._detail_edit.show()
            self._toggle_btn.setText("Hide technical detail")
        else:
            self._detail_edit.hide()
            self._toggle_btn.setText("Show technical detail")
        self.adjustSize()
