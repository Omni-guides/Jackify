"""Workflow management for ConfigureNewModlistScreen (Mixin)."""
from pathlib import Path
from PySide6.QtCore import QThread, Signal
import os
import time
import logging
import warnings
from jackify.shared.resolution_utils import get_resolution_fallback
from jackify.shared.errors import configuration_failed
from jackify.backend.services.steam_restart_service import ensure_flatpak_steam_filesystem_access

logger = logging.getLogger(__name__)

class ConfigureNewModlistWorkflowMixin:
    """Mixin providing workflow management for ConfigureNewModlistScreen."""

    def _detect_game_type_from_mo2_ini(self, install_dir: str) -> str:
        """Detect game type by checking ModOrganizer.ini for loader executables."""
        from pathlib import Path

        # Enderal and FNV run on the Skyrim/FO3 engine and share its loader
        # executables (skse64_loader.exe, etc.), so they must be identified before
        # the generic engine keyword scan below or they always get misdetected as
        # skyrim/fallout3.
        try:
            from jackify.backend.handlers.modlist_handler import ModlistHandler
            special = ModlistHandler().detect_special_game_type(install_dir)
            if special == 'fnv':
                return 'falloutnv'
            if special:
                return special
        except Exception as e:
            logger.warning(f"Special game type detection failed: {e}")

        mo2_ini = Path(install_dir) / "ModOrganizer.ini"
        if not mo2_ini.exists():
            return 'skyrim'  # Fallback to most common

        try:
            content = mo2_ini.read_text(encoding='utf-8', errors='ignore').lower()

            if 'skse64_loader.exe' in content or 'skyrim special edition' in content:
                return 'skyrim'
            elif 'f4se_loader.exe' in content or 'fallout 4' in content:
                return 'fallout4'
            elif 'nvse_loader.exe' in content or 'fallout new vegas' in content:
                return 'falloutnv'
            elif 'fose_loader.exe' in content or 'fallout 3' in content:
                return 'fallout3'
            elif 'obse_loader.exe' in content or 'oblivion' in content:
                return 'oblivion'
            elif 'starfield' in content:
                return 'starfield'
            elif 'enderal' in content:
                return 'enderal'
            else:
                return 'skyrim'
        except Exception as e:
            logger.warning(f"Error detecting game type from ModOrganizer.ini: {e}")
            return 'skyrim'

    def validate_and_start_configure(self):
        # Reload config to pick up any settings changes made in Settings dialog
        self.config_handler.reload_config()

        # Check protontricks before proceeding
        if not self._check_protontricks():
            return
        
        # Rotate log file at start of each workflow run (keep 5 backups)
        from jackify.backend.handlers.logging_handler import LoggingHandler
        from pathlib import Path
        log_handler = LoggingHandler()
        log_handler.rotate_log_file_per_run(Path(self.modlist_log_path), backup_count=5)
        
        # Validate ModOrganizer.exe path
        mo2_path = self.install_dir_edit.text().strip()
        from jackify.frontends.gui.services.message_service import MessageService
        if not mo2_path:
            MessageService.warning(self, "Missing Path", "Please specify the path to ModOrganizer.exe", safety_level="low")
            return
        if not os.path.isfile(mo2_path):
            MessageService.warning(self, "Invalid Path", "The specified path does not point to a valid file", safety_level="low")
            return
        if not mo2_path.endswith('ModOrganizer.exe'):
            MessageService.warning(self, "Invalid File", "The specified file is not ModOrganizer.exe", safety_level="low")
            return
        
        # Start time tracking
        self._workflow_start_time = time.time()

        # Initialize progress indicator
        self.progress_indicator.set_status("Preparing to configure...", 0)

        # Start CPU tracking
        self.file_progress_list.start_cpu_tracking()

        # Disable controls during configuration (after validation passes)
        self._disable_controls_during_operation()
        
        # Validate modlist name
        modlist_name = self.modlist_name_edit.text().strip()
        if not modlist_name:
            MessageService.warning(self, "Missing Name", "Please specify a name for your modlist", safety_level="low")
            self._enable_controls_after_operation()
            return
        
        # Handle resolution saving
        resolution = self.resolution_combo.currentText()
        if resolution and resolution != "Leave unchanged":
            success = self.resolution_service.save_resolution(resolution)
            if success:
                logger.debug(f"Resolution saved successfully: {resolution}")
            else:
                logger.debug("Failed to save resolution")
        else:
            # Clear saved resolution if "Leave unchanged" is selected
            if self.resolution_service.has_saved_resolution():
                self.resolution_service.clear_saved_resolution()
                logger.debug("Saved resolution cleared")
        
        # Start configuration - automated workflow handles Steam restart internally
        self.configure_modlist()

    def configure_modlist(self):
        # Reload config from disk to pick up any settings changes from Settings dialog
        # Refresh Proton version and winetricks settings
        self.config_handler._load_config()

        _raw_mo2_path = os.path.realpath(self.install_dir_edit.text().strip())
        install_dir = os.path.dirname(_raw_mo2_path) if _raw_mo2_path.endswith('ModOrganizer.exe') else _raw_mo2_path
        modlist_name = self.modlist_name_edit.text().strip()
        mo2_exe_path = _raw_mo2_path
        resolution = self.resolution_combo.currentText()
        if not install_dir or not modlist_name:
            MessageService.warning(self, "Missing Info", "Install directory or modlist name is missing.", safety_level="low")
            return

        # Use automated prefix service instead of manual steps
        self._safe_append_text("")
        self._safe_append_text("=== Steam Integration Phase ===")
        logger.info("Starting automated Steam setup workflow...")

        # Start automated prefix workflow
        self._start_automated_prefix_workflow(modlist_name, install_dir, mo2_exe_path, resolution)

    def _start_automated_prefix_workflow(self, modlist_name, install_dir, mo2_exe_path, resolution):
        """Start the automated prefix workflow using AutomatedPrefixService in a background thread"""
        ensure_flatpak_steam_filesystem_access(Path(install_dir))
        from jackify import __version__ as jackify_version
        logger.info("Jackify v%s", jackify_version)
        logger.info("Initialising automated Steam setup for '%s'...", modlist_name)
        logger.info("Starting automated Steam shortcut creation and configuration...")
        
        # Disable the start button to prevent multiple workflows
        self.start_btn.setEnabled(False)
        
        # Create and start the automated prefix thread
        class AutomatedPrefixThread(QThread):
            progress_update = Signal(str)
            workflow_complete = Signal(object)  # Will emit the result tuple
            error_occurred = Signal(object)  # error (JackifyError or str)
            def __init__(self, modlist_name, install_dir, mo2_exe_path, steamdeck, auto_restart):
                super().__init__()
                self.modlist_name = modlist_name
                self.install_dir = install_dir
                self.mo2_exe_path = mo2_exe_path
                self.steamdeck = steamdeck
                self.auto_restart = auto_restart

            def run(self):
                try:
                    from jackify.backend.services.automated_prefix_service import AutomatedPrefixService

                    prefix_service = AutomatedPrefixService()

                    def progress_callback(message):
                        self.progress_update.emit(message)

                    from jackify.backend.services.nxm_downloader import resolve_mo2_download_dir
                    download_dir = resolve_mo2_download_dir(Path(self.install_dir))

                    result = prefix_service.run_working_workflow(
                        self.modlist_name, self.install_dir, self.mo2_exe_path,
                        progress_callback, steamdeck=self.steamdeck, auto_restart=self.auto_restart,
                        download_dir=download_dir,
                    )

                    self.workflow_complete.emit(result)

                except Exception as e:
                    from jackify.shared.errors import JackifyError, prefix_creation_failed
                    if not isinstance(e, JackifyError):
                        e = prefix_creation_failed(str(e))
                    self.error_occurred.emit(e)
        
        # Detect Steam Deck once using centralized service
        from jackify.backend.services.platform_detection_service import PlatformDetectionService
        platform_service = PlatformDetectionService.get_instance()
        _is_steamdeck = platform_service.is_steamdeck

        # Decide whether to restart Steam: checkbox checked = yes; unchecked = ask (only skip if user clicks No)
        from PySide6.QtWidgets import QMessageBox
        from jackify.frontends.gui.services.message_service import MessageService

        auto_restart = self.auto_restart_checkbox.isChecked()
        if not auto_restart:
            reply = MessageService.question(
                self,
                "Restart Steam?",
                "Steam will need to restart to detect the new shortcut. Do you want Jackify to restart Steam when the time comes?",
                safety_level="medium"
            )
            # Only skip restart when user explicitly clicks No; treat Yes or dialog close as restart
            auto_restart = reply != QMessageBox.No

        logger.info("Configure New Modlist: starting automated prefix workflow with auto_restart=%s", auto_restart)

        # Create and start the thread
        self.automated_prefix_thread = AutomatedPrefixThread(modlist_name, install_dir, mo2_exe_path, _is_steamdeck, auto_restart)
        self.automated_prefix_thread.progress_update.connect(self._handle_progress_update)
        self.automated_prefix_thread.workflow_complete.connect(self._on_automated_prefix_complete)
        self.automated_prefix_thread.error_occurred.connect(self._on_automated_prefix_error)
        self.automated_prefix_thread.start()

    def _on_automated_prefix_complete(self, result):
        """Handle completion of the automated prefix workflow"""
        try:
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
                        self.continue_configuration_after_automated_prefix(new_appid, self.modlist_name_edit.text().strip(), 
                                                                         os.path.dirname(self.install_dir_edit.text().strip()) if self.install_dir_edit.text().strip().endswith('ModOrganizer.exe') else self.install_dir_edit.text().strip(), 
                                                                         last_timestamp)
                    else:
                        error_reason = last_timestamp or "Unknown error"
                        self._safe_append_text(f"Automated Steam setup failed: {error_reason}")
                        self.start_btn.setEnabled(True)
            elif isinstance(result, tuple) and len(result) == 3:
                # Fallback for old format (backward compatibility)
                success, prefix_path, new_appid = result
                if success:
                    self._safe_append_text(f"Automated Steam setup completed successfully!")
                    self._safe_append_text(f"New AppID assigned: {new_appid}")

                    # Continue with post-Steam configuration
                    self.continue_configuration_after_automated_prefix(new_appid, self.modlist_name_edit.text().strip(),
                                                                     os.path.dirname(self.install_dir_edit.text().strip()) if self.install_dir_edit.text().strip().endswith('ModOrganizer.exe') else self.install_dir_edit.text().strip())
                else:
                    self._safe_append_text(f"Automated Steam setup failed")
                    self.start_btn.setEnabled(True)
            else:
                # Handle unexpected result format
                self._safe_append_text(f"Automated Steam setup failed - unexpected result format")
                self.start_btn.setEnabled(True)
                
        except Exception as e:
            logger.error("Error handling automated prefix result: %s", e)
            self._safe_append_text(f"Error handling automated prefix result: {str(e)}")
            self.start_btn.setEnabled(True)
        finally:
            self._cleanup_automated_prefix_thread()

    def _cleanup_automated_prefix_thread(self):
        """Safely release the automated prefix thread after it has finished."""
        if not hasattr(self, 'automated_prefix_thread') or self.automated_prefix_thread is None:
            return
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            try:
                self.automated_prefix_thread.progress_update.disconnect()
                self.automated_prefix_thread.workflow_complete.disconnect()
                self.automated_prefix_thread.error_occurred.disconnect()
            except (RuntimeError, TypeError):
                pass
        if self.automated_prefix_thread.isRunning():
            self.automated_prefix_thread.quit()
            self.automated_prefix_thread.wait(5000)
        self.automated_prefix_thread.deleteLater()
        self.automated_prefix_thread = None

    def _on_automated_prefix_error(self, error):
        """Handle error from the automated prefix workflow"""
        from jackify.shared.errors import JackifyError, classify_exception
        from jackify.frontends.gui.services.message_service import MessageService
        if not isinstance(error, JackifyError):
            error = classify_exception(str(error))
        logger.error(f"Automated prefix error: {error.message}")
        self._safe_append_text(f"[FAILED] {error.message}")
        MessageService.show_error(self, error)
        self._enable_controls_after_operation()
        self._cleanup_automated_prefix_thread()

    def continue_configuration_after_automated_prefix(self, new_appid, modlist_name, install_dir, last_timestamp=None):
        """Continue the configuration process with the new AppID after automated prefix creation"""
        # Headers are now shown at start of Steam Integration
        # No need to show them again here
        logger.debug("Configuration phase continues after Steam Integration")
        
        logger.debug(f"continue_configuration_after_automated_prefix called with appid: {new_appid}")
        try:
            # Get resolution from UI
            resolution = self.resolution_combo.currentText()
            resolution_value = resolution.split()[0] if resolution != "Leave unchanged" else None
            
            # Update the context with the new AppID (same format as manual steps)
            mo2_exe_path = self.install_dir_edit.text().strip()
            updated_context = {
                'name': modlist_name,
                'path': install_dir,
                'mo2_exe_path': mo2_exe_path,
                'modlist_value': None,
                'modlist_source': None,
                'resolution': resolution_value,
                'skip_confirmation': True,
                'appid': new_appid,
                'game_name': 'Skyrim Special Edition'  # Default for new modlist
            }
            self.context = updated_context  # Ensure context is always set
            logger.debug(f"Updated context with new AppID: {new_appid}")
            
            # Create new config thread with updated context
            from PySide6.QtCore import QThread, Signal
            
            # Capture parent's method and system_info
            detect_game_type_func = self._detect_game_type_from_mo2_ini
            parent_system_info = self.system_info
            
            class ConfigThread(QThread):
                progress_update = Signal(str)
                configuration_complete = Signal(bool, str, str, bool)
                error_occurred = Signal(str)
                
                def __init__(self, context, system_info, detect_func):
                    super().__init__()
                    self.context = context
                    self.system_info = system_info
                    self.detect_game_type = detect_func
                
                def run(self):
                    try:
                        from jackify.backend.services.modlist_service import ModlistService
                        from jackify.backend.models.modlist import ModlistContext
                        from pathlib import Path
                        
                        # Initialize backend service
                        modlist_service = ModlistService(self.system_info)
                        
                        # Detect game type from ModOrganizer.ini using captured function
                        detected_game_type = self.detect_game_type(self.context['path'])
                        
                        # Convert context to ModlistContext for service
                        modlist_context = ModlistContext(
                            name=self.context['name'],
                            install_dir=Path(self.context['path']),
                            download_dir=None,
                            game_type=detected_game_type,
                            nexus_api_key='',  # Not needed for configuration
                            modlist_value=self.context.get('modlist_value'),
                            modlist_source=self.context.get('modlist_source', 'identifier'),
                            resolution=self.context.get('resolution') or get_resolution_fallback(None),
                            skip_confirmation=True
                        )
                        
                        # Add app_id to context
                        modlist_context.app_id = self.context['appid']
                        
                        # Define callbacks
                        def progress_callback(message):
                            self.progress_update.emit(message)
                            
                        def completion_callback(success, message, modlist_name, enb_detected=False):
                            self.configuration_complete.emit(success, message, modlist_name, enb_detected)
                            
                        self.progress_update.emit("")
                        self.progress_update.emit("=== Configuration Phase ===")
                        self.progress_update.emit("")
                        self.progress_update.emit("Starting modlist configuration...")
                        result = modlist_service.configure_modlist_post_steam(
                            context=modlist_context,
                            progress_callback=progress_callback,
                            completion_callback=completion_callback
                        )
                        
                        if not result:
                            self.progress_update.emit("Configuration failed to start")
                            self.error_occurred.emit("Configuration failed to start")
                            
                    except Exception as e:
                        self.error_occurred.emit(str(e))
            
            # Start configuration thread
            self.config_thread = ConfigThread(updated_context, parent_system_info, detect_game_type_func)
            self.config_thread.progress_update.connect(self._handle_progress_update)
            self.config_thread.configuration_complete.connect(self.on_configuration_complete)
            self.config_thread.error_occurred.connect(self.on_configuration_error)
            self.config_thread.start()
            
        except Exception as e:
            logger.error("Error continuing configuration: %s", e, exc_info=True)
            self._safe_append_text(f"Error continuing configuration: {e}")
            self.on_configuration_error(str(e))

    def continue_configuration_after_manual_steps(self, new_appid, modlist_name, install_dir):
        """Continue the configuration process with the corrected AppID after manual steps validation"""
        try:
            # Update the context with the new AppID
            mo2_exe_path = self.install_dir_edit.text().strip()
            resolution = self.resolution_combo.currentText()
            
            updated_context = {
                'name': modlist_name,
                'path': install_dir,
                'mo2_exe_path': mo2_exe_path,
                'resolution': resolution.split()[0] if resolution != "Leave unchanged" else None,
                'skip_confirmation': True,
                'appid': new_appid,
                'game_name': 'Skyrim Special Edition'  # Default for new modlist
            }
            logger.debug(f"Updated context with new AppID: {new_appid}")
            
            # Create new config thread with updated context (same as Tuxborn)
            from PySide6.QtCore import QThread, Signal
            
            # Capture parent's method and system_info
            detect_game_type_func = self._detect_game_type_from_mo2_ini
            parent_system_info = self.system_info
            
            class ConfigThread(QThread):
                progress_update = Signal(str)
                configuration_complete = Signal(bool, str, str, bool)
                error_occurred = Signal(str)
                
                def __init__(self, context, system_info, detect_func):
                    super().__init__()
                    self.context = context
                    self.system_info = system_info
                    self.detect_game_type = detect_func
                    
                def run(self):
                    try:
                        from jackify.backend.services.modlist_service import ModlistService
                        from jackify.backend.models.modlist import ModlistContext
                        from pathlib import Path
                        
                        # Initialize backend service
                        modlist_service = ModlistService(self.system_info)
                        
                        # Detect game type from ModOrganizer.ini using captured function
                        detected_game_type = self.detect_game_type(self.context['path'])
                        
                        # Convert context to ModlistContext for service
                        modlist_context = ModlistContext(
                            name=self.context['name'],
                            install_dir=Path(self.context['path']),
                            download_dir=None,
                            game_type=detected_game_type,
                            nexus_api_key='',  # Not needed for configuration
                            modlist_value='',  # Not needed for existing modlist
                            modlist_source='existing',
                            resolution=self.context.get('resolution') or get_resolution_fallback(None),
                            skip_confirmation=True
                        )
                        
                        # Add app_id to context
                        if 'appid' in self.context:
                            modlist_context.app_id = self.context['appid']
                        
                        # Define callbacks
                        def progress_callback(message):
                            self.progress_update.emit(message)
                            
                        def completion_callback(success, message, modlist_name, enb_detected=False):
                            self.configuration_complete.emit(success, message, modlist_name, enb_detected)
                            
                        self.progress_update.emit("Starting configuration with backend service...")

                        success = modlist_service.configure_modlist_post_steam(
                            context=modlist_context,
                            progress_callback=progress_callback,
                            completion_callback=completion_callback
                        )
                        
                        if not success:
                            self.error_occurred.emit(
                                "Configuration did not complete successfully. "
                                "Review the latest workflow output above for the failing step."
                            )
                            
                    except Exception as e:
                        import traceback
                        error_msg = f"Configuration error: {e}\n{traceback.format_exc()}"
                        self.error_occurred.emit(error_msg)
            
            # Create and start the configuration thread
            self.config_thread = ConfigThread(updated_context, parent_system_info, detect_game_type_func)
            self.config_thread.progress_update.connect(self._handle_progress_update)
            self.config_thread.configuration_complete.connect(self.on_configuration_complete)
            self.config_thread.error_occurred.connect(self.on_configuration_error)
            self.config_thread.start()
            
        except Exception as e:
            logger.error("Error continuing configuration: %s", e, exc_info=True)
            self._safe_append_text(f"Error continuing configuration: {e}")
            MessageService.show_error(self, configuration_failed(str(e)))

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
