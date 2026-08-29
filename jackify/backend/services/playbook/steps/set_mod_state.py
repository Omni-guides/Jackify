"""
set_mod_state step: enable or disable mods in a modlist.txt (MO2's `+name`/`-name` format).

Generalizes problem_mods_service.py's disable_problem_mods() - same `[tag] Name` normalization
and atomic-write pattern - but bidirectional (enable or disable) and driven by a step-supplied
mod list rather than the fixed problem-mods manifest. The spec doesn't say which modlist.txt to
use (that depends on which MO2 profile is active, which isn't a Jackify-known constant), so this
step requires an explicit `path` field rather than assuming one.
"""
import os
import re
import tempfile
from typing import List

from ..paths import PlaybookPathError
from .base import StepContext, StepResult, default_completed

completed = default_completed

_TAG_PREFIX_RE = re.compile(r'^\[.*?\]\s*')


def _bare_name(name: str) -> str:
    return _TAG_PREFIX_RE.sub("", name)


def execute(ctx: StepContext, step) -> StepResult:
    fields = step.fields
    mods: List[str] = fields.get("mods", [])
    state = fields.get("state")
    if not mods or state not in ("enabled", "disabled"):
        return StepResult(False, "set_mod_state: mods (non-empty) and state are both required")

    try:
        path = ctx.resolve(fields["path"])
    except (KeyError, PlaybookPathError) as e:
        return StepResult(False, f"set_mod_state: invalid path: {e}")

    if not path.is_file():
        return StepResult(False, f"set_mod_state: modlist file does not exist: {path}")

    try:
        content = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as e:
        return StepResult(False, f"set_mod_state: could not read {path}: {e}")

    target_set = {m.lower() for m in mods}
    want_prefix = "+" if state == "enabled" else "-"
    lines = content.splitlines(keepends=True)
    new_lines = []
    changed = []

    for line in lines:
        stripped = line.rstrip("\r\n")
        if stripped[:1] in ("+", "-"):
            current_prefix, name = stripped[0], stripped[1:]
            bare = _bare_name(name)
            if name.lower() in target_set or bare.lower() in target_set:
                if current_prefix != want_prefix:
                    eol = line[len(stripped):]
                    new_lines.append(f"{want_prefix}{name}{eol}")
                    changed.append(name)
                    continue
        new_lines.append(line)

    if not changed:
        return StepResult(True, "no change needed")

    new_content = "".join(new_lines)
    try:
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".playbook_modlist_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(new_content)
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except Exception as e:
        return StepResult(False, f"set_mod_state: write failed: {e}")

    return StepResult(True, f"{state}: {', '.join(changed)}")
