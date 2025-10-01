#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Winetricks Handler Module
Handles wine component installation using bundled winetricks
"""

import os
import subprocess
import logging
from pathlib import Path
from typing import Optional, List

logger = logging.getLogger(__name__)


class WinetricksHandler:
    """
    Handles wine component installation using bundled winetricks
    """

    def __init__(self, logger=None):
        self.logger = logger or logging.getLogger(__name__)
        self.winetricks_path = self._get_bundled_winetricks_path()

    def _get_bundled_winetricks_path(self) -> Optional[str]:
        """
        Get the path to the bundled winetricks script following AppImage best practices
        """
        possible_paths = []

        # AppImage environment - use APPDIR (standard AppImage best practice)
        if os.environ.get('APPDIR'):
            appdir_path = os.path.join(os.environ['APPDIR'], 'opt', 'jackify', 'tools', 'winetricks')
            possible_paths.append(appdir_path)

        # Development environment - relative to module location
        module_dir = Path(__file__).parent.parent.parent  # Go from handlers/ up to jackify/
        dev_path = module_dir / 'tools' / 'winetricks'
        possible_paths.append(str(dev_path))

        # Try each path until we find one that works
        for path in possible_paths:
            if os.path.exists(path) and os.access(path, os.X_OK):
                self.logger.debug(f"Found bundled winetricks at: {path}")
                return str(path)

        self.logger.error(f"Bundled winetricks not found. Tried paths: {possible_paths}")
        return None

    def _get_bundled_cabextract(self) -> Optional[str]:
        """
        Get the path to the bundled cabextract binary, checking same locations as winetricks
        """
        possible_paths = []

        # AppImage environment - same pattern as winetricks detection
        if os.environ.get('APPDIR'):
            appdir_path = os.path.join(os.environ['APPDIR'], 'opt', 'jackify', 'tools', 'cabextract')
            possible_paths.append(appdir_path)

        # Development environment - relative to module location, same as winetricks
        module_dir = Path(__file__).parent.parent.parent  # Go from handlers/ up to jackify/
        dev_path = module_dir / 'tools' / 'cabextract'
        possible_paths.append(str(dev_path))

        # Try each path until we find one that works
        for path in possible_paths:
            if os.path.exists(path) and os.access(path, os.X_OK):
                self.logger.debug(f"Found bundled cabextract at: {path}")
                return str(path)

        # Fallback to system PATH
        try:
            import shutil
            system_cabextract = shutil.which('cabextract')
            if system_cabextract:
                self.logger.debug(f"Using system cabextract: {system_cabextract}")
                return system_cabextract
        except Exception:
            pass

        self.logger.warning("Bundled cabextract not found in tools directory")
        return None

    def is_available(self) -> bool:
        """
        Check if winetricks is available and ready to use
        """
        if not self.winetricks_path:
            self.logger.error("Bundled winetricks not found")
            return False

        try:
            env = os.environ.copy()
            result = subprocess.run(
                [self.winetricks_path, '--version'],
                capture_output=True,
                text=True,
                env=env,
                timeout=10
            )
            if result.returncode == 0:
                self.logger.debug(f"Winetricks version: {result.stdout.strip()}")
                return True
            else:
                self.logger.error(f"Winetricks --version failed: {result.stderr}")
                return False
        except Exception as e:
            self.logger.error(f"Error testing winetricks: {e}")
            return False

    def install_wine_components(self, wineprefix: str, game_var: str, specific_components: Optional[List[str]] = None) -> bool:
        """
        Install the specified Wine components into the given prefix using winetricks.
        If specific_components is None, use the default set (fontsmooth=rgb, xact, xact_x64, vcrun2022).
        """
        if not self.is_available():
            self.logger.error("Winetricks is not available")
            return False

        env = os.environ.copy()
        env['WINEDEBUG'] = '-all'  # Suppress Wine debug output
        env['WINEPREFIX'] = wineprefix
        env['WINETRICKS_GUI'] = 'none'  # Suppress GUI popups
        # Less aggressive popup suppression - don't completely disable display
        if 'DISPLAY' in env:
            # Keep DISPLAY but add window manager hints to prevent focus stealing
            env['WINEDLLOVERRIDES'] = 'winemenubuilder.exe=d'  # Disable Wine menu integration
        else:
            # No display available anyway
            env['DISPLAY'] = ''

        # Force winetricks to use Proton wine binary - NEVER fall back to system wine
        try:
            from ..handlers.config_handler import ConfigHandler
            from ..handlers.wine_utils import WineUtils

            config = ConfigHandler()
            user_proton_path = config.get_proton_path()

            # If user selected a specific Proton, try that first
            wine_binary = None
            if user_proton_path != 'auto':
                # Check if user-selected Proton still exists
                if os.path.exists(user_proton_path):
                    # Resolve symlinks to handle ~/.steam/steam -> ~/.local/share/Steam
                    resolved_proton_path = os.path.realpath(user_proton_path)

                    # Check for wine binary in different Proton structures
                    valve_proton_wine = os.path.join(resolved_proton_path, 'dist', 'bin', 'wine')
                    ge_proton_wine = os.path.join(resolved_proton_path, 'files', 'bin', 'wine')

                    if os.path.exists(valve_proton_wine):
                        wine_binary = valve_proton_wine
                        self.logger.info(f"Using user-selected Proton: {user_proton_path}")
                    elif os.path.exists(ge_proton_wine):
                        wine_binary = ge_proton_wine
                        self.logger.info(f"Using user-selected GE-Proton: {user_proton_path}")
                    else:
                        self.logger.warning(f"User-selected Proton path invalid: {user_proton_path}")
                else:
                    self.logger.warning(f"User-selected Proton no longer exists: {user_proton_path}")

            # Fall back to auto-detection if user selection failed or is 'auto'
            if not wine_binary:
                self.logger.info("Falling back to automatic Proton detection")
                best_proton = WineUtils.select_best_proton()
                if best_proton:
                    wine_binary = WineUtils.find_proton_binary(best_proton['name'])
                    self.logger.info(f"Auto-selected Proton: {best_proton['name']} at {best_proton['path']}")

            if not wine_binary:
                self.logger.error("Cannot run winetricks: No compatible Proton version found")
                return False

            if not (os.path.exists(wine_binary) and os.access(wine_binary, os.X_OK)):
                self.logger.error(f"Cannot run winetricks: Wine binary not found or not executable: {wine_binary}")
                return False

            env['WINE'] = str(wine_binary)
            self.logger.info(f"Using Proton wine binary for winetricks: {wine_binary}")

            # CRITICAL: Set up protontricks-compatible environment
            proton_dist_path = os.path.dirname(os.path.dirname(wine_binary))  # e.g., /path/to/proton/dist/bin/wine -> /path/to/proton/dist
            self.logger.debug(f"Proton dist path: {proton_dist_path}")

            # Set WINEDLLPATH like protontricks does
            env['WINEDLLPATH'] = f"{proton_dist_path}/lib64/wine:{proton_dist_path}/lib/wine"

            # Ensure Proton bin directory is first in PATH
            env['PATH'] = f"{proton_dist_path}/bin:{env.get('PATH', '')}"

            # Set DLL overrides exactly like protontricks
            dll_overrides = {
                "beclient": "b,n",
                "beclient_x64": "b,n",
                "dxgi": "n",
                "d3d9": "n",
                "d3d10core": "n",
                "d3d11": "n",
                "d3d12": "n",
                "d3d12core": "n",
                "nvapi": "n",
                "nvapi64": "n",
                "nvofapi64": "n",
                "nvcuda": "b"
            }

            # Merge with existing overrides
            existing_overrides = env.get('WINEDLLOVERRIDES', '')
            if existing_overrides:
                # Parse existing overrides
                for override in existing_overrides.split(';'):
                    if '=' in override:
                        name, value = override.split('=', 1)
                        dll_overrides[name] = value

            env['WINEDLLOVERRIDES'] = ';'.join(f"{name}={setting}" for name, setting in dll_overrides.items())

            # Set Wine defaults from protontricks
            env['WINE_LARGE_ADDRESS_AWARE'] = '1'
            env['DXVK_ENABLE_NVAPI'] = '1'

            self.logger.debug(f"Set protontricks environment: WINEDLLPATH={env['WINEDLLPATH']}")

        except Exception as e:
            self.logger.error(f"Cannot run winetricks: Failed to get Proton wine binary: {e}")
            return False

        # Set up bundled cabextract for winetricks
        bundled_cabextract = self._get_bundled_cabextract()
        if bundled_cabextract:
            env['PATH'] = f"{os.path.dirname(bundled_cabextract)}:{env.get('PATH', '')}"
            self.logger.info(f"Using bundled cabextract: {bundled_cabextract}")
        else:
            self.logger.warning("Bundled cabextract not found, relying on system PATH")

        # Set winetricks cache to jackify_data_dir for self-containment
        from jackify.shared.paths import get_jackify_data_dir
        jackify_cache_dir = get_jackify_data_dir() / 'winetricks_cache'
        jackify_cache_dir.mkdir(parents=True, exist_ok=True)
        env['WINETRICKS_CACHE'] = str(jackify_cache_dir)

        if specific_components is not None:
            all_components = specific_components
            self.logger.info(f"Installing specific components: {all_components}")
        else:
            all_components = ["fontsmooth=rgb", "xact", "xact_x64", "vcrun2022"]
            self.logger.info(f"Installing default components: {all_components}")

        if not all_components:
            self.logger.info("No Wine components to install.")
            return True

        # Reorder components for proper installation sequence
        components_to_install = self._reorder_components_for_installation(all_components)
        self.logger.info(f"WINEPREFIX: {wineprefix}, Game: {game_var}, Ordered Components: {components_to_install}")

        # Install components separately if dotnet40 is present (mimics protontricks behavior)
        if "dotnet40" in components_to_install:
            self.logger.info("dotnet40 detected - installing components separately like protontricks")
            return self._install_components_separately(components_to_install, wineprefix, wine_binary, env)

        # For non-dotnet40 installations, install all components together (faster)
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            if attempt > 1:
                self.logger.warning(f"Retrying component installation (attempt {attempt}/{max_attempts})...")
                self._cleanup_wine_processes()

            try:
                # Build winetricks command - using --unattended for silent installation
                cmd = [self.winetricks_path, '--unattended'] + components_to_install

                self.logger.debug(f"Running: {' '.join(cmd)}")
                self.logger.debug(f"Environment WINE={env.get('WINE', 'NOT SET')}")
                self.logger.debug(f"Environment DISPLAY={env.get('DISPLAY', 'NOT SET')}")
                self.logger.debug(f"Environment WINEPREFIX={env.get('WINEPREFIX', 'NOT SET')}")
                result = subprocess.run(
                    cmd,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=600
                )

                self.logger.debug(f"Winetricks output: {result.stdout}")
                if result.returncode == 0:
                    self.logger.info("Wine Component installation command completed successfully.")
                    return True
                else:
                    # Special handling for dotnet40 verification issue (mimics protontricks behavior)
                    if "dotnet40" in components_to_install and "ngen.exe not found" in result.stderr:
                        self.logger.warning("dotnet40 verification warning (common in Steam Proton prefixes)")
                        self.logger.info("Checking if dotnet40 was actually installed...")

                        # Check if dotnet40 appears in winetricks.log (indicates successful installation)
                        log_path = os.path.join(wineprefix, 'winetricks.log')
                        if os.path.exists(log_path):
                            try:
                                with open(log_path, 'r') as f:
                                    log_content = f.read()
                                if 'dotnet40' in log_content:
                                    self.logger.info("dotnet40 found in winetricks.log - installation succeeded despite verification warning")
                                    return True
                            except Exception as e:
                                self.logger.warning(f"Could not read winetricks.log: {e}")

                    self.logger.error(f"Winetricks command failed (Attempt {attempt}/{max_attempts}). Return Code: {result.returncode}")
                    self.logger.error(f"Stdout: {result.stdout.strip()}")
                    self.logger.error(f"Stderr: {result.stderr.strip()}")

            except Exception as e:
                self.logger.error(f"Error during winetricks run (Attempt {attempt}/{max_attempts}): {e}", exc_info=True)

        self.logger.error(f"Failed to install Wine components after {max_attempts} attempts.")
        return False

    def _reorder_components_for_installation(self, components: list) -> list:
        """
        Reorder components for proper installation sequence.
        Critical: dotnet40 must be installed before dotnet6/dotnet7 to avoid conflicts.
        """
        # Simple reordering: dotnet40 first, then everything else
        reordered = []

        # Add dotnet40 first if it exists
        if "dotnet40" in components:
            reordered.append("dotnet40")

        # Add all other components in original order
        for component in components:
            if component != "dotnet40":
                reordered.append(component)

        if reordered != components:
            self.logger.info(f"Reordered for dotnet40 compatibility: {reordered}")

        return reordered

    def _prepare_prefix_for_dotnet(self, wineprefix: str, wine_binary: str) -> bool:
        """
        Prepare the Wine prefix for .NET installation by mimicking protontricks preprocessing.
        This removes mono components and specific symlinks that interfere with .NET installation.
        """
        try:
            env = os.environ.copy()
            env['WINEDEBUG'] = '-all'
            env['WINEPREFIX'] = wineprefix

            # Step 1: Remove mono components (mimics protontricks behavior)
            self.logger.info("Preparing prefix for .NET installation: removing mono")
            mono_result = subprocess.run([
                self.winetricks_path,
                '-q',
                'remove_mono'
            ], env=env, capture_output=True, text=True, timeout=300)

            if mono_result.returncode != 0:
                self.logger.warning(f"Mono removal warning (non-critical): {mono_result.stderr}")

            # Step 2: Set Windows version to XP (protontricks uses winxp for dotnet40)
            self.logger.info("Setting Windows version to XP for .NET compatibility")
            winxp_result = subprocess.run([
                self.winetricks_path,
                '-q',
                'winxp'
            ], env=env, capture_output=True, text=True, timeout=300)

            if winxp_result.returncode != 0:
                self.logger.warning(f"Windows XP setting warning: {winxp_result.stderr}")

            # Step 3: Remove mscoree.dll symlinks (critical for .NET installation)
            self.logger.info("Removing problematic mscoree.dll symlinks")
            dosdevices_path = os.path.join(wineprefix, 'dosdevices', 'c:')
            mscoree_paths = [
                os.path.join(dosdevices_path, 'windows', 'syswow64', 'mscoree.dll'),
                os.path.join(dosdevices_path, 'windows', 'system32', 'mscoree.dll')
            ]

            for dll_path in mscoree_paths:
                if os.path.exists(dll_path) or os.path.islink(dll_path):
                    try:
                        os.remove(dll_path)
                        self.logger.debug(f"Removed symlink: {dll_path}")
                    except Exception as e:
                        self.logger.warning(f"Could not remove {dll_path}: {e}")

            self.logger.info("Prefix preparation complete for .NET installation")
            return True

        except Exception as e:
            self.logger.error(f"Error preparing prefix for .NET: {e}")
            return False

    def _install_components_separately(self, components: list, wineprefix: str, wine_binary: str, base_env: dict) -> bool:
        """
        Install components separately like protontricks does.
        This is necessary when dotnet40 is present to avoid component conflicts.
        """
        self.logger.info(f"Installing {len(components)} components separately (protontricks style)")

        for i, component in enumerate(components, 1):
            self.logger.info(f"Installing component {i}/{len(components)}: {component}")

            # Prepare environment for this component
            env = base_env.copy()

            # Special preprocessing for dotnet40 only
            if component == "dotnet40":
                self.logger.info("Applying dotnet40 preprocessing")
                if not self._prepare_prefix_for_dotnet(wineprefix, wine_binary):
                    self.logger.error("Failed to prepare prefix for dotnet40")
                    return False
            else:
                # For non-dotnet40 components, ensure we're in Windows 10 mode
                self.logger.debug(f"Installing {component} in standard mode")
                try:
                    subprocess.run([
                        self.winetricks_path, '-q', 'win10'
                    ], env=env, capture_output=True, text=True, timeout=300)
                except Exception as e:
                    self.logger.warning(f"Could not set win10 mode for {component}: {e}")

            # Install this component
            max_attempts = 3
            component_success = False

            for attempt in range(1, max_attempts + 1):
                if attempt > 1:
                    self.logger.warning(f"Retrying {component} installation (attempt {attempt}/{max_attempts})")
                    self._cleanup_wine_processes()

                try:
                    cmd = [self.winetricks_path, '--unattended', component]
                    env['WINEPREFIX'] = wineprefix
                    env['WINE'] = wine_binary

                    self.logger.debug(f"Running: {' '.join(cmd)}")

                    result = subprocess.run(
                        cmd,
                        env=env,
                        capture_output=True,
                        text=True,
                        timeout=600
                    )

                    if result.returncode == 0:
                        self.logger.info(f"✓ {component} installed successfully")
                        component_success = True
                        break
                    else:
                        # Special handling for dotnet40 verification issue
                        if component == "dotnet40" and "ngen.exe not found" in result.stderr:
                            self.logger.warning("dotnet40 verification warning (expected in Steam Proton)")

                            # Check winetricks.log for actual success
                            log_path = os.path.join(wineprefix, 'winetricks.log')
                            if os.path.exists(log_path):
                                try:
                                    with open(log_path, 'r') as f:
                                        if 'dotnet40' in f.read():
                                            self.logger.info("✓ dotnet40 confirmed in winetricks.log")
                                            component_success = True
                                            break
                                except Exception as e:
                                    self.logger.warning(f"Could not read winetricks.log: {e}")

                        self.logger.error(f"✗ {component} failed (attempt {attempt}): {result.stderr.strip()}")
                        self.logger.debug(f"Full stdout for {component}: {result.stdout.strip()}")

                except Exception as e:
                    self.logger.error(f"Error installing {component} (attempt {attempt}): {e}")

            if not component_success:
                self.logger.error(f"Failed to install {component} after {max_attempts} attempts")
                return False

        self.logger.info("✓ All components installed successfully using separate sessions")
        return True

    def _cleanup_wine_processes(self):
        """
        Internal method to clean up wine processes during component installation
        Only cleanup winetricks processes - NEVER kill all wine processes
        """
        try:
            # Only cleanup winetricks processes - do NOT kill other wine apps
            subprocess.run("pkill -f winetricks", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.logger.debug("Cleaned up winetricks processes only")
        except Exception as e:
            self.logger.error(f"Error cleaning up winetricks processes: {e}")