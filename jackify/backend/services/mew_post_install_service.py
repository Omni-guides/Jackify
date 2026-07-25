"""
Mojave Express (MEW) Post-Install Service

Automates the post-installation steps documented at:
https://mojaveexpressguide.com/docs/Installation

1. Root Mods - copy files from the GOG/Steam manual-install folder to game root
2. 4GB Patcher / BSA Decompression - these are FNV-wide fixes, not MEW-specific; the same
   native Linux tools VNVPostInstallService already downloads and runs are reused here via
   composition rather than duplicated.
3. Radio Fix - runs the modlist's bundled Windows batch script under Wine. Best-effort: MEW's
   guide does not document a consequence of skipping this step (only that new radio songs
   won't play), so a failure here is reported but never blocks the rest of automation.
"""

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Callable

from .vnv_post_install_service import VNVPostInstallService
from ..handlers.subprocess_utils import get_clean_subprocess_env

logger = logging.getLogger(__name__)


class MEWPostInstallService:
    """Handles automated post-installation tasks for the Mojave Express modlist."""

    ROOT_MODS_DIR_NAME = "__GOG or STEAM ONLY Files Requiring Manual Install"
    RADIO_FIX_DIR_NAME = "__Radio Fix"
    RADIO_FIX_BAT_NAME = "Run This.bat"
    RADIO_FIX_SUCCESS_MARKER = "conversion complete"

    def __init__(self, modlist_install_location: Path, game_root: Path,
                 ttw_installer_path: Optional[Path] = None,
                 wineprefix: Optional[str] = None,
                 wine_binary: Optional[str] = None):
        """
        Args:
            modlist_install_location: Path to the MEW installation
            game_root: Path to Fallout New Vegas game root
            ttw_installer_path: Path to TTW_Linux_Installer (used for BSA decompression)
            wineprefix: WINEPREFIX for the modlist's Steam prefix (required for Radio Fix only)
            wine_binary: Path to the wine binary to use (required for Radio Fix only)
        """
        self.modlist_install = modlist_install_location
        self.game_root = game_root
        self.wineprefix = wineprefix
        self.wine_binary = wine_binary

        self.root_mods_dir = self.modlist_install / self.ROOT_MODS_DIR_NAME
        self.radio_fix_dir = self.modlist_install / self.RADIO_FIX_DIR_NAME

        # 4GB patch and BSA decompression are FNV-wide fixes with no VNV-specific logic in
        # their implementation; reuse VNVPostInstallService for these two steps (including
        # its shared download cache) instead of duplicating them.
        self.fnv_tools = VNVPostInstallService(
            modlist_install_location=modlist_install_location,
            game_root=game_root,
            ttw_installer_path=ttw_installer_path,
        )

    def should_run_automation(self, modlist_name: str) -> bool:
        """Check if this modlist should trigger MEW automation."""
        name = modlist_name.lower()
        return "mojave express" in name or name == "mew"

    def get_automation_description(self) -> str:
        return (
            "Mojave Express Automation\n\n"
            "Jackify can automatically perform the following post-install steps:\n\n"
            "1. Copy root mods to game directory\n"
            "2. Download and run Linux 4GB patcher\n"
            "3. Download and run BSA decompressor (reduces loading times)\n"
            "4. Run the Radio Fix (adds new radio songs to in-game radios)\n\n"
            "Jackify will download the required tools automatically where possible.\n"
            "If you are not a Nexus Premium member, you will be prompted to\n"
            "manually download any tools that cannot be fetched automatically.\n\n"
            "Would you like Jackify to automate these steps?"
        )

    def get_manual_download_items(self, include_bsa: bool = False) -> list:
        return self.fnv_tools.get_manual_download_items(include_bsa=include_bsa)

    def check_already_completed(self) -> dict:
        """
        Check which MEW automation steps have already been completed.

        Returns:
            Dict with keys: 'root_mods', '4gb_patch', 'bsa_decompressed', 'radio_fix'
        """
        fnv_status = self.fnv_tools.check_already_completed()
        radio_marker = self.game_root / ".jackify_mew_radio_fixed"
        return {
            'root_mods': (self.game_root / "FNVpatch.exe").exists(),
            '4gb_patch': fnv_status['4gb_patch'],
            'bsa_decompressed': fnv_status['bsa_decompressed'],
            'radio_fix': radio_marker.exists(),
        }

    def copy_root_mods(self) -> tuple[bool, str]:
        """
        Copy files from the GOG/Steam manual-install folder to game root.

        Returns:
            (success: bool, message: str)
        """
        try:
            if not self.root_mods_dir.exists():
                return False, (
                    f"Manual install directory not found: {self.root_mods_dir}. "
                    "Epic Games installs are not currently supported by this automation."
                )
            if not self.game_root.exists():
                return False, f"Game root directory not found: {self.game_root}"

            copied_files = []
            for item in self.root_mods_dir.iterdir():
                dest = self.game_root / item.name
                if item.is_file():
                    shutil.copy2(item, dest)
                    copied_files.append(item.name)
                elif item.is_dir():
                    shutil.copytree(item, dest, dirs_exist_ok=True)
                    copied_files.append(f"{item.name}/")

            if not copied_files:
                return False, "No files found to copy"

            logger.info(f"Copied {len(copied_files)} items to game root")
            return True, f"Copied {len(copied_files)} items to game root"

        except Exception as e:
            error_msg = f"Failed to copy root mods: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return False, error_msg

    def run_4gb_patcher(self, progress_callback: Optional[Callable[[str], None]] = None,
                       manual_file_callback: Optional[Callable[[str, str], Optional[Path]]] = None) -> tuple[bool, str]:
        return self.fnv_tools.run_4gb_patcher(progress_callback, manual_file_callback)

    def run_bsa_decompressor(self, progress_callback: Optional[Callable[[str], None]] = None,
                            manual_file_callback: Optional[Callable[[str, str], Optional[Path]]] = None) -> tuple[bool, str]:
        return self.fnv_tools.run_bsa_decompressor(progress_callback, manual_file_callback)

    def run_radio_fix(self, progress_callback: Optional[Callable[[str], None]] = None) -> tuple[bool, str]:
        """
        Run the bundled Radio Fix batch script under Wine.

        Non-critical step - see class docstring.

        Returns:
            (success: bool, message: str)
        """
        marker = self.game_root / ".jackify_mew_radio_fixed"
        if marker.exists():
            return True, "Radio Fix already completed"

        bat_path = self.radio_fix_dir / self.RADIO_FIX_BAT_NAME
        if not bat_path.exists():
            return False, f"Radio Fix script not found: {bat_path}"

        if not self.wine_binary or not self.wineprefix:
            return False, "Radio Fix requires a Wine prefix, but none was available"

        if progress_callback:
            progress_callback("Running Radio Fix...")

        env = get_clean_subprocess_env()
        env['WINEPREFIX'] = self.wineprefix
        env['WINEDEBUG'] = '-all'

        try:
            result = subprocess.run(
                [self.wine_binary, "cmd", "/c", self.RADIO_FIX_BAT_NAME],
                cwd=str(self.radio_fix_dir),
                env=env,
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                timeout=1800,
            )
        except subprocess.TimeoutExpired:
            return False, "Radio Fix timed out after 30 minutes"
        except Exception as e:
            error_msg = f"Failed to run Radio Fix: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return False, error_msg

        output = (result.stdout or "") + (result.stderr or "")
        if self.RADIO_FIX_SUCCESS_MARKER in output.lower():
            marker.touch()
            logger.info("Radio Fix completed successfully")
            return True, "Radio Fix completed successfully"

        logger.warning(f"Radio Fix did not report success. Output:\n{output[-2000:]}")
        return False, "Radio Fix ran but did not report success - it may need to be run manually"

    def run_all_steps(self, progress_callback: Optional[Callable[[str], None]] = None,
                      manual_file_callback: Optional[Callable[[str, str], Optional[Path]]] = None) -> tuple[bool, str]:
        """
        Run all MEW post-install steps in sequence.

        Radio Fix failure is logged and reported but does not fail the overall result.

        Returns:
            (success: bool, message: str)
        """
        def update_progress(msg: str):
            if progress_callback:
                progress_callback(msg)
            logger.info(msg)

        try:
            update_progress("Step 1/4: Copying root mods to game directory...")
            success, msg = self.copy_root_mods()
            if not success:
                return False, f"Root mods failed: {msg}"
            update_progress(f"Root mods: {msg}")

            update_progress("Step 2/4: Downloading and running 4GB patcher...")
            success, msg = self.run_4gb_patcher(update_progress, manual_file_callback)
            if not success:
                return False, f"4GB patcher failed: {msg}"
            update_progress(f"4GB patcher: {msg}")

            update_progress("Step 3/4: Downloading and running BSA decompressor...")
            success, msg = self.run_bsa_decompressor(update_progress, manual_file_callback)
            if not success:
                return False, f"BSA decompression failed: {msg}"
            update_progress(f"BSA decompression: {msg}")

            update_progress("Step 4/4: Running Radio Fix...")
            success, msg = self.run_radio_fix(update_progress)
            if success:
                update_progress(f"Radio Fix: {msg}")
            else:
                update_progress(f"Radio Fix skipped: {msg}")
                logger.warning(f"Radio Fix non-fatal failure: {msg}")

            return True, "MEW post-install completed"

        except Exception as e:
            error_msg = f"MEW post-install failed: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return False, error_msg
