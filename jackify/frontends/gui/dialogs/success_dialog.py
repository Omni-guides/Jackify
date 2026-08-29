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

from jackify.frontends.gui.services.message_service import open_url

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
    
    def __init__(
        self,
        modlist_name: str,
        workflow_type: str,
        time_taken: str,
        game_name: str = None,
        verification_results=None,
        disabled_problem_mods=None,
        readme_url: str = None,
        parent=None,
    ):
        super().__init__(parent)
        self.modlist_name = modlist_name
        self.workflow_type = workflow_type
        self.time_taken = time_taken
        self.game_name = game_name
        self.verification_results = verification_results
        self.disabled_problem_mods = disabled_problem_mods or []
        self.readme_url = readme_url
        self.setWindowTitle("Complete" if (verification_results and verification_results.failures) else "Success!")
        self.setWindowModality(Qt.NonModal)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setFixedWidth(500)
        self.setMinimumHeight(400)
        self.setWindowFlag(Qt.WindowDoesNotAcceptFocus, True)
        self.setStyleSheet("QDialog { background: #181818; color: #fff; border-radius: 12px; }" )
        layout = QVBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(20, 20, 20, 20)

        # --- Card background for content ---
        card = QFrame(self)
        card.setObjectName("successCard")
        card.setFrameShape(QFrame.StyledPanel)
        card.setFrameShadow(QFrame.Raised)
        # Increase card width and reduce margins to maximize text width for 800p screens
        card.setFixedWidth(460)
        # Remove fixed minimum height to allow natural sizing based on content
        card.setMaximumHeight(16777215)  # Remove max height constraint to allow expansion
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(12)
        card_layout.setContentsMargins(20, 28, 20, 28)  # Reduced left/right margins to give more text width
        card.setStyleSheet(
            "QFrame#successCard { "
            "  background: #23272e; "
            "  border-radius: 12px; "
            "  border: 1px solid #353a40; "
            "}"
        )
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.MinimumExpanding)

        has_verify_failures = bool(
            self.verification_results and self.verification_results.failures
        )

        title_text = "Complete" if has_verify_failures else "Success!"
        title_color = "#f0c040" if has_verify_failures else "#3fd0ea"
        title_label = QLabel(title_text)
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet(
            f"QLabel {{ "
            f"  font-size: 22px; "
            f"  font-weight: 600; "
            f"  color: {title_color}; "
            f"  margin-bottom: 2px; "
            f"}}"
        )
        card_layout.addWidget(title_label)

        # Personalized message (modlist name in Jackify Blue, but less bold)
        modlist_name_html = f'<span style="color:#3fb7d6; font-size:17px; font-weight:500;">{self.modlist_name}</span>'
        if has_verify_failures:
            suffix_map = {
                "install": "installed with issues - review verification results.",
                "update": "updated with issues - review verification results.",
                "configure_new": "configured with issues - review verification results.",
                "configure_existing": "configuration updated with issues - review verification results.",
                "tool_config": "tool compatibility configured with issues - review verification results.",
            }
            suffix_text = suffix_map.get(self.workflow_type, "completed with issues - review verification results.")
        elif self.workflow_type == "install":
            suffix_text = "installed successfully!"
        elif self.workflow_type == "update":
            suffix_text = "updated successfully!"
        elif self.workflow_type == "configure_new":
            suffix_text = "configured successfully!"
        elif self.workflow_type == "configure_existing":
            suffix_text = "configuration updated successfully!"
        elif self.workflow_type == "tool_config":
            suffix_text = "tool compatibility configured successfully!"
        else:
            message_text = self._build_success_message()
            suffix_text = message_text.replace(self.modlist_name, "").strip()
        
        # Build complete message with proper HTML formatting - ensure both parts are visible
        message_html = f'{modlist_name_html} <span style="font-size:15px; color:#e0e0e0;">{suffix_text}</span>'
        message_label = QLabel(message_html)
        # Center the success message within the wider card for all screen sizes
        message_label.setAlignment(Qt.AlignCenter)
        message_label.setWordWrap(True)
        message_label.setMinimumHeight(30)  # Ensure label has minimum height to be visible
        message_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        message_label.setStyleSheet(
            "QLabel { "
            "  font-size: 15px; "
            "  color: #e0e0e0; "
            "  line-height: 1.3; "
            "  margin-bottom: 6px; "
            "  padding: 0px; "
            "}"
        )
        message_label.setTextFormat(Qt.RichText)
        # Ensure the label uses full width of the card before wrapping
        card_layout.addWidget(message_label)

        # Time taken (omit label if time is not available)
        if self.time_taken:
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
        # Remove fixed minimum height to allow natural sizing
        next_steps_label.setStyleSheet(
            "QLabel { "
            "  font-size: 13px; "
            "  color: #b0b0b0; "
            "  line-height: 1.4; "
            "  padding: 6px; "
            "  background-color: transparent; "
            "  border-radius: 6px; "
            "  border: none; "
            "}"
        )
        card_layout.addWidget(next_steps_label)

        # Verification results summary
        if self.verification_results is not None:
            self._add_verification_section(card_layout)

        # Problem mods that were auto-disabled
        if self.disabled_problem_mods:
            self._add_problem_mods_section(card_layout)

        # Readme link (install workflow only)
        if self.readme_url:
            readme_label = QLabel(
                f'<a href="{self.readme_url}" style="color:#3fd0ea; text-decoration:none;">'
                "Open modlist readme"
                "</a>"
            )
            readme_label.setAlignment(Qt.AlignCenter)
            readme_label.setStyleSheet(
                "QLabel { color: #3fd0ea; font-size: 11px; margin-top: 4px; padding: 4px; background-color: transparent; }"
            )
            readme_label.setTextInteractionFlags(Qt.TextBrowserInteraction)
            readme_label.setOpenExternalLinks(False)
            readme_label.linkActivated.connect(open_url)
            card_layout.addWidget(readme_label)

        # Subtle Ko-Fi support link
        kofi_label = QLabel('<a href="https://ko-fi.com/omni1" style="color:#3fd0ea; text-decoration:none;">Enjoying Jackify? Support development ♥</a>')
        kofi_label.setAlignment(Qt.AlignCenter)
        kofi_label.setStyleSheet(
            "QLabel { "
            "  color: #3fd0ea; "
            "  font-size: 11px; "
            "  margin-top: 8px; "
            "  padding: 4px; "
            "  background-color: transparent; "
            "}"
        )
        kofi_label.setTextInteractionFlags(Qt.TextBrowserInteraction)
        kofi_label.setOpenExternalLinks(False)
        kofi_label.linkActivated.connect(open_url)
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
        self.exit_btn.clicked.connect(self._safe_exit)

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
            "update": f"{self.modlist_name} updated successfully!",
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

        base_message = ""
        if self.workflow_type == "tool_config":
            base_message = (
                f"Modding tools for {self.modlist_name} are now configured. "
                "xEdit, Synthesis, Pandora, and DLL overrides are ready to use from within Mod Organizer 2."
            )
        elif self.workflow_type == "tuxborn":
            base_message = f"You can now launch Tuxborn from Steam and enjoy your modded {game_display} experience!"
        elif self.workflow_type == "game_downgrade":
            base_message = "Steam has been restarted. The game is ready to use with modlists built for this version."
        elif self.workflow_type == "game_downgrade_restore":
            base_message = "Steam has been restarted. The game has been restored to its previous version."
        elif self.workflow_type == "game_downgrade_dry_run":
            base_message = (
                "No game files or Steam settings were changed - this was a preview only. "
                "Uncheck \"Dry run\" and run it again to actually apply the downgrade."
            )
        elif self.workflow_type == "install" and self.modlist_name == "Wabbajack":
            base_message = "You can now launch Wabbajack from Steam and install modlists. Once the modlist install is complete, you can run \"Configure New Modlist\" in Jackify to complete the configuration for running the modlist on Linux."
        else:
            try:
                from jackify.backend.handlers.config_handler import ConfigHandler
                auto_tool_compat = ConfigHandler().get('auto_tool_compat', True)
            except Exception:
                auto_tool_compat = True

            tool_hint = (
                "<br><br>"
                "<span style=\"color:#b0b0b0; font-size:12px;\">"
                "If you use modding tools such as xEdit, Synthesis, or Pandora, "
                "run <b>Configure Tool Compatibility</b> from the Additional Tasks menu."
                "</span>"
            ) if not auto_tool_compat else ""

            base_message = (
                f"You can now launch {self.modlist_name} from Steam and enjoy your modded {game_display} experience!"
                f"{tool_hint}"
            )

        # ENB Proton warning shown in separate dialog
        return base_message

    def _add_verification_section(self, card_layout):
        """Add a verification summary section to the card layout."""
        from PySide6.QtWidgets import QScrollArea

        r = self.verification_results
        n_pass = len(r.passes)
        n_warn = len(r.warnings)
        n_fail = len(r.failures)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #353a40;")
        card_layout.addWidget(sep)

        if n_fail:
            summary_text = f"[FAIL] Verification: {n_fail} failure(s), {n_warn} warning(s)"
            summary_color = "#e05050"
        elif n_warn:
            summary_text = f"[WARN] Verification: {n_warn} warning(s) - review before playing"
            summary_color = "#f0c040"
        else:
            summary_text = f"[OK] Verification passed ({n_pass} checks)"
            summary_color = "#3fd0ea"

        summary_row = QHBoxLayout()
        summary_row.setContentsMargins(0, 0, 0, 0)
        summary_row.setSpacing(8)

        summary_lbl = QLabel(summary_text)
        summary_lbl.setAlignment(Qt.AlignCenter)
        summary_lbl.setWordWrap(True)
        summary_lbl.setStyleSheet(
            f"QLabel {{ font-size: 12px; font-weight: bold; color: {summary_color}; }}"
        )
        summary_row.addStretch()
        summary_row.addWidget(summary_lbl)

        view_btn = QPushButton("View checks")
        view_btn.setFixedWidth(90)
        view_btn.setStyleSheet(
            "QPushButton { font-size: 11px; color: #ccc; background: #3a3a3a; "
            "border: 1px solid #555; border-radius: 4px; padding: 3px 6px; }"
            "QPushButton:hover { background: #4a4a4a; color: #fff; }"
        )
        view_btn.setCursor(Qt.PointingHandCursor)
        view_btn.clicked.connect(lambda: self._show_verification_detail())
        summary_row.addWidget(view_btn)
        summary_row.addStretch()

        row_widget = QWidget()
        row_widget.setLayout(summary_row)
        card_layout.addWidget(row_widget)

        if n_fail or n_warn:
            detail_widget = QWidget()
            detail_layout = QVBoxLayout(detail_widget)
            detail_layout.setContentsMargins(0, 0, 0, 0)
            detail_layout.setSpacing(2)

            for msg in r.failures:
                lbl = QLabel(f"[FAIL] {msg}")
                lbl.setWordWrap(True)
                lbl.setStyleSheet("color: #e05050; font-size: 11px;")
                detail_layout.addWidget(lbl)
            for msg in r.warnings:
                lbl = QLabel(f"[WARN] {msg}")
                lbl.setWordWrap(True)
                lbl.setStyleSheet("color: #f0c040; font-size: 11px;")
                detail_layout.addWidget(lbl)

            scroll = QScrollArea()
            scroll.setWidget(detail_widget)
            scroll.setWidgetResizable(True)
            scroll.setMaximumHeight(120)
            scroll.setStyleSheet(
                "QScrollArea { border: 1px solid #353a40; border-radius: 4px; background: #1a1d23; }"
            )
            card_layout.addWidget(scroll)

    def _show_verification_detail(self):
        """Open the full verification results dialog."""
        try:
            from jackify.frontends.gui.dialogs.verification_results_dialog import VerificationResultsDialog
            dlg = VerificationResultsDialog(self.verification_results, parent=self)
            dlg.show()
        except Exception as exc:
            logger.error("Could not open verification dialog: %s", exc)

    def _add_problem_mods_section(self, card_layout):
        """Add an auto-disabled problem mods section to the card layout."""
        from PySide6.QtWidgets import QFrame

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #444;")
        card_layout.addWidget(sep)

        header = QLabel("Compatibility Notice")
        header.setStyleSheet("font-size: 12px; font-weight: bold; color: #c8a050; margin-top: 4px;")
        card_layout.addWidget(header)

        msg_text = (
            "Due to known compatibility issues with Proton, the following mods were "
            "automatically disabled:\n\n"
            + "\n".join(f"  - {name}" for name in self.disabled_problem_mods)
        )
        msg_label = QLabel(msg_text)
        msg_label.setWordWrap(True)
        msg_label.setStyleSheet("font-size: 11px; color: #bbb; margin-bottom: 4px;")
        card_layout.addWidget(msg_label)

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

    def _safe_exit(self):
        """Safely exit the application with proper cleanup"""
        try:
            if self._timer.isActive():
                self._timer.stop()
            self.close()
            QApplication.quit()
        except Exception as e:
            logger.error(f"Error during safe exit: {e}")
            QApplication.quit() 
