# Copy of ConfigureNewModlistScreen, adapted for existing modlists
from PySide6.QtWidgets import *
from PySide6.QtCore import *
from PySide6.QtGui import *
from ..shared_theme import JACKIFY_COLOR_BLUE, DEBUG_BORDERS
from ..utils import ansi_to_html, set_responsive_minimum
# Progress reporting components
from jackify.frontends.gui.widgets.progress_indicator import OverallProgressIndicator
from jackify.frontends.gui.widgets.file_progress_list import FileProgressList
from jackify.shared.progress_models import InstallationPhase, InstallationProgress
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
from jackify.frontends.gui.services.message_service import MessageService

def debug_print(message):
    """Print debug message only if debug mode is enabled"""
    from jackify.backend.handlers.config_handler import ConfigHandler
    config_handler = ConfigHandler()
    if config_handler.get('debug_mode', False):
        print(message)

class ConfigureExistingModlistScreen(QWidget):
    steam_restart_finished = Signal(bool, str)
    resize_request = Signal(str)
    def __init__(self, stacked_widget=None, main_menu_index=0):
        super().__init__()
        debug_print("DEBUG: ConfigureExistingModlistScreen __init__ called")
        self.stacked_widget = stacked_widget
        self.main_menu_index = main_menu_index
        self.debug = DEBUG_BORDERS
        self.refresh_paths()
        
        # --- Detect Steam Deck ---
        from jackify.backend.services.platform_detection_service import PlatformDetectionService
        platform_service = PlatformDetectionService.get_instance()
        steamdeck = platform_service.is_steamdeck
        self.shortcut_handler = ShortcutHandler(steamdeck=steamdeck)
        
        # Initialize services early
        from jackify.backend.services.api_key_service import APIKeyService
        from jackify.backend.services.resolution_service import ResolutionService
        from jackify.backend.handlers.config_handler import ConfigHandler
        self.api_key_service = APIKeyService()
        self.resolution_service = ResolutionService()
        self.config_handler = ConfigHandler()
        
        # --- Fetch shortcuts for ModOrganizer.exe - deferred to showEvent to avoid blocking init ---
        # Initialize empty list, will be populated when screen is shown
        self.mo2_shortcuts = []
        self._shortcuts_loaded = False
        self._shortcut_loader = None  # Thread for async shortcut loading

        # Initialize progress reporting components
        self.progress_indicator = OverallProgressIndicator(show_progress_bar=True)
        self.progress_indicator.set_status("Ready to configure", 0)
        self.file_progress_list = FileProgressList()

        # Create "Show Details" checkbox
        self.show_details_checkbox = QCheckBox("Show details")
        self.show_details_checkbox.setChecked(False)  # Start collapsed
        self.show_details_checkbox.setToolTip("Toggle between activity summary and detailed console output")
        self.show_details_checkbox.toggled.connect(self._on_show_details_toggled)

        # --- UI Layout ---
        main_overall_vbox = QVBoxLayout(self)
        main_overall_vbox.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        main_overall_vbox.setContentsMargins(50, 50, 50, 0)  # No bottom margin
        if self.debug:
            self.setStyleSheet("border: 2px solid magenta;")
        # --- Header (title, description) ---
        header_layout = QVBoxLayout()
        header_layout.setSpacing(1)  # Reduce spacing between title and description
        title = QLabel("<b>Configure Existing Modlist</b>")
        title.setStyleSheet(f"font-size: 20px; color: {JACKIFY_COLOR_BLUE}; margin: 0px; padding: 0px;")
        title.setAlignment(Qt.AlignHCenter)
        title.setMaximumHeight(30)  # Force compact height
        header_layout.addWidget(title)
        desc = QLabel(
            "This screen allows you to configure an existing modlist in Jackify. "
            "Select your Steam shortcut for ModOrganizer.exe, set your resolution, and complete post-install configuration."
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
        # --- Upper section: shortcut selector (left) + process monitor (right) ---
        upper_hbox = QHBoxLayout()
        upper_hbox.setContentsMargins(0, 0, 0, 0)
        upper_hbox.setSpacing(16)
        user_config_vbox = QVBoxLayout()
        user_config_vbox.setAlignment(Qt.AlignTop)
        # --- [Options] header (moved here for alignment) ---
        options_header = QLabel("<b>[Options]</b>")
        options_header.setStyleSheet(f"color: {JACKIFY_COLOR_BLUE}; font-size: 13px; font-weight: bold;")
        options_header.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        user_config_vbox.addWidget(options_header)
        form_grid = QGridLayout()
        form_grid.setHorizontalSpacing(12)
        form_grid.setVerticalSpacing(6)  # Reduced from 8 to 6 for better readability
        form_grid.setContentsMargins(0, 0, 0, 0)
        # --- Shortcut selector ---
        shortcut_label = QLabel("Select Modlist:")
        self.shortcut_combo = QComboBox()
        self.shortcut_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.shortcut_combo.addItem("Please Select...")
        self.shortcut_map = []
        for shortcut in self.mo2_shortcuts:
            display = f"{shortcut.get('AppName', shortcut.get('appname', 'Unknown'))} ({shortcut.get('StartDir', shortcut.get('startdir', ''))})"
            self.shortcut_combo.addItem(display)
            self.shortcut_map.append(shortcut)
        
        # Add refresh button next to dropdown
        refresh_btn = QPushButton("↻")
        refresh_btn.setToolTip("Refresh modlist list")
        refresh_btn.setFixedSize(30, 30)
        refresh_btn.clicked.connect(self.refresh_modlist_list)
        
        # Create horizontal layout for dropdown and refresh button
        shortcut_hbox = QHBoxLayout()
        shortcut_hbox.addWidget(self.shortcut_combo)
        shortcut_hbox.addWidget(refresh_btn)
        shortcut_hbox.setSpacing(4)
        shortcut_hbox.setStretch(0, 1)  # Make dropdown expand
        
        form_grid.addWidget(shortcut_label, 0, 0, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        form_grid.addLayout(shortcut_hbox, 0, 1)
        # --- Info message under shortcut selector ---
        info_label = QLabel("<span style='color:#aaa'>If you don't see your modlist entry in this list, please ensure you have added it to Steam as a non-steam game, set a proton version in properties, and have started the modlist Steam entry at least once. You can also click the refresh button (↻) to update the list.</span>")
        info_label.setWordWrap(True)
        form_grid.addWidget(info_label, 1, 0, 1, 2)
        # --- Resolution selector ---
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
        form_grid.addWidget(self.resolution_combo, 2, 1)
        
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
        form_section_widget = QWidget()
        form_section_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        form_section_widget.setLayout(form_grid)
        form_section_widget.setMinimumHeight(160)  # Reduced to match compact form
        form_section_widget.setMaximumHeight(240)  # Increased to show resolution dropdown
        if self.debug:
            form_section_widget.setStyleSheet("border: 2px solid blue;")
            form_section_widget.setToolTip("FORM_SECTION")
        user_config_vbox.addWidget(form_section_widget)
        btn_row = QHBoxLayout()
        btn_row.setAlignment(Qt.AlignHCenter)
        self.start_btn = QPushButton("Start Configuration")
        btn_row.addWidget(self.start_btn)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.cancel_and_cleanup)
        btn_row.addWidget(cancel_btn)
        user_config_widget = QWidget()
        user_config_widget.setLayout(user_config_vbox)
        if self.debug:
            user_config_widget.setStyleSheet("border: 2px solid orange;")
            user_config_widget.setToolTip("USER_CONFIG_WIDGET")
        # Right: Tabbed interface with Activity and Process Monitor
        # Both tabs are always available, user can switch between them
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
        process_monitor_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        if self.debug:
            process_monitor_widget.setStyleSheet("border: 2px solid purple;")
            process_monitor_widget.setToolTip("PROCESS_MONITOR")
        self.process_monitor_widget = process_monitor_widget

        # Set up File Progress List (Activity tab)
        self.file_progress_list.setMinimumSize(QSize(300, 20))
        self.file_progress_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # Create tab widget to hold both Activity and Process Monitor
        self.activity_tabs = QTabWidget()
        self.activity_tabs.setStyleSheet("QTabWidget::pane { background: #222; border: 1px solid #444; } QTabBar::tab { background: #222; color: #ccc; padding: 6px 16px; } QTabBar::tab:selected { background: #333; color: #3fd0ea; } QTabWidget { margin: 0px; padding: 0px; } QTabBar { margin: 0px; padding: 0px; }")
        self.activity_tabs.setContentsMargins(0, 0, 0, 0)
        self.activity_tabs.setDocumentMode(False)
        self.activity_tabs.setTabPosition(QTabWidget.North)
        if self.debug:
            self.activity_tabs.setStyleSheet("border: 2px solid cyan;")
            self.activity_tabs.setToolTip("ACTIVITY_TABS")

        # Add both widgets as tabs
        self.activity_tabs.addTab(self.file_progress_list, "Activity")
        self.activity_tabs.addTab(process_monitor_widget, "Process Monitor")

        upper_hbox.addWidget(user_config_widget, stretch=11)
        upper_hbox.addWidget(self.activity_tabs, stretch=9)
        upper_hbox.setAlignment(Qt.AlignTop)
        upper_section_widget = QWidget()
        upper_section_widget.setLayout(upper_hbox)
        # Use Fixed size policy for consistent height
        upper_section_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        upper_section_widget.setMaximumHeight(280)  # Increased to show resolution dropdown
        if self.debug:
            upper_section_widget.setStyleSheet("border: 2px solid green;")
            upper_section_widget.setToolTip("UPPER_SECTION")
        main_overall_vbox.addWidget(upper_section_widget)

        # Status banner with progress indicator and "Show details" toggle
        banner_row = QHBoxLayout()
        banner_row.setContentsMargins(0, 0, 0, 0)
        banner_row.setSpacing(8)
        banner_row.addWidget(self.progress_indicator, 1)
        banner_row.addStretch()
        banner_row.addWidget(self.show_details_checkbox)
        banner_row_widget = QWidget()
        banner_row_widget.setLayout(banner_row)
        banner_row_widget.setMaximumHeight(45)  # Compact height
        banner_row_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        main_overall_vbox.addWidget(banner_row_widget)

        # Console output area (shown when "Show details" is checked)
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self.console.setMinimumHeight(50)
        self.console.setMaximumHeight(1000)
        self.console.setFontFamily('monospace')
        self.console.setVisible(False)  # Hidden by default (compact mode)
        if self.debug:
            self.console.setStyleSheet("border: 2px solid yellow;")
            self.console.setToolTip("CONSOLE")

        # Set up scroll tracking for professional auto-scroll behavior
        self._setup_scroll_tracking()

        # Wrap button row in widget for debug borders
        btn_row_widget = QWidget()
        btn_row_widget.setLayout(btn_row)
        btn_row_widget.setMaximumHeight(50)
        if self.debug:
            btn_row_widget.setStyleSheet("border: 2px solid red;")
            btn_row_widget.setToolTip("BUTTON_ROW")

        # Create a container that holds console + button row with proper spacing
        console_and_buttons_widget = QWidget()
        console_and_buttons_layout = QVBoxLayout()
        console_and_buttons_layout.setContentsMargins(0, 0, 0, 0)
        console_and_buttons_layout.setSpacing(8)

        console_and_buttons_layout.addWidget(self.console, stretch=1)
        console_and_buttons_layout.addWidget(btn_row_widget)

        console_and_buttons_widget.setLayout(console_and_buttons_layout)
        console_and_buttons_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        console_and_buttons_widget.setFixedHeight(50)  # Lock to button row height when console is hidden
        if self.debug:
            console_and_buttons_widget.setStyleSheet("border: 2px solid lightblue;")
            console_and_buttons_widget.setToolTip("CONSOLE_AND_BUTTONS_CONTAINER")
        # Add without stretch to prevent squashing upper section
        main_overall_vbox.addWidget(console_and_buttons_widget)

        # Store references for toggle functionality
        self.console_and_buttons_widget = console_and_buttons_widget
        self.console_and_buttons_layout = console_and_buttons_layout
        self.main_overall_vbox = main_overall_vbox

        self.setLayout(main_overall_vbox)
        self.process = None
        self.log_timer = None
        self.last_log_pos = 0
        self.top_timer = QTimer(self)
        self.top_timer.timeout.connect(self.update_top_panel)
        self.top_timer.start(2000)
        self.start_btn.clicked.connect(self.validate_and_start_configure)
        self.steam_restart_finished.connect(self._on_steam_restart_finished)

        # Scroll tracking for professional auto-scroll behavior
        self._user_manually_scrolled = False
        self._was_at_bottom = True
        
        # Time tracking for workflow completion
        self._workflow_start_time = None
        
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
            self.shortcut_combo,
            # Resolution controls
            self.resolution_combo,
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
        self.modlist_log_path = get_jackify_logs_dir() / 'Configure_Existing_Modlist_workflow.log'
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

    def _on_show_details_toggled(self, checked):
        """Handle Show Details checkbox toggle"""
        self._toggle_console_visibility(checked)

    def _toggle_console_visibility(self, is_checked):
        """Toggle console visibility and window size"""
        main_window = None
        try:
            parent = self.parent()
            while parent and not isinstance(parent, QMainWindow):
                parent = parent.parent()
            if parent and isinstance(parent, QMainWindow):
                main_window = parent
        except Exception:
            pass

        if is_checked:
            # Show console
            self.console.setVisible(True)
            self.console.setMinimumHeight(200)
            self.console.setMaximumHeight(16777215)
            self.console.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

            # Allow expansion when console is visible
            if hasattr(self, 'console_and_buttons_widget'):
                self.console_and_buttons_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
                self.console_and_buttons_widget.setMinimumHeight(0)
                self.console_and_buttons_widget.setMaximumHeight(16777215)
                self.console_and_buttons_widget.updateGeometry()

            # Stop CPU tracking when showing console
            self.file_progress_list.stop_cpu_tracking()

            # Expand window
            if main_window:
                try:
                    from PySide6.QtCore import QSize
                    # On Steam Deck, keep fullscreen; on other systems, set normal window state
                    if not (hasattr(main_window, 'system_info') and main_window.system_info.is_steamdeck):
                        main_window.showNormal()
                    main_window.setMaximumHeight(16777215)
                    main_window.setMinimumHeight(0)
                    expanded_min = 900
                    current_size = main_window.size()
                    target_height = max(expanded_min, 900)
                    main_window.setMinimumHeight(expanded_min)
                    main_window.resize(current_size.width(), target_height)
                    self.main_overall_vbox.invalidate()
                    self.updateGeometry()
                except Exception:
                    pass
        else:
            # Hide console
            self.console.setVisible(False)
            self.console.setMinimumHeight(0)
            self.console.setMaximumHeight(0)
            self.console.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)

            # Lock height when console is hidden
            if hasattr(self, 'console_and_buttons_widget'):
                self.console_and_buttons_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                self.console_and_buttons_widget.setFixedHeight(50)
                self.console_and_buttons_widget.updateGeometry()

            # CPU tracking will start when user clicks "Start Configuration", not here
            # (Removed to avoid blocking showEvent)

            # Collapse window
            if main_window:
                try:
                    from PySide6.QtCore import QSize
                    # Use fixed compact height for consistency across all workflow screens
                    compact_height = 620
                    # On Steam Deck, keep fullscreen; on other systems, set normal window state
                    if not (hasattr(main_window, 'system_info') and main_window.system_info.is_steamdeck):
                        main_window.showNormal()
                    set_responsive_minimum(main_window, min_width=960, min_height=compact_height)
                    current_size = main_window.size()
                    main_window.resize(current_size.width(), compact_height)
                except Exception:
                    pass

    def _handle_progress_update(self, text):
        """Handle progress updates - update console, activity window, and progress indicator"""
        # Always append to console
        self._safe_append_text(text)

        # Parse the message to update UI widgets
        message_lower = text.lower()

        # Update progress indicator based on key status messages
        if "setting protontricks permissions" in message_lower or "permissions" in message_lower:
            self.progress_indicator.set_status("Setting permissions...", 20)
        elif "applying curated registry" in message_lower or "registry" in message_lower:
            self.progress_indicator.set_status("Applying registry files...", 40)
        elif "installing wine components" in message_lower or "wine component" in message_lower:
            self.progress_indicator.set_status("Installing wine components...", 60)
        elif "dotnet" in message_lower and "fix" in message_lower:
            self.progress_indicator.set_status("Applying dotnet fixes...", 75)
        elif "setting ownership" in message_lower or "ownership and permissions" in message_lower:
            self.progress_indicator.set_status("Setting permissions...", 85)
        elif "verifying" in message_lower:
            self.progress_indicator.set_status("Verifying setup...", 90)
        elif "steam integration complete" in message_lower or "configuration complete" in message_lower:
            self.progress_indicator.set_status("Configuration complete", 100)

        # Update activity window with generic configuration status
        # Only update if message contains meaningful progress (not blank lines or separators)
        if text.strip() and not text.strip().startswith('='):
            # Show generic "Configuring modlist..." in activity window
            self.file_progress_list.update_files(
                [],
                current_phase="Configuring",
                summary_info={"current": 1, "total": 1, "label": "Setting up modlist"}
            )

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

    def validate_and_start_configure(self):
        # Reload config to pick up any settings changes made in Settings dialog
        self.config_handler.reload_config()

        # Rotate log file at start of each workflow run (keep 5 backups)
        from jackify.backend.handlers.logging_handler import LoggingHandler
        from pathlib import Path
        log_handler = LoggingHandler()
        log_handler.rotate_log_file_per_run(Path(self.modlist_log_path), backup_count=5)

        # Initialize progress indicator
        self.progress_indicator.set_status("Preparing to configure...", 0)

        # Start CPU tracking
        self.file_progress_list.start_cpu_tracking()

        # Disable controls during configuration
        self._disable_controls_during_operation()
        
        # Get selected shortcut
        idx = self.shortcut_combo.currentIndex() - 1  # Account for 'Please Select...'
        from jackify.frontends.gui.services.message_service import MessageService
        if idx < 0 or idx >= len(self.shortcut_map):
            MessageService.critical(self, "No Shortcut Selected", "Please select a ModOrganizer.exe Steam shortcut to configure.", safety_level="medium")
            self._enable_controls_after_operation()
            return
        shortcut = self.shortcut_map[idx]
        modlist_name = shortcut.get('AppName', shortcut.get('appname', ''))
        install_dir = shortcut.get('StartDir', shortcut.get('startdir', ''))
        if not modlist_name or not install_dir:
            MessageService.critical(self, "Invalid Shortcut", "The selected shortcut is missing required information.", safety_level="medium")
            self._enable_controls_after_operation()
            return
        resolution = self.resolution_combo.currentText()
        # Handle resolution saving
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
        # Start the workflow (no shortcut creation needed)
        self.start_workflow(modlist_name, install_dir, resolution)

    def start_workflow(self, modlist_name, install_dir, resolution):
        """Start the configuration workflow using backend service directly"""
        # CRITICAL: Reload config from disk to pick up any settings changes from Settings dialog
        # This ensures Proton version and winetricks settings are current
        self.config_handler._load_config()

        try:
            # Start time tracking
            self._workflow_start_time = time.time()

            from jackify import __version__ as jackify_version
            self._safe_append_text(f"Jackify v{jackify_version}")
            self._safe_append_text("[Jackify] Starting post-install configuration...")
            
            # Create configuration thread using backend service
            from PySide6.QtCore import QThread, Signal
            
            class ConfigurationThread(QThread):
                progress_update = Signal(str)
                configuration_complete = Signal(bool, str, str, bool)
                error_occurred = Signal(str)
                
                def __init__(self, modlist_name, install_dir, resolution):
                    super().__init__()
                    self.modlist_name = modlist_name
                    self.install_dir = install_dir
                    self.resolution = resolution
                    
                def run(self):
                    try:
                        from jackify.backend.models.configuration import SystemInfo
                        from jackify.backend.services.modlist_service import ModlistService
                        from jackify.backend.models.modlist import ModlistContext
                        from pathlib import Path
                        import os
                        
                        # Initialize backend service
                        system_info = SystemInfo(is_steamdeck=False)  # TODO: Detect Steam Deck
                        modlist_service = ModlistService(system_info)
                        
                        # Create modlist context for existing modlist configuration
                        mo2_exe_path = os.path.join(self.install_dir, "ModOrganizer.exe")
                        modlist_context = ModlistContext(
                            name=self.modlist_name,
                            install_dir=Path(self.install_dir),
                            download_dir=Path(self.install_dir).parent / 'Downloads',  # Default
                            game_type='skyrim',  # Default for now - TODO: detect from modlist
                            nexus_api_key='',  # Not needed for configuration-only
                            modlist_value='',  # Not needed for existing modlist
                            modlist_source='existing',
                            skip_confirmation=True
                        )
                        
                        # For existing modlists, add resolution if specified
                        if self.resolution != "Leave unchanged":
                            modlist_context.resolution = self.resolution.split()[0]
                        # Note: If "Leave unchanged" is selected, resolution stays None (no fallback needed)
                        
                        # Define callbacks
                        def progress_callback(message):
                            self.progress_update.emit(message)
                            
                        def completion_callback(success, message, modlist_name, enb_detected=False):
                            self.configuration_complete.emit(success, message, modlist_name, enb_detected)
                            
                        def manual_steps_callback(modlist_name, retry_count):
                            # Existing modlists shouldn't need manual steps, but handle gracefully
                            self.progress_update.emit(f"Note: Manual steps callback triggered for {modlist_name} (retry {retry_count})")
                        
                        # Call the working configuration service method
                        self.progress_update.emit("Starting existing modlist configuration...")
                        
                        # For existing modlists, call configure_modlist_post_steam directly
                        # since Steam setup and manual steps should already be done
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
            self.config_thread = ConfigurationThread(modlist_name, install_dir, resolution)
            self.config_thread.progress_update.connect(self._handle_progress_update)
            self.config_thread.configuration_complete.connect(self.on_configuration_complete)
            self.config_thread.error_occurred.connect(self.on_configuration_error)
            self.config_thread.start()
            
        except Exception as e:
            self._safe_append_text(f"[ERROR] Failed to start configuration: {e}")
            MessageService.critical(self, "Configuration Error", f"Failed to start configuration: {e}", safety_level="medium")
    
    def on_configuration_complete(self, success, message, modlist_name):
        """Handle configuration completion"""
        # Re-enable all controls when workflow completes
        self._enable_controls_after_operation()
        
        if success:
            # Calculate time taken
            time_taken = self._calculate_time_taken()

            # Clear Activity window before showing success dialog
            self.file_progress_list.clear()

            # Show success dialog with celebration
            success_dialog = SuccessDialog(
                modlist_name=modlist_name,
                workflow_type="configure_existing",
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

    def show_manual_steps_dialog(self, extra_warning=""):
        modlist_name = self.shortcut_combo.currentText().split('(')[0].strip() or "your modlist"
        msg = (
            f"<b>Manual Proton Setup Required for <span style='color:#3fd0ea'>{modlist_name}</span></b><br>"
            "After Steam restarts, complete the following steps in Steam:<br>"
            f"1. Locate the '<b>{modlist_name}</b>' entry in your Steam Library<br>"
            "2. Right-click and select 'Properties'<br>"
            "3. Switch to the 'Compatibility' tab<br>"
            "4. Check the box labeled 'Force the use of a specific Steam Play compatibility tool'<br>"
            "5. Select 'Proton - Experimental' from the dropdown menu<br>"
            "6. Close the Properties window<br>"
            f"7. Launch '<b>{modlist_name}</b>' from your Steam Library<br>"
            "8. Wait for Wabbajack to download its files and fully load<br>"
            "9. Once Wabbajack has fully loaded, CLOSE IT completely and return here<br>"
            "<br>Once you have completed ALL the steps above, click OK to continue."
            f"{extra_warning}"
        )
        reply = MessageService.question(self, "Manual Steps Required", msg, safety_level="medium")
        if reply == QMessageBox.Yes:
            if self.config_process and self.config_process.state() == QProcess.Running:
                self.config_process.write(b'\n')
                self.config_process.waitForBytesWritten(1000)
            self._config_prompt_state = None
            self._manual_steps_buffer = []
        else:
            # User clicked Cancel or closed the dialog - cancel the workflow
            self._safe_append_text("\n🛑 Manual steps cancelled by user. Workflow stopped.")
            # Terminate the configuration process
            if self.config_process and self.config_process.state() == QProcess.Running:
                self.config_process.terminate()
                self.config_process.waitForFinished(2000)
            # Re-enable all controls
            self._enable_controls_after_operation()
            self.cancel_btn.setVisible(True)

    def show_next_steps_dialog(self, message):
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QHBoxLayout, QApplication
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

    def go_back(self):
        """Navigate back to main menu and restore window size"""
        # Emit collapse signal to restore compact mode
        self.resize_request.emit('collapse')

        # Restore window size before navigating away
        try:
            main_window = self.window()
            if main_window:
                from PySide6.QtCore import QSize
                from ..utils import apply_window_size_and_position

                # Only set minimum size - DO NOT RESIZE
                main_window.setMaximumSize(QSize(16777215, 16777215))
                set_responsive_minimum(main_window, min_width=960, min_height=420)
                # DO NOT resize - let window stay at current size
        except Exception:
            pass

        if self.stacked_widget:
            self.stacked_widget.setCurrentIndex(self.main_menu_index)

    def cleanup_processes(self):
        """Clean up any running processes when the window closes or is cancelled"""
        # Stop CPU tracking if active
        if hasattr(self, 'file_progress_list'):
            self.file_progress_list.stop_cpu_tracking()

        # Clean up configuration thread if running
        if hasattr(self, 'config_thread') and self.config_thread.isRunning():
            self.config_thread.terminate()
            self.config_thread.wait(1000)

    def cancel_and_cleanup(self):
        """Handle Cancel button - clean up processes and go back"""
        self.cleanup_processes()
        self.go_back()

    def showEvent(self, event):
        """Called when the widget becomes visible - ensure collapsed state"""
        super().showEvent(event)

        # Load shortcuts asynchronously (only once, on first show) to avoid blocking UI
        if not self._shortcuts_loaded:
            # Load in background thread to avoid blocking UI
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, self._load_shortcuts_async)
            self._shortcuts_loaded = True

        # Ensure initial collapsed layout each time this screen is opened
        try:
            from PySide6.QtCore import Qt as _Qt
            # Ensure checkbox is unchecked without emitting signals
            if self.show_details_checkbox.isChecked():
                self.show_details_checkbox.blockSignals(True)
                self.show_details_checkbox.setChecked(False)
                self.show_details_checkbox.blockSignals(False)
            # Force collapsed state
            self._toggle_console_visibility(False)
            
            # Only set minimum size - DO NOT RESIZE
            main_window = self.window()
            if main_window:
                from PySide6.QtCore import QSize
                main_window.setMaximumSize(QSize(16777215, 16777215))
                set_responsive_minimum(main_window, min_width=960, min_height=420)
                # DO NOT resize - let window stay at current size
        except Exception as e:
            # If initial collapse fails, log but don't crash
            print(f"Warning: Failed to set initial collapsed state: {e}")
    
    def hideEvent(self, event):
        """Clean up thread when screen is hidden"""
        super().hideEvent(event)
        # Clean up shortcut loader thread if it's still running
        if self._shortcut_loader is not None:
            if self._shortcut_loader.isRunning():
                self._shortcut_loader.finished_signal.disconnect()
                self._shortcut_loader.terminate()
                self._shortcut_loader.wait(1000)  # Wait up to 1 second for cleanup
            self._shortcut_loader = None
    
    def _load_shortcuts_async(self):
        """Load ModOrganizer.exe shortcuts asynchronously to avoid blocking UI"""
        from PySide6.QtCore import QThread, Signal, QObject
        
        class ShortcutLoaderThread(QThread):
            finished_signal = Signal(list)  # Emits list of shortcuts when done
            error_signal = Signal(str)  # Emits error message if something goes wrong
            
            def run(self):
                try:
                    # Suppress all logging/output in background thread to avoid reentrant stderr issues
                    import logging
                    import sys
                    
                    # Temporarily redirect stderr to avoid reentrant calls
                    old_stderr = sys.stderr
                    try:
                        # Use a null device or StringIO to capture errors without writing to stderr
                        from io import StringIO
                        sys.stderr = StringIO()
                        
                        # Fetch shortcuts for ModOrganizer.exe using existing backend functionality
                        from jackify.backend.handlers.modlist_handler import ModlistHandler  
                        
                        # Initialize modlist handler with empty config dict to use default initialization
                        modlist_handler = ModlistHandler({})
                        discovered_modlists = modlist_handler.discover_executable_shortcuts("ModOrganizer.exe")
                        
                        # Convert to shortcut_handler format for UI compatibility
                        shortcuts = []
                        for modlist in discovered_modlists:
                            # Convert discovered modlist format to shortcut format
                            shortcut = {
                                'AppName': modlist.get('name', 'Unknown'),
                                'AppID': modlist.get('appid', ''),
                                'StartDir': modlist.get('path', ''),
                                'Exe': f"{modlist.get('path', '')}/ModOrganizer.exe"
                            }
                            shortcuts.append(shortcut)
                        
                        # Restore stderr before emitting signal
                        sys.stderr = old_stderr
                        self.finished_signal.emit(shortcuts)
                    except Exception as inner_e:
                        # Restore stderr before emitting error
                        sys.stderr = old_stderr
                        error_msg = str(inner_e)
                        self.error_signal.emit(error_msg)
                        self.finished_signal.emit([])
                except Exception as e:
                    # Fallback error handling
                    error_msg = str(e)
                    self.error_signal.emit(error_msg)
                    self.finished_signal.emit([])
        
        # Show loading state in dropdown
        if hasattr(self, 'shortcut_combo'):
            self.shortcut_combo.clear()
            self.shortcut_combo.addItem("Loading modlists...")
            self.shortcut_combo.setEnabled(False)
        
        # Clean up any existing thread first
        if self._shortcut_loader is not None:
            if self._shortcut_loader.isRunning():
                self._shortcut_loader.finished_signal.disconnect()
                self._shortcut_loader.terminate()
                self._shortcut_loader.wait(1000)  # Wait up to 1 second
            self._shortcut_loader = None
        
        # Start background thread
        self._shortcut_loader = ShortcutLoaderThread()
        self._shortcut_loader.finished_signal.connect(self._on_shortcuts_loaded)
        self._shortcut_loader.error_signal.connect(self._on_shortcuts_error)
        self._shortcut_loader.start()
    
    def _on_shortcuts_loaded(self, shortcuts):
        """Update UI when shortcuts are loaded"""
        self.mo2_shortcuts = shortcuts
        
        # Update the dropdown
        if hasattr(self, 'shortcut_combo'):
            self.shortcut_combo.clear()
            self.shortcut_combo.setEnabled(True)
            self.shortcut_combo.addItem("Please Select...")
            self.shortcut_map.clear()
            
            for shortcut in self.mo2_shortcuts:
                display = f"{shortcut.get('AppName', shortcut.get('appname', 'Unknown'))} ({shortcut.get('StartDir', shortcut.get('startdir', ''))})"
                self.shortcut_combo.addItem(display)
                self.shortcut_map.append(shortcut)
    
    def _on_shortcuts_error(self, error_msg):
        """Handle errors from shortcut loading thread"""
        # Log error from main thread (safe to write to stderr here)
        debug_print(f"Warning: Failed to load shortcuts: {error_msg}")
        # Update UI to show error state
        if hasattr(self, 'shortcut_combo'):
            self.shortcut_combo.clear()
            self.shortcut_combo.setEnabled(True)
            self.shortcut_combo.addItem("Error loading modlists - please try again")

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
                # Include configuration threads that might be running
                config_threads = (
                    hasattr(self, 'config_thread') and 
                    self.config_thread and 
                    self.config_thread.isRunning() and
                    ("python" in line_lower or "jackify" in line_lower)
                )
                
                if (heavy_processes or configure_processes or config_threads) and "jackify-gui.py" not in line_lower:
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

    def _on_steam_restart_finished(self, success, message):
        pass 

    def refresh_modlist_list(self):
        """Refresh the modlist dropdown by re-detecting ModOrganizer.exe shortcuts (async)"""
        # Use async loading to avoid blocking UI
        self._shortcuts_loaded = False  # Allow reload
        self._load_shortcuts_async() 

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

    def reset_screen_to_defaults(self):
        """Reset the screen to default state when navigating back from main menu"""
        # Clear the shortcut selection
        self.shortcut_combo.clear()
        self.shortcut_map.clear()
        # Auto-refresh modlist list when screen is entered
        self.refresh_modlist_list()

        # Clear console and process monitor
        self.console.clear()
        self.process_monitor.clear()

        # Reset resolution combo to saved config preference
        saved_resolution = self.resolution_service.get_saved_resolution()
        if saved_resolution:
            combo_items = [self.resolution_combo.itemText(i) for i in range(self.resolution_combo.count())]
            resolution_index = self.resolution_service.get_resolution_index(saved_resolution, combo_items)
            self.resolution_combo.setCurrentIndex(resolution_index)
        elif self.resolution_combo.count() > 0:
            self.resolution_combo.setCurrentIndex(0)  # Fallback to "Leave unchanged"

        # Re-enable controls (in case they were disabled from previous errors)
        self._enable_controls_after_operation()

    def cleanup(self):
        """Clean up any running threads when the screen is closed"""
        debug_print("DEBUG: cleanup called - cleaning up ConfigurationThread")
        
        # Clean up config thread if running
        if hasattr(self, 'config_thread') and self.config_thread and self.config_thread.isRunning():
            debug_print("DEBUG: Terminating ConfigurationThread")
            try:
                self.config_thread.progress_update.disconnect()
                self.config_thread.configuration_complete.disconnect()
                self.config_thread.error_occurred.disconnect()
            except:
                pass
            self.config_thread.terminate()
            self.config_thread.wait(2000)  # Wait up to 2 seconds 