"""TTW integration methods for InstallModlistScreen (Mixin)."""
from pathlib import Path
from PySide6.QtCore import QTimer
import logging
import os

logger = logging.getLogger(__name__)


class TTWIntegrationMixin:
    """Mixin providing TTW integration methods for InstallModlistScreen."""

    def _check_ttw_eligibility(self, modlist_name: str, game_type: str, install_dir: str) -> bool:
        """Check if modlist is FNV, TTW-compatible, and doesn't already have TTW

        Args:
            modlist_name: Name of the installed modlist
            game_type: Game type (e.g., 'falloutnv')
            install_dir: Modlist installation directory

        Returns:
            bool: True if should offer TTW integration
        """
        try:
            # Check 1: Must be Fallout New Vegas
            if game_type.lower() not in ['falloutnv', 'fallout new vegas', 'fallout_new_vegas']:
                return False

            # Check 2: Must be eligible per a matching playbook's offer_tool_flow step
            from jackify.backend.services.playbook.hook_wiring import modlist_offers_tool_flow
            if not modlist_offers_tool_flow(install_dir, modlist_name, "ttw_install"):
                return False

            # Check 3: TTW must not already be installed
            if self._detect_existing_ttw(install_dir):
                logger.debug("TTW already installed, skipping prompt")
                return False

            return True

        except Exception as e:
            logger.debug(f"Error checking TTW eligibility: {e}")
            return False

    def _detect_existing_ttw(self, install_dir: str) -> bool:
        """Check if TTW is already installed in the modlist

        Args:
            install_dir: Modlist installation directory

        Returns:
            bool: True if TTW is already present
        """
        try:
            mods_dir = Path(install_dir) / "mods"
            if not mods_dir.exists():
                return False

            # Check for folders containing "Tale of Two Wastelands" that have actual TTW content
            # Exclude separators and placeholder folders
            for folder in mods_dir.iterdir():
                if not folder.is_dir():
                    continue

                folder_name_lower = folder.name.lower()

                # Skip separator folders and placeholders
                if "_separator" in folder_name_lower or "put" in folder_name_lower or "here" in folder_name_lower:
                    continue

                # Check if folder name contains TTW indicator
                if "tale of two wastelands" in folder_name_lower:
                    # Verify it has actual TTW content by checking for the main ESM
                    ttw_esm = folder / "TaleOfTwoWastelands.esm"
                    if ttw_esm.exists():
                        logger.debug(f"Found existing TTW installation: {folder.name}")
                        return True
                    else:
                        logger.debug(f"Found TTW folder but no ESM, skipping: {folder.name}")

            return False

        except Exception as e:
            logger.debug(f"Error detecting existing TTW: {e}")
            return False  # Assume not installed on error

    def _initiate_ttw_workflow(self, modlist_name: str, install_dir: str):
        """Navigate to TTW screen and set it up for modlist integration

        Args:
            modlist_name: Name of the modlist that needs TTW integration
            install_dir: Path to the modlist installation directory
        """
        try:
            # Store modlist context for later use when TTW completes
            self._ttw_modlist_name = modlist_name
            self._ttw_install_dir = install_dir

            # Get reference to TTW screen BEFORE navigation
            if self.stacked_widget:
                # Remember which screen to return to after TTW completes
                self._ttw_return_screen_index = self.stacked_widget.currentIndex()

                # Navigate first - triggers lazy init and reset_screen_to_defaults.
                # set_modlist_integration_mode must be called AFTER so it overwrites
                # the default dir that reset_screen_to_defaults populates.
                self.stacked_widget.setCurrentIndex(5)

                ttw_screen = self.stacked_widget.widget(5)

                if hasattr(ttw_screen, 'set_modlist_integration_mode'):
                    ttw_screen.set_modlist_integration_mode(modlist_name, install_dir)

                    # Connect to completion signal to show success dialog after TTW
                    if hasattr(ttw_screen, 'integration_complete'):
                        ttw_screen.integration_complete.connect(self._on_ttw_integration_complete)
                else:
                    logger.debug("WARNING: TTW screen does not support modlist integration mode yet")

                # Force collapsed state shortly after navigation to avoid any
                # showEvent/layout timing races that may leave it expanded
                try:
                    QTimer.singleShot(50, lambda: getattr(ttw_screen, 'force_collapsed_state', lambda: None)())
                except Exception:
                    pass

                # TTW needs the user to supply the installer file and destination - without an
                # explicit interruption here, a user who has alt-tabbed away has no way to know
                # Jackify is waiting on them, and installs have sat idle for an hour because of
                # it. Deliberate focus steal, matching the existing Steam-restart pattern.
                if hasattr(self, '_start_focus_reclaim_retries'):
                    self._start_focus_reclaim_retries()
                from jackify.frontends.gui.services.message_service import MessageService
                MessageService.information(
                    self,
                    "Tale of Two Wastelands Setup Required",
                    f"'{modlist_name}' requires Tale of Two Wastelands.\n\n"
                    "Jackify needs you to provide the TTW installer file and installation "
                    "directory on the screen behind this dialog before it can continue.",
                )

        except Exception as e:
            logger.debug(f"ERROR: Failed to initiate TTW workflow: {e}")
            from jackify.frontends.gui.services.message_service import MessageService
            MessageService.critical(
                self,
                "TTW Navigation Failed",
                f"Failed to navigate to TTW installation screen: {str(e)}"
            )

    def _on_ttw_integration_complete(self, success: bool, ttw_version: str = ""):
        """Handle completion of TTW integration and show final success dialog

        Args:
            success: Whether TTW integration completed successfully
            ttw_version: Version of TTW that was installed
        """
        try:
            if not success:
                from jackify.frontends.gui.services.message_service import MessageService
                MessageService.critical(
                    self,
                    "TTW Integration Failed",
                    "Tale of Two Wastelands integration did not complete successfully."
                )
                return

            # Navigate back to the screen that initiated TTW
            if self.stacked_widget:
                self.stacked_widget.setCurrentIndex(getattr(self, '_ttw_return_screen_index', 4))

            # Calculate elapsed time from workflow start
            import time
            if hasattr(self, '_install_workflow_start_time'):
                time_taken = int(time.time() - self._install_workflow_start_time)
                mins, secs = divmod(time_taken, 60)
                time_str = f"{mins} minutes, {secs} seconds" if mins else f"{secs} seconds"
            else:
                time_str = "unknown"

            # Build success message including TTW installation
            modlist_name = getattr(self, '_ttw_modlist_name', 'Unknown')
            game_name = "Fallout New Vegas"

            # Check for modlist post-install fixes (playbooks - VNV, etc.) after TTW installation
            vnv_automation_running = False
            if hasattr(self, '_ttw_install_dir') and hasattr(self, '_ttw_modlist_name'):
                vnv_automation_running = self._check_and_run_playbook_automation(
                    self._ttw_modlist_name, self._ttw_install_dir,
                    appid=getattr(self, '_current_appid', None), game_type='falloutnv',
                )

            if vnv_automation_running:
                self._pending_success_dialog_params = {
                    'modlist_name': modlist_name,
                    'workflow_type': 'install',
                    'time_taken': time_str,
                    'game_name': game_name,
                    'enb_detected': False,
                    'install_dir': getattr(self, '_ttw_install_dir', '') or '',
                    'game_type': 'falloutnv',
                    'appid': getattr(self, '_current_appid', '') or '',
                }
                return

            # No VNV automation - end post-install feedback now
            self._end_post_install_feedback(True)

            self._run_verifier_then_show_success(
                install_dir=getattr(self, '_ttw_install_dir', '') or '',
                game_type='falloutnv',
                appid=getattr(self, '_current_appid', '') or '',
                success_params={
                    'modlist_name': modlist_name,
                    'workflow_type': 'install',
                    'time_taken': time_str,
                    'game_name': game_name,
                    'enb_detected': False,
                    'playbook_warnings': list(getattr(self._playbook_controller, 'last_failure_notices', None) or []) if hasattr(self, '_playbook_controller') else [],
                },
            )

        except Exception as e:
            logger.debug(f"ERROR: Failed to show final success dialog: {e}")
            from jackify.frontends.gui.services.message_service import MessageService
            MessageService.critical(
                self,
                "Display Error",
                f"TTW integration completed but failed to show success dialog: {str(e)}"
            )

