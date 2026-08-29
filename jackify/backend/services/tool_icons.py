"""
Cached per-tool icon images for the Tools Hub, keyed by tool_id.

Best-effort only: the owner avatar behind a tool's GitHub repo is not a real project logo,
just a recognisable image so cards aren't all identical colour tiles. Fetched once per tool
and cached to disk - no network call needed on later visits. Tools without a github_repo (or
where the fetch fails) keep the card's own colour-tile placeholder.
"""
import logging
from pathlib import Path
from typing import Optional

import requests

from jackify.shared.paths import get_jackify_data_dir

logger = logging.getLogger(__name__)

_TIMEOUT = 8


def _icons_dir() -> Path:
    d = get_jackify_data_dir() / "tool_icons"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_cached_icon_path(tool_id: str) -> Optional[Path]:
    p = _icons_dir() / f"{tool_id}.png"
    return p if p.is_file() else None


def fetch_and_cache_icon(tool_id: str, github_repo: str) -> Optional[Path]:
    """Download the GitHub repo owner's avatar and cache it as this tool's icon."""
    owner = github_repo.split("/")[0]
    url = f"https://github.com/{owner}.png?size=200"
    try:
        resp = requests.get(url, timeout=_TIMEOUT, verify=True)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.debug("Tool icon fetch failed for %s (%s): %s", tool_id, url, e)
        return None

    dest = _icons_dir() / f"{tool_id}.png"
    try:
        dest.write_bytes(resp.content)
        return dest
    except OSError as e:
        logger.warning("Failed to cache tool icon for %s: %s", tool_id, e)
        return None
