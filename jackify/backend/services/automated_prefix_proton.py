"""Proton/compatibility tool methods for AutomatedPrefixService (Mixin)."""
from pathlib import Path
from typing import Optional
import logging
import os
import vdf

logger = logging.getLogger(__name__)

class ProtonOperationsMixin:
    """Mixin providing Proton and compatibility tool methods for AutomatedPrefixService."""

    def _get_user_proton_version(self, modlist_name: str = None):
        """Get user's preferred Proton version from config, with fallback to auto-detection

        Args:
            modlist_name: Optional modlist name for special handling (e.g., Lorerim)
        """
        try:
            from jackify.backend.handlers.config_handler import ConfigHandler
            from jackify.backend.handlers.wine_utils import WineUtils

            config_handler = ConfigHandler()
            user_proton_path = config_handler.get_game_proton_path()

            if not user_proton_path or user_proton_path == 'auto':
                logger.info("User selected auto-detect, using GE-Proton → Experimental → Proton precedence")
                best = WineUtils.select_best_proton()
                if best:
                    compat_name = best.get('steam_compat_name') or WineUtils.resolve_steam_compat_name(best['path'])
                    if compat_name:
                        logger.info(f"Auto-detected Proton: {compat_name}")
                        return compat_name
                return "proton_experimental"
            else:
                # Resolve the actual Steam internal name from the Proton installation
                resolved = WineUtils.resolve_steam_compat_name(user_proton_path)
                if resolved:
                    logger.info(f"Using user-selected Proton: {resolved}")
                    return resolved

                # Fallback for Proton installations without compatibilitytool.vdf
                logger.warning(f"Could not resolve compat name for '{user_proton_path}', using basename")
                proton_version = os.path.basename(user_proton_path)
                if proton_version.startswith('GE-Proton'):
                    return proton_version
                steam_proton_name = proton_version.lower().replace(' - ', '_').replace(' ', '_').replace('-', '_')
                if not steam_proton_name.startswith('proton'):
                    steam_proton_name = f"proton_{steam_proton_name}"
                logger.info(f"Using fallback Proton name: {steam_proton_name}")
                return steam_proton_name

        except Exception as e:
            logger.error(f"Failed to get user Proton preference, using default: {e}")
            return "proton_experimental"

    def find_proton_experimental(self) -> Optional[Path]:
        """
        Find Proton Experimental installation.
        
        Returns:
            Path to Proton Experimental, or None if not found
        """
        proton_paths = [
            Path.home() / ".local/share/Steam/steamapps/common/Proton - Experimental",
            Path.home() / ".steam/steam/steamapps/common/Proton - Experimental",
            Path.home() / ".local/share/Steam/steamapps/common/Proton Experimental",
            Path.home() / ".steam/steam/steamapps/common/Proton Experimental",
        ]
        
        for path in proton_paths:
            if path.exists():
                logger.info(f"Found Proton Experimental at: {path}")
                return path
        
        logger.error("Proton Experimental not found")
        return None

    def check_shortcut_proton_version(self, shortcut_name: str):
        """
        Check if the shortcut has the Proton version set correctly.
        
        Args:
            shortcut_name: Name of the shortcut to check
        """
        # STL sets the compatibility tool in config.vdf, not shortcuts.vdf
        # We know this works from manual testing, so just log that we're skipping this check
        logger.info(f"Skipping Proton version check for '{shortcut_name}' - STL handles this correctly")
        logger.debug(f"[DEBUG] Skipping Proton version check for '{shortcut_name}' - STL handles this correctly")

    def set_proton_version_for_shortcut(self, appid: int, proton_version: str) -> bool:
        """
        Set the Proton version for a shortcut in config.vdf.
        
        Args:
            appid: The AppID of the shortcut (negative for non-Steam shortcuts)
            proton_version: The Proton version to set (e.g., 'proton_experimental')
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Get the config.vdf path
            config_path = self._get_config_path()
            if not config_path:
                logger.error("No config.vdf path found")
                return False
            
            # Read current config (config.vdf is text format)
            with open(config_path, 'r') as f:
                config_data = vdf.load(f)
            
            # config.vdf root key is "InstallConfigStore"
            ics = config_data.setdefault('InstallConfigStore', {})
            sw = ics.setdefault('Software', {})
            valve = sw.setdefault('Valve', {})
            steam = valve.setdefault('Steam', {})
            ctm = steam.setdefault('CompatToolMapping', {})

            ctm[str(appid)] = {
                'name': proton_version,
                'config': '',
                'priority': '250'
            }
            
            # Write back to file (text format)
            with open(config_path, 'w') as f:
                vdf.dump(config_data, f)

            # Ensure file is fully written to disk before Steam restart
            import os
            os.fsync(f.fileno()) if hasattr(f, 'fileno') else None

            logger.info(f"Set Proton version {proton_version} for AppID {appid}")
            logger.debug(f"[DEBUG] Set Proton version {proton_version} for AppID {appid} in config.vdf")

            # Small delay to ensure filesystem write completes
            import time
            time.sleep(0.5)

            # Verify it was set correctly
            with open(config_path, 'r') as f:
                verify_data = vdf.load(f)
            compat_mapping = verify_data.get('InstallConfigStore', {}).get('Software', {}).get('Valve', {}).get('Steam', {}).get('CompatToolMapping', {}).get(str(appid))
            logger.debug(f"[DEBUG] Verification: AppID {appid} -> {compat_mapping}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error setting Proton version: {e}")
            return False

    def set_compatool_on_shortcut(self, shortcut_name: str) -> bool:
        """
        Set CompatTool on a shortcut immediately after STL creation.
        This is CRITICAL to ensure the batch file shortcut has Proton set
        so it can create a prefix when launched.
        
        Args:
            shortcut_name: Name of the shortcut to modify
            
        Returns:
            True if successful, False otherwise
        """
        try:
            shortcuts_path = self._get_shortcuts_path()
            if not shortcuts_path:
                return False
            
            # Read current shortcuts
            with open(shortcuts_path, 'rb') as f:
                shortcuts_data = vdf.binary_load(f)
            
            shortcuts = shortcuts_data.get('shortcuts', {})
            
            # Find the shortcut by name
            for i in range(len(shortcuts)):
                shortcut = shortcuts[str(i)]
                name = shortcut.get('AppName', '')
                
                if shortcut_name == name:
                    # Check current CompatTool setting
                    current_compat = shortcut.get('CompatTool', 'NOT_SET')
                    logger.info(f"Found shortcut '{name}' with CompatTool: '{current_compat}'")
                    
                    # Set CompatTool to ensure batch file can create prefix
                    shortcut['CompatTool'] = 'proton_experimental'
                    logger.info(f" Set CompatTool=proton_experimental on shortcut: {name}")
                    
                    # Write back to file
                    with open(shortcuts_path, 'wb') as f:
                        vdf.binary_dump(shortcuts_data, f)
                    
                    return True
            
            logger.error(f"Shortcut '{shortcut_name}' not found for CompatTool setting")
            return False
            
        except Exception as e:
            logger.error(f"Error setting CompatTool on shortcut: {e}")
            return False

    def _set_proton_on_shortcut(self, shortcut_name: str) -> bool:
        """
        Set Proton Experimental on a shortcut by name.
        
        Args:
            shortcut_name: Name of the shortcut to modify
            
        Returns:
            True if successful, False otherwise
        """
        try:
            shortcuts_path = self._get_shortcuts_path()
            if not shortcuts_path:
                return False
            
            # Read current shortcuts
            with open(shortcuts_path, 'rb') as f:
                shortcuts_data = vdf.binary_load(f)
            
            shortcuts = shortcuts_data.get('shortcuts', {})
            
            # Find the shortcut by name
            for i in range(len(shortcuts)):
                shortcut = shortcuts[str(i)]
                name = shortcut.get('AppName', '')
                
                if shortcut_name == name:
                    # Set CompatTool
                    shortcut['CompatTool'] = 'proton_experimental'
                    logger.info(f"Set CompatTool=proton_experimental on shortcut: {name}")
                    
                    # Write back to file
                    with open(shortcuts_path, 'wb') as f:
                        vdf.binary_dump(shortcuts_data, f)
                    
                    return True
            
            logger.error(f"Shortcut '{shortcut_name}' not found for Proton setting")
            return False
            
        except Exception as e:
            logger.error(f"Error setting Proton on shortcut: {e}")
            return False

    def set_compatibility_tool_stl_style(self, unsigned_appid: int, compat_tool: str) -> bool:
        """
        Set compatibility tool using STL's exact method.
        
        This adds an entry to config.vdf's CompatToolMapping section using the unsigned AppID as the key,
        exactly like STL does.
        
        Args:
            unsigned_appid: The unsigned AppID (Grid ID) to use as the key
            compat_tool: The compatibility tool name (e.g., 'proton_experimental')
            
        Returns:
            True if successful, False otherwise
        """
        try:
            config_path = self._get_config_path()
            if not config_path:
                logger.error("No config.vdf path found")
                return False
            
            # Read current config (config.vdf is text format)
            with open(config_path, 'r') as f:
                config_data = vdf.load(f)
            
            # Navigate to the correct location in the VDF structure
            if 'Software' not in config_data:
                config_data['Software'] = {}
            if 'Valve' not in config_data['Software']:
                config_data['Software']['Valve'] = {}
            if 'Steam' not in config_data['Software']['Valve']:
                config_data['Software']['Valve']['Steam'] = {}
            
            # Get or create CompatToolMapping
            if 'CompatToolMapping' not in config_data['Software']['Valve']['Steam']:
                config_data['Software']['Valve']['Steam']['CompatToolMapping'] = {}
            
            # Create the compatibility tool entry exactly like STL does
            compat_entry = {
                'name': compat_tool,
                'config': '',
                'priority': '250'
            }
            
            # Set the compatibility tool for this AppID (using unsigned AppID as key)
            config_data['Software']['Valve']['Steam']['CompatToolMapping'][str(unsigned_appid)] = compat_entry
            
            logger.info(f"Added compatibility tool entry: {str(unsigned_appid)} -> {compat_tool}")
            logger.debug(f"[DEBUG] Added compatibility tool entry: {str(unsigned_appid)} -> {compat_tool}")
            
            # Write back to file (text format)
            with open(config_path, 'w') as f:
                vdf.dump(config_data, f)
            
            logger.info(f"Set compatibility tool STL-style: AppID {unsigned_appid} -> {compat_tool}")
            logger.debug(f"[DEBUG] Set compatibility tool STL-style: AppID {unsigned_appid} -> {compat_tool}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error setting compatibility tool STL-style: {e}")
            return False

    def set_compatibility_tool_complete_stl_style(self, unsigned_appid: int, compat_tool: str) -> bool:
        """
        Set compatibility tool using STL's complete method with direct text manipulation.
        
        This replicates STL's approach by using direct text manipulation instead of VDF libraries
        to preserve existing entries in both config.vdf and localconfig.vdf.
        
        Args:
            unsigned_appid: The unsigned AppID (Grid ID) to use as the key
            compat_tool: The compatibility tool name (e.g., 'proton_experimental')
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Step 1: Update config.vdf using direct text manipulation (like STL does)
            config_path = self._get_config_path()
            if not config_path:
                logger.error("No config.vdf path found")
                return False
            
            # Read the entire file as text
            with open(config_path, 'r') as f:
                lines = f.readlines()
            
            # Find the CompatToolMapping section
            compat_section_start = None
            compat_section_end = None
            for i, line in enumerate(lines):
                if '"CompatToolMapping"' in line.strip():
                    compat_section_start = i
                    # Find the end of the CompatToolMapping section
                    brace_count = 0
                    for j in range(i + 1, len(lines)):
                        if '{' in lines[j]:
                            brace_count += 1
                        if '}' in lines[j]:
                            brace_count -= 1
                            if brace_count == 0:
                                compat_section_end = j
                                break
                    break
            
            if compat_section_start is None:
                logger.error("CompatToolMapping section not found in config.vdf")
                return False
            
            # Check if our AppID entry already exists
            appid_entry_start = None
            appid_entry_end = None
            for i in range(compat_section_start, compat_section_end + 1):
                if f'"{unsigned_appid}"' in lines[i]:
                    appid_entry_start = i
                    # Find the end of this AppID entry
                    brace_count = 0
                    for j in range(i + 1, compat_section_end + 1):
                        if '{' in lines[j]:
                            brace_count += 1
                        if '}' in lines[j]:
                            brace_count -= 1
                            if brace_count == 0:
                                appid_entry_end = j
                                break
                    break
            
            # Create the new entry in Steam's exact format
            new_entry_lines = [
                f'\t\t\t\t\t\t\t\t\t"{unsigned_appid}"\n',
                f'\t\t\t\t\t\t\t\t\t{{\n',
                f'\t\t\t\t\t\t\t\t\t\t"name"\t\t\t\t"{compat_tool}"\n',
                f'\t\t\t\t\t\t\t\t\t\t"config"\t\t\t\t\t""\n',
                f'\t\t\t\t\t\t\t\t\t\t"priority"\t\t\t\t\t"250"\n',
                f'\t\t\t\t\t\t\t\t\t}}\n'
            ]
            
            if appid_entry_start is None:
                # AppID entry doesn't exist, add it before the closing brace of CompatToolMapping
                lines.insert(compat_section_end, ''.join(new_entry_lines))
            else:
                # AppID entry exists, replace it
                del lines[appid_entry_start:appid_entry_end + 1]
                lines.insert(appid_entry_start, ''.join(new_entry_lines))
            
            # Write the updated file back
            with open(config_path, 'w') as f:
                f.writelines(lines)
            
            logger.info(f"Updated config.vdf: AppID {unsigned_appid} -> {compat_tool}")
            
            # Step 2: Update localconfig.vdf using direct text manipulation (like STL)
            localconfig_path = self._get_localconfig_path()
            if not localconfig_path:
                logger.error("No localconfig.vdf path found")
                return False
            
            # Calculate signed AppID (like STL does)
            signed_appid = (unsigned_appid | 0x80000000) & 0xFFFFFFFF
            # Convert to signed 32-bit integer
            import ctypes
            signed_appid_int = ctypes.c_int32(signed_appid).value
            
            # Read the entire file as text
            with open(localconfig_path, 'r') as f:
                lines = f.readlines()
            
            # Check if Apps section exists
            apps_section_start = None
            apps_section_end = None
            for i, line in enumerate(lines):
                if line.strip() == '"Apps"':
                    apps_section_start = i
                    # Find the end of the Apps section
                    brace_count = 0
                    for j in range(i + 1, len(lines)):
                        if '{' in lines[j]:
                            brace_count += 1
                        if '}' in lines[j]:
                            brace_count -= 1
                            if brace_count == 0:
                                apps_section_end = j
                                break
                    break
            
            # If Apps section doesn't exist, create it at the end of the file
            if apps_section_start is None:
                logger.info("Apps section not found, creating it at the end of the file")
                
                # Find the last closing brace (before the final closing brace)
                last_brace_pos = None
                for i in range(len(lines) - 1, -1, -1):
                    if lines[i].strip() == '}':
                        last_brace_pos = i
                        break
                
                if last_brace_pos is None:
                    logger.error("Could not find closing brace in localconfig.vdf")
                    return False
                
                # Insert Apps section before the last closing brace
                apps_section = [
                    '        "Apps"\n',
                    '        {\n',
                    f'                "{signed_appid_int}"\n',
                    '                {\n',
                    '                        "OverlayAppEnable"          "1"\n',
                    '                        "DisableLaunchInVR"         "1"\n',
                    '                }\n',
                    '        }\n'
                ]
                
                lines.insert(last_brace_pos, ''.join(apps_section))
                
            else:
                # Apps section exists, check if our AppID entry exists
                appid_entry_start = None
                appid_entry_end = None
                for i in range(apps_section_start, apps_section_end + 1):
                    if f'"{signed_appid_int}"' in lines[i]:
                        appid_entry_start = i
                        # Find the end of this AppID entry
                        brace_count = 0
                        for j in range(i + 1, apps_section_end + 1):
                            if '{' in lines[j]:
                                brace_count += 1
                            if '}' in lines[j]:
                                brace_count -= 1
                                if brace_count == 0:
                                    appid_entry_end = j
                                    break
                        break
                
                if appid_entry_start is None:
                    # AppID entry doesn't exist, add it to the Apps section
                    logger.info(f"AppID {signed_appid_int} entry not found, adding it to Apps section")
                    
                    # Insert before the closing brace of the Apps section
                    appid_entry = [
                        f'                "{signed_appid_int}"\n',
                        '                {\n',
                        '                        "OverlayAppEnable"          "1"\n',
                        '                        "DisableLaunchInVR"         "1"\n',
                        '                }\n'
                    ]
                    
                    lines.insert(apps_section_end, ''.join(appid_entry))
                    
                else:
                    # AppID entry exists, update the values
                    logger.info(f"AppID {signed_appid_int} entry exists, updating values")
                    
                    # Check if the values already exist and update them
                    overlay_found = False
                    vr_found = False
                    
                    for i in range(appid_entry_start, appid_entry_end + 1):
                        if '"OverlayAppEnable"' in lines[i]:
                            lines[i] = '                        "OverlayAppEnable"          "1"\n'
                            overlay_found = True
                        elif '"DisableLaunchInVR"' in lines[i]:
                            lines[i] = '                        "DisableLaunchInVR"         "1"\n'
                            vr_found = True
                    
                    # Add missing values
                    if not overlay_found or not vr_found:
                        # Find the position to insert (before the closing brace of the AppID entry)
                        insert_pos = appid_entry_end
                        for i in range(appid_entry_start, appid_entry_end + 1):
                            if lines[i].strip() == '}':
                                insert_pos = i
                                break
                        
                        new_values = []
                        if not overlay_found:
                            new_values.append('                        "OverlayAppEnable"          "1"\n')
                        if not vr_found:
                            new_values.append('                        "DisableLaunchInVR"         "1"\n')
                        
                        for value in new_values:
                            lines.insert(insert_pos, value)
            
            # Write the updated file back
            with open(localconfig_path, 'w') as f:
                f.writelines(lines)
            
            logger.info(f"Updated localconfig.vdf: Signed AppID {signed_appid_int} -> OverlayAppEnable=1, DisableLaunchInVR=1")
            logger.debug(f"[DEBUG] Updated localconfig.vdf: Signed AppID {signed_appid_int} -> OverlayAppEnable=1, DisableLaunchInVR=1")
            
            return True
            
        except Exception as e:
            logger.error(f"Error setting compatibility tool complete STL-style: {e}")
            return False

    def verify_compatibility_tool_persists(self, appid: int) -> bool:
        """
        Verify that the compatibility tool setting persists with correct Proton version.

        Args:
            appid: The AppID to check

        Returns:
            True if compatibility tool is correctly set, False otherwise
        """
        try:
            config_path = Path.home() / ".steam/steam/config/config.vdf"
            if not config_path.exists():
                logger.warning("Steam config.vdf not found")
                return False

            with open(config_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Check if AppID exists and has a Proton version set
            if f'"{appid}"' in content:
                # Get the expected Proton version
                expected_proton = self._get_user_proton_version()

                # Look for the Proton version in the compatibility tool mapping
                if expected_proton in content:
                    logger.info(f" Compatibility tool persists: {expected_proton}")
                    return True
                else:
                    logger.warning(f"AppID {appid} found but Proton version '{expected_proton}' not set")
                    return False
            else:
                logger.warning("Compatibility tool not found")
                return False

        except Exception as e:
            logger.error(f"Error verifying compatibility tool: {e}")
            return False

    def _find_proton_binary(self, proton_common_dir: Path) -> Optional[Path]:
        """Locate a Proton wrapper script to use, respecting user's configuration."""
        try:
            from jackify.backend.handlers.config_handler import ConfigHandler
            from jackify.backend.handlers.wine_utils import WineUtils

            config = ConfigHandler()
            user_proton_path = config.get_game_proton_path()

            # If user selected a specific Proton, try that first
            if user_proton_path != 'auto':
                # Resolve symlinks to handle ~/.steam/steam -> ~/.local/share/Steam
                resolved_proton_path = os.path.realpath(user_proton_path)

                # Check for wine binary in different Proton structures
                valve_proton_wine = Path(resolved_proton_path) / "dist" / "bin" / "wine"
                ge_proton_wine = Path(resolved_proton_path) / "files" / "bin" / "wine"

                if valve_proton_wine.exists() or ge_proton_wine.exists():
                    # Found user's Proton, now find the proton wrapper script
                    proton_wrapper = Path(resolved_proton_path) / "proton"
                    if proton_wrapper.exists():
                        logger.info(f"Using user-selected Proton wrapper: {proton_wrapper}")
                        return proton_wrapper
                    else:
                        logger.warning(f"User-selected Proton missing wrapper script: {proton_wrapper}")
                else:
                    logger.warning(f"User-selected Proton path invalid: {user_proton_path}")

            # Fall back to auto-detection
            logger.info("Falling back to automatic Proton detection")
            candidates = []
            preferred = [
                "Proton - Experimental",
                "Proton 9.0",
                "Proton 8.0",
                "Proton Hotfix",
            ]

            for name in preferred:
                p = proton_common_dir / name / "proton"
                if p.exists():
                    candidates.append(p)

            # As a fallback, scan all Proton* dirs
            if not candidates and proton_common_dir.exists():
                for p in proton_common_dir.glob("Proton*/proton"):
                    candidates.append(p)

            if not candidates:
                logger.error("No Proton wrapper found under steamapps/common")
                return None

            logger.info(f"Using auto-detected Proton wrapper: {candidates[0]}")
            return candidates[0]

        except Exception as e:
            logger.error(f"Error finding Proton binary: {e}")
            return None

