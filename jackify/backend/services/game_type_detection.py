"""Canonical game type detection, consolidating what used to be independent implementations
scattered across the CLI, GUI, and several backend services (each with its own vocabulary and
its own gaps - notably FNV/Enderal/etc being missed by the loader-executable-only scan).

Two entry points, both returning a jackify.backend.models.game_types canonical short key
(or None): detect_pre_install() for before any files exist on disk (.wabbajack metadata or a
gallery listing), and detect_from_install() for ground truth - the installed modlist's own
ModOrganizer.ini.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Union

from jackify.backend.models.game_types import normalize_game_name

logger = logging.getLogger(__name__)

# ModlistHandler.detect_special_game_type() predates this module and is called directly by
# several other sites with these exact strings - its own return values are not changed here.
# Only these two differ from game_types.py's canonical vocabulary; everything else it returns
# (enderal, cp2077, bg3, skyrimvr, fallout4vr) already matches.
_SPECIAL_TYPE_TO_CANONICAL = {
    "fnv": "falloutnv",
    "fo3": "fallout3",
}

# Last-resort content scan when gameName= is missing or unrecognized. Precise loader-exe
# filenames are checked first, across every game, before any loose word marker - issue #238
# was a Starfield modlist misdetected as Oblivion because the loose "oblivion" word matched a
# cross-game MO2 plugin name ("Oblivion Support Plugin") before "starfield" was even reached.
# A precise marker like sfse_loader.exe won't collide with unrelated plugin/mod names the way
# a bare game-name word can, so it must always win over a later game's loose word match.
# sksevr_loader.exe/f4sevr_loader.exe added after a FUS (Skyrim VR) modlist was found
# misdetected as Oblivion this same way - detect_special_game_type()'s own gameName= check
# for skyrimvr never matched (Wabbajack's packaged gameName= for VR modlists is inconsistent),
# so it fell through to this scan, which had no VR-aware marker at all to compete with
# whatever "oblivion" substring won by default.
# bg3.exe/cyberpunk2077.exe/enderal launcher.exe added at the same time, closing the same
# gap for the two game types (bg3, cp2077) that previously had no entry here at all, and
# for enderal, whose only entry was a bare loose word sitting after "oblivion" below -
# every game type detect_special_game_type() knows about now also has a precise marker
# here, so none of them can lose to a loose "oblivion" word by default.
_LOADER_MARKERS = (
    ("skse64_loader.exe", "skyrim"),
    ("f4se_loader.exe", "fallout4"),
    ("nvse_loader.exe", "falloutnv"),
    ("fose_loader.exe", "fallout3"),
    ("obse_loader.exe", "oblivion"),
    ("obse64_loader.exe", "oblivion_remastered"),
    ("sfse_loader.exe", "starfield"),
    ("sksevr_loader.exe", "skyrimvr"),
    ("f4sevr_loader.exe", "fallout4vr"),
    ("enderal launcher.exe", "enderal"),
    ("bg3.exe", "bg3"),
    ("bg3_dx11.exe", "bg3"),
    ("cyberpunk2077.exe", "cp2077"),
    ("skyrim special edition", "skyrim"),
    ("fallout 4", "fallout4"),
    ("fallout new vegas", "falloutnv"),
    ("fallout 3", "fallout3"),
    ("oblivion", "oblivion"),
    ("starfield", "starfield"),
    ("enderal", "enderal"),
)


def detect_pre_install(
    wabbajack_path: Optional[Union[str, Path]] = None,
    gallery_info: Optional[dict] = None,
) -> Optional[str]:
    """Detect game type before install runs, from .wabbajack metadata or a gallery listing.

    File mode returns 'unknown' (not None) when the .wabbajack parses fine but names a Wabbajack
    Game enum value Jackify doesn't recognize - callers use that sentinel to still surface the
    unsupported-game notice rather than silently skipping it. Gallery mode returns None on a
    miss; callers that need the same 'unknown' sentinel apply it themselves.
    """
    if wabbajack_path is not None:
        from jackify.backend.handlers.wabbajack_parser import WabbajackParser
        result = WabbajackParser().parse_wabbajack_game_type(Path(wabbajack_path))
        if not result:
            return None
        if isinstance(result, tuple):
            game_type, _raw = result
            return game_type
        return result

    if gallery_info:
        return normalize_game_name(gallery_info.get('game', ''))

    return None


def detect_from_install(install_dir: Union[str, Path]) -> Optional[str]:
    """Ground-truth game type from an installed modlist's own ModOrganizer.ini.

    Signals checked in order, most direct first: (a) FNV/FO3/Enderal/etc special cases via
    ModlistHandler.detect_special_game_type(), (b) the ini's own gameName= declaration, (c) a
    last-resort loader-executable content scan for profiles with a missing/unrecognized
    gameName=.
    """
    install_path = Path(install_dir)

    try:
        from jackify.backend.handlers.modlist_handler import ModlistHandler
        special = ModlistHandler().detect_special_game_type(str(install_path))
        if special:
            return _SPECIAL_TYPE_TO_CANONICAL.get(special, special)
    except Exception as e:
        logger.debug("Special game type detection failed for %s: %s", install_path, e)

    ini_path = next(
        (p for p in (install_path / "ModOrganizer.ini", install_path / "files" / "ModOrganizer.ini")
         if p.is_file()),
        None,
    )
    if ini_path is None:
        return None

    try:
        content = ini_path.read_text(encoding='utf-8', errors='ignore').lower()
    except Exception as e:
        logger.debug("Could not read %s: %s", ini_path, e)
        return None

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        # MO2 itself re-saves this file via Qt's QSettings, which writes "key = value"
        # (spaces around "="), not the unspaced "key=value" a freshly-packaged modlist ships
        # with - match on the key alone so both formats work (issue #238).
        if key.strip() == "gamename":
            canonical = normalize_game_name(value.strip())
            if canonical:
                return canonical
            break

    for marker, canonical in _LOADER_MARKERS:
        if marker in content:
            return canonical

    return None
