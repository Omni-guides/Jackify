"""Resolve the real game directory inside a modlist's Stock Game style folder."""

import logging
import re
from collections import deque
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

GAME_EXES = frozenset({
    'skyrimse.exe', 'skyrim.exe', 'skyrimvr.exe', 'fallout4.exe', 'fallout4vr.exe',
    'falloutnv.exe', 'fallout3.exe', 'oblivion.exe', 'morrowind.exe', 'starfield.exe',
    'enderal launcher.exe', 'bg3.exe', 'cyberpunk2077.exe',
})

_SKIP_DIRS = frozenset({'data', 'mods', 'profiles', 'downloads', 'overwrite'})
_MAX_DEPTH = 3


def _has_game_exe(directory: Path) -> bool:
    try:
        return any(p.name.lower() in GAME_EXES for p in directory.iterdir() if p.is_file())
    except OSError:
        return False


def find_game_dir(start: Path, max_depth: int = _MAX_DEPTH) -> Optional[Path]:
    """Breadth-first search below start (inclusive) for the folder holding the game exe."""
    queue = deque([(start, 0)])
    while queue:
        current, depth = queue.popleft()
        if _has_game_exe(current):
            return current
        if depth >= max_depth:
            continue
        try:
            children = sorted(p for p in current.iterdir()
                              if p.is_dir() and p.name.lower() not in _SKIP_DIRS)
        except OSError:
            continue
        queue.extend((child, depth + 1) for child in children)
    return None


def game_dir_from_ini(modlist_dir: Path, ini_path: Optional[Path]) -> Optional[Path]:
    """Return MO2's gamePath as a Linux path when it points inside the modlist folder."""
    if not ini_path or not Path(ini_path).is_file():
        return None
    try:
        content = Path(ini_path).read_text(encoding='utf-8', errors='ignore')
    except OSError:
        return None
    match = re.search(r'^gamePath\s*=\s*@ByteArray\((.*)\)\s*$', content,
                      re.MULTILINE | re.IGNORECASE)
    if not match:
        return None
    raw = re.sub(r'\\+', '/', match.group(1).strip())
    if not raw.upper().startswith('Z:'):
        return None
    candidate = Path(raw[2:])
    try:
        candidate.relative_to(modlist_dir)
    except ValueError:
        return None
    return candidate if candidate.is_dir() and _has_game_exe(candidate) else None


def resolve_game_dir(modlist_dir: Path, name_match: Optional[Path],
                     ini_path: Optional[Path] = None) -> Optional[Path]:
    """Pick the actual game directory, whatever the modlist author called its folders.

    Order: MO2's own gamePath, then the game exe found below the name-matched
    folder, then the name-matched folder itself.
    """
    from_ini = game_dir_from_ini(Path(modlist_dir), ini_path)
    if from_ini:
        return from_ini
    if name_match:
        found = find_game_dir(Path(name_match))
        if found:
            return found
    return name_match
