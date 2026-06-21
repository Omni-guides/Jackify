"""Configure Modlist Command: CLI command for configuring a modlist post-install."""

import logging
import os
import threading
from pathlib import Path
from typing import Optional

from jackify.shared.colors import (
    COLOR_INFO,
    COLOR_ERROR,
    COLOR_WARNING,
    COLOR_PROMPT,
    COLOR_RESET,
    COLOR_SUCCESS,
)

logger = logging.getLogger(__name__)


class ConfigureModlistCommand:
    """Handler for the configure-modlist CLI command."""

    def __init__(self, backend_services):
        self.backend_services = backend_services
        self.test_mode = False

    def add_parser(self, subparsers):
        p = subparsers.add_parser(
            "configure-modlist",
            help="Configure a modlist post-install (for GUI integration)",
        )
        p.add_argument("--modlist-name", type=str, required=True,
                       help="Name of the modlist to configure (Steam shortcut name)")
        p.add_argument("--install-dir", type=str, required=True,
                       help="Install directory of the modlist")
        p.add_argument("--download-dir", type=str, help="Downloads directory (optional)")
        p.add_argument("--nexus-api-key", type=str, help="Nexus API key (optional)")
        p.add_argument("--mo2-exe-path", type=str,
                       help="Path to ModOrganizer.exe (for AppID lookup)")
        p.add_argument("--resolution", type=str, help="Resolution to set (optional)")
        p.add_argument("--skip-confirmation", action="store_true",
                       help="Skip confirmation prompts")
        return p

    def execute(self, args) -> int:
        logger.info("Starting non-interactive modlist configuration (CLI mode)")

        try:
            context = self._build_context_from_args(args)
            result = self._execute_legacy_configuration(context)

            if result is not True:
                logger.info("Finished non-interactive modlist configuration")
                return 1

            logger.info("Finished non-interactive modlist configuration")

            install_dir = context.get("install_dir", "") or ""
            modlist_name = context.get("modlist_name", "") or ""
            skip_confirm = bool(context.get("skip_confirmation", False))

            if not install_dir:
                return 0

            game_type = self._detect_game_type(install_dir)
            app_id = self._lookup_app_id(install_dir)

            self._run_post_configure_hooks(
                install_dir, modlist_name, game_type, app_id, skip_confirm
            )

            return 0

        except Exception as e:
            logger.error("Failed to configure modlist: %s", e)
            print(f"{COLOR_ERROR}Configuration failed: {e}{COLOR_RESET}")
            return 1

    # ------------------------------------------------------------------
    # Post-configure hooks (mirrors configuration_phase in install path)
    # ------------------------------------------------------------------

    def _run_post_configure_hooks(
        self,
        install_dir: str,
        modlist_name: str,
        game_type: str,
        app_id: Optional[str],
        skip_confirm: bool,
    ) -> None:
        # TTW
        try:
            from jackify.backend.handlers.modlist_install_cli_ttw import prompt_ttw_if_eligible
            prompt_ttw_if_eligible(install_dir, modlist_name)
        except Exception as e:
            logger.error("TTW post-install prompt failed: %s", e, exc_info=True)
            print(f"{COLOR_WARNING}TTW integration prompt failed. Check logs for details.{COLOR_RESET}")

        # VNV
        try:
            from jackify.backend.services.vnv_integration_helper import (
                run_vnv_automation_if_applicable,
                should_offer_vnv_automation,
            )
            if should_offer_vnv_automation(modlist_name, Path(install_dir)):
                def _confirm_vnv(description: str) -> bool:
                    print(f"\n{description}\n")
                    try:
                        ans = input(f"{COLOR_PROMPT}Run VNV post-install automation now? (Y/n): {COLOR_RESET}").strip().lower()
                    except (EOFError, KeyboardInterrupt):
                        return False
                    return ans in ("", "y", "yes")

                from jackify.backend.services.automated_prefix_service import AutomatedPrefixService
                automation_ran, vnv_error = run_vnv_automation_if_applicable(
                    modlist_name=modlist_name,
                    modlist_install_location=Path(install_dir),
                    game_root=None,
                    ttw_installer_path=AutomatedPrefixService.get_ttw_installer_path(),
                    progress_callback=print,
                    manual_file_callback=None,
                    confirmation_callback=_confirm_vnv,
                )
                if automation_ran and not vnv_error:
                    print(f"{COLOR_INFO}VNV post-install automation completed.{COLOR_RESET}")
                if vnv_error:
                    print(f"{COLOR_WARNING}VNV automation encountered an error: {vnv_error}{COLOR_RESET}")
        except Exception as e:
            logger.error("VNV post-install automation failed: %s", e, exc_info=True)
            print(f"{COLOR_WARNING}VNV automation could not be completed. Check logs for details.{COLOR_RESET}")

        # JContainers
        try:
            from jackify.backend.handlers.modlist_fixup_handler import (
                check_jcontainers_needs_fix,
                apply_jcontainers_fix,
            )
            if check_jcontainers_needs_fix(Path(install_dir), game_type):
                print(f"\n{COLOR_WARNING}JContainers Compatibility Fix{COLOR_RESET}")
                print(f"{COLOR_INFO}The mod JContainers has been detected. The Nexusmods version is known to cause crashes on Linux/Proton.{COLOR_RESET}")
                print(f"{COLOR_INFO}A fixed version is available from the mod's GitHub page. The original DLL will be backed up first.{COLOR_RESET}")
                try:
                    user_input = input(f"{COLOR_PROMPT}Apply JContainers fix now? (Y/n): {COLOR_RESET}").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    user_input = "n"
                if user_input in ("", "y", "yes"):
                    apply_jcontainers_fix(Path(install_dir), game_type)
                    print(f"{COLOR_INFO}JContainers fix applied.{COLOR_RESET}")
                else:
                    print(f"{COLOR_INFO}JContainers fix skipped.{COLOR_RESET}")
        except Exception as e:
            logger.warning("JContainers fix check failed (non-fatal): %s", e)

        # Steam artwork
        if app_id:
            try:
                from jackify.backend.handlers.modlist_handler import ModlistHandler
                ModlistHandler().set_steam_grid_images(str(app_id), install_dir, game_type=game_type)
                logger.info("Steam artwork applied for app_id %s", app_id)
            except Exception as e:
                logger.warning("Steam artwork failed: %s", e)

        # Install verification
        try:
            from jackify.backend.services.install_verifier_service import (
                run_install_verification,
                resolve_pfx_for_appid,
            )
            from jackify.frontends.cli.ui.indeterminate_status import CliIndeterminateStatus
            _pfx = resolve_pfx_for_appid(str(app_id)) if app_id else None
            if _pfx and _pfx.is_dir():
                _verif_result: list = [None]
                _spinner = CliIndeterminateStatus()
                _spinner.set("Running install verification...")

                def _verif_worker() -> None:
                    _verif_result[0] = run_install_verification(
                        _pfx,
                        Path(install_dir),
                        game_type or "",
                        str(app_id) if app_id else "",
                        modlist_name,
                    )

                t = threading.Thread(target=_verif_worker, daemon=True)
                t.start()
                t.join()
                _spinner.stop()
                r = _verif_result[0]
                if r is not None:
                    n_pass = len(r.passes) if hasattr(r, "passes") else 0
                    n_warn = len(r.warnings) if hasattr(r, "warnings") else 0
                    n_fail = len(r.failures) if hasattr(r, "failures") else 0
                    print(f"{COLOR_INFO}Install verification: {n_pass} passed, {n_warn} warnings, {n_fail} failed{COLOR_RESET}")
                    if hasattr(r, "failures"):
                        for msg in r.failures:
                            print(f"  {COLOR_WARNING}[FAIL] {msg}{COLOR_RESET}")
                    if hasattr(r, "warnings"):
                        for msg in r.warnings:
                            print(f"  {COLOR_INFO}[WARN] {msg}{COLOR_RESET}")
        except Exception as e:
            logger.warning("Install verification failed: %s", e)

        print(f"{COLOR_SUCCESS}Configuration completed successfully!{COLOR_RESET}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _detect_game_type(self, install_dir: str) -> str:
        try:
            ini = os.path.join(install_dir, "ModOrganizer.ini")
            if os.path.isfile(ini):
                from jackify.backend.handlers.modlist_handler import ModlistHandler
                handler = ModlistHandler({})
                handler.modlist_ini = ini
                handler.modlist_dir = install_dir
                if handler._detect_game_variables():
                    return handler.game_var_full or ""
        except Exception as e:
            logger.debug("Game type detection failed: %s", e)
        return ""

    def _lookup_app_id(self, install_dir: str) -> Optional[str]:
        try:
            from jackify.backend.handlers.shortcut_handler import ShortcutHandler
            from jackify.backend.services.platform_detection_service import PlatformDetectionService
            platform_service = PlatformDetectionService.get_instance()
            sh = ShortcutHandler(steamdeck=platform_service.is_steamdeck, verbose=False)
            for sc in sh.find_shortcuts_by_exe("ModOrganizer.exe"):
                if os.path.realpath(sc.get("StartDir", "")) == os.path.realpath(install_dir):
                    raw = sc.get("appid")
                    if raw is not None:
                        return str(int(raw) & 0xFFFFFFFF)
        except Exception as e:
            logger.debug("AppID lookup failed: %s", e)
        return None

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build_context_from_args(self, args) -> dict:
        return {
            "modlist_name": getattr(args, "modlist_name", None),
            "install_dir": getattr(args, "install_dir", None),
            "download_dir": getattr(args, "download_dir", None),
            "nexus_api_key": getattr(args, "nexus_api_key", os.environ.get("NEXUS_API_KEY")),
            "mo2_exe_path": getattr(args, "mo2_exe_path", None),
            "resolution": getattr(args, "resolution", None),
            "skip_confirmation": getattr(args, "skip_confirmation", False),
            "modlist_value": getattr(args, "modlist_value", None),
            "modlist_source": getattr(args, "modlist_source", None),
        }

    def _execute_legacy_configuration(self, context: dict):
        from jackify.backend.handlers.menu_handler import ModlistMenuHandler
        from jackify.backend.handlers.config_handler import ConfigHandler

        config_handler = ConfigHandler()
        modlist_menu = ModlistMenuHandler(
            config_handler=config_handler,
            test_mode=self.test_mode,
        )
        return modlist_menu._configure_new_modlist(
            default_modlist_dir=context["install_dir"],
            default_modlist_name=context["modlist_name"],
        )
