"""
InstallModlistScreen for Jackify GUI
"""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QComboBox, QHBoxLayout, QLineEdit, QPushButton, QGridLayout, QFileDialog, QTextEdit, QSizePolicy, QTabWidget, QDialog, QListWidget, QListWidgetItem, QMessageBox, QProgressDialog, QCheckBox
from PySide6.QtCore import Qt, QSize, QThread, Signal, QTimer, QProcess, QMetaObject, QUrl
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
import re
from jackify.backend.handlers.subprocess_utils import ProcessManager
from jackify.backend.services.api_key_service import APIKeyService
from jackify.backend.services.resolution_service import ResolutionService
from jackify.backend.handlers.config_handler import ConfigHandler
from ..dialogs import SuccessDialog
from jackify.backend.handlers.validation_handler import ValidationHandler
from jackify.frontends.gui.dialogs.warning_dialog import WarningDialog
from jackify.frontends.gui.services.message_service import MessageService

def debug_print(message):
    """Print debug message only if debug mode is enabled"""
    from jackify.backend.handlers.config_handler import ConfigHandler
    config_handler = ConfigHandler()
    if config_handler.get('debug_mode', False):
        print(message)

class ModlistFetchThread(QThread):
    result = Signal(list, str)
    def __init__(self, game_type, log_path, mode='list-modlists'):
        super().__init__()
        self.game_type = game_type
        self.log_path = log_path
        self.mode = mode
    
    def run(self):
        try:
            # Use proper backend service - NOT the misnamed CLI class
            from jackify.backend.services.modlist_service import ModlistService
            from jackify.backend.models.configuration import SystemInfo
            
            # Initialize backend service
            # Detect if we're on Steam Deck
            is_steamdeck = False
            try:
                if os.path.exists('/etc/os-release'):
                    with open('/etc/os-release') as f:
                        if 'steamdeck' in f.read().lower():
                            is_steamdeck = True
            except Exception:
                pass
            
            system_info = SystemInfo(is_steamdeck=is_steamdeck)
            modlist_service = ModlistService(system_info)
            
            # Get modlists using proper backend service
            modlist_infos = modlist_service.list_modlists(game_type=self.game_type)
            # Return full modlist objects instead of just IDs to preserve enhanced metadata  
            # Only log on success, not on every call
            with open(self.log_path, 'a') as logf:
                logf.write(f"[Backend Success] Found {len(modlist_infos)} modlists for {self.game_type}\n")
            self.result.emit(modlist_infos, '')
            
        except Exception as e:
            error_msg = f"Backend service error: {str(e)}"
            with open(self.log_path, 'a') as logf:
                logf.write(f"[Backend Error] {error_msg}\n")
            self.result.emit([], error_msg)

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

class TuxbornInstallerScreen(QWidget):
    steam_restart_finished = Signal(bool, str)
    def __init__(self, stacked_widget=None, main_menu_index=0):
        super().__init__()
        debug_print("DEBUG: TuxbornInstallerScreen __init__ called")
        self.stacked_widget = stacked_widget
        self.main_menu_index = main_menu_index
        self.debug = DEBUG_BORDERS
        self.online_modlists = {}  # {game_type: [modlist_dict, ...]}
        self.modlist_details = {}  # {modlist_name: modlist_dict}

        # Path for workflow log
        self.modlist_log_path = os.path.expanduser('~/Jackify/logs/Tuxborn_Installer_workflow.log')
        os.makedirs(os.path.dirname(self.modlist_log_path), exist_ok=True)

        # Initialize services early
        from jackify.backend.services.api_key_service import APIKeyService
        from jackify.backend.services.resolution_service import ResolutionService
        from jackify.backend.handlers.config_handler import ConfigHandler
        self.api_key_service = APIKeyService()
        self.resolution_service = ResolutionService()
        self.config_handler = ConfigHandler()

        # Scroll tracking for professional auto-scroll behavior
        self._user_manually_scrolled = False
        self._was_at_bottom = True
        
        # Time tracking for workflow completion
        self._workflow_start_time = None
        
        # Manual steps retry counter (legacy - should not be used in automated workflow)
        self._manual_steps_retry_count = 0

        main_overall_vbox = QVBoxLayout(self)
        main_overall_vbox.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        main_overall_vbox.setContentsMargins(50, 25, 50, 0)  # Reduce top margin to move header closer to top
        if self.debug:
            self.setStyleSheet("border: 2px solid magenta;")

        # --- Header (title, description) ---
        header_layout = QVBoxLayout()
        header_layout.setSpacing(2)
        # Title (no logo)
        title = QLabel("<b>Tuxborn Automatic Installer</b>")
        title.setStyleSheet(f"font-size: 20px; color: {JACKIFY_COLOR_BLUE};")
        title.setAlignment(Qt.AlignHCenter)
        header_layout.addWidget(title)
        # Description
        desc = QLabel(
            "This screen allows you to install the Tuxborn modlist using Jackify's native Linux tools. "
            "Configure your options and start the installation."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #ccc;")
        desc.setAlignment(Qt.AlignHCenter)
        header_layout.addWidget(desc)
        header_widget = QWidget()
        header_widget.setLayout(header_layout)
        header_widget.setMaximumHeight(75)  # Prevent expansion, match Install a Modlist screen
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
        # --- Tabs for source selection ---
        # self.source_tabs = QTabWidget()  # REMOVE
        # --- Online List Tab ---
        # online_tab = QWidget()
        # online_tab_vbox = QVBoxLayout()
        # online_tab_vbox.setAlignment(Qt.AlignTop)
# Game selection removed - Tuxborn is pre-selected
        # online_tab_vbox.addWidget(self.online_group)
        # online_tab.setLayout(online_tab_vbox)
        # self.source_tabs.addTab(online_tab, "Select Modlist")
        # --- File Picker Tab ---
        # file_tab = QWidget()
        # file_tab_vbox = QVBoxLayout()
        # file_tab_vbox.setAlignment(Qt.AlignTop)
        # self.file_group = QWidget()
        # file_layout = QHBoxLayout()
        # file_layout.setContentsMargins(0, 0, 0, 0)
        # self.file_edit = QLineEdit()
        # self.file_edit.setMinimumWidth(400)
        # file_btn = QPushButton("Browse")
        # file_btn.clicked.connect(self.browse_wabbajack_file)
        # file_layout.addWidget(QLabel(".wabbajack File:"))
        # file_layout.addWidget(self.file_edit)
        # file_layout.addWidget(file_btn)
        # self.file_group.setLayout(file_layout)
        # file_tab_vbox.addWidget(self.file_group)
        # file_tab.setLayout(file_tab_vbox)
        # self.source_tabs.addTab(file_tab, "Use .wabbajack File")
        # user_config_vbox.addWidget(self.source_tabs)
        # --- Install/Downloads Dir/API Key (reuse Tuxborn style) ---
        form_grid = QGridLayout()
        form_grid.setHorizontalSpacing(12)
        form_grid.setVerticalSpacing(6)  # Match Install a Modlist screen spacing
        form_grid.setContentsMargins(0, 0, 0, 0)
        # Modlist Name (NEW FIELD)
        modlist_name_label = QLabel("Modlist Name:")
        self.modlist_name_edit = QLineEdit("Tuxborn")
        self.modlist_name_edit.setMaximumHeight(25)  # Force compact height
        form_grid.addWidget(modlist_name_label, 0, 0, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        form_grid.addWidget(self.modlist_name_edit, 0, 1)
        # Install Dir
        install_dir_label = QLabel("Install Directory:")
        self.install_dir_edit = QLineEdit(self.config_handler.get_modlist_install_base_dir())
        self.install_dir_edit.setMaximumHeight(25)  # Force compact height
        browse_install_btn = QPushButton("Browse")
        browse_install_btn.clicked.connect(self.browse_install_dir)
        install_dir_hbox = QHBoxLayout()
        install_dir_hbox.addWidget(self.install_dir_edit)
        install_dir_hbox.addWidget(browse_install_btn)
        form_grid.addWidget(install_dir_label, 1, 0, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        form_grid.addLayout(install_dir_hbox, 1, 1)
        # Downloads Dir
        downloads_dir_label = QLabel("Downloads Directory:")
        self.downloads_dir_edit = QLineEdit(self.config_handler.get_modlist_downloads_base_dir())
        self.downloads_dir_edit.setMaximumHeight(25)  # Force compact height
        browse_downloads_btn = QPushButton("Browse")
        browse_downloads_btn.clicked.connect(self.browse_downloads_dir)
        downloads_dir_hbox = QHBoxLayout()
        downloads_dir_hbox.addWidget(self.downloads_dir_edit)
        downloads_dir_hbox.addWidget(browse_downloads_btn)
        form_grid.addWidget(downloads_dir_label, 2, 0, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        form_grid.addLayout(downloads_dir_hbox, 2, 1)
        # API Key
        api_key_label = QLabel("Nexus API Key:")
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setMaximumHeight(25)  # Force compact height
        # Services already initialized above
        # Set up obfuscation timer and state
        self.api_key_obfuscation_timer = QTimer(self)
        self.api_key_obfuscation_timer.setSingleShot(True)
        self.api_key_obfuscation_timer.timeout.connect(self._obfuscate_api_key)
        self.api_key_original_text = ""
        self.api_key_is_obfuscated = False
        # Connect events for obfuscation
        self.api_key_edit.textChanged.connect(self._on_api_key_text_changed)
        self.api_key_edit.focusInEvent = self._on_api_key_focus_in
        self.api_key_edit.focusOutEvent = self._on_api_key_focus_out
        # Load saved API key if available
        saved_key = self.api_key_service.get_saved_api_key()
        if saved_key:
            self.api_key_original_text = saved_key  # Set original text first
            self.api_key_edit.setText(saved_key)
            self._obfuscate_api_key()  # Immediately obfuscate saved keys
        form_grid.addWidget(api_key_label, 3, 0, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        form_grid.addWidget(self.api_key_edit, 3, 1)
        # API Key save checkbox and info (row 4)
        api_save_layout = QHBoxLayout()
        api_save_layout.setContentsMargins(0, 0, 0, 0)
        api_save_layout.setSpacing(8)
        self.save_api_key_checkbox = QCheckBox("Save API Key")
        self.save_api_key_checkbox.setChecked(self.api_key_service.has_saved_api_key())
        self.save_api_key_checkbox.toggled.connect(self._on_api_key_save_toggled)
        api_save_layout.addWidget(self.save_api_key_checkbox, alignment=Qt.AlignTop)
        
        # Validate button removed - validation now happens silently on save checkbox toggle
        api_info = QLabel(
            '<small>Storing your API Key locally is done so at your own risk.<br>'
            'You can get your API key at: <a href="https://www.nexusmods.com/users/myaccount?tab=api">'
            'https://www.nexusmods.com/users/myaccount?tab=api</a></small>'
        )
        api_info.setOpenExternalLinks(False)
        api_info.linkActivated.connect(self._open_url_safe)
        api_info.setWordWrap(True)
        api_info.setAlignment(Qt.AlignLeft)
        api_save_layout.addWidget(api_info, stretch=1)
        api_save_widget = QWidget()
        api_save_widget.setLayout(api_save_layout)
        # Set reasonable maximum height to prevent excessive size while allowing natural height
        api_save_widget.setMaximumHeight(55)  # Increase by another 2px for better fit
        if self.debug:
            api_save_widget.setStyleSheet("border: 2px solid lightblue;")
            api_save_widget.setToolTip("API_SAVE_SECTION")
        form_grid.addWidget(api_save_widget, 4, 1)
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
        form_grid.addWidget(resolution_label, 5, 0, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        form_grid.addWidget(self.resolution_combo, 5, 1)
        form_section_widget = QWidget()
        form_section_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        form_section_widget.setLayout(form_grid)
        form_section_widget.setMinimumHeight(220)  # Match Install a Modlist screen
        form_section_widget.setMaximumHeight(240)  # Match Install a Modlist screen
        if self.debug:
            form_section_widget.setStyleSheet("border: 2px solid blue;")
            form_section_widget.setToolTip("FORM_SECTION")
        user_config_vbox.addWidget(form_section_widget)
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
        upper_section_widget.setMaximumWidth(1300)
        upper_section_widget.setMaximumHeight(235)  # Increase by another 15px for better fit
        if self.debug:
            upper_section_widget.setStyleSheet("border: 2px solid green;")
            upper_section_widget.setToolTip("UPPER_SECTION")
        main_overall_vbox.addWidget(upper_section_widget)
        # Remove spacing - console should expand to fill available space
        
        # --- Buttons (moved BEFORE console creation) ---
        btn_row = QHBoxLayout()
        btn_row.setAlignment(Qt.AlignHCenter)
        self.start_btn = QPushButton("Start Installation")
        btn_row.addWidget(self.start_btn)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.go_back)
        btn_row.addWidget(self.cancel_btn)
        self.cancel_install_btn = QPushButton("Cancel Installation")
        self.cancel_install_btn.clicked.connect(self.cancel_installation)
        self.cancel_install_btn.setVisible(False)  # Hidden until installation starts
        btn_row.addWidget(self.cancel_install_btn)
        
        btn_row_widget = QWidget()
        btn_row_widget.setLayout(btn_row)
        btn_row_widget.setMaximumHeight(50)
        if self.debug:
            btn_row_widget.setStyleSheet("border: 2px solid red;")
            btn_row_widget.setToolTip("BUTTON_ROW")
        
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
        self.steam_restart_finished.connect(self._on_steam_restart_finished)

    def _open_url_safe(self, url):
        """Safely open URL using subprocess to avoid Qt library conflicts in PyInstaller"""
        import subprocess
        try:
            subprocess.Popen(['xdg-open', url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            print(f"Warning: Could not open URL {url}: {e}")

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

    def showEvent(self, event):
        """Called when the widget becomes visible - reload saved API key and parent directories"""
        super().showEvent(event)
        # Reload saved API key if available and field is empty
        if not self.api_key_edit.text().strip() or (self.api_key_is_obfuscated and not self.api_key_original_text.strip()):
            saved_key = self.api_key_service.get_saved_api_key()
            if saved_key:
                self.api_key_original_text = saved_key
                self.api_key_edit.setText(saved_key)
                self.api_key_is_obfuscated = False  # Start unobfuscated
                # Set checkbox state
                self.save_api_key_checkbox.setChecked(True)
                # Start obfuscation timer
                self.api_key_obfuscation_timer.start(3000)
        
        # Load saved parent directories and pre-populate fields
        self._load_saved_parent_directories()

    def _load_saved_parent_directories(self):
        """Load standard Settings menu defaults and pre-populate directory fields"""
        try:
            # Use the same Settings menu defaults as other workflows
            install_base_dir = self.config_handler.get("modlist_install_base_dir", os.path.expanduser("~/Games"))
            if install_base_dir:
                # Pre-populate with standard base + Skyrim + Tuxborn
                suggested_install_dir = os.path.join(install_base_dir, "Skyrim", "Tuxborn")
                self.install_dir_edit.setText(suggested_install_dir)
                debug_print(f"DEBUG: Pre-populated install directory with Settings default: {suggested_install_dir}")
            
            # Load standard download base directory
            downloads_base_dir = self.config_handler.get("modlist_downloads_base_dir", os.path.expanduser("~/Games/Modlist_Downloads"))
            if downloads_base_dir:
                # Pre-populate with standard downloads base
                self.downloads_dir_edit.setText(downloads_base_dir)
                debug_print(f"DEBUG: Pre-populated download directory with Settings default: {downloads_base_dir}")
                
        except Exception as e:
            print(f"DEBUG: Error loading Settings menu defaults: {e}")
    
    def _save_parent_directories(self, install_dir, downloads_dir):
        """Removed automatic saving - user should set defaults in settings"""
        pass

    def _on_api_key_text_changed(self, text):
        """Handle API key text changes for obfuscation timing"""
        if not self.api_key_is_obfuscated:
            self.api_key_original_text = text
            # Restart the obfuscation timer (3 seconds after last change)
            self.api_key_obfuscation_timer.stop()
            if text.strip():  # Only start timer if there's actual text
                self.api_key_obfuscation_timer.start(3000)  # 3 seconds
        else:
            # If currently obfuscated and user is typing/pasting, un-obfuscate
            if text != self.api_key_service.get_api_key_display(self.api_key_original_text):
                self.api_key_is_obfuscated = False
                self.api_key_original_text = text
                if text.strip():
                    self.api_key_obfuscation_timer.start(3000)
    
    def _on_api_key_focus_out(self, event):
        """Handle API key field losing focus - immediately obfuscate"""
        QLineEdit.focusOutEvent(self.api_key_edit, event)
        self._obfuscate_api_key()

    def _on_api_key_focus_in(self, event):
        """Handle API key field gaining focus - de-obfuscate if needed"""
        # Call the original focusInEvent first
        QLineEdit.focusInEvent(self.api_key_edit, event)
        if self.api_key_is_obfuscated:
            self.api_key_edit.blockSignals(True)
            self.api_key_edit.setText(self.api_key_original_text)
            self.api_key_is_obfuscated = False
            self.api_key_edit.blockSignals(False)
        self.api_key_obfuscation_timer.stop()

    def _obfuscate_api_key(self):
        """Obfuscate the API key text field"""
        if not self.api_key_is_obfuscated and self.api_key_original_text.strip():
            self.api_key_edit.blockSignals(True)
            masked_text = self.api_key_service.get_api_key_display(self.api_key_original_text)
            self.api_key_edit.setText(masked_text)
            self.api_key_is_obfuscated = True
            self.api_key_edit.blockSignals(False)

    def _get_actual_api_key(self):
        """Get the actual API key value (not the obfuscated version)"""
        if self.api_key_is_obfuscated:
            return self.api_key_original_text
        else:
            return self.api_key_edit.text()

    def open_game_type_dialog(self):
        dlg = SelectionDialog("Select Game Type", self.game_types, self)
        if dlg.exec() == QDialog.Accepted and dlg.selected_item:
            self.game_type_btn.setText(dlg.selected_item)
            self.fetch_modlists_for_game_type(dlg.selected_item)

    def fetch_modlists_for_game_type(self, game_type):
        self.modlist_btn.setText("Fetching modlists...")
        self.modlist_btn.setEnabled(False)
        game_type_map = {
            "Skyrim": "skyrim",
            "Fallout 4": "fallout4",
            "Fallout New Vegas": "falloutnv",
            "Oblivion": "oblivion",
            "Starfield": "starfield",
            "Oblivion Remastered": "oblivion_remastered",
            "Other": "other"
        }
        cli_game_type = game_type_map.get(game_type, "other")
        log_path = self.modlist_log_path
        # Use backend service for listing modlists
        self.fetch_thread = ModlistFetchThread(
            cli_game_type, log_path, mode='list-modlists')
        self.fetch_thread.result.connect(self.on_modlists_fetched)
        self.fetch_thread.start()

    def on_modlists_fetched(self, modlist_infos, error):
        # Handle both new format (modlist objects) and old format (string IDs) for backward compatibility
        if modlist_infos and isinstance(modlist_infos[0], str):
            # Old format - just IDs as strings
            filtered = [m for m in modlist_infos if m and not m.startswith('DEBUG:')]
            self.current_modlists = filtered
        else:
            # New format - full modlist objects with enhanced metadata
            filtered_modlists = [m for m in modlist_infos if m and hasattr(m, 'id')]
            self.current_modlists = [m.id for m in filtered_modlists]  # Keep IDs for selection
        if error:
            self.modlist_btn.setText("Error fetching modlists.")
            self.modlist_btn.setEnabled(False)
            self._safe_append_text(f"[Modlist Fetch Error]\n{error}")
        elif self.current_modlists:
            self.modlist_btn.setText("Select Modlist")
            self.modlist_btn.setEnabled(True)
        else:
            self.modlist_btn.setText("No modlists found.")
            self.modlist_btn.setEnabled(False)

    def open_modlist_dialog(self):
        if not self.current_modlists:
            return
        dlg = SelectionDialog("Select Modlist", self.current_modlists, self)
        if dlg.exec() == QDialog.Accepted and dlg.selected_item:
            self.modlist_btn.setText(dlg.selected_item)
            # Store selection as needed

    def browse_wabbajack_file(self):
        file, _ = QFileDialog.getOpenFileName(self, "Select .wabbajack File", os.path.expanduser("~"), "Wabbajack Files (*.wabbajack)")
        if file:
            self.file_edit.setText(file)

    def browse_install_dir(self):
        dir = QFileDialog.getExistingDirectory(self, "Select Install Directory", self.install_dir_edit.text())
        if dir:
            self.install_dir_edit.setText(dir)

    def browse_downloads_dir(self):
        dir = QFileDialog.getExistingDirectory(self, "Select Downloads Directory", self.downloads_dir_edit.text())
        if dir:
            self.downloads_dir_edit.setText(dir)

    def go_back(self):
        if self.stacked_widget:
            self.stacked_widget.setCurrentIndex(0)  # Return to Main Menu

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
                if (
                    ("jackify-engine" in line_lower or "7zz" in line_lower or "compressonator" in line_lower or
                     "wine" in line_lower or "wine64" in line_lower or "protontricks" in line_lower)
                    and "jackify-gui.py" not in line_lower
                ):
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

    def _on_api_key_save_toggled(self, checked):
        """Handle immediate API key saving with silent validation when checkbox is toggled"""
        try:
            if checked:
                # Save API key if one is entered
                api_key = self._get_actual_api_key().strip()
                if api_key:
                    # Silently validate API key first
                    is_valid, validation_message = self.api_key_service.validate_api_key_works(api_key)
                    if not is_valid:
                        # Show error dialog for invalid API key
                        from jackify.frontends.gui.services.message_service import MessageService
                        MessageService.critical(
                            self, 
                            "Invalid API Key", 
                            f"The API key is invalid and cannot be saved.\n\nError: {validation_message}", 
                            safety_level="low"
                        )
                        self.save_api_key_checkbox.setChecked(False)  # Uncheck on validation failure
                        return
                    
                    # API key is valid, proceed with saving
                    success = self.api_key_service.save_api_key(api_key)
                    if success:
                        self._show_api_key_feedback("✓ API key saved successfully", is_success=True)
                        print("DEBUG: API key validated and saved immediately on checkbox toggle")
                    else:
                        self._show_api_key_feedback("✗ Failed to save API key - check permissions", is_success=False)
                        # Uncheck the checkbox since save failed
                        self.save_api_key_checkbox.setChecked(False)
                        print("DEBUG: Failed to save API key immediately")
                else:
                    self._show_api_key_feedback("⚠ Enter an API key first", is_success=False)
                    # Uncheck the checkbox since no key to save
                    self.save_api_key_checkbox.setChecked(False)
            else:
                # Clear saved API key when unchecked
                if self.api_key_service.has_saved_api_key():
                    success = self.api_key_service.clear_saved_api_key()
                    if success:
                        self._show_api_key_feedback("✓ API key cleared", is_success=True)
                        print("DEBUG: Saved API key cleared immediately on checkbox toggle")
                    else:
                        self._show_api_key_feedback("✗ Failed to clear API key", is_success=False)
                        print("DEBUG: Failed to clear API key")
        except Exception as e:
            self._show_api_key_feedback(f"✗ Error: {str(e)}", is_success=False)
            self.save_api_key_checkbox.setChecked(False)
            print(f"DEBUG: Error in _on_api_key_save_toggled: {e}")
    
    def _show_api_key_feedback(self, message, is_success=True):
        """Show temporary feedback message for API key operations"""
        # Use tooltip for immediate feedback
        color = "#22c55e" if is_success else "#ef4444"  # Green for success, red for error
        self.save_api_key_checkbox.setToolTip(message)
        
        # Temporarily change checkbox style to show feedback
        original_style = self.save_api_key_checkbox.styleSheet()
        feedback_style = f"QCheckBox {{ color: {color}; font-weight: bold; }}"
        self.save_api_key_checkbox.setStyleSheet(feedback_style)
        
        # Reset style and tooltip after 3 seconds
        from PySide6.QtCore import QTimer
        def reset_feedback():
            self.save_api_key_checkbox.setStyleSheet(original_style)
            self.save_api_key_checkbox.setToolTip("")
        
        QTimer.singleShot(3000, reset_feedback)
    

    def validate_and_start_install(self):
        try:
            debug_print('DEBUG: validate_and_start_install called')
            
            # Rotate log file at start of each workflow run (keep 5 backups)
            from jackify.backend.handlers.logging_handler import LoggingHandler
            from pathlib import Path
            log_handler = LoggingHandler()
            log_handler.rotate_log_file_per_run(Path(self.modlist_log_path), backup_count=5)
            
            # Start time tracking
            self._workflow_start_time = time.time()
            
            # Hardcode Tuxborn values
            modlist = 'Tuxborn/Tuxborn'
            install_mode = 'online'
            install_dir = self.install_dir_edit.text().strip()
            downloads_dir = self.downloads_dir_edit.text().strip()
            # Get the actual API key (not obfuscated version)
            api_key = self._get_actual_api_key().strip()
            validation_handler = ValidationHandler()
            from pathlib import Path
            is_safe, reason = validation_handler.is_safe_install_directory(Path(install_dir))
            if not is_safe:
                dlg = WarningDialog(reason, parent=self)
                if not dlg.exec() or not dlg.confirmed:
                    return
            if not os.path.isdir(install_dir):
                create = MessageService.question(self, "Create Directory?",
                    f"The install directory does not exist:\n{install_dir}\n\nWould you like to create it?",
                    safety_level="low")
                if create == QMessageBox.Yes:
                    try:
                        os.makedirs(install_dir, exist_ok=True)
                    except Exception as e:
                        MessageService.critical(self, "Error", f"Failed to create install directory:\n{e}", safety_level="medium")
                        return
                else:
                    return
            if not os.path.isdir(downloads_dir):
                create = MessageService.question(self, "Create Directory?",
                    f"The downloads directory does not exist:\n{downloads_dir}\n\nWould you like to create it?",
                    safety_level="low")
                if create == QMessageBox.Yes:
                    try:
                        os.makedirs(downloads_dir, exist_ok=True)
                    except Exception as e:
                        MessageService.critical(self, "Error", f"Failed to create downloads directory:\n{e}", safety_level="medium")
                        return
                else:
                    return
            # Handle API key saving BEFORE validation (to match settings dialog behavior)
            if self.save_api_key_checkbox.isChecked():
                if api_key:
                    success = self.api_key_service.save_api_key(api_key)
                    if success:
                        debug_print("DEBUG: API key saved successfully")
                    else:
                        debug_print("DEBUG: Failed to save API key")
            else:
                # If checkbox is unchecked, clear any saved API key
                if self.api_key_service.has_saved_api_key():
                    self.api_key_service.clear_saved_api_key()
                    debug_print("DEBUG: Saved API key cleared")
            
            # Validate API key for installation purposes
            if not api_key or not self.api_key_service._validate_api_key_format(api_key):
                MessageService.warning(self, "Invalid API Key", "Please enter a valid Nexus API Key.", safety_level="low")
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
            
            # Handle parent directory saving
            self._save_parent_directories(install_dir, downloads_dir)
            
            self.console.clear()
            self.process_monitor.clear()
            self.start_btn.setEnabled(False)
            debug_print(f'DEBUG: Calling run_modlist_installer with modlist={modlist}, install_dir={install_dir}, downloads_dir={downloads_dir}, api_key={api_key[:6]}..., install_mode={install_mode}')
            self.run_modlist_installer(modlist, install_dir, downloads_dir, api_key, install_mode)
        except Exception as e:
            debug_print(f"DEBUG: Exception in validate_and_start_install: {e}")

    def run_modlist_installer(self, modlist, install_dir, downloads_dir, api_key, install_mode='online'):
        debug_print('DEBUG: run_modlist_installer called - USING THREADED BACKEND WRAPPER')
        
        # Clear console for fresh installation output
        self.console.clear()
        self._safe_append_text("Starting Tuxborn installation with custom progress handling...")
        
        # Update UI state for installation
        self.start_btn.setEnabled(False)
        self.cancel_btn.setVisible(False)
        self.cancel_install_btn.setVisible(True)
        
        # Create installation thread
        from PySide6.QtCore import QThread, Signal
        
        class InstallationThread(QThread):
            output_received = Signal(str)
            progress_received = Signal(str)
            installation_finished = Signal(bool, str)
            
            def __init__(self, modlist, install_dir, downloads_dir, api_key, modlist_name):
                super().__init__()
                self.modlist = modlist
                self.install_dir = install_dir
                self.downloads_dir = downloads_dir
                self.api_key = api_key
                self.modlist_name = modlist_name
                self.cancelled = False
                self.process_manager = None
            
            def cancel(self):
                self.cancelled = True
                if self.process_manager:
                    self.process_manager.cancel()
            
            def run(self):
                import re
                try:
                    engine_path = get_jackify_engine_path()
                    cmd = [engine_path, "install", "-m", self.modlist, "-o", self.install_dir, "-d", self.downloads_dir]
                    
                    # Check for debug mode and add --debug flag
                    from jackify.backend.handlers.config_handler import ConfigHandler
                    config_handler = ConfigHandler()
                    debug_mode = config_handler.get('debug_mode', False)
                    if debug_mode:
                        cmd.append('--debug')
                        debug_print("DEBUG: Added --debug flag to jackify-engine command")
                    env = os.environ.copy()
                    env['NEXUS_API_KEY'] = self.api_key
                    self.process_manager = ProcessManager(cmd, env=env, text=False, bufsize=0)
                    ansi_escape = re.compile(rb'\x1b\[[0-9;?]*[ -/]*[@-~]')
                    buffer = b''
                    while True:
                        if self.cancelled:
                            self.cancel()
                            break
                        char = self.process_manager.read_stdout_char()
                        if not char:
                            break
                        buffer += char
                        while b'\n' in buffer or b'\r' in buffer:
                            if b'\r' in buffer and (buffer.index(b'\r') < buffer.index(b'\n') if b'\n' in buffer else True):
                                line, buffer = buffer.split(b'\r', 1)
                                line = ansi_escape.sub(b'', line)
                                self.progress_received.emit(line.decode('utf-8', errors='replace'))
                            elif b'\n' in buffer:
                                line, buffer = buffer.split(b'\n', 1)
                                line = ansi_escape.sub(b'', line)
                                self.output_received.emit(line.decode('utf-8', errors='replace'))
                    if buffer:
                        line = ansi_escape.sub(b'', buffer)
                        self.output_received.emit(line.decode('utf-8', errors='replace'))
                    self.process_manager.wait()
                    if self.cancelled:
                        self.installation_finished.emit(False, "Installation cancelled by user")
                    elif self.process_manager.proc.returncode == 0:
                        self.installation_finished.emit(True, "Installation completed successfully")
                    else:
                        self.installation_finished.emit(False, "Installation failed")
                except Exception as e:
                    import traceback
                    error_msg = f"Installation error: {e}\n{traceback.format_exc()}"
                    self.installation_finished.emit(False, error_msg)
                finally:
                    if self.cancelled and self.process_manager:
                        self.process_manager.cancel()
        
        # Create and start thread
        modlist_name = self.modlist_name_edit.text().strip()
        self.install_thread = InstallationThread(modlist, install_dir, downloads_dir, api_key, modlist_name)
        
        # Connect signals for proper GUI updates
        self.install_thread.output_received.connect(self.on_installation_output)
        self.install_thread.progress_received.connect(self.on_installation_progress)
        self.install_thread.installation_finished.connect(self.on_installation_finished)
        
        # Start installation
        self.install_thread.start()
        
        self._safe_append_text("Installation thread started...")
    
    def on_installation_output(self, message):
        """Handle regular output from installation thread"""
        self._safe_append_text(message)
    
    def on_installation_progress(self, progress_message):
        """Replace the last line in the console for progress updates"""
        cursor = self.console.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.movePosition(QTextCursor.StartOfLine, QTextCursor.KeepAnchor)
        cursor.removeSelectedText()
        cursor.insertText(progress_message)
        # Don't force scroll for progress updates - let user control
    
    def on_installation_finished(self, success, message):
        """Handle installation completion"""
        if success:
            self._safe_append_text(f"\nSuccess: {message}")
            self.process_finished(0, QProcess.NormalExit, message)  # Simulate successful completion
        else:
            self._safe_append_text(f"\nError: {message}")
            self.process_finished(1, QProcess.CrashExit, message)  # Simulate error

    def process_finished(self, exit_code, exit_status, message=None):
        # Reset button states
        self.start_btn.setEnabled(True)
        self.cancel_btn.setVisible(True)
        self.cancel_install_btn.setVisible(False)
        
        # Import MessageService at the top of the method for all code paths
        from jackify.frontends.gui.services.message_service import MessageService
        
        if exit_code == 0:
            # Only show the install complete dialog here
            reply = MessageService.question(
                self, "Modlist Install Complete!",
                "Modlist install complete!\n\nWould you like to add this modlist to Steam and configure it now? Steam will restart, closing any game you have open!",
                safety_level="medium"
            )
            if reply == QMessageBox.Yes:
                # Proceed directly to restart Steam - automated workflow will handle shortcut creation
                self.restart_steam_and_configure()
            else:
                # User selected "No" - show completion message and keep GUI open
                self._safe_append_text("\nModlist installation completed successfully!")
                self._safe_append_text("Note: You can manually configure Steam integration later if needed.")
                MessageService.information(
                    self, "Installation Complete", 
                    "Modlist installation completed successfully!\n\n"
                    "The modlist has been installed but Steam integration was skipped.\n"
                    "You can manually add the modlist to Steam later if desired.",
                    safety_level="medium"
                )
        else:
            # Check for user cancellation
            if message and "cancelled by user" in message.lower():
                MessageService.information(self, "Installation Cancelled", "The installation was cancelled by the user.", safety_level="low")
            else:
                MessageService.critical(self, "Install Failed", "The modlist install failed. Please check the console output for details.", safety_level="medium")
        self.console.moveCursor(QTextCursor.End)

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

    def restart_steam_and_configure(self):
        """Restart Steam using backend service directly - DECOUPLED FROM CLI"""
        print("DEBUG: restart_steam_and_configure called - using direct backend service")
        progress = QProgressDialog("Restarting Steam...", None, 0, 0, self)
        progress.setWindowTitle("Restarting Steam")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        progress.show()
        self.setEnabled(False)
        
        def do_restart():
            print("DEBUG: do_restart thread started - using direct backend service")
            try:
                from jackify.backend.handlers.shortcut_handler import ShortcutHandler
                
                # Use backend service directly instead of CLI subprocess
                shortcut_handler = ShortcutHandler(steamdeck=False)  # TODO: Use proper system info
                
                print("DEBUG: About to call secure_steam_restart()")
                success = shortcut_handler.secure_steam_restart()
                print(f"DEBUG: secure_steam_restart() returned: {success}")
                
                out = "Steam restart completed successfully." if success else "Steam restart failed."
                
            except Exception as e:
                print(f"DEBUG: Exception in do_restart: {e}")
                success = False
                out = str(e)
                
            self.steam_restart_finished.emit(success, out)
            
        threading.Thread(target=do_restart, daemon=True).start()
        self._steam_restart_progress = progress  # Store to close later

    def _on_steam_restart_finished(self, success, out):
        print("DEBUG: _on_steam_restart_finished called")
        # Safely cleanup progress dialog on main thread
        if hasattr(self, '_steam_restart_progress') and self._steam_restart_progress:
            try:
                self._steam_restart_progress.close()
                self._steam_restart_progress.deleteLater()  # Use deleteLater() for safer cleanup
            except Exception as e:
                print(f"DEBUG: Error closing progress dialog: {e}")
            finally:
                self._steam_restart_progress = None
        
        self.setEnabled(True)
        if success:
            self._safe_append_text("Steam restarted successfully.")
            
            # Use automated prefix service instead of manual steps
            self._safe_append_text("Starting automated Steam setup workflow...")
            self._safe_append_text("This will automatically configure Steam integration without manual steps.")
            
            # Start automated prefix workflow
            modlist_name = self.modlist_name_edit.text().strip()
            install_dir = self.install_dir_edit.text().strip()
            mo2_exe_path = os.path.join(install_dir, "ModOrganizer.exe")
            self._start_automated_prefix_workflow(modlist_name, install_dir, mo2_exe_path)
        else:
            self._safe_append_text("Failed to restart Steam.\n" + out)
            MessageService.critical(self, "Steam Restart Failed", "Failed to restart Steam automatically. Please restart Steam manually, then try again.", safety_level="medium")

    def _start_automated_prefix_workflow(self, modlist_name, install_dir, mo2_exe_path):
        """Start the automated prefix workflow using AutomatedPrefixService"""
        try:
            from jackify.backend.services.automated_prefix_service import AutomatedPrefixService
            
            self._safe_append_text(f"Initializing automated Steam setup for '{modlist_name}'...")
            
            # Initialize the automated prefix service
            prefix_service = AutomatedPrefixService()
            
            # Define progress callback for GUI updates
            def progress_callback(message):
                self._safe_append_text(f"{message}")
            
            # Run the automated workflow
            self._safe_append_text("Starting automated Steam shortcut creation and configuration...")
            result = prefix_service.run_working_workflow(
                modlist_name, install_dir, mo2_exe_path, progress_callback
            )
            
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
                        self.continue_configuration_after_automated_prefix(new_appid, modlist_name, install_dir, last_timestamp)
                    else:
                        self._safe_append_text(f"Automated Steam setup failed")
                        self._safe_append_text("Please check the logs for details.")
                        self.start_btn.setEnabled(True)
                        self.cancel_btn.setVisible(True)
                        self.cancel_install_btn.setVisible(False)
            elif isinstance(result, tuple) and len(result) == 3:
                # Fallback for old format (backward compatibility)
                success, prefix_path, new_appid = result
                if success:
                    self._safe_append_text(f"Automated Steam setup completed successfully!")
                    self._safe_append_text(f"New AppID assigned: {new_appid}")
                    
                    # Continue with post-Steam configuration
                    self.continue_configuration_after_automated_prefix(new_appid, modlist_name, install_dir)
                else:
                    self._safe_append_text(f"Automated Steam setup failed")
                    self._safe_append_text("Please check the logs for details.")
                    self.start_btn.setEnabled(True)
                    self.cancel_btn.setVisible(True)
                    self.cancel_install_btn.setVisible(False)
            else:
                # Handle unexpected result format
                self._safe_append_text(f"Automated Steam setup failed - unexpected result format")
                self._safe_append_text("Please check the logs for details.")
                self.start_btn.setEnabled(True)
                self.cancel_btn.setVisible(True)
                self.cancel_install_btn.setVisible(False)
                
        except Exception as e:
            self._safe_append_text(f"Error during automated Steam setup: {str(e)}")
            self._safe_append_text("Please check the logs for details.")
            self.start_btn.setEnabled(True)
            self.cancel_btn.setVisible(True)
            self.cancel_install_btn.setVisible(False)

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
        modlist_name = self.modlist_name_edit.text().strip()
        install_dir = self.install_dir_edit.text().strip()
        mo2_exe_path = os.path.join(install_dir, "ModOrganizer.exe")
        self._start_automated_prefix_workflow(modlist_name, install_dir, mo2_exe_path)

    def show_manual_steps_dialog(self, extra_warning=""):
        modlist_name = self.modlist_name_edit.text().strip() or "your modlist"
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
            "8. Wait for Mod Organizer 2 to fully open<br>"
            "9. Once Mod Organizer has fully loaded, CLOSE IT completely and return here<br>"
            "<br>Once you have completed ALL the steps above, click OK to continue."
            f"{extra_warning}"
        )
        reply = MessageService.question(self, "Manual Steps Required", msg, safety_level="medium")
        if reply == QMessageBox.Yes:
            self.validate_manual_steps_completion()
        else:
            # User clicked Cancel or closed the dialog - cancel the workflow
            self._safe_append_text("\n🛑 Manual steps cancelled by user. Workflow stopped.")
            # Reset button states
            self.start_btn.setEnabled(True)
            self.cancel_btn.setVisible(True)
            self.cancel_install_btn.setVisible(False)

    def validate_manual_steps_completion(self):
        """Validate that manual steps were actually completed and handle retry logic"""
        modlist_name = self.modlist_name_edit.text().strip()
        install_dir = self.install_dir_edit.text().strip()
        mo2_exe_path = os.path.join(install_dir, "ModOrganizer.exe")
        
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
            modlist_handler.appid = current_appid
            modlist_handler.game_var = "skyrimspecialedition"  # Tuxborn is always Skyrim
            
            # Set compat_data_path for Proton detection
            compat_data_path_str = path_handler.find_compat_data(current_appid)
            if compat_data_path_str:
                from pathlib import Path
                modlist_handler.compat_data_path = Path(compat_data_path_str)
            
            # Check Proton version
            self._safe_append_text(f"Attempting to detect Proton version for AppID {current_appid}...")
            if modlist_handler._detect_proton_version():
                self._safe_append_text(f"Raw detected Proton version: '{modlist_handler.proton_ver}'")
                if modlist_handler.proton_ver and 'experimental' in modlist_handler.proton_ver.lower():
                    proton_ok = True
                    self._safe_append_text(f"Proton version validated: {modlist_handler.proton_ver}")
                else:
                    self._safe_append_text(f"Error: Wrong Proton version detected: '{modlist_handler.proton_ver}' (expected 'experimental' in name)")
            else:
                self._safe_append_text("Error: Could not detect Proton version from any source")
                
        except Exception as e:
            self._safe_append_text(f"Error checking Proton version: {e}")
            proton_ok = False
        
        # Check 2: Compatdata directory exists
        compatdata_ok = False
        try:
            from jackify.backend.handlers.path_handler import PathHandler
            path_handler = PathHandler()
            
            self._safe_append_text(f"Searching for compatdata directory for AppID {current_appid}...")
            prefix_path_str = path_handler.find_compat_data(current_appid)
            self._safe_append_text(f"Compatdata search result: '{prefix_path_str}'")
            
            if prefix_path_str and os.path.isdir(prefix_path_str):
                compatdata_ok = True
                self._safe_append_text(f"Compatdata directory found: {prefix_path_str}")
            else:
                if prefix_path_str:
                    self._safe_append_text(f"Error: Path exists but is not a directory: {prefix_path_str}")
                else:
                    self._safe_append_text(f"Error: No compatdata directory found for AppID {current_appid}")
                
        except Exception as e:
            self._safe_append_text(f"Error checking compatdata: {e}")
            compatdata_ok = False
        
        # Handle validation results
        if proton_ok and compatdata_ok:
            self._safe_append_text("Manual steps validation passed!")
            self._safe_append_text("Continuing configuration with updated AppID...")
            
            # Continue configuration with the corrected AppID and context
            self.continue_configuration_after_manual_steps(current_appid, modlist_name, install_dir)
        else:
            # Validation failed - handle retry logic
            missing_items = []
            if not proton_ok:
                missing_items.append("• Proton - Experimental not set")
            if not compatdata_ok:
                missing_items.append("• Shortcut not launched from Steam (no compatdata)")
            
            missing_text = "\n".join(missing_items)
            self._safe_append_text(f"Manual steps validation failed:\n{missing_text}")
            self.handle_validation_failure(missing_text)
    
    def continue_configuration_after_automated_prefix(self, new_appid, modlist_name, install_dir, last_timestamp=None):
        """Continue the configuration process with the new AppID after automated prefix creation"""
        if last_timestamp:
            # Initialize timing to continue from the last timestamp
            from jackify.shared.timing import continue_from_timestamp
            continue_from_timestamp(last_timestamp)
            debug_print(f"Timing continued from {last_timestamp}")
        
        debug_print(f"continue_configuration_after_automated_prefix called with appid: {new_appid}")
        try:
            # Update the context with the new AppID (same format as manual steps)
            updated_context = {
                'name': modlist_name,
                'path': install_dir,
                'mo2_exe_path': os.path.join(install_dir, "ModOrganizer.exe"),
                'modlist_value': 'Tuxborn/Tuxborn',  # Hardcoded for Tuxborn
                'modlist_source': 'identifier',
                'resolution': getattr(self, '_current_resolution', '2560x1600'),
                'skip_confirmation': True,
                'manual_steps_completed': True,  # Mark as completed since automated prefix is done
                'appid': new_appid,  # Use the NEW AppID from automated prefix creation
                'game_name': self.context.get('game_name', 'Skyrim Special Edition') if hasattr(self, 'context') else 'Skyrim Special Edition'
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
                            modlist_value=self.context['modlist_value'],
                            modlist_source=self.context['modlist_source'],
                            resolution=self.context.get('resolution', '2560x1600'),
                            skip_confirmation=True,
                            engine_installed=True  # Skip path manipulation for engine workflows
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
            updated_context = {
                'name': modlist_name,
                'path': install_dir,
                'mo2_exe_path': os.path.join(install_dir, "ModOrganizer.exe"),
                'modlist_value': 'Tuxborn/Tuxborn',  # Hardcoded for Tuxborn
                'modlist_source': 'identifier',
                'resolution': getattr(self, '_current_resolution', '2560x1600'),
                'skip_confirmation': True,
                'manual_steps_completed': True,  # Mark as completed
                'appid': new_appid,  # Use the NEW AppID from Steam
                'game_name': self.context.get('game_name', 'Skyrim Special Edition') if hasattr(self, 'context') else 'Skyrim Special Edition'
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
                            game_type='skyrim',  # Tuxborn is always Skyrim
                            nexus_api_key='',  # Not needed for configuration
                            modlist_value=self.context.get('modlist_value', 'Tuxborn/Tuxborn'),
                            modlist_source=self.context.get('modlist_source', 'identifier'),
                            resolution=self.context.get('resolution'),  # Pass resolution from GUI context
                            skip_confirmation=True,
                            engine_installed=True  # Skip path manipulation for engine workflows
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
                        
                        # Call the new service method for post-Steam configuration
                        self.progress_update.emit("Starting Tuxborn configuration (post-Steam setup)...")
                        result = modlist_service.configure_modlist_post_steam(
                            context=modlist_context,
                            progress_callback=progress_callback,
                            manual_steps_callback=manual_steps_callback,
                            completion_callback=completion_callback
                        )
                        
                    except Exception as e:
                        self.error_occurred.emit(str(e))
            
            # Clean up old thread if exists
            if hasattr(self, 'config_thread') and self.config_thread is not None:
                # Disconnect all signals to prevent "Internal C++ object already deleted" errors
                try:
                    self.config_thread.progress_update.disconnect()
                    self.config_thread.configuration_complete.disconnect()
                    self.config_thread.error_occurred.disconnect()
                except:
                    pass  # Ignore errors if already disconnected
                if self.config_thread.isRunning():
                    self.config_thread.quit()
                    self.config_thread.wait(5000)  # Wait up to 5 seconds
                self.config_thread.deleteLater()
                self.config_thread = None
            
            # Start new config thread
            self.config_thread = ConfigThread(updated_context)
            self.config_thread.progress_update.connect(self._safe_append_text)
            self.config_thread.configuration_complete.connect(self.on_configuration_complete)
            self.config_thread.error_occurred.connect(self.on_configuration_error)
            self.config_thread.start()
            
        except Exception as e:
            self._safe_append_text(f"Error continuing configuration: {e}")
            self.on_configuration_error(str(e))

    def on_configuration_complete(self, success, message, modlist_name):
        """Handle configuration completion on main thread"""
        if success:
            # Calculate time taken
            time_taken = self._calculate_time_taken()
            
            # Show success dialog with celebration
            game_name = self.context.get('game_name', 'Skyrim Special Edition')
            success_dialog = SuccessDialog(
                modlist_name="Tuxborn",
                workflow_type="tuxborn",
                time_taken=time_taken,
                game_name=game_name,
                parent=self
            )
            success_dialog.show()
        elif self._manual_steps_retry_count >= 3:
            # Max retries reached - show failure message
                        MessageService.critical(self, "Manual Steps Failed",
                               "Manual steps validation failed after multiple attempts.", safety_level="medium")
        else:
            # Configuration failed for other reasons
            MessageService.critical(self, "Configuration Failed",
                               "Post-install configuration failed. Please check the console output.", safety_level="medium")
            
        # Clean up thread
        if hasattr(self, 'config_thread') and self.config_thread is not None:
            # Disconnect all signals to prevent "Internal C++ object already deleted" errors
            try:
                self.config_thread.progress_update.disconnect()
                self.config_thread.configuration_complete.disconnect()
                self.config_thread.error_occurred.disconnect()
            except:
                pass  # Ignore errors if already disconnected
            if self.config_thread.isRunning():
                self.config_thread.quit()
                self.config_thread.wait(5000)  # Wait up to 5 seconds
            self.config_thread.deleteLater()
            self.config_thread = None
    
    def on_configuration_error(self, error_message):
        """Handle configuration error on main thread"""
        self._safe_append_text(f"Configuration failed with error: {error_message}")
        MessageService.critical(self, "Configuration Error", f"Configuration failed: {error_message}", safety_level="medium")
        
        # Clean up thread
        if hasattr(self, 'config_thread') and self.config_thread is not None:
            # Disconnect all signals to prevent "Internal C++ object already deleted" errors
            try:
                self.config_thread.progress_update.disconnect()
                self.config_thread.configuration_complete.disconnect()
                self.config_thread.error_occurred.disconnect()
            except:
                pass  # Ignore errors if already disconnected
            if self.config_thread.isRunning():
                self.config_thread.quit()
                self.config_thread.wait(5000)  # Wait up to 5 seconds
            self.config_thread.deleteLater()
            self.config_thread = None

    def handle_validation_failure(self, missing_text):
        """Handle failed validation with retry logic"""
        self._manual_steps_retry_count += 1
        
        if self._manual_steps_retry_count < 3:
            # Show retry dialog
            MessageService.critical(self, "Manual Steps Incomplete", 
                               f"Manual steps validation failed:\n\n{missing_text}\n\n"
                               "Please complete the missing steps and try again.", safety_level="medium")
            # Show manual steps dialog again
            extra_warning = ""
            if self._manual_steps_retry_count >= 2:
                extra_warning = "<br><b style='color:#f33'>It looks like you have not completed the manual steps yet. Please try again.</b>"
            self.show_manual_steps_dialog(extra_warning)
        else:
            # Max retries reached
            MessageService.critical(self, "Manual Steps Failed", 
                               "Manual steps validation failed after multiple attempts.", safety_level="medium")
            self.on_configuration_complete(False, "Manual steps validation failed after multiple attempts", self._current_modlist_name)

    def show_next_steps_dialog(self, message):
        # EXACT LEGACY show_next_steps_dialog
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
                self.stacked_widget.setCurrentIndex(0)  # Main menu
        def on_exit():
            QApplication.quit()
        btn_return.clicked.connect(on_return)
        btn_exit.clicked.connect(on_exit)
        dlg.exec()

    def cleanup_processes(self):
        """Clean up any running processes when the window closes or is cancelled"""
        debug_print("DEBUG: cleanup_processes called - cleaning up InstallationThread and other processes")
        
        # Clean up InstallationThread if running
        if hasattr(self, 'install_thread') and self.install_thread.isRunning():
            debug_print("DEBUG: Cancelling running InstallationThread")
            self.install_thread.cancel()
            self.install_thread.wait(3000)  # Wait up to 3 seconds
            if self.install_thread.isRunning():
                self.install_thread.terminate()
        
        # Clean up other threads
        threads = [
            'config_thread', 'fetch_thread'
        ]
        for thread_name in threads:
            if hasattr(self, thread_name):
                thread = getattr(self, thread_name)
                if thread and thread.isRunning():
                    debug_print(f"DEBUG: Terminating {thread_name}")
                    thread.terminate()
                    thread.wait(1000)  # Wait up to 1 second
    
    def cancel_installation(self):
        """Cancel the currently running installation"""
        reply = MessageService.question(
            self, "Cancel Installation", 
            "Are you sure you want to cancel the installation?",
            safety_level="low"
        )
        
        if reply == QMessageBox.Yes:
            self._safe_append_text("\n🛑 Cancelling installation...")
            
            # Cancel the installation thread if it exists
            if hasattr(self, 'install_thread') and self.install_thread.isRunning():
                self.install_thread.cancel()
                self.install_thread.wait(3000)  # Wait up to 3 seconds for graceful shutdown
                if self.install_thread.isRunning():
                    self.install_thread.terminate()  # Force terminate if needed
                    self.install_thread.wait(1000)
            
            # Cleanup any remaining processes
            self.cleanup_processes()
            
            # Reset button states
            self.start_btn.setEnabled(True)
            self.cancel_btn.setVisible(True)
            self.cancel_install_btn.setVisible(False)
            
            self._safe_append_text("Installation cancelled by user.")
        
    def closeEvent(self, event):
        """Handle window close event - clean up processes"""
        self.cleanup_processes()
        event.accept() 

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