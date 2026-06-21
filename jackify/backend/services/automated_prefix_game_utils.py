#!/usr/bin/env python3
"""
Game utilities mixin for AutomatedPrefixService.

Handles game-specific operations:
- Launch options generation
- Game detection
- User directory creation
- Proton version preferences
"""
import os
import logging
from pathlib import Path
from typing import Optional, List

logger = logging.getLogger(__name__)


class GameUtilsMixin:
    """Mixin for game-related utility operations"""

    def _find_steam_game(self, app_id: str, common_names: list) -> Optional[str]:
        """Find a Steam game installation path by AppID and common names"""
        import os
        from pathlib import Path

        # Get Steam libraries from libraryfolders.vdf - check multiple possible locations
        possible_config_paths = [
            Path.home() / ".steam/steam/config/libraryfolders.vdf",
            Path.home() / ".local/share/Steam/config/libraryfolders.vdf",
            Path.home() / ".var/app/com.valvesoftware.Steam/.local/share/Steam/config/libraryfolders.vdf"  # Flatpak
        ]

        steam_config_path = None
        for path in possible_config_paths:
            if path.exists():
                steam_config_path = path
                break

        if not steam_config_path:
            return None
            
        steam_libraries = []
        try:
            with open(steam_config_path, 'r') as f:
                content = f.read()
                # Parse library paths from VDF
                import re
                library_matches = re.findall(r'"path"\s+"([^"]+)"', content)
                steam_libraries = [Path(path) / "steamapps" / "common" for path in library_matches]
        except Exception as e:
            logger.warning(f"Failed to parse Steam library folders: {e}")
            return None
        
        # Search for game in each library
        for library_path in steam_libraries:
            if not library_path.exists():
                continue
                
            # Check manifest file first (more reliable)
            manifest_path = library_path.parent / "appmanifest_{}.acf".format(app_id)
            if manifest_path.exists():
                try:
                    with open(manifest_path, 'r') as f:
                        content = f.read()
                        install_dir_match = re.search(r'"installdir"\s+"([^"]+)"', content)
                        if install_dir_match:
                            game_path = library_path / install_dir_match.group(1)
                            if game_path.exists():
                                return str(game_path)
                except Exception:
                    pass
            
            # Fallback: check common folder names
            for name in common_names:
                game_path = library_path / name
                if game_path.exists():
                    return str(game_path)
                    
        return None

    def _detect_skyrim_se_modlist(self, modlist_dir: str) -> bool:
        """
        Return True if modlist_dir is a Skyrim SE (non-VR) modlist.

        Used only to trigger first-launch seeding when special_game_type is None.
        Other games are not yet confirmed to need this treatment.
        """
        if not modlist_dir:
            return False
        try:
            mo2_ini = Path(modlist_dir) / "ModOrganizer.ini"
            if not mo2_ini.exists():
                mo2_ini = Path(modlist_dir) / "files" / "ModOrganizer.ini"
            if not mo2_ini.exists():
                return False
            content = mo2_ini.read_text(errors='ignore').lower()
            # Anchor VR check to gameName= to avoid false positives from plugin
            # setting keys like enable_skyrimVR=false appearing in SE modlists.
            for _line in content.splitlines():
                if _line.strip().startswith("gamename="):
                    game_name_value = _line.strip()[len("gamename="):]
                    if 'skyrim vr' in game_name_value or 'skyrimvr' in game_name_value:
                        return False
                    break
            return 'skyrim special edition' in content or 'skse64_loader' in content
        except Exception as e:
            logger.debug(f"Could not check Skyrim SE detection for {modlist_dir}: {e}")
        return False

    def _create_game_user_directories(self, modlist_compatdata_path: str, special_game_type: str,
                                      modlist_dir: Optional[str] = None):
        """
        Pre-create game-specific user directories to prevent first-launch issues.

        Creates both My Documents/My Games and AppData/Local directories for the game.
        special_game_type covers FNV/FO3/Enderal (vanilla-compatdata games). For standard
        games like Skyrim SE that aren't "special" in that sense, modlist_dir is used to
        detect what directories to seed.
        """
        # Bethesda-pattern games: same name used for both My Games and AppData/Local
        game_dir_names = {
            "skyrim": "Skyrim Special Edition",
            "skyrimvr": "Skyrim VR",
            "fnv": "FalloutNV",
            "fo3": "Fallout3",
            "fo4": "Fallout4",
            "fallout4vr": "Fallout4VR",
            "oblivion": "Oblivion",
            "oblivion_remastered": "Oblivion Remastered",
            "enderal": "Enderal Special Edition",
            "starfield": "Starfield",
        }

        # Non-Bethesda games: AppData/Local only, with a vendor-namespaced subdirectory
        game_appdata_only = {
            "cp2077": os.path.join("CD Projekt Red", "Cyberpunk 2077"),
            "bg3": os.path.join("Larian Studios", "Baldur's Gate 3"),
        }

        # special_game_type covers FNV/FO3/Enderal (vanilla-compatdata games).
        # Skyrim SE returns None from detect_special_game_type but still needs seeding.
        game_type = special_game_type
        if special_game_type is None and modlist_dir and self._detect_skyrim_se_modlist(modlist_dir):
            game_type = "skyrim"

        base_path = os.path.join(modlist_compatdata_path, "pfx", "drive_c", "users", "steamuser")

        if game_type in game_appdata_only:
            appdata_dir = os.path.join(base_path, "AppData", "Local", game_appdata_only[game_type])
            try:
                os.makedirs(appdata_dir, exist_ok=True)
                logger.info(f"Created AppData/Local directory: {appdata_dir}")
            except Exception as e:
                logger.warning(f"Failed to create AppData/Local directory {appdata_dir}: {e}")
            return

        game_dir_name = game_dir_names.get(game_type)
        if not game_dir_name:
            logger.debug(f"No user directory mapping for game type: {game_type}")
            return

        directories_to_create = [
            os.path.join(base_path, "Documents", "My Games", game_dir_name),
            os.path.join(base_path, "AppData", "Local", game_dir_name),
        ]

        created_count = 0
        for directory in directories_to_create:
            try:
                os.makedirs(directory, exist_ok=True)
                logger.info(f"Created user directory: {directory}")
                created_count += 1
            except Exception as e:
                logger.warning(f"Failed to create directory {directory}: {e}")

        if created_count > 0:
            logger.info(f"Created {created_count} user directories for {game_dir_name}")

        if game_type == "skyrim":
            self._seed_skyrim_first_launch_files(base_path, game_dir_name)
        elif game_type == "fo4":
            self._seed_fo4_first_launch_files(base_path, game_dir_name)
        elif game_type == "skyrimvr":
            self._seed_skyrimvr_first_launch_files(base_path, game_dir_name)
        elif game_type == "fallout4vr":
            self._seed_fallout4vr_first_launch_files(base_path, game_dir_name)
    def _seed_skyrim_first_launch_files(self, prefix_user: str, docs_dir_name: str) -> None:
        """Delegate to FileSystemHandler to seed Skyrim first-launch fix files."""
        try:
            from jackify.backend.handlers.filesystem_handler import FileSystemHandler
            fsh = FileSystemHandler()
            fsh._seed_skyrim_first_launch_files(prefix_user, docs_dir_name)
        except Exception as e:
            logger.warning(f"Could not seed Skyrim first-launch files: {e}")

    def _seed_fo4_first_launch_files(self, prefix_user: str, docs_dir_name: str) -> None:
        """Delegate to FileSystemHandler to seed Fallout 4 first-launch fix files."""
        try:
            from jackify.backend.handlers.filesystem_handler import FileSystemHandler
            fsh = FileSystemHandler()
            fsh._seed_fo4_first_launch_files(prefix_user, docs_dir_name)
        except Exception as e:
            logger.warning(f"Could not seed FO4 first-launch files: {e}")

    def _seed_skyrimvr_first_launch_files(self, prefix_user: str, docs_dir_name: str) -> None:
        """Delegate to FileSystemHandler to seed Skyrim VR first-launch fix files."""
        try:
            from jackify.backend.handlers.filesystem_handler import FileSystemHandler
            fsh = FileSystemHandler()
            fsh._seed_skyrimvr_first_launch_files(prefix_user, docs_dir_name)
        except Exception as e:
            logger.warning(f"Could not seed SkyrimVR first-launch files: {e}")

    def _seed_fallout4vr_first_launch_files(self, prefix_user: str, docs_dir_name: str) -> None:
        """Delegate to FileSystemHandler to seed Fallout 4 VR first-launch fix files."""
        try:
            from jackify.backend.handlers.filesystem_handler import FileSystemHandler
            fsh = FileSystemHandler()
            fsh._seed_fallout4vr_first_launch_files(prefix_user, docs_dir_name)
        except Exception as e:
            logger.warning(f"Could not seed FO4VR first-launch files: {e}")
