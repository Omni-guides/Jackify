"""Prefix creation methods for AutomatedPrefixService (Mixin)."""
from pathlib import Path
from typing import Optional
import logging
import os
import time
import subprocess
import re

logger = logging.getLogger(__name__)

class PrefixCreationMixin:
    """Mixin providing prefix creation methods for AutomatedPrefixService."""

    def _get_preferred_steam_root_and_type(self) -> tuple[Optional[Path], Optional[str]]:
        """Resolve the active Steam root/type using the shared v0.5 selector."""
        from jackify.shared.steam_utils import (
            STEAM_PREFERENCE_AUTO,
            resolve_preferred_steam_installation,
        )
        from ..handlers.config_handler import ConfigHandler

        preference = STEAM_PREFERENCE_AUTO
        try:
            preference = ConfigHandler().get("steam_install_preference", STEAM_PREFERENCE_AUTO)
        except Exception:
            logger.debug("Could not read steam_install_preference; falling back to auto", exc_info=True)

        preferred_type, preferred_root = resolve_preferred_steam_installation(preference)
        return preferred_root, preferred_type

    def _get_library_roots_for_steam_root(self, steam_root: Path) -> list[Path]:
        """
        Read library roots for one chosen Steam install only.

        This avoids mixing native and Flatpak libraries in dual-install environments.
        """
        roots: list[Path] = [steam_root]
        vdf_path = steam_root / "config" / "libraryfolders.vdf"
        if not vdf_path.is_file():
            return roots

        try:
            text = vdf_path.read_text(encoding="utf-8", errors="ignore")
            for match in re.finditer(r'"path"\s*"([^"]+)"', text):
                raw_path = match.group(1).replace("\\\\", "\\")
                lib_root = Path(raw_path).expanduser()
                try:
                    resolved = lib_root.resolve()
                except (OSError, RuntimeError):
                    resolved = lib_root
                if resolved not in roots:
                    roots.append(resolved)
        except Exception:
            logger.debug("Failed reading libraryfolders.vdf for %s", steam_root, exc_info=True)
        return roots

    def _get_compatdata_path_for_appid(self, appid: int) -> Optional[Path]:
        """
        Get the compatdata path for a given AppID.
        
        First tries to find existing compatdata, then constructs path from libraryfolders.vdf
        for creating new prefixes.
        
        Args:
            appid: The AppID to get the path for
            
        Returns:
            Path to the compatdata directory, or None if not found
        """
        from ..handlers.path_handler import PathHandler
        
        # First, try to find existing compatdata
        compatdata_path = PathHandler.find_compat_data(str(appid))
        if compatdata_path:
            return compatdata_path
        
        # Prefix doesn't exist yet - derive it from the selected active Steam root,
        # not from a mixed native/Flatpak library list.
        preferred_root, _preferred_type = self._get_preferred_steam_root_and_type()
        if preferred_root:
            compatdata_base = preferred_root / "steamapps" / "compatdata"
            return compatdata_base / str(appid)
        
        # Only fallback if VDF parsing completely fails
        logger.warning("Could not get library paths from libraryfolders.vdf, using fallback locations")
        fallback_bases = [
            Path.home() / ".var/app/com.valvesoftware.Steam/data/Steam/steamapps/compatdata",
            Path.home() / ".var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/compatdata",
            Path.home() / ".steam/steam/steamapps/compatdata",
            Path.home() / ".local/share/Steam/steamapps/compatdata",
        ]
        
        for base_path in fallback_bases:
            if base_path.is_dir():
                return base_path / str(appid)
        
        return None

    def verify_prefix_creation(self, prefix_path: Path) -> bool:
        """
        Verify that the prefix was created successfully.
        
        Args:
            prefix_path: Path to the prefix directory
            
        Returns:
            True if prefix is valid, False otherwise
        """
        try:
            logger.info(f"Verifying prefix: {prefix_path}")
            
            # Check if prefix exists and has proper structure
            if not prefix_path.exists():
                logger.error("Prefix directory does not exist")
                return False
            
            pfx_dir = prefix_path / "pfx"
            if not pfx_dir.exists():
                logger.error("Prefix exists but no pfx subdirectory")
                return False
            
            # Check for key Wine files
            system_reg = pfx_dir / "system.reg"
            user_reg = pfx_dir / "user.reg"
            drive_c = pfx_dir / "drive_c"
            
            if not system_reg.exists():
                logger.error("No system.reg found in prefix")
                return False
            
            if not user_reg.exists():
                logger.error("No user.reg found in prefix")
                return False
            
            if not drive_c.exists():
                logger.error("No drive_c directory found in prefix")
                return False
            
            logger.info("Prefix structure verified successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error verifying prefix: {e}")
            return False

    def wait_for_prefix_completion(self, prefix_id: str, timeout: int = 60) -> bool:
        """
        Wait for system.reg to stop growing (indicates prefix creation is complete).
        
        Args:
            prefix_id: The Steam prefix ID to monitor
            timeout: Maximum seconds to wait
            
        Returns:
            True if prefix creation completed, False if timeout
        """
        try:
            prefix_path = Path.home() / f".local/share/Steam/steamapps/compatdata/{prefix_id}"
            system_reg = prefix_path / "pfx/system.reg"
            
            logger.info(f"Monitoring prefix completion: {system_reg}")
            
            last_size = 0
            stable_count = 0
            
            for i in range(timeout):
                if system_reg.exists():
                    current_size = system_reg.stat().st_size
                    logger.debug(f"system.reg size: {current_size} bytes")
                    
                    if current_size == last_size:
                        stable_count += 1
                        if stable_count >= 3:  # Stable for 3 seconds
                            logger.info(" system.reg size stable - prefix creation complete")
                            return True
                    else:
                        stable_count = 0
                        last_size = current_size
                
                time.sleep(1)
            
            logger.warning(f"Timeout waiting for prefix completion after {timeout} seconds")
            return False
            
        except Exception as e:
            logger.error(f"Error monitoring prefix completion: {e}")
            return False

    def create_prefix_with_proton_wrapper(self, appid: int) -> bool:
        """
        Create a Proton prefix directly using Proton's wrapper and STEAM_COMPAT_DATA_PATH.
        
        Args:
            appid: The AppID to create the prefix for
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Determine Steam locations from the selected active Steam install only.
            steam_root, steam_type = self._get_preferred_steam_root_and_type()
            if not steam_root:
                logger.error("Could not determine active Steam root for prefix creation")
                return False

            if not steam_root.is_dir():
                logger.error("Preferred Steam root does not exist: %s", steam_root)
                return False

            compatdata_dir = steam_root / "steamapps" / "compatdata"
            proton_common_dir = steam_root / "steamapps" / "common"
            logger.info(
                "Prefix creation using preferred Steam install: type=%s root=%s",
                steam_type or "unknown",
                steam_root,
            )

            # Ensure compatdata root exists and is a directory we actually want to use
            if not compatdata_dir.is_dir():
                logger.error(f"Compatdata root does not exist: {compatdata_dir}. Aborting prefix creation.")
                return False
            
            # Find a Proton wrapper to use
            proton_path = self._find_proton_binary(proton_common_dir)
            if not proton_path:
                logger.error("No Proton wrapper found")
                return False
            
            # Set up environment variables
            env = os.environ.copy()
            env['STEAM_COMPAT_CLIENT_INSTALL_PATH'] = str(steam_root)
            env['STEAM_COMPAT_DATA_PATH'] = str(compatdata_dir / str(abs(appid)))
            # Suppress GUI windows using jackify-engine's proven approach
            env['DISPLAY'] = ''
            env['WAYLAND_DISPLAY'] = ''
            env['WINEDEBUG'] = '-all'
            env['WINEDLLOVERRIDES'] = 'msdia80.dll=n;conhost.exe=d;cmd.exe=d'
            
            # Create the compatdata directory for this AppID (but never the whole tree)
            compat_dir = compatdata_dir / str(abs(appid))
            compat_dir.mkdir(exist_ok=True)
            
            logger.info(f"Creating Proton prefix for AppID {appid}")
            logger.info(f"STEAM_COMPAT_CLIENT_INSTALL_PATH={env['STEAM_COMPAT_CLIENT_INSTALL_PATH']}")
            logger.info(f"STEAM_COMPAT_DATA_PATH={env['STEAM_COMPAT_DATA_PATH']}")
            
            # Run proton run wineboot -u to initialize the prefix
            cmd = [str(proton_path), 'run', 'wineboot', '-u']
            logger.info(f"Running: {' '.join(cmd)}")

            # Adjust timeout for SD card installations on Steam Deck (slower I/O)
            from ..services.platform_detection_service import PlatformDetectionService
            platform_service = PlatformDetectionService.get_instance()
            is_steamdeck_sdcard = (platform_service.is_steamdeck and
                                 str(proton_path).startswith('/run/media/'))
            timeout = 180 if is_steamdeck_sdcard else 60
            if is_steamdeck_sdcard:
                logger.info(f"Using extended timeout ({timeout}s) for Steam Deck SD card Proton installation")

            # Use jackify-engine's approach: UseShellExecute=false, CreateNoWindow=true equivalent
            result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout,
                                  shell=False, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            logger.info(f"Proton exit code: {result.returncode}")
            
            if result.stdout:
                logger.info(f"stdout: {result.stdout.strip()[:500]}")
            if result.stderr:
                logger.info(f"stderr: {result.stderr.strip()[:500]}")
            
            # Give a moment for files to land
            time.sleep(3)
            
            # Check if prefix was created
            pfx = compat_dir / 'pfx'
            if pfx.exists():
                logger.info(f" Proton prefix created at: {pfx}")
                return True
            else:
                logger.warning(f"Proton prefix not found at: {pfx}")
                return False
                
        except subprocess.TimeoutExpired:
            logger.warning(
                f"Proton wineboot did not finish within {timeout}s; a cold Proton build can "
                "still be doing one-time setup in the background. Polling for the prefix "
                "to appear before giving up."
            )
            pfx = compat_dir / 'pfx'
            poll_deadline = time.monotonic() + timeout
            while time.monotonic() < poll_deadline:
                if pfx.exists():
                    logger.info(f"Proton prefix appeared during extended wait at: {pfx}")
                    return True
                time.sleep(5)
            logger.warning(f"Proton prefix still not found at: {pfx} after extended wait")
            return False
        except Exception as e:
            logger.error(f"Error creating prefix: {e}")
            return False
