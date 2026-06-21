"""Wine/Proton operation methods for ModlistHandler (Mixin)."""
from pathlib import Path
from typing import Tuple, Optional
import os
import logging
import subprocess
import shutil
import vdf
import json
import configparser

logger = logging.getLogger(__name__)


class ModlistWineOpsMixin:
    """Mixin providing Wine and Proton operation methods for ModlistHandler."""

    def verify_proton_setup(self, appid_to_check: str) -> Tuple[bool, str]:
        """Verifies that Proton is correctly set up for a given AppID.

        Checks config.vdf for Proton Experimental and existence of compatdata/pfx dir.

        Args:
            appid_to_check: The AppID string to verify.

        Returns:
            tuple: (bool success, str status_code)
                   Status codes: 'ok', 'invalid_appid', 'config_vdf_missing', 
                                 'config_vdf_error', 'proton_check_failed', 
                                 'wrong_proton_version', 'compatdata_missing',
                                 'prefix_missing'
        """
        self.logger.info(f"Verifying Proton setup for AppID: {appid_to_check}")
        
        if not appid_to_check or not appid_to_check.isdigit():
            self.logger.error("Invalid AppID provided for verification.")
            return False, 'invalid_appid'

        proton_tool_name = None
        compatdata_path_found = None
        prefix_exists = False

        # 1. Find and Parse config.vdf
        config_vdf_path = None
        possible_steam_paths = [
            Path.home() / ".steam/steam",
            Path.home() / ".local/share/Steam",
            Path.home() / ".steam/root"
        ]
        for steam_path in possible_steam_paths:
            potential_path = steam_path / "config/config.vdf"
            if potential_path.is_file():
                config_vdf_path = potential_path
                self.logger.debug(f"Found config.vdf at: {config_vdf_path}")
                break
        
        if not config_vdf_path:
            self.logger.error("Could not locate Steam's config.vdf file.")
            return False, 'config_vdf_missing'

        try:
            self.logger.debug(f"Loading config.vdf: {config_vdf_path}")
            with open(str(config_vdf_path), 'r') as f:
                config_data = vdf.load(f, mapper=vdf.VDFDict)

            steam_config_section = config_data.get('InstallConfigStore', {}).get('Software', {}).get('Valve', {}).get('Steam', {})
            compat_mapping = steam_config_section.get('CompatToolMapping', {})
            app_mapping = compat_mapping.get(appid_to_check, {})
            proton_tool_name = app_mapping.get('name')
            self.proton_ver = proton_tool_name
            
            if proton_tool_name:
                self.logger.info(f"Proton tool name from config.vdf: {proton_tool_name}")
            else:
                 self.logger.warning(f"CompatToolMapping entry not found for AppID {appid_to_check} in config.vdf.")
                 # Add more debug info here about what *was* found
                 self.logger.debug(f"CompatToolMapping contents: {json.dumps(compat_mapping.get(appid_to_check, 'Key not found'), indent=2)}")
                 return False, 'proton_check_failed' # Compatibility not explicitly set

        except FileNotFoundError:
            self.logger.error(f"Config.vdf file not found during load attempt: {config_vdf_path}")
            return False, 'config_vdf_missing'
        except Exception as e:
            self.logger.error(f"Error parsing config.vdf: {e}", exc_info=True)
            return False, 'config_vdf_error'

        # 2. Check if the correct Proton version is set (allowing variations)
        # Target: Proton Experimental
        if not proton_tool_name or 'experimental' not in proton_tool_name.lower():
            self.logger.warning(f"Incorrect Proton version detected: '{proton_tool_name}'. Expected 'Proton Experimental'.")
            return False, 'wrong_proton_version'
        
        self.logger.info("Proton version check passed ('Proton Experimental' set).")

        # 3. Check for compatdata / prefix directory existence
        possible_compat_bases = [
            Path.home() / ".steam/steam/steamapps/compatdata",
            Path.home() / ".local/share/Steam/steamapps/compatdata",
             # Add SD card paths if necessary / detectable
             # Path("/run/media/mmcblk0p1/steamapps/compatdata") # Example
        ]
        
        compat_dir_found = False
        for base_path in possible_compat_bases:
            potential_compat_path = base_path / appid_to_check
            if potential_compat_path.is_dir():
                self.logger.debug(f"Found compatdata directory: {potential_compat_path}")
                compat_dir_found = True
                # Check for prefix *within* the found compatdata dir
                prefix_path = potential_compat_path / "pfx"
                if prefix_path.is_dir():
                     self.logger.info(f"Wine prefix directory verified: {prefix_path}")
                     prefix_exists = True
                     break # Found both compatdata and prefix, exit loop
                else:
                     self.logger.warning(f"Compatdata directory found, but prefix missing: {prefix_path}")
                     # Keep searching other base paths in case prefix exists elsewhere
            
        if not compat_dir_found:
             self.logger.error(f"Compatdata directory not found for AppID {appid_to_check} in standard locations.")
             return False, 'compatdata_missing'
             
        if not prefix_exists:
             # Found compatdata but no pfx inside any of them
             self.logger.error(f"Wine prefix directory (pfx) not found within any located compatdata directory for AppID {appid_to_check}.")
             return False, 'prefix_missing'

        # All checks passed
        self.logger.info(f"Proton setup verification successful for AppID {appid_to_check}.")
        return True, 'ok'

    def set_steam_grid_images(self, appid: str, modlist_dir: str, game_type: str = None):
        """
        Copies artwork from the modlist's SteamIcons directory to Steam's grid folder.
        Falls back to SteamGridDB if no SteamIcons directory is present and an API key
        is configured.
        """
        if modlist_dir:
            try:
                from jackify.backend.services.steamgriddb_service import detect_game_type_from_modlist
                detected_game_type = detect_game_type_from_modlist(modlist_dir)
                if detected_game_type:
                    game_type = detected_game_type
            except Exception as e:
                self.logger.debug(f"Steam artwork game type auto-detect failed for {modlist_dir}: {e}")

        steam_icons_dir = Path(modlist_dir) / "SteamIcons"
        if not steam_icons_dir.is_dir():
            self._try_steamgriddb_artwork(appid, game_type, modlist_dir)
            return

        # Find all non-zero Steam user directories
        userdata_base = Path.home() / ".steam/steam/userdata"
        if not userdata_base.is_dir():
            self.logger.error(f"Steam userdata directory not found at {userdata_base}")
            return

        images = [
            ("grid-hero.png", f"{appid}_hero.png"),
            ("grid-logo.png", f"{appid}_logo.png"),
            ("grid-tall.png", f"{appid}p.png"),
            ("grid-wide.png", f"{appid}.png"),
        ]

        for user_dir in userdata_base.iterdir():
            if not user_dir.is_dir() or user_dir.name == "0":
                continue
            grid_dir = user_dir / "config/grid"
            grid_dir.mkdir(parents=True, exist_ok=True)

            for src_name, dest_name in images:
                src_path = steam_icons_dir / src_name
                dest_path = grid_dir / dest_name
                if src_path.exists():
                    try:
                        shutil.copyfile(src_path, dest_path)
                        self.logger.info(f"Copied {src_path} to {dest_path}")
                    except Exception as e:
                        self.logger.error(f"Failed to copy {src_path} to {dest_path}: {e}")
                else:
                    self.logger.debug(f"Image {src_path} not found; skipping.")

            # Tenfoot: use explicit file if provided, otherwise resize the landscape grid
            tenfoot_src = steam_icons_dir / "grid-tenfoot.png"
            tenfoot_dest = grid_dir / f"{appid}_tenfoot.png"
            wide_src = steam_icons_dir / "grid-wide.png"
            if tenfoot_src.exists():
                try:
                    shutil.copyfile(tenfoot_src, tenfoot_dest)
                    self.logger.info(f"Copied {tenfoot_src} to {tenfoot_dest}")
                except Exception as e:
                    self.logger.error(f"Failed to copy tenfoot image: {e}")
            elif wide_src.exists():
                try:
                    shutil.copyfile(wide_src, tenfoot_dest)
                    self.logger.info(f"Copied landscape image as tenfoot fallback: {tenfoot_dest}")
                except Exception as e:
                    self.logger.warning(f"Could not copy tenfoot image: {e}")

        missing_sources = [src for src, _ in images if not (steam_icons_dir / src).exists()]
        if missing_sources:
            self._try_steamgriddb_artwork(appid, game_type, modlist_dir, skip_existing=True)

    def _try_steamgriddb_artwork(self, appid: str, game_type: str = None, modlist_dir: str = None, skip_existing: bool = False):
        """Fetch artwork from SteamGridDB. When skip_existing is True, slots already present in grid_dir are not overwritten."""
        if not game_type and modlist_dir:
            from jackify.backend.services.steamgriddb_service import detect_game_type_from_modlist
            game_type = detect_game_type_from_modlist(modlist_dir)
        if not game_type:
            self.logger.warning(f"SteamGridDB fallback skipped: could not detect game type for {modlist_dir}")
            return

        userdata_base = Path.home() / ".steam/steam/userdata"
        if not userdata_base.is_dir():
            return

        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            from jackify.backend.services.steamgriddb_service import fetch_artwork
            count = fetch_artwork(game_type, tmp_dir)
            if count == 0:
                self.logger.debug(f"SteamGridDB returned no artwork for game type: {game_type}")
                return

            for user_dir in userdata_base.iterdir():
                if not user_dir.is_dir() or user_dir.name == "0":
                    continue
                grid_dir = user_dir / "config/grid"
                grid_dir.mkdir(parents=True, exist_ok=True)

                images = [
                    ("grid-tall.png", f"{appid}p.png"),
                    ("grid-wide.png", f"{appid}.png"),
                    ("grid-hero.png", f"{appid}_hero.png"),
                    ("grid-logo.png", f"{appid}_logo.png"),
                ]
                for src_name, dest_name in images:
                    src = tmp_dir / src_name
                    if src.exists():
                        dest = grid_dir / dest_name
                        if skip_existing and dest.exists():
                            continue
                        try:
                            shutil.copyfile(src, dest)
                        except Exception as e:
                            self.logger.warning(f"Failed to copy {src_name}: {e}")

                # Generate tenfoot from landscape
                tenfoot_dest = grid_dir / f"{appid}_tenfoot.png"
                wide = tmp_dir / "grid-wide.png"
                if wide.exists() and not (skip_existing and tenfoot_dest.exists()):
                    try:
                        from PySide6.QtGui import QImage
                        img = QImage(str(wide))
                        if not img.isNull():
                            img.scaled(600, 350).save(str(tenfoot_dest))
                    except Exception as e:
                        self.logger.debug(f"Could not generate tenfoot: {e}")

            self.logger.info(f"Applied SteamGridDB artwork for game type '{game_type}' ({count} images)")

    def get_modlist_wine_components(self, modlist_name, game_var_full=None):
        """
        Returns the full list of Wine components to install for a given modlist/game.
        - Always includes the default set (fontsmooth=rgb, xact, xact_x64, vcrun2022)
        - Adds game-specific extras (from bash script logic)
        - Adds any modlist-specific extras (from MODLIST_WINE_COMPONENTS)
        """
        default_components = ["fontsmooth=rgb", "xact", "xact_x64", "vcrun2022"]
        extras = []
        # Determine game type
        game = (game_var_full or modlist_name or "").lower().replace(" ", "")
        # Add game-specific extras
        if "fallout4vr" in game or "fo4vr" in game:
            extras += ["d3dcompiler_47", "d3dx11_43", "d3dcompiler_43", "dotnet6", "dotnet7", "dotnet8", "dotnetdesktop6", "vcrun2012"]
        elif "skyrim" in game or "fallout4" in game or "starfield" in game or "oblivion_remastered" in game or "enderal" in game:
            extras += ["d3dcompiler_47", "d3dx11_43", "d3dcompiler_43", "dotnet6", "dotnet7", "dotnet8", "dotnetdesktop6"]
        elif "falloutnewvegas" in game or "fnv" in game or "fallout3" in game or "fo3" in game or "oblivion" in game:
            extras += ["d3dx9_43", "d3dx9"]
        elif "cp2077" in game or "cyberpunk" in game:
            extras += ["d3dcompiler_47", "d3dx11_43", "d3dcompiler_43", "dotnet6", "dotnet7", "dotnet8", "dotnetdesktop6"]
        elif "bg3" in game or "baldursgate" in game:
            extras += ["d3dcompiler_47", "d3dx11_43", "d3dcompiler_43", "dotnet6", "dotnet7", "dotnet8", "dotnetdesktop6"]
        else:
            # Unknown game type - install the union of all known component sets
            extras += ["d3dcompiler_47", "d3dx11_43", "d3dcompiler_43", "dotnet6", "dotnet7", "dotnet8", "dotnetdesktop6", "d3dx9_43", "d3dx9"]
        # Add modlist-specific extras
        modlist_lower = modlist_name.lower().replace(" ", "") if modlist_name else ""
        for key, components in self.MODLIST_WINE_COMPONENTS.items():
            if key in modlist_lower:
                extras += components
        # Remove duplicates while preserving order, then promote Wine EXE installers
        # (dotnet48, dotnet40) to the front so the long-running installs happen first.
        seen = set()
        full_list = [x for x in default_components + extras if not (x in seen or seen.add(x))]
        _slow = [c for c in full_list if c in ('dotnet48', 'dotnet40')]
        _rest = [c for c in full_list if c not in ('dotnet48', 'dotnet40')]
        return _slow + _rest

    def _re_enforce_windows_10_mode(self):
        """
        Re-enforce the final Windows version after modlist-specific configurations.
        Re-applies win10 after modlist-specific winetricks components, which can
        leave the prefix at a lower version.
        """
        try:
            if not hasattr(self, 'appid') or not self.appid:
                self.logger.warning("Cannot re-enforce Windows 11 mode - no AppID available")
                return

            from ..handlers.winetricks_handler import WinetricksHandler
            from ..handlers.path_handler import PathHandler

            # Get prefix path for the AppID - must be compatdata/pfx/, not compatdata/
            compatdata_path = PathHandler.find_compat_data(str(self.appid))
            if not compatdata_path:
                self.logger.warning("Cannot re-enforce Windows 11 mode - prefix path not found")
                return
            prefix_path = compatdata_path / "pfx"

            # Use winetricks handler to set Windows 11 mode
            winetricks_handler = WinetricksHandler()
            wine_binary = winetricks_handler._get_wine_binary_for_prefix(str(prefix_path))
            if not wine_binary:
                self.logger.warning("Cannot re-enforce Windows 11 mode - wine binary not found")
                return

            env = os.environ.copy()
            env['WINEPREFIX'] = str(prefix_path)
            env['WINE'] = wine_binary
            result = subprocess.run(
                [winetricks_handler.winetricks_path, '-q', 'win10'],
                env=env,
                capture_output=True,
                text=True,
                timeout=300
            )
            if result.returncode == 0:
                self.logger.info("Windows 11 mode re-enforced after modlist-specific configurations")
            else:
                self.logger.warning("Could not set Windows 11 mode: %s", result.stderr)

        except Exception as e:
            self.logger.warning(f"Error re-enforcing Windows 11 mode: {e}")

    def _handle_symlinked_downloads(self) -> bool:
        """
        Check if downloads_directory in ModOrganizer.ini points to a symlink.
        If it does, comment out the line to force MO2 to use default behavior.

        Returns:
            bool: True on success or no action needed, False on error
        """
        try:
            if not self.modlist_ini or not os.path.exists(self.modlist_ini):
                self.logger.warning("ModOrganizer.ini not found for symlink check")
                return True  # Non-critical

            # Read the INI file
            # Allow duplicate sections/keys since some ModOrganizer.ini variants repeat [General]
            # Latest occurrence wins, which matches how we only need the final downloads_directory value.
            config = configparser.ConfigParser(allow_no_value=True, delimiters=['='], strict=False)
            config.optionxform = str  # Preserve case sensitivity

            try:
                # Read file manually to handle BOM
                with open(self.modlist_ini, 'r', encoding='utf-8-sig') as f:
                    config.read_file(f)
            except UnicodeDecodeError:
                with open(self.modlist_ini, 'r', encoding='latin-1') as f:
                    config.read_file(f)

            # Check if downloads_directory or download_directory exists and is a symlink
            downloads_key = None
            downloads_path = None

            if 'General' in config:
                # Check for both possible key names
                if 'downloads_directory' in config['General']:
                    downloads_key = 'downloads_directory'
                    downloads_path = config['General']['downloads_directory']
                elif 'download_directory' in config['General']:
                    downloads_key = 'download_directory'
                    downloads_path = config['General']['download_directory']

            if downloads_path:

                if downloads_path and os.path.exists(downloads_path):
                    # Check if the path or any parent directory contains symlinks
                    def has_symlink_in_path(path):
                        """Check if path or any parent directory is a symlink"""
                        current_path = Path(path).resolve()
                        check_path = Path(path)

                        # Walk up the path checking each component
                        for parent in [check_path] + list(check_path.parents):
                            if parent.is_symlink():
                                return True, str(parent)
                        return False, None

                    has_symlink, symlink_path = has_symlink_in_path(downloads_path)
                    if has_symlink:
                        self.logger.info(f"Detected symlink in downloads directory path: {symlink_path} -> {downloads_path}")
                        self.logger.info("Commenting out downloads_directory to avoid Wine symlink issues")

                        # Read the file manually to preserve comments and formatting
                        with open(self.modlist_ini, 'r', encoding='utf-8') as f:
                            lines = f.readlines()

                        # Find and comment out the downloads directory line
                        modified = False
                        for i, line in enumerate(lines):
                            if line.strip().startswith(f'{downloads_key}='):
                                lines[i] = '#' + line  # Comment out the line
                                modified = True
                                break

                        if modified:
                            # Write the modified file back
                            with open(self.modlist_ini, 'w', encoding='utf-8') as f:
                                f.writelines(lines)
                            self.logger.info(f"{downloads_key} line commented out successfully")
                        else:
                            self.logger.warning("downloads_directory line not found in file")
                    else:
                        self.logger.debug(f"downloads_directory is not a symlink: {downloads_path}")
                else:
                    self.logger.debug("downloads_directory path does not exist or is empty")
            else:
                self.logger.debug("No downloads_directory found in ModOrganizer.ini")

            return True

        except Exception as e:
            self.logger.error(f"Error handling symlinked downloads: {e}", exc_info=True)
            return False

    def _apply_universal_dotnet_fixes(self):
        """
        Apply universal dotnet4.x compatibility registry fixes to ALL modlists.
        Now called AFTER wine component installation to prevent overwrites.
        Includes wineserver shutdown/flush to ensure persistence.
        """
        try:
            prefix_path = os.path.join(str(self.compat_data_path), "pfx")
            if not os.path.exists(prefix_path):
                self.logger.warning(f"Prefix path not found: {prefix_path}")
                return False

            self.logger.info("Applying universal dotnet4.x compatibility registry fixes (post-component installation)...")

            # Find the appropriate Wine binary to use for registry operations
            wine_binary = self._find_wine_binary_for_registry()
            if not wine_binary:
                self.logger.error("Could not find Wine binary for registry operations")
                return False

            # Find wineserver binary for flushing registry changes
            wine_dir = os.path.dirname(wine_binary)
            wineserver_binary = os.path.join(wine_dir, 'wineserver')
            if not os.path.exists(wineserver_binary):
                self.logger.warning(f"wineserver not found at {wineserver_binary}, registry flush may not work")
                wineserver_binary = None

            # Set environment for Wine registry operations
            env = os.environ.copy()
            env['WINEPREFIX'] = prefix_path
            env['WINEDEBUG'] = '-all'  # Suppress Wine debug output

            self._wait_for_wineserver(prefix_path)

            # Registry fix 1: Set *mscoree=native as a per-exe AppDefaults override for
            # SkyrimSE.exe only. A global DllOverrides entry breaks .NET 9/10 bootstrap
            # (Synthesis), because the override intercepts mscoree loading for ALL processes
            # including the SDK host. Scoping it to SkyrimSE.exe isolates the fix to the
            # game process without affecting Synthesis or any other .NET tool.
            self.logger.debug("Setting *mscoree=native AppDefaults override for SkyrimSE.exe...")
            cmd1 = [
                wine_binary, 'reg', 'add',
                'HKEY_CURRENT_USER\\Software\\Wine\\AppDefaults\\SkyrimSE.exe\\DllOverrides',
                '/v', '*mscoree', '/t', 'REG_SZ', '/d', 'native', '/f'
            ]

            result1 = subprocess.run(cmd1, env=env, capture_output=True, text=True, errors='replace', timeout=30)
            self.logger.info(f"*mscoree registry command result: returncode={result1.returncode}, stdout={result1.stdout[:200]}, stderr={result1.stderr[:200]}")
            if result1.returncode == 0:
                self.logger.info("Successfully applied *mscoree=native DLL override")
            else:
                self.logger.error(f"Failed to set *mscoree DLL override: returncode={result1.returncode}, stderr={result1.stderr}")

            # Registry fix 2: Set OnlyUseLatestCLR=1
            # Use latest CLR to avoid .NET version conflicts
            self.logger.debug("Setting OnlyUseLatestCLR=1 registry entry...")
            cmd2 = [
                wine_binary, 'reg', 'add',
                'HKEY_LOCAL_MACHINE\\Software\\Microsoft\\.NETFramework',
                '/v', 'OnlyUseLatestCLR', '/t', 'REG_DWORD', '/d', '1', '/f'
            ]

            result2 = subprocess.run(cmd2, env=env, capture_output=True, text=True, errors='replace', timeout=30)
            self.logger.info(f"OnlyUseLatestCLR registry command result: returncode={result2.returncode}, stdout={result2.stdout[:200]}, stderr={result2.stderr[:200]}")
            if result2.returncode == 0:
                self.logger.info("Successfully applied OnlyUseLatestCLR=1 registry entry")
            else:
                self.logger.error(f"Failed to set OnlyUseLatestCLR: returncode={result2.returncode}, stderr={result2.stderr}")

            # NDP v4.8 keys (Release DWORD etc.) are written by the winetricks dotnet48 verb
            # during component installation; they are not set here.

            # Force wineserver to flush registry changes to disk
            if wineserver_binary:
                self.logger.debug("Flushing registry changes to disk via wineserver shutdown...")
                try:
                    subprocess.run([wineserver_binary, '-w'], env=env, timeout=30, capture_output=True)
                    self.logger.debug("Registry changes flushed to disk")
                except Exception as e:
                    self.logger.warning(f"Registry flush failed (non-critical): {e}")

            ok = result1.returncode == 0 and result2.returncode == 0
            if ok:
                self.logger.info("Universal dotnet4.x compatibility fixes applied and flushed")
            else:
                self.logger.error("One or more dotnet4.x registry commands failed - see errors above")
            return ok

        except Exception as e:
            self.logger.error(f"Failed to apply universal dotnet4.x fixes: {e}")
            return False

    def _find_wine_binary_for_registry(self) -> Optional[str]:
        """Find wine binary from Install Proton path"""
        try:
            # Use Install Proton from config (used by jackify-engine)
            from ..handlers.config_handler import ConfigHandler
            config_handler = ConfigHandler()
            proton_path = config_handler.get_proton_path()

            if proton_path:
                proton_path = Path(proton_path).expanduser()

                # Check both GE-Proton and Valve Proton structures
                wine_candidates = [
                    proton_path / "files" / "bin" / "wine",  # GE-Proton
                    proton_path / "dist" / "bin" / "wine"    # Valve Proton
                ]

                for wine_bin in wine_candidates:
                    if wine_bin.exists() and wine_bin.is_file():
                        return str(wine_bin)

            # Fallback: use best detected Proton
            from ..handlers.wine_utils import WineUtils
            best_proton = WineUtils.select_best_proton()
            if best_proton:
                wine_binary = WineUtils.find_proton_binary(best_proton['name'])
                if wine_binary:
                    return wine_binary

            return None
        except Exception as e:
            self.logger.error(f"Error finding Wine binary: {e}")
            return None

    def _wait_for_wineserver(self, prefix_path: str) -> None:
        """Wait for wineserver to stop for the given prefix before direct file edits.

        Harmless if wineserver is already stopped - exits immediately.
        Prevents in-memory hive flush from overwriting direct .reg file edits.
        """
        wine_binary = self._find_wine_binary_for_registry()
        if not wine_binary:
            self.logger.debug("No wine binary found; skipping wineserver wait")
            return
        wineserver = os.path.join(os.path.dirname(wine_binary), "wineserver")
        if not os.path.exists(wineserver):
            self.logger.debug("wineserver binary not found; skipping wait")
            return
        env = os.environ.copy()
        env["WINEPREFIX"] = prefix_path
        env["WINEDEBUG"] = "-all"
        try:
            subprocess.run([wineserver, "-w"], env=env, timeout=30, capture_output=True)
            self.logger.debug("wineserver stopped for prefix %s", prefix_path)
        except Exception as e:
            self.logger.debug("wineserver wait returned non-zero (likely already stopped): %s", e)

    def _apply_modlist_registry_tweaks(self) -> bool:
        """Write user.reg values required for modlist operation.

          - FontSmoothing/Type/Gamma/Orientation  (ClearType subpixel rendering)
          - HIGHDPIAWARE                           (prevents Wine DPI scaling on tools)
          - ShowDotFiles=Y                         (MO2 must see hidden dirs inside the prefix)
        """
        try:
            prefix_path = os.path.join(str(self.compat_data_path), "pfx")
            user_reg = os.path.join(prefix_path, "user.reg")
            if not os.path.exists(user_reg):
                self.logger.warning("user.reg not found at %s; skipping modlist registry tweaks", user_reg)
                return False

            self._wait_for_wineserver(prefix_path)

            tweaks = [
                (
                    "[Control Panel\\\\Desktop]",
                    '"FontSmoothing"',
                    '"2"',
                ),
                (
                    "[Control Panel\\\\Desktop]",
                    '"FontSmoothingGamma"',
                    "dword:00000578",
                ),
                (
                    "[Control Panel\\\\Desktop]",
                    '"FontSmoothingOrientation"',
                    "dword:00000001",
                ),
                (
                    "[Control Panel\\\\Desktop]",
                    '"FontSmoothingType"',
                    "dword:00000002",
                ),
                (
                    "[Software\\\\Microsoft\\\\Windows NT\\\\CurrentVersion\\\\AppCompatFlags\\\\Layers]",
                    '@',
                    '"~ HIGHDPIAWARE"',
                ),
                (
                    "[Software\\\\Wine]",
                    '"ShowDotFiles"',
                    '"Y"',
                ),
            ]

            with open(user_reg, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()

            for section, key, value in tweaks:
                in_section = False
                updated = False
                insert_at = None
                for i, line in enumerate(lines):
                    stripped = line.strip()
                    if stripped.lower() == section.lower():
                        in_section = True
                        continue
                    if stripped.startswith("[") and in_section:
                        insert_at = i
                        break
                    if in_section and stripped.lower().startswith(key.lower()):
                        lines[i] = f"{key}={value}\n"
                        updated = True
                        break

                if not updated:
                    entry = f"{key}={value}\n"
                    if insert_at is not None:
                        lines.insert(insert_at, entry)
                    elif in_section:
                        lines.append(entry)
                    else:
                        lines.append(f"\n{section}\n")
                        lines.append(entry)

            with open(user_reg, "w", encoding="utf-8") as f:
                f.writelines(lines)

            self.logger.info("Modlist registry tweaks applied (font smoothing, HIGHDPIAWARE, ShowDotFiles)")
            return True

        except Exception as e:
            self.logger.error("Failed to apply modlist registry tweaks: %s", e)
            return False

    def _audit_registry_state(self) -> bool:
        """Read user.reg and system.reg and log whether every expected value is present.

        Returns True only when all checks pass. Logs a WARNING for each missing or
        wrong value so the application log always carries a clear post-configuration
        record of registry state.
        """
        try:
            prefix_path = os.path.join(str(self.compat_data_path), "pfx")
            user_reg = os.path.join(prefix_path, "user.reg")
            system_reg = os.path.join(prefix_path, "system.reg")

            def _read(path):
                if not os.path.exists(path):
                    return ""
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    return f.read()

            user_content = _read(user_reg)
            system_content = _read(system_reg)

            checks = [
                # (description, file_content, expected_substring)
                (
                    "ShowDotFiles=Y (user.reg)",
                    user_content,
                    '"ShowDotFiles"="Y"',
                ),
                (
                    "FontSmoothing=2 (user.reg)",
                    user_content,
                    '"FontSmoothing"="2"',
                ),
                (
                    "FontSmoothingType=2 (user.reg)",
                    user_content,
                    '"FontSmoothingType"=dword:00000002',
                ),
                (
                    "FontSmoothingGamma (user.reg)",
                    user_content,
                    '"FontSmoothingGamma"=dword:00000578',
                ),
                (
                    "FontSmoothingOrientation (user.reg)",
                    user_content,
                    '"FontSmoothingOrientation"=dword:00000001',
                ),
                (
                    "HIGHDPIAWARE (user.reg)",
                    user_content,
                    'HIGHDPIAWARE',
                ),
                (
                    "*mscoree=native (user.reg)",
                    user_content,
                    '"*mscoree"="native"',
                ),
                (
                    "OnlyUseLatestCLR=1 (system.reg)",
                    system_content,
                    '"OnlyUseLatestCLR"=dword:00000001',
                ),
            ]

            all_ok = True
            for description, content, needle in checks:
                if needle in content:
                    self.logger.info("Registry audit [OK] %s", description)
                else:
                    self.logger.warning("Registry audit [MISSING] %s", description)
                    all_ok = False

            if all_ok:
                self.logger.info("Registry audit complete - all values confirmed present")
            else:
                self.logger.warning(
                    "Registry audit complete - one or more values missing; "
                    "see [MISSING] entries above"
                )
            return all_ok

        except Exception as e:
            self.logger.error("Registry audit failed with exception: %s", e)
            return False

    def _search_wine_in_proton_directory(self, proton_path: Path) -> Optional[str]:
        """
        Recursively search for wine binary within a Proton directory.
        This handles cases where the directory structure might differ between Proton versions.
        
        Args:
            proton_path: Path to the Proton directory to search
            
        Returns:
            Path to wine binary if found, None otherwise
        """
        try:
            if not proton_path.exists() or not proton_path.is_dir():
                return None

            # Search for 'wine' executable (not 'wine64' or 'wine-preloader')
            # Limit search depth to avoid scanning entire filesystem
            max_depth = 5
            for root, dirs, files in os.walk(proton_path, followlinks=False):
                # Calculate depth relative to proton_path
                depth = len(Path(root).relative_to(proton_path).parts)
                if depth > max_depth:
                    dirs.clear()  # Don't descend further
                    continue
                
                # Check if 'wine' is in this directory
                if 'wine' in files:
                    wine_path = Path(root) / 'wine'
                    # Verify it's actually an executable file
                    if wine_path.is_file() and os.access(wine_path, os.X_OK):
                        self.logger.debug(f"Found wine binary at: {wine_path}")
                        return str(wine_path)

            return None
        except Exception as e:
            self.logger.debug(f"Error during recursive wine search in {proton_path}: {e}")
            return None
