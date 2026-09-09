"""
TTW_Linux_Installer Handler

Handles downloading, installation, and execution of TTW_Linux_Installer for TTW installations.
Replaces hoolamike for TTW-specific functionality.
"""

import logging
import os
from pathlib import Path
from typing import Optional, Tuple

from .path_handler import PathHandler
from .filesystem_handler import FileSystemHandler
from .config_handler import ConfigHandler
from .logging_handler import LoggingHandler
from .ttw_installer_backend import TTWInstallerBackendMixin

logger = logging.getLogger(__name__)

# Define default TTW_Linux_Installer paths
from jackify.shared.paths import get_jackify_data_dir
JACKIFY_BASE_DIR = get_jackify_data_dir()
DEFAULT_TTW_INSTALLER_DIR = JACKIFY_BASE_DIR / "TTW_Linux_Installer"
TTW_INSTALLER_EXECUTABLE_NAME = "mpi_installer"

# Nexus distribution info. SulfurNitride confirmed (2026-09-09) TTW_Linux_Installer is Nexus-only
# going forward - the GitHub release pipeline never reliably attached Linux assets and is retired.
# No file-name filter: the mod's actual uploaded file name is release-note-style (e.g. "Linux-
# NixOS Fixes"), not anything containing "mpi" - the mod page carries only this one Linux build,
# so "latest uploaded file" is unambiguous without filtering by name at all.
TTW_INSTALLER_NEXUS_MOD_ID = 1657
TTW_INSTALLER_NEXUS_DOMAIN = "site"
TTW_INSTALLER_NEXUS_FILE_FILTER = None

_NEXUS_MANUAL_PREFIX = "NEXUS_MANUAL_REQUIRED:"
_NEXUS_LOGIN_REQUIRED = "NEXUS_LOGIN_REQUIRED"


def describe_install_failure(message: str) -> str:
    """Turn install_ttw_installer()'s NEXUS_MANUAL_REQUIRED/NEXUS_LOGIN_REQUIRED sentinels into
    readable text for callers that cannot show the guided GUI download dialog (CLI, background
    automation). Any other failure message is returned unchanged."""
    if message == _NEXUS_LOGIN_REQUIRED:
        return (
            "You are not logged into Nexus Mods. Open Settings and connect your Nexus Mods "
            "account, then try again."
        )
    if message.startswith(_NEXUS_MANUAL_PREFIX):
        url = message[len(_NEXUS_MANUAL_PREFIX):]
        return (
            "TTW_Linux_Installer is distributed via Nexus Mods only. Without Nexus Premium, "
            f"it must be installed manually: install it via the Tools Hub, or download it "
            f"yourself from {url} and place mpi_installer in {DEFAULT_TTW_INSTALLER_DIR}."
        )
    return message


def sync_manual_install_state(install_dir: Path) -> None:
    """Point every TTWInstallerHandler instance at install_dir.

    Everything that actually runs TTW (GUI/CLI install flows, FNV/TTW automation) finds the
    binary via config, not the generic Tools Hub manifest, so a Tools Hub manual-download
    install (Nexus without Premium) needs to update the same config key install_ttw_installer()
    itself sets on success.
    """
    try:
        cfg = ConfigHandler()
        cfg.set('ttw_installer_install_path', str(install_dir))
        cfg.save_config()
    except Exception as e:
        logger.warning(f"Could not sync TTW_Linux_Installer config state: {e}")


def status_from_config() -> Tuple[bool, Optional[str], Optional[Path]]:
    """Tools Hub's TTW status check: scan the known install locations directly rather than
    trust config (which a manual-download install can leave stale) - returns
    (installed, version, executable_path)."""
    try:
        from jackify.backend.services.tool_registry import TOOLS_BASE_DIR, _read_manifest
        search_dirs = [TOOLS_BASE_DIR / "ttw_installer", DEFAULT_TTW_INSTALLER_DIR]
        for tool_dir in search_dirs:
            direct = tool_dir / TTW_INSTALLER_EXECUTABLE_NAME
            exe = direct if direct.is_file() else next(
                (p for p in tool_dir.rglob(TTW_INSTALLER_EXECUTABLE_NAME) if p.is_file()), None
            )
            if exe:
                return True, _read_manifest("ttw_installer").get("installed_version"), exe
        return False, None, None
    except Exception as e:
        logger.debug(f"TTW status check failed: {e}")
        return False, None, None


class TTWInstallerHandler(TTWInstallerBackendMixin):
    """Handles TTW installation using TTW_Linux_Installer (replaces hoolamike for TTW)."""

    def __init__(self, steamdeck: bool, verbose: bool, filesystem_handler: FileSystemHandler, 
                 config_handler: ConfigHandler, menu_handler=None):
        """Initialize the handler."""
        self.steamdeck = steamdeck
        self.verbose = verbose
        self.path_handler = PathHandler()
        self.filesystem_handler = filesystem_handler
        self.config_handler = config_handler
        self.menu_handler = menu_handler
        
        # Set up logging
        logging_handler = LoggingHandler()
        logging_handler.rotate_log_for_logger('ttw-install', 'TTW_Install_workflow.log')
        self.logger = logging_handler.setup_logger('ttw-install', 'TTW_Install_workflow.log')
        
        # Installation paths
        self.ttw_installer_dir: Path = DEFAULT_TTW_INSTALLER_DIR
        self.ttw_installer_executable_path: Optional[Path] = None
        self.ttw_installer_installed: bool = False
        
        # Load saved install path from config
        saved_path_str = self.config_handler.get('ttw_installer_install_path')
        if saved_path_str and Path(saved_path_str).is_dir():
            self.ttw_installer_dir = Path(saved_path_str)
            self.logger.info(f"Loaded TTW_Linux_Installer path from config: {self.ttw_installer_dir}")
        
        # Check if already installed
        self._check_installation()

    def _ensure_dirs_exist(self):
        """Ensure base directories exist."""
        self.ttw_installer_dir.mkdir(parents=True, exist_ok=True)

    def _check_installation(self):
        """Check if TTW_Linux_Installer is installed at expected location."""
        potential_exe_path = self.ttw_installer_dir / TTW_INSTALLER_EXECUTABLE_NAME
        if not potential_exe_path.is_file():
            # The Nexus archive nests the binary under a build-specific subfolder rather than
            # the top level the old GitHub asset used - fall back to a recursive search.
            potential_exe_path = next(
                (p for p in self.ttw_installer_dir.rglob(TTW_INSTALLER_EXECUTABLE_NAME) if p.is_file()),
                potential_exe_path,
            )
        if potential_exe_path.is_file() and os.access(potential_exe_path, os.X_OK):
            self.ttw_installer_executable_path = potential_exe_path
            self.ttw_installer_installed = True
            self.logger.info(f"Found TTW_Linux_Installer at: {self.ttw_installer_executable_path}")
            return

        # Not found
        self.ttw_installer_installed = False
        self.ttw_installer_executable_path = None
        self.logger.info(f"TTW_Linux_Installer not found (searched for: {TTW_INSTALLER_EXECUTABLE_NAME})")

    def install_ttw_installer(
        self, install_dir: Optional[Path] = None, version: Optional[str] = None
    ) -> Tuple[bool, str]:
        """Download and install TTW_Linux_Installer from Nexus Mods.

        Premium users download directly via the Nexus API; everyone else gets a
        NEXUS_MANUAL_REQUIRED sentinel, same convention every other Nexus-only Tools Hub
        entry (e.g. Radium Textures) already uses - the GUI turns that into a guided
        manual-download dialog.

        Args:
            install_dir: Optional directory to install to (defaults to ~/Jackify/TTW_Linux_Installer)
            version: Unused - Nexus has no per-version pinned download API the way GitHub
                releases did. Kept only so existing call sites don't need updating.

        Returns:
            (success: bool, message: str)
        """
        try:
            target_dir = Path(install_dir) if install_dir else self.ttw_installer_dir
            target_dir.mkdir(parents=True, exist_ok=True)

            nexus_url = f"https://www.nexusmods.com/{TTW_INSTALLER_NEXUS_DOMAIN}/mods/{TTW_INSTALLER_NEXUS_MOD_ID}"

            from jackify.backend.services.nexus_auth_service import NexusAuthService
            from jackify.backend.services.nexus_premium_service import NexusPremiumService
            from jackify.backend.services.nexus_download_service import NexusDownloadService

            auth = NexusAuthService()
            token = auth.get_auth_token()
            if not token:
                self.logger.info("No Nexus session for TTW_Linux_Installer - login required")
                return False, _NEXUS_LOGIN_REQUIRED

            is_oauth = auth.get_auth_method() == "oauth"
            is_premium, _ = NexusPremiumService().check_premium_status(token, is_oauth=is_oauth)
            if not is_premium:
                self.logger.info("Nexus Premium not available for TTW_Linux_Installer - manual download required")
                return False, f"NEXUS_MANUAL_REQUIRED:{nexus_url}"

            svc = NexusDownloadService(token, is_oauth=is_oauth)
            nexus_version = svc.get_latest_file_version(
                TTW_INSTALLER_NEXUS_DOMAIN, TTW_INSTALLER_NEXUS_MOD_ID,
                file_name_filter=TTW_INSTALLER_NEXUS_FILE_FILTER,
            )
            ok, archive_path, dl_msg = svc.download_latest_file(
                TTW_INSTALLER_NEXUS_DOMAIN, TTW_INSTALLER_NEXUS_MOD_ID, target_dir,
                file_name_filter=TTW_INSTALLER_NEXUS_FILE_FILTER,
            )
            if not ok or not archive_path:
                self.logger.error(f"Nexus download failed for TTW_Linux_Installer: {dl_msg}")
                return False, dl_msg or "Failed to download TTW_Linux_Installer from Nexus"

            # Reuse Tools Hub's archive extractor (zip/tar.gz/7z) rather than duplicating it -
            # Nexus file format isn't guaranteed the way the old GitHub asset pattern was.
            from jackify.backend.services.tool_registry import _extract_archive
            ok, err = _extract_archive(archive_path, target_dir)
            if not ok:
                return False, err

            exe_path = None
            potential_path = target_dir / TTW_INSTALLER_EXECUTABLE_NAME
            if potential_path.is_file():
                exe_path = potential_path
            else:
                for p in target_dir.rglob(TTW_INSTALLER_EXECUTABLE_NAME):
                    if p.is_file():
                        exe_path = p
                        break

            if not exe_path or not exe_path.is_file():
                return False, f"TTW_Linux_Installer executable not found after extraction (searched for: {TTW_INSTALLER_EXECUTABLE_NAME})"
            self.logger.info(f"Found executable: {exe_path}")

            # Set executable permissions
            try:
                os.chmod(exe_path, 0o755)
            except Exception as e:
                self.logger.warning(f"Failed to chmod +x on {exe_path}: {e}")

            # Update state. The Nexus archive bundles both the Linux and Windows builds in
            # sibling subfolders (unlike the old GitHub asset, which was Linux-only at the top
            # level), so the executable's own directory - not the extraction root - is what
            # every consumer (this class's own _check_installation, and Tools Hub's status
            # check) actually looks in.
            self.ttw_installer_dir = exe_path.parent
            self.ttw_installer_executable_path = exe_path
            self.ttw_installer_installed = True
            self.config_handler.set('ttw_installer_install_path', str(exe_path.parent))
            if nexus_version:
                self.config_handler.set('ttw_installer_version', nexus_version)
            try:
                self.config_handler.save_config()
            except Exception as e:
                self.logger.warning(f"Could not persist TTW_Linux_Installer config state: {e}")

            self.logger.info(f"TTW_Linux_Installer installed successfully at {exe_path}")
            return True, f"TTW_Linux_Installer installed at {target_dir}"

        except Exception as e:
            self.logger.error(f"Error installing TTW_Linux_Installer: {e}", exc_info=True)
            return False, f"Error installing TTW_Linux_Installer: {e}"

    def get_installed_ttw_installer_version(self) -> Optional[str]:
        """Return the installed TTW_Linux_Installer version stored in Jackify config, if any."""
        try:
            v = self.config_handler.get('ttw_installer_version')
            return str(v) if v else None
        except Exception:
            return None

