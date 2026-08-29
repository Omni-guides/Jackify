"""
Tools Hub screen.

Manages independently-versioned engines and tools. On each show, the tool list
is rebuilt from the effective definitions (remote manifest if fetched, else
baked-in). A background thread fetches the manifest; if the tool list changes
the cards are rebuilt and version checks restart.
"""

import logging
from typing import Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from jackify.backend.services.tool_registry import (
    ToolDefinition, ToolRegistry, ToolStatus,
    apply_remote_manifest, get_active_engine_id, get_effective_definitions,
)
from jackify.frontends.gui.mixins.thread_lifecycle_mixin import ThreadLifecycleMixin
from jackify.frontends.gui.screens.modlist_dashboard_card import CARD_WIDTH
from jackify.frontends.gui.screens.tools_hub_card import ToolCard, btn_style, section_header
from jackify.frontends.gui.screens.tools_hub_threads import (
    ArchiveInstallThread, IconFetchThread, ManifestFetchThread,
    ReleaseFetchThread, ToolActionThread, VersionCheckThread,
)
from jackify.frontends.gui.services.message_service import MessageService
from jackify.frontends.gui.shared_theme import (
    COLOR_BTN_BACK as _C_BACK,
    COLOR_BTN_INSTALL as _C_INSTALL,
    COLOR_BTN_UPDATE as _C_UPDATE,
)
from jackify.frontends.gui.utils import set_responsive_minimum

logger = logging.getLogger(__name__)


# -- main screen -------------------------------------------------------------
class ToolsHubScreen(ThreadLifecycleMixin, QWidget):
    """Tools Hub: engine selection and third-party tool management."""

    def __init__(self, stacked_widget=None, ttw_screen_index: int = 5, parent=None):
        super().__init__(parent)
        self.stacked_widget = stacked_widget
        self.ttw_screen_index = ttw_screen_index

        self._cards: Dict[str, ToolCard] = {}
        self._action_thread: Optional[ToolActionThread] = None
        self._version_thread: Optional[VersionCheckThread] = None
        self._manifest_thread: Optional[ManifestFetchThread] = None
        self._release_thread: Optional[ReleaseFetchThread] = None
        self._icon_thread: Optional[IconFetchThread] = None
        self._active_engine_id = get_active_engine_id()

        self._setup_ui()

    def _setup_ui(self):
        root = QVBoxLayout()
        root.setContentsMargins(30, 24, 30, 24)
        root.setSpacing(0)
        self.setLayout(root)

        # Lives in the persistent header's tab row (next to the Tools Hub tab), not in this
        # screen's own body - see main_window_ui.py's _make_third_party_tools_screen and
        # modlist_dashboard_tabs.py's action slot. Built here because it's this screen's own
        # state machine (enable/disable/style) that drives it.
        self.update_all_button = QPushButton("Update All")
        self.update_all_button.setFixedSize(150, 30)
        self.update_all_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.update_all_button.setStyleSheet(btn_style(_C_UPDATE, disabled=True, width=134))
        self.update_all_button.setEnabled(False)
        self.update_all_button.clicked.connect(self._on_update_all)

        disclaimer = QLabel(
            "Some of these tools are developed and maintained by their respective authors, "
            "independently of Jackify. Jackify provides download and update management "
            "as a convenience only. The Jackify project offers no warranty or support "
            "for third-party tools."
        )
        disclaimer.setWordWrap(True)
        disclaimer.setStyleSheet("color: #aaa; font-size: 12px;")
        root.addWidget(disclaimer)

        root.addSpacing(12)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._list_widget = QWidget()
        self._list_widget.setStyleSheet("background: transparent;")
        self._list_layout = QVBoxLayout()
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(6)
        self._list_widget.setLayout(self._list_layout)

        # Engine and Tools side by side rather than stacked - with only a couple of cards per
        # section today, a full-width stack is mostly wasted vertical space. Each column gets
        # its own responsive grid so this still holds up as more tools are added.
        columns_row = QHBoxLayout()
        columns_row.setSpacing(24)

        engine_col = QVBoxLayout()
        engine_col.setSpacing(4)
        self._engine_header = section_header("Engine")
        engine_col.addWidget(self._engine_header)
        self._engine_grid = QGridLayout()
        self._engine_grid.setSpacing(10)
        self._engine_grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        engine_col.addLayout(self._engine_grid)
        engine_col.addStretch(1)
        columns_row.addLayout(engine_col, stretch=1)

        tools_col = QVBoxLayout()
        tools_col.setSpacing(4)
        self._tools_header = section_header("Tools")
        tools_col.addWidget(self._tools_header)
        self._tools_grid = QGridLayout()
        self._tools_grid.setSpacing(10)
        self._tools_grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        tools_col.addLayout(self._tools_grid)
        tools_col.addStretch(1)
        columns_row.addLayout(tools_col, stretch=1)

        self._list_layout.addLayout(columns_row)
        self._list_layout.addSpacing(10)

        self._placeholder_label = QLabel("More tools coming soon")
        self._placeholder_label.setAlignment(Qt.AlignCenter)
        self._placeholder_label.setStyleSheet(
            "color: #555; font-size: 12px; font-style: italic; "
            "background-color: #222; border: 1px dashed #333; "
            "border-radius: 6px; padding: 10px;"
        )
        self._list_layout.addWidget(self._placeholder_label)
        self._list_layout.addStretch()

        self._scroll_area = scroll
        scroll.setWidget(self._list_widget)
        root.addWidget(scroll, stretch=1)

    # card list management

    def _rebuild_card_list(self):
        for grid in (self._engine_grid, self._tools_grid):
            while grid.count():
                item = grid.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
        self._cards.clear()

        statuses = ToolRegistry().get_all_statuses()
        engines = [s for s in statuses if s.definition.is_engine]
        tools   = [s for s in statuses if not s.definition.is_engine]

        self._engine_header.setVisible(bool(engines))
        for s in engines:
            self._add_card(s, self._engine_grid)
        self._lay_out_grid(self._engine_grid)

        self._tools_header.setVisible(bool(tools))
        for s in tools:
            self._add_card(s, self._tools_grid)
        self._lay_out_grid(self._tools_grid)

        self._start_icon_fetch()

    def _add_card(self, status: ToolStatus, grid: QGridLayout):
        card = ToolCard(status, self._active_engine_id)
        card.action_requested.connect(self._on_action)
        card.engine_activated.connect(self._on_engine_activated)
        self._cards[status.definition.tool_id] = card
        grid.addWidget(card)  # position assigned in _lay_out_grid

    def _lay_out_grid(self, grid: QGridLayout) -> None:
        """Responsive column count based on available width - same approach the Dashboard
        uses for its own card grid, but scoped to this column's half of the screen rather
        than the whole viewport since Engine and Tools now sit side by side."""
        available_width = self._scroll_area.viewport().width() // 2 - 12
        if available_width <= 0:
            available_width = self.width() // 2 - 60
        if available_width <= 0:
            available_width = 400
        spacing = grid.spacing()
        columns = max(1, (available_width + spacing) // (CARD_WIDTH + spacing))
        columns = min(columns, 5)

        widgets = [grid.itemAt(i).widget() for i in range(grid.count())]
        for item in list(widgets):
            grid.removeWidget(item)
        for i, widget in enumerate(widgets):
            row, col = divmod(i, columns)
            grid.addWidget(widget, row, col)
        for col in range(columns):
            grid.setColumnStretch(col, 0)
        if columns < 5:
            grid.setColumnStretch(columns, 1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_engine_grid"):
            self._lay_out_grid(self._engine_grid)
            self._lay_out_grid(self._tools_grid)

    # show / manifest / version check

    def showEvent(self, event):
        super().showEvent(event)
        try:
            mw = self.window()
            if mw:
                set_responsive_minimum(mw, min_width=960, min_height=520)
        except Exception:
            pass
        self._active_engine_id = get_active_engine_id()
        self._rebuild_card_list()
        self._start_manifest_fetch()
        self._start_version_check()

    def _start_icon_fetch(self):
        if self._icon_thread and self._icon_thread.isRunning():
            return
        from jackify.backend.services.tool_icons import get_cached_icon_path
        targets = [
            (tool_id, card._status.definition.github_repo)
            for tool_id, card in self._cards.items()
            if tool_id != "jackify-engine"
            and card._status.definition.is_engine
            and card._status.definition.github_repo
            and not get_cached_icon_path(tool_id)
        ]
        if not targets:
            return
        self._icon_thread = IconFetchThread(targets)
        self._icon_thread.icon_ready.connect(self._on_icon_ready)
        self._icon_thread.start()

    def _on_icon_ready(self, tool_id: str, path) -> None:
        card = self._cards.get(tool_id)
        if card:
            card.set_icon_pixmap(path)

    def _start_manifest_fetch(self):
        if self._manifest_thread and self._manifest_thread.isRunning():
            return
        self._manifest_thread = ManifestFetchThread()
        self._manifest_thread.manifest_ready.connect(self._on_manifest_ready)
        self._manifest_thread.start()

    def _on_manifest_ready(self, definitions: List[ToolDefinition]):
        current_ids = set(self._cards.keys())
        new_ids = {d.tool_id for d in definitions if not d.hidden}
        apply_remote_manifest(definitions)
        if current_ids != new_ids:
            if self._version_thread and self._version_thread.isRunning():
                self._version_thread.quit()
            self._rebuild_card_list()
            self._start_version_check()

    def _start_version_check(self):
        if self._version_thread and self._version_thread.isRunning():
            return
        self._version_thread = VersionCheckThread()
        self._version_thread.version_ready.connect(self._on_version_ready)
        self._version_thread.start()

    def _on_version_ready(self, tool_id: str, tag: str):
        card = self._cards.get(tool_id)
        if card:
            has_update = card.set_latest_version(tag)
            if has_update:
                self.update_all_button.setEnabled(True)
                self.update_all_button.setStyleSheet(btn_style(_C_UPDATE, width=134))
        any_updates = any(c._status.update_available for c in self._cards.values())
        self._notify_tab_bar(any_updates)

    def _notify_tab_bar(self, has_updates: bool) -> None:
        """Highlight the persistent "Tools Hub" tab when an update is available, so the
        indicator is visible even while viewing Modlists or Additional Tasks."""
        try:
            header = getattr(self.window(), "_app_header", None)
            if header and self.stacked_widget:
                header.set_needs_attention(self.stacked_widget.indexOf(self), has_updates)
        except Exception:
            pass

    # engine activation

    def _on_engine_activated(self, tool_id: str):
        self._active_engine_id = tool_id
        for card in self._cards.values():
            card.set_active_engine(tool_id)
        card = self._cards.get(tool_id)
        name = card._status.definition.display_name if card else tool_id
        MessageService.information(self, "Engine Changed", f"{name} is now the active engine.")

    # action dispatch

    def _on_action(self, tool_id: str, action: str):
        if action == "launch_jackify_ui":
            if self.stacked_widget:
                self.stacked_widget.setCurrentIndex(self.ttw_screen_index)
                ttw_screen = self.stacked_widget.widget(self.ttw_screen_index)
                if hasattr(ttw_screen, 'main_menu_index'):
                    ttw_screen.main_menu_index = self.stacked_widget.indexOf(self)
            return
        if self._action_thread and self._action_thread.isRunning():
            MessageService.information(self, "Busy", "Another operation is running. Please wait.")
            return

        if action == "downgrade":
            self._start_downgrade_flow(tool_id)
            return

        card = self._cards.get(tool_id)
        if card:
            label_map = {
                "install": "Installing...", "update": "Updating...", "uninstall": "Removing...",
            }
            card.set_busy(True, label_map.get(action, "Working..."))
        self._action_thread = ToolActionThread(tool_id, action)
        self._action_thread.finished_signal.connect(self._on_action_finished)
        self._action_thread.start()

    def _on_action_finished(self, tool_id: str, success: bool, message: str):
        self._action_thread = None
        card = self._cards.get(tool_id)

        if not success and message.startswith("NEXUS_MANUAL_REQUIRED:"):
            if card:
                card.set_busy(False)
            self._start_nexus_manual_install(tool_id, message[len("NEXUS_MANUAL_REQUIRED:"):])
            return

        if success:
            status = ToolRegistry().get_status(tool_id)
            if status and status.installed and card:
                card.mark_installed(status.installed_version or "")
                if status.latest_version:
                    card.set_latest_version(status.latest_version)
            elif card:
                card.mark_uninstalled()
            self._notify_tab_bar(any(c._status.update_available for c in self._cards.values()))
            if message:
                MessageService.information(self, "Done", message)
        else:
            if card:
                card.set_busy(False)
            MessageService.warning(self, "Failed", message)

    def _start_nexus_manual_install(self, tool_id: str, nexus_url: str) -> None:
        from jackify.frontends.gui.dialogs.nexus_manual_install_dialog import NexusManualInstallDialog
        defn = next((d for d in get_effective_definitions() if d.tool_id == tool_id), None)
        display_name = defn.display_name if defn else tool_id
        dlg = NexusManualInstallDialog(tool_id, display_name, nexus_url, parent=self)
        if dlg.exec() != NexusManualInstallDialog.Accepted:
            return
        archive = dlg.selected_archive
        if not archive:
            return
        card = self._cards.get(tool_id)
        if card:
            card.set_busy(True, "Installing...")
        self._action_thread = ArchiveInstallThread(tool_id, archive)
        self._action_thread.finished_signal.connect(self._on_action_finished)
        self._action_thread.start()

    def _on_update_all(self):
        updates = [tid for tid, card in self._cards.items()
                   if card._status.installed and card._status.update_available]
        if not updates:
            return
        names = ", ".join(self._cards[tid]._status.definition.display_name for tid in updates)
        if MessageService.question(self, "Update All", f"Update the following tools?\n\n{names}") != QMessageBox.Yes:
            return
        self._pending_updates: List[str] = updates
        self._run_next_update()

    def _run_next_update(self):
        if not self._pending_updates:
            return
        tool_id = self._pending_updates.pop(0)
        card = self._cards.get(tool_id)
        if card:
            card.set_busy(True, "Updating...")
        self._action_thread = ToolActionThread(tool_id, "update")
        self._action_thread.finished_signal.connect(self._on_update_all_step)
        self._action_thread.start()

    def _on_update_all_step(self, tool_id: str, success: bool, message: str):
        self._action_thread = None
        self._on_action_finished(tool_id, success, message if not success else "")
        if getattr(self, "_pending_updates", []):
            self._run_next_update()
        else:
            any_remaining = any(c._status.installed and c._status.update_available for c in self._cards.values())
            self.update_all_button.setEnabled(any_remaining)
            if not any_remaining:
                self.update_all_button.setStyleSheet(btn_style(_C_UPDATE, disabled=True, width=134))

    def _start_downgrade_flow(self, tool_id: str):
        card = self._cards.get(tool_id)
        status = ToolRegistry().get_status(tool_id)
        if not status:
            return
        if not status.definition.github_repo:
            MessageService.warning(self, "Change Version", "Version selection is only available for GitHub-hosted tools.")
            return
        if card:
            card.set_busy(True, "Fetching releases...")
        self._release_thread = ReleaseFetchThread(tool_id, status.definition.github_repo)
        self._release_thread.releases_ready.connect(self._on_releases_ready)
        self._release_thread.start()

    def _on_releases_ready(self, tool_id: str, releases: list):
        card = self._cards.get(tool_id)
        if card:
            card.set_busy(False)
        if not releases:
            MessageService.warning(self, "Change Version", "Could not fetch release list from GitHub.")
            return
        status = ToolRegistry().get_status(tool_id)
        current = status.installed_version if status else None
        version = self._show_version_picker(tool_id, releases, current)
        if not version:
            return
        if card:
            card.set_busy(True, "Changing version...")
        self._action_thread = ToolActionThread(tool_id, "install", version=version)
        self._action_thread.finished_signal.connect(self._on_action_finished)
        self._action_thread.start()

    def _show_version_picker(self, tool_id: str, releases: list, current_version: Optional[str]) -> Optional[str]:
        dlg = QDialog(self.window())
        dlg.setWindowTitle("Select Version")
        dlg.setWindowModality(Qt.ApplicationModal)
        dlg.setMinimumWidth(360)
        dlg.setStyleSheet(
            "QDialog { background-color: #232323; color: #e0e0e0; }"
            "QLabel { color: #e0e0e0; background: transparent; border: none; }"
            "QComboBox { background-color: #2a2a2a; color: #e0e0e0; border: 1px solid #444; "
            "            border-radius: 4px; padding: 4px 8px; }"
            "QComboBox QAbstractItemView { background-color: #2a2a2a; color: #e0e0e0; "
            "                              selection-background-color: #3a3a3a; }"
        )
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        if current_version:
            lbl = QLabel(f"Currently installed: <b>{current_version}</b>")
            lbl.setTextFormat(Qt.RichText)
            layout.addWidget(lbl)
        combo = QComboBox()
        for rel in releases:
            tag = rel.get("tag_name") or rel.get("name", "")
            date = (rel.get("published_at") or "")[:10]
            combo.addItem(f"{tag}  ({date})", userData=tag)
        layout.addWidget(combo)
        sep = QLabel()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: #3a3a3a; border: none;")
        layout.addWidget(sep)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedSize(90, 30)
        cancel_btn.setStyleSheet(btn_style(_C_BACK, width=90))
        cancel_btn.clicked.connect(dlg.reject)
        btn_row.addWidget(cancel_btn)
        install_btn = QPushButton("Install")
        install_btn.setFixedSize(90, 30)
        install_btn.setStyleSheet(btn_style(_C_INSTALL, width=90))
        install_btn.setDefault(True)
        install_btn.clicked.connect(dlg.accept)
        btn_row.addWidget(install_btn)
        layout.addLayout(btn_row)
        if dlg.exec() != QDialog.Accepted:
            return None
        return combo.currentData()

