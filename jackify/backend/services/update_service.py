"""
Update service for checking and applying Jackify updates.

This service handles checking for updates via GitHub releases API
and coordinating the update process.
"""

import json
import logging
import os
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
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
    file_size: Optional[int] = None
    is_critical: bool = False


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
        """
        Check for available updates via GitHub releases API.
        
        Returns:
            UpdateInfo if update available, None otherwise
        """
        try:
            url = f"{self.github_api_base}/repos/{self.github_repo}/releases/latest"
            headers = {
                'Accept': 'application/vnd.github.v3+json',
                'User-Agent': f'Jackify/{self.current_version}'
            }
            
            logger.debug(f"Checking for updates at {url}")
            response = requests.get(url, headers=headers, timeout=self.update_check_timeout)
            response.raise_for_status()
            
            release_data = response.json()
            latest_version = release_data['tag_name'].lstrip('v')
            
            if self._is_newer_version(latest_version):
                # Find AppImage asset
                download_url = None
                file_size = None
                
                for asset in release_data.get('assets', []):
                    if asset['name'].endswith('.AppImage'):
                        download_url = asset['browser_download_url']
                        file_size = asset['size']
                        break
                
                if download_url:
                    return UpdateInfo(
                        version=latest_version,
                        tag_name=release_data['tag_name'],
                        release_date=release_data['published_at'],
                        changelog=release_data.get('body', ''),
                        download_url=download_url,
                        file_size=file_size
                    )
                else:
                    logger.warning(f"No AppImage found in release {latest_version}")
            
            return None
            
        except requests.RequestException as e:
            logger.error(f"Failed to check for updates: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error checking for updates: {e}")
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
    
    def check_for_updates_async(self, callback: Callable[[Optional[UpdateInfo]], None]) -> None:
        """
        Check for updates in background thread.
        
        Args:
            callback: Function to call with update info (or None)
        """
        def check_worker():
            try:
                update_info = self.check_for_updates()
                callback(update_info)
            except Exception as e:
                logger.error(f"Error in background update check: {e}")
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
        
        if not can_self_update():
            logger.debug("Cannot write to AppImage - updates not possible")
            return False
        
        return True
    
    def download_update(self, update_info: UpdateInfo, 
                       progress_callback: Optional[Callable[[int, int], None]] = None) -> Optional[Path]:
        """
        Download update to temporary location.
        
        Args:
            update_info: Information about the update to download
            progress_callback: Optional callback for download progress (bytes_downloaded, total_bytes)
            
        Returns:
            Path to downloaded file, or None if download failed
        """
        try:
            logger.info(f"Downloading update {update_info.version} from {update_info.download_url}")
            
            response = requests.get(update_info.download_url, stream=True)
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            downloaded_size = 0
            
            # Create temporary file
            temp_dir = Path(tempfile.gettempdir()) / "jackify_updates"
            temp_dir.mkdir(exist_ok=True)
            
            temp_file = temp_dir / f"Jackify-{update_info.version}.AppImage"
            
            with open(temp_file, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded_size += len(chunk)
                        
                        if progress_callback:
                            progress_callback(downloaded_size, total_size)
            
            # Make executable
            temp_file.chmod(0o755)
            
            logger.info(f"Update downloaded successfully to {temp_file}")
            return temp_file
            
        except Exception as e:
            logger.error(f"Failed to download update: {e}")
            return None
    
    def apply_update(self, new_appimage_path: Path) -> bool:
        """
        Apply update by replacing current AppImage.
        
        This creates a helper script that waits for Jackify to exit,
        then replaces the AppImage and restarts it.
        
        Args:
            new_appimage_path: Path to downloaded update
            
        Returns:
            bool: True if update application was initiated successfully
        """
        current_appimage = get_appimage_path()
        if not current_appimage:
            logger.error("Cannot determine current AppImage path")
            return False
        
        try:
            # Create update helper script
            helper_script = self._create_update_helper(current_appimage, new_appimage_path)
            
            if helper_script:
                # Launch helper script and exit
                logger.info("Launching update helper and exiting")
                subprocess.Popen(['nohup', 'bash', str(helper_script)], 
                               stdout=subprocess.DEVNULL, 
                               stderr=subprocess.DEVNULL)
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to apply update: {e}")
            return False
    
    def _create_update_helper(self, current_appimage: Path, new_appimage: Path) -> Optional[Path]:
        """
        Create helper script for update replacement.
        
        Args:
            current_appimage: Path to current AppImage
            new_appimage: Path to new AppImage
            
        Returns:
            Path to helper script, or None if creation failed
        """
        try:
            temp_dir = Path(tempfile.gettempdir()) / "jackify_updates"
            temp_dir.mkdir(exist_ok=True)
            
            helper_script = temp_dir / "update_helper.sh"
            
            script_content = f'''#!/bin/bash
# Jackify Update Helper Script
# This script replaces the current AppImage with the new version

CURRENT_APPIMAGE="{current_appimage}"
NEW_APPIMAGE="{new_appimage}"

echo "Jackify Update Helper"
echo "Waiting for Jackify to exit..."

# Wait for Jackify to exit (give it a few seconds)
sleep 3

echo "Replacing AppImage..."

# Backup current version (optional)
if [ -f "$CURRENT_APPIMAGE" ]; then
    cp "$CURRENT_APPIMAGE" "$CURRENT_APPIMAGE.backup"
fi

# Replace with new version
if cp "$NEW_APPIMAGE" "$CURRENT_APPIMAGE"; then
    chmod +x "$CURRENT_APPIMAGE"
    echo "Update completed successfully!"
    
    # Clean up temporary file
    rm -f "$NEW_APPIMAGE"
    
    # Restart Jackify
    echo "Restarting Jackify..."
    exec "$CURRENT_APPIMAGE"
else
    echo "Update failed - could not replace AppImage"
    # Restore backup if replacement failed
    if [ -f "$CURRENT_APPIMAGE.backup" ]; then
        mv "$CURRENT_APPIMAGE.backup" "$CURRENT_APPIMAGE"
        echo "Restored original AppImage"
    fi
fi

# Clean up this script
rm -f "{helper_script}"
'''
            
            with open(helper_script, 'w') as f:
                f.write(script_content)
            
            # Make executable
            helper_script.chmod(0o755)
            
            logger.debug(f"Created update helper script: {helper_script}")
            return helper_script
            
        except Exception as e:
            logger.error(f"Failed to create update helper script: {e}")
            return None