"""Detection and discovery methods for ModlistHandler (Mixin)."""
from pathlib import Path
from typing import Dict, List, Optional
import os
import re
import logging
import subprocess

logger = logging.getLogger(__name__)


class ModlistDetectionMixin:
    """Mixin providing detection and discovery methods for ModlistHandler.

    These methods are separated for code organization but require
    ModlistHandler's instance attributes (self.logger, self.path_handler, etc.)
    """

    def _detect_modlists_from_shortcuts(self) -> bool:
        """
        Detect modlists from Steam shortcuts.vdf entries
        """
        self.logger.info("Detecting modlists from Steam shortcuts")
        return False

    def discover_executable_shortcuts(self, executable_name: str) -> List[Dict]:
        """Discovers non-Steam shortcuts pointing to a specific executable.

        Args:
            executable_name: The name of the executable (e.g., "ModOrganizer.exe")
                             to look for in the shortcut's 'Exe' path.

        Returns:
            A list of dictionaries, each containing validated shortcut info:
            {'name': AppName, 'appid': AppID, 'path': StartDir}
            Returns an empty list if none are found or an error occurs.
        """
        self.logger.info(f"Discovering non-Steam shortcuts for executable: {executable_name}")
        discovered_modlists_info = []

        try:
            # Get shortcuts pointing to the executable from shortcuts.vdf
            matching_vdf_shortcuts = self.shortcut_handler.find_shortcuts_by_exe(executable_name)
            if not matching_vdf_shortcuts:
                self.logger.debug(f"No shortcuts found pointing to '{executable_name}' in shortcuts.vdf.")
                return []
            self.logger.debug(f"Shortcuts matching executable '{executable_name}' in VDF: {matching_vdf_shortcuts}")

            # Process each matching shortcut and convert signed AppID to unsigned
            for vdf_shortcut in matching_vdf_shortcuts:
                app_name = vdf_shortcut.get('AppName')
                start_dir = vdf_shortcut.get('StartDir')
                signed_appid = vdf_shortcut.get('appid')

                if not app_name or not start_dir:
                    self.logger.warning(f"Skipping VDF shortcut due to missing AppName or StartDir: {vdf_shortcut}")
                    continue

                if signed_appid is None:
                    self.logger.warning(f"Skipping VDF shortcut due to missing appid: {vdf_shortcut}")
                    continue

                # Convert signed AppID to unsigned AppID (the format used by Steam prefixes)
                if signed_appid < 0:
                    unsigned_appid = signed_appid + (2**32)
                else:
                    unsigned_appid = signed_appid

                # Append dictionary with all necessary info using unsigned AppID
                modlist_info = {
                    'name': app_name,
                    'appid': unsigned_appid,
                    'path': start_dir
                }
                discovered_modlists_info.append(modlist_info)
                self.logger.info(f"Discovered shortcut: '{app_name}' (Signed: {signed_appid} -> Unsigned: {unsigned_appid}, Path: {start_dir})")

        except Exception as e:
            self.logger.error(f"Error discovering executable shortcuts: {e}", exc_info=True)
            return []

        if not discovered_modlists_info:
            self.logger.warning("No validated shortcuts found after correlation.")

        return discovered_modlists_info

    def _detect_game_variables(self):
        """Detect game_var and game_var_full based on ModOrganizer.ini content."""
        if not self.modlist_ini or not Path(self.modlist_ini).is_file():
            self.logger.error("Cannot detect game variables: ModOrganizer.ini path not set or file not found.")
            self.game_var = "Unknown"
            self.game_var_full = "Unknown"
            return False

        from jackify.backend.services.game_type_detection import detect_from_install
        from jackify.backend.models.game_types import GAME_DISPLAY_NAMES

        game_type = detect_from_install(self.modlist_dir)
        if game_type:
            self.game_var = game_type
            self.game_var_full = GAME_DISPLAY_NAMES.get(game_type, game_type)
            self.logger.info(f"Detected game type '{self.game_var_full}' from {self.modlist_ini}")
            return True
        else:
            self.logger.warning("Could not detect game type from ModOrganizer.ini content.")
            self.game_var = "Unknown"
            self.game_var_full = "Unknown"
            return False

    def _detect_proton_version(self):
        """Detect the Proton version used for the modlist prefix."""
        self.logger.info(f"Detecting Proton version for AppID {self.appid}...")
        self.proton_ver = "Unknown"

        if not self.appid:
            self.logger.error("Cannot detect Proton version without a valid AppID.")
            return False

        # Check config.vdf first for user-selected tool name
        try:
            config_vdf_path = self.path_handler.find_steam_config_vdf()
            if config_vdf_path and config_vdf_path.exists():
                import vdf
                with open(config_vdf_path, 'r') as f:
                    data = vdf.load(f)

                mapping = data.get('InstallConfigStore', {}).get('Software', {}).get('Valve', {}).get('Steam', {}).get('CompatToolMapping', {})
                app_mapping = mapping.get(str(self.appid), {})
                tool_name = app_mapping.get('name', '')

                if tool_name and 'experimental' in tool_name.lower():
                    self.proton_ver = tool_name
                    self.logger.info(f"Detected Proton tool from config.vdf: {self.proton_ver}")
                    return True
                elif tool_name:
                    self.logger.debug(f"Proton tool from config.vdf: {tool_name}. Checking registry for runtime version.")
                else:
                    self.logger.debug(f"No specific Proton tool mapping found for AppID {self.appid} in config.vdf.")
            else:
                self.logger.debug("config.vdf not found, proceeding with registry check.")

        except ImportError:
            self.logger.warning("Python 'vdf' library not found. Cannot check config.vdf for Proton version. Skipping.")
        except Exception as e:
            self.logger.warning(f"Error reading config.vdf: {e}. Proceeding with registry check.")

        # If config.vdf didn't yield 'Experimental', check prefix files
        if not self.compat_data_path or not self.compat_data_path.exists():
            self.logger.warning(f"Compatdata path '{self.compat_data_path}' not found or invalid for AppID {self.appid}. Cannot detect Proton version via prefix files.")
            return False

        # Method 1: Check system.reg
        system_reg_path = self.compat_data_path / "pfx" / "system.reg"
        if system_reg_path.exists():
            try:
                with open(system_reg_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                match = re.search(r'"SteamClientProtonVersion"="([^"]+)"\r?', content)
                if match:
                    version_str = match.group(1).strip()
                    if version_str:
                        if "GE" in version_str.upper():
                            self.proton_ver = version_str
                        else:
                            self.proton_ver = f"Proton {version_str}"
                        self.logger.info(f"Detected Proton runtime version from system.reg: {self.proton_ver}")
                        return True
                else:
                    self.logger.debug("'SteamClientProtonVersion' not found in system.reg.")
            except Exception as e:
                self.logger.warning(f"Error reading system.reg: {e}")
        else:
            self.logger.debug("system.reg not found.")

        # Method 2: Check config_info
        config_info_path = self.compat_data_path / "config_info"
        if config_info_path.exists():
            try:
                with open(config_info_path, 'r') as f:
                    version_str = f.readline().strip()
                if version_str:
                    if "GE" in version_str.upper():
                        self.proton_ver = version_str
                    else:
                        self.proton_ver = f"Proton {version_str}"
                    self.logger.info(f"Detected Proton runtime version from config_info: {self.proton_ver}")
                    return True
            except Exception as e:
                self.logger.warning(f"Error reading config_info: {e}")
        else:
            self.logger.debug("config_info file not found.")

        self.logger.warning(f"Could not detect Proton version for AppID {self.appid} from prefix files.")
        return False

    def _detect_steam_library_info(self) -> bool:
        """Detects Steam Library path and whether it's on an SD card."""
        from .path_handler import PathHandler

        self.logger.debug("Detecting Steam Library path...")
        steam_lib_path_str = PathHandler.find_steam_library()

        if not steam_lib_path_str:
            self.logger.error("PathHandler.find_steam_library() failed to find a Steam library.")
            self.steam_library = None
            self.basegame_sdcard = False
            return False

        self.steam_library = steam_lib_path_str
        self.logger.info(f"Detected Steam Library: {self.steam_library}")

        self.logger.debug(f"Checking if Steam Library {self.steam_library} is on SD card...")
        steam_lib_path_obj = Path(self.steam_library)
        self.basegame_sdcard = self.filesystem_handler.is_sd_card(steam_lib_path_obj)
        self.logger.info(f"Base game library on SD card: {self.basegame_sdcard}")

        return True

    def _detect_stock_game_path(self):
        """Detects common 'Stock Game' or 'Game Root' directories within the modlist path."""
        self.logger.info("Step 7a: Detecting Stock Game/Game Root directory...")
        if not self.modlist_dir:
            self.logger.error("Modlist directory not set, cannot detect stock game path.")
            return False

        modlist_path = Path(self.modlist_dir)
        common_names = [
            "Stock Game",
            "StockGame",
            "STOCK GAME",
            "Stock Game Folder",
            "Stock Folder",
            "Skyrim Stock",
            Path("root/Skyrim Special Edition"),
            "Game Root",
        ]

        found_path = None
        for name in common_names:
            potential_path = modlist_path / name
            if potential_path.is_dir():
                found_path = str(potential_path)
                self.logger.info(f"Found potential stock game directory: {found_path}")
                break

        if found_path:
            self.stock_game_path = found_path
            return True
        else:
            self.stock_game_path = None
            self.logger.info("No common Stock Game/Game Root directory found. Will assume vanilla game path is needed for some operations.")
            return True

    def _is_steam_deck(self):
        """Detect if running on Steam Deck."""
        try:
            if os.path.exists('/etc/os-release'):
                with open('/etc/os-release') as f:
                    if 'steamdeck' in f.read().lower():
                        return True
            user_services = subprocess.run(['systemctl', '--user', 'list-units', '--type=service', '--no-pager'], capture_output=True, text=True)
            if 'app-steam@autostart.service' in user_services.stdout:
                return True
        except Exception as e:
            self.logger.warning(f"Error detecting Steam Deck: {e}")
        return False

    def detect_special_game_type(self, modlist_dir: str) -> Optional[str]:
        """
        Detect if this modlist requires vanilla compatdata instead of new prefix.

        Detects special game types that need to use existing vanilla game compatdata:
        - FNV: Has nvse_loader.exe
        - Enderal: Has Enderal Launcher.exe

        Args:
            modlist_dir: Path to the modlist installation directory

        Returns:
            str: Game type ("fnv", "enderal") or None if not a special game
        """
        if not modlist_dir:
            return None

        modlist_path = Path(modlist_dir)
        if not modlist_path.exists() or not modlist_path.is_dir():
            self.logger.debug(f"Modlist directory does not exist: {modlist_dir}")
            return None

        self.logger.debug(f"Checking for special game type in: {modlist_dir}")

        # Check ModOrganizer.ini for indicators
        try:
            mo2_ini = modlist_path / "ModOrganizer.ini"
            if not mo2_ini.exists():
                somnium_mo2_ini = modlist_path / "files" / "ModOrganizer.ini"
                if somnium_mo2_ini.exists():
                    mo2_ini = somnium_mo2_ini

            if mo2_ini.exists():
                try:
                    content = mo2_ini.read_text(errors='ignore').lower()
                    # Extract gameName= for authoritative game type checks.
                    # Full-content scans can false-positive on plugin setting keys
                    # (e.g. enable_skyrimVR=false in a Skyrim SE ini).
                    game_name_value = ""
                    for _line in content.splitlines():
                        stripped_line = _line.strip()
                        if stripped_line.startswith("gamename="):
                            game_name_value = stripped_line[len("gamename="):]
                            break
                    if 'nvse' in content or 'nvse_loader' in content or 'fallout new vegas' in content or 'falloutnv' in content:
                        self.logger.info("Detected FNV via ModOrganizer.ini markers")
                        return "fnv"
                    if 'fose' in content or 'fose_loader' in content or ('fallout 3' in content and 'fallout 4' not in content):
                        self.logger.info("Detected FO3 via ModOrganizer.ini markers")
                        return "fo3"
                    if any(pattern in content for pattern in ['enderal launcher', 'enderal.exe', 'enderal launcher.exe', 'enderalsteam']):
                        self.logger.info("Detected Enderal via ModOrganizer.ini markers")
                        return "enderal"
                    if 'cyberpunk 2077' in content or 'cyberpunk2077' in content or 'cp2077' in content:
                        self.logger.info("Detected Cyberpunk 2077 via ModOrganizer.ini markers")
                        return "cp2077"
                    if "baldur's gate 3" in content or 'baldursgate3' in content or 'bg3' in content:
                        self.logger.info("Detected Baldur's Gate 3 via ModOrganizer.ini markers")
                        return "bg3"
                    if 'skyrim vr' in game_name_value or 'skyrimvr' in game_name_value:
                        self.logger.info("Detected SkyrimVR via ModOrganizer.ini gameName")
                        return "skyrimvr"
                    if 'fallout 4 vr' in game_name_value or 'fallout4vr' in game_name_value:
                        self.logger.info("Detected Fallout 4 VR via ModOrganizer.ini gameName")
                        return "fallout4vr"
                except Exception as e:
                    self.logger.debug(f"Failed reading ModOrganizer.ini for detection: {e}")
        except Exception:
            pass

        # Check for FNV and Enderal launchers in common locations
        candidates = [modlist_path]
        try:
            from .path_handler import STOCK_GAME_FOLDERS
            for folder_name in STOCK_GAME_FOLDERS:
                sub = modlist_path / folder_name
                if sub.exists() and sub.is_dir():
                    candidates.append(sub)
        except Exception:
            pass

        for base in candidates:
            nvse_loader = base / "nvse_loader.exe"
            if nvse_loader.exists():
                self.logger.info(f"Detected FNV modlist: found nvse_loader.exe in '{base}'")
                return "fnv"
            fose_loader = base / "fose_loader.exe"
            if fose_loader.exists():
                self.logger.info(f"Detected FO3 modlist: found fose_loader.exe in '{base}'")
                return "fo3"
            enderal_launcher = base / "Enderal Launcher.exe"
            if enderal_launcher.exists():
                self.logger.info(f"Detected Enderal modlist: found Enderal Launcher.exe in '{base}'")
                return "enderal"
            cp2077_exe = base / "Cyberpunk2077.exe"
            if cp2077_exe.exists():
                self.logger.info(f"Detected Cyberpunk 2077 modlist: found Cyberpunk2077.exe in '{base}'")
                return "cp2077"
            bg3_exe = base / "bg3.exe"
            bg3_dx11_exe = base / "bg3_dx11.exe"
            if bg3_exe.exists() or bg3_dx11_exe.exists():
                self.logger.info(f"Detected BG3 modlist: found BG3 executable in '{base}'")
                return "bg3"

        # Final heuristic using game_var
        try:
            game_type = getattr(self, 'game_var', None)
            if isinstance(game_type, str):
                gt = game_type.strip().lower()
                if 'fallout new vegas' in gt or gt == 'fnv':
                    self.logger.info("Heuristic detection: game_var indicates FNV")
                    return "fnv"
                if 'fallout 3' in gt or gt == 'fo3':
                    self.logger.info("Heuristic detection: game_var indicates FO3")
                    return "fo3"
                if 'enderal' in gt:
                    self.logger.info("Heuristic detection: game_var indicates Enderal")
                    return "enderal"
                if 'cyberpunk' in gt or 'cp2077' in gt:
                    self.logger.info("Heuristic detection: game_var indicates Cyberpunk 2077")
                    return "cp2077"
                if "baldur" in gt or 'bg3' in gt:
                    self.logger.info("Heuristic detection: game_var indicates BG3")
                    return "bg3"
                if 'skyrim vr' in gt or 'skyrimvr' in gt:
                    self.logger.info("Heuristic detection: game_var indicates SkyrimVR")
                    return "skyrimvr"
                if 'fallout 4 vr' in gt or 'fallout4vr' in gt:
                    self.logger.info("Heuristic detection: game_var indicates Fallout 4 VR")
                    return "fallout4vr"
        except Exception:
            pass

        self.logger.debug("No special game type detected - standard workflow will be used")
        return None
