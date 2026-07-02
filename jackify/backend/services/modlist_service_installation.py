"""
Modlist installation phase for ModlistService (Mixin).

Runs engine installation only; configuration is handled separately after Steam setup.
"""

import logging
import os
import subprocess
from pathlib import Path

from ..models.modlist import ModlistContext

logger = logging.getLogger(__name__)


class ModlistServiceInstallationMixin:
    """Mixin providing install_modlist and _run_installation_only for ModlistService."""

    def install_modlist(self, context: ModlistContext,
                        progress_callback=None,
                        output_callback=None) -> bool:
        """Install a modlist (installation only, no configuration).

        Configuration must be called separately after Steam setup.
        """
        logger.info(f"Installing modlist (INSTALLATION ONLY): {context.name}")

        try:
            if not self._validate_install_context(context):
                logger.error("Invalid installation context")
                return False

            fs_handler = self._get_filesystem_handler()
            fs_handler.ensure_directory(context.install_dir)
            fs_handler.ensure_directory(context.download_dir)

            from ..core.modlist_operations import ModlistInstallCLI

            modlist_cli = ModlistInstallCLI(self.system_info)

            install_context = {
                'modlist_name': context.name,
                'install_dir': context.install_dir,
                'download_dir': context.download_dir,
                'nexus_api_key': context.nexus_api_key,
                'game_type': context.game_type,
                'modlist_value': context.modlist_value,
                'resolution': getattr(context, 'resolution', None),
                'skip_confirmation': True
            }

            original_gui_mode = os.environ.get('JACKIFY_GUI_MODE')
            os.environ['JACKIFY_GUI_MODE'] = '1'

            try:
                confirmed_context = modlist_cli.run_discovery_phase(context_override=install_context)
                if not confirmed_context:
                    logger.error("Discovery phase failed or was cancelled")
                    return False

                from ..handlers.subprocess_utils import suspend_baloo, resume_baloo
                suspend_baloo()
                try:
                    success = self._run_installation_only(
                        confirmed_context,
                        progress_callback=progress_callback,
                        output_callback=output_callback
                    )
                finally:
                    resume_baloo()

                if success:
                    logger.info("Modlist installation completed successfully (configuration done separately)")
                    return True
                logger.error("Modlist installation failed")
                return False

            finally:
                if original_gui_mode is not None:
                    os.environ['JACKIFY_GUI_MODE'] = original_gui_mode
                else:
                    os.environ.pop('JACKIFY_GUI_MODE', None)

        except Exception as e:
            error_message = str(e)
            logger.error(f"Failed to install modlist {context.name}: {error_message}")

            from .resource_manager import handle_file_descriptor_error
            try:
                if any(indicator in error_message.lower() for indicator in
                       ['too many open files', 'emfile', 'resource temporarily unavailable']):
                    result = handle_file_descriptor_error(error_message, "modlist installation")
                    if result['auto_fix_success']:
                        logger.info(f"File descriptor limit increased automatically. {result['recommendation']}")
                    elif result['error_detected']:
                        logger.warning(f"File descriptor issue detected but automatic fix failed. {result['recommendation']}")
                        if result.get('manual_instructions'):
                            distro = result['manual_instructions']['distribution']
                            logger.info(f"Manual ulimit increase instructions available for {distro} distribution")
            except Exception as resource_error:
                logger.debug(f"Error checking for resource limit issues: {resource_error}")

            return False

    def _run_installation_only(self, context, progress_callback=None, output_callback=None) -> bool:
        """Run only the installation phase using the engine."""
        from ..core.modlist_operations import get_jackify_engine_path

        try:
            install_dir_context = context['install_dir']
            if isinstance(install_dir_context, tuple):
                actual_install_path = Path(install_dir_context[0])
                if install_dir_context[1]:
                    actual_install_path.mkdir(parents=True, exist_ok=True)
            else:
                actual_install_path = Path(install_dir_context)
            install_dir_str = str(actual_install_path)

            download_dir_context = context['download_dir']
            if isinstance(download_dir_context, tuple):
                actual_download_path = Path(download_dir_context[0])
                if download_dir_context[1]:
                    actual_download_path.mkdir(parents=True, exist_ok=True)
            else:
                actual_download_path = Path(download_dir_context)
            download_dir_str = str(actual_download_path)

            from ..services.nexus_auth_service import NexusAuthService
            auth_service = NexusAuthService()
            current_api_key, current_oauth_info = auth_service.get_auth_for_engine()

            api_key = current_api_key or context.get('nexus_api_key')
            oauth_info = current_oauth_info or context.get('nexus_oauth_info')

            engine_path = get_jackify_engine_path()
            engine_dir = os.path.dirname(engine_path)
            if not os.path.isfile(engine_path) or not os.access(engine_path, os.X_OK):
                if output_callback:
                    output_callback(f"Jackify Install Engine not found or not executable at: {engine_path}")
                return False

            cmd = [engine_path, 'install', '--show-file-progress']

            modlist_value = context.get('modlist_value')
            if modlist_value and modlist_value.endswith('.wabbajack') and os.path.isfile(modlist_value):
                cmd += ['-w', modlist_value]
            elif modlist_value:
                cmd += ['-m', modlist_value]
            elif context.get('machineid'):
                cmd += ['-m', context['machineid']]
            cmd += ['-o', install_dir_str, '-d', download_dir_str]

            writeback_path = str(auth_service.get_token_writeback_path())
            env_overrides = {
                'JACKIFY_TOKEN_WRITEBACK': writeback_path,
                'DOTNET_SYSTEM_GLOBALIZATION_INVARIANT': "1",
            }
            if oauth_info:
                env_overrides['NEXUS_OAUTH_INFO'] = oauth_info
                from jackify.backend.services.nexus_oauth_service import NexusOAuthService
                env_overrides['NEXUS_OAUTH_CLIENT_ID'] = NexusOAuthService.CLIENT_ID
                if api_key:
                    env_overrides['NEXUS_API_KEY'] = api_key
            elif api_key:
                env_overrides['NEXUS_API_KEY'] = api_key

            try:
                pretty_cmd = ' '.join([f'"{arg}"' if ' ' in arg else arg for arg in cmd])
                if output_callback:
                    output_callback(f"Launching Jackify Install Engine with command: {pretty_cmd}")

                from jackify.backend.handlers.subprocess_utils import (
                    increase_file_descriptor_limit,
                    get_clean_subprocess_env,
                )
                success, old_limit, new_limit, message = increase_file_descriptor_limit()
                if output_callback:
                    if success:
                        output_callback(f"File descriptor limit: {message}")
                    else:
                        output_callback(f"File descriptor limit warning: {message}")

                clean_env = get_clean_subprocess_env(env_overrides)
                proc = subprocess.Popen(
                    cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=False, env=clean_env, cwd=engine_dir
                )

                def _write_stdin(line: str) -> bool:
                    try:
                        payload = line if line.endswith('\n') else line + '\n'
                        proc.stdin.write(payload.encode())
                        proc.stdin.flush()
                        return True
                    except (OSError, BrokenPipeError):
                        return False

                from jackify.backend.utils.cc_content_detector import is_cc_content_error, extract_cc_filename, is_creation_kit_missing_error
                import json as _json
                _cc_filename = None
                _ck_missing = False
                _pending_manual: list = []
                buffer = b''
                while True:
                    chunk = proc.stdout.read(1)
                    if not chunk:
                        break
                    buffer += chunk

                    if chunk in (b'\n', b'\r'):
                        line = buffer.decode('utf-8', errors='replace')
                        decoded = line.rstrip()
                        buffer = b''

                        # JSON engine events - handle silently, don't pass to output_callback
                        if decoded.strip().startswith('{'):
                            try:
                                obj = _json.loads(decoded.strip())
                                event = obj.get('event')
                                if event == 'manual_download_required':
                                    _pending_manual.append(obj)
                                    continue
                                if event == 'manual_download_list_complete':
                                    loop_iter = obj.get('loop_iteration', 1)
                                    for item in _pending_manual:
                                        item['loop_iteration'] = loop_iter
                                    items_batch = list(_pending_manual)
                                    _pending_manual.clear()
                                    from jackify.backend.handlers.config_handler import ConfigHandler
                                    raw_limit = ConfigHandler().get('manual_download_concurrent_limit', 2)
                                    try:
                                        manual_limit = int(raw_limit)
                                    except (TypeError, ValueError):
                                        manual_limit = 2
                                    manual_limit = max(1, min(5, manual_limit))
                                    from jackify.frontends.cli.commands.manual_download_flow import run_cli_manual_download_phase
                                    completed = run_cli_manual_download_phase(
                                        events=items_batch,
                                        loop_iteration=loop_iter,
                                        download_dir=actual_download_path,
                                        stdin_write=_write_stdin,
                                        output_callback=output_callback,
                                        concurrent_limit=manual_limit,
                                    )
                                    if not completed:
                                        if proc.poll() is None:
                                            proc.terminate()
                                        break
                                    continue
                                if event == 'manual_download_phase_complete':
                                    if output_callback:
                                        found = obj.get('total_found', 0)
                                        required = obj.get('total_required', 0)
                                        output_callback(f"All manual downloads confirmed ({found}/{required}). Resuming installation...")
                                    continue
                            except (_json.JSONDecodeError, ValueError):
                                pass

                        if output_callback:
                            output_callback(decoded)
                        if _cc_filename is None and is_cc_content_error(decoded):
                            _cc_filename = extract_cc_filename(decoded) or ""
                        if not _ck_missing and is_creation_kit_missing_error(decoded):
                            _ck_missing = True

                if buffer:
                    line = buffer.decode('utf-8', errors='replace')
                    decoded = line.rstrip()
                    if output_callback:
                        output_callback(decoded)
                    if _cc_filename is None and is_cc_content_error(decoded):
                        _cc_filename = extract_cc_filename(decoded) or ""
                    if not _ck_missing and is_creation_kit_missing_error(decoded):
                        _ck_missing = True

                proc.wait()
                auth_service.apply_token_writeback(writeback_path)
                if proc.returncode != 0:
                    if output_callback:
                        output_callback(f"Jackify Install Engine exited with code {proc.returncode}.")
                    if _cc_filename is not None and output_callback:
                        fname_note = f" ({_cc_filename})" if _cc_filename else ""
                        output_callback("")
                        output_callback(f"[WARN] Anniversary Edition Content Missing{fname_note}")
                        output_callback("  - Open Vanilla Skyrim SE/AE and let it run until all Creation Club content has downloaded.")
                        output_callback("  - From the Skyrim main menu, go into Creations and select 'Download All'.")
                        output_callback("  - If specific files are still missing, search for and download them from the Creations menu.")
                        output_callback("  - If problems persist, uninstall and reinstall Skyrim, then launch once to trigger the AE download.")
                        output_callback("  - Note: Skyrim AE via Steam Family Sharing does not transfer DLC content.")
                    if _ck_missing and output_callback:
                        _gt = context.get('game_type') or ''
                        if 'fallout4' in _gt.lower():
                            _ck_name = "Fallout 4 Creation Kit"
                            _ck_search = "Fallout 4: Creation Kit"
                        else:
                            _ck_name = "Skyrim Special Edition Creation Kit"
                            _ck_search = "Skyrim Special Edition: Creation Kit"
                        output_callback("")
                        output_callback("[WARN] Creation Kit Files Missing")
                        output_callback(f"  This modlist requires the {_ck_name}.")
                        output_callback(f"  - In Steam, search for '{_ck_search}' and install it.")
                        output_callback("  - Right-click it in Steam > Properties > Compatibility and set a Proton version.")
                        output_callback("  - Click Play to launch the Creation Kit.")
                        if 'fallout4' not in _gt.lower():
                            output_callback("  - When asked whether to unzip Scripts.zip, select NO.")
                        output_callback("  - Once the Creation Kit opens successfully, close it.")
                        output_callback("  - Re-run the modlist install in Jackify.")
                    return False
                if output_callback:
                    output_callback("Installation completed successfully")
                return True

            except Exception as e:
                error_msg = f"Error running Jackify Install Engine: {e}"
                logger.error(error_msg)
                if output_callback:
                    output_callback(error_msg)
                return False

        except Exception as e:
            error_msg = f"Error running Jackify Install Engine: {e}"
            logger.error(error_msg)
            if output_callback:
                output_callback(error_msg)
            return False
