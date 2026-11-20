"""
Hook wiring: builds identity/roots/StepContext for a real modlist and runs `run_hook()`
against the shared, process-wide `PlaybookRegistry`.

Step 6 of the Modlist Playbook System. The call site in `modlist_configuration.py` is a single
guarded call to `run_configuration_hook(self)`; everything else (resolving roots, reading the
active MO2 profile, building mod-state lookups, never raising) lives here, matching the
non-fatal pattern every other step in `_execute_configuration_steps()` already follows.

User controls (section 9.3): the `playbooks_enabled` setting (default on, Settings dialog) and
`JACKIFY_DISABLE_PLAYBOOKS=1` both disable this entirely, checked before anything else runs.
"""
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .catalog import Catalog
from .registry import MatchIdentity, PlaybookRegistry
from .schema import Playbook
from .url_policy import UrlPolicyError, validate_https_allowlisted_url
from .runtime import HookRunResult, compute_install_key, run_hook
from .steps.base import StepContext

logger = logging.getLogger(__name__)

_registry = PlaybookRegistry()
_TAG_PREFIX_RE = re.compile(r'^\[.*?\]\s*')


def get_registry() -> PlaybookRegistry:
    """Process-wide playbook registry, synced at startup (step 7)."""
    return _registry


def playbooks_disabled() -> bool:
    """True if the user has turned modlist fixes off, via setting or environment variable."""
    if os.environ.get("JACKIFY_DISABLE_PLAYBOOKS") == "1":
        return True
    try:
        from jackify.backend.handlers.config_handler import ConfigHandler
        return not ConfigHandler().get("playbooks_enabled", True)
    except Exception:
        return False


def run_configuration_hook(handler, consent_callback=None) -> List[HookRunResult]:
    """
    Run `post_configure` playbooks for the modlist `handler` (a `ModlistHandler`-shaped object)
    just finished configuring. Never raises - any problem here is logged and treated as "no
    playbooks ran", the same non-fatal handling every surrounding configuration step already has.

    Called with no `consent_callback` at Step 17 itself (`defer_playbooks=False` callers only) -
    real consent for the GUI happens after the caller's background thread completes
    (`PlaybookAutomationController`), and for the CLI right after this call returns
    (`run_playbook_automation_cli`), both using `find_matching_playbooks()`/`build_confirmation_text()`
    against the same registry. Omitting `consent_callback` here means every heavy playbook is
    declined by design (see `runtime.run_hook()`) - the safe default for any caller that hasn't
    wired its own consent flow.
    """
    if playbooks_disabled():
        logger.debug("Playbooks disabled by setting or JACKIFY_DISABLE_PLAYBOOKS, skipping hook")
        return []
    try:
        return _run_post_configure(handler, consent_callback)
    except Exception as e:
        logger.warning("Playbook post_configure hook failed (non-fatal): %s", e)
        return []


def resolve_game_type(modlist_dir: str, game_type: Optional[str] = None) -> Optional[str]:
    """
    Playbook-form game name (e.g. "Fallout New Vegas") for a modlist. Normalises the caller's
    value (any known spelling); if the caller has none, reads it from the install's own
    ModOrganizer.ini. Returns None only if both fail.
    """
    from jackify.backend.models.game_types import to_display_name
    resolved = to_display_name(game_type)
    if resolved:
        return resolved
    try:
        from jackify.backend.services.game_type_detection import detect_from_install
        resolved = to_display_name(detect_from_install(modlist_dir))
    except Exception as e:
        logger.debug("Game type detection failed for %s: %s", modlist_dir, e)
    if not resolved:
        logger.warning("Could not determine game type for %s (given: %r)", modlist_dir, game_type)
    return resolved


def run_install_hook(modlist_dir: str, modlist_name: str, consent_callback=None,
                     game_type: Optional[str] = None) -> List[HookRunResult]:
    """
    Run `post_install` playbooks right after engine install succeeds, before shortcut creation
    (section 7's table) - the convergence point in `AutomatedPrefixService.run_working_workflow()`
    that both the GUI thread and CLI configuration phase already funnel through. No appid or
    Wine prefix exists yet at this point, so `roots` only has `{modlist_dir}`. Never raises.

    Unlike `run_configuration_hook()`, `consent_callback` here is not yet wired to any UI - this
    call site still runs inside `run_working_workflow()`'s background thread, so a heavy
    post_install playbook (currently only `begin-again.json`'s `offer_tool_flow`) is always
    declined for now. This is harmless: `offer_tool_flow` steps only hand off to TTW's own
    existing prompt/install flow (see `modlist_offers_tool_flow()`) rather than executing
    anything themselves, so nothing is lost by never consenting to them here.
    """
    if playbooks_disabled():
        logger.debug("Playbooks disabled by setting or JACKIFY_DISABLE_PLAYBOOKS, skipping hook")
        return []
    try:
        return _run_post_install(modlist_dir, modlist_name, consent_callback, game_type)
    except Exception as e:
        logger.warning("Playbook post_install hook failed (non-fatal): %s", e)
        return []


@dataclass
class ToolFlowOffer:
    """A matching playbook's `offer_tool_flow` step for a flow, as the GUI/CLI needs to act on it."""
    playbook: Playbook
    output_dir: Optional[str]
    # True when the playbook has more to do than hand off to the flow (other steps or
    # prerequisites), so one combined consent dialog replaces the flow's own question.
    combined_consent: bool


def get_tool_flow_offer(modlist_dir: str, modlist_name: str, flow: str,
                        game_type: Optional[str] = None) -> Optional[ToolFlowOffer]:
    """
    The matching playbook's `offer_tool_flow` step for `flow` (e.g. "ttw_install"), or None.
    Replaces `ttw_compatible_modlists.py`'s static whitelist as the eligibility check
    `_check_ttw_eligibility()`/`_is_ttw_eligible()` use - the actual install flow (TTW's own
    prompt and installer) is unchanged, only the "is this modlist eligible" question moves
    from a name/regex whitelist to real playbook matching (name/profile signal plus file
    evidence via `confirm`). Never raises; a modlist not yet covered by any playbook simply has
    no offer, which is the deliberate trade-off while TTW-compatible modlists are migrated from
    the whitelist one playbook at a time.
    """
    if playbooks_disabled():
        return None
    try:
        from .runtime import find_matching_playbooks
        from .steps import execute_step
        identity, step_ctx, _install_key = build_install_hook_context(
            modlist_dir, modlist_name, game_type)
        for playbook in find_matching_playbooks("post_install", _registry, identity, step_ctx):
            playbook_hook = playbook.hook or "post_configure"
            for step in playbook.steps:
                if (step.hook or playbook_hook) != "post_install":
                    continue
                if step.type != "offer_tool_flow" or step.fields.get("flow") != flow:
                    continue
                result = execute_step(step_ctx, step)
                output_dir = (result.data or {}).get("output_dir") if result.success else None
                others = [s for s in playbook.steps if s is not step]
                return ToolFlowOffer(
                    playbook=playbook, output_dir=output_dir,
                    combined_consent=bool(others or playbook.prerequisites),
                )
        return None
    except Exception as e:
        logger.warning("Playbook offer_tool_flow check failed (non-fatal): %s", e)
        return None


def modlist_offers_tool_flow(modlist_dir: str, modlist_name: str, flow: str,
                             game_type: Optional[str] = None) -> bool:
    """True if a matching post_install playbook has an `offer_tool_flow` step for `flow`."""
    return get_tool_flow_offer(modlist_dir, modlist_name, flow, game_type) is not None


def get_proton_recommendation(modlist_dir: str, modlist_name: str,
                              game_type: Optional[str] = None) -> Optional[Dict]:
    """
    The first matching playbook's `proton_recommendation` ({"recommended": [...]}), or None.
    Advice only, so the playbooks_enabled setting does not gate it. Never raises.
    """
    try:
        from .expressions import evaluate as evaluate_expression
        identity, step_ctx, _install_key = build_install_hook_context(
            modlist_dir, modlist_name, game_type)
        expression_context = step_ctx.expression_context()
        for playbook in _registry.find_candidates(identity):
            if playbook.proton_recommendation and evaluate_expression(playbook.confirm, expression_context):
                return playbook.proton_recommendation
    except Exception as e:
        logger.warning("Playbook Proton recommendation lookup failed (non-fatal): %s", e)
    return None


def get_user_archive_requests(modlist_dir: str, modlist_name: str,
                              game_type: Optional[str] = None) -> List[Dict]:
    """
    Every `extract_archive` step across the matching playbooks (all hooks) as
    {archive_id, label, prompt, url, name_contains}, for the caller to locate or ask the user for
    before the hook runs. Never raises.
    """
    if playbooks_disabled():
        return []
    try:
        from .runtime import find_matching_playbooks
        identity, step_ctx, _install_key = build_install_hook_context(
            modlist_dir, modlist_name, game_type)
        requests: List[Dict] = []
        seen = set()
        for hook in ("post_install", "post_configure"):
            for playbook in find_matching_playbooks(hook, _registry, identity, step_ctx):
                for step in playbook.steps:
                    archive_id = step.fields.get("archive_id")
                    if step.type != "extract_archive" or not archive_id or archive_id in seen:
                        continue
                    seen.add(archive_id)
                    url = step.fields.get("url")
                    try:
                        url = validate_https_allowlisted_url(url, f"step {step.id!r} url") if url else None
                    except UrlPolicyError as e:
                        logger.warning("Ignoring step url: %s", e)
                        url = None
                    requests.append({
                        "url": url,
                        "archive_id": archive_id,
                        "label": step.label,
                        "prompt": step.fields.get("prompt") or step.label,
                        "name_contains": list(step.fields.get("name_contains") or []),
                    })
        return requests
    except Exception as e:
        logger.warning("Playbook archive request lookup failed (non-fatal): %s", e)
        return []


def _assemble_context(
    modlist_dir: Path, modlist_name: str, game_type: Optional[str], roots: dict,
    appid: Optional[str], with_auth: bool, user_files: Optional[Dict[str, Path]] = None,
) -> Tuple[MatchIdentity, StepContext, str]:
    """Single place identity, StepContext and install_key are built, so game_type can never be
    set on one and dropped on another."""
    from .mo2_profile import get_selected_mo2_profile
    mo2_profile = get_selected_mo2_profile(modlist_dir)

    mod_enabled_fn = mod_present_fn = None
    if mo2_profile:
        modlist_txt = modlist_dir / "profiles" / mo2_profile / "modlist.txt"
        if modlist_txt.is_file():
            enabled, present = _mod_lookups(modlist_txt)
            mod_enabled_fn = lambda name: name.lower() in enabled
            mod_present_fn = lambda name: name.lower() in present

    identity = MatchIdentity(game_type=game_type, name=modlist_name, mo2_profile=mo2_profile)

    auth_service = None
    if with_auth:
        from jackify.backend.services.nexus_auth_service import NexusAuthService
        auth_service = NexusAuthService()
    step_ctx = StepContext(
        roots=roots,
        catalog=_registry.get_catalog() or Catalog(),
        auth_service=auth_service,
        mo2_profile=mo2_profile,
        game_type=game_type,
        mod_enabled=mod_enabled_fn,
        mod_present=mod_present_fn,
        user_files=dict(user_files or {}),
    )
    return identity, step_ctx, compute_install_key(appid, modlist_dir)


def build_install_hook_context(
    modlist_dir: str, modlist_name: str, game_type: Optional[str] = None,
) -> Tuple[MatchIdentity, StepContext, str]:
    """
    Build the (identity, step_ctx, install_key) triple for a post_install hook run, without
    running anything - reused by `run_install_hook()` and by GUI/CLI callers that need to check
    for matches (`find_matching_playbooks`) before a background thread completes, since consent
    for a heavy playbook may require a dialog that can't be shown from that thread.
    """
    modlist_path = Path(modlist_dir)
    return _assemble_context(
        modlist_path, modlist_name, resolve_game_type(modlist_dir, game_type),
        {"modlist_dir": modlist_path}, appid=None, with_auth=False,
    )


def _run_post_install(modlist_dir: str, modlist_name: str, consent_callback=None,
                      game_type: Optional[str] = None) -> List[HookRunResult]:
    identity, step_ctx, install_key = build_install_hook_context(modlist_dir, modlist_name, game_type)
    return run_hook("post_install", _registry, identity, step_ctx, install_key, consent_callback)


def _mod_lookups(modlist_txt: Path) -> Tuple[set, set]:
    """(enabled, present) lowercased mod-name sets, both bare and `[tag] Name` forms, parsed
    from a modlist.txt. `present` includes disabled ('-') entries; `enabled` only '+' ones."""
    enabled, present = set(), set()
    try:
        for line in modlist_txt.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped[:1] not in ("+", "-"):
                continue
            name = stripped[1:].lower()
            bare = _TAG_PREFIX_RE.sub("", name)
            present.update((name, bare))
            if stripped[0] == "+":
                enabled.update((name, bare))
    except OSError:
        pass
    return enabled, present


def build_configuration_hook_context(handler) -> Optional[Tuple[MatchIdentity, StepContext, str]]:
    """
    Build the (identity, step_ctx, install_key) triple for a post_configure hook run against
    `handler` (a `ModlistHandler`-shaped object), without running anything. See
    `build_install_hook_context()`'s docstring for why this is exposed separately from
    `run_configuration_hook()`. Returns None if `handler` lacks a resolved `modlist_dir`, mirroring
    that function's existing early-return.
    """
    modlist_dir = Path(handler.modlist_dir) if getattr(handler, "modlist_dir", None) else None
    if modlist_dir is None:
        return None

    roots = {"modlist_dir": modlist_dir}
    if getattr(handler, "stock_game_path", None):
        roots["game_root"] = Path(handler.stock_game_path)
    elif getattr(handler, "game_var_full", None):
        # No embedded Stock Game folder: the modlist uses the user's own Steam/Heroic install
        from jackify.backend.handlers.path_handler import PathHandler
        vanilla_root = PathHandler().find_vanilla_game_paths().get(handler.game_var_full)
        if vanilla_root:
            roots["game_root"] = Path(vanilla_root)

    wineprefix: Optional[str] = None
    if getattr(handler, "appid", None):
        try:
            wineprefix = handler.protontricks_handler.get_wine_prefix_path(handler.appid)
        except Exception:
            wineprefix = None
    if wineprefix:
        roots["prefix"] = Path(wineprefix)
        roots["drive_c"] = Path(wineprefix) / "drive_c"

    try:
        downloads_dir = handler.path_handler.get_download_directory_linux_path(
            modlist_dir / "ModOrganizer.ini"
        )
    except Exception:
        downloads_dir = None
    if downloads_dir:
        roots["downloads_dir"] = Path(downloads_dir)

    from .mo2_profile import get_selected_mo2_profile
    game_type = getattr(handler, "game_var_full", None)
    return _assemble_context(
        modlist_dir, getattr(handler, "modlist_name", None) or modlist_dir.name,
        game_type, roots, appid=getattr(handler, "appid", None), with_auth=True,
    )


def build_gui_configuration_context(
    modlist_name: str, install_dir: str,
    appid: Optional[str] = None, game_type_full: Optional[str] = None,
    user_files: Optional[Dict[str, Path]] = None,
) -> Tuple[MatchIdentity, StepContext, str]:
    """
    Build the (identity, step_ctx, install_key) triple for a post_configure hook run from a GUI
    screen, which has no `ModlistHandler` instance to hand (it was created and discarded inside
    `configure_modlist_post_steam()`'s CLI-handler stack) - only the primitives every screen
    already tracks post-configure: modlist name/dir, appid, and a human-friendly game type
    (matching `find_vanilla_game_paths()`'s keys, e.g. "Fallout New Vegas"). Mirrors
    `build_configuration_hook_context()`'s roots but resolves `game_root`/`prefix` directly
    rather than through a handler, the same way `vnv_automation_controller.py` already does today.
    """
    modlist_dir = Path(install_dir)
    roots = {"modlist_dir": modlist_dir}

    if game_type_full:
        from jackify.backend.handlers.path_handler import PathHandler
        game_root = PathHandler().find_vanilla_game_paths().get(game_type_full)
        if game_root:
            roots["game_root"] = Path(game_root)

    if appid:
        try:
            from jackify.backend.handlers.protontricks_handler import ProtontricksHandler
            wineprefix = ProtontricksHandler(steamdeck=False).get_wine_prefix_path(appid)
        except Exception:
            wineprefix = None
        if wineprefix:
            roots["prefix"] = Path(wineprefix)
            roots["drive_c"] = Path(wineprefix) / "drive_c"

    return _assemble_context(
        modlist_dir, modlist_name, game_type_full, roots, appid=appid, with_auth=True,
        user_files=user_files,
    )


def _run_post_configure(handler, consent_callback=None) -> List[HookRunResult]:
    built = build_configuration_hook_context(handler)
    if built is None:
        return []
    identity, step_ctx, install_key = built
    return run_hook("post_configure", _registry, identity, step_ctx, install_key, consent_callback)
