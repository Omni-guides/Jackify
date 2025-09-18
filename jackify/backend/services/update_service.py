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
    is_delta_update: bool = False


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
                    # Determine if this is a delta update
                    is_delta = '.delta' in download_url or 'delta' in download_url.lower()
                    
                    return UpdateInfo(
                        version=latest_version,
                        tag_name=release_data['tag_name'],
                        release_date=release_data['published_at'],
                        changelog=release_data.get('body', ''),
                        download_url=download_url,
                        file_size=file_size,
                        is_delta_update=is_delta
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
        Download update using full AppImage replacement.
        
        Since we can't rely on external tools being available, we use a reliable
        full replacement approach that works on all systems without dependencies.
        
        Args:
            update_info: Information about the update to download
            progress_callback: Optional callback for download progress (bytes_downloaded, total_bytes)
            
        Returns:
            Path to downloaded file, or None if download failed
        """
        try:
            logger.info(f"Downloading update {update_info.version} (full replacement)")
            return self._download_update_manual(update_info, progress_callback)
            
        except Exception as e:
            logger.error(f"Failed to download update: {e}")
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
            logger.info(f"Manual download of update {update_info.version} from {update_info.download_url}")
            
            response = requests.get(update_info.download_url, stream=True)
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            downloaded_size = 0
            
            # Create update directory in user's home directory
            home_dir = Path.home()
            update_dir = home_dir / "Jackify" / "updates"
            update_dir.mkdir(parents=True, exist_ok=True)
            
            temp_file = update_dir / f"Jackify-{update_info.version}.AppImage"
            
            with open(temp_file, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded_size += len(chunk)
                        
                        if progress_callback:
                            progress_callback(downloaded_size, total_size)
            
            # Make executable
            temp_file.chmod(0o755)
            
            logger.info(f"Manual update downloaded successfully to {temp_file}")
            return temp_file
            
        except Exception as e:
            logger.error(f"Failed to download update manually: {e}")
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
            # Create update directory in user's home directory
            home_dir = Path.home()
            update_dir = home_dir / "Jackify" / "updates"
            update_dir.mkdir(parents=True, exist_ok=True)
            
            helper_script = update_dir / "update_helper.sh"
            
            script_content = f'''#!/bin/bash
# Jackify Update Helper Script
# This script safely replaces the current AppImage with the new version

CURRENT_APPIMAGE="{current_appimage}"
NEW_APPIMAGE="{new_appimage}"
TEMP_NAME="$CURRENT_APPIMAGE.updating"

echo "Jackify Update Helper"
echo "Waiting for Jackify to exit..."

# Wait longer for Jackify to fully exit and unmount
sleep 5

echo "Validating new AppImage..."

# Validate new AppImage exists and is executable
if [ ! -f "$NEW_APPIMAGE" ]; then
    echo "ERROR: New AppImage not found: $NEW_APPIMAGE"
    exit 1
fi

# Test that new AppImage can execute --version
if ! timeout 10 "$NEW_APPIMAGE" --version >/dev/null 2>&1; then
    echo "ERROR: New AppImage failed validation test"
    exit 1
fi

echo "New AppImage validated successfully"
echo "Performing safe replacement..."

# Backup current version
if [ -f "$CURRENT_APPIMAGE" ]; then
    cp "$CURRENT_APPIMAGE" "$CURRENT_APPIMAGE.backup"
fi

# Safe replacement: copy to temp name first, then atomic move
if cp "$NEW_APPIMAGE" "$TEMP_NAME"; then
    chmod +x "$TEMP_NAME"
    
    # Atomic move to replace
    if mv "$TEMP_NAME" "$CURRENT_APPIMAGE"; then
        echo "Update completed successfully!"
        
        # Clean up
        rm -f "$NEW_APPIMAGE"
        rm -f "$CURRENT_APPIMAGE.backup"
        
        # Restart Jackify
        echo "Restarting Jackify..."
        sleep 1
        exec "$CURRENT_APPIMAGE"
    else
        echo "ERROR: Failed to move updated AppImage"
        rm -f "$TEMP_NAME"
        # Restore backup
        if [ -f "$CURRENT_APPIMAGE.backup" ]; then
            mv "$CURRENT_APPIMAGE.backup" "$CURRENT_APPIMAGE"
            echo "Restored original AppImage"
        fi
        exit 1
    fi
else
    echo "ERROR: Failed to copy new AppImage"
    exit 1
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