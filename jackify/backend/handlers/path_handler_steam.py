#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Steam path and library mixin for PathHandler.
Extracted from path_handler for file-size and domain separation.
"""

import os
import re
import logging
from pathlib import Path
from typing import Optional, List
from datetime import datetime
import vdf
from jackify.shared.steam_utils import (
    get_ordered_steam_roots,
    STEAM_PREFERENCE_AUTO,
)

logger = logging.getLogger(__name__)


class PathHandlerSteamMixin:
    """Mixin providing Steam config, library, and shortcuts path discovery."""

    @staticmethod
    def find_steam_config_vdf() -> Optional[Path]:
        """Finds the active Steam config.vdf file."""
        logger.debug("Searching for Steam config.vdf...")
        possible_steam_paths = get_ordered_steam_roots(STEAM_PREFERENCE_AUTO)
        for steam_path in possible_steam_paths:
            potential_path = steam_path / "config/config.vdf"
            if potential_path.is_file():
                logger.info(f"Found config.vdf at: {potential_path}")
                return potential_path
        logger.warning("Could not locate Steam's config.vdf file in standard locations.")
        return None

    @staticmethod
    def find_steam_library() -> Optional[Path]:
        """Find the primary Steam library common directory containing games."""
        logger.debug("Attempting to find Steam library...")
        ordered_roots = get_ordered_steam_roots(STEAM_PREFERENCE_AUTO)
        libraryfolders_vdf_paths = [
            str(root / "config" / "libraryfolders.vdf") for root in ordered_roots
        ]
        for path in libraryfolders_vdf_paths:
            if os.path.exists(path):
                backup_dir = os.path.join(os.path.dirname(path), "backups")
                if not os.path.exists(backup_dir):
                    try:
                        os.makedirs(backup_dir)
                    except OSError as e:
                        logger.warning(f"Could not create backup directory {backup_dir}: {e}")
                timestamp = datetime.now().strftime("%Y%m%d")
                backup_filename = f"libraryfolders_{timestamp}.vdf.bak"
                backup_path = os.path.join(backup_dir, backup_filename)
                if not os.path.exists(backup_path):
                    try:
                        import shutil
                        shutil.copy2(path, backup_path)
                        logger.debug(f"Created backup of libraryfolders.vdf at {backup_path}")
                    except Exception as e:
                        logger.error(f"Failed to create backup of libraryfolders.vdf: {e}")
        libraryfolders_vdf_path_obj = None
        found_path_str = None
        for path_str in libraryfolders_vdf_paths:
            if os.path.exists(path_str):
                found_path_str = path_str
                libraryfolders_vdf_path_obj = Path(path_str)
                logger.debug(f"Found libraryfolders.vdf at: {path_str}")
                break
        if not libraryfolders_vdf_path_obj or not libraryfolders_vdf_path_obj.is_file():
            logger.warning("libraryfolders.vdf not found or is not a file. Cannot automatically detect Steam Library.")
            return None
        library_paths = []
        try:
            with open(found_path_str, 'r') as f:
                content = f.read()
                path_matches = re.finditer(r'"path"\s*"([^"]+)"', content)
                for match in path_matches:
                    library_path_str = match.group(1).replace('\\\\', '\\')
                    common_path = os.path.join(library_path_str, "steamapps", "common")
                    if os.path.isdir(common_path):
                        library_paths.append(Path(common_path))
                        logger.debug(f"Found potential common path: {common_path}")
                    else:
                        logger.debug(f"Skipping non-existent common path derived from VDF: {common_path}")
            logger.debug(f"Found {len(library_paths)} valid library common paths from VDF.")
            if library_paths:
                logger.info(f"Using Steam library common path: {library_paths[0]}")
                return library_paths[0]
            logger.debug("No valid common paths found in VDF, checking default location...")
            for root in ordered_roots:
                default_common_path = root / "steamapps" / "common"
                if default_common_path.is_dir():
                    logger.info(f"Using default Steam library common path: {default_common_path}")
                    return default_common_path
            logger.error("No valid Steam library common path found in VDF or default locations.")
            return None
        except Exception as e:
            logger.error(f"Error parsing libraryfolders.vdf or finding Steam library: {e}", exc_info=True)
            return None

    @staticmethod
    def get_steam_library_path(steam_path: str) -> Optional[str]:
        """Get the Steam library path from libraryfolders.vdf."""
        try:
            libraryfolders_path = os.path.join(steam_path, 'steamapps', 'libraryfolders.vdf')
            if not os.path.exists(libraryfolders_path):
                return None
            with open(libraryfolders_path, 'r', encoding='utf-8') as f:
                content = f.read()
            libraries = {}
            current_library = None
            for line in content.split('\n'):
                line = line.strip()
                if line.startswith('"path"'):
                    current_library = line.split('"')[3].replace('\\\\', '\\')
                elif line.startswith('"apps"') and current_library:
                    libraries[current_library] = True
            for library_path in libraries:
                if os.path.exists(library_path):
                    return library_path
            return None
        except Exception as e:
            logger.error(f"Error getting Steam library path: {str(e)}")
            return None

    @staticmethod
    def get_mountpoint(path) -> Optional[str]:
        """Return the mount point for the given path (Linux). Used for STEAM_COMPAT_MOUNTS."""
        if not path:
            return None
        try:
            p = Path(path).resolve()
            if not p.exists():
                p = p.parent
            while p != p.parent:
                if os.path.ismount(p):
                    return str(p)
                p = p.parent
            return str(p)
        except (OSError, RuntimeError) as e:
            logger.debug(f"Could not get mountpoint for {path}: {e}")
            return None

    def get_steam_compat_mount_paths(self, install_dir=None, download_dir=None) -> List[str]:
        """
        Build list of mount paths for STEAM_COMPAT_MOUNTS: other Steam library roots plus
        mountpoints of install_dir and download_dir so MO2 can access game and downloads.
        """
        seen = set()
        result = []
        main_steam_lib_path_obj = self.find_steam_library()
        if main_steam_lib_path_obj and main_steam_lib_path_obj.name == "common":
            main_steam_lib_path = main_steam_lib_path_obj.parent.parent
        else:
            main_steam_lib_path = main_steam_lib_path_obj
        main_resolved = str(main_steam_lib_path.resolve()) if main_steam_lib_path else None
        for lib_path in self.get_all_steam_library_paths():
            try:
                r = str(lib_path.resolve())
            except (OSError, RuntimeError):
                r = str(lib_path)
            if r not in seen and r != main_resolved:
                seen.add(r)
                result.append(r)
        if download_dir:
            p = str(Path(str(download_dir)).resolve())
            if p not in seen:
                seen.add(p)
                result.append(p)
        return result

    @staticmethod
    def get_all_steam_library_paths() -> List[Path]:
        """Finds all Steam library paths listed in all known libraryfolders.vdf files (including Flatpak)."""
        logger.info("[DEBUG] Searching for all Steam libraryfolders.vdf files...")
        ordered_roots = get_ordered_steam_roots(STEAM_PREFERENCE_AUTO)
        vdf_paths = [root / "config" / "libraryfolders.vdf" for root in ordered_roots]
        library_paths = set()
        for vdf_path in vdf_paths:
            if vdf_path.is_file():
                logger.info(f"[DEBUG] Parsing libraryfolders.vdf: {vdf_path}")
                try:
                    with open(vdf_path, 'r', encoding='utf-8') as f:
                        data = vdf.load(f)
                        libraryfolders = data.get('libraryfolders', {})
                        for key, lib_data in libraryfolders.items():
                            if isinstance(lib_data, dict) and 'path' in lib_data:
                                lib_path = Path(lib_data['path'])
                                try:
                                    resolved_path = lib_path.resolve()
                                    library_paths.add(resolved_path)
                                    logger.debug(f"[DEBUG] Found library path: {resolved_path}")
                                except (OSError, RuntimeError) as resolve_err:
                                    logger.warning(f"[DEBUG] Could not resolve {lib_path}, using as-is: {resolve_err}")
                                    library_paths.add(lib_path)
                except Exception as e:
                    logger.error(f"[DEBUG] Failed to parse {vdf_path}: {e}")
        logger.info(f"[DEBUG] All detected Steam libraries: {library_paths}")
        return list(library_paths)

    def _find_shortcuts_vdf(self) -> Optional[str]:
        """Helper to find the active shortcuts.vdf file for the current Steam user."""
        try:
            from jackify.backend.services.native_steam_service import NativeSteamService
            steam_service = NativeSteamService()
            shortcuts_path = steam_service.get_shortcuts_vdf_path()
            if shortcuts_path:
                logger.info(f"Found shortcuts.vdf using multi-user detection: {shortcuts_path}")
                return str(shortcuts_path)
            logger.error("Could not determine shortcuts.vdf path using multi-user detection")
            return None
        except Exception as e:
            logger.error(f"Error using multi-user detection for shortcuts.vdf: {e}")
            return None
