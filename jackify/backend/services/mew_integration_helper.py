"""
MEW Integration Helper

Helper functions to integrate Mojave Express post-install automation into modlist workflows.
Mirrors vnv_integration_helper.py. Handles detection, confirmation, and execution for:
- Install Modlist
- Configure New Modlist
- Configure Existing Modlist
"""

import logging
import configparser
import re
from pathlib import Path
from typing import Optional, Callable, Tuple

from .mew_post_install_service import MEWPostInstallService

logger = logging.getLogger(__name__)


def _parse_bytearray_value(value: str) -> str:
    """Parse Qt @ByteArray format, e.g. '@ByteArray(Mojave Express)' -> 'Mojave Express'."""
    match = re.match(r'@ByteArray\((.*)\)', value)
    if match:
        return match.group(1)
    return value


def _check_modorganizer_ini_profile(modlist_install_location: Path) -> bool:
    """Check ModOrganizer.ini for a MEW profile name."""
    try:
        mo_ini_path = modlist_install_location / "ModOrganizer.ini"
        if not mo_ini_path.exists():
            logger.debug(f"ModOrganizer.ini not found at {mo_ini_path}")
            return False

        config = configparser.ConfigParser()
        config.read(mo_ini_path, encoding='utf-8-sig')

        if 'General' not in config:
            logger.debug("No [General] section in ModOrganizer.ini")
            return False

        selected_profile_raw = config.get('General', 'selected_profile', fallback='')
        if not selected_profile_raw:
            logger.debug("No selected_profile in ModOrganizer.ini")
            return False

        selected_profile = _parse_bytearray_value(selected_profile_raw).strip().lower()
        logger.debug(f"Found selected_profile: {selected_profile}")

        return selected_profile in ("mojave express", "mew")

    except Exception as e:
        logger.debug(f"Error checking ModOrganizer.ini for MEW profile: {e}")
        return False


def should_offer_mew_automation(modlist_name: str, modlist_install_location: Optional[Path] = None) -> bool:
    """
    Check if MEW automation should be offered for this modlist.

    Detection methods (in order of reliability):
    1. Check ModOrganizer.ini selected_profile (most reliable)
    2. Check modlist name for MEW patterns
    """
    if modlist_install_location:
        if _check_modorganizer_ini_profile(modlist_install_location):
            logger.info(f"MEW detected via ModOrganizer.ini profile in {modlist_install_location}")
            return True

    modlist_name_lower = modlist_name.lower()
    if "mojave express" in modlist_name_lower or modlist_name_lower == "mew":
        logger.info(f"MEW detected via name pattern in '{modlist_name}'")
        return True

    return False


def _find_wine_binary() -> Optional[str]:
    """
    Locate a wine binary from the configured Proton install.

    Same lookup ModlistWineOpsMixin._find_wine_binary_for_registry() uses; duplicated here
    (rather than instantiating that mixin's host class) since it has no other dependency.
    """
    try:
        from ..handlers.config_handler import ConfigHandler
        proton_path = ConfigHandler().get_proton_path()
        if proton_path:
            proton_path = Path(proton_path).expanduser()
            for candidate in (proton_path / "files" / "bin" / "wine", proton_path / "dist" / "bin" / "wine"):
                if candidate.is_file():
                    return str(candidate)

        from ..handlers.wine_utils import WineUtils
        best_proton = WineUtils.select_best_proton()
        if best_proton:
            return WineUtils.find_proton_binary(best_proton['name'])
    except Exception as e:
        logger.debug(f"Error finding Wine binary for MEW automation: {e}")
    return None


def run_mew_automation_if_applicable(
    modlist_name: str,
    modlist_install_location: Path,
    game_root: Optional[Path],
    appid: Optional[str] = None,
    ttw_installer_path: Optional[Path] = None,
    progress_callback: Optional[Callable[[str], None]] = None,
    manual_file_callback: Optional[Callable[[str, str], Optional[Path]]] = None,
    confirmation_callback: Optional[Callable[[str], bool]] = None
) -> Tuple[bool, Optional[str]]:
    """
    Check if MEW automation should run, get user confirmation, and execute if confirmed.

    Args:
        modlist_name: Name of the installed modlist
        modlist_install_location: Path to modlist installation
        game_root: Path to game root directory
        appid: Steam AppID for the modlist's shortcut, used to resolve the Wine prefix for
               the Radio Fix step. Radio Fix is skipped (non-fatal) if not provided.
        ttw_installer_path: Optional path to TTW_Linux_Installer (for BSA decompression)
        progress_callback: Optional callback for progress updates
        manual_file_callback: Optional callback for manual file selection (non-Premium)
        confirmation_callback: Optional callback for user confirmation

    Returns:
        Tuple of (automation_was_run: bool, error_message: Optional[str])
    """
    try:
        if not should_offer_mew_automation(modlist_name, modlist_install_location):
            logger.debug(f"Modlist '{modlist_name}' does not require MEW automation")
            return False, None

        logger.info(f"MEW detected: {modlist_name}")

        resolved_game_root = game_root
        if resolved_game_root is None:
            try:
                from jackify.backend.handlers.path_handler import PathHandler
                game_paths = PathHandler().find_vanilla_game_paths()
                resolved_game_root = game_paths.get('Fallout New Vegas')
            except Exception as detect_err:
                logger.debug(f"MEW game root auto-detection failed: {detect_err}")

        if resolved_game_root is None:
            logger.warning("MEW detected but Fallout New Vegas game root could not be resolved")
            if progress_callback:
                progress_callback("MEW automation skipped: Fallout New Vegas path not found")
            return False, None

        wineprefix = None
        wine_binary = None
        if appid:
            try:
                from ..handlers.protontricks_handler import ProtontricksHandler
                wineprefix = ProtontricksHandler(steamdeck=False).get_wine_prefix_path(appid)
            except Exception as e:
                logger.debug(f"MEW wineprefix lookup failed: {e}")
            wine_binary = _find_wine_binary()
            if not wineprefix or not wine_binary:
                logger.warning("MEW Radio Fix will be skipped: wine prefix/binary unavailable")
        else:
            logger.warning("MEW Radio Fix will be skipped: no appid provided")

        mew_service = MEWPostInstallService(
            modlist_install_location=modlist_install_location,
            game_root=resolved_game_root,
            ttw_installer_path=ttw_installer_path,
            wineprefix=wineprefix,
            wine_binary=wine_binary,
        )

        completed = mew_service.check_already_completed()
        if completed['root_mods'] and completed['4gb_patch'] and completed['bsa_decompressed'] and completed['radio_fix']:
            logger.info("MEW automation steps already completed")
            if progress_callback:
                progress_callback("MEW post-install steps already completed")
            return False, None

        if not confirmation_callback:
            logger.error("MEW automation requires confirmation_callback")
            return False, "MEW automation requires user confirmation"

        description = mew_service.get_automation_description()
        if not confirmation_callback(description):
            logger.info("User declined MEW automation")
            if progress_callback:
                progress_callback("MEW automation skipped by user")
            return False, None

        logger.info("Starting MEW post-install automation")
        if progress_callback:
            progress_callback("Running MEW post-install automation...")

        success, message = mew_service.run_all_steps(
            progress_callback=progress_callback,
            manual_file_callback=manual_file_callback
        )

        if success:
            logger.info(f"MEW automation completed: {message}")
            if progress_callback:
                progress_callback(f"MEW automation: {message}")
            return True, None
        else:
            logger.error(f"MEW automation failed: {message}")
            return True, message

    except Exception as e:
        error_msg = f"MEW automation error: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return True, error_msg
