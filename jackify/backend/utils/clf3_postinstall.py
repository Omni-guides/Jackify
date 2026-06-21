"""
Post-install fixups applied after a CLF3 install completes.
"""
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_SDCARD_RE = re.compile(r'^/run/media/')


def _linux_to_wine_path(path_str: str) -> str:
    """Convert an absolute Linux path to a Wine-format path (Z: or D: for SD card)."""
    if _SDCARD_RE.match(path_str):
        from jackify.backend.handlers.wine_utils import WineUtils
        stripped = WineUtils._strip_sdcard_path(path_str).lstrip('/')
        return "D:\\" + stripped.replace('/', '\\')
    return "Z:\\" + path_str.lstrip('/').replace('/', '\\')


def inject_mo2_download_dir(install_dir: str, downloads_dir: str) -> None:
    """Ensure ModOrganizer.ini contains download_directory pointing at downloads_dir.

    Some modlists ship a bundled ModOrganizer.ini that omits download_directory.
    MO2 then defaults to its own internal path, causing it to report all downloads
    as missing on first launch. This injects the correct path if absent.
    """
    ini_path = Path(install_dir) / "ModOrganizer.ini"
    if not ini_path.exists():
        return

    content = ini_path.read_text(encoding="utf-8", errors="replace")

    if "download_directory=" in content.lower():
        return

    wine_path = _linux_to_wine_path(str(downloads_dir))
    entry = f"download_directory={wine_path}"

    lines = content.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.strip().lower() == "[general]":
            lines.insert(i + 1, entry + "\n")
            ini_path.write_text("".join(lines), encoding="utf-8")
            logger.info(f"Injected download_directory into {ini_path}: {wine_path}")
            return

    logger.debug(f"ModOrganizer.ini has no [General] section, skipping injection: {ini_path}")
