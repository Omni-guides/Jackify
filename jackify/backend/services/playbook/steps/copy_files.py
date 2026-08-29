"""copy_files step: copy a file or directory tree from `source` to `dest`.

`merge` defaults true, matching `dirs_exist_ok=True` - the VNV root-mods step relies on this to
add its files into `Data/` without deleting vanilla files already there.
"""
import shutil

from ..paths import PlaybookPathError
from .base import StepContext, StepResult, default_completed

completed = default_completed


def execute(ctx: StepContext, step) -> StepResult:
    try:
        source = ctx.resolve(step.fields["source"])
        dest = ctx.resolve(step.fields["dest"])
    except (KeyError, PlaybookPathError) as e:
        return StepResult(False, f"copy_files: invalid source/dest: {e}")

    if not source.exists():
        return StepResult(False, f"copy_files: source does not exist: {source}")

    merge = bool(step.fields.get("merge", True))
    try:
        if source.is_dir():
            if dest.exists() and not merge:
                return StepResult(False, f"copy_files: destination already exists: {dest}")
            shutil.copytree(source, dest, dirs_exist_ok=merge)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
    except Exception as e:
        return StepResult(False, f"copy_files failed: {e}")

    return StepResult(True)
