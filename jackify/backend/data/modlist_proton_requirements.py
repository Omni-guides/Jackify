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


# Keys are lowercase modlist names. Overrides the per-game recommendation.
# recommended: Proton builds in order of recommendation
MODLIST_PROTON_WARNINGS: dict[str, dict] = {
    "nuclear sunset": {
        "recommended": ["GE-Proton10-14"],
    },
}


def get_proton_warning(modlist_name: str, game_type: str, install_dir: str = "") -> Optional[dict]:
    if modlist_name:
        warning = MODLIST_PROTON_WARNINGS.get(modlist_name.strip().lower())
        if warning:
            return warning
    if install_dir:
        from jackify.backend.services.playbook.hook_wiring import get_proton_recommendation
        warning = get_proton_recommendation(install_dir, modlist_name or "", game_type or None)
        if warning:
            return warning
    return get_game_proton_warning(game_type)
