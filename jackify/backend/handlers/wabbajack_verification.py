"""Verification methods for InstallWabbajackHandler (Mixin)."""
import logging
import shutil
from pathlib import Path
from typing import Optional

from .status_utils import clear_status, show_status
from jackify.shared.colors import COLOR_ERROR, COLOR_INFO, COLOR_RESET

logger = logging.getLogger(__name__)


class WabbajackVerificationMixin:
    """Mixin providing verification and validation methods."""

    def _find_steam_config_vdf(self) -> Optional[Path]:
        """Finds the path to the primary Steam config.vdf file."""
        self.logger.debug("Searching for Steam config.vdf...")
        common_paths = [
            Path.home() / ".steam/steam/config/config.vdf",
            Path.home() / ".local/share/Steam/config/config.vdf",
            Path.home() / ".var/app/com.valvesoftware.Steam/.config/Valve Corporation/Steam/config/config.vdf"
        ]
        for path in common_paths:
            if path.is_file():
                self.logger.info(f"Found config.vdf at: {path}")
                return path
        self.logger.error("Could not find Steam config.vdf in common locations.")
        return None

    def _verify_manual_steps(self) -> bool:
        """
        Verifies that the user has performed the manual steps using ModlistHandler.
        Checks AppID, Proton version set, and prefix existence.

        Returns:
            bool: True if verification passes AND compatdata_path is set, False otherwise.
        """
        self.logger.info("Verifying manual Proton setup steps...")
        self.compatdata_path = None

        clear_status()
        if not self._redetect_appid():
            print(f"{COLOR_ERROR}Error: Could not find the Steam shortcut '{self.shortcut_name}' using protontricks.{COLOR_RESET}")
            print(f"{COLOR_INFO}Ensure Steam has restarted and the shortcut is visible.{COLOR_RESET}")
            return False

        self.logger.debug(f"Verification using final AppID: {self.final_appid}")

        show_status("Verifying Proton Setup")

        if not hasattr(self, 'modlist_handler') or not self.modlist_handler:
            self.logger.critical("ModlistHandler not initialized in InstallWabbajackHandler!")
            self.logger.error("Internal Error: Modlist handler not available for verification.")
            return False

        verified, status_code = self.modlist_handler.verify_proton_setup(self.final_appid)

        if not verified:
            if status_code == 'wrong_proton_version':
                proton_ver = getattr(self.modlist_handler, 'proton_ver', 'Unknown')
                print(f"{COLOR_ERROR}\nVerification Failed: Incorrect Proton version detected ('{proton_ver}'). Expected 'Proton Experimental' (or similar).{COLOR_RESET}")
                print(f"{COLOR_INFO}Please ensure you selected the correct Proton version in the shortcut's Compatibility properties.{COLOR_RESET}")
            elif status_code == 'proton_check_failed':
                print(f"{COLOR_ERROR}\nVerification Failed: Compatibility tool not detected as set for '{self.shortcut_name}' in Steam config.{COLOR_RESET}")
                print(f"{COLOR_INFO}Please ensure you forced a Proton version in the shortcut's Compatibility properties.{COLOR_RESET}")
            elif status_code == 'compatdata_missing':
                print(f"{COLOR_ERROR}\nVerification Failed: Steam compatdata directory for AppID {self.final_appid} not found.{COLOR_RESET}")
                print(f"{COLOR_INFO}Have you launched the shortcut '{self.shortcut_name}' at least once after setting Proton?{COLOR_RESET}")
            elif status_code == 'prefix_missing':
                print(f"{COLOR_ERROR}\nVerification Failed: Wine prefix directory (pfx) not found inside compatdata.{COLOR_RESET}")
                print(f"{COLOR_INFO}This usually means the shortcut hasn't been launched successfully after setting Proton.{COLOR_RESET}")
            elif status_code == 'config_vdf_missing' or status_code == 'config_vdf_error':
                print(f"{COLOR_ERROR}\nVerification Failed: Could not read or parse Steam's config.vdf file ({status_code}).{COLOR_RESET}")
                print(f"{COLOR_INFO}Check file permissions or integrity. Check logs for details.{COLOR_RESET}")
            else:
                print(f"{COLOR_ERROR}\nVerification Failed: An unexpected error occurred ({status_code}). Check logs.{COLOR_RESET}")
            return False

        self.logger.info("Basic verification checks passed. Confirming compatdata path...")

        modlist_handler_compat_path = getattr(self.modlist_handler, 'compat_data_path', None)
        if modlist_handler_compat_path:
            self.compatdata_path = modlist_handler_compat_path
            self.logger.info(f"Compatdata path obtained from ModlistHandler: {self.compatdata_path}")
        else:
            self.logger.info("ModlistHandler did not set compat_data_path. Attempting manual lookup via PathHandler.")
            if not hasattr(self, 'path_handler') or not self.path_handler:
                self.logger.critical("PathHandler not initialized in InstallWabbajackHandler!")
                self.logger.error("Internal Error: Path handler not available for verification.")
                return False

            self.compatdata_path = self.path_handler.find_compat_data(self.final_appid)
            if self.compatdata_path:
                self.logger.info(f"Manually found compatdata path via PathHandler: {self.compatdata_path}")
            else:
                self.logger.error("Verification checks passed, but COULD NOT FIND compatdata path via ModlistHandler or PathHandler.")
                print(f"\n{COLOR_ERROR}Verification Error: Basic checks passed, but failed to locate the compatdata directory for AppID {self.final_appid}.{COLOR_RESET}")
                print(f"{COLOR_INFO}This is unexpected. Check Steam filesystem structure and logs.{COLOR_RESET}")
                return False

        self.logger.info("Manual steps verification successful (including path confirmation).")
        logger.info(f"Verification successful! (AppID: {self.final_appid}, Path: {self.compatdata_path})")
        return True

    def _backup_and_replace_final_reg_files(self) -> bool:
        """Backs up current reg files and replaces them with the final downloaded versions."""
        if not self.compatdata_path:
            self.logger.error("Cannot backup/replace reg files: compatdata_path not set.")
            return False

        pfx_path = self.compatdata_path / 'pfx'
        system_reg = pfx_path / 'system.reg'
        user_reg = pfx_path / 'user.reg'
        system_reg_bak = pfx_path / 'system.reg.orig'
        user_reg_bak = pfx_path / 'user.reg.orig'

        self.logger.info("Backing up existing registry files...")
        logger.info("Backing up current registry files...")
        try:
            if system_reg.exists():
                shutil.copy2(system_reg, system_reg_bak)
                self.logger.debug(f"Backed up {system_reg} to {system_reg_bak}")
            else:
                self.logger.warning(f"Original {system_reg} not found for backup.")

            if user_reg.exists():
                shutil.copy2(user_reg, user_reg_bak)
                self.logger.debug(f"Backed up {user_reg} to {user_reg_bak}")
            else:
                self.logger.warning(f"Original {user_reg} not found for backup.")

        except Exception as e:
            self.logger.error(f"Error backing up registry files: {e}", exc_info=True)
            print(f"{COLOR_ERROR}Error backing up registry files: {e}{COLOR_RESET}")
            return False

        final_system_reg_url = "https://github.com/Omni-guides/Wabbajack-Modlist-Linux/raw/refs/heads/main/files/system.reg.github"
        final_user_reg_url = "https://github.com/Omni-guides/Wabbajack-Modlist-Linux/raw/refs/heads/main/files/user.reg.github"

        logger.info("Downloading and applying final registry settings...")
        system_ok = self._download_and_replace_reg_file(final_system_reg_url, system_reg)
        user_ok = self._download_and_replace_reg_file(final_user_reg_url, user_reg)

        if system_ok and user_ok:
            self.logger.info("Successfully applied final registry files.")
            return True
        else:
            self.logger.error("Failed to download or replace one or both final registry files.")
            self.logger.error("Failed to apply final registry settings.")
            return False
