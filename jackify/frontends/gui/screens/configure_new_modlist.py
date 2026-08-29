"""
ConfigureNewModlistScreen for Jackify GUI
"""
import logging
from pathlib import Path
import warnings
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QComboBox, QHBoxLayout, QLineEdit, QPushButton, QGridLayout, QFileDialog, QTextEdit, QSizePolicy, QTabWidget, QDialog, QListWidget, QListWidgetItem, QMessageBox, QProgressDialog, QCheckBox, QMainWindow
from PySide6.QtCore import Qt, QSize, QThread, Signal, QTimer, QProcess, QMetaObject
from PySide6.QtGui import QPixmap, QTextCursor
from ..shared_theme import JACKIFY_COLOR_BLUE
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
from PySide6.QtWidgets import QApplication
from jackify.frontends.gui.services.message_service import MessageService
from jackify.shared.resolution_utils import get_resolution_fallback
from jackify.shared.errors import configuration_failed
from .configure_new_modlist_ui_setup import ConfigureNewModlistUISetupMixin
from .configure_new_modlist_console import ConfigureNewModlistConsoleMixin
from .configure_new_modlist_workflow import ConfigureNewModlistWorkflowMixin
from .configure_new_modlist_dialogs import ConfigureNewModlistDialogsMixin, ModlistFetchThread, SelectionDialog
from .screen_back_mixin import ScreenBackMixin
from .install_modlist_ttw import TTWIntegrationMixin
from .install_modlist_postinstall import PostInstallFeedbackMixin
from .install_verifier_mixin import InstallVerifierMixin
from .playbook_automation_mixin import PlaybookAutomationMixin
from jackify.frontends.gui.mixins.thread_lifecycle_mixin import ThreadLifecycleMixin

logger = logging.getLogger(__name__)

class ConfigureNewModlistScreen(ThreadLifecycleMixin, ScreenBackMixin, TTWIntegrationMixin, InstallVerifierMixin, ConfigureNewModlistUISetupMixin, ConfigureNewModlistConsoleMixin, ConfigureNewModlistWorkflowMixin, ConfigureNewModlistDialogsMixin, PostInstallFeedbackMixin, PlaybookAutomationMixin, QWidget):
    resize_request = Signal(str)

    def request_prefill(self, modlist_name: str, install_dir: str) -> None:
        """Pre-fill name and exe path from the registry, for the Dashboard's Reconfigure on a
        modlist with no prefix."""
        try:
            if modlist_name:
                self.modlist_name_edit.setText(modlist_name)
            if not install_dir:
                return
            exe = Path(install_dir) / "ModOrganizer.exe"
            self.install_dir_edit.setText(str(exe) if exe.is_file() else install_dir)
        except Exception as e:
            logger.debug("Configure New prefill skipped: %s", e)

    def cancel_and_cleanup(self):
        """Handle Cancel button - clean up processes and go back"""
        if getattr(self, '_playbook_controller', None) is not None:
            self._playbook_controller.cleanup()
            self._playbook_controller = None
        appid = str(getattr(self, 'context', {}).get('appid', '') or '')
        self._kill_prefix_wine_processes(appid)
        self.cleanup_processes()
        self.collapse_show_details_before_leave()
        self.go_back()

    def showEvent(self, event):
        """Called when the widget becomes visible - ensure collapsed state"""
        super().showEvent(event)
        self.force_collapsed_details_state()

    def on_configuration_complete(self, success, message, modlist_name, enb_detected=False):
        """Handle configuration completion (same as Tuxborn)"""
        # Re-enable all controls when workflow completes
        self._enable_controls_after_operation()

        if success:
            raw = self.install_dir_edit.text().strip()
            install_dir = os.path.dirname(raw) if raw.endswith('ModOrganizer.exe') else raw

            if install_dir:
                game_type = self._detect_game_type_from_mo2_ini(install_dir)
                if game_type in ('falloutnv', 'fallout_new_vegas'):
                    from jackify.backend.utils.modlist_meta import get_modlist_name
                    identified_name = get_modlist_name(install_dir)
                    if identified_name and self._check_ttw_eligibility(identified_name, game_type, install_dir):
                        self._cleanup_config_thread()
                        self._initiate_ttw_workflow(identified_name, install_dir)
                        return

            # Check for modlist post-install fixes (playbooks - VNV, MEW, etc.) after configuration
            if install_dir and self._check_and_run_playbook_automation(
                modlist_name, install_dir,
                appid=getattr(self, '_current_appid', None), game_type=game_type,
            ):
                self._pending_success_dialog_params = {
                    'modlist_name': modlist_name,
                    'workflow_type': 'configure_new',
                    'time_taken': self._calculate_time_taken(),
                    'game_name': getattr(self, '_current_game_name', None),
                    'enb_detected': enb_detected,
                    'install_dir': install_dir,
                    'game_type': game_type,
                    'appid': getattr(self, '_current_appid', '') or '',
                }
                return

            # Calculate time taken
            time_taken = self._calculate_time_taken()

            game_type = self._detect_game_type_from_mo2_ini(install_dir) if install_dir else "unknown"
            self._run_verifier_then_show_success(
                install_dir=install_dir or "",
                game_type=game_type,
                success_params={
                    'modlist_name': modlist_name,
                    'workflow_type': 'configure_new',
                    'time_taken': time_taken,
                    'game_name': getattr(self, '_current_game_name', None),
                    'enb_detected': enb_detected,
                    'playbook_warnings': list(getattr(self._playbook_controller, 'last_failure_notices', None) or []) if hasattr(self, '_playbook_controller') else [],
                },
            )
        else:
            self._safe_append_text(f"Configuration failed: {message}")
            MessageService.show_error(self, configuration_failed(str(message)))
        self._cleanup_config_thread()
    
    def on_configuration_error(self, error_message):
        """Handle configuration error"""
        # Re-enable all controls on error
        self._enable_controls_after_operation()
        
        self._safe_append_text(f"Configuration error: {error_message}")
        MessageService.show_error(self, configuration_failed(str(error_message)))
        self._cleanup_config_thread()

    def _cleanup_config_thread(self):
        """Safely stop and release configuration thread."""
        if not hasattr(self, 'config_thread') or self.config_thread is None:
            return

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            try:
                self.config_thread.progress_update.disconnect()
                self.config_thread.configuration_complete.disconnect()
                self.config_thread.error_occurred.disconnect()
            except (RuntimeError, TypeError):
                pass

        if self.config_thread.isRunning():
            self.config_thread.quit()
            self.config_thread.wait(5000)

        self.config_thread.deleteLater()
        self.config_thread = None

    def reset_screen_to_defaults(self):
        """Reset the screen to default state when navigating back from main menu"""
        # Reset form fields
        self.install_dir_edit.setText("/path/to/Modlist/ModOrganizer.exe")

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
        self.force_collapsed_details_state()

    def cleanup(self):
        """Clean up any running threads when the screen is closed"""
        if getattr(self, '_playbook_controller', None) is not None:
            self._playbook_controller.cleanup()
            self._playbook_controller = None
        self._park_all_threads()
