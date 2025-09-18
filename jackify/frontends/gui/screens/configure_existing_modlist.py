# Copy of ConfigureNewModlistScreen, adapted for existing modlists
from PySide6.QtWidgets import *
from PySide6.QtCore import *
from PySide6.QtGui import *
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

def debug_print(message):
    """Print debug message only if debug mode is enabled"""
    from jackify.backend.handlers.config_handler import ConfigHandler
    config_handler = ConfigHandler()
    if config_handler.get('debug_mode', False):
        print(message)

class ConfigureExistingModlistScreen(QWidget):
    steam_restart_finished = Signal(bool, str)
    def __init__(self, stacked_widget=None, main_menu_index=0):
        super().__init__()
        debug_print("DEBUG: ConfigureExistingModlistScreen __init__ called")
        self.stacked_widget = stacked_widget
        self.main_menu_index = main_menu_index
        self.debug = DEBUG_BORDERS
        self.refresh_paths()
        
        # --- Detect Steam Deck ---
        steamdeck = os.path.exists('/etc/os-release') and 'steamdeck' in open('/etc/os-release').read().lower()
        self.shortcut_handler = ShortcutHandler(steamdeck=steamdeck)
        
        # Initialize services early
        from jackify.backend.services.api_key_service import APIKeyService
        from jackify.backend.services.resolution_service import ResolutionService
        from jackify.backend.handlers.config_handler import ConfigHandler
        self.api_key_service = APIKeyService()
        self.resolution_service = ResolutionService()
        self.config_handler = ConfigHandler()
        
        # --- Fetch shortcuts for ModOrganizer.exe using existing backend functionality ---
        # Use existing discover_executable_shortcuts which already filters by protontricks availability
        from jackify.backend.handlers.modlist_handler import ModlistHandler  
        
        # Initialize modlist handler with empty config dict to use default initialization
        modlist_handler = ModlistHandler({})
        discovered_modlists = modlist_handler.discover_executable_shortcuts("ModOrganizer.exe")
        
        # Convert to shortcut_handler format for UI compatibility
        self.mo2_shortcuts = []
        for modlist in discovered_modlists:
            # Convert discovered modlist format to shortcut format
            shortcut = {
                'AppName': modlist.get('name', 'Unknown'),
                'AppID': modlist.get('appid', ''),
                'StartDir': modlist.get('path', ''),
                'Exe': f"{modlist.get('path', '')}/ModOrganizer.exe"
            }
            self.mo2_shortcuts.append(shortcut)
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
            display = f"{shortcut.get('AppName', 'Unknown')} ({shortcut.get('StartDir', '')})"
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
        cancel_btn.clicked.connect(self.go_back)
        btn_row.addWidget(cancel_btn)
        user_config_widget = QWidget()
        user_config_widget.setLayout(user_config_vbox)
        if self.debug:
            user_config_widget.setStyleSheet("border: 2px solid orange;")
            user_config_widget.setToolTip("USER_CONFIG_WIDGET")
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
        # Rotate log file at start of each workflow run (keep 5 backups)
        from jackify.backend.handlers.logging_handler import LoggingHandler
        from pathlib import Path
        log_handler = LoggingHandler()
        log_handler.rotate_log_file_per_run(Path(self.modlist_log_path), backup_count=5)
        
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
        modlist_name = shortcut.get('AppName', '')
        install_dir = shortcut.get('StartDir', '')
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
        try:
            # Start time tracking
            self._workflow_start_time = time.time()
            
            self._safe_append_text("[Jackify] Starting post-install configuration...")
            
            # Create configuration thread using backend service
            from PySide6.QtCore import QThread, Signal
            
            class ConfigurationThread(QThread):
                progress_update = Signal(str)
                configuration_complete = Signal(bool, str, str)
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
                        
                        # Define callbacks
                        def progress_callback(message):
                            self.progress_update.emit(message)
                            
                        def completion_callback(success, message, modlist_name):
                            self.configuration_complete.emit(success, message, modlist_name)
                            
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
            self.config_thread.progress_update.connect(self._safe_append_text)
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
        if self.stacked_widget:
            self.stacked_widget.setCurrentIndex(self.main_menu_index)

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
        """Refresh the modlist dropdown by re-detecting ModOrganizer.exe shortcuts"""
        try:
            # Re-detect shortcuts using existing backend functionality
            from jackify.backend.handlers.modlist_handler import ModlistHandler  
            
            # Initialize modlist handler with empty config dict to use default initialization
            modlist_handler = ModlistHandler({})
            discovered_modlists = modlist_handler.discover_executable_shortcuts("ModOrganizer.exe")
            
            # Convert to shortcut_handler format for UI compatibility
            self.mo2_shortcuts = []
            for modlist in discovered_modlists:
                # Convert discovered modlist format to shortcut format
                shortcut = {
                    'AppName': modlist.get('name', 'Unknown'),
                    'AppID': modlist.get('appid', ''),
                    'StartDir': modlist.get('path', ''),
                    'Exe': f"{modlist.get('path', '')}/ModOrganizer.exe"
                }
                self.mo2_shortcuts.append(shortcut)
            
            # Clear and repopulate the combo box
            self.shortcut_combo.clear()
            self.shortcut_combo.addItem("Please Select...")
            self.shortcut_map.clear()
            
            for shortcut in self.mo2_shortcuts:
                display = f"{shortcut.get('AppName', 'Unknown')} ({shortcut.get('StartDir', '')})"
                self.shortcut_combo.addItem(display)
                self.shortcut_map.append(shortcut)
            
            # Show feedback to user in UI only (don't write to log before workflow starts)
            # Feedback is shown by the updated dropdown items
            
        except Exception as e:
            # Don't write to log file before workflow starts - just show error in UI
            MessageService.warning(self, "Refresh Error", f"Failed to refresh modlist list: {e}", safety_level="low") 

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