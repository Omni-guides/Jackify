"""create_directory step: mkdir(parents=True, exist_ok=True) at `path`."""
from ..paths import PlaybookPathError
from .base import StepContext, StepResult, default_completed

completed = default_completed


def execute(ctx: StepContext, step) -> StepResult:
    try:
        path = ctx.resolve(step.fields["path"])
    except (KeyError, PlaybookPathError) as e:
        return StepResult(False, f"create_directory: invalid path: {e}")

    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return StepResult(False, f"create_directory failed: {e}")

    return StepResult(True)
