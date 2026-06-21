"""NXM download dialog: modlist picker and download runner."""

import logging
from pathlib import Path
from typing import Optional, List, Dict, Tuple

from PySide6.QtCore import QThread, Signal, Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QCheckBox,
    QPushButton,
    QProgressBar,
    QFrame,
)

from jackify.backend.services.nxm_url import NxmUrl
from jackify.frontends.gui.shared_theme import JACKIFY_COLOR_BLUE
import jackify.backend.services.nxm_session as nxm_session

logger = logging.getLogger(__name__)

_BG_DARK = "#16191d"
_BG_CARD = "#1e2228"
_BG_LIST = "#1a1d23"
_BORDER = "#333"
_TEXT = "#d0d0d0"
_TEXT_DIM = "#8f98a3"
_TEXT_BRIGHT = "#e0e0e0"
_ERROR = "#cc4444"


class _ModNameFetchThread(QThread):
    name_ready = Signal(str)

    def __init__(self, nxm: NxmUrl, parent=None):
        super().__init__(parent)
        self.nxm = nxm

    def run(self) -> None:
        try:
            from jackify.backend.services.nexus_auth_service import NexusAuthService
            svc = NexusAuthService()
            token = svc.get_auth_token()
            method = svc.get_auth_method() or "api_key"
        except Exception:
            try:
                from jackify.backend.services.api_key_service import APIKeyService
                token = APIKeyService().get_saved_api_key()
                method = "api_key"
            except Exception:
                return

        if not token:
            return

        try:
            import requests
            if method == "oauth":
                headers = {"Authorization": f"Bearer {token}", "User-Agent": "jackify"}
            else:
                headers = {"apikey": token, "User-Agent": "jackify"}
            url = (
                f"https://api.nexusmods.com/v1/games/{self.nxm.game}"
                f"/mods/{self.nxm.mod_id}.json"
            )
            resp = requests.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            name = resp.json().get("name", "")
            if name:
                self.name_ready.emit(name)
        except Exception as e:
            logger.debug("Mod name fetch failed: %s", e)


class _DownloadThread(QThread):
    progress = Signal(int, int)
    finished = Signal(bool, str)

    def __init__(
        self,
        nxm: NxmUrl,
        download_dir: Path,
        auth_token: str,
        auth_method: str,
        parent=None,
    ):
        super().__init__(parent)
        self.nxm = nxm
        self.download_dir = download_dir
        self.auth_token = auth_token
        self.auth_method = auth_method

    def run(self) -> None:
        from jackify.backend.services.nxm_downloader import (
            get_nxm_download_url,
            download_nxm_file,
            filename_from_cdn_url,
        )

        cdn_url = get_nxm_download_url(self.nxm, self.auth_token, self.auth_method)
        if not cdn_url:
            self.finished.emit(False, "Could not resolve download URL from Nexus API.")
            return

        filename = filename_from_cdn_url(
            cdn_url, f"mod_{self.nxm.mod_id}_file_{self.nxm.file_id}.zip"
        )
        ok, msg = download_nxm_file(cdn_url, self.download_dir, filename, self._on_progress)
        self.finished.emit(ok, msg)

    def _on_progress(self, downloaded: int, total: int) -> None:
        self.progress.emit(downloaded, total)


class NxmDownloadDialog(QDialog):
    """Modlist picker and download runner for incoming nxm:// links.

    When auto_start_modlist is provided the picker is hidden and the download
    begins immediately - used when session memory has a remembered modlist.
    """

    def __init__(
        self,
        nxm: NxmUrl,
        modlists: List[Dict],
        parent=None,
        auto_start_modlist: Optional[Dict] = None,
    ):
        super().__init__(parent)
        self.nxm = nxm
        self.modlists = modlists
        self._thread: Optional[_DownloadThread] = None
        self._name_thread: Optional[_ModNameFetchThread] = None
        self._auto_start_modlist = auto_start_modlist

        self.setWindowTitle("NXM Download")
        self.setMinimumWidth(520)
        self.setModal(False)
        self.setStyleSheet(f"QDialog {{ background: {_BG_DARK}; color: {_TEXT}; }}")
        self._build_ui(show_picker=auto_start_modlist is None)
        if auto_start_modlist is None:
            self._apply_session_memory()
        self._fetch_mod_name()

    # --- UI construction ---

    def _build_ui(self, show_picker: bool = True) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        layout.addWidget(self._make_header())

        if show_picker:
            layout.addWidget(self._make_section_label("Select modlist:"))
            layout.addWidget(self._make_modlist_list())
            layout.addWidget(self._make_dest_label())
            layout.addWidget(self._make_session_row())
        else:
            name = self._auto_start_modlist.get("name", "")
            lbl = QLabel(f"Downloading to: <span style='color:{JACKIFY_COLOR_BLUE}'>{name}</span>")
            lbl.setTextFormat(Qt.RichText)
            lbl.setStyleSheet(f"color: {_TEXT};")
            layout.addWidget(lbl)
            self._clear_session_btn = QPushButton("Change modlist (clear session)")
            self._clear_session_btn.setFlat(True)
            self._clear_session_btn.setStyleSheet(f"color: {JACKIFY_COLOR_BLUE};")
            self._clear_session_btn.clicked.connect(self._on_clear_and_reopen)
            layout.addWidget(self._clear_session_btn)

        layout.addWidget(self._make_progress_section())
        layout.addWidget(self._make_separator())
        layout.addLayout(self._make_button_row())

    def _make_header(self) -> QFrame:
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background: {_BG_CARD}; border-radius: 6px; border: 1px solid {_BORDER}; }}"
        )
        vbox = QVBoxLayout(card)
        vbox.setContentsMargins(12, 10, 12, 10)
        vbox.setSpacing(4)

        self._title_label = QLabel(f"<b>NXM Download: Mod {self.nxm.mod_id}</b>")
        self._title_label.setStyleSheet(f"color: {_TEXT_BRIGHT}; font-size: 13px; border: none;")
        self._title_label.setTextFormat(Qt.RichText)
        vbox.addWidget(self._title_label)

        detail = QLabel(
            f"Game: <span style='color:{JACKIFY_COLOR_BLUE}'>{self.nxm.game}</span>"
            f" &nbsp;|&nbsp; Mod ID: {self.nxm.mod_id}"
            f" &nbsp;|&nbsp; File ID: {self.nxm.file_id}"
        )
        detail.setTextFormat(Qt.RichText)
        detail.setStyleSheet(f"color: {_TEXT_DIM}; font-size: 11px; border: none;")
        vbox.addWidget(detail)
        return card

    def _make_section_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {_TEXT_DIM}; font-size: 11px;")
        return lbl

    def _make_modlist_list(self) -> QListWidget:
        self._list = QListWidget()
        self._list.setMaximumHeight(150)
        self._list.setStyleSheet(
            f"QListWidget {{ background: {_BG_LIST}; color: {_TEXT}; "
            f"border: 1px solid {_BORDER}; border-radius: 4px; }}"
            f"QListWidget::item:selected {{ background: #2a3a4a; color: {_TEXT_BRIGHT}; }}"
            f"QListWidget::item:hover {{ background: #222830; }}"
        )
        for ml in self.modlists:
            item = QListWidgetItem(ml["name"])
            item.setData(Qt.UserRole, ml)
            self._list.addItem(item)
        self._list.currentItemChanged.connect(self._on_selection_changed)
        return self._list

    def _make_dest_label(self) -> QLabel:
        self._dest_label = QLabel("Download directory: (none)")
        self._dest_label.setStyleSheet(f"color: {_TEXT_DIM}; font-size: 11px;")
        self._dest_label.setWordWrap(True)
        return self._dest_label

    def _make_session_row(self) -> QFrame:
        container = QFrame()
        container.setStyleSheet("QFrame { border: none; }")
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)

        self._remember_cb = QCheckBox("Remember for this session")
        self._remember_cb.setStyleSheet(f"color: {_TEXT};")
        row.addWidget(self._remember_cb)
        row.addStretch()

        self._clear_btn = QPushButton("Clear remembered modlist")
        self._clear_btn.setFlat(True)
        self._clear_btn.setStyleSheet(f"color: {JACKIFY_COLOR_BLUE};")
        self._clear_btn.clicked.connect(self._on_clear_session)
        row.addWidget(self._clear_btn)

        self._update_clear_button()
        return container

    def _make_progress_section(self) -> QFrame:
        container = QFrame()
        container.setStyleSheet("QFrame { border: none; }")
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(4)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet(f"color: {_TEXT_DIM};")
        self._status_label.setVisible(False)
        self._status_label.setWordWrap(True)
        self._status_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        vbox.addWidget(self._status_label)

        self._progress_bar = QProgressBar()
        self._progress_bar.setStyleSheet(
            f"QProgressBar {{ border: 1px solid {_BORDER}; border-radius: 4px; "
            f"background: #2c2c2c; height: 10px; color: transparent; }}"
            f"QProgressBar::chunk {{ background: {JACKIFY_COLOR_BLUE}; border-radius: 3px; }}"
        )
        self._progress_bar.setVisible(False)
        vbox.addWidget(self._progress_bar)
        return container

    def _make_button_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addStretch()

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setStyleSheet(
            f"QPushButton {{ background: #3a2020; color: {_TEXT}; border: 1px solid {_BORDER}; "
            f"border-radius: 4px; padding: 5px 14px; }}"
            f"QPushButton:hover {{ background: #5a2828; }}"
        )
        self._cancel_btn.clicked.connect(self.reject)
        row.addWidget(self._cancel_btn)

        self._download_btn = QPushButton("Download")
        self._download_btn.setEnabled(False)
        self._download_btn.setDefault(True)
        self._download_btn.setStyleSheet(
            f"QPushButton {{ background: {JACKIFY_COLOR_BLUE}; color: #000; font-weight: 600; "
            f"border: none; border-radius: 4px; padding: 5px 18px; }}"
            f"QPushButton:hover {{ background: #5ae0f5; }}"
            f"QPushButton:disabled {{ background: #2a4a52; color: #555; }}"
        )
        self._download_btn.clicked.connect(self._on_download)
        row.addWidget(self._download_btn)
        return row

    @staticmethod
    def _make_separator() -> QFrame:
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color: {_BORDER};")
        return sep

    # --- Session memory ---

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._auto_start_modlist is not None:
            QTimer.singleShot(0, self._start_auto_download)

    def _start_auto_download(self) -> None:
        self._start_download_for(self._auto_start_modlist)

    def _on_clear_and_reopen(self) -> None:
        nxm_session.clear_remembered_modlist()
        self.reject()
        dlg = NxmDownloadDialog(self.nxm, self.modlists, parent=self.parent())
        dlg.show()

    def _fetch_mod_name(self) -> None:
        self._name_thread = _ModNameFetchThread(self.nxm, self)
        self._name_thread.name_ready.connect(self._on_mod_name_ready)
        self._name_thread.start()

    def _on_mod_name_ready(self, name: str) -> None:
        self._title_label.setText(f"<b>NXM Download: {name}</b>")
        self._name_thread = None

    def _apply_session_memory(self) -> None:
        remembered = nxm_session.get_remembered_modlist()
        if not remembered:
            return
        for i in range(self._list.count()):
            if self._list.item(i).text() == remembered:
                self._list.setCurrentRow(i)
                self._remember_cb.setChecked(True)
                break

    def _on_clear_session(self) -> None:
        nxm_session.clear_remembered_modlist()
        self._remember_cb.setChecked(False)
        self._update_clear_button()

    def _update_clear_button(self) -> None:
        self._clear_btn.setVisible(bool(nxm_session.get_remembered_modlist()))

    def _on_selection_changed(self) -> None:
        item = self._list.currentItem()
        self._download_btn.setEnabled(item is not None)
        if item:
            modlist = item.data(Qt.UserRole)
            self._update_dest_label(modlist)

    def _update_dest_label(self, modlist: Dict) -> None:
        from jackify.backend.services.nxm_downloader import resolve_mo2_download_dir
        modlist_dir = Path(modlist.get("modlist_dir", ""))
        download_dir = resolve_mo2_download_dir(modlist_dir)
        if download_dir:
            self._dest_label.setText(f"Download directory: {download_dir}")
            self._dest_label.setStyleSheet(f"color: {_TEXT_DIM}; font-size: 11px;")
        else:
            self._dest_label.setText("Download directory: not configured - run Configure first")
            self._dest_label.setStyleSheet(f"color: {_ERROR}; font-size: 11px;")

    # --- Download ---

    def _on_download(self) -> None:
        item = self._list.currentItem()
        if not item:
            return
        modlist = item.data(Qt.UserRole)
        if self._remember_cb.isChecked():
            nxm_session.set_remembered_modlist(modlist["name"])
            self._update_clear_button()
        self._start_download_for(modlist)

    def _start_download_for(self, modlist: Dict) -> None:
        modlist_dir = Path(modlist.get("modlist_dir", ""))

        from jackify.backend.services.nxm_downloader import resolve_mo2_download_dir
        download_dir = resolve_mo2_download_dir(modlist_dir)

        if not download_dir or not download_dir.exists():
            self._set_status(
                f"Download directory not found for {modlist['name']}. "
                "Run Configure for this modlist first.",
                error=True,
            )
            return

        token, method = self._get_auth()
        if not token:
            self._set_status(
                "Not logged in to Nexus. Please log in via Settings > Nexus Authentication.",
                error=True,
            )
            return

        self._set_downloading(True)
        self._thread = _DownloadThread(self.nxm, download_dir, token, method, self)
        self._thread.progress.connect(self._on_progress)
        self._thread.finished.connect(self._on_download_finished)
        self._thread.start()

    def _get_auth(self) -> Tuple[Optional[str], str]:
        """Return (token, auth_method). auth_method is 'oauth' or 'api_key'."""
        try:
            from jackify.backend.services.nexus_auth_service import NexusAuthService
            svc = NexusAuthService()
            token = svc.get_auth_token()
            method = svc.get_auth_method() or "api_key"
            if token:
                return token, method
        except Exception as e:
            logger.warning("NexusAuthService unavailable: %s", e)
        try:
            from jackify.backend.services.api_key_service import APIKeyService
            key = APIKeyService().get_saved_api_key()
            if key:
                return key, "api_key"
        except Exception as e:
            logger.warning("APIKeyService unavailable: %s", e)
        return None, "api_key"

    def _on_progress(self, downloaded: int, total: int) -> None:
        if total > 0:
            self._progress_bar.setValue(int(downloaded * 100 / total))

    def _on_download_finished(self, success: bool, message: str) -> None:
        self._set_downloading(False)
        self._thread = None
        if success:
            self._set_status("Download complete. MO2 will pick it up automatically.", error=False)
            QTimer.singleShot(3000, self.accept)
        else:
            self._set_status(f"Download failed: {message}", error=True)

    def _set_downloading(self, active: bool) -> None:
        self._download_btn.setEnabled(not active)
        self._cancel_btn.setEnabled(not active)
        if hasattr(self, "_list"):
            self._list.setEnabled(not active)
        self._progress_bar.setVisible(active)
        self._progress_bar.setValue(0)
        if active:
            self._set_status("Downloading...", error=False)

    def _set_status(self, text: str, error: bool = False) -> None:
        self._status_label.setText(text)
        self._status_label.setVisible(bool(text))
        colour = _ERROR if error else JACKIFY_COLOR_BLUE
        self._status_label.setStyleSheet(f"color: {colour};")


def show_no_modlists_error() -> None:
    """Show a standalone error when no modlists are found."""
    from PySide6.QtWidgets import QMessageBox
    msg = QMessageBox()
    msg.setWindowTitle("Jackify - NXM Handler")
    msg.setIcon(QMessageBox.Warning)
    msg.setText(
        "No installed modlists found.\n\n"
        "NXM download handling requires at least one modlist that has been "
        "installed and configured with Jackify."
    )
    msg.exec()
