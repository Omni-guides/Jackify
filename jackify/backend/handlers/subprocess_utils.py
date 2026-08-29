import os
import signal
import subprocess
import time
import resource
import sys
import shutil
import logging
import threading

logger = logging.getLogger(__name__)


def suspend_baloo() -> bool:
    """Suspend KDE Baloo file indexer. Safe to call on non-KDE or headless systems."""
    if not shutil.which("balooctl"):
        return False
    try:
        subprocess.run(["balooctl", "suspend"], capture_output=True, timeout=5)
        logger.debug("Baloo file indexer suspended")
        return True
    except Exception:
        return False


def resume_baloo() -> None:
    """Resume KDE Baloo file indexer. No-op if balooctl is not present."""
    if not shutil.which("balooctl"):
        return
    try:
        subprocess.run(["balooctl", "resume"], capture_output=True, timeout=5)
        logger.debug("Baloo file indexer resumed")
    except Exception:
        pass

def get_safe_python_executable():
    """
    Get a safe Python executable for subprocess calls.
    When running as AppImage, returns system Python instead of AppImage path
    to prevent recursive AppImage spawning.
    
    Returns:
        str: Path to Python executable safe for subprocess calls
    """
    # Check if we're running as AppImage
    is_appimage = (
        'APPIMAGE' in os.environ or
        'APPDIR' in os.environ or
        (sys.argv[0] and sys.argv[0].endswith('.AppImage'))
    )
    
    if is_appimage:
        # Running as AppImage - use system Python to avoid recursive spawning
        # Try to find system Python (same logic as AppRun)
        for cmd in ['python3', 'python3.13', 'python3.12', 'python3.11', 'python3.10', 'python3.9', 'python3.8']:
            python_path = shutil.which(cmd)
            if python_path:
                return python_path
        # Fallback: if we can't find system Python, this is a problem
        # But we'll still return sys.executable as last resort
        return sys.executable
    else:
        # Not AppImage - sys.executable is safe
        return sys.executable

def get_clean_subprocess_env(extra_env=None):
    """
    Returns a copy of os.environ with bundled-runtime variables and other problematic entries removed.
    Optionally merges in extra_env dict.
    Also ensures bundled tools (lz4, cabextract, winetricks) are in PATH when running as AppImage.
    CRITICAL: Preserves system PATH to ensure system utilities (wget, curl, unzip, xz, gzip, sha256sum) are available.
    """
    from pathlib import Path
    
    env = os.environ.copy()

    # Save APPDIR before removing it (we need it to find bundled tools)
    appdir = env.get('APPDIR')

    # Remove AppImage-specific variables that can confuse subprocess calls
    # These variables cause subprocesses to be interpreted as new AppImage launches
    for key in ['APPIMAGE', 'APPDIR', 'ARGV0', 'OWD']:
        env.pop(key, None)

    # Remove bundle-specific variables
    for k in list(env):
        if k.startswith('_MEIPASS'):
            del env[k]

    # Get current PATH - ensure we preserve system paths
    current_path = env.get('PATH', '')

    # Ensure common system directories are in PATH if not already present
    # Critical for tools in /usr/bin, /usr/local/bin, etc.
    system_paths = ['/usr/bin', '/usr/local/bin', '/bin', '/sbin', '/usr/sbin']
    path_parts = current_path.split(':') if current_path else []
    for sys_path in system_paths:
        if sys_path not in path_parts and os.path.isdir(sys_path):
            path_parts.append(sys_path)

    # Add bundled tools directory to PATH if running as AppImage
    # cabextract and winetricks must be available to subprocesses
    # System utilities (wget, curl, unzip, xz, gzip, sha256sum) come from system PATH
    # appdir saved before env cleanup above
    # lz4 was only needed for TTW installer, no longer bundled
    tools_dir = None
    
    if appdir:
        # Running as AppImage - use APPDIR
        tools_dir = os.path.join(appdir, 'opt', 'jackify', 'tools')
        logger = logging.getLogger(__name__)
        if not os.path.isdir(tools_dir):
            logger.debug(f"Tools directory not found: {tools_dir}")
            tools_dir = None
        else:
            # Tools directory exists - add it to PATH for cabextract, winetricks, etc.
            logger.debug(f"Found bundled tools directory at: {tools_dir}")
    else:
        logging.getLogger(__name__).debug("APPDIR not set - not running as AppImage, skipping bundled tools")
    
    # Build final PATH: system PATH first, then bundled tools (lz4, cabextract, winetricks)
    # System utilities (wget, curl, unzip, xz, gzip, sha256sum) are preferred from system
    final_path_parts = []
    
    # Add all other paths first (system utilities take precedence)
    seen = set()
    for path_part in path_parts:
        if path_part and path_part not in seen:
            final_path_parts.append(path_part)
            seen.add(path_part)
    
    # Then add bundled tools directory (for cabextract, winetricks, etc.)
    if tools_dir and os.path.isdir(tools_dir) and tools_dir not in seen:
        final_path_parts.append(tools_dir)
        seen.add(tools_dir)
    
    
    env['PATH'] = ':'.join(final_path_parts)
    
    # Optionally restore LD_LIBRARY_PATH to system default if needed
    # (You can add more logic here if you know your system's default)
    if extra_env:
        env.update(extra_env)
    return env

_active_process_groups = set()
_active_process_groups_lock = threading.Lock()


def register_process_group(pgid):
    """Track a process group started outside ProcessManager (e.g. a raw Popen
    call site) so it can be killed by PID instead of pattern-matched later."""
    with _active_process_groups_lock:
        _active_process_groups.add(pgid)


def unregister_process_group(pgid):
    """Stop tracking a process group once its owner has cleaned it up."""
    with _active_process_groups_lock:
        _active_process_groups.discard(pgid)


def kill_all_registered_process_groups(sig=signal.SIGKILL):
    """Kill every currently tracked process group. Used by emergency/shutdown
    cleanup paths that have no reference to the specific process that spawned
    each group, replacing pattern-based pkill calls."""
    with _active_process_groups_lock:
        pgids = list(_active_process_groups)
    for pgid in pgids:
        try:
            os.killpg(pgid, sig)
        except Exception:
            pass
        unregister_process_group(pgid)


def increase_file_descriptor_limit(target_limit=1048576):
    """
    Temporarily increase the file descriptor limit for the current process.
    
    Args:
        target_limit (int): Desired file descriptor limit (default: 1048576)
        
    Returns:
        tuple: (success: bool, old_limit: int, new_limit: int, message: str)
    """
    try:
        # Get current soft and hard limits
        soft_limit, hard_limit = resource.getrlimit(resource.RLIMIT_NOFILE)
        
        # Don't decrease the limit if it's already higher
        if soft_limit >= target_limit:
            return True, soft_limit, soft_limit, f"Current limit ({soft_limit}) already sufficient"
        
        # Set new limit (can't exceed hard limit)
        new_limit = min(target_limit, hard_limit)
        resource.setrlimit(resource.RLIMIT_NOFILE, (new_limit, hard_limit))
        
        return True, soft_limit, new_limit, f"Increased file descriptor limit from {soft_limit} to {new_limit}"
        
    except (OSError, ValueError) as e:
        # Get current limit for reporting
        try:
            soft_limit, _ = resource.getrlimit(resource.RLIMIT_NOFILE)
        except (OSError, ValueError):
            soft_limit = "unknown"
        
        return False, soft_limit, soft_limit, f"Failed to increase file descriptor limit: {e}"

class ProcessManager:
    """
    Shared process manager for robust subprocess launching, tracking, and cancellation.
    """
    def __init__(self, cmd, env=None, cwd=None, text=False, bufsize=0, separate_stderr=False, enable_stdin=False, use_pty=False):
        self.cmd = cmd
        # Default to cleaned environment if None to prevent AppImage variable inheritance
        if env is None:
            self.env = get_clean_subprocess_env()
        else:
            self.env = env
        self.cwd = cwd
        self.text = text
        self.bufsize = bufsize
        self.separate_stderr = separate_stderr
        self.enable_stdin = enable_stdin
        self.use_pty = use_pty
        self._pty_master_fd = None
        self.proc = None
        self.process_group_pid = None
        self._stdin_lock = threading.Lock()
        self._start_process()

    def _start_process(self):
        stderr_arg = subprocess.PIPE if self.separate_stderr else subprocess.STDOUT
        stdin_arg = subprocess.PIPE if self.enable_stdin else None
        if self.use_pty:
            import pty
            master_fd, slave_fd = pty.openpty()
            self._pty_master_fd = master_fd
            # TERM=dumb + NO_COLOR prevent CLF3 from using cursor movement or ANSI
            # sequences (which would cause in-place overwrites we can't capture).
            # isatty() still returns True on the slave, so Rust line-buffers stdout.
            pty_env = dict(self.env) if self.env else {}
            pty_env['TERM'] = 'dumb'
            pty_env['NO_COLOR'] = '1'
            self.proc = subprocess.Popen(
                self.cmd,
                stdin=stdin_arg,
                stdout=slave_fd,
                stderr=stderr_arg,
                env=pty_env,
                cwd=self.cwd,
                start_new_session=True,
                pass_fds=(slave_fd,),
            )
            os.close(slave_fd)
        else:
            self.proc = subprocess.Popen(
                self.cmd,
                stdin=stdin_arg,
                stdout=subprocess.PIPE,
                stderr=stderr_arg,
                env=self.env,
                cwd=self.cwd,
                text=self.text,
                bufsize=self.bufsize,
                start_new_session=True,
            )
        self.process_group_pid = os.getpgid(self.proc.pid)

    def cancel(self, timeout_terminate=2, timeout_kill=1):
        """
        Attempt to robustly terminate the process and its children.
        """
        try:
            if self.proc:
                # Terminate process group first so child tools don't survive parent exit.
                if self.process_group_pid:
                    try:
                        os.killpg(self.process_group_pid, signal.SIGTERM)
                    except Exception:
                        pass

                try:
                    self.proc.terminate()
                except Exception:
                    pass

                try:
                    self.proc.wait(timeout=timeout_terminate)
                except subprocess.TimeoutExpired:
                    pass
                except Exception:
                    pass

                # Escalate to SIGKILL for stubborn children/process group.
                if self.process_group_pid:
                    try:
                        os.killpg(self.process_group_pid, signal.SIGKILL)
                    except Exception:
                        pass

                try:
                    self.proc.kill()
                except Exception:
                    pass

                try:
                    self.proc.wait(timeout=timeout_kill)
                except subprocess.TimeoutExpired:
                    pass
                except Exception:
                    pass
        finally:
            # Always close pipes - unblocks threads blocked on read(1) or iterating stderr
            if self._pty_master_fd is not None:
                try:
                    os.close(self._pty_master_fd)
                except Exception:
                    pass
                self._pty_master_fd = None
            if self.proc:
                for pipe in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
                    if pipe:
                        try:
                            pipe.close()
                        except Exception:
                            pass

    def is_running(self):
        return self.proc and self.proc.poll() is None

    def wait(self, timeout=None):
        if self.proc:
            return self.proc.wait(timeout=timeout)
        return None

    def read_stdout_line(self):
        if self.proc and self.proc.stdout:
            return self.proc.stdout.readline()
        return None

    def read_stdout_char(self):
        if self._pty_master_fd is not None:
            try:
                return os.read(self._pty_master_fd, 1)
            except (OSError, IOError):
                return None
        if self.proc and self.proc.stdout:
            try:
                return self.proc.stdout.read(1)
            except (ValueError, OSError):
                return None
        return None

    def write_stdin(self, line: str) -> bool:
        """
        Write a line to the process stdin. Thread-safe.
        Returns True on success, False if stdin is not available or process is gone.
        """
        if not self.enable_stdin or not self.proc or not self.proc.stdin:
            return False
        with self._stdin_lock:
            try:
                payload = line if line.endswith('\n') else line + '\n'
                self.proc.stdin.write(payload.encode())
                self.proc.stdin.flush()
                return True
            except (OSError, BrokenPipeError):
                return False
