"""NXM download pipeline: resolve CDN URL and save to modlist download directory."""

import logging
from pathlib import Path
from typing import Optional, Callable, Tuple

import requests

from jackify.backend.services.nxm_url import NxmUrl

logger = logging.getLogger(__name__)

_NEXUS_API_BASE = "https://api.nexusmods.com/v1"
_CHUNK_SIZE = 65536


def get_nxm_download_url(nxm: NxmUrl, auth_token: str, auth_method: str = "api_key") -> Optional[str]:
    """Resolve an NXM URL to a CDN download URL using the Nexus API.

    The key/expires from the NXM URL authorise the request for both Premium
    and non-Premium accounts.
    """
    url = (
        f"{_NEXUS_API_BASE}/games/{nxm.game}/mods/{nxm.mod_id}"
        f"/files/{nxm.file_id}/download_link.json"
    )
    if auth_method == "oauth":
        headers = {"Authorization": f"Bearer {auth_token}", "User-Agent": "jackify"}
    else:
        headers = {"apikey": auth_token, "User-Agent": "jackify"}

    params: dict = {}
    if nxm.key:
        params["key"] = nxm.key
    if nxm.expires:
        params["expires"] = nxm.expires

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list) and data:
            cdn_url = data[0].get("URI")
            logger.debug("Resolved NXM CDN URL for file %s", nxm.file_id)
            return cdn_url
        logger.warning("Nexus API returned empty download link list for file %s", nxm.file_id)
        return None
    except requests.HTTPError as e:
        logger.error(
            "Nexus API error resolving NXM URL (method=%s, status=%s): %s",
            auth_method, e.response.status_code if e.response else "?", e,
        )
        return None
    except Exception as e:
        logger.error("Unexpected error resolving NXM URL: %s", e)
        return None


def resolve_mo2_download_dir(modlist_dir: Path) -> Optional[Path]:
    """Read download_directory from ModOrganizer.ini and resolve to a Linux path.

    Returns None if the directory is not configured or cannot be resolved.
    Delegates to PathHandler which handles all MO2 path formats correctly.
    """
    from jackify.backend.handlers.path_handler import PathHandler
    ini_path = modlist_dir / "ModOrganizer.ini"
    if not ini_path.exists():
        logger.warning("ModOrganizer.ini not found at %s", ini_path)
        return None
    dl_str = PathHandler().get_download_directory_linux_path(ini_path)
    if dl_str:
        return Path(dl_str)
    default = modlist_dir / "downloads"
    logger.debug("No download_directory in ini, using default: %s", default)
    return default


def download_nxm_file(
    cdn_url: str,
    download_dir: Path,
    filename: str,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> Tuple[bool, str]:
    """Download a file to the modlist download directory.

    Returns (success, message).
    """
    try:
        download_dir.mkdir(parents=True, exist_ok=True)
        dest = download_dir / filename

        resp = requests.get(cdn_url, stream=True, timeout=60)
        resp.raise_for_status()

        total = int(resp.headers.get("content-length", 0))
        downloaded = 0

        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=_CHUNK_SIZE):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback and total > 0:
                        progress_callback(downloaded, total)

        logger.info("NXM download complete: %s (%d bytes)", dest.name, downloaded)
        return True, f"Saved to {dest}"

    except Exception as e:
        logger.error("NXM download failed: %s", e)
        return False, str(e)


def filename_from_cdn_url(cdn_url: str, fallback: str) -> str:
    """Extract a filename from a CDN URL, falling back to provided name."""
    path = cdn_url.split("?")[0].rstrip("/")
    name = path.split("/")[-1]
    return name if name else fallback
