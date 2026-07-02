"""Settings dialog for Jackify GUI."""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QCheckBox,
    QTabWidget, QFileDialog, QMessageBox, QProgressDialog, QApplication, QToolButton
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from pathlib import Path
import json
import os
import logging

from jackify.frontends.gui.services.message_service import MessageService
from .settings_dialog_tabs import SettingsDialogTabsMixin
from .settings_dialog_proton import SettingsDialogProtonMixin

logger = logging.getLogger(__name__)


class SettingsDialog(SettingsDialogTabsMixin, SettingsDialogProtonMixin, QDialog):
    def __init__(self, parent=None):
        try:
            super().__init__(parent)
            from jackify.backend.handlers.config_handler import ConfigHandler
            import logging
            self.logger = logging.getLogger(__name__)
            self.config_handler = ConfigHandler()
            self._original_debug_mode = self.config_handler.get('debug_mode', False)
            self.setWindowTitle("Settings")
            self.setModal(True)
            self.setMinimumWidth(650)
            self.setMaximumWidth(800)
            self.setStyleSheet("QDialog { background-color: #232323; color: #eee; } QPushButton:hover { background-color: #333; }")

            main_layout = QVBoxLayout()
            self.setLayout(main_layout)

            # Create tab widget
            self.tab_widget = QTabWidget()
            self.tab_widget.setStyleSheet("""
                QTabWidget::pane { border: 1px solid #555; background: #232323; }
                QTabBar::tab { background: #333; color: #eee; padding: 8px 16px; margin: 2px; }
                QTabBar::tab:selected { background: #555; }
                QTabBar::tab:hover { background: #444; }
            """)
            main_layout.addWidget(self.tab_widget)

            # Create tabs
            self._create_general_tab()
            self._create_advanced_tab()

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

            # Add error label for validation messages
            self.error_label = QLabel("")
            self.error_label.setStyleSheet("QLabel { color: #ff6b6b; }")
            main_layout.addWidget(self.error_label)

            main_layout.addSpacing(10)
            main_layout.addLayout(btn_layout)

        except Exception as e:
            logger.error(f"Exception in SettingsDialog.__init__: {e}", exc_info=True)

    def _toggle_api_key_visibility(self, checked):
        eye_icon = QIcon.fromTheme("view-visible")
        if not eye_icon.isNull():
            self.api_show_btn.setIcon(eye_icon)
            self.api_show_btn.setText("")
        else:
            self.api_show_btn.setIcon(QIcon())
            self.api_show_btn.setText("\U0001F441")
        if checked:
            self.api_key_edit.setEchoMode(QLineEdit.Normal)
            self.api_show_btn.setStyleSheet("QToolButton { color: #3fd0ea; }")
        else:
            self.api_key_edit.setEchoMode(QLineEdit.Password)
            self.api_show_btn.setStyleSheet("")

    def _pick_directory(self, line_edit):
        from jackify.frontends.gui.utils import browse_directory
        dir_path = browse_directory(self, "Select Directory", line_edit.text())
        if dir_path:
            line_edit.setText(dir_path)

    def _show_help(self):
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

    def _on_api_key_changed(self):
        api_key = self.api_key_edit.text().strip()
        self.config_handler.save_api_key(api_key)


    def _update_oauth_status(self):
        from jackify.backend.services.nexus_auth_service import NexusAuthService
        auth_service = NexusAuthService()
        authenticated, method, username = auth_service.get_auth_status()
        if authenticated and method == 'oauth':
            tier_label = ""
            try:
                token = auth_service.get_auth_token()
                if token:
                    from jackify.backend.services.nexus_premium_service import NexusPremiumService
                    is_premium, _ = NexusPremiumService().check_premium_status(token, is_oauth=True)
                    tier_label = " [Premium]" if is_premium else " [Free]"
            except Exception:
                pass
            display = f"Authorised as {username}{tier_label}" if username else "Authorised"
            self.oauth_status_label.setText(display)
            self.oauth_status_label.setStyleSheet("color: #3fd0ea;")
            self.oauth_btn.setText("Revoke")
        elif method == 'oauth_expired':
            self.oauth_status_label.setText("OAuth token expired")
            self.oauth_status_label.setStyleSheet("color: #FFA726;")
            self.oauth_btn.setText("Re-authorise")
        else:
            self.oauth_status_label.setText("Not authorised")
            self.oauth_status_label.setStyleSheet("color: #f44336;")
            self.oauth_btn.setText("Authorise")

    def _handle_oauth_click(self):
        from jackify.backend.services.nexus_auth_service import NexusAuthService
        auth_service = NexusAuthService()
        authenticated, method, _ = auth_service.get_auth_status()
        if authenticated and method == 'oauth':
            reply = MessageService.question(self, "Revoke", "Revoke OAuth authorisation?", safety_level="low")
            if reply == QMessageBox.Yes:
                auth_service.revoke_oauth()
                self._update_oauth_status()
                MessageService.information(self, "Revoked", "OAuth authorisation has been revoked.", safety_level="low")
        else:
            reply = MessageService.question(self, "Authorise with Nexus",
                "Your browser will open for Nexus authorisation.\n\n"
                "Note: Your browser may ask permission to open 'xdg-open'\n"
                "or Jackify's protocol handler - please click 'Open' or 'Allow'.\n\n"
                "Please log in and authorise Jackify when prompted.\n\n"
                "Continue?", safety_level="low")
            if reply != QMessageBox.Yes:
                return
            progress = QProgressDialog(
                "Waiting for authorisation...\n\nPlease check your browser.",
                "Cancel", 0, 0, self
            )
            progress.setWindowTitle("Nexus OAuth")
            progress.setWindowModality(Qt.WindowModal)
            progress.setMinimumDuration(0)
            progress.setMinimumWidth(400)
            progress.show()
            QApplication.processEvents()
            def show_message(msg):
                progress.setLabelText(f"Waiting for authorisation...\n\n{msg}")
                QApplication.processEvents()
            success = auth_service.authorize_oauth(show_browser_message_callback=show_message)
            progress.close()
            QApplication.processEvents()
            self._update_oauth_status()
            if success:
                _, _, username = auth_service.get_auth_status()
                msg = "OAuth authorisation successful!"
                if username:
                    msg += f"\n\nAuthorised as: {username}"
                MessageService.information(self, "Success", msg, safety_level="low")
            else:
                MessageService.warning(self, "Failed", "OAuth authorisation failed or was cancelled.", safety_level="low")

    def _save(self):
        try:
            # Validate values (only if resource_edits exist)
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
                self.resource_settings[k] = resource_data

            # Save bandwidth limit to Downloads resource MaxThroughput (only if bandwidth UI exists)
            if self.bandwidth_spin:
                if "Downloads" not in self.resource_settings:
                    self.resource_settings["Downloads"] = {"MaxTasks": 16}  # Provide default MaxTasks
                # Convert KB/s to bytes/s for storage (resource_settings.json expects bytes)
                bandwidth_kb = self.bandwidth_spin.value()
                bandwidth_bytes = bandwidth_kb * 1024
                self.resource_settings["Downloads"]["MaxThroughput"] = bandwidth_bytes

            # Save all resource settings (including bandwidth) in one operation
            self._save_json(self.resource_settings_path, self.resource_settings)

            # Save debug mode to config
            self.config_handler.set('debug_mode', self.debug_checkbox.isChecked())
            # OAuth disabled for v0.1.8 - no fallback setting needed
            # Save API key
            api_key = self.api_key_edit.text().strip()
            self.config_handler.save_api_key(api_key)
            # Save modlist base dirs
            self.config_handler.set("modlist_install_base_dir", self.install_dir_edit.text().strip())
            self.config_handler.set("modlist_downloads_base_dir", self.download_dir_edit.text().strip())
            # Save jackify data directory (always store actual path, never None)
            jackify_data_dir = self.jackify_data_dir_edit.text().strip()
            self.config_handler.set("jackify_data_dir", jackify_data_dir)

            # Initialize with existing config values as fallback (prevents UnboundLocalError if auto-detection fails)
            resolved_install_path = self.config_handler.get("proton_path", "")
            resolved_install_version = self.config_handler.get("proton_version", "")

            # Save Install Proton selection - resolve "auto" to actual path
            selected_install_proton_path = self.install_proton_dropdown.currentData()
            if selected_install_proton_path == "none":
                # No Proton detected - warn user but allow saving other settings
                MessageService.warning(
                    self,
                    "No Compatible Proton Installed",
                    "Jackify requires Proton 9.0+, Proton Experimental, or GE-Proton 10+ to install modlists.\n\n"
                    "To install Proton:\n"
                    "1. Install any Windows game in Steam (Proton downloads automatically), OR\n"
                    "2. Install GE-Proton using ProtonPlus or ProtonUp-Qt, OR\n"
                    "3. Download GE-Proton manually from:\n"
                    "   https://github.com/GloriousEggroll/proton-ge-custom/releases\n\n"
                    "Your other settings will be saved, but modlist installation may not work without Proton.",
                    safety_level="medium"
                )
                logger.warning("No Proton detected - user warned, allowing save to proceed for other settings")
                # Don't modify Proton config, but continue to save other settings
            elif selected_install_proton_path == "auto":
                # Resolve "auto" to actual best Proton path using unified detection
                try:
                    from jackify.backend.handlers.wine_utils import WineUtils
                    best_proton = WineUtils.select_best_proton()

                    if best_proton:
                        resolved_install_path = str(best_proton['path'])
                        resolved_install_version = best_proton['name']
                        self.config_handler.set("proton_path", resolved_install_path)
                        self.config_handler.set("proton_version", resolved_install_version)
                    else:
                        # No Proton found - clear persisted selection so startup normalization
                        # can auto-heal once a compatible Proton is installed.
                        logger.warning("Auto Proton selection failed: No Proton versions found")
                        resolved_install_path = None
                        resolved_install_version = None
                        self.config_handler.set("proton_path", None)
                        self.config_handler.set("proton_version", None)
                except Exception as e:
                    # Exception during detection - clear persisted selection to avoid stale path usage.
                    logger.error(f"Auto Proton selection failed with exception: {e}", exc_info=True)
                    resolved_install_path = None
                    resolved_install_version = None
                    self.config_handler.set("proton_path", None)
                    self.config_handler.set("proton_version", None)
            else:
                # User selected specific Proton version
                resolved_install_path = selected_install_proton_path
                resolved_install_version = self.install_proton_dropdown.currentText()
                self.config_handler.set("proton_path", resolved_install_path)
                self.config_handler.set("proton_version", resolved_install_version)

            # Save Game Proton selection
            selected_game_proton_path = self.game_proton_dropdown.currentData()
            if selected_game_proton_path == "same_as_install":
                # Use same as install proton
                resolved_game_path = resolved_install_path
                resolved_game_version = resolved_install_version
            else:
                # User selected specific game Proton version
                resolved_game_path = selected_game_proton_path
                resolved_game_version = self.game_proton_dropdown.currentText()

            self.config_handler.set("game_proton_path", resolved_game_path)
            self.config_handler.set("game_proton_version", resolved_game_version)

            # Save auto tool compat preference
            self.config_handler.set('auto_tool_compat', self.auto_tool_compat_checkbox.isChecked())
            self.config_handler.set('force_github_updates', self.force_github_updates_checkbox.isChecked())
            if getattr(self, 'clf3_default_checkbox', None):
                from jackify.backend.services.tool_registry import set_active_engine_id
                set_active_engine_id("clf3" if self.clf3_default_checkbox.isChecked() else "jackify-engine")

            # Save component installation method preference
            if self.winetricks_radio.isChecked():
                method = 'winetricks'
            else:  # protontricks_radio (alternative)
                method = 'system_protontricks'

            old_method = self.config_handler.get('component_installation_method', 'winetricks')
            method_changed = (old_method != method)

            self.config_handler.set("component_installation_method", method)
            self.config_handler.set("use_winetricks_for_components", method == 'winetricks')

            # Force immediate save and verify
            save_result = self.config_handler.save_config()
            if not save_result:
                self.logger.error("Failed to save Proton configuration")
            else:
                self.logger.info(f"Saved Proton config: install_path={resolved_install_path}, game_path={resolved_game_path}")
                # Verify the save worked by reading it back
                saved_path = self.config_handler.get("proton_path")
                if saved_path != resolved_install_path:
                    self.logger.error(f"Config save verification failed: expected {resolved_install_path}, got {saved_path}")
                else:
                    self.logger.debug("Config save verified successfully")

            # Refresh cached paths in GUI screens if Jackify directory changed
            self._refresh_gui_paths()

            # Check if debug mode changed and prompt for restart
            new_debug_mode = self.debug_checkbox.isChecked()
            if new_debug_mode != self._original_debug_mode:
                reply = MessageService.question(self, "Restart Required", "Debug mode change requires a restart. Restart Jackify now?", safety_level="medium")
                if reply == QMessageBox.Yes:
                    import os, sys
                    # User requested restart - do it regardless of execution environment
                    self.accept()

                    # Check if running from AppImage
                    if os.environ.get('APPIMAGE'):
                        # AppImage: restart the AppImage
                        os.execv(os.environ['APPIMAGE'], [os.environ['APPIMAGE']] + sys.argv[1:])
                    else:
                        # Dev mode: restart the Python module
                        os.execv(sys.executable, [sys.executable, '-m', 'jackify.frontends.gui'] + sys.argv[1:])
                    return

            # If we get here, no restart was needed
            # Check protontricks if user just switched to it
            if method_changed and method == 'system_protontricks':
                main_window = self.parent()
                if main_window and hasattr(main_window, 'protontricks_service'):
                    is_installed, installation_type, details = main_window.protontricks_service.detect_protontricks(use_cache=False)
                    if not is_installed:
                        from jackify.frontends.gui.dialogs.protontricks_error_dialog import ProtontricksErrorDialog
                        dialog = ProtontricksErrorDialog(main_window.protontricks_service, main_window)
                        dialog.exec()

            MessageService.information(self, "Settings Saved", "Settings have been saved successfully.", safety_level="low")
            self.accept()

        except Exception as e:
            self.logger.error(f"Error saving settings: {e}")
            MessageService.warning(self, "Save Error", f"Failed to save settings: {e}", safety_level="medium")

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
            ]
            
            for screen in screens_to_refresh:
                if screen and hasattr(screen, 'refresh_paths'):
                    screen.refresh_paths()
                    
        except Exception as e:
            logger.warning(f"Could not refresh GUI paths: {e}")

    def _bold_label(self, text):
        label = QLabel(text)
        label.setStyleSheet("font-weight: bold; color: #fff;")
        return label
