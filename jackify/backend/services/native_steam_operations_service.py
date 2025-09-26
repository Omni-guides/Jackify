#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Native Steam Operations Service

This service provides direct Steam operations using VDF parsing and path discovery.
Replaces protontricks dependencies with native Steam functionality.
"""

import os
import logging
import vdf
from pathlib import Path
from typing import Dict, Optional, List
import subprocess
import shutil

logger = logging.getLogger(__name__)


class NativeSteamOperationsService:
    """
    Service providing native Steam operations for shortcut discovery and prefix management.

    Replaces protontricks functionality with:
    - Direct VDF parsing for shortcut discovery
    - Native compatdata path construction
    - Direct Steam library detection
    """

    def __init__(self, steamdeck: bool = False):
        self.steamdeck = steamdeck
        self.logger = logger

    def list_non_steam_shortcuts(self) -> Dict[str, str]:
        """
        List non-Steam shortcuts via direct VDF parsing.

        Returns:
            Dict mapping shortcut name to AppID string
        """
        logger.info("Listing non-Steam shortcuts via native VDF parsing...")
        shortcuts = {}

        try:
            # Find all possible shortcuts.vdf locations
            shortcuts_paths = self._find_shortcuts_vdf_paths()

            for shortcuts_path in shortcuts_paths:
                logger.debug(f"Checking shortcuts.vdf at: {shortcuts_path}")

                if not shortcuts_path.exists():
                    continue

                try:
                    with open(shortcuts_path, 'rb') as f:
                        data = vdf.binary_load(f)

                    shortcuts_data = data.get('shortcuts', {})
                    for shortcut_key, shortcut_data in shortcuts_data.items():
                        if isinstance(shortcut_data, dict):
                            app_name = shortcut_data.get('AppName', '').strip()
                            app_id = shortcut_data.get('appid', '')

                            if app_name and app_id:
                                # Convert to positive AppID string (compatible format)
                                positive_appid = str(abs(int(app_id)))
                                shortcuts[app_name] = positive_appid
                                logger.debug(f"Found non-Steam shortcut: '{app_name}' with AppID {positive_appid}")

                except Exception as e:
                    logger.warning(f"Error reading shortcuts.vdf at {shortcuts_path}: {e}")
                    continue

            if not shortcuts:
                logger.warning("No non-Steam shortcuts found in any shortcuts.vdf")

        except Exception as e:
            logger.error(f"Error listing non-Steam shortcuts: {e}")

        return shortcuts

    def set_steam_permissions(self, modlist_dir: str, steamdeck: bool = False) -> bool:
        """
        Handle Steam access permissions for native operations.

        Since we're using direct file access, no special permissions needed.

        Args:
            modlist_dir: Modlist directory path (for future use)
            steamdeck: Steam Deck flag (for future use)

        Returns:
            Always True (no permissions needed for native operations)
        """
        logger.debug("Using native Steam operations, no permission setting needed")
        return True

    def get_wine_prefix_path(self, appid: str) -> Optional[str]:
        """
        Get WINEPREFIX path via direct compatdata discovery.

        Args:
            appid: Steam AppID string

        Returns:
            WINEPREFIX path string or None if not found
        """
        logger.debug(f"Getting WINEPREFIX for AppID {appid} using native path discovery")

        try:
            # Find all possible compatdata locations
            compatdata_paths = self._find_compatdata_paths()

            for compatdata_base in compatdata_paths:
                prefix_path = compatdata_base / appid / "pfx"
                logger.debug(f"Checking prefix path: {prefix_path}")

                if prefix_path.exists():
                    logger.debug(f"Found WINEPREFIX: {prefix_path}")
                    return str(prefix_path)

            logger.error(f"WINEPREFIX not found for AppID {appid} in any compatdata location")
            return None

        except Exception as e:
            logger.error(f"Error getting WINEPREFIX for AppID {appid}: {e}")
            return None

    def _find_shortcuts_vdf_paths(self) -> List[Path]:
        """Find all possible shortcuts.vdf file locations"""
        paths = []

        # Standard Steam locations
        steam_locations = [
            Path.home() / ".steam/steam",
            Path.home() / ".local/share/Steam",
            Path.home() / ".var/app/com.valvesoftware.Steam/home/.steam/steam",
            Path.home() / ".var/app/com.valvesoftware.Steam/home/.local/share/Steam"
        ]

        for steam_root in steam_locations:
            if not steam_root.exists():
                continue

            # Find userdata directories
            userdata_path = steam_root / "userdata"
            if userdata_path.exists():
                for user_dir in userdata_path.iterdir():
                    if user_dir.is_dir() and user_dir.name.isdigit():
                        shortcuts_path = user_dir / "config" / "shortcuts.vdf"
                        paths.append(shortcuts_path)

        return paths

    def _find_compatdata_paths(self) -> List[Path]:
        """Find all possible compatdata directory locations"""
        paths = []

        # Standard compatdata locations
        standard_locations = [
            Path.home() / ".steam/steam/steamapps/compatdata",
            Path.home() / ".local/share/Steam/steamapps/compatdata",
            Path.home() / ".var/app/com.valvesoftware.Steam/home/.steam/steam/steamapps/compatdata",
            Path.home() / ".var/app/com.valvesoftware.Steam/home/.local/share/Steam/steamapps/compatdata"
        ]

        for path in standard_locations:
            if path.exists():
                paths.append(path)

        # Also check additional Steam libraries via libraryfolders.vdf
        try:
            from jackify.shared.paths import PathHandler
            all_steam_libs = PathHandler.get_all_steam_library_paths()

            for lib_path in all_steam_libs:
                compatdata_path = lib_path / "steamapps" / "compatdata"
                if compatdata_path.exists():
                    paths.append(compatdata_path)

        except Exception as e:
            logger.debug(f"Could not get additional Steam library paths: {e}")

        return paths