"""CLI configuration phase methods for ModlistInstallCLI (Mixin)."""
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

from jackify.shared.colors import (
    COLOR_PROMPT,
    COLOR_RESET,
    COLOR_INFO,
    COLOR_ERROR,
    COLOR_SUCCESS,
    COLOR_WARNING,
)

logger = logging.getLogger(__name__)


class ModlistOperationsConfigurationCLIMixin:
    """Mixin providing CLI configuration phase methods."""

    def _clf3_fetch_wabbajack(self, engine_path: str, machine_name: str, engine_dir: str) -> "str | None":
        """
        Resolve a gallery machine name to a local .wabbajack file for CLF3.

        Looks up the CDN download URL from the metadata cache, then runs
        `clf3 fetch` to download the file.  Returns the local path on success,
        or None (with an error printed) on failure.
        """
        from jackify.shared.paths import get_jackify_data_dir, get_jackify_downloads_dir
        import json as _json

        list_id = machine_name.split('/')[-1] if '/' in machine_name else machine_name
        local_path = str(get_jackify_downloads_dir() / f"{list_id}.wabbajack")

        if os.path.isfile(local_path):
            self.logger.info("CLF3: using cached wabbajack file at %s", local_path)
            return local_path

        download_url = None
        cache_file = get_jackify_data_dir() / "modlist-cache" / "metadata" / "modlist_metadata.json"
        if cache_file.is_file():
            try:
                data = _json.loads(cache_file.read_text(encoding="utf-8"))
                for entry in data.get("modlists", []):
                    if entry.get("namespacedName") == machine_name or entry.get("machineURL") == list_id:
                        download_url = (entry.get("links") or {}).get("download")
                        break
            except Exception as e:
                self.logger.warning("CLF3: could not read metadata cache: %s", e)

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

    def configuration_phase(self):
        """
        Run the configuration phase: execute the active install engine.
        """

        print(f"\n{COLOR_PROMPT}--- Configuration Phase: Installing Modlist ---{COLOR_RESET}")
        start_time = time.time()

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
                return
            engine_dir = os.path.dirname(engine_path)
            clf3_mode = is_clf3_active()

            if os.environ.get('JACKIFY_GUI_MODE') == '1':
                if not self.context.get('modlist_source'):
                    self.context['modlist_source'] = 'identifier'
                if not self.context.get('modlist_value'):
                    self.logger.error("modlist_value is missing in context for GUI workflow!")
                    return

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
                        return

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
            original_env_values = {
                'NEXUS_API_KEY': os.environ.get('NEXUS_API_KEY'),
                'NEXUS_OAUTH_TOKEN': os.environ.get('NEXUS_OAUTH_TOKEN'),
                'NEXUS_OAUTH_INFO': os.environ.get('NEXUS_OAUTH_INFO'),
                'JACKIFY_TOKEN_WRITEBACK': os.environ.get('JACKIFY_TOKEN_WRITEBACK'),
                'DOTNET_SYSTEM_GLOBALIZATION_INVARIANT': os.environ.get('DOTNET_SYSTEM_GLOBALIZATION_INVARIANT')
            }

            try:
                if clf3_mode:
                    if api_key:
                        os.environ['NEXUS_OAUTH_TOKEN'] = api_key
                else:
                    if writeback_path:
                        os.environ['JACKIFY_TOKEN_WRITEBACK'] = writeback_path
                    if api_key:
                        os.environ['NEXUS_API_KEY'] = api_key
                    if oauth_info:
                        os.environ['NEXUS_OAUTH_INFO'] = oauth_info
                        from jackify.backend.services.nexus_oauth_service import NexusOAuthService
                        os.environ['NEXUS_OAUTH_CLIENT_ID'] = NexusOAuthService.CLIENT_ID
                        self.logger.debug("Set NEXUS_OAUTH_INFO and NEXUS_OAUTH_CLIENT_ID for engine")
                    elif not api_key:
                        for key in ('NEXUS_API_KEY', 'NEXUS_OAUTH_INFO', 'NEXUS_OAUTH_CLIENT_ID'):
                            os.environ.pop(key, None)
                        self.logger.debug("No Nexus auth available, cleared inherited env vars")
                    os.environ['DOTNET_SYSTEM_GLOBALIZATION_INVARIANT'] = "1"

                self.logger.info("Environment prepared for %s install process.", engine_id)
                self.logger.debug(f"NEXUS_API_KEY in os.environ (pre-call): {'[SET]' if os.environ.get('NEXUS_API_KEY') else '[NOT SET]'}")

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
                clean_env = get_clean_subprocess_env()

                if clf3_mode:
                    import threading as _threading
                    from jackify.backend.handlers.progress_parser_clf3 import CLF3ProgressStateManager
                    clf3_parser = CLF3ProgressStateManager()
                    self._current_process = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=False,
                        env=clean_env,
                        cwd=engine_dir,
                    )
                    proc = self._current_process

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
                        return
                    self.logger.info("CLF3 completed successfully.")

                if not clf3_mode:
                    self._current_process = subprocess.Popen(
                        cmd,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=False,
                        env=clean_env,
                        cwd=engine_dir,
                    )
                    proc = self._current_process

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
                        return
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

                return
            finally:
                for key, original_value in original_env_values.items():
                    current_value_in_os_environ = os.environ.get(key)

                    display_original_value = f"'[REDACTED]'" if key == 'NEXUS_API_KEY' else f"'{original_value}'"

                    if original_value is not None:
                        if current_value_in_os_environ != original_value:
                            os.environ[key] = original_value
                            self.logger.debug(f"Restored os.environ['{key}'] to its original value: {display_original_value}.")
                        else:
                            os.environ[key] = original_value
                            self.logger.debug(f"os.environ['{key}'] ('{display_original_value}') matched original value. Ensured restoration.")
                    else:
                        if key in os.environ:
                            self.logger.debug(f"Original os.environ['{key}'] was not set. Removing current value ('{'[REDACTED]' if os.environ.get(key) and key == 'NEXUS_API_KEY' else os.environ.get(key)}') that was set for the call.")
                            del os.environ[key]

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

            return
        finally:
            sys.stdout = orig_stdout
            sys.stderr = orig_stderr
            workflow_log.close()

        elapsed = int(time.time() - start_time)
        print(f"\nElapsed time: {elapsed//3600:02d}:{(elapsed%3600)//60:02d}:{elapsed%60:02d} (hh:mm:ss)\n")
        print(f"{COLOR_INFO}Your modlist has been installed to: {install_dir_str}{COLOR_RESET}\n")

        try:
            from jackify.backend.utils.modlist_meta import write_modlist_meta
            _meta_game_type = self.context.get('detected_game') or self.context.get('special_game_type')
            write_modlist_meta(
                install_dir_str,
                self.context.get('modlist_name', ''),
                _meta_game_type,
                install_mode=self.context.get('install_mode', 'online'),
            )
        except Exception as _meta_err:
            self.logger.debug("Modlist meta write skipped: %s", _meta_err)

        try:
            from jackify.backend.handlers.path_handler import PathHandler
            _ini_path = Path(install_dir_str) / "ModOrganizer.ini"
            _modlist_sdcard = install_dir_str.startswith('/run/media/')
            PathHandler().set_download_directory(_ini_path, download_dir_str, _modlist_sdcard)
            self.logger.info("Set download_directory in ModOrganizer.ini: %s", download_dir_str)
        except Exception as _ini_err:
            self.logger.warning("Could not set download_directory in ModOrganizer.ini: %s", _ini_err)

        if self.context.get('machineid') != 'Tuxborn/Tuxborn':
            print(f"{COLOR_WARNING}Only Skyrim, Fallout 4, Fallout New Vegas, Oblivion, Starfield, and Oblivion Remastered modlists are compatible with Jackify's post-install configuration. Any modlist can be downloaded/installed, but only these games are supported for automated configuration.{COLOR_RESET}")

        self.logger.debug("configuration_phase: Starting post-install game detection...")

        modorganizer_ini = os.path.join(install_dir_str, "ModOrganizer.ini")
        detected_game = None
        self.logger.debug(f"configuration_phase: Looking for ModOrganizer.ini at: {modorganizer_ini}")
        if os.path.isfile(modorganizer_ini):
            self.logger.debug("configuration_phase: Found ModOrganizer.ini, detecting game...")
            from ..handlers.modlist_handler import ModlistHandler
            handler = ModlistHandler({}, steamdeck=self.steamdeck)
            handler.modlist_ini = modorganizer_ini
            handler.modlist_dir = install_dir_str
            if handler._detect_game_variables():
                detected_game = handler.game_var_full
                self.logger.debug(f"configuration_phase: Detected game: {detected_game}")
            else:
                self.logger.debug("configuration_phase: Failed to detect game variables")
        else:
            self.logger.debug("configuration_phase: ModOrganizer.ini not found")

        supported_games = ["Skyrim Special Edition", "Fallout 4", "Fallout New Vegas", "Oblivion", "Starfield", "Oblivion Remastered", "Enderal"]
        is_tuxborn = self.context.get('machineid') == 'Tuxborn/Tuxborn'
        self.logger.debug(f"configuration_phase: detected_game='{detected_game}', is_tuxborn={is_tuxborn}")
        self.logger.debug(f"configuration_phase: Checking condition: (detected_game in supported_games) or is_tuxborn")
        self.logger.debug(f"configuration_phase: Result: {(detected_game in supported_games) or is_tuxborn}")

        if (detected_game in supported_games) or is_tuxborn:
            self.logger.debug("configuration_phase: Entering Steam configuration workflow...")
            shortcut_name = self.context.get('modlist_name')
            self.logger.debug(f"configuration_phase: shortcut_name from context: '{shortcut_name}'")

            if is_tuxborn and not shortcut_name:
                self.logger.warning("Tuxborn is true, but shortcut_name (modlist_name in context) is missing. Defaulting to 'Tuxborn Automatic Installer'")
                shortcut_name = "Tuxborn Automatic Installer"
            elif not shortcut_name:
                print("\n" + "-" * 28)
                print(f"{COLOR_PROMPT}Please provide a name for the Steam shortcut for '{self.context.get('modlist_name', 'this modlist')}'.{COLOR_RESET}")
                raw_shortcut_name = input(f"{COLOR_PROMPT}Steam Shortcut Name (or 'q' to cancel): {COLOR_RESET} ").strip()
                if raw_shortcut_name.lower() == 'q' or not raw_shortcut_name:
                    self.logger.debug("configuration_phase: User cancelled shortcut name input")
                    return
                shortcut_name = raw_shortcut_name

            self.logger.debug(f"configuration_phase: Final shortcut_name: '{shortcut_name}'")

            is_gui_mode = os.environ.get('JACKIFY_GUI_MODE') == '1'
            self.logger.debug(f"configuration_phase: is_gui_mode={is_gui_mode}")

            if not is_gui_mode:
                self.logger.debug("configuration_phase: Not in GUI mode, prompting user for configuration...")
                print("\n" + "-" * 28)
                print(
                    f"{COLOR_PROMPT}Would you like to add '{shortcut_name}' to Steam and configure it now? "
                    f"Steam will restart and close any running game.{COLOR_RESET}"
                )
                configure_choice = input(f"{COLOR_PROMPT}Configure now? (Y/n): {COLOR_RESET}").strip().lower()
                self.logger.debug(f"configuration_phase: User choice: '{configure_choice}'")

                if configure_choice == 'n':
                    print(f"{COLOR_INFO}Skipping Steam configuration. You can configure it later using 'Configure New Modlist'.{COLOR_RESET}")
                    self.logger.debug("configuration_phase: User chose to skip Steam configuration")
                    return
            else:
                self.logger.debug("configuration_phase: In GUI mode, proceeding automatically...")

            self.logger.debug("configuration_phase: Proceeding with Steam configuration...")

            if not is_gui_mode:
                from jackify.backend.handlers.resolution_handler import ResolutionHandler
                resolution_handler = ResolutionHandler()

                is_steamdeck = self.steamdeck if hasattr(self, 'steamdeck') else False

                selected_resolution = resolution_handler.select_resolution(steamdeck=is_steamdeck)
                if selected_resolution:
                    self.context['resolution'] = selected_resolution
                    self.logger.info(f"Resolution set to: {selected_resolution}")

            self.logger.info(f"Starting Steam configuration for '{shortcut_name}'")

            mo2_exe_path = os.path.join(install_dir_str, 'ModOrganizer.exe')

            app_id = None
            use_automated_prefix = os.environ.get('JACKIFY_USE_AUTOMATED_PREFIX', '1') == '1'
            existing_shortcut_appid = self.context.get('existing_shortcut_appid')
            update_existing_install = bool(self.context.get('update_existing_install'))

            if update_existing_install and existing_shortcut_appid:
                app_id = str(existing_shortcut_appid)
                success = True
                prefix_path = None
                result = True
                print(f"\n{COLOR_INFO}Update mode selected. Reusing existing Steam shortcut AppID {app_id}.{COLOR_RESET}")
                use_automated_prefix = False

            if use_automated_prefix:
                print(f"\n{COLOR_INFO}Using automated Steam setup workflow...{COLOR_RESET}")

                from ..services.automated_prefix_service import AutomatedPrefixService
                prefix_service = AutomatedPrefixService()

                start_time = time.time()

                def progress_callback(message):
                    noisy_patterns = (
                        "using bundled tools directory",
                        "bundled tools available",
                        "checking winetricks dependencies",
                        "(bundled)",
                        "(system)",
                        "wget",
                        "curl",
                        "aria2c",
                        "sha256sum",
                        "cabextract",
                    )
                    message_lc = message.lower()
                    if any(pattern in message_lc for pattern in noisy_patterns):
                        # Keep dependency/tool chatter in logs only for CLI readability.
                        self.logger.debug("Automated prefix detail: %s", message)
                        return

                    elapsed = time.time() - start_time
                    hours = int(elapsed // 3600)
                    minutes = int((elapsed % 3600) // 60)
                    seconds = int(elapsed % 60)
                    timestamp = f"[{hours:02d}:{minutes:02d}:{seconds:02d}]"
                    self.logger.info("Automated prefix progress: %s", message)
                    print(f"{COLOR_INFO}{timestamp} {message}{COLOR_RESET}")

                try:
                    _is_steamdeck = False
                    if os.path.exists('/etc/os-release'):
                        with open('/etc/os-release') as f:
                            if 'steamdeck' in f.read().lower():
                                _is_steamdeck = True
                except Exception:
                    _is_steamdeck = False
                from jackify.backend.services.nxm_downloader import resolve_mo2_download_dir
                download_dir = resolve_mo2_download_dir(Path(install_dir_str))
                result = prefix_service.run_working_workflow(
                    shortcut_name, install_dir_str, mo2_exe_path, progress_callback,
                    steamdeck=_is_steamdeck, download_dir=download_dir,
                )

                if isinstance(result, tuple) and len(result) == 4:
                    if result[0] == "CONFLICT":
                        conflicts = result[1]
                        print(f"\n{COLOR_WARNING}Found existing Steam shortcut(s) with the same name and path:{COLOR_RESET}")

                        for i, conflict in enumerate(conflicts, 1):
                            print(f"  {i}. Name: {conflict['name']}")
                            print(f"     Executable: {conflict['exe']}")
                            print(f"     Start Directory: {conflict['startdir']}")

                        print(f"\n{COLOR_PROMPT}Options:{COLOR_RESET}")
                        print("  * Replace - Remove the existing shortcut and create a new one")
                        print("  * Cancel - Keep the existing shortcut and stop the installation")
                        print("  * Skip - Continue without creating a Steam shortcut")

                        choice = input(f"\n{COLOR_PROMPT}Choose an option (replace/cancel/skip): {COLOR_RESET}").strip().lower()

                        if choice == 'replace':
                            print(f"{COLOR_INFO}Replacing existing shortcut...{COLOR_RESET}")
                            success, app_id = prefix_service.replace_existing_shortcut(shortcut_name, mo2_exe_path, install_dir_str)
                            if success and app_id:
                                result = prefix_service.continue_workflow_after_conflict_resolution(
                                    shortcut_name, install_dir_str, mo2_exe_path, app_id, progress_callback
                                )
                                if isinstance(result, tuple) and len(result) >= 3:
                                    success, prefix_path, app_id = result[0], result[1], result[2]
                                else:
                                    success, prefix_path, app_id = False, None, None
                            else:
                                success, prefix_path, app_id = False, None, None
                        elif choice == 'cancel':
                            print(f"{COLOR_INFO}Cancelling installation.{COLOR_RESET}")
                            return
                        elif choice == 'skip':
                            print(f"{COLOR_INFO}Skipping Steam shortcut creation.{COLOR_RESET}")
                            success, prefix_path, app_id = True, None, None
                        else:
                            print(f"{COLOR_ERROR}Invalid choice. Cancelling.{COLOR_RESET}")
                            return
                    else:
                        success, prefix_path, app_id, last_timestamp = result
                elif isinstance(result, tuple) and len(result) == 3:
                    if result[0] == "CONFLICT":
                        conflicts = result[1]
                        print(f"\n{COLOR_WARNING}Found existing Steam shortcut(s) with the same name and path:{COLOR_RESET}")

                        for i, conflict in enumerate(conflicts, 1):
                            print(f"  {i}. Name: {conflict['name']}")
                            print(f"     Executable: {conflict['exe']}")
                            print(f"     Start Directory: {conflict['startdir']}")

                        print(f"\n{COLOR_PROMPT}Options:{COLOR_RESET}")
                        print("  * Replace - Remove the existing shortcut and create a new one")
                        print("  * Cancel - Keep the existing shortcut and stop the installation")
                        print("  * Skip - Continue without creating a Steam shortcut")

                        choice = input(f"\n{COLOR_PROMPT}Choose an option (replace/cancel/skip): {COLOR_RESET}").strip().lower()

                        if choice == 'replace':
                            print(f"{COLOR_INFO}Replacing existing shortcut...{COLOR_RESET}")
                            success, app_id = prefix_service.replace_existing_shortcut(shortcut_name, mo2_exe_path, install_dir_str)
                            if success and app_id:
                                result = prefix_service.continue_workflow_after_conflict_resolution(
                                    shortcut_name, install_dir_str, mo2_exe_path, app_id, progress_callback
                                )
                                if isinstance(result, tuple) and len(result) >= 3:
                                    success, prefix_path, app_id = result[0], result[1], result[2]
                                else:
                                    success, prefix_path, app_id = False, None, None
                            else:
                                success, prefix_path, app_id = False, None, None
                        elif choice == 'cancel':
                            print(f"{COLOR_INFO}Cancelling installation.{COLOR_RESET}")
                            return
                        elif choice == 'skip':
                            print(f"{COLOR_INFO}Skipping Steam shortcut creation.{COLOR_RESET}")
                            success, prefix_path, app_id = True, None, None
                        else:
                            print(f"{COLOR_ERROR}Invalid choice. Cancelling.{COLOR_RESET}")
                            return
                    else:
                        success, prefix_path, app_id = result
                else:
                    if result is True:
                        success, prefix_path, app_id = True, None, None
                    else:
                        success, prefix_path, app_id = False, None, None
            if success:
                if update_existing_install and app_id:
                    print(f"{COLOR_SUCCESS}Update mode Steam setup confirmed.{COLOR_RESET}")
                    print(f"{COLOR_INFO}Reusing Steam AppID: {app_id}{COLOR_RESET}")
                    # Apply artwork and restart Steam -- skipped in update path since the full
                    # workflow is bypassed, but artwork and Steam state still need refreshing.
                    _game_type = self.context.get('detected_game') or self.context.get('special_game_type')
                    try:
                        from jackify.backend.handlers.modlist_handler import ModlistHandler
                        ModlistHandler().set_steam_grid_images(str(app_id), install_dir_str, game_type=_game_type)
                    except Exception as e:
                        self.logger.warning("Failed to apply Steam artwork in update mode: %s", e)
                    if _game_type == 'cp2077':
                        # CP2077 launch options may be absent on lists originally installed
                        # under v0.5 before CP2077 support was added.
                        try:
                            from jackify.backend.handlers.shortcut_handler import ShortcutHandler
                            from jackify.backend.handlers.config_handler import ConfigHandler
                            sh = ShortcutHandler(
                                config_handler=ConfigHandler(),
                                steamdeck=bool(self.system_info and self.system_info.is_steamdeck),
                            )
                            sh.update_shortcut_launch_options(
                                shortcut_name,
                                mo2_exe_path,
                                'WINEDLLOVERRIDES="version=n,b;winmm=n,b" %command%',
                            )
                        except Exception as e:
                            self.logger.warning("Failed to update CP2077 launch options in update mode: %s", e)
                    try:
                        from jackify.backend.services.automated_prefix_service import AutomatedPrefixService
                        AutomatedPrefixService(self.system_info).restart_steam()
                    except Exception as e:
                        self.logger.warning("Failed to restart Steam in update mode: %s", e)
                else:
                    print(f"{COLOR_SUCCESS}Automated Steam setup completed successfully!{COLOR_RESET}")
                    if prefix_path:
                        print(f"{COLOR_INFO}Proton prefix created at: {prefix_path}{COLOR_RESET}")
                    if app_id:
                        print(f"{COLOR_INFO}Steam AppID: {app_id}{COLOR_RESET}")
            else:
                print(f"{COLOR_ERROR}Automated Steam setup failed. Result: {result}{COLOR_RESET}")
                print(f"{COLOR_ERROR}Steam integration was not completed. Please check the logs for details.{COLOR_RESET}")
                return

            from jackify.backend.services.modlist_service import ModlistService
            from jackify.backend.models.modlist import ModlistContext

            modlist_context = ModlistContext(
                name=shortcut_name,
                install_dir=Path(install_dir_str),
                download_dir=Path(download_dir_str),
                game_type=self.context.get('detected_game', 'Unknown'),
                nexus_api_key='',
                modlist_value=self.context.get('modlist_value', ''),
                modlist_source=self.context.get('modlist_source', 'identifier'),
                resolution=self.context.get('resolution'),
                mo2_exe_path=Path(mo2_exe_path),
                skip_confirmation=True,
                engine_installed=True
            )

            modlist_context.app_id = app_id

            modlist_service = ModlistService(self.system_info)

            if 'progress_callback' in locals() and progress_callback:
                progress_callback("")
                progress_callback("=== Configuration Phase ===")

                print(f"\n{COLOR_INFO}=== Configuration Phase ==={COLOR_RESET}")
                self.logger.info("Running post-installation configuration phase using ModlistService")

            configuration_success = modlist_service.configure_modlist_post_steam(modlist_context)

            if configuration_success:
                self.logger.info("Post-installation configuration completed successfully")
                print(f"{COLOR_INFO}Core configuration complete. Checking post-install automation...{COLOR_RESET}")

                if getattr(modlist_context, 'enb_detected', False):
                    print(f"\n{COLOR_WARNING}ENB Detected{COLOR_RESET}")
                    from jackify.backend.data.modlist_proton_requirements import get_proton_requirement
                    _proton_req = get_proton_requirement(shortcut_name)
                    if _proton_req:
                        print(f"{COLOR_WARNING}This modlist requires {_proton_req['required']} for ENB compatibility.{COLOR_RESET}")
                        print(f"{COLOR_INFO}{_proton_req['note']}{COLOR_RESET}")
                    else:
                        print(f"{COLOR_INFO}If you plan on using ENB as part of this modlist, you will need one of the following Proton versions:{COLOR_RESET}")
                        print(f"{COLOR_INFO}  (In order of recommendation){COLOR_RESET}")
                        print(f"{COLOR_INFO}  - Proton-CachyOS{COLOR_RESET}")
                        print(f"{COLOR_INFO}  - GE-Proton{COLOR_RESET}")
                        print(f"{COLOR_INFO}  - Proton 9 (Valve){COLOR_RESET}")
                        print(f"{COLOR_WARNING}  Valve Proton 10 has known ENB compatibility issues.{COLOR_RESET}")

                from jackify.backend.data.modlist_proton_requirements import get_game_proton_warning
                _game_warning = get_game_proton_warning(detected_game or '')
                if _game_warning:
                    print(f"\n{COLOR_INFO}Recommended Proton versions for this game (in order of recommendation):{COLOR_RESET}")
                    for _version in _game_warning['recommended']:
                        print(f"{COLOR_INFO}  - {_version}{COLOR_RESET}")
                try:
                    # Ensure CLI install flow gets the same VNV automation behavior as GUI.
                    from jackify.backend.services.vnv_integration_helper import (
                        run_vnv_automation_if_applicable,
                        should_offer_vnv_automation,
                    )
                    from jackify.backend.services.automated_prefix_service import AutomatedPrefixService
                    from jackify.backend.services.vnv_post_install_service import VNVPostInstallService
                    from jackify.backend.handlers.path_handler import PathHandler
                    from jackify.frontends.cli.commands.vnv_manual_downloads import (
                        build_vnv_cli_manual_file_callback,
                        create_vnv_cli_progress_callback,
                        ensure_vnv_cli_manual_downloads,
                    )

                    modlist_name_for_automation = self.context.get('modlist_name') or shortcut_name or ""
                    def _confirm_vnv(description: str) -> bool:
                        print(f"\n{description}\n")
                        try:
                            user_input = input(f"{COLOR_PROMPT}Run VNV post-install automation now? (Y/n): {COLOR_RESET}").strip().lower()
                        except (EOFError, KeyboardInterrupt):
                            return False
                        return user_input in ("", "y", "yes")
                    install_path = Path(install_dir_str)
                    if should_offer_vnv_automation(modlist_name_for_automation, install_path):
                        game_paths = PathHandler().find_vanilla_game_paths()
                        resolved_game_root = game_paths.get('Fallout New Vegas')
                        vnv_service = VNVPostInstallService(
                            modlist_install_location=install_path,
                            game_root=resolved_game_root or install_path,
                            ttw_installer_path=AutomatedPrefixService.get_ttw_installer_path(),
                        )
                        completed = vnv_service.check_already_completed()
                        all_vnv_steps_done = (
                            completed['root_mods']
                            and completed['4gb_patch']
                            and completed['bsa_decompressed']
                        )
                        if all_vnv_steps_done:
                            print(f"{COLOR_INFO}VNV post-install steps are already complete.{COLOR_RESET}")
                        elif _confirm_vnv(vnv_service.get_automation_description()):
                            if not ensure_vnv_cli_manual_downloads(vnv_service, output_callback=print):
                                print(f"{COLOR_WARNING}VNV manual downloads were not completed. Skipping VNV automation.{COLOR_RESET}")
                            else:
                                progress_callback, close_progress = create_vnv_cli_progress_callback(print)
                                try:
                                    automation_ran, vnv_error = run_vnv_automation_if_applicable(
                                        modlist_name=modlist_name_for_automation,
                                        modlist_install_location=install_path,
                                        game_root=None,  # Auto-detect from modlist structure.
                                        ttw_installer_path=AutomatedPrefixService.get_ttw_installer_path(),
                                        progress_callback=progress_callback,
                                        manual_file_callback=build_vnv_cli_manual_file_callback(vnv_service, output_callback=print),
                                        confirmation_callback=lambda _description: True,
                                    )
                                finally:
                                    close_progress()
                                if automation_ran and not vnv_error:
                                    print(f"{COLOR_INFO}VNV post-install automation completed.{COLOR_RESET}")
                                if vnv_error:
                                    print(f"{COLOR_WARNING}VNV automation encountered an error: {vnv_error}{COLOR_RESET}")
                                    print(f"{COLOR_INFO}You can complete these steps manually by following: https://vivanewvegas.moddinglinked.com/wabbajack.html{COLOR_RESET}")
                        else:
                            print(f"{COLOR_INFO}VNV automation skipped by user.{COLOR_RESET}")
                except Exception as vnv_err:
                    self.logger.error("VNV post-install automation failed: %s", vnv_err, exc_info=True)
                    print(f"{COLOR_WARNING}VNV automation could not be completed. Check logs for details.{COLOR_RESET}")
                try:
                    # Ensure CLI install flow gets the same MEW automation behavior as GUI.
                    from jackify.backend.services.mew_integration_helper import (
                        run_mew_automation_if_applicable,
                        should_offer_mew_automation,
                    )
                    from jackify.backend.services.automated_prefix_service import AutomatedPrefixService
                    from jackify.backend.services.mew_post_install_service import MEWPostInstallService
                    from jackify.backend.handlers.path_handler import PathHandler
                    from jackify.frontends.cli.commands.vnv_manual_downloads import (
                        build_vnv_cli_manual_file_callback,
                        create_vnv_cli_progress_callback,
                        ensure_vnv_cli_manual_downloads,
                    )

                    modlist_name_for_mew = self.context.get('modlist_name') or shortcut_name or ""
                    def _confirm_mew(description: str) -> bool:
                        print(f"\n{description}\n")
                        try:
                            user_input = input(f"{COLOR_PROMPT}Run MEW post-install automation now? (Y/n): {COLOR_RESET}").strip().lower()
                        except (EOFError, KeyboardInterrupt):
                            return False
                        return user_input in ("", "y", "yes")
                    install_path_mew = Path(install_dir_str)
                    if should_offer_mew_automation(modlist_name_for_mew, install_path_mew):
                        game_paths = PathHandler().find_vanilla_game_paths()
                        resolved_game_root = game_paths.get('Fallout New Vegas')
                        mew_service = MEWPostInstallService(
                            modlist_install_location=install_path_mew,
                            game_root=resolved_game_root or install_path_mew,
                            ttw_installer_path=AutomatedPrefixService.get_ttw_installer_path(),
                        )
                        completed = mew_service.check_already_completed()
                        all_mew_steps_done = (
                            completed['root_mods']
                            and completed['4gb_patch']
                            and completed['bsa_decompressed']
                            and completed['radio_fix']
                        )
                        if all_mew_steps_done:
                            print(f"{COLOR_INFO}MEW post-install steps are already complete.{COLOR_RESET}")
                        elif _confirm_mew(mew_service.get_automation_description()):
                            if not ensure_vnv_cli_manual_downloads(mew_service.fnv_tools, output_callback=print):
                                print(f"{COLOR_WARNING}MEW manual downloads were not completed. Skipping MEW automation.{COLOR_RESET}")
                            else:
                                progress_callback, close_progress = create_vnv_cli_progress_callback(print)
                                try:
                                    automation_ran, mew_error = run_mew_automation_if_applicable(
                                        modlist_name=modlist_name_for_mew,
                                        modlist_install_location=install_path_mew,
                                        game_root=None,  # Auto-detect from modlist structure.
                                        appid=str(app_id) if app_id else None,
                                        ttw_installer_path=AutomatedPrefixService.get_ttw_installer_path(),
                                        progress_callback=progress_callback,
                                        manual_file_callback=build_vnv_cli_manual_file_callback(mew_service.fnv_tools, output_callback=print),
                                        confirmation_callback=lambda _description: True,
                                    )
                                finally:
                                    close_progress()
                                if automation_ran and not mew_error:
                                    print(f"{COLOR_INFO}MEW post-install automation completed.{COLOR_RESET}")
                                if mew_error:
                                    print(f"{COLOR_WARNING}MEW automation encountered an error: {mew_error}{COLOR_RESET}")
                                    print(f"{COLOR_INFO}You can complete these steps manually by following: https://mojaveexpressguide.com/docs/Installation{COLOR_RESET}")
                        else:
                            print(f"{COLOR_INFO}MEW automation skipped by user.{COLOR_RESET}")
                except Exception as mew_err:
                    self.logger.error("MEW post-install automation failed: %s", mew_err, exc_info=True)
                    print(f"{COLOR_WARNING}MEW automation could not be completed. Check logs for details.{COLOR_RESET}")
                try:
                    # v0.4.0 contract: offer TTW flow for eligible FNV lists (e.g., Begin Again).
                    from jackify.backend.handlers.modlist_install_cli_ttw import prompt_ttw_if_eligible

                    prompt_ttw_if_eligible(
                        install_dir_str,
                        self.context.get('modlist_name') or shortcut_name or "",
                    )
                except Exception as ttw_err:
                    self.logger.error("TTW post-install prompt failed: %s", ttw_err, exc_info=True)
                    print(f"{COLOR_WARNING}TTW integration prompt failed. Check logs for details.{COLOR_RESET}")
                try:
                    from jackify.backend.handlers.modlist_fixup_handler import (
                        check_jcontainers_needs_fix,
                        apply_jcontainers_fix,
                    )
                    _jc_game_type = detected_game or self.context.get('detected_game', '')
                    needs_fix = check_jcontainers_needs_fix(Path(install_dir_str), _jc_game_type)
                    if needs_fix:
                        print(f"\n{COLOR_WARNING}JContainers Compatibility Fix{COLOR_RESET}")
                        print(f"{COLOR_INFO}The mod JContainers has been detected. The Nexusmods version is known to cause crashes on Linux/Proton.{COLOR_RESET}")
                        print(f"{COLOR_INFO}A fixed version is available from the mod's GitHub page. The original DLL will be backed up first.{COLOR_RESET}")
                        try:
                            user_input = input(f"{COLOR_PROMPT}Apply JContainers fix now? (Y/n): {COLOR_RESET}").strip().lower()
                        except (EOFError, KeyboardInterrupt):
                            user_input = "n"
                        if user_input in ("", "y", "yes"):
                            apply_jcontainers_fix(Path(install_dir_str), _jc_game_type)
                            print(f"{COLOR_INFO}JContainers fix applied.{COLOR_RESET}")
                        else:
                            print(f"{COLOR_INFO}JContainers fix skipped.{COLOR_RESET}")
                except Exception as jc_err:
                    self.logger.warning("JContainers fix check failed (non-fatal): %s", jc_err)
                try:
                    from jackify.backend.services.install_verifier_service import (
                        run_install_verification, resolve_pfx_for_appid, _load_verifier as _lv_final,
                    )
                    from jackify.frontends.cli.ui.indeterminate_status import CliIndeterminateStatus
                    import threading
                    _pfx = resolve_pfx_for_appid(str(app_id)) if app_id else None
                    if _pfx and _pfx.is_dir():
                        _vmod_final = _lv_final()
                        _norm_gt = _vmod_final.detect_game_type(Path(install_dir_str))
                        _verif_result = [None]
                        _spinner = CliIndeterminateStatus()
                        _spinner.set("Running install verification...")
                        def _verif_worker():
                            _verif_result[0] = run_install_verification(
                                _pfx,
                                Path(install_dir_str),
                                _norm_gt,
                                str(app_id) if app_id else "",
                                shortcut_name,
                            )
                        _t = threading.Thread(target=_verif_worker, daemon=True)
                        _t.start()
                        _t.join()
                        _spinner.stop()
                        r = _verif_result[0]
                        if r is not None:
                            n_pass = len(r.passes) if hasattr(r, 'passes') else 0
                            n_warn = len(r.warnings) if hasattr(r, 'warnings') else 0
                            n_fail = len(r.failures) if hasattr(r, 'failures') else 0
                            _total = n_pass + n_warn + n_fail
                            print(f"\n--- Install Verification ---")
                            print(f"  {n_pass} passed, {n_warn} warnings, {n_fail} failed (of {_total} checks)")
                            for msg in (r.failures if hasattr(r, 'failures') else []):
                                print(f"{COLOR_ERROR}  [FAIL] {msg}{COLOR_RESET}")
                            for msg in (r.warnings if hasattr(r, 'warnings') else []):
                                print(f"{COLOR_WARNING}  [WARN] {msg}{COLOR_RESET}")
                            if not n_fail and not n_warn:
                                print(f"{COLOR_SUCCESS}  All checks passed.{COLOR_RESET}")
                            print()
                except Exception as verif_err:
                    print(f"{COLOR_WARNING}[WARN] Install verifier failed: {verif_err}{COLOR_RESET}")
                    self.logger.warning("Install verification failed: %s", verif_err, exc_info=True)
                from jackify.shared.paths import get_jackify_logs_dir
                print("")
                print("")
                print("=" * 35)
                print("= Configuration phase complete =")
                print("=" * 35)
                print("")
                print("Modlist Install and Configuration complete!")
                print(f"  You should now be able to Launch '{shortcut_name}' through Steam")
                print("  Congratulations and enjoy the game!")
                print("")
                print(f"Detailed log available at: {get_jackify_logs_dir()}/Configure_New_Modlist_workflow.log")
            else:
                print(f"{COLOR_WARNING}Configuration had some issues but completed.{COLOR_RESET}")
                self.logger.warning("Post-installation configuration had issues")
        else:
            print(f"{COLOR_INFO}Modlist installation complete.{COLOR_RESET}")
            if detected_game:
                print(f"{COLOR_WARNING}Detected game '{detected_game}' is not supported for automated Steam configuration.{COLOR_RESET}")
            else:
                print(f"{COLOR_WARNING}Could not detect game type from ModOrganizer.ini for automated configuration.{COLOR_RESET}")
            print(f"{COLOR_INFO}You may need to manually configure the modlist for Steam/Proton.{COLOR_RESET}")
