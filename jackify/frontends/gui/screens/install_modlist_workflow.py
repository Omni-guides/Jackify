"""Installation workflow methods for InstallModlistScreen (Mixin)."""
from PySide6.QtWidgets import QMessageBox
import logging
import os
import shutil
import time

from jackify.frontends.gui.dialogs.existing_setup_dialog import prompt_existing_setup_dialog
from jackify.backend.services.update_detection import (
    evaluate_update_candidate as _svc_evaluate,
    find_existing_shortcut_appid as _svc_find_appid,
    normalize_version_token,
    normalize_modlist_name,
)
from .install_modlist_output_mixin import InstallModlistOutputMixin
from .install_modlist_workflow_execution import InstallWorkflowExecutionMixin
from .install_modlist_workflow_validation import InstallWorkflowValidationMixin

logger = logging.getLogger(__name__)


class InstallWorkflowMixin(InstallWorkflowExecutionMixin, InstallWorkflowValidationMixin, InstallModlistOutputMixin):
    """Mixin providing installation workflow methods for InstallModlistScreen."""

    # normalize_version_token and normalize_modlist_name are imported from update_detection service
    _normalize_version_token = staticmethod(normalize_version_token)
    _normalize_modlist_name = staticmethod(normalize_modlist_name)

    def _get_requested_modlist_version(self, install_mode: str) -> str | None:
        """Return selected modlist version from gallery metadata when available."""
        if install_mode != "online":
            return None
        info = getattr(self, "selected_modlist_info", None) or {}
        return normalize_version_token(info.get("version"))

    def _evaluate_update_candidate(
        self,
        modlist_name: str,
        install_dir: str,
        install_mode: str,
        existing_appid: str | None,
    ) -> tuple[bool, dict]:
        requested_version = self._get_requested_modlist_version(install_mode)
        return _svc_evaluate(modlist_name, install_dir, existing_appid, requested_version)

    def _resolve_modorganizer_ini_path(self, install_dir: str) -> str | None:
        """Return ModOrganizer.ini path for standard/special layouts."""
        candidates = [
            os.path.join(install_dir, "ModOrganizer.ini"),
            os.path.join(install_dir, "files", "ModOrganizer.ini"),
        ]
        for candidate in candidates:
            if os.path.isfile(candidate):
                return candidate
        return None

    def _capture_mo2_path_state(self, ini_path: str) -> dict[str, str]:
        """Capture path-critical keys from ModOrganizer.ini for update comparison."""
        state: dict[str, str] = {}
        section = "root"
        try:
            with open(ini_path, "r", encoding="utf-8", errors="ignore") as f:
                for raw_line in f:
                    line = raw_line.strip()
                    if not line or line.startswith(("#", ";")):
                        continue
                    if line.startswith("[") and line.endswith("]"):
                        section = line[1:-1].strip() or "root"
                        continue
                    if "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip()
                    key_lower = key.lower()
                    if (
                        key_lower in {"gamepath", "download_directory"}
                        or key_lower.startswith("binary")
                        or key_lower.startswith("workingdirectory")
                    ):
                        state[f"{section}.{key}"] = value
        except Exception as e:
            logger.warning("Failed to capture MO2 path state from %s: %s", ini_path, e)
        return state

    def _create_update_ini_backup(self, ini_path: str, label: str) -> str | None:
        """Create timestamped backup of ModOrganizer.ini for update traceability."""
        try:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            backup_path = f"{ini_path}.{label}_{timestamp}.bak"
            shutil.copy2(ini_path, backup_path)
            return backup_path
        except Exception as e:
            logger.warning("Failed to create %s backup for %s: %s", label, ini_path, e)
            return None

    def _record_pre_update_ini_snapshot(self, install_dir: str) -> None:
        """Capture pre-engine MO2 ini snapshot/backup for update-mode comparison."""
        ini_path = self._resolve_modorganizer_ini_path(install_dir)
        if not ini_path:
            self._update_pre_engine_ini_path = None
            self._update_pre_engine_ini_state = {}
            logger.warning("Update mode: ModOrganizer.ini not found before engine phase")
            return

        self._update_pre_engine_ini_path = ini_path
        self._update_pre_engine_ini_state = self._capture_mo2_path_state(ini_path)
        self._update_pre_engine_ini_backup = self._create_update_ini_backup(ini_path, "pre_update")
        logger.info(
            "Update mode: captured pre-engine MO2 state | ini=%s backup=%s keys=%d",
            ini_path,
            self._update_pre_engine_ini_backup,
            len(self._update_pre_engine_ini_state),
        )

    def _record_post_engine_ini_snapshot_and_diff(self, install_dir: str) -> None:
        """Capture post-engine MO2 snapshot and log path-key drift vs pre-engine state."""
        ini_path = self._resolve_modorganizer_ini_path(install_dir)
        if not ini_path:
            logger.warning("Update mode: ModOrganizer.ini not found after engine phase")
            return

        post_state = self._capture_mo2_path_state(ini_path)
        post_backup = self._create_update_ini_backup(ini_path, "post_engine")
        pre_state = getattr(self, "_update_pre_engine_ini_state", {}) or {}

        changed: list[str] = []
        for key in sorted(set(pre_state) | set(post_state)):
            before = pre_state.get(key)
            after = post_state.get(key)
            if before != after:
                changed.append(f"{key}: '{before}' -> '{after}'")

        self._update_ini_path_drift_detected = bool(changed)
        self._update_post_engine_ini_state = post_state
        self._update_post_engine_ini_path = ini_path
        logger.info(
            "Update mode: captured post-engine MO2 state | ini=%s backup=%s keys=%d changed=%d",
            ini_path,
            post_backup,
            len(post_state),
            len(changed),
        )
        if changed:
            logger.warning("Update mode: MO2 path-key changes detected after engine phase")
            for change in changed:
                logger.warning("Update mode INI diff | %s", change)
        else:
            logger.info("Update mode: no path-key changes detected in ModOrganizer.ini after engine phase")

    def _verify_update_ini_after_configuration(self, install_dir: str) -> None:
        """Log-only verification of path-critical ModOrganizer.ini keys after update configuration."""
        summary = self._evaluate_update_ini_verification(install_dir)
        if not summary.get("ini_found"):
            logger.warning("Update mode verify: ModOrganizer.ini not found after configuration")
            return

        logger.info(
            "Update mode verify: MO2 ini post-config summary | ini=%s critical_keys=%d empty_critical=%d changed_vs_post_engine=%d changed_vs_pre_engine=%d",
            summary["ini_path"],
            summary["critical_key_count"],
            summary["empty_critical_count"],
            summary["changed_vs_post_engine_count"],
            summary["changed_vs_pre_engine_count"],
        )
        if summary["empty_critical_keys"]:
            logger.warning("Update mode verify: empty critical MO2 keys detected")
            for key in summary["empty_critical_keys"]:
                logger.warning("Update mode verify | empty key: %s", key)

    def _evaluate_update_ini_verification(self, install_dir: str) -> dict:
        """
        Evaluate post-config MO2 path-key integrity for update-mode installs.

        Returns a summary dictionary that can be consumed by logging or tests.
        """
        ini_path = self._resolve_modorganizer_ini_path(install_dir)
        if not ini_path:
            return {
                "ini_found": False,
                "ini_path": None,
                "critical_key_count": 0,
                "empty_critical_count": 0,
                "empty_critical_keys": [],
                "changed_vs_post_engine_count": 0,
                "changed_vs_pre_engine_count": 0,
                "changed_vs_post_engine_keys": [],
                "changed_vs_pre_engine_keys": [],
            }

        final_state = self._capture_mo2_path_state(ini_path)
        pre_state = getattr(self, "_update_pre_engine_ini_state", {}) or {}
        post_engine_state = getattr(self, "_update_post_engine_ini_state", {}) or {}

        critical_items = {
            k: v
            for k, v in final_state.items()
            if (
                k.lower().endswith(".gamepath")
                or ".binary" in k.lower()
                or ".workingdirectory" in k.lower()
                or k.lower().endswith(".download_directory")
            )
        }
        empty_critical = [k for k, v in critical_items.items() if not (v or "").strip()]

        changed_vs_post_engine = [
            k
            for k in sorted(set(post_engine_state) | set(final_state))
            if post_engine_state.get(k) != final_state.get(k)
        ]
        changed_vs_pre_engine = [
            k
            for k in sorted(set(pre_state) | set(final_state))
            if pre_state.get(k) != final_state.get(k)
        ]
        return {
            "ini_found": True,
            "ini_path": ini_path,
            "critical_key_count": len(critical_items),
            "empty_critical_count": len(empty_critical),
            "empty_critical_keys": empty_critical,
            "changed_vs_post_engine_count": len(changed_vs_post_engine),
            "changed_vs_pre_engine_count": len(changed_vs_pre_engine),
            "changed_vs_post_engine_keys": changed_vs_post_engine,
            "changed_vs_pre_engine_keys": changed_vs_pre_engine,
        }

    def _find_existing_shortcut_appid(self, modlist_name: str, install_dir: str) -> str | None:
        """Return existing Steam shortcut AppID for this install dir/name when present."""
        return _svc_find_appid(modlist_name, install_dir)

    def _prompt_update_or_new_install(
        self,
        modlist_name: str,
        install_dir: str,
        update_meta: dict | None = None,
    ) -> str:
        """Prompt user when update conditions are met. Returns: 'update'|'new'|'cancel'."""
        version_note = ""
        if update_meta:
            relation = update_meta.get("version_relation")
            req = update_meta.get("requested_version")
            inst = update_meta.get("installed_version")
            if relation == "different":
                version_note = (
                    f"\n\nDetected version change: installed v{inst} -> selected v{req}."
                )
            elif relation == "same" and inst:
                version_note = (
                    f"\n\nDetected same version (v{inst}). "
                    "Use the existing setup if you are repairing or reconfiguring this install."
                )

        body = (
            "Jackify detected an existing modlist installation in the selected directory.\n\n"
            "Choose 'Use Existing Setup' to continue with the current install and Steam shortcut. "
            "Choose 'Create New Shortcut' only if you want a separate Steam entry with a different name."
            f"{version_note}"
        )

        action, new_name = prompt_existing_setup_dialog(
            self,
            window_title="Existing Modlist Setup Detected",
            heading="Use Existing Setup or Create a New Shortcut",
            body=body,
            existing_name=modlist_name,
            requested_name=modlist_name,
            install_dir=install_dir,
            field_label="New shortcut name",
            reuse_label="Use Existing Setup",
            new_label="Create New Shortcut",
            cancel_label="Cancel",
        )

        if action == "reuse":
            return "update"
        if action == "new":
            if not new_name:
                MessageBox = QMessageBox  # keep local usage explicit
                MessageBox.warning(self, "Invalid Name", "Please enter a valid shortcut name.")
                return "cancel"
            if new_name == modlist_name:
                QMessageBox.warning(self, "Same Name", "Please enter a different name to create a separate shortcut.")
                return "cancel"
            self.modlist_name_edit.setText(new_name)
            return "new"
        return "cancel"
