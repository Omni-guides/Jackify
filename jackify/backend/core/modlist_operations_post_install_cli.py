"""CLI post-install workflow methods for ModlistInstallCLI (Mixin).

Covers everything that happens after the install engine exits successfully:
recording metadata, creating/reusing the Steam shortcut and Proton prefix, running
ModlistService's post-Steam configuration, and the post-configuration automation
pass (playbooks, TTW prompt, JContainers fix, problem-mod fixes, install verification).
"""
import logging
import os
import time
from pathlib import Path
from typing import Callable, Optional, Tuple

from jackify.shared.colors import (
    COLOR_PROMPT,
    COLOR_RESET,
    COLOR_INFO,
    COLOR_ERROR,
    COLOR_SUCCESS,
    COLOR_WARNING,
)

logger = logging.getLogger(__name__)


class ModlistOperationsPostInstallCLIMixin:
    """Mixin providing CLI post-install workflow methods."""

    def _finalize_successful_install(self, install_dir_str: str, download_dir_str: str, elapsed: int) -> None:
        """Record install metadata/registry/backup and set the download directory."""
        print(f"\nElapsed time: {elapsed//3600:02d}:{(elapsed%3600)//60:02d}:{elapsed%60:02d} (hh:mm:ss)\n")
        print(f"{COLOR_INFO}Your modlist has been installed to: {install_dir_str}{COLOR_RESET}\n")

        try:
            from jackify.backend.utils.modlist_meta import write_modlist_meta
            _meta_game_type = (
                self.context.get('detected_game')
                or self.context.get('game_type')
                or self.context.get('special_game_type')
            )
            write_modlist_meta(
                install_dir_str,
                self.context.get('modlist_name', ''),
                _meta_game_type,
                install_mode=self.context.get('install_mode', 'online'),
            )
            from jackify.backend.services.install_registry import register_install
            register_install(
                install_dir_str,
                self.context.get('modlist_name', ''),
                game_type=_meta_game_type,
            )
            from jackify.backend.services.profile_backup_service import backup_modlist_profiles
            backup_modlist_profiles(install_dir_str)
            from jackify import __version__ as _jackify_version
            from jackify.backend.services.jackify_db import gather_environment_fields, record_event
            record_event(
                "install_completed", "success",
                modlist_name=self.context.get('modlist_name', ''), game_type=_meta_game_type,
                install_mode=self.context.get('install_mode', 'online'),
                jackify_version=_jackify_version, duration_seconds=elapsed,
                **gather_environment_fields(),
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

    def _run_steam_configuration(
        self, install_dir_str: str, is_tuxborn: bool, gui_mode: bool
    ) -> Optional[Tuple[str, Optional[str], str, Optional[Callable]]]:
        """Create/reuse the Steam shortcut and Proton prefix for this modlist.

        Returns (shortcut_name, app_id, mo2_exe_path, progress_callback) on success,
        or None if the user cancelled or setup failed (a message has already been printed).
        """
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
                return None
            shortcut_name = raw_shortcut_name

        self.logger.debug(f"configuration_phase: Final shortcut_name: '{shortcut_name}'")

        is_gui_mode = gui_mode
        self.logger.debug(f"configuration_phase: is_gui_mode={is_gui_mode}")

        if not is_gui_mode:
            self.logger.debug("configuration_phase: Not in GUI mode, prompting user for configuration...")
            from jackify.shared.messages import STEAM_RESTART_WARNING
            print("\n" + "-" * 28)
            print(
                f"{COLOR_PROMPT}Would you like to add '{shortcut_name}' to Steam and configure it now? "
                f"{STEAM_RESTART_WARNING}{COLOR_RESET}"
            )
            configure_choice = input(f"{COLOR_PROMPT}Configure now? (Y/n): {COLOR_RESET}").strip().lower()
            self.logger.debug(f"configuration_phase: User choice: '{configure_choice}'")

            if configure_choice == 'n':
                print(f"{COLOR_INFO}Skipping Steam configuration. You can configure it later using 'Configure New Modlist'.{COLOR_RESET}")
                self.logger.debug("configuration_phase: User chose to skip Steam configuration")
                return None
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
                        return None
                    elif choice == 'skip':
                        print(f"{COLOR_INFO}Skipping Steam shortcut creation.{COLOR_RESET}")
                        success, prefix_path, app_id = True, None, None
                    else:
                        print(f"{COLOR_ERROR}Invalid choice. Cancelling.{COLOR_RESET}")
                        return None
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
                        return None
                    elif choice == 'skip':
                        print(f"{COLOR_INFO}Skipping Steam shortcut creation.{COLOR_RESET}")
                        success, prefix_path, app_id = True, None, None
                    else:
                        print(f"{COLOR_ERROR}Invalid choice. Cancelling.{COLOR_RESET}")
                        return None
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
                _game_type = (
                    self.context.get('detected_game')
                    or self.context.get('game_type')
                    or self.context.get('special_game_type')
                )
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
            return None

        return (
            shortcut_name,
            app_id,
            mo2_exe_path,
            progress_callback if 'progress_callback' in locals() and progress_callback else None,
        )

    def _run_post_configuration_automation(
        self, install_dir_str: str, shortcut_name: str, app_id: Optional[str],
        detected_game: Optional[str], modlist_context,
    ) -> None:
        """Run every post-install automation step after configure_modlist_post_steam succeeds:
        playbooks, TTW prompt, JContainers fix, problem-mod fixes, install verification."""
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
            from jackify.backend.services.playbook.hook_wiring import (
                build_gui_configuration_context, get_registry, playbooks_disabled,
            )
            from jackify.frontends.cli.commands.playbook_automation import run_playbook_automation_cli

            modlist_name_for_automation = self.context.get('modlist_name') or shortcut_name or ""
            if not playbooks_disabled():
                identity, step_ctx, install_key = build_gui_configuration_context(
                    modlist_name_for_automation, install_dir_str,
                    appid=str(app_id) if app_id else None, game_type_full=detected_game,
                )
                run_playbook_automation_cli(
                    "post_configure", get_registry(), identity, step_ctx, install_key, output=print,
                )
        except Exception as playbook_err:
            self.logger.error("Playbook automation failed: %s", playbook_err, exc_info=True)
            print(f"{COLOR_WARNING}Modlist post-install fixes could not be completed. Check logs for details.{COLOR_RESET}")
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
            from jackify.backend.services.install_verifier_service import resolve_pfx_for_appid
            from jackify.backend.services.problem_mods_service import (
                detect_game_type_from_install_dir,
                disable_problem_mods,
                create_prefix_dirs,
                get_enabled_mods,
            )
            _pm_game_type = detect_game_type_from_install_dir(install_dir_str) or detected_game or self.context.get('detected_game', '')
            _all_disabled: list = []
            _all_enabled_mods: set = set()
            for _modlist_txt in Path(install_dir_str).glob("profiles/*/modlist.txt"):
                _disabled = disable_problem_mods(_modlist_txt, _pm_game_type)
                for _name in _disabled:
                    if _name not in _all_disabled:
                        _all_disabled.append(_name)
                _all_enabled_mods |= get_enabled_mods(_modlist_txt)
            if _all_disabled:
                print(f"{COLOR_INFO}Disabled known-problematic mod(s): {', '.join(_all_disabled)}{COLOR_RESET}")
                self.logger.info(
                    "Disabled %d problem mod(s) (%s): %s",
                    len(_all_disabled), _pm_game_type, ", ".join(_all_disabled),
                )
            _pm_pfx = resolve_pfx_for_appid(str(app_id)) if app_id else None
            if _pm_pfx and _all_enabled_mods:
                _created = create_prefix_dirs(_pm_pfx, _pm_game_type, _all_enabled_mods)
                if _created:
                    self.logger.info(
                        "Created %d prefix dir(s) (%s): %s",
                        len(_created), _pm_game_type, ", ".join(_created),
                    )
        except Exception as pm_err:
            self.logger.warning("Problem mods fix check failed (non-fatal): %s", pm_err)
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
