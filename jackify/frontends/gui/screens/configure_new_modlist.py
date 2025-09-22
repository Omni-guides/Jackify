"""
ConfigureNewModlistScreen for Jackify GUI
"""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QComboBox, QHBoxLayout, QLineEdit, QPushButton, QGridLayout, QFileDialog, QTextEdit, QSizePolicy, QTabWidget, QDialog, QListWidget, QListWidgetItem, QMessageBox, QProgressDialog, QCheckBox
from PySide6.QtCore import Qt, QSize, QThread, Signal, QTimer, QProcess, QMetaObject
from PySide6.QtGui import QPixmap, QTextCursor
from ..shared_theme import JACKIFY_COLOR_BLUE, DEBUG_BORDERS
from ..utils import ansi_to_html
import os
import subprocess
import sys
import threading
import time
from jackify.backend.handlers.shortcut_handler import ShortcutHandler
import traceback
import signal
from jackify.backend.core.modlist_operations import get_jackify_engine_path
from jackify.backend.handlers.subprocess_utils import ProcessManager
from jackify.backend.services.api_key_service import APIKeyService
from jackify.backend.services.resolution_service import ResolutionService
from jackify.backend.handlers.config_handler import ConfigHandler
from ..dialogs import SuccessDialog
from PySide6.QtWidgets import QApplication
from jackify.frontends.gui.services.message_service import MessageService
from jackify.shared.resolution_utils import get_resolution_fallback

def debug_print(message):
    """Print debug message only if debug mode is enabled"""
    from jackify.backend.handlers.config_handler import ConfigHandler
    config_handler = ConfigHandler()
    if config_handler.get('debug_mode', False):
        print(message)

class ModlistFetchThread(QThread):
    result = Signal(list, str)
    def __init__(self, cli_path, game_type, project_root, log_path, mode='list-modlists', modlist_name=None, install_dir=None, download_dir=None):
        super().__init__()
        self.cli_path = cli_path
        self.game_type = game_type
        self.project_root = project_root
        self.log_path = log_path
        self.mode = mode
        self.modlist_name = modlist_name
        self.install_dir = install_dir
        self.download_dir = download_dir
    def run(self):
        if self.mode == 'list-modlists':
            cmd = [sys.executable, self.cli_path, '--install-modlist', '--list-modlists', '--game-type', self.game_type]
        elif self.mode == 'install':
            cmd = [sys.executable, self.cli_path, '--install-modlist', '--install', '--modlist-name', self.modlist_name, '--install-dir', self.install_dir, '--download-dir', self.download_dir, '--game-type', self.game_type]
        else:
            self.result.emit([], '[ModlistFetchThread] Unknown mode')
            return
        try:
            with open(self.log_path, 'a') as logf:
                logf.write(f"\n[Modlist Fetch CMD] {cmd}\n")
                proc = subprocess.Popen(cmd, cwd=self.project_root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                stdout, stderr = proc.communicate()
                logf.write(f"[stdout]\n{stdout}\n[stderr]\n{stderr}\n")
                if proc.returncode == 0:
                    modlist_ids = [line.strip() for line in stdout.splitlines() if line.strip()]
                    self.result.emit(modlist_ids, '')
                else:
                    self.result.emit([], stderr)
        except Exception as e:
            self.result.emit([], str(e))

class SelectionDialog(QDialog):
    def __init__(self, title, items, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(350)
        self.setMinimumHeight(300)
        layout = QVBoxLayout(self)
        self.list_widget = QListWidget()
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        for item in items:
            QListWidgetItem(item, self.list_widget)
        layout.addWidget(self.list_widget)
        self.selected_item = None
        self.list_widget.itemClicked.connect(self.on_item_clicked)
    def on_item_clicked(self, item):
        self.selected_item = item.text()
        self.accept()

class ConfigureNewModlistScreen(QWidget):
    steam_restart_finished = Signal(bool, str)
    def __init__(self, stacked_widget=None, main_menu_index=0):
        super().__init__()
        debug_print("DEBUG: ConfigureNewModlistScreen __init__ called")
        self.stacked_widget = stacked_widget
        self.main_menu_index = main_menu_index
        self.debug = DEBUG_BORDERS
        self.online_modlists = {}  # {game_type: [modlist_dict, ...]}
        self.modlist_details = {}  # {modlist_name: modlist_dict}
        
        # Initialize services early
        from jackify.backend.services.api_key_service import APIKeyService
        from jackify.backend.services.resolution_service import ResolutionService
        from jackify.backend.services.protontricks_detection_service import ProtontricksDetectionService
        from jackify.backend.handlers.config_handler import ConfigHandler
        self.api_key_service = APIKeyService()
        self.resolution_service = ResolutionService()
        self.config_handler = ConfigHandler()
        self.protontricks_service = ProtontricksDetectionService()

        # Path for workflow log
        self.refresh_paths()

        # Scroll tracking for professional auto-scroll behavior
        self._user_manually_scrolled = False
        self._was_at_bottom = True
        
        # Time tracking for workflow completion
        self._workflow_start_time = None

        main_overall_vbox = QVBoxLayout(self)
        main_overall_vbox.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        main_overall_vbox.setContentsMargins(50, 50, 50, 0)  # No bottom margin
        if self.debug:
            self.setStyleSheet("border: 2px solid magenta;")

        # --- Header (title, description) ---
        header_layout = QVBoxLayout()
        header_layout.setSpacing(1)  # Reduce spacing between title and description
        # Title (no logo)
        title = QLabel("<b>Configure New Modlist</b>")
        title.setStyleSheet(f"font-size: 20px; color: {JACKIFY_COLOR_BLUE}; margin: 0px; padding: 0px;")
        title.setAlignment(Qt.AlignHCenter)
        title.setMaximumHeight(30)  # Force compact height
        header_layout.addWidget(title)
        # Description
        desc = QLabel(
            "This screen allows you to configure a newly installed modlist in Jackify. "
            "Set up your Steam shortcut, restart Steam, and complete post-install configuration."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #ccc; margin: 0px; padding: 0px; line-height: 1.2;")
        desc.setAlignment(Qt.AlignHCenter)
        desc.setMaximumHeight(40)  # Force compact height for description
        header_layout.addWidget(desc)
        header_widget = QWidget()
        header_widget.setLayout(header_layout)
        header_widget.setMaximumHeight(75)  # Match other screens
        if self.debug:
            header_widget.setStyleSheet("border: 2px solid pink;")
            header_widget.setToolTip("HEADER_SECTION")
        main_overall_vbox.addWidget(header_widget)

        # --- Upper section: user-configurables (left) + process monitor (right) ---
        upper_hbox = QHBoxLayout()
        upper_hbox.setContentsMargins(0, 0, 0, 0)
        upper_hbox.setSpacing(16)
        # Left: user-configurables (form and controls)
        user_config_vbox = QVBoxLayout()
        user_config_vbox.setAlignment(Qt.AlignTop)
        # --- [Options] header (moved here for alignment) ---
        options_header = QLabel("<b>[Options]</b>")
        options_header.setStyleSheet(f"color: {JACKIFY_COLOR_BLUE}; font-size: 13px; font-weight: bold;")
        options_header.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        user_config_vbox.addWidget(options_header)
        # --- Install/Downloads Dir/API Key (reuse Tuxborn style) ---
        form_grid = QGridLayout()
        form_grid.setHorizontalSpacing(12)
        form_grid.setVerticalSpacing(6)  # Reduced from 8 to 6 for better readability
        form_grid.setContentsMargins(0, 0, 0, 0)
        # Modlist Name (NEW FIELD)
        modlist_name_label = QLabel("Modlist Name:")
        self.modlist_name_edit = QLineEdit()
        self.modlist_name_edit.setMaximumHeight(25)  # Force compact height
        form_grid.addWidget(modlist_name_label, 0, 0, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        form_grid.addWidget(self.modlist_name_edit, 0, 1)
        # Install Dir
        install_dir_label = QLabel("ModOrganizer.exe Path:")
        self.install_dir_edit = QLineEdit("/path/to/Modlist/ModOrganizer.exe")
        self.install_dir_edit.setMaximumHeight(25)  # Force compact height
        browse_install_btn = QPushButton("Browse")
        browse_install_btn.clicked.connect(self.browse_install_dir)
        install_dir_hbox = QHBoxLayout()
        install_dir_hbox.addWidget(self.install_dir_edit)
        install_dir_hbox.addWidget(browse_install_btn)
        form_grid.addWidget(install_dir_label, 1, 0, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        form_grid.addLayout(install_dir_hbox, 1, 1)
        # --- Resolution Dropdown ---
        resolution_label = QLabel("Resolution:")
        self.resolution_combo = QComboBox()
        self.resolution_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.resolution_combo.addItem("Leave unchanged")
        self.resolution_combo.addItems([
            "1280x720",
            "1280x800 (Steam Deck)",
            "1366x768",
            "1440x900",
            "1600x900",
            "1600x1200",
            "1680x1050",
            "1920x1080",
            "1920x1200",
            "2048x1152",
            "2560x1080",
            "2560x1440",
            "2560x1600",
            "3440x1440",
            "3840x1600",
            "3840x2160",
            "3840x2400",
            "5120x1440",
            "5120x2160",
            "7680x4320"
        ])
        form_grid.addWidget(resolution_label, 2, 0, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        
        # Load saved resolution if available
        saved_resolution = self.resolution_service.get_saved_resolution()
        is_steam_deck = False
        try:
            if os.path.exists('/etc/os-release'):
                with open('/etc/os-release') as f:
                    if 'steamdeck' in f.read().lower():
                        is_steam_deck = True
        except Exception:
            pass
        if saved_resolution:
            combo_items = [self.resolution_combo.itemText(i) for i in range(self.resolution_combo.count())]
            resolution_index = self.resolution_service.get_resolution_index(saved_resolution, combo_items)
            self.resolution_combo.setCurrentIndex(resolution_index)
            debug_print(f"DEBUG: Loaded saved resolution: {saved_resolution} (index: {resolution_index})")
        elif is_steam_deck:
            # Set default to 1280x800 (Steam Deck)
            combo_items = [self.resolution_combo.itemText(i) for i in range(self.resolution_combo.count())]
            if "1280x800 (Steam Deck)" in combo_items:
                self.resolution_combo.setCurrentIndex(combo_items.index("1280x800 (Steam Deck)"))
            else:
                self.resolution_combo.setCurrentIndex(0)
        # Otherwise, default is 'Leave unchanged' (index 0)
        
        # Horizontal layout for resolution dropdown and auto-restart checkbox
        resolution_and_restart_layout = QHBoxLayout()
        resolution_and_restart_layout.setSpacing(12)
        
        # Resolution dropdown (made smaller)
        self.resolution_combo.setMaximumWidth(280)  # Constrain width but keep aesthetically pleasing
        resolution_and_restart_layout.addWidget(self.resolution_combo)
        
        # Add stretch to push checkbox to the right
        resolution_and_restart_layout.addStretch()
        
        # Auto-accept Steam restart checkbox (right-aligned)
        self.auto_restart_checkbox = QCheckBox("Auto-accept Steam restart")
        self.auto_restart_checkbox.setChecked(False)  # Always default to unchecked per session
        self.auto_restart_checkbox.setToolTip("When checked, Steam restart dialog will be automatically accepted, allowing unattended configuration")
        resolution_and_restart_layout.addWidget(self.auto_restart_checkbox)
        
        # Update the form grid to use the combined layout
        form_grid.addLayout(resolution_and_restart_layout, 2, 1)
        
        form_section_widget = QWidget()
        form_section_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        form_section_widget.setLayout(form_grid)
        form_section_widget.setMinimumHeight(120)  # Reduced to match compact form
        form_section_widget.setMaximumHeight(240)  # Increased to show resolution dropdown
        if self.debug:
            form_section_widget.setStyleSheet("border: 2px solid blue;")
            form_section_widget.setToolTip("FORM_SECTION")
        user_config_vbox.addWidget(form_section_widget)
        # --- Buttons ---
        btn_row = QHBoxLayout()
        btn_row.setAlignment(Qt.AlignHCenter)
        self.start_btn = QPushButton("Start Configuration")
        btn_row.addWidget(self.start_btn)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.go_back)
        btn_row.addWidget(cancel_btn)
        user_config_widget = QWidget()
        user_config_widget.setLayout(user_config_vbox)
        if self.debug:
            user_config_widget.setStyleSheet("border: 2px solid orange;")
            user_config_widget.setToolTip("USER_CONFIG_WIDGET")
        # Right: process monitor (as before)
        self.process_monitor = QTextEdit()
        self.process_monitor.setReadOnly(True)
        self.process_monitor.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self.process_monitor.setMinimumSize(QSize(300, 20))
        self.process_monitor.setStyleSheet(f"background: #222; color: {JACKIFY_COLOR_BLUE}; font-family: monospace; font-size: 11px; border: 1px solid #444;")
        self.process_monitor_heading = QLabel("<b>[Process Monitor]</b>")
        self.process_monitor_heading.setStyleSheet(f"color: {JACKIFY_COLOR_BLUE}; font-size: 13px; margin-bottom: 2px;")
        self.process_monitor_heading.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        process_vbox = QVBoxLayout()
        process_vbox.setContentsMargins(0, 0, 0, 0)
        process_vbox.setSpacing(2)
        process_vbox.addWidget(self.process_monitor_heading)
        process_vbox.addWidget(self.process_monitor)
        process_monitor_widget = QWidget()
        process_monitor_widget.setLayout(process_vbox)
        if self.debug:
            process_monitor_widget.setStyleSheet("border: 2px solid purple;")
            process_monitor_widget.setToolTip("PROCESS_MONITOR")
        upper_hbox.addWidget(user_config_widget, stretch=11)
        upper_hbox.addWidget(process_monitor_widget, stretch=9)
        upper_hbox.setAlignment(Qt.AlignTop)
        upper_section_widget = QWidget()
        upper_section_widget.setLayout(upper_hbox)
        upper_section_widget.setMaximumHeight(280)  # Increased to show resolution dropdown
        if self.debug:
            upper_section_widget.setStyleSheet("border: 2px solid green;")
            upper_section_widget.setToolTip("UPPER_SECTION")
        main_overall_vbox.addWidget(upper_section_widget)
        # Remove spacing - console should expand to fill available space
        # --- Console output area (full width, placeholder for now) ---
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self.console.setMinimumHeight(50)   # Very small minimum - can shrink to almost nothing
        self.console.setMaximumHeight(1000) # Allow growth when space available
        self.console.setFontFamily('monospace')
        if self.debug:
            self.console.setStyleSheet("border: 2px solid yellow;")
            self.console.setToolTip("CONSOLE")
        
        # Set up scroll tracking for professional auto-scroll behavior
        self._setup_scroll_tracking()
        
        # Wrap button row in widget for debug borders
        btn_row_widget = QWidget()
        btn_row_widget.setLayout(btn_row)
        btn_row_widget.setMaximumHeight(50)  # Limit height to make it more compact
        if self.debug:
            btn_row_widget.setStyleSheet("border: 2px solid red;")
            btn_row_widget.setToolTip("BUTTON_ROW")
        
        # Create a container that holds console + button row with proper spacing
        console_and_buttons_widget = QWidget()
        console_and_buttons_layout = QVBoxLayout()
        console_and_buttons_layout.setContentsMargins(0, 0, 0, 0)
        console_and_buttons_layout.setSpacing(8)  # Small gap between console and buttons
        
        console_and_buttons_layout.addWidget(self.console, stretch=1)  # Console fills most space
        console_and_buttons_layout.addWidget(btn_row_widget)  # Buttons at bottom of this container
        
        console_and_buttons_widget.setLayout(console_and_buttons_layout)
        if self.debug:
            console_and_buttons_widget.setStyleSheet("border: 2px solid lightblue;")
            console_and_buttons_widget.setToolTip("CONSOLE_AND_BUTTONS_CONTAINER")
        main_overall_vbox.addWidget(console_and_buttons_widget, stretch=1)  # This container fills remaining space
        self.setLayout(main_overall_vbox)

        # --- Process Monitor (right) ---
        self.process = None
        self.log_timer = None
        self.last_log_pos = 0
        # --- Process Monitor Timer ---
        self.top_timer = QTimer(self)
        self.top_timer.timeout.connect(self.update_top_panel)
        self.top_timer.start(2000)
        # --- Start Configuration button ---
        self.start_btn.clicked.connect(self.validate_and_start_configure)
        # --- Connect steam_restart_finished signal ---
        self.steam_restart_finished.connect(self._on_steam_restart_finished)
        
        # Initialize empty controls list - will be populated after UI is built
        self._actionable_controls = []
        
        # Now collect all actionable controls after UI is fully built
        self._collect_actionable_controls()

    def _collect_actionable_controls(self):
        """Collect all actionable controls that should be disabled during operations (except Cancel)"""
        self._actionable_controls = [
            # Main action button
            self.start_btn,
            # Form fields
            self.modlist_name_edit,
            self.install_dir_edit,
            # Resolution controls
            self.resolution_combo,
            # Checkboxes  
            self.auto_restart_checkbox,
        ]

    def _disable_controls_during_operation(self):
        """Disable all actionable controls during configure operations (except Cancel)"""
        for control in self._actionable_controls:
            if control:
                control.setEnabled(False)

    def _enable_controls_after_operation(self):
        """Re-enable all actionable controls after configure operations complete"""
        for control in self._actionable_controls:
            if control:
                control.setEnabled(True)

    def refresh_paths(self):
        """Refresh cached paths when config changes."""
        from jackify.shared.paths import get_jackify_logs_dir
        self.modlist_log_path = get_jackify_logs_dir() / 'Configure_New_Modlist_workflow.log'
        os.makedirs(os.path.dirname(self.modlist_log_path), exist_ok=True)

    def resizeEvent(self, event):
        """Handle window resize to prioritize form over console"""
        super().resizeEvent(event)
        self._adjust_console_for_form_priority()

    def _adjust_console_for_form_priority(self):
        """Console now dynamically fills available space with stretch=1, no manual calculation needed"""
        # The console automatically fills remaining space due to stretch=1 in the layout
        # Remove any fixed height constraints to allow natural stretching
        self.console.setMaximumHeight(16777215)  # Reset to default maximum
        self.console.setMinimumHeight(50)  # Keep minimum height for usability

    def _setup_scroll_tracking(self):
        """Set up scroll tracking for professional auto-scroll behavior"""
        scrollbar = self.console.verticalScrollBar()
        scrollbar.sliderPressed.connect(self._on_scrollbar_pressed)
        scrollbar.sliderReleased.connect(self._on_scrollbar_released)
        scrollbar.valueChanged.connect(self._on_scrollbar_value_changed)

    def _on_scrollbar_pressed(self):
        """User started manually scrolling"""
        self._user_manually_scrolled = True

    def _on_scrollbar_released(self):
        """User finished manually scrolling"""
        self._user_manually_scrolled = False

    def _on_scrollbar_value_changed(self):
        """Track if user is at bottom of scroll area"""
        scrollbar = self.console.verticalScrollBar()
        # Use tolerance to account for rounding and rapid updates
        self._was_at_bottom = scrollbar.value() >= scrollbar.maximum() - 1
        
        # If user manually scrolls to bottom, reset manual scroll flag
        if self._was_at_bottom and self._user_manually_scrolled:
            # Small delay to allow user to scroll away if they want
            from PySide6.QtCore import QTimer
            QTimer.singleShot(100, self._reset_manual_scroll_if_at_bottom)
    
    def _reset_manual_scroll_if_at_bottom(self):
        """Reset manual scroll flag if user is still at bottom after delay"""
        scrollbar = self.console.verticalScrollBar()
        if scrollbar.value() >= scrollbar.maximum() - 1:
            self._user_manually_scrolled = False

    def _safe_append_text(self, text):
        """Append text with professional auto-scroll behavior"""
        # Write all messages to log file
        self._write_to_log_file(text)
        
        scrollbar = self.console.verticalScrollBar()
        # Check if user was at bottom BEFORE adding text
        was_at_bottom = (scrollbar.value() >= scrollbar.maximum() - 1)  # Allow 1px tolerance
        
        # Add the text
        self.console.append(text)
        
        # Auto-scroll if user was at bottom and hasn't manually scrolled
        # Re-check bottom state after text addition for better reliability
        if (was_at_bottom and not self._user_manually_scrolled) or \
           (not self._user_manually_scrolled and scrollbar.value() >= scrollbar.maximum() - 2):
            scrollbar.setValue(scrollbar.maximum())
            # Ensure user can still manually scroll up during rapid updates
            if scrollbar.value() == scrollbar.maximum():
                self._was_at_bottom = True

    def _write_to_log_file(self, message):
        """Write message to workflow log file with timestamp"""
        try:
            from datetime import datetime
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            with open(self.modlist_log_path, 'a', encoding='utf-8') as f:
                f.write(f"[{timestamp}] {message}\n")
        except Exception:
            # Logging should never break the workflow
            pass

    def browse_install_dir(self):
        file, _ = QFileDialog.getOpenFileName(self, "Select ModOrganizer.exe", os.path.expanduser("~"), "ModOrganizer.exe (ModOrganizer.exe)")
        if file:
            self.install_dir_edit.setText(file)

    def go_back(self):
        if self.stacked_widget:
            self.stacked_widget.setCurrentIndex(3)  # Return to Modlist Tasks menu

    def update_top_panel(self):
        try:
            result = subprocess.run([
                "ps", "-eo", "pcpu,pmem,comm,args"
            ], stdout=subprocess.PIPE, text=True, timeout=2)
            lines = result.stdout.splitlines()
            header = "CPU%\tMEM%\tCOMMAND"
            filtered = [header]
            process_rows = []
            for line in lines[1:]:
                line_lower = line.lower()
                # Include jackify-engine and related heavy processes
                heavy_processes = (
                    "jackify-engine" in line_lower or "7zz" in line_lower or 
                    "texconv" in line_lower or "wine" in line_lower or 
                    "wine64" in line_lower or "protontricks" in line_lower
                )
                # Include Python processes running configure-modlist command
                configure_processes = (
                    "python" in line_lower and "configure-modlist" in line_lower
                )
                # Include QProcess processes that might be configuration-related
                qprocess_config = (
                    hasattr(self, 'config_process') and 
                    self.config_process and 
                    self.config_process.state() == QProcess.Running and
                    ("python" in line_lower or "jackify" in line_lower)
                )
                
                if (heavy_processes or configure_processes or qprocess_config) and "jackify-gui.py" not in line_lower:
                    cols = line.strip().split(None, 3)
                    if len(cols) >= 3:
                        process_rows.append(cols)
            process_rows.sort(key=lambda x: float(x[0]), reverse=True)
            for cols in process_rows:
                filtered.append('\t'.join(cols))
            if len(filtered) == 1:
                filtered.append("[No Jackify-related processes found]")
            self.process_monitor.setPlainText('\n'.join(filtered))
        except Exception as e:
            self.process_monitor.setPlainText(f"[process info unavailable: {e}]")

    def _check_protontricks(self):
        """Check if protontricks is available before critical operations"""
        try:
            is_installed, installation_type, details = self.protontricks_service.detect_protontricks()
            
            if not is_installed:
                # Show protontricks error dialog
                from jackify.frontends.gui.dialogs.protontricks_error_dialog import ProtontricksErrorDialog
                dialog = ProtontricksErrorDialog(self.protontricks_service, self)
                result = dialog.exec()
                
                if result == QDialog.Rejected:
                    return False
                
                # Re-check after dialog
                is_installed, _, _ = self.protontricks_service.detect_protontricks(use_cache=False)
                return is_installed
            
            return True
            
        except Exception as e:
            print(f"Error checking protontricks: {e}")
            from jackify.frontends.gui.services.message_service import MessageService
            MessageService.warning(self, "Protontricks Check Failed", 
                                 f"Unable to verify protontricks installation: {e}\n\n"
                                 "Continuing anyway, but some features may not work correctly.")
            return True  # Continue anyway

    def validate_and_start_configure(self):
        # Check protontricks before proceeding
        if not self._check_protontricks():
            return
        
        # Rotate log file at start of each workflow run (keep 5 backups)
        from jackify.backend.handlers.logging_handler import LoggingHandler
        from pathlib import Path
        log_handler = LoggingHandler()
        log_handler.rotate_log_file_per_run(Path(self.modlist_log_path), backup_count=5)
        
        # Validate ModOrganizer.exe path
        mo2_path = self.install_dir_edit.text().strip()
        from jackify.frontends.gui.services.message_service import MessageService
        if not mo2_path:
            MessageService.warning(self, "Missing Path", "Please specify the path to ModOrganizer.exe", safety_level="low")
            return
        if not os.path.isfile(mo2_path):
            MessageService.warning(self, "Invalid Path", "The specified path does not point to a valid file", safety_level="low")
            return
        if not mo2_path.endswith('ModOrganizer.exe'):
            MessageService.warning(self, "Invalid File", "The specified file is not ModOrganizer.exe", safety_level="low")
            return
        
        # Start time tracking
        self._workflow_start_time = time.time()
        
        # Disable controls during configuration (after validation passes)
        self._disable_controls_during_operation()
        
        # Validate modlist name
        modlist_name = self.modlist_name_edit.text().strip()
        if not modlist_name:
            MessageService.warning(self, "Missing Name", "Please specify a name for your modlist", safety_level="low")
            self._enable_controls_after_operation()
            return
        # --- Shortcut creation will be handled by automated workflow ---
        from jackify.backend.handlers.shortcut_handler import ShortcutHandler
        steamdeck = os.path.exists('/etc/os-release') and 'steamdeck' in open('/etc/os-release').read().lower()
        shortcut_handler = ShortcutHandler(steamdeck=steamdeck)  # Still needed for Steam restart
        
        # Check if auto-restart is enabled
        auto_restart_enabled = hasattr(self, 'auto_restart_checkbox') and self.auto_restart_checkbox.isChecked()
        
        if auto_restart_enabled:
            # Auto-accept Steam restart - proceed without dialog
            self._safe_append_text("Auto-accepting Steam restart (unattended mode enabled)")
            reply = QMessageBox.Yes  # Simulate user clicking Yes
        else:
            # --- User confirmation before restarting Steam ---
            reply = MessageService.question(
                self, "Ready to Configure Modlist",
                "Would you like to restart Steam and begin post-install configuration now? Restarting Steam could close any games you have open!",
                safety_level="medium"
            )
        
        debug_print(f"DEBUG: Steam restart dialog returned: {reply!r}")
        if reply not in (QMessageBox.Yes, QMessageBox.Ok, QMessageBox.AcceptRole):
            self._enable_controls_after_operation()
            if self.stacked_widget:
                self.stacked_widget.setCurrentIndex(0)
            return
        # Handle resolution saving
        resolution = self.resolution_combo.currentText()
        if resolution and resolution != "Leave unchanged":
            success = self.resolution_service.save_resolution(resolution)
            if success:
                debug_print(f"DEBUG: Resolution saved successfully: {resolution}")
            else:
                debug_print("DEBUG: Failed to save resolution")
        else:
            # Clear saved resolution if "Leave unchanged" is selected
            if self.resolution_service.has_saved_resolution():
                self.resolution_service.clear_saved_resolution()
                debug_print("DEBUG: Saved resolution cleared")
        # --- Steam Configuration (progress dialog, thread, and signal) ---
        progress = QProgressDialog("Steam Configuration...", None, 0, 0, self)
        progress.setWindowTitle("Steam Configuration")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        progress.show()
        def do_restart():
            try:
                ok = shortcut_handler.secure_steam_restart()
                out = ''
            except Exception as e:
                ok = False
                out = str(e)
                self._safe_append_text(f"[ERROR] Exception during Steam restart: {e}")
            self.steam_restart_finished.emit(ok, out)
        threading.Thread(target=do_restart, daemon=True).start()
        self._steam_restart_progress = progress

    def _on_steam_restart_finished(self, success, out):
        if hasattr(self, '_steam_restart_progress'):
            self._steam_restart_progress.close()
            del self._steam_restart_progress
        self._enable_controls_after_operation()
        if success:
            self._safe_append_text("Steam restarted successfully.")
            
            # Start configuration immediately - the CLI will handle any manual steps
            self._safe_append_text("Starting modlist configuration...")
            self.configure_modlist()
        else:
            self._safe_append_text("Failed to restart Steam.\n" + str(out))
            MessageService.critical(self, "Steam Restart Failed", "Failed to restart Steam automatically. Please restart Steam manually, then try again.", safety_level="medium")

    def configure_modlist(self):
        install_dir = os.path.dirname(self.install_dir_edit.text().strip()) if self.install_dir_edit.text().strip().endswith('ModOrganizer.exe') else self.install_dir_edit.text().strip()
        modlist_name = self.modlist_name_edit.text().strip()
        mo2_exe_path = self.install_dir_edit.text().strip()
        resolution = self.resolution_combo.currentText()
        if not install_dir or not modlist_name:
            MessageService.warning(self, "Missing Info", "Install directory or modlist name is missing.", safety_level="low")
            return
        
        # Use automated prefix service instead of manual steps
        self._safe_append_text("")
        self._safe_append_text("=== Steam Integration Phase ===")
        self._safe_append_text("Starting automated Steam setup workflow...")
        
        # Start automated prefix workflow
        self._start_automated_prefix_workflow(modlist_name, install_dir, mo2_exe_path, resolution)

    def _start_automated_prefix_workflow(self, modlist_name, install_dir, mo2_exe_path, resolution):
        """Start the automated prefix workflow using AutomatedPrefixService in a background thread"""
        self._safe_append_text(f"Initializing automated Steam setup for '{modlist_name}'...")
        self._safe_append_text("Starting automated Steam shortcut creation and configuration...")
        
        # Disable the start button to prevent multiple workflows
        self.start_btn.setEnabled(False)
        
        # Create and start the automated prefix thread
        class AutomatedPrefixThread(QThread):
            progress_update = Signal(str)
            workflow_complete = Signal(object)  # Will emit the result tuple
            error_occurred = Signal(str)
            
            def __init__(self, modlist_name, install_dir, mo2_exe_path, steamdeck):
                super().__init__()
                self.modlist_name = modlist_name
                self.install_dir = install_dir
                self.mo2_exe_path = mo2_exe_path
                self.steamdeck = steamdeck
                
            def run(self):
                try:
                    from jackify.backend.services.automated_prefix_service import AutomatedPrefixService
                    
                    # Initialize the automated prefix service
                    prefix_service = AutomatedPrefixService()
                    
                    # Define progress callback for GUI updates
                    def progress_callback(message):
                        self.progress_update.emit(message)
                    
                    # Run the automated workflow (this contains the blocking operations)
                    result = prefix_service.run_working_workflow(
                        self.modlist_name, self.install_dir, self.mo2_exe_path, 
                        progress_callback, steamdeck=self.steamdeck
                    )
                    
                    # Emit the result
                    self.workflow_complete.emit(result)
                    
                except Exception as e:
                    self.error_occurred.emit(str(e))
        
        # Detect Steam Deck once
        try:
            import os
            _is_steamdeck = False
            if os.path.exists('/etc/os-release'):
                with open('/etc/os-release') as f:
                    if 'steamdeck' in f.read().lower():
                        _is_steamdeck = True
        except Exception:
            _is_steamdeck = False
        
        # Create and start the thread
        self.automated_prefix_thread = AutomatedPrefixThread(modlist_name, install_dir, mo2_exe_path, _is_steamdeck)
        self.automated_prefix_thread.progress_update.connect(self._safe_append_text)
        self.automated_prefix_thread.workflow_complete.connect(self._on_automated_prefix_complete)
        self.automated_prefix_thread.error_occurred.connect(self._on_automated_prefix_error)
        self.automated_prefix_thread.start()
    
    def _on_automated_prefix_complete(self, result):
        """Handle completion of the automated prefix workflow"""
        try:
            # Handle the result - check for conflicts
            if isinstance(result, tuple) and len(result) == 4:
                if result[0] == "CONFLICT":
                    # Conflict detected - show conflict resolution dialog
                    conflicts = result[1]
                    self.show_shortcut_conflict_dialog(conflicts)
                    return
                else:
                    # Normal result
                    success, prefix_path, new_appid, last_timestamp = result
                    if success:
                        self._safe_append_text(f"Automated Steam setup completed successfully!")
                        self._safe_append_text(f"New AppID assigned: {new_appid}")
                        
                        # Continue with post-Steam configuration, passing the last timestamp
                        self.continue_configuration_after_automated_prefix(new_appid, self.modlist_name_edit.text().strip(), 
                                                                         os.path.dirname(self.install_dir_edit.text().strip()) if self.install_dir_edit.text().strip().endswith('ModOrganizer.exe') else self.install_dir_edit.text().strip(), 
                                                                         last_timestamp)
                    else:
                        self._safe_append_text(f"Automated Steam setup failed")
                        self._safe_append_text("Please check the logs for details.")
                        self.start_btn.setEnabled(True)
            elif isinstance(result, tuple) and len(result) == 3:
                # Fallback for old format (backward compatibility)
                success, prefix_path, new_appid = result
                if success:
                    self._safe_append_text(f"Automated Steam setup completed successfully!")
                    self._safe_append_text(f"New AppID assigned: {new_appid}")
                    
                    # Continue with post-Steam configuration
                    self.continue_configuration_after_automated_prefix(new_appid, self.modlist_name_edit.text().strip(), 
                                                                     os.path.dirname(self.install_dir_edit.text().strip()) if self.install_dir_edit.text().strip().endswith('ModOrganizer.exe') else self.install_dir_edit.text().strip())
                else:
                    self._safe_append_text(f"Automated Steam setup failed")
                    self._safe_append_text("Please check the logs for details.")
                    self.start_btn.setEnabled(True)
            else:
                # Handle unexpected result format
                self._safe_append_text(f"Automated Steam setup failed - unexpected result format")
                self._safe_append_text("Please check the logs for details.")
                self.start_btn.setEnabled(True)
                
        except Exception as e:
            self._safe_append_text(f"Error handling automated prefix result: {str(e)}")
            self.start_btn.setEnabled(True)
    
    def _on_automated_prefix_error(self, error_message):
        """Handle error from the automated prefix workflow"""
        self._safe_append_text(f"Error during automated Steam setup: {error_message}")
        self._safe_append_text("Please check the logs for details.")
        self._enable_controls_after_operation()

    def show_shortcut_conflict_dialog(self, conflicts):
        """Show dialog to resolve shortcut name conflicts"""
        conflict_names = [c['name'] for c in conflicts]
        conflict_info = f"Found existing Steam shortcut: '{conflict_names[0]}'"
        
        modlist_name = self.modlist_name_edit.text().strip()
        
        # Create dialog with Jackify styling
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QHBoxLayout
        from PySide6.QtCore import Qt
        
        dialog = QDialog(self)
        dialog.setWindowTitle("Steam Shortcut Conflict")
        dialog.setModal(True)
        dialog.resize(450, 180)
        
        # Apply Jackify dark theme styling
        dialog.setStyleSheet("""
            QDialog {
                background-color: #2b2b2b;
                color: #ffffff;
            }
            QLabel {
                color: #ffffff;
                font-size: 14px;
                padding: 10px 0px;
            }
            QLineEdit {
                background-color: #404040;
                color: #ffffff;
                border: 2px solid #555555;
                border-radius: 4px;
                padding: 8px;
                font-size: 14px;
                selection-background-color: #3fd0ea;
            }
            QLineEdit:focus {
                border-color: #3fd0ea;
            }
            QPushButton {
                background-color: #404040;
                color: #ffffff;
                border: 2px solid #555555;
                border-radius: 4px;
                padding: 8px 16px;
                font-size: 14px;
                min-width: 120px;
            }
            QPushButton:hover {
                background-color: #505050;
                border-color: #3fd0ea;
            }
            QPushButton:pressed {
                background-color: #303030;
            }
        """)
        
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # Conflict message
        conflict_label = QLabel(f"{conflict_info}\n\nPlease choose a different name for your shortcut:")
        layout.addWidget(conflict_label)
        
        # Text input for new name
        name_input = QLineEdit(modlist_name)
        name_input.selectAll()
        layout.addWidget(name_input)
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)
        
        create_button = QPushButton("Create with New Name")
        cancel_button = QPushButton("Cancel")
        
        button_layout.addStretch()
        button_layout.addWidget(cancel_button)
        button_layout.addWidget(create_button)
        layout.addLayout(button_layout)
        
        # Connect signals
        def on_create():
            new_name = name_input.text().strip()
            if new_name and new_name != modlist_name:
                dialog.accept()
                # Retry workflow with new name
                self.retry_automated_workflow_with_new_name(new_name)
            elif new_name == modlist_name:
                # Same name - show warning
                from jackify.backend.services.message_service import MessageService
                MessageService.warning(self, "Same Name", "Please enter a different name to resolve the conflict.")
            else:
                # Empty name
                from jackify.backend.services.message_service import MessageService
                MessageService.warning(self, "Invalid Name", "Please enter a valid shortcut name.")
        
        def on_cancel():
            dialog.reject()
            self._safe_append_text("Shortcut creation cancelled by user")
        
        create_button.clicked.connect(on_create)
        cancel_button.clicked.connect(on_cancel)
        
        # Make Enter key work
        name_input.returnPressed.connect(on_create)
        
        dialog.exec()
    
    def retry_automated_workflow_with_new_name(self, new_name):
        """Retry the automated workflow with a new shortcut name"""
        # Update the modlist name field temporarily
        original_name = self.modlist_name_edit.text()
        self.modlist_name_edit.setText(new_name)
        
        # Restart the automated workflow
        self._safe_append_text(f"Retrying with new shortcut name: '{new_name}'")
        self._start_automated_prefix_workflow(new_name, os.path.dirname(self.install_dir_edit.text().strip()) if self.install_dir_edit.text().strip().endswith('ModOrganizer.exe') else self.install_dir_edit.text().strip(), self.install_dir_edit.text().strip(), self.resolution_combo.currentText())

    # Old CLI-based handlers removed - now using backend service directly

    # Manual steps methods removed - now using automated prefix service
        """Validate that manual steps were actually completed and handle retry logic"""
        modlist_name = self.modlist_name_edit.text().strip()
        install_dir = os.path.dirname(self.install_dir_edit.text().strip()) if self.install_dir_edit.text().strip().endswith('ModOrganizer.exe') else self.install_dir_edit.text().strip()
        mo2_exe_path = self.install_dir_edit.text().strip()
        
        # CRITICAL: Re-detect the AppID after Steam restart and manual steps
        # Steam assigns a NEW AppID during restart, different from the one we initially created
        self._safe_append_text(f"Re-detecting AppID for shortcut '{modlist_name}' after Steam restart...")
        from jackify.backend.handlers.shortcut_handler import ShortcutHandler
        shortcut_handler = ShortcutHandler(steamdeck=False)
        current_appid = shortcut_handler.get_appid_for_shortcut(modlist_name, mo2_exe_path)
        
        if not current_appid or not current_appid.isdigit():
            self._safe_append_text(f"Error: Could not find Steam-assigned AppID for shortcut '{modlist_name}'")
            self._safe_append_text("Error: This usually means the shortcut was not launched from Steam")
            self.handle_validation_failure("Could not find Steam shortcut")
            return
        
        self._safe_append_text(f"Found Steam-assigned AppID: {current_appid}")
        self._safe_append_text(f"Validating manual steps completion for AppID: {current_appid}")
        
        # Check manual steps completion (same validation as Tuxborn)
        validation_passed = True
        missing_details = []
        
        # Check 1: Proton version
        proton_ok = False
        try:
            from jackify.backend.handlers.modlist_handler import ModlistHandler
            from jackify.backend.handlers.path_handler import PathHandler
            
            # Initialize ModlistHandler with correct parameters
            path_handler = PathHandler()
            modlist_handler = ModlistHandler(steamdeck=False, verbose=False)
            
            # Set required properties manually after initialization
            modlist_handler.modlist_dir = install_dir
            modlist_handler.appid = current_appid  # Use the re-detected AppID
            modlist_handler.game_var = "skyrimspecialedition"  # Default for now
            
            # Set compat_data_path for Proton detection using the re-detected AppID
            compat_data_path_str = path_handler.find_compat_data(current_appid)
            if compat_data_path_str:
                from pathlib import Path
                modlist_handler.compat_data_path = Path(compat_data_path_str)
            
            # Check Proton version using the re-detected AppID
            self._safe_append_text(f"Attempting to detect Proton version for AppID {current_appid}...")
            if modlist_handler._detect_proton_version():
                self._safe_append_text(f"Raw detected Proton version: '{modlist_handler.proton_ver}'")
                
                if modlist_handler.proton_ver and 'experimental' in modlist_handler.proton_ver.lower():
                    self._safe_append_text(f"Proton version validated: {modlist_handler.proton_ver}")
                    proton_ok = True
                else:
                    self._safe_append_text(f"Error: Wrong Proton version detected: '{modlist_handler.proton_ver}' (expected 'experimental' in name)")
            else:
                self._safe_append_text("Error: Could not detect Proton version from any source")
                
        except Exception as e:
            self._safe_append_text(f"Error checking Proton version: {e}")
        
        if not proton_ok:
            validation_passed = False
            missing_details.append("Error: Proton version not set to 'Proton - Experimental'")
        
        # Check 2: Compatdata directory exists
        compatdata_ok = False
        try:
            from jackify.backend.handlers.path_handler import PathHandler
            path_handler = PathHandler()
            self._safe_append_text(f"Searching for compatdata directory for AppID {current_appid}...")
            prefix_path_str = path_handler.find_compat_data(current_appid)
            self._safe_append_text(f"Compatdata search result: '{prefix_path_str}'")
            
            if prefix_path_str:
                from pathlib import Path
                prefix_path = Path(prefix_path_str)
                if prefix_path.exists() and prefix_path.is_dir():
                    self._safe_append_text(f"Compatdata directory found: {prefix_path_str}")
                    compatdata_ok = True
                elif prefix_path.exists():
                    self._safe_append_text(f"Error: Path exists but is not a directory: {prefix_path_str}")
                else:
                    self._safe_append_text(f"Error: No compatdata directory found for AppID {current_appid}")
            else:
                self._safe_append_text(f"ERROR: No compatdata directory found for AppID {current_appid}")
        except Exception as e:
            self._safe_append_text(f"Error checking compatdata: {e}")
        
        if not compatdata_ok:
            validation_passed = False
            missing_details.append("Error: Modlist was not launched from Steam (no compatdata directory)")
        
        if validation_passed:
            self._safe_append_text("Manual steps validation passed!")
            self._safe_append_text("Continuing configuration with updated AppID...")
            
            # Continue with configuration (same as Tuxborn)
            self.continue_configuration_after_manual_steps(current_appid, modlist_name, install_dir)
        else:
            missing_text = "\n".join(missing_details)
            self._safe_append_text(f"Manual steps validation failed:\n{missing_text}")
            self.handle_validation_failure(missing_text)
    
    def continue_configuration_after_automated_prefix(self, new_appid, modlist_name, install_dir, last_timestamp=None):
        """Continue the configuration process with the new AppID after automated prefix creation"""
        # Headers are now shown at start of Steam Integration
        # No need to show them again here
        debug_print("Configuration phase continues after Steam Integration")
        
        debug_print(f"continue_configuration_after_automated_prefix called with appid: {new_appid}")
        try:
            # Get resolution from UI
            resolution = self.resolution_combo.currentText()
            resolution_value = resolution.split()[0] if resolution != "Leave unchanged" else None
            
            # Update the context with the new AppID (same format as manual steps)
            mo2_exe_path = self.install_dir_edit.text().strip()
            updated_context = {
                'name': modlist_name,
                'path': install_dir,
                'mo2_exe_path': mo2_exe_path,
                'modlist_value': None,
                'modlist_source': None,
                'resolution': resolution_value,
                'skip_confirmation': True,
                'manual_steps_completed': True,  # Mark as completed since automated prefix is done
                'appid': new_appid,  # Use the NEW AppID from automated prefix creation
                'game_name': 'Skyrim Special Edition'  # Default for new modlist
            }
            self.context = updated_context  # Ensure context is always set
            debug_print(f"Updated context with new AppID: {new_appid}")
            
            # Create new config thread with updated context
            class ConfigThread(QThread):
                progress_update = Signal(str)
                configuration_complete = Signal(bool, str, str)
                error_occurred = Signal(str)
                
                def __init__(self, context):
                    super().__init__()
                    self.context = context
                
                def run(self):
                    try:
                        from jackify.backend.services.modlist_service import ModlistService
                        from jackify.backend.models.configuration import SystemInfo
                        from jackify.backend.models.modlist import ModlistContext
                        from pathlib import Path
                        
                        # Initialize backend service
                        system_info = SystemInfo(is_steamdeck=False)
                        modlist_service = ModlistService(system_info)
                        
                        # Convert context to ModlistContext for service
                        modlist_context = ModlistContext(
                            name=self.context['name'],
                            install_dir=Path(self.context['path']),
                            download_dir=Path(self.context['path']).parent / 'Downloads',  # Default
                            game_type='skyrim',  # Default for now
                            nexus_api_key='',  # Not needed for configuration
                            modlist_value=self.context.get('modlist_value'),
                            modlist_source=self.context.get('modlist_source', 'identifier'),
                            resolution=self.context.get('resolution') or get_resolution_fallback(None),
                            skip_confirmation=True
                        )
                        
                        # Add app_id to context
                        modlist_context.app_id = self.context['appid']
                        
                        # Define callbacks
                        def progress_callback(message):
                            self.progress_update.emit(message)
                            
                        def completion_callback(success, message, modlist_name):
                            self.configuration_complete.emit(success, message, modlist_name)
                            
                        def manual_steps_callback(modlist_name, retry_count):
                            # This shouldn't happen since automated prefix creation is complete
                            self.progress_update.emit(f"Unexpected manual steps callback for {modlist_name}")
                        
                        # Call the service method for post-Steam configuration
                        self.progress_update.emit("")
                        self.progress_update.emit("=== Configuration Phase ===")
                        self.progress_update.emit("")
                        self.progress_update.emit("Starting modlist configuration...")
                        result = modlist_service.configure_modlist_post_steam(
                            context=modlist_context,
                            progress_callback=progress_callback,
                            manual_steps_callback=manual_steps_callback,
                            completion_callback=completion_callback
                        )
                        
                        if not result:
                            self.progress_update.emit("Configuration failed to start")
                            self.error_occurred.emit("Configuration failed to start")
                            
                    except Exception as e:
                        self.error_occurred.emit(str(e))
            
            # Start configuration thread
            self.config_thread = ConfigThread(updated_context)
            self.config_thread.progress_update.connect(self._safe_append_text)
            self.config_thread.configuration_complete.connect(self.on_configuration_complete)
            self.config_thread.error_occurred.connect(self.on_configuration_error)
            self.config_thread.start()
            
        except Exception as e:
            self._safe_append_text(f"Error continuing configuration: {e}")
            import traceback
            self._safe_append_text(f"Full traceback: {traceback.format_exc()}")
            self.on_configuration_error(str(e))

    def continue_configuration_after_manual_steps(self, new_appid, modlist_name, install_dir):
        """Continue the configuration process with the corrected AppID after manual steps validation"""
        try:
            # Update the context with the new AppID
            mo2_exe_path = self.install_dir_edit.text().strip()
            resolution = self.resolution_combo.currentText()
            
            updated_context = {
                'name': modlist_name,
                'path': install_dir,
                'mo2_exe_path': mo2_exe_path,
                'resolution': resolution.split()[0] if resolution != "Leave unchanged" else None,
                'skip_confirmation': True,
                'manual_steps_completed': True,  # Mark as completed
                'appid': new_appid,  # Use the NEW AppID from Steam
                'game_name': 'Skyrim Special Edition'  # Default for new modlist
            }
            debug_print(f"Updated context with new AppID: {new_appid}")
            
            # Create new config thread with updated context (same as Tuxborn)
            from PySide6.QtCore import QThread, Signal
            
            class ConfigThread(QThread):
                progress_update = Signal(str)
                configuration_complete = Signal(bool, str, str)
                error_occurred = Signal(str)
                
                def __init__(self, context):
                    super().__init__()
                    self.context = context
                    
                def run(self):
                    try:
                        from jackify.backend.models.configuration import SystemInfo
                        from jackify.backend.services.modlist_service import ModlistService
                        from jackify.backend.models.modlist import ModlistContext
                        from pathlib import Path
                        
                        # Initialize backend service
                        system_info = SystemInfo(is_steamdeck=False)
                        modlist_service = ModlistService(system_info)
                        
                        # Convert context to ModlistContext for service
                        modlist_context = ModlistContext(
                            name=self.context['name'],
                            install_dir=Path(self.context['path']),
                            download_dir=Path(self.context['path']).parent / 'Downloads',  # Default
                            game_type='skyrim',  # Default for configure new
                            nexus_api_key='',  # Not needed for configuration
                            modlist_value='',  # Not needed for existing modlist
                            modlist_source='existing',
                            resolution=self.context.get('resolution'),
                            skip_confirmation=True
                        )
                        
                        # Add app_id to context
                        if 'appid' in self.context:
                            modlist_context.app_id = self.context['appid']
                        
                        # Define callbacks
                        def progress_callback(message):
                            self.progress_update.emit(message)
                            
                        def completion_callback(success, message, modlist_name):
                            self.configuration_complete.emit(success, message, modlist_name)
                            
                        def manual_steps_callback(modlist_name, retry_count):
                            # This shouldn't happen since manual steps should be done
                            self.progress_update.emit(f"Unexpected manual steps callback for {modlist_name}")
                        
                        # Call the working configuration service method
                        self.progress_update.emit("Starting configuration with backend service...")
                        
                        success = modlist_service.configure_modlist_post_steam(
                            context=modlist_context,
                            progress_callback=progress_callback,
                            manual_steps_callback=manual_steps_callback,
                            completion_callback=completion_callback
                        )
                        
                        if not success:
                            self.error_occurred.emit("Configuration failed - check logs for details")
                            
                    except Exception as e:
                        import traceback
                        error_msg = f"Configuration error: {e}\n{traceback.format_exc()}"
                        self.error_occurred.emit(error_msg)
            
            # Create and start the configuration thread
            self.config_thread = ConfigThread(updated_context)
            self.config_thread.progress_update.connect(self._safe_append_text)
            self.config_thread.configuration_complete.connect(self.on_configuration_complete)
            self.config_thread.error_occurred.connect(self.on_configuration_error)
            self.config_thread.start()
            
        except Exception as e:
            self._safe_append_text(f"Error continuing configuration: {e}")
            MessageService.critical(self, "Configuration Error", f"Failed to continue configuration: {e}", safety_level="medium")

    def on_configuration_complete(self, success, message, modlist_name):
        """Handle configuration completion (same as Tuxborn)"""
        # Re-enable all controls when workflow completes
        self._enable_controls_after_operation()
        
        if success:
            # Calculate time taken
            time_taken = self._calculate_time_taken()
            
            # Show success dialog with celebration
            success_dialog = SuccessDialog(
                modlist_name=modlist_name,
                workflow_type="configure_new",
                time_taken=time_taken,
                game_name=getattr(self, '_current_game_name', None),
                parent=self
            )
            success_dialog.show()
        else:
            self._safe_append_text(f"Configuration failed: {message}")
            MessageService.critical(self, "Configuration Failed", 
                               f"Configuration failed: {message}", safety_level="medium")
    
    def on_configuration_error(self, error_message):
        """Handle configuration error"""
        # Re-enable all controls on error
        self._enable_controls_after_operation()
        
        self._safe_append_text(f"Configuration error: {error_message}")
        MessageService.critical(self, "Configuration Error", f"Configuration failed: {error_message}", safety_level="medium")

    def handle_validation_failure(self, missing_text):
        """Handle manual steps validation failure with retry logic"""
        self._manual_steps_retry_count += 1
        
        if self._manual_steps_retry_count < 3:
            # Show retry dialog
            MessageService.critical(self, "Manual Steps Incomplete", 
                               f"Manual steps validation failed:\n\n{missing_text}\n\n"
                               "Please complete the manual steps and try again.", safety_level="medium")
            # Show manual steps dialog again
            extra_warning = ""
            if self._manual_steps_retry_count >= 2:
                extra_warning = "<br><b style='color:#f33'>It looks like you have not completed the manual steps yet. Please try again.</b>"
            self.show_manual_steps_dialog(extra_warning)
        else:
            # Max retries reached
            MessageService.critical(self, "Manual Steps Failed", 
                               "Manual steps validation failed after multiple attempts.", safety_level="medium")
            self.on_configuration_complete(False, "Manual steps validation failed after multiple attempts", self.modlist_name_edit.text().strip())

    # Old CLI-based process finished handler removed - now using backend service callbacks

    def _calculate_time_taken(self) -> str:
        """Calculate and format the time taken for the workflow"""
        if self._workflow_start_time is None:
            return "unknown time"
        
        elapsed_seconds = time.time() - self._workflow_start_time
        elapsed_minutes = int(elapsed_seconds // 60)
        elapsed_seconds_remainder = int(elapsed_seconds % 60)
        
        if elapsed_minutes > 0:
            if elapsed_minutes == 1:
                return f"{elapsed_minutes} minute {elapsed_seconds_remainder} seconds"
            else:
                return f"{elapsed_minutes} minutes {elapsed_seconds_remainder} seconds"
        else:
            return f"{elapsed_seconds_remainder} seconds"

    def show_next_steps_dialog(self, message):
        dlg = QDialog(self)
        dlg.setWindowTitle("Next Steps")
        dlg.setModal(True)
        layout = QVBoxLayout(dlg)
        label = QLabel(message)
        label.setWordWrap(True)
        layout.addWidget(label)
        btn_row = QHBoxLayout()
        btn_return = QPushButton("Return")
        btn_exit = QPushButton("Exit")
        btn_row.addWidget(btn_return)
        btn_row.addWidget(btn_exit)
        layout.addLayout(btn_row)
        def on_return():
            dlg.accept()
            if self.stacked_widget:
                self.stacked_widget.setCurrentIndex(0)
        def on_exit():
            QApplication.quit()
        btn_return.clicked.connect(on_return)
        btn_exit.clicked.connect(on_exit)
        dlg.exec()

    def cleanup(self):
        """Clean up any running threads when the screen is closed"""
        debug_print("DEBUG: cleanup called - cleaning up threads")
        
        # Clean up automated prefix thread if running
        if hasattr(self, 'automated_prefix_thread') and self.automated_prefix_thread and self.automated_prefix_thread.isRunning():
            debug_print("DEBUG: Terminating AutomatedPrefixThread")
            try:
                self.automated_prefix_thread.progress_update.disconnect()
                self.automated_prefix_thread.workflow_complete.disconnect()
                self.automated_prefix_thread.error_occurred.disconnect()
            except:
                pass
            self.automated_prefix_thread.terminate()
            self.automated_prefix_thread.wait(2000)  # Wait up to 2 seconds
        
        # Clean up config thread if running
        if hasattr(self, 'config_thread') and self.config_thread and self.config_thread.isRunning():
            debug_print("DEBUG: Terminating ConfigThread")
            try:
                self.config_thread.progress_update.disconnect()
                self.config_thread.configuration_complete.disconnect()
                self.config_thread.error_occurred.disconnect()
            except:
                pass
            self.config_thread.terminate()
            self.config_thread.wait(2000)  # Wait up to 2 seconds 