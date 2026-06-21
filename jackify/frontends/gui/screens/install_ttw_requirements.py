"""TTW installer requirements and validation for InstallTTWScreen (Mixin)."""
import logging
from pathlib import Path
from typing import Dict, Optional, Tuple

from jackify.frontends.gui.services.message_service import MessageService

logger = logging.getLogger(__name__)

# Maps TTW-required game display names to Jackify game_type strings.
_TTW_GAMES = {
    'Fallout 3': 'fallout3',
    'Fallout New Vegas': 'falloutnv',
}


def _detect_ttw_games() -> Dict[str, Tuple[Path, str]]:
    """
    Return a dict of {display_name: (path, store)} for each TTW-required game found.
    Tries Steam appmanifests first, then Heroic (GOG/Epic).
    """
    from jackify.backend.handlers.vanilla_game_finder import VanillaGameFinder
    finder = VanillaGameFinder()
    results = {}
    for display_name, game_type in _TTW_GAMES.items():
        location = finder.find(game_type)
        if location:
            results[display_name] = location
    return results


class TTWRequirementsMixin:
    """Mixin providing TTW installer requirement checking and validation for InstallTTWScreen."""

    _ttw_installer_ready: bool = False

    def check_requirements(self):
        detected = _detect_ttw_games()

        for display_name, label_widget in (
            ('Fallout 3', self.fallout3_status),
            ('Fallout New Vegas', self.fnv_status),
        ):
            if display_name in detected:
                _, store = detected[display_name]
                store_label = {'steam': 'Steam', 'gog': 'GOG', 'epic': 'Epic'}.get(store, store)
                label_widget.setText(f"{display_name}: Detected ({store_label})")
                label_widget.setStyleSheet("color: #3fd0ea;")
            else:
                label_widget.setText(f"{display_name}: Not Found")
                label_widget.setStyleSheet("color: #f44336;")

        self._update_start_button_state()

    def _check_ttw_installer_status(self):
        status = None
        try:
            from jackify.backend.services.tool_registry import ToolRegistry
            status = ToolRegistry().get_status("ttw_installer")
            self._ttw_installer_ready = bool(status and status.installed)
        except Exception as e:
            logger.debug("TTW installer status check failed: %s", e)
            self._ttw_installer_ready = False

        if self._ttw_installer_ready:
            version_text = f"Ready (v{status.installed_version})" if status and status.installed_version else "Ready"
            self.ttw_installer_status.setText(version_text)
            self.ttw_installer_status.setStyleSheet("color: #3fd0ea;")
            self.ttw_installer_btn.setVisible(False)
        else:
            self.ttw_installer_status.setText("Not installed - install via Tools Hub")
            self.ttw_installer_status.setStyleSheet("color: #f44336;")
            self.ttw_installer_btn.setText("Open Tools Hub")
            self.ttw_installer_btn.setEnabled(True)
            self.ttw_installer_btn.setVisible(True)

        self._update_start_button_state()

    def install_ttw_installer(self):
        """Navigate to Tools Hub for TTW Linux Installer management."""
        if self.stacked_widget:
            self.stacked_widget.setCurrentIndex(10)

    def _check_ttw_requirements(self, silent: bool = False) -> bool:
        detected = _detect_ttw_games()
        missing = [name for name in _TTW_GAMES if name not in detected]

        if missing:
            if not silent:
                MessageService.warning(
                    self,
                    "Missing Required Games",
                    f"TTW requires both Fallout 3 and Fallout New Vegas to be installed.\n\n"
                    f"Not found: {', '.join(missing)}\n\n"
                    "Install via Steam, GOG (through Heroic), or another supported store."
                )
            return False

        if not self._ttw_installer_ready:
            if not silent:
                MessageService.warning(
                    self,
                    "TTW Linux Installer Required",
                    "TTW Linux Installer is not installed.\n\nInstall it from the Tools Hub before proceeding."
                )
            return False

        return True

    def _update_start_button_state(self):
        requirements_met = self._check_ttw_requirements(silent=True)
        mpi_file_selected = bool(self.file_edit.text().strip())
        self.start_btn.setEnabled(requirements_met and mpi_file_selected)
        if not requirements_met:
            self.start_btn.setText("Requirements Not Met")
        elif not mpi_file_selected:
            self.start_btn.setText("Select TTW .mpi File")
        else:
            self.start_btn.setText("Start Installation")
