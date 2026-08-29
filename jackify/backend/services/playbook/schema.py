"""
Playbook schema: dataclasses, parsing and structural validation.

Every playbook goes through this module before any of its steps can run, so it is kept small
and reviewable in full rather than spread across the registry/catalog/runtime layers. See
docs/0.8_work/modlist_playbook_system.md section 4.
"""
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from packaging.specifiers import InvalidSpecifier, SpecifierSet

from .url_policy import UrlPolicyError, validate_https_allowlisted_url

_PLAYBOOK_ID_RE = re.compile(r'^[a-z0-9][a-z0-9-]{2,63}$')
_VALID_HOOKS = {"post_install", "post_configure"}
_VALID_ON_FAILURE = {"abort_playbook", "continue", "warn"}
_MAX_STEPS = 32
_SUPPORTED_SCHEMA_VERSION = 1

_COMMON_STEP_FIELDS = {
    "id", "type", "label", "hook", "completed_when", "on_failure", "failure_message",
}


class PlaybookValidationError(ValueError):
    """A playbook failed structural validation. Callers should log and skip it, not crash."""


@dataclass
class MatchBlock:
    machine_urls: List[str] = field(default_factory=list)
    name_contains: List[str] = field(default_factory=list)
    name_exact: List[str] = field(default_factory=list)
    name_patterns: List[str] = field(default_factory=list)
    mo2_profiles: List[str] = field(default_factory=list)
    game_types: List[str] = field(default_factory=list)


@dataclass
class Step:
    id: str
    type: str
    label: str
    hook: Optional[str] = None
    completed_when: Optional[dict] = None
    on_failure: str = "warn"
    failure_message: Optional[str] = None
    # Type-specific fields (source/dest/tool/script/etc) not common to every step type.
    fields: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Playbook:
    schema_version: int
    playbook_id: str
    revision: int
    display_name: str
    summary: str
    maintainer: str
    created: str
    match: MatchBlock
    confirm: dict
    steps: List[Step]
    reference_url: Optional[str] = None
    requires_jackify_version: Optional[str] = None
    hook: str = "post_configure"
    intro: str = ""
    outro: str = ""
    disabled: bool = False


def _require(data: dict, field_name: str, expected_type: type) -> Any:
    if field_name not in data:
        raise PlaybookValidationError(f"missing required field: {field_name}")
    value = data[field_name]
    if not isinstance(value, expected_type):
        raise PlaybookValidationError(
            f"field {field_name!r} must be {expected_type.__name__}, got {type(value).__name__}"
        )
    return value


def _parse_match(data: dict) -> MatchBlock:
    match_data = _require(data, "match", dict)
    match = MatchBlock(
        machine_urls=list(match_data.get("machine_urls", [])),
        name_contains=list(match_data.get("name_contains", [])),
        name_exact=list(match_data.get("name_exact", [])),
        name_patterns=list(match_data.get("name_patterns", [])),
        mo2_profiles=list(match_data.get("mo2_profiles", [])),
        game_types=list(match_data.get("game_types", [])),
    )
    for pattern in match.name_patterns:
        try:
            re.compile(pattern)
        except re.error as e:
            raise PlaybookValidationError(f"invalid name_patterns regex {pattern!r}: {e}")
    return match


def _parse_reference_url(data: dict) -> Optional[str]:
    url = data.get("reference_url")
    if url is None:
        return None
    try:
        return validate_https_allowlisted_url(url, "reference_url")
    except UrlPolicyError as e:
        raise PlaybookValidationError(str(e))


def _parse_requires_jackify_version(data: dict) -> Optional[str]:
    requires = data.get("requires", {})
    if not isinstance(requires, dict) or not requires.get("jackify_version"):
        return None
    spec = requires["jackify_version"]
    try:
        SpecifierSet(spec)
    except InvalidSpecifier as e:
        raise PlaybookValidationError(f"invalid requires.jackify_version {spec!r}: {e}")
    return spec


def _parse_step(raw: Any) -> Step:
    if not isinstance(raw, dict):
        raise PlaybookValidationError("each step must be a JSON object")

    step_id = _require(raw, "id", str)
    step_type = _require(raw, "type", str)
    label = _require(raw, "label", str)

    hook = raw.get("hook")
    if hook is not None and hook not in _VALID_HOOKS:
        raise PlaybookValidationError(f"step {step_id!r}: invalid hook {hook!r}")

    on_failure = raw.get("on_failure", "warn")
    if on_failure not in _VALID_ON_FAILURE:
        raise PlaybookValidationError(f"step {step_id!r}: invalid on_failure {on_failure!r}")

    completed_when = raw.get("completed_when")
    if completed_when is not None and not isinstance(completed_when, dict):
        raise PlaybookValidationError(f"step {step_id!r}: completed_when must be an object")

    return Step(
        id=step_id,
        type=step_type,
        label=label,
        hook=hook,
        completed_when=completed_when,
        on_failure=on_failure,
        failure_message=raw.get("failure_message"),
        fields={k: v for k, v in raw.items() if k not in _COMMON_STEP_FIELDS},
    )


def _parse_steps(data: dict) -> List[Step]:
    raw_steps = _require(data, "steps", list)
    if not (1 <= len(raw_steps) <= _MAX_STEPS):
        raise PlaybookValidationError(f"steps must contain 1 to {_MAX_STEPS} entries")

    steps = []
    seen_ids = set()
    for raw_step in raw_steps:
        step = _parse_step(raw_step)
        if step.id in seen_ids:
            raise PlaybookValidationError(f"duplicate step id: {step.id}")
        seen_ids.add(step.id)
        steps.append(step)
    return steps


def parse_playbook(data: dict) -> Playbook:
    """
    Parse and structurally validate a playbook.

    Raises PlaybookValidationError on any problem; callers are expected to log and skip the
    offending playbook rather than let one bad manifest break sync for every other playbook.
    """
    if not isinstance(data, dict):
        raise PlaybookValidationError("playbook must be a JSON object")

    schema_version = _require(data, "schema_version", int)
    if schema_version > _SUPPORTED_SCHEMA_VERSION:
        raise PlaybookValidationError(
            f"unsupported schema_version {schema_version} "
            f"(max known {_SUPPORTED_SCHEMA_VERSION})"
        )

    playbook_id = _require(data, "playbook_id", str)
    if not _PLAYBOOK_ID_RE.match(playbook_id):
        raise PlaybookValidationError(f"invalid playbook_id: {playbook_id!r}")

    revision = _require(data, "revision", int)
    if revision < 1:
        raise PlaybookValidationError("revision must be >= 1")

    hook = data.get("hook", "post_configure")
    if hook not in _VALID_HOOKS:
        raise PlaybookValidationError(f"invalid hook: {hook!r}")

    return Playbook(
        schema_version=schema_version,
        playbook_id=playbook_id,
        revision=revision,
        display_name=_require(data, "display_name", str),
        summary=_require(data, "summary", str),
        maintainer=_require(data, "maintainer", str),
        created=_require(data, "created", str),
        match=_parse_match(data),
        confirm=_require(data, "confirm", dict),
        steps=_parse_steps(data),
        reference_url=_parse_reference_url(data),
        requires_jackify_version=_parse_requires_jackify_version(data),
        hook=hook,
        intro=data.get("intro", ""),
        outro=data.get("outro", ""),
        disabled=bool(data.get("disabled", False)),
    )
