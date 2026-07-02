"""Guided dialog for installing a Nexus-only tool via manual browser download."""

import logging
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QFileDialog, QFrame,
)

from jackify.frontends.gui.services.message_service import open_url

logger = logging.getLogger(__name__)


class NexusManualInstallDialog(QDialog):
    """
    Guides the user through manually downloading a Nexus-only tool and handing
    the archive to Jackify for extraction and installation.
    """

    def __init__(self, tool_id: str, display_name: str, nexus_url: str, parent=None):
        super().__init__(parent)
        self._tool_id = tool_id
        self._nexus_url = nexus_url
        self._archive_path: Optional[Path] = None

        self.setWindowTitle(f"Install {display_name}")
        self.setModal(True)
        self.setMinimumWidth(480)
        self.setStyleSheet("QDialog { background: #181818; color: #fff; }")
        self._build_ui(display_name)
        self.adjustSize()

    def _build_ui(self, display_name: str) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(20, 20, 20, 20)

        card = QFrame(self)
        card.setObjectName("dialogCard")
        card.setFrameShape(QFrame.StyledPanel)
        card.setFrameShadow(QFrame.Raised)
        card.setStyleSheet(
            "QFrame#dialogCard { "
            "  background: #2d2d2d; "
            "  border-radius: 12px; "
            "  border: 1px solid #555; "
            "}"
        )
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(16)
        card_layout.setContentsMargins(28, 28, 28, 28)

        title_label = QLabel(f"Manual download required: {display_name}")
        title_label.setStyleSheet("color: #3fd0ea; font-size: 14px; font-weight: 600;")
        title_label.setWordWrap(True)
        card_layout.addWidget(title_label)

        body_label = QLabel(
            f"{display_name} is only available on Nexus Mods. As you do not have Nexus "
            "Premium, please perform the following steps manually:\n\n"
            f"1. Click 'Open Nexus Page' below and click Manual Download on the Nexus page "
            f"to download {display_name}\n"
            "2. Once the download is complete, click 'Browse...' below and select the "
            "downloaded archive\n"
            "3. Click Install to complete the installation."
        )
        body_label.setWordWrap(True)
        card_layout.addWidget(body_label)

        nexus_btn = QPushButton("Open Nexus Page")
        nexus_btn.clicked.connect(self._open_nexus)
        card_layout.addWidget(nexus_btn)

        file_row = QHBoxLayout()
        self._file_edit = QLineEdit()
        self._file_edit.setPlaceholderText("No file selected...")
        self._file_edit.setReadOnly(True)
        self._file_edit.setStyleSheet(
            "QLineEdit { "
            "  background: #1a1a1a; "
            "  color: #fff; "
            "  border: 1px solid #555; "
            "  border-radius: 4px; "
            "  padding: 8px; "
            "}"
        )
        file_row.addWidget(self._file_edit)

        browse_btn = QPushButton("Browse...")
        browse_btn.setMinimumWidth(90)
        browse_btn.clicked.connect(self._browse)
        file_row.addWidget(browse_btn)
        card_layout.addLayout(file_row)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setMinimumWidth(100)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        self._install_btn = QPushButton("Install")
        self._install_btn.setDefault(True)
        self._install_btn.setMinimumWidth(100)
        self._install_btn.setEnabled(False)
        self._install_btn.clicked.connect(self.accept)
        btn_row.addWidget(self._install_btn)

        card_layout.addLayout(btn_row)
        main_layout.addWidget(card)

    def _open_nexus(self) -> None:
        if self._nexus_url:
            open_url(self._nexus_url)

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select downloaded archive",
            str(Path.home() / "Downloads"),
            "Archives (*.zip *.tar.gz *.tar.xz *.7z);;All files (*)",
        )
        if path:
            self._archive_path = Path(path)
            self._file_edit.setText(path)
            self._install_btn.setEnabled(True)

    @property
    def selected_archive(self) -> Optional[Path]:
        return self._archive_path

    @property
    def tool_id(self) -> str:
        return self._tool_id
