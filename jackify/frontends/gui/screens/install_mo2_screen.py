"""
Install MO2 Screen

Downloads and configures a standalone Mod Organizer 2 instance via
MO2SetupService. No Wabbajack modlist required.
"""

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QGridLayout, QTextEdit, QCheckBox,
    QMessageBox, QSizePolicy,
)
from PySide6.QtCore import Qt, QThread, Signal, QSize

from jackify.backend.models.configuration import SystemInfo
from jackify.backend.services.automated_prefix_service import AutomatedPrefixService
from jackify.shared.errors import mo2_setup_failed
from jackify.shared.progress_models import FileProgress, OperationType
from ..dialogs.existing_setup_dialog import prompt_existing_setup_dialog
from ..services.message_service import MessageService
from ..shared_theme import JACKIFY_COLOR_BLUE
from ..utils import set_responsive_minimum, browse_directory
from .screen_focus_reclaim import FocusReclaimMixin, STEAM_RESTART_SENTINEL
from ..widgets.progress_indicator import OverallProgressIndicator
from ..widgets.file_progress_list import FileProgressList
from .screen_back_mixin import ScreenBackMixin
from ..mixins.thread_lifecycle_mixin import ThreadLifecycleMixin

logger = logging.getLogger(__name__)


class MO2SetupWorker(QThread):
    """Background worker for standalone MO2 setup"""

    progress_update = Signal(str)
    log_output = Signal(str)
    setup_complete = Signal(bool, object, str)  # success, app_id (int|None), error_msg

    def __init__(self, install_dir: Path, shortcut_name: str, existing_appid: int | None = None):
        super().__init__()
        self.install_dir = install_dir
        self.shortcut_name = shortcut_name
        self.existing_appid = existing_appid

    def run(self):
        from jackify.backend.services.mo2_setup_service import MO2SetupService

        def _progress(msg: str):
            if self.isInterruptionRequested():
                return
            self.progress_update.emit(msg)
            self.log_output.emit(msg)

        try:
            service = MO2SetupService()
            success, app_id, error_msg = service.setup_mo2(
                install_dir=self.install_dir,
                shortcut_name=self.shortcut_name,
                existing_appid=self.existing_appid,
                progress_callback=_progress,
                should_cancel=self.isInterruptionRequested,
            )
            if self.isInterruptionRequested():
                self.setup_complete.emit(False, None, "MO2 setup cancelled.")
                return
            self.setup_complete.emit(success, app_id, error_msg or "")
        except Exception as e:
            logger.exception("Unhandled exception in MO2 setup worker")
            self.setup_complete.emit(False, None, str(e))


class InstallMO2Screen(ThreadLifecycleMixin, ScreenBackMixin, FocusReclaimMixin, QWidget):
    """Standalone MO2 setup screen"""

    resize_request = Signal(str)

    def __init__(
        self,
        stacked_widget=None,
        additional_tasks_index: int = 3,
        system_info: Optional[SystemInfo] = None,
    ):
        super().__init__()
        self.stacked_widget = stacked_widget
        self.main_menu_index = additional_tasks_index
        self.additional_tasks_index = additional_tasks_index
        self.system_info = system_info or SystemInfo(is_steamdeck=False)
        self.worker = None

        self._user_manually_scrolled = False
        self._was_at_bottom = True

        from jackify.shared.paths import get_jackify_logs_dir
        self.log_path = get_jackify_logs_dir() / "MO2_Install_workflow.log"
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)

        self.progress_indicator = OverallProgressIndicator(show_progress_bar=False)
        self.progress_indicator.set_status("Ready", 0)

        self.file_progress_list = FileProgressList()

        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        main_layout.setContentsMargins(50, 50, 50, 0)
        main_layout.setSpacing(12)

        self._setup_header(main_layout)
        self._setup_upper_section(main_layout)
        self._setup_status_banner(main_layout)
        self._setup_console(main_layout)
        self._setup_buttons(main_layout)

    def _setup_header(self, layout):
        header_layout = QVBoxLayout()
        header_layout.setSpacing(1)

        title = QLabel("<b>Setup Mod Organizer 2</b>")
        title.setStyleSheet(f"font-size: 20px; color: {JACKIFY_COLOR_BLUE}; margin: 0px; padding: 0px;")
        title.setAlignment(Qt.AlignHCenter)
        title.setMaximumHeight(30)
        header_layout.addWidget(title)

        desc = QLabel("Download and configure a standalone MO2 instance with a Proton prefix")
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #ccc; margin: 0px; padding: 0px;")
        desc.setAlignment(Qt.AlignHCenter)
        desc.setMaximumHeight(40)
        header_layout.addWidget(desc)

        header_widget = QWidget()
        header_widget.setLayout(header_layout)
        header_widget.setMaximumHeight(75)
        layout.addWidget(header_widget)

    def _setup_upper_section(self, layout):
        upper_hbox = QHBoxLayout()
        upper_hbox.setContentsMargins(0, 0, 0, 0)
        upper_hbox.setSpacing(16)

        # Left: form
        form_widget = self._build_form_widget()
        upper_hbox.addWidget(form_widget, stretch=11)

        # Right: activity window
        activity_header = QLabel("<b>[Activity]</b>")
        activity_header.setStyleSheet(
            f"color: {JACKIFY_COLOR_BLUE}; font-size: 13px; margin-bottom: 2px;"
        )
        activity_header.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self.file_progress_list.setMinimumSize(QSize(300, 20))
        self.file_progress_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        activity_vbox = QVBoxLayout()
        activity_vbox.setContentsMargins(0, 0, 0, 0)
        activity_vbox.setSpacing(2)
        activity_vbox.addWidget(activity_header)
        activity_vbox.addWidget(self.file_progress_list, stretch=1)

        activity_widget = QWidget()
        activity_widget.setLayout(activity_vbox)
        activity_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        upper_hbox.addWidget(activity_widget, stretch=9)

        upper_section = QWidget()
        upper_section.setLayout(upper_hbox)
        upper_section.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        upper_section.setMaximumHeight(240)
        layout.addWidget(upper_section)

    def _build_form_widget(self):
        form_vbox = QVBoxLayout()
        form_vbox.setAlignment(Qt.AlignTop)
        form_vbox.setContentsMargins(0, 0, 0, 0)
        form_vbox.setSpacing(8)

        options_header = QLabel("<b>[Options]</b>")
        options_header.setStyleSheet(
            f"color: {JACKIFY_COLOR_BLUE}; font-size: 13px; font-weight: bold;"
        )
        options_header.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form_vbox.addWidget(options_header)

        form_grid = QGridLayout()
        form_grid.setHorizontalSpacing(12)
        form_grid.setVerticalSpacing(8)
        form_grid.setContentsMargins(0, 0, 0, 0)

        # Shortcut name
        form_grid.addWidget(QLabel("Shortcut Name:"), 0, 0, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        self.shortcut_name_edit = QLineEdit("Mod Organizer 2")
        self.shortcut_name_edit.setMaximumHeight(25)
        form_grid.addWidget(self.shortcut_name_edit, 0, 1)

        # Install directory
        form_grid.addWidget(QLabel("Install Directory:"), 1, 0, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        default_dir = str(Path.home() / "ModOrganizer2")
        self.install_dir_edit = QLineEdit(default_dir)
        self.install_dir_edit.setMaximumHeight(25)

        browse_btn = QPushButton("Browse")
        browse_btn.setFixedSize(80, 25)
        browse_btn.clicked.connect(self._browse_folder)

        dir_hbox = QHBoxLayout()
        dir_hbox.addWidget(self.install_dir_edit)
        dir_hbox.addWidget(browse_btn)
        form_grid.addLayout(dir_hbox, 1, 1)

        form_vbox.addLayout(form_grid)

        info = QLabel(
            "Jackify will download the latest Mod Organizer 2 release from GitHub, extract it to the "
            "chosen directory, add it as a non-Steam game, and configure a Proton prefix automatically. "
            "Steam will be restarted during this process."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #999; font-size: 11px;")
        form_vbox.addWidget(info)

        form_widget = QWidget()
        form_widget.setLayout(form_vbox)
        form_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        return form_widget

    def _setup_status_banner(self, layout):
        banner_row = QHBoxLayout()
        banner_row.setContentsMargins(0, 0, 0, 0)
        banner_row.setSpacing(8)
        banner_row.addWidget(self.progress_indicator, 1)
        banner_row.addStretch()

        self.show_details_checkbox = QCheckBox("Show details")
        self.show_details_checkbox.setChecked(False)
        self.show_details_checkbox.toggled.connect(self._on_show_details_toggled)
        banner_row.addWidget(self.show_details_checkbox)

        banner_widget = QWidget()
        banner_widget.setLayout(banner_row)
        banner_widget.setMaximumHeight(45)
        banner_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout.addWidget(banner_widget)

    def _setup_console(self, layout):
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self.console.setMinimumHeight(50)
        self.console.setMaximumHeight(1000)
        self.console.setFontFamily('monospace')
        self.console.setVisible(False)

        scrollbar = self.console.verticalScrollBar()
        scrollbar.sliderPressed.connect(lambda: setattr(self, '_user_manually_scrolled', True))
        scrollbar.sliderReleased.connect(lambda: setattr(self, '_user_manually_scrolled', False))
        scrollbar.valueChanged.connect(self._on_scrollbar_value_changed)

        layout.addWidget(self.console, stretch=1)

    def _on_scrollbar_value_changed(self):
        scrollbar = self.console.verticalScrollBar()
        self._was_at_bottom = scrollbar.value() >= scrollbar.maximum() - 1

    def _setup_buttons(self, layout):
        btn_row = QHBoxLayout()
        btn_row.setAlignment(Qt.AlignHCenter)

        self.start_btn = QPushButton("Start Setup")
        self.start_btn.setFixedHeight(35)
        self.start_btn.clicked.connect(self._start_setup)
        btn_row.addWidget(self.start_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setFixedHeight(35)
        self.cancel_btn.clicked.connect(self._go_back)
        btn_row.addWidget(self.cancel_btn)

        btn_widget = QWidget()
        btn_widget.setLayout(btn_row)
        btn_widget.setMaximumHeight(50)
        layout.addWidget(btn_widget)

    def _on_show_details_toggled(self, checked):
        self.console.setVisible(checked)
        if checked:
            self.console.setMinimumHeight(200)
            self.console.setMaximumHeight(16777215)
            self.console.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            self.resize_request.emit("expand")
        else:
            self.console.setMinimumHeight(0)
            self.console.setMaximumHeight(0)
            self.console.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            self.resize_request.emit("compact")

    def _browse_folder(self):
        folder = browse_directory(self, "Select MO2 Installation Folder", str(Path.home()))
        if folder:
            self.install_dir_edit.setText(folder)

    # ------------------------------------------------------------------
    # Activity window helpers
    # ------------------------------------------------------------------

    # Maps a substring of the progress message to (item_id, display_label, OperationType, percent)
    _ACTIVITY_MAP = [
        ("Fetching latest MO2",     "fetch",    "Fetching release info",              OperationType.UNKNOWN,  0.0),
        ("Downloading ",            "download", "Downloading MO2 archive",            OperationType.DOWNLOAD, 0.0),
        ("Extracting to ",          "extract",  "Extracting archive",                 OperationType.EXTRACT,  0.0),
        ("MO2 installed at",        "extract",  "Extracting archive",                 OperationType.EXTRACT,  100.0),
        ("Creating Steam shortcut", "prefix",   "Creating Steam shortcut & prefix",   OperationType.INSTALL,  0.0),
        ("MO2 setup complete",      "complete", "Setup complete",                     OperationType.INSTALL,  100.0),
    ]

    def _on_activity_progress(self, message: str):
        for trigger, item_id, label, op_type, pct in self._ACTIVITY_MAP:
            if trigger in message:
                fp = FileProgress(
                    filename=label,
                    operation=op_type,
                    percent=pct,
                    current_size=0,
                    total_size=0,
                )
                self.file_progress_list.update_files([fp])
                break

    # ------------------------------------------------------------------

    def _start_setup(self):
        install_dir_text = self.install_dir_edit.text().strip()
        if not install_dir_text:
            MessageService.warning(self, "No Directory", "Please select an installation directory.")
            return

        install_dir = Path(install_dir_text).resolve()
        shortcut_name = self.shortcut_name_edit.text().strip() or "Mod Organizer 2"

        confirm = MessageService.question(
            self,
            "Confirm MO2 Setup",
            f"Install Mod Organizer 2 to:\n{install_dir}\n\n"
            "Jackify will download MO2, add it to Steam, and configure a Proton prefix.\n"
            "Steam will be restarted during this process.\n\nContinue?",
            safety_level="medium",
        )
        if confirm != QMessageBox.Yes:
            return

        existing_appid = None
        candidate_exe = install_dir / "ModOrganizer.exe"
        prefix_service = AutomatedPrefixService()
        conflict_result = prefix_service.handle_existing_shortcut_conflict(
            shortcut_name,
            str(candidate_exe),
            str(install_dir),
        )
        if isinstance(conflict_result, list):
            action, new_name = prompt_existing_setup_dialog(
                self,
                window_title="Existing Modlist Setup Detected",
                heading="Use Existing Setup or Create a New Shortcut",
                body=(
                    "Jackify found an existing Steam shortcut for this Mod Organizer 2 setup.\n\n"
                    "Choose 'Use Existing Setup' to reuse the current Steam shortcut, or enter a "
                    "different name to create a separate shortcut."
                ),
                existing_name=conflict_result[0].get("name", shortcut_name),
                requested_name=shortcut_name,
                install_dir=str(install_dir),
                field_label="New shortcut name",
                reuse_label="Use Existing Setup",
                new_label="Create New Shortcut",
                cancel_label="Cancel",
            )
            if action == "reuse":
                existing_appid = conflict_result[0].get("appid")
                if not existing_appid:
                    MessageService.warning(self, "Existing Setup Not Found", "Jackify could not determine the Steam AppID for the existing shortcut.")
                    return
                self.console.append(f"Reusing existing Steam shortcut '{shortcut_name}'.")
            elif action == "new":
                if not new_name:
                    MessageService.warning(self, "Invalid Name", "Please enter a valid shortcut name.")
                    return
                if new_name == shortcut_name:
                    MessageService.warning(self, "Same Name", "Please enter a different name to create a separate shortcut.")
                    return
                shortcut_name = new_name
                self.shortcut_name_edit.setText(new_name)
            else:
                self.console.append("Shortcut creation cancelled by user")
                return

        self.console.clear()
        self.file_progress_list.clear()
        self.file_progress_list.start_cpu_tracking()

        from jackify.backend.handlers.logging_handler import LoggingHandler
        log_handler = LoggingHandler()
        log_handler.rotate_log_file_per_run(self.log_path, backup_count=5)

        self._write_to_log_file("=" * 60)
        self._write_to_log_file("MO2 Setup Started")
        self._write_to_log_file(f"Install directory: {install_dir}")
        self._write_to_log_file(f"Shortcut name: {shortcut_name}")
        if existing_appid:
            self._write_to_log_file(f"Existing AppID: {existing_appid}")
        self._write_to_log_file("=" * 60)

        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.setText("Cancel Setup")
        self.shortcut_name_edit.setEnabled(False)
        self.install_dir_edit.setEnabled(False)
        self.progress_indicator.set_status("Starting...", 0)

        self.worker = MO2SetupWorker(install_dir, shortcut_name, int(existing_appid) if existing_appid else None)
        self.worker.progress_update.connect(self._on_progress_update)
        self.worker.progress_update.connect(self._on_activity_progress)
        self.worker.log_output.connect(self._on_log_output)
        self.worker.setup_complete.connect(self._on_setup_complete)
        self.worker.start()

    def _on_progress_update(self, message: str):
        self.progress_indicator.set_status(message, 0)
        if STEAM_RESTART_SENTINEL in message:
            self._start_focus_reclaim_retries()

    def _on_log_output(self, message: str):
        self._write_to_log_file(message)
        scrollbar = self.console.verticalScrollBar()
        was_at_bottom = scrollbar.value() >= scrollbar.maximum() - 1
        self.console.append(message)
        if was_at_bottom and not self._user_manually_scrolled:
            scrollbar.setValue(scrollbar.maximum())

    def _write_to_log_file(self, message: str):
        try:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            with open(self.log_path, 'a', encoding='utf-8') as f:
                f.write(f"[{timestamp}] {message}\n")
        except Exception:
            pass

    def _on_setup_complete(self, success: bool, app_id, error_msg: str):
        self.file_progress_list.stop_cpu_tracking()

        if success:
            self.progress_indicator.set_status("Setup complete!", 100)
            MessageService.information(
                self,
                "MO2 Setup Complete",
                f"Mod Organizer 2 has been installed and configured.\n\n"
                f"Steam AppID: {app_id}\n\n"
                "Launch MO2 from your Steam library.",
            )
            self.install_dir_edit.setText(str(Path.home() / "ModOrganizer2"))
            self.shortcut_name_edit.setText("Mod Organizer 2")
        else:
            self.progress_indicator.set_status("Setup failed", 0)
            MessageService.show_error(self, mo2_setup_failed(error_msg or "Setup failed."))

        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.setText("Cancel")
        self.shortcut_name_edit.setEnabled(True)
        self.install_dir_edit.setEnabled(True)
        if self.worker is not None:
            try:
                self.worker.deleteLater()
            except Exception:
                pass
            self.worker = None

    def _go_back(self):
        if self.worker and self.worker.isRunning():
            reply = MessageService.question(
                self,
                "MO2 Setup In Progress",
                "MO2 setup is still running. Leave this screen and cancel setup?",
                critical=False,
                safety_level="medium",
            )
            if reply != QMessageBox.Yes:
                return
            self.cleanup_processes()
        self.collapse_show_details_before_leave()
        self.go_back()

    def cleanup_processes(self):
        self._stop_focus_reclaim()
        try:
            self.file_progress_list.stop_cpu_tracking()
        except Exception:
            pass

    def reset_screen_to_defaults(self):
        self.file_progress_list.clear()
        self.console.clear()
        self.progress_indicator.set_status("Ready", 0)
        self.force_collapsed_details_state()

    def showEvent(self, event):
        super().showEvent(event)
        self.force_collapsed_details_state()
        try:
            main_window = self.window()
            if main_window:
                main_window.setMaximumSize(QSize(16777215, 16777215))
                set_responsive_minimum(main_window, min_width=960, min_height=420)
        except Exception:
            pass
