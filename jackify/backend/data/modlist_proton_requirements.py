"""Per-modlist Proton version requirements for ENB compatibility warnings."""

from typing import Optional

# Keys are lowercase modlist names (matched case-insensitively).
# required: specific Proton build known to work
# note: shown to the user alongside the requirement
MODLIST_PROTON_REQUIREMENTS: dict[str, dict[str, str]] = {
    "lorerim": {
        "required": "GE-Proton10-34",
        "note": "Proton-CachyOS 11 and Valve Proton are known to not work with this list.",
    },
}


def get_proton_requirement(modlist_name: str) -> Optional[dict[str, str]]:
    if not modlist_name:
        return None
    return MODLIST_PROTON_REQUIREMENTS.get(modlist_name.strip().lower())
