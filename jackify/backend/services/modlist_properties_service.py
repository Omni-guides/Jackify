"""
Backend actions for the Modlist Dashboard's Properties popout that aren't already served by an
existing service (install_registry.py for data, modlist_uninstall_service.py for uninstall,
dashboard_images.py for artwork).

Proton version changes and MO2 Skip toggling. Both edit files Steam holds open while running
(config.vdf, shortcuts.vdf) - Steam must be shut down first or it can overwrite the change right
back, so both follow the same shutdown -> edit -> restart shape as modlist_uninstall_service.py
rather than editing with Steam still running.
"""
import logging
import os
import re
from typing import Callable, List, Optional, Tuple

logger = logging.getLogger(__name__)

# MO2's own MOShortcut parser (moshortcut.cpp) treats anything before the first ':' after the
# scheme as an *instance name*, used to disambiguate which registered MO2 instance a shortcut
# is for (isForInstance(): matches an empty instance or an absolute directory path against a
# portable install, or a display name against a registered one - see envshortcut.cpp:365 for
# MO2's own shortcut generator using the absolute path form). A Wabbajack/Jackify modlist is
# always a self-contained portable install with no registered instance, and the Steam shortcut
# this gets embedded in already points its StartDir at that exact modlist directory - there is
# nothing to disambiguate, so no instance name is needed at all: "moshortcut://<executable>",
# not "moshortcut://<modlist name>:<executable>" (the modlist's display name matches neither of
# isForInstance()'s checks and silently fails to resolve - confirmed by a live report).
#
# The whole token is one shell word with no quoting of its own, so it gets wrapped in a single
# pair of quotes whenever the title contains spaces. Recognise both that quoted form and a bare
# unquoted one (e.g. hand-added by a user, no spaces), and both the current no-instance form and
# the old instance-prefixed one (already-added entries from before this fix), so any existing
# moshortcut entry is still detected and removable regardless of which form added it.
_MOSHORTCUT_RE = re.compile(r'\s*"moshortcut://[^"]*"\s*$|\s*moshortcut://\S*\s*$')


def is_mo2_skip_enabled(launch_options: str) -> bool:
    return "moshortcut://" in (launch_options or "")


def _add_moshortcut(launch_options: str, binary_title: str) -> str:
    return f'{launch_options.rstrip()} "moshortcut://{binary_title}"'


def _remove_moshortcut(launch_options: str) -> str:
    return _MOSHORTCUT_RE.sub('', launch_options or '').rstrip()


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


def _get_shortcut_handler():
    from jackify.backend.handlers.shortcut_handler import ShortcutHandler
    from jackify.backend.services.platform_detection_service import PlatformDetectionService

    platform_service = PlatformDetectionService.get_instance()
    return ShortcutHandler(steamdeck=platform_service.is_steamdeck, verbose=False)


def mo2_skip_status(install_dir: str, modlist_name: str) -> bool:
    """Whether the modlist's Steam shortcut currently has a moshortcut:// launch option."""
    exe_path = os.path.join(install_dir, "ModOrganizer.exe")
    current = _get_shortcut_handler().get_shortcut_launch_options(modlist_name, exe_path)
    return is_mo2_skip_enabled(current or "")


def toggle_mo2_skip(
    install_dir: str, modlist_name: str, binary_title: Optional[str] = None,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> Tuple[bool, str]:
    """
    Add or remove a moshortcut:// launch option on the modlist's Steam shortcut, so MO2
    skips straight to the given executable on launch. Pass `binary_title` to add the skip;
    omit it to remove an existing one. Returns (success, message).
    """
    def report(msg: str) -> None:
        logger.info(msg)
        if progress_callback:
            progress_callback(msg)

    from .steam_restart_service import shutdown_steam, start_steam

    handler = _get_shortcut_handler()
    exe_path = os.path.join(install_dir, "ModOrganizer.exe")

    current = handler.get_shortcut_launch_options(modlist_name, exe_path)
    if current is None:
        return False, "Could not find this modlist's Steam shortcut."

    if is_mo2_skip_enabled(current):
        new_options = _remove_moshortcut(current)
        action = "Removing"
    else:
        if not binary_title:
            return False, "No executable was selected to launch."
        new_options = _add_moshortcut(current, binary_title)
        action = "Adding"

    report("Shutting down Steam...")
    if not shutdown_steam():
        return False, "Steam did not shut down - MO2 Skip was not changed."

    ok = handler.update_shortcut_launch_options(modlist_name, exe_path, new_options)

    report("Restarting Steam...")
    restarted = start_steam()

    if not ok:
        return False, f"{action} MO2 Skip failed."
    if not restarted:
        return True, "MO2 Skip updated, but Steam did not restart automatically - start it manually."
    return True, ""
