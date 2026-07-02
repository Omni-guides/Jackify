"""Configuration phase workflow for InstallModlistScreen (Mixin)."""
import warnings
from PySide6.QtWidgets import QMessageBox, QProgressDialog
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from .screen_focus_reclaim import FocusReclaimMixin, STEAM_RESTART_SENTINEL
from PySide6.QtGui import QFont
from jackify.frontends.gui.services.message_service import MessageService
from jackify.shared.errors import manual_steps_incomplete, configuration_failed
from jackify.backend.handlers.validation_handler import ValidationHandler
from jackify.backend.models.modlist import ModlistContext
from pathlib import Path
import traceback
import os
import time
import logging

logger = logging.getLogger(__name__)
from .install_modlist_shortcut_dialog import InstallModlistShortcutDialogMixin

class ConfigurationPhaseMixin(FocusReclaimMixin, InstallModlistShortcutDialogMixin):
    """Mixin providing configuration phase workflow and dialog management for InstallModlistScreen."""

    def on_configuration_progress(self, progress_msg):
        """Handle progress updates from modlist configuration"""
        if not (progress_msg.startswith("[NATIVE_DL] ") or progress_msg.startswith("[NATIVE_INSTALL] ") or progress_msg.startswith("[NATIVE_WAIT] ")):
            self._safe_append_text(progress_msg)
        self._handle_post_install_progress(progress_msg)

    def show_steam_restart_progress(self, message):
        """Show Steam restart progress dialog"""
        self.steam_restart_progress = QProgressDialog(message, None, 0, 0, self)
        self.steam_restart_progress.setWindowTitle("Restarting Steam")
        self.steam_restart_progress.setWindowModality(Qt.WindowModal)
        self.steam_restart_progress.setMinimumDuration(0)
        self.steam_restart_progress.setValue(0)
        self.steam_restart_progress.show()

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
        pass

    def _detect_game_type_from_mo2_ini(self, install_dir: str) -> str:
        """Detect game type by checking ModOrganizer.ini for loader executables."""
        from pathlib import Path
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

    def on_configuration_complete(self, success, message, modlist_name, enb_detected=False):
        """Handle configuration completion on main thread"""
        try:
            install_dir = self.install_dir_edit.text().strip()
            # Stop CPU tracking now that everything is complete
            self.file_progress_list.stop_cpu_tracking()
            # Re-enable controls now that installation/configuration is complete
            self._enable_controls_after_operation()
            # Don't end post-install feedback yet - may continue with VNV automation
            # Will be called in _on_vnv_complete or after VNV check

            if success:
                # Check if we need to show Somnium guidance
                if self._show_somnium_guidance:
                    self._show_somnium_post_install_guidance()
                
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

                # Check for TTW eligibility before showing final success dialog
                ttw_modlist_name = modlist_name
                try:
                    from jackify.backend.utils.modlist_meta import get_modlist_name
                    canonical_name = get_modlist_name(install_dir)
                    if canonical_name:
                        ttw_modlist_name = canonical_name
                except Exception:
                    pass

                if self._check_ttw_eligibility(ttw_modlist_name, self._current_game_type, install_dir):
                    # Offer TTW installation
                    reply = MessageService.question(
                        self,
                        "Install TTW?",
                        f"{ttw_modlist_name} requires Tale of Two Wastelands!\n\n"
                        "Would you like to install TTW now?\n\n"
                        "This will:\n"
                        "• Guide you through TTW installation\n"
                        "• Attempt to integrate TTW into your modlist automatically\n"
                        "• Configure load order if integration is supported\n\n"
                        "Note: Automatic integration works for some modlists (like Begin Again). "
                        "Other modlists may require manual TTW setup. "
                        "TTW installation can take a while.\n\n"
                        "You can also install TTW later from Additional Tasks & Tools.",
                        critical=False,
                        safety_level="medium"
                    )

                    if reply == QMessageBox.Yes:
                        self._cleanup_config_thread()
                        # Navigate to TTW screen
                        self._initiate_ttw_workflow(ttw_modlist_name, install_dir)
                        return  # Don't show success dialog yet, will show after TTW completes

                # Check for VNV post-install automation after TTW check
                vnv_automation_running = self._check_and_run_vnv_automation(modlist_name, install_dir)

                if vnv_automation_running:
                    self._cleanup_config_thread()
                    self._pending_success_dialog_params = {
                        'modlist_name': modlist_name,
                        'workflow_type': "update" if getattr(self, "_is_update_install", False) else "install",
                        'time_taken': time_str,
                        'game_name': game_name,
                        'enb_detected': enb_detected,
                        'install_dir': install_dir,
                        'game_type': getattr(self, '_current_game_type', 'unknown') or 'unknown',
                        'appid': getattr(self, '_current_appid', '') or '',
                    }
                    return

                # No VNV automation - end post-install feedback now
                self._end_post_install_feedback(True)

                if getattr(self, "_is_update_install", False):
                    try:
                        self._verify_update_ini_after_configuration(install_dir)
                    except Exception as e:
                        logger.warning("Update mode verify: failed post-config INI verification: %s", e)

                workflow_type = "update" if getattr(self, "_is_update_install", False) else "install"
                game_type_for_verify = getattr(self, '_current_game_type', 'unknown') or 'unknown'
                self._run_verifier_then_show_success(
                    install_dir=install_dir,
                    game_type=game_type_for_verify,
                    success_params={
                        'modlist_name': modlist_name,
                        'workflow_type': workflow_type,
                        'time_taken': time_str,
                        'game_name': game_name,
                        'enb_detected': enb_detected,
                        'readme_url': getattr(self, '_readme_url', None),
                    },
                )
            elif hasattr(self, '_manual_steps_retry_count') and self._manual_steps_retry_count >= 3:
                # Max retries reached - show failure message
                self._end_post_install_feedback(False)
                MessageService.show_error(self, manual_steps_incomplete())
            else:
                # Configuration failed for other reasons
                self._end_post_install_feedback(False)
                MessageService.show_error(
                    self,
                    configuration_failed(
                        "Post-install configuration failed.",
                        context={
                            "operation": "install_modlist",
                            "step": "post_install_configuration",
                            "modlist_name": modlist_name,
                            "install_dir": install_dir,
                            "workflow_type": "update" if getattr(self, "_is_update_install", False) else "install",
                        },
                    ),
                )
        except Exception as e:
            # Ensure controls are re-enabled even on unexpected errors
            self._enable_controls_after_operation()
            raise
        self._cleanup_config_thread()

    def on_configuration_error(self, error_message):
        """Handle configuration error on main thread"""
        self._safe_append_text(f"Configuration failed with error: {error_message}")
        MessageService.show_error(
            self,
            configuration_failed(
                str(error_message),
                context={
                    "operation": "install_modlist",
                    "step": "post_install_configuration",
                    "modlist_name": self.modlist_name_edit.text().strip(),
                    "install_dir": self.install_dir_edit.text().strip(),
                    "workflow_type": "update" if getattr(self, "_is_update_install", False) else "install",
                },
            ),
        )

        # Re-enable all controls on error
        self._enable_controls_after_operation()

        self._cleanup_config_thread()

    def _cleanup_config_thread(self):
        """Safely stop and release the configuration worker thread."""
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
            self._safe_append_text("\nManual steps cancelled by user. Workflow stopped.")
            # Re-enable all controls when workflow is cancelled
            self._enable_controls_after_operation()
            self.cancel_btn.setVisible(True)
            self.cancel_install_btn.setVisible(False)

    def _get_mo2_path(self, install_dir, modlist_name):
        """Get ModOrganizer.exe path, handling Somnium's non-standard structure"""
        mo2_exe_path = os.path.join(install_dir, "ModOrganizer.exe")
        if not os.path.exists(mo2_exe_path) and "somnium" in modlist_name.lower():
            somnium_path = os.path.join(install_dir, "files", "ModOrganizer.exe")
            if os.path.exists(somnium_path):
                mo2_exe_path = somnium_path
        return mo2_exe_path

    def validate_manual_steps_completion(self):
        """Validate that manual steps were actually completed and handle retry logic"""
        modlist_name = self.modlist_name_edit.text().strip()
        install_dir = self.install_dir_edit.text().strip()
        mo2_exe_path = self._get_mo2_path(install_dir, modlist_name)
        
        # Add delay to allow Steam filesystem updates to complete
        logger.info("Waiting for Steam filesystem updates to complete...")
        time.sleep(2)
        
        # CRITICAL: Re-detect the AppID after Steam restart and manual steps
        # Steam assigns a NEW AppID during restart, different from the one we initially created
        logger.info(f"Re-detecting AppID for shortcut '{modlist_name}' after Steam restart...")
        from jackify.backend.handlers.shortcut_handler import ShortcutHandler
        from jackify.backend.services.platform_detection_service import PlatformDetectionService

        platform_service = PlatformDetectionService.get_instance()
        shortcut_handler = ShortcutHandler(steamdeck=platform_service.is_steamdeck)
        current_appid = shortcut_handler.get_appid_for_shortcut(modlist_name, mo2_exe_path)
        
        if not current_appid or not current_appid.isdigit():
            self._safe_append_text(f"Error: Could not find Steam-assigned AppID for shortcut '{modlist_name}'")
            self._safe_append_text("Error: This usually means the shortcut was not launched from Steam")
            self._safe_append_text("Suggestion: Check that Steam is running and shortcuts are visible in library")
            self.handle_validation_failure("Could not find Steam shortcut")
            return
        
        self._safe_append_text(f"Found Steam-assigned AppID: {current_appid}")
        logger.info(f"Validating manual steps completion for AppID: {current_appid}")
        
        # Check 1: Proton version
        proton_ok = False
        try:
            from jackify.backend.handlers.modlist_handler import ModlistHandler
            from jackify.backend.handlers.path_handler import PathHandler
            
            # Initialize ModlistHandler with correct parameters
            path_handler = PathHandler()

            # Use centralized Steam Deck detection
            platform_service = PlatformDetectionService.get_instance()

            modlist_handler = ModlistHandler(steamdeck=platform_service.is_steamdeck, verbose=False)
            
            # Set required properties manually after initialization
            modlist_handler.modlist_dir = install_dir
            modlist_handler.appid = current_appid
            modlist_handler.game_var = "skyrimspecialedition"  # Default for now
            
            # Set compat_data_path for Proton detection
            compat_data_path_str = path_handler.find_compat_data(current_appid)
            if compat_data_path_str:
                modlist_handler.compat_data_path = Path(compat_data_path_str)
            
            # Check Proton version
            logger.info(f"Attempting to detect Proton version for AppID {current_appid}...")
            if modlist_handler._detect_proton_version():
                logger.info(f"Raw detected Proton version: '{modlist_handler.proton_ver}'")
                if modlist_handler.proton_ver and 'experimental' in modlist_handler.proton_ver.lower():
                    proton_ok = True
                    logger.info(f"Proton version validated: {modlist_handler.proton_ver}")
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
            
            logger.info(f"Searching for compatdata directory for AppID {current_appid}...")
            logger.info("Checking standard Steam locations and Flatpak Steam...")
            prefix_path_str = path_handler.find_compat_data(current_appid)
            logger.info(f"Compatdata search result: '{prefix_path_str}'")
            
            if prefix_path_str and os.path.isdir(prefix_path_str):
                compatdata_ok = True
                logger.info(f"Compatdata directory found: {prefix_path_str}")
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
            logger.info("Continuing configuration with updated AppID...")
            
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
        # Headers are now shown at start of Steam Integration
        # No need to show them again here
        logger.debug("Configuration phase continues after Steam Integration")
        
        logger.debug(f"continue_configuration_after_automated_prefix called with appid: {new_appid}")
        try:
            # Update the context with the new AppID (same format as manual steps)
            updated_context = {
                'name': modlist_name,
                'path': install_dir,
                'mo2_exe_path': self._get_mo2_path(install_dir, modlist_name),
                'modlist_value': None,
                'modlist_source': None,
                'resolution': getattr(self, '_current_resolution', None),
                'skip_confirmation': True,
                'appid': new_appid,
                'game_name': self.context.get('game_name', 'Skyrim Special Edition') if hasattr(self, 'context') else 'Skyrim Special Edition'
            }
            self.context = updated_context  # Ensure context is always set
            logger.debug(f"Updated context with new AppID: {new_appid}")
            
            # Get Steam Deck detection once and pass to ConfigThread
            from jackify.backend.services.platform_detection_service import PlatformDetectionService
            platform_service = PlatformDetectionService.get_instance()
            is_steamdeck = platform_service.is_steamdeck

            # Create new config thread with updated context
            # Capture parent's method for game type detection
            detect_game_type_func = self._detect_game_type_from_mo2_ini
            
            class ConfigThread(QThread):
                progress_update = Signal(str)
                configuration_complete = Signal(bool, str, str, bool)
                error_occurred = Signal(str)

                def __init__(self, context, is_steamdeck, detect_func):
                    super().__init__()
                    self.context = context
                    self.is_steamdeck = is_steamdeck
                    self.detect_game_type = detect_func
                
                def run(self):
                    try:
                        from jackify.backend.services.modlist_service import ModlistService
                        from jackify.backend.models.configuration import SystemInfo
                        from jackify.backend.models.modlist import ModlistContext
                        
                        # Initialize backend service with passed Steam Deck detection
                        system_info = SystemInfo(is_steamdeck=self.is_steamdeck)
                        modlist_service = ModlistService(system_info)
                        
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
                            resolution=self.context.get('resolution'),
                            skip_confirmation=True,
                            engine_installed=True  # Skip path manipulation for engine workflows
                        )
                        
                        # Add app_id to context
                        modlist_context.app_id = self.context['appid']
                        
                        # Define callbacks
                        def progress_callback(message):
                            self.progress_update.emit(message)
                            
                        def completion_callback(success, message, modlist_name, enb_detected=False):
                            self.configuration_complete.emit(success, message, modlist_name, enb_detected)
                            
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
            self.config_thread = ConfigThread(updated_context, is_steamdeck, detect_game_type_func)
            self.config_thread.progress_update.connect(self.on_configuration_progress)
            self.config_thread.configuration_complete.connect(self.on_configuration_complete)
            self.config_thread.error_occurred.connect(self.on_configuration_error)
            self.config_thread.start()
            
        except Exception as e:
            self._safe_append_text(f"Error continuing configuration: {e}")
            self._safe_append_text(f"Full traceback: {traceback.format_exc()}")
            self.on_configuration_error(str(e))

    def continue_configuration_after_manual_steps(self, new_appid, modlist_name, install_dir):
        """Continue the configuration process with the corrected AppID after manual steps validation"""
        try:
            # Update the context with the new AppID
            updated_context = {
                'name': modlist_name,
                'path': install_dir,
                'mo2_exe_path': self._get_mo2_path(install_dir, modlist_name),
                'modlist_value': None,
                'modlist_source': None,
                'resolution': getattr(self, '_current_resolution', None),
                'skip_confirmation': True,
                'appid': new_appid

            }
            
            logger.debug(f"Updated context with new AppID: {new_appid}")
            
            # Clean up old thread if exists and wait for it to finish
            if hasattr(self, 'config_thread') and self.config_thread is not None:
                # Disconnect all signals to prevent "Internal C++ object already deleted" errors
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", RuntimeWarning)
                    try:
                        self.config_thread.progress_update.disconnect()
                        self.config_thread.configuration_complete.disconnect()
                        self.config_thread.error_occurred.disconnect()
                    except (RuntimeError, TypeError):
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
        # Get Steam Deck detection once
        from jackify.backend.services.platform_detection_service import PlatformDetectionService
        platform_service = PlatformDetectionService.get_instance()
        is_steamdeck = platform_service.is_steamdeck

        # Capture parent's method for game type detection
        detect_game_type_func = self._detect_game_type_from_mo2_ini

        class ConfigThread(QThread):
            progress_update = Signal(str)
            configuration_complete = Signal(bool, str, str)
            error_occurred = Signal(str)

            def __init__(self, context, is_steamdeck, detect_func, parent=None):
                super().__init__(parent)
                self.context = context
                self.is_steamdeck = is_steamdeck
                self.detect_game_type = detect_func
                
            def run(self):
                try:
                    from jackify.backend.models.configuration import SystemInfo
                    from jackify.backend.services.modlist_service import ModlistService
                    from jackify.backend.models.modlist import ModlistContext
                    
                    # Initialize backend service with passed Steam Deck detection
                    system_info = SystemInfo(is_steamdeck=self.is_steamdeck)
                    modlist_service = ModlistService(system_info)
                    
                    # Detect game type from ModOrganizer.ini using captured function
                    detected_game_type = self.detect_game_type(self.context['path'])
                    
                    # Convert context to ModlistContext for service
                    modlist_context = ModlistContext(
                        name=self.context['name'],
                        install_dir=Path(self.context['path']),
                        download_dir=None,
                        game_type=detected_game_type,
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
                        
                    result = modlist_service.configure_modlist_post_steam(
                        context=modlist_context,
                        progress_callback=progress_callback,
                        completion_callback=completion_callback
                    )
                    
                    if not result:
                        self.progress_update.emit("WARNING: configure_modlist_post_steam returned False")
                    
                except Exception as e:
                    error_details = f"Error in configuration: {e}\nTraceback: {traceback.format_exc()}"
                    self.progress_update.emit(f"ERROR: {error_details}")
                    self.error_occurred.emit(str(e))
        
        return ConfigThread(context, is_steamdeck, detect_game_type_func, parent=self)
