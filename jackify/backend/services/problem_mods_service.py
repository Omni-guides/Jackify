"""Problem mods service.

Identifies and disables mods with known Proton compatibility issues by
rewriting modlist.txt files atomically.
"""

import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Optional, List

import requests

from jackify.backend.models.game_types import normalize_game_name
from jackify.shared.paths import get_jackify_data_dir

logger = logging.getLogger(__name__)

PROBLEM_MODS_MANIFEST_URL = (
    "https://raw.githubusercontent.com/Omni-guides/Jackify/main/manifests/problem_mods.json"
)
_BUNDLED_MANIFEST_PATH = Path(__file__).parent / "problem_mods_manifest.json"

_CANONICAL_TO_MANIFEST_KEY = {
    "skyrim": "SkyrimSE",
    "skyrimse": "SkyrimSE",
    "fallout4": "Fallout4",
    "skyrimvr": "SkyrimVR",
    "fallout4vr": "Fallout4VR",
    "enderal": "Enderal",
}


def _unwrap_manifest_payload(payload) -> tuple:
    """(version, games dict) from a manifest payload. A missing/absent manifest_version is
    always 0, so it can never outrank a genuinely versioned bundled manifest - see
    manifest_versioning.is_newer."""
    if isinstance(payload, dict):
        try:
            version = int(payload.get("manifest_version", 0) or 0)
        except (TypeError, ValueError):
            version = 0
        games = {k: v for k, v in payload.items() if k != "manifest_version"}
        return version, games
    return 0, {}


def _read_bundled_payload() -> dict:
    with open(_BUNDLED_MANIFEST_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _load_bundled_manifest() -> dict:
    try:
        _, games = _unwrap_manifest_payload(_read_bundled_payload())
        return games
    except Exception as e:
        logger.debug("Bundled problem mods manifest load failed: %s", e)
    return {}


def _bundled_manifest_version() -> int:
    try:
        version, _ = _unwrap_manifest_payload(_read_bundled_payload())
        return version
    except Exception:
        return 0


_BUNDLED_MANIFEST_VERSION: int = _bundled_manifest_version()
_manifest_cache: Optional[dict] = _load_bundled_manifest() or None


def _disk_cache_path() -> Path:
    return get_jackify_data_dir() / "manifests" / "problem_mods.json"


def _load_disk_cache() -> Optional[dict]:
    path = _disk_cache_path()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        version, games = _unwrap_manifest_payload(payload)
        from jackify.backend.services.manifest_versioning import is_newer
        if not is_newer(version, _BUNDLED_MANIFEST_VERSION):
            logger.debug(
                "Ignoring problem mods disk cache (version %s, bundled is %s)",
                version, _BUNDLED_MANIFEST_VERSION,
            )
            return None
        return games
    except Exception:
        pass
    return None


def _save_disk_cache(version: int, games: dict) -> None:
    path = _disk_cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".problem_mods_", suffix=".tmp")
        payload = {"manifest_version": version, **games}
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        os.replace(tmp, path)
    except Exception as e:
        logger.debug("Problem mods manifest disk save failed: %s", e)


def fetch_remote_manifest() -> Optional[dict]:
    """Fetch the remote problem mods manifest. Returns the games dict, or None on failure or
    if the remote isn't newer than what's already bundled in this build (see
    manifest_versioning.is_newer)."""
    try:
        resp = requests.get(PROBLEM_MODS_MANIFEST_URL, timeout=8, verify=True)
        resp.raise_for_status()
        payload = resp.json()
        version, games = _unwrap_manifest_payload(payload)
        from jackify.backend.services.manifest_versioning import is_newer
        if not is_newer(version, _BUNDLED_MANIFEST_VERSION):
            logger.info(
                "Remote problem mods manifest (version %s) is not newer than bundled (version %s) - ignoring",
                version, _BUNDLED_MANIFEST_VERSION,
            )
            return None
        _save_disk_cache(version, games)
        return games
    except Exception as e:
        logger.debug("Problem mods manifest fetch failed: %s", e)
    return None


def apply_remote_manifest(data: dict) -> None:
    """Store fetched manifest in memory. fetch_remote_manifest() already version-gated it and
    persisted to disk, so this only updates the in-session cache."""
    global _manifest_cache
    _manifest_cache = data


def _effective_manifest() -> dict:
    if _manifest_cache is not None:
        return _manifest_cache
    disk = _load_disk_cache()
    if disk is not None:
        return disk
    return _load_bundled_manifest()


def _get_mod_fixes(game_type: str) -> List[dict]:
    """Return mod_fixes list for the given game type.

    Handles old format (plain list of mod names = disable-only entries) so
    cached manifests from before the format change continue to work.
    """
    canonical = normalize_game_name(game_type) or game_type.lower().replace(" ", "")
    manifest_key = _CANONICAL_TO_MANIFEST_KEY.get(canonical)
    if not manifest_key:
        return []
    raw = _effective_manifest().get(manifest_key, {})
    if isinstance(raw, list):
        return [{"mod": name, "disable": True} for name in raw]
    if isinstance(raw, dict):
        return raw.get("mod_fixes", [])
    return []


def get_problem_mods(game_type: str) -> List[str]:
    """Return names of mods flagged for disabling for the given game type."""
    return [fix["mod"] for fix in _get_mod_fixes(game_type) if fix.get("disable")]


def detect_game_type_from_install_dir(install_dir: str) -> str:
    """Read ModOrganizer.ini directly for the modlist's actual game type.

    Ground truth for mod-fix lookups - a caller's own game_type value (registry
    metadata, GUI pre-install validation state) can be stale or wrong for the
    specific modlist on disk, causing fixes to silently no-op.
    """
    try:
        ini = os.path.join(install_dir, "ModOrganizer.ini")
        if os.path.isfile(ini):
            from jackify.backend.handlers.modlist_handler import ModlistHandler
            handler = ModlistHandler({})
            handler.modlist_ini = ini
            handler.modlist_dir = install_dir
            if handler._detect_game_variables():
                return handler.game_var_full or ""
    except Exception as e:
        logger.debug("Game type detection failed: %s", e)
    return ""


def get_enabled_mods(modlist_txt_path: Path) -> set:
    """Return lowercase set of enabled mod names from a modlist.txt."""
    try:
        lines = modlist_txt_path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return set()
    mods = set()
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("+"):
            name = stripped[1:]
            mods.add(name.lower())
            bare = re.sub(r'^\[.*?\]\s*', '', name)
            if bare != name:
                mods.add(bare.lower())
    return mods


def create_prefix_dirs(wineprefix: Path, game_type: str, enabled_mods: set) -> List[str]:
    """Create directories inside a Wine prefix for present problem mods.

    Only acts when the associated mod is actually enabled in the modlist.
    Paths are relative to drive_c inside the prefix.
    Returns list of paths created.
    """
    created: List[str] = []
    for fix in _get_mod_fixes(game_type):
        if not fix.get("create_dirs"):
            continue
        if fix.get("mod", "").lower() not in enabled_mods:
            continue
        for rel_path in fix["create_dirs"]:
            target = wineprefix / "drive_c" / rel_path
            if target.exists():
                continue
            try:
                target.mkdir(parents=True, exist_ok=True)
                logger.info("Created prefix directory for '%s': %s", fix["mod"], target)
                created.append(rel_path)
            except Exception as e:
                logger.warning("Could not create prefix directory %s: %s", target, e)
    return created


def disable_problem_mods(modlist_txt_path: Path, game_type: str) -> List[str]:
    """Disable problem mods in modlist.txt by prepending '-' to enabled entries.

    Reads modlist.txt, disables any enabled ('+name') line whose name is in the
    problem list, writes the file back atomically. Idempotent: already-disabled
    entries are not counted.

    Returns list of mod names actually disabled (empty if none).
    """
    problem_names = get_problem_mods(game_type)
    if not problem_names:
        return []

    problem_set = {n.lower() for n in problem_names}

    try:
        content = modlist_txt_path.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning("Could not read modlist.txt at %s: %s", modlist_txt_path, e)
        return []

    lines = content.splitlines(keepends=True)
    disabled: List[str] = []
    new_lines: List[str] = []

    for line in lines:
        stripped = line.rstrip("\r\n")
        if stripped.startswith("+"):
            name = stripped[1:]
            # Strip leading [tag] prefixes (e.g. "[PC] MCM Booster" -> "MCM Booster")
            bare_name = re.sub(r'^\[.*?\]\s*', '', name)
            if name.lower() in problem_set or bare_name.lower() in problem_set:
                eol = line[len(stripped):]
                new_lines.append(f"-{name}{eol}")
                disabled.append(name)
                continue
        new_lines.append(line)

    if not disabled:
        return []

    new_content = "".join(new_lines)
    try:
        dir_ = modlist_txt_path.parent
        fd, tmp_path = tempfile.mkstemp(dir=dir_, prefix=".modlist_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(new_content)
            os.replace(tmp_path, modlist_txt_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except Exception as e:
        logger.warning("Could not write modlist.txt at %s: %s", modlist_txt_path, e)
        return []

    return disabled
