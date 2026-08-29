"""
Per-install cached artwork for the Modlist Dashboard, keyed by install_id.

Deliberately not keyed by machine_url: backfilled installs (discovered via an existing Steam
shortcut, not installed through Jackify's gallery) never have a machine_url and never will, so
relying on it would permanently exclude them from having any artwork at all. Instead, an image
gets saved here once, from whatever source was available at the time (the gallery's own image
cache at install completion, or a user-chosen file via "Add Image..."), and the dashboard reads
purely from disk after that - no network call on open, matching the dashboard's own "must not
issue network calls on open" rule.
"""
import logging
import shutil
from pathlib import Path
from typing import Optional

from jackify.shared.paths import get_jackify_data_dir

logger = logging.getLogger(__name__)

_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")


def _images_dir() -> Path:
    d = get_jackify_data_dir() / "dashboard_images"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_cached_image_path(install_id: str) -> Optional[Path]:
    """Return the cached artwork path for this install, or None if it has none yet."""
    for ext in _EXTENSIONS:
        p = _images_dir() / f"{install_id}{ext}"
        if p.is_file():
            return p
    return None


def save_image_from_path(install_id: str, source_path: str) -> Optional[Path]:
    """Copy an image (gallery-cached or user-chosen) in as this install's dashboard artwork."""
    src = Path(source_path)
    if not src.is_file():
        return None
    remove_cached_image(install_id)
    suffix = src.suffix.lower() if src.suffix.lower() in _EXTENSIONS else ".png"
    dest = _images_dir() / f"{install_id}{suffix}"
    try:
        shutil.copyfile(src, dest)
        return dest
    except OSError as e:
        logger.warning("Failed to save dashboard image for %s: %s", install_id, e)
        return None


def remove_cached_image(install_id: str) -> None:
    """Delete any cached artwork for this install. Safe to call when none exists."""
    for ext in _EXTENSIONS:
        p = _images_dir() / f"{install_id}{ext}"
        if p.is_file():
            try:
                p.unlink()
            except OSError as e:
                logger.debug("Failed to remove cached dashboard image %s: %s", p, e)


def get_modlist_specific_art_path(install_dir: str) -> Optional[Path]:
    """
    Real, modlist-specific artwork the modlist itself ships in its own SteamIcons/ directory
    (`ModlistWineOpsMixin.set_steam_grid_images()` copies these straight into Steam's grid
    folder at configure time when present) - checking the modlist's own directory rather than
    Steam's merged grid folder is what makes this distinguishable from the generic SteamGridDB
    fallback art in `get_steam_grid_art_path()`, since both end up copied to the exact same
    Steam grid filenames and are otherwise indistinguishable once there.
    """
    if not install_dir:
        return None
    steam_icons_dir = Path(install_dir) / "SteamIcons"
    for filename in ("grid-wide.png", "grid-hero.png"):
        candidate = steam_icons_dir / filename
        if candidate.is_file():
            return candidate
    return None


def get_steam_grid_art_path(appid: str) -> Optional[Path]:
    """
    Last-resort fallback artwork for cards with no dashboard-specific or modlist-specific
    image: the generic per-game art `_try_steamgriddb_artwork()` (modlist_wine_ops.py) writes
    into Steam's own userdata/<user>/config/grid/ whenever a modlist ships no SteamIcons/ of
    its own. Exists on disk already for almost every entry with an appid - no network call
    needed here, matching the dashboard's "no network call on open" rule.

    Prefers the wide/landscape grid image (closer to the card's own aspect ratio) over the
    hero banner.
    """
    if not appid:
        return None
    try:
        from jackify.backend.services.native_steam_service import NativeSteamService

        service = NativeSteamService()
        if not service.find_steam_user() or not service.user_config_path:
            return None
        grid_dir = service.user_config_path / "grid"
        for filename in (f"{appid}.png", f"{appid}.jpg", f"{appid}_hero.png"):
            candidate = grid_dir / filename
            if candidate.is_file():
                return candidate
    except Exception as e:
        logger.debug("Steam grid artwork lookup failed for appid %s: %s", appid, e)
    return None
