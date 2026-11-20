"""
Locating files the user has to supply themselves (login-gated downloads) for `extract_archive`
steps: a lookup in the usual download folders by filename hint, so the GUI/CLI only has to ask
the user when nothing is found.
"""
import logging
import os
from pathlib import Path
from typing import Iterable, List, Optional

logger = logging.getLogger(__name__)

_ARCHIVE_SUFFIXES = {".zip", ".7z", ".rar"}


def default_download_dirs() -> List[Path]:
    """Configured watch directory first, then the XDG download directory, then ~/Downloads."""
    candidates: List[Path] = []
    try:
        from jackify.backend.handlers.config_handler import ConfigHandler
        configured = ConfigHandler().get("manual_download_watch_directory", None)
        if configured:
            candidates.append(Path(str(configured)).expanduser())
    except Exception as e:
        logger.debug("Could not read manual_download_watch_directory: %s", e)
    xdg = os.environ.get("XDG_DOWNLOAD_DIR", "")
    if xdg:
        candidates.append(Path(xdg).expanduser())
    candidates.append(Path.home() / "Downloads")
    seen, result = set(), []
    for directory in candidates:
        if directory.is_dir() and directory not in seen:
            seen.add(directory)
            result.append(directory)
    return result


def find_user_archive(name_contains: Iterable[str], search_dirs: Optional[Iterable[Path]] = None) -> Optional[Path]:
    """Newest top-level archive whose filename contains every one of `name_contains` (case-insensitive)."""
    needles = [n.lower() for n in name_contains if n]
    if not needles:
        return None
    best: Optional[Path] = None
    best_mtime = -1.0
    for directory in (search_dirs if search_dirs is not None else default_download_dirs()):
        try:
            entries = list(Path(directory).iterdir())
        except OSError:
            continue
        for path in entries:
            if path.suffix.lower() not in _ARCHIVE_SUFFIXES or not path.is_file():
                continue
            name = path.name.lower()
            if not all(n in name for n in needles):
                continue
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if mtime > best_mtime:
                best, best_mtime = path, mtime
    return best
