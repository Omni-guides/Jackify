"""Prompt-and-install flow for a Tools Hub-managed tool, usable from anywhere a workflow
discovers it needs a tool it can't proceed without (e.g. CLF3 as the selected engine, or TTW
Linux Installer for an FNV modlist). Reuses ToolRegistry().install() - the exact same call
Tools Hub itself makes - so the outcome (Nexus Premium auto-download, or the manual-download
dialog for everyone else) is identical no matter where the prompt was triggered from.
"""

from typing import Tuple

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QProgressBar, QMessageBox

from jackify.frontends.gui.shared_theme import JACKIFY_COLOR_BLUE

_NEXUS_MANUAL_PREFIX = "NEXUS_MANUAL_REQUIRED:"
_NEXUS_LOGIN_REQUIRED = "NEXUS_LOGIN_REQUIRED"


class _ToolInstallThread(QThread):
    finished_signal = Signal(bool, str)

    def __init__(self, tool_id: str):
        super().__init__()
        self._tool_id = tool_id

    def run(self):
        from jackify.backend.services.tool_registry import ToolRegistry
        try:
            ok, msg = ToolRegistry().install(self._tool_id)
        except Exception as exc:
            ok, msg = False, str(exc)
        self.finished_signal.emit(ok, msg)


def _run_install_dialog(parent, tool_id: str, display_name: str) -> Tuple[bool, str]:
    """Modal progress dialog around ToolRegistry().install(tool_id). Returns (ok, message)."""
    dlg = QDialog(parent)
    dlg.setWindowTitle(f"Installing {display_name}")
    dlg.setModal(True)
    dlg.setMinimumWidth(360)
    layout = QVBoxLayout(dlg)
    layout.setSpacing(12)
    layout.setContentsMargins(16, 16, 16, 16)

    label = QLabel(f"Downloading {display_name}...")
    label.setStyleSheet("color: #ccc; font-size: 13px;")
    layout.addWidget(label)

    bar = QProgressBar()
    bar.setRange(0, 0)
    bar.setTextVisible(False)
    bar.setFixedHeight(6)
    bar.setStyleSheet(f"""
        QProgressBar {{ border: none; background-color: #333; border-radius: 3px; }}
        QProgressBar::chunk {{ background-color: {JACKIFY_COLOR_BLUE}; border-radius: 3px; }}
    """)
    layout.addWidget(bar)

    result = [False, ""]
    thread = _ToolInstallThread(tool_id)

    def on_done(ok: bool, msg: str):
        result[0] = ok
        result[1] = msg
        dlg.accept()

    thread.finished_signal.connect(on_done)
    thread.start()
    dlg.exec()
    thread.wait(5000)
    return result[0], result[1]


def _run_manual_nexus_dialog(parent, tool_id: str, display_name: str, nexus_url: str) -> bool:
    """Same guided manual-download dialog Tools Hub shows for a Nexus-only tool without Premium."""
    from jackify.frontends.gui.dialogs.nexus_manual_install_dialog import NexusManualInstallDialog
    from jackify.frontends.gui.screens.tools_hub_threads import ArchiveInstallThread

    dlg = NexusManualInstallDialog(tool_id, display_name, nexus_url, parent=parent)
    if dlg.exec() != QDialog.Accepted or not dlg.selected_archive:
        return False

    result = [False, ""]
    thread = ArchiveInstallThread(tool_id, dlg.selected_archive)

    def on_done(_tool_id: str, ok: bool, msg: str):
        result[0] = ok
        result[1] = msg

    thread.finished_signal.connect(on_done)
    thread.start()
    thread.wait(30000)

    if not result[0]:
        QMessageBox.critical(parent, f"{display_name} Install Failed", result[1] or "Install failed")
    return result[0]


def ensure_tool_installed(parent, tool_id: str, display_name: str) -> bool:
    """If tool_id is already installed, return True. Otherwise prompt to install it now via
    the same path Tools Hub uses, and return whether it ended up installed."""
    from jackify.backend.services.tool_registry import ToolRegistry

    status = ToolRegistry().get_status(tool_id)
    if status and status.installed:
        return True

    reply = QMessageBox.question(
        parent,
        f"{display_name} Not Installed",
        f"{display_name} is not installed.\n\nDownload and install it now to continue?",
        QMessageBox.Yes | QMessageBox.No,
    )
    if reply != QMessageBox.Yes:
        return False

    ok, msg = _run_install_dialog(parent, tool_id, display_name)
    if ok:
        return True

    if msg.startswith(_NEXUS_MANUAL_PREFIX):
        nexus_url = msg[len(_NEXUS_MANUAL_PREFIX):]
        return _run_manual_nexus_dialog(parent, tool_id, display_name, nexus_url)

    if msg == _NEXUS_LOGIN_REQUIRED:
        QMessageBox.warning(
            parent, "Nexus Login Required",
            "You are not logged into Nexus Mods. Open Settings and connect your Nexus Mods "
            "account, then try again.",
        )
        return False

    QMessageBox.critical(parent, f"{display_name} Install Failed", f"Could not install {display_name}:\n\n{msg}")
    return False
