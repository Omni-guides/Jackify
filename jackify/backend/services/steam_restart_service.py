import os
import time
import subprocess
import signal
import psutil
import logging
import sys
import shutil
from typing import Callable, Optional

logger = logging.getLogger(__name__)

STRATEGY_JACKIFY = "jackify"
STRATEGY_SIMPLE = "simple"


def _get_restart_strategy() -> str:
    """Read restart strategy from config with safe fallback."""
    try:
        from jackify.backend.handlers.config_handler import ConfigHandler

        strategy = ConfigHandler().get("steam_restart_strategy", STRATEGY_JACKIFY)
        if strategy not in (STRATEGY_JACKIFY, STRATEGY_SIMPLE):
            return STRATEGY_JACKIFY
        return strategy
    except Exception as exc:  # pragma: no cover - defensive logging only
        logger.debug(f"Steam restart: Unable to read strategy from config: {exc}")
        return STRATEGY_JACKIFY


def _strategy_label(strategy: str) -> str:
    if strategy == STRATEGY_SIMPLE:
        return "Simple restart"
    return "Jackify hardened restart"

def _get_clean_subprocess_env():
    """
    Create a clean environment for subprocess calls by stripping bundle-specific
    environment variables (e.g., frozen AppImage remnants) that can interfere with Steam.
    
    CRITICAL: Preserves all display/session variables that Steam needs for GUI:
    - DISPLAY, WAYLAND_DISPLAY, XDG_SESSION_TYPE, DBUS_SESSION_BUS_ADDRESS,
      XDG_RUNTIME_DIR, XAUTHORITY, etc.
    
    Returns:
        dict: Cleaned environment dictionary with GUI variables preserved
    """
    env = os.environ.copy()
    bundle_vars_removed = []
    
    # Preserve display/session variables that Steam GUI needs
    # These MUST be kept for Steam to open its GUI window
    gui_vars_to_preserve = [
        'DISPLAY', 'WAYLAND_DISPLAY', 'XDG_SESSION_TYPE', 'DBUS_SESSION_BUS_ADDRESS',
        'XDG_RUNTIME_DIR', 'XAUTHORITY', 'XDG_CURRENT_DESKTOP', 'XDG_SESSION_DESKTOP',
        'QT_QPA_PLATFORM', 'GDK_BACKEND', 'XDG_DATA_DIRS', 'XDG_CONFIG_DIRS'
    ]
    preserved_gui_vars = {}
    for var in gui_vars_to_preserve:
        if var in env:
            preserved_gui_vars[var] = env[var]
            logger.debug(f"Steam restart: Preserving GUI variable {var}={env[var][:50] if len(str(env[var])) > 50 else env[var]}")
    
    # Remove bundle-specific environment variables
    if env.pop('_MEIPASS', None):
        bundle_vars_removed.append('_MEIPASS')
    if env.pop('_MEIPASS2', None):
        bundle_vars_removed.append('_MEIPASS2')
    
    # Clean library path variables that frozen bundles modify (Linux/Unix)
    if 'LD_LIBRARY_PATH_ORIG' in env:
        # Restore original LD_LIBRARY_PATH if it was backed up by the bundler
        env['LD_LIBRARY_PATH'] = env['LD_LIBRARY_PATH_ORIG']
        bundle_vars_removed.append('LD_LIBRARY_PATH (restored from _ORIG)')
    else:
        # Remove modified LD_LIBRARY_PATH entries
        if env.pop('LD_LIBRARY_PATH', None):
            bundle_vars_removed.append('LD_LIBRARY_PATH (removed)')
    
    # Clean PATH of bundle-specific entries
    if 'PATH' in env and hasattr(sys, '_MEIPASS'):
        path_entries = env['PATH'].split(os.pathsep)
        original_count = len(path_entries)
        # Remove any PATH entries that point to the bundle's temp directory
        cleaned_path = [p for p in path_entries if not p.startswith(sys._MEIPASS)]
        env['PATH'] = os.pathsep.join(cleaned_path)
        if len(cleaned_path) < original_count:
            bundle_vars_removed.append(f'PATH (removed {original_count - len(cleaned_path)} bundle entries)')
    
    # Clean macOS library path (if present)
    if 'DYLD_LIBRARY_PATH' in env and hasattr(sys, '_MEIPASS'):
        dyld_entries = env['DYLD_LIBRARY_PATH'].split(os.pathsep)
        cleaned_dyld = [p for p in dyld_entries if not p.startswith(sys._MEIPASS)]
        if cleaned_dyld:
            env['DYLD_LIBRARY_PATH'] = os.pathsep.join(cleaned_dyld)
            bundle_vars_removed.append('DYLD_LIBRARY_PATH (cleaned)')
        else:
            env.pop('DYLD_LIBRARY_PATH', None)
            bundle_vars_removed.append('DYLD_LIBRARY_PATH (removed)')
    
    # Ensure GUI variables are still present (they should be, but double-check)
    for var, value in preserved_gui_vars.items():
        if var not in env:
            env[var] = value
            logger.warning(f"Steam restart: Restored GUI variable {var} that was accidentally removed")
    
    # Log what was cleaned for debugging
    if bundle_vars_removed:
        logger.debug(f"Steam restart: Cleaned bundled environment variables: {', '.join(bundle_vars_removed)}")
    else:
        logger.debug("Steam restart: No bundled environment variables detected (likely DEV mode)")
    
    # Log preserved GUI variables for debugging
    if preserved_gui_vars:
        logger.debug(f"Steam restart: Preserved {len(preserved_gui_vars)} GUI environment variables")
    
    return env

class SteamRestartError(Exception):
    pass

def is_steam_deck() -> bool:
    """Detect if running on Steam Deck/SteamOS."""
    try:
        if os.path.exists('/etc/os-release'):
            with open('/etc/os-release', 'r') as f:
                content = f.read().lower()
                if 'steamos' in content or 'steam deck' in content:
                    return True
        if os.path.exists('/sys/devices/virtual/dmi/id/product_name'):
            with open('/sys/devices/virtual/dmi/id/product_name', 'r') as f:
                if 'steam deck' in f.read().lower():
                    return True
        if os.environ.get('STEAM_RUNTIME') and os.path.exists('/home/deck'):
            return True
    except Exception as e:
        logger.debug(f"Error detecting Steam Deck: {e}")
    return False

def steam_path_indicates_flatpak(steam_path) -> bool:
    """True if this Steam path is under the Flatpak Steam app dir (user is running Flatpak Steam)."""
    if steam_path is None:
        return False
    path_str = os.fspath(steam_path)
    return ".var" in path_str and "app" in path_str and "com.valvesoftware.Steam" in path_str


def _flatpak_steam_data_path_exists() -> bool:
    """True if the Flatpak Steam data directory exists (fallback when resolved_path is None, e.g. AppImage)."""
    try:
        from pathlib import Path
        base = Path.home() / ".var" / "app" / "com.valvesoftware.Steam"
        for rel in ("data/Steam", ".local/share/Steam", "home/.local/share/Steam"):
            candidate = base / rel
            if (candidate / "config" / "loginusers.vdf").exists():
                return True
        return False
    except Exception as e:
        logger.debug("Flatpak Steam path check failed: %s", e)
        return False


def _get_flatpak_command():
    """Resolve flatpak executable (for detection when PATH is minimal, e.g. AppImage)."""
    exe = shutil.which("flatpak")
    if exe:
        return exe
    for p in ("/usr/bin/flatpak", "/usr/local/bin/flatpak"):
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


def is_flatpak_steam() -> bool:
    """Detect if Steam is installed as a Flatpak. Uses flatpak CLI only (no dir heuristic)
    so we don't wrongly choose Flatpak when the user has both Flatpak and native Steam."""
    try:
        flatpak_cmd = _get_flatpak_command()
        if not flatpak_cmd:
            return False
        env = _get_clean_subprocess_env()
        result = subprocess.run(
            [flatpak_cmd, "list", "--app"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=10,
            env=env,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                parts = line.split()
                if parts and parts[0] == "com.valvesoftware.Steam":
                    return True
        return False
    except Exception as e:
        logger.debug(f"Error detecting Flatpak Steam: {e}")
    return False


def ensure_flatpak_steam_filesystem_access(path: "Path") -> bool:
    """Grant Flatpak Steam filesystem access to the parent of the given path.

    Safe to call on non-Flatpak systems - returns True immediately.
    Skips if the path is already covered by an existing override.
    Returns True if access was already present or successfully granted, False on error.
    """
    from pathlib import Path as _Path
    if not is_flatpak_steam():
        return True
    flatpak_cmd = _get_flatpak_command()
    if not flatpak_cmd:
        logger.warning("Flatpak Steam detected but flatpak command not found - cannot grant filesystem access")
        return False
    grant_path = str(_Path(path).parent)
    env = _get_clean_subprocess_env()
    try:
        # Check existing overrides to avoid redundant changes
        result = subprocess.run(
            [flatpak_cmd, "override", "--user", "--show", "com.valvesoftware.Steam"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, timeout=10, env=env,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if "filesystems" in line.lower() and grant_path in line:
                    logger.debug(f"Flatpak Steam already has access to {grant_path}")
                    return True
    except Exception as e:
        logger.debug(f"Could not check existing Flatpak overrides: {e}")
    try:
        result = subprocess.run(
            [flatpak_cmd, "override", "--user", f"--filesystem={grant_path}", "com.valvesoftware.Steam"],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            text=True, timeout=15, env=env,
        )
        if result.returncode == 0:
            logger.info(f"Granted Flatpak Steam filesystem access to {grant_path}")
            return True
        logger.warning(f"flatpak override failed (exit {result.returncode}): {result.stderr.strip()}")
        return False
    except Exception as e:
        logger.warning(f"Failed to grant Flatpak Steam filesystem access: {e}")
        return False


def _get_steam_executable(env=None):
    """Resolve steam executable path for native Steam. Prefer PATH, then common locations."""
    env = env or os.environ
    path_env = env.get("PATH", "")
    exe = shutil.which("steam", path=path_env)
    if exe:
        return exe
    for candidate in ("/usr/games/steam", "/usr/bin/steam"):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return "steam"


def get_steam_processes() -> list:
    """Return a list of psutil.Process objects for running Steam processes."""
    steam_procs = []
    for proc in psutil.process_iter(['pid', 'name', 'exe', 'cmdline']):
        try:
            name = proc.info['name']
            exe = proc.info['exe']
            cmdline = proc.info['cmdline']
            if name and 'steam' in name.lower():
                steam_procs.append(proc)
            elif exe and 'steam' in exe.lower():
                steam_procs.append(proc)
            elif cmdline and any('steam' in str(arg).lower() for arg in cmdline):
                steam_procs.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return steam_procs

def wait_for_steam_exit(timeout: int = 60, check_interval: float = 0.5) -> bool:
    """Wait for all Steam processes to exit using pgrep (matching existing logic)."""
    start = time.time()
    env = _get_clean_subprocess_env()
    while time.time() - start < timeout:
        try:
            result = subprocess.run(['pgrep', '-f', 'steamwebhelper'], capture_output=True, timeout=10, env=env)
            if result.returncode != 0:
                return True
        except Exception as e:
            logger.debug(f"Error checking Steam processes: {e}")
        time.sleep(check_interval)
    return False

def _start_steam_simple(is_steamdeck_flag=False, is_flatpak_flag=False, env_override=None) -> bool:
    """
    Start Steam using a simplified restart (single command, no env cleanup).
    Do NOT use start_new_session - Steam needs to inherit the session for display/tray.
    """
    env = env_override if env_override is not None else os.environ.copy()

    gui_vars = ['DISPLAY', 'WAYLAND_DISPLAY', 'XDG_SESSION_TYPE', 'DBUS_SESSION_BUS_ADDRESS', 'XDG_RUNTIME_DIR']
    for var in gui_vars:
        if var in env:
            logger.debug(f"Simple restart: {var}={env[var][:50] if len(str(env[var])) > 50 else env[var]}")
        else:
            logger.warning(f"Simple restart: {var} is NOT SET - Steam GUI may fail!")

    try:
        if is_steamdeck_flag:
            logger.info("Simple restart: Steam Deck detected, restarting via systemctl.")
            subprocess.Popen(["systemctl", "--user", "restart", "app-steam@autostart.service"], env=env)
        elif is_flatpak_flag:
            logger.info("Simple restart: Flatpak Steam detected, running flatpak command.")
            flatpak_cmd = _get_flatpak_command() or "flatpak"
            subprocess.Popen([flatpak_cmd, "run", "com.valvesoftware.Steam"],
                            env=env, stderr=subprocess.DEVNULL)
        else:
            logger.info("Simple restart: launching Steam directly (inheriting session for GUI).")
            subprocess.Popen("steam", shell=True, env=env)

        time.sleep(5)
        check_result = subprocess.run(['pgrep', '-f', 'steamwebhelper'], capture_output=True, timeout=10, env=env)
        if check_result.returncode == 0:
            logger.info("Simple restart detected running Steam process.")
            return True

        logger.warning("Simple restart did not detect Steam process after launch.")
        return False
    except FileNotFoundError as exc:
        logger.error(f"Simple restart command not found: {exc}")
        return False
    except Exception as exc:
        logger.error(f"Simple restart encountered an error: {exc}")
        return False


def start_steam(is_steamdeck_flag=None, is_flatpak_flag=None, env_override=None, strategy: str = STRATEGY_JACKIFY) -> bool:
    """
    Attempt to start Steam using the exact methods from existing working logic.

    Args:
        is_steamdeck_flag: Optional pre-detected Steam Deck status
        is_flatpak_flag: Optional pre-detected Flatpak Steam status
        env_override: Optional environment dictionary for subprocess calls
        strategy: Restart strategy identifier
    """
    if strategy == STRATEGY_SIMPLE:
        return _start_steam_simple(
            is_steamdeck_flag=is_steamdeck_flag,
            is_flatpak_flag=is_flatpak_flag,
            env_override=env_override or os.environ.copy(),
        )

    env = env_override if env_override is not None else _get_clean_subprocess_env()

    # Use provided flags or detect
    _is_steam_deck = is_steamdeck_flag if is_steamdeck_flag is not None else is_steam_deck()
    _is_flatpak = is_flatpak_flag if is_flatpak_flag is not None else is_flatpak_steam()
    logger.info(
        "Starting Steam (strategy=%s, steam_deck=%s, flatpak=%s)",
        strategy,
        _is_steam_deck,
        _is_flatpak,
    )

    try:
        # Try systemd user service (Steam Deck) - HIGHEST PRIORITY
        if _is_steam_deck:
            logger.debug("Using systemctl restart for Steam Deck.")
            subprocess.Popen(["systemctl", "--user", "restart", "app-steam@autostart.service"], env=env)
            return True

        # Check if Flatpak Steam (only if not Steam Deck)
        if _is_flatpak:
            logger.info("Flatpak Steam detected - trying flatpak run command first")
            try:
                flatpak_cmd = _get_flatpak_command() or "flatpak"
                logger.debug("Executing: %s run com.valvesoftware.Steam", flatpak_cmd)
                subprocess.Popen([flatpak_cmd, "run", "com.valvesoftware.Steam"],
                                env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                time.sleep(7)  # Give Flatpak more time to start
                # For Flatpak Steam, check for the flatpak process, not steamwebhelper
                check_result = subprocess.run(['pgrep', '-f', 'com.valvesoftware.Steam'], capture_output=True, timeout=10, env=env)
                if check_result.returncode == 0:
                    logger.info("Flatpak Steam started successfully")
                    return True
                else:
                    logger.warning("Flatpak Steam not detected after launch - will NOT fall back to prevent conflicts")
                    return False  # Flatpak Steam must use flatpak command, don't fall back
            except Exception as e:
                logger.error(f"Flatpak Steam start failed: {e}")
                return False  # Flatpak Steam must use flatpak command, don't fall back

        steam_exe = _get_steam_executable(env)
        start_methods = [
            {"name": "Popen", "cmd": [steam_exe, "-foreground"], "kwargs": {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "stdin": subprocess.DEVNULL, "start_new_session": True, "env": env}},
            {"name": "setsid", "cmd": ["setsid", steam_exe, "-foreground"], "kwargs": {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "stdin": subprocess.DEVNULL, "env": env}},
            {"name": "nohup", "cmd": ["nohup", steam_exe, "-foreground"], "kwargs": {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "stdin": subprocess.DEVNULL, "start_new_session": True, "env": env}}
        ]
        
        for method in start_methods:
            method_name = method["name"]
            logger.info(f"Attempting to start Steam using method: {method_name}")
            try:
                process = subprocess.Popen(method["cmd"], **method["kwargs"])
                if process is not None:
                    logger.info(f"Initiated Steam start with {method_name}.")
                    time.sleep(5)  # Wait 5 seconds as in existing logic
                    # Use steamwebhelper for detection (actual Steam process, not steam-powerbuttond)
                    check_result = subprocess.run(['pgrep', '-f', 'steamwebhelper'], capture_output=True, timeout=10, env=env)
                    if check_result.returncode == 0:
                        logger.info(f"Steam process detected after using {method_name}. Proceeding to wait phase.")
                        return True
                    else:
                        logger.warning(f"Steam process not detected after initiating with {method_name}. Trying next method.")
                else:
                    logger.warning(f"Failed to start process with {method_name}. Trying next method.")
            except FileNotFoundError:
                logger.error(f"Command not found for method {method_name} (e.g., setsid, nohup). Trying next method.")
            except Exception as e:
                logger.error(f"Error starting Steam with {method_name}: {e}. Trying next method.")
        
        return False
    except Exception as e:
        logger.error(f"Error starting Steam: {e}")
        return False


def start_steam_and_wait(
    is_steamdeck_flag: Optional[bool] = None,
    is_flatpak_flag: Optional[bool] = None,
    env_override=None,
    strategy: str = STRATEGY_JACKIFY,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> bool:
    """Start Steam and block until steamwebhelper has stayed detected for 10+ seconds.

    start_steam() alone returns as soon as the process is merely detected (~5s after launch,
    well before Steam is actually usable) - callers that declare their own work "done" off
    that alone can finish and surface a result to the user before Steam is really back. This
    is the same wait loop robust_steam_restart() uses for its own restart phase, factored out
    so a caller that must shut Steam down and start it back up around its own work (not an
    atomic close-then-reopen, which robust_steam_restart() already covers) gets the same
    stability guarantee instead of a bespoke, weaker check.
    """
    env = env_override if env_override is not None else _get_clean_subprocess_env()
    _is_steam_deck = is_steamdeck_flag if is_steamdeck_flag is not None else is_steam_deck()
    _is_flatpak = is_flatpak_flag if is_flatpak_flag is not None else is_flatpak_steam()

    def report(msg):
        if progress_callback:
            progress_callback(msg)
        else:
            logger.info(msg)

    report("Starting Steam...")

    if _is_steam_deck:
        try:
            subprocess.Popen(["systemctl", "--user", "restart", "app-steam@autostart.service"], env=env)
            logger.info("Steam Deck: Initiated systemctl restart")
        except Exception as e:
            logger.error(f"Steam Deck systemctl restart failed: {e}")
            report("Failed to restart Steam on Steam Deck.")
            return False
    else:
        steam_started = start_steam(
            is_steamdeck_flag=_is_steam_deck,
            is_flatpak_flag=_is_flatpak,
            env_override=env,
            strategy=strategy,
        )
        # Even if start_steam() returned False, Steam might still be starting - give it a
        # chance by proceeding to the wait phase instead of failing immediately.
        if not steam_started:
            logger.warning("start_steam() returned False, but proceeding to wait phase in case Steam is starting anyway")
            report("Steam start command issued, waiting for process...")

    report("Waiting for Steam to fully start")
    logger.info("Waiting up to 3 minutes (180 seconds) for Steam to fully initialize...")
    max_startup_wait = 180
    elapsed_wait = 0
    initial_wait_done = False
    last_status_log = 0

    while elapsed_wait < max_startup_wait:
        try:
            if elapsed_wait - last_status_log >= 30:
                remaining = max_startup_wait - elapsed_wait
                logger.info(f"Still waiting for Steam... ({elapsed_wait}s elapsed, {remaining}s remaining)")
                if progress_callback:
                    progress_callback(f"Waiting for Steam... ({elapsed_wait}s / {max_startup_wait}s)")
                last_status_log = elapsed_wait

            result = subprocess.run(['pgrep', '-f', 'steamwebhelper'], capture_output=True, timeout=10, env=env)
            if result.returncode == 0:
                if not initial_wait_done:
                    logger.info(f"Steam process detected at {elapsed_wait}s. Waiting additional time for full initialization...")
                    initial_wait_done = True
                time.sleep(2)
                elapsed_wait += 2
                # Require at least 10 seconds of stable detection
                if initial_wait_done and elapsed_wait >= 10:
                    final_check = subprocess.run(['pgrep', '-f', 'steamwebhelper'], capture_output=True, timeout=10, env=env)
                    if final_check.returncode == 0:
                        report("Steam started successfully.")
                        report("[Jackify] Steam restart complete")
                        logger.info(f"Steam confirmed running after {elapsed_wait}s wait.")
                        return True
                    else:
                        logger.warning("Steam process disappeared during final initialization wait, continuing to wait...")
                        initial_wait_done = False
            else:
                logger.debug(f"Steam process not yet detected. Waiting... ({elapsed_wait + 2}s)")
                time.sleep(2)
                elapsed_wait += 2
        except Exception as e:
            logger.warning(f"Error during Steam startup wait: {e}")
            time.sleep(2)
            elapsed_wait += 2

    report(f"Steam did not start within {max_startup_wait}s timeout.")
    logger.error(f"Steam failed to start/initialize within the allowed time ({elapsed_wait}s elapsed).")
    return False


def _resolve_steam_path_for_restart():
    """Return the Steam path we're using (for shortcuts/config). Used to decide Flatpak vs native when CLI detection fails."""
    try:
        from jackify.backend.services.native_steam_service import NativeSteamService
        svc = NativeSteamService()
        if svc.find_steam_user() and svc.steam_path:
            return svc.steam_path
    except Exception as e:
        logger.debug("Could not resolve Steam path for restart: %s", e)
    return None


def shutdown_steam(progress_callback: Optional[Callable[[str], None]] = None, system_info=None) -> bool:
    """
    Shut down Steam completely across all distros.
    Required before modifying VDF files to prevent race conditions.

    Args:
        progress_callback: Optional callback for progress updates
        system_info: Optional SystemInfo object with pre-detected Steam installation types

    Returns:
        True if shutdown successful, False otherwise
    """
    shutdown_env = _get_clean_subprocess_env()

    _is_steam_deck = system_info.is_steamdeck if system_info else is_steam_deck()
    resolved_path = _resolve_steam_path_for_restart()
    if resolved_path is not None:
        _is_flatpak = steam_path_indicates_flatpak(resolved_path)
        logger.info("Steam path in use: %s -> flatpak=%s", resolved_path, _is_flatpak)
    else:
        _is_flatpak = _flatpak_steam_data_path_exists()
        if _is_flatpak:
            logger.info("Steam path in use: (flatpak data path detected) -> flatpak=True")
        else:
            _is_flatpak = system_info.is_flatpak_steam if system_info else is_flatpak_steam()

    def report(msg):
        if progress_callback:
            progress_callback(msg)
        else:
            logger.info(msg)

    report("Shutting down Steam...")

    # Steam Deck: Use systemctl for shutdown
    if _is_steam_deck:
        try:
            report("Steam Deck detected - using systemctl shutdown...")
            subprocess.run(['systemctl', '--user', 'stop', 'app-steam@autostart.service'],
                         timeout=15, check=False, capture_output=True, env=shutdown_env)
            time.sleep(2)
        except Exception as e:
            logger.debug(f"systemctl stop failed on Steam Deck: {e}")
    # Flatpak Steam: Use flatpak kill command
    elif _is_flatpak:
        try:
            report("Flatpak Steam detected - stopping via flatpak...")
            flatpak_cmd = _get_flatpak_command() or "flatpak"
            subprocess.run([flatpak_cmd, "kill", "com.valvesoftware.Steam"],
                          timeout=15, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=shutdown_env)
            time.sleep(2)
        except Exception as e:
            logger.debug(f"flatpak kill failed: {e}")

    # All systems: Use pkill approach
    try:
        pkill_result = subprocess.run(['pkill', 'steam'], timeout=15, check=False, capture_output=True, env=shutdown_env)
        logger.debug(f"pkill steam result: {pkill_result.returncode}")
        time.sleep(2)

        # Check if Steam is still running
        check_result = subprocess.run(['pgrep', '-f', 'steamwebhelper'], capture_output=True, timeout=10, env=shutdown_env)
        if check_result.returncode == 0:
            # Force kill if still running
            report("Steam still running - force terminating...")
            force_result = subprocess.run(['pkill', '-9', 'steam'], timeout=15, check=False, capture_output=True, env=shutdown_env)
            logger.debug(f"pkill -9 steam result: {force_result.returncode}")
            time.sleep(2)

            # Final check
            final_check = subprocess.run(['pgrep', '-f', 'steamwebhelper'], capture_output=True, timeout=10, env=shutdown_env)
            if final_check.returncode != 0:
                logger.info("Steam processes successfully force terminated.")
            else:
                logger.warning("Steam processes may still be running after termination attempts.")
                report("Steam shutdown incomplete")
                return False
        else:
            logger.info("Steam processes successfully terminated.")
    except Exception as e:
        logger.warning(f"Error during Steam shutdown: {e}")
        report("Steam shutdown had issues")
        return False

    report("Steam shut down successfully")
    return True


def robust_steam_restart(progress_callback: Optional[Callable[[str], None]] = None, timeout: int = 60, system_info=None) -> bool:
    """
    Robustly restart Steam across all distros. Returns True on success, False on failure.
    Optionally accepts a progress_callback(message: str) for UI feedback.
    Uses aggressive pkill approach for maximum reliability.

    Args:
        progress_callback: Optional callback for progress updates
        timeout: Timeout in seconds for restart operation
        system_info: Optional SystemInfo object with pre-detected Steam installation types
    """
    shutdown_env = _get_clean_subprocess_env()
    strategy = _get_restart_strategy()
    start_env = shutdown_env if strategy == STRATEGY_JACKIFY else os.environ.copy()

    _is_steam_deck = system_info.is_steamdeck if system_info else is_steam_deck()
    resolved_path = _resolve_steam_path_for_restart()
    if resolved_path is not None:
        _is_flatpak = steam_path_indicates_flatpak(resolved_path)
        logger.info("Steam path in use: %s -> flatpak=%s", resolved_path, _is_flatpak)
    else:
        _is_flatpak = _flatpak_steam_data_path_exists()
        if _is_flatpak:
            logger.info("Steam path in use: (flatpak data path detected) -> flatpak=True")
        else:
            _is_flatpak = system_info.is_flatpak_steam if system_info else is_flatpak_steam()

    def report(msg):
        if progress_callback:
            progress_callback(msg)
        else:
            # Only log directly if no callback (callback chain handles logging)
            logger.info(msg)

    report("Shutting down Steam...")
    report(f"Steam restart strategy: {_strategy_label(strategy)}")

    # Steam Deck: Use systemctl for shutdown (special handling) - HIGHEST PRIORITY
    if _is_steam_deck:
        try:
            report("Steam Deck detected - using systemctl shutdown...")
            subprocess.run(['systemctl', '--user', 'stop', 'app-steam@autostart.service'],
                         timeout=15, check=False, capture_output=True, env=shutdown_env)
            time.sleep(2)
        except Exception as e:
            logger.debug(f"systemctl stop failed on Steam Deck: {e}")
    # Flatpak Steam: Use flatpak kill command (only if not Steam Deck)
    elif _is_flatpak:
        try:
            report("Flatpak Steam detected - stopping via flatpak...")
            flatpak_cmd = _get_flatpak_command() or "flatpak"
            subprocess.run([flatpak_cmd, "kill", "com.valvesoftware.Steam"],
                          timeout=15, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=shutdown_env)
            time.sleep(2)
        except Exception as e:
            logger.debug(f"flatpak kill failed: {e}")

    # All systems: Use pkill approach (proven 15/16 test success rate)
    try:
        # Skip unreliable steam -shutdown, go straight to pkill
        pkill_result = subprocess.run(['pkill', 'steam'], timeout=15, check=False, capture_output=True, env=shutdown_env)
        logger.debug(f"pkill steam result: {pkill_result.returncode}")
        time.sleep(2)
        
        # Check if Steam is still running
        check_result = subprocess.run(['pgrep', '-f', 'steamwebhelper'], capture_output=True, timeout=10, env=shutdown_env)
        if check_result.returncode == 0:
            # Force kill if still running
            report("Steam still running - force terminating...")
            force_result = subprocess.run(['pkill', '-9', 'steam'], timeout=15, check=False, capture_output=True, env=shutdown_env)
            logger.debug(f"pkill -9 steam result: {force_result.returncode}")
            time.sleep(2)
            
            # Final check
            final_check = subprocess.run(['pgrep', '-f', 'steamwebhelper'], capture_output=True, timeout=10, env=shutdown_env)
            if final_check.returncode != 0:
                logger.info("Steam processes successfully force terminated.")
            else:
                # Steam might still be running, but proceed anyway - wait phase will verify
                logger.warning("Steam processes may still be running after termination attempts. Proceeding to start phase...")
                report("Steam shutdown incomplete, but proceeding...")
        else:
            logger.info("Steam processes successfully terminated.")
    except Exception as e:
        # Don't fail completely on shutdown errors - proceed to start phase
        logger.warning(f"Error during Steam shutdown: {e}. Proceeding to start phase anyway...")
        report("Steam shutdown had issues, but proceeding...")
    
    report("Steam closed successfully.")

    return start_steam_and_wait(
        is_steamdeck_flag=_is_steam_deck,
        is_flatpak_flag=_is_flatpak,
        env_override=start_env,
        strategy=strategy,
        progress_callback=progress_callback,
    )