"""
run_catalog_tool step: acquire and run a catalog tool.

Everything about *how* the tool runs (args, timeout, success criteria) is a catalog property,
approved once and reused by every playbook that references it - a playbook can only say which
tool, never how it runs. `{acquired}` in a catalog entry's `run.args` substitutes to the
acquired file's path; the standard path variables ({game_root} etc.) substitute to their
resolved roots. Output is streamed line-by-line via `ctx.log()` as the subprocess runs (not
just reported pass/fail at the end) so the GUI/CLI progress feed shows what is actually
happening - `run.progress_pattern`/`run.progress_label` drive a live percent readout when the
tool supports one (e.g. the BSA decompressor).
"""
import os
import re
import signal
import subprocess

from jackify.backend.handlers.subprocess_utils import (
    get_clean_subprocess_env,
    register_process_group,
    unregister_process_group,
)
from ..acquire import AcquisitionError, acquire_tool
from ..expressions import evaluate
from ..paths import PlaybookPathError
from ..schema import Step
from .base import StepContext, StepResult, default_completed, stream_subprocess_output

completed = default_completed

_DEFAULT_TIMEOUT = 60


def _substitute_args(args, acquired_path, roots) -> list:
    substitutions = {"{acquired}": str(acquired_path)}
    substitutions.update({f"{{{name}}}": str(root) for name, root in roots.items()})
    result = []
    for arg in args:
        for placeholder, value in substitutions.items():
            arg = arg.replace(placeholder, value)
        result.append(arg)
    return result


def execute(ctx: StepContext, step: Step) -> StepResult:
    tool_id = step.fields.get("tool")
    if not tool_id:
        return StepResult(False, "run_catalog_tool: tool is required")

    catalog = ctx.catalog
    tool = catalog.tools.get(tool_id) if catalog else None
    if tool is None:
        return StepResult(False, f"run_catalog_tool: unknown catalog tool {tool_id!r}")

    try:
        acquired = acquire_tool(tool, ctx.auth_service)
    except AcquisitionError as e:
        return StepResult(
            False, f"run_catalog_tool: {e}",
            data={"tool_id": tool_id, "tool_display_name": tool.display_name,
                  "manual_download_metadata": e.manual_download_metadata,
                  "manual_download": tool.manual_download},
        )

    run = tool.run
    args = _substitute_args(run.args if run else [], acquired, ctx.roots) if run else []
    executable = str(acquired)
    if tool.run_via_tool:
        from jackify.backend.services.tool_registry import ToolRegistry
        runner = ToolRegistry().get_binary_path(tool.run_via_tool)
        if runner is None:
            return StepResult(False, f"run_catalog_tool: {tool.run_via_tool!r} is not installed")
        executable = str(runner)

    cwd = None
    cwd_template = step.fields.get("cwd")
    if cwd_template:
        try:
            cwd = ctx.resolve(cwd_template)
        except PlaybookPathError as e:
            return StepResult(False, f"run_catalog_tool: invalid cwd: {e}")

    timeout_seconds = run.timeout_seconds if run else _DEFAULT_TIMEOUT
    progress_pattern = re.compile(run.progress_pattern) if run and run.progress_pattern else None
    progress_label = (run.progress_label if run else None) or tool.display_name
    ctx.log(f"Running {tool.display_name}...")

    last_percent = None

    def _on_line(line: str) -> None:
        nonlocal last_percent
        if not progress_pattern:
            return
        match = progress_pattern.search(line)
        if not match:
            return
        groups = match.groupdict()
        percent = groups.get("percent")
        if percent == last_percent:
            return
        last_percent = percent
        detail = (groups.get("detail") or "").strip()
        message = f"{progress_label}: {percent}%"
        if detail:
            message += f" - {detail}"
        ctx.log(message)

    try:
        proc = subprocess.Popen(
            [executable, *args],
            cwd=str(cwd) if cwd else None,
            env=get_clean_subprocess_env(),
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            start_new_session=True,
        )
    except OSError as e:
        return StepResult(False, f"run_catalog_tool: failed to start {tool.display_name}: {e}")

    register_process_group(proc.pid)
    try:
        output = stream_subprocess_output(proc, timeout_seconds, _on_line)
        exit_code = proc.returncode
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
        proc.communicate()
        return StepResult(False, f"run_catalog_tool: {tool.display_name} timed out after {timeout_seconds}s")
    finally:
        unregister_process_group(proc.pid)

    success_when = run.success_when if run else None
    if success_when is not None:
        success = evaluate(success_when, ctx.expression_context(exit_code=exit_code, output=output))
    else:
        success = exit_code == 0

    if not success:
        return StepResult(False, f"{tool.display_name} did not report success (exit code {exit_code})")
    return StepResult(True)
