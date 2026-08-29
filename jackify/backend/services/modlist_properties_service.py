"""
Backend actions for the Modlist Dashboard's Properties popout that aren't already served by an
existing service (install_registry.py for data, modlist_uninstall_service.py for uninstall,
dashboard_images.py for artwork).

Currently just Proton version changes. NativeSteamService.set_proton_version() edits config.vdf
directly, the same class of risk as editing shortcuts.vdf - Steam must be shut down first or it
can overwrite the change right back, so this follows the same shutdown -> edit -> restart shape
as modlist_uninstall_service.py rather than calling set_proton_version() with Steam still running.
"""
import logging
from typing import Callable, List, Optional, Tuple

logger = logging.getLogger(__name__)


def list_available_proton_versions() -> List[str]:
    """Names of every Proton build Jackify can detect, best (most recent GE) first."""
    from jackify.backend.handlers.wine_utils import WineUtils
    try:
        return [v["name"] for v in WineUtils.scan_all_proton_versions() if v.get("name")]
    except Exception as e:
        logger.warning("Could not list Proton versions: %s", e)
        return []


def change_proton_version(
    appid: str, proton_version: str, progress_callback: Optional[Callable[[str], None]] = None
) -> Tuple[bool, str]:
    """Returns (success, message)."""
    def report(msg: str) -> None:
        logger.info(msg)
        if progress_callback:
            progress_callback(msg)

    from .steam_restart_service import shutdown_steam, start_steam
    from .native_steam_service import NativeSteamService

    report("Shutting down Steam...")
    if not shutdown_steam():
        return False, "Steam did not shut down - Proton version was not changed."

    try:
        ok = NativeSteamService().set_proton_version(int(appid), proton_version)
    except Exception as e:
        logger.error("Proton version change failed for appid %s: %s", appid, e, exc_info=True)
        ok = False

    report("Restarting Steam...")
    restarted = start_steam()

    if not ok:
        return False, f"Could not set Proton version to {proton_version}."
    if not restarted:
        return True, "Proton version changed, but Steam did not restart automatically - start it manually."
    return True, ""
