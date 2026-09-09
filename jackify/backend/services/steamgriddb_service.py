"""
SteamGridDB artwork fetching service.

Fetches top-voted artwork for a game from steamgriddb.com using the
official API. Used as a fallback when a modlist has no SteamIcons/ directory.

PRIVATE: This file contains an obfuscated API key. Do NOT sync to public-src.
"""

import base64
import logging
import urllib.request
import urllib.error
import json
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.steamgriddb.com/api/v2"

# Obfuscated Jackify service key - XOR with mask, base64-encoded.
# Keep this file out of public-src.
_OBF = b"LgRUXwtXTwUEAw02cnR7EHgEVFldXklTUlFQNiQmJBM="
_MSK = b"Jackify2024SGDB!Jackify2024SGDB!"


def _get_api_key() -> str:
    raw = base64.b64decode(_OBF)
    return bytes(a ^ b for a, b in zip(raw, _MSK)).decode()

# Steam App IDs for each Jackify game type key
GAME_STEAM_APP_IDS = {
    "skyrim":              "489830",
    "skyrimvr":            "611670",
    "fallout4":            "377160",
    "fallout4vr":          "611660",
    "falloutnv":           "22380",
    "fallout3":            "22300",
    "oblivion":            "22330",
    "oblivion_remastered": "2623190",
    "enderal":             "976620",
    "starfield":           "1716740",
    "cp2077":              "1091500",
    "bg3":                 "1086940",
}

# Artwork slots: (endpoint_path, query_string, dest_filename)
_ARTWORK_SLOTS = [
    ("grids",  "dimensions=600x900&types=static&nsfw=false",  "grid-tall.png"),
    ("grids",  "dimensions=920x430&types=static&nsfw=false",  "grid-wide.png"),
    ("heroes", "dimensions=1920x620&types=static&nsfw=false", "grid-hero.png"),
    ("logos",  "types=static&nsfw=false",                     "grid-logo.png"),
]


def _api_get(endpoint: str, api_key: str) -> Optional[dict]:
    url = f"{_BASE_URL}/{endpoint}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "Jackify/0.6",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        logger.warning(f"SteamGridDB API error {e.code} for {url}")
    except Exception as e:
        logger.warning(f"SteamGridDB request failed for {url}: {e}")
    return None


def _download(url: str, dest: Path) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Jackify/0.6"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            dest.write_bytes(resp.read())
        return True
    except Exception as e:
        logger.warning(f"Failed to download {url}: {e}")
        return False


def detect_game_type_from_modlist(modlist_dir: str) -> Optional[str]:
    """Detect the Jackify game type key from the modlist's own ModOrganizer.ini.

    Covers all supported game types. Returns None if the ini cannot be read or the game type
    cannot be determined.
    """
    if not modlist_dir:
        return None
    from jackify.backend.services.game_type_detection import detect_from_install
    return detect_from_install(modlist_dir)


def fetch_artwork(game_type: str, dest_dir: Path, skip_existing: bool = False) -> int:
    """
    Fetch top-voted artwork for game_type from SteamGridDB into dest_dir.

    Returns the number of images successfully downloaded.
    dest_dir must already exist. When skip_existing is True, slots where the
    file already exists in dest_dir are skipped.
    """
    steam_appid = GAME_STEAM_APP_IDS.get(game_type)
    if not steam_appid:
        logger.debug(f"No Steam App ID mapping for game type: {game_type}")
        return 0

    api_key = _get_api_key()
    downloaded = 0
    for endpoint, query, filename in _ARTWORK_SLOTS:
        dest_path = dest_dir / filename
        if skip_existing and dest_path.exists():
            continue
        data = _api_get(f"{endpoint}/steam/{steam_appid}?{query}", api_key)
        if not data or not data.get("success") or not data.get("data"):
            logger.debug(f"No {endpoint} results for {game_type} ({steam_appid})")
            continue
        image_url = data["data"][0]["url"]
        if _download(image_url, dest_path):
            logger.info(f"Downloaded {filename} for {game_type} from SteamGridDB")
            downloaded += 1

    return downloaded
