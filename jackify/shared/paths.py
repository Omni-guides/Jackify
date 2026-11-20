"""
Path utilities for Jackify.

This module provides standardized path resolution for Jackify directories,
supporting configurable data directory while keeping config in a fixed location.
"""

import logging
import os
import shutil
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


_unavailable_data_dir: Optional[Path] = None


def _is_usable_data_dir(path: Path) -> bool:
    """True if path is writable, or can be created under a writable existing ancestor."""
    candidate = path
    while not candidate.exists():
        if candidate.parent == candidate:
            return False
        candidate = candidate.parent
    return candidate.is_dir() and os.access(candidate, os.W_OK | os.X_OK)


def _warn_data_dir_unavailable(path: Path) -> None:
    global _unavailable_data_dir
    if _unavailable_data_dir is None:
        _unavailable_data_dir = path
        logger.warning(
            f"Configured Jackify data directory is unavailable ({path}) - using ~/Jackify "
            "for this session. The saved setting is unchanged."
        )


def get_unavailable_data_dir() -> Optional[Path]:
    """The configured data directory that was bypassed this session, if any."""
    return _unavailable_data_dir


def get_jackify_data_dir() -> Path:
    """
    Get the configurable Jackify data directory.
    
    This directory contains:
    - downloaded_mod_lists/
    - logs/ 
    - temporary proton prefixes during installation
    
    Returns:
        Path: The Jackify data directory (always set in config)
    """
    try:
        # Import here to avoid circular imports
        from jackify.backend.handlers.config_handler import ConfigHandler
        
        config_handler = ConfigHandler()
        jackify_data_dir = config_handler.get('jackify_data_dir')
        
        # Config handler now always ensures this is set, but fallback just in case
        if jackify_data_dir:
            configured = Path(jackify_data_dir).expanduser()
            if _is_usable_data_dir(configured):
                return configured
            _warn_data_dir_unavailable(configured)
        return Path.home() / "Jackify"
            
    except Exception:
        # Emergency fallback if config system fails
        return Path.home() / "Jackify"


def get_jackify_logs_dir() -> Path:
    """Get the logs directory within the Jackify data directory."""
    return get_jackify_data_dir() / "logs"


def get_jackify_downloads_dir() -> Path:
    """Get the downloaded modlists directory within the Jackify data directory."""
    return get_jackify_data_dir() / "downloaded_mod_lists"


def get_jackify_config_dir() -> Path:
    """
    Get the Jackify configuration directory (always ~/.config/jackify).
    
    This directory contains:
    - config.json (settings)
    - API keys and credentials
    - Resource settings
    
    Returns:
        Path: Always ~/.config/jackify
    """
    return Path.home() / ".config" / "jackify"


def cleanup_stale_tmp() -> None:
    """Remove stale engine temp directories from the Jackify tmp dir.

    The engine writes TTW working files (xd3 patches, patch manifests) into
    UUID-named subdirectories under <data_dir>/.tmp/ during TTW installation.
    These are never cleaned up on failure or interruption and can accumulate
    several GB per run. Any such directory present at startup is always stale -
    no TTW install can be in flight before the application has started.

    jackify-proton-extraction is also cleaned up - the engine no longer uses it
    and it can accumulate ~700MB.
    """
    tmp_dir = get_jackify_data_dir() / ".tmp"
    if not tmp_dir.is_dir():
        return

    stale_prefixes = ("ttw_mpi_", "ttw_ogg_", "jackify-proton-extraction")
    removed = 0
    freed = 0

    for entry in tmp_dir.iterdir():
        if not any(entry.name.startswith(p) for p in stale_prefixes):
            continue
        try:
            if entry.is_dir():
                size = sum(f.stat().st_size for f in entry.rglob("*") if f.is_file())
                shutil.rmtree(entry)
            else:
                size = entry.stat().st_size
                entry.unlink()
            freed += size
            removed += 1
            logger.debug(f"Removed stale engine tmp: {entry.name}")
        except Exception as e:
            logger.warning(f"Could not remove stale engine tmp {entry.name}: {e}")

    if removed:
        freed_mb = freed / (1024 * 1024)
        logger.info(f"Cleaned {removed} stale engine tmp entries ({freed_mb:.0f} MB freed)")