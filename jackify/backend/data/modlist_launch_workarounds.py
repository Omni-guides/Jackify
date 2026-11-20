"""Temporary per-modlist Steam launch option workarounds.

Remove an entry once the underlying cause is fixed upstream.
"""

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Steam client build 1794424036 (Nov 2026) stops delivering the text-input result to
# ShowGamepadTextInput under Proton on Steam Deck, so Skyrim character naming fails.
# SteamDeck=0 makes the game use its own naming dialog instead. Remove once Valve fixes it.
TUXBORN_DECK_NAMING_ENV = "SteamDeck=0"

_TUXBORN_KEYWORD = "tuxborn"
# Both the full package and Tuxborn Low Only ship these two profiles, so their presence
# identifies either variant for gallery and .wabbajack installs alike.
_TUXBORN_LOW_PROFILES = ("Tuxborn - Low-Deck", "Tuxborn MCO - Low-Deck")


def is_tuxborn_install(shortcut_name: str, install_dir: str) -> bool:
    """True if any independent signal says this install is Tuxborn (full or Low Only)."""
    if install_dir:
        root = Path(install_dir)
        try:
            if any((root / "profiles" / name).is_dir() for name in _TUXBORN_LOW_PROFILES):
                return True
            if any(root.glob("Tuxborn*.compiler_settings")):
                return True
        except OSError:
            pass
    return _TUXBORN_KEYWORD in (shortcut_name or "").lower()


def get_modlist_launch_env(shortcut_name: str, install_dir: str, is_steamdeck: bool) -> Optional[str]:
    """Extra env assignments to prepend to the launch options, or None."""
    if is_steamdeck and is_tuxborn_install(shortcut_name, install_dir):
        logger.info("Tuxborn on Steam Deck detected - adding %s to launch options", TUXBORN_DECK_NAMING_ENV)
        return TUXBORN_DECK_NAMING_ENV
    return None
