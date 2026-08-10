#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Proton scanning and selection mixin for WineUtils.
Extracted from wine_utils for file-size and domain separation.
"""

import os
import re
import logging
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any

logger = logging.getLogger(__name__)

VALVE_PROTON_APPID_MAP = {
    '2805730': 'proton_9',
    '3658110': 'proton_10',
    '4628710': 'proton_11',
    '1493710': 'proton_experimental',
    '2180100': 'proton_hotfix',
    '1887720': 'proton_8',
}

VALVE_PROTON_DIR_PATTERN = re.compile(r'^Proton (\d+)\.\d+(?: \(Beta\))?$')


class WineUtilsProtonMixin:
    """Mixin providing Proton scanning, selection, and path resolution."""

    @staticmethod
    def get_proton_version(compat_data_path: str) -> str:
        """
        Detect the Proton version used by a Steam game/shortcut.

        Args:
            compat_data_path: Path to the compatibility data directory.

        Returns:
            Detected Proton version or 'Unknown' if not found.
        """
        logger.info("Detecting Proton version...")
        if not os.path.isdir(compat_data_path):
            logger.warning(f"Compatdata directory not found at '{compat_data_path}'")
            return "Unknown"
        system_reg_path = os.path.join(compat_data_path, "pfx", "system.reg")
        if os.path.isfile(system_reg_path):
            try:
                with open(system_reg_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                match = re.search(r'"SteamClientProtonVersion"="([^"]+)"', content)
                if match:
                    version = match.group(1).strip()
                    proton_ver = version if "GE" in version else f"Proton {version}"
                    logger.debug(f"Detected Proton version from registry: {proton_ver}")
                    return proton_ver
            except Exception as e:
                logger.debug(f"Error reading system.reg: {e}")
        config_info_path = os.path.join(compat_data_path, "config_info")
        if os.path.isfile(config_info_path):
            try:
                with open(config_info_path, "r") as f:
                    config_ver = f.readline().strip()
                if config_ver:
                    proton_ver = config_ver if "GE" in config_ver else f"Proton {config_ver}"
                    logger.debug(f"Detected Proton version from config_info: {proton_ver}")
                    return proton_ver
            except Exception as e:
                logger.debug(f"Error reading config_info: {e}")
        logger.warning("Could not detect Proton version")
        return "Unknown"

    @staticmethod
    def find_proton_binary(proton_version: str) -> Optional[str]:
        """
        Find the full path to the Proton binary given a version string.
        Returns the path to 'files/bin/wine', or None if not found.
        """
        version_patterns = [proton_version, proton_version.replace(' ', '_'), proton_version.replace(' ', '')]
        steam_common_paths = []
        compatibility_paths = []
        try:
            from .path_handler import PathHandler
            root_steam_libs = PathHandler.get_all_steam_library_paths()
            for lib_path in root_steam_libs:
                lib = Path(lib_path)
                if lib.exists():
                    common_path = lib / "steamapps/common"
                    if common_path.exists():
                        steam_common_paths.append(common_path)
                    compatibility_paths.append(lib / "compatibilitytools.d")
        except Exception as e:
            logger.warning(f"Could not detect Steam libraries from libraryfolders.vdf: {e}")
        if not steam_common_paths:
            steam_common_paths = [
                Path.home() / ".steam/steam/steamapps/common",
                Path.home() / ".local/share/Steam/steamapps/common",
                Path.home() / ".steam/root/steamapps/common"
            ]
        if not compatibility_paths:
            compatibility_paths = [
                Path.home() / ".steam/steam/compatibilitytools.d",
                Path.home() / ".local/share/Steam/compatibilitytools.d"
            ]
        compatibility_paths.extend([
            Path.home() / ".steam/root/compatibilitytools.d",
            Path.home() / ".var/app/com.valvesoftware.Steam/.local/share/Steam/compatibilitytools.d",
            Path.home() / ".var/app/com.valvesoftware.Steam.CompatibilityTool.Proton-GE/.local/share/Steam/compatibilitytools.d",
            Path.home() / ".var/app/com.valvesoftware.Steam/.local/share/Steam/compatibilitytools.d/GE-Proton"
        ])
        if proton_version.strip().startswith("Proton 9"):
            proton9_candidates = ["Proton 9.0", "Proton 9.0 (Beta)"]
            for base_path in steam_common_paths:
                for name in proton9_candidates:
                    candidate = base_path / name / "files/bin/wine"
                    if candidate.is_file():
                        return str(candidate)
                for subdir in base_path.glob("Proton 9*"):
                    wine_bin = subdir / "files/bin/wine"
                    if wine_bin.is_file():
                        return str(wine_bin)
        all_paths = steam_common_paths + compatibility_paths
        for base_path in all_paths:
            if not base_path.is_dir():
                continue
            for pattern in version_patterns:
                proton_dir = base_path / pattern
                wine_bin = proton_dir / "files/bin/wine"
                if wine_bin.is_file():
                    return str(wine_bin)
                for subdir in base_path.glob(f"*{pattern}*"):
                    wine_bin = subdir / "files/bin/wine"
                    if wine_bin.is_file():
                        return str(wine_bin)
        try:
            from .config_handler import ConfigHandler
            config = ConfigHandler()
            fallback_path = config.get_proton_path()
            if fallback_path != 'auto':
                fallback_wine_bin = Path(fallback_path) / "files/bin/wine"
                if fallback_wine_bin.is_file():
                    logger.info(f"Requested Proton version '{proton_version}' not found. Falling back to user's configured version.")
                    return str(fallback_wine_bin)
        except Exception:
            pass
        for base_path in steam_common_paths:
            wine_bin = base_path / "Proton - Experimental" / "files/bin/wine"
            if wine_bin.is_file():
                logger.warning(f"Requested Proton version '{proton_version}' not found. Falling back to 'Proton - Experimental'.")
                return str(wine_bin)
        return None

    @staticmethod
    def get_proton_paths(appid: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Get the Proton paths for a given AppID.
        Returns (compatdata_path, proton_path, wine_bin) or (None, None, None) if not found.
        """
        logger.info(f"Getting Proton paths for AppID {appid}")
        possible_compat_bases = [
            Path.home() / ".steam/steam/steamapps/compatdata",
            Path.home() / ".local/share/Steam/steamapps/compatdata"
        ]
        compatdata_path = None
        for base_path in possible_compat_bases:
            potential_compat_path = base_path / appid
            if potential_compat_path.is_dir():
                compatdata_path = str(potential_compat_path)
                logger.debug(f"Found compatdata directory: {compatdata_path}")
                break
        if not compatdata_path:
            logger.error(f"Could not find compatdata directory for AppID {appid}")
            return None, None, None
        proton_version = WineUtilsProtonMixin.get_proton_version(compatdata_path)
        if proton_version == "Unknown":
            logger.error(f"Could not determine Proton version for AppID {appid}")
            return None, None, None
        wine_bin = WineUtilsProtonMixin.find_proton_binary(proton_version)
        if not wine_bin:
            logger.error(f"Could not find Proton binary for version {proton_version}")
            return None, None, None
        proton_path = str(Path(wine_bin).parent.parent)
        logger.debug(f"Found Proton path: {proton_path}")
        return compatdata_path, proton_path, wine_bin

    @staticmethod
    def get_steam_library_paths() -> List[Path]:
        """Get all Steam library paths from libraryfolders.vdf."""
        steam_common_paths = []
        try:
            from .path_handler import PathHandler
            library_paths = PathHandler.get_all_steam_library_paths()
            logger.info(f"PathHandler found Steam libraries: {library_paths}")
            for lib_path in library_paths:
                common_path = lib_path / "steamapps" / "common"
                if common_path.exists():
                    steam_common_paths.append(common_path)
                    logger.debug(f"Added Steam library: {common_path}")
                else:
                    logger.debug(f"Steam library path doesn't exist: {common_path}")
        except Exception as e:
            logger.error(f"PathHandler failed to read libraryfolders.vdf: {e}")
        fallback_paths = [
            Path.home() / ".steam/steam/steamapps/common",
            Path.home() / ".local/share/Steam/steamapps/common",
            Path.home() / ".steam/root/steamapps/common"
        ]
        for fallback_path in fallback_paths:
            if fallback_path.exists() and fallback_path not in steam_common_paths:
                steam_common_paths.append(fallback_path)
                logger.debug(f"Added fallback Steam library: {fallback_path}")
        logger.info(f"Final Steam library paths for Proton scanning: {steam_common_paths}")
        return steam_common_paths

    @staticmethod
    def get_compatibility_tool_paths() -> List[Path]:
        """Get all compatibility tool paths for GE-Proton and other custom Proton versions."""
        compat_paths = [
            Path.home() / ".steam/steam/compatibilitytools.d",
            Path.home() / ".local/share/Steam/compatibilitytools.d",
            Path.home() / ".steam/root/compatibilitytools.d",
            Path.home() / ".var/app/com.valvesoftware.Steam/.local/share/Steam/compatibilitytools.d",
            Path.home() / ".var/app/com.valvesoftware.Steam.CompatibilityTool.Proton-GE/.local/share/Steam/compatibilitytools.d",
            Path.home() / ".var/app/com.valvesoftware.Steam/.local/share/Steam/compatibilitytools.d/GE-Proton",
            Path("/usr/share/steam/compatibilitytools.d"),
            Path("/usr/lib/steam/compatibilitytools.d"),
        ]
        seen_real = set()
        result = []
        for path in compat_paths:
            if path.exists():
                real = path.resolve()
                if real not in seen_real:
                    seen_real.add(real)
                    result.append(path)
        return result

    @staticmethod
    def _parse_compat_tool_name(proton_dir: Path) -> Optional[str]:
        """Parse the Steam internal name from a compatibilitytool.vdf file."""
        vdf_path = proton_dir / "compatibilitytool.vdf"
        if not vdf_path.exists():
            return None
        try:
            with open(vdf_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            match = re.search(r'"compat_tools"\s*\{[^{]*"([^"]+)"\s*(?://[^\n]*)?\s*\{', content, re.DOTALL)
            if match:
                return match.group(1)
        except Exception as e:
            logger.warning(f"Failed to parse {vdf_path}: {e}")
        return None

    @staticmethod
    def _find_valve_proton_appid(proton_dir_name: str) -> Optional[str]:
        """Find the Steam App ID for a Valve Proton by matching appmanifest installdir."""
        steam_libs = WineUtilsProtonMixin.get_steam_library_paths()
        for lib_path in steam_libs:
            steamapps_dir = lib_path.parent
            for manifest in steamapps_dir.glob("appmanifest_*.acf"):
                try:
                    with open(manifest, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                    installdir_match = re.search(r'"installdir"\s+"([^"]+)"', content)
                    appid_match = re.search(r'"appid"\s+"(\d+)"', content)
                    if installdir_match and appid_match and installdir_match.group(1) == proton_dir_name:
                        return appid_match.group(1)
                except Exception:
                    continue
        return None

    @staticmethod
    def resolve_steam_compat_name(proton_path: Any) -> Optional[str]:
        """
        Resolve the correct Steam config.vdf internal name for a Proton installation.
        Returns internal name for CompatToolMapping, or None if unresolvable.
        """
        proton_path = Path(proton_path)
        if not proton_path.is_dir():
            logger.warning(f"Proton path not found: {proton_path}")
            return None
        compat_name = WineUtilsProtonMixin._parse_compat_tool_name(proton_path)
        if compat_name:
            logger.debug(f"Resolved compat name from vdf: {proton_path.name} -> {compat_name}")
            return compat_name
        dir_name = proton_path.name
        appid = WineUtilsProtonMixin._find_valve_proton_appid(dir_name)
        if appid and appid in VALVE_PROTON_APPID_MAP:
            name = VALVE_PROTON_APPID_MAP[appid]
            logger.debug(f"Resolved Valve Proton: {dir_name} (AppID {appid}) -> {name}")
            return name
        if dir_name.startswith('GE-Proton'):
            return dir_name
        version_match = VALVE_PROTON_DIR_PATTERN.match(dir_name)
        if version_match:
            name = f"proton_{version_match.group(1)}"
            logger.debug(f"Derived Valve Proton name from directory: {dir_name} -> {name}")
            return name
        logger.warning(f"Could not resolve Steam compat name for: {proton_path}")
        return None

    @staticmethod
    def scan_thirdparty_proton_versions() -> List[Dict[str, Any]]:
        """Scan for non-GE third-party Proton versions in compatibilitytools.d directories."""
        logger.info("Scanning for third-party Proton versions...")
        found_versions = []
        seen_names = set()
        compat_paths = WineUtilsProtonMixin.get_compatibility_tool_paths()
        if not compat_paths:
            return []
        for compat_path in compat_paths:
            try:
                for proton_dir in compat_path.iterdir():
                    if not proton_dir.is_dir():
                        continue
                    dir_name = proton_dir.name
                    if dir_name.startswith("GE-Proton"):
                        continue
                    wine_bin = proton_dir / "files" / "bin" / "wine"
                    if not wine_bin.exists():
                        continue
                    compat_name = WineUtilsProtonMixin._parse_compat_tool_name(proton_dir)
                    if not compat_name:
                        continue
                    vdf_path = proton_dir / "compatibilitytool.vdf"
                    try:
                        with open(vdf_path, 'r', encoding='utf-8', errors='ignore') as f:
                            vdf_content = f.read()
                        if '"from_oslist"  "linux"' in vdf_content:
                            continue
                    except Exception:
                        pass
                    if 'hotfix' in compat_name.lower():
                        continue
                    if compat_name in seen_names:
                        continue
                    seen_names.add(compat_name)
                    found_versions.append({
                        'name': dir_name,
                        'path': proton_dir,
                        'wine_bin': wine_bin,
                        'priority': 175,
                        'type': 'ThirdParty-Proton',
                        'steam_compat_name': compat_name,
                    })
                    logger.debug(f"Found third-party Proton: {dir_name} (compat name: {compat_name})")
            except Exception as e:
                logger.warning(f"Error scanning {compat_path}: {e}")
        logger.info(f"Found {len(found_versions)} third-party Proton version(s)")
        return found_versions

    @staticmethod
    def scan_ge_proton_versions() -> List[Dict[str, Any]]:
        """Scan for available GE-Proton versions in compatibilitytools.d directories."""
        logger.info("Scanning for available GE-Proton versions...")
        found_versions = []
        compat_paths = WineUtilsProtonMixin.get_compatibility_tool_paths()
        if not compat_paths:
            logger.warning("No compatibility tool paths found")
            return []
        for compat_path in compat_paths:
            logger.debug(f"Scanning compatibility tools: {compat_path}")
            try:
                for proton_dir in compat_path.iterdir():
                    if not proton_dir.is_dir():
                        continue
                    dir_name = proton_dir.name
                    if not dir_name.startswith("GE-Proton"):
                        continue
                    wine_bin = proton_dir / "files" / "bin" / "wine"
                    if not wine_bin.exists() or not wine_bin.is_file():
                        logger.debug(f"Skipping {dir_name} - no wine binary found")
                        continue
                    version_match = re.match(r'GE-Proton(\d+)-(\d+)', dir_name)
                    if version_match:
                        major_ver = int(version_match.group(1))
                        minor_ver = int(version_match.group(2))
                        priority = 200 + (major_ver * 10) + minor_ver  # kept for backward compat; sort uses tuple key
                        compat_name = WineUtilsProtonMixin._parse_compat_tool_name(proton_dir) or dir_name
                        found_versions.append({
                            'name': dir_name,
                            'path': proton_dir,
                            'wine_bin': wine_bin,
                            'priority': priority,
                            'major_version': major_ver,
                            'minor_version': minor_ver,
                            'type': 'GE-Proton',
                            'steam_compat_name': compat_name,
                        })
                        logger.debug(f"Found {dir_name} at {proton_dir} (priority: {priority})")
                    else:
                        logger.debug(f"Skipping {dir_name} - unknown GE-Proton version format")
            except Exception as e:
                logger.warning(f"Error scanning {compat_path}: {e}")
        found_versions.sort(key=lambda x: (x['major_version'], x['minor_version']), reverse=True)
        logger.info(f"Found {len(found_versions)} GE-Proton version(s)")
        return found_versions

    @staticmethod
    def scan_valve_proton_versions() -> List[Dict[str, Any]]:
        """Scan for available Valve Proton versions. Discovers all installed X.Y releases dynamically."""
        logger.info("Scanning for available Valve Proton versions...")
        found_versions = []
        seen_names: set = set()
        steam_libs = WineUtilsProtonMixin.get_steam_library_paths()
        if not steam_libs:
            logger.warning("No Steam library paths found")
            return []

        for steam_path in steam_libs:
            if not steam_path.is_dir():
                continue
            for entry in steam_path.iterdir():
                if not entry.is_dir():
                    continue
                name = entry.name
                wine_bin = entry / "files" / "bin" / "wine"
                if not wine_bin.is_file():
                    continue
                if name in seen_names:
                    continue

                if name == "Proton - Experimental":
                    major, minor, is_beta = 9999, 9999, False
                else:
                    m = re.match(r'^Proton (\d+)\.(\d+)(\s+\(Beta\))?$', name)
                    if not m:
                        continue
                    major, minor, is_beta = int(m.group(1)), int(m.group(2)), bool(m.group(3))

                compat_name = WineUtilsProtonMixin.resolve_steam_compat_name(entry)
                found_versions.append({
                    'name': name,
                    'path': entry,
                    'wine_bin': wine_bin,
                    'priority': major * 10 + (0 if is_beta else 1),
                    'major_version': major,
                    'minor_version': minor,
                    'type': 'Valve-Proton',
                    'steam_compat_name': compat_name,
                })
                seen_names.add(name)
                logger.debug(f"Found Valve Proton: {name}")

        found_versions.sort(
            key=lambda x: (x['major_version'], x['minor_version'], 0 if x['name'].endswith('(Beta)') else 1),
            reverse=True,
        )
        logger.info(f"Found {len(found_versions)} Valve Proton version(s)")
        return found_versions

    @staticmethod
    def scan_all_proton_versions() -> List[Dict[str, Any]]:
        """Scan for all available Proton versions (GE + third-party + Valve) with unified priority."""
        logger.info("Scanning for all available Proton versions...")
        all_versions = []
        all_versions.extend(WineUtilsProtonMixin.scan_ge_proton_versions())
        all_versions.extend(WineUtilsProtonMixin.scan_thirdparty_proton_versions())
        all_versions.extend(WineUtilsProtonMixin.scan_valve_proton_versions())
        def _type_rank(v: dict) -> int:
            t = v.get('type', '')
            if t == 'GE-Proton':
                return 2 if v.get('major_version', 0) >= 10 else -1
            if t == 'ThirdParty-Proton':
                return 1
            if t == 'Valve-Proton':
                return 0
            return -1

        all_versions.sort(
            key=lambda x: (
                _type_rank(x),
                x.get('major_version', 0),
                x.get('minor_version', 0),
                x.get('priority', 0),
            ),
            reverse=True,
        )
        unique_versions = []
        seen_names = set()
        for version in all_versions:
            if version['name'] not in seen_names:
                unique_versions.append(version)
                seen_names.add(version['name'])
        if unique_versions:
            logger.debug(f"Found {len(unique_versions)} total Proton version(s)")
            logger.debug(f"Best available: {unique_versions[0]['name']} ({unique_versions[0]['type']})")
        else:
            logger.warning("No Proton versions found")
        return unique_versions

    @staticmethod
    def select_best_proton() -> Optional[Dict[str, Any]]:
        """Select the best available Proton version. Prefers GE-Proton, then Valve, then any third-party build."""
        available_versions = WineUtilsProtonMixin.scan_all_proton_versions()
        if not available_versions:
            logger.warning("No Proton versions found")
            return None
        best_version = available_versions[0]
        if best_version.get('type') == 'ThirdParty-Proton':
            logger.debug(f"No GE/Valve Proton found; using third-party build: {best_version['name']}")
        else:
            logger.info(f"Selected Proton: {best_version['name']} ({best_version['type']})")
        return best_version

    @staticmethod
    def select_best_valve_proton() -> Optional[Dict[str, Any]]:
        """Select the best available Valve Proton. Kept for backward compatibility."""
        available_versions = WineUtilsProtonMixin.scan_valve_proton_versions()
        if not available_versions:
            logger.warning("No compatible Valve Proton versions found")
            return None
        best_version = available_versions[0]
        logger.info(f"Selected Valve Proton version: {best_version['name']}")
        return best_version

    @staticmethod
    def check_proton_requirements() -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Check if a compatible Proton version is available for workflows."""
        logger.info("Checking Proton requirements for workflow...")
        best_proton = WineUtilsProtonMixin.select_best_proton()
        if best_proton:
            proton_type = best_proton.get('type', 'Unknown')
            status_msg = f"[OK] Using {best_proton['name']} ({proton_type}) for this workflow"
            logger.info(f"Proton requirements satisfied: {best_proton['name']} ({proton_type})")
            return True, status_msg, best_proton
        status_msg = "[FAIL] No compatible Proton version found (GE-Proton 10+, Proton 9+, 10, or Experimental required)"
        logger.warning("Proton requirements not met - no compatible version found")
        return False, status_msg, None
