"""UI setup and control management for ConfigureExistingModlistScreen (Mixin)."""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton,
    QGridLayout, QTextEdit, QSizePolicy, QTabWidget, QCheckBox, QMainWindow
)
from PySide6.QtCore import Qt, QSize, QTimer
import os
import subprocess
from ..shared_theme import JACKIFY_COLOR_BLUE
from ..utils import set_responsive_minimum
from jackify.frontends.gui.widgets.progress_indicator import OverallProgressIndicator
from jackify.frontends.gui.widgets.file_progress_list import FileProgressList
from jackify.backend.handlers.shortcut_handler import ShortcutHandler
import logging

logger = logging.getLogger(__name__)
class ConfigureExistingModlistUIMixin:
    """Mixin providing UI setup and control management for ConfigureExistingModlistScreen."""

    def __init__(self, stacked_widget=None, main_menu_index=0, system_info=None):
        super().__init__()
        logger.debug("ConfigureExistingModlistScreen __init__ called")
        self.stacked_widget = stacked_widget
        self.main_menu_index = main_menu_index
        from jackify.backend.models.configuration import SystemInfo
        self.system_info = system_info or SystemInfo(is_steamdeck=False)
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
        self._pending_appid_to_select = None  # Set by request_select_appid() (Dashboard prefill)

        # Initialize progress reporting components
        self.progress_indicator = OverallProgressIndicator(show_progress_bar=True)
        self.progress_indicator.set_status("Ready to configure", 0)
        self.file_progress_list = FileProgressList()
        self._post_install_sequence = self._build_post_install_sequence()
        self._post_install_total_steps = len(self._post_install_sequence)
        self._post_install_current_step = 0
        self._post_install_active = False
        self._post_install_last_label = ""
        self._bsa_hold_deadline = 0.0

        # Create "Show Details" checkbox
        self.show_details_checkbox = QCheckBox("Show details")
        self.show_details_checkbox.setChecked(False)  # Start collapsed
        self.show_details_checkbox.setToolTip("Toggle between activity summary and detailed console output")
        self.show_details_checkbox.toggled.connect(self._on_show_details_toggled)

        # --- UI Layout ---
        main_overall_vbox = QVBoxLayout(self)
        main_overall_vbox.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        main_overall_vbox.setContentsMargins(50, 50, 50, 0)  # No bottom margin
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
        form_grid.setVerticalSpacing(6)
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
        # Numbered guidance when empty, short one-liner once modlists are listed - text is
        # kept in sync with self.mo2_shortcuts by _update_shortcut_info_label().
        self.shortcut_info_label = QLabel()
        self.shortcut_info_label.setWordWrap(True)
        form_grid.addWidget(self.shortcut_info_label, 1, 0, 1, 2)
        self._update_shortcut_info_label()
        # --- Resolution selector ---
        resolution_label = QLabel("Resolution:")
        self.resolution_combo = QComboBox()
        self.resolution_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.resolution_combo.addItem("Leave unchanged")
        self.resolution_combo.addItems(self.resolution_service.get_resolution_list())
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
            logger.debug(f"Loaded saved resolution: {saved_resolution} (index: {resolution_index})")
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
        user_config_vbox.addWidget(form_section_widget)
        btn_row = QHBoxLayout()
        btn_row.setAlignment(Qt.AlignHCenter)
        self.start_btn = QPushButton("Start Configuration")
        btn_row.addWidget(self.start_btn)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.cancel_and_cleanup)
        btn_row.addWidget(self.cancel_btn)
        user_config_widget = QWidget()
        user_config_widget.setLayout(user_config_vbox)
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

        # Set up scroll tracking for professional auto-scroll behavior
        self._setup_scroll_tracking()

        btn_row_widget = QWidget()
        btn_row_widget.setLayout(btn_row)
        btn_row_widget.setMaximumHeight(50)

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
