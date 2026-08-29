"""
Modlist Lifecycle Dashboard screen - the app's home screen.

Lists every registered install (Jackify-created or discovered via an existing Steam shortcut,
per design decision Q2), with status, Proton version, and per-row actions. Opens instantly with
no network call; "Check for Updates" refreshes gallery metadata in the background and recomputes
every row's status (design decision Q3). See docs/0.8_work/modlist_lifecycle_dashboard.md.
"""
import logging
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QApplication,
    QFrame, QGridLayout, QLabel, QMessageBox, QProgressDialog, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from jackify.backend.services.dashboard_images import get_cached_image_path, save_image_from_path
from jackify.backend.services.dashboard_status import (
    STATUS_MISSING,
    STATUS_NOT_CONFIGURED,
    STATUS_READY,
    STATUS_UNKNOWN_VERSION,
    STATUS_UPDATE_AVAILABLE,
    get_proton_version_display,
    resolve_all_statuses,
)
from jackify.backend.services.install_registry import (
    InstallEntry,
    backfill_from_shortcuts,
    load_registry,
    mark_missing_installs,
    remove_from_registry,
)
from jackify.frontends.gui.dialogs.warning_dialog import WarningDialog
from jackify.frontends.gui.mixins.thread_lifecycle_mixin import ThreadLifecycleMixin
from jackify.frontends.gui.screens.modlist_dashboard_card import (
    CARD_WIDTH, AddModlistCard, DashboardCard, btn_style,
)
from jackify.frontends.gui.screens.modlist_dashboard_threads import (
    GalleryVersionFetchThread, UninstallThread,
)
from jackify.frontends.gui.screens.screen_focus_reclaim import FocusReclaimMixin
from jackify.frontends.gui.services.message_service import MessageService, open_url
from jackify.frontends.gui.shared_theme import COLOR_BTN_UPDATE

logger = logging.getLogger(__name__)

_STATUS_LABELS = {
    STATUS_READY: "Ready",
    STATUS_UPDATE_AVAILABLE: "Update Available",
    STATUS_NOT_CONFIGURED: "Not Configured",
    STATUS_MISSING: "Missing",
    STATUS_UNKNOWN_VERSION: "Unknown Version",
}


class ModlistDashboardScreen(ThreadLifecycleMixin, FocusReclaimMixin, QWidget):
    """Modlist Dashboard - the app's home screen and default body under the "Modlists" tab.
    The tab bar itself is persistent chrome owned by the main window, not part of this
    widget - see modlist_dashboard_tabs.py."""

    def __init__(self, stacked_widget=None,
                 configure_existing_index: int = 8, dashboard_index: int = 12,
                 install_modlist_index: int = 4, configure_new_index: int = 6,
                 parent=None):
        super().__init__(parent)
        self.stacked_widget = stacked_widget
        self.configure_existing_index = configure_existing_index
        self.dashboard_index = dashboard_index
        self.install_modlist_index = install_modlist_index
        self.configure_new_index = configure_new_index

        self._entries: List[InstallEntry] = []
        self._cards: Dict[str, DashboardCard] = {}
        self._gallery_versions: Dict[str, str] = {}
        self._version_thread: Optional[GalleryVersionFetchThread] = None
        self._uninstall_thread: Optional[UninstallThread] = None
        self._uninstall_progress = None

        self._setup_ui()

    def _setup_ui(self):
        root = QVBoxLayout()
        root.setContentsMargins(30, 14, 30, 24)
        root.setSpacing(0)
        self.setLayout(root)

        # Lives in the persistent header's tab row (next to the Modlists tab), not in this
        # screen's own body - see main_window_ui.py's _make_modlist_dashboard_screen and
        # modlist_dashboard_tabs.py's action slot. Built here because it's this screen's own
        # state machine (enable/disable/text) that drives it.
        self.check_updates_button = QPushButton("Check for Updates")
        self.check_updates_button.setFixedSize(150, 30)
        self.check_updates_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.check_updates_button.setStyleSheet(btn_style(COLOR_BTN_UPDATE))
        self.check_updates_button.clicked.connect(self._on_check_updates)

        # showEvent() already re-syncs (backfill + missing-check) on every navigation to this
        # screen, but that only fires on navigation - nothing forces a re-check while already
        # sitting on the Dashboard tab and something changes externally (a directory renamed,
        # a shortcut edited by hand in Steam). No network call, unlike Check for Updates.
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setFixedSize(90, 30)
        self.refresh_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.refresh_button.setStyleSheet(btn_style(COLOR_BTN_UPDATE))
        self.refresh_button.clicked.connect(self._on_refresh)

        self._empty_label = QLabel(
            "No modlists registered yet. Click \"Add a Modlist\" below to install a new one "
            "or set up one you already have."
        )
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._empty_label.setStyleSheet("color: #aaa; font-size: 13px;")
        self._empty_label.setWordWrap(True)
        root.addWidget(self._empty_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._list_widget = QWidget()
        self._list_widget.setStyleSheet("background: transparent;")
        self._list_layout = QGridLayout()
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(10)
        self._list_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self._list_widget.setLayout(self._list_layout)
        self._add_card = AddModlistCard()
        self._add_card.install_requested.connect(self._on_add_install_new)
        self._add_card.add_existing_requested.connect(self._on_add_existing)
        self._scroll_area = scroll
        scroll.setWidget(self._list_widget)
        root.addWidget(scroll, stretch=1)

    def showEvent(self, event):
        super().showEvent(event)
        self._reload()
        # Auto-check once per visit to this screen rather than requiring the button click
        # first - navigating to the Dashboard is already the deliberate "check on my
        # modlists" action, so the button becomes a way to re-check, not the only way to
        # check at all. Guarded so flipping back and forth between screens doesn't refire
        # the network fetch every time.
        if not self._gallery_versions and not (self._version_thread and self._version_thread.isRunning()):
            self._on_check_updates()

    def _on_refresh(self):
        """Force the same re-sync showEvent() does on navigation, without leaving the tab.
        No network call, so this is near-instant - the button flashes "Refreshed" briefly
        so a click is confirmed even when nothing on screen actually changes."""
        self._reload()
        self.refresh_button.setText("Refreshed")
        QTimer.singleShot(1200, lambda: self.refresh_button.setText("Refresh"))

    def _reload(self):
        try:
            backfill_from_shortcuts()
        except Exception as e:
            logger.debug("Dashboard backfill failed (non-fatal): %s", e)
        self._entries = mark_missing_installs()
        self._rebuild_card_list()

    def _rebuild_card_list(self):
        # A background thread (e.g. the gallery version fetch) can finish while a modal
        # dialog for one of these cards (e.g. Properties) is still open - tearing down and
        # recreating every card out from under it caused a real segfault (found 2026-08-29).
        # Skip the rebuild while any modal dialog is active; whatever opened it already
        # rebuilds the list itself once it closes, so nothing is lost, only deferred.
        if QApplication.activeModalWidget() is not None:
            return
        # The add tile is reused across rebuilds - detach it rather than delete it
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None and widget is not self._add_card:
                widget.deleteLater()
        self._add_card.setParent(self._list_widget)
        self._cards.clear()

        self._empty_label.setVisible(not self._entries)

        statuses = resolve_all_statuses(self._entries, gallery_versions=self._gallery_versions)
        for entry in self._entries:
            status = statuses.get(entry.install_id, STATUS_MISSING)
            proton_version = get_proton_version_display(entry.appid) if entry.appid else None
            latest_version = self._gallery_versions.get(entry.machine_url) if entry.machine_url else None
            card = DashboardCard(entry, status, proton_version, latest_version)
            card.action_requested.connect(self._on_card_action)
            self._cards[entry.install_id] = card
        self._lay_out_grid()

    def _lay_out_grid(self):
        """Place cards into a responsive grid, column count based on available width - same
        approach the Gallery uses for its own cards."""
        available_width = self._scroll_area.viewport().width()
        if available_width <= 0:
            available_width = self.width() - 60
        if available_width <= 0:
            available_width = 900  # not yet sized (e.g. first-ever showEvent) - reasonable default
        card_spacing = self._list_layout.spacing()
        columns = max(1, (available_width + card_spacing) // (CARD_WIDTH + card_spacing))

        placed = 0
        row, col = divmod(placed, columns)
        self._list_layout.addWidget(self._add_card, row, col)
        placed += 1

        for entry in self._entries:
            card = self._cards.get(entry.install_id)
            if card is None:
                continue
            row, col = divmod(placed, columns)
            self._list_layout.addWidget(card, row, col)
            placed += 1

        for col in range(columns):
            self._list_layout.setColumnStretch(col, 0)
        if columns < 5:
            self._list_layout.setColumnStretch(columns, 1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._lay_out_grid()

    def _on_check_updates(self):
        if self._version_thread and self._version_thread.isRunning():
            return
        self.check_updates_button.setEnabled(False)
        self.check_updates_button.setText("Checking...")
        self._version_thread = GalleryVersionFetchThread()
        self._version_thread.versions_ready.connect(self._on_versions_ready)
        self._version_thread.start()

    def _on_versions_ready(
        self, versions: Dict[str, str], by_title: Dict[str, object], by_machine_url: Dict[str, object],
        error: str,
    ):
        self._gallery_versions = versions
        self.check_updates_button.setEnabled(True)

        if error:
            self.check_updates_button.setText("Check for Updates")
            MessageService.warning(
                self, "Check for Updates Failed",
                f"Could not fetch modlist gallery data:\n\n{error}",
            )
            return

        updated = self._backfill_missing_registry_fields(by_title)
        self._backfill_missing_images(by_machine_url, by_title)
        self.check_updates_button.setText(f"Updated {updated}" if updated else "Up to date")
        QTimer.singleShot(2500, lambda: self.check_updates_button.setText("Check for Updates"))
        self._rebuild_card_list()

    def _backfill_missing_registry_fields(self, by_title: Dict[str, object]) -> int:
        """
        Fill in machine_url (identity only, never version) for entries that predate that field
        existing, by matching modlist_name against the gallery listing this "Check for
        Updates" click already fetched. Deliberately does NOT set installed_version from this
        match: a name match only tells us which gallery listing this install probably
        corresponds to, not what version was actually installed - only real install-time
        capture (the modlist's own .wabbajack manifest, or the gallery selection used at
        install) is trustworthy enough to claim as "installed_version", since a wrong guess
        there can either falsely claim an update is available or silently hide a real one.
        Returns how many entries were updated, so the button can show a concrete result
        instead of silently doing (or not doing) something.
        """
        if not by_title:
            return 0
        from jackify.backend.services.install_registry import register_install

        updated = 0
        for entry in self._entries:
            if entry.machine_url:
                continue
            modlist = by_title.get(entry.modlist_name.lower())
            if modlist is None:
                continue
            machine_url = getattr(modlist, "namespacedName", None)
            if not machine_url:
                continue
            register_install(entry.install_dir, entry.modlist_name, machine_url=machine_url)
            entry.machine_url = machine_url
            updated += 1
        return updated

    def _backfill_missing_images(
        self, by_machine_url: Dict[str, object], by_title: Dict[str, object],
    ) -> None:
        """
        Save the gallery's own per-modlist artwork as this install's dashboard image for any
        entry that doesn't have one cached yet, regardless of whether machine_url was already
        known - a known machine_url only means the registry fields don't need backfilling, not
        that the image-save step at install time (install_modlist_progress.py) ever ran for
        this particular install (e.g. it predates that step, or the save failed at the time).
        """
        if not by_machine_url and not by_title:
            return
        from jackify.backend.services.modlist_gallery_service import ModlistGalleryService

        for entry in self._entries:
            if get_cached_image_path(entry.install_id):
                continue
            modlist = by_machine_url.get(entry.machine_url) if entry.machine_url else None
            if modlist is None:
                modlist = by_title.get(entry.modlist_name.lower())
            if modlist is None:
                continue
            try:
                cache_path = ModlistGalleryService().get_image_cache_path(modlist, size="large")
                if cache_path.is_file():
                    save_image_from_path(entry.install_id, str(cache_path))
            except Exception as e:
                logger.debug("Dashboard image backfill failed for %s: %s", entry.modlist_name, e)

    def _entry_by_id(self, install_id: str) -> Optional[InstallEntry]:
        return next((e for e in self._entries if e.install_id == install_id), None)

    def _on_card_action(self, install_id: str, action: str):
        entry = self._entry_by_id(install_id)
        if entry is None:
            return
        if action == "launch":
            self._launch(entry)
        elif action == "properties":
            self._open_properties(entry)
        elif action == "configure":
            self._go_to_configure(entry)
        elif action == "update":
            self._go_to_update(entry)
        elif action == "open_dir":
            open_url(entry.install_dir)
        elif action == "open_extender_logs":
            self._open_extender_logs(entry)
        elif action == "uninstall":
            self._uninstall(entry)
        elif action == "remove_from_list":
            self._remove_from_list(entry)

    def _open_properties(self, entry: InstallEntry):
        from jackify.frontends.gui.dialogs.modlist_properties_dialog import ModlistPropertiesDialog

        statuses = resolve_all_statuses([entry], gallery_versions=self._gallery_versions)
        status = statuses.get(entry.install_id, STATUS_MISSING)
        status_text = _STATUS_LABELS.get(status, status)
        proton_version = get_proton_version_display(entry.appid) if entry.appid else None

        dlg = ModlistPropertiesDialog(entry, status_text, proton_version, status=status, parent=self)
        dlg.action_requested.connect(self._on_card_action)
        dlg.artwork_changed.connect(self._on_artwork_changed)
        dlg.exec()
        # Proton version or artwork may have changed even if the dialog closed via Close
        # rather than an action that already triggers its own reload.
        self._entries = load_registry()
        self._rebuild_card_list()

    def _open_extender_logs(self, entry: InstallEntry):
        from jackify.backend.services.crash_log_service import get_crash_log_dir, open_path
        from jackify.backend.services.dashboard_status import _default_prefix_resolver

        pfx = _default_prefix_resolver(entry.appid) if entry.appid else None
        log_dir = get_crash_log_dir(Path(pfx) if pfx else None, entry.game_type)
        if not log_dir or not open_path(log_dir):
            MessageService.warning(
                self, "Log Directory Not Found",
                f"Could not find the log directory for \"{entry.modlist_name}\". "
                "It may not exist yet if the game has never been launched.",
            )

    def _on_artwork_changed(self, install_id: str):
        card = self._cards.get(install_id)
        if card:
            card.refresh_thumbnail()

    def _launch(self, entry: InstallEntry):
        if not entry.appid:
            logger.warning("Dashboard launch requested for %r with no appid", entry.modlist_name)
            MessageService.warning(
                self, "Cannot Launch",
                f"\"{entry.modlist_name}\" has no known Steam AppID, so Jackify cannot launch it "
                "directly - open it from your Steam library instead.",
            )
            return
        from jackify.backend.services.steam_launch_service import launch_steam_app

        logger.info("Dashboard launching %r via -applaunch %s", entry.modlist_name, entry.appid)
        if not launch_steam_app(entry.appid):
            MessageService.warning(
                self, "Launch Failed",
                f"Could not launch \"{entry.modlist_name}\" - open it from your Steam library instead.",
            )

    def _on_add_install_new(self):
        self._go_to_screen(self.install_modlist_index)

    def _on_add_existing(self):
        self._go_to_screen(self.configure_new_index)

    def _go_to_screen(self, index: int):
        """Navigate and ask the screen to return here. Screens 1-9 are lazy-initialised, so
        fetch the widget after switching, not before."""
        if not self.stacked_widget:
            return
        self.stacked_widget.setCurrentIndex(index)
        screen = self.stacked_widget.widget(index)
        if hasattr(screen, "request_return_target"):
            screen.request_return_target(self.dashboard_index)

    def _go_to_configure(self, entry: InstallEntry):
        """A modlist with no prefix cannot be reached from Configure Existing, which lists only
        modlists that already have one, so it is rebuilt in Configure New instead."""
        statuses = resolve_all_statuses([entry], gallery_versions=self._gallery_versions)
        if statuses.get(entry.install_id) == STATUS_NOT_CONFIGURED:
            self._go_to_configure_new(entry)
            return
        self._go_to_configure_existing(entry)

    def _go_to_configure_new(self, entry: InstallEntry):
        if not self.stacked_widget:
            return
        self._go_to_screen(self.configure_new_index)
        screen = self.stacked_widget.widget(self.configure_new_index)
        if hasattr(screen, "request_prefill"):
            screen.request_prefill(entry.modlist_name, entry.install_dir)

    def _go_to_configure_existing(self, entry: InstallEntry):
        if not self.stacked_widget:
            return
        # Screens 1-9 are lazy-initialised: widget(index) is still a placeholder until
        # setCurrentIndex actually triggers the real screen's construction, so it must be
        # fetched *after* switching, not before - getting this backwards means both
        # request_return_target and request_select_appid silently no-op on the placeholder
        # on this screen's first visit of the session.
        self.stacked_widget.setCurrentIndex(self.configure_existing_index)
        screen = self.stacked_widget.widget(self.configure_existing_index)
        if hasattr(screen, "request_return_target"):
            screen.request_return_target(self.dashboard_index)
        if entry.appid and hasattr(screen, "request_select_appid"):
            screen.request_select_appid(entry.appid)

    def _go_to_update(self, entry: InstallEntry):
        """Update is a reinstall to a newer version, not a reconfigure - route to Install
        Modlist so the engine actually fetches the new content. compute_status() only ever
        returns STATUS_UPDATE_AVAILABLE when entry.machine_url is set (dashboard_status.py
        looks it up by machine_url), so this is reached with a machine_url in practice; the
        None check is a defensive fallback, not the expected path."""
        if not self.stacked_widget or not entry.machine_url:
            self._go_to_configure(entry)
            return
        self._go_to_screen(self.install_modlist_index)
        screen = self.stacked_widget.widget(self.install_modlist_index)
        if hasattr(screen, "request_update_prefill"):
            screen.request_update_prefill(entry.machine_url, entry.modlist_name, entry.install_dir)

    def _uninstall(self, entry: InstallEntry):
        provenance_note = (
            " Jackify did not install this modlist, so it cannot verify what else is in this "
            "directory."
            if entry.provenance == "backfill" else ""
        )
        dlg = WarningDialog(
            f"Deletes the install directory, the Steam shortcut \"{entry.modlist_name}\", and "
            f"its Proton prefix (saves, configs, everything).\n\n"
            f"{entry.install_dir}\n\n"
            f"Warning: Steam will be restarted during removal - this will close any running "
            f"game.{provenance_note}\n\n"
            f"This cannot be undone.",
            parent=self,
        )
        if not dlg.exec() or not dlg.confirmed:
            return

        if not self._confirm_files_stay_behind(entry):
            return

        self.check_updates_button.setEnabled(False)
        card = self._cards.get(entry.install_id)
        if card:
            card.setEnabled(False)

        self._show_uninstall_progress(entry)
        self._uninstall_thread = UninstallThread(entry, parent=self)
        self._uninstall_thread.progress.connect(self._on_uninstall_progress)
        self._uninstall_thread.finished_uninstall.connect(
            lambda success, message: self._on_uninstall_done(entry, success, message)
        )
        self._uninstall_thread.start()

    def _show_uninstall_progress(self, entry: InstallEntry):
        self._uninstall_progress = QProgressDialog(
            f"Removing {entry.modlist_name}...", None, 0, 0, self
        )
        self._uninstall_progress.setWindowTitle("Uninstalling Modlist")
        self._uninstall_progress.setWindowModality(Qt.WindowModal)
        self._uninstall_progress.setMinimumDuration(0)
        # Fixed, not minimum: a long path in a step message grew the dialog and QProgressDialog
        # never shrinks back, so the stop and start steps appeared as two differently sized
        # dialogs. Messages are elided to fit instead.
        self._uninstall_progress.setFixedWidth(520)
        self._uninstall_progress.setValue(0)
        self._uninstall_progress.show()

    def _on_uninstall_progress(self, message: str):
        if getattr(self, "_uninstall_progress", None) is not None:
            self._uninstall_progress.setLabelText(self._elide_progress_message(message))

    def _elide_progress_message(self, message: str) -> str:
        """Keep a step message inside the fixed dialog width, cutting the middle of any path."""
        metrics = self._uninstall_progress.fontMetrics()
        return metrics.elidedText(message, Qt.ElideMiddle, 520 - 60)

    def _hide_uninstall_progress(self):
        progress = getattr(self, "_uninstall_progress", None)
        if progress is None:
            return
        try:
            progress.close()
            progress.deleteLater()
        except Exception:
            pass
        self._uninstall_progress = None
        # Steam takes focus when it comes back up, leaving Jackify behind the Steam window
        self._start_focus_reclaim_retries()

    def _confirm_files_stay_behind(self, entry: InstallEntry) -> bool:
        """Second confirmation when the files cannot be reached - the first dialog promises to
        delete the install directory, and that promise cannot be kept here. Deliberately a
        plain Yes/No, not another typed-DELETE WarningDialog: the destructive part (shortcut +
        prefix removal) was already confirmed in dialog 1, and this dialog's only new
        information is that the files will NOT be touched - the opposite of scary. A second
        typed-DELETE here just invites the user to retype it on autopilot without reading what
        changed, same reasoning as _remove_from_list()'s plain Yes/No below."""
        if Path(entry.install_dir).is_dir():
            return True

        reply = MessageService.question(
            self, "Files Not Found",
            f"The files for \"{entry.modlist_name}\" cannot be reached, so they will NOT be "
            f"deleted:\n\n{entry.install_dir}\n\n"
            f"The drive may be disconnected, or the folder may already have been removed.\n\n"
            f"Continuing removes the Steam shortcut and the Proton prefix only. If the drive "
            f"comes back later, you will need to delete the modlist folder yourself.",
            safety_level="medium",
        )
        return reply == QMessageBox.Yes

    def _on_uninstall_done(self, entry: InstallEntry, success: bool, message: str):
        self._hide_uninstall_progress()
        self.check_updates_button.setEnabled(True)
        if not success:
            MessageService.critical(
                self, "Uninstall Failed",
                f"Could not uninstall \"{entry.modlist_name}\":\n\n{message}",
            )
        elif message:
            MessageService.warning(
                self, "Uninstalled With Warnings",
                f"\"{entry.modlist_name}\" was uninstalled, but some cleanup steps had issues:\n\n{message}",
            )
        self._entries = load_registry()
        self._rebuild_card_list()

    def _remove_from_list(self, entry: InstallEntry):
        """Drop the registry entry only - the CLI's "Remove from this list only" action,
        for a modlist whose Steam shortcut/prefix/files should not be touched (e.g. Missing
        because its drive is temporarily unmounted). Not destructive - only edits Jackify's
        own tracking file - so a plain Yes/No question, not the typed-DELETE WarningDialog
        Uninstall uses."""
        reply = MessageService.question(
            self, "Remove from List",
            f"Remove \"{entry.modlist_name}\" from Jackify's tracked list?\n\n"
            f"The Steam shortcut, Proton prefix and files are left untouched. If it is "
            f"reinstalled or its drive comes back, use \"Add an Existing Modlist\" to bring "
            f"it back onto the Dashboard.",
            safety_level="low",
        )
        if reply != QMessageBox.Yes:
            return

        # No rebuild here - this runs from the Properties dialog's own nested event loop
        # (dlg.exec() is still active), and rebuilding now would destroy the card whose
        # mousePressEvent opened that dialog while it is still on the call stack, three
        # frames up. _open_properties() already rebuilds unconditionally once dlg.exec()
        # actually returns, which is the only point it is safe to do so.
        remove_from_registry(entry.install_id)

