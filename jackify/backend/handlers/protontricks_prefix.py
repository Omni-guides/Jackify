#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Protontricks prefix/Wine component mixin.
Extracted from protontricks_handler for file-size and domain separation.
"""

import os
import subprocess
from pathlib import Path
from typing import Optional, List

import logging

logger = logging.getLogger(__name__)


class ProtontricksPrefixMixin:
    """Mixin for Wine prefix operations: dotfiles, win10, prefix path, component install/verify."""

    def enable_dotfiles(self, appid):
        """Enable visibility of (.)dot files in the Wine prefix. Returns True on success."""
        self.logger.debug(f"APPID={appid}")
        self.logger.info("Enabling visibility of (.)dot files...")
        try:
            result = self.run_protontricks(
                "-c", "WINEDEBUG=-all wine reg query \"HKEY_CURRENT_USER\\Software\\Wine\" /v ShowDotFiles",
                appid,
                stderr=subprocess.DEVNULL
            )
            if result and result.returncode == 0 and "ShowDotFiles" in result.stdout and "Y" in result.stdout:
                self.logger.info("DotFiles already enabled via registry... skipping")
                return True
            elif result and result.returncode != 0:
                self.logger.info(f"Initial query for ShowDotFiles likely failed (Exit Code: {result.returncode}). Proceeding to set it. Stderr: {result.stderr}")
            elif not result:
                self.logger.error("Failed to execute initial dotfile query command.")

            dotfiles_set_success = False
            self.logger.debug("Attempting to set ShowDotFiles registry key...")
            result_add = self.run_protontricks(
                "-c", "WINEDEBUG=-all wine reg add \"HKEY_CURRENT_USER\\Software\\Wine\" /v ShowDotFiles /d Y /f",
                appid,
            )
            if result_add and result_add.returncode == 0:
                self.logger.info("'wine reg add' command executed successfully.")
                dotfiles_set_success = True
            elif result_add:
                self.logger.warning(f"'wine reg add' command failed (Exit Code: {result_add.returncode}). Stderr: {result_add.stderr}")
            else:
                self.logger.error("Failed to execute 'wine reg add' command.")

            self.logger.debug("Ensuring user.reg has correct entry...")
            prefix_path = self.get_wine_prefix_path(appid)
            if prefix_path:
                user_reg_path = Path(prefix_path) / "user.reg"
                try:
                    if user_reg_path.exists():
                        content = user_reg_path.read_text(encoding='utf-8', errors='ignore')
                        has_correct_format = '[Software\\\\Wine]' in content and '"ShowDotFiles"="Y"' in content
                        has_broken_format = '[SoftwareWine]' in content and '"ShowDotFiles"="Y"' in content
                        if has_broken_format and not has_correct_format:
                            self.logger.debug(f"Found broken ShowDotFiles format in {user_reg_path}, fixing...")
                            content = content.replace('[SoftwareWine]', '[Software\\\\Wine]')
                            user_reg_path.write_text(content, encoding='utf-8')
                            dotfiles_set_success = True
                        elif not has_correct_format:
                            self.logger.debug(f"Adding ShowDotFiles entry to {user_reg_path}")
                            with open(user_reg_path, 'a', encoding='utf-8') as f:
                                f.write('\n[Software\\\\Wine] 1603891765\n')
                                f.write('"ShowDotFiles"="Y"\n')
                            dotfiles_set_success = True
                        else:
                            self.logger.debug("ShowDotFiles already present in correct format in user.reg")
                            dotfiles_set_success = True
                    else:
                        self.logger.info(f"user.reg not found at {user_reg_path}, creating it.")
                        with open(user_reg_path, 'w', encoding='utf-8') as f:
                            f.write('[Software\\\\Wine] 1603891765\n')
                            f.write('"ShowDotFiles"="Y"\n')
                        dotfiles_set_success = True
                except Exception as e:
                    self.logger.warning(f"Error reading/writing user.reg: {e}")
            else:
                self.logger.warning("Could not get WINEPREFIX path, skipping user.reg modification.")

            self.logger.debug("Verifying dotfile setting after attempts...")
            verify_result = self.run_protontricks(
                "-c", "WINEDEBUG=-all wine reg query \"HKEY_CURRENT_USER\\Software\\Wine\" /v ShowDotFiles",
                appid,
                stderr=subprocess.DEVNULL
            )
            query_verified = False
            if verify_result and verify_result.returncode == 0 and "ShowDotFiles" in verify_result.stdout and "Y" in verify_result.stdout:
                self.logger.debug("Verification query successful and key is set.")
                query_verified = True
            elif verify_result:
                self.logger.info(f"Verification query failed or key not found (Exit Code: {verify_result.returncode}). Stderr: {verify_result.stderr}")
            else:
                self.logger.error("Failed to execute verification query command.")

            if dotfiles_set_success:
                if query_verified:
                    self.logger.info("Dotfiles enabled and verified successfully!")
                else:
                    self.logger.info("Dotfiles potentially enabled (reg add/user.reg succeeded), but verification query failed.")
                return True
            self.logger.error("Failed to enable dotfiles using registry and user.reg methods.")
            return False
        except Exception as e:
            self.logger.error(f"Unexpected error enabling dotfiles: {e}", exc_info=True)
            return False

    def set_win10_prefix(self, appid):
        """Set Windows 10 version in the proton prefix. Returns True on success."""
        try:
            env = self._get_clean_subprocess_env()
            env["WINEDEBUG"] = "-all"
            if self.which_protontricks == 'flatpak':
                cmd = self._get_flatpak_run_args() + ["com.github.Matoking.protontricks", "--no-bwrap", appid, "win10"]
            else:
                cmd = ["protontricks", "--no-bwrap", appid, "win10"]
            subprocess.run(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception as e:
            self.logger.error(f"Error setting Windows 10 prefix: {e}")
            return False

    def get_wine_prefix_path(self, appid, log_missing: bool = True) -> Optional[str]:
        """
        Get the WINEPREFIX path for a given AppID.
        Uses native path discovery when enabled, else protontricks -c echo $WINEPREFIX.

        log_missing=False downgrades the not-found log to debug, for callers where a
        missing prefix is an expected state rather than a fault.
        """
        if self.use_native_operations:
            self.logger.debug(f"Getting WINEPREFIX for AppID {appid} via native path discovery")
            try:
                return self._get_native_steam_service().get_wine_prefix_path(
                    appid, log_missing=log_missing
                )
            except Exception as e:
                self.logger.warning(f"Native WINEPREFIX detection failed, falling back to protontricks: {e}")

        self.logger.debug(f"Getting WINEPREFIX for AppID {appid}")
        result = self.run_protontricks("-c", "echo $WINEPREFIX", appid)
        if result and result.returncode == 0 and result.stdout.strip():
            prefix_path = result.stdout.strip()
            self.logger.debug(f"Detected WINEPREFIX: {prefix_path}")
            return prefix_path
        message = f"Failed to get WINEPREFIX for AppID {appid}. Stderr: {result.stderr if result else 'N/A'}"
        if log_missing:
            self.logger.error(message)
        else:
            self.logger.debug(message)
        return None

    def install_wine_components(self, appid, game_var, specific_components: Optional[List[str]] = None):
        """
        Install Wine components into the prefix using protontricks.
        If specific_components is None, use default set (fontsmooth=rgb, xact, xact_x64, vcrun2022).
        """
        self.logger.info("=" * 80)
        self.logger.info("USING PROTONTRICKS")
        self.logger.info("=" * 80)
        env = self._get_clean_subprocess_env()
        env["WINEDEBUG"] = "-all"
        # Preserve the desktop display variables for Step 4. The validated fix
        # for the blank taskbar popup regression was keeping DISPLAY available.
        # Do not strip extra desktop activation vars here without a reproduced,
        # evidence-backed need.

        if self.which_protontricks == 'native':
            winetricks_path = self._get_bundled_winetricks_path()
            if winetricks_path:
                env['WINETRICKS'] = str(winetricks_path)
                self.logger.debug(f"Set WINETRICKS for native protontricks: {winetricks_path}")
            else:
                self.logger.info("Bundled winetricks not found - native protontricks will use system winetricks")
            cabextract_path = self._get_bundled_cabextract_path()
            if cabextract_path:
                cabextract_dir = str(cabextract_path.parent)
                current_path = env.get('PATH', '')
                env['PATH'] = f"{cabextract_dir}{os.pathsep}{current_path}" if current_path else cabextract_dir
                self.logger.debug(f"Added bundled cabextract to PATH for native protontricks: {cabextract_dir}")
            else:
                self.logger.info("Bundled cabextract not found - native protontricks will use system cabextract")
        else:
            self.logger.info(f"Using {self.which_protontricks} protontricks - it has its own winetricks (cannot access AppImage mounts)")

        from ..handlers.config_handler import ConfigHandler
        config_handler = ConfigHandler()
        debug_mode = config_handler.get('debug_mode', False)
        if not debug_mode:
            env['WINETRICKS_SUPER_QUIET'] = '1'
            self.logger.debug("Set WINETRICKS_SUPER_QUIET=1 in install_wine_components to suppress winetricks verbose output")

        from jackify.shared.paths import get_jackify_data_dir
        jackify_cache_dir = get_jackify_data_dir() / 'winetricks_cache'
        jackify_cache_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_flatpak_cache_access(jackify_cache_dir)
        env['WINETRICKS_CACHE'] = str(jackify_cache_dir)
        self.logger.info(f"Using winetricks cache: {jackify_cache_dir}")

        if specific_components is not None:
            components_to_install = specific_components
            self.logger.info(f"Installing specific components: {components_to_install}")
        else:
            components_to_install = ["fontsmooth=rgb", "xact", "xact_x64", "vcrun2022"]
            self.logger.info(f"Installing default components: {components_to_install}")
        if not components_to_install:
            self.logger.info("No Wine components to install.")
            return True
        self.logger.info(f"AppID: {appid}, Game: {game_var}, Components: {components_to_install}")
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            if attempt > 1:
                self.logger.warning(f"Retrying component installation (attempt {attempt}/{max_attempts})...")
                self._cleanup_wine_processes()
            try:
                result = self.run_protontricks("--no-bwrap", appid, "-q", *components_to_install, env=env, timeout=600)
                self.logger.debug(f"Protontricks output: {result.stdout if result else ''}")
                if result and result.returncode == 0:
                    self.logger.info("Wine Component installation command completed.")
                    if self._verify_components_installed(appid, components_to_install):
                        self.logger.info("Component verification successful - all components installed correctly.")
                        return True
                    self.logger.error(f"Component verification failed (Attempt {attempt}/{max_attempts})")
                else:
                    self.logger.error(f"Protontricks command failed (Attempt {attempt}/{max_attempts}). Return Code: {result.returncode if result else 'N/A'}")
                    config_handler = ConfigHandler()
                    debug_mode = config_handler.get('debug_mode', False)
                    if debug_mode:
                        self.logger.error(f"Stdout: {result.stdout.strip() if result else ''}")
                        self.logger.error(f"Stderr: {result.stderr.strip() if result else ''}")
                    elif result and result.stderr:
                        stderr_lower = result.stderr.lower()
                        if any(k in stderr_lower for k in ['error', 'failed', 'cannot', 'warning: cannot find']):
                            error_lines = [line for line in result.stderr.strip().split('\n')
                                          if any(k in line.lower() for k in ['error', 'failed', 'cannot', 'warning: cannot find'])
                                          and 'executing' not in line.lower()]
                            if error_lines:
                                self.logger.error(f"Stderr (errors only): {' '.join(error_lines)}")
            except Exception as e:
                self.logger.error(f"Error during protontricks run (Attempt {attempt}/{max_attempts}): {e}", exc_info=True)
        self.logger.error(f"Failed to install Wine components after {max_attempts} attempts.")
        return False

    def _verify_components_installed(self, appid: str, components: List[str]) -> bool:
        """Verify every requested component is present in protontricks list-installed."""
        try:
            self.logger.info("Verifying installed components...")
            result = self.run_protontricks("--no-bwrap", appid, "list-installed", timeout=30)
            if not result or result.returncode != 0:
                self.logger.error("Failed to query installed components")
                self.logger.debug(f"list-installed stderr: {result.stderr if result else 'N/A'}")
                return False
            installed_output = result.stdout.lower()
            self.logger.debug(f"Installed components output: {installed_output}")
            missing = []
            for component in components:
                base_component = component.split('=')[0].lower()
                if base_component in installed_output or component.lower() in installed_output:
                    continue
                missing.append(component)
            if missing:
                self.logger.error(f"Components not in list-installed: {missing}")
                return False
            self.logger.info("Verification passed - all components in list-installed")
            return True
        except Exception as e:
            self.logger.error(f"Error verifying components: {e}", exc_info=True)
            return False

    def _cleanup_wine_processes(self):
        """Clean up wine-related processes during component installation."""
        try:
            subprocess.run("pgrep -f 'win7|win10|ShowDotFiles|protontricks' | xargs -r kill -9",
                          shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run("pkill -9 winetricks",
                          shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            self.logger.error(f"Error cleaning up wine processes: {e}")
