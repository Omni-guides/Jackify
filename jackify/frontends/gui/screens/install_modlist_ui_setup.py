"""UI setup methods for InstallModlistScreen (Mixin)."""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QComboBox, QHBoxLayout, QLineEdit, QPushButton, QGridLayout, QFileDialog, QTextEdit, QSizePolicy, QTabWidget, QDialog, QListWidget, QListWidgetItem, QMessageBox, QProgressDialog, QApplication, QCheckBox, QStyledItemDelegate, QStyle, QTableWidget, QTableWidgetItem, QHeaderView, QMainWindow
from PySide6.QtCore import Qt, QSize, QThread, Signal, QTimer, QProcess, QMetaObject, QUrl
from PySide6.QtGui import QPixmap, QTextCursor, QColor, QPainter, QFont
from ..shared_theme import JACKIFY_COLOR_BLUE, DEBUG_BORDERS
from ..utils import ansi_to_html, set_responsive_minimum
from jackify.backend.handlers.wabbajack_parser import WabbajackParser
from jackify.backend.handlers.progress_parser import ProgressStateManager
from jackify.frontends.gui.widgets.progress_indicator import OverallProgressIndicator
from jackify.frontends.gui.widgets.file_progress_list import FileProgressList
import os
import logging

logger = logging.getLogger(__name__)
class InstallModlistUISetupMixin:
    """Mixin providing UI initialization for InstallModlistScreen."""

    def __init__(self, stacked_widget=None, main_menu_index=0, system_info=None):
        super().__init__()
        # Set size policy to prevent unnecessary expansion - let content determine size
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.stacked_widget = stacked_widget
        self.main_menu_index = main_menu_index
        from jackify.backend.models.configuration import SystemInfo
        self.system_info = system_info or SystemInfo(is_steamdeck=False)
        self.debug = DEBUG_BORDERS
        # Remember original main window geometry/min-size to restore on expand (like TTW screen)
        self._saved_geometry = None
        self._saved_min_size = None
        self.online_modlists = {}  # {game_type: [modlist_dict, ...]}
        self.modlist_details = {}  # {modlist_name: modlist_dict}

        # Initialize log path (can be refreshed via refresh_paths method)
        self.refresh_paths()

        # Initialize services early
        from jackify.backend.services.api_key_service import APIKeyService
        from jackify.backend.services.nexus_auth_service import NexusAuthService
        from jackify.backend.services.resolution_service import ResolutionService
        from jackify.backend.services.protontricks_detection_service import ProtontricksDetectionService
        from jackify.backend.handlers.config_handler import ConfigHandler
        self.api_key_service = APIKeyService()
        self.auth_service = NexusAuthService()
        self.resolution_service = ResolutionService()
        self.config_handler = ConfigHandler()
        self.protontricks_service = ProtontricksDetectionService()
        
        # Somnium guidance tracking
        self._show_somnium_guidance = False
        self._somnium_install_dir = None

        # Console deduplication tracking
        self._last_console_line = None
        
        # Gallery cache preloading tracking
        self._gallery_cache_preload_started = False
        self._gallery_cache_preload_thread = None

        # Scroll tracking for professional auto-scroll behavior
        self._user_manually_scrolled = False
        self._was_at_bottom = True
        
        # Initialize Wabbajack parser for game detection
        self.wabbajack_parser = WabbajackParser()
        
        # R&D: Initialize progress reporting components
        self.progress_state_manager = ProgressStateManager()
        self.progress_indicator = OverallProgressIndicator(show_progress_bar=True)
        self.file_progress_list = FileProgressList()  # Shows all active files (scrolls if needed)
        self._premium_notice_shown = False
        self._premium_failure_active = False
        self._installation_cancelled = False
        self._non_premium_gate_enabled = False
        self._non_premium_info_acknowledged = False
        self._pending_manual_download_events = None
        self._non_premium_info_dlg = None
        self._stalled_download_start_time = None
        self._stalled_download_notified = False
        self._stalled_data_snapshot = 0
        self._post_install_sequence = self._build_post_install_sequence()
        self._post_install_total_steps = len(self._post_install_sequence)
        self._post_install_current_step = 0
        self._post_install_active = False
        self._post_install_last_label = ""
        self._bsa_hold_deadline = 0.0

        # No throttling needed - render loop handles smooth updates at 60fps

        # R&D: Create "Show Details" checkbox (reuse TTW pattern)
        self.show_details_checkbox = QCheckBox("Show details")
        self.show_details_checkbox.setChecked(False)  # Start collapsed
        self.show_details_checkbox.setToolTip("Toggle between activity summary and detailed console output")
        self.show_details_checkbox.toggled.connect(self._on_show_details_toggled)

        main_overall_vbox = QVBoxLayout(self)
        self.main_overall_vbox = main_overall_vbox  # Store reference for expand/collapse
        main_overall_vbox.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        main_overall_vbox.setContentsMargins(50, 50, 50, 0)  # No bottom margin
        main_overall_vbox.setSpacing(0)  # No spacing between widgets to eliminate gaps
        if self.debug:
            self.setStyleSheet("border: 2px solid magenta;")

        # --- Header (title, description) ---
        header_layout = QVBoxLayout()
        header_layout.setSpacing(1)  # Reduce spacing between title and description
        # Title (no logo)
        title = QLabel("<b>Install a Modlist</b>")
        title.setStyleSheet(f"font-size: 20px; color: {JACKIFY_COLOR_BLUE}; margin: 0px; padding: 0px;")
        title.setAlignment(Qt.AlignHCenter)
        title.setMaximumHeight(30)  # Force compact height
        header_layout.addWidget(title)
        # Description
        desc = QLabel(
            "This screen allows you to install a Wabbajack modlist using Jackify. "
            "Configure your options and start the installation."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #ccc; margin: 0px; padding: 0px; line-height: 1.2;")
        desc.setAlignment(Qt.AlignHCenter)
        desc.setMaximumHeight(40)  # Force compact height for description
        header_layout.addWidget(desc)
        header_widget = QWidget()
        header_widget.setLayout(header_layout)
        header_widget.setMaximumHeight(75)  # Increase header height by 25% (60 + 15)
        if self.debug:
            header_widget.setStyleSheet("border: 2px solid pink;")
            header_widget.setToolTip("HEADER_SECTION")
        main_overall_vbox.addWidget(header_widget)

        # --- Upper section: user-configurables (left) + process monitor (right) ---
        upper_hbox = QHBoxLayout()
        upper_hbox.setContentsMargins(0, 0, 0, 0)
        upper_hbox.setSpacing(16)
        upper_hbox.setAlignment(Qt.AlignTop)  # Align both sides at the top
        # Left: user-configurables (form and controls)
        user_config_vbox = QVBoxLayout()
        user_config_vbox.setAlignment(Qt.AlignTop)
        user_config_vbox.setSpacing(4)  # Reduce spacing between major form sections
        user_config_vbox.setContentsMargins(0, 0, 0, 0)  # No margins to ensure tab alignment
        # --- Tabs for source selection ---
        self.source_tabs = QTabWidget()
        self.source_tabs.setStyleSheet("QTabWidget::pane { background: #222; border: 1px solid #444; } QTabBar::tab { background: #222; color: #ccc; padding: 6px 16px; } QTabBar::tab:selected { background: #333; color: #3fd0ea; } QTabWidget { margin: 0px; padding: 0px; } QTabBar { margin: 0px; padding: 0px; }")
        self.source_tabs.setContentsMargins(0, 0, 0, 0)  # Ensure no margins for alignment
        self.source_tabs.setDocumentMode(False)  # Keep frame for consistency
        self.source_tabs.setTabPosition(QTabWidget.North)  # Ensure tabs are at top
        if self.debug:
            self.source_tabs.setStyleSheet("border: 2px solid cyan;")
            self.source_tabs.setToolTip("SOURCE_TABS")
        # --- Online List Tab ---
        online_tab = QWidget()
        online_tab_vbox = QVBoxLayout()
        online_tab_vbox.setAlignment(Qt.AlignTop)
        # Online List Controls
        self.online_group = QWidget()
        online_layout = QHBoxLayout()
        online_layout.setContentsMargins(0, 0, 0, 0)
        # --- Game Type Selection ---
        self.game_types = ["Skyrim", "Fallout 4", "Fallout New Vegas", "Oblivion", "Starfield", "Oblivion Remastered", "Enderal", "Skyrim VR", "Fallout 4 VR", "Baldur's Gate 3", "Other"]
        self.game_type_btn = QPushButton("Please Select...")
        self.game_type_btn.setMinimumWidth(200)
        self.game_type_btn.clicked.connect(self.open_game_type_dialog)
        # --- Modlist Selection ---
        self.modlist_btn = QPushButton("Select Modlist")
        self.modlist_btn.setMinimumWidth(300)
        self.modlist_btn.setMaximumWidth(300)
        self.modlist_btn.clicked.connect(self.open_modlist_dialog)
        self.modlist_btn.setEnabled(False)
        online_layout.addWidget(QLabel("Game Type:"))
        online_layout.addWidget(self.game_type_btn)
        online_layout.addSpacing(4)
        online_layout.addWidget(QLabel("Modlist:"))
        online_layout.addWidget(self.modlist_btn)
        self.online_group.setLayout(online_layout)
        online_tab_vbox.addWidget(self.online_group)
        online_tab.setLayout(online_tab_vbox)
        self.source_tabs.addTab(online_tab, "Select Modlist")
        # --- File Picker Tab ---
        file_tab = QWidget()
        file_tab_vbox = QVBoxLayout()
        file_tab_vbox.setAlignment(Qt.AlignTop)
        self.file_group = QWidget()
        file_layout = QHBoxLayout()
        file_layout.setContentsMargins(0, 0, 0, 0)
        self.file_edit = QLineEdit()
        self.file_edit.setMinimumWidth(400)
        self.file_btn = QPushButton("Browse")
        self.file_btn.clicked.connect(self.browse_wabbajack_file)
        file_layout.addWidget(QLabel(".wabbajack File:"))
        file_layout.addWidget(self.file_edit)
        file_layout.addWidget(self.file_btn)
        self.file_group.setLayout(file_layout)
        file_tab_vbox.addWidget(self.file_group)
        file_tab.setLayout(file_tab_vbox)
        self.source_tabs.addTab(file_tab, "Use .wabbajack File")
        user_config_vbox.addWidget(self.source_tabs)
        # --- Install/Downloads Dir/API Key (reuse Tuxborn style) ---
        form_grid = QGridLayout()
        form_grid.setHorizontalSpacing(12)
        form_grid.setVerticalSpacing(6)  # Increased from 1 to 6 for better readability
        form_grid.setContentsMargins(0, 0, 0, 0)
        # Modlist Name (NEW FIELD)
        modlist_name_label = QLabel("Modlist Name:")
        self.modlist_name_edit = QLineEdit()
        self.modlist_name_edit.setMaximumHeight(25)  # Force compact height
        form_grid.addWidget(modlist_name_label, 0, 0, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        form_grid.addWidget(self.modlist_name_edit, 0, 1)
        # Install Dir
        install_dir_label = QLabel("Install Directory:")
        self.install_dir_edit = QLineEdit(self.config_handler.get_modlist_install_base_dir())
        self.install_dir_edit.setMaximumHeight(25)  # Force compact height
        self.browse_install_btn = QPushButton("Browse")
        self.browse_install_btn.clicked.connect(self.browse_install_dir)
        install_dir_hbox = QHBoxLayout()
        install_dir_hbox.addWidget(self.install_dir_edit)
        install_dir_hbox.addWidget(self.browse_install_btn)
        form_grid.addWidget(install_dir_label, 1, 0, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        form_grid.addLayout(install_dir_hbox, 1, 1)
        # Downloads Dir
        downloads_dir_label = QLabel("Downloads Directory:")
        self.downloads_dir_edit = QLineEdit(self.config_handler.get_modlist_downloads_base_dir())
        self.downloads_dir_edit.setMaximumHeight(25)  # Force compact height
        self.browse_downloads_btn = QPushButton("Browse")
        self.browse_downloads_btn.clicked.connect(self.browse_downloads_dir)
        downloads_dir_hbox = QHBoxLayout()
        downloads_dir_hbox.addWidget(self.downloads_dir_edit)
        downloads_dir_hbox.addWidget(self.browse_downloads_btn)
        form_grid.addWidget(downloads_dir_label, 2, 0, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        form_grid.addLayout(downloads_dir_hbox, 2, 1)

        # Nexus Login (OAuth)
        nexus_login_label = QLabel("Nexus Login:")
        self.nexus_status = QLabel("Checking...")
        self.nexus_status.setStyleSheet("color: #ccc;")
        self.nexus_login_btn = QPushButton("Authorise")
        self.nexus_login_btn.setStyleSheet("""
            QPushButton:hover { opacity: 0.95; }
            QPushButton:disabled { opacity: 0.6; }
        """)
        self.nexus_login_btn.setMaximumWidth(90)
        self.nexus_login_btn.setVisible(False)
        self.nexus_login_btn.clicked.connect(self._handle_nexus_login_click)

        nexus_hbox = QHBoxLayout()
        nexus_hbox.setContentsMargins(0, 0, 0, 0)
        nexus_hbox.setSpacing(8)
        nexus_hbox.addWidget(self.nexus_login_btn)
        nexus_hbox.addWidget(self.nexus_status)
        nexus_hbox.addStretch()

        form_grid.addWidget(nexus_login_label, 3, 0, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        form_grid.addLayout(nexus_hbox, 3, 1)

        # Update nexus status on init
        self._update_nexus_status()


        # --- Resolution Dropdown ---
        resolution_label = QLabel("Resolution:")
        self.resolution_combo = QComboBox()
        self.resolution_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.resolution_combo.addItem("Leave unchanged")
        self.resolution_combo.addItems(self.resolution_service.get_resolution_list())
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
        form_grid.addWidget(resolution_label, 5, 0, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        
        # Horizontal layout for resolution dropdown and right-side checkboxes
        resolution_and_restart_layout = QHBoxLayout()
        resolution_and_restart_layout.setSpacing(12)

        self.resolution_combo.setMaximumWidth(280)
        resolution_and_restart_layout.addWidget(self.resolution_combo)

        resolution_and_restart_layout.addStretch()

        right_checks_layout = QVBoxLayout()
        right_checks_layout.setSpacing(4)
        right_checks_layout.setContentsMargins(0, 0, 0, 0)

        self.auto_restart_checkbox = QCheckBox("Auto-accept Steam restart")
        self.auto_restart_checkbox.setChecked(False)
        self.auto_restart_checkbox.setToolTip("When checked, Steam restart dialog will be automatically accepted, allowing unattended installation")
        right_checks_layout.addWidget(self.auto_restart_checkbox)

        engine_row = QHBoxLayout()
        engine_row.setSpacing(4)
        engine_row.setContentsMargins(0, 0, 0, 0)
        self.engine_checkbox = QCheckBox("Use Experimental Engine")
        self.engine_checkbox.setToolTip("Use CLF3 (SulfurNitride) as the install engine instead of jackify-engine")
        self.engine_checkbox.toggled.connect(self._on_engine_checkbox_toggled)
        engine_row.addWidget(self.engine_checkbox)
        engine_whats_this = QLabel('<a href="https://github.com/Omni-guides/Jackify/wiki/Install-Engines" style="color: #6fa8dc; font-size: 11px;">(what\'s this?)</a>')
        engine_whats_this.setOpenExternalLinks(False)
        engine_whats_this.linkActivated.connect(self._open_url_safe)
        engine_row.addWidget(engine_whats_this)
        engine_row.addStretch()
        engine_row_widget = QWidget()
        engine_row_widget.setLayout(engine_row)
        self._engine_row_widget = engine_row_widget
        right_checks_layout.addWidget(engine_row_widget)
        self._init_engine_checkbox()

        resolution_and_restart_layout.addLayout(right_checks_layout)

        form_grid.addLayout(resolution_and_restart_layout, 5, 1)
        form_section_widget = QWidget()
        form_section_widget.setLayout(form_grid)
        # Let form section size naturally to its content
        # Don't force a fixed height - let it calculate based on grid content
        form_section_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        if self.debug:
            form_section_widget.setStyleSheet("border: 2px solid blue;")
            form_section_widget.setToolTip("FORM_SECTION")
        user_config_vbox.addWidget(form_section_widget)
        # --- Buttons ---
        btn_row = QHBoxLayout()
        btn_row.setAlignment(Qt.AlignHCenter)
        self.start_btn = QPushButton("Start Installation")
        btn_row.addWidget(self.start_btn)
        

        
        # Cancel button (goes back to menu)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.cancel_and_cleanup)
        btn_row.addWidget(self.cancel_btn)
        
        # Cancel Installation button (appears during installation)
        self.cancel_install_btn = QPushButton("Cancel Installation")
        self.cancel_install_btn.clicked.connect(self.cancel_installation)
        self.cancel_install_btn.setVisible(False)  # Hidden by default
        btn_row.addWidget(self.cancel_install_btn)
        
        # Wrap button row in widget for debug borders
        btn_row_widget = QWidget()
        btn_row_widget.setLayout(btn_row)
        btn_row_widget.setMaximumHeight(50)  # Limit height to make it more compact
        if self.debug:
            btn_row_widget.setStyleSheet("border: 2px solid red;")
            btn_row_widget.setToolTip("BUTTON_ROW")
        user_config_widget = QWidget()
        self.user_config_widget = user_config_widget  # Store reference for height calculation
        user_config_widget.setLayout(user_config_vbox)
        user_config_widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)  # Fixed height - don't expand unnecessarily
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
        # Match size policy - Process Monitor should expand to fill available space
        process_monitor_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        if self.debug:
            process_monitor_widget.setStyleSheet("border: 2px solid purple;")
            process_monitor_widget.setToolTip("PROCESS_MONITOR")
        # Store reference
        self.process_monitor_widget = process_monitor_widget
        
        # Set up File Progress List (Activity tab)
        # Match Process Monitor size policy exactly - expand to fill available space
        self.file_progress_list.setMinimumSize(QSize(300, 20))
        self.file_progress_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        # Create tab widget to hold both Activity and Process Monitor
        # Match styling of source_tabs on the left for consistency
        self.activity_tabs = QTabWidget()
        self.activity_tabs.setStyleSheet("QTabWidget::pane { background: #222; border: 1px solid #444; } QTabBar::tab { background: #222; color: #ccc; padding: 6px 16px; } QTabBar::tab:selected { background: #333; color: #3fd0ea; } QTabWidget { margin: 0px; padding: 0px; } QTabBar { margin: 0px; padding: 0px; }")
        self.activity_tabs.setContentsMargins(0, 0, 0, 0)  # Ensure no margins for alignment
        self.activity_tabs.setDocumentMode(False)  # Match left tabs
        self.activity_tabs.setTabPosition(QTabWidget.North)  # Ensure tabs are at top
        if self.debug:
            self.activity_tabs.setStyleSheet("border: 2px solid cyan;")
            self.activity_tabs.setToolTip("ACTIVITY_TABS")
        
        # Add both widgets as tabs
        self.activity_tabs.addTab(self.file_progress_list, "Activity")
        self.activity_tabs.addTab(process_monitor_widget, "Process Monitor")
        
        upper_hbox.addWidget(user_config_widget, stretch=1, alignment=Qt.AlignTop)
        # Add tab widget with stretch=3 to match original Process Monitor stretch
        upper_hbox.addWidget(self.activity_tabs, stretch=3, alignment=Qt.AlignTop)
        upper_section_widget = QWidget()
        self.upper_section_widget = upper_section_widget  # Store reference for showEvent
        upper_section_widget.setLayout(upper_hbox)
        # Use Fixed size policy - the height should be based on LEFT side only
        # Consistent height for both Active Files and Process Monitor
        upper_section_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        # Calculate height based on LEFT side (user_config_widget) only
        self._upper_section_fixed_height = None  # Will be set in showEvent based on left side
        if self.debug:
            upper_section_widget.setStyleSheet("border: 2px solid green;")
            upper_section_widget.setToolTip("UPPER_SECTION")
        main_overall_vbox.addWidget(upper_section_widget)
        
        # Add spacing between upper section and progress banner
        main_overall_vbox.addSpacing(8)
        
        # R&D: Progress indicator banner row (similar to TTW screen)
        banner_row = QHBoxLayout()
        banner_row.setContentsMargins(0, 0, 0, 0)
        banner_row.setSpacing(8)
        banner_row.addWidget(self.progress_indicator, 1)
        banner_row.addStretch()
        banner_row.addWidget(self.show_details_checkbox)
        banner_row_widget = QWidget()
        banner_row_widget.setLayout(banner_row)
        # Constrain height to prevent unwanted vertical expansion
        banner_row_widget.setMaximumHeight(45)  # Compact height: 34px label + small margin
        banner_row_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        main_overall_vbox.addWidget(banner_row_widget)
        
        # Add spacing between progress banner and console/details area
        main_overall_vbox.addSpacing(8)
        
        # R&D: File progress list is now in the upper section (replacing Process Monitor)
        # Console shows below when "Show details" is checked
        # File progress list is already added to upper_hbox above
        
        # Remove spacing - console should expand to fill available space
        # --- Console output area (full width, placeholder for now) ---
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        # R&D: Console starts hidden (only shows when "Show details" is checked)
        self.console.setMinimumHeight(0)
        self.console.setMaximumHeight(0)
        self.console.setVisible(False)
        self.console.setFontFamily('monospace')
        if self.debug:
            self.console.setStyleSheet("border: 2px solid yellow;")
            self.console.setToolTip("CONSOLE")
        
        # Set up scroll tracking for professional auto-scroll behavior
        self._setup_scroll_tracking()
        
        # Create a container that holds console + button row with proper spacing
        console_and_buttons_widget = QWidget()
        console_and_buttons_layout = QVBoxLayout()
        console_and_buttons_layout.setContentsMargins(0, 0, 0, 0)
        console_and_buttons_layout.setSpacing(0)  # No spacing - console is hidden initially
        
        # Console with stretch only when visible, buttons always at natural size
        console_and_buttons_layout.addWidget(self.console)  # No stretch initially - will be set dynamically
        console_and_buttons_layout.addWidget(btn_row_widget)  # Buttons at bottom of this container
        
        console_and_buttons_widget.setLayout(console_and_buttons_layout)
        self.console_and_buttons_widget = console_and_buttons_widget  # Store reference for stretch control
        self.console_and_buttons_layout = console_and_buttons_layout  # Store reference for spacing control
        # Use Minimum size policy - takes only the minimum space needed
        console_and_buttons_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        # Constrain height to button row only when console is hidden - match button row height exactly
        # Button row is 50px max, so container should be exactly that when collapsed
        console_and_buttons_widget.setFixedHeight(50)  # Lock to exact button row height when console is hidden
        if self.debug:
            console_and_buttons_widget.setStyleSheet("border: 2px solid lightblue;")
            console_and_buttons_widget.setToolTip("CONSOLE_AND_BUTTONS_CONTAINER")
        # Add without stretch - let it size naturally to content
        main_overall_vbox.addWidget(console_and_buttons_widget)
        self.setLayout(main_overall_vbox)

        self.current_modlists = []

        # --- Process Monitor (right) ---
        self.process = None
        self.log_timer = None
        self.last_log_pos = 0
        # --- Process Monitor Timer ---
        self.top_timer = QTimer(self)
        self.top_timer.timeout.connect(self.update_top_panel)
        self.top_timer.start(2000)
        # --- Start Installation button ---
        self.start_btn.clicked.connect(self.validate_and_start_install)
        

        
        # Initialize process tracking
        self.process = None
        
        # Initialize empty controls list - will be populated after UI is built
        self._actionable_controls = []
        
        # Now collect all actionable controls after UI is fully built
        self._collect_actionable_controls()

    def _init_engine_checkbox(self) -> None:
        from jackify.backend.services.tool_registry import get_active_engine_id
        self._engine_row_widget.setVisible(True)
        self.engine_checkbox.blockSignals(True)
        self.engine_checkbox.setChecked(get_active_engine_id() == "clf3")
        self.engine_checkbox.blockSignals(False)

    def _on_engine_checkbox_toggled(self, checked: bool) -> None:
        pass  # state is read at install time; persistent default lives in Settings
