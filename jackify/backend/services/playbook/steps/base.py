"""
Shared step execution context and result types for playbook_steps/.

Every step type module exposes `completed(ctx, step) -> bool` and
`execute(ctx, step) -> StepResult`. Idempotency checking (completed_when, falling back to
write_marker) is identical across types, so it lives here once rather than being
reimplemented per step - see docs/0.8_work/modlist_playbook_system.md section 6.
"""
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from ..expressions import ExpressionContext, evaluate
from ..paths import PlaybookPathError, resolve_path
from ..schema import Step


@dataclass
class StepContext:
    """Everything a step needs to check completion and execute, resolved once per hook run."""
    roots: Dict[str, Path] = field(default_factory=dict)
    catalog: Any = None  # playbook.catalog.Catalog, resolved lazily to avoid an import cycle
    auth_service: Any = None  # NexusAuthService, only needed by acquisition-backed steps
    mo2_profile: Optional[str] = None
    game_type: Optional[str] = None
    mod_enabled: Optional[Callable[[str], bool]] = None
    mod_present: Optional[Callable[[str], bool]] = None
    log: Callable[[str], None] = lambda msg: None

    def expression_context(self, exit_code: Optional[int] = None, output: str = "") -> ExpressionContext:
        return ExpressionContext(
            roots=self.roots, mo2_profile=self.mo2_profile, game_type=self.game_type,
            exit_code=exit_code, output=output,
            mod_enabled=self.mod_enabled, mod_present=self.mod_present,
        )

    def resolve(self, template: str) -> Path:
        """Resolve a path template against this context's roots. Raises PlaybookPathError."""
        return resolve_path(template, self.roots)


@dataclass
class StepResult:
    success: bool
    message: str = ""
    # Structured payload for steps whose result the runtime needs to act on beyond pass/fail
    # (e.g. show_user_message queues its content here rather than displaying anything itself).
    data: Optional[Dict[str, Any]] = None


def default_completed(ctx: StepContext, step: Step) -> bool:
    """Shared idempotency check: explicit completed_when first, else write_marker existence."""
    if step.completed_when is not None:
        return evaluate(step.completed_when, ctx.expression_context())
    write_marker = step.fields.get("write_marker")
    if write_marker:
        try:
            return ctx.resolve(write_marker).exists()
        except PlaybookPathError:
            return False
    return False


def stream_subprocess_output(proc: subprocess.Popen, timeout_seconds: int, on_line: Callable[[str], None]) -> str:
    """
    Read stdout line-by-line as it arrives, calling `on_line` for each line, honoring the
    overall timeout across the whole read (not per-line). Returns the full captured output.
    Raises subprocess.TimeoutExpired (matching proc.communicate()'s contract) if the deadline
    passes before the process exits. Shared by every step type that runs a real subprocess
    (run_catalog_tool, run_modlist_script), so progress reaches the UI live rather than only
    once the process exits.
    """
    import select

    output_chunks = []
    deadline = time.monotonic() + timeout_seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(proc.args, timeout_seconds)
        ready, _, _ = select.select([proc.stdout], [], [], min(remaining, 0.5))
        if ready:
            line = proc.stdout.readline()
            if line == "":
                break
            output_chunks.append(line)
            on_line(line)
        elif proc.poll() is not None:
            break
    proc.stdout.close()
    proc.wait(timeout=max(deadline - time.monotonic(), 0.1))
    return "".join(output_chunks)


def touch_write_marker(ctx: StepContext, step: Step) -> None:
    """After a successful execute(), create the write_marker file if the step declares one."""
    write_marker = step.fields.get("write_marker")
    if not write_marker:
        return
    try:
        marker_path = ctx.resolve(write_marker)
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        marker_path.touch()
    except PlaybookPathError as e:
        ctx.log(f"Could not write completion marker {write_marker!r}: {e}")
