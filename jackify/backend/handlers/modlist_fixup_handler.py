"""Modlist fixup handler.

Applies known binary fixes to installed modlists during the configure phase.
Each fix is idempotent: it checks the current state before acting and skips
if the fix is already in place.
"""
import hashlib
import logging
import os
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from jackify.shared.paths import get_jackify_data_dir

logger = logging.getLogger(__name__)

# JContainers SE - Linux crash fix
# Nexus releases up to and including 4.2.9.0 crash on Linux.
# Fixed build from https://github.com/rfortier/JContainers-rwf (pending Nexus release).
# We replace the DLL in-place in whichever mod directory ships it.
_JCONTAINERS_FIXED_SHA256 = "4c00d7194c61097361e8f93521d79752a975fca5f54446e391debb0c56999590"
_JCONTAINERS_FIXED_URL = (
    "https://github.com/rfortier/JContainers-rwf/releases/download/v4.2.13.2/"
    "JContainers64-v4.2.13.2.for.1.6.1170.patch.luajit.with.gc64.7z"
)
_JCONTAINERS_DLL_NAME = "JContainers64.dll"
_JCONTAINERS_ARCHIVE_NAME = "JContainers64-v4.2.13.2.linux-fix.7z"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _get_7z() -> Optional[Path]:
    candidates = []
    appdir = os.environ.get("APPDIR")
    if appdir:
        candidates.append(Path(appdir) / "opt" / "jackify" / "tools" / "7z")
    candidates.append(Path(__file__).parent.parent.parent / "tools" / "7z")
    for p in candidates:
        if p.exists() and os.access(p, os.X_OK):
            return p
    return None


def _find_dll_in_archive(seven_z: Path, archive: Path) -> Optional[str]:
    """Return the internal path of JContainers64.dll within the archive, or None."""
    try:
        result = subprocess.run(
            [str(seven_z), "l", "-ba", "-slt", str(archive)],
            capture_output=True, text=True, timeout=30,
        )
        for line in result.stdout.splitlines():
            if line.startswith("Path = ") and line.lower().endswith(_JCONTAINERS_DLL_NAME.lower()):
                return line[7:].strip()
    except Exception as exc:
        logger.debug("7z list failed: %s", exc)
    return None


_JCONTAINERS_TARGET_SKSE = "skse64_1_6_1170.dll"


def _detect_skse_dll(mods_dir: Path) -> Optional[str]:
    """Return the SKSE loader DLL filename found in mods, or None."""
    for dll in mods_dir.glob("*/Root/skse64_*.dll"):
        return dll.name
    return None


def check_jcontainers_needs_fix(modlist_dir: Path, game_type: Optional[str]) -> list:
    """Return list of JContainers64.dll paths that need replacing, or empty list."""
    if not game_type or "skyrim" not in game_type.lower():
        return []
    mods_dir = Path(modlist_dir) / "mods"
    if not mods_dir.is_dir():
        return []
    if _detect_skse_dll(mods_dir) != _JCONTAINERS_TARGET_SKSE:
        return []
    targets = list(mods_dir.glob(f"*/SKSE/Plugins/{_JCONTAINERS_DLL_NAME}"))
    return [p for p in targets if _sha256(p) != _JCONTAINERS_FIXED_SHA256]


def apply_jcontainers_fix(
    modlist_dir: Path,
    game_var_full: Optional[str],
    status_callback: Optional[Callable] = None,
) -> None:
    """Replace a broken JContainers64.dll with the Linux-compatible build.

    Scoped to Skyrim-based modlists only. Skips silently if already fixed,
    if no JContainers mod is found, or if required tools are unavailable.
    """
    if not game_var_full or "skyrim" not in game_var_full.lower():
        return

    mods_dir = Path(modlist_dir) / "mods"
    if not mods_dir.is_dir():
        return

    if _detect_skse_dll(mods_dir) != _JCONTAINERS_TARGET_SKSE:
        return

    targets = list(mods_dir.glob(f"*/SKSE/Plugins/{_JCONTAINERS_DLL_NAME}"))
    if not targets:
        logger.debug("JContainers fix: no %s found under %s", _JCONTAINERS_DLL_NAME, mods_dir)
        return

    needs_fix = [p for p in targets if _sha256(p) != _JCONTAINERS_FIXED_SHA256]
    if not needs_fix:
        logger.debug("JContainers fix: all instances already at known-good version")
        return

    seven_z = _get_7z()
    if not seven_z:
        logger.warning("JContainers fix: 7z not available, cannot apply fix")
        return

    if status_callback:
        status_callback("Applying JContainers Linux compatibility fix")
    logger.info("JContainers fix: %d instance(s) need replacement", len(needs_fix))

    cache_dir = get_jackify_data_dir() / "component_cache" / "fixups"
    cache_dir.mkdir(parents=True, exist_ok=True)
    archive_path = cache_dir / _JCONTAINERS_ARCHIVE_NAME

    if not archive_path.exists():
        logger.info("JContainers fix: downloading fixed archive from %s", _JCONTAINERS_FIXED_URL)
        try:
            urllib.request.urlretrieve(_JCONTAINERS_FIXED_URL, archive_path)
        except Exception as exc:
            logger.error("JContainers fix: download failed: %s", exc)
            return

    dll_internal_path = _find_dll_in_archive(seven_z, archive_path)
    if not dll_internal_path:
        logger.error("JContainers fix: could not locate %s inside archive", _JCONTAINERS_DLL_NAME)
        archive_path.unlink(missing_ok=True)
        return

    with tempfile.TemporaryDirectory() as tmp:
        try:
            subprocess.run(
                [str(seven_z), "e", str(archive_path), f"-o{tmp}", dll_internal_path, "-y"],
                capture_output=True, timeout=60, check=True,
            )
        except subprocess.CalledProcessError as exc:
            logger.error("JContainers fix: extraction failed: %s", exc)
            archive_path.unlink(missing_ok=True)
            return

        extracted = Path(tmp) / _JCONTAINERS_DLL_NAME
        if not extracted.exists():
            logger.error("JContainers fix: %s not found after extraction", _JCONTAINERS_DLL_NAME)
            archive_path.unlink(missing_ok=True)
            return

        actual_hash = _sha256(extracted)
        if actual_hash != _JCONTAINERS_FIXED_SHA256:
            logger.error(
                "JContainers fix: extracted DLL hash %s does not match expected %s, aborting",
                actual_hash, _JCONTAINERS_FIXED_SHA256,
            )
            archive_path.unlink(missing_ok=True)
            return

        import shutil
        for target in needs_fix:
            try:
                backup = target.with_suffix(".dll.bak")
                shutil.copy2(str(target), str(backup))
                logger.info("JContainers fix: backed up %s -> %s", target.name, backup.name)
                shutil.copy2(str(extracted), str(target))
                logger.info("JContainers fix: replaced %s", target)
            except Exception as exc:
                logger.error("JContainers fix: failed to replace %s: %s", target, exc)
