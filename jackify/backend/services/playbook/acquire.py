"""
Catalog acquisition: resolving a CatalogTool/CatalogAsset to a local, ready-to-use file.

Generalizes the existing per-tool download code in vnv_post_install_service.py
(NexusDownloadService, zip/7z extraction, chmod, the Nexus file-matching heuristic) to work
from catalog data instead of two hardcoded mod ids. The manual-download fallback is prepared
here (get_manual_download_metadata) but not wired to a dialog: that is GUI/runtime-layer work,
matching how VNVPostInstallService.get_manual_download_items() already works today - backend
prepares DownloadItem-compatible metadata, the GUI's ManualDownloadManager/Dialog consumes it.
See docs/0.8_work/modlist_playbook_system.md section 5.
"""
import hashlib
import logging
import stat
import subprocess
import zipfile
from pathlib import Path
from typing import List, Optional

import requests

from jackify.backend.handlers.subprocess_utils import get_clean_subprocess_env
from jackify.backend.services.nexus_auth_service import NexusAuthService
from jackify.backend.services.nexus_download_service import NexusDownloadService
from jackify.backend.services.tool_registry import ToolRegistry, _find_7z_binary
from .catalog import CatalogAsset, CatalogTool, asset_cache_dir, select_file

logger = logging.getLogger(__name__)

_NEXUS_FILES_URL = "https://api.nexusmods.com/v1/games/{game_domain}/mods/{mod_id}/files.json"
_METADATA_TIMEOUT = 8
_URL_DOWNLOAD_TIMEOUT = 60


class AcquisitionError(Exception):
    """
    Automatic acquisition failed.

    `manual_download_metadata` is populated when source == "nexus" and a suitable file could
    still be identified via the Nexus API (works without Premium) - the caller can route this
    to the existing manual-download flow. It is None when metadata lookup also failed, in which
    case the catalog entry's static `manual_download.instructions` is the only fallback.
    """

    def __init__(self, message: str, manual_download_metadata: Optional[dict] = None):
        super().__init__(message)
        self.manual_download_metadata = manual_download_metadata


def _select_nexus_file(files: List[dict], file_filter: Optional[str]) -> Optional[dict]:
    """
    Generalizes VNVPostInstallService._select_manual_download_file: a file_filter substring
    match (newest first) takes priority, falling back to the MAIN category file, falling back
    to the newest active file of any kind.
    """
    active = [f for f in files if f.get("category_name") not in ("ARCHIVED", "REMOVED")]
    if file_filter:
        filtered = [f for f in active if file_filter.lower() in f.get("file_name", "").lower()]
        if filtered:
            filtered.sort(key=lambda f: f.get("uploaded_timestamp", 0), reverse=True)
            return filtered[0]
    main_files = [f for f in active if f.get("category_name") == "MAIN"]
    if main_files:
        main_files.sort(key=lambda f: f.get("uploaded_timestamp", 0), reverse=True)
        return main_files[0]
    if active:
        active.sort(key=lambda f: f.get("uploaded_timestamp", 0), reverse=True)
        return active[0]
    return None


def get_manual_download_metadata(tool: CatalogTool, auth_service: NexusAuthService) -> Optional[dict]:
    """DownloadItem-compatible metadata dict for a nexus-source catalog tool, or None if it
    can't be resolved (no auth, API error, no suitable file) - the caller falls back to the
    catalog entry's static manual_download instructions instead."""
    if tool.source != "nexus":
        return None
    token = auth_service.get_auth_token()
    if not token:
        return None
    headers = {"Accept": "application/json"}
    if auth_service.get_auth_method() == "oauth":
        headers["Authorization"] = f"Bearer {token}"
    else:
        headers["apikey"] = token

    try:
        resp = requests.get(
            _NEXUS_FILES_URL.format(game_domain=tool.game_domain, mod_id=tool.mod_id),
            headers=headers, timeout=_METADATA_TIMEOUT,
        )
        resp.raise_for_status()
        files = resp.json().get("files", [])
    except Exception as e:
        logger.debug("Manual-download metadata lookup failed for %s: %s", tool.id, e)
        return None

    match = _select_nexus_file(files, tool.file_filter)
    if match is None:
        return None
    return {
        "file_name": match["file_name"],
        "mod_name": tool.display_name,
        "nexus_url": (
            f"https://www.nexusmods.com/{tool.game_domain}/mods/{tool.mod_id}"
            f"?tab=files&file_id={match['file_id']}"
        ),
        "expected_hash": "",
        "expected_size": match.get("size_kb", 0) * 1024,
        "mod_id": tool.mod_id,
        "file_id": match["file_id"],
    }


def _find_cached_download(cache_dir: Path) -> Optional[Path]:
    """A prior successful acquisition already left exactly one file directly in the cache dir
    (extraction output lives in its own `_extracted` subdirectory) - reuse it."""
    if not cache_dir.exists():
        return None
    candidates = [p for p in cache_dir.iterdir() if p.is_file()]
    return candidates[0] if len(candidates) == 1 else None


def _download_via_nexus(tool: CatalogTool, auth_service: NexusAuthService, dest_dir: Path) -> Optional[Path]:
    token = auth_service.ensure_valid_auth()
    if not token:
        logger.warning("No Nexus authentication available for %s", tool.id)
        return None
    success, path, message = NexusDownloadService(token).download_latest_file(
        tool.game_domain, tool.mod_id, dest_dir, file_name_filter=tool.file_filter,
    )
    if not success:
        logger.info("Automatic download failed for %s: %s", tool.id, message)
        return None
    return path


def _download_via_url(url: str, sha256: str, dest_dir: Path) -> Optional[Path]:
    dest = dest_dir / Path(url).name
    try:
        resp = requests.get(url, timeout=_URL_DOWNLOAD_TIMEOUT, stream=True, verify=True)
        resp.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(1048576):
                f.write(chunk)
    except Exception as e:
        logger.warning("Direct download failed for %s: %s", url, e)
        return None

    digest = hashlib.sha256()
    with open(dest, "rb") as f:
        for chunk in iter(lambda: f.read(1048576), b""):
            digest.update(chunk)
    if digest.hexdigest().lower() != sha256.lower():
        logger.warning("SHA256 mismatch for %s, discarding download", url)
        dest.unlink(missing_ok=True)
        return None
    return dest


def extract_archive(archive_path: Path, extract_dir: Path) -> bool:
    if extract_dir.exists() and any(extract_dir.iterdir()):
        return True
    extract_dir.mkdir(parents=True, exist_ok=True)
    suffix = archive_path.suffix.lower()
    try:
        if suffix == ".zip":
            with zipfile.ZipFile(archive_path, "r") as zf:
                zf.extractall(extract_dir)
            return True
        if suffix == ".7z":
            sevenzip = _find_7z_binary()
            if not sevenzip:
                logger.warning("7z binary not available, cannot extract %s", archive_path)
                return False
            result = subprocess.run(
                [sevenzip, "x", "-y", f"-o{extract_dir}", str(archive_path)],
                env=get_clean_subprocess_env(), capture_output=True, text=True, timeout=120,
            )
            return result.returncode == 0
    except Exception as e:
        logger.warning("Extraction failed for %s: %s", archive_path, e)
        return False
    logger.warning("Unsupported archive type for extraction: %s", archive_path)
    return False


def acquire_tool(tool: CatalogTool, auth_service: Optional[NexusAuthService] = None) -> Path:
    """
    Resolve a catalog tool to a local file: shared cache -> source-specific acquisition ->
    extract -> select -> chmod.

    Raises AcquisitionError on failure (see its docstring for the manual-download case).
    """
    if tool.source == "tool":
        binary = ToolRegistry().get_binary_path(tool.tool_registry_id)
        if binary is None:
            raise AcquisitionError(f"Tool {tool.tool_registry_id!r} is not installed")
        return binary

    cache_dir = asset_cache_dir(tool.id)
    cache_dir.mkdir(parents=True, exist_ok=True)
    downloaded = _find_cached_download(cache_dir)

    if downloaded is None:
        if tool.source == "nexus":
            if auth_service is None:
                auth_service = NexusAuthService()
            downloaded = _download_via_nexus(tool, auth_service, cache_dir)
            if downloaded is None:
                metadata = get_manual_download_metadata(tool, auth_service)
                raise AcquisitionError(
                    f"Automatic download failed for {tool.display_name}",
                    manual_download_metadata=metadata,
                )
        elif tool.source == "url":
            downloaded = _download_via_url(tool.url, tool.sha256, cache_dir)
            if downloaded is None:
                raise AcquisitionError(f"Download failed for {tool.display_name}")
        else:
            raise AcquisitionError(f"Unknown catalog tool source: {tool.source!r}")

    result_path = downloaded
    if tool.extract:
        extract_dir = cache_dir / f"{downloaded.stem}_extracted"
        if not extract_archive(downloaded, extract_dir):
            raise AcquisitionError(f"Extraction failed for {tool.display_name}")
        selected = select_file(extract_dir, tool.select)
        if selected is None:
            raise AcquisitionError(f"Could not locate expected file inside {tool.display_name}")
        result_path = selected

    if tool.chmod_exec:
        result_path.chmod(result_path.stat().st_mode | stat.S_IEXEC)

    return result_path


def acquire_asset(asset: CatalogAsset) -> Path:
    """Resolve a catalog asset (source is always 'url', always SHA256-pinned) to a local file."""
    cache_dir = asset_cache_dir(asset.id)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = _find_cached_download(cache_dir)
    if cached is not None:
        return cached
    downloaded = _download_via_url(asset.url, asset.sha256, cache_dir)
    if downloaded is None:
        raise AcquisitionError(f"Download failed for {asset.display_name}")
    return downloaded
