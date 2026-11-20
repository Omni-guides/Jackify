"""
Nexus login handling for wabbajack-cli, shared by the GUI and CLI installers.

The CLI cannot refresh a Jackify-issued token (Nexus ties it to Jackify's client), so Jackify
loads its login into the CLI's own encrypted storage, keeps it fresh while an install runs, and
re-pushes it as soon as the CLI reports an expired login.
"""
import logging
import os
import re
import subprocess
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterable, Optional

from jackify.backend.services.engine_invoker import (
    build_wabbajack_cli_env_vars,
    write_wabbajack_cli_resource_settings,
)

logger = logging.getLogger(__name__)

# The CLI logs these when it finds the stored token expired and its own refresh is refused
LOGIN_TROUBLE_RE = re.compile(
    r'Refreshing OAuth Token|Nexus OAuth Token refresh failed|Keeping the stored Nexus login'
)
# Reasons the CLI gives for files it could not fetch because it had no usable login
LOGIN_REFUSAL_RE = re.compile(r'unauthorized|no api key or oauth token', re.IGNORECASE)
AUTO_RERUN_LIMIT = 2
LOGIN_LOST_MESSAGE = (
    "[Jackify] Jackify could not refresh your Nexus Mods login. Downloads will be refused "
    "until you log in to Nexus Mods again in Jackify."
)
LOGIN_LOST_ERROR = (
    "Jackify could not refresh your Nexus Mods login, so downloads were refused. "
    "Log in to Nexus Mods again in Jackify and retry."
)


def only_login_refusals(reasons: Iterable[str]) -> bool:
    """True when every manual-download reason is the CLI lacking a usable login."""
    reasons = list(reasons)
    return bool(reasons) and all(LOGIN_REFUSAL_RE.search(r) for r in reasons)


class WabbajackCliLogin:
    """Keeps wabbajack-cli supplied with a working Nexus login for one install."""

    def __init__(self, data_home: Path, auth_service=None, oauth_info: Optional[str] = None,
                 api_key: Optional[str] = None, notify: Optional[Callable[[str], None]] = None):
        self.data_home = Path(data_home)
        self.auth_service = auth_service
        self.oauth_info = oauth_info
        self.api_key = api_key
        self.notify = notify
        self.engine_path = ""
        self.stored_login: Optional[str] = None
        self.lost = False
        self.wake = threading.Event()

    def clear_stored(self) -> None:
        """Delete the CLI's own saved login.

        The CLI prefers that file over NEXUS_OAUTH_INFO, so a leftover would silently
        replace Jackify's token on the next run and leave a token on disk.
        """
        try:
            (self.data_home / "Wabbajack" / "encrypted" / "nexus-oauth-info").unlink(missing_ok=True)
        except OSError as e:
            logger.warning("Could not remove stored wabbajack-cli login: %s", e)

    def build_env(self) -> dict:
        env_vars = build_wabbajack_cli_env_vars(self.oauth_info, self.api_key)
        env_vars['DOTNET_SYSTEM_GLOBALIZATION_INVARIANT'] = "1"
        self.data_home.mkdir(parents=True, exist_ok=True)
        env_vars['XDG_DATA_HOME'] = str(self.data_home)
        write_wabbajack_cli_resource_settings(self.data_home)
        self.clear_stored()
        login = env_vars.get('NEXUS_OAUTH_INFO')
        if login and self.store(login, env_vars):
            # The stored login takes priority over the variable, and is what Jackify keeps fresh
            del env_vars['NEXUS_OAUTH_INFO']
            self.stored_login = login
        return env_vars

    def store(self, login_json: str, env_vars: dict) -> bool:
        """Load the login into the CLI's storage via its encrypt verb.

        The CLI re-reads that storage on every Nexus request, so overwriting it while an
        install runs hands the CLI a refreshed token without a restart.
        """
        from jackify.backend.handlers.subprocess_utils import get_clean_subprocess_env
        tmp_path = None
        try:
            fd, tmp_path = tempfile.mkstemp(dir=str(self.data_home), suffix=".json")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(login_json)
            result = subprocess.run(
                [self.engine_path, "encrypt", "-i", tmp_path, "-n", "nexus-oauth-info"],
                env=get_clean_subprocess_env(env_vars), capture_output=True, text=True, timeout=60,
            )
            if result.returncode != 0:
                logger.warning("wabbajack-cli encrypt failed (exit %s): %s",
                               result.returncode, (result.stderr or result.stdout).strip()[-300:])
                return False
            return True
        except (OSError, subprocess.SubprocessError) as e:
            logger.warning("Could not store Nexus login for wabbajack-cli: %s", e)
            return False
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    def sync_once(self, env_vars: dict, force: bool = False) -> bool:
        """Refresh Jackify's token if due and push a changed login into the CLI's storage."""
        if not self.auth_service:
            return False
        _, login = self.auth_service.get_auth_for_engine()
        if not login:
            if force:
                self.note_lost()
            return False
        if login == self.stored_login and not force:
            return False
        if not self.store(login, env_vars):
            return False
        self.stored_login = login
        self.lost = False
        logger.info("Pushed refreshed Nexus login to wabbajack-cli")
        return True

    def note_lost(self) -> None:
        """Tell the user once that the CLI's expired login could not be replaced."""
        if self.lost:
            return
        self.lost = True
        logger.warning("Jackify could not refresh the Nexus login for wabbajack-cli")
        if self.notify:
            self.notify(LOGIN_LOST_MESSAGE)

    def watch_line(self, line: str) -> None:
        """Wake the sync at once when the CLI reports login trouble."""
        if LOGIN_TROUBLE_RE.search(line):
            logger.info("wabbajack-cli reports an expired Nexus login, refreshing it now")
            self.wake.set()

    def run_sync(self, stop: threading.Event, sync: Callable[[bool], object]) -> None:
        interval = float(os.environ.get("JACKIFY_WJCLI_SYNC_SECS", "300"))
        force = bool(os.environ.get("JACKIFY_WJCLI_SYNC_FORCE"))
        while True:
            woken = self.wake.wait(interval)
            self.wake.clear()
            if stop.is_set():
                break
            try:
                sync(force or woken)
            except Exception as e:
                logger.warning("wabbajack-cli login sync failed: %s", e)

    @contextmanager
    def keep_fresh(self, sync: Callable[[bool], object]):
        """Run a background refresh for the duration of one CLI run."""
        stop = threading.Event()
        worker = None
        if self.stored_login and self.oauth_info:
            worker = threading.Thread(target=self.run_sync, args=(stop, sync), daemon=True)
            worker.start()
        try:
            yield
        finally:
            stop.set()
            self.wake.set()
            if worker:
                worker.join(timeout=5.0)
