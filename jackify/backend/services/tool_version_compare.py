"""Direction-aware version comparison for Tools Hub update checks."""
import re
from typing import Optional

from packaging.version import InvalidVersion, Version


def is_tool_update_available(latest: str, installed: str) -> bool:
    """True only if the latest published tag is a strictly greater ordered version than
    installed. A plain inequality check flags a locally-installed dev build newer than the
    latest published release (e.g. installed 0.5.9, latest v0.5.8) as an update, which is
    backwards. Unparseable versions return False rather than raising, since "cannot tell"
    must not present as an update either."""
    try:
        return Version(latest.lstrip("v")) > Version(installed.lstrip("v"))
    except InvalidVersion:
        return False


def guess_version_from_filename(filename: str) -> Optional[str]:
    """Best-effort fallback when no Nexus session is available to look up the real version:
    Nexus filenames for these tools carry an x.y or x.y.z token (e.g. "... 0.2.1 2026-...")."""
    match = re.search(r"\d+\.\d+(?:\.\d+)?", filename)
    return match.group(0) if match else None
