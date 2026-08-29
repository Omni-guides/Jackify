"""Update-vs-new installation detection service.

Free functions used by both GUI (install_modlist_workflow.py) and CLI
(modlist_operations.py) to avoid duplicated logic.
"""

import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def normalize_version_token(value: Optional[str]) -> Optional[str]:
    """Return a normalised version token for equality checks."""
    if value is None:
        return None
    token = str(value).strip()
    if not token:
        return None
    return token.lstrip("vV").lower()


def normalize_modlist_name(value: Optional[str]) -> str:
    """Return a case/whitespace-normalised modlist name for comparison."""
    return " ".join((value or "").strip().lower().split())


def _default_candidate_result() -> dict:
    return {
        "eligible": False,
        "reason": "unknown",
        "requested_version": None,
        "installed_version": None,
        "version_relation": "unknown",
        "installed_name": None,
    }


def compare_installed_version(
    modlist_name: str,
    install_dir: str,
    requested_version: Optional[str] = None,
) -> dict:
    """
    Version-comparison half of evaluate_update_candidate(), usable without a resolved Steam
    appid. Extracted for the Lifecycle Dashboard, which wants this comparison for every
    registered install regardless of whether it has a matched shortcut yet - see
    docs/0.8_work/modlist_lifecycle_dashboard.md section 4.
    """
    from jackify.backend.utils.modlist_meta import read_modlist_meta

    result = _default_candidate_result()

    meta = read_modlist_meta(install_dir)
    if not meta:
        result["reason"] = "missing_meta"
        return result

    installed_name = (meta.get("modlist_name") or "").strip()
    result["installed_name"] = installed_name

    if normalize_modlist_name(installed_name) != normalize_modlist_name(modlist_name):
        result["reason"] = "modlist_name_mismatch"
        return result

    installed_version = normalize_version_token(meta.get("modlist_version"))
    result["requested_version"] = requested_version
    result["installed_version"] = installed_version

    if requested_version and installed_version:
        result["version_relation"] = (
            "same" if requested_version == installed_version else "different"
        )

    result["eligible"] = True
    result["reason"] = "eligible"
    return result


def evaluate_update_candidate(
    modlist_name: str,
    install_dir: str,
    existing_appid: Optional[str],
    requested_version: Optional[str] = None,
) -> tuple[bool, dict]:
    """Decide whether update-mode should be offered.

    Args:
        modlist_name: Name of the modlist being installed.
        install_dir: Resolved installation directory path.
        existing_appid: Steam AppID from an existing shortcut (None if not found).
        requested_version: Pre-computed normalised version from the selected modlist
            (pass None when unavailable, e.g. offline/file-based installs).

    Returns:
        (eligible, result_dict) where eligible is True when update mode is safe to offer.
    """
    if not existing_appid:
        result = _default_candidate_result()
        result["reason"] = "missing_shortcut_appid"
        return False, result

    result = compare_installed_version(modlist_name, install_dir, requested_version)
    return result["eligible"], result


def find_existing_shortcut_appid(modlist_name: str, install_dir: str) -> Optional[str]:
    """Return the Steam AppID of an existing shortcut for this install, or None."""
    try:
        from jackify.backend.handlers.shortcut_handler import ShortcutHandler
        from jackify.backend.services.platform_detection_service import PlatformDetectionService

        platform_service = PlatformDetectionService.get_instance()
        shortcut_handler = ShortcutHandler(
            steamdeck=platform_service.is_steamdeck, verbose=False
        )

        install_real = os.path.realpath(install_dir)
        candidate_exes = [
            os.path.join(install_real, "ModOrganizer.exe"),
            os.path.join(install_real, "files", "ModOrganizer.exe"),
        ]

        for exe_path in candidate_exes:
            if not os.path.exists(exe_path):
                continue
            appid = shortcut_handler.get_appid_from_vdf(modlist_name, exe_path)
            if appid:
                return appid

        for shortcut in shortcut_handler.find_shortcuts_by_exe("ModOrganizer.exe"):
            if (
                (shortcut.get("AppName", "").strip() == modlist_name.strip())
                and os.path.realpath(shortcut.get("StartDir", "")) == install_real
            ):
                raw_appid = shortcut.get("appid")
                if raw_appid is not None:
                    return str(int(raw_appid) & 0xFFFFFFFF)
    except Exception as e:
        logger.warning("Update detection: failed shortcut lookup: %s", e)
    return None
