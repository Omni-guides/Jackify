"""
Playbook registry: startup sync, cache, bundled fallback, hash verification, and matching.

Mirrors tool_registry.py's caching strategy (in-memory session cache -> disk cache -> bundled
copy), but with the playbook system's own index-plus-hash-pinned-files format: an index lists
every playbook id and its expected SHA256, each playbook is fetched as its own file and
discarded if its content doesn't match the index hash. One malformed or tampered playbook can
never break sync for the rest. See docs/0.8_work/modlist_playbook_system.md sections 3 and 3.2.
"""
import hashlib
import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import requests

from jackify.shared.paths import get_jackify_data_dir
from .catalog import Catalog, CatalogValidationError, parse_catalog
from .schema import MatchBlock, Playbook, PlaybookValidationError, parse_playbook

logger = logging.getLogger(__name__)

PLAYBOOKS_INDEX_URL = "https://raw.githubusercontent.com/Omni-guides/Jackify/main/manifests/playbooks/playbooks_index.json"
PLAYBOOK_FILE_URL_TEMPLATE = (
    "https://raw.githubusercontent.com/Omni-guides/Jackify/main/manifests/playbooks/playbooks/{playbook_id}.json"
)
CATALOG_URL = "https://raw.githubusercontent.com/Omni-guides/Jackify/main/manifests/playbooks/catalog.json"
_REQUEST_TIMEOUT = 8
_BUNDLED_DIR = Path(__file__).parent / "bundled"


@dataclass
class MatchIdentity:
    """Identity signals gathered by the caller, in the priority order from section 3.2."""
    machine_url: Optional[str] = None
    name: Optional[str] = None
    mo2_profile: Optional[str] = None
    game_type: Optional[str] = None


def matches_identity(match: MatchBlock, identity: MatchIdentity) -> bool:
    """
    True if `identity` positively matches `match`.

    `game_types`, when present, is an AND filter only - it can never be the sole reason a
    playbook matches, since that would be game-wide behaviour, which stays coded in Python.
    """
    positive = False

    if identity.machine_url and identity.machine_url in match.machine_urls:
        positive = True

    if identity.name:
        if identity.name in match.name_exact:
            positive = True
        name_lower = identity.name.lower()
        if any(needle.lower() in name_lower for needle in match.name_contains):
            positive = True
        if any(_safe_search(pattern, identity.name) for pattern in match.name_patterns):
            positive = True

    if identity.mo2_profile and identity.mo2_profile in match.mo2_profiles:
        positive = True

    if not positive:
        return False

    if match.game_types and identity.game_type not in match.game_types:
        return False

    return True


def _safe_search(pattern: str, value: str) -> bool:
    try:
        return re.search(pattern, value) is not None
    except re.error:
        return False


def _disk_dir() -> Path:
    return get_jackify_data_dir() / "playbooks"


def _disk_index_path() -> Path:
    return _disk_dir() / "index.json"


def _disk_file_path(playbook_id: str) -> Path:
    return _disk_dir() / "files" / f"{playbook_id}.json"


def _bundled_index_path() -> Path:
    return _BUNDLED_DIR / "index.json"


def _bundled_file_path(playbook_id: str) -> Path:
    return _BUNDLED_DIR / "files" / f"{playbook_id}.json"


def _disk_catalog_path() -> Path:
    return _disk_dir() / "catalog.json"


def _bundled_catalog_path() -> Path:
    return _BUNDLED_DIR / "catalog.json"


def _sha256_of(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _atomic_write_bytes(path: Path, raw: bytes) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".playbook_tmp_")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(raw)
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except Exception as e:
        logger.debug("Playbook cache write failed for %s: %s", path, e)


def _read_bytes(path: Path) -> Optional[bytes]:
    try:
        return path.read_bytes()
    except OSError:
        return None


def _fetch_bytes(url: str) -> Optional[bytes]:
    try:
        resp = requests.get(url, timeout=_REQUEST_TIMEOUT, verify=True)
        resp.raise_for_status()
        return resp.content
    except Exception as e:
        logger.debug("Playbook fetch failed for %s: %s", url, e)
        return None


class PlaybookRegistry:
    """Holds the currently-effective set of playbooks and how to (re)sync it."""

    def __init__(self):
        self._playbooks: Dict[str, Playbook] = {}
        self._catalog: Optional[Catalog] = None

    def get_all(self) -> List[Playbook]:
        return [p for p in self._playbooks.values() if not p.disabled]

    def get_catalog(self) -> Optional[Catalog]:
        return self._catalog

    def find_candidates(self, identity: MatchIdentity) -> List[Playbook]:
        """Playbooks whose `match` block matches `identity`. Matching alone is not consent to
        run - callers must still evaluate each candidate's `confirm` block (section 3.2)."""
        return [p for p in self.get_all() if matches_identity(p.match, identity)]

    def sync(self) -> bool:
        """
        Fetch the latest index, playbook files, and catalog from the registry repo.

        Returns True if the remote index was reachable (individual playbooks may still fail
        their own verification independently). Returns False if the registry itself was
        unreachable, in which case the disk cache is used, falling back to the bundled copy if
        the disk cache is empty too - the existing in-memory set is left untouched if neither
        of those has anything either, so a mid-session sync failure never clears a working set.
        The catalog syncs independently of the playbook index using the same fallback order.
        """
        self._sync_catalog()

        index_raw = _fetch_bytes(PLAYBOOKS_INDEX_URL)
        if index_raw is None:
            logger.debug("Playbook index unreachable, using cached/bundled set")
            if not self._playbooks:
                self._load_from_disk_or_bundled()
            return False

        index = _parse_index(index_raw)
        if index is None:
            logger.warning("Playbook index fetched but malformed, using cached/bundled set")
            if not self._playbooks:
                self._load_from_disk_or_bundled()
            return False

        _atomic_write_bytes(_disk_index_path(), index_raw)

        playbooks: Dict[str, Playbook] = {}
        for entry in index:
            playbook = self._sync_one(entry)
            if playbook is not None:
                playbooks[playbook.playbook_id] = playbook

        if playbooks:
            self._playbooks = playbooks
        return True

    def _sync_one(self, entry: dict) -> Optional[Playbook]:
        playbook_id = entry.get("playbook_id")
        expected_sha256 = entry.get("sha256")
        if not isinstance(playbook_id, str) or not isinstance(expected_sha256, str):
            logger.warning("Playbook index entry missing playbook_id/sha256, skipping")
            return None

        url = PLAYBOOK_FILE_URL_TEMPLATE.format(playbook_id=playbook_id)
        raw = _fetch_bytes(url)
        if raw is not None and _sha256_of(raw) == expected_sha256.lower():
            playbook = _parse_raw(raw, playbook_id)
            if playbook is not None:
                _atomic_write_bytes(_disk_file_path(playbook_id), raw)
                return playbook
            logger.warning("Playbook %s failed validation, discarding", playbook_id)
        elif raw is not None:
            logger.warning("Playbook %s hash mismatch, discarding", playbook_id)

        # Remote copy unusable this sync - fall back to a verified disk or bundled copy so a
        # transient fetch failure for one file doesn't remove a previously-working playbook.
        for path in (_disk_file_path(playbook_id), _bundled_file_path(playbook_id)):
            cached = _read_bytes(path)
            if cached is not None and _sha256_of(cached) == expected_sha256.lower():
                playbook = _parse_raw(cached, playbook_id)
                if playbook is not None:
                    return playbook
        return None

    def _sync_catalog(self) -> None:
        """Fetch catalog.json, falling back to disk then bundled. Unlike playbook files, the
        catalog is one blob with one merge review (section 5.1) - it is not per-entry
        hash-pinned, so a fetched-but-invalid catalog simply keeps whatever catalog is already
        in memory rather than partially applying it."""
        raw = _fetch_bytes(CATALOG_URL)
        if raw is not None:
            catalog = _parse_catalog_bytes(raw)
            if catalog is not None:
                _atomic_write_bytes(_disk_catalog_path(), raw)
                self._catalog = catalog
                return
            logger.warning("Remote catalog fetched but failed validation, keeping current catalog")

        if self._catalog is not None:
            return

        for path in (_disk_catalog_path(), _bundled_catalog_path()):
            cached = _read_bytes(path)
            if cached is None:
                continue
            catalog = _parse_catalog_bytes(cached)
            if catalog is not None:
                self._catalog = catalog
                return

    def _load_from_disk_or_bundled(self) -> None:
        for index_path in (_disk_index_path(), _bundled_index_path()):
            raw = _read_bytes(index_path)
            if raw is None:
                continue
            index = _parse_index(raw)
            if index is None:
                continue
            playbooks: Dict[str, Playbook] = {}
            for entry in index:
                playbook_id = entry.get("playbook_id")
                expected_sha256 = entry.get("sha256")
                if not isinstance(playbook_id, str) or not isinstance(expected_sha256, str):
                    continue
                for file_path in (_disk_file_path(playbook_id), _bundled_file_path(playbook_id)):
                    cached = _read_bytes(file_path)
                    if cached is not None and _sha256_of(cached) == expected_sha256.lower():
                        playbook = _parse_raw(cached, playbook_id)
                        if playbook is not None:
                            playbooks[playbook_id] = playbook
                        break
            if playbooks:
                self._playbooks = playbooks
                return


def _parse_index(raw: bytes) -> Optional[list]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("playbooks"), list):
        return None
    return data["playbooks"]


def _parse_raw(raw: bytes, playbook_id: str) -> Optional[Playbook]:
    try:
        data = json.loads(raw)
        return parse_playbook(data)
    except (json.JSONDecodeError, PlaybookValidationError) as e:
        logger.warning("Playbook %s failed validation: %s", playbook_id, e)
        return None


def _parse_catalog_bytes(raw: bytes) -> Optional[Catalog]:
    try:
        data = json.loads(raw)
        return parse_catalog(data)
    except (json.JSONDecodeError, CatalogValidationError) as e:
        logger.warning("Catalog failed validation: %s", e)
        return None
