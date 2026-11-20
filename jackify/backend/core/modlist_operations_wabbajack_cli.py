"""CLI install path for the Wabbajack Linux CLI engine (ModlistInstallCLI mixin)."""
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from jackify.backend.handlers.progress_parser_wabbajack_cli import WabbajackCliProgressStateManager
from jackify.backend.handlers.wabbajack_cli_login import (
    AUTO_RERUN_LIMIT,
    LOGIN_LOST_ERROR,
    WabbajackCliLogin,
    only_login_refusals,
)
from jackify.backend.handlers.wabbajack_cli_manual_downloads import (
    build_manual_events,
    find_wabbajack_file,
    load_archives,
)
from jackify.backend.handlers.wabbajack_cli_output import ANSI_RE, DEBUG_LINE_RE, QUIET_LINE_RE
from jackify.shared.colors import COLOR_ERROR, COLOR_INFO, COLOR_RESET, COLOR_WARNING
from jackify.shared.paths import get_jackify_data_dir

logger = logging.getLogger(__name__)


class ModlistOperationsWabbajackCliMixin:
    """Runs wabbajack-cli for a CLI install, including login upkeep and manual downloads."""

    def _run_wabbajack_cli_install(self, cmd: List[str], engine_path: str, modlist_value: str,
                                   download_dir: Path, auth_service, oauth_info: Optional[str],
                                   api_key: Optional[str]) -> bool:
        """Install with wabbajack-cli. Returns True when the install completed."""
        login = WabbajackCliLogin(
            get_jackify_data_dir() / "wabbajack-cli-data", auth_service, oauth_info, api_key,
            notify=lambda msg: print(f"{COLOR_WARNING}{msg}{COLOR_RESET}"),
        )
        login.engine_path = engine_path
        env_vars = login.build_env()
        iteration = 1
        auto_reruns = 0
        try:
            while True:
                parser = WabbajackCliProgressStateManager()
                returncode = self._wjcli_cli_run_once(cmd, env_vars, engine_path, login, parser)
                if returncode != 3 or not parser.manual.items:
                    break
                items = parser.manual.items
                if auto_reruns < AUTO_RERUN_LIMIT and only_login_refusals(i.reason for i in items):
                    auto_reruns += 1
                    logger.info("All manual downloads were refused for lack of a login, retrying")
                    login.sync_once(env_vars, force=True)
                    if login.lost:
                        auto_reruns = AUTO_RERUN_LIMIT
                    else:
                        continue
                if not self._wjcli_cli_manual_phase(items, modlist_value, download_dir, iteration):
                    return False
                iteration += 1
        finally:
            login.clear_stored()
        if returncode != 0:
            summary = LOGIN_LOST_ERROR if login.lost else parser.get_failure_summary()
            print(f"{COLOR_ERROR}Wabbajack Linux CLI exited with code {returncode}"
                  f"{': ' + summary if summary else '.'}{COLOR_RESET}")
            logger.error("wabbajack-cli exited with code %d: %s", returncode, summary)
            self._record_install_failure("engine_crash")
            return False
        logger.info("wabbajack-cli completed successfully.")
        return True

    def _wjcli_cli_manual_phase(self, items, modlist_value: str, download_dir: Path,
                                iteration: int) -> bool:
        from jackify.backend.handlers.config_handler import ConfigHandler
        from jackify.frontends.cli.commands.manual_download_flow import run_cli_manual_download_phase
        archives = load_archives(find_wabbajack_file(modlist_value, str(download_dir)))
        try:
            limit = int(ConfigHandler().get('manual_download_concurrent_limit', 2))
        except (TypeError, ValueError):
            limit = 2
        return run_cli_manual_download_phase(
            events=build_manual_events(items, archives, iteration),
            loop_iteration=iteration,
            download_dir=download_dir,
            stdin_write=lambda _payload: True,
            concurrent_limit=max(1, min(5, limit)),
        )

    def _wjcli_cli_run_once(self, cmd: List[str], env_vars: dict, engine_path: str,
                            login: WabbajackCliLogin, parser: WabbajackCliProgressStateManager) -> int:
        from jackify.backend.handlers.subprocess_utils import (
            get_clean_subprocess_env,
            register_process_group,
            unregister_process_group,
        )
        self._current_process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=False,
            env=get_clean_subprocess_env(env_vars), cwd=os.path.dirname(engine_path),
            start_new_session=True,
        )
        proc = self._current_process
        pgid = os.getpgid(proc.pid)
        register_process_group(pgid)
        try:
            with login.keep_fresh(lambda force: login.sync_once(env_vars, force)):
                self._wjcli_cli_stream(proc, parser, login)
            proc.wait()
        finally:
            unregister_process_group(pgid)
            self._current_process = None
        return proc.returncode

    @staticmethod
    def _wjcli_cli_stream(proc, parser: WabbajackCliProgressStateManager,
                          login: WabbajackCliLogin) -> None:
        inline_active = False
        last_phase = ''
        for raw in proc.stdout:
            line = ANSI_RE.sub(b'', raw).decode('utf-8', errors='replace').rstrip('\r\n')
            if not line.strip():
                continue
            login.watch_line(line)
            if parser.process_line(line):
                state = parser.get_state()
                if state.phase_name != last_phase:
                    if inline_active:
                        print()
                        inline_active = False
                    last_phase = state.phase_name or ''
                    print(f"\n=== {last_phase} ===")
                if state.message:
                    print(f"\r{state.message}\033[K", end='', flush=True)
                    inline_active = True
            stripped = line.strip()
            if DEBUG_LINE_RE.match(stripped) or QUIET_LINE_RE.match(stripped):
                continue
            if inline_active:
                print()
                inline_active = False
            print(line)
        if inline_active:
            print()
        sys.stdout.flush()
