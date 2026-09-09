import logging
import shutil
from pathlib import Path
from typing import Union

logger = logging.getLogger(__name__)

PROFILES_BACKUP_DIRNAME = "profiles_backup"


def backup_modlist_profiles(install_dir: Union[str, Path]) -> bool:
    """Copy a modlist's profiles/ directory to profiles_backup/ inside the install dir.

    Replaces any existing backup rather than accumulating history - this is a single
    last-known-good safety net, not a versioned archive. Never raises; failures are
    logged and reported via the return value so a backup problem never blocks an
    otherwise-successful install or update.
    """
    install_dir = Path(install_dir)
    profiles_dir = install_dir / "profiles"
    backup_dir = install_dir / PROFILES_BACKUP_DIRNAME

    if not profiles_dir.is_dir():
        logger.debug(f"No profiles directory to back up at {profiles_dir}")
        return False

    try:
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
        shutil.copytree(profiles_dir, backup_dir)
        logger.info(f"Backed up profiles directory to {backup_dir}")
        return True
    except Exception as e:
        logger.warning(f"Failed to back up profiles directory for {install_dir}: {e}")
        return False
