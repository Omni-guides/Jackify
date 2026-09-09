"""Small input dialogs for GameDowngradeScreen - split out to keep that file under the size
guardrail. Backed by GameDowngradePromptDriver rather than a terminal; see that module for why
a plain piped stdin is sufficient for steamcmd's interactive prompts.
"""

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QLineEdit, QVBoxLayout


class _AnswerDialog(QDialog):
    """Small modal for one line of input - plain text or password-masked."""

    def __init__(self, title: str, label: str, password: bool = False, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(360)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(label))
        self._field = QLineEdit()
        if password:
            self._field.setEchoMode(QLineEdit.Password)
        layout.addWidget(self._field)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._field.setFocus()

    def value(self) -> str:
        return self._field.text()


class _LoginDialog(QDialog):
    """Modal asking for both Steam username and password in one go."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Steam Login")
        self.setMinimumWidth(360)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Enter your Steam login for steamcmd:"))

        note = QLabel("Jackify never stores or logs your Steam credentials.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #aaa; font-size: 11px;")
        layout.addWidget(note)

        layout.addWidget(QLabel("Username:"))
        self._username_field = QLineEdit()
        layout.addWidget(self._username_field)

        layout.addWidget(QLabel("Password:"))
        self._password_field = QLineEdit()
        self._password_field.setEchoMode(QLineEdit.Password)
        layout.addWidget(self._password_field)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._username_field.setFocus()

    def values(self) -> tuple:
        return self._username_field.text().strip(), self._password_field.text()
