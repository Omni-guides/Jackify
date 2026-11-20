"""
CLI counterpart of the GUI's combined playbook consent for TTW: one up-front confirmation covering
every step of a playbook that offers TTW and has more to do, then TTW into the modlist's own TTW
folder, then locating (or asking for) any user-supplied archives, so the playbook's remaining
steps run without a second prompt.
"""
import logging
from pathlib import Path
from typing import Callable, Dict, Optional, Set

from jackify.backend.handlers.modlist_install_cli_ttw import (
    TTW_OFFER_HANDLED, is_ttw_offer_eligible, launch_ttw_for_playbook,
)
from jackify.backend.services.playbook.hook_wiring import (
    get_tool_flow_offer, get_user_archive_requests,
)
from jackify.backend.services.playbook.registry import MatchIdentity
from jackify.backend.services.playbook.runtime import build_combined_confirmation_text
from jackify.backend.services.playbook.steps.base import StepContext
from jackify.backend.services.playbook.user_files import find_user_archive

logger = logging.getLogger(__name__)


def _ask_yes(prompt: str) -> bool:
    try:
        return input(prompt).strip().lower() in ("", "y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False


def _ask_for_archive(request: Dict, output: Callable[[str], None]) -> Optional[Path]:
    output("")
    output(f"{request['prompt']}.")
    output("Jackify could not find it in your downloads folder.")
    if request.get("url"):
        output(f"Download it from (a login may be required): {request['url']}")
    while True:
        try:
            answer = input("Path to the downloaded archive (Enter to skip): ").strip()
        except (EOFError, KeyboardInterrupt):
            return None
        if not answer:
            return None
        path = Path(answer).expanduser()
        if path.is_file():
            return path
        output(f"File not found: {path}")


def _collect_archives(install_dir: str, name: str, game: str, output: Callable[[str], None]) -> Dict[str, Path]:
    found: Dict[str, Path] = {}
    for request in get_user_archive_requests(install_dir, name, game):
        path = find_user_archive(request["name_contains"])
        if path:
            output(f"Found {path.name} in {path.parent}")
        else:
            path = _ask_for_archive(request, output)
        if path:
            found[request["archive_id"]] = path
        else:
            output(f"No archive selected for: {request['label']}")
    return found


def run_combined_ttw_flow(
    identity: MatchIdentity, step_ctx: StepContext, output: Callable[[str], None],
) -> Set[str]:
    """
    Returns the ids of playbooks the user consented to (empty when no combined offer applies or
    the user declined). Records the install dir as handled either way so the standalone TTW
    prompt does not ask a second time.
    """
    modlist_dir = step_ctx.roots.get("modlist_dir")
    name, game = identity.name, identity.game_type
    if not modlist_dir or not name or not game:
        return set()
    install_dir = str(modlist_dir)
    if install_dir in TTW_OFFER_HANDLED or not is_ttw_offer_eligible(install_dir, game, name):
        return set()
    offer = get_tool_flow_offer(install_dir, name, "ttw_install", game)
    if offer is None or not offer.combined_consent:
        return set()

    TTW_OFFER_HANDLED.add(install_dir)
    output("")
    output(build_combined_confirmation_text(offer.playbook))
    if not _ask_yes("Run these steps now? (Y/n): "):
        return set()

    if not launch_ttw_for_playbook(install_dir, name, offer.output_dir):
        output(f"TTW was not installed, so {name} will not work yet. Install it with the TTW tool in "
               "Additional Tasks, then add the result to the modlist's mods folder. "
               "Continuing with the remaining steps.")
    step_ctx.user_files.update(_collect_archives(install_dir, name, game, output))
    return {offer.playbook.playbook_id}
