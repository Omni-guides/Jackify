"""tools_manifest.json's on-disk shape and disk-cache I/O - split out of tool_registry.py to
stay under the file-size guardrail. Pure format/IO helpers with no ToolDefinition dependency;
the version-gating decision itself lives in manifest_versioning.is_newer().
"""

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import List, Tuple

logger = logging.getLogger(__name__)


def unwrap_manifest_payload(payload) -> Tuple[int, list]:
    """(version, entries) from {"manifest_version": N, "tools": [...]} or a bare pre-versioning
    list (always version 0)."""
    if isinstance(payload, dict):
        try:
            version = int(payload.get("manifest_version", 0) or 0)
        except (TypeError, ValueError):
            version = 0
        return version, payload.get("tools", [])
    if isinstance(payload, list):
        return 0, payload
    return 0, []


def disk_cache_path() -> Path:
    from jackify.shared.paths import get_jackify_data_dir
    return get_jackify_data_dir() / "manifests" / "tools_manifest.json"


def save_disk_cache(version: int, entries: list) -> None:
    path = disk_cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tools_manifest_", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"manifest_version": version, "tools": entries}, fh, indent=2)
        os.replace(tmp, path)
    except Exception as e:
        logger.debug("Tool manifest disk save failed: %s", e)
