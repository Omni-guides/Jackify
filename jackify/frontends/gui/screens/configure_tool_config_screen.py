"""
Configure Tool Compatibility screen.

Applies Wine registry settings for modding tools (xEdit, Pandora, DLL overrides)
to an existing configured modlist prefix. Available from Additional Tasks.
"""

import logging
import subprocess
from typing import Optional

from PySide6.QtCore import Qt, QSize, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QLabel,
    QPushButton, QSizePolicy, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

from jackify.frontends.gui.mixins.thread_lifecycle_mixin import ThreadLifecycleMixin
from jackify.frontends.gui.services.message_service import MessageService
from jackify.frontends.gui.shared_theme import JACKIFY_COLOR_BLUE
from jackify.frontends.gui.utils import set_responsive_minimum

logger = logging.getLogger(__name__)


class _ShortcutLoaderThread(QThread):
    finished_signal = Signal(list)   # list of {"name": str, "appid": str}
    error_signal = Signal(str)

    def run(self):
        try:
            from jackify.backend.handlers.modlist_handler import ModlistHandler
            handler = ModlistHandler()
            discovered = handler.discover_executable_shortcuts("ModOrganizer.exe")
            shortcuts = [
                {"name": m.get("name", "Unknown"), "appid": str(m.get("appid", ""))}
                for m in discovered
                if m.get("appid")
            ]
            self.finished_signal.emit(shortcuts)
        except Exception as e:
            self.error_signal.emit(str(e))


class _ApplyThread(QThread):
    log_signal = Signal(str)
    finished_signal = Signal(bool)

    def __init__(self, appid: str):
        super().__init__()
        self._appid = appid

    def run(self):
        from jackify.backend.services.tool_config_service import apply_tool_config_for_appid
        ok = apply_tool_config_for_appid(self._appid, log=self.log_signal.emit)
        self.finished_signal.emit(ok)


class ConfigureToolConfigScreen(ThreadLifecycleMixin, QWidget):
    """Apply tool compatibility settings to an existing modlist prefix."""

    def __init__(self, stacked_widget=None, additional_tasks_index: int = 3, parent=None):
        super().__init__(parent)
        self.stacked_widget = stacked_widget
        self.additional_tasks_index = additional_tasks_index
        self._shortcuts: list = []
        self._loader: Optional[_ShortcutLoaderThread] = None
        self._apply_thread: Optional[_ApplyThread] = None
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

        title = QLabel("<b>Configure Tool Compatibility</b>")
        title.setStyleSheet(f"font-size: 20px; color: {JACKIFY_COLOR_BLUE};")
        title.setAlignment(Qt.AlignHCenter)
        header_layout.addWidget(title)

        header_layout.addSpacing(10)

        desc = QLabel(
            "Applies Wine registry settings needed for modding tools to work correctly: "
            "xEdit family (WinXP compatibility), Pandora (window decoration), "
            "and global DLL overrides."
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

        # Left: form
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

        modlist_label = QLabel("Modlist:")
        form_grid.addWidget(modlist_label, 0, 0, alignment=Qt.AlignLeft | Qt.AlignVCenter)

        self._combo = QComboBox()
        self._combo.setMinimumWidth(280)
        self._combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._combo.addItem("Loading modlists...")
        self._combo.setEnabled(False)
        form_grid.addWidget(self._combo, 0, 1)

        form_widget = QWidget()
        form_widget.setLayout(form_grid)
        form_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        user_config_vbox.addWidget(form_widget)

        user_config_vbox.addSpacing(10)

        tools_info = QLabel(
            "<b>Tools configured by this workflow:</b><br>"
            "&nbsp;&nbsp;xEdit family &nbsp;|&nbsp; Synthesis &nbsp;|&nbsp; Pandora<br>"
            "<br>"
            "Run this once after installing a modlist if modding tools are not "
            "launching correctly from within Mod Organizer 2.<br>"
            "<br>"
            "<i>These fixes are applied on a best-effort basis. Tool compatibility "
            "can change with Proton and Wine updates. Not all tools are guaranteed "
            "to work on all Proton versions.</i>"
        )
        tools_info.setWordWrap(True)
        tools_info.setStyleSheet("color: #aaa; font-size: 12px;")
        tools_info.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        user_config_vbox.addWidget(tools_info)

        # Buttons (apply + back) - placed in left column like other screens
        btn_row = QHBoxLayout()
        btn_row.setAlignment(Qt.AlignHCenter)

        self._apply_btn = QPushButton("Apply Tool Configurations")
        self._apply_btn.setEnabled(False)
        btn_row.addWidget(self._apply_btn)

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

        # Right: Activity + Process Monitor tabs
        self._activity_log = QTextEdit()
        self._activity_log.setReadOnly(True)
        self._activity_log.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self._activity_log.setMinimumSize(QSize(300, 20))
        self._activity_log.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._activity_log.setStyleSheet(
            f"background: #222; color: {JACKIFY_COLOR_BLUE}; "
            "font-family: monospace; font-size: 11px; border: 1px solid #444;"
        )

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

        self.activity_tabs.addTab(self._activity_log, "Activity")
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
        self._status_banner = QLabel("Ready to apply")
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

        # Process monitor refresh timer
        self._top_timer = QTimer(self)
        self._top_timer.timeout.connect(self._update_top_panel)
        self._top_timer.start(2000)

        self._apply_btn.clicked.connect(self._on_apply)

    # ------------------------------------------------------------------

    def showEvent(self, event):
        super().showEvent(event)
        logger.info("Configure Tool Compatibility screen opened")
        try:
            main_window = self.window()
            if main_window:
                set_responsive_minimum(main_window, min_width=960, min_height=520)
        except Exception:
            pass
        self._load_shortcuts()

    def _load_shortcuts(self):
        if self._loader and self._loader.isRunning():
            return
        self._combo.clear()
        self._combo.addItem("Loading modlists...")
        self._combo.setEnabled(False)
        self._apply_btn.setEnabled(False)
        self._loader = _ShortcutLoaderThread()
        self._loader.finished_signal.connect(self._on_shortcuts_loaded)
        self._loader.error_signal.connect(self._on_shortcuts_error)
        self._loader.start()

    def _on_shortcuts_loaded(self, shortcuts: list):
        self._shortcuts = shortcuts
        self._combo.clear()
        if not shortcuts:
            self._combo.addItem("No configured modlists found")
            self._combo.setEnabled(False)
            self._apply_btn.setEnabled(False)
            return
        for s in shortcuts:
            self._combo.addItem(s["name"])
        self._combo.setEnabled(True)
        self._apply_btn.setEnabled(True)

    def _on_shortcuts_error(self, error: str):
        self._combo.clear()
        self._combo.addItem("Error loading modlists")
        self._combo.setEnabled(False)
        self._activity_log.append(f"Failed to load modlists: {error}")

    def _on_apply(self):
        idx = self._combo.currentIndex()
        if idx < 0 or idx >= len(self._shortcuts):
            return
        shortcut = self._shortcuts[idx]
        appid = shortcut["appid"]
        name = shortcut["name"]

        self._activity_log.clear()
        self.console.clear()
        self._activity_log.append(f"Applying tool configurations to: {name} (AppID {appid})")
        self._status_banner.setText("Applying...")
        logger.info("Applying tool compat config: %s (AppID %s)", name, appid)
        self._apply_btn.setEnabled(False)
        self._combo.setEnabled(False)

        self._apply_thread = _ApplyThread(appid)
        self._apply_thread.log_signal.connect(self._activity_log.append)
        self._apply_thread.log_signal.connect(self.console.append)
        self._apply_thread.finished_signal.connect(self._on_apply_finished)
        self._apply_thread.start()

    def _on_apply_finished(self, success: bool):
        self._apply_thread = None
        self._apply_btn.setEnabled(True)
        self._combo.setEnabled(True)
        if success:
            self._activity_log.append("\nDone. Tool compatibility settings applied successfully.")
            self._status_banner.setText("Applied successfully")
            logger.info("Tool compat config applied successfully")
            idx = self._combo.currentIndex()
            name = self._shortcuts[idx]["name"] if 0 <= idx < len(self._shortcuts) else "Modlist"
            from ..dialogs.success_dialog import SuccessDialog
            success_dialog = SuccessDialog(
                modlist_name=name,
                workflow_type="tool_config",
                time_taken="",
                parent=self
            )
            success_dialog.show()
        else:
            self._activity_log.append("\nFailed. Check the output above for details.")
            self._status_banner.setText("Apply failed - see details")
            logger.warning("Tool compat config failed")
            MessageService.warning(
                self, "Failed",
                "Tool configuration did not complete successfully.\nSee the log for details."
            )

    def _go_back(self):
        if self.stacked_widget:
            self.stacked_widget.setCurrentIndex(self.additional_tasks_index)

    def _on_show_details_toggled(self, checked: bool):
        if checked:
            self.console.setMinimumHeight(200)
            self.console.setMaximumHeight(16777215)
            self.console.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        else:
            self.console.setMinimumHeight(0)
            self.console.setMaximumHeight(0)
            self.console.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)

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
                if (
                    "wine" in ll or "wine64" in ll or "protontricks" in ll
                    or "jackify-engine" in ll
                ) and "jackify-gui.py" not in ll:
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

