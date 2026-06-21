"""Steam shortcut conflict handling for InstallModlistScreen (Mixin)."""
import logging
import os

from PySide6.QtCore import QThread, Signal

from jackify.frontends.gui.dialogs.existing_setup_dialog import prompt_existing_setup_dialog
from jackify.frontends.gui.services.message_service import MessageService

logger = logging.getLogger(__name__)


class InstallModlistShortcutDialogMixin:
    """Mixin providing shortcut conflict dialog and retry-with-new-name for InstallModlistScreen."""

    def _restore_controls_after_shortcut_dialog_abort(self):
        """Return Install Modlist to a usable state when shortcut resolution is aborted."""
        if hasattr(self, "_abort_install_validation"):
            try:
                self._abort_install_validation()
                return
            except Exception:
                pass
        try:
            self._enable_controls_after_operation()
        except Exception:
            pass
        try:
            self.cancel_btn.setVisible(True)
            self.cancel_install_btn.setVisible(False)
        except Exception:
            pass

    def show_shortcut_conflict_dialog(self, conflicts):
        """Show dialog to resolve existing install / shortcut conflicts."""
        existing_name = conflicts[0].get("name") or self.modlist_name_edit.text().strip()
        modlist_name = self.modlist_name_edit.text().strip()
        install_dir = os.path.realpath(self.install_dir_edit.text().strip())

        action, new_name = prompt_existing_setup_dialog(
            self,
            window_title="Existing Modlist Setup Detected",
            heading="Modlist Update or New Install",
            body=(
                "Jackify detected an existing Steam shortcut for this modlist setup.\n\n"
                "If you are updating, repairing, or reconfiguring an existing install, choose "
                "'Use Existing Setup'. If you want a separate Steam entry, enter a different "
                "name and choose 'Create New Shortcut'."
            ),
            existing_name=existing_name,
            requested_name=modlist_name,
            install_dir=install_dir,
            field_label="New shortcut name",
            reuse_label="Use Existing Setup",
            new_label="Create New Shortcut",
            cancel_label="Cancel",
        )

        if action == "reuse":
            existing_appid = conflicts[0].get("appid")
            if not existing_appid:
                MessageService.warning(
                    self,
                    "Existing Setup Not Found",
                    "Jackify could not determine the Steam AppID for the existing shortcut.",
                )
                self._restore_controls_after_shortcut_dialog_abort()
                return
            self._safe_append_text(f"Reusing existing Steam shortcut '{existing_name}'.")
            self._reuse_shortcut_with_prefix_check(int(existing_appid), modlist_name, install_dir)
            return

        if action == "new":
            if new_name and new_name != modlist_name:
                self.retry_automated_workflow_with_new_name(new_name)
                return
            if new_name == modlist_name:
                MessageService.warning(self, "Same Name", "Please enter a different name to resolve the conflict.")
            else:
                MessageService.warning(self, "Invalid Name", "Please enter a valid shortcut name.")
            self._restore_controls_after_shortcut_dialog_abort()
            return

        self._safe_append_text("Shortcut creation cancelled by user")
        self._restore_controls_after_shortcut_dialog_abort()

    def _reuse_shortcut_with_prefix_check(self, appid: int, modlist_name: str, install_dir: str) -> None:
        """Continue configuration after conflict resolution, creating the prefix if it is missing."""
        from jackify.backend.services.automated_prefix_service import AutomatedPrefixService
        svc = AutomatedPrefixService()
        if svc.get_prefix_path(appid):
            self.continue_configuration_after_automated_prefix(appid, modlist_name, install_dir, None)
            return

        logger.info("Proton prefix missing for AppID %s; creating before configuration", appid)
        self._safe_append_text("[00:00:00] Proton prefix not found; creating prefix...")

        class _PrefixCreateThread(QThread):
            finished = Signal(bool)

            def __init__(self, appid):
                super().__init__()
                self._appid = appid

            def run(self):
                try:
                    from jackify.backend.services.automated_prefix_service import AutomatedPrefixService
                    ok = AutomatedPrefixService().create_prefix_with_proton_wrapper(self._appid)
                    self.finished.emit(ok)
                except Exception as exc:
                    logger.error("Prefix creation thread failed: %s", exc)
                    self.finished.emit(False)

        _thread = _PrefixCreateThread(appid)

        def _on_done(success):
            _thread.deleteLater()
            if not success:
                logger.error("Failed to create Proton prefix for AppID %s", appid)
                MessageService.warning(
                    self,
                    "Prefix Creation Failed",
                    "Jackify could not create the Proton prefix.\n\n"
                    "Try launching the modlist from Steam once to initialise it, then run Configure.",
                )
                self._restore_controls_after_shortcut_dialog_abort()
                return
            self._safe_append_text("[00:00:00] Proton prefix created.")
            self.continue_configuration_after_automated_prefix(appid, modlist_name, install_dir, None)

        _thread.finished.connect(_on_done)
        self._prefix_create_thread = _thread
        _thread.start()

    def retry_automated_workflow_with_new_name(self, new_name):
        """Retry the automated workflow with a new shortcut name."""
        self.modlist_name_edit.setText(new_name)
        self._safe_append_text(f"Retrying with new shortcut name: '{new_name}'")
        self.start_automated_prefix_workflow()
