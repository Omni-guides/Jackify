"""Runs the Nexus OAuth browser flow off the GUI thread so the dialog stays responsive."""
from PySide6.QtCore import QThread, Signal


class OAuthAuthorizeThread(QThread):
    finished_signal = Signal(bool)
    message_signal = Signal(str)

    def __init__(self, auth_service, parent=None):
        super().__init__(parent)
        self.auth_service = auth_service

    def run(self) -> None:
        success = self.auth_service.authorize_oauth(show_browser_message_callback=self.message_signal.emit)
        self.finished_signal.emit(success)
