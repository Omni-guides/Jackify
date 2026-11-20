"""Confirmation for the dashboard's Remove from List action."""
from typing import Optional

from PySide6.QtWidgets import QCheckBox, QMessageBox, QWidget

from jackify.backend.services.install_registry import InstallEntry


def ask_remove_from_list(parent: QWidget, entry: InstallEntry) -> Optional[bool]:
    """None if cancelled, else whether to also delete the Steam shortcut and Proton prefix."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Question)
    box.setWindowTitle("Remove from List")
    box.setText(
        f"Remove \"{entry.modlist_name}\" from Jackify's tracked list?\n\n"
        f"The modlist files are left untouched. Use \"Add an Existing Modlist\" to bring it "
        f"back onto the Dashboard."
    )
    box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
    box.setDefaultButton(QMessageBox.No)
    tick = None
    if entry.appid:
        tick = QCheckBox("Also delete the Steam shortcut and Proton prefix")
        tick.setChecked(True)
        tick.setToolTip(
            "Saves and settings stored inside the Proton prefix are deleted with it. "
            "Steam is restarted, which closes any running game."
        )
        box.setCheckBox(tick)
    if box.exec() != QMessageBox.Yes:
        return None
    return bool(tick and tick.isChecked())
