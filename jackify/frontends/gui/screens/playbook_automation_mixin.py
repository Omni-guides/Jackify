"""
Shared playbook automation methods for any screen that needs post-configure/post-install fixes
applied after a background config/install thread completes - replaces the near-identical
install_modlist_vnv.py/install_modlist_mew.py mixins and the duplicate inline methods that used
to live directly on configure_new_modlist_dialogs.py/configure_existing_modlist_workflow.py.

Delegates to PlaybookAutomationController for the actual confirm/execute/manual-download flow.
"""
import logging

from jackify.backend.models.game_types import GAME_DISPLAY_NAMES
from jackify.backend.services.playbook.hook_wiring import build_gui_configuration_context, get_registry

logger = logging.getLogger(__name__)


class PlaybookAutomationMixin:
    """Mixin providing playbook automation methods for any GUI screen."""

    def _check_and_run_playbook_automation(
        self, modlist_name: str, install_dir: str,
        appid: str = None, game_type: str = None, hook: str = "post_configure",
    ) -> bool:
        """Check for matching playbooks and start automation if applicable.

        Returns:
            True if a heavy playbook is running (caller should defer its success dialog)
            False if nothing needed consent (caller should show success dialog immediately)
        """
        from ..services.playbook_automation_controller import PlaybookAutomationController

        # Not every screen sets _current_appid (only configure_existing_modlist_workflow.py
        # does) - fall back to the screen's own context dict, same as the old VNV/MEW
        # controllers did, so steps needing a Wine prefix (e.g. MEW's Radio Fix) still get one
        # on a fresh install.
        if not appid:
            ctx = getattr(self, "context", None)
            appid = ctx.get("appid") if isinstance(ctx, dict) else None

        game_type_full = GAME_DISPLAY_NAMES.get(game_type) if game_type else None
        identity, step_ctx, install_key = build_gui_configuration_context(
            modlist_name, install_dir, appid=appid, game_type_full=game_type_full,
        )

        self._playbook_controller = PlaybookAutomationController()
        return self._playbook_controller.attempt(
            parent=self,
            hook=hook,
            registry=get_registry(),
            identity=identity,
            step_ctx=step_ctx,
            install_key=install_key,
            on_progress=self._safe_append_text,
            on_complete=self._on_playbook_automation_complete,
            begin_feedback=self._begin_playbook_progress,
            handle_feedback=self._handle_post_install_progress,
        )

    def _on_playbook_automation_complete(self, success: bool, error: str):
        """Handle playbook automation completion and show deferred success dialog."""
        self._end_post_install_feedback(not bool(error))

        if not success and error:
            from ..services.message_service import MessageService
            MessageService.warning(
                self,
                "Modlist Fix Failed",
                f"A modlist post-install fix encountered an error:\n\n{error}",
            )
        elif success:
            self._safe_append_text("Modlist post-install fixes completed successfully.")

        if hasattr(self, '_pending_success_dialog_params'):
            params = self._pending_success_dialog_params
            del self._pending_success_dialog_params
            self._run_verifier_then_show_success(
                install_dir=params.get('install_dir', ''),
                game_type=params.get('game_type', 'unknown'),
                appid=params.get('appid', ''),
                success_params={
                    'modlist_name': params['modlist_name'],
                    'workflow_type': params.get('workflow_type', 'install'),
                    'time_taken': params['time_taken'],
                    'game_name': params.get('game_name'),
                    'enb_detected': params.get('enb_detected', False),
                    'playbook_warnings': list(getattr(self._playbook_controller, 'last_failure_notices', None) or []),
                },
            )
