"""
VanillaGameFinder

Locates vanilla game installations across Steam and Heroic (GOG/Epic)
without requiring manual path entry from the user.

Detection order: Steam appmanifest -> Heroic GOG -> Heroic Epic.
No manual path override is offered here; that belongs in user settings.
"""
import json
import logging
import re
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple

logger = logging.getLogger(__name__)

# Store identifiers returned alongside the detected path.
STORE_STEAM = "steam"
STORE_GOG = "gog"
STORE_EPIC = "epic"
STORE_UNKNOWN = "unknown"

GameLocation = Tuple[Path, str]  # (path, store)


class SteamEntry(NamedTuple):
    app_id: str
    dir_names: List[str]


# Maps Jackify game_type -> ordered list of Steam candidates to try.
# Multiple entries handle games with ambiguous type strings (e.g. skyrim = SSE or LE).
_STEAM_CATALOG: Dict[str, List[SteamEntry]] = {
    'skyrim': [
        SteamEntry('489830', ['Skyrim Special Edition']),
        SteamEntry('72850', ['Skyrim']),
    ],
    'skyrimvr': [SteamEntry('611670', ['Skyrim VR'])],
    'fallout4': [SteamEntry('377160', ['Fallout 4'])],
    'fallout4vr': [SteamEntry('611660', ['Fallout 4 VR'])],
    'falloutnv': [SteamEntry('22380', ['Fallout New Vegas', 'FalloutNV'])],
    'fallout3': [
        SteamEntry('22300', ['Fallout 3', 'Fallout3']),
        SteamEntry('22370', ['Fallout 3 goty', 'Fallout 3 GOTY', 'Fallout3']),
    ],
    'oblivion': [SteamEntry('22330', ['Oblivion'])],
    'oblivion_remastered': [SteamEntry('2623190', ['Oblivion Remastered'])],
    'morrowind': [SteamEntry('22320', ['Morrowind'])],
    'starfield': [SteamEntry('1716740', ['Starfield'])],
    'enderal': [
        SteamEntry('976620', ['Enderal Special Edition']),
        SteamEntry('933480', ['Enderal Forgotten Stories', 'Enderal']),
    ],
    'bg3': [SteamEntry('1086940', ['Baldurs Gate 3', "Baldur's Gate 3"])],
    'cp2077': [SteamEntry('1091500', ['Cyberpunk 2077'])],
    'witcher3': [SteamEntry('292030', ['The Witcher 3 Wild Hunt', 'The Witcher 3: Wild Hunt'])],
    'darksouls3': [SteamEntry('374320', ['DARK SOULS III'])],
    'eldenring': [SteamEntry('1245620', ['ELDEN RING'])],
    'sekiro': [SteamEntry('814380', ['Sekiro'])],
    'mountandblade2': [SteamEntry('261550', ['Mount & Blade II Bannerlord'])],
    'stardewvalley': [SteamEntry('413150', ['Stardew Valley'])],
    'dragonageinquisition': [SteamEntry('1222690', ['Dragon Age Inquisition'])],
    'hogwartslegacy': [SteamEntry('990080', ['Hogwarts Legacy'])],
}

# Maps Jackify game_type -> list of GOG app IDs (appName in installed.json).
# Source: Fluorine-Manager/libs/basic_games/gog_utils.py approach + CLF3 known_games.rs IDs.
_HEROIC_GOG_CATALOG: Dict[str, List[str]] = {
    'falloutnv':            ['1454587428'],
    'fallout3':             ['1454315831'],
    'oblivion':             ['1458058109'],
    'morrowind':            ['1440163901'],
    'bg3':                  ['1456460669'],
    'cp2077':               ['1423049311'],
    'witcher3':             ['1495134320'],
    'skyrim':               ['1711230643'],
    'stardewvalley':        ['1453375253'],
}

# Maps Jackify game_type -> list of Epic/Legendary app_name slugs (installed.json key).
_HEROIC_EPIC_CATALOG: Dict[str, List[str]] = {
    'fallout3':             ['adeae8bbfc94427db57c7dfecce3f1d4'],
    'falloutnv':            ['5daeb974a22a435988892319b3a4f476'],
}

# Epic installs some games into a language-specific subdirectory inside the install root.
# Maps game_type -> glob pattern to find the real game directory one level down.
# Language suffix varies (English, German, French, ...) so we glob rather than hardcode.
_EPIC_SUBDIR_GLOB: Dict[str, str] = {
    'fallout3':  'Fallout 3 GOTY *',
    'falloutnv': 'Fallout New Vegas *',
}

# Candidate Heroic config roots: native install then Flatpak.
_HEROIC_CONFIG_ROOTS: List[Path] = [
    Path.home() / '.config' / 'heroic',
    Path.home() / '.var' / 'app' / 'com.heroicgameslauncher.hgl' / 'config' / 'heroic',
]


class VanillaGameFinder:
    """
    Locates vanilla (store-installed) game directories for a given Jackify game_type.
    Returns a (Path, store) tuple so callers can warn when the game is not on Steam.
    Searches Steam first, then Heroic-managed stores (GOG, Epic).
    """

    def find(self, game_type: str) -> Optional[GameLocation]:
        """
        Return (path, store) for the detected game installation, or None.
        store is one of: 'steam', 'gog', 'epic', 'unknown'.
        """
        result = self._find_steam(game_type)
        if result:
            logger.info("VanillaGameFinder: found %s via Steam at %s", game_type, result)
            return result, STORE_STEAM

        result = self._find_heroic(game_type)
        if result:
            path, store = result
            logger.info("VanillaGameFinder: found %s via %s at %s", game_type, store, path)
            return path, store

        logger.debug("VanillaGameFinder: no installation found for %s", game_type)
        return None

    # ------------------------------------------------------------------
    # Steam
    # ------------------------------------------------------------------

    def _find_steam(self, game_type: str) -> Optional[Path]:
        entries = _STEAM_CATALOG.get(game_type)
        if not entries:
            return None
        try:
            from jackify.backend.handlers.path_handler_steam import PathHandlerSteamMixin
            library_paths = PathHandlerSteamMixin.get_all_steam_library_paths()
        except Exception as e:
            logger.debug("Steam library path detection failed: %s", e)
            return None

        for library in library_paths:
            steamapps = library / 'steamapps'
            if not steamapps.is_dir():
                continue
            for entry in entries:
                path = self._check_steam_entry(steamapps, entry)
                if path:
                    return path
        return None

    def _check_steam_entry(self, steamapps: Path, entry: SteamEntry) -> Optional[Path]:
        manifest = steamapps / f'appmanifest_{entry.app_id}.acf'
        if not manifest.is_file():
            return None
        try:
            content = manifest.read_text(encoding='utf-8', errors='replace')
            state_match = re.search(r'"StateFlags"\s+"(\d+)"', content)
            if state_match and not (int(state_match.group(1)) & 4):
                logger.debug("Skipping %s: StateFlags=%s (not fully installed)", manifest.name, state_match.group(1))
                return None
            match = re.search(r'"installdir"\s+"([^"]+)"', content)
            if match:
                path = steamapps / 'common' / match.group(1)
                if path.is_dir():
                    return path
            for name in entry.dir_names:
                fallback = steamapps / 'common' / name
                if fallback.is_dir():
                    return fallback
        except OSError as e:
            logger.debug("Could not read appmanifest %s: %s", manifest, e)
        return None

    # ------------------------------------------------------------------
    # Heroic (GOG via gog_store/installed.json, Epic via legendaryConfig)
    # Approach adapted from Fluorine-Manager/libs/basic_games/gog_utils.py
    # ------------------------------------------------------------------

    def _find_heroic(self, game_type: str) -> Optional[Tuple[Path, str]]:
        gog_ids = _HEROIC_GOG_CATALOG.get(game_type)
        if gog_ids:
            path = self._find_heroic_gog(gog_ids)
            if path:
                return path, STORE_GOG

        epic_ids = _HEROIC_EPIC_CATALOG.get(game_type)
        if epic_ids:
            path = self._find_heroic_epic(epic_ids, game_type=game_type)
            if path:
                return path, STORE_EPIC

        return None

    def _find_heroic_gog(self, app_ids: List[str]) -> Optional[Path]:
        id_set = set(app_ids)
        for config_root in _HEROIC_CONFIG_ROOTS:
            installed_file = config_root / 'gog_store' / 'installed.json'
            if not installed_file.is_file():
                continue
            try:
                data = json.loads(installed_file.read_text(encoding='utf-8'))
            except (OSError, json.JSONDecodeError) as e:
                logger.debug("Could not read Heroic GOG installed.json %s: %s", installed_file, e)
                continue
            for entry in data.get('installed', []):
                if not isinstance(entry, dict):
                    continue
                if entry.get('appName') not in id_set:
                    continue
                install_path = entry.get('install_path') or entry.get('installPath', '')
                if install_path:
                    path = Path(install_path)
                    if path.is_dir():
                        return path
        return None

    def _find_heroic_epic(self, app_ids: List[str], game_type: str = '') -> Optional[Path]:
        id_set = set(app_ids)
        subdir_glob = _EPIC_SUBDIR_GLOB.get(game_type, '')
        for config_root in _HEROIC_CONFIG_ROOTS:
            installed_file = config_root / 'legendaryConfig' / 'legendary' / 'installed.json'
            if not installed_file.is_file():
                continue
            try:
                data = json.loads(installed_file.read_text(encoding='utf-8'))
            except (OSError, json.JSONDecodeError) as e:
                logger.debug("Could not read Heroic Epic installed.json %s: %s", installed_file, e)
                continue
            for app_name, entry in data.items():
                if not isinstance(entry, dict):
                    continue
                if app_name not in id_set:
                    continue
                install_path = entry.get('install_path', '')
                if not install_path:
                    continue
                path = Path(install_path)
                if not path.is_dir():
                    continue
                # Epic installs some titles into a language-specific subdirectory.
                # Glob for it rather than hardcoding the language suffix.
                if subdir_glob:
                    matches = sorted(path.glob(subdir_glob))
                    if matches:
                        logger.debug("Epic subdir match for %s: %s", game_type, matches[0])
                        return matches[0]
                return path
        return None
