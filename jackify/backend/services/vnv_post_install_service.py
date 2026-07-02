"""
Viva New Vegas Post-Install Service

Automates the post-installation steps required for Viva New Vegas modlist:
1. Root Mods - Copy files from '__Files Requiring Manual Install' to game root
2. 4GB Patcher - Download Linux version from Nexus, run natively
3. BSA Decompression - Download FNV BSA Decompressor MPI, run via TTW_Linux_Installer

These steps are documented at: https://vivanewvegas.moddinglinked.com/wabbajack.html

Uses native Linux tools (no Wine required) by downloading from Nexus with OAuth.
"""

import logging
import os
import json
import shutil
import subprocess
import stat
import tempfile
import zipfile
from pathlib import Path
from typing import Optional, Callable

from ..handlers.subprocess_utils import get_clean_subprocess_env
from .nexus_download_service import NexusDownloadService
from .nexus_auth_service import NexusAuthService
from .tool_registry import _find_7z_binary

logger = logging.getLogger(__name__)


class VNVPostInstallService:
    """Handles automated post-installation tasks for Viva New Vegas modlist."""

    # Nexus mod IDs for required tools
    LINUX_4GB_PATCHER_MOD_ID = 62552
    FNV_BSA_DECOMPRESSOR_MOD_ID = 65854
    GAME_DOMAIN = "newvegas"

    def __init__(self, modlist_install_location: Path, game_root: Path,
                 ttw_installer_path: Optional[Path] = None):
        """
        Initialize VNV post-install service.

        Args:
            modlist_install_location: Path to the VNV installation (e.g., ~/VNV)
            game_root: Path to Fallout New Vegas game root
            ttw_installer_path: Path to TTW_Linux_Installer executable (for BSA decompression)
        """
        self.modlist_install = modlist_install_location
        self.game_root = game_root
        self.ttw_installer_path = ttw_installer_path

        # VNV-specific paths
        self.manual_install_dir = self.modlist_install / "__Files Requiring Manual Install"

        # Download cache directory
        from jackify.shared.paths import get_jackify_data_dir
        self.cache_dir = get_jackify_data_dir() / "vnv_post_install_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Initialize authentication
        self.auth_service = NexusAuthService()
        self.download_service = None

    def _ensure_auth(self, progress_callback: Optional[Callable[[str], None]] = None) -> bool:
        """
        Ensure we have valid Nexus authentication for downloads.

        Args:
            progress_callback: Optional callback for progress updates

        Returns:
            True if authenticated
        """
        auth_token = self.auth_service.ensure_valid_auth()

        if not auth_token:
            if progress_callback:
                progress_callback("Nexus authentication required for post-install steps")
            logger.error("No Nexus authentication available")
            return False

        self.download_service = NexusDownloadService(auth_token)
        return True

    def _ensure_download_service(self, progress_callback: Optional[Callable[[str], None]] = None) -> bool:
        if self.download_service is not None:
            return True
        return self._ensure_auth(progress_callback)

    def _find_cached_4gb_patcher(self) -> Optional[Path]:
        for path in self.cache_dir.iterdir():
            if path.is_file() and path.suffix.lower() == ".zip" and "4gb" in path.name.lower():
                return path
        for path in self.cache_dir.iterdir():
            if path.is_dir() and path.name.lower().endswith("_extracted") and "4gb" in path.name.lower():
                for child in path.iterdir():
                    if child.is_file():
                        return child
        return None

    def _find_cached_bsa_mpi(self) -> Optional[Path]:
        for path in self.cache_dir.iterdir():
            if path.is_file() and path.suffix.lower() == ".mpi" and "bsa" in path.name.lower():
                return path
        for path in self.cache_dir.iterdir():
            if path.is_dir() and path.name.lower().endswith("_extracted") and "bsa" in path.name.lower():
                for child in path.rglob("*.mpi"):
                    if child.is_file():
                        return child
        return None

    def _find_cached_bsa_package(self) -> Optional[Path]:
        preferred = []
        fallback = []
        for path in self.cache_dir.iterdir():
            if not path.is_file():
                continue
            lower = path.name.lower()
            if "bsa" not in lower or path.suffix.lower() not in {".zip", ".7z"}:
                continue
            if path.suffix.lower() == ".zip":
                preferred.append(path)
            else:
                fallback.append(path)
        candidates = sorted(preferred) or sorted(fallback)
        return candidates[0] if candidates else None

    def _extract_bsa_package(self, archive_path: Path) -> tuple[bool, Optional[Path], str]:
        extract_dir = self.cache_dir / f"{archive_path.stem}_extracted"
        mpi_path = next((p for p in extract_dir.rglob("*.mpi") if p.is_file()), None) if extract_dir.exists() else None
        if mpi_path:
            return True, mpi_path, f"Using extracted BSA package from {archive_path.name}"

        extract_dir.mkdir(parents=True, exist_ok=True)
        try:
            suffix = archive_path.suffix.lower()
            if suffix == ".zip":
                with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                    zip_ref.extractall(extract_dir)
            elif suffix == ".7z":
                sevenzip = _find_7z_binary()
                if not sevenzip:
                    return False, None, "7z binary not found (bundled copy missing and no system 7z/7zz on PATH)"
                result = subprocess.run(
                    [sevenzip, "x", "-y", f"-o{extract_dir}", str(archive_path)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if result.returncode != 0:
                    return False, None, (result.stderr or result.stdout or "7z extraction failed").strip()
            else:
                return False, None, f"Unsupported BSA package format: {archive_path.name}"
        except Exception as e:
            return False, None, str(e)

        mpi_path = next((p for p in extract_dir.rglob("*.mpi") if p.is_file()), None)
        if not mpi_path:
            return False, None, f"No .mpi file found in BSA package: {archive_path.name}"
        return True, mpi_path, f"Extracted BSA package {archive_path.name}"

    @staticmethod
    def _select_manual_download_file(files: list[dict], mod_id: int) -> Optional[dict]:
        def _active(entries: list[dict]) -> list[dict]:
            return [f for f in entries if f.get("category_name") not in ("ARCHIVED", "REMOVED")]

        active_files = _active(files)
        if mod_id == VNVPostInstallService.LINUX_4GB_PATCHER_MOD_ID:
            proton_files = [
                f for f in active_files
                if "proton" in f.get("file_name", "").lower() and f.get("file_name", "").lower().endswith(".zip")
            ]
            if proton_files:
                proton_files.sort(key=lambda f: f.get("uploaded_timestamp", 0), reverse=True)
                return proton_files[0]
        if mod_id == VNVPostInstallService.FNV_BSA_DECOMPRESSOR_MOD_ID:
            zip_files = [f for f in active_files if f.get("file_name", "").lower().endswith(".zip")]
            if zip_files:
                zip_files.sort(key=lambda f: f.get("uploaded_timestamp", 0), reverse=True)
                return zip_files[0]

        main_files = [f for f in active_files if f.get("category_name") == "MAIN"]
        if main_files:
            main_files.sort(key=lambda f: f.get("uploaded_timestamp", 0), reverse=True)
            return main_files[0]

        if active_files:
            active_files.sort(key=lambda f: f.get("uploaded_timestamp", 0), reverse=True)
            return active_files[0]
        return None

    def should_run_automation(self, modlist_name: str) -> bool:
        """
        Check if this modlist should trigger VNV automation.

        Args:
            modlist_name: Name of the installed modlist

        Returns:
            True if VNV automation should be offered
        """
        return "viva new vegas" in modlist_name.lower()

    def get_automation_description(self) -> str:
        """
        Get user-friendly description of what VNV automation does.

        Returns:
            Description string for confirmation dialog
        """
        return (
            "Viva New Vegas Automation\n\n"
            "Jackify can automatically perform the following post-install steps:\n\n"
            "1. Copy root mods to game directory\n"
            "2. Download and run Linux 4GB patcher\n"
            "3. Download and run BSA decompressor (reduces loading times)\n\n"
            "Jackify will download the required tools automatically where possible.\n"
            "If you are not a Nexus Premium member, you will be prompted to\n"
            "manually download any tools that cannot be fetched automatically.\n\n"
            "Would you like Jackify to automate these steps?"
        )

    def get_manual_download_items(self, include_bsa: bool = False) -> list:
        """
        Query Nexus for the current MAIN file of each required VNV tool and return
        a list of DownloadItem-compatible event dicts for use with ManualDownloadManager.
        Works with any Nexus auth (not Premium-only).
        Returns an empty list if auth is unavailable or queries fail.
        """
        import requests as _requests
        token = self.auth_service.get_auth_token()
        if not token:
            return []
        auth_method = self.auth_service.get_auth_method()
        headers = {"Accept": "application/json"}
        if auth_method == "oauth":
            headers["Authorization"] = f"Bearer {token}"
        else:
            headers["apikey"] = token

        tools = [(self.LINUX_4GB_PATCHER_MOD_ID, "4GB Patcher")]
        if include_bsa:
            tools.append((self.FNV_BSA_DECOMPRESSOR_MOD_ID, "BSA Decompressor"))
        items = []
        for mod_id, label in tools:
            try:
                resp = _requests.get(
                    f"https://api.nexusmods.com/v1/games/newvegas/mods/{mod_id}/files.json",
                    headers=headers, timeout=8,
                )
                resp.raise_for_status()
                files = resp.json().get("files", [])
                match = self._select_manual_download_file(files, mod_id)
                if match is None:
                    logger.warning(f"VNV tool lookup: no suitable file found for mod {mod_id} ({label})")
                    continue
                file_id = match["file_id"]
                items.append({
                    "file_name": match["file_name"],
                    "mod_name": label,
                    "nexus_url": f"https://www.nexusmods.com/newvegas/mods/{mod_id}?tab=files&file_id={file_id}",
                    "expected_hash": "",
                    "expected_size": match.get("size_kb", 0) * 1024,
                    "mod_id": mod_id,
                    "file_id": file_id,
                })
            except Exception as e:
                logger.warning(f"VNV tool lookup failed for mod {mod_id} ({label}): {e}")
        return items

    def check_already_completed(self) -> dict:
        """
        Check which VNV automation steps have already been completed.

        Returns:
            Dict with keys: 'root_mods', '4gb_patch', 'bsa_decompressed'
        """
        # Check if 4GB patch already applied
        backup_exe = self.game_root / "FalloutNV_backup.exe"
        already_patched = backup_exe.exists()

        # Check if root mods copied (look for FNVpatch.exe in game root)
        root_mods_copied = (self.game_root / "FNVpatch.exe").exists()

        # Check for BSA decompression marker file
        marker_file = self.game_root / ".jackify_bsa_decompressed"
        bsa_decompressed = marker_file.exists()

        return {
            'root_mods': root_mods_copied,
            '4gb_patch': already_patched,
            'bsa_decompressed': bsa_decompressed
        }

    def run_all_steps(self, progress_callback: Optional[Callable[[str], None]] = None,
                      manual_file_callback: Optional[Callable[[str, str], Optional[Path]]] = None,
                      skip_confirmation: bool = False) -> tuple[bool, str]:
        """
        Run all VNV post-install steps in sequence.

        Args:
            progress_callback: Optional callback for progress updates
            manual_file_callback: Optional callback for manual file selection (non-Premium users)
                                 Takes (title, instructions) returns Path or None
            skip_confirmation: Skip user confirmation (for programmatic use)

        Returns:
            (success: bool, message: str)
        """
        def update_progress(msg: str):
            if progress_callback:
                progress_callback(msg)
            logger.info(msg)

        try:
            # Step 1: Copy root mods
            update_progress("Step 1/3: Copying root mods to game directory...")
            success, msg = self.copy_root_mods()
            if not success:
                return False, f"Root mods failed: {msg}"
            update_progress(f"Root mods: {msg}")

            # Step 2: Run 4GB patcher
            update_progress("Step 2/3: Downloading and running 4GB patcher...")
            success, msg = self.run_4gb_patcher(update_progress, manual_file_callback)
            if not success:
                return False, f"4GB patcher failed: {msg}"
            update_progress(f"4GB patcher: {msg}")

            # Step 3: Run BSA decompressor
            update_progress("Step 3/3: Downloading and running BSA decompressor...")
            success, msg = self.run_bsa_decompressor(update_progress, manual_file_callback)
            if not success:
                return False, f"BSA decompression failed: {msg}"
            update_progress(f"BSA decompression: {msg}")

            return True, "VNV post-install completed successfully"

        except Exception as e:
            error_msg = f"VNV post-install failed: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return False, error_msg

    def copy_root_mods(self) -> tuple[bool, str]:
        """
        Copy files from '__Files Requiring Manual Install' to game root.

        Returns:
            (success: bool, message: str)
        """
        try:
            if not self.manual_install_dir.exists():
                return False, f"Manual install directory not found: {self.manual_install_dir}"

            if not self.game_root.exists():
                return False, f"Game root directory not found: {self.game_root}"

            # Copy all files from manual install to game root
            copied_files = []
            for item in self.manual_install_dir.iterdir():
                dest = self.game_root / item.name

                if item.is_file():
                    shutil.copy2(item, dest)
                    copied_files.append(item.name)
                    logger.debug(f"Copied: {item.name}")
                elif item.is_dir():
                    # Merge directories to preserve vanilla game files (e.g., BSA files in Data/)
                    # dirs_exist_ok=True allows adding NVSE to Data/ without deleting vanilla BSAs
                    shutil.copytree(item, dest, dirs_exist_ok=True)
                    copied_files.append(f"{item.name}/")
                    logger.debug(f"Copied directory: {item.name}/")

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
        """
        Download and run native Linux 4GB patcher.

        Args:
            progress_callback: Optional callback for progress updates
            manual_file_callback: Optional callback for manual file selection
                                 Takes (title, instructions) returns Path or None

        Returns:
            (success: bool, message: str)
        """
        try:
            # Check if already patched
            backup_exe = self.game_root / "FalloutNV_backup.exe"
            if backup_exe.exists():
                logger.info("Game already has 4GB patch (backup exists)")
                return True, "Game already patched (backup exists)"

            # Check cache first - look for extracted executable or zip
            patcher_path = self._find_cached_4gb_patcher()
            if patcher_path:
                logger.info(f"Using cached 4GB patcher: {patcher_path}")

            if not patcher_path:
                # Try to download from Nexus
                # Linux version is named "FNV4GB for Proton", not "linux"
                if not self._ensure_download_service(progress_callback):
                    return False, "Nexus authentication required to download the 4GB patcher."
                success, patcher_path, msg = self.download_service.download_latest_file(
                    self.GAME_DOMAIN,
                    self.LINUX_4GB_PATCHER_MOD_ID,
                    self.cache_dir,
                    file_name_filter="proton",
                    progress_callback=progress_callback
                )

                if not success:
                    # Download failed - offer manual download
                    logger.error(f"Automatic download failed: {msg}")
                    logger.debug(f"Looking for file with 'proton' in name on mod {self.LINUX_4GB_PATCHER_MOD_ID}")

                    if not manual_file_callback:
                        return False, f"Failed to download 4GB patcher: {msg}\n\nPlease download manually from: https://www.nexusmods.com/newvegas/mods/62552"

                    instructions = (
                        "Automatic download failed (requires Nexus Premium).\n\n"
                        "Please download the Linux 4GB Patcher manually:\n\n"
                        "1. Visit: https://www.nexusmods.com/newvegas/mods/62552\n\n"
                        "2. Download the file named 'FNV4GB for Linux'\n\n"
                        "3. Select the downloaded file below"
                    )

                    patcher_path = manual_file_callback("4GB Patcher Required", instructions)

                    if not patcher_path or not patcher_path.exists():
                        return False, "4GB patcher file not provided"

                    # Copy to cache for future use
                    cached_path = self.cache_dir / patcher_path.name
                    shutil.copy2(patcher_path, cached_path)
                    patcher_path = cached_path
                    logger.info(f"Using manually selected 4GB patcher: {patcher_path}")

            # Extract if it's a zip file and not already extracted
            if patcher_path.suffix.lower() == '.zip':
                extract_dir = self.cache_dir / f"{patcher_path.stem}_extracted"

                # Extract if not already done
                if not extract_dir.exists():
                    logger.info(f"Extracting {patcher_path.name}...")
                    extract_dir.mkdir(parents=True, exist_ok=True)
                    with zipfile.ZipFile(patcher_path, 'r') as zip_ref:
                        zip_ref.extractall(extract_dir)
                    logger.info(f"Extracted to {extract_dir}")

                # Find the executable
                executables = list(extract_dir.glob("*"))
                if not executables:
                    return False, "No files found in 4GB patcher zip"

                # Look for executable file (FalloutNVPatcher or similar)
                patcher_exe = None
                for f in executables:
                    if f.is_file() and ('fallout' in f.name.lower() or 'patcher' in f.name.lower() or 'fnv' in f.name.lower()):
                        patcher_exe = f
                        break

                if not patcher_exe:
                    # Use first file if no obvious match
                    patcher_exe = next((f for f in executables if f.is_file()), None)

                if not patcher_exe:
                    return False, "No executable found in 4GB patcher zip"

                patcher_path = patcher_exe
                logger.info(f"Using patcher executable: {patcher_path.name}")

            # Make executable
            patcher_path.chmod(patcher_path.stat().st_mode | stat.S_IEXEC)

            # Run patcher
            if progress_callback:
                progress_callback("Running 4GB patcher...")

            result = subprocess.run(
                [str(patcher_path)],
                cwd=str(self.game_root),
                capture_output=True,
                text=True,
                timeout=60
            )

            # Check if backup was created (indicates success)
            if backup_exe.exists():
                logger.info("4GB patch applied successfully")
                return True, "4GB patch applied successfully"
            else:
                logger.warning(f"Patcher output: {result.stdout}")
                if result.stderr:
                    logger.warning(f"Patcher errors: {result.stderr}")
                return False, "Patcher ran but FalloutNV_backup.exe not created"

        except subprocess.TimeoutExpired:
            return False, "4GB patcher timed out after 60 seconds"
        except Exception as e:
            error_msg = f"Failed to run 4GB patcher: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return False, error_msg

    def run_bsa_decompressor(self, progress_callback: Optional[Callable[[str], None]] = None,
                            manual_file_callback: Optional[Callable[[str, str], Optional[Path]]] = None) -> tuple[bool, str]:
        """
        Download FNV BSA Decompressor MPI and run via TTW_Linux_Installer.

        Args:
            progress_callback: Optional callback for progress updates
            manual_file_callback: Optional callback for manual file selection
                                 Takes (title, instructions) returns Path or None

        Returns:
            (success: bool, message: str)
        """
        try:
            # Check if already completed
            marker_file = self.game_root / ".jackify_bsa_decompressed"
            if marker_file.exists():
                logger.info("BSA decompression already completed (marker file exists)")
                return True, "BSA decompression already completed"

            if not self.ttw_installer_path or not self.ttw_installer_path.exists():
                from .ttw_installer_service import ensure_ttw_installer_available

                self.ttw_installer_path, message = ensure_ttw_installer_available(progress_callback)
                if not self.ttw_installer_path:
                    return False, f"TTW_Linux_Installer is required for BSA decompression: {message}"

            mpi_path = self._find_cached_bsa_mpi()
            if mpi_path:
                logger.info(f"Using cached BSA Decompressor MPI: {mpi_path}")
            else:
                package_path = self._find_cached_bsa_package()
                if not package_path:
                    if not self._ensure_download_service(progress_callback):
                        return False, "Nexus authentication required to download the BSA Decompressor."
                    success, package_path, msg = self.download_service.download_latest_file(
                        self.GAME_DOMAIN,
                        self.FNV_BSA_DECOMPRESSOR_MOD_ID,
                        self.cache_dir,
                        file_name_filter=".zip",
                        progress_callback=progress_callback
                    )
                    if not success:
                        logger.warning(f"Automatic download failed: {msg}")
                        if not manual_file_callback:
                            return False, f"Failed to download BSA Decompressor package: {msg}\n\nPlease download manually from: https://www.nexusmods.com/newvegas/mods/65854"

                        instructions = (
                            "Automatic download failed (requires Nexus Premium).\n\n"
                            "Please download the FNV BSA Decompressor package manually:\n"
                            "1. Visit: https://www.nexusmods.com/newvegas/mods/65854\n"
                            "2. Download the zip package\n"
                            "3. Select the downloaded archive below"
                        )
                        selected_path = manual_file_callback("BSA Decompressor Required", instructions)
                        if not selected_path or not selected_path.exists():
                            return False, "BSA Decompressor package not provided"
                        if selected_path.suffix.lower() not in {'.zip', '.7z', '.mpi'}:
                            return False, f"Selected file is not a supported BSA package: {selected_path}"
                        cached_path = self.cache_dir / selected_path.name
                        shutil.copy2(selected_path, cached_path)
                        package_path = cached_path
                        logger.info(f"Using manually selected BSA package: {package_path}")

                if package_path.suffix.lower() == ".mpi":
                    mpi_path = package_path
                else:
                    if progress_callback:
                        progress_callback("Preparing BSA decompressor package...")
                    success, mpi_path, msg = self._extract_bsa_package(package_path)
                    if not success or not mpi_path:
                        return False, f"Failed to prepare BSA Decompressor package: {msg}"
                    logger.info(msg)

            # Create temp output directory
            with tempfile.TemporaryDirectory() as temp_output:
                temp_output_path = Path(temp_output)

                # Create config file for TTW_Linux_Installer (handles spaces in paths better)
                config_file = self.ttw_installer_path.parent / "ttw-config.json"
                config_data = {
                    "FalloutNVRoot": str(self.game_root),
                    "MpiPackagePath": str(mpi_path),
                    "DestinationPath": str(temp_output_path)
                }
                with open(config_file, 'w') as f:
                    json.dump(config_data, f, indent=2)
                logger.debug(f"Created MPI config file: {config_file}")

                # Run via TTW_Linux_Installer
                if progress_callback:
                    progress_callback("Ensuring TTW_Linux_Installer is available...")
                    progress_callback("Running BSA decompressor...")

                cmd = [
                    str(self.ttw_installer_path),
                    "--start"
                ]

                logger.info(f"Running BSA decompressor: {' '.join(cmd)}")
                logger.debug(f"Using config file: {config_file}")
                logger.debug(f"Config: {json.dumps(config_data, indent=2)}")

                env = get_clean_subprocess_env()

                # Stream output and parse progress
                import re
                process = subprocess.Popen(
                    cmd,
                    cwd=str(self.ttw_installer_path.parent),
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1
                )

                # Pattern to match progress: "Assets processed: 12345/48649"
                progress_pattern = re.compile(r'Assets processed: (\d+)/(\d+)')
                last_progress = None

                # Capture all output for diagnostics
                all_output = []
                already_modified_detected = False

                # Stream output line by line
                for line in process.stdout:
                    line = line.rstrip()
                    all_output.append(line)

                    # Check for "already modified" messages
                    if "already" in line.lower() and ("modified" in line.lower() or "decompressed" in line.lower()):
                        already_modified_detected = True
                        logger.info(f"BSA decompressor reports: {line}")

                    # Check for progress updates
                    match = progress_pattern.search(line)
                    if match:
                        current = int(match.group(1))
                        total = int(match.group(2))
                        percent = (current / total * 100) if total > 0 else 0
                        progress_msg = f"Decompressing BSA files: {current}/{total} ({percent:.1f}%)"

                        # Only send update if progress changed significantly
                        if last_progress is None or current - last_progress >= total // 100:
                            if progress_callback:
                                progress_callback(progress_msg)
                            # Log progress updates (not every single file)
                            logger.debug(f"BSA decompression progress: {current}/{total} ({percent:.1f}%)")
                            last_progress = current

                # Wait for process to complete
                return_code = process.wait(timeout=600)

                # Log full output for debugging failures
                if return_code != 0:
                    logger.debug(f"BSA decompressor output:\n" + "\n".join(all_output[-50:]))  # Last 50 lines

                # Clean up config file after execution
                try:
                    if config_file.exists():
                        config_file.unlink()
                        logger.debug(f"Cleaned up config file: {config_file}")
                except Exception as e:
                    logger.warning(f"Failed to clean up config file: {e}")

                if return_code == 0:
                    # Check if files were actually extracted to temp directory
                    extracted_files = list(temp_output_path.rglob("*"))
                    if extracted_files:
                        logger.info(f"BSA decompression extracted {len(extracted_files)} files")
                        
                        # Copy extracted files back to game Data directory
                        data_dir = self.game_root / "Data"
                        copied_count = 0
                        for extracted_file in extracted_files:
                            if extracted_file.is_file():
                                # Preserve relative path structure
                                relative_path = extracted_file.relative_to(temp_output_path)
                                dest_file = data_dir / relative_path
                                dest_file.parent.mkdir(parents=True, exist_ok=True)
                                shutil.copy2(extracted_file, dest_file)
                                copied_count += 1
                        
                        logger.info(f"Copied {copied_count} decompressed files to {data_dir}")
                        
                        # Create marker file to indicate completion
                        marker_file = self.game_root / ".jackify_bsa_decompressed"
                        marker_file.touch()
                        logger.info("BSA decompression completed successfully")
                        return True, "BSA decompression completed successfully"
                    else:
                        # No files extracted - might be already decompressed or failed silently
                        logger.warning("BSA decompressor returned 0 but no files were extracted")
                        # Check if already decompressed by looking for marker
                        marker_file = self.game_root / ".jackify_bsa_decompressed"
                        if marker_file.exists():
                            logger.info("BSA files already decompressed (marker file exists)")
                            return True, "BSA files already decompressed"
                        else:
                            return False, "BSA decompressor completed but no files were extracted"
                else:
                    # Exit code 1 often means "already decompressed" - check output and marker
                    marker_file = self.game_root / ".jackify_bsa_decompressed"

                    # If output explicitly said "already modified/decompressed", treat as success
                    if already_modified_detected:
                        logger.info("BSA decompressor reports files already modified - marking as completed")
                        marker_file.touch()
                        return True, "BSA files already decompressed"

                    # Check marker file
                    if marker_file.exists():
                        logger.info("BSA decompressor returned error but marker file exists - assuming already completed")
                        return True, "BSA decompression already completed"

                    # Try to provide helpful error message based on exit code and output
                    logger.error(f"BSA decompressor failed with exit code {return_code}")

                    error_details = f"BSA decompressor failed with exit code {return_code}."

                    if return_code == 1:
                        error_details += (
                            "\n\nThis may indicate the BSA files are already decompressed or modified. "
                            "If you've run this before, the step may have already completed. "
                            "Otherwise, try running the decompressor manually from: "
                            "https://www.nexusmods.com/newvegas/mods/65854"
                        )
                    else:
                        error_details += (
                            f"\n\nPlease check that:\n"
                            f"1. Fallout New Vegas is properly installed at: {self.game_root}\n"
                            f"2. The BSA files exist in the Data directory\n"
                            f"3. You have write permissions to the game directory\n\n"
                            f"You can complete this step manually using the guide at:\n"
                            f"https://vivanewvegas.moddinglinked.com/wabbajack.html"
                        )

                    return False, error_details

        except subprocess.TimeoutExpired:
            return False, "BSA decompression timed out after 10 minutes"
        except Exception as e:
            error_msg = f"Failed to run BSA decompressor: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return False, error_msg
