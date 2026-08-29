"""
Path variable resolution for the playbook system.

Every playbook path starts with a variable ({modlist_dir}, {game_root}, etc.) and is resolved
against a caller-supplied set of roots. This is the single choke point every playbook file
operation goes through, so it is deliberately paranoid: `..` traversal, absolute-path smuggling,
NUL bytes, and symlink escapes are all rejected before the path is used for anything. See
docs/0.8_work/modlist_playbook_system.md section 4.5.
"""
import re
from pathlib import Path
from typing import Dict

_VARIABLE_RE = re.compile(r'^\{([a-zA-Z_][a-zA-Z0-9_]*(?::[a-zA-Z0-9_.-]+)?)\}(/.*)?$')


class PlaybookPathError(ValueError):
    """A playbook-supplied path failed variable resolution or would escape its root."""


def resolve_path(template: str, roots: Dict[str, Path]) -> Path:
    """
    Resolve a playbook path template such as "{modlist_dir}/sub/dir" against known roots.

    Args:
        template: The path string as written in a playbook.
        roots: Map of variable name (without braces, e.g. "modlist_dir" or "asset:some-id")
               to an existing root directory.

    Returns:
        The resolved, realpath'd absolute Path, guaranteed to be inside the matched root.

    Raises:
        PlaybookPathError: for anything that isn't a clean relative path under a known root.
    """
    if not isinstance(template, str) or not template:
        raise PlaybookPathError("path must be a non-empty string")

    match = _VARIABLE_RE.match(template)
    if not match:
        raise PlaybookPathError(f"path must start with a known {{variable}}: {template!r}")

    variable, remainder = match.group(1), match.group(2) or ""

    root = roots.get(variable)
    if root is None:
        raise PlaybookPathError(f"unknown path variable: {{{variable}}}")

    if "\x00" in remainder:
        raise PlaybookPathError("path contains a NUL byte")
    if ".." in remainder.split("/"):
        raise PlaybookPathError(f"path contains '..': {template!r}")
    if "~" in remainder:
        raise PlaybookPathError(f"path contains '~': {template!r}")

    # remainder is "" or starts with "/" per the regex; strip all leading slashes so it can
    # never be (mis)treated as an absolute path when joined below.
    relative = remainder.lstrip("/")

    root_real = Path(root).resolve()
    candidate = (root_real / relative) if relative else root_real
    candidate_real = candidate.resolve()

    try:
        candidate_real.relative_to(root_real)
    except ValueError:
        raise PlaybookPathError(f"path escapes its root (symlink or traversal): {template!r}")

    return candidate_real
