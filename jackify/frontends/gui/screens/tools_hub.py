"""
Tools Hub screen.

Manages independently-versioned engines and tools. On each show, the tool list
is rebuilt from the effective definitions (remote manifest if fetched, else
baked-in). A background thread fetches the manifest; if the tool list changes
the cards are rebuilt and version checks restart.
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from jackify.backend.services.tool_registry import (
    ToolDefinition, ToolRegistry, ToolStatus,
    apply_remote_manifest, fetch_remote_manifest, fetch_release_list,
    get_active_engine_id, get_effective_definitions,
)
from jackify.frontends.gui.mixins.thread_lifecycle_mixin import ThreadLifecycleMixin
from jackify.frontends.gui.screens.tools_hub_card import ToolCard, btn_style, section_header
from jackify.frontends.gui.services.message_service import MessageService
from jackify.frontends.gui.shared_theme import JACKIFY_COLOR_BLUE
from jackify.frontends.gui.utils import set_responsive_minimum

logger = logging.getLogger(__name__)

_C_UPDATE   = "#4a5568"
_C_BACK     = "#4a5568"
_C_INSTALL  = "#1a5fa8"


# -- background threads ------------------------------------------------------
class _VersionCheckThread(QThread):
    version_ready = Signal(str, str)   # tool_id, latest_tag

    def run(self):
        registry = ToolRegistry()
        for defn in get_effective_definitions():
            try:
                tag = registry.check_latest_version(defn.tool_id)
                self.version_ready.emit(defn.tool_id, tag or "unknown")
            except Exception as e:
                logger.debug("Version check failed for %s: %s", defn.tool_id, e)
                self.version_ready.emit(defn.tool_id, "unknown")


class _ToolActionThread(QThread):
    finished_signal = Signal(str, bool, str)   # tool_id, success, message

    def __init__(self, tool_id: str, action: str, version: Optional[str] = None):
        super().__init__()
        self._tool_id = tool_id
        self._action = action
        self._version = version

    def run(self):
        registry = ToolRegistry()
        try:
            if self._action == "install":
                ok, msg = registry.install(self._tool_id, version=self._version)
            elif self._action == "update":
                ok, msg = registry.update(self._tool_id)
            elif self._action == "uninstall":
                ok, msg = registry.uninstall(self._tool_id)
            else:
                ok, msg = False, f"Unknown action: {self._action}"
        except Exception as e:
            ok, msg = False, str(e)
        self.finished_signal.emit(self._tool_id, ok, msg)


class _ArchiveInstallThread(QThread):
    finished_signal = Signal(str, bool, str)   # tool_id, success, message

    def __init__(self, tool_id: str, archive_path: Path):
        super().__init__()
        self._tool_id = tool_id
        self._archive_path = archive_path

    def run(self):
        try:
            ok, msg = ToolRegistry().install_from_archive(self._tool_id, self._archive_path)
        except Exception as e:
            ok, msg = False, str(e)
        self.finished_signal.emit(self._tool_id, ok, msg)


class _ManifestFetchThread(QThread):
    manifest_ready = Signal(list)   # List[ToolDefinition]

    def run(self):
        result = fetch_remote_manifest()
        if result:
            self.manifest_ready.emit(result)


class _ReleaseFetchThread(QThread):
    releases_ready = Signal(str, list)   # tool_id, List[dict]

    def __init__(self, tool_id: str, github_repo: str):
        super().__init__()
        self._tool_id = tool_id
        self._github_repo = github_repo

    def run(self):
        releases = fetch_release_list(self._github_repo)
        self.releases_ready.emit(self._tool_id, releases)


# -- main screen -------------------------------------------------------------
class ToolsHubScreen(ThreadLifecycleMixin, QWidget):
    """Tools Hub: engine selection and third-party tool management."""

    def __init__(self, stacked_widget=None, main_menu_index: int = 0, ttw_screen_index: int = 5, parent=None):
        super().__init__(parent)
        self.stacked_widget = stacked_widget
        self.main_menu_index = main_menu_index
        self.ttw_screen_index = ttw_screen_index

        self._cards: Dict[str, ToolCard] = {}
        self._action_thread: Optional[_ToolActionThread] = None
        self._version_thread: Optional[_VersionCheckThread] = None
        self._manifest_thread: Optional[_ManifestFetchThread] = None
        self._release_thread: Optional[_ReleaseFetchThread] = None
        self._active_engine_id = get_active_engine_id()

        self._setup_ui()

    def _setup_ui(self):
        root = QVBoxLayout()
        root.setContentsMargins(30, 24, 30, 24)
        root.setSpacing(0)
        self.setLayout(root)

        header_row = QHBoxLayout()
        self._btn_update_all = QPushButton("Update All")
        self._btn_update_all.setFixedSize(100, 30)
        self._btn_update_all.setStyleSheet(btn_style(_C_UPDATE, disabled=True))
        self._btn_update_all.setEnabled(False)
        self._btn_update_all.clicked.connect(self._on_update_all)
        # Left spacer matches button width so title stays centred
        left_spacer = QWidget()
        left_spacer.setFixedWidth(100)
        header_row.addWidget(left_spacer)
        header_row.addStretch()
        title = QLabel("<b>Tools Hub</b>")
        title.setStyleSheet(f"font-size: 20px; color: {JACKIFY_COLOR_BLUE};")
        header_row.addWidget(title)
        header_row.addStretch()
        header_row.addWidget(self._btn_update_all)
        root.addLayout(header_row)

        root.addSpacing(6)

        disclaimer = QLabel(
            "Some of these tools are developed and maintained by their respective authors, "
            "independently of Jackify. Jackify provides download and update management "
            "as a convenience only. The Jackify project offers no warranty or support "
            "for third-party tools."
        )
        disclaimer.setWordWrap(True)
        disclaimer.setStyleSheet("color: #aaa; font-size: 12px;")
        root.addWidget(disclaimer)

        root.addSpacing(10)
        sep = QLabel()
        sep.setFixedHeight(2)
        sep.setStyleSheet("background: #fff;")
        root.addWidget(sep)
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

        scroll.setWidget(self._list_widget)
        root.addWidget(scroll, stretch=1)

        root.addSpacing(12)
        back_row = QHBoxLayout()
        back_row.addStretch()
        back_btn = QPushButton("Back to Main Menu")
        back_btn.setFixedSize(160, 34)
        back_btn.setStyleSheet(
            f"QPushButton {{ background-color: {_C_BACK}; color: white; border: none; "
            f"border-radius: 6px; font-size: 12px; font-weight: bold; }}"
            f"QPushButton:hover {{ background-color: #5a6578; }}"
            f"QPushButton:pressed {{ background-color: {JACKIFY_COLOR_BLUE}; }}"
        )
        back_btn.clicked.connect(self._go_back)
        back_row.addWidget(back_btn)
        back_row.addStretch()
        root.addLayout(back_row)

    # card list management

    def _rebuild_card_list(self):
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._cards.clear()

        statuses = ToolRegistry().get_all_statuses()
        engines = [s for s in statuses if s.definition.is_engine]
        tools   = [s for s in statuses if not s.definition.is_engine]

        if engines:
            self._list_layout.addWidget(section_header("Engine"))
            self._list_layout.addSpacing(4)
            for s in engines:
                self._add_card(s)
            self._list_layout.addSpacing(10)

        if tools:
            self._list_layout.addWidget(section_header("Tools"))
            self._list_layout.addSpacing(4)
            for s in tools:
                self._add_card(s)

        placeholder = QLabel("More tools coming soon")
        placeholder.setAlignment(Qt.AlignCenter)
        placeholder.setStyleSheet(
            "color: #555; font-size: 12px; font-style: italic; "
            "background-color: #222; border: 1px dashed #333; "
            "border-radius: 6px; padding: 10px;"
        )
        self._list_layout.addWidget(placeholder)

        self._list_layout.addStretch()

    def _add_card(self, status: ToolStatus):
        card = ToolCard(status, self._active_engine_id)
        card.action_requested.connect(self._on_action)
        card.engine_activated.connect(self._on_engine_activated)
        self._cards[status.definition.tool_id] = card
        self._list_layout.addWidget(card)

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

    def _start_manifest_fetch(self):
        if self._manifest_thread and self._manifest_thread.isRunning():
            return
        self._manifest_thread = _ManifestFetchThread()
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
        self._version_thread = _VersionCheckThread()
        self._version_thread.version_ready.connect(self._on_version_ready)
        self._version_thread.start()

    def _on_version_ready(self, tool_id: str, tag: str):
        card = self._cards.get(tool_id)
        if card:
            has_update = card.set_latest_version(tag)
            if has_update:
                self._btn_update_all.setEnabled(True)
                self._btn_update_all.setStyleSheet(btn_style(_C_UPDATE))
        any_updates = any(c._status.update_available for c in self._cards.values())
        main_menu = self._get_main_menu()
        if main_menu:
            main_menu.notify_tool_updates(any_updates)

    def _get_main_menu(self):
        try:
            from jackify.frontends.gui.screens.main_menu import MainMenu
            w = self.window()
            if w and hasattr(w, 'main_menu'):
                return w.main_menu
        except Exception:
            pass
        return None

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
        self._action_thread = _ToolActionThread(tool_id, action)
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
        self._action_thread = _ArchiveInstallThread(tool_id, archive)
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
        self._action_thread = _ToolActionThread(tool_id, "update")
        self._action_thread.finished_signal.connect(self._on_update_all_step)
        self._action_thread.start()

    def _on_update_all_step(self, tool_id: str, success: bool, message: str):
        self._action_thread = None
        self._on_action_finished(tool_id, success, message if not success else "")
        if getattr(self, "_pending_updates", []):
            self._run_next_update()
        else:
            any_remaining = any(c._status.installed and c._status.update_available for c in self._cards.values())
            self._btn_update_all.setEnabled(any_remaining)
            if not any_remaining:
                self._btn_update_all.setStyleSheet(btn_style(_C_UPDATE, disabled=True))

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
        self._release_thread = _ReleaseFetchThread(tool_id, status.definition.github_repo)
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
        self._action_thread = _ToolActionThread(tool_id, "install", version=version)
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
        cancel_btn.setStyleSheet(btn_style(_C_BACK))
        cancel_btn.clicked.connect(dlg.reject)
        btn_row.addWidget(cancel_btn)
        install_btn = QPushButton("Install")
        install_btn.setFixedSize(90, 30)
        install_btn.setStyleSheet(btn_style(_C_INSTALL))
        install_btn.setDefault(True)
        install_btn.clicked.connect(dlg.accept)
        btn_row.addWidget(install_btn)
        layout.addLayout(btn_row)
        if dlg.exec() != QDialog.Accepted:
            return None
        return combo.currentData()

    def _go_back(self):
        if self.stacked_widget:
            self.stacked_widget.setCurrentIndex(self.main_menu_index)

