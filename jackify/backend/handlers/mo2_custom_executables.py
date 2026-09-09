"""
Reads MO2's [customExecutables] section from ModOrganizer.ini to find candidate
executables for the "MO2 Skip" launch shortcut (moshortcut://).

Deliberately does line-by-line scanning rather than configparser, matching the
existing [customExecutables] handling in path_handler_mo2.py - MO2 ini values can
contain '%' characters (paths, arguments) that trip configparser's default
interpolation.
"""
import logging
import os
import re
from pathlib import Path
from typing import List, Optional, TypedDict, Union

logger = logging.getLogger(__name__)

_SECTION_RE = re.compile(r'^\s*\[customExecutables\]\s*$', re.IGNORECASE)
_ANY_SECTION_RE = re.compile(r'^\s*\[.*\]\s*$')
_ENTRY_KEY_RE = re.compile(r'^(\d+)\\(title|binary|hide)\s*=\s*(.*)$', re.IGNORECASE)

# Known script-extender loader executables across Jackify-supported games. Purpose-
# specific to this picker - not shared with path_handler_mo2.py's TARGET_EXEC_LOWER,
# which serves an unrelated gamePath-rewrite feature.
KNOWN_LAUNCH_EXE_NAMES = {
    "skse64_loader.exe", "skse_loader.exe",  # Skyrim SE/LE, SkyrimVR
    "f4se_loader.exe",                        # Fallout4, Fallout4VR
    "nvse_loader.exe",                        # FalloutNV
    "fose_loader.exe",                        # Fallout3
    "obse_loader.exe", "obse64_loader.exe",   # Oblivion
    "sfse_loader.exe",                        # Starfield
}


class LaunchCandidate(TypedDict):
    index: int
    title: str
    binary: str


def _strip_quotes(value: str) -> str:
    return value.strip().strip('"')


def _binary_basename(binary: str) -> str:
    return os.path.basename(_strip_quotes(binary).replace('\\', '/')).lower()


def list_custom_executables(modlist_ini_path: Union[str, Path]) -> List[LaunchCandidate]:
    """Parse every visible (hide != true) entry from [customExecutables]."""
    modlist_ini_path = Path(modlist_ini_path)
    if not modlist_ini_path.is_file():
        logger.debug(f"No ModOrganizer.ini found at {modlist_ini_path}")
        return []

    entries: dict = {}
    in_section = False
    try:
        with open(modlist_ini_path, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                stripped = line.strip()
                if _SECTION_RE.match(stripped):
                    in_section = True
                    continue
                if in_section and _ANY_SECTION_RE.match(stripped):
                    break
                if not in_section:
                    continue
                m = _ENTRY_KEY_RE.match(stripped)
                if not m:
                    continue
                idx, key, value = int(m.group(1)), m.group(2).lower(), m.group(3)
                entries.setdefault(idx, {})[key] = value
    except Exception as e:
        logger.warning(f"Failed to read customExecutables from {modlist_ini_path}: {e}")
        return []

    candidates: List[LaunchCandidate] = []
    for idx in sorted(entries):
        entry = entries[idx]
        if entry.get('hide', 'false').strip().lower() == 'true':
            continue
        title = entry.get('title', '').strip()
        binary = entry.get('binary', '').strip()
        if not title or not binary:
            continue
        candidates.append({"index": idx, "title": title, "binary": binary})
    return candidates


def list_launch_candidates(modlist_ini_path: Union[str, Path]) -> List[LaunchCandidate]:
    """
    Visible customExecutables entries, preferring script-extender loaders (the real
    "play the modlist" targets) over MO2's own generated helper entries.

    Falls back to all visible entries if no known loader executable is present, so
    the picker still works for games without a script extender.
    """
    visible = list_custom_executables(modlist_ini_path)
    loaders = [c for c in visible if _binary_basename(c["binary"]) in KNOWN_LAUNCH_EXE_NAMES]
    return loaders if loaders else visible
