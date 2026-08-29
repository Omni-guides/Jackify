"""
CLI-side consent, execution and manual-download handling for the Modlist Playbook System.

Generic replacement for the VNV/MEW-specific `input()` blocks in `menu_handler_modlist.py` -
any playbook (present or future) gets the same treatment: assemble the confirmation text from
`build_confirmation_text()` (shared with the GUI controller so the wording matches), prompt via
`input()`, execute on consent, and fall back to the CLI download manager one tool at a time for
non-Premium Nexus accounts (sequential dialogs, per the accepted v0.8 UX decision - no combined
pre-flight scan).
"""
import logging
from typing import Callable, Optional

from jackify.backend.services.playbook.catalog import asset_cache_dir
from jackify.backend.services.playbook.registry import MatchIdentity, PlaybookRegistry
from jackify.backend.services.playbook.runtime import build_confirmation_text, run_hook
from jackify.backend.services.playbook.schema import Playbook
from jackify.backend.services.playbook.steps.base import StepContext
from jackify.frontends.cli.commands.manual_download_flow import run_cli_manual_download_phase

logger = logging.getLogger(__name__)


def _confirm_via_input(playbook: Playbook, hook: str, output: Callable[[str], None]) -> bool:
    playbook_hook = playbook.hook or "post_configure"
    steps_for_hook = [s for s in playbook.steps if (s.hook or playbook_hook) == hook]
    output("")
    output(build_confirmation_text(playbook, steps_for_hook))
    try:
        answer = input("Run these steps now? (Y/n): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return answer in ("", "y", "yes")


def _handle_manual_download(item: dict, output: Callable[[str], None]) -> bool:
    """One catalog tool's manual-download fallback. Returns True if the user completed it (or it
    wasn't actually needed), False if they gave up - caller decides whether to retry the step."""
    metadata = item.get("manual_download_metadata")
    tool_id = item.get("tool_id")
    if not metadata or not tool_id:
        static = item.get("manual_download")
        if static is not None:
            output("")
            output(f"{item.get('tool_display_name', 'Tool')} requires a manual download:")
            output(static.instructions)
        return False

    output("")
    output(f"{item.get('tool_display_name', 'Tool')} requires a manual Nexus download. Opening Jackify CLI Download Manager...")
    return run_cli_manual_download_phase(
        events=[metadata],
        loop_iteration=1,
        download_dir=asset_cache_dir(tool_id),
        stdin_write=lambda _payload: True,
        output_callback=output,
        concurrent_limit=1,
    )


def run_playbook_automation_cli(
    hook: str,
    registry: PlaybookRegistry,
    identity: MatchIdentity,
    step_ctx: StepContext,
    install_key: str,
    output: Optional[Callable[[str], None]] = None,
) -> None:
    """
    Run every playbook matching `identity` for `hook`, prompting for consent and handling
    manual downloads. Never raises - matches `hook_wiring`'s non-fatal contract, since this
    runs after the modlist is already successfully installed/configured.
    """
    output = output or print
    step_ctx.log = output

    def _confirm(playbook: Playbook) -> bool:
        return _confirm_via_input(playbook, hook, output)

    try:
        results = run_hook(hook, registry, identity, step_ctx, install_key, consent_callback=_confirm)
    except Exception as e:
        logger.warning("Playbook automation failed (non-fatal): %s", e)
        return

    for result in results:
        if not result.applied:
            continue
        if result.manual_downloads:
            if any(_handle_manual_download(item, output) for item in result.manual_downloads):
                try:
                    run_hook(hook, registry, identity, step_ctx, install_key, consent_callback=lambda pb: True)
                except Exception as e:
                    logger.warning("Playbook retry after manual download failed (non-fatal): %s", e)
        for notice in result.failure_notices:
            output(f"Playbook step issue: {notice}")
        for message in result.queued_messages:
            output("")
            output(f"{message.get('title', '')}: {message.get('body', '')}")
