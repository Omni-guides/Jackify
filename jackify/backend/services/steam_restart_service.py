import os
import time
import subprocess
import signal
import psutil
import logging
import sys
from typing import Callable, Optional

logger = logging.getLogger(__name__)

def _get_clean_subprocess_env():
    """
    Create a clean environment for subprocess calls by removing PyInstaller-specific
    environment variables that can interfere with Steam execution.
    
    Returns:
        dict: Cleaned environment dictionary
    """
    env = os.environ.copy()
    pyinstaller_vars_removed = []
    
    # Remove PyInstaller-specific environment variables
    if env.pop('_MEIPASS', None):
        pyinstaller_vars_removed.append('_MEIPASS')
    if env.pop('_MEIPASS2', None):
        pyinstaller_vars_removed.append('_MEIPASS2')
    
    # Clean library path variables that PyInstaller modifies (Linux/Unix)
    if 'LD_LIBRARY_PATH_ORIG' in env:
        # Restore original LD_LIBRARY_PATH if it was backed up by PyInstaller
        env['LD_LIBRARY_PATH'] = env['LD_LIBRARY_PATH_ORIG']
        pyinstaller_vars_removed.append('LD_LIBRARY_PATH (restored from _ORIG)')
    else:
        # Remove PyInstaller-modified LD_LIBRARY_PATH
        if env.pop('LD_LIBRARY_PATH', None):
            pyinstaller_vars_removed.append('LD_LIBRARY_PATH (removed)')
    
    # Clean PATH of PyInstaller-specific entries
    if 'PATH' in env and hasattr(sys, '_MEIPASS'):
        path_entries = env['PATH'].split(os.pathsep)
        original_count = len(path_entries)
        # Remove any PATH entries that point to PyInstaller temp directory
        cleaned_path = [p for p in path_entries if not p.startswith(sys._MEIPASS)]
        env['PATH'] = os.pathsep.join(cleaned_path)
        if len(cleaned_path) < original_count:
            pyinstaller_vars_removed.append(f'PATH (removed {original_count - len(cleaned_path)} PyInstaller entries)')
    
    # Clean macOS library path (if present)
    if 'DYLD_LIBRARY_PATH' in env and hasattr(sys, '_MEIPASS'):
        dyld_entries = env['DYLD_LIBRARY_PATH'].split(os.pathsep)
        cleaned_dyld = [p for p in dyld_entries if not p.startswith(sys._MEIPASS)]
        if cleaned_dyld:
            env['DYLD_LIBRARY_PATH'] = os.pathsep.join(cleaned_dyld)
            pyinstaller_vars_removed.append('DYLD_LIBRARY_PATH (cleaned)')
        else:
            env.pop('DYLD_LIBRARY_PATH', None)
            pyinstaller_vars_removed.append('DYLD_LIBRARY_PATH (removed)')
    
    # Log what was cleaned for debugging
    if pyinstaller_vars_removed:
        logger.debug(f"Steam restart: Cleaned PyInstaller environment variables: {', '.join(pyinstaller_vars_removed)}")
    else:
        logger.debug("Steam restart: No PyInstaller environment variables detected (likely DEV mode)")
    
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

def start_steam() -> bool:
    """Attempt to start Steam using the exact methods from existing working logic."""
    env = _get_clean_subprocess_env()
    try:
        # Try systemd user service (Steam Deck)
        if is_steam_deck():
            subprocess.Popen(["systemctl", "--user", "restart", "app-steam@autostart.service"], env=env)
            return True
        
        # Use startup methods with only -silent flag (no -minimized or -no-browser)
        start_methods = [
            {"name": "Popen", "cmd": ["steam", "-silent"], "kwargs": {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "stdin": subprocess.DEVNULL, "start_new_session": True, "env": env}},
            {"name": "setsid", "cmd": ["setsid", "steam", "-silent"], "kwargs": {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "stdin": subprocess.DEVNULL, "env": env}},
            {"name": "nohup", "cmd": ["nohup", "steam", "-silent"], "kwargs": {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "stdin": subprocess.DEVNULL, "start_new_session": True, "preexec_fn": os.setpgrp, "env": env}}
        ]
        
        for method in start_methods:
            method_name = method["name"]
            logger.info(f"Attempting to start Steam using method: {method_name}")
            try:
                process = subprocess.Popen(method["cmd"], **method["kwargs"])
                if process is not None:
                    logger.info(f"Initiated Steam start with {method_name}.")
                    time.sleep(5)  # Wait 5 seconds as in existing logic
                    check_result = subprocess.run(['pgrep', '-f', 'steam'], capture_output=True, timeout=10, env=env)
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

def robust_steam_restart(progress_callback: Optional[Callable[[str], None]] = None, timeout: int = 60) -> bool:
    """
    Robustly restart Steam across all distros. Returns True on success, False on failure.
    Optionally accepts a progress_callback(message: str) for UI feedback.
    Uses aggressive pkill approach for maximum reliability.
    """
    env = _get_clean_subprocess_env()
    
    def report(msg):
        logger.info(msg)
        if progress_callback:
            progress_callback(msg)

    report("Shutting down Steam...")
    
    # Steam Deck: Use systemctl for shutdown (special handling)
    if is_steam_deck():
        try:
            report("Steam Deck detected - using systemctl shutdown...")
            subprocess.run(['systemctl', '--user', 'stop', 'app-steam@autostart.service'], 
                         timeout=15, check=False, capture_output=True, env=env)
            time.sleep(2)
        except Exception as e:
            logger.debug(f"systemctl stop failed on Steam Deck: {e}")
    
    # All systems: Use pkill approach (proven 15/16 test success rate)
    try:
        # Skip unreliable steam -shutdown, go straight to pkill
        pkill_result = subprocess.run(['pkill', 'steam'], timeout=15, check=False, capture_output=True, env=env)
        logger.debug(f"pkill steam result: {pkill_result.returncode}")
        time.sleep(2)
        
        # Check if Steam is still running
        check_result = subprocess.run(['pgrep', '-f', 'steamwebhelper'], capture_output=True, timeout=10, env=env)
        if check_result.returncode == 0:
            # Force kill if still running
            report("Steam still running - force terminating...")
            force_result = subprocess.run(['pkill', '-9', 'steam'], timeout=15, check=False, capture_output=True, env=env)
            logger.debug(f"pkill -9 steam result: {force_result.returncode}")
            time.sleep(2)
            
            # Final check
            final_check = subprocess.run(['pgrep', '-f', 'steamwebhelper'], capture_output=True, timeout=10, env=env)
            if final_check.returncode != 0:
                logger.info("Steam processes successfully force terminated.")
            else:
                report("Failed to terminate Steam processes.")
                return False
        else:
            logger.info("Steam processes successfully terminated.")
    except Exception as e:
        logger.error(f"Error during Steam shutdown: {e}")
        report("Failed to shut down Steam.")
        return False
    
    report("Steam closed successfully.")

    # Start Steam using platform-specific logic
    report("Starting Steam...")
    
    # Steam Deck: Use systemctl restart (keep existing working approach)
    if is_steam_deck():
        try:
            subprocess.Popen(["systemctl", "--user", "restart", "app-steam@autostart.service"], env=env)
            logger.info("Steam Deck: Initiated systemctl restart")
        except Exception as e:
            logger.error(f"Steam Deck systemctl restart failed: {e}")
            report("Failed to restart Steam on Steam Deck.")
            return False
    else:
        # All other distros: Use proven steam -silent method
        if not start_steam():
            report("Failed to start Steam.")
            return False

    # Wait for Steam to fully initialize using existing logic
    report("Waiting for Steam to fully start")
    logger.info("Waiting up to 2 minutes for Steam to fully initialize...")
    max_startup_wait = 120
    elapsed_wait = 0
    initial_wait_done = False
    
    while elapsed_wait < max_startup_wait:
        try:
            result = subprocess.run(['pgrep', '-f', 'steam'], capture_output=True, timeout=10, env=env)
            if result.returncode == 0:
                if not initial_wait_done:
                    logger.info("Steam process detected. Waiting additional time for full initialization...")
                    initial_wait_done = True
                time.sleep(5)
                elapsed_wait += 5
                if initial_wait_done and elapsed_wait >= 15:
                    final_check = subprocess.run(['pgrep', '-f', 'steam'], capture_output=True, timeout=10, env=env)
                    if final_check.returncode == 0:
                        report("Steam started successfully.")
                        logger.info("Steam confirmed running after wait.")
                        return True
                    else:
                        logger.warning("Steam process disappeared during final initialization wait.")
                        break
            else:
                logger.debug(f"Steam process not yet detected. Waiting... ({elapsed_wait + 5}s)")
                time.sleep(5)
                elapsed_wait += 5
        except Exception as e:
            logger.warning(f"Error during Steam startup wait: {e}")
            time.sleep(5)
            elapsed_wait += 5
    
    report("Steam did not start within timeout.")
    logger.error("Steam failed to start/initialize within the allowed time.")
    return False 