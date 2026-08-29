"""
Downgrade Game Version screen.

Drives jackify-game-downgrader (bundled external tool, see tool_registry.py) to downgrade a
Steam install of Skyrim SE or Fallout 4 to a script-extender-compatible build. The Steam login
itself (password, Steam Guard) happens through native dialogs backed by
GameDowngradePromptDriver rather than a terminal - see that module for why a plain piped stdin
is sufficient. Available from Additional Tasks.
"""

import logging
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QSizePolicy, QTabWidget, QTextEdit, QVBoxLayout,
    QWidget,
)

from jackify.frontends.gui.mixins.thread_lifecycle_mixin import ThreadLifecycleMixin
from jackify.frontends.gui.services.message_service import MessageService
from jackify.frontends.gui.shared_theme import JACKIFY_COLOR_BLUE
from jackify.frontends.gui.utils import set_responsive_minimum
from jackify.frontends.gui.widgets.file_progress_list import FileProgressList
from jackify.frontends.gui.dialogs import SuccessDialog

logger = logging.getLogger(__name__)


class _AnswerDialog(QDialog):
    """Small modal for one line of input - plain text or password-masked."""

    def __init__(self, title: str, label: str, password: bool = False, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(360)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(label))
        self._field = QLineEdit()
        if password:
            self._field.setEchoMode(QLineEdit.Password)
        layout.addWidget(self._field)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._field.setFocus()

    def value(self) -> str:
        return self._field.text()


class _LoginDialog(QDialog):
    """Modal asking for both Steam username and password in one go."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Steam Login")
        self.setMinimumWidth(360)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Enter your Steam login for steamcmd:"))

        note = QLabel("Jackify never stores or logs your Steam credentials.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #aaa; font-size: 11px;")
        layout.addWidget(note)

        layout.addWidget(QLabel("Username:"))
        self._username_field = QLineEdit()
        layout.addWidget(self._username_field)

        layout.addWidget(QLabel("Password:"))
        self._password_field = QLineEdit()
        self._password_field.setEchoMode(QLineEdit.Password)
        layout.addWidget(self._password_field)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._username_field.setFocus()

    def values(self) -> tuple:
        return self._username_field.text().strip(), self._password_field.text()


class GameDowngradeScreen(ThreadLifecycleMixin, QWidget):
    """Setup + run screen for the Game Version Downgrader tool."""

    def __init__(self, stacked_widget=None, additional_tasks_index: int = 3, parent=None):
        super().__init__(parent)
        self.stacked_widget = stacked_widget
        self.additional_tasks_index = additional_tasks_index
        self._driver = None
        self._binary_path: Optional[str] = None
        self._python3: Optional[str] = None
        self._user_cancelled = False
        self._recent_log_lines: list = []
        self._run_description = ""
        self._run_started_at = 0.0
        self._was_dry_run = False
        self._is_restore = False
        self._setup_ui()

    def _setup_ui(self):
        main_vbox = QVBoxLayout(self)
        main_vbox.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        main_vbox.setContentsMargins(50, 50, 50, 0)
        main_vbox.setSpacing(12)

        # --- Header ---
        header_widget = QWidget()
        header_layout = QVBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(2)

        title = QLabel("<b>Downgrade Game Version</b>")
        title.setStyleSheet(f"font-size: 20px; color: {JACKIFY_COLOR_BLUE};")
        title.setAlignment(Qt.AlignHCenter)
        header_layout.addWidget(title)

        header_layout.addSpacing(10)

        desc = QLabel(
            "Downgrades a Steam install of Skyrim SE or Fallout 4 to an older, "
            "script-extender-compatible build. Requires your Steam login - your "
            "password/Steam Guard code goes straight to steamcmd (Valve's own tool); "
            "Jackify never stores or logs it."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #ccc; font-size: 13px;")
        desc.setAlignment(Qt.AlignHCenter)
        desc.setMaximumHeight(50)
        header_layout.addWidget(desc)

        header_layout.addSpacing(12)
        header_widget.setLayout(header_layout)
        header_widget.setFixedHeight(120)
        main_vbox.addWidget(header_widget)

        # --- Upper section: form (left) + tabs (right) ---
        upper_hbox = QHBoxLayout()
        upper_hbox.setContentsMargins(0, 0, 0, 0)
        upper_hbox.setSpacing(16)

        user_config_vbox = QVBoxLayout()
        user_config_vbox.setAlignment(Qt.AlignTop)
        user_config_vbox.setSpacing(4)

        options_header = QLabel("<b>[Options]</b>")
        options_header.setStyleSheet(f"color: {JACKIFY_COLOR_BLUE}; font-size: 13px; font-weight: bold;")
        options_header.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        user_config_vbox.addWidget(options_header)

        form_grid = QGridLayout()
        form_grid.setHorizontalSpacing(12)
        form_grid.setVerticalSpacing(6)
        form_grid.setContentsMargins(0, 0, 0, 0)

        game_label = QLabel("Game:")
        self._game_combo = QComboBox()
        self._game_combo.setMinimumWidth(220)
        self._game_combo.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        form_grid.addWidget(game_label, 0, 0, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        form_grid.addWidget(self._game_combo, 0, 1, alignment=Qt.AlignLeft)

        version_label = QLabel("Downgrade to:")
        self._version_combo = QComboBox()
        self._version_combo.setMinimumWidth(220)
        self._version_combo.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        form_grid.addWidget(version_label, 1, 0, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        form_grid.addWidget(self._version_combo, 1, 1, alignment=Qt.AlignLeft)

        self._dry_run_check = QCheckBox("Dry run (preview only, changes nothing)")
        self._dry_run_check.setChecked(False)
        form_grid.addWidget(self._dry_run_check, 2, 1, alignment=Qt.AlignLeft)

        self._backup_check = QCheckBox("Create full backup before downgrading (recommended)")
        self._backup_check.setChecked(True)
        form_grid.addWidget(self._backup_check, 3, 1, alignment=Qt.AlignLeft)

        form_widget = QWidget()
        form_widget.setLayout(form_grid)
        form_widget.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        form_row = QHBoxLayout()
        form_row.setContentsMargins(0, 0, 0, 0)
        form_row.addWidget(form_widget)
        form_row.addStretch(1)
        user_config_vbox.addLayout(form_row)

        user_config_vbox.addSpacing(10)

        restore_row = QHBoxLayout()
        restore_row.setContentsMargins(0, 0, 0, 0)
        restore_row.setSpacing(8)
        restore_label = QLabel("Already downgraded this game?")
        restore_label.setStyleSheet("color: #999; font-size: 12px;")
        self._restore_btn = QPushButton("Restore Previous Downgrade")
        self._restore_btn.clicked.connect(self._on_restore)
        restore_row.addWidget(restore_label)
        restore_row.addWidget(self._restore_btn)
        restore_row.addStretch(1)
        user_config_vbox.addLayout(restore_row)

        user_config_vbox.addSpacing(10)

        note = QLabel(
            "<i>Jackify will close Steam automatically before starting and restart it "
            "afterward. If the game itself is still running outside Steam, you'll be asked "
            "to close it manually. steamcmd keeps its own local login session once you've "
            "signed in once, the same as staying logged into Steam.</i>"
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #aaa; font-size: 12px;")
        note.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        user_config_vbox.addWidget(note)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setAlignment(Qt.AlignHCenter)

        self._start_btn = QPushButton("Start")
        self._start_btn.clicked.connect(self._on_start)
        btn_row.addWidget(self._start_btn)

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self._on_cancel)
        self._cancel_btn.setVisible(False)
        btn_row.addWidget(self._cancel_btn)

        self._back_btn = QPushButton("Back")
        self._back_btn.clicked.connect(self._go_back)
        btn_row.addWidget(self._back_btn)

        btn_row.insertStretch(0, 1)
        btn_row.addStretch(1)

        self.show_details_checkbox = QCheckBox("Show details")
        self.show_details_checkbox.setChecked(False)
        self.show_details_checkbox.setToolTip("Toggle between activity summary and detailed console output")
        self.show_details_checkbox.toggled.connect(self._on_show_details_toggled)

        btn_row_widget = QWidget()
        btn_row_widget.setLayout(btn_row)
        btn_row_widget.setMaximumHeight(50)
        self.btn_row_widget = btn_row_widget

        user_config_widget = QWidget()
        user_config_widget.setLayout(user_config_vbox)
        user_config_widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

        # Right: Activity + Process Monitor tabs. Activity mirrors the same live, single-row
        # per-item progress display used for modlist/archive downloads (FileProgressList) -
        # not a scrolling text log - since the downgrader's own depot-transfer spinner is a
        # single-line, in-place progress update, not a stream of discrete events.
        self._activity_list = FileProgressList()
        self._activity_list.setMinimumSize(QSize(300, 20))
        self._activity_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.process_monitor = QTextEdit()
        self.process_monitor.setReadOnly(True)
        self.process_monitor.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self.process_monitor.setMinimumSize(QSize(300, 20))
        self.process_monitor.setStyleSheet(
            f"background: #222; color: {JACKIFY_COLOR_BLUE}; "
            "font-family: monospace; font-size: 11px; border: 1px solid #444;"
        )

        process_vbox = QVBoxLayout()
        process_vbox.setContentsMargins(0, 0, 0, 0)
        process_vbox.setSpacing(2)
        process_vbox.addWidget(self.process_monitor)
        process_monitor_widget = QWidget()
        process_monitor_widget.setLayout(process_vbox)
        process_monitor_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.process_monitor_widget = process_monitor_widget

        self.activity_tabs = QTabWidget()
        self.activity_tabs.setStyleSheet(
            "QTabWidget::pane { background: #222; border: 1px solid #444; } "
            "QTabBar::tab { background: #222; color: #ccc; padding: 6px 16px; } "
            "QTabBar::tab:selected { background: #333; color: #3fd0ea; } "
            "QTabWidget { margin: 0px; padding: 0px; } "
            "QTabBar { margin: 0px; padding: 0px; }"
        )
        self.activity_tabs.setContentsMargins(0, 0, 0, 0)
        self.activity_tabs.setDocumentMode(False)
        self.activity_tabs.setTabPosition(QTabWidget.North)

        self.activity_tabs.addTab(self._activity_list, "Activity")
        self.activity_tabs.addTab(process_monitor_widget, "Process Monitor")

        upper_hbox.addWidget(user_config_widget, stretch=11)
        upper_hbox.addWidget(self.activity_tabs, stretch=9)
        upper_hbox.setAlignment(Qt.AlignTop)

        upper_section_widget = QWidget()
        upper_section_widget.setLayout(upper_hbox)
        upper_section_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        upper_section_widget.setMaximumHeight(280)
        main_vbox.addWidget(upper_section_widget)

        # --- Status banner ---
        self._status_banner = QLabel("Ready to downgrade")
        self._status_banner.setAlignment(Qt.AlignCenter)
        self._status_banner.setStyleSheet(f"""
            background-color: #2a2a2a;
            color: {JACKIFY_COLOR_BLUE};
            padding: 6px 8px;
            border-radius: 4px;
            font-weight: bold;
            font-size: 13px;
        """)
        self._status_banner.setMaximumHeight(34)
        self._status_banner.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        banner_row = QHBoxLayout()
        banner_row.setContentsMargins(0, 0, 0, 0)
        banner_row.setSpacing(8)
        banner_row.addWidget(self._status_banner, 1)
        banner_row.addStretch()
        banner_row.addWidget(self.show_details_checkbox)
        banner_row_widget = QWidget()
        banner_row_widget.setLayout(banner_row)
        banner_row_widget.setMaximumHeight(45)
        banner_row_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        main_vbox.addWidget(banner_row_widget)

        # --- Console (hidden by default) ---
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self.console.setMinimumHeight(0)
        self.console.setMaximumHeight(0)
        self.console.setFontFamily("monospace")

        main_vbox.addWidget(self.console, stretch=1)
        main_vbox.addWidget(btn_row_widget, alignment=Qt.AlignHCenter)

        self.main_overall_vbox = main_vbox
        self.setLayout(main_vbox)

        self._top_timer = QTimer(self)
        self._top_timer.timeout.connect(self._update_top_panel)
        self._top_timer.start(2000)

        self._game_combo.currentIndexChanged.connect(self._on_game_changed)

    def showEvent(self, event):
        super().showEvent(event)
        if self._driver is None and self._cancel_btn.isVisible():
            # Returning to the screen after it was navigated away from mid-run (hideEvent
            # below cancels and parks the driver, so no finished signal will ever arrive to
            # reset this) - fall back to idle instead of staying stuck on Cancel/disabled-Back.
            self._reset_to_idle_ui()
            self._status_banner.setText("Ready to downgrade")
        set_responsive_minimum(self.window(), min_width=960, min_height=520)
        if self._game_combo.count() == 0:
            self._load_games()

    def hideEvent(self, event):
        # ThreadLifecycleMixin's hideEvent (invoked via super() below) disconnects the
        # driver's signals and hands it to the background registry the moment this screen is
        # navigated away from - cancel a still-running download first, otherwise it keeps
        # running unmanaged (and will still restart Steam on its own) with no UI left able to
        # show or stop it.
        if self._driver:
            self._driver.cancel()
        super().hideEvent(event)

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _load_games(self):
        from jackify.backend.services.tool_registry import ToolRegistry

        binary = ToolRegistry().get_binary_path("jackify-game-downgrader")
        python3 = shutil.which("python3")
        if not binary or not python3:
            MessageService.critical(
                self, "Not Installed",
                "Game Version Downgrader is not installed. Install it from the Tools Hub, "
                "then return to this screen.",
            )
            self._start_btn.setEnabled(False)
            return

        self._binary_path = str(binary)
        self._python3 = python3

        try:
            result = subprocess.run(
                [python3, self._binary_path, "list-games"],
                capture_output=True, text=True, timeout=15,
            )
            games = []
            for line in result.stdout.splitlines():
                line = line.strip()
                if ":" in line and not line.lower().startswith("supported games"):
                    key, _, name = line.partition(":")
                    games.append((key.strip(), name.strip()))
        except Exception as e:
            logger.warning("Failed to list downgrader games: %s", e)
            games = []

        self._game_combo.clear()
        self._game_combo.addItem("Please select...", userData=None)
        for key, name in games:
            self._game_combo.addItem(name, userData=key)
        self._game_combo.setCurrentIndex(0)

    def _has_restore_state(self, game_key: str) -> bool:
        """Best-effort local check for a pending downgrade to restore, so the button can be
        greyed out up front instead of running the full Steam shutdown/restart cycle just to
        learn there was nothing to restore (that round trip previously took several minutes
        for a no-op). This reaches into game_downgrade/data/<game>/state.json, an internal
        detail of a separate tool rather than a documented interface - if that layout ever
        changes, this fails safe (treated as nothing to restore), not as an app error."""
        if not self._binary_path:
            return False
        try:
            install_dir = Path(self._binary_path).parent
            return (install_dir / "game_downgrade" / "data" / game_key / "state.json").is_file()
        except OSError:
            return False

    def _refresh_restore_availability(self):
        game_key = self._game_combo.currentData()
        enabled = bool(game_key) and self._has_restore_state(game_key)
        self._restore_btn.setEnabled(enabled)
        self._restore_btn.setToolTip("" if enabled else "No previous downgrade recorded for this game")

    def _on_game_changed(self, _index: int):
        self._version_combo.clear()
        game_key = self._game_combo.currentData()
        self._refresh_restore_availability()
        if not game_key or not self._binary_path:
            return
        try:
            result = subprocess.run(
                [self._python3, self._binary_path, "list-versions", "--game", game_key],
                capture_output=True, text=True, timeout=15,
            )
            versions = [
                line.strip() for line in result.stdout.splitlines()
                if line.strip() and not line.lower().startswith("available downgrade targets")
            ]
        except Exception as e:
            logger.warning("Failed to list downgrader versions: %s", e)
            versions = []
        # list-versions already outputs newest-first, so the most likely-wanted target
        # ends up as the default (first/selected) entry without any reordering here.
        self._version_combo.addItems(versions)

    def _on_start(self):
        game_key = self._game_combo.currentData()
        version = self._version_combo.currentText()
        if not game_key:
            MessageService.warning(self, "No Game Selected", "Select a game first.")
            return
        if not version:
            MessageService.warning(self, "No Version Selected", "Select a version to downgrade to first.")
            return

        reply = MessageService.question(
            self,
            "Restart Steam?",
            "Steam must be closed before the downgrader can run. Steam will be shut down now "
            "and any running game will be closed; Jackify will restart Steam automatically when "
            "the downgrade finishes.\n\nContinue?",
            safety_level="medium",
        )
        if reply == QMessageBox.No:
            return

        args = ["downgrade", "--game", game_key, "--version", version, "--managed-restart"]
        if self._dry_run_check.isChecked():
            args.append("--dry-run")
        elif not self._backup_check.isChecked():
            args.append("--no-backup")

        self._is_restore = False
        self._was_dry_run = self._dry_run_check.isChecked()
        self._launch_driver(args, f"{self._game_combo.currentText()} -> {version}")

    def _on_restore(self):
        game_key = self._game_combo.currentData()
        if not game_key:
            MessageService.warning(self, "No Game Selected", "Select a game first.")
            return

        reply = MessageService.question(
            self,
            "Restore Previous Version?",
            "This reverts the game to its state before the last downgrade (or just restores "
            "Steam's own update settings if no backup was kept). Steam will be shut down now "
            "and any running game will be closed; Jackify will restart Steam automatically "
            "when the restore finishes.\n\nContinue?",
            safety_level="medium",
        )
        if reply == QMessageBox.No:
            return

        self._is_restore = True
        self._was_dry_run = False
        self._launch_driver(
            ["restore", "--game", game_key, "--managed-restart"],
            f"Restore: {self._game_combo.currentText()}",
        )

    def _launch_driver(self, args: list, description: str):
        self._activity_list.clear()
        self.console.clear()
        self._recent_log_lines = []
        self._user_cancelled = False
        self._run_description = description
        self._run_started_at = time.monotonic()
        self._on_log_line(f"Starting: {description}")
        self._status_banner.setText("Starting...")
        self._start_btn.setVisible(False)
        self._restore_btn.setVisible(False)
        self._cancel_btn.setVisible(True)
        self._back_btn.setEnabled(False)
        self._game_combo.setEnabled(False)
        self._version_combo.setEnabled(False)
        self._dry_run_check.setEnabled(False)
        self._backup_check.setEnabled(False)

        from jackify.backend.services.game_downgrade_prompt_driver import GameDowngradePromptDriver

        system_info = getattr(self.window(), "system_info", None)
        self._driver = GameDowngradePromptDriver(
            self._binary_path, self._python3, args, system_info=system_info,
        )
        self._driver.log_line.connect(self._on_log_line)
        self._driver.phase_status.connect(self._set_status)
        self._driver.need_login.connect(self._on_need_login)
        self._driver.need_password.connect(self._on_need_password)
        self._driver.need_guard_code.connect(self._on_need_guard_code)
        self._driver.waiting_for_phone_approval.connect(self._on_waiting_for_phone)
        self._driver.waiting_for_process_close.connect(self._on_waiting_for_process_close)
        self._driver.depot_progress.connect(self._on_depot_progress)
        self._driver.need_generic_input.connect(self._on_need_generic_input)
        self._driver.finished.connect(self._on_finished)
        self._driver.start()

    def _set_status(self, text: str):
        """Push one line of status to all three surfaces at once - banner, Activity, console -
        so they can never drift out of sync showing three different things for the same
        moment (this screen has repeatedly regressed from ad hoc single-surface updates)."""
        self._status_banner.setText(text)
        self._activity_list.update_or_add_item(item_id="status", label=text, progress=0)
        self._append_log(text)

    def _append_log(self, text: str):
        self.console.append(text)
        self._recent_log_lines.append(text)
        del self._recent_log_lines[:-6]

    def _on_log_line(self, line: str):
        # Raw downgrader stdout, not a status transition - console/failure-detail history
        # only. Routing every line through _set_status meant a multi-line informational note
        # from the downgrader (e.g. its six-print() phone-approval explainer ending in
        # "steamcmd waits silently for it.") left only that last, out-of-context fragment on
        # the banner/Activity once the burst settled - both are single-line, overwrite-in-
        # place surfaces meant to reflect the current phase, not narrate arbitrary output.
        self._append_log(line)

    def _on_depot_progress(self, depot_id: str, percent: int, done_mb: int, total_mb: int):
        banner_text = f"Downloading depot {depot_id}: {percent}% ({done_mb}/{total_mb} MB)"
        self._activity_list.update_or_add_item(
            item_id="status", label=f"depot {depot_id}: {done_mb}/{total_mb} MB", progress=percent,
        )
        self._status_banner.setText(banner_text)
        # Keep the raw log (Show details) in step with the banner/Activity tab instead of
        # freezing on whatever line preceded the depot download - one line per real progress
        # tick (already throttled to ~1/s by the tool itself), same as engine output does for
        # modlist/archive downloads elsewhere.
        self.console.append(banner_text)
        self._recent_log_lines.append(banner_text)
        del self._recent_log_lines[:-6]

    # ------------------------------------------------------------------
    # Run - prompt handling
    # ------------------------------------------------------------------

    def _cancel_driver(self):
        # A modal prompt dialog is application-modal, so the screen's own Cancel button can't
        # be reached while one is open - its Cancel button rejecting the dialog must actually
        # cancel the run, not silently feed an empty username/password/code into steamcmd
        # (which would just fail confusingly instead of cancelling cleanly).
        if self._driver:
            self._user_cancelled = True
            self._driver.cancel()

    def _on_need_login(self):
        self._set_status("Waiting for Steam login...")
        dlg = _LoginDialog(parent=self)
        if dlg.exec() == QDialog.Accepted:
            username, password = dlg.values()
            if self._driver:
                self._driver.provide_login(username, password)
            del password
        else:
            self._cancel_driver()

    def _on_need_password(self):
        self._set_status("Waiting for Steam password...")
        dlg = _AnswerDialog("Steam Password", "Enter your Steam password:", password=True, parent=self)
        if dlg.exec() == QDialog.Accepted:
            answer = dlg.value()
            if self._driver:
                self._driver.provide_answer(answer)
            del answer
        else:
            self._cancel_driver()

    def _on_need_guard_code(self):
        self._set_status("Waiting for Steam Guard code...")
        dlg = _AnswerDialog("Steam Guard Code", "Enter the Steam Guard code from your email/authenticator:", parent=self)
        if dlg.exec() == QDialog.Accepted:
            answer = dlg.value()
            if self._driver:
                self._driver.provide_answer(answer)
        else:
            self._cancel_driver()

    def _on_waiting_for_phone(self, waiting: bool):
        if waiting:
            self._set_status("Check your phone - approve the login in the Steam Mobile app")
        else:
            self._set_status("Running...")

    def _on_waiting_for_process_close(self, label: str):
        if not label:
            # Empty label = resolved (the driver saw real output resume after this wait).
            self._set_status("Running...")
            return
        self._set_status(
            f"Waiting - close {label} to continue "
            f"(fully exit it and the downgrade will continue automatically)"
        )

    def _on_need_generic_input(self, message: str):
        self._set_status(f"Waiting for input: {message}")
        dlg = _AnswerDialog("Input Needed", f"{message}\nType a reply and press Enter:", parent=self)
        if dlg.exec() == QDialog.Accepted:
            answer = dlg.value()
            if self._driver:
                self._driver.provide_answer(answer)
        else:
            self._cancel_driver()

    def _on_cancel(self):
        self._cancel_driver()

    def _reset_to_idle_ui(self):
        self._back_btn.setEnabled(True)
        self._cancel_btn.setVisible(False)
        self._start_btn.setVisible(True)
        self._restore_btn.setVisible(True)
        self._game_combo.setEnabled(True)
        self._version_combo.setEnabled(True)
        self._dry_run_check.setEnabled(True)
        self._backup_check.setEnabled(True)
        # Whatever the last Activity row was doing (a plain status message shows as an
        # indeterminate pulsing bar - see FileProgressItem._set_indeterminate), it has no
        # more work to reflect once the run is over in any way - success, failure, or
        # cancel - so it must not keep animating after the fact.
        self._activity_list.clear()

    def _on_finished(self, returncode: int, real_changes_started: bool):
        self._reset_to_idle_ui()
        # A completed downgrade creates restore state; a completed restore clears it - refresh
        # after every run so the button reflects what actually happened, not the pre-run state.
        self._refresh_restore_availability()
        self._driver = None
        user_cancelled = self._user_cancelled
        self._user_cancelled = False

        action = "restore" if self._is_restore else "downgrade"

        if returncode == 0:
            self._status_banner.setText("Completed successfully")
            elapsed = int(time.monotonic() - self._run_started_at)
            time_taken = f"{elapsed // 60}m {elapsed % 60}s" if elapsed >= 60 else f"{elapsed}s"
            workflow_type = (
                "game_downgrade_restore" if self._is_restore
                else "game_downgrade_dry_run" if self._was_dry_run
                else "game_downgrade"
            )
            dlg = SuccessDialog(
                modlist_name=self._run_description or action.capitalize(),
                workflow_type=workflow_type,
                time_taken=time_taken,
                parent=self,
            )
            dlg.show()
            return

        if self._is_restore and not user_cancelled and any(
            "nothing to restore" in line.lower() for line in self._recent_log_lines
        ):
            self._status_banner.setText("Nothing to restore")
            MessageService.information(
                self, "Nothing to Restore",
                f"{self._game_combo.currentText()} has no recorded downgrade to undo "
                "(a dry run doesn't count - only a real downgrade leaves something to restore).",
            )
            return

        if user_cancelled:
            self._status_banner.setText("Cancelled")
            message = f"The {action} was cancelled."
        else:
            self._status_banner.setText("Ended - see details")
            detail = "\n".join(self._recent_log_lines[-6:]) if self._recent_log_lines else None
            message = f"The {action} did not complete:\n\n{detail}" if detail else (
                "The downgrader ended unexpectedly. Check the log for details."
            )

        if real_changes_started:
            message += (
                "\n\nA real (non-dry-run) downgrade was in progress and may not have finished "
                "cleanly. Open a terminal and run 'jackify-game-downgrader restore' to revert it."
            )
        MessageService.warning(self, f"{action.capitalize()} Ended", message)

    def _go_back(self):
        if self._driver:
            action = "Restore" if self._is_restore else "Downgrade"
            MessageService.warning(self, f"{action} In Progress", "Cancel the current run first.")
            return
        if self.stacked_widget:
            self.stacked_widget.setCurrentIndex(self.additional_tasks_index)

    def _on_show_details_toggled(self, checked: bool):
        main_window = self.window()
        is_steamdeck = bool(
            main_window and getattr(getattr(main_window, "system_info", None), "is_steamdeck", False)
        )

        if checked:
            self.console.setVisible(True)
            self.console.setMinimumHeight(200)
            self.console.setMaximumHeight(16777215)
            self.console.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            if not main_window or is_steamdeck:
                return
            main_window.showNormal()
            main_window.setMaximumHeight(16777215)
            main_window.setMinimumHeight(0)
            expanded_min = 900
            current_size = main_window.size()
            main_window.setMinimumHeight(expanded_min)
            main_window.resize(current_size.width(), max(expanded_min, current_size.height()))
            self.main_overall_vbox.invalidate()
            self.updateGeometry()
        else:
            self.console.setVisible(False)
            self.console.setMinimumHeight(0)
            self.console.setMaximumHeight(0)
            self.console.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            if not main_window or is_steamdeck:
                return
            compact_height = 620
            main_window.showNormal()
            set_responsive_minimum(main_window, min_width=960, min_height=compact_height)
            main_window.setMaximumSize(QSize(16777215, 16777215))
            current_size = main_window.size()
            main_window.resize(current_size.width(), compact_height)

    def _update_top_panel(self):
        try:
            result = subprocess.run(
                ["ps", "-eo", "pcpu,pmem,comm,args"],
                stdout=subprocess.PIPE, text=True, timeout=2
            )
            lines = result.stdout.splitlines()
            header = "CPU%\tMEM%\tCOMMAND"
            filtered = [header]
            rows = []
            for line in lines[1:]:
                ll = line.lower()
                if ("steamcmd" in ll or "jackify-game-downgrader" in ll) and "jackify-gui.py" not in ll:
                    cols = line.strip().split(None, 3)
                    if len(cols) >= 3:
                        rows.append(cols)
            rows.sort(key=lambda x: float(x[0]), reverse=True)
            for cols in rows:
                filtered.append("\t".join(cols))
            if len(filtered) == 1:
                filtered.append("[No relevant processes]")
            self.process_monitor.setPlainText("\n".join(filtered))
        except Exception as e:
            self.process_monitor.setPlainText(f"[process info unavailable: {e}]")
