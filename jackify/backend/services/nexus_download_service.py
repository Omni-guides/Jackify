"""
Nexus Download Service

Handles downloading mod files from Nexus Mods using OAuth authentication.
"""

import logging
import requests
import time
from pathlib import Path
from typing import Optional, Callable, Tuple

logger = logging.getLogger(__name__)


class NexusDownloadService:
    """Service for downloading files from Nexus Mods"""

    NEXUS_API_BASE = "https://api.nexusmods.com/v1"

    def __init__(self, auth_token: str):
        """
        Initialize Nexus download service.

        Args:
            auth_token: OAuth access token or API key
        """
        self.auth_token = auth_token
        self.headers = {
            "Authorization": f"Bearer {auth_token}",
            "User-Agent": "jackify"
        }

    def get_mod_files(self, game_domain: str, mod_id: int) -> Optional[list]:
        """
        Get list of files for a mod.

        Args:
            game_domain: Game domain (e.g., 'newvegas')
            mod_id: Mod ID number

        Returns:
            List of file metadata dicts, or None if failed
        """
        try:
            url = f"{self.NEXUS_API_BASE}/games/{game_domain}/mods/{mod_id}/files.json"

            response = requests.get(url, headers=self.headers, timeout=30)
            response.raise_for_status()

            data = response.json()
            files = data.get('files', [])

            logger.info(f"Found {len(files)} files for mod {mod_id}")
            return files

        except Exception as e:
            logger.error(f"Failed to get mod files: {e}")
            return None

    def get_download_link(self, game_domain: str, mod_id: int, file_id: int) -> Optional[str]:
        """
        Get download link for a specific file.

        Args:
            game_domain: Game domain (e.g., 'newvegas')
            mod_id: Mod ID number
            file_id: File ID number

        Returns:
            Download URL, or None if failed
        """
        try:
            url = f"{self.NEXUS_API_BASE}/games/{game_domain}/mods/{mod_id}/files/{file_id}/download_link.json"

            response = requests.get(url, headers=self.headers, timeout=30)

            # Check for specific error codes
            if response.status_code == 403:
                logger.error(f"Download link request forbidden (403) - Nexus Premium required for file {file_id}")
                return None
            elif response.status_code == 404:
                logger.error(f"Download link request not found (404) - file {file_id} may not exist")
                return None

            response.raise_for_status()

            data = response.json()

            # API returns list of download servers
            if isinstance(data, list) and len(data) > 0:
                download_url = data[0].get('URI')
                logger.info(f"Got download link for file {file_id}")
                return download_url
            else:
                logger.error(f"No download link returned for file {file_id}")
                return None

        except requests.exceptions.HTTPError as e:
            logger.error(f"Failed to get download link: HTTP {e.response.status_code} - {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to get download link: {e}")
            return None

    def download_file(
        self,
        download_url: str,
        output_path: Path,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> bool:
        """
        Download a file from Nexus.

        Args:
            download_url: Download URL from get_download_link()
            output_path: Where to save the file
            progress_callback: Optional callback(downloaded_bytes, total_bytes)

        Returns:
            True if successful
        """
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)

            response = requests.get(download_url, stream=True, timeout=60)
            response.raise_for_status()

            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0

            with open(output_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)

                        if progress_callback and total_size > 0:
                            progress_callback(downloaded, total_size)

            logger.info(f"Downloaded {output_path.name} ({downloaded} bytes)")
            return True

        except Exception as e:
            logger.error(f"Download failed: {e}")
            if output_path.exists():
                output_path.unlink()
            return False

    def get_latest_file_version(
        self,
        game_domain: str,
        mod_id: int,
        file_name_filter: Optional[str] = None,
    ) -> Optional[str]:
        """Return the version string of the most recent file for a mod, or None."""
        files = self.get_mod_files(game_domain, mod_id)
        if not files:
            return None
        if file_name_filter:
            files = [f for f in files if file_name_filter.lower() in f.get("file_name", "").lower()]
        if not files:
            return None
        files.sort(key=lambda f: f.get("uploaded_timestamp", 0), reverse=True)
        return files[0].get("version") or None

    def download_latest_file(
        self,
        game_domain: str,
        mod_id: int,
        output_dir: Path,
        file_name_filter: Optional[str] = None,
        progress_callback: Optional[Callable[[str], None]] = None
    ) -> Tuple[bool, Optional[Path], str]:
        """
        Download the latest file from a mod.

        Args:
            game_domain: Game domain (e.g., 'newvegas')
            mod_id: Mod ID number
            output_dir: Directory to save file
            file_name_filter: Optional substring to filter files (e.g., 'linux', 'mpi')
            progress_callback: Optional callback for status updates

        Returns:
            Tuple of (success, file_path, message)
        """
        def update_progress(msg: str):
            if progress_callback:
                progress_callback(msg)
            logger.info(msg)

        try:
            update_progress(f"Fetching file list for mod {mod_id}...")

            files = self.get_mod_files(game_domain, mod_id)
            if not files:
                return False, None, "Failed to get mod file list"

            # Filter files if requested
            if file_name_filter:
                filtered = [f for f in files if file_name_filter.lower() in f.get('file_name', '').lower()]
                if not filtered:
                    available_files = [f.get('file_name', 'unknown') for f in files]
                    logger.warning(f"No files matching '{file_name_filter}' in: {available_files}")
                    return False, None, f"No files found matching '{file_name_filter}'. Available: {', '.join(available_files)}"
                files = filtered

            # Get the most recent file
            files.sort(key=lambda f: f.get('uploaded_timestamp', 0), reverse=True)
            latest_file = files[0]

            file_id = latest_file['file_id']
            file_name = latest_file['file_name']

            update_progress(f"Downloading {file_name}...")

            download_url = self.get_download_link(game_domain, mod_id, file_id)
            if not download_url:
                return False, None, "Failed to get download link"

            output_path = output_dir / file_name

            def download_progress(downloaded, total):
                if total > 0:
                    percent = (downloaded / total) * 100
                    update_progress(f"Downloading: {percent:.1f}%")

            success = self.download_file(download_url, output_path, download_progress)

            if success:
                return True, output_path, f"Downloaded {file_name}"
            else:
                return False, None, "Download failed"

        except Exception as e:
            error_msg = f"Download failed: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return False, None, error_msg
