"""Mixin that runs verify_install.py before showing the success dialog."""

import logging
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThread, Signal

logger = logging.getLogger(__name__)


class VerifierThread(QThread):
    finished = Signal(object)

    def __init__(self, pfx: Path, modlist_dir: Path, game_type: str, appid: str, modlist_name: str = "", parent=None):
        super().__init__(parent)
        self.pfx = pfx
        self.modlist_dir = modlist_dir
        self.game_type = game_type
        self.appid = appid
        self.modlist_name = modlist_name

    def run(self):
        try:
            from jackify.backend.services.install_verifier_service import run_install_verification
            results = run_install_verification(self.pfx, self.modlist_dir, self.game_type, self.appid, self.modlist_name)
        except Exception as e:
            logger.warning("Verifier thread error: %s", e)
            results = None
        self.finished.emit(results)


def _resolve_pfx_for_appid(appid: str) -> Optional[Path]:
    from jackify.backend.services.install_verifier_service import resolve_pfx_for_appid
    return resolve_pfx_for_appid(appid)


class InstallVerifierMixin:
    """Mixin: run the verifier before showing the success dialog."""

    def _get_appid_for_install_dir(self, install_dir: str) -> str:
        stored = getattr(self, "_current_appid", "") or ""
        if stored:
            return stored
        try:
            import os
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
        return ""

    def _maybe_apply_jcontainers_fix(self, install_dir: str, game_type: str) -> None:
        """Apply the JContainers Linux fix if needed, with a countdown confirmation dialog."""
        try:
            from jackify.backend.handlers.modlist_fixup_handler import (
                check_jcontainers_needs_fix,
                apply_jcontainers_fix,
            )
            needs_fix = check_jcontainers_needs_fix(Path(install_dir), game_type)
            if not needs_fix:
                return

            from jackify.frontends.gui.services.message_service import SafeMessageBox
            from PySide6.QtWidgets import QMessageBox
            dlg = SafeMessageBox(parent=self, safety_level="low")
            dlg.setup_safety_features(
                title="JContainers Compatibility Fix",
                message=(
                    "The mod JContainers has been detected. The Nexusmods version of "
                    "JContainers is known to cause crashes on Linux/Proton.\n\n"
                    "A fixed version is available from the mod's GitHub page - would you "
                    "like the fixed version to be applied now?\n\n"
                    "The original DLL will be backed up as part of the process."
                ),
                danger_action="Yes",
                safe_action="No",
                is_question=True,
            )
            result = dlg.exec()
            if result == QMessageBox.Yes:
                apply_jcontainers_fix(Path(install_dir), game_type)
                logger.info("JContainers fix applied post-configure")
        except Exception as e:
            logger.warning("JContainers fix check failed (non-fatal): %s", e)

    def _apply_problem_mods_disable(
        self, install_dir: str, game_type: str, success_params: dict, appid: str = ""
    ) -> None:
        """Disable known-problematic mods and apply prefix fixes across all profiles."""
        try:
            from jackify.backend.services.problem_mods_service import (
                disable_problem_mods,
                create_prefix_dirs,
                get_enabled_mods,
            )

            install_path = Path(install_dir)
            all_disabled: list = []
            all_enabled_mods: set = set()
            for modlist_txt in install_path.glob("profiles/*/modlist.txt"):
                disabled = disable_problem_mods(modlist_txt, game_type)
                for name in disabled:
                    if name not in all_disabled:
                        all_disabled.append(name)
                all_enabled_mods |= get_enabled_mods(modlist_txt)

            if all_disabled:
                logger.info(
                    "Disabled %d problem mod(s) for %s (%s): %s",
                    len(all_disabled),
                    success_params.get("modlist_name", ""),
                    game_type,
                    ", ".join(all_disabled),
                )
                success_params["disabled_problem_mods"] = all_disabled

            resolved_appid = str(appid or self._get_appid_for_install_dir(install_dir) or "")
            pfx = _resolve_pfx_for_appid(resolved_appid) if resolved_appid else None
            if pfx and all_enabled_mods:
                created = create_prefix_dirs(pfx, game_type, all_enabled_mods)
                if created:
                    logger.info(
                        "Created %d prefix dir(s) for %s (%s): %s",
                        len(created),
                        success_params.get("modlist_name", ""),
                        game_type,
                        ", ".join(created),
                    )
        except Exception as e:
            logger.warning("Problem mods fix check failed (non-fatal): %s", e)

    def _run_verifier_then_show_success(
        self,
        install_dir: str,
        game_type: str,
        success_params: dict,
        appid: str = "",
    ):
        """
        Show 'Verifying...' state, run the verifier in a background thread,
        then show SuccessDialog with results embedded.

        success_params keys: modlist_name, workflow_type, time_taken, game_name, enb_detected, game_type
        """
        success_params["game_type"] = game_type
        self._maybe_apply_jcontainers_fix(install_dir, game_type)
        self._apply_problem_mods_disable(install_dir, game_type, success_params, appid)
        if hasattr(self, "progress_indicator"):
            self.progress_indicator.set_status("Verifying installation...", 100)
        if hasattr(self, "file_progress_list"):
            self.file_progress_list.update_or_add_item(
                "__verifier__", "Verifying installation...", 0.0
            )

        resolved_appid = str(appid or self._get_appid_for_install_dir(install_dir) or "")
        pfx = _resolve_pfx_for_appid(resolved_appid)

        if not install_dir or pfx is None:
            logger.info(
                "Verifier skipped: pfx not found (appid=%s dir=%s)",
                resolved_appid, install_dir,
            )
            self._show_success_dialog(success_params, verification_results=None)
            return

        self._verifier_thread = VerifierThread(
            pfx=pfx,
            modlist_dir=Path(install_dir),
            game_type=game_type,
            appid=resolved_appid,
            modlist_name=success_params.get("modlist_name", ""),
            parent=self,
        )
        self._verifier_thread.finished.connect(
            lambda r: self._on_verifier_complete_show_success(r, success_params)
        )
        self._verifier_thread.start()

    def _on_verifier_complete_show_success(self, results, success_params: dict):
        if self._verifier_thread is not None:
            self._verifier_thread.wait(2000)
            self._verifier_thread.deleteLater()
            self._verifier_thread = None
        if results is not None:
            n_pass = len(results.passes)
            n_warn = len(results.warnings)
            n_fail = len(results.failures)
            logger.info(
                "Install verification: %d passed, %d warnings, %d failures",
                n_pass, n_warn, n_fail,
            )
            for msg in results.failures:
                logger.warning("Verifier FAIL: %s", msg)
            for msg in results.warnings:
                logger.info("Verifier WARN: %s", msg)
        else:
            logger.warning("Install verifier returned no results (script error)")

        self._show_success_dialog(success_params, verification_results=results)

    def _show_success_dialog(self, params: dict, verification_results=None):
        """Clear the activity window and show SuccessDialog with optional verification results."""
        if hasattr(self, "file_progress_list"):
            self.file_progress_list.clear()

        from jackify.frontends.gui.dialogs import SuccessDialog
        dlg = SuccessDialog(
            modlist_name=params["modlist_name"],
            workflow_type=params["workflow_type"],
            time_taken=params["time_taken"],
            game_name=params.get("game_name"),
            verification_results=verification_results,
            disabled_problem_mods=params.get("disabled_problem_mods"),
            readme_url=params.get("readme_url"),
            parent=self,
        )
        dlg.show()

        if params.get("enb_detected"):
            try:
                from jackify.frontends.gui.dialogs.enb_proton_dialog import ENBProtonDialog
                enb_dialog = ENBProtonDialog(modlist_name=params["modlist_name"], parent=self)
                enb_dialog.exec()
            except Exception as e:
                logger.warning("Failed to show ENB dialog: %s", e)

        try:
            from jackify.backend.data.modlist_proton_requirements import get_game_proton_warning
            _game_warning = get_game_proton_warning(params.get("game_type", ""))
            if _game_warning:
                from jackify.frontends.gui.dialogs.game_proton_warning_dialog import GameProtonWarningDialog
                game_proton_dialog = GameProtonWarningDialog(
                    modlist_name=params["modlist_name"],
                    warning=_game_warning,
                    game_label=params.get("game_name") or "this game",
                    parent=self,
                )
                game_proton_dialog.exec()
        except Exception as e:
            logger.warning("Failed to show game Proton warning dialog: %s", e)
