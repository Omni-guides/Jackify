"""UI setup methods for InstallTTWScreen (Mixin)."""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QHBoxLayout, QLineEdit, QPushButton, QGridLayout, QFileDialog, QTextEdit, QSizePolicy, QCheckBox, QFrame, QTabWidget
from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QFont
from ..shared_theme import JACKIFY_COLOR_BLUE, DEBUG_BORDERS
from jackify.frontends.gui.services.message_service import open_url
from jackify.backend.handlers.wabbajack_parser import WabbajackParser
from jackify.frontends.gui.widgets.file_progress_list import FileProgressList


class TTWUISetupMixin:
    """Mixin providing UI initialization for InstallTTWScreen."""

    def __init__(self, stacked_widget=None, main_menu_index=0, system_info=None):
        super().__init__()
        self.stacked_widget = stacked_widget
        self.main_menu_index = main_menu_index
        self.system_info = system_info
        self.debug = DEBUG_BORDERS
        self.online_modlists = {}  # {game_type: [modlist_dict, ...]}
        self.modlist_details = {}  # {modlist_name: modlist_dict}

        # Initialize log path (can be refreshed via refresh_paths method)
        self.refresh_paths()

        # Initialize services early
        from jackify.backend.services.api_key_service import APIKeyService
        from jackify.backend.services.resolution_service import ResolutionService
        from jackify.backend.services.protontricks_detection_service import ProtontricksDetectionService
        from jackify.backend.handlers.config_handler import ConfigHandler
        self.api_key_service = APIKeyService()
        self.resolution_service = ResolutionService()
        self.config_handler = ConfigHandler()
        self.protontricks_service = ProtontricksDetectionService()

        # Modlist integration mode tracking
        self._integration_mode = False
        self._integration_modlist_name = None
        self._integration_install_dir = None

        # Somnium guidance tracking
        self._show_somnium_guidance = False
        self._somnium_install_dir = None

        # Scroll tracking for professional auto-scroll behavior
        self._user_manually_scrolled = False
        self._was_at_bottom = True
        
        # Initialize Wabbajack parser for game detection
        self.wabbajack_parser = WabbajackParser()
        # Remember original main window geometry/min-size to restore on expand
        self._saved_geometry = None
        self._saved_min_size = None

        main_overall_vbox = QVBoxLayout(self)
        main_overall_vbox.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        # Match other workflow screens
        main_overall_vbox.setContentsMargins(50, 50, 50, 0)
        main_overall_vbox.setSpacing(12)
        if self.debug:
            self.setStyleSheet("border: 2px solid magenta;")

        # --- Header (title, description) ---
        header_widget = QWidget()
        header_layout = QVBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(2)

        # Title
        title = QLabel("<b>Install Tale of Two Wastelands (TTW)</b>")
        title.setStyleSheet(f"font-size: 20px; color: {JACKIFY_COLOR_BLUE};")
        title.setAlignment(Qt.AlignHCenter)
        header_layout.addWidget(title)

        header_layout.addSpacing(10)

        # Description area with fixed height
        desc = QLabel(
            "This screen allows you to install Tale of Two Wastelands (TTW) using TTW_Linux_Installer. "
            "Configure your options and start the installation."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #ccc; font-size: 13px;")
        desc.setAlignment(Qt.AlignHCenter)
        desc.setMaximumHeight(50)  # Fixed height for description zone
        header_layout.addWidget(desc)

        header_layout.addSpacing(12)

        header_widget.setLayout(header_layout)
        header_widget.setFixedHeight(120)  # Fixed total header height to match other screens
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
        user_config_vbox.setSpacing(4)  # Reduce spacing between major form sections
        
        # --- Instructions ---
        instruction_text = QLabel(
            "Tale of Two Wastelands installation requires a .mpi file you can get from: "
            '<a href="https://mod.pub/ttw/133/files">https://mod.pub/ttw/133/files</a> '
            "(requires a user account for ModPub)"
        )
        instruction_text.setWordWrap(True)
        instruction_text.setStyleSheet("color: #ccc; font-size: 12px; margin: 0px; padding: 0px; line-height: 1.2;")
        instruction_text.setTextInteractionFlags(Qt.TextBrowserInteraction)
        instruction_text.linkActivated.connect(open_url)
        user_config_vbox.addWidget(instruction_text)
        
        # --- Compact Form Grid for inputs (align with other screens) ---
        form_grid = QGridLayout()
        form_grid.setHorizontalSpacing(12)
        form_grid.setVerticalSpacing(6)
        form_grid.setContentsMargins(0, 0, 0, 0)

        # Row 0: TTW .mpi File location
        file_label = QLabel("TTW .mpi File location:")
        self.file_edit = QLineEdit()
        self.file_edit.setMaximumHeight(25)
        self.file_edit.textChanged.connect(self._update_start_button_state)
        self.file_btn = QPushButton("Browse")
        self.file_btn.clicked.connect(self.browse_wabbajack_file)
        file_hbox = QHBoxLayout()
        file_hbox.addWidget(self.file_edit)
        file_hbox.addWidget(self.file_btn)
        form_grid.addWidget(file_label, 0, 0, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        form_grid.addLayout(file_hbox, 0, 1)

        # Row 1: Output Directory
        install_dir_label = QLabel("Output Directory:")
        self.install_dir_edit = QLineEdit(self.config_handler.get_modlist_install_base_dir())
        self.install_dir_edit.setMaximumHeight(25)
        self.browse_install_btn = QPushButton("Browse")
        self.browse_install_btn.clicked.connect(self.browse_install_dir)
        install_dir_hbox = QHBoxLayout()
        install_dir_hbox.addWidget(self.install_dir_edit)
        install_dir_hbox.addWidget(self.browse_install_btn)
        form_grid.addWidget(install_dir_label, 1, 0, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        form_grid.addLayout(install_dir_hbox, 1, 1)

        # --- TTW_Linux_Installer Status aligned in form grid (row 2) ---
        ttw_installer_label = QLabel("TTW_Linux_Installer Status:")
        self.ttw_installer_status = QLabel("Checking...")
        self.ttw_installer_btn = QPushButton("Install now")
        self.ttw_installer_btn.setStyleSheet("""
            QPushButton:hover { opacity: 0.95; }
            QPushButton:disabled { opacity: 0.6; }
        """)
        self.ttw_installer_btn.setVisible(False)
        self.ttw_installer_btn.clicked.connect(self.install_ttw_installer)
        ttw_installer_hbox = QHBoxLayout()
        ttw_installer_hbox.setContentsMargins(0, 0, 0, 0)
        ttw_installer_hbox.setSpacing(8)
        ttw_installer_hbox.addWidget(self.ttw_installer_status)
        ttw_installer_hbox.addWidget(self.ttw_installer_btn)
        ttw_installer_hbox.addStretch()
        form_grid.addWidget(ttw_installer_label, 2, 0, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        form_grid.addLayout(ttw_installer_hbox, 2, 1)

        # --- Game Requirements aligned in form grid (row 3) ---
        game_req_label = QLabel("Game Requirements:")
        self.fallout3_status = QLabel("Fallout 3: Checking...")
        self.fallout3_status.setStyleSheet("color: #ccc;")
        self.fnv_status = QLabel("Fallout New Vegas: Checking...")
        self.fnv_status.setStyleSheet("color: #ccc;")
        game_req_hbox = QHBoxLayout()
        game_req_hbox.setContentsMargins(0, 0, 0, 0)
        game_req_hbox.setSpacing(16)
        game_req_hbox.addWidget(self.fallout3_status)
        game_req_hbox.addWidget(self.fnv_status)
        game_req_hbox.addStretch()
        form_grid.addWidget(game_req_label, 3, 0, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        form_grid.addLayout(game_req_hbox, 3, 1)

        form_group = QWidget()
        form_group.setLayout(form_grid)
        user_config_vbox.addWidget(form_group)
        
        # (TTW_Linux_Installer and Game Requirements now aligned in form_grid above)
        
        # --- Buttons ---
        btn_row = QHBoxLayout()
        btn_row.setAlignment(Qt.AlignHCenter)
        self.start_btn = QPushButton("Start Installation")
        self.start_btn.setEnabled(False)  # Disabled until requirements are met
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

        # Add stretches to center buttons row
        btn_row.insertStretch(0, 1)
        btn_row.addStretch(1)

        # Show Details Checkbox (collapsible console)
        self.show_details_checkbox = QCheckBox("Show details")
        # Start collapsed by default (console hidden until user opts in)
        self.show_details_checkbox.setChecked(False)
        self.show_details_checkbox.setToolTip("Toggle between activity summary and detailed console output")
        # Use toggled(bool) for reliable signal and map to our handler
        try:
            self.show_details_checkbox.toggled.connect(self._on_show_details_toggled)
        except Exception:
            # Fallback to stateChanged if toggled is unavailable
            self.show_details_checkbox.stateChanged.connect(self._toggle_console_visibility)
        # Checkbox placed in status banner row, right-aligned

        # Wrap button row in widget for debug borders
        btn_row_widget = QWidget()
        btn_row_widget.setLayout(btn_row)
        btn_row_widget.setMaximumHeight(50)  # Limit height to make it more compact
        if self.debug:
            btn_row_widget.setStyleSheet("border: 2px solid red;")
            btn_row_widget.setToolTip("BUTTON_ROW")
        # Keep a reference for dynamic sizing when collapsing/expanding
        self.btn_row_widget = btn_row_widget
        user_config_widget = QWidget()
        user_config_widget.setLayout(user_config_vbox)
        user_config_widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        if self.debug:
            user_config_widget.setStyleSheet("border: 2px solid orange;")
            user_config_widget.setToolTip("USER_CONFIG_WIDGET")

        # Right: Tabbed interface with Activity and Process Monitor
        # Both tabs are always available, user can switch between them
        self.file_progress_list = FileProgressList()
        self.file_progress_list.setMinimumSize(QSize(300, 20))
        self.file_progress_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

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
        self.upper_section_widget = QWidget()
        self.upper_section_widget.setLayout(upper_hbox)
        # Use Fixed size policy for consistent height
        self.upper_section_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.upper_section_widget.setMaximumHeight(280)  # Fixed height to match other workflow screens
        if self.debug:
            self.upper_section_widget.setStyleSheet("border: 2px solid green;")
            self.upper_section_widget.setToolTip("UPPER_SECTION")
        main_overall_vbox.addWidget(self.upper_section_widget)

        # --- Status Banner (shows high-level progress) ---
        self.status_banner = QLabel("Ready to install")
        self.status_banner.setAlignment(Qt.AlignCenter)
        self.status_banner.setStyleSheet(f"""
            background-color: #2a2a2a;
            color: {JACKIFY_COLOR_BLUE};
            padding: 6px 8px;
            border-radius: 4px;
            font-weight: bold;
            font-size: 13px;
        """)
        # Prevent banner from expanding vertically
        self.status_banner.setMaximumHeight(34)
        self.status_banner.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        # Show the banner by default so users see status even when collapsed
        self.status_banner.setVisible(True)
        # Create a compact banner row with the checkbox right-aligned
        banner_row = QHBoxLayout()
        # Minimal padding to avoid visible gaps
        banner_row.setContentsMargins(0, 0, 0, 0)
        banner_row.setSpacing(8)
        banner_row.addWidget(self.status_banner, 1)
        banner_row.addStretch()
        banner_row.addWidget(self.show_details_checkbox)
        banner_row_widget = QWidget()
        banner_row_widget.setLayout(banner_row)
        banner_row_widget.setMaximumHeight(45)  # Compact height
        banner_row_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        main_overall_vbox.addWidget(banner_row_widget)

        # Remove spacing - console should expand to fill available space
        # --- Console output area (full width, placeholder for now) ---
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        # Console starts hidden; toggled via Show details
        self.console.setMinimumHeight(0)
        self.console.setMaximumHeight(0)
        self.console.setFontFamily('monospace')
        if self.debug:
            self.console.setStyleSheet("border: 2px solid yellow;")
            self.console.setToolTip("CONSOLE")

        # Set up scroll tracking for professional auto-scroll behavior
        self._setup_scroll_tracking()

        # Add console directly so we can hide/show without affecting buttons
        main_overall_vbox.addWidget(self.console, stretch=1)
        # Place the button row after the console so it's always visible and centered
        main_overall_vbox.addWidget(btn_row_widget, alignment=Qt.AlignHCenter)

        # Store reference to main layout
        self.main_overall_vbox = main_overall_vbox
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

