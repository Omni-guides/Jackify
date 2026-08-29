"""
Launching an already-installed Steam entry (game or non-Steam shortcut).

Separate from steam_restart_service.py, which owns starting/stopping the Steam client
itself - this is a single, narrow action (launch one app) built on top of that module's
already-proven native-vs-Flatpak detection and AppImage-env-stripping helpers.
"""
import logging
import subprocess

from jackify.backend.services.steam_restart_service import (
    _get_clean_subprocess_env,
    _get_flatpak_command,
    _get_steam_executable,
    is_flatpak_steam,
)

logger = logging.getLogger(__name__)


def _shortcut_rungameid(legacy_appid: int) -> int:
    """
    Convert a non-Steam shortcut's legacy 32-bit AppID (the value stored in shortcuts.vdf,
    used for compatdata/CompatToolMapping/grid artwork, and what Jackify's own install
    registry stores as entry.appid) into the 64-bit ID Steam's `steam://rungameid/` URI
    actually expects for shortcuts specifically.

    Confirmed by reading a real shortcuts.vdf directly: Jackify's stored appid for "Tuxborn"
    is 3761760148 (unsigned reading of the same bit pattern shortcuts.vdf stores as the
    signed int -533207148 - both correct for CompatToolMapping/protontricks/grid art, which
    all use the legacy 32-bit form). Neither that legacy id nor Steam's `-applaunch` flag
    launches a shortcut ("Game configuration unavailable"); the 64-bit form
    `(legacy << 32) | 0x02000000` is Steam's own documented shortcut-launch ID, shown by the
    client itself when copying a non-Steam game's Steam URL.
    """
    return (legacy_appid << 32) | 0x02000000


def launch_steam_app(appid: str) -> bool:
    """
    Launch an installed Steam entry (always a non-Steam shortcut for Dashboard entries) via
    `steam://rungameid/<64-bit shortcut id>`, invoking Steam directly rather than going
    through xdg-open (depends on x-scheme-handler/steam resolving correctly - tried first,
    had no visible effect) or `-applaunch` with the legacy 32-bit id (tried next, produced
    Steam's own "Game configuration unavailable" error).
    """
    env = _get_clean_subprocess_env()
    try:
        rungameid = _shortcut_rungameid(int(appid))
        uri = f"steam://rungameid/{rungameid}"
        if is_flatpak_steam():
            flatpak_cmd = _get_flatpak_command() or "flatpak"
            cmd = [flatpak_cmd, "run", "com.valvesoftware.Steam", uri]
        else:
            cmd = [_get_steam_executable(env), uri]
        logger.info("Launching Steam app %s via: %s", appid, cmd)
        subprocess.Popen(
            cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return True
    except Exception as e:
        logger.error("Failed to launch Steam app %s: %s", appid, e)
        return False
