"""
Wabbajack Linux CLI support for InstallerThread: environment, progress parsing and the stdout loop.
"""

import logging
import os
import threading
from pathlib import Path
from typing import Optional

from jackify.backend.handlers.wabbajack_cli_manual_downloads import (
    build_manual_events,
    find_wabbajack_file,
    load_archives,
)
from jackify.backend.handlers.wabbajack_cli_login import (
    AUTO_RERUN_LIMIT,
    LOGIN_LOST_ERROR,
    WabbajackCliLogin,
    only_login_refusals,
)
from jackify.backend.handlers.wabbajack_cli_ticker import ProgressTicker
from jackify.backend.handlers.wabbajack_cli_output import ANSI_RE, DEBUG_LINE_RE, QUIET_LINE_RE
from jackify.shared.errors import JackifyError
from jackify.shared.paths import get_jackify_data_dir

logger = logging.getLogger(__name__)


class WabbajackCliInstallerMixin:
    """Wabbajack Linux CLI behaviour for InstallerThread."""

    _wjcli_parser = None
    _wjcli_continue: Optional[threading.Event] = None
    _wjcli_waiting = False
    _wjcli_login_state: Optional[WabbajackCliLogin] = None

    @staticmethod
    def _wjcli_data_home() -> Path:
        """XDG_DATA_HOME for the CLI: keeps its caches out of any Wabbajack install the user has."""
        return get_jackify_data_dir() / "wabbajack-cli-data"

    def _wjcli_login(self, engine_path: str = "") -> WabbajackCliLogin:
        if self._wjcli_login_state is None:
            self._wjcli_login_state = WabbajackCliLogin(
                self._wjcli_data_home(), notify=lambda msg: self.output_received.emit(msg + "\n"),
            )
        state = self._wjcli_login_state
        state.auth_service = getattr(self, 'auth_service', None)
        state.oauth_info = getattr(self, 'oauth_info', None)
        state.api_key = getattr(self, 'api_key', None)
        if engine_path:
            state.engine_path = engine_path
        return state

    @property
    def _wjcli_stored_login(self) -> Optional[str]:
        return self._wjcli_login().stored_login

    @property
    def _wjcli_login_lost(self) -> bool:
        return self._wjcli_login().lost

    @property
    def _wjcli_wake(self) -> threading.Event:
        return self._wjcli_login().wake

    def _wjcli_env_vars(self, engine_path: str) -> dict:
        return self._wjcli_login(engine_path).build_env()

    @classmethod
    def _wjcli_clear_stored_login(cls) -> None:
        WabbajackCliLogin(cls._wjcli_data_home()).clear_stored()

    def _wjcli_store_login(self, engine_path: str, login_json: str, env_vars: dict) -> bool:
        return self._wjcli_login(engine_path).store(login_json, env_vars)

    def _wjcli_sync_login_once(self, engine_path: str, env_vars: dict, force: bool = False) -> bool:
        return self._wjcli_login(engine_path).sync_once(env_vars, force)

    def _wjcli_run_login_sync(self, engine_path: str, env_vars: dict, stop: threading.Event) -> None:
        self._wjcli_login(engine_path).run_sync(
            stop, lambda force: self._wjcli_sync_login_once(engine_path, env_vars, force))

    def _wjcli_run_output(self, engine_path: str, env_vars: dict) -> None:
        """Run the stdout loop while a background thread keeps the CLI's Nexus login fresh."""
        login = self._wjcli_login(engine_path)
        with login.keep_fresh(lambda force: self._wjcli_sync_login_once(engine_path, env_vars, force)):
            self._wjcli_run_stdout_loop()

    def _wjcli_start_session(self) -> None:
        from jackify.backend.handlers.progress_parser_wabbajack_cli import (
            WabbajackCliProgressStateManager,
        )
        self._wjcli_parser = WabbajackCliProgressStateManager()
        self._wjcli_login().wake.clear()

    def _wjcli_run_stdout_loop(self) -> None:
        """Forward CLI output to Show Details and parsed progress to the Activity panel.

        Nothing is emitted once the user has cancelled: the CLI prints an error per
        interrupted download afterwards, which is not a failure.
        """
        parser = self._wjcli_parser
        ticker = ProgressTicker(parser, str(self.downloads_dir), self.progress_updated.emit)
        ticker.start()
        try:
            self._wjcli_forward_stdout(parser)
        finally:
            ticker.stop()

    def _wjcli_forward_stdout(self, parser) -> None:
        for raw in self.process_manager.proc.stdout:
            if self.cancelled:
                self.cancel()
                break
            decoded = ANSI_RE.sub(b'', raw).decode('utf-8', errors='replace').rstrip('\r\n')
            if not decoded.strip():
                continue
            self._remember_stdout_line(decoded)
            self._wjcli_login().watch_line(decoded)
            if parser.process_line(decoded):
                self.progress_updated.emit(parser.get_state())
            stripped = decoded.strip()
            if DEBUG_LINE_RE.match(stripped) or QUIET_LINE_RE.match(stripped):
                continue
            self.output_received.emit(decoded + '\n')

    def _wjcli_failure_error(self, returncode: int) -> Optional[JackifyError]:
        summary = self._wjcli_parser.get_failure_summary() if self._wjcli_parser else None
        if self._wjcli_login_lost:
            summary = LOGIN_LOST_ERROR
        if not summary:
            return None
        return JackifyError(
            "Installation failed",
            summary,
            technical=f"wabbajack-cli exit code {returncode}",
        )

    def _wjcli_release_wait(self) -> None:
        """Unblock a pending wait for the manual download dialog (continue or cancel)."""
        if self._wjcli_continue is not None:
            self._wjcli_continue.set()

    def _wjcli_handle_manual_downloads(self, returncode: int, cmd: list, env_vars: dict,
                                       engine_path: str) -> int:
        """While the CLI stops for files the user must fetch, show them and re-run on continue.

        The CLI has no continue command: it exits with code 3 and the listing. Once the dialog
        reports the files are in the downloads folder, running it again picks them up.
        """
        iteration = 1
        auto_reruns = 0
        while returncode == 3 and self._wjcli_parser.manual.items and not self.cancelled:
            items = self._wjcli_parser.manual.items
            if auto_reruns < AUTO_RERUN_LIMIT and only_login_refusals(i.reason for i in items):
                # Every file failed for the login alone: refresh it and retry without asking the user
                auto_reruns += 1
                logger.info("All manual downloads were refused for lack of a login, retrying with a fresh login")
                try:
                    self._wjcli_sync_login_once(engine_path, env_vars, force=True)
                except Exception as e:
                    logger.warning("wabbajack-cli login refresh before retry failed: %s", e)
                if self._wjcli_login_lost:
                    auto_reruns = AUTO_RERUN_LIMIT
                    continue
                returncode = self._wjcli_rerun(cmd, env_vars, engine_path)
                continue
            archives = load_archives(find_wabbajack_file(self.modlist, self.downloads_dir))
            if iteration == 1 and any('premium' in i.reason.lower() for i in items):
                self.non_premium_detected.emit()
            self._wjcli_continue = threading.Event()
            self._wjcli_waiting = True
            self.manual_download_list_received.emit(build_manual_events(items, archives, iteration))
            self._wjcli_continue.wait()
            self._wjcli_waiting = False
            if self.cancelled:
                break
            iteration += 1
            returncode = self._wjcli_rerun(cmd, env_vars, engine_path)
        return returncode

    def _wjcli_rerun(self, cmd: list, env_vars: dict, engine_path: str) -> int:
        from jackify.backend.handlers.subprocess_utils import ProcessManager, get_clean_subprocess_env
        self._wjcli_start_session()
        self.process_manager = ProcessManager(
            cmd, env=get_clean_subprocess_env(env_vars), text=False, separate_stderr=True, enable_stdin=True
        )
        stderr_thread = threading.Thread(target=self._read_stderr, daemon=True)
        stderr_thread.start()
        self._wjcli_run_output(engine_path, env_vars)
        stderr_thread.join(timeout=5)
        return self.process_manager.wait()
