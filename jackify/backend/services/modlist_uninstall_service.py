"""
Uninstall a modlist Jackify's Lifecycle Dashboard knows about: Steam shortcut, Proton prefix,
install directory, cached dashboard artwork, and its registry entry.

Steam must be shut down first - editing shortcuts.vdf while Steam is running risks Steam
rewriting it back over our change, the same reason shortcut creation shuts Steam down first.
Restarted at the end regardless of what failed in between, so the user is never left with Steam
down. Every step is independent and best-effort: one failing (e.g. prefix already gone) must not
block the rest, since the goal is "get as clean as possible," not "abort on the first surprise."
"""
import logging
import shutil
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from .install_registry import InstallEntry, remove_from_registry
from .dashboard_images import remove_cached_image

logger = logging.getLogger(__name__)


def uninstall_modlist(
    entry: InstallEntry, progress_callback: Optional[Callable[[str], None]] = None
) -> Tuple[bool, str]:
    """Returns (success, message). success is False only if Steam itself failed to come back up
    or come down; individual missing-file cleanup steps are logged but never fail the whole
    operation."""
    def report(msg: str) -> None:
        logger.info(msg)
        if progress_callback:
            progress_callback(msg)

    from .steam_restart_service import shutdown_steam, start_steam_and_wait
    from .native_steam_service import NativeSteamService
    from jackify.backend.handlers.path_handler import PathHandler

    report("Shutting down Steam...")
    if not shutdown_steam():
        return False, "Steam did not shut down - uninstall aborted to avoid corrupting shortcuts.vdf."

    warnings: List[str] = []

    if entry.appid:
        try:
            if NativeSteamService().remove_shortcut(entry.modlist_name):
                report(f"Removed Steam shortcut '{entry.modlist_name}'")
            else:
                warnings.append(f"Steam shortcut '{entry.modlist_name}' was not found (already removed?)")
        except Exception as e:
            warnings.append(f"Could not remove Steam shortcut: {e}")
            logger.warning("Uninstall: shortcut removal failed for %s: %s", entry.modlist_name, e)

        try:
            compat_data = PathHandler.find_compat_data(str(entry.appid))
            if compat_data and compat_data.is_dir():
                shutil.rmtree(compat_data)
                report(f"Removed Proton prefix: {compat_data}")
        except Exception as e:
            warnings.append(f"Could not remove Proton prefix: {e}")
            logger.warning("Uninstall: prefix removal failed for appid %s: %s", entry.appid, e)

    try:
        install_path = Path(entry.install_dir)
        if install_path.is_dir():
            shutil.rmtree(install_path)
            report(f"Removed install directory: {entry.install_dir}")
        else:
            # Otherwise this reports a clean uninstall with the files still on disk
            warnings.append(
                f"The install directory was not available, so the modlist's files were left in "
                f"place. Remove them yourself if the drive comes back:\n{entry.install_dir}"
            )
            report("Install directory not available - files left in place")
    except Exception as e:
        warnings.append(f"Could not remove install directory: {e}")
        logger.warning("Uninstall: install dir removal failed for %s: %s", entry.install_dir, e)

    remove_cached_image(entry.install_id)
    remove_from_registry(entry.install_id)

    if not start_steam_and_wait(progress_callback=report):
        warnings.append("Steam did not restart automatically - start it manually.")

    return True, "\n".join(warnings)
