"""
MO2 Setup Service

Downloads and configures a standalone Mod Organizer 2 instance:
  - Fetches latest release from GitHub
  - Extracts with 7z
  - Creates a Steam shortcut and Proton prefix via AutomatedPrefixService
"""

import re
import logging
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable, Optional, Tuple

import requests

from jackify.backend.services.tool_registry import _find_7z_binary

logger = logging.getLogger(__name__)


def _is_dangerous_path(path: Path) -> bool:
    home = Path.home().resolve()
    dangerous = [Path('/'), Path('/home'), Path('/root'), home]
    return any(path.resolve() == d for d in dangerous)


class MO2SetupService:
    """Download, extract, and configure a standalone MO2 instance."""

    GITHUB_API = "https://api.github.com/repos/ModOrganizer2/modorganizer/releases/latest"
    ASSET_PATTERN = re.compile(r"Mod\.Organizer-\d+\.\d+(\.\d+)?\.7z$")

    def _extract_archive(
        self,
        archive_path: Path,
        install_dir: Path,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> Tuple[bool, Optional[str]]:
        """Extract the MO2 archive without interactive prompts and honor cancellation."""

        sevenzip = _find_7z_binary()
        if not sevenzip:
            return False, "7z binary not found (bundled copy missing and no system 7z/7zz on PATH)"

        process = None
        try:
            process = subprocess.Popen(
                [sevenzip, 'x', '-y', '-aoa', str(archive_path), f'-o{install_dir}'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            while True:
                if should_cancel and should_cancel():
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                    return False, "MO2 setup cancelled."

                returncode = process.poll()
                if returncode is not None:
                    stdout, stderr = process.communicate()
                    if returncode != 0:
                        err = (stderr or stdout or "").strip()
                        return False, f"Extraction failed: {err or '7z returned a non-zero exit code.'}"
                    return True, None

                time.sleep(0.1)
        except Exception as e:
            if process is not None:
                try:
                    process.kill()
                except Exception:
                    pass
            return False, f"Extraction failed: {e}"

    def setup_mo2(
        self,
        install_dir: Path,
        shortcut_name: str = "Mod Organizer 2",
        existing_appid: Optional[int] = None,
        progress_callback: Optional[Callable[[str], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> Tuple[bool, Optional[int], Optional[str]]:
        """
        Download, extract, and configure MO2.

        Returns (success, app_id, error_message).
        """

        def _progress(msg: str):
            logger.info(msg)
            if progress_callback:
                progress_callback(msg)
        
        def _cancel_requested() -> bool:
            try:
                return bool(should_cancel and should_cancel())
            except Exception:
                return False

        if not _find_7z_binary():
            return False, None, "7z binary not found (bundled copy missing and no system 7z/7zz on PATH)"

        if _is_dangerous_path(install_dir):
            return False, None, f"Refusing to install to dangerous path: {install_dir}"

        # Create directory
        try:
            install_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            return False, None, f"Could not create directory: {e}"

        # Fetch release info
        _progress("Fetching latest MO2 release info...")
        if _cancel_requested():
            return False, None, "MO2 setup cancelled."
        try:
            resp = requests.get(self.GITHUB_API, timeout=15, verify=True)
            resp.raise_for_status()
            release = resp.json()
        except Exception as e:
            return False, None, f"Failed to fetch MO2 release info: {e}"

        # Find asset
        asset = None
        for a in release.get('assets', []):
            if self.ASSET_PATTERN.match(a['name']):
                asset = a
                break
        if not asset:
            return False, None, "Could not find main MO2 .7z asset in latest release."

        # Download
        _progress(f"Downloading {asset['name']}...")
        if _cancel_requested():
            return False, None, "MO2 setup cancelled."
        try:
            with tempfile.NamedTemporaryFile(prefix="jackify-mo2-", suffix=".7z", delete=False) as tmp_file:
                archive_path = Path(tmp_file.name)
            with requests.get(asset['browser_download_url'], stream=True, timeout=120, verify=True) as r:
                r.raise_for_status()
                with open(archive_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if _cancel_requested():
                            try:
                                archive_path.unlink(missing_ok=True)
                            except Exception:
                                pass
                            return False, None, "MO2 setup cancelled."
                        f.write(chunk)
        except Exception as e:
            return False, None, f"Failed to download MO2 archive: {e}"

        # Extract
        _progress(f"Extracting to {install_dir}...")
        if _cancel_requested():
            return False, None, "MO2 setup cancelled."
        extract_ok, extract_error = self._extract_archive(archive_path, install_dir, should_cancel)
        if not extract_ok:
            try:
                archive_path.unlink(missing_ok=True)
            except Exception:
                pass
            return False, None, extract_error

        # Validate
        mo2_exe = install_dir / "ModOrganizer.exe"
        if not mo2_exe.exists():
            # MO2 release archives usually extract into a single top-level folder.
            # Limit search depth to direct children to avoid expensive recursive scans.
            mo2_exe = None
            for child in install_dir.iterdir():
                candidate = child / "ModOrganizer.exe"
                if candidate.exists():
                    mo2_exe = candidate
                    break
        if not mo2_exe:
            return False, None, "ModOrganizer.exe not found after extraction."

        # Cleanup archive
        try:
            archive_path.unlink()
        except Exception:
            pass

        _progress(f"MO2 installed at: {mo2_exe.parent}")

        # Set up Steam shortcut and Proton prefix
        _progress("Creating Steam shortcut and Proton prefix...")
        if _cancel_requested():
            return False, None, "MO2 setup cancelled."
        try:
            from .automated_prefix_service import AutomatedPrefixService
            svc = AutomatedPrefixService()
            if existing_appid is not None:
                app_id = int(existing_appid)
                _progress(f"Reusing existing Steam shortcut with AppID: {app_id}")
                prefix_path = svc.get_prefix_path(app_id)
                if prefix_path is None:
                    if not svc.create_prefix_with_proton_wrapper(app_id):
                        return False, None, "Failed to create Proton prefix for existing shortcut."
                    prefix_path = svc.get_prefix_path(app_id)
                success = True
            else:
                success, prefix_path, app_id, _last_ts = svc.run_working_workflow(
                    shortcut_name=shortcut_name,
                    modlist_install_dir=str(install_dir),
                    final_exe_path=str(mo2_exe),
                    progress_callback=_progress,
                )
        except Exception as e:
            logger.error(f"AutomatedPrefixService failed: {e}")
            return False, None, f"Prefix setup failed: {e}"

        if not success:
            return False, None, "Failed to create Steam shortcut or Proton prefix."

        _progress("MO2 setup complete.")
        return True, app_id, None
