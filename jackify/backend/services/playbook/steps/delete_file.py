"""
delete_file step: remove a single file, restricted to inside {modlist_dir}.

Refuses directories and glob patterns - this step removes exactly one named file, never a
pattern or a tree. `backup` defaults true: the file is renamed aside (`<name>.deleted`), not
unlinked, so a bad playbook can't destroy user data irrecoverably. `resolve_path()` never
expands a glob (paths are always resolved as an exact literal), so this check is a guard
against an author mistakenly assuming wildcard support, not a real security boundary - it's
kept narrow to `*`/`?` since `[`/`]` are legitimate in an ordinary Wabbajack/MO2 folder name
(e.g. "[NoDelete] Stock New Vegas") and never actually interpreted as a character class here.
"""
from ..paths import PlaybookPathError
from .base import StepContext, StepResult, default_completed

completed = default_completed

_GLOB_CHARS = set("*?")


def execute(ctx: StepContext, step) -> StepResult:
    template = step.fields.get("path", "")
    if not template.startswith("{modlist_dir}"):
        return StepResult(False, "delete_file: path must be inside {modlist_dir}")
    if any(c in _GLOB_CHARS for c in template):
        return StepResult(False, "delete_file: glob patterns are not allowed")

    try:
        path = ctx.resolve(template)
    except PlaybookPathError as e:
        return StepResult(False, f"delete_file: invalid path: {e}")

    if path.is_dir():
        return StepResult(False, f"delete_file: refuses to delete a directory: {path}")
    if not path.exists():
        return StepResult(True, "already absent")

    backup = step.fields.get("backup", True)
    try:
        if backup:
            path.rename(path.with_name(path.name + ".deleted"))
        else:
            path.unlink()
    except OSError as e:
        return StepResult(False, f"delete_file failed: {e}")

    return StepResult(True)
