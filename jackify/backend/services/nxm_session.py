"""NXM session state: remembers which modlist to route downloads to.

Clears when the process exits. Not persisted to disk.
"""

import logging
import re
from pathlib import Path
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)

_remembered_modlist: Optional[str] = None


def get_remembered_modlist() -> Optional[str]:
    return _remembered_modlist


def set_remembered_modlist(name: str) -> None:
    global _remembered_modlist
    _remembered_modlist = name


def clear_remembered_modlist() -> None:
    global _remembered_modlist
    _remembered_modlist = None


def detect_active_mo2_modlist(modlists: List[Dict]) -> Optional[Dict]:
    """Return the modlist whose MO2 instance is currently running, or None.

    Scans live processes for ModOrganizer.exe and matches the install path
    against the provided modlist list.
    """
    try:
        import psutil
    except ImportError:
        logger.debug("psutil not available, skipping MO2 process detection")
        return None

    mo2_dirs: List[Path] = []
    try:
        for proc in psutil.process_iter(["cmdline"]):
            try:
                cmdline = proc.info.get("cmdline") or []
                for arg in cmdline:
                    arg_str = str(arg)
                    if "ModOrganizer.exe" in arg_str:
                        resolved = _resolve_mo2_path(arg_str)
                        if resolved:
                            mo2_dirs.append(resolved)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception as e:
        logger.debug("MO2 process scan failed: %s", e)
        return None

    if not mo2_dirs:
        return None

    matches = []
    for modlist in modlists:
        ml_dir = Path(modlist.get("modlist_dir", "")).resolve()
        for mo2_dir in mo2_dirs:
            try:
                if mo2_dir.resolve() == ml_dir:
                    matches.append(modlist)
                    break
            except Exception:
                continue

    if len(matches) == 1:
        logger.debug("Active MO2 instance matched modlist: %s", matches[0].get("name"))
        return matches[0]

    if len(matches) > 1:
        logger.debug("Multiple active MO2 instances found, falling back to picker")
    else:
        logger.debug("MO2 process found but no modlist match for dirs: %s", mo2_dirs)
    return None


def _resolve_mo2_path(arg: str) -> Optional[Path]:
    """Extract and resolve the modlist directory from a ModOrganizer.exe cmdline arg."""
    # Wine path: Z:\path\to\modlist\ModOrganizer.exe
    m = re.match(r"(?i)z:([\\/].+?)[\\/]ModOrganizer\.exe", arg)
    if m:
        linux_path = m.group(1).replace("\\", "/")
        return Path(linux_path)

    # Raw Linux path: /path/to/modlist/ModOrganizer.exe
    m = re.match(r"(/.+?)/ModOrganizer\.exe", arg)
    if m:
        return Path(m.group(1))

    return None
