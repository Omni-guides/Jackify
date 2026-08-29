"""
run_modlist_script step: run a `.bat`/`.cmd` file the modlist itself ships (MEW's Radio Fix).

This is the widest surface in the system, and that is by design, not oversight: it runs a
script the modlist author shipped, under the modlist's own Wine prefix - the same thing a user
running the modlist's manual instructions would do. The playbook cannot supply or modify the
script, only point at one already present in the install. Timeout capped at 1800s regardless of
what the step requests; process group is killed on timeout, matching the rest of the system.
"""
import logging
import os
import signal
import subprocess
from pathlib import Path
from typing import Optional

from jackify.backend.handlers.subprocess_utils import (
    get_clean_subprocess_env,
    register_process_group,
    unregister_process_group,
)
from ..expressions import evaluate
from ..paths import PlaybookPathError
from ..schema import Step
from .base import StepContext, StepResult, default_completed, stream_subprocess_output

logger = logging.getLogger(__name__)

completed = default_completed

_MAX_TIMEOUT = 1800
_ALLOWED_EXTENSIONS = (".bat", ".cmd")


def _find_wine_binary() -> Optional[str]:
    """
    Locate a wine binary from the configured Proton install.

    Same lookup ModlistWineOpsMixin._find_wine_binary_for_registry() uses; duplicated here
    (rather than instantiating that mixin's host class) since it has no other dependency.
    """
    try:
        from jackify.backend.handlers.config_handler import ConfigHandler
        proton_path = ConfigHandler().get_proton_path()
        if proton_path:
            proton_path = Path(proton_path).expanduser()
            for candidate in (proton_path / "files" / "bin" / "wine", proton_path / "dist" / "bin" / "wine"):
                if candidate.is_file():
                    return str(candidate)

        from jackify.backend.handlers.wine_utils import WineUtils
        best_proton = WineUtils.select_best_proton()
        if best_proton:
            return WineUtils.find_proton_binary(best_proton['name'])
    except Exception as e:
        logger.debug(f"Error finding Wine binary for run_modlist_script: {e}")
    return None


def execute(ctx: StepContext, step: Step) -> StepResult:
    fields = step.fields
    script_template = fields.get("script", "")
    if not script_template.startswith("{modlist_dir}"):
        return StepResult(False, "run_modlist_script: script must be inside {modlist_dir}")

    try:
        script_path = ctx.resolve(script_template)
    except PlaybookPathError as e:
        return StepResult(False, f"run_modlist_script: invalid script path: {e}")

    if script_path.suffix.lower() not in _ALLOWED_EXTENSIONS:
        return StepResult(False, "run_modlist_script: script must be .bat or .cmd")
    if not script_path.is_file():
        return StepResult(False, f"run_modlist_script: script not found: {script_path}")

    prefix = ctx.roots.get("prefix")
    if not prefix:
        return StepResult(False, "run_modlist_script: no Wine prefix available")

    wine_bin = _find_wine_binary()
    if not wine_bin:
        return StepResult(False, "run_modlist_script: no Wine binary available")

    timeout_seconds = min(int(fields.get("timeout_seconds", _MAX_TIMEOUT)), _MAX_TIMEOUT)

    env = get_clean_subprocess_env()
    env["WINEPREFIX"] = str(prefix)
    env["WINEDEBUG"] = "-all"

    ctx.log(f"Running {step.label}...")
    last_line = None

    def _on_line(line: str) -> None:
        nonlocal last_line
        text = line.strip()
        if not text or text == last_line:
            return
        last_line = text
        ctx.log(f"{step.label}: {text}")

    try:
        proc = subprocess.Popen(
            [wine_bin, "cmd", "/c", script_path.name],
            cwd=str(script_path.parent), env=env,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            start_new_session=True,
        )
    except OSError as e:
        return StepResult(False, f"run_modlist_script: failed to start: {e}")

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
        return StepResult(False, f"run_modlist_script: timed out after {timeout_seconds}s")
    finally:
        unregister_process_group(proc.pid)

    success_when = fields.get("success_when")
    if success_when is not None:
        success = evaluate(success_when, ctx.expression_context(exit_code=exit_code, output=output))
    else:
        success = exit_code == 0

    if not success:
        failure_message = fields.get("failure_message") or "script did not report success"
        return StepResult(False, failure_message)
    return StepResult(True)
