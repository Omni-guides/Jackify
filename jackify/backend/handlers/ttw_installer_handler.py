"""
TTW_Linux_Installer Handler

Handles downloading, installation, and execution of TTW_Linux_Installer for TTW installations.
Replaces hoolamike for TTW-specific functionality.
"""

import logging
import os
import subprocess
import tarfile
import zipfile
from pathlib import Path
from typing import Optional, Tuple
import requests

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
TTW_INSTALLER_EXECUTABLE_NAME = "ttw_linux_gui"  # Same executable, runs in CLI mode with args

# GitHub release info
TTW_INSTALLER_REPO = "SulfurNitride/TTW_Linux_Installer"
TTW_INSTALLER_RELEASE_URL = f"https://api.github.com/repos/{TTW_INSTALLER_REPO}/releases/latest"
# Pin to 0.0.7 - last version with old format (ttw_linux_gui, universal-mpi-installer)
# Set to None to use latest release
TTW_INSTALLER_PINNED_VERSION = "0.0.7"


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
        """Check if TTW_Linux_Installer is installed at expected location.

        Checks for both old format (ttw_linux_gui) and new format (mpi_installer) executables.
        """
        
        # Check for both old (ttw_linux_gui) and new (mpi_installer) executable names
        exe_names = [TTW_INSTALLER_EXECUTABLE_NAME, "mpi_installer"]
        for exe_name in exe_names:
            potential_exe_path = self.ttw_installer_dir / exe_name
            if potential_exe_path.is_file() and os.access(potential_exe_path, os.X_OK):
                self.ttw_installer_executable_path = potential_exe_path
                self.ttw_installer_installed = True
                self.logger.info(f"Found TTW_Linux_Installer at: {self.ttw_installer_executable_path}")
                return
        
        # Not found
        self.ttw_installer_installed = False
        self.ttw_installer_executable_path = None
        self.logger.info(f"TTW_Linux_Installer not found (searched for: {', '.join(exe_names)})")

    def install_ttw_installer(self, install_dir: Optional[Path] = None) -> Tuple[bool, str]:
        """Download and install TTW_Linux_Installer from GitHub releases.
        
        Args:
            install_dir: Optional directory to install to (defaults to ~/Jackify/TTW_Linux_Installer)
            
        Returns:
            (success: bool, message: str)
        """
        try:
            target_dir = Path(install_dir) if install_dir else self.ttw_installer_dir
            target_dir.mkdir(parents=True, exist_ok=True)

            # Fetch release info - always use pinned version when set; never use latest
            if TTW_INSTALLER_PINNED_VERSION:
                tag_candidates = [
                    TTW_INSTALLER_PINNED_VERSION,
                    f"v{TTW_INSTALLER_PINNED_VERSION}" if not TTW_INSTALLER_PINNED_VERSION.startswith("v") else None,
                ]
                tag_candidates = [t for t in tag_candidates if t]
                data = None
                release_tag = None
                for tag in tag_candidates:
                    release_url = f"https://api.github.com/repos/{TTW_INSTALLER_REPO}/releases/tags/{tag}"
                    self.logger.info(f"Fetching pinned TTW_Linux_Installer version {tag} from {release_url}")
                    resp = requests.get(release_url, timeout=15, verify=True)
                    if resp.status_code == 200:
                        data = resp.json()
                        release_tag = data.get("tag_name") or data.get("name")
                        break
                    if resp.status_code != 404:
                        resp.raise_for_status()
                if not data:
                    return False, (
                        f"Pinned release {TTW_INSTALLER_PINNED_VERSION} not found on GitHub "
                        f"(tried tags: {', '.join(tag_candidates)}). Check repo and tag names."
                    )
            else:
                release_url = TTW_INSTALLER_RELEASE_URL
                self.logger.info(f"Fetching latest TTW_Linux_Installer release from {release_url}")
                resp = requests.get(release_url, timeout=15, verify=True)
                resp.raise_for_status()
                data = resp.json()
                release_tag = data.get("tag_name") or data.get("name")

            # Find Linux asset - universal-mpi-installer pattern (can be .zip or .tar.gz)
            linux_asset = None
            asset_names = [asset.get("name", "") for asset in data.get("assets", [])]
            self.logger.info(f"Available release assets: {asset_names}")
            
            for asset in data.get("assets", []):
                name = asset.get("name", "").lower()
                # Look for universal-mpi-installer pattern
                if "universal-mpi-installer" in name and name.endswith((".zip", ".tar.gz")):
                    linux_asset = asset
                    self.logger.info(f"Found Linux asset: {asset.get('name')}")
                    break

            if not linux_asset:
                all_assets = [asset.get("name", "") for asset in data.get("assets", [])]
                self.logger.error(f"No suitable Linux asset found. Available assets: {all_assets}")
                release_desc = f"release {release_tag}" if release_tag else "release"
                return False, f"No suitable Linux TTW_Linux_Installer asset found in {release_desc}. Available assets: {', '.join(all_assets)}"

            download_url = linux_asset.get("browser_download_url")
            asset_name = linux_asset.get("name")
            if not download_url or not asset_name:
                return False, f"Release {release_tag or 'unknown'} is missing required asset metadata"

            # Download to target directory
            temp_path = target_dir / asset_name
            self.logger.info(f"Downloading {asset_name} from {download_url}")
            if not self.filesystem_handler.download_file(download_url, temp_path, overwrite=True, quiet=True):
                return False, "Failed to download TTW_Linux_Installer asset"

            # Extract archive (zip or tar.gz)
            try:
                self.logger.info(f"Extracting {asset_name} to {target_dir}")
                if asset_name.lower().endswith('.tar.gz'):
                    with tarfile.open(temp_path, "r:gz") as tf:
                        tf.extractall(path=target_dir)
                elif asset_name.lower().endswith('.zip'):
                    with zipfile.ZipFile(temp_path, "r") as zf:
                        zf.extractall(path=target_dir)
                else:
                    return False, f"Unsupported archive format: {asset_name}"
            finally:
                try:
                    temp_path.unlink(missing_ok=True)  # cleanup
                except Exception:
                    pass

            # Find executable - support both old (ttw_linux_gui) and new (mpi_installer) names
            # Try old name first (since we're pinning to 0.0.7)
            exe_names = [TTW_INSTALLER_EXECUTABLE_NAME, "mpi_installer"]
            exe_path = None
            
            for exe_name in exe_names:
                potential_path = target_dir / exe_name
                if potential_path.is_file():
                    exe_path = potential_path
                    self.logger.info(f"Found executable: {exe_name}")
                    break
                # Search recursively
                for p in target_dir.rglob(exe_name):
                    if p.is_file():
                        exe_path = p
                        self.logger.info(f"Found executable: {exe_name} at {p}")
                        break
                if exe_path:
                    break

            if not exe_path or not exe_path.is_file():
                return False, f"TTW_Linux_Installer executable not found after extraction (searched for: {', '.join(exe_names)})"
            
            # Remove any other executable versions to avoid confusion
            for exe_name in exe_names:
                if exe_name != exe_path.name:
                    other_exe = target_dir / exe_name
                    if other_exe.is_file():
                        self.logger.info(f"Removing other version executable: {other_exe}")
                        try:
                            other_exe.unlink()
                        except Exception as e:
                            self.logger.warning(f"Failed to remove {other_exe}: {e}")

            # Set executable permissions
            try:
                os.chmod(exe_path, 0o755)
            except Exception as e:
                self.logger.warning(f"Failed to chmod +x on {exe_path}: {e}")

            # Update state
            self.ttw_installer_dir = target_dir
            self.ttw_installer_executable_path = exe_path
            self.ttw_installer_installed = True
            self.config_handler.set('ttw_installer_install_path', str(target_dir))
            if release_tag:
                self.config_handler.set('ttw_installer_version', release_tag)

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

    def is_ttw_installer_update_available(self) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Check if TTW_Linux_Installer update is available.
        If a version is pinned, compares against pinned version instead of latest.
        Returns (update_available, installed_version, target_version).
        """
        installed = self.get_installed_ttw_installer_version()
        
        # If we have a pinned version, compare against that instead of latest
        if TTW_INSTALLER_PINNED_VERSION:
            if not installed:
                # No version recorded - check if executable exists to infer version
                if self.ttw_installer_installed and self.ttw_installer_executable_path:
                    exe_name = self.ttw_installer_executable_path.name
                    # If pinned to 0.0.7 but found mpi_installer, it's wrong version
                    if TTW_INSTALLER_PINNED_VERSION == "0.0.7" and exe_name == "mpi_installer":
                        return (True, None, TTW_INSTALLER_PINNED_VERSION)
                    # If pinned to 0.0.7 and found ttw_linux_gui, assume correct
                    elif TTW_INSTALLER_PINNED_VERSION == "0.0.7" and exe_name == "ttw_linux_gui":
                        return (False, None, TTW_INSTALLER_PINNED_VERSION)
                # Not installed - don't show as update available
                return (False, None, TTW_INSTALLER_PINNED_VERSION)
            
            # Compare against pinned version
            if installed != TTW_INSTALLER_PINNED_VERSION:
                # Installed version doesn't match pinned - show as out of date (allows downgrade)
                return (True, installed, TTW_INSTALLER_PINNED_VERSION)
            else:
                return (False, installed, TTW_INSTALLER_PINNED_VERSION)
        
        # No pinned version - check against latest release (original behavior)
        # If executable exists but no version is recorded, don't show as "out of date"
        if not installed and self.ttw_installer_installed:
            self.logger.info("TTW_Linux_Installer executable found but no version recorded in config")
            # Don't treat as update available - just show as "Ready" (unknown version)
            return (False, None, None)
        
        try:
            resp = requests.get(TTW_INSTALLER_RELEASE_URL, timeout=10, verify=True)
            resp.raise_for_status()
            latest = resp.json().get('tag_name') or resp.json().get('name')
            if not latest:
                return (False, installed, None)
            if not installed:
                # No version recorded and executable doesn't exist; treat as not installed
                return (False, None, str(latest))
            return (installed != str(latest), installed, str(latest))
        except Exception as e:
            self.logger.warning(f"Error checking for TTW_Linux_Installer updates: {e}")
            return (False, installed, None)

