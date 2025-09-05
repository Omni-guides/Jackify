import os
import signal
import subprocess
import time
import resource

def get_clean_subprocess_env(extra_env=None):
    """
    Returns a copy of os.environ with PyInstaller and other problematic variables removed.
    Optionally merges in extra_env dict.
    """
    env = os.environ.copy()
    # Remove PyInstaller-specific variables
    for k in list(env):
        if k.startswith('_MEIPASS'):
            del env[k]
    # Optionally restore LD_LIBRARY_PATH to system default if needed
    # (You can add more logic here if you know your system's default)
    if extra_env:
        env.update(extra_env)
    return env

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
        except:
            soft_limit = "unknown"
        
        return False, soft_limit, soft_limit, f"Failed to increase file descriptor limit: {e}"

class ProcessManager:
    """
    Shared process manager for robust subprocess launching, tracking, and cancellation.
    """
    def __init__(self, cmd, env=None, cwd=None, text=False, bufsize=0):
        self.cmd = cmd
        self.env = env
        self.cwd = cwd
        self.text = text
        self.bufsize = bufsize
        self.proc = None
        self.process_group_pid = None
        self._start_process()

    def _start_process(self):
        self.proc = subprocess.Popen(
            self.cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=self.env,
            cwd=self.cwd,
            text=self.text,
            bufsize=self.bufsize,
            start_new_session=True
        )
        self.process_group_pid = os.getpgid(self.proc.pid)

    def cancel(self, timeout_terminate=2, timeout_kill=1, max_cleanup_attempts=3):
        """
        Attempt to robustly terminate the process and its children.
        """
        cleanup_attempts = 0
        if self.proc:
            try:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=timeout_terminate)
                    return
                except subprocess.TimeoutExpired:
                    pass
            except Exception:
                pass
            try:
                self.proc.kill()
                try:
                    self.proc.wait(timeout=timeout_kill)
                    return
                except subprocess.TimeoutExpired:
                    pass
            except Exception:
                pass
            # Kill process group if possible
            if self.process_group_pid:
                try:
                    os.killpg(self.process_group_pid, signal.SIGKILL)
                except Exception:
                    pass
            # Last resort: pkill by command name
            while cleanup_attempts < max_cleanup_attempts:
                try:
                    subprocess.run(['pkill', '-f', os.path.basename(self.cmd[0])], timeout=5, capture_output=True)
                except Exception:
                    pass
                cleanup_attempts += 1

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
        if self.proc and self.proc.stdout:
            return self.proc.stdout.read(1)
        return None 