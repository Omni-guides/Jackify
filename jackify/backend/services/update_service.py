"""
Update service for checking and applying Jackify updates.

This service handles checking for updates via GitHub releases API
and coordinating the update process.
"""

import logging
import os
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Callable
import requests

from ...shared.appimage_utils import get_appimage_path, is_appimage, can_self_update


logger = logging.getLogger(__name__)


@dataclass
class UpdateInfo:
    """Information about an available update."""
    version: str
    tag_name: str
    release_date: str
    changelog: str
    download_url: str
    source: str = "github"
    file_size: Optional[int] = None
    is_critical: bool = False
    is_delta_update: bool = False
    github_download_url: Optional[str] = None


class UpdateService:
    """Service for checking and applying Jackify updates."""
    
    def __init__(self, current_version: str):
        """
        Initialize the update service.
        
        Args:
            current_version: Current version of Jackify (e.g. "0.1.1")
        """
        self.current_version = current_version
        self.github_repo = "Omni-guides/Jackify"
        self.github_api_base = "https://api.github.com"
        self.update_check_timeout = 10  # seconds

    def check_for_updates(self) -> Optional[UpdateInfo]:
        """Check for available updates via GitHub releases API.

        Returns UpdateInfo if an update is available, None otherwise.
        """
        try:
            url = f"{self.github_api_base}/repos/{self.github_repo}/releases/latest"
            headers = {
                'Accept': 'application/vnd.github.v3+json',
                'User-Agent': f'Jackify/{self.current_version}'
            }
            token = os.environ.get('GITHUB_TOKEN')
            if token:
                headers['Authorization'] = f'Bearer {token}'

            logger.debug(f"Checking for updates at {url}")
            response = requests.get(url, headers=headers, timeout=self.update_check_timeout)
            if response.status_code == 403:
                logger.debug("GitHub API rate limit reached (403) - update check skipped")
                return None
            response.raise_for_status()
            
            release_data = response.json()
            latest_version = release_data['tag_name'].lstrip('v')
            
            if self._is_newer_version(latest_version):
                # Check if this version was skipped
                if self._is_version_skipped(latest_version):
                    logger.debug(f"Version {latest_version} was skipped by user")
                    return None
                
                # Find AppImage asset (prefer delta update if available)
                download_url = None
                file_size = None
                
                # Look for delta update first (smaller download)
                for asset in release_data.get('assets', []):
                    if asset['name'].endswith('.AppImage.delta') or 'delta' in asset['name'].lower():
                        download_url = asset['browser_download_url']
                        file_size = asset['size']
                        logger.debug(f"Found delta update: {asset['name']} ({file_size} bytes)")
                        break
                
                # Fallback to full AppImage if no delta available
                if not download_url:
                    for asset in release_data.get('assets', []):
                        if asset['name'].endswith('.AppImage'):
                            download_url = asset['browser_download_url']
                            file_size = asset['size']
                            logger.debug(f"Found full AppImage: {asset['name']} ({file_size} bytes)")
                            break
                
                if download_url:
                    github_url = download_url
                    nexus_url = self._try_nexus_download_url(latest_version)
                    update_source = "github"
                    if nexus_url:
                        download_url = nexus_url
                        update_source = "nexus"
                        logger.info("Update source: Nexus CDN (version %s)", latest_version)
                    else:
                        logger.info("Update source: GitHub Releases (version %s)", latest_version)

                    is_delta = '.delta' in download_url or 'delta' in download_url.lower()

                    try:
                        safe_version = str(latest_version) if latest_version else ""
                        safe_tag = str(release_data.get('tag_name', ''))
                        safe_date = str(release_data.get('published_at', ''))
                        safe_changelog = str(release_data.get('body', ''))[:1000]
                        safe_url = str(download_url)

                        logger.debug(f"Creating UpdateInfo for version {safe_version}")

                        update_info = UpdateInfo(
                            version=safe_version,
                            tag_name=safe_tag,
                            release_date=safe_date,
                            changelog=safe_changelog,
                            download_url=safe_url,
                            file_size=file_size,
                            is_delta_update=is_delta,
                            source=update_source,
                            github_download_url=str(github_url),
                        )
                        
                        logger.debug(f"UpdateInfo created successfully")
                        return update_info
                        
                    except Exception as e:
                        logger.error(f"Failed to create UpdateInfo: {e}")
                        return None
                else:
                    logger.warning(f"No AppImage found in release {latest_version}")
            
            return None
            
        except requests.RequestException as e:
            logger.error(f"Failed to check for updates: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error checking for updates: {e}")
            return None
    
    _NEXUS_MOD_ID = 1427

    def _try_nexus_download_url(self, target_version: str) -> Optional[str]:
        """
        If the user is Nexus Premium, query the Nexus files list for the mod
        and return a CDN download URL for the file matching target_version.
        Returns None on any failure or if the version is not yet on Nexus.
        """
        try:
            from jackify.backend.handlers.config_handler import ConfigHandler
            if ConfigHandler().get('force_github_updates', False):
                logger.info("Nexus update source bypassed: force_github_updates is enabled")
                return None
        except Exception:
            pass
        try:
            from jackify.backend.services.nexus_auth_service import NexusAuthService
            auth_service = NexusAuthService()
            token = auth_service.get_auth_token()
            if not token:
                logger.info("Nexus update lookup skipped: no auth token")
                return None
            auth_method = auth_service.get_auth_method()
            is_oauth = auth_method == "oauth"

            from jackify.backend.services.nexus_premium_service import NexusPremiumService
            is_premium, _ = NexusPremiumService().check_premium_status(token, is_oauth=is_oauth)
            if not is_premium:
                logger.info("Nexus update lookup skipped: not Premium")
                return None

            auth_headers = {"Accept": "application/json"}
            if is_oauth:
                auth_headers["Authorization"] = f"Bearer {token}"
            else:
                auth_headers["apikey"] = token

            files_url = f"https://api.nexusmods.com/v1/games/site/mods/{self._NEXUS_MOD_ID}/files.json"
            resp = requests.get(files_url, headers=auth_headers, timeout=8)
            resp.raise_for_status()
            files = resp.json().get("files", [])

            # Prefer MAIN category; accept any non-archived/removed file matching the version.
            match = None
            for f in files:
                if f.get("version") != target_version:
                    continue
                if f.get("category_name") == "MAIN":
                    match = f
                    break
                if f.get("category_name") not in ("ARCHIVED", "REMOVED"):
                    match = match or f

            if match is None:
                logger.info("Nexus update lookup: version %s not found on Nexus", target_version)
                return None

            nexus_file_id = match["file_id"]
            dl_url = f"https://api.nexusmods.com/v1/games/site/mods/{self._NEXUS_MOD_ID}/files/{nexus_file_id}/download_link.json"
            resp = requests.get(dl_url, headers=auth_headers, timeout=8)
            resp.raise_for_status()
            links = resp.json()
            if isinstance(links, list) and links:
                cdn_url = links[0].get("URI")
                if cdn_url:
                    logger.info("Nexus update CDN link obtained for version %s (file_id=%s)", target_version, nexus_file_id)
                    return cdn_url
            logger.info("Nexus update lookup: empty download links for version %s", target_version)
        except Exception as e:
            logger.info("Nexus update lookup failed, falling back to GitHub: %s", e)
        return None

    def _is_newer_version(self, version: str) -> bool:
        """
        Compare versions to determine if update is newer.
        
        Args:
            version: Version to compare against current
            
        Returns:
            bool: True if version is newer than current
        """
        try:
            # Simple version comparison for semantic versioning
            def version_tuple(v):
                return tuple(map(int, v.split('.')))
            
            return version_tuple(version) > version_tuple(self.current_version)
        except ValueError:
            logger.warning(f"Could not parse version: {version}")
            return False
    
    def _is_version_skipped(self, version: str) -> bool:
        """
        Check if a version was skipped by the user.
        
        Args:
            version: Version to check
            
        Returns:
            bool: True if version was skipped, False otherwise
        """
        try:
            from ...backend.handlers.config_handler import ConfigHandler
            config_handler = ConfigHandler()
            skipped_versions = config_handler.get('skipped_versions', [])
            return version in skipped_versions
        except Exception as e:
            logger.warning(f"Error checking skipped versions: {e}")
            return False
    
    def check_for_updates_async(self, callback: Callable[[Optional[UpdateInfo]], None]) -> None:
        """
        Check for updates in background thread.
        
        Args:
            callback: Function to call with update info (or None)
        """
        def check_worker():
            try:
                update_info = self.check_for_updates()
                logger.debug(f"check_worker: Received update_info: {update_info}")
                logger.debug(f"check_worker: About to call callback...")
                callback(update_info)
                logger.debug(f"check_worker: Callback completed")
            except Exception as e:
                logger.error(f"Error in background update check: {e}")
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")
                callback(None)
        
        thread = threading.Thread(target=check_worker, daemon=True)
        thread.start()
    
    def can_update(self) -> bool:
        """
        Check if updating is possible in current environment.
        
        Returns:
            bool: True if updating is possible
        """
        if not is_appimage():
            logger.debug("Not running as AppImage - updates not supported")
            return False
        
        appimage_path = get_appimage_path()
        if not appimage_path:
            logger.debug("AppImage path validation failed - updates not supported")
            return False
        
        if not can_self_update():
            logger.debug("Cannot write to AppImage - updates not possible")
            return False
        
        logger.debug(f"Self-updating enabled for AppImage: {appimage_path}")
        return True
    
    def download_update(self, update_info: UpdateInfo,
                       progress_callback: Optional[Callable[[int, int], None]] = None) -> Optional[Path]:
        """
        Download update AppImage. Falls back to GitHub if the primary source fails.
        """
        logger.info("Downloading update %s from %s (full replacement)", update_info.version, update_info.source)
        result = self._download_update_manual(update_info, progress_callback)
        if result:
            logger.info("Update download complete: %s from %s -> %s", update_info.version, update_info.source, result)
            return result

        # Primary source failed - fall back to GitHub if we came from Nexus
        if update_info.source == "nexus" and update_info.github_download_url:
            logger.warning("Nexus download failed, falling back to GitHub")
            fallback = UpdateInfo(
                version=update_info.version,
                tag_name=update_info.tag_name,
                release_date=update_info.release_date,
                changelog=update_info.changelog,
                download_url=update_info.github_download_url,
                source="github",
                file_size=update_info.file_size,
                is_delta_update=False,
                github_download_url=update_info.github_download_url,
            )
            result = self._download_update_manual(fallback, progress_callback)
            if result:
                logger.info("Update download complete via GitHub fallback: %s -> %s", update_info.version, result)
                return result

        logger.error("Update download failed: %s", update_info.version)
        return None
    
    def _download_update_manual(self, update_info: UpdateInfo, 
                               progress_callback: Optional[Callable[[int, int], None]] = None) -> Optional[Path]:
        """
        Fallback manual download method.
        
        Args:
            update_info: Information about the update to download
            progress_callback: Optional callback for download progress
            
        Returns:
            Path to downloaded file, or None if download failed
        """
        try:
            logger.info("Downloading update %s from %s (%s)", update_info.version, update_info.source, update_info.download_url)
            
            response = requests.get(update_info.download_url, stream=True)
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            downloaded_size = 0
            
            # Create update directory in user's data directory
            from jackify.shared.paths import get_jackify_data_dir
            update_dir = get_jackify_data_dir() / "updates"
            update_dir.mkdir(parents=True, exist_ok=True)
            
            # Nexus delivers a .7z archive; GitHub delivers the AppImage directly.
            # Detect which we have after download, then handle accordingly.
            # Saving as .7z avoids any path collision with the final .AppImage name.
            archive_file = update_dir / f"Jackify-{update_info.version}.7z"
            temp_file = update_dir / f"Jackify-{update_info.version}.AppImage"

            with open(archive_file, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded_size += len(chunk)

                        if progress_callback:
                            progress_callback(downloaded_size, total_size)

            if self._is_7z_archive(archive_file):
                logger.info("Downloaded file is a 7z archive, extracting AppImage")
                extracted = self._extract_appimage_from_7z(archive_file, update_dir, update_info.version)
                archive_file.unlink(missing_ok=True)
                if not extracted:
                    logger.error("Failed to extract AppImage from 7z archive")
                    return None
                temp_file = extracted
            else:
                archive_file.rename(temp_file)

            # Make executable
            temp_file.chmod(0o755)

            logger.info("Update downloaded successfully: %s from %s -> %s", update_info.version, update_info.source, temp_file)
            return temp_file

        except Exception as e:
            logger.error(f"Failed to download update manually: {e}")
            return None

    def _is_7z_archive(self, path: Path) -> bool:
        """Detect 7z archive by magic bytes (37 7A BC AF 27 1C)."""
        try:
            with open(path, 'rb') as f:
                magic = f.read(6)
            return magic == b'7z\xbc\xaf\x27\x1c'
        except Exception:
            return False

    def _get_bundled_7z_path(self) -> Optional[Path]:
        """Return path to bundled 7z binary (AppImage or dev)."""
        import os
        candidates = []
        appdir = os.environ.get('APPDIR')
        if appdir:
            candidates.append(Path(appdir) / 'opt' / 'jackify' / 'tools' / '7z')
        candidates.append(Path(__file__).parent.parent.parent / 'tools' / '7z')
        for p in candidates:
            if p.exists() and os.access(p, os.X_OK):
                return p
        return None

    def _extract_appimage_from_7z(self, archive: Path, dest_dir: Path, version: str) -> Optional[Path]:
        """Extract AppImage from a 7z archive into dest_dir."""
        seven_z = self._get_bundled_7z_path()
        if not seven_z:
            logger.error("Bundled 7z not found, cannot extract update archive")
            return None
        out_path = dest_dir / f"Jackify-{version}.AppImage"
        if out_path.exists():
            out_path.unlink()
        tmp_dir = Path(tempfile.mkdtemp(dir=dest_dir))
        try:
            result = subprocess.run(
                [str(seven_z), 'e', str(archive), f'-o{tmp_dir}', '-y'],
                capture_output=True, text=True, timeout=120
            )
            if result.returncode != 0:
                logger.error("7z extraction failed (rc=%d): %s", result.returncode, result.stderr.strip())
                return None
            candidates = list(tmp_dir.glob('*.AppImage'))
            if not candidates:
                logger.error("No .AppImage found in archive contents: %s",
                             [p.name for p in tmp_dir.iterdir()])
                return None
            extracted = candidates[0]
            logger.debug("Found %s in archive (%d bytes)", extracted.name, extracted.stat().st_size)
            shutil.move(str(extracted), str(out_path))
            if not out_path.exists():
                logger.error("AppImage missing after move to %s", out_path)
                return None
            logger.info("Extracted AppImage to %s (%d bytes)", out_path, out_path.stat().st_size)
            return out_path
        except Exception as e:
            logger.error("Exception during 7z extraction: %s", e)
            return None
        finally:
            shutil.rmtree(str(tmp_dir), ignore_errors=True)
    
    def apply_update(self, new_appimage_path: Path) -> bool:
        """
        Apply update by replacing current AppImage.

        Creates a helper script that waits for Jackify to exit,
        then replaces the AppImage and restarts it.
        """
        current_appimage = get_appimage_path()
        if not current_appimage:
            logger.error("Cannot determine current AppImage path")
            return False

        try:
            helper_script = self._create_update_helper(current_appimage, new_appimage_path)

            if helper_script:
                logger.info("Applying update: replacing %s with %s", current_appimage, new_appimage_path)
                subprocess.Popen(['nohup', 'bash', str(helper_script)],
                                 stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
                return True

            return False

        except Exception as e:
            logger.error(f"Failed to apply update: {e}")
            return False

    def _create_update_helper(self, current_appimage: Path, new_appimage: Path) -> Optional[Path]:
        """Create helper script that replaces the AppImage after Jackify exits."""
        try:
            from jackify.shared.paths import get_jackify_data_dir
            update_dir = get_jackify_data_dir() / "updates"
            update_dir.mkdir(parents=True, exist_ok=True)

            helper_script = update_dir / "update_helper.sh"

            script_content = f'''#!/bin/bash
# Jackify Update Helper Script
CURRENT_APPIMAGE="{current_appimage}"
NEW_APPIMAGE="{new_appimage}"
TEMP_NAME="$CURRENT_APPIMAGE.updating"

echo "Jackify Update Helper"
echo "Waiting for Jackify to exit..."
sleep 5

echo "Validating new AppImage..."
if [ ! -f "$NEW_APPIMAGE" ]; then
    echo "ERROR: New AppImage not found: $NEW_APPIMAGE"
    exit 1
fi

if ! timeout 10 "$NEW_APPIMAGE" --version >/dev/null 2>&1; then
    echo "ERROR: New AppImage failed validation test"
    exit 1
fi

echo "New AppImage validated successfully"
echo "Performing safe replacement..."

if [ -f "$CURRENT_APPIMAGE" ]; then
    cp "$CURRENT_APPIMAGE" "$CURRENT_APPIMAGE.backup"
fi

if cp "$NEW_APPIMAGE" "$TEMP_NAME"; then
    chmod +x "$TEMP_NAME"
    if mv "$TEMP_NAME" "$CURRENT_APPIMAGE"; then
        echo "Update completed successfully!"
        rm -f "$NEW_APPIMAGE"
        rm -f "$CURRENT_APPIMAGE.backup"
        echo "Restarting Jackify..."
        sleep 1
        exec "$CURRENT_APPIMAGE"
    else
        echo "ERROR: Failed to move updated AppImage"
        rm -f "$TEMP_NAME"
        if [ -f "$CURRENT_APPIMAGE.backup" ]; then
            mv "$CURRENT_APPIMAGE.backup" "$CURRENT_APPIMAGE"
        fi
        exit 1
    fi
else
    echo "ERROR: Failed to copy new AppImage"
    exit 1
fi

rm -f "{helper_script}"
'''

            with open(helper_script, 'w') as f:
                f.write(script_content)

            helper_script.chmod(0o755)
            logger.debug(f"Created update helper script: {helper_script}")
            return helper_script

        except Exception as e:
            logger.error(f"Failed to create update helper script: {e}")
            return None
