"""
Additional Tasks & Tools Screen

Additional tools and automation. Follows the same pattern as ModlistTasksScreen.
"""

import logging
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QFrame, QGridLayout, QScrollArea
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPixmap

from jackify.backend.models.configuration import SystemInfo
from ..screens.modlist_dashboard_card import CARD_HEIGHT, CARD_WIDTH, IMAGE_HEIGHT, IMAGE_WIDTH
from ..utils import set_responsive_minimum
from ..mixins.thread_lifecycle_mixin import ThreadLifecycleMixin

logger = logging.getLogger(__name__)

# Distinct from Tools Hub's engine/tool tile colours (_TILE_ENGINE/_TILE_TOOL in
# tools_hub_card.py) - these tiles represent one-off actions, not installable things.
_TILE_ACTION = "#3a4a5a"


class _ActionTile(QFrame):
    """Clickable action tile - same compact icon-card shape as the Dashboard and Tools Hub
    cards, but with the action's full name painted directly into the tile (word-wrapped)
    instead of misleading 2-3 letter initials ("Setup Mod Organizer 2" -> "SMO")."""
    clicked = Signal()

    def __init__(self, title: str, description: str, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet(
            "_ActionTile { background-color: #2a2a2a; border: 1px solid #3a3a3a; border-radius: 6px; } "
            "_ActionTile:hover { background-color: #333333; border: 1px solid #5a9fd6; }"
        )
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(CARD_WIDTH, CARD_HEIGHT)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        tile_label = QLabel()
        tile_label.setFixedSize(IMAGE_WIDTH, IMAGE_HEIGHT)
        tile_label.setAlignment(Qt.AlignCenter)
        tile_label.setStyleSheet("background: #1c1c1c; border-radius: 4px; border: none;")
        tile_label.setPixmap(self._name_pixmap(title, tile_label.size()))
        layout.addWidget(tile_label, alignment=Qt.AlignHCenter)

        desc_label = QLabel(description)
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("color: #999; font-size: 11px; background: transparent; border: none;")
        layout.addWidget(desc_label)
        layout.addStretch(1)

    @staticmethod
    def _name_pixmap(title: str, size) -> QPixmap:
        base = QColor(_TILE_ACTION)
        pixmap = QPixmap(size)
        painter = QPainter(pixmap)
        gradient = QLinearGradient(0, 0, size.width(), size.height())
        gradient.setColorAt(0.0, base.lighter(130))
        gradient.setColorAt(1.0, base.darker(140))
        painter.fillRect(pixmap.rect(), gradient)
        painter.setPen(QColor(255, 255, 255, 230))
        font = QFont("Sans", 15, QFont.Bold)
        painter.setFont(font)
        text_rect = pixmap.rect().adjusted(14, 10, -14, -10)
        painter.drawText(text_rect, Qt.AlignCenter | Qt.TextWordWrap, title)
        painter.end()
        return pixmap

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class AdditionalTasksScreen(ThreadLifecycleMixin, QWidget):
    """Additional Tasks screen for automation and standalone tools."""

    def __init__(self, stacked_widget=None, system_info: Optional[SystemInfo] = None,
                 install_mo2_screen_index: int = 9, game_downgrade_screen_index: int = 13):
        super().__init__()
        self.stacked_widget = stacked_widget
        self.system_info = system_info or SystemInfo(is_steamdeck=False)
        self.install_mo2_screen_index = install_mo2_screen_index
        self.game_downgrade_screen_index = game_downgrade_screen_index

        self._setup_ui()

    MENU_ITEMS = [
        ("Run Install Verifier", "run_verifier", "Check an installed modlist for common configuration problems"),
        ("Browse Crash Logs", "crash_logs", "Find and open crash logs for an installed modlist"),
        ("Create Diagnostic Bundle", "diagnostic_bundle", "Package logs and system info for support reporting"),
        ("Configure Tool Compatibility", "tool_config", "Apply xEdit, Pandora and DLL fixes to an existing modlist prefix"),
        ("Setup Mod Organizer 2", "setup_mo2", "Download and configure a standalone MO2 instance"),
        ("Install Wabbajack", "wabbajack_install", "Install Wabbajack.exe via Proton (automated setup)"),
        ("Downgrade Game Version", "downgrade_game", "Downgrade Skyrim SE or Fallout 4 to a script-extender-compatible build"),
    ]

    def _setup_ui(self):
        """Set up the user interface following ModlistTasksScreen pattern"""
        layout = QVBoxLayout()
        layout.setContentsMargins(30, 24, 30, 16)
        layout.setSpacing(12)  # Match main menu spacing

        # Header section
        self._setup_header(layout)

        # Menu buttons section - scrollable so a full grid never gets clipped by the
        # window chrome (e.g. on Steam Deck's 1280x800), matching Dashboard/Tools Hub.
        self._setup_menu_buttons(layout)

        self.setLayout(layout)

    def _setup_header(self, layout):
        """Set up the header section"""
        desc = QLabel("Wabbajack installer, MO2 setup, and additional tools.")
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #ccc; font-size: 13px;")
        desc.setAlignment(Qt.AlignHCenter)
        layout.addWidget(desc)
        layout.addSpacing(12)

    def _setup_menu_buttons(self, layout):
        """Set up the scrollable, responsive card grid."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        grid_widget = QWidget()
        grid_widget.setStyleSheet("background: transparent;")
        self._button_grid = QGridLayout()
        self._button_grid.setSpacing(12)
        self._button_grid.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        grid_widget.setLayout(self._button_grid)

        self._tiles = []
        for label, action_id, description in self.MENU_ITEMS:
            tile = _ActionTile(label, description)
            tile.clicked.connect(lambda checked=False, a=action_id: self._handle_button_click(a))
            self._tiles.append(tile)

        self._scroll_area = scroll
        scroll.setWidget(grid_widget)
        layout.addWidget(scroll, stretch=1)

        self._lay_out_grid()

    def _lay_out_grid(self):
        """Responsive column count based on available width - same approach the Dashboard
        and Tools Hub use for their own card grids."""
        available_width = self._scroll_area.viewport().width()
        if available_width <= 0:
            available_width = self.width() - 60
        if available_width <= 0:
            available_width = 900  # not yet sized (e.g. first-ever showEvent)
        spacing = self._button_grid.spacing()
        columns = max(1, (available_width + spacing) // (CARD_WIDTH + spacing))
        columns = min(columns, len(self._tiles) or 1)

        for tile in self._tiles:
            self._button_grid.removeWidget(tile)
        for i, tile in enumerate(self._tiles):
            row, col = divmod(i, columns)
            self._button_grid.addWidget(tile, row, col)
        for col in range(columns):
            self._button_grid.setColumnStretch(col, 0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_button_grid"):
            self._lay_out_grid()

    def _handle_button_click(self, action_id):
        """Handle button clicks"""
        if action_id == "run_verifier":
            self._run_install_verifier()
        elif action_id == "wabbajack_install":
            self._show_wabbajack_installer()
        elif action_id == "setup_mo2":
            self._show_mo2_setup()
        elif action_id == "tool_config":
            self._show_tool_config()
        elif action_id == "diagnostic_bundle":
            self._run_diagnostic_bundle()
        elif action_id == "crash_logs":
            self._browse_crash_logs()
        elif action_id == "downgrade_game":
            self._show_downgrade_game()

    def _browse_crash_logs(self):
        """Pick a modlist, then pick one of its crash logs to open."""
        from ..dialogs.crash_log_dialog import browse_crash_logs
        browse_crash_logs(self)

    def _show_wabbajack_installer(self):
        """Navigate to Wabbajack installer screen"""
        if self.stacked_widget:
            # Navigate to Wabbajack installer screen (index 7)
            self.stacked_widget.setCurrentIndex(7)

    def _show_mo2_setup(self):
        """Navigate to standalone MO2 setup screen"""
        if self.stacked_widget:
            self.stacked_widget.setCurrentIndex(self.install_mo2_screen_index)

    def _show_tool_config(self):
        if self.stacked_widget:
            self.stacked_widget.setCurrentIndex(11)

    def _show_downgrade_game(self):
        """Navigate to the Downgrade Game Version screen"""
        if self.stacked_widget:
            self.stacked_widget.setCurrentIndex(self.game_downgrade_screen_index)

    def _run_install_verifier(self):
        """Prompt user to pick a modlist, run the verifier, and show results."""
        from ..services.message_service import MessageService
        try:
            from jackify.backend.services.install_verifier_service import _load_verifier
            verifier_mod = _load_verifier()
            modlists = verifier_mod.discover_installed_modlists()
        except Exception as e:
            MessageService.critical(
                self,
                "Verifier Error",
                f"Could not load install verifier: {e}",
            )
            return

        if not modlists:
            MessageService.information(
                self,
                "No Modlists Found",
                "No installed modlists were found in Steam shortcuts.\n\n"
                "Ensure ModOrganizer.exe shortcuts exist in Steam for your modlists.",
            )
            return

        from PySide6.QtWidgets import QDialog, QVBoxLayout, QListWidget, QListWidgetItem, QPushButton, QLabel, QHBoxLayout
        picker = QDialog(self)
        picker.setWindowTitle("Select Modlist to Verify")
        picker.setMinimumWidth(480)
        picker.setMinimumHeight(260)
        picker_layout = QVBoxLayout(picker)
        picker_layout.addWidget(QLabel("Select a modlist to verify:"))

        lw = QListWidget()
        for m in modlists:
            pfx_ok = m["pfx"] and m["pfx"].is_dir()
            suffix = "" if pfx_ok else " (prefix not found)"
            item = QListWidgetItem(f"{m['name']}{suffix}")
            item.setData(1000, m)
            lw.addItem(item)
        lw.setCurrentRow(0)
        picker_layout.addWidget(lw)

        btn_row = QHBoxLayout()
        ok_btn = QPushButton("Run Verifier")
        cancel_btn = QPushButton("Cancel")
        btn_row.addStretch()
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        picker_layout.addLayout(btn_row)

        ok_btn.clicked.connect(picker.accept)
        cancel_btn.clicked.connect(picker.reject)
        lw.itemDoubleClicked.connect(lambda _: picker.accept())

        if picker.exec() != QDialog.Accepted:
            return

        selected_item = lw.currentItem()
        if not selected_item:
            return
        selected = selected_item.data(1000)

        pfx = selected.get("pfx")
        if not pfx or not pfx.is_dir():
            MessageService.warning(
                self,
                "Prefix Not Found",
                f"The Proton prefix for '{selected['name']}' was not found.\n\n"
                "Launch the modlist from Steam at least once to create the prefix.",
            )
            return

        from PySide6.QtCore import QThread, Signal as _Signal

        class _VerifierThread(QThread):
            done = _Signal(object)

            def __init__(self, verifier_module, entry, parent=None):
                super().__init__(parent)
                self._verifier = verifier_module
                self._entry = entry

            def run(self):
                try:
                    r = self._verifier.run_verification(
                        pfx=self._entry["pfx"],
                        modlist_dir=self._entry["modlist_dir"],
                        game_type=self._entry["game_type"],
                        appid=self._entry["appid"],
                        modlist_name=self._entry.get("name", ""),
                    )
                except Exception as exc:
                    logger.warning("On-demand verifier error: %s", exc)
                    r = None
                self.done.emit(r)

        from jackify.frontends.gui.services.message_service import MessageService as _MS
        progress_dlg = QDialog(self)
        progress_dlg.setWindowTitle("Verifying...")
        progress_dlg.setModal(True)
        prog_layout = QVBoxLayout(progress_dlg)
        prog_layout.addWidget(QLabel(f"Running verifier for '{selected['name']}'...\nThis may take a moment."))
        progress_dlg.setFixedSize(340, 100)
        progress_dlg.show()

        self._verifier_ondemand_thread = _VerifierThread(verifier_mod, selected, parent=self)

        def _on_done(results):
            progress_dlg.accept()
            self._verifier_ondemand_thread = None
            if results is None:
                MessageService.critical(
                    self,
                    "Verifier Error",
                    "The verifier encountered an error and could not complete.",
                )
                return
            from jackify.frontends.gui.dialogs.verification_results_dialog import VerificationResultsDialog
            dlg = VerificationResultsDialog(results, parent=self)
            dlg.exec()

        self._verifier_ondemand_thread.done.connect(_on_done)
        self._verifier_ondemand_thread.start()

    def _run_diagnostic_bundle(self):
        """Open the diagnostic bundle dialog; bundle is only created when the user confirms."""
        from PySide6.QtWidgets import (
            QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit
        )
        from PySide6.QtCore import QThread, Signal as _Signal

        class _BundleThread(QThread):
            done = _Signal(object, str)  # (bundle_path or None, error_msg)

            def run(self):
                try:
                    from jackify.backend.services.diagnostic_service import build_bundle
                    path = build_bundle()
                    self.done.emit(path, "")
                except Exception as exc:
                    self.done.emit(None, str(exc))

        dlg = QDialog(self)
        dlg.setWindowTitle("Diagnostic Bundle")
        dlg.setMinimumWidth(600)
        dlg.setMinimumHeight(220)
        dlg.setStyleSheet("QDialog { background: #181818; color: #fff; }")

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        status_label = QLabel("Package logs and system info into a file for support reporting.")
        layout.addWidget(status_label)

        path_box = QTextEdit()
        path_box.setReadOnly(True)
        path_box.setMinimumHeight(60)
        path_box.setVisible(False)
        layout.addWidget(path_box)

        btn_row = QHBoxLayout()
        create_btn = QPushButton("Create Bundle")
        cancel_btn = QPushButton("Cancel")
        btn_row.addWidget(create_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

        cancel_btn.clicked.connect(dlg.reject)

        def _on_create():
            create_btn.setEnabled(False)
            cancel_btn.setEnabled(False)
            status_label.setText("Collecting logs and system info...")
            self._diag_thread = _BundleThread(parent=self)
            self._diag_thread.done.connect(_on_done)
            self._diag_thread.start()

        def _on_done(bundle_path, error):
            self._diag_thread = None
            cancel_btn.setEnabled(True)
            cancel_btn.setText("Close")
            if not bundle_path:
                status_label.setText(f"Failed: {error}")
                return
            status_label.setText("Bundle created:")
            path_box.setPlainText(str(bundle_path))
            path_box.setVisible(True)

        create_btn.clicked.connect(_on_create)
        dlg.exec()

    def showEvent(self, event):
        """Called when the widget becomes visible - resize to compact size"""
        super().showEvent(event)
        # _lay_out_grid() ran once at construction time, before this screen had ever been
        # sized inside the stacked widget, so it read a too-small fallback viewport width.
        # Switching stacked-widget pages doesn't fire resizeEvent (the widget's size doesn't
        # actually change), so re-run it here now that we're visible - same reason
        # Dashboard's _lay_out_grid() is called from its own showEvent. Deferred via
        # singleShot(0) rather than called directly: showEvent can fire before the scroll
        # area's viewport has actually been resized to its final width (confirmed - reading
        # it synchronously here can still see a stale, too-small value), so this waits for
        # the current event loop pass to finish settling layout first.
        if hasattr(self, "_button_grid"):
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, self._lay_out_grid)
        try:
            main_window = self.window()
            if main_window:
                from PySide6.QtCore import QSize
                # Only set minimum size - DO NOT RESIZE
                main_window.setMaximumSize(QSize(16777215, 16777215))
                set_responsive_minimum(main_window, min_width=960, min_height=420)
                # DO NOT resize - let window stay at current size
        except Exception:
            pass