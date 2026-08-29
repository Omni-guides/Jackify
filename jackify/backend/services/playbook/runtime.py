"""
playbook_runtime.py: run_hook() - the sequence from section 7.

match (registry.find_candidates, already done by the caller building `identity`) -> hash
verification (already done by the registry at sync time) -> validate schema/requires -> evaluate
confirm -> if heavy, get consent -> execute in order (completed_when, on_failure) -> record
journal -> queue failure notices/messages/flow offers for the caller to surface.

Consent and message/flow display are GUI-layer concerns; this module never shows anything
itself. `consent_callback` defaults to declining heavy playbooks when no callback is supplied,
rather than silently running impactful steps with nothing able to ask permission.
"""
import hashlib
import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import Version

from jackify import __version__ as JACKIFY_VERSION
from jackify.shared.paths import get_jackify_data_dir
from .expressions import evaluate as evaluate_expression
from .registry import MatchIdentity, PlaybookRegistry
from .schema import Playbook
from .steps import STEP_MODULES, execute_step, is_completed
from .steps.base import StepContext, touch_write_marker

logger = logging.getLogger(__name__)

# Section 4.3: any of these makes a playbook "heavy" - shown in a declinable confirmation
# dialog rather than applied silently.
_HEAVY_TYPES = {
    "run_catalog_tool", "run_modlist_script", "offer_tool_flow", "replace_mod", "replace_mod_file",
}


@dataclass
class HookRunResult:
    playbook_id: str
    revision: int
    applied: bool
    step_results: Dict[str, str] = field(default_factory=dict)
    failure_notices: List[str] = field(default_factory=list)
    queued_messages: List[dict] = field(default_factory=list)
    offered_flows: List[str] = field(default_factory=list)
    # Populated when a run_catalog_tool step fails acquisition and the tool supports a
    # manual-download fallback - the GUI/CLI layer surfaces this instead of just a failure notice.
    manual_downloads: List[dict] = field(default_factory=list)


def compute_install_key(appid: Optional[str], modlist_dir: Path) -> str:
    """Journal key: appid where known, else a stable hash of the install directory."""
    if appid:
        return str(appid)
    return hashlib.sha256(str(Path(modlist_dir).resolve()).encode("utf-8")).hexdigest()[:16]


def is_heavy(playbook: Playbook, steps=None) -> bool:
    return any(step.type in _HEAVY_TYPES for step in (steps if steps is not None else playbook.steps))


def build_confirmation_text(playbook: Playbook, steps_for_hook: list) -> str:
    """
    Assemble the consent dialog/prompt text per design doc section 4.2: `display_name` heading,
    `intro`, the numbered `step.label`s, `outro`. This reproduces today's hand-written VNV/MEW
    `get_automation_description()` wording exactly (verified byte-for-byte in tests) - a playbook
    author supplies the ingredients, never the assembled text, so they cannot describe a step the
    playbook does not contain.
    """
    numbered_steps = "\n".join(f"{i}. {step.label}" for i, step in enumerate(steps_for_hook, start=1))
    parts = [playbook.display_name, "", playbook.intro, "", numbered_steps]
    if playbook.outro:
        parts += ["", playbook.outro]
    parts += ["", "Would you like Jackify to automate these steps?"]
    return "\n".join(parts)


def run_hook(
    hook: str,
    registry: PlaybookRegistry,
    identity: MatchIdentity,
    step_ctx: StepContext,
    install_key: str,
    consent_callback: Optional[Callable[[Playbook], bool]] = None,
) -> List[HookRunResult]:
    """
    Run every playbook matching `identity` and `hook`.

    A problem with one playbook (unknown step type, unmet requires, declined consent, a failed
    step) never affects another - each candidate is handled independently, consistent with the
    registry's "one malformed playbook never breaks sync for the rest" guarantee.
    """
    results = []
    for playbook in registry.find_candidates(identity):
        matched = _match_one(playbook, hook, step_ctx)
        if matched is None:
            continue
        logger.info(
            "Playbook %s matched for %s hook (%d step(s))",
            playbook.playbook_id, hook, len(matched),
        )
        result = _run_one(playbook, matched, step_ctx, install_key, consent_callback)
        if result is not None:
            results.append(result)
    return results


def find_matching_playbooks(hook: str, registry: PlaybookRegistry, identity: MatchIdentity, step_ctx: StepContext):
    """
    Side-effect-free preview of what `run_hook()` would act on: every candidate whose steps,
    `requires` and `confirm` all pass for this hook, without executing or consenting anything.

    Safe to call from a background thread (matching and `confirm` evaluation involve no
    execution, no journal writes, no dialogs) - the GUI/CLI layer uses this to decide whether a
    consent prompt is needed at all before the background config/install thread completes,
    since the actual consent + execution must happen afterward on the main thread.
    """
    matches = []
    for playbook in registry.find_candidates(identity):
        steps_for_hook = _match_one(playbook, hook, step_ctx)
        if steps_for_hook is not None:
            matches.append(playbook)
    return matches


def _requires_satisfied(playbook: Playbook) -> bool:
    if not playbook.requires_jackify_version:
        return True
    try:
        return Version(JACKIFY_VERSION) in SpecifierSet(playbook.requires_jackify_version)
    except InvalidSpecifier:
        return False


def _match_one(playbook: Playbook, hook: str, step_ctx: StepContext) -> Optional[list]:
    """Shared by `run_hook()` and `find_matching_playbooks()`: unknown-type/requires/hook-filter/
    confirm checks, with no execution or consent. Returns the matched steps for this hook, or
    None if the playbook does not apply."""
    unknown_types = {s.type for s in playbook.steps if s.type not in STEP_MODULES}
    if unknown_types:
        logger.warning(
            "Playbook %s uses unknown step type(s) %s, skipping whole playbook",
            playbook.playbook_id, sorted(unknown_types),
        )
        return None

    if not _requires_satisfied(playbook):
        logger.warning(
            "Playbook %s requires jackify_version %s, current %s does not satisfy it, skipping",
            playbook.playbook_id, playbook.requires_jackify_version, JACKIFY_VERSION,
        )
        return None

    playbook_hook = playbook.hook or "post_configure"
    steps_for_hook = [s for s in playbook.steps if (s.hook or playbook_hook) == hook]
    if not steps_for_hook:
        return None

    if not evaluate_expression(playbook.confirm, step_ctx.expression_context()):
        logger.debug("Playbook %s confirm block did not match, skipping", playbook.playbook_id)
        return None

    return steps_for_hook


def _run_one(
    playbook: Playbook,
    steps_for_hook: list,
    step_ctx: StepContext,
    install_key: str,
    consent_callback: Optional[Callable[[Playbook], bool]],
) -> Optional[HookRunResult]:
    if is_heavy(playbook, steps_for_hook):
        consented = consent_callback(playbook) if consent_callback else False
        if not consented:
            logger.info("Playbook %s declined (no consent)", playbook.playbook_id)
            _write_journal_entry(install_key, playbook.playbook_id, playbook.revision, "declined")
            return HookRunResult(
                playbook.playbook_id, playbook.revision, applied=False,
                step_results={s.id: "declined" for s in steps_for_hook},
            )

    step_results: Dict[str, str] = {}
    failure_notices: List[str] = []
    queued_messages: List[dict] = []
    offered_flows: List[str] = []
    manual_downloads: List[dict] = []

    for step in steps_for_hook:
        if is_completed(step_ctx, step):
            step_results[step.id] = "skipped_already_done"
            continue

        result = execute_step(step_ctx, step)
        if result.success:
            step_results[step.id] = "applied"
            touch_write_marker(step_ctx, step)
            if result.data:
                if "offer_flow" in result.data:
                    offered_flows.append(result.data["offer_flow"])
                elif "title" in result.data:
                    queued_messages.append(result.data)
        else:
            step_results[step.id] = "failed"
            display_message = step.failure_message or result.message
            failure_notices.append(f"{step.label}: {display_message}")
            logger.warning(
                "Playbook %s step %s failed: %s (raw: %s)",
                playbook.playbook_id, step.id, display_message, result.message,
            )
            if result.data and result.data.get("manual_download_metadata"):
                manual_downloads.append({
                    "step_id": step.id,
                    "step_label": step.label,
                    **result.data,
                })
            if step.on_failure == "abort_playbook":
                break

    applied = sum(1 for r in step_results.values() if r == "applied")
    skipped = sum(1 for r in step_results.values() if r == "skipped_already_done")
    failed = sum(1 for r in step_results.values() if r == "failed")
    logger.info(
        "Playbook %s finished: %d applied, %d skipped (already done), %d failed",
        playbook.playbook_id, applied, skipped, failed,
    )

    _write_journal_entry(install_key, playbook.playbook_id, playbook.revision, "applied", step_results)

    return HookRunResult(
        playbook_id=playbook.playbook_id, revision=playbook.revision, applied=True,
        step_results=step_results, failure_notices=failure_notices,
        queued_messages=queued_messages, offered_flows=offered_flows,
        manual_downloads=manual_downloads,
    )


def _journal_path(install_key: str) -> Path:
    return get_jackify_data_dir() / "playbooks" / "state" / f"{install_key}.json"


def _write_journal_entry(
    install_key: str, playbook_id: str, revision: int, result: str,
    step_results: Optional[Dict[str, str]] = None,
) -> None:
    """Advisory only (section 7) - skip decisions always re-evaluate completed_when against the
    filesystem, never trust this file. Failure to write is logged and otherwise ignored."""
    path = _journal_path(install_key)
    entry = {
        "playbook_id": playbook_id, "revision": revision, "timestamp": time.time(),
        "result": result, "step_results": step_results or {},
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"entries": []}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                data = {"entries": []}
        data.setdefault("entries", []).append(entry)

        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".playbook_journal_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except Exception as e:
        logger.debug("Playbook journal write failed for %s: %s", install_key, e)
