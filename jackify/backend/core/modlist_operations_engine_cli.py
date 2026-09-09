"""CLI engine-invocation methods for ModlistInstallCLI (Mixin).

Runs the active install engine (jackify-engine or CLF3) as a subprocess and streams
its output, handling manual-download pauses and CLF3's structured progress protocol.
"""
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple

from jackify.shared.colors import (
    COLOR_RESET,
    COLOR_INFO,
    COLOR_ERROR,
    COLOR_WARNING,
)

logger = logging.getLogger(__name__)


class ModlistOperationsEngineCLIMixin:
    """Mixin providing CLI install-engine invocation methods."""

    def _record_install_failure(self, failure_reason: str) -> None:
        """JackifyDB failure record - isolated try/except since a data-collection call must
        never affect the (already failing) install flow."""
        try:
            from jackify import __version__ as _jackify_version
            from jackify.backend.services.jackify_db import gather_environment_fields, record_event
            record_event(
                "install_completed", "failure",
                modlist_name=self.context.get('modlist_name', ''),
                game_type=(
                    self.context.get('detected_game')
                    or self.context.get('game_type')
                    or self.context.get('special_game_type')
                ),
                install_mode=self.context.get('install_mode', 'online'),
                jackify_version=_jackify_version, failure_phase="install",
                failure_reason=failure_reason,
                **gather_environment_fields(),
            )
        except Exception as e:
            self.logger.debug("JackifyDB failure record skipped: %s", e)

    def _clf3_fetch_wabbajack(self, engine_path: str, machine_name: str, engine_dir: str) -> "str | None":
        """
        Resolve a gallery machine name to a local .wabbajack file for CLF3.

        Looks up the CDN download URL from the metadata cache, then runs
        `clf3 fetch` to download the file.  Returns the local path on success,
        or None (with an error printed) on failure.
        """
        from jackify.shared.paths import get_jackify_downloads_dir
        from jackify.backend.services.modlist_download_url import get_modlist_download_url

        list_id = machine_name.split('/')[-1] if '/' in machine_name else machine_name
        local_path = str(get_jackify_downloads_dir() / f"{list_id}.wabbajack")

        if os.path.isfile(local_path):
            self.logger.info("CLF3: using cached wabbajack file at %s", local_path)
            return local_path

        download_url = get_modlist_download_url(machine_name)

        if not download_url:
            print(
                f"{COLOR_ERROR}CLF3 requires a download URL for '{machine_name}' but none was found in the "
                f"gallery cache. Refresh the modlist gallery or use a local .wabbajack file.{COLOR_RESET}"
            )
            return None

        print(f"{COLOR_INFO}Downloading modlist file via CLF3...{COLOR_RESET}")
        from jackify.backend.handlers.subprocess_utils import get_clean_subprocess_env
        fetch_cmd = [engine_path, "fetch", download_url, "--output", local_path]
        self.logger.debug("CLF3 fetch command: %s", " ".join(fetch_cmd))
        fetch_env = get_clean_subprocess_env({})
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        fetch_result = subprocess.run(
            fetch_cmd, capture_output=True, text=True, env=fetch_env, cwd=engine_dir
        )
        if fetch_result.returncode != 0:
            err = fetch_result.stderr.strip() or fetch_result.stdout.strip() or "unknown error"
            print(f"{COLOR_ERROR}Failed to download modlist file:\n{err}{COLOR_RESET}")
            return None

        print(f"{COLOR_INFO}Modlist file ready.{COLOR_RESET}")
        return local_path

    def _run_install_engine(self, gui_mode: bool = False) -> Optional[Tuple[str, str]]:
        """Execute the active install engine and stream its output to the console/log.

        Returns (install_dir_str, download_dir_str) on success, or None if the run
        was aborted or failed (an error has already been printed/logged).
        """
        from jackify.shared.paths import get_jackify_logs_dir
        log_dir = get_jackify_logs_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        workflow_log_path = log_dir / "Modlist_Install_workflow.log"
        max_logs = 3
        max_size = 1024 * 1024
        if workflow_log_path.exists() and workflow_log_path.stat().st_size > max_size:
            for i in range(max_logs, 0, -1):
                prev = log_dir / f"Modlist_Install_workflow.log.{i-1}" if i > 1 else workflow_log_path
                dest = log_dir / f"Modlist_Install_workflow.log.{i}"
                if prev.exists():
                    if dest.exists():
                        dest.unlink()
                    prev.rename(dest)
        workflow_log = open(workflow_log_path, 'a')
        class TeeStdout:
            def __init__(self, *files):
                self.files = files
            def write(self, data):
                for f in self.files:
                    f.write(data)
                    f.flush()
            def flush(self):
                for f in self.files:
                    f.flush()
        orig_stdout, orig_stderr = sys.stdout, sys.stderr
        sys.stdout = TeeStdout(sys.stdout, workflow_log)
        sys.stderr = TeeStdout(sys.stderr, workflow_log)
        try:
            install_dir_context = self.context['install_dir']
            if isinstance(install_dir_context, tuple):
                actual_install_path = Path(install_dir_context[0])
                if install_dir_context[1]:
                    self.logger.info(f"Creating install directory as it was marked for creation: {actual_install_path}")
                    actual_install_path.mkdir(parents=True, exist_ok=True)
            else:
                actual_install_path = Path(install_dir_context)
            install_dir_str = str(actual_install_path)
            self.logger.debug(f"Processed install directory for engine: {install_dir_str}")

            download_dir_context = self.context['download_dir']
            if isinstance(download_dir_context, tuple):
                actual_download_path = Path(download_dir_context[0])
                if download_dir_context[1]:
                    self.logger.info(f"Creating download directory as it was marked for creation: {actual_download_path}")
                    actual_download_path.mkdir(parents=True, exist_ok=True)
            else:
                actual_download_path = Path(download_dir_context)
            download_dir_str = str(actual_download_path)
            self.logger.debug(f"Processed download directory for engine: {download_dir_str}")

            modlist_arg = self.context.get('modlist_value') or self.context.get('machineid')
            machineid = self.context.get('machineid')

            from jackify.backend.services.nexus_auth_service import NexusAuthService
            auth_service = NexusAuthService()
            current_api_key, current_oauth_info = auth_service.get_auth_for_engine()

            api_key = current_api_key or self.context.get('nexus_api_key')
            oauth_info = current_oauth_info or self.context.get('nexus_oauth_info')

            from jackify.backend.services.engine_invoker import (
                get_active_engine_id, get_engine_path, build_install_command,
                resolve_game_dir, resolve_game_location, is_clf3_active,
            )
            from jackify.backend.handlers.config_handler import ConfigHandler
            config_handler = ConfigHandler()

            engine_id = get_active_engine_id()
            engine_path = get_engine_path(engine_id)
            if not engine_path or not os.path.isfile(engine_path) or not os.access(engine_path, os.X_OK):
                print(f"{COLOR_ERROR}Install engine not found or not executable: {engine_id} ({engine_path or 'path unknown'}){COLOR_RESET}")
                return None
            engine_dir = os.path.dirname(engine_path)
            clf3_mode = is_clf3_active()

            if gui_mode:
                if not self.context.get('modlist_source'):
                    self.context['modlist_source'] = 'identifier'
                if not self.context.get('modlist_value'):
                    self.logger.error("modlist_value is missing in context for GUI workflow!")
                    return None

            modlist_value = self.context.get('modlist_value') or self.context.get('machineid', '')
            debug_mode = config_handler.get('debug_mode', False)

            game_dir = None
            if clf3_mode:
                game_type = self.context.get('game_type')
                location = resolve_game_location(game_type)
                if location:
                    game_dir, game_store = location
                    if game_store != 'steam':
                        store_label = {'gog': 'GOG', 'epic': 'Epic Games'}.get(game_store, game_store)
                        print(
                            f"[WARN] Game detected from {store_label}, not Steam. "
                            "Most Wabbajack modlists require the Steam version. "
                            "If the install fails with hash errors, a store version mismatch is likely the cause."
                        )
                else:
                    self.logger.warning("CLF3: could not resolve game directory for game_type=%s", game_type)

                if not (modlist_value.endswith('.wabbajack') and os.path.isfile(modlist_value)):
                    modlist_value = self._clf3_fetch_wabbajack(
                        engine_path, modlist_value, engine_dir
                    )
                    if modlist_value is None:
                        return None

            cmd = build_install_command(
                engine_id=engine_id,
                engine_path=engine_path,
                wabbajack=modlist_value,
                install_dir=install_dir_str,
                downloads_dir=download_dir_str,
                game_dir=game_dir,
                install_mode='file' if (modlist_value.endswith('.wabbajack') and os.path.isfile(modlist_value)) else 'online',
                debug=debug_mode,
            )
            if debug_mode and not clf3_mode:
                self.logger.info("Adding --debug flag to jackify-engine")
            writeback_path = str(auth_service.get_token_writeback_path()) if not clf3_mode else None
            extra_env = {}
            _registered_pgids = []

            try:
                if clf3_mode:
                    if api_key:
                        extra_env['NEXUS_OAUTH_TOKEN'] = api_key
                else:
                    if writeback_path:
                        extra_env['JACKIFY_TOKEN_WRITEBACK'] = writeback_path
                    if api_key:
                        extra_env['NEXUS_API_KEY'] = api_key
                    if oauth_info:
                        extra_env['NEXUS_OAUTH_INFO'] = oauth_info
                        from jackify.backend.services.nexus_oauth_service import NexusOAuthService
                        extra_env['NEXUS_OAUTH_CLIENT_ID'] = NexusOAuthService.CLIENT_ID
                        self.logger.debug("Set NEXUS_OAUTH_INFO and NEXUS_OAUTH_CLIENT_ID for engine")
                    extra_env['DOTNET_SYSTEM_GLOBALIZATION_INVARIANT'] = "1"

                self.logger.info("Environment prepared for %s install process.", engine_id)
                self.logger.debug(f"NEXUS_API_KEY for engine call: {'[SET]' if extra_env.get('NEXUS_API_KEY') else '[NOT SET]'}")

                pretty_cmd = ' '.join([f'"{arg}"' if ' ' in arg else arg for arg in cmd])
                engine_label = "CLF3" if clf3_mode else "Jackify Install Engine"
                print(f"{COLOR_INFO}Launching {engine_label} with command:{COLOR_RESET} {pretty_cmd}")

                from jackify.backend.handlers.subprocess_utils import increase_file_descriptor_limit
                success, old_limit, new_limit, message = increase_file_descriptor_limit()
                if success:
                    self.logger.debug(f"File descriptor limit: {message}")
                else:
                    self.logger.warning(f"File descriptor limit: {message}")

                from jackify.backend.handlers.subprocess_utils import get_clean_subprocess_env
                clean_env = get_clean_subprocess_env(extra_env)

                if clf3_mode:
                    import threading as _threading
                    from jackify.backend.handlers.progress_parser_clf3 import CLF3ProgressStateManager
                    clf3_parser = CLF3ProgressStateManager()
                    from jackify.backend.handlers.subprocess_utils import register_process_group
                    self._current_process = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=False,
                        env=clean_env,
                        cwd=engine_dir,
                        start_new_session=True,
                    )
                    proc = self._current_process
                    _pgid = os.getpgid(proc.pid)
                    register_process_group(_pgid)
                    _registered_pgids.append(_pgid)

                    def _drain_stderr():
                        for _ in proc.stderr:
                            pass

                    stderr_thread = _threading.Thread(target=_drain_stderr, daemon=True)
                    stderr_thread.start()

                    _inline_active = False
                    _last_phase = ''
                    for raw in proc.stdout:
                        line = raw.decode('utf-8', errors='replace').rstrip('\r\n')
                        if not line.strip():
                            continue
                        if line.strip().startswith('{'):
                            prev_phase = clf3_parser.get_state().phase_name
                            changed = clf3_parser.process_line(line)
                            if changed:
                                state = clf3_parser.get_state()
                                new_phase = state.phase_name or ''
                                if new_phase != _last_phase:
                                    if _inline_active:
                                        print()
                                        _inline_active = False
                                    _last_phase = new_phase
                                    print(f"\n=== {new_phase} ===")
                                msg = state.message
                                if state.phase_name == "Queuing" and state.phase_max_steps:
                                    msg = f"Queuing archives: {state.phase_step}/{state.phase_max_steps}"
                                if msg:
                                    print(f"\r{msg}\033[K", end='', flush=True)
                                    _inline_active = True
                        else:
                            if _inline_active:
                                print()
                                _inline_active = False
                            print(line)

                    if _inline_active:
                        print()
                    stderr_thread.join(timeout=2)
                    proc.wait()
                    self._current_process = None
                    if proc.returncode != 0:
                        print(f"{COLOR_ERROR}CLF3 exited with code {proc.returncode}.{COLOR_RESET}")
                        self.logger.error("CLF3 exited with code %d.", proc.returncode)
                        return None
                    self.logger.info("CLF3 completed successfully.")

                if not clf3_mode:
                    from jackify.backend.handlers.subprocess_utils import register_process_group
                    self._current_process = subprocess.Popen(
                        cmd,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=False,
                        env=clean_env,
                        cwd=engine_dir,
                        start_new_session=True,
                    )
                    proc = self._current_process
                    _pgid = os.getpgid(proc.pid)
                    register_process_group(_pgid)
                    _registered_pgids.append(_pgid)

                def _write_stdin(payload: str) -> bool:
                    if not proc.stdin or proc.poll() is not None:
                        return False
                    try:
                        proc.stdin.write((payload + '\n').encode('utf-8'))
                        proc.stdin.flush()
                        return True
                    except Exception:
                        self.logger.debug("Failed writing to engine stdin", exc_info=True)
                        return False

                buffer = b''
                inline_progress_active = False
                pending_manual = []
                while True:
                    chunk = proc.stdout.read(1)
                    if not chunk:
                        break
                    buffer += chunk

                    if chunk in (b'\n', b'\r'):
                        line = buffer.decode('utf-8', errors='replace')
                        decoded = line.rstrip('\r\n')
                        if decoded.startswith('{'):
                            try:
                                event = json.loads(decoded)
                            except (json.JSONDecodeError, ValueError):
                                event = None
                            if event:
                                event_name = event.get('event')
                                if event_name == 'manual_download_required':
                                    pending_manual.append(event)
                                    buffer = b''
                                    continue
                                if event_name == 'manual_download_list_complete':
                                    loop_iter = event.get('loop_iteration', 1)
                                    for item in pending_manual:
                                        item['loop_iteration'] = loop_iter
                                    from jackify.backend.handlers.config_handler import ConfigHandler
                                    raw_limit = ConfigHandler().get('manual_download_concurrent_limit', 2)
                                    try:
                                        manual_limit = int(raw_limit)
                                    except (TypeError, ValueError):
                                        manual_limit = 2
                                    from jackify.frontends.cli.commands.manual_download_flow import run_cli_manual_download_phase
                                    completed = run_cli_manual_download_phase(
                                        events=list(pending_manual),
                                        loop_iteration=loop_iter,
                                        download_dir=actual_download_path,
                                        stdin_write=_write_stdin,
                                        concurrent_limit=max(1, min(5, manual_limit)),
                                    )
                                    if not completed:
                                        if proc.poll() is None:
                                            proc.terminate()
                                        buffer = b''
                                        break
                                    pending_manual.clear()
                                    buffer = b''
                                    continue
                                if event_name == 'manual_download_phase_complete':
                                    print("All manual downloads confirmed. Resuming installation...")
                                    buffer = b''
                                    continue
                        if '[FILE_PROGRESS]' in line:
                            parts = line.split('[FILE_PROGRESS]', 1)
                            if parts[0].strip():
                                line = parts[0].rstrip()
                            else:
                                buffer = b''
                                continue
                        clean_line = line.rstrip('\r\n')
                        if clean_line.startswith("Installing files "):
                            print(f"\r{clean_line}", end='')
                            sys.stdout.flush()
                            inline_progress_active = True
                        else:
                            if inline_progress_active:
                                print()
                                inline_progress_active = False
                            print(line, end='')
                        buffer = b''

                if buffer:
                    line = buffer.decode('utf-8', errors='replace')
                    if '[FILE_PROGRESS]' in line:
                        parts = line.split('[FILE_PROGRESS]', 1)
                        if parts[0].strip():
                            line = parts[0].rstrip()
                        else:
                            line = ''
                    if line:
                        if inline_progress_active:
                            print()
                            inline_progress_active = False
                        print(line, end='')

                if inline_progress_active:
                    print()

                proc.wait()
                self._current_process = None
                if writeback_path:
                    auth_service.apply_token_writeback(writeback_path)
                if not clf3_mode:
                    if proc.returncode != 0:
                        print(f"{COLOR_ERROR}Jackify Install Engine exited with code {proc.returncode}.{COLOR_RESET}")
                        self.logger.error(f"Engine exited with code {proc.returncode}.")
                        self._record_install_failure("engine_crash")
                        return None
                    self.logger.info(f"Engine completed with code {proc.returncode}.")
            except Exception as e:
                error_message = str(e)
                print(f"{COLOR_ERROR}Error running Jackify Install Engine: {error_message}{COLOR_RESET}\n")
                self.logger.error(f"Exception running engine: {error_message}", exc_info=True)

                try:
                    from jackify.backend.services.resource_manager import handle_file_descriptor_error
                    if any(indicator in error_message.lower() for indicator in ['too many open files', 'emfile', 'resource temporarily unavailable']):
                        result = handle_file_descriptor_error(error_message, "Jackify Install Engine execution")
                        if result['auto_fix_success']:
                            print(f"{COLOR_INFO}File descriptor limit increased automatically. {result['recommendation']}{COLOR_RESET}")
                            self.logger.info(f"File descriptor limit increased automatically. {result['recommendation']}")
                        elif result['error_detected']:
                            print(f"{COLOR_WARNING}File descriptor limit issue detected. {result['recommendation']}{COLOR_RESET}")
                            self.logger.warning(f"File descriptor limit issue detected but automatic fix failed. {result['recommendation']}")
                            if result['manual_instructions']:
                                distro = result['manual_instructions']['distribution']
                                print(f"{COLOR_INFO}Manual ulimit increase instructions available for {distro} distribution{COLOR_RESET}")
                                self.logger.info(f"Manual ulimit increase instructions available for {distro} distribution")
                except Exception as resource_error:
                    self.logger.debug(f"Error checking for resource limit issues: {resource_error}")

                self._record_install_failure("engine_crash")
                return None
            finally:
                from jackify.backend.handlers.subprocess_utils import unregister_process_group
                for _pgid in _registered_pgids:
                    unregister_process_group(_pgid)

        except Exception as e:
            error_message = str(e)
            print(f"{COLOR_ERROR}Error during installation workflow: {error_message}{COLOR_RESET}\n")
            self.logger.error(f"Exception in installation workflow: {error_message}", exc_info=True)

            try:
                from jackify.backend.services.resource_manager import handle_file_descriptor_error
                if any(indicator in error_message.lower() for indicator in ['too many open files', 'emfile', 'resource temporarily unavailable']):
                    result = handle_file_descriptor_error(error_message, "installation workflow")
                    if result['auto_fix_success']:
                        print(f"{COLOR_INFO}File descriptor limit increased automatically. {result['recommendation']}{COLOR_RESET}")
                        self.logger.info(f"File descriptor limit increased automatically. {result['recommendation']}")
                    elif result['error_detected']:
                        print(f"{COLOR_WARNING}File descriptor limit issue detected. {result['recommendation']}{COLOR_RESET}")
                        self.logger.warning(f"File descriptor limit issue detected but automatic fix failed. {result['recommendation']}")
                        if result['manual_instructions']:
                            distro = result['manual_instructions']['distribution']
                            print(f"{COLOR_INFO}Manual ulimit increase instructions available for {distro} distribution{COLOR_RESET}")
                            self.logger.info(f"Manual ulimit increase instructions available for {distro} distribution")
            except Exception as resource_error:
                self.logger.debug(f"Error checking for resource limit issues: {resource_error}")

            self._record_install_failure("unknown")
            return None
        finally:
            sys.stdout = orig_stdout
            sys.stderr = orig_stderr
            workflow_log.close()

        return install_dir_str, download_dir_str
