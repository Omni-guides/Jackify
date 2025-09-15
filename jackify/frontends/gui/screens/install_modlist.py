"""
InstallModlistScreen for Jackify GUI
"""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QComboBox, QHBoxLayout, QLineEdit, QPushButton, QGridLayout, QFileDialog, QTextEdit, QSizePolicy, QTabWidget, QDialog, QListWidget, QListWidgetItem, QMessageBox, QProgressDialog, QApplication, QCheckBox, QStyledItemDelegate, QStyle, QTableWidget, QTableWidgetItem, QHeaderView
from PySide6.QtCore import Qt, QSize, QThread, Signal, QTimer, QProcess, QMetaObject, QUrl
from PySide6.QtGui import QPixmap, QTextCursor, QColor, QPainter, QFont
from ..shared_theme import JACKIFY_COLOR_BLUE, DEBUG_BORDERS
from ..utils import ansi_to_html
from ..widgets.unsupported_game_dialog import UnsupportedGameDialog
import os
import subprocess
import sys
import threading
from jackify.backend.handlers.shortcut_handler import ShortcutHandler
from jackify.backend.handlers.wabbajack_parser import WabbajackParser
import traceback
from jackify.backend.core.modlist_operations import get_jackify_engine_path
import signal
import re
import time
from jackify.backend.handlers.subprocess_utils import ProcessManager
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
            self.result.emit(modlist_infos, '')
            
        except Exception as e:
            error_msg = f"Backend service error: {str(e)}"
            # Don't write to log file before workflow starts - just return error
            self.result.emit([], error_msg)


class SelectionDialog(QDialog):
    def __init__(self, title, items, parent=None, show_search=True, placeholder_text="Search modlists...", show_legend=False):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(600)
        self.setMinimumHeight(300)
        layout = QVBoxLayout(self)

        self.show_search = show_search
        if self.show_search:
            # Search box with clear button
            search_layout = QHBoxLayout()
            self.search_box = QLineEdit()
            self.search_box.setPlaceholderText(placeholder_text)
            # Make placeholder text lighter
            self.search_box.setStyleSheet("QLineEdit { color: #ccc; } QLineEdit:placeholder { color: #aaa; }")
            self.clear_btn = QPushButton("Clear")
            self.clear_btn.setFixedWidth(50)
            search_layout.addWidget(self.search_box)
            search_layout.addWidget(self.clear_btn)
            layout.addLayout(search_layout)

        if show_legend:
            # Use table for modlist selection with proper columns
            self.table_widget = QTableWidget()
            self.table_widget.setColumnCount(4)
            self.table_widget.setHorizontalHeaderLabels(["Modlist Name", "Download", "Install", "Total"])
            
            # Configure table appearance
            self.table_widget.setSelectionBehavior(QTableWidget.SelectRows)
            self.table_widget.setSelectionMode(QTableWidget.SingleSelection)
            self.table_widget.verticalHeader().setVisible(False)
            self.table_widget.setAlternatingRowColors(True)
            
            # Set column widths
            header = self.table_widget.horizontalHeader()
            header.setSectionResizeMode(0, QHeaderView.Stretch)  # Modlist name takes remaining space
            header.setSectionResizeMode(1, QHeaderView.ResizeToContents)  # Download size
            header.setSectionResizeMode(2, QHeaderView.ResizeToContents)  # Install size  
            header.setSectionResizeMode(3, QHeaderView.ResizeToContents)  # Total size
            
            
            self._all_items = list(items)
            self._populate_table(self._all_items)
            layout.addWidget(self.table_widget)
            
            # Apply initial NSFW filter since checkbox starts unchecked
            self._filter_nsfw(False)
        else:
            # Use list for non-modlist dialogs (backward compatibility)
            self.list_widget = QListWidget()
            self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.list_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            self._all_items = list(items)
            self._populate_list(self._all_items)
            layout.addWidget(self.list_widget)
        
        # Add interactive legend bar only for modlist selection dialogs
        if show_legend:
            legend_layout = QHBoxLayout()
            legend_layout.setContentsMargins(10, 5, 10, 5)
            
            # Status indicator explanation (far left)
            status_label = QLabel('<small><b>[DOWN]</b> Unavailable</small>')
            status_label.setStyleSheet("color: #bbb;")
            legend_layout.addWidget(status_label)
            
            # Spacer after DOWN legend
            legend_layout.addSpacing(15)
            
            # No need for size format explanation since we have table headers now
            # Just add some spacing
            
            # Main spacer to push NSFW checkbox to far right
            legend_layout.addStretch()
            
            # NSFW filter checkbox (far right)
            self.nsfw_checkbox = QCheckBox("Show NSFW")
            self.nsfw_checkbox.setStyleSheet("color: #bbb; font-size: 11px;")
            self.nsfw_checkbox.setChecked(False)  # Default to hiding NSFW content
            self.nsfw_checkbox.toggled.connect(self._filter_nsfw)
            legend_layout.addWidget(self.nsfw_checkbox)
            
            # Legend container
            legend_widget = QWidget()
            legend_widget.setLayout(legend_layout)
            legend_widget.setStyleSheet("background-color: #333; border-radius: 3px; margin: 2px;")
            layout.addWidget(legend_widget)
        
        self.selected_item = None
        
        # Connect appropriate signals based on widget type
        if show_legend:
            self.table_widget.itemClicked.connect(self.on_table_item_clicked)
            if self.show_search:
                self.search_box.textChanged.connect(self._filter_table)
                self.clear_btn.clicked.connect(self._clear_search)
                self.search_box.returnPressed.connect(self._focus_table)
                self.search_box.installEventFilter(self)
        else:
            self.list_widget.itemClicked.connect(self.on_item_clicked)
            if self.show_search:
                self.search_box.textChanged.connect(self._filter_list)
                self.clear_btn.clicked.connect(self._clear_search)
                self.search_box.returnPressed.connect(self._focus_list)
                self.search_box.installEventFilter(self)

    def _populate_list(self, items):
        self.list_widget.clear()
        for item in items:
            # Create list item - custom delegate handles all styling
            QListWidgetItem(item, self.list_widget)

    def _populate_table(self, items):
        self.table_widget.setRowCount(len(items))
        for row, item in enumerate(items):
            # Parse the item string to extract components
            # Format: "[STATUS] Modlist Name    Download|Install|Total"
            
            # Extract status indicators
            status_down = '[DOWN]' in item
            status_nsfw = '[NSFW]' in item
            
            # Clean the item string
            clean_item = item.replace('[DOWN]', '').replace('[NSFW]', '').strip()
            
            # Split into name and sizes
            # The format should be "Name    Download|Install|Total"
            parts = clean_item.rsplit('    ', 1)  # Split from right to separate name from sizes
            if len(parts) == 2:
                name = parts[0].strip()
                sizes = parts[1].strip()
                size_parts = sizes.split('|')
                if len(size_parts) == 3:
                    download_size, install_size, total_size = [s.strip() for s in size_parts]
                else:
                    # Fallback if format is unexpected
                    download_size = install_size = total_size = sizes
            else:
                # Fallback if format is unexpected
                name = clean_item
                download_size = install_size = total_size = ""
            
            # Create table items
            name_item = QTableWidgetItem(name)
            download_item = QTableWidgetItem(download_size)
            install_item = QTableWidgetItem(install_size)
            total_item = QTableWidgetItem(total_size)
            
            # Apply styling
            if status_down:
                # Gray out and strikethrough for DOWN items
                for item_widget in [name_item, download_item, install_item, total_item]:
                    item_widget.setForeground(QColor('#999999'))
                    font = item_widget.font()
                    font.setStrikeOut(True)
                    item_widget.setFont(font)
            elif status_nsfw:
                # Red text for NSFW items - but only the name, sizes stay white
                name_item.setForeground(QColor('#ff4444'))
                for item_widget in [download_item, install_item, total_item]:
                    item_widget.setForeground(QColor('#ffffff'))
            else:
                # White text for normal items
                for item_widget in [name_item, download_item, install_item, total_item]:
                    item_widget.setForeground(QColor('#ffffff'))
            
            # Add status indicators to name if present
            if status_nsfw:
                name_item.setText(f"[NSFW] {name}")
            if status_down:
                # For DOWN items, we want [DOWN] normal and the name strikethrough
                # Since we can't easily mix fonts in a single QTableWidgetItem, 
                # we'll style the whole item but the visual effect will be clear
                name_item.setText(f"[DOWN] {name_item.text()}")
            
            # Right-align size columns
            download_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            install_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            total_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            
            # Add items to table
            self.table_widget.setItem(row, 0, name_item)
            self.table_widget.setItem(row, 1, download_item)
            self.table_widget.setItem(row, 2, install_item)
            self.table_widget.setItem(row, 3, total_item)
            
            # Store original item text as data for filtering
            name_item.setData(Qt.UserRole, item)

    def _filter_list(self, text):
        text = text.strip().lower()
        if not text:
            filtered = self._all_items
        else:
            filtered = [item for item in self._all_items if text in item.lower()]
        self._populate_list(filtered)
        if filtered:
            self.list_widget.setCurrentRow(0)

    def _clear_search(self):
        self.search_box.clear()
        self.search_box.setFocus()

    def _focus_list(self):
        self.list_widget.setFocus()
        self.list_widget.setCurrentRow(0)

    def _focus_table(self):
        self.table_widget.setFocus()
        self.table_widget.setCurrentCell(0, 0)

    def _filter_table(self, text):
        text = text.strip().lower()
        if not text:
            # Show all rows
            for row in range(self.table_widget.rowCount()):
                self.table_widget.setRowHidden(row, False)
        else:
            # Filter rows based on modlist name
            for row in range(self.table_widget.rowCount()):
                name_item = self.table_widget.item(row, 0)
                if name_item:
                    # Search in the modlist name
                    match = text in name_item.text().lower()
                    self.table_widget.setRowHidden(row, not match)

    def on_table_item_clicked(self, item):
        # Get the original item text from the name column
        row = item.row()
        name_item = self.table_widget.item(row, 0)
        if name_item:
            original_item = name_item.data(Qt.UserRole)
            self.selected_item = original_item
            self.accept()

    def _filter_nsfw(self, show_nsfw):
        """Filter NSFW modlists based on checkbox state"""
        if show_nsfw:
            # Show all items
            filtered_items = self._all_items
        else:
            # Hide NSFW items
            filtered_items = [item for item in self._all_items if '[NSFW]' not in item]
        
        # Use appropriate populate method based on widget type
        if hasattr(self, 'table_widget'):
            self._populate_table(filtered_items)
            # Apply search filter if there's search text
            if hasattr(self, 'search_box') and self.search_box.text().strip():
                self._filter_table(self.search_box.text())
        else:
            self._populate_list(filtered_items)
            # Apply search filter if there's search text
            if hasattr(self, 'search_box') and self.search_box.text().strip():
                self._filter_list(self.search_box.text())

    def eventFilter(self, obj, event):
        if self.show_search and obj == self.search_box and event.type() == event.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Tab):
                # Focus appropriate widget
                if hasattr(self, 'table_widget'):
                    self._focus_table()
                else:
                    self._focus_list()
                return True
        return super().eventFilter(obj, event)

    def on_item_clicked(self, item):
        self.selected_item = item.text()
        self.accept()

class InstallModlistScreen(QWidget):
    steam_restart_finished = Signal(bool, str)
    def __init__(self, stacked_widget=None, main_menu_index=0):
        super().__init__()
        self.stacked_widget = stacked_widget
        self.main_menu_index = main_menu_index
        self.debug = DEBUG_BORDERS
        self.online_modlists = {}  # {game_type: [modlist_dict, ...]}
        self.modlist_details = {}  # {modlist_name: modlist_dict}

        # Path for workflow log
        self.modlist_log_path = os.path.expanduser('~/Jackify/logs/Modlist_Install_workflow.log')
        os.makedirs(os.path.dirname(self.modlist_log_path), exist_ok=True)

        # Initialize services early
        from jackify.backend.services.api_key_service import APIKeyService
        from jackify.backend.services.resolution_service import ResolutionService
        from jackify.backend.services.protontricks_detection_service import ProtontricksDetectionService
        from jackify.backend.handlers.config_handler import ConfigHandler
        self.api_key_service = APIKeyService()
        self.resolution_service = ResolutionService()
        self.config_handler = ConfigHandler()
        self.protontricks_service = ProtontricksDetectionService()

        # Scroll tracking for professional auto-scroll behavior
        self._user_manually_scrolled = False
        self._was_at_bottom = True
        
        # Initialize Wabbajack parser for game detection
        self.wabbajack_parser = WabbajackParser()

        main_overall_vbox = QVBoxLayout(self)
        main_overall_vbox.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        main_overall_vbox.setContentsMargins(50, 50, 50, 0)  # No bottom margin
        if self.debug:
            self.setStyleSheet("border: 2px solid magenta;")

        # --- Header (title, description) ---
        header_layout = QVBoxLayout()
        header_layout.setSpacing(1)  # Reduce spacing between title and description
        # Title (no logo)
        title = QLabel("<b>Install a Modlist (Automated)</b>")
        title.setStyleSheet(f"font-size: 20px; color: {JACKIFY_COLOR_BLUE}; margin: 0px; padding: 0px;")
        title.setAlignment(Qt.AlignHCenter)
        title.setMaximumHeight(30)  # Force compact height
        header_layout.addWidget(title)
        # Description
        desc = QLabel(
            "This screen allows you to install a Wabbajack modlist using Jackify's native Linux tools. "
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
        # Left: user-configurables (form and controls)
        user_config_vbox = QVBoxLayout()
        user_config_vbox.setAlignment(Qt.AlignTop)
        user_config_vbox.setSpacing(4)  # Reduce spacing between major form sections
        # --- Tabs for source selection ---
        self.source_tabs = QTabWidget()
        self.source_tabs.setStyleSheet("QTabWidget::pane { background: #222; border: 1px solid #444; } QTabBar::tab { background: #222; color: #ccc; padding: 6px 16px; } QTabBar::tab:selected { background: #333; color: #3fd0ea; }")
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
        self.game_types = ["Skyrim", "Fallout 4", "Fallout New Vegas", "Oblivion", "Starfield", "Oblivion Remastered", "Enderal", "Other"]
        self.game_type_btn = QPushButton("Please Select...")
        self.game_type_btn.setMinimumWidth(200)
        self.game_type_btn.clicked.connect(self.open_game_type_dialog)
        # --- Modlist Selection ---
        self.modlist_btn = QPushButton("Select Modlist")
        self.modlist_btn.setMinimumWidth(300)
        self.modlist_btn.clicked.connect(self.open_modlist_dialog)
        self.modlist_btn.setEnabled(False)
        online_layout.addWidget(QLabel("Game Type:"))
        online_layout.addWidget(self.game_type_btn)
        online_layout.addSpacing(4)  # Reduced from 16 to 4
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
        file_btn = QPushButton("Browse")
        file_btn.clicked.connect(self.browse_wabbajack_file)
        file_layout.addWidget(QLabel(".wabbajack File:"))
        file_layout.addWidget(self.file_edit)
        file_layout.addWidget(file_btn)
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
        # Nexus API Key
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
        # Remove height constraint to prevent text truncation
        if self.debug:
            api_save_widget.setStyleSheet("border: 2px solid blue;")
            api_save_widget.setToolTip("API_KEY_SECTION")
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
        form_section_widget.setMinimumHeight(220)  # Increased to allow RED API key box proper height
        form_section_widget.setMaximumHeight(240)  # Increased to allow RED API key box proper height
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
        user_config_widget.setLayout(user_config_vbox)
        user_config_widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)  # Allow vertical expansion to fill space
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
        upper_hbox.addWidget(user_config_widget, stretch=1)
        upper_hbox.addWidget(process_monitor_widget, stretch=3)
        upper_hbox.setAlignment(Qt.AlignTop)
        upper_section_widget = QWidget()
        upper_section_widget.setLayout(upper_hbox)
        upper_section_widget.setMaximumHeight(320)  # Increased to ensure resolution dropdown is visible
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
        

        
        # Initialize process tracking
        self.process = None

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
        """Called when the widget becomes visible - always reload saved API key"""
        super().showEvent(event)
        # Always reload saved API key to pick up changes from Settings dialog
        saved_key = self.api_key_service.get_saved_api_key()
        if saved_key:
            self.api_key_original_text = saved_key
            self.api_key_edit.setText(saved_key)
            self.api_key_is_obfuscated = False  # Start unobfuscated
            # Set checkbox state
            self.save_api_key_checkbox.setChecked(True)
            # Immediately obfuscate saved keys (don't wait 3 seconds)
            self._obfuscate_api_key()
        elif not self.api_key_edit.text().strip():
            # Only clear if no saved key and field is empty
            self.api_key_original_text = ""
            self.save_api_key_checkbox.setChecked(False)
        # Do NOT load saved parent directories

    def _load_saved_parent_directories(self):
        """No-op: do not pre-populate install/download directories from saved values."""
        pass

    def _update_directory_suggestions(self, modlist_name):
        """Update directory suggestions based on modlist name"""
        try:
            if not modlist_name:
                return
                
            # Update install directory suggestion with modlist name
            saved_install_parent = self.config_handler.get_default_install_parent_dir()
            if saved_install_parent:
                suggested_install_dir = os.path.join(saved_install_parent, modlist_name)
                self.install_dir_edit.setText(suggested_install_dir)
                debug_print(f"DEBUG: Updated install directory suggestion: {suggested_install_dir}")
            
            # Update download directory suggestion
            saved_download_parent = self.config_handler.get_default_download_parent_dir()
            if saved_download_parent:
                suggested_download_dir = os.path.join(saved_download_parent, "Downloads")
                self.downloads_dir_edit.setText(suggested_download_dir)
                debug_print(f"DEBUG: Updated download directory suggestion: {suggested_download_dir}")
                
        except Exception as e:
            debug_print(f"DEBUG: Error updating directory suggestions: {e}")
    
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

    def _on_api_key_focus_out(self, event):
        """Handle API key field losing focus - immediately obfuscate"""
        QLineEdit.focusOutEvent(self.api_key_edit, event)
        self._obfuscate_api_key()

    def _obfuscate_api_key(self):
        """Obfuscate the API key text field"""
        if not self.api_key_is_obfuscated and self.api_key_original_text.strip():
            # Block signals to prevent recursion
            self.api_key_edit.blockSignals(True)
            # Show masked version
            masked_text = self.api_key_service.get_api_key_display(self.api_key_original_text)
            self.api_key_edit.setText(masked_text)
            self.api_key_is_obfuscated = True
            # Re-enable signals
            self.api_key_edit.blockSignals(False)
    
    def _get_actual_api_key(self):
        """Get the actual API key value (not the obfuscated version)"""
        if self.api_key_is_obfuscated:
            return self.api_key_original_text
        else:
            return self.api_key_edit.text()

    def open_game_type_dialog(self):
        dlg = SelectionDialog("Select Game Type", self.game_types, self, show_search=False)
        if dlg.exec() == QDialog.Accepted and dlg.selected_item:
            self.game_type_btn.setText(dlg.selected_item)
            self.fetch_modlists_for_game_type(dlg.selected_item)

    def fetch_modlists_for_game_type(self, game_type):
        self.current_game_type = game_type  # Store for display formatting
        self.modlist_btn.setText("Fetching modlists...")
        self.modlist_btn.setEnabled(False)
        game_type_map = {
            "Skyrim": "skyrim",
            "Fallout 4": "fallout4",
            "Fallout New Vegas": "falloutnv",
            "Oblivion": "oblivion",
            "Starfield": "starfield",
            "Oblivion Remastered": "oblivion_remastered",
            "Enderal": "enderal",
            "Other": "other"
        }
        cli_game_type = game_type_map.get(game_type, "other")
        log_path = self.modlist_log_path
        # Use backend service directly - NO CLI CALLS
        self.fetch_thread = ModlistFetchThread(
            cli_game_type, log_path, mode='list-modlists')
        self.fetch_thread.result.connect(self.on_modlists_fetched)
        self.fetch_thread.start()

    def on_modlists_fetched(self, modlist_infos, error):
        # Handle the case where modlist_infos might be strings (backward compatibility)
        if modlist_infos and isinstance(modlist_infos[0], str):
            # Old format - just IDs as strings
            filtered = [m for m in modlist_infos if m and not m.startswith('DEBUG:')]
            self.current_modlists = filtered
            self.current_modlist_display = filtered
        else:
            # New format - full modlist objects with enhanced metadata
            filtered_modlists = [m for m in modlist_infos if m and hasattr(m, 'id')]
            filtered = filtered_modlists  # Set filtered for the condition check below
            self.current_modlists = [m.id for m in filtered_modlists]  # Keep IDs for selection
            
            # Create enhanced display strings with size info and status indicators
            display_strings = []
            for modlist in filtered_modlists:
                # Get enhanced metadata
                download_size = getattr(modlist, 'download_size', '')
                install_size = getattr(modlist, 'install_size', '')
                total_size = getattr(modlist, 'total_size', '')
                status_down = getattr(modlist, 'status_down', False)
                status_nsfw = getattr(modlist, 'status_nsfw', False)
                
                # Format display string without redundant game type: "Modlist Name - Download|Install|Total"
                # For "Other" category, include game type in brackets for clarity
                # Use padding to create alignment: left-aligned name, right-aligned sizes
                if hasattr(self, 'current_game_type') and self.current_game_type == "Other":
                    name_part = f"{modlist.name} [{modlist.game}]"
                else:
                    name_part = modlist.name
                size_part = f"{download_size}|{install_size}|{total_size}"
                
                # Create aligned display using string formatting (approximate alignment)
                display_str = f"{name_part:<50} {size_part:>15}"
                
                # Add status indicators at the beginning if present
                if status_down or status_nsfw:
                    status_parts = []
                    if status_down:
                        status_parts.append("[DOWN]")
                    if status_nsfw:
                        status_parts.append("[NSFW]") 
                    display_str = " ".join(status_parts) + " " + display_str
                
                display_strings.append(display_str)
            
            self.current_modlist_display = display_strings
        
        # Create mapping from display string back to modlist ID for selection
        self._modlist_id_map = {}
        if len(self.current_modlist_display) == len(self.current_modlists):
            self._modlist_id_map = {display: modlist_id for display, modlist_id in 
                                  zip(self.current_modlist_display, self.current_modlists)}
        else:
            # Fallback for backward compatibility
            self._modlist_id_map = {mid: mid for mid in self.current_modlists}
        if error:
            self.modlist_btn.setText("Error fetching modlists.")
            self.modlist_btn.setEnabled(False)
            # Don't write to log file before workflow starts - just show error in UI
        elif filtered:
            self.modlist_btn.setText("Select Modlist")
            self.modlist_btn.setEnabled(True)
        else:
            self.modlist_btn.setText("No modlists found.")
            self.modlist_btn.setEnabled(False)

    def open_modlist_dialog(self):
        if not self.current_modlist_display:
            return
        dlg = SelectionDialog("Select Modlist", self.current_modlist_display, self, show_search=True, placeholder_text="Search modlists...", show_legend=True)
        if dlg.exec() == QDialog.Accepted and dlg.selected_item:
            modlist_id = self._modlist_id_map.get(dlg.selected_item, dlg.selected_item)
            self.modlist_btn.setText(modlist_id)
            # Fetch and store the full ModlistInfo for unsupported game detection
            try:
                from jackify.backend.services.modlist_service import ModlistService
                from jackify.backend.models.configuration import SystemInfo
                is_steamdeck = False
                if os.path.exists('/etc/os-release'):
                    with open('/etc/os-release') as f:
                        if 'steamdeck' in f.read().lower():
                            is_steamdeck = True
                system_info = SystemInfo(is_steamdeck=is_steamdeck)
                modlist_service = ModlistService(system_info)
                all_modlists = modlist_service.list_modlists()
                selected_info = next((m for m in all_modlists if m.id == modlist_id), None)
                self.selected_modlist_info = selected_info.to_dict() if selected_info else None
                
                # Auto-populate the Modlist Name field with the display name (user can still modify)
                if selected_info and selected_info.name:
                    self.modlist_name_edit.setText(selected_info.name)
            except Exception as e:
                self.selected_modlist_info = None

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
                if (
                    ("jackify-engine" in line_lower or "7zz" in line_lower or "texconv" in line_lower or
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
            MessageService.warning(self, "Protontricks Check Failed", 
                                 f"Unable to verify protontricks installation: {e}\n\n"
                                 "Continuing anyway, but some features may not work correctly.")
            return True  # Continue anyway

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
                        debug_print("DEBUG: API key validated and saved immediately on checkbox toggle")
                    else:
                        self._show_api_key_feedback("✗ Failed to save API key - check permissions", is_success=False)
                        # Uncheck the checkbox since save failed
                        self.save_api_key_checkbox.setChecked(False)
                        debug_print("DEBUG: Failed to save API key immediately")
                else:
                    self._show_api_key_feedback("Enter an API key first", is_success=False)
                    # Uncheck the checkbox since no key to save
                    self.save_api_key_checkbox.setChecked(False)
            else:
                # Clear saved API key when unchecked
                if self.api_key_service.has_saved_api_key():
                    success = self.api_key_service.clear_saved_api_key()
                    if success:
                        self._show_api_key_feedback("✓ API key cleared", is_success=True)
                        debug_print("DEBUG: Saved API key cleared immediately on checkbox toggle")
                    else:
                        self._show_api_key_feedback("✗ Failed to clear API key", is_success=False)
                        debug_print("DEBUG: Failed to clear API key")
        except Exception as e:
            self._show_api_key_feedback(f"✗ Error: {str(e)}", is_success=False)
            self.save_api_key_checkbox.setChecked(False)
            debug_print(f"DEBUG: Error in _on_api_key_save_toggled: {e}")
    
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
        import time
        self._install_workflow_start_time = time.time()
        debug_print('DEBUG: validate_and_start_install called')
        
        # Check protontricks before proceeding
        if not self._check_protontricks():
            return
        
        try:
            tab_index = self.source_tabs.currentIndex()
            install_mode = 'online'
            if tab_index == 1:  # .wabbajack File tab
                modlist = self.file_edit.text().strip()
                if not modlist or not os.path.isfile(modlist) or not modlist.endswith('.wabbajack'):
                    MessageService.warning(self, "Invalid Modlist", "Please select a valid .wabbajack file.")
                    return
                install_mode = 'file'
            else:
                modlist = self.modlist_btn.text().strip()
                if not modlist or modlist in ("Select Modlist", "Fetching modlists...", "No modlists found.", "Error fetching modlists."):
                    MessageService.warning(self, "Invalid Modlist", "Please select a valid modlist.")
                    return
                
                # For online modlists, use machine_url instead of display name
                if hasattr(self, 'selected_modlist_info') and self.selected_modlist_info:
                    machine_url = self.selected_modlist_info.get('machine_url')
                    if machine_url:
                        modlist = machine_url  # Use machine URL for installation
                        debug_print(f"DEBUG: Using machine_url for installation: {machine_url}")
                    else:
                        debug_print("DEBUG: No machine_url found in selected_modlist_info, using display name")
            install_dir = self.install_dir_edit.text().strip()
            downloads_dir = self.downloads_dir_edit.text().strip()
            api_key = self._get_actual_api_key().strip()
            modlist_name = self.modlist_name_edit.text().strip()
            missing_fields = []
            if not modlist_name:
                missing_fields.append("Modlist Name")
            if not install_dir:
                missing_fields.append("Install Directory")
            if not downloads_dir:
                missing_fields.append("Downloads Directory")
            if not api_key:
                missing_fields.append("Nexus API Key")
            if missing_fields:
                MessageService.warning(self, "Missing Required Fields", f"Please fill in all required fields before starting the install:\n- " + "\n- ".join(missing_fields))
                return
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
                    critical=False  # Non-critical, won't steal focus
                )
                if create == QMessageBox.Yes:
                    try:
                        os.makedirs(install_dir, exist_ok=True)
                    except Exception as e:
                        MessageService.critical(self, "Error", f"Failed to create install directory:\n{e}")
                        return
                else:
                    return
            if not os.path.isdir(downloads_dir):
                create = MessageService.question(self, "Create Directory?",
                    f"The downloads directory does not exist:\n{downloads_dir}\n\nWould you like to create it?",
                    critical=False  # Non-critical, won't steal focus
                )
                if create == QMessageBox.Yes:
                    try:
                        os.makedirs(downloads_dir, exist_ok=True)
                    except Exception as e:
                        MessageService.critical(self, "Error", f"Failed to create downloads directory:\n{e}")
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
                MessageService.warning(self, "Invalid API Key", "Please enter a valid Nexus API Key.")
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
            
            # Detect game type and check support
            game_type = None
            game_name = None
            
            if install_mode == 'file':
                # Parse .wabbajack file to get game type
                from pathlib import Path
                wabbajack_path = Path(modlist)
                result = self.wabbajack_parser.parse_wabbajack_game_type(wabbajack_path)
                if result:
                    if isinstance(result, tuple):
                        game_type, raw_game_type = result
                        # Get display name for the game
                        display_names = {
                            'skyrim': 'Skyrim',
                            'fallout4': 'Fallout 4',
                            'falloutnv': 'Fallout New Vegas',
                            'oblivion': 'Oblivion',
                            'starfield': 'Starfield',
                            'oblivion_remastered': 'Oblivion Remastered',
                            'enderal': 'Enderal'
                        }
                        if game_type == 'unknown' and raw_game_type:
                            game_name = raw_game_type
                        else:
                            game_name = display_names.get(game_type, game_type)
                    else:
                        game_type = result
                        display_names = {
                            'skyrim': 'Skyrim',
                            'fallout4': 'Fallout 4',
                            'falloutnv': 'Fallout New Vegas',
                            'oblivion': 'Oblivion',
                            'starfield': 'Starfield',
                            'oblivion_remastered': 'Oblivion Remastered',
                            'enderal': 'Enderal'
                        }
                        game_name = display_names.get(game_type, game_type)
            else:
                # For online modlists, try to get game type from selected modlist
                if hasattr(self, 'selected_modlist_info') and self.selected_modlist_info:
                    game_name = self.selected_modlist_info.get('game', '')
                    debug_print(f"DEBUG: Detected game_name from selected_modlist_info: '{game_name}'")
                    
                    # Map game name to game type
                    game_mapping = {
                        'skyrim special edition': 'skyrim',
                        'skyrim': 'skyrim',
                        'fallout 4': 'fallout4',
                        'fallout new vegas': 'falloutnv',
                        'oblivion': 'oblivion',
                        'starfield': 'starfield',
                        'oblivion_remastered': 'oblivion_remastered',
                        'enderal': 'enderal'
                    }
                    game_type = game_mapping.get(game_name.lower())
                    debug_print(f"DEBUG: Mapped game_name '{game_name}' to game_type: '{game_type}'")
                    if not game_type:
                        game_type = 'unknown'
                        debug_print(f"DEBUG: Game type not found in mapping, setting to 'unknown'")
                else:
                    debug_print(f"DEBUG: No selected_modlist_info found")
                    game_type = 'unknown'
            
            # Store game type and name for later use
            self._current_game_type = game_type
            self._current_game_name = game_name
            
            # Check if game is supported
            debug_print(f"DEBUG: Checking if game_type '{game_type}' is supported")
            is_supported = self.wabbajack_parser.is_supported_game(game_type) if game_type else False
            debug_print(f"DEBUG: is_supported_game('{game_type}') returned: {is_supported}")
            
            if game_type and not is_supported:
                debug_print(f"DEBUG: Game '{game_type}' is not supported, showing dialog")
                # Show unsupported game dialog
                dialog = UnsupportedGameDialog(self, game_name)
                if not dialog.show_dialog(self, game_name):
                    # User cancelled
                    return
            
            self.console.clear()
            self.process_monitor.clear()
            
            # Update button states for installation
            self.start_btn.setEnabled(False)
            self.cancel_btn.setVisible(False)
            self.cancel_install_btn.setVisible(True)
            
            debug_print(f'DEBUG: Calling run_modlist_installer with modlist={modlist}, install_dir={install_dir}, downloads_dir={downloads_dir}, api_key={api_key[:6]}..., install_mode={install_mode}')
            self.run_modlist_installer(modlist, install_dir, downloads_dir, api_key, install_mode)
        except Exception as e:
            debug_print(f"DEBUG: Exception in validate_and_start_install: {e}")
            import traceback
            debug_print(f"DEBUG: Traceback: {traceback.format_exc()}")
            # Re-enable the button in case of exception
            self.start_btn.setEnabled(True)
            self.cancel_btn.setVisible(True)
            self.cancel_install_btn.setVisible(False)
            # Also re-enable the entire widget
            self.setEnabled(True)
            debug_print(f"DEBUG: Widget re-enabled in exception handler, widget enabled: {self.isEnabled()}")
            print(f"DEBUG: Widget re-enabled in exception handler, widget enabled: {self.isEnabled()}")  # Always print

    def run_modlist_installer(self, modlist, install_dir, downloads_dir, api_key, install_mode='online'):
        debug_print('DEBUG: run_modlist_installer called - USING THREADED BACKEND WRAPPER')
        
        # Rotate log file at start of each workflow run (keep 5 backups)
        from jackify.backend.handlers.logging_handler import LoggingHandler
        from pathlib import Path
        log_handler = LoggingHandler()
        log_handler.rotate_log_file_per_run(Path(self.modlist_log_path), backup_count=5)
        
        # Clear console for fresh installation output
        self.console.clear()
        self._safe_append_text("Starting modlist installation with custom progress handling...")
        
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
            
            def __init__(self, modlist, install_dir, downloads_dir, api_key, modlist_name, install_mode='online'):
                super().__init__()
                self.modlist = modlist
                self.install_dir = install_dir
                self.downloads_dir = downloads_dir
                self.api_key = api_key
                self.modlist_name = modlist_name
                self.install_mode = install_mode
                self.cancelled = False
                self.process_manager = None
            
            def cancel(self):
                self.cancelled = True
                if self.process_manager:
                    self.process_manager.cancel()
            
            def run(self):
                try:
                    engine_path = get_jackify_engine_path()
                    if self.install_mode == 'file':
                        cmd = [engine_path, "install", "-w", self.modlist, "-o", self.install_dir, "-d", self.downloads_dir]
                    else:
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
                    self.process_manager = ProcessManager(cmd, env=env, text=False)
                    ansi_escape = re.compile(rb'\x1b\[[0-9;?]*[ -/]*[@-~]')
                    buffer = b''
                    last_was_blank = False
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
                                decoded = line.decode('utf-8', errors='replace')
                                self.progress_received.emit(decoded)
                            elif b'\n' in buffer:
                                line, buffer = buffer.split(b'\n', 1)
                                line = ansi_escape.sub(b'', line)
                                decoded = line.decode('utf-8', errors='replace')
                                # Collapse multiple blank lines to one
                                if decoded.strip() == '':
                                    if not last_was_blank:
                                        self.output_received.emit('')
                                    last_was_blank = True
                                else:
                                    self.output_received.emit(decoded)
                                    last_was_blank = False
                    if buffer:
                        line = ansi_escape.sub(b'', buffer)
                        decoded = line.decode('utf-8', errors='replace')
                        self.output_received.emit(decoded)
                    self.process_manager.wait()
                    if self.cancelled:
                        self.installation_finished.emit(False, "Installation cancelled by user")
                    elif self.process_manager.proc.returncode == 0:
                        self.installation_finished.emit(True, "Installation completed successfully")
                    else:
                        self.installation_finished.emit(False, "Installation failed")
                except Exception as e:
                    self.installation_finished.emit(False, f"Installation error: {str(e)}")
                finally:
                    if self.cancelled and self.process_manager:
                        self.process_manager.cancel()

        # After the InstallationThread class definition, add:
        self.install_thread = InstallationThread(
            modlist, install_dir, downloads_dir, api_key, self.modlist_name_edit.text().strip(), install_mode
        )
        self.install_thread.output_received.connect(self.on_installation_output)
        self.install_thread.progress_received.connect(self.on_installation_progress)
        self.install_thread.installation_finished.connect(self.on_installation_finished)
        self.install_thread.start()

    def on_installation_output(self, message):
        """Handle regular output from installation thread"""
        # Filter out internal status messages from user console
        if message.strip().startswith('[Jackify]'):
            # Log internal messages to file but don't show in console
            self._write_to_log_file(message)
            return
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
        debug_print(f"DEBUG: on_installation_finished called with success={success}, message={message}")
        if success:
            self._safe_append_text(f"\nSuccess: {message}")
            self.process_finished(0, QProcess.NormalExit)  # Simulate successful completion
        else:
            self._safe_append_text(f"\nError: {message}")
            self.process_finished(1, QProcess.CrashExit)  # Simulate error

    def process_finished(self, exit_code, exit_status):
        debug_print(f"DEBUG: process_finished called with exit_code={exit_code}, exit_status={exit_status}")
        # Reset button states
        self.start_btn.setEnabled(True)
        self.cancel_btn.setVisible(True)
        self.cancel_install_btn.setVisible(False)
        debug_print("DEBUG: Button states reset in process_finished")
        

        if exit_code == 0:
            # Check if this was an unsupported game
            game_type = getattr(self, '_current_game_type', None)
            game_name = getattr(self, '_current_game_name', None)
            
            if game_type and not self.wabbajack_parser.is_supported_game(game_type):
                # Show success message for unsupported games without post-install configuration
                MessageService.information(
                    self, "Modlist Install Complete!",
                    f"Modlist installation completed successfully!\n\n"
                    f"Note: Post-install configuration was skipped for unsupported game type: {game_name or game_type}\n\n"
                    f"You will need to manually configure Steam shortcuts and other post-install steps."
                )
                self._safe_append_text(f"\nModlist installation completed successfully.")
                self._safe_append_text(f"\nWarning: Post-install configuration skipped for unsupported game: {game_name or game_type}")
            else:
                # Show the normal install complete dialog for supported games
                reply = MessageService.question(
                    self, "Modlist Install Complete!",
                    "Modlist install complete!\n\nWould you like to add this modlist to Steam and configure it now? Steam will restart, closing any game you have open!",
                    critical=False  # Non-critical, won't steal focus
                )
                if reply == QMessageBox.Yes:
                    # --- Create Steam shortcut BEFORE restarting Steam ---
                    # Proceed directly to automated prefix creation
                    self.start_automated_prefix_workflow()
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
            # Check for user cancellation first
            last_output = self.console.toPlainText()
            if "cancelled by user" in last_output.lower():
                MessageService.information(self, "Installation Cancelled", "The installation was cancelled by the user.", safety_level="low")
            else:
                MessageService.critical(self, "Install Failed", "The modlist install failed. Please check the console output for details.")
                self._safe_append_text(f"\nInstall failed (exit code {exit_code}).")
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
        # Write all messages to log file (including internal messages)
        self._write_to_log_file(text)
        
        # Filter out internal status messages from user console display
        if text.strip().startswith('[Jackify]'):
            # Internal messages are logged but not shown in user console
            return
            
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
        debug_print("DEBUG: restart_steam_and_configure called - using direct backend service")
        progress = QProgressDialog("Restarting Steam...", None, 0, 0, self)
        progress.setWindowTitle("Restarting Steam")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        progress.show()
        self.setEnabled(False)
        debug_print(f"DEBUG: Widget disabled in restart_steam_and_configure, widget enabled: {self.isEnabled()}")
        print(f"DEBUG: Widget disabled in restart_steam_and_configure, widget enabled: {self.isEnabled()}")  # Always print
        
        def do_restart():
            debug_print("DEBUG: do_restart thread started - using direct backend service")
            try:
                from jackify.backend.handlers.shortcut_handler import ShortcutHandler
                
                # Use backend service directly instead of CLI subprocess
                shortcut_handler = ShortcutHandler(steamdeck=False)  # TODO: Use proper system info
                
                debug_print("DEBUG: About to call secure_steam_restart()")
                success = shortcut_handler.secure_steam_restart()
                debug_print(f"DEBUG: secure_steam_restart() returned: {success}")
                
                out = "Steam restart completed successfully." if success else "Steam restart failed."
                
            except Exception as e:
                debug_print(f"DEBUG: Exception in do_restart: {e}")
                success = False
                out = str(e)
                
            self.steam_restart_finished.emit(success, out)
            
        threading.Thread(target=do_restart, daemon=True).start()
        self._steam_restart_progress = progress  # Store to close later

    def _on_steam_restart_finished(self, success, out):
        debug_print("DEBUG: _on_steam_restart_finished called")
        # Safely cleanup progress dialog on main thread
        if hasattr(self, '_steam_restart_progress') and self._steam_restart_progress:
            try:
                self._steam_restart_progress.close()
                self._steam_restart_progress.deleteLater()  # Use deleteLater() for safer cleanup
            except Exception as e:
                debug_print(f"DEBUG: Error closing progress dialog: {e}")
            finally:
                self._steam_restart_progress = None
        
        self.setEnabled(True)
        debug_print(f"DEBUG: Widget re-enabled in _on_steam_restart_finished, widget enabled: {self.isEnabled()}")
        print(f"DEBUG: Widget re-enabled in _on_steam_restart_finished, widget enabled: {self.isEnabled()}")  # Always print
        if success:
            self._safe_append_text("Steam restarted successfully.")
            
            # Save context for later use in configuration
            self._manual_steps_retry_count = 0
            self._current_modlist_name = self.modlist_name_edit.text().strip()
            
            # Save resolution for later use in configuration
            resolution = self.resolution_combo.currentText()
            self._current_resolution = resolution.split()[0] if resolution != "Leave unchanged" else "2560x1600"
            
            # Use automated prefix creation instead of manual steps
            debug_print("DEBUG: Starting automated prefix creation workflow")
            self._safe_append_text("Starting automated prefix creation workflow...")
            self.start_automated_prefix_workflow()
        else:
            self._safe_append_text("Failed to restart Steam.\n" + out)
            MessageService.critical(self, "Steam Restart Failed", "Failed to restart Steam automatically. Please restart Steam manually, then try again.")

    def start_automated_prefix_workflow(self):
        """Start the automated prefix creation workflow"""
        try:
            modlist_name = self.modlist_name_edit.text().strip()
            install_dir = self.install_dir_edit.text().strip()
            final_exe_path = os.path.join(install_dir, "ModOrganizer.exe")
            
            if not os.path.exists(final_exe_path):
                self._safe_append_text(f"ERROR: ModOrganizer.exe not found at {final_exe_path}")
                MessageService.critical(self, "ModOrganizer.exe Not Found", 
                    f"ModOrganizer.exe not found at:\n{final_exe_path}\n\nCannot proceed with automated setup.")
                return
            
            # Run automated prefix creation in separate thread
            from PySide6.QtCore import QThread, Signal
            
            class AutomatedPrefixThread(QThread):
                finished = Signal(bool, str, str, str)  # success, prefix_path, appid (as string), last_timestamp
                progress = Signal(str)  # progress messages
                error = Signal(str)  # error messages
                show_progress_dialog = Signal(str)  # show progress dialog with message
                hide_progress_dialog = Signal()  # hide progress dialog
                conflict_detected = Signal(list)  # conflicts list
                
                def __init__(self, modlist_name, install_dir, final_exe_path):
                    super().__init__()
                    self.modlist_name = modlist_name
                    self.install_dir = install_dir
                    self.final_exe_path = final_exe_path
                
                def run(self):
                    try:
                        from jackify.backend.services.automated_prefix_service import AutomatedPrefixService
                        
                        def progress_callback(message):
                            self.progress.emit(message)
                            # Show progress dialog during Steam restart
                            if "Steam restarted successfully" in message:
                                self.hide_progress_dialog.emit()
                            elif "Restarting Steam..." in message:
                                self.show_progress_dialog.emit("Restarting Steam...")
                        
                        prefix_service = AutomatedPrefixService()
                        # Determine Steam Deck once and pass through the workflow
                        try:
                            import os
                            _is_steamdeck = False
                            if os.path.exists('/etc/os-release'):
                                with open('/etc/os-release') as f:
                                    if 'steamdeck' in f.read().lower():
                                        _is_steamdeck = True
                        except Exception:
                            _is_steamdeck = False
                        result = prefix_service.run_working_workflow(
                            self.modlist_name, self.install_dir, self.final_exe_path, progress_callback, steamdeck=_is_steamdeck
                        )
                        
                        # Handle the result - check for conflicts
                        if isinstance(result, tuple) and len(result) == 4:
                            if result[0] == "CONFLICT":
                                # Conflict detected - emit signal to main GUI
                                conflicts = result[1]
                                self.hide_progress_dialog.emit()
                                self.conflict_detected.emit(conflicts)
                                return
                            else:
                                # Normal result with timestamp
                                success, prefix_path, new_appid, last_timestamp = result
                        elif isinstance(result, tuple) and len(result) == 3:
                            # Fallback for old format (backward compatibility)
                            if result[0] == "CONFLICT":
                                # Conflict detected - emit signal to main GUI
                                conflicts = result[1]
                                self.hide_progress_dialog.emit()
                                self.conflict_detected.emit(conflicts)
                                return
                            else:
                                # Normal result (old format)
                                success, prefix_path, new_appid = result
                                last_timestamp = None
                        else:
                            # Handle non-tuple result
                            success = result
                            prefix_path = ""
                            new_appid = "0"
                            last_timestamp = None
                        
                        # Ensure progress dialog is hidden when workflow completes
                        self.hide_progress_dialog.emit()
                        self.finished.emit(success, prefix_path or "", str(new_appid) if new_appid else "0", last_timestamp)
                        
                    except Exception as e:
                        # Ensure progress dialog is hidden on error
                        self.hide_progress_dialog.emit()
                        self.error.emit(str(e))
            
            # Create and start thread
            self.prefix_thread = AutomatedPrefixThread(modlist_name, install_dir, final_exe_path)
            self.prefix_thread.finished.connect(self.on_automated_prefix_finished)
            self.prefix_thread.error.connect(self.on_automated_prefix_error)
            self.prefix_thread.progress.connect(self.on_automated_prefix_progress)
            self.prefix_thread.show_progress_dialog.connect(self.show_steam_restart_progress)
            self.prefix_thread.hide_progress_dialog.connect(self.hide_steam_restart_progress)
            self.prefix_thread.conflict_detected.connect(self.show_shortcut_conflict_dialog)
            self.prefix_thread.start()
            
        except Exception as e:
            debug_print(f"DEBUG: Exception in start_automated_prefix_workflow: {e}")
            import traceback
            debug_print(f"DEBUG: Traceback: {traceback.format_exc()}")
            self._safe_append_text(f"ERROR: Failed to start automated workflow: {e}")
    
    def on_automated_prefix_finished(self, success, prefix_path, new_appid_str, last_timestamp=None):
        """Handle completion of automated prefix creation"""
        if success:
            debug_print(f"SUCCESS: Automated prefix creation completed!")
            debug_print(f"Prefix created at: {prefix_path}")
            if new_appid_str and new_appid_str != "0":
                debug_print(f"AppID: {new_appid_str}")
            
            # Convert string AppID back to integer for configuration
            new_appid = int(new_appid_str) if new_appid_str and new_appid_str != "0" else None
            
            # Continue with configuration using the new AppID and timestamp
            modlist_name = self.modlist_name_edit.text().strip()
            install_dir = self.install_dir_edit.text().strip()
            self.continue_configuration_after_automated_prefix(new_appid, modlist_name, install_dir, last_timestamp)
        else:
            self._safe_append_text(f"ERROR: Automated prefix creation failed")
            self._safe_append_text("Please check the logs for details")
            MessageService.critical(self, "Automated Setup Failed", 
                "Automated prefix creation failed. Please check the console output for details.")
    
    def on_automated_prefix_error(self, error_msg):
        """Handle error in automated prefix creation"""
        self._safe_append_text(f"ERROR: Error during automated prefix creation: {error_msg}")
        MessageService.critical(self, "Automated Setup Error", 
            f"Error during automated prefix creation: {error_msg}")
    
    def on_automated_prefix_progress(self, progress_msg):
        """Handle progress updates from automated prefix creation"""
        self._safe_append_text(progress_msg)
    
    def on_configuration_progress(self, progress_msg):
        """Handle progress updates from modlist configuration"""
        self._safe_append_text(progress_msg)
    
    def show_steam_restart_progress(self, message):
        """Show Steam restart progress dialog"""
        from PySide6.QtWidgets import QProgressDialog
        from PySide6.QtCore import Qt
        
        self.steam_restart_progress = QProgressDialog(message, None, 0, 0, self)
        self.steam_restart_progress.setWindowTitle("Restarting Steam")
        self.steam_restart_progress.setWindowModality(Qt.WindowModal)
        self.steam_restart_progress.setMinimumDuration(0)
        self.steam_restart_progress.setValue(0)
        self.steam_restart_progress.show()
        self.setEnabled(False)
    
    def hide_steam_restart_progress(self):
        """Hide Steam restart progress dialog"""
        if hasattr(self, 'steam_restart_progress') and self.steam_restart_progress:
            try:
                self.steam_restart_progress.close()
                self.steam_restart_progress.deleteLater()
            except Exception:
                pass
            finally:
                self.steam_restart_progress = None
        self.setEnabled(True)

    def on_configuration_complete(self, success, message, modlist_name):
        """Handle configuration completion on main thread"""
        if success:
            # Show celebration SuccessDialog after the entire workflow
            from ..dialogs import SuccessDialog
            import time
            if not hasattr(self, '_install_workflow_start_time'):
                self._install_workflow_start_time = time.time()
            time_taken = int(time.time() - self._install_workflow_start_time)
            mins, secs = divmod(time_taken, 60)
            time_str = f"{mins} minutes, {secs} seconds" if mins else f"{secs} seconds"
            display_names = {
                'skyrim': 'Skyrim',
                'fallout4': 'Fallout 4',
                'falloutnv': 'Fallout New Vegas',
                'oblivion': 'Oblivion',
                'starfield': 'Starfield',
                'oblivion_remastered': 'Oblivion Remastered',
                'enderal': 'Enderal'
            }
            game_name = display_names.get(self._current_game_type, self._current_game_name)
            success_dialog = SuccessDialog(
                modlist_name=modlist_name,
                workflow_type="install",
                time_taken=time_str,
                game_name=game_name,
                parent=self
            )
            success_dialog.show()
        elif hasattr(self, '_manual_steps_retry_count') and self._manual_steps_retry_count >= 3:
            # Max retries reached - show failure message
            MessageService.critical(self, "Manual Steps Failed", 
                               "Manual steps validation failed after multiple attempts.")
        else:
            # Configuration failed for other reasons
            MessageService.critical(self, "Configuration Failed", 
                               "Post-install configuration failed. Please check the console output.")
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
        MessageService.critical(self, "Configuration Error", f"Configuration failed: {error_message}")
        
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
        
        # Add delay to allow Steam filesystem updates to complete
        self._safe_append_text("Waiting for Steam filesystem updates to complete...")
        import time
        time.sleep(2)
        
        # CRITICAL: Re-detect the AppID after Steam restart and manual steps
        # Steam assigns a NEW AppID during restart, different from the one we initially created
        self._safe_append_text(f"Re-detecting AppID for shortcut '{modlist_name}' after Steam restart...")
        from jackify.backend.handlers.shortcut_handler import ShortcutHandler
        shortcut_handler = ShortcutHandler(steamdeck=False)
        current_appid = shortcut_handler.get_appid_for_shortcut(modlist_name, mo2_exe_path)
        
        if not current_appid or not current_appid.isdigit():
            self._safe_append_text(f"Error: Could not find Steam-assigned AppID for shortcut '{modlist_name}'")
            self._safe_append_text("Error: This usually means the shortcut was not launched from Steam")
            self._safe_append_text("Suggestion: Check that Steam is running and shortcuts are visible in library")
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
            modlist_handler.game_var = "skyrimspecialedition"  # Default for now
            
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
            self._safe_append_text("Checking standard Steam locations and Flatpak Steam...")
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
                    self._safe_append_text("Suggestion: Ensure you launched the shortcut from Steam at least once")
                    self._safe_append_text("Suggestion: Check if Steam is using Flatpak (different file paths)")
                
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
        self.start_automated_prefix_workflow()
    
    def continue_configuration_after_automated_prefix(self, new_appid, modlist_name, install_dir, last_timestamp=None):
        """Continue the configuration process with the new AppID after automated prefix creation"""
        # Headers are now shown at start of Steam Integration
        # No need to show them again here
        debug_print("Configuration phase continues after Steam Integration")
        
        debug_print(f"continue_configuration_after_automated_prefix called with appid: {new_appid}")
        try:
            # Update the context with the new AppID (same format as manual steps)
            updated_context = {
                'name': modlist_name,
                'path': install_dir,
                'mo2_exe_path': os.path.join(install_dir, "ModOrganizer.exe"),
                'modlist_value': None,
                'modlist_source': None,
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
                            modlist_value=self.context.get('modlist_value'),
                            modlist_source=self.context.get('modlist_source', 'identifier'),
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
            self.config_thread.progress_update.connect(self.on_configuration_progress)
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
                'modlist_value': None,
                'modlist_source': None,
                'resolution': getattr(self, '_current_resolution', '2560x1600'),
                'skip_confirmation': True,
                'manual_steps_completed': True,  # Mark as completed
                'appid': new_appid  # Use the NEW AppID from Steam
            }
            
            debug_print(f"Updated context with new AppID: {new_appid}")
            
            # Clean up old thread if exists and wait for it to finish
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
            self.config_thread = self._create_config_thread(updated_context)
            self.config_thread.progress_update.connect(self.on_configuration_progress)
            self.config_thread.configuration_complete.connect(self.on_configuration_complete)
            self.config_thread.error_occurred.connect(self.on_configuration_error)
            self.config_thread.start()
            
        except Exception as e:
            self._safe_append_text(f"Error continuing configuration: {e}")
            self.on_configuration_error(str(e))

    def _create_config_thread(self, context):
        """Create a new ConfigThread with proper lifecycle management"""
        from PySide6.QtCore import QThread, Signal
        
        class ConfigThread(QThread):
            progress_update = Signal(str)
            configuration_complete = Signal(bool, str, str)
            error_occurred = Signal(str)
            
            def __init__(self, context, parent=None):
                super().__init__(parent)
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
                        game_type='skyrim',  # Default for now
                        nexus_api_key='',  # Not needed for configuration
                        modlist_value=self.context.get('modlist_value', ''),
                        modlist_source=self.context.get('modlist_source', 'identifier'),
                        resolution=self.context.get('resolution'),  # Pass resolution from GUI
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
                    result = modlist_service.configure_modlist_post_steam(
                        context=modlist_context,
                        progress_callback=progress_callback,
                        manual_steps_callback=manual_steps_callback,
                        completion_callback=completion_callback
                    )
                    
                    if not result:
                        self.progress_update.emit("WARNING: configure_modlist_post_steam returned False")
                    
                except Exception as e:
                    import traceback
                    error_details = f"Error in configuration: {e}\nTraceback: {traceback.format_exc()}"
                    self.progress_update.emit(f"DEBUG: {error_details}")
                    self.error_occurred.emit(str(e))
        
        return ConfigThread(context, parent=self)

    def handle_validation_failure(self, missing_text):
        """Handle failed validation with retry logic"""
        self._manual_steps_retry_count += 1
        
        if self._manual_steps_retry_count < 3:
            # Show retry dialog with increasingly detailed guidance
            retry_guidance = ""
            if self._manual_steps_retry_count == 1:
                retry_guidance = "\n\nTip: Make sure Steam is fully restarted before trying again."
            elif self._manual_steps_retry_count == 2:
                retry_guidance = "\n\nTip: If using Flatpak Steam, ensure compatdata is being created in the correct location."
            
            MessageService.critical(self, "Manual Steps Incomplete", 
                               f"Manual steps validation failed:\n\n{missing_text}\n\n"
                               f"Please complete the missing steps and try again.{retry_guidance}")
            # Show manual steps dialog again
            extra_warning = ""
            if self._manual_steps_retry_count >= 2:
                extra_warning = "<br><b style='color:#f33'>It looks like you have not completed the manual steps yet. Please try again.</b>"
            self.show_manual_steps_dialog(extra_warning)
        else:
            # Max retries reached
            MessageService.critical(self, "Manual Steps Failed", 
                               "Manual steps validation failed after multiple attempts.\n\n"
                               "Common issues:\n"
                               "• Steam not fully restarted\n"
                               "• Shortcut not launched from Steam\n"
                               "• Flatpak Steam using different file paths\n"
                               "• Proton - Experimental not selected")
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
            'prefix_thread', 'config_thread', 'fetch_thread'
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
            critical=False  # Non-critical, won't steal focus
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
            
            # Cancel the automated prefix thread if it exists
            if hasattr(self, 'prefix_thread') and self.prefix_thread.isRunning():
                self.prefix_thread.terminate()
                self.prefix_thread.wait(3000)  # Wait up to 3 seconds for graceful shutdown
                if self.prefix_thread.isRunning():
                    self.prefix_thread.terminate()  # Force terminate if needed
                    self.prefix_thread.wait(1000)
            
            # Cancel the configuration thread if it exists
            if hasattr(self, 'config_thread') and self.config_thread.isRunning():
                self.config_thread.terminate()
                self.config_thread.wait(3000)  # Wait up to 3 seconds for graceful shutdown
                if self.config_thread.isRunning():
                    self.config_thread.terminate()  # Force terminate if needed
                    self.config_thread.wait(1000)
            
            # Cleanup any remaining processes
            self.cleanup_processes()
            
            # Reset button states
            self.start_btn.setEnabled(True)
            self.cancel_btn.setVisible(True)
            self.cancel_install_btn.setVisible(False)
            
            self._safe_append_text("Installation cancelled by user.")

    def cancel_and_cleanup(self):
        """Handle Cancel button - clean up processes and go back"""
        self.cleanup_processes()
        self.go_back()
    
    def closeEvent(self, event):
        """Handle window close event - clean up processes"""
        self.cleanup_processes()
        event.accept() 