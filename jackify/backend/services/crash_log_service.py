"""Locate and open script-extender crash logs for installed modlists.

Crash loggers write into the script extender's log directory inside the Wine prefix,
alongside every other plugin's log - a real prefix here held 168 files of which two
were crashes. So crash logs are matched by filename rather than by opening the folder.

Only game types whose crash log location is confirmed are listed. Adding one is a
single CRASH_LOG_SOURCES entry, but it should be backed by an actual observed crash
log rather than assumed from the game's script extender.
"""

import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# game_type -> (My Games subdirectory, script extender log subdirectory)
# Both confirmed by observed crash-*.log files in real prefixes.
CRASH_LOG_SOURCES: Dict[str, tuple] = {
    "skyrim": ("Skyrim Special Edition", "SKSE"),
    "fallout4": ("Fallout4", "F4SE"),
}

CRASH_LOG_PATTERN = "crash-*.log"

_DOCUMENTS_SUBPATH = "drive_c/users/steamuser/Documents/My Games"

# xdg-open and the file manager it launches are system binaries; the AppImage's
# bundled Qt and loader paths break them. Same stripping the OAuth browser launch uses.
_GRAPHICAL_CONFLICT_VARS = (
    "LD_LIBRARY_PATH",
    "PYTHONPATH",
    "PYTHONHOME",
    "QT_PLUGIN_PATH",
    "QML2_IMPORT_PATH",
)


@dataclass
class CrashLog:
    path: Path
    modified: float

    @property
    def name(self) -> str:
        return self.path.name


def supports_crash_logs(game_type: Optional[str]) -> bool:
    return game_type in CRASH_LOG_SOURCES


def get_extender_name(game_type: Optional[str]) -> Optional[str]:
    """Return the script extender name (SKSE, F4SE) for a supported game type, or None."""
    source = CRASH_LOG_SOURCES.get(game_type)
    return source[1] if source else None


def get_crash_log_dir(pfx: Optional[Path], game_type: Optional[str]) -> Optional[Path]:
    """Return the script extender log directory for a prefix, or None if unsupported."""
    if not pfx or not supports_crash_logs(game_type):
        return None
    game_dir, extender_dir = CRASH_LOG_SOURCES[game_type]
    return Path(pfx) / _DOCUMENTS_SUBPATH / game_dir / extender_dir


def list_crash_logs(pfx: Optional[Path], game_type: Optional[str]) -> List[CrashLog]:
    """Crash logs for a modlist, newest first. Empty when none or unsupported."""
    log_dir = get_crash_log_dir(pfx, game_type)
    if not log_dir or not log_dir.is_dir():
        return []
    logs = []
    for path in log_dir.glob(CRASH_LOG_PATTERN):
        if not path.is_file():
            continue
        try:
            logs.append(CrashLog(path=path, modified=path.stat().st_mtime))
        except OSError as e:
            logger.debug("Could not stat crash log %s: %s", path, e)
    return sorted(logs, key=lambda c: c.modified, reverse=True)


def find_modlists_with_crash_logs() -> List[Dict]:
    """Installed modlists whose game type is supported and whose prefix exists.

    Reuses the shortcut-based discovery the Install Verifier already uses.
    """
    try:
        from jackify.tools.verify_install import discover_installed_modlists
        modlists = discover_installed_modlists()
    except Exception as e:
        logger.error("Could not discover installed modlists: %s", e)
        return []

    eligible = []
    for entry in modlists:
        if not supports_crash_logs(entry.get("game_type")):
            continue
        pfx = entry.get("pfx")
        if not pfx or not Path(pfx).is_dir():
            continue
        eligible.append(entry)
    return eligible


def open_path(target: Path) -> bool:
    """Open a file or directory with the system handler. Returns False on failure."""
    target = Path(target)
    if not target.exists():
        logger.warning("Cannot open missing path: %s", target)
        return False
    try:
        from jackify.backend.handlers.subprocess_utils import get_clean_subprocess_env
        env = get_clean_subprocess_env()
    except Exception:
        env = os.environ.copy()

    for var in _GRAPHICAL_CONFLICT_VARS:
        env.pop(var, None)

    try:
        subprocess.Popen(
            ["xdg-open", str(target)],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        logger.info("Opened %s", target)
        return True
    except FileNotFoundError:
        logger.error("xdg-open not found - cannot open %s", target)
        return False
    except Exception as e:
        logger.error("Failed to open %s: %s", target, e)
        return False
