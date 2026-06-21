#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Game path and compatdata mixin for PathHandler.
Extracted from path_handler for file-size and domain separation.
"""

import os
import re
import logging
from pathlib import Path
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)


class PathHandlerGameMixin:
    """Mixin providing game install path and compatdata discovery."""

    @classmethod
    def find_compat_data(cls, appid: str) -> Optional[Path]:
        """Find the compatdata directory for a given AppID."""
        if not appid:
            logger.error(f"Invalid AppID provided for compatdata search: {appid}")
            return None
        appid_clean = appid.lstrip('-')
        if not appid_clean.isdigit():
            logger.error(f"Invalid AppID provided for compatdata search: {appid}")
            return None
        logger.debug(f"Searching for compatdata directory for AppID: {appid}")
        library_paths = cls.get_all_steam_library_paths()
        if library_paths:
            logger.debug(f"Checking compatdata in {len(library_paths)} Steam libraries")
            for library_path in library_paths:
                compatdata_base = library_path / "steamapps" / "compatdata"
                if not compatdata_base.is_dir():
                    logger.debug(f"Compatdata directory does not exist: {compatdata_base}")
                    continue
                potential_path = compatdata_base / appid
                if potential_path.is_dir():
                    logger.info(f"Found compatdata directory: {potential_path}")
                    return potential_path
                logger.debug(f"Compatdata for AppID {appid} not found in {compatdata_base}")
        is_flatpak_steam = any('.var/app/com.valvesoftware.Steam' in str(lib) for lib in library_paths) if library_paths else False
        if not library_paths or is_flatpak_steam:
            logger.debug("Checking fallback compatdata locations...")
            if is_flatpak_steam:
                fallback_locations = [
                    Path.home() / ".var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/compatdata",
                    Path.home() / ".var/app/com.valvesoftware.Steam/data/Steam/steamapps/compatdata",
                ]
            else:
                fallback_locations = [
                    Path.home() / ".local/share/Steam/steamapps/compatdata",
                    Path.home() / ".steam/steam/steamapps/compatdata",
                ]
            for compatdata_base in fallback_locations:
                if compatdata_base.is_dir():
                    potential_path = compatdata_base / appid
                    if potential_path.is_dir():
                        logger.warning(f"Found compatdata directory in fallback location: {potential_path}")
                        return potential_path
        logger.warning(f"Compatdata directory for AppID {appid} not found in any Steam library or fallback location.")
        return None

    @staticmethod
    def detect_stock_game_path(game_type: str, steam_library: Path) -> Optional[Path]:
        """Detect the stock game path for a given game type and Steam library."""
        try:
            game_app_ids = {
                'skyrim': '489830', 'fallout4': '377160', 'fnv': '22380', 'oblivion': '22330'
            }
            if game_type not in game_app_ids:
                return None
            app_id = game_app_ids[game_type]
            game_path = steam_library / 'steamapps' / 'common'
            possible_names = {
                'skyrim': ['Skyrim Special Edition', 'Skyrim'],
                'fallout4': ['Fallout 4'],
                'fnv': ['Fallout New Vegas', 'FalloutNV'],
                'oblivion': ['Oblivion']
            }
            if game_type not in possible_names:
                return None
            for name in possible_names[game_type]:
                potential_path = game_path / name
                if potential_path.exists():
                    return potential_path
            return None
        except Exception as e:
            logging.error(f"Error detecting stock game path: {e}")
            return None

    @classmethod
    def find_game_install_paths(cls, target_appids: Dict[str, str]) -> Dict[str, Path]:
        """Find installation paths for multiple specified games using Steam app IDs."""
        library_paths = cls.get_all_steam_library_paths()
        if not library_paths:
            logger.warning("Failed to find any Steam library paths")
            return {}
        results = {}
        for library_path in library_paths:
            common_dir = library_path / "steamapps" / "common"
            if not common_dir.is_dir():
                logger.debug(f"No 'steamapps/common' directory in library: {library_path}")
                continue
            try:
                game_dirs = [d for d in common_dir.iterdir() if d.is_dir()]
            except (PermissionError, OSError) as e:
                logger.warning(f"Cannot access directory {common_dir}: {e}")
                continue
            for game_name, app_id in target_appids.items():
                if game_name in results:
                    continue
                appmanifest_path = library_path / "steamapps" / f"appmanifest_{app_id}.acf"
                if appmanifest_path.is_file():
                    try:
                        with open(appmanifest_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                            match = re.search(r'"installdir"\s+"([^"]+)"', content)
                            if match:
                                install_dir_name = match.group(1)
                                install_path = common_dir / install_dir_name
                                if install_path.is_dir():
                                    results[game_name] = install_path
                                    logger.info(f"Found {game_name} at {install_path}")
                                    continue
                    except Exception as e:
                        logger.warning(f"Error reading appmanifest for {game_name}: {e}")
        return results

    @classmethod
    def find_vanilla_game_paths(cls, game_names=None) -> Dict[str, Path]:
        """Locate vanilla game installations via Steam, Heroic GOG, or Heroic Epic."""
        GAME_TYPE_MAP = {
            "Skyrim Special Edition": "skyrim",
            "Fallout 4":              "fallout4",
            "Fallout New Vegas":      "falloutnv",
            "Oblivion":               "oblivion",
            "Fallout 3":              "fallout3",
        }
        if game_names is None:
            game_names = list(GAME_TYPE_MAP.keys())

        from jackify.backend.handlers.vanilla_game_finder import VanillaGameFinder
        finder = VanillaGameFinder()
        found_games = {}
        for game in game_names:
            game_type = GAME_TYPE_MAP.get(game)
            if not game_type:
                continue
            result = finder.find(game_type)
            if result:
                path, store = result
                found_games[game] = path
                logger.info("Found vanilla game %s via %s at %s", game, store, path)
            else:
                logger.debug("No installation found for %s", game)
        return found_games

    def _detect_stock_game_path(self) -> bool:
        """Detects common Stock Game or Game Root directories within the modlist path. Expects self.logger, self.modlist_dir, self.stock_game_path."""
        self.logger.info("Step 7a: Detecting Stock Game/Game Root directory...")
        if not self.modlist_dir:
            self.logger.error("Modlist directory not set, cannot detect stock game path.")
            return False
        modlist_path = Path(self.modlist_dir)
        preferred_order = [
            "Stock Game", "StockGame", "STOCK GAME", "Skyrim Stock", "Stock Game Folder",
            "Stock Folder", Path("root/Skyrim Special Edition"), "Game Root"
        ]
        found_path = None
        for name in preferred_order:
            potential_path = modlist_path / name
            if potential_path.is_dir():
                found_path = str(potential_path)
                self.logger.info(f"Found potential stock game directory: {found_path}")
                break
        if found_path:
            self.stock_game_path = found_path
            return True
        self.stock_game_path = None
        searched = [str(modlist_path / n) for n in preferred_order]
        self.logger.info(f"No common Stock Game/Game Root directory found (searched: {searched}). Will assume vanilla game path is needed for some operations.")
        return True
