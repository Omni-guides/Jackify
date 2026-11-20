"""Checks that a modlist folder is complete enough to configure."""
from pathlib import Path
from typing import Optional


def incomplete_install_reason(install_dir: str) -> Optional[str]:
    """Return a plain explanation when the folder is not a finished modlist install, else None."""
    root = Path(install_dir)
    if not root.is_dir():
        return f"The modlist folder does not exist: {root}"
    if not (root / "ModOrganizer.ini").is_file():
        return (
            f"ModOrganizer.ini is missing from {root}. This looks like an incomplete install, "
            "so there is nothing to configure yet. Finish the install first."
        )
    return None
