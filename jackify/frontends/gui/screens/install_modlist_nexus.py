"""Nexus authentication methods for InstallModlistScreen (Mixin)."""
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QMessageBox, QApplication
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication
import logging
import webbrowser

logger = logging.getLogger(__name__)


class NexusAuthMixin:
    """Mixin providing Nexus authentication methods for InstallModlistScreen."""

    def _update_nexus_status(self):
        """Update the Nexus login status display"""
        authenticated, method, username = self.auth_service.get_auth_status()

        if authenticated and method == 'oauth':
            # OAuth authorised
            status_text = "Authorised"
            if username:
                status_text += f" ({username})"
            self.nexus_status.setText(status_text)
            self.nexus_status.setStyleSheet("color: #3fd0ea;")
            self.nexus_login_btn.setText("Revoke")
            self.nexus_login_btn.setVisible(True)
        elif authenticated and method == 'api_key':
            # API Key in use (fallback - configured in Settings)
            self.nexus_status.setText("API Key")
            self.nexus_status.setStyleSheet("color: #FFA726;")
            self.nexus_login_btn.setText("Authorise")
            self.nexus_login_btn.setVisible(True)
        else:
            # Not authorised
            self.nexus_status.setText("Not Authorised")
            self.nexus_status.setStyleSheet("color: #f44336;")
            self.nexus_login_btn.setText("Authorise")
            self.nexus_login_btn.setVisible(True)

    def _show_copyable_url_dialog(self, url: str):
        """Show a dialog with a copyable URL"""
        dialog = QDialog(self)
        dialog.setWindowTitle("Manual Browser Open Required")
        dialog.setModal(True)
        dialog.setMinimumWidth(600)

        layout = QVBoxLayout()
        layout.setSpacing(15)

        info_label = QLabel(
            "Could not open browser automatically.\n\n"
            "Please copy the URL below and paste it into your browser:"
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #ccc; font-size: 12px;")
        layout.addWidget(info_label)

        url_input = QLineEdit()
        url_input.setText(url)
        url_input.setReadOnly(True)
        url_input.selectAll()
        url_input.setStyleSheet("""
            QLineEdit {
                background-color: #1a1a1a;
                color: #3fd0ea;
                border: 1px solid #444;
                border-radius: 4px;
                padding: 8px;
                font-family: monospace;
                font-size: 11px;
            }
        """)
        layout.addWidget(url_input)

        button_layout = QHBoxLayout()
        button_layout.addStretch()

        copy_btn = QPushButton("Copy URL")
        copy_btn.setStyleSheet("""
            QPushButton {
                background-color: #3fd0ea;
                color: #000;
                border: none;
                border-radius: 4px;
                padding: 8px 20px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #5fdfff;
            }
        """)
        def copy_to_clipboard():
            clipboard = QApplication.clipboard()
            clipboard.setText(url)
            copy_btn.setText("Copied!")
            copy_btn.setEnabled(False)
        copy_btn.clicked.connect(copy_to_clipboard)
        button_layout.addWidget(copy_btn)

        close_btn = QPushButton("Close")
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #444;
                color: #ccc;
                border: none;
                border-radius: 4px;
                padding: 8px 20px;
            }
            QPushButton:hover {
                background-color: #555;
            }
        """)
        close_btn.clicked.connect(dialog.accept)
        button_layout.addWidget(close_btn)

        layout.addLayout(button_layout)
        dialog.setLayout(layout)
        dialog.exec()

    def _show_oauth_paste_dialog(self):
        """Show dialog for pasting jackify:// callback URL as manual fallback."""
        import urllib.parse
        from pathlib import Path

        dialog = QDialog(self)
        dialog.setWindowTitle("Paste Callback URL")
        dialog.setModal(True)
        dialog.setMinimumWidth(560)

        layout = QVBoxLayout()
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        info_label = QLabel(
            "If your browser did not complete the flow automatically:\n\n"
            "1. Click Continue in your browser if you have not already.\n"
            "2. If a URL starting with jackify:// appears in your browser\n"
            "   address bar, copy it and paste it below."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #ccc; font-size: 12px;")
        layout.addWidget(info_label)

        url_input = QLineEdit()
        url_input.setPlaceholderText("jackify://oauth/callback?code=...&state=...")
        url_input.setStyleSheet("""
            QLineEdit {
                background-color: #1a1a1a;
                color: #3fd0ea;
                border: 1px solid #444;
                border-radius: 4px;
                padding: 8px;
                font-family: monospace;
                font-size: 11px;
            }
        """)
        layout.addWidget(url_input)

        error_label = QLabel("")
        error_label.setStyleSheet("color: #f44336; font-size: 11px;")
        error_label.setWordWrap(True)
        layout.addWidget(error_label)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        submit_btn = QPushButton("Submit")
        submit_btn.setStyleSheet("""
            QPushButton {
                background-color: #3fd0ea;
                color: #000;
                border: none;
                border-radius: 4px;
                padding: 8px 20px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #5fdfff;
            }
        """)

        def on_submit():
            url = url_input.text().strip()
            if not url.startswith('jackify://oauth/callback'):
                error_label.setText("URL must start with jackify://oauth/callback")
                return
            parsed = urllib.parse.urlparse(url)
            params = urllib.parse.parse_qs(parsed.query)
            code = params.get('code', [None])[0]
            state = params.get('state', [None])[0]
            if not code or not state:
                error_label.setText("URL is missing required code or state parameter.")
                return
            callback_file = Path.home() / ".config" / "jackify" / "oauth_callback.tmp"
            try:
                callback_file.parent.mkdir(parents=True, exist_ok=True)
                callback_file.write_text(f"{code}\n{state}")
                logger.info("OAuth callback written via manual paste")
                dialog.accept()
            except Exception as e:
                error_label.setText(f"Failed to write callback: {e}")

        submit_btn.clicked.connect(on_submit)
        url_input.returnPressed.connect(on_submit)
        btn_layout.addWidget(submit_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #444;
                color: #ccc;
                border: none;
                border-radius: 4px;
                padding: 8px 20px;
            }
            QPushButton:hover {
                background-color: #555;
            }
        """)
        cancel_btn.clicked.connect(dialog.reject)
        btn_layout.addWidget(cancel_btn)

        layout.addLayout(btn_layout)
        dialog.setLayout(layout)
        dialog.exec()

    def _handle_nexus_login_click(self):
        """Handle Nexus login button click"""
        from jackify.frontends.gui.services.message_service import MessageService

        authenticated, method, _ = self.auth_service.get_auth_status()
        if authenticated and method == 'oauth':
            reply = MessageService.question(self, "Revoke", "Revoke OAuth authorisation?", safety_level="low")
            if reply == QMessageBox.Yes:
                self.auth_service.revoke_oauth()
                self._update_nexus_status()
        else:
            reply = MessageService.question(self, "Authorise with Nexus",
                "Your browser will open for Nexus authorisation.\n\n"
                "Note: Your browser may ask permission to open 'xdg-open'\n"
                "or Jackify's protocol handler - please click 'Open' or 'Allow'.\n\n"
                "Please log in and authorise Jackify when prompted.\n\n"
                "Continue?", safety_level="low")

            if reply != QMessageBox.Yes:
                return

            # Build waiting dialog with paste fallback always accessible
            wait_dialog = QDialog(self)
            wait_dialog.setWindowTitle("Nexus OAuth")
            wait_dialog.setWindowModality(Qt.WindowModal)
            wait_dialog.setMinimumWidth(420)

            wait_layout = QVBoxLayout()
            wait_layout.setSpacing(12)
            wait_layout.setContentsMargins(20, 20, 20, 20)

            wait_label = QLabel(
                "Waiting for authorisation...\n\n"
                "Please complete authorisation in your browser.\n\n"
                "Your browser may ask permission to open Jackify - click Open or Allow."
            )
            wait_label.setWordWrap(True)
            wait_label.setStyleSheet("color: #ccc; font-size: 12px;")
            wait_layout.addWidget(wait_label)

            wait_layout.addStretch()

            btn_layout = QHBoxLayout()

            paste_btn = QPushButton("Paste callback URL")
            paste_btn.setToolTip(
                "If your browser shows a jackify:// URL after clicking Continue, paste it here."
            )
            paste_btn.setStyleSheet("""
                QPushButton {
                    background-color: #333;
                    color: #aaa;
                    border: 1px solid #555;
                    border-radius: 4px;
                    padding: 8px 16px;
                }
                QPushButton:hover {
                    background-color: #444;
                    color: #ccc;
                }
            """)
            paste_btn.clicked.connect(self._show_oauth_paste_dialog)
            btn_layout.addWidget(paste_btn)

            btn_layout.addStretch()

            oauth_cancelled = [False]

            cancel_btn = QPushButton("Cancel")
            cancel_btn.setStyleSheet("""
                QPushButton {
                    background-color: #444;
                    color: #ccc;
                    border: none;
                    border-radius: 4px;
                    padding: 8px 16px;
                }
                QPushButton:hover {
                    background-color: #555;
                }
            """)
            def on_cancel_click():
                oauth_cancelled[0] = True
                self.auth_service.cancel_oauth()
                wait_dialog.close()
            cancel_btn.clicked.connect(on_cancel_click)
            btn_layout.addWidget(cancel_btn)

            wait_layout.addLayout(btn_layout)
            wait_dialog.setLayout(wait_layout)
            wait_dialog.show()
            QApplication.processEvents()

            # Create OAuth thread to prevent GUI freeze
            class OAuthThread(QThread):
                finished_signal = Signal(bool)
                message_signal = Signal(str)
                manual_url_signal = Signal(str)

                def __init__(self, auth_service, parent=None):
                    super().__init__(parent)
                    self.auth_service = auth_service

                def run(self):
                    def show_message(msg):
                        if "Could not open browser" in msg and "Please open this URL manually:" in msg:
                            url_start = msg.find("Please open this URL manually:") + len("Please open this URL manually:")
                            url = msg[url_start:].strip()
                            self.manual_url_signal.emit(url)
                        else:
                            self.message_signal.emit(msg)

                    success = self.auth_service.authorize_oauth(show_browser_message_callback=show_message)
                    self.finished_signal.emit(success)

            oauth_thread = OAuthThread(self.auth_service, self)

            def update_progress_message(msg):
                if not oauth_cancelled[0]:
                    wait_label.setText(f"Waiting for authorisation...\n\n{msg}")
                    QApplication.processEvents()

            def show_manual_url_dialog(url):
                if not oauth_cancelled[0]:
                    wait_dialog.hide()
                    self._show_copyable_url_dialog(url)
                    wait_dialog.show()

            oauth_thread.message_signal.connect(update_progress_message)
            oauth_thread.manual_url_signal.connect(show_manual_url_dialog)

            oauth_success = [False]
            def on_oauth_finished(success):
                oauth_success[0] = success

            oauth_thread.finished_signal.connect(on_oauth_finished)
            oauth_thread.start()

            while oauth_thread.isRunning():
                QApplication.processEvents()
                oauth_thread.wait(100)
                if oauth_cancelled[0]:
                    oauth_thread.wait(2000)
                    break

            wait_dialog.close()
            QApplication.processEvents()

            self._update_nexus_status()
            self._enable_controls_after_operation()

            if oauth_success[0]:
                _, _, username = self.auth_service.get_auth_status()
                if username:
                    msg = f"OAuth authorisation successful!<br><br>Authorised as: {username}"
                else:
                    msg = "OAuth authorisation successful!"
                MessageService.information(self, "Success", msg, safety_level="low")
            elif oauth_cancelled[0]:
                MessageService.information(self, "Cancelled", "OAuth authorisation cancelled.", safety_level="low")
            else:
                MessageService.warning(
                    self,
                    "Authorisation Failed",
                    "OAuth authorisation timed out.\n\n"
                    "If your browser shows a URL starting with jackify:// after\n"
                    "clicking Continue, try again and use 'Paste callback URL'\n"
                    "during the wait to complete authorisation manually.\n\n"
                    "If the issue persists, an API key can be configured in Settings.",
                    safety_level="medium"
                )
