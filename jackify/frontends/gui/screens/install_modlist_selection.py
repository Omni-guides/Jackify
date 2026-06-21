"""Modlist selection methods for InstallModlistScreen (Mixin)."""
from pathlib import Path
from PySide6.QtWidgets import QMessageBox, QApplication, QDialog
from jackify.frontends.gui.utils import browse_directory, browse_file
from PySide6.QtCore import QTimer, Qt
import logging
import os
import re
# Runtime imports to avoid circular dependencies
from .install_modlist_dialogs import SelectionDialog, ModlistFetchThread  # Runtime import
from jackify.frontends.gui.screens.modlist_gallery import ModlistGalleryDialog  # Runtime import

logger = logging.getLogger(__name__)


class ModlistSelectionMixin:
    """Mixin providing modlist selection methods for InstallModlistScreen."""

    def open_game_type_dialog(self):
        dlg = SelectionDialog("Select Game Type", self.game_types, self, show_search=False)
        if dlg.exec() == QDialog.Accepted and dlg.selected_item:
            self.game_type_btn.setText(dlg.selected_item)
            # Store game type for gallery filter
            self.current_game_type = dlg.selected_item
            # Enable modlist button immediately - gallery will fetch its own data
            self.modlist_btn.setEnabled(True)
            self.modlist_btn.setText("Select Modlist")
            # No need to fetch modlists here - gallery does it when opened

    def fetch_modlists_for_game_type(self, game_type):
        self.current_game_type = game_type  # Store for display formatting
        self.modlist_btn.setText("Fetching modlists...")
        self.modlist_btn.setEnabled(False)
        game_type_map = {
            "Skyrim": "skyrim",
            "Fallout 4": "fallout4",
            "Fallout New Vegas": "falloutnv",
            "Oblivion": "oblivion",
            "Starfield": "starfield",
            "Oblivion Remastered": "oblivion_remastered",
            "Enderal": "enderal",
            "Skyrim VR": "skyrimvr",
            "Fallout 4 VR": "fallout4vr",
            "Baldur's Gate 3": "bg3",
            "Other": "other"
        }
        cli_game_type = game_type_map.get(game_type, "other")
        log_path = self.modlist_log_path
        # Use backend service directly - NO CLI CALLS
        self.fetch_thread = ModlistFetchThread(
            cli_game_type, log_path, mode='list-modlists')
        self.fetch_thread.result.connect(self.on_modlists_fetched)
        self.fetch_thread.start()

    def on_modlists_fetched(self, modlist_infos, error):
        # Handle the case where modlist_infos might be strings (backward compatibility)
        if modlist_infos and isinstance(modlist_infos[0], str):
            filtered = [m for m in modlist_infos if m and not m.startswith('DEBUG:')]
            self.current_modlists = filtered
            self.current_modlist_display = filtered
        else:
            # New format - full modlist objects with enhanced metadata
            filtered_modlists = [m for m in modlist_infos if m and hasattr(m, 'id')]
            filtered = filtered_modlists  # Set filtered for the condition check below
            self.current_modlists = [m.id for m in filtered_modlists]  # Keep IDs for selection
            
            # Create enhanced display strings with size info and status indicators
            display_strings = []
            for modlist in filtered_modlists:
                # Get enhanced metadata
                download_size = getattr(modlist, 'download_size', '')
                install_size = getattr(modlist, 'install_size', '')
                total_size = getattr(modlist, 'total_size', '')
                status_down = getattr(modlist, 'status_down', False)
                status_nsfw = getattr(modlist, 'status_nsfw', False)
                
                # Format display string without redundant game type: "Modlist Name - Download|Install|Total"
                # For "Other" category, include game type in brackets for clarity
                # Use padding to create alignment: left-aligned name, right-aligned sizes
                if hasattr(self, 'current_game_type') and self.current_game_type == "Other":
                    name_part = f"{modlist.name} [{modlist.game}]"
                else:
                    name_part = modlist.name
                size_part = f"{download_size}|{install_size}|{total_size}"
                
                # Create aligned display using string formatting (approximate alignment)
                display_str = f"{name_part:<50} {size_part:>15}"
                
                # Add status indicators at the beginning if present
                if status_down or status_nsfw:
                    status_parts = []
                    if status_down:
                        status_parts.append("[DOWN]")
                    if status_nsfw:
                        status_parts.append("[NSFW]") 
                    display_str = " ".join(status_parts) + " " + display_str
                
                display_strings.append(display_str)
            
            self.current_modlist_display = display_strings
        
        # Create mapping from display string back to modlist ID for selection
        self._modlist_id_map = {}
        if len(self.current_modlist_display) == len(self.current_modlists):
            self._modlist_id_map = {display: modlist_id for display, modlist_id in 
                                  zip(self.current_modlist_display, self.current_modlists)}
        else:
            # Fallback for backward compatibility
            self._modlist_id_map = {mid: mid for mid in self.current_modlists}
        if error:
            self.modlist_btn.setText("Error fetching modlists.")
            self.modlist_btn.setEnabled(False)
            # Don't write to log file before workflow starts - just show error in UI
        elif filtered:
            self.modlist_btn.setText("Select Modlist")
            self.modlist_btn.setEnabled(True)
        else:
            self.modlist_btn.setText("No modlists found.")
            self.modlist_btn.setEnabled(False)

    def open_modlist_dialog(self):
        # CRITICAL: Prevent opening gallery without game type selected
        # Prevent engine path resolution / subprocess issues
        if not hasattr(self, 'current_game_type') or not self.current_game_type:
            QMessageBox.warning(
                self,
                "Game Type Required",
                "Please select a game type before opening the modlist gallery."
            )
            return
        
        self.modlist_btn.setEnabled(False)
        cursor_overridden = False
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            cursor_overridden = True

            game_type_to_human_friendly = {
                "Skyrim": "Skyrim Special Edition",
                "Fallout 4": "Fallout 4",
                "Fallout New Vegas": "Fallout New Vegas",
                "Oblivion": "Oblivion",
                "Starfield": "Starfield",
                "Oblivion Remastered": "Oblivion",
                "Enderal": "Enderal Special Edition",
                "Skyrim VR": "Skyrim VR",
                "Fallout 4 VR": "Fallout 4 VR",
                "Baldur's Gate 3": "Baldur's Gate 3",
                "Other": None
            }

            game_filter = None
            if hasattr(self, 'current_game_type'):
                game_filter = game_type_to_human_friendly.get(self.current_game_type)

            self._gallery_dlg = ModlistGalleryDialog(game_filter=game_filter, parent=self)
            if cursor_overridden:
                QApplication.restoreOverrideCursor()
                cursor_overridden = False

            if self._gallery_dlg.exec() == QDialog.Accepted and self._gallery_dlg.selected_metadata:
                metadata = self._gallery_dlg.selected_metadata
                self.modlist_btn.setText(metadata.title)
                self.selected_modlist_info = {
                    'machine_url': metadata.namespacedName,
                    'title': metadata.title,
                    'author': metadata.author,
                    'game': metadata.gameHumanFriendly,
                    'description': metadata.description,
                    'nsfw': metadata.nsfw,
                    'force_down': metadata.forceDown,
                    'readme_url': metadata.links.readme if metadata.links else None,
                    'download_url': metadata.links.download if metadata.links else None,
                }
                self.modlist_name_edit.setText(metadata.title)

                # Auto-append modlist name to install directory
                base_install_dir = self.config_handler.get_modlist_install_base_dir()
                if base_install_dir:
                    # Sanitize modlist title for filesystem use
                    safe_title = re.sub(r'[<>:"/\\|?*]', '', metadata.title)
                    safe_title = safe_title.strip()
                    modlist_install_path = os.path.join(base_install_dir, safe_title)
                    self.install_dir_edit.setText(modlist_install_path)
        finally:
            if cursor_overridden:
                QApplication.restoreOverrideCursor()
            self.modlist_btn.setEnabled(True)

    def browse_wabbajack_file(self):
        file = browse_file(self, "Select .wabbajack File", os.path.expanduser("~"), "Wabbajack Files (*.wabbajack)")
        if file:
            self.file_edit.setText(file)

    def browse_install_dir(self):
        dir = browse_directory(self, "Select Install Directory", self.install_dir_edit.text())
        if dir:
            self.install_dir_edit.setText(dir)

    def browse_downloads_dir(self):
        dir = browse_directory(self, "Select Downloads Directory", self.downloads_dir_edit.text())
        if dir:
            self.downloads_dir_edit.setText(dir)

