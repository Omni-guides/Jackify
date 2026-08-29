"""NXM download pipeline: resolve CDN URL and save to modlist download directory."""

import logging
import re
from pathlib import Path
from typing import Optional, Callable, Tuple
from urllib.parse import unquote

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
        logger.info("Resolved MO2 download directory from ini: %s", dl_str)
        return Path(dl_str)
    default = modlist_dir / "downloads"
    # Warning, not debug: when this fallback is wrong the download still reports success and
    # the archive simply lands somewhere the user is not looking. Reports of "NXM downloads
    # don't go to the downloads folder" are unreproducible without this line in the log.
    logger.warning(
        "No download_directory resolved from %s - falling back to default: %s",
        ini_path, default,
    )
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
    partial = None
    try:
        download_dir.mkdir(parents=True, exist_ok=True)
        logger.info("NXM download starting: %s -> %s", filename, download_dir)

        resp = requests.get(cdn_url, stream=True, timeout=60)
        resp.raise_for_status()

        # The CDN URL's path is sometimes an opaque object key with no real name in it at
        # all - the response's Content-Disposition header, when present, is authoritative.
        header_name = _filename_from_content_disposition(resp.headers.get("content-disposition"))
        if header_name:
            filename = header_name
        dest = download_dir / filename

        total = int(resp.headers.get("content-length", 0))
        downloaded = 0

        # Download to a .part file and rename only once the transfer is verifiably complete,
        # so an interrupted download can never be left sitting at the finished filename where
        # it would look like a valid archive.
        partial = dest.with_name(dest.name + ".part")
        with open(partial, "wb") as f:
            for chunk in resp.iter_content(chunk_size=_CHUNK_SIZE):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback and total > 0:
                        progress_callback(downloaded, total)

        if downloaded == 0:
            logger.error("NXM download produced an empty file: %s", cdn_url)
            partial.unlink(missing_ok=True)
            return False, "Download produced an empty file"
        if total > 0 and downloaded != total:
            logger.error(
                "Truncated NXM download: got %d bytes, expected %d", downloaded, total
            )
            partial.unlink(missing_ok=True)
            return False, f"Truncated download: got {downloaded} of {total} bytes"

        partial.replace(dest)
        logger.info("NXM download complete: %s (%d bytes) -> %s", dest.name, downloaded, dest)
        return True, f"Saved to {dest}"

    except Exception as e:
        logger.error("NXM download failed: %s", e)
        if partial is not None:
            partial.unlink(missing_ok=True)
        return False, str(e)


def filename_from_cdn_url(cdn_url: str, fallback: str) -> str:
    """Extract a filename from a CDN URL, falling back to provided name.

    Nexus's CDN sometimes uses an opaque object key as the URL path (no real name or
    extension at all) - the actual filename in that case only appears in the download
    response's Content-Disposition header, read separately in download_nxm_file()."""
    path = cdn_url.split("?")[0].rstrip("/")
    name = path.split("/")[-1]
    return name if name else fallback


def _filename_from_content_disposition(header_value: Optional[str]) -> Optional[str]:
    """Parse a filename out of a Content-Disposition header value, RFC 6266 UTF-8 form
    preferred over the plain quoted form when both are present."""
    if not header_value:
        return None
    match = re.search(r"filename\*=UTF-8''([^;]+)", header_value, re.IGNORECASE)
    if match:
        return unquote(match.group(1))
    match = re.search(r'filename="?([^";]+)"?', header_value, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None
