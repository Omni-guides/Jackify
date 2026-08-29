"""
Service for fetching and managing modlist metadata for the gallery view.

Handles jackify-engine integration, caching, and image management.
"""
import json
import subprocess
import time
import threading
import logging
from pathlib import Path
from typing import Optional, List, Dict
from datetime import datetime, timedelta
import urllib.request

logger = logging.getLogger(__name__)

from jackify.backend.models.modlist_metadata import (
    ModlistMetadataResponse,
    ModlistMetadata,
    parse_modlist_metadata_response
)
from jackify.backend.core.modlist_operations import get_jackify_engine_path
from jackify.backend.handlers.config_handler import ConfigHandler
from jackify.shared.paths import get_jackify_data_dir


class ModlistGalleryService:
    """Service for fetching and caching modlist metadata from jackify-engine"""

    # Metadata is always fetched fresh from engine; images are cached indefinitely (managed separately)
    _engine_call_lock = threading.Lock()

    def __init__(self):
        """Initialize the gallery service"""
        self.config_handler = ConfigHandler()
        self._engine_process: Optional[subprocess.Popen] = None
        # Cache directories in Jackify Data Directory
        jackify_data_dir = get_jackify_data_dir()
        self.CACHE_DIR = jackify_data_dir / "modlist-cache" / "metadata"
        self.IMAGE_CACHE_DIR = jackify_data_dir / "modlist-cache" / "images"
        self.METADATA_CACHE_FILE = self.CACHE_DIR / "modlist_metadata.json"
        self._ensure_cache_dirs()
        # Tag metadata caches (avoid refetching per render)
        self._tag_mappings_cache: Optional[Dict[str, str]] = None
        self._tag_mapping_lookup: Optional[Dict[str, str]] = None
        self._allowed_tags_cache: Optional[set] = None
        self._allowed_tags_lookup: Optional[Dict[str, str]] = None

    def cancel(self) -> None:
        """Kill any in-progress engine call. Safe to call from any thread."""
        proc = self._engine_process
        if proc is not None:
            try:
                proc.kill()
            except Exception:
                pass

    def _ensure_cache_dirs(self):
        """Create cache directories if they don't exist"""
        self.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self.IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def fetch_modlist_metadata(
        self,
        include_validation: bool = True,
        include_search_index: bool = False,
        sort_by: str = "title",
        force_refresh: bool = False
    ) -> Optional[ModlistMetadataResponse]:
        """
        Fetch modlist metadata from jackify-engine.

        NOTE: Metadata is ALWAYS fetched fresh from the engine to ensure up-to-date
        version numbers and sizes for frequently-updated modlists. Only images are cached.

        Args:
            include_validation: Include validation status (slower)
            include_search_index: Include mod search index (slower)
            sort_by: Sort order (title, size, date)
            force_refresh: Deprecated parameter (kept for API compatibility)

        Returns:
            ModlistMetadataResponse or None if fetch fails
        """
        # Always fetch fresh data from jackify-engine
        # The engine itself is fast (~1-2 seconds) and always gets latest metadata
        try:
            metadata = self._fetch_from_engine(
                include_validation=include_validation,
                include_search_index=include_search_index,
                sort_by=sort_by
            )

            # Still save to cache as a fallback for offline scenarios
            if metadata:
                self._save_to_cache(metadata)

            return metadata

        except Exception as e:
            logger.warning("Error fetching modlist metadata: %s - falling back to cache", e)
            return self._load_from_cache()

    def _fetch_from_engine(
        self,
        include_validation: bool,
        include_search_index: bool,
        sort_by: str
    ) -> Optional[ModlistMetadataResponse]:
        """Call jackify-engine to fetch modlist metadata"""
        # Use thread lock to prevent concurrent engine calls
        # Multiple simultaneous calls could cause recursive spawning issues
        with self._engine_call_lock:
            # Get engine path BEFORE cleaning environment
            # get_jackify_engine_path() may need APPDIR to locate the engine
            engine_path = get_jackify_engine_path()
            if not engine_path:
                raise FileNotFoundError("jackify-engine not found")

            # Build command
            cmd = [str(engine_path), "list-modlists", "--json", "--sort-by", sort_by]

            if include_validation:
                cmd.append("--include-validation-status")

            if include_search_index:
                cmd.append("--include-search-index")

            # Execute command
            # Use centralized clean environment to prevent AppImage recursive spawning
            # Must happen AFTER engine path resolution
            from jackify.backend.handlers.subprocess_utils import get_clean_subprocess_env
            clean_env = get_clean_subprocess_env()

            self._engine_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=clean_env,
            )
            try:
                stdout_data, stderr_data = self._engine_process.communicate(timeout=300)
                returncode = self._engine_process.returncode
            except subprocess.TimeoutExpired:
                self._engine_process.kill()
                raise RuntimeError("jackify-engine timed out")
            finally:
                self._engine_process = None

            if returncode != 0:
                raise RuntimeError(f"jackify-engine failed: {stderr_data}")

            # Parse JSON response - skip progress messages and extract JSON
            # jackify-engine prints progress to stdout before the JSON
            stdout = stdout_data.strip()

            # Find the start of JSON (first '{' on its own line)
            lines = stdout.split('\n')
            json_start = 0
            for i, line in enumerate(lines):
                if line.strip().startswith('{'):
                    json_start = i
                    break

            json_text = '\n'.join(lines[json_start:])
            data = json.loads(json_text)
            return parse_modlist_metadata_response(data)

    def _load_from_cache(self) -> Optional[ModlistMetadataResponse]:
        """Load metadata from cache file"""
        if not self.METADATA_CACHE_FILE.exists():
            return None

        try:
            with open(self.METADATA_CACHE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return parse_modlist_metadata_response(data)
        except Exception as e:
            logger.warning("Error loading metadata cache: %s", e)
            return None

    def _save_to_cache(self, metadata: ModlistMetadataResponse):
        """Save metadata to cache file"""
        try:
            # Convert to dict for JSON serialization
            data = {
                'metadataVersion': metadata.metadataVersion,
                'timestamp': metadata.timestamp,
                'count': metadata.count,
                'modlists': [self._metadata_to_dict(m) for m in metadata.modlists]
            }

            with open(self.METADATA_CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)

        except Exception as e:
            logger.warning("Error saving metadata cache: %s", e)

    def _metadata_to_dict(self, metadata: ModlistMetadata) -> dict:
        """Convert ModlistMetadata to dict for JSON serialization"""
        result = {
            'title': metadata.title,
            'description': metadata.description,
            'author': metadata.author,
            'maintainers': metadata.maintainers,
            'namespacedName': metadata.namespacedName,
            'repositoryName': metadata.repositoryName,
            'machineURL': metadata.machineURL,
            'game': metadata.game,
            'gameHumanFriendly': metadata.gameHumanFriendly,
            'official': metadata.official,
            'nsfw': metadata.nsfw,
            'utilityList': metadata.utilityList,
            'forceDown': metadata.forceDown,
            'imageContainsTitle': metadata.imageContainsTitle,
            'version': metadata.version,
            'displayVersionOnlyInInstallerView': metadata.displayVersionOnlyInInstallerView,
            'dateCreated': metadata.dateCreated,
            'dateUpdated': metadata.dateUpdated,
            'tags': metadata.tags,
            'mods': metadata.mods
        }

        if metadata.images:
            result['images'] = {
                'small': metadata.images.small,
                'large': metadata.images.large
            }

        if metadata.links:
            result['links'] = {
                'image': metadata.links.image,
                'readme': metadata.links.readme,
                'download': metadata.links.download,
                'discordURL': metadata.links.discordURL,
                'websiteURL': metadata.links.websiteURL
            }

        if metadata.sizes:
            result['sizes'] = {
                'downloadSize': metadata.sizes.downloadSize,
                'downloadSizeFormatted': metadata.sizes.downloadSizeFormatted,
                'installSize': metadata.sizes.installSize,
                'installSizeFormatted': metadata.sizes.installSizeFormatted,
                'totalSize': metadata.sizes.totalSize,
                'totalSizeFormatted': metadata.sizes.totalSizeFormatted,
                'numberOfArchives': metadata.sizes.numberOfArchives,
                'numberOfInstalledFiles': metadata.sizes.numberOfInstalledFiles
            }

        if metadata.validation:
            result['validation'] = {
                'failed': metadata.validation.failed,
                'passed': metadata.validation.passed,
                'updating': metadata.validation.updating,
                'mirrored': metadata.validation.mirrored,
                'modListIsMissing': metadata.validation.modListIsMissing,
                'hasFailures': metadata.validation.hasFailures
            }

        return result

    def download_images(
        self,
        game_filter: Optional[str] = None,
        size: str = "both",
        overwrite: bool = False
    ) -> bool:
        """
        Download modlist images to cache using jackify-engine.

        Args:
            game_filter: Filter by game name (None = all games)
            size: Image size to download (small, large, both)
            overwrite: Overwrite existing images

        Returns:
            True if successful, False otherwise
        """
        # Build command (engine path will be resolved inside lock)
        cmd = [
            "placeholder",  # Will be replaced with actual engine path
            "download-modlist-images",
            "--output", str(self.IMAGE_CACHE_DIR),
            "--size", size
        ]

        if game_filter:
            cmd.extend(["--game", game_filter])

        if overwrite:
            cmd.append("--overwrite")

        # Execute command
        try:
            # Use thread lock to prevent concurrent engine calls
            with self._engine_call_lock:
                # Get engine path BEFORE cleaning environment
                # get_jackify_engine_path() may need APPDIR to locate the engine
                engine_path = get_jackify_engine_path()
                if not engine_path:
                    return False
                
                # Update cmd with resolved engine path
                cmd[0] = str(engine_path)
                
                # Use centralized clean environment to prevent AppImage recursive spawning
                # Must happen AFTER engine path resolution
                from jackify.backend.handlers.subprocess_utils import get_clean_subprocess_env
                clean_env = get_clean_subprocess_env()

                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=3600,  # 1 hour timeout for downloads
                    env=clean_env
                )
            return result.returncode == 0
        except Exception as e:
            logger.warning("Error downloading gallery images: %s", e)
            return False

    def get_cached_image_path(self, metadata: ModlistMetadata, size: str = "large") -> Optional[Path]:
        """
        Get path to cached image for a modlist (only if it exists).

        Args:
            metadata: Modlist metadata
            size: Image size (small or large)

        Returns:
            Path to cached image or None if not cached
        """
        filename = f"{metadata.machineURL}_{size}.webp"
        image_path = self.IMAGE_CACHE_DIR / metadata.repositoryName / filename

        if image_path.exists():
            return image_path
        return None
    
    def get_image_cache_path(self, metadata: ModlistMetadata, size: str = "large") -> Path:
        """
        Get path where image should be cached (always returns path, even if file doesn't exist).

        Args:
            metadata: Modlist metadata
            size: Image size (small or large)

        Returns:
            Path where image should be cached
        """
        filename = f"{metadata.machineURL}_{size}.webp"
        return self.IMAGE_CACHE_DIR / metadata.repositoryName / filename

    def get_image_url(self, metadata: ModlistMetadata, size: str = "large") -> Optional[str]:
        """
        Get image URL for a modlist.

        Args:
            metadata: Modlist metadata
            size: Image size (small or large)

        Returns:
            Image URL or None if images not available
        """
        if not metadata.images:
            return None

        return metadata.images.large if size == "large" else metadata.images.small

    def clear_cache(self):
        """Clear all cached metadata and images"""
        if self.METADATA_CACHE_FILE.exists():
            self.METADATA_CACHE_FILE.unlink()

        # Clear image cache
        if self.IMAGE_CACHE_DIR.exists():
            import shutil
            shutil.rmtree(self.IMAGE_CACHE_DIR)
            self.IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def load_tag_mappings(self) -> Dict[str, str]:
        """
        Load tag mappings from Wabbajack GitHub repository.
        Maps variant tag names to canonical tag names.
        
        Returns:
            Dictionary mapping variant tags to canonical tags
        """
        url = "https://raw.githubusercontent.com/wabbajack-tools/mod-lists/master/tag_mappings.json"
        try:
            with urllib.request.urlopen(url, timeout=10) as response:
                data = json.loads(response.read().decode('utf-8'))
                return data
        except Exception as e:
            logger.warning(f"Could not load tag mappings: {e}")
            return {}
    
    def load_allowed_tags(self) -> set:
        """
        Load allowed tags from Wabbajack GitHub repository.
        
        Returns:
            Set of allowed tag names (preserving original case)
        """
        url = "https://raw.githubusercontent.com/wabbajack-tools/mod-lists/master/allowed_tags.json"
        try:
            with urllib.request.urlopen(url, timeout=10) as response:
                data = json.loads(response.read().decode('utf-8'))
                return set(data)  # Return as set preserving original case
        except Exception as e:
            logger.warning(f"Could not load allowed tags: {e}")
            return set()

    def _ensure_tag_metadata(self):
        """Ensure tag mappings/allowed tags (and lookups) are cached."""
        if self._tag_mappings_cache is None:
            self._tag_mappings_cache = self.load_tag_mappings()
        if self._tag_mapping_lookup is None:
            self._tag_mapping_lookup = {k.lower(): v for k, v in self._tag_mappings_cache.items()}
        if self._allowed_tags_cache is None:
            self._allowed_tags_cache = self.load_allowed_tags()
        if self._allowed_tags_lookup is None:
            self._allowed_tags_lookup = {tag.lower(): tag for tag in self._allowed_tags_cache}

    def normalize_tag_value(self, tag: str) -> str:
        """
        Normalize a tag to its canonical display form using Wabbajack mappings.
        Returns the normalized tag (original casing preserved when possible).
        """
        if not tag:
            return ""
        self._ensure_tag_metadata()
        tag_key = tag.strip().lower()
        if not tag_key:
            return ""
        canonical = self._tag_mapping_lookup.get(tag_key, tag.strip())
        # Prefer allowed tag casing if available
        return self._allowed_tags_lookup.get(canonical.lower(), canonical)

    def normalize_tags_for_display(self, tags: Optional[List[str]]) -> List[str]:
        """Normalize a list of tags for UI display (deduped, canonical casing)."""
        if not tags:
            return []
        self._ensure_tag_metadata()
        normalized = []
        seen = set()
        for tag in tags:
            normalized_tag = self.normalize_tag_value(tag)
            key = normalized_tag.lower()
            if key and key not in seen:
                normalized.append(normalized_tag)
                seen.add(key)
        return normalized
