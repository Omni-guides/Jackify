"""Pre-install validation step methods for InstallModlistScreen (Mixin).

Each step takes the shared ctx dict built up by validate_and_start_install
(install_modlist_workflow_execution.py), mutates it in place, and returns
False if it already handled its own abort (dialog shown, controls re-enabled).
"""

from pathlib import Path
from PySide6.QtWidgets import QMessageBox
import logging
import os

from jackify.backend.services.steam_restart_service import ensure_flatpak_steam_filesystem_access
from jackify.backend.models.game_types import GAME_DISPLAY_NAMES, GAME_NAME_TO_TYPE
from jackify.shared.errors import install_dir_create_failed

logger = logging.getLogger(__name__)


class InstallWorkflowValidationMixin:
    """Mixin providing validate_and_start_install's extracted step methods."""

    def _resolve_install_source(self, ctx: dict) -> bool:
        """Resolve install/downloads dirs and modlist source. Returns False if aborted."""
        install_dir = self.install_dir_edit.text().strip()
        downloads_dir = self.downloads_dir_edit.text().strip()

        if self._session_engine_id() == "clf3" and not self._ensure_clf3_installed():
            self.progress_indicator.reset()
            self._enable_controls_after_operation()
            return False

        tab_index = self.source_tabs.currentIndex()
        install_mode = 'online'
        if tab_index == 1:  # .wabbajack File tab
            modlist = self.file_edit.text().strip()
            if not modlist or not os.path.isfile(modlist) or not modlist.endswith('.wabbajack'):
                self._abort_with_message(
                    "warning",
                    "Invalid Modlist",
                    "Please select a valid .wabbajack file."
                )
                return False
            install_mode = 'file'
        else:
            # For online modlists, ALWAYS use machine_url from selected_modlist_info
            # Button text is now the display name (title), NOT the machine URL
            if not hasattr(self, 'selected_modlist_info') or not self.selected_modlist_info:
                self._abort_with_message(
                    "warning",
                    "Invalid Modlist",
                    "Modlist information is missing. Please select the modlist again from the gallery."
                )
                return False

            machine_url = self.selected_modlist_info.get('machine_url')
            if not machine_url:
                self._abort_with_message(
                    "warning",
                    "Invalid Modlist",
                    "Modlist information is incomplete. Please select the modlist again from the gallery."
                )
                return False

            # Use machine_url, NOT button text
            modlist = machine_url

            if self._session_engine_id() == "clf3":
                download_url = self.selected_modlist_info.get('download_url')
                if not download_url:
                    self._abort_with_message(
                        "warning",
                        "Download URL Unavailable",
                        "Could not determine the download URL for this modlist.\n\n"
                        "Use the '.wabbajack File' tab to select a local file instead."
                    )
                    return False
                from jackify.shared.paths import get_jackify_downloads_dir
                list_id = machine_url.split('/')[-1] if '/' in machine_url else machine_url
                wabbajack_local = str(get_jackify_downloads_dir() / f"{list_id}.wabbajack")
                modlist = wabbajack_local
                self._clf3_cdn_url = download_url

        ctx['install_dir'] = install_dir
        ctx['downloads_dir'] = downloads_dir
        ctx['install_mode'] = install_mode
        ctx['modlist'] = modlist
        return True

    def _authenticate_for_install(self, ctx: dict) -> bool:
        """Fetch and log the Nexus auth token for this install. Returns False if aborted."""
        # Get authentication token (OAuth or API key) with automatic refresh
        api_key, oauth_info = self.auth_service.get_auth_for_engine()
        if not api_key:
            self._abort_with_message(
                "warning",
                "Authorisation Required",
                "Please authorise with Nexus Mods before installing modlists.\n\n"
                "Click the 'Authorise' button above to log in with OAuth,\n"
                "or configure an API key in Settings.",
                safety_level="medium"
            )
            return False

        # Log authentication status at install start (Issue #111 diagnostics)
        auth_method = self.auth_service.get_auth_method()
        logger.info("=" * 60)
        logger.info("Authentication Status at Install Start")
        logger.info(f"Method: {auth_method or 'UNKNOWN'}")
        logger.info(f"Token length: {len(api_key)} chars")

        if auth_method == 'oauth':
            token_handler = self.auth_service.token_handler
            token_info = token_handler.get_token_info()
            if 'expires_in_minutes' in token_info:
                logger.info(f"OAuth expires in: {token_info['expires_in_minutes']:.1f} minutes")
            if token_info.get('refresh_token_likely_expired'):
                logger.warning(f"OAuth refresh token age: {token_info['refresh_token_age_days']:.1f} days (may need re-auth)")
        logger.info("=" * 60)

        ctx['api_key'] = api_key
        ctx['oauth_info'] = oauth_info
        return True

    def _validate_fields_and_dirs(self, ctx: dict) -> bool:
        """Validate required fields and install/downloads directories. Returns False if aborted."""
        install_dir = ctx['install_dir']
        downloads_dir = ctx['downloads_dir']

        modlist_name = self.modlist_name_edit.text().strip()

        from jackify.backend.services.install_validation import validate_install_request
        issues = validate_install_request(
            modlist_name=modlist_name,
            install_dir=install_dir,
            download_dir=downloads_dir,
            fields_to_check={'modlist_name', 'install_dir', 'download_dir'},
        )
        field_labels = {
            'modlist_name': "Modlist Name",
            'install_dir': "Install Directory",
            'download_dir': "Downloads Directory",
        }
        missing_fields = [
            field_labels[i.field] for i in issues
            if i.code == 'missing_field' and i.field in field_labels
        ]
        if missing_fields:
            self._abort_with_message(
                "warning",
                "Missing Required Fields",
                "Please fill in all required fields before starting the install:\n- " + "\n- ".join(missing_fields)
            )
            return False

        dir_issue = next((i for i in issues if i.code in ('unsafe_directory', 'dangerous_directory')), None)
        if dir_issue and dir_issue.code == 'dangerous_directory':
            self._abort_with_message("warning", "Invalid Install Directory", dir_issue.message)
            return False
        if dir_issue:
            from jackify.frontends.gui.dialogs.warning_dialog import WarningDialog
            dlg = WarningDialog(dir_issue.message, parent=self)
            result = dlg.exec()
            if not result or not dlg.confirmed:
                self._abort_install_validation()
                return False
        if not os.path.isdir(install_dir):
            from ..services.message_service import MessageService
            create = MessageService.question(self, "Create Directory?",
                f"The install directory does not exist:\n{install_dir}\n\nWould you like to create it?",
                critical=False  # Non-critical, won't steal focus
            )
            if create == QMessageBox.Yes:
                try:
                    os.makedirs(install_dir, exist_ok=True)
                except Exception as e:
                    MessageService.show_error(self, install_dir_create_failed(install_dir, str(e)))
                    self._abort_install_validation()
                    return False
            else:
                self._abort_install_validation()
                return False
        if not os.path.isdir(downloads_dir):
            from ..services.message_service import MessageService
            create = MessageService.question(self, "Create Directory?",
                f"The downloads directory does not exist:\n{downloads_dir}\n\nWould you like to create it?",
                critical=False  # Non-critical, won't steal focus
            )
            if create == QMessageBox.Yes:
                try:
                    os.makedirs(downloads_dir, exist_ok=True)
                except Exception as e:
                    MessageService.show_error(self, install_dir_create_failed(downloads_dir, str(e)))
                    self._abort_install_validation()
                    return False
            else:
                self._abort_install_validation()
                return False

        ctx['modlist_name'] = modlist_name
        return True

    def _persist_resolution_and_dirs(self, ctx: dict) -> None:
        """Save the selected resolution and remember the chosen parent directories."""
        install_dir = ctx['install_dir']
        downloads_dir = ctx['downloads_dir']

        # Handle resolution saving
        resolution = self.resolution_combo.currentText()
        if resolution and resolution != "Leave unchanged":
            raw_resolution = resolution.split(" (")[0] if " (" in resolution else resolution
            self._current_resolution = raw_resolution
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

        ensure_flatpak_steam_filesystem_access(Path(install_dir))

        # Handle parent directory saving
        self._save_parent_directories(install_dir, downloads_dir)

    def _detect_game(self, ctx: dict) -> bool:
        """Detect the modlist's game type and gate on support. Returns False if aborted."""
        modlist = ctx['modlist']
        install_mode = ctx['install_mode']

        game_type = None
        game_name = None

        readme_url = None
        if install_mode == 'file':
            # Parse .wabbajack file to get game type
            wabbajack_path = Path(modlist)
            readme_url = self.wabbajack_parser.parse_wabbajack_readme(wabbajack_path)
            result = self.wabbajack_parser.parse_wabbajack_game_type(wabbajack_path)
            if result:
                if isinstance(result, tuple):
                    game_type, raw_game_type = result
                    if game_type == 'unknown' and raw_game_type:
                        game_name = raw_game_type
                    else:
                        game_name = GAME_DISPLAY_NAMES.get(game_type, game_type)
                else:
                    game_type = result
                    game_name = GAME_DISPLAY_NAMES.get(game_type, game_type)
        else:
            # For online modlists, try to get game type from selected modlist
            if hasattr(self, 'selected_modlist_info') and self.selected_modlist_info:
                readme_url = self.selected_modlist_info.get('readme_url')
                game_name = self.selected_modlist_info.get('game', '')
                logger.debug(f"Detected game_name from selected_modlist_info: '{game_name}'")
                game_type = GAME_NAME_TO_TYPE.get(game_name.lower())
                logger.debug(f"Mapped game_name '{game_name}' to game_type: '{game_type}'")
                if not game_type:
                    game_type = 'unknown'
                    logger.debug(f"Game type not found in mapping, setting to 'unknown'")
            else:
                logger.debug(f"No selected_modlist_info found")
                game_type = 'unknown'

        # Store game type and name for later use
        self._current_game_type = game_type
        self._current_game_name = game_name

        # Check if game is supported
        logger.debug(f"Checking if game_type '{game_type}' is supported")
        logger.debug(f"game_type='{game_type}', game_name='{game_name}'")
        from jackify.backend.services.install_validation import validate_install_request
        issues = validate_install_request(game_type=game_type, fields_to_check=set())
        unsupported = any(i.code == 'unsupported_game' for i in issues)
        vr_notice = any(i.code == 'vr_game' for i in issues)
        logger.debug(f"is_supported_game('{game_type}') unsupported={unsupported}")

        if unsupported:
            logger.debug(f"Game '{game_type}' is not supported, showing dialog")
            from ..widgets.unsupported_game_dialog import UnsupportedGameDialog
            dialog = UnsupportedGameDialog(self, game_name)
            if not dialog.show_dialog(self, game_name):
                self._abort_install_validation()
                return False
        elif vr_notice:
            from ..widgets.unsupported_game_dialog import UnsupportedGameDialog
            if not UnsupportedGameDialog.show_dialog(self, game_name, vr_warning=True):
                self._abort_install_validation()
                return False

        ctx['readme_url'] = readme_url
        return True

    def _reset_install_ui_state(self, ctx: dict) -> None:
        """Reset console, progress indicators and per-run flags before launching the engine."""
        self.console.clear()
        self.process_monitor.clear()

        # Collapse Show Details if it was left open by the previous run.
        if self.show_details_checkbox.isChecked():
            self.show_details_checkbox.blockSignals(True)
            self.show_details_checkbox.setChecked(False)
            self.show_details_checkbox.blockSignals(False)
            from PySide6.QtCore import Qt as _Qt
            self._toggle_console_visibility(_Qt.Unchecked)

        self.progress_indicator.reset()
        self.progress_state_manager.reset()
        self.file_progress_list.clear()
        self.file_progress_list.start_cpu_tracking()  # Start tracking CPU during installation
        self._is_update_install = False
        self._existing_shortcut_appid = None
        self._premium_notice_shown = False
        self._stalled_download_start_time = None
        self._stalled_download_notified = False
        self._stalled_data_snapshot = 0
        self._token_error_notified = False  # Reset token error notification
        self._premium_failure_active = False
        self._installation_cancelled = False
        self._non_premium_gate_enabled = False
        self._non_premium_info_acknowledged = False
        self._pending_manual_download_events = None
        self._post_install_active = False
        self._post_install_current_step = 0
        # Activity tab is always visible (tabs handle visibility automatically)

        # Update button states for installation
        self.start_btn.setEnabled(False)
        self.cancel_btn.setVisible(False)
        self.cancel_install_btn.setVisible(True)

    def _check_update_mode(self, ctx: dict) -> bool:
        """Detect update-vs-new workflow, then re-confirm the modlist source is safe to launch.
        Returns False if aborted."""
        modlist_name = ctx['modlist_name']
        install_dir = ctx['install_dir']
        install_mode = ctx['install_mode']
        modlist = ctx['modlist']

        # Detect update-vs-new workflow before starting engine install.
        from jackify.backend.utils.modlist_meta import JACKIFY_META_FILE
        install_real = os.path.realpath(install_dir)
        meta_exists = (Path(install_real) / JACKIFY_META_FILE).exists()
        existing_appid = self._find_existing_shortcut_appid(modlist_name, install_real)
        if meta_exists and existing_appid:
            eligible, update_meta = self._evaluate_update_candidate(
                modlist_name,
                install_real,
                install_mode,
                existing_appid,
            )
            if not eligible:
                logger.info(
                    "Update mode not offered | reason=%s requested_name=%s installed_name=%s",
                    update_meta.get("reason"),
                    modlist_name,
                    update_meta.get("installed_name"),
                )
            else:
                logger.info(
                    "Update mode candidate | version_relation=%s requested_version=%s installed_version=%s",
                    update_meta.get("version_relation"),
                    update_meta.get("requested_version"),
                    update_meta.get("installed_version"),
                )
                decision = self._prompt_update_or_new_install(modlist_name, install_real, update_meta)
                if decision == "cancel":
                    self._abort_install_validation()
                    return False
                if decision == "new":
                    from ..services.message_service import MessageService

                    MessageService.warning(
                        self,
                        "Shortcut Name Already Exists",
                        "A Steam shortcut with this name already points to this install directory.\n\n"
                        "For a new install, choose a different Modlist Name before starting.",
                        safety_level="medium",
                    )
                    self._abort_install_validation()
                    return False
                # update
                self._is_update_install = True
                self._existing_shortcut_appid = existing_appid
                self._safe_append_text(
                    f"Update mode selected. Reusing existing Steam shortcut AppID {existing_appid}."
                )
                self._record_pre_update_ini_snapshot(install_real)

        # Final safety check - ensure online modlists use machine_url
        # CLF3 is exempt: it uses a pre-resolved local .wabbajack path, not machine_url
        if install_mode == 'online' and self._session_engine_id() != "clf3":
            if hasattr(self, 'selected_modlist_info') and self.selected_modlist_info:
                expected_machine_url = self.selected_modlist_info.get('machine_url')
                if expected_machine_url:
                    modlist = expected_machine_url  # Force use machine_url
                else:
                    self._abort_with_message(
                        "critical",
                        "Installation Error",
                        "Cannot determine modlist machine URL. Please select the modlist again."
                    )
                    return False
            else:
                self._abort_with_message(
                    "critical",
                    "Installation Error",
                    "Modlist information is missing. Please select the modlist again from the gallery."
                )
                return False

        ctx['modlist'] = modlist
        return True
