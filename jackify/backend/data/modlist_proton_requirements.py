"""Per-modlist and per-game Proton version requirements/warnings."""

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


# Keys are lowercase game_type identifiers (e.g. "falloutnv", "fallout_new_vegas").
# recommended: Proton builds recommended for this game, in order of recommendation
GAME_PROTON_WARNINGS: dict[str, dict] = {
    "falloutnv": {
        "recommended": ["GE-Proton10-14", "Proton Experimental (latest)", "Proton-CachyOS"],
    },
    "fallout_new_vegas": {
        "recommended": ["GE-Proton10-14", "Proton Experimental (latest)", "Proton-CachyOS"],
    },
}


def get_game_proton_warning(game_type: str) -> Optional[dict]:
    if not game_type:
        return None
    return GAME_PROTON_WARNINGS.get(game_type.strip().lower())
