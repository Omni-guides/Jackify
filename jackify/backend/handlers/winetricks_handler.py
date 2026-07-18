#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Winetricks Handler Module
Handles wine component installation using bundled winetricks.
Discovery, installation strategy, and verification live in mixins.
"""

import os
import shutil
import subprocess
import logging
from pathlib import Path
from typing import Optional, List, Callable

from .winetricks_discovery import WinetricksDiscoveryMixin
from .winetricks_env import WinetricksEnvMixin
from .winetricks_installation import WinetricksInstallationMixin
from .winetricks_verification import WinetricksVerificationMixin

logger = logging.getLogger(__name__)


class WinetricksHandler(
    WinetricksDiscoveryMixin,
    WinetricksEnvMixin,
    WinetricksInstallationMixin,
    WinetricksVerificationMixin,
):
    """Handles wine component installation. Discovery, installation, verification in mixins."""

    def __init__(self, logger=None):
        self.logger = logger or logging.getLogger(__name__)
        self.winetricks_path = self._get_bundled_winetricks_path()

    def install_wine_components(self, wineprefix: str, game_var: str, specific_components: Optional[List[str]] = None, status_callback: Optional[Callable[[str], None]] = None, appid: Optional[str] = None) -> bool:
        """
        Install the specified Wine components into the given prefix using winetricks.
        If specific_components is None, use the default set (fontsmooth=rgb, xact, xact_x64, vcrun2022).

        Args:
            wineprefix: Path to Wine prefix
            game_var: Game name for logging
            specific_components: Optional list of specific components to install
            status_callback: Optional callback function(status_message: str) for progress updates
            appid: Optional Steam App ID (for fallback or logging)
        """
        if not self.is_available():
            self.logger.error("Winetricks is not available")
            return False

        env, components_to_install = self._build_winetricks_env(wineprefix, status_callback, specific_components)
        if env is None:
            return False
        if not components_to_install:
            return True

        native_wineprefix = env.get('WINEPREFIX', wineprefix)
        wine_binary = env.get('WINE', '')

        # Check user preference for component installation method
        from ..handlers.config_handler import ConfigHandler
        config_handler = ConfigHandler()

        # Get component installation method with migration
        method = config_handler.get('component_installation_method', 'native')

        # Migrate bundled_protontricks to system_protontricks (no longer supported)
        if method == 'bundled_protontricks':
            self.logger.warning("Bundled protontricks no longer supported, migrating to system_protontricks")
            method = 'system_protontricks'
            config_handler.set('component_installation_method', 'system_protontricks')

        # Native installer tier: direct-source downloads, no winetricks dependency.
        # Only runs in "native" mode - "winetricks" and "system_protontricks" are explicit
        # full-bypass modes, e.g. as an escape hatch if a native install regression ships.
        native = None
        if method == 'native' and wine_binary:
            try:
                from .native_component_installer import NativeComponentInstaller
                native = NativeComponentInstaller(native_wineprefix, wine_binary, env, self.logger)
            except Exception as native_exc:
                self.logger.warning("Native installer init failed: %s", native_exc)

        if native:
            try:
                _native_ok, components_to_install = native.install_components(
                    components_to_install, status_callback
                )
                if not components_to_install:
                    self._set_windows_10_mode_after_install(native_wineprefix, env)
                    return True
            except Exception as native_exc:
                self.logger.warning("Native installer skipped due to error: %s", native_exc)

        # dotnet48 (NSF/CSF modlists) installs via the bundled winetricks verb. Fully remove
        # Wine Mono first (files + mscoree stub + uninstaller entry + its NDP registry keys) so
        # the prefix is in the clean "no .NET, no mono" state a fresh winetricks dotnet48 expects:
        # this avoids the "same or higher version already installed" bail (the NDP keys are
        # mono-registered, winetricks #2367) and lets winetricks complete the .NET first-run
        # during the verb, so it does not fire at game launch.
        # The status message persists through the install (the main winetricks call emits none
        # before it blocks), so the UI shows dotnet48 rather than the prior native component.
        if 'dotnet48' in components_to_install:
            if status_callback:
                status_callback("[NATIVE_INSTALL] dotnet48")
                status_callback("Installing .NET Framework 4.8 (dotnet48) - the long step, can take several minutes")
            self.logger.info("Installing dotnet48 via winetricks (NSF/CSF) - long-running step")
            self._kill_wineserver_for_prefix(env)
            self._remove_wine_mono(native_wineprefix)

        # Flatpak Steam: use protontricks only; bundled winetricks is unreliable (e.g. from AppImage)
        flatpak_steam = False
        try:
            from ..services.steam_restart_service import is_flatpak_steam
            flatpak_steam = is_flatpak_steam()
        except Exception as e:
            self.logger.debug("Could not check Flatpak Steam via CLI: %s", e)
        if not flatpak_steam and self._is_flatpak_steam_prefix(wineprefix):
            flatpak_steam = True
            self.logger.info("Flatpak Steam prefix detected (path): using protontricks only")
        if flatpak_steam:
            self.logger.info("Flatpak Steam detected: using protontricks only for component installation")
            return self._install_components_protontricks_only(
                components_to_install, wineprefix, game_var, status_callback, appid=appid
            )

        # Choose installation method based on user preference
        if method == 'system_protontricks':
            self.logger.info("=" * 80)
            self.logger.info("USING PROTONTRICKS")
            self.logger.info("=" * 80)
            self.logger.info("Using system protontricks for all components")
            return self._install_components_protontricks_only(components_to_install, wineprefix, game_var, status_callback)

        # Install all components together with winetricks (faster)
        self.logger.info("=" * 80)
        self.logger.info("USING WINETRICKS")
        self.logger.info("=" * 80)
        max_attempts = 3
        winetricks_failed = False
        last_error_details = None

        for attempt in range(1, max_attempts + 1):
            if attempt > 1:
                self.logger.warning(f"Retrying component installation (attempt {attempt}/{max_attempts})...")
                self._cleanup_wine_processes()
            elif attempt == 1:
                self._kill_wineserver_for_prefix(env)

            try:
                cmd = [self.winetricks_path, '--unattended'] + components_to_install
                run_env = env

                # Log full command for advanced users to reproduce manually (debug mode only)
                cmd_str = ' '.join(cmd)
                self.logger.debug("=" * 80)
                self.logger.debug("WINETRICKS COMMAND (for manual reproduction):")
                self.logger.debug(f"  {cmd_str}")
                self.logger.debug("")
                self.logger.debug("Environment variables required:")
                self.logger.debug(f"  WINEPREFIX={env.get('WINEPREFIX', 'NOT SET')}")
                self.logger.debug(f"  WINE={env.get('WINE', 'NOT SET')}")
                self.logger.debug(f"  WINESERVER={env.get('WINESERVER', 'NOT SET')}")
                self.logger.debug("=" * 80)

                # Enhanced diagnostics for bundled winetricks
                self.logger.debug("=== Winetricks Environment Diagnostics ===")
                self.logger.debug(f"Bundled winetricks path: {self.winetricks_path}")
                self.logger.debug(f"Winetricks exists: {os.path.exists(self.winetricks_path)}")
                self.logger.debug(f"Winetricks executable: {os.access(self.winetricks_path, os.X_OK)}")
                if os.path.exists(self.winetricks_path):
                    try:
                        winetricks_stat = os.stat(self.winetricks_path)
                        self.logger.debug(f"Winetricks permissions: {oct(winetricks_stat.st_mode)}")
                        self.logger.debug(f"Winetricks size: {winetricks_stat.st_size} bytes")
                    except Exception as stat_err:
                        self.logger.debug(f"Could not stat winetricks: {stat_err}")

                self.logger.debug(f"WINE binary: {env.get('WINE', 'NOT SET')}")
                wine_binary = env.get('WINE', '')
                if wine_binary and os.path.exists(wine_binary):
                    self.logger.debug(f"WINE binary exists: True")
                else:
                    self.logger.debug(f"WINE binary exists: False")

                self.logger.debug(f"WINEPREFIX: {env.get('WINEPREFIX', 'NOT SET')}")
                wineprefix = env.get('WINEPREFIX', '')
                if wineprefix and os.path.exists(wineprefix):
                    self.logger.debug(f"WINEPREFIX exists: True")
                    self.logger.debug(f"WINEPREFIX/pfx exists: {os.path.exists(os.path.join(wineprefix, 'pfx'))}")
                else:
                    self.logger.debug(f"WINEPREFIX exists: False")

                self.logger.debug(f"DISPLAY: {env.get('DISPLAY', 'NOT SET')}")
                self.logger.debug(f"WINETRICKS_CACHE: {env.get('WINETRICKS_CACHE', 'NOT SET')}")
                self.logger.debug(f"Components to install: {components_to_install}")
                self.logger.debug("==========================================")

                result = subprocess.run(
                    cmd,
                    env=run_env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=600
                )

                self.logger.debug(f"Winetricks output: {result.stdout}")
                if result.returncode == 0:
                    self.logger.info("Wine Component installation command completed.")

                    # Verify components were actually installed
                    if self._verify_components_installed(wineprefix, components_to_install, env):
                        self.logger.info("Component verification successful - all components installed correctly.")
                        components_list = ', '.join(components_to_install)
                        if status_callback:
                            status_callback(f"Wine components installed and verified: {components_list}")
                        self._set_windows_10_mode_after_install(wineprefix, env)
                        return True
                    else:
                        self.logger.error(f"Component verification failed (Attempt {attempt}/{max_attempts})")
                        winetricks_failed = True
                elif result.returncode == 1 and "returned status 120" in result.stderr and "aborting" in result.stderr.lower():
                    # VC redist / some installers return 120 under Wine (ERROR_CALL_NOT_IMPLEMENTED); install may still have succeeded
                    self.logger.info("Winetricks returned 1 with status 120 (installer quirk under Wine); verifying components...")
                    if self._verify_components_installed(wineprefix, components_to_install, env):
                        self.logger.info("Component verification passed after status 120 - accepting as success.")
                        if status_callback:
                            status_callback(f"Wine components installed and verified: {', '.join(components_to_install)}")
                        self._set_windows_10_mode_after_install(wineprefix, env)
                        return True
                    last_error_details = {'returncode': result.returncode, 'stdout': result.stdout.strip(), 'stderr': result.stderr.strip(), 'attempt': attempt}
                    winetricks_failed = True
                else:
                    # Store detailed error information for fallback diagnostics
                    last_error_details = {
                        'returncode': result.returncode,
                        'stdout': result.stdout.strip(),
                        'stderr': result.stderr.strip(),
                        'attempt': attempt
                    }

                    # Log full error details to help diagnose failures
                    self.logger.error("=" * 80)
                    self.logger.error(f"WINETRICKS FAILED (Attempt {attempt}/{max_attempts})")
                    self.logger.error(f"Return Code: {result.returncode}")
                    self.logger.error("")
                    self.logger.error("STDOUT:")
                    if result.stdout.strip():
                        for line in result.stdout.strip().split('\n'):
                            self.logger.error(f"  {line}")
                    else:
                        self.logger.error("  (empty)")
                    self.logger.error("")
                    self.logger.error("STDERR:")
                    if result.stderr.strip():
                        # Filter out verbose winetricks "Executing..." messages - these are informational, not errors
                        error_lines = []
                        verbose_lines = []
                        for line in result.stderr.strip().split('\n'):
                            line_lower = line.lower().strip()
                            # Skip verbose informational messages
                            if (line_lower.startswith('executing ') or 
                                (line_lower.startswith('grep: warning:') and 'stray' in line_lower) or
                                ('warning; possible' in line_lower and 'extra bytes' in line_lower)):
                                # These are verbose info messages, log at debug level instead
                                verbose_lines.append(line)
                            else:
                                # Actual error/warning messages (including "returned status", "aborting", dbus errors, etc.)
                                error_lines.append(line)
                        
                        if error_lines:
                            self.logger.error("  Actual errors/warnings:")
                            for line in error_lines:
                                self.logger.error(f"  {line}")
                            if verbose_lines:
                                self.logger.debug(f"  ({len(verbose_lines)} verbose 'Executing...' lines suppressed - see debug log for details)")
                        else:
                            self.logger.error("  (only verbose output, no actual errors)")
                            if verbose_lines:
                                self.logger.debug(f"  ({len(verbose_lines)} verbose lines suppressed)")
                    else:
                        self.logger.error("  (empty)")
                    self.logger.error("=" * 80)

                    # Enhanced error diagnostics with actionable information
                    stderr_lower = result.stderr.lower()
                    stdout_lower = result.stdout.lower()
                    
                    # Log which diagnostic category matches
                    diagnostic_found = False

                    if "command not found" in stderr_lower or "no such file" in stderr_lower:
                        self.logger.error("DIAGNOSTIC: Winetricks or dependency binary not found")
                        self.logger.error("  - Bundled winetricks may be missing dependencies")
                        self.logger.error("  - Check dependency check output above for missing tools")
                        self.logger.error("  - Will attempt protontricks fallback if all attempts fail")
                        diagnostic_found = True
                    elif ("returned status" in stderr_lower and "aborting" in stderr_lower) or "connection reset by peer" in stderr_lower:
                        self.logger.error("DIAGNOSTIC: Wine/Proton command failed (regedit, VC redist, etc.)")
                        self.logger.error("  - Wine subprocess returned non-zero or wineserver connection reset")
                        self.logger.error("  - Common when running winetricks from AppImage against Proton prefix; protontricks fallback uses same prefix from inside Steam env")
                        diagnostic_found = True
                    elif "w_metadata" in stderr_lower and ("unix path" in stderr_lower or "windows path" in stderr_lower):
                        self.logger.error("DIAGNOSTIC: Winetricks metadata bug (e.g. jet40 installed_file path)")
                        self.logger.error("  - Known winetricks bug: component metadata uses Unix path instead of Windows path")
                        self.logger.error("  - Upstream fix in newer winetricks; protontricks fallback will be used")
                        diagnostic_found = True
                    elif "permission denied" in stderr_lower:
                        self.logger.error("DIAGNOSTIC: Permission issue detected")
                        self.logger.error(f"  - Check permissions on: {self.winetricks_path}")
                        self.logger.error(f"  - Check permissions on WINEPREFIX: {env.get('WINEPREFIX', 'N/A')}")
                        diagnostic_found = True
                    elif "timeout" in stderr_lower:
                        self.logger.error("DIAGNOSTIC: Timeout issue detected during component download/install")
                        self.logger.error("  - Network may be slow or unstable")
                        self.logger.error("  - Component download may be taking too long")
                        diagnostic_found = True
                    elif "sha256sum mismatch" in stderr_lower or ("checksum" in stderr_lower and ("fail" in stderr_lower or "mismatch" in stderr_lower)):
                        self.logger.error("DIAGNOSTIC: Checksum verification failed")
                        self.logger.error("  - Component download may be corrupted")
                        self.logger.error("  - Network issue or upstream file change")
                        diagnostic_found = True
                    elif ("please install" in stderr_lower or "please install" in stdout_lower) and ("wget" in stderr_lower or "aria2c" in stderr_lower or "curl" in stderr_lower or "wget" in stdout_lower or "aria2c" in stdout_lower or "curl" in stdout_lower):
                        # Winetricks explicitly says to install a downloader
                        self._handle_missing_downloader_error()
                        diagnostic_found = True
                    elif "curl" in stderr_lower or "wget" in stderr_lower or "aria2c" in stderr_lower:
                        self.logger.error("DIAGNOSTIC: Download tool (curl/wget/aria2c) issue")
                        self.logger.error("  - Network connectivity problem or missing download tool")
                        self.logger.error("  - Check dependency check output above")
                        diagnostic_found = True
                    elif "cabextract" in stderr_lower and ("not found" in stderr_lower or "failed" in stderr_lower or "command not found" in stderr_lower or "no such file" in stderr_lower):
                        self.logger.error("DIAGNOSTIC: cabextract missing or failed")
                        self.logger.error("  - Required for extracting Windows cabinet files")
                        self.logger.error("  - Bundled cabextract should be available, check PATH")
                        diagnostic_found = True
                    elif ("unzip" in stderr_lower or "7z" in stderr_lower) and ("not found" in stderr_lower or "failed" in stderr_lower or "error" in stderr_lower):
                        self.logger.error("DIAGNOSTIC: Archive extraction tool (unzip/7z) missing or failed")
                        self.logger.error("  - Required for extracting zip/7z archives")
                        self.logger.error("  - Check dependency check output above")
                        diagnostic_found = True
                    
                    if not diagnostic_found:
                        self.logger.error("DIAGNOSTIC: Unknown winetricks failure pattern")
                        self.logger.error("  - Error details logged above (STDOUT/STDERR)")
                        self.logger.error("  - Check dependency check output above for missing tools")
                        self.logger.error("  - Will attempt protontricks fallback if all attempts fail")

                    winetricks_failed = True

            except subprocess.TimeoutExpired as e:
                self.logger.error(f"Winetricks timed out (Attempt {attempt}/{max_attempts}): {e}")
                last_error_details = {'error': 'timeout', 'attempt': attempt}
                winetricks_failed = True
            except Exception as e:
                self.logger.error(f"Error during winetricks run (Attempt {attempt}/{max_attempts}): {e}", exc_info=True)
                last_error_details = {'error': str(e), 'attempt': attempt}
                winetricks_failed = True

        # All winetricks attempts failed - try automatic fallback to protontricks
        if winetricks_failed:
            self.logger.error("=" * 80)
            self.logger.error(f"WINETRICKS FAILED AFTER {max_attempts} ATTEMPTS")
            self.logger.error("")
            if last_error_details:
                self.logger.error("Last error details:")
                if 'returncode' in last_error_details:
                    self.logger.error(f"  Return code: {last_error_details['returncode']}")
                if 'stderr' in last_error_details and last_error_details['stderr']:
                    self.logger.error(f"  Last stderr (first 500 chars): {last_error_details['stderr'][:500]}")
                if 'stdout' in last_error_details and last_error_details['stdout']:
                    self.logger.error(f"  Last stdout (first 500 chars): {last_error_details['stdout'][:500]}")
            self.logger.error("")
            self.logger.error("Attempting automatic fallback to protontricks...")
            self.logger.error("=" * 80)

            # Network diagnostics before fallback (non-fatal)
            self.logger.warning("=" * 80)
            self.logger.warning("NETWORK DIAGNOSTICS: Testing connectivity to component download sources...")
            try:
                # Check if curl is available
                curl_check = subprocess.run(['which', 'curl'], capture_output=True, timeout=5)
                if curl_check.returncode == 0:
                    # Test Microsoft download servers (used by winetricks for .NET, VC runtimes, DirectX)
                    test_result = subprocess.run(['curl', '-I', '--max-time', '10', 'https://download.microsoft.com'],
                                                capture_output=True, text=True, timeout=15)
                    if test_result.returncode == 0:
                        self.logger.warning("Can reach download.microsoft.com")
                    else:
                        self.logger.error("Cannot reach download.microsoft.com - network/DNS issue likely")
                        self.logger.error(f"  Curl exit code: {test_result.returncode}")
                        if test_result.stderr:
                            self.logger.error(f"  Curl error: {test_result.stderr.strip()}")
                else:
                    self.logger.warning("curl not available, skipping network diagnostic test")
            except Exception as e:
                self.logger.warning(f"Network diagnostic test skipped: {e}")
            self.logger.warning("=" * 80)

            # Check if protontricks is available for fallback using centralized handler
            try:
                from .protontricks_handler import ProtontricksHandler
                steamdeck = os.path.exists('/home/deck')
                protontricks_handler = ProtontricksHandler(steamdeck)
                protontricks_available = protontricks_handler.detect_protontricks()

                if protontricks_available:
                    self.logger.warning("=" * 80)
                    self.logger.warning("AUTOMATIC FALLBACK: Winetricks failed, attempting protontricks fallback...")
                    self.logger.warning(f"Last winetricks error: {last_error_details}")
                    self.logger.warning("=" * 80)
                    self.logger.info("=" * 80)
                    self.logger.info("USING PROTONTRICKS")
                    self.logger.info("=" * 80)

                    # Attempt fallback to protontricks
                    fallback_success = self._install_components_protontricks_only(components_to_install, wineprefix, game_var, status_callback)

                    if fallback_success:
                        self.logger.info("SUCCESS: Protontricks fallback succeeded where winetricks failed")
                        return True
                    else:
                        self.logger.error("FAILURE: Both winetricks and protontricks fallback failed")
                        return False
                else:
                    self.logger.error("Protontricks not available for fallback")
                    self.logger.error(f"Final winetricks error details: {last_error_details}")
                    return False
            except Exception as e:
                self.logger.error(f"Could not check for protontricks fallback: {e}")
                return False

        return False

    def _handle_missing_downloader_error(self):
        """Handle winetricks error indicating missing downloader - provide platform-specific instructions"""
        from ..services.platform_detection_service import PlatformDetectionService
        
        platform = PlatformDetectionService.get_instance()
        is_steamos = platform.is_steamdeck
        
        self.logger.error("=" * 80)
        self.logger.error("CRITICAL: Winetricks cannot find a downloader (curl, wget, or aria2c)")
        self.logger.error("")
        
        if is_steamos:
            self.logger.error("STEAMOS/STEAM DECK DETECTED")
            self.logger.error("")
            self.logger.error("SteamOS has a read-only filesystem. To install packages:")
            self.logger.error("")
            self.logger.error("1. Disable read-only mode (required for package installation):")
            self.logger.error("   sudo steamos-readonly disable")
            self.logger.error("")
            self.logger.error("2. Install curl (recommended - most reliable):")
            self.logger.error("   sudo pacman -S curl")
            self.logger.error("")
            self.logger.error("3. (Optional) Re-enable read-only mode after installation:")
            self.logger.error("   sudo steamos-readonly enable")
            self.logger.error("")
            self.logger.error("Note: curl is usually pre-installed on SteamOS. If missing,")
            self.logger.error("      the above steps will install it.")
        else:
            self.logger.error("SOLUTION: Install one of the following downloaders:")
            self.logger.error("")
            self.logger.error("  For Debian/Ubuntu/PopOS:")
            self.logger.error("    sudo apt install curl  # or: sudo apt install wget")
            self.logger.error("")
            self.logger.error("  For Fedora/RHEL/CentOS:")
            self.logger.error("    sudo dnf install curl  # or: sudo dnf install wget")
            self.logger.error("")
            self.logger.error("  For Arch/Manjaro:")
            self.logger.error("    sudo pacman -S curl  # or: sudo pacman -S wget")
            self.logger.error("")
            self.logger.error("  For openSUSE:")
            self.logger.error("    sudo zypper install curl  # or: sudo zypper install wget")
            self.logger.error("")
            self.logger.error("Note: Most Linux distributions include curl by default.")
            self.logger.error("      If curl is missing, install it using your package manager.")
        
        self.logger.error("=" * 80)

    def _kill_wineserver_for_prefix(self, env: dict) -> None:
        """Kill wineserver for the current WINEPREFIX so the next wine invocation starts a fresh one (avoids connection reset by peer)."""
        wineserver = env.get('WINESERVER')
        if not wineserver or not os.path.exists(wineserver):
            return
        try:
            subprocess.run(
                [wineserver, '-k'],
                env=env,
                timeout=10,
                capture_output=True,
            )
            self.logger.debug("Killed wineserver for prefix so winetricks can start a fresh one")
        except Exception as e:
            self.logger.debug("Wineserver -k failed (non-fatal): %s", e)

    def _remove_wine_mono(self, wineprefix: str) -> None:
        """Fully remove Wine Mono so a clean winetricks dotnet48 install behaves as on a fresh
        prefix - the state that installs without the "already installed" bail and without
        deferring the .NET first-run to game launch.

        Removes: the mono mscoree.dll stubs, the mono runtime directory, the "Wine Mono"
        uninstaller registry sections, and the mono-registered NET Framework Setup\\NDP keys
        (those are what trigger the #2367 bail). Wineserver must be dead so the system.reg
        edit persists.
        """
        import time
        time.sleep(2)

        for sub in ('system32', 'syswow64'):
            dll = os.path.join(wineprefix, 'drive_c', 'windows', sub, 'mscoree.dll')
            try:
                if os.path.isfile(dll):
                    with open(dll, 'rb') as f:
                        is_mono_stub = b'WINE_MONO_OVERRIDES' in f.read()
                    if is_mono_stub:
                        os.unlink(dll)
                        self.logger.debug("Removed Mono mscoree.dll stub: %s", dll)
            except Exception:
                pass

        mono_dir = os.path.join(wineprefix, 'drive_c', 'windows', 'mono')
        if os.path.isdir(mono_dir):
            shutil.rmtree(mono_dir, ignore_errors=True)
            self.logger.debug("Removed Wine Mono runtime directory")

        system_reg = os.path.join(wineprefix, 'system.reg')
        if not os.path.isfile(system_reg):
            return
        try:
            with open(system_reg, encoding='utf-8', errors='replace') as f:
                lines = f.readlines()
            out, section, drop = [], [], False
            removed_mono, removed_ndp = 0, 0
            for line in lines:
                if line.lstrip().startswith('['):
                    if section and not drop:
                        out.extend(section)
                    end = line.strip().rfind(']')
                    key = line.strip()[1:end].lower() if end > 0 else ''
                    drop = 'net framework setup\\\\ndp' in key
                    if drop:
                        removed_ndp += 1
                    section = [line]
                elif section:
                    section.append(line)
                    s = line.strip()
                    if s.startswith('"DisplayName"=') and 'Wine Mono' in s and not drop:
                        drop = True
                        removed_mono += 1
                else:
                    out.append(line)
            if section and not drop:
                out.extend(section)
            with open(system_reg, 'w', encoding='utf-8') as f:
                f.writelines(out)
            self.logger.info("Removed Wine Mono: %d uninstaller section(s) + %d NDP section(s)", removed_mono, removed_ndp)
        except Exception as exc:
            self.logger.warning("Wine Mono registry removal failed (non-fatal): %s", exc)

    def _cleanup_wine_processes(self):
        """Clean up winetricks processes only during component installation."""
        try:
            subprocess.run("pkill -f winetricks", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.logger.debug("Cleaned up winetricks processes only")
        except Exception as e:
            self.logger.error(f"Error cleaning up winetricks processes: {e}")