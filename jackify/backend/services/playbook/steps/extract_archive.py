"""
extract_archive step: extract an archive the user supplied into a modlist directory.

The archive itself cannot be fetched by Jackify (login-gated hosts), so the GUI/CLI layer asks the
user for it before the hook runs and records it in `ctx.user_files[archive_id]`. `name_contains`
and `prompt` are hints for that earlier lookup; this step only does the extraction. A missing
archive is a plain step failure, handled by the step's `on_failure` like any other.
"""
import logging
import subprocess
import zipfile
from pathlib import Path

from jackify.backend.handlers.subprocess_utils import get_clean_subprocess_env
from jackify.backend.services.tool_registry import _find_7z_binary
from ..paths import PlaybookPathError
from .base import StepContext, StepResult, default_completed

logger = logging.getLogger(__name__)

completed = default_completed

_EXTRACT_TIMEOUT = 900


def _extract(archive: Path, dest: Path) -> bool:
    dest.mkdir(parents=True, exist_ok=True)
    try:
        if archive.suffix.lower() == ".zip":
            with zipfile.ZipFile(archive, "r") as zf:
                zf.extractall(dest)
            return True
        sevenzip = _find_7z_binary()
        if not sevenzip:
            logger.warning("7z binary not available, cannot extract %s", archive)
            return False
        result = subprocess.run(
            [sevenzip, "x", "-y", f"-o{dest}", str(archive)],
            env=get_clean_subprocess_env(), capture_output=True, text=True, timeout=_EXTRACT_TIMEOUT,
        )
        return result.returncode == 0
    except Exception as e:
        logger.warning("Extraction failed for %s: %s", archive, e)
        return False


def execute(ctx: StepContext, step) -> StepResult:
    archive_id = step.fields.get("archive_id")
    dest_template = step.fields.get("dest")
    if not archive_id or not dest_template:
        return StepResult(False, "extract_archive: archive_id and dest are required")

    archive = ctx.user_files.get(archive_id)
    if archive is None or not Path(archive).is_file():
        return StepResult(False, "the archive was not provided")

    try:
        dest = ctx.resolve(dest_template)
    except PlaybookPathError as e:
        return StepResult(False, f"extract_archive: bad dest: {e}")

    ctx.log(f"Extracting {Path(archive).name}")
    if not _extract(Path(archive), dest):
        return StepResult(False, f"could not extract {Path(archive).name}")
    return StepResult(True)
