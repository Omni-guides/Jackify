"""
Jackify GUI Frontend Main Application

Main entry point for the Jackify GUI application using PySide6.
This replaces the legacy jackify_gui implementation with a refactored architecture.
"""

import sys
import os
from pathlib import Path

# Suppress xkbcommon locale errors (harmless but annoying)
os.environ['QT_LOGGING_RULES'] = '*.debug=false;qt.qpa.*=false;*.warning=false'
os.environ['QT_ENABLE_GLYPH_CACHE_WORKAROUND'] = '1'

# Hidden diagnostic flag for debugging PyInstaller environment issues - must be first
if '--env-diagnostic' in sys.argv:
    import json
    from datetime import datetime
    
    print("PyInstaller Environment Diagnostic")
    print("=" * 50)
    
    # Check if we're in PyInstaller
    is_frozen = getattr(sys, 'frozen', False)
    meipass = getattr(sys, '_MEIPASS', None)
    
    print(f"Frozen: {is_frozen}")
    print(f"_MEIPASS: {meipass}")
    
    # Capture environment data
    env_data = {
        'timestamp': datetime.now().isoformat(),
        'context': 'pyinstaller_internal',
        'frozen': is_frozen,
        'meipass': meipass,
        'python_executable': sys.executable,
        'working_directory': os.getcwd(),
        'sys_path': sys.path,
    }
    
    # PyInstaller-specific environment variables
    pyinstaller_vars = {}
    for key, value in os.environ.items():
        if any(term in key.lower() for term in ['mei', 'pyinstaller', 'tmp']):
            pyinstaller_vars[key] = value
    
    env_data['pyinstaller_vars'] = pyinstaller_vars
    
    # Check LD_LIBRARY_PATH
    ld_path = os.environ.get('LD_LIBRARY_PATH', '')
    if ld_path:
        suspicious = [p for p in ld_path.split(':') if 'mei' in p.lower() or 'tmp' in p.lower()]
        env_data['ld_library_path'] = ld_path
        env_data['ld_library_path_suspicious'] = suspicious
    
    # Try to find jackify-engine from PyInstaller context
    engine_paths = []
    if meipass:
        meipass_path = Path(meipass)
        potential_engine = meipass_path / "jackify" / "engine" / "jackify-engine"
        if potential_engine.exists():
            engine_paths.append(str(potential_engine))
    
    env_data['engine_paths_found'] = engine_paths
    
    # Output the results
    print("\nEnvironment Data:")
    print(json.dumps(env_data, indent=2))
    
    # Save to file
    try:
        output_file = Path.cwd() / "pyinstaller_env_capture.json"
        with open(output_file, 'w') as f:
            json.dump(env_data, f, indent=2)
        print(f"\nData saved to: {output_file}")
    except Exception as e:
        print(f"\nCould not save data: {e}")
    
    sys.exit(0)

from jackify import __version__ as jackify_version

if '--help' in sys.argv or '-h' in sys.argv:
    print("""Jackify - Native Linux Modlist Manager\n\nUsage:\n  jackify [--cli] [--debug] [--version] [--help]\n\nOptions:\n  --cli         Launch CLI frontend\n  --debug       Enable debug logging\n  --version     Show version and exit\n  --help, -h    Show this help message and exit\n\nIf no options are given, the GUI will launch by default.\n""")
    sys.exit(0)

if '-v' in sys.argv or '--version' in sys.argv or '-V' in sys.argv:
    print(f"Jackify version {jackify_version}")
    sys.exit(0)


from jackify import __version__

# Add src directory to Python path
src_dir = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(src_dir))

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QVBoxLayout, QPushButton,
    QStackedWidget, QHBoxLayout, QDialog, QFormLayout, QLineEdit, QCheckBox, QSpinBox, QMessageBox, QGroupBox, QGridLayout, QFileDialog, QToolButton, QStyle
)
from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QIcon
import json

# Import backend services and models
from jackify.backend.models.configuration import SystemInfo
from jackify.backend.services.modlist_service import ModlistService
from jackify.frontends.gui.services.message_service import MessageService
from jackify.frontends.gui.shared_theme import DEBUG_BORDERS

def debug_print(message):
    """Print debug message only if debug mode is enabled"""
    from jackify.backend.handlers.config_handler import ConfigHandler
    config_handler = ConfigHandler()
    if config_handler.get('debug_mode', False):
        print(message)

# Constants for styling and disclaimer
DISCLAIMER_TEXT = (
    "Disclaimer: Jackify is currently in an alpha state. This software is provided as-is, "
    "without any warranty or guarantee of stability. By using Jackify, you acknowledge that you do so at your own risk. "
    "The developers are not responsible for any data loss, system issues, or other problems that may arise from its use. "
    "Please back up your data and use caution."
)

MENU_ITEMS = [
    ("Modlist Tasks", "modlist_tasks"),
    ("Tuxborn Automatic Installer", "tuxborn_installer"),
    ("Hoolamike Tasks", "hoolamike_tasks"),
    ("Additional Tasks", "additional_tasks"),
    ("Exit Jackify", "exit_jackify"),
]


class FeaturePlaceholder(QWidget):
    """Placeholder widget for features not yet implemented"""
    
    def __init__(self, stacked_widget=None):
        super().__init__()
        layout = QVBoxLayout()
        
        label = QLabel("[Feature screen placeholder]")
        label.setAlignment(Qt.AlignCenter)
        layout.addWidget(label)
        
        back_btn = QPushButton("Back to Main Menu")
        if stacked_widget:
            back_btn.clicked.connect(lambda: stacked_widget.setCurrentIndex(0))
        layout.addWidget(back_btn)
        
        self.setLayout(layout)


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        try:
            super().__init__(parent)
            from jackify.backend.handlers.config_handler import ConfigHandler
            self.config_handler = ConfigHandler()
            self._original_debug_mode = self.config_handler.get('debug_mode', False)
            self.setWindowTitle("Settings")
            self.setModal(True)
            self.setMinimumWidth(750)
            self.setStyleSheet("QDialog { background-color: #232323; color: #eee; } QPushButton:hover { background-color: #333; }")
            main_layout = QVBoxLayout()
            self.setLayout(main_layout)

            # --- Resource Limits Section ---
            resource_group = QGroupBox("Resource Limits")
            resource_group.setStyleSheet("QGroupBox { border: 1px solid #555; border-radius: 6px; margin-top: 8px; padding: 8px; background: #23282d; } QGroupBox:title { subcontrol-origin: margin; left: 10px; padding: 0 3px 0 3px; font-weight: bold; color: #fff; }")
            resource_layout = QGridLayout()
            resource_group.setLayout(resource_layout)
            resource_layout.setVerticalSpacing(4)
            resource_layout.setHorizontalSpacing(8)
            resource_layout.addWidget(self._bold_label("Resource"), 0, 0, 1, 1, Qt.AlignLeft)
            resource_layout.addWidget(self._bold_label("Max Tasks"), 0, 1, 1, 1, Qt.AlignLeft)
            self.resource_settings_path = os.path.expanduser("~/.config/jackify/resource_settings.json")
            self.resource_settings = self._load_json(self.resource_settings_path)
            self.resource_edits = {}
            resource_row_index = 0
            for resource_row_index, (k, v) in enumerate(self.resource_settings.items(), start=1):
                try:
                    # Create resource label with optional inline checkbox for File Extractor
                    if k == "File Extractor":
                        # Create horizontal layout for File Extractor with inline checkbox
                        resource_row = QHBoxLayout()
                        resource_label = QLabel(f"{k}:", parent=self)
                        resource_row.addWidget(resource_label)
                        resource_row.addSpacing(10)  # Add some spacing
                        
                        multithreading_checkbox = QCheckBox("Multithreading (Experimental)")
                        multithreading_checkbox.setChecked(v.get('_7zzMultiThread', 'off') == 'on')
                        multithreading_checkbox.setToolTip("Enables multithreaded file extraction using 7-Zip. May improve extraction speed on multi-core systems but could be less stable.")
                        multithreading_checkbox.setStyleSheet("color: #fff;")
                        resource_row.addWidget(multithreading_checkbox)
                        resource_row.addStretch()  # Push checkbox to the left
                        
                        # Add the horizontal layout to the grid
                        resource_layout.addLayout(resource_row, resource_row_index, 0)
                    else:
                        resource_layout.addWidget(QLabel(f"{k}:", parent=self), resource_row_index, 0, 1, 1, Qt.AlignLeft)
                    
                    max_tasks_spin = QSpinBox()
                    max_tasks_spin.setMinimum(1)
                    max_tasks_spin.setMaximum(128)
                    max_tasks_spin.setValue(v.get('MaxTasks', 16))
                    max_tasks_spin.setToolTip("Maximum number of concurrent tasks for this resource.")
                    max_tasks_spin.setFixedWidth(160)
                    resource_layout.addWidget(max_tasks_spin, resource_row_index, 1)
                    
                    # Store the widgets (checkbox for File Extractor, None for others)
                    if k == "File Extractor":
                        self.resource_edits[k] = (multithreading_checkbox, max_tasks_spin)
                    else:
                        self.resource_edits[k] = (None, max_tasks_spin)
                except Exception as e:
                    print(f"[ERROR] Failed to create widgets for resource '{k}': {e}")
                    continue
            
            # If no resources exist, show helpful message
            if not self.resource_edits:
                info_label = QLabel("Resource Limit settings will be generated once a modlist install action is performed")
                info_label.setStyleSheet("color: #aaa; font-style: italic; padding: 20px; font-size: 11pt;")
                info_label.setWordWrap(True)
                info_label.setAlignment(Qt.AlignCenter)
                info_label.setMinimumHeight(60)  # Ensure enough height to prevent cutoff
                resource_layout.addWidget(info_label, 1, 0, 3, 2)  # Span more rows for better space
            
            # Bandwidth limiter row (only show if Downloads resource exists)
            if "Downloads" in self.resource_settings:
                downloads_throughput = self.resource_settings["Downloads"].get("MaxThroughput", 0)
                
                self.bandwidth_spin = QSpinBox()
                self.bandwidth_spin.setMinimum(0)
                self.bandwidth_spin.setMaximum(1000000)
                self.bandwidth_spin.setValue(downloads_throughput)
                self.bandwidth_spin.setSuffix(" KB/s")
                self.bandwidth_spin.setFixedWidth(160)
                self.bandwidth_spin.setToolTip("Set the maximum download speed for modlist downloads. 0 = unlimited.")
                bandwidth_note = QLabel("(0 = unlimited)")
                bandwidth_note.setStyleSheet("color: #aaa; font-size: 10pt;")
                # Create horizontal layout for bandwidth row
                bandwidth_row = QHBoxLayout()
                bandwidth_row.addWidget(self.bandwidth_spin)
                bandwidth_row.addWidget(bandwidth_note)
                bandwidth_row.addStretch()  # Push to the left
                
                resource_layout.addWidget(QLabel("Bandwidth Limit:", parent=self), resource_row_index+1, 0, 1, 1, Qt.AlignLeft)
                resource_layout.addLayout(bandwidth_row, resource_row_index+1, 1)
            else:
                self.bandwidth_spin = None  # No bandwidth UI if Downloads resource doesn't exist
            main_layout.addWidget(resource_group)
            main_layout.addSpacing(12)

            # --- Debug & Diagnostics Section ---
            debug_group = QGroupBox("Debug & Diagnostics")
            debug_group.setStyleSheet("QGroupBox { border: 1px solid #555; border-radius: 6px; margin-top: 8px; padding: 8px; background: #23282d; } QGroupBox:title { subcontrol-origin: margin; left: 10px; padding: 0 3px 0 3px; font-weight: bold; color: #fff; }")
            debug_layout = QVBoxLayout()
            debug_group.setLayout(debug_layout)
            self.debug_checkbox = QCheckBox("Enable debug mode (requires restart)")
            # Load debug_mode from config
            self.debug_checkbox.setChecked(self.config_handler.get('debug_mode', False))
            self.debug_checkbox.setToolTip("Enable verbose debug logging. Requires Jackify restart to take effect.")
            self.debug_checkbox.setStyleSheet("color: #fff;")
            debug_layout.addWidget(self.debug_checkbox)
            main_layout.addWidget(debug_group)
            main_layout.addSpacing(12)

            # --- Nexus API Key Section ---
            api_group = QGroupBox("Nexus API Key")
            api_group.setStyleSheet("QGroupBox { border: 1px solid #555; border-radius: 6px; margin-top: 8px; padding: 8px; background: #23282d; } QGroupBox:title { subcontrol-origin: margin; left: 10px; padding: 0 3px 0 3px; font-weight: bold; color: #fff; }")
            api_layout = QHBoxLayout()
            api_group.setLayout(api_layout)
            self.api_key_edit = QLineEdit()
            self.api_key_edit.setEchoMode(QLineEdit.Password)
            api_key = self.config_handler.get_api_key()
            if api_key:
                self.api_key_edit.setText(api_key)
            else:
                self.api_key_edit.setText("")
            self.api_key_edit.setToolTip("Your Nexus API Key (obfuscated by default, click Show to reveal)")
            # Connect for immediate saving when text changes
            self.api_key_edit.textChanged.connect(self._on_api_key_changed)
            self.api_show_btn = QToolButton()
            self.api_show_btn.setCheckable(True)
            self.api_show_btn.setIcon(QIcon.fromTheme("view-visible"))
            self.api_show_btn.setToolTip("Show or hide your API key")
            self.api_show_btn.toggled.connect(self._toggle_api_key_visibility)
            self.api_show_btn.setStyleSheet("")
            clear_api_btn = QPushButton("Clear API Key")
            clear_api_btn.clicked.connect(self._clear_api_key)
            api_layout.addWidget(QLabel("Nexus API Key:"))
            api_layout.addWidget(self.api_key_edit)
            api_layout.addWidget(self.api_show_btn)
            api_layout.addWidget(clear_api_btn)
            main_layout.addWidget(api_group)
            main_layout.addSpacing(12)

            # --- Directories & Paths Section ---
            dir_group = QGroupBox("Directories & Paths")
            dir_group.setStyleSheet("QGroupBox { border: 1px solid #555; border-radius: 6px; margin-top: 8px; padding: 8px; background: #23282d; } QGroupBox:title { subcontrol-origin: margin; left: 10px; padding: 0 3px 0 3px; font-weight: bold; color: #fff; }")
            dir_layout = QFormLayout()
            dir_group.setLayout(dir_layout)
            self.install_dir_edit = QLineEdit(self.config_handler.get("modlist_install_base_dir", ""))
            self.install_dir_edit.setToolTip("Default directory for modlist installations.")
            self.install_dir_btn = QPushButton()
            self.install_dir_btn.setIcon(QIcon.fromTheme("folder-open"))
            self.install_dir_btn.setToolTip("Browse for directory")
            self.install_dir_btn.setFixedWidth(32)
            self.install_dir_btn.clicked.connect(lambda: self._pick_directory(self.install_dir_edit))
            install_dir_row = QHBoxLayout()
            install_dir_row.addWidget(self.install_dir_edit)
            install_dir_row.addWidget(self.install_dir_btn)
            dir_layout.addRow(QLabel("Install Base Dir:"), install_dir_row)
            self.download_dir_edit = QLineEdit(self.config_handler.get("modlist_downloads_base_dir", ""))
            self.download_dir_edit.setToolTip("Default directory for modlist downloads.")
            self.download_dir_btn = QPushButton()
            self.download_dir_btn.setIcon(QIcon.fromTheme("folder-open"))
            self.download_dir_btn.setToolTip("Browse for directory")
            self.download_dir_btn.setFixedWidth(32)
            self.download_dir_btn.clicked.connect(lambda: self._pick_directory(self.download_dir_edit))
            download_dir_row = QHBoxLayout()
            download_dir_row.addWidget(self.download_dir_edit)
            download_dir_row.addWidget(self.download_dir_btn)
            dir_layout.addRow(QLabel("Downloads Base Dir:"), download_dir_row)
            
            # Jackify Data Directory
            from jackify.shared.paths import get_jackify_data_dir
            current_jackify_dir = str(get_jackify_data_dir())
            self.jackify_data_dir_edit = QLineEdit(current_jackify_dir)
            self.jackify_data_dir_edit.setToolTip("Directory for Jackify data (logs, downloads, temp files). Default: ~/Jackify")
            self.jackify_data_dir_btn = QPushButton()
            self.jackify_data_dir_btn.setIcon(QIcon.fromTheme("folder-open"))
            self.jackify_data_dir_btn.setToolTip("Browse for directory")
            self.jackify_data_dir_btn.setFixedWidth(32)
            self.jackify_data_dir_btn.clicked.connect(lambda: self._pick_directory(self.jackify_data_dir_edit))
            jackify_data_dir_row = QHBoxLayout()
            jackify_data_dir_row.addWidget(self.jackify_data_dir_edit)
            jackify_data_dir_row.addWidget(self.jackify_data_dir_btn)
            
            # Reset to default button
            reset_jackify_dir_btn = QPushButton("Reset")
            reset_jackify_dir_btn.setToolTip("Reset to default (~/ Jackify)")
            reset_jackify_dir_btn.setFixedWidth(50)
            reset_jackify_dir_btn.clicked.connect(lambda: self.jackify_data_dir_edit.setText(str(Path.home() / "Jackify")))
            jackify_data_dir_row.addWidget(reset_jackify_dir_btn)
            
            dir_layout.addRow(QLabel("Jackify Data Dir:"), jackify_data_dir_row)
            main_layout.addWidget(dir_group)
            main_layout.addSpacing(12)

            # --- Save/Close/Help Buttons ---
            btn_layout = QHBoxLayout()
            self.help_btn = QPushButton("Help")
            self.help_btn.setToolTip("Help/documentation coming soon!")
            self.help_btn.clicked.connect(self._show_help)
            btn_layout.addWidget(self.help_btn)
            btn_layout.addStretch(1)
            save_btn = QPushButton("Save")
            close_btn = QPushButton("Close")
            save_btn.clicked.connect(self._save)
            close_btn.clicked.connect(self.reject)
            btn_layout.addWidget(save_btn)
            btn_layout.addWidget(close_btn)
            main_layout.addSpacing(10)
            main_layout.addLayout(btn_layout)

            # Set tab order for accessibility
            # Get the first resource's widgets if any exist
            if self.resource_edits:
                first_resource_key = list(self.resource_edits.keys())[0]
                first_multithreading, first_max_tasks = self.resource_edits[first_resource_key]
                # Set tab order starting with the first max tasks spinner
                self.setTabOrder(first_max_tasks, self.bandwidth_spin)
            # Continue with bandwidth spinner regardless of resources
            self.setTabOrder(self.bandwidth_spin, self.debug_checkbox)
            self.setTabOrder(self.debug_checkbox, self.api_key_edit)
            self.setTabOrder(self.api_key_edit, self.api_show_btn)
            self.setTabOrder(self.api_show_btn, clear_api_btn)
            self.setTabOrder(clear_api_btn, self.install_dir_edit)
            self.setTabOrder(self.install_dir_edit, self.install_dir_btn)
            self.setTabOrder(self.install_dir_btn, self.download_dir_edit)
            self.setTabOrder(self.download_dir_edit, self.download_dir_btn)
            self.setTabOrder(self.download_dir_btn, save_btn)
            self.setTabOrder(save_btn, close_btn)

            self.error_label = QLabel("")
            self.error_label.setStyleSheet("color: #f55; font-weight: bold;")
            main_layout.insertWidget(0, self.error_label)
        except Exception as e:
            print(f"[ERROR] Exception in SettingsDialog __init__: {e}")
            import traceback
            traceback.print_exc()
            raise

    def _toggle_api_key_visibility(self, checked):
        # Always use the same eyeball icon, only change color when toggled
        eye_icon = QIcon.fromTheme("view-visible")
        if not eye_icon.isNull():
            self.api_show_btn.setIcon(eye_icon)
            self.api_show_btn.setText("")
        else:
            self.api_show_btn.setIcon(QIcon())
            self.api_show_btn.setText("\U0001F441")  # 👁
        if checked:
            self.api_key_edit.setEchoMode(QLineEdit.Normal)
            self.api_show_btn.setStyleSheet("QToolButton { color: #4fc3f7; }")  # Jackify blue
        else:
            self.api_key_edit.setEchoMode(QLineEdit.Password)
            self.api_show_btn.setStyleSheet("")

    def _pick_directory(self, line_edit):
        dir_path = QFileDialog.getExistingDirectory(self, "Select Directory", line_edit.text() or os.path.expanduser("~"))
        if dir_path:
            line_edit.setText(dir_path)

    def _show_help(self):
        from jackify.frontends.gui.services.message_service import MessageService
        MessageService.information(self, "Help", "Help/documentation coming soon!", safety_level="low")

    def _load_json(self, path):
        if os.path.exists(path):
            try:
                with open(path, 'r') as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _save_json(self, path, data):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            MessageService.warning(self, "Error", f"Failed to save {path}: {e}", safety_level="medium")

    def _clear_api_key(self):
        self.api_key_edit.setText("")
        self.config_handler.clear_api_key()
        MessageService.information(self, "API Key Cleared", "Nexus API Key has been cleared.", safety_level="low")

    def _on_api_key_changed(self, text):
        """Handle immediate API key saving when text changes"""
        api_key = text.strip()
        self.config_handler.save_api_key(api_key)

    def _save(self):
        # Validate values
        for k, (multithreading_checkbox, max_tasks_spin) in self.resource_edits.items():
            if max_tasks_spin.value() > 128:
                self.error_label.setText(f"Invalid value for {k}: Max Tasks must be <= 128.")
                return
        if self.bandwidth_spin and self.bandwidth_spin.value() > 1000000:
            self.error_label.setText("Bandwidth limit must be <= 1,000,000 KB/s.")
            return
        self.error_label.setText("")
        # Save resource settings
        for k, (multithreading_checkbox, max_tasks_spin) in self.resource_edits.items():
            resource_data = self.resource_settings.get(k, {})
            resource_data['MaxTasks'] = max_tasks_spin.value()
            # Only add multithreading setting for File Extractor
            if k == "File Extractor" and multithreading_checkbox:
                if multithreading_checkbox.isChecked():
                    resource_data['_7zzMultiThread'] = 'on'
                else:
                    # Remove the setting if unchecked (don't add 'off')
                    resource_data.pop('_7zzMultiThread', None)
            self.resource_settings[k] = resource_data
        
        # Save bandwidth limit to Downloads resource MaxThroughput (only if bandwidth UI exists)
        if self.bandwidth_spin:
            if "Downloads" not in self.resource_settings:
                self.resource_settings["Downloads"] = {"MaxTasks": 16}  # Provide default MaxTasks
            self.resource_settings["Downloads"]["MaxThroughput"] = self.bandwidth_spin.value()
        
        # Save all resource settings (including bandwidth) in one operation
        self._save_json(self.resource_settings_path, self.resource_settings)
        
        # Save debug mode to config
        self.config_handler.set('debug_mode', self.debug_checkbox.isChecked())
        # Save API key
        api_key = self.api_key_edit.text().strip()
        self.config_handler.save_api_key(api_key)
        # Save modlist base dirs
        self.config_handler.set("modlist_install_base_dir", self.install_dir_edit.text().strip())
        self.config_handler.set("modlist_downloads_base_dir", self.download_dir_edit.text().strip())
        # Save jackify data directory (always store actual path, never None)
        jackify_data_dir = self.jackify_data_dir_edit.text().strip()
        self.config_handler.set("jackify_data_dir", jackify_data_dir)
        self.config_handler.save_config()
        
        # Refresh cached paths in GUI screens if Jackify directory changed
        self._refresh_gui_paths()
        
        # Check if debug mode changed and prompt for restart
        new_debug_mode = self.debug_checkbox.isChecked()
        if new_debug_mode != self._original_debug_mode:
            reply = MessageService.question(self, "Restart Required", "Debug mode change requires a restart. Restart Jackify now?", safety_level="low")
            if reply == QMessageBox.Yes:
                import os, sys
                if getattr(sys, 'frozen', False):
                    # PyInstaller bundle: safe to restart
                    self.accept()
                    os.execv(sys.executable, [sys.executable] + sys.argv)
                    return
                else:
                    # Dev mode: show message instead of auto-restart
                    MessageService.information(self, "Manual Restart Required", "Please restart Jackify manually to apply debug mode changes.", safety_level="low")
                    self.accept()
                    return
        MessageService.information(self, "Settings Saved", "Settings have been saved successfully.", safety_level="low")
        self.accept()

    def _refresh_gui_paths(self):
        """Refresh cached paths in all GUI screens."""
        try:
            # Get the main window through parent relationship
            main_window = self.parent()
            if not main_window or not hasattr(main_window, 'stacked_widget'):
                return
            
            # Refresh paths in all screens that have the method
            screens_to_refresh = [
                getattr(main_window, 'install_modlist_screen', None),
                getattr(main_window, 'configure_new_modlist_screen', None),
                getattr(main_window, 'configure_existing_modlist_screen', None),
                getattr(main_window, 'tuxborn_screen', None),
            ]
            
            for screen in screens_to_refresh:
                if screen and hasattr(screen, 'refresh_paths'):
                    screen.refresh_paths()
                    
        except Exception as e:
            print(f"Warning: Could not refresh GUI paths: {e}")

    def _bold_label(self, text):
        label = QLabel(text)
        label.setStyleSheet("font-weight: bold; color: #fff;")
        return label


class JackifyMainWindow(QMainWindow):
    """Main window for Jackify GUI application"""
    
    def __init__(self, dev_mode=False):
        super().__init__()
        self.setWindowTitle("Jackify")
        self.setMinimumSize(1400, 950)
        self.resize(1400, 900)
        
        # Initialize backend services
        self._initialize_backend()
        
        # Set up UI
        self._setup_ui(dev_mode=dev_mode)
        
        # Set up cleanup
        QApplication.instance().aboutToQuit.connect(self.cleanup_processes)
    
    def _initialize_backend(self):
        """Initialize backend services for direct use (no subprocess)"""
        # Determine system info
        self.system_info = SystemInfo(is_steamdeck=self._is_steamdeck())
        
        # Apply resource limits for optimal operation
        self._apply_resource_limits()
        
        # Initialize backend services
        self.backend_services = {
            'modlist_service': ModlistService(self.system_info)
        }
        
        # Initialize GUI services
        self.gui_services = {}
        
        # Initialize protontricks detection service
        from jackify.backend.services.protontricks_detection_service import ProtontricksDetectionService
        self.protontricks_service = ProtontricksDetectionService(steamdeck=self.system_info.is_steamdeck)
        
        # Initialize update service
        from jackify.backend.services.update_service import UpdateService
        self.update_service = UpdateService(__version__)
        
        debug_print(f"GUI Backend initialized - Steam Deck: {self.system_info.is_steamdeck}")
    
    def _is_steamdeck(self):
        """Check if running on Steam Deck"""
        try:
            if os.path.exists("/etc/os-release"):
                with open("/etc/os-release", "r") as f:
                    content = f.read()
                    if "steamdeck" in content:
                        return True
            return False
        except Exception:
            return False
    
    def _apply_resource_limits(self):
        """Apply recommended resource limits for optimal Jackify operation"""
        try:
            from jackify.backend.services.resource_manager import ResourceManager
            
            resource_manager = ResourceManager()
            success = resource_manager.apply_recommended_limits()
            
            if success:
                status = resource_manager.get_limit_status()
                if status['target_achieved']:
                    debug_print(f"Resource limits optimized: file descriptors set to {status['current_soft']}")
                else:
                    print(f"Resource limits improved: file descriptors increased to {status['current_soft']} (target: {status['target_limit']})")
            else:
                # Log the issue but don't block startup
                status = resource_manager.get_limit_status()
                print(f"Warning: Could not optimize resource limits: current file descriptors={status['current_soft']}, target={status['target_limit']}")
                
                # Check if debug mode is enabled for additional info
                from jackify.backend.handlers.config_handler import ConfigHandler
                config_handler = ConfigHandler()
                if config_handler.get('debug_mode', False):
                    instructions = resource_manager.get_manual_increase_instructions()
                    print(f"Manual increase instructions available for {instructions['distribution']}")
                    
        except Exception as e:
            # Don't block startup on resource management errors
            print(f"Warning: Error applying resource limits: {e}")
    
    def _setup_ui(self, dev_mode=False):
        """Set up the user interface"""
        # Create stacked widget for screen navigation
        self.stacked_widget = QStackedWidget()
        
        # Create screens using refactored codebase
        from jackify.frontends.gui.screens import (
            MainMenu, TuxbornInstallerScreen, ModlistTasksScreen, 
            InstallModlistScreen, ConfigureNewModlistScreen, ConfigureExistingModlistScreen
        )
        
        self.main_menu = MainMenu(stacked_widget=self.stacked_widget, dev_mode=dev_mode)
        self.feature_placeholder = FeaturePlaceholder(stacked_widget=self.stacked_widget)
        
        self.modlist_tasks_screen = ModlistTasksScreen(
            stacked_widget=self.stacked_widget, 
            main_menu_index=0,
            dev_mode=dev_mode
        )
        self.tuxborn_screen = TuxbornInstallerScreen(
            stacked_widget=self.stacked_widget, 
            main_menu_index=0
        )
        self.install_modlist_screen = InstallModlistScreen(
            stacked_widget=self.stacked_widget, 
            main_menu_index=3
        )
        self.configure_new_modlist_screen = ConfigureNewModlistScreen(
            stacked_widget=self.stacked_widget, 
            main_menu_index=3
        )
        self.configure_existing_modlist_screen = ConfigureExistingModlistScreen(
            stacked_widget=self.stacked_widget, 
            main_menu_index=3
        )
        
        # Add screens to stacked widget
        self.stacked_widget.addWidget(self.main_menu)           # Index 0: Main Menu
        self.stacked_widget.addWidget(self.tuxborn_screen)      # Index 1: Tuxborn Installer
        self.stacked_widget.addWidget(self.feature_placeholder) # Index 2: Placeholder
        self.stacked_widget.addWidget(self.modlist_tasks_screen)  # Index 3: Modlist Tasks
        self.stacked_widget.addWidget(self.install_modlist_screen)        # Index 4: Install Modlist
        self.stacked_widget.addWidget(self.configure_new_modlist_screen)  # Index 5: Configure New
        self.stacked_widget.addWidget(self.configure_existing_modlist_screen)  # Index 6: Configure Existing
        
        # Add debug tracking for screen changes
        self.stacked_widget.currentChanged.connect(self._debug_screen_change)
        
        # --- Persistent Bottom Bar ---
        bottom_bar = QWidget()
        bottom_bar_layout = QHBoxLayout()
        bottom_bar_layout.setContentsMargins(10, 2, 10, 2)
        bottom_bar_layout.setSpacing(0)
        bottom_bar.setLayout(bottom_bar_layout)
        bottom_bar.setFixedHeight(32)
        bottom_bar_style = "background-color: #181818; border-top: 1px solid #222;"
        if DEBUG_BORDERS:
            bottom_bar_style += " border: 2px solid lime;"
        bottom_bar.setStyleSheet(bottom_bar_style)

        # Version label (left)
        version_label = QLabel(f"Jackify v{__version__}")
        version_label.setStyleSheet("color: #bbb; font-size: 13px;")
        bottom_bar_layout.addWidget(version_label, alignment=Qt.AlignLeft)

        # Spacer
        bottom_bar_layout.addStretch(1)

        # Ko-Fi support link (center)
        kofi_link = QLabel('<a href="https://ko-fi.com/omni1" style="color:#72A5F2; text-decoration:none;">♥ Support on Ko-fi</a>')
        kofi_link.setStyleSheet("color: #72A5F2; font-size: 13px;")
        kofi_link.setTextInteractionFlags(Qt.TextBrowserInteraction)
        kofi_link.setOpenExternalLinks(True)
        kofi_link.setToolTip("Support Jackify development")
        bottom_bar_layout.addWidget(kofi_link, alignment=Qt.AlignCenter)

        # Spacer
        bottom_bar_layout.addStretch(1)

        # Settings button (right side)
        settings_btn = QLabel('<a href="#" style="color:#6cf; text-decoration:none;">Settings</a>')
        settings_btn.setStyleSheet("color: #6cf; font-size: 13px; padding-right: 8px;")
        settings_btn.setTextInteractionFlags(Qt.TextBrowserInteraction)
        settings_btn.setOpenExternalLinks(False)
        settings_btn.linkActivated.connect(self.open_settings_dialog)
        bottom_bar_layout.addWidget(settings_btn, alignment=Qt.AlignRight)

        # About button (right side)
        about_btn = QLabel('<a href="#" style="color:#6cf; text-decoration:none;">About</a>')
        about_btn.setStyleSheet("color: #6cf; font-size: 13px; padding-right: 8px;")
        about_btn.setTextInteractionFlags(Qt.TextBrowserInteraction)
        about_btn.setOpenExternalLinks(False)
        about_btn.linkActivated.connect(self.open_about_dialog)
        bottom_bar_layout.addWidget(about_btn, alignment=Qt.AlignRight)

        # --- Main Layout ---
        central_widget = QWidget()
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.addWidget(self.stacked_widget, stretch=1)  # Screen takes all available space
        main_layout.addWidget(bottom_bar)  # Bottom bar stays at bottom
        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)
        
        # Start with main menu
        self.stacked_widget.setCurrentIndex(0)
        
        # Check for protontricks after UI is set up
        self._check_protontricks_on_startup()

    def _debug_screen_change(self, index):
        """Debug method to track screen changes"""
        # Only show debug info if debug mode is enabled
        from jackify.backend.handlers.config_handler import ConfigHandler
        config_handler = ConfigHandler()
        if not config_handler.get('debug_mode', False):
            return
            
        screen_names = {
            0: "Main Menu",
            1: "Tuxborn Installer", 
            2: "Feature Placeholder",
            3: "Modlist Tasks Menu",
            4: "Install Modlist Screen",
            5: "Configure New Modlist",
            6: "Configure Existing Modlist"
        }
        screen_name = screen_names.get(index, f"Unknown Screen (Index {index})")
        widget = self.stacked_widget.widget(index)
        widget_class = widget.__class__.__name__ if widget else "None"
        # Only print screen change debug to stderr to avoid workflow log pollution
        import sys
        print(f"[DEBUG] Screen changed to Index {index}: {screen_name} (Widget: {widget_class})", file=sys.stderr)
        
        # Additional debug for the install modlist screen
        if index == 4:
            print(f"   Install Modlist Screen details:", file=sys.stderr)
            print(f"      - Widget type: {type(widget)}", file=sys.stderr)
            print(f"      - Widget file: {widget.__class__.__module__}", file=sys.stderr)
            if hasattr(widget, 'windowTitle'):
                print(f"      - Window title: {widget.windowTitle()}", file=sys.stderr)
            if hasattr(widget, 'layout'):
                layout = widget.layout()
                if layout:
                    print(f"      - Layout type: {type(layout)}", file=sys.stderr)
                    print(f"      - Layout children count: {layout.count()}", file=sys.stderr)
        
    def _check_protontricks_on_startup(self):
        """Check for protontricks installation on startup"""
        try:
            is_installed, installation_type, details = self.protontricks_service.detect_protontricks()
            
            if not is_installed:
                print(f"Protontricks not found: {details}")
                # Show error dialog
                from jackify.frontends.gui.dialogs.protontricks_error_dialog import ProtontricksErrorDialog
                dialog = ProtontricksErrorDialog(self.protontricks_service, self)
                result = dialog.exec()
                
                if result == QDialog.Rejected:
                    # User chose to exit
                    print("User chose to exit due to missing protontricks")
                    sys.exit(1)
            else:
                debug_print(f"Protontricks detected: {details}")
                
        except Exception as e:
            print(f"Error checking protontricks: {e}")
            # Continue anyway - don't block startup on detection errors
    
    def _check_for_updates_on_startup(self):
        """Check for updates on startup in background thread"""
        try:
            debug_print("Checking for updates on startup...")
            
            def update_check_callback(update_info):
                """Handle update check results"""
                try:
                    if update_info:
                        debug_print(f"Update available: v{update_info.version}")
                        # Show update dialog
                        from jackify.frontends.gui.dialogs.update_dialog import UpdateDialog
                        dialog = UpdateDialog(update_info, self.update_service, self)
                        dialog.show()  # Non-blocking
                    else:
                        debug_print("No updates available")
                except Exception as e:
                    debug_print(f"Error showing update dialog: {e}")
            
            # Check for updates in background
            self.update_service.check_for_updates_async(update_check_callback)
            
        except Exception as e:
            debug_print(f"Error checking for updates on startup: {e}")
            # Continue anyway - don't block startup on update check errors
    
    def cleanup_processes(self):
        """Clean up any running processes before closing"""
        try:
            # Clean up GUI services
            for service in self.gui_services.values():
                if hasattr(service, 'cleanup'):
                    service.cleanup()
            
            # Clean up screen processes
            screens = [
                self.modlist_tasks_screen, self.tuxborn_screen, self.install_modlist_screen,
                self.configure_new_modlist_screen, self.configure_existing_modlist_screen
            ]
            for screen in screens:
                if hasattr(screen, 'cleanup_processes'):
                    screen.cleanup_processes()
                elif hasattr(screen, 'cleanup'):
                    screen.cleanup()
            
            # Final safety net: kill any remaining jackify-engine processes
            try:
                import subprocess
                subprocess.run(['pkill', '-f', 'jackify-engine'], timeout=5, capture_output=True)
            except Exception:
                pass  # pkill might fail if no processes found, which is fine
                    
        except Exception as e:
            print(f"Error during cleanup: {e}")

    def closeEvent(self, event):
        """Handle window close event"""
        self.cleanup_processes()
        event.accept()

    def open_settings_dialog(self):
        try:
            dlg = SettingsDialog(self)
            dlg.exec()
        except Exception as e:
            print(f"[ERROR] Exception in open_settings_dialog: {e}")
            import traceback
            traceback.print_exc()

    def open_about_dialog(self):
        try:
            from jackify.frontends.gui.dialogs.about_dialog import AboutDialog
            dlg = AboutDialog(self.system_info, self)
            dlg.exec()
        except Exception as e:
            print(f"[ERROR] Exception in open_about_dialog: {e}")
            import traceback
            traceback.print_exc()


def resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath(os.path.dirname(__file__)), relative_path)


def main():
    """Main entry point for the GUI application"""
    # Check for CLI mode argument
    if len(sys.argv) > 1 and '--cli' in sys.argv:
        # Launch CLI frontend instead of GUI
        try:
            from jackify.frontends.cli.__main__ import main as cli_main
            print("CLI mode detected - switching to CLI frontend")
            return cli_main()
        except ImportError as e:
            print(f"Error importing CLI frontend: {e}")
            print("CLI mode not available. Falling back to GUI mode.")
    
    # Load config and set debug mode if needed
    from jackify.backend.handlers.config_handler import ConfigHandler
    config_handler = ConfigHandler()
    debug_mode = config_handler.get('debug_mode', False)
    # Command-line --debug always takes precedence
    if '--debug' in sys.argv or '-d' in sys.argv:
        debug_mode = True
    import logging
    if debug_mode:
        logging.getLogger().setLevel(logging.DEBUG)
        print("[Jackify] Debug mode enabled (from config or CLI)")
    else:
        logging.getLogger().setLevel(logging.WARNING)

    dev_mode = '--dev' in sys.argv

    # Launch GUI application
    from PySide6.QtGui import QIcon
    app = QApplication(sys.argv)
    
    # Global cleanup function for signal handling
    def emergency_cleanup():
        debug_print("Cleanup: terminating jackify-engine processes")
        try:
            import subprocess
            subprocess.run(['pkill', '-f', 'jackify-engine'], timeout=5, capture_output=True)
        except Exception:
            pass
    
    # Set up signal handlers for graceful shutdown
    import signal
    def signal_handler(sig, frame):
        print(f"Received signal {sig}, cleaning up...")
        emergency_cleanup()
        app.quit()
    
    signal.signal(signal.SIGINT, signal_handler)   # Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler)  # System shutdown
    
    # Set the application icon
    icon_path = resource_path('assets/JackifyLogo_256.png')
    app.setWindowIcon(QIcon(icon_path))
    window = JackifyMainWindow(dev_mode=dev_mode)
    window.show()
    
    # Start background update check after window is shown
    window._check_for_updates_on_startup()
    
    # Ensure cleanup on exit
    import atexit
    atexit.register(emergency_cleanup)
    
    return app.exec()


if __name__ == "__main__":
    sys.exit(main()) 