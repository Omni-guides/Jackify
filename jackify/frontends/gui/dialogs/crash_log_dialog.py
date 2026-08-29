"""Crash log browser: pick a modlist, then pick one of its crash logs.

The script extender log directory holds every plugin's log, so listing matched crash
logs here saves the user picking them out of a folder of a hundred-odd files.
"""

import datetime
import logging
from typing import Dict, List, Optional

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from jackify.backend.services.crash_log_service import (
    CrashLog,
    find_modlists_with_crash_logs,
    get_crash_log_dir,
    list_crash_logs,
    open_path,
)

logger = logging.getLogger(__name__)

_ENTRY_ROLE = 1000


def browse_crash_logs(parent) -> None:
    """Entry point for the Additional Tasks menu item."""
    from ..services.message_service import MessageService

    try:
        modlists = find_modlists_with_crash_logs()
    except Exception as e:
        logger.error("Crash log discovery failed: %s", e, exc_info=True)
        MessageService.critical(parent, "Crash Logs", f"Could not scan for modlists: {e}")
        return

    if not modlists:
        MessageService.information(
            parent,
            "No Modlists Found",
            "No installed modlists with crash log support were found.\n\n"
            "Crash log browsing currently covers Skyrim Special Edition and Fallout 4 "
            "modlists with an existing Steam prefix.",
        )
        return

    # Always ask, even with a single eligible modlist - matches the Install Verifier's
    # picker (additional_tasks.py::_run_install_verifier), and the answer isn't obvious
    # to the user from the menu item alone once a second modlist becomes eligible.
    entry = _pick_modlist(parent, modlists)
    if entry is None:
        return

    _show_logs_for(parent, entry)


def _pick_modlist(parent, modlists: List[Dict]) -> Optional[Dict]:
    dlg = QDialog(parent)
    dlg.setWindowTitle("Select Modlist")
    dlg.setMinimumWidth(480)
    dlg.setMinimumHeight(260)
    layout = QVBoxLayout(dlg)
    layout.addWidget(QLabel("Select a modlist to browse crash logs for:"))

    lw = QListWidget()
    for m in modlists:
        count = len(list_crash_logs(m.get("pfx"), m.get("game_type")))
        suffix = "no crash logs" if count == 0 else f"{count} crash log{'s' if count != 1 else ''}"
        item = QListWidgetItem(f"{m['name']}  ({suffix})")
        item.setData(_ENTRY_ROLE, m)
        lw.addItem(item)
    lw.setCurrentRow(0)
    layout.addWidget(lw)

    btn_row = QHBoxLayout()
    ok_btn = QPushButton("Select")
    cancel_btn = QPushButton("Cancel")
    btn_row.addStretch()
    btn_row.addWidget(ok_btn)
    btn_row.addWidget(cancel_btn)
    layout.addLayout(btn_row)

    ok_btn.clicked.connect(dlg.accept)
    cancel_btn.clicked.connect(dlg.reject)
    lw.itemDoubleClicked.connect(lambda _: dlg.accept())

    if dlg.exec() != QDialog.Accepted:
        return None
    current = lw.currentItem()
    return current.data(_ENTRY_ROLE) if current else None


def _show_logs_for(parent, entry: Dict) -> None:
    from ..services.message_service import MessageService

    pfx = entry.get("pfx")
    game_type = entry.get("game_type")
    logs = list_crash_logs(pfx, game_type)
    log_dir = get_crash_log_dir(pfx, game_type)

    if not logs:
        if log_dir and log_dir.is_dir():
            reply = MessageService.question(
                parent,
                "No Crash Logs",
                f"No crash logs found for '{entry['name']}'.\n\n"
                "That usually means the game has not crashed, or no crash logger is "
                "installed.\n\nOpen the script extender log folder anyway?",
                safety_level="low",
            )
            from PySide6.QtWidgets import QMessageBox
            if reply == QMessageBox.Yes:
                _open(parent, log_dir)
        else:
            MessageService.information(
                parent,
                "No Crash Logs",
                f"No script extender log folder was found for '{entry['name']}'.\n\n"
                f"Expected at:\n{log_dir}",
            )
        return

    _show_log_picker(parent, entry, logs, log_dir)


def _show_log_picker(parent, entry: Dict, logs: List[CrashLog], log_dir) -> None:
    dlg = QDialog(parent)
    dlg.setWindowTitle("Crash Logs")
    dlg.setMinimumWidth(520)
    dlg.setMinimumHeight(300)
    layout = QVBoxLayout(dlg)
    layout.addWidget(QLabel(f"Crash logs for '{entry['name']}' (newest first):"))

    lw = QListWidget()
    for log in logs:
        stamp = datetime.datetime.fromtimestamp(log.modified).strftime("%Y-%m-%d %H:%M")
        item = QListWidgetItem(f"{log.name}    {stamp}")
        item.setData(_ENTRY_ROLE, log)
        lw.addItem(item)
    lw.setCurrentRow(0)
    layout.addWidget(lw)

    btn_row = QHBoxLayout()
    open_log_btn = QPushButton("Open Log")
    open_folder_btn = QPushButton("Open Folder")
    close_btn = QPushButton("Close")
    btn_row.addStretch()
    btn_row.addWidget(open_log_btn)
    btn_row.addWidget(open_folder_btn)
    btn_row.addWidget(close_btn)
    layout.addLayout(btn_row)

    def _open_selected():
        current = lw.currentItem()
        if current:
            _open(dlg, current.data(_ENTRY_ROLE).path)

    open_log_btn.clicked.connect(_open_selected)
    open_folder_btn.clicked.connect(lambda: _open(dlg, log_dir))
    close_btn.clicked.connect(dlg.reject)
    lw.itemDoubleClicked.connect(lambda _: _open_selected())

    dlg.exec()


def _open(parent, target) -> None:
    from ..services.message_service import MessageService

    if not open_path(target):
        MessageService.warning(
            parent,
            "Could Not Open",
            f"Jackify could not open:\n{target}\n\n"
            "No system file handler responded. The path above can be opened manually.",
        )
