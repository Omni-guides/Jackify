"""USVFS Linux fix manifest: supported games and the original -> patched DLL pairings.

Bundled copy ships with the build; a newer remote or disk-cached copy overrides it (see
manifest_versioning.is_newer). Adding a USVFS build or widening the game scope is a manifest
edit, not an app release. Matching stays exact-hash, so an unknown DLL is never patched.
"""

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Dict, FrozenSet, Optional

import requests

from jackify.backend.services.manifest_versioning import is_newer
from jackify.shared.paths import get_jackify_data_dir

logger = logging.getLogger(__name__)

USVFS_MANIFEST_URL = (
    "https://raw.githubusercontent.com/Omni-guides/Jackify/main/manifests/usvfs_builds.json"
)
_BUNDLED_MANIFEST_PATH = Path(__file__).parent / "usvfs_builds.json"
_BUILD_FIELDS = ("version", "release_tag", "asset_name", "patched_sha256")

_manifest_cache: Optional[dict] = None


def _clean(payload) -> Optional[dict]:
    """Normalised manifest from a raw payload, or None if it is unusable. Malformed build
    entries are dropped individually so one bad entry cannot disable the rest."""
    if not isinstance(payload, dict):
        return None
    try:
        version = int(payload.get("manifest_version", 0) or 0)
    except (TypeError, ValueError):
        version = 0
    games = payload.get("supported_games")
    builds = payload.get("builds")
    if not isinstance(games, list) or not isinstance(builds, dict):
        return None
    cleaned = {}
    for original_hash, entry in builds.items():
        if not isinstance(entry, dict) or not all(
            isinstance(entry.get(f), str) and entry.get(f) for f in _BUILD_FIELDS
        ):
            logger.warning("Ignoring malformed USVFS manifest entry %s", original_hash)
            continue
        cleaned[str(original_hash).lower()] = {
            **entry, "patched_sha256": entry["patched_sha256"].lower(),
        }
    return {
        "manifest_version": version,
        "supported_games": [str(g).lower() for g in games],
        "builds": cleaned,
    }


def _load_bundled() -> dict:
    try:
        with open(_BUNDLED_MANIFEST_PATH, "r", encoding="utf-8") as fh:
            cleaned = _clean(json.load(fh))
        if cleaned is not None:
            return cleaned
    except Exception as e:
        logger.warning("Bundled USVFS manifest load failed: %s", e)
    return {"manifest_version": 0, "supported_games": [], "builds": {}}


def _disk_cache_path() -> Path:
    return get_jackify_data_dir() / "manifests" / "usvfs_builds.json"


def _load_disk_cache(bundled_version: int) -> Optional[dict]:
    try:
        with open(_disk_cache_path(), "r", encoding="utf-8") as fh:
            cleaned = _clean(json.load(fh))
        if cleaned is not None and is_newer(cleaned["manifest_version"], bundled_version):
            return cleaned
    except Exception:
        pass
    return None


def _save_disk_cache(payload: dict) -> None:
    path = _disk_cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".usvfs_builds_", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        os.replace(tmp, path)
    except Exception as e:
        logger.debug("USVFS manifest disk save failed: %s", e)


def fetch_remote_manifest() -> Optional[dict]:
    """Fetch the remote manifest. Returns it only if valid and strictly newer than the
    bundled copy; None otherwise. Persists a newer manifest to the disk cache."""
    try:
        resp = requests.get(USVFS_MANIFEST_URL, timeout=8, verify=True)
        resp.raise_for_status()
        raw = resp.json()
        cleaned = _clean(raw)
        if cleaned is None:
            logger.info("Remote USVFS manifest is malformed - ignoring")
            return None
        bundled_version = _load_bundled()["manifest_version"]
        if not is_newer(cleaned["manifest_version"], bundled_version):
            logger.info(
                "Remote USVFS manifest (version %s) is not newer than bundled (version %s) - ignoring",
                cleaned["manifest_version"], bundled_version,
            )
            return None
        _save_disk_cache(raw)
        return cleaned
    except Exception as e:
        logger.debug("USVFS manifest fetch failed: %s", e)
    return None


def apply_remote_manifest(data: dict) -> None:
    """Store a fetched manifest in memory; fetch_remote_manifest() already version-gated it."""
    global _manifest_cache
    _manifest_cache = data


def get_manifest() -> dict:
    global _manifest_cache
    if _manifest_cache is None:
        bundled = _load_bundled()
        _manifest_cache = _load_disk_cache(bundled["manifest_version"]) or bundled
    return _manifest_cache


def get_supported_builds() -> Dict[str, dict]:
    return get_manifest()["builds"]


def get_patched_hashes() -> FrozenSet[str]:
    return frozenset(b["patched_sha256"] for b in get_supported_builds().values())


def get_supported_games() -> FrozenSet[str]:
    return frozenset(get_manifest()["supported_games"])
