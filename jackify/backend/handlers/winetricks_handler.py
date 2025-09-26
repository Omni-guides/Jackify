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
            user_proton_path = config.get('proton_path', 'auto')

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
            components_to_install = specific_components
            self.logger.info(f"Installing specific components: {components_to_install}")
        else:
            components_to_install = ["fontsmooth=rgb", "xact", "xact_x64", "vcrun2022"]
            self.logger.info(f"Installing default components: {components_to_install}")

        if not components_to_install:
            self.logger.info("No Wine components to install.")
            return True

        self.logger.info(f"WINEPREFIX: {wineprefix}, Game: {game_var}, Components: {components_to_install}")

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
                    self.logger.error(f"Winetricks command failed (Attempt {attempt}/{max_attempts}). Return Code: {result.returncode}")
                    self.logger.error(f"Stdout: {result.stdout.strip()}")
                    self.logger.error(f"Stderr: {result.stderr.strip()}")

            except Exception as e:
                self.logger.error(f"Error during winetricks run (Attempt {attempt}/{max_attempts}): {e}", exc_info=True)

        self.logger.error(f"Failed to install Wine components after {max_attempts} attempts.")
        return False

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