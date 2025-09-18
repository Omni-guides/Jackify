from pathlib import Path
import json
import logging
from typing import Union, Dict, Optional, List, Tuple
import re
import time
import vdf
import os
import subprocess
import shutil
import requests
import atexit
import signal
import sys

# Import our modules
from .path_handler import PathHandler
# from .wine_utils import WineUtils  # Removed unused import
from .filesystem_handler import FileSystemHandler
from .protontricks_handler import ProtontricksHandler
from .shortcut_handler import ShortcutHandler
from .resolution_handler import ResolutionHandler

# Import our safe VDF handler
from .vdf_handler import VDFHandler

# Import colors from the new central location
from .ui_colors import COLOR_PROMPT, COLOR_RESET, COLOR_INFO, COLOR_SELECTION, COLOR_ERROR

# Standard logging (no file handler)
import logging

# Initialize logger
logger = logging.getLogger(__name__)

# Ensure terminal state is restored on exit, error, or interrupt
def _restore_terminal():
    try:
        # Skip stty in GUI mode to prevent "Inappropriate ioctl for device" error
        if os.environ.get('JACKIFY_GUI_MODE') == '1':
            return
        os.system('stty sane')
    except Exception:
        pass

# Only register signal handlers if we're in the main thread
try:
    import threading
    if threading.current_thread() is threading.main_thread():
        atexit.register(_restore_terminal)
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, lambda signum, frame: (_restore_terminal(), sys.exit(1)))
except Exception:
    # If signal handling fails, just continue without it
    pass

class ModlistHandler:
    """
    Handles operations related to modlist detection and configuration
    """
    
    # Dictionary mapping modlist name patterns (lowercase, spaces optional) 
    # to lists of additional Wine components or special actions.
    MODLIST_SPECIFIC_COMPONENTS = {
        # Pattern: [component1, component2, ... or special_action_string]
        "wildlander": ["dotnet48"], # Example from bash script
        "licentia": ["dotnet8"],   # Example from bash script (needs special handling)
        "nolvus": ["dotnet6", "dotnet7"], # Example
        # Add other modlists and their specific needs here
        # e.g., "fallout4_anotherlife": ["some_component"] 
    }
    
    # Canonical mapping of modlist-specific Wine components (from omni-guides.sh)
    MODLIST_WINE_COMPONENTS = {
        "wildlander": ["dotnet472"],
        "librum": ["dotnet40", "dotnet8"],
        "apostasy": ["dotnet40", "dotnet8"],
        "nordicsouls": ["dotnet40"],
        "livingskyrim": ["dotnet40"],
        "lsiv": ["dotnet40"],
        "ls4": ["dotnet40"],
        "lostlegacy": ["dotnet48"],
    }
    
    def __init__(self, steam_path_or_config: Union[Dict, str, Path, None] = None, 
                 mo2_path: Optional[Union[str, Path]] = None, 
                 steamdeck: bool = False,
                 verbose: bool = False, # Add verbose flag
                 filesystem_handler: Optional['FileSystemHandler'] = None):
        """
        Initialize the ModlistHandler.
        Can be initialized with:
        1. A config dictionary: ModlistHandler(config_dict, steamdeck=True)
        2. Explicit paths: ModlistHandler(steam_path="/path/to/steam", mo2_path="/path/to/mo2", steamdeck=False)
        3. Default (will try to find paths if needed later): ModlistHandler()

        Args:
            steam_path_or_config: Config dict or path to Steam installation.
            mo2_path: Path to ModOrganizer installation (needed if steam_path_or_config is a path).
            steamdeck: Boolean indicating if running on Steam Deck.
            verbose: Boolean indicating if verbose output is desired.
            filesystem_handler: Optional FileSystemHandler instance to use instead of creating a new one.
        """
        # Use standard logging (no file handler)
        self.logger = logging.getLogger(__name__)
        self.logger.propagate = False
        self.steamdeck = steamdeck
        self.steam_path: Optional[Path] = None
        self.verbose = verbose # Store verbose flag
        self.mo2_path: Optional[Path] = None

        if isinstance(steam_path_or_config, dict):
            # Scenario 1: Init with config dict
            self.logger.debug("Initializing ModlistHandler with config dict")
            steam_path_str = steam_path_or_config.get('steam_path')
            self.steam_path = Path(steam_path_str) if steam_path_str else None
            mo2_path_str = steam_path_or_config.get('mo2_path')
            self.mo2_path = Path(mo2_path_str) if mo2_path_str else None
        elif steam_path_or_config:
            # Scenario 2: Init with explicit paths
            self.logger.debug("Initializing ModlistHandler with explicit paths")
            self.steam_path = Path(steam_path_or_config)
            if mo2_path:
                 self.mo2_path = Path(mo2_path)
            else:
                 # Decide if mo2_path is strictly required here
                 self.logger.warning("MO2 path not provided during path-based initialization")
                 # If MO2 path is essential, raise ValueError
                 # raise ValueError("mo2_path is required when providing steam_path directly")
        else:
             # Scenario 3: Default init, paths might be found later if needed
             self.logger.debug("Initializing ModlistHandler with default settings")
             # Paths remain None for now

        self.modlists: Dict[str, Dict] = {}
        self.launch_options = [
            "--no-sandbox",
            "--disable-gpu-sandbox",
            "--disable-software-rasterizer",
            "--disable-dev-shm-usage"
        ]
        # Initialize state reset variables first
        self.modlist = None
        self.appid = None
        self.game_var = None
        self.game_var_full = None
        self.modlist_dir = None
        self.modlist_ini = None
        self.steam_library = None
        self.basegame_sdcard = False
        self.modlist_sdcard = False
        self.compat_data_path = None
        self.proton_ver = None
        self.game_name = None
        self.selected_resolution = None
        self.which_protontricks = None 
        self.steamdeck = steamdeck
        self.stock_game_path = None
        
        # Initialize Handlers (should happen regardless of how paths were provided)
        self.protontricks_handler = ProtontricksHandler(steamdeck=self.steamdeck, logger=self.logger)
        self.shortcut_handler = ShortcutHandler(steamdeck=self.steamdeck, verbose=self.verbose)
        self.filesystem_handler = filesystem_handler if filesystem_handler else FileSystemHandler()
        self.resolution_handler = ResolutionHandler()
        self.path_handler = PathHandler() # Assuming PathHandler is needed

        # Use shared timing for consistency across services
        
        # Load modlists if steam_path is known
        if self.steam_path:
            self._load_modlists()
        else:
            self.logger.debug("Steam path not known during init, skipping initial modlist load.")

        # Use static methods from VDFHandler
        self.vdf_handler = VDFHandler
    
    def _get_progress_timestamp(self):
        """Get consistent progress timestamp"""
        from jackify.shared.timing import get_timestamp
        return get_timestamp()
    
    # --- Original methods continue below --- 
    def _load_modlists(self) -> None:
        """Load modlists from local configuration or detect from Steam shortcuts."""
        try:
            # Try to load from local config first
            if not self.steam_path or not self.steam_path.exists():
                 self.logger.warning("Steam path not valid in __init__, cannot load modlists.json")
                 self._detect_modlists_from_shortcuts() 
                 return
                 
            config_path = self.steam_path.parent / 'modlists.json'
            if config_path.exists():
                with open(config_path, 'r') as f:
                    self.modlists = json.load(f)
                self.logger.info("Loaded modlists from local configuration")
                return
            
            self._detect_modlists_from_shortcuts()
        except Exception as e:
            self.logger.error(f"Error loading modlists: {e}")

    def _detect_modlists_from_shortcuts(self) -> bool:
        """
        Detect modlists from Steam shortcuts.vdf entries
        """
        self.logger.info("Detecting modlists from Steam shortcuts")
        return False # Placeholder return

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
            # 1. Get ALL non-Steam shortcuts from Protontricks
            # Now calls the renamed method without filtering
            protontricks_shortcuts = self.protontricks_handler.list_non_steam_shortcuts()
            if not protontricks_shortcuts:
                self.logger.warning("Protontricks did not list any non-Steam shortcuts.")
                return []
            self.logger.debug(f"Protontricks non-Steam shortcuts found: {protontricks_shortcuts}")

            # 2. Get shortcuts pointing to the executable from shortcuts.vdf
            matching_vdf_shortcuts = self.shortcut_handler.find_shortcuts_by_exe(executable_name)
            if not matching_vdf_shortcuts:
                self.logger.debug(f"No shortcuts found pointing to '{executable_name}' in shortcuts.vdf.")
                return []
            self.logger.debug(f"Shortcuts matching executable '{executable_name}' in VDF: {matching_vdf_shortcuts}")

            # 3. Correlate the two lists and extract required info
            for vdf_shortcut in matching_vdf_shortcuts:
                app_name = vdf_shortcut.get('AppName')
                start_dir = vdf_shortcut.get('StartDir')
                
                if not app_name or not start_dir:
                    self.logger.warning(f"Skipping VDF shortcut due to missing AppName or StartDir: {vdf_shortcut}")
                    continue

                if app_name in protontricks_shortcuts:
                    app_id = protontricks_shortcuts[app_name]
                    
                    # Append dictionary with all necessary info
                    modlist_info = {
                        'name': app_name,
                        'appid': app_id,
                        'path': start_dir
                    }
                    discovered_modlists_info.append(modlist_info)
                    self.logger.info(f"Validated shortcut: '{app_name}' (AppID: {app_id}, Path: {start_dir})")
                else:
                    # Downgraded from WARNING to INFO
                    self.logger.info(f"Shortcut '{app_name}' found in VDF but not listed by protontricks. Skipping.")

        except Exception as e:
            self.logger.error(f"Error discovering executable shortcuts: {e}", exc_info=True)
            return [] 

        if not discovered_modlists_info:
             self.logger.warning("No validated shortcuts found after correlation.")
        
        return discovered_modlists_info 

    def set_modlist(self, modlist_info: Dict) -> bool:
        """Sets the internal context based on the selected modlist dictionary.

        Extracts AppName, AppID, and StartDir from the input dictionary
        and sets internal state variables like self.game_name, self.appid, 
        self.modlist_dir, self.modlist_ini.

        Args:
            modlist_info: Dictionary containing {'name', 'appid', 'path'}.

        Returns:
            True if the context was successfully set, False otherwise.
        """
        self.logger.info(f"Setting context for selected modlist: {modlist_info.get('name')}")
        
        # 1. Extract info from dictionary
        app_name = modlist_info.get('name')
        app_id = modlist_info.get('appid')
        modlist_dir_path_str = modlist_info.get('path')

        if not all([app_name, app_id, modlist_dir_path_str]):
            self.logger.error(f"Incomplete modlist info provided: {modlist_info}")
            return False
            
        self.logger.debug(f"Using AppName: {app_name}, AppID: {app_id}, Path: {modlist_dir_path_str}")
        modlist_dir_path = Path(modlist_dir_path_str)

        # 2. Validate paths and set internal state
        if not modlist_dir_path.is_dir():
            self.logger.error(f"Modlist directory does not exist: {modlist_dir_path}")
            return False
            
        modlist_ini_path = modlist_dir_path / "ModOrganizer.ini"
        if not modlist_ini_path.is_file():
             self.logger.error(f"ModOrganizer.ini not found in directory: {modlist_dir_path}")
             return False

        # Set state variables
        self.game_name = app_name 
        self.appid = str(app_id)  # Ensure AppID is always stored as string
        self.modlist_dir = Path(modlist_dir_path_str) 
        self.modlist_ini = modlist_ini_path 
        
        # Determine if modlist is on SD card
        # Use str() for startswith check
        if str(self.modlist_dir).startswith("/run/media") or str(self.modlist_dir).startswith("/media"):
             self.modlist_sdcard = True
             self.logger.info("Modlist appears to be on an SD card.")
        else:
             self.modlist_sdcard = False

        # Find and set compatdata path now that we have appid
        # Ensure PathHandler is available (should be initialized in __init__)
        if hasattr(self, 'path_handler'):
             # Convert appid to string since find_compat_data expects a string
             appid_str = str(self.appid)
             self.compat_data_path = self.path_handler.find_compat_data(appid_str)
             if self.compat_data_path:
                  self.logger.debug(f"Found compatdata path: {self.compat_data_path}")
             else:
                  self.logger.warning(f"Could not find compatdata path for AppID {self.appid}")
        else:
             self.logger.error("PathHandler not initialized, cannot find compatdata path.")
             self.compat_data_path = None # Ensure it's None if handler missing

        self.logger.info(f"Modlist context set successfully for '{self.game_name}' (AppID: {self.appid})")
        self.logger.debug(f"  Directory: {self.modlist_dir}")
        self.logger.debug(f"  INI Path: {self.modlist_ini}")
        self.logger.debug(f"  On SD Card: {self.modlist_sdcard}")
        
        # Store engine_installed flag for conditional path manipulation
        self.engine_installed = modlist_info.get('engine_installed', False)
        self.logger.debug(f"  Engine Installed: {self.engine_installed}")
        
        # Call internal detection methods to populate more state
        if not self._detect_game_variables():
            self.logger.warning("Failed to auto-detect game type after setting context.")
            # Decide if failure to detect game should make set_modlist return False
            # return False 

        # TODO: Add calls here or later to detect_steam_library, 
        # detect_compatdata_path, detect_proton_version based on the now-known AppID/paths
        # to fully populate the handler's state before configuration phase.

        return True

    def _detect_game_variables(self):
        """Detect game_var and game_var_full based on ModOrganizer.ini content."""
        if not self.modlist_ini or not Path(self.modlist_ini).is_file():
            self.logger.error("Cannot detect game variables: ModOrganizer.ini path not set or file not found.")
            self.game_var = "Unknown"
            self.game_var_full = "Unknown"
            return False

        # Define mapping from loader executable to full game name
        loader_to_game = {
            "skse64_loader.exe": "Skyrim Special Edition",
            "f4se_loader.exe": "Fallout 4",
            "nvse_loader.exe": "Fallout New Vegas",
            "obse_loader.exe": "Oblivion"
            # Add others if needed
        }
        
        # Short name lookup (can derive from full name later)
        short_name_lookup = {
            "Skyrim Special Edition": "Skyrim",
            "Fallout 4": "Fallout",
            "Fallout New Vegas": "FNV", # Or "Fallout"
            "Oblivion": "Oblivion"
        }

        try:
            with open(self.modlist_ini, 'r', encoding='utf-8', errors='ignore') as f:
                ini_content = f.read().lower() # Read entire file, lowercase for easier matching
        except Exception as e:
            self.logger.error(f"Error reading ModOrganizer.ini ({self.modlist_ini}): {e}")
            self.game_var = "Unknown"
            self.game_var_full = "Unknown"
            return False

        found_game = None
        for loader, game_name in loader_to_game.items():
            # Look for the loader name within the INI content
            # A simple check might be enough, or use regex for more specific context 
            # (e.g., in a binary= line)
            if loader in ini_content:
                found_game = game_name
                self.logger.info(f"Detected game type '{found_game}' based on finding '{loader}' in ModOrganizer.ini")
                break
        
        if found_game:
            self.game_var_full = found_game
            self.game_var = short_name_lookup.get(found_game, found_game.split()[0]) # Fallback short name
            return True
        else:
            # Fallback: Could try checking self.game_name keywords as a last resort?
            self.logger.warning(f"Could not detect game type from ModOrganizer.ini content. Check INI for known loaders (skse64, f4se, nvse, obse).")
            # Optionally, ask the user here?
            self.game_var = "Unknown"
            self.game_var_full = "Unknown"
            return False # Indicate detection failed

    def _detect_proton_version(self):
        """Detect the Proton version used for the modlist prefix."""
        self.logger.info(f"Detecting Proton version for AppID {self.appid}...")
        self.proton_ver = "Unknown"

        if not self.appid:
            self.logger.error("Cannot detect Proton version without a valid AppID.")
            return False

        # --- Check config.vdf first for user-selected tool name ---
        try:
            # Reuse PathHandler's method to find config.vdf
            config_vdf_path = self.path_handler.find_steam_config_vdf()
            if config_vdf_path and config_vdf_path.exists():
                import vdf # Assuming vdf library is available
                with open(config_vdf_path, 'r') as f:
                    data = vdf.load(f)
                
                # Navigate the VDF structure (adjust path as needed based on vdf library usage)
                mapping = data.get('InstallConfigStore', {}).get('Software', {}).get('Valve', {}).get('Steam', {}).get('CompatToolMapping', {})
                app_mapping = mapping.get(str(self.appid), {})
                tool_name = app_mapping.get('name', '')

                if tool_name and 'experimental' in tool_name.lower():
                    self.proton_ver = tool_name # Use the name from config.vdf (e.g., proton_experimental)
                    self.logger.info(f"Detected Proton tool from config.vdf: {self.proton_ver}")
                    return True
                elif tool_name: # If found but not experimental, log it but proceed to reg check
                    self.logger.debug(f"Proton tool from config.vdf: {tool_name}. Checking registry for runtime version.")
                else:
                    self.logger.debug(f"No specific Proton tool mapping found for AppID {self.appid} in config.vdf.")
            else:
                 self.logger.debug("config.vdf not found, proceeding with registry check.")

        except ImportError:
             self.logger.warning("Python 'vdf' library not found. Cannot check config.vdf for Proton version. Skipping.")
        except Exception as e:
            self.logger.warning(f"Error reading config.vdf: {e}. Proceeding with registry check.")
        # --- End config.vdf check ---
        
        # --- If config.vdf didn't yield 'Experimental', check prefix files --- 
        if not self.compat_data_path or not self.compat_data_path.exists():
            self.logger.warning(f"Compatdata path '{self.compat_data_path}' not found or invalid for AppID {self.appid}. Cannot detect Proton version via prefix files.")
            # Keep self.proton_ver as "Unknown" if config.vdf also failed
            return False

        # Method 1: Check system.reg (Primary runtime check)
        system_reg_path = self.compat_data_path / "pfx" / "system.reg"
        if system_reg_path.exists():
            try:
                with open(system_reg_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                # Use regex to find the version string
                match = re.search(r'"SteamClientProtonVersion"="([^"]+)"\r?', content)
                if match:
                    version_str = match.group(1).strip()
                    if version_str:
                        # Check if it's a GE version
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

        # Method 2: Check config_info (Fallback runtime check)
        config_info_path = self.compat_data_path / "config_info"
        if config_info_path.exists():
            try:
                with open(config_info_path, 'r') as f:
                    version_str = f.readline().strip()
                if version_str:
                    # Check if it's a GE version
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

        # If neither method worked
        self.logger.warning(f"Could not detect Proton version for AppID {self.appid} from prefix files.")
        # self.proton_ver remains "Unknown" from initialization
        return False

    def display_modlist_summary(self, skip_confirmation: bool = False) -> bool:
        """Display the detected modlist summary and ask for confirmation."""
        if not self.appid or not self.modlist_dir or not self.modlist_ini:
            logger.error("Cannot display summary: Missing essential modlist context.")
            return False

        # Detect potentially missing info if not already set
        if not self.game_name:
             self._detect_game_variables()
        if not self.proton_ver or self.proton_ver == "Unknown":
             self._detect_proton_version()

        # Don't reset timing - continue from Steam Integration timing
        print("=== Configuration Summary ===")
        print(f"{self._get_progress_timestamp()} Selected Modlist: {self.game_name}")
        print(f"{self._get_progress_timestamp()} Game Type: {self.game_var_full if self.game_var_full else 'Unknown'}")
        print(f"{self._get_progress_timestamp()} Steam App ID: {self.appid}")
        print(f"{self._get_progress_timestamp()} Modlist Directory: {self.modlist_dir}")
        print(f"{self._get_progress_timestamp()} ModOrganizer.ini: {self.modlist_dir}/ModOrganizer.ini")
        print(f"{self._get_progress_timestamp()} Proton Version: {self.proton_ver if self.proton_ver else 'Unknown'}")
        print(f"{self._get_progress_timestamp()} Resolution: {self.selected_resolution if self.selected_resolution else 'Default'}")
        print(f"{self._get_progress_timestamp()} Modlist on SD Card: {self.modlist_sdcard}")
        print("")

        if skip_confirmation:
            return True
        # Ask for confirmation
        proceed = input(f"{COLOR_PROMPT}Proceed with configuration? (Y/n): {COLOR_RESET}").lower()
        if proceed == 'n': # Now defaults to Yes unless 'n' is entered
            logger.info("Configuration cancelled by user after summary.")
            return False
        else:
            return True

    def _execute_configuration_steps(self, status_callback=None, manual_steps_completed=False):
        """
        Runs the actual configuration steps for the selected modlist.
        Args:
            status_callback (callable, optional): A function to call with status updates during configuration.
            manual_steps_completed (bool): If True, skip the manual steps prompt (used for new modlist flow).
        """
        # Store status_callback for Configuration Summary
        self._current_status_callback = status_callback
        
        self.logger.info("Executing configuration steps...")
        
        # Ensure required context is set
        if not all([self.modlist_dir, self.appid, self.game_var, self.steamdeck is not None]):
            self.logger.error("Cannot execute configuration steps: Missing required context (modlist_dir, appid, game_var, steamdeck status).")
            print("Error: Missing required information to start configuration.")
            return False
            
        # Step 1: Set protontricks permissions
        if status_callback:
            # Reset timing for Prefix Configuration section
            from jackify.shared.timing import start_new_phase
            start_new_phase()
            
            status_callback("")  # Blank line after Configuration Summary
            status_callback("")  # Extra blank line before Prefix Configuration  
            status_callback("=== Prefix Configuration ===")
            status_callback(f"{self._get_progress_timestamp()} Setting Protontricks permissions")
        self.logger.info("Step 1: Setting Protontricks permissions...")
        if not self.protontricks_handler.set_protontricks_permissions(self.modlist_dir, self.steamdeck):
            self.logger.error("Failed to set Protontricks permissions. Configuration aborted.")
            print("Error: Could not set necessary Protontricks permissions.")
            return False # Abort on failure
        self.logger.info("Step 1: Setting Protontricks permissions... Done")

        # Step 2: Prompt user for manual steps and wait for compatdata
        skip_manual_prompt = False
        if not manual_steps_completed:
            # Check if Proton Experimental is already set and compatdata exists
            proton_ok = False
            compatdata_ok = False
            
            # Check Proton version
            self.logger.debug(f"[MANUAL STEPS DEBUG] Checking Proton version for AppID {self.appid}")
            if self._detect_proton_version():
                self.logger.debug(f"[MANUAL STEPS DEBUG] Detected Proton version: {self.proton_ver}")
                if self.proton_ver and 'experimental' in self.proton_ver.lower():
                    proton_ok = True
                    self.logger.debug("[MANUAL STEPS DEBUG] Proton Experimental detected - proton_ok = True")
            else:
                self.logger.debug("[MANUAL STEPS DEBUG] Could not detect Proton version")
                
            # Check compatdata/prefix
            prefix_path_str = self.path_handler.find_compat_data(str(self.appid))
            self.logger.debug(f"[MANUAL STEPS DEBUG] Compatdata path search result: {prefix_path_str}")

            if prefix_path_str and os.path.isdir(prefix_path_str):
                compatdata_ok = True
                self.logger.debug("[MANUAL STEPS DEBUG] Compatdata directory exists - compatdata_ok = True")
            else:
                self.logger.debug("[MANUAL STEPS DEBUG] Compatdata directory does not exist")
                
            self.logger.debug(f"[MANUAL STEPS DEBUG] proton_ok: {proton_ok}, compatdata_ok: {compatdata_ok}")
            
            if proton_ok and compatdata_ok:
                self.logger.info("Proton Experimental and compatdata already set for this AppID; skipping manual steps prompt.")
                skip_manual_prompt = True
            else:
                self.logger.debug("[MANUAL STEPS DEBUG] Manual steps will be required")
                
        self.logger.debug(f"[MANUAL STEPS DEBUG] manual_steps_completed: {manual_steps_completed}, skip_manual_prompt: {skip_manual_prompt}")
        
        if not manual_steps_completed and not skip_manual_prompt:
            # Check if we're in GUI mode - if so, don't show CLI prompts, just fail and let GUI callbacks handle it
            gui_mode = os.environ.get('JACKIFY_GUI_MODE') == '1'
            
            if gui_mode:
                # In GUI mode: don't show CLI prompts, just fail so GUI can show dialog and retry
                self.logger.info("GUI mode detected: skipping CLI manual steps prompt, will fail configuration to trigger GUI callback")
                if status_callback:
                    status_callback("Manual Steam/Proton setup required - this will be handled by GUI dialog")
                # Return False to trigger manual steps callback in GUI
                return False
            else:
                # CLI mode: show the traditional CLI prompt
                if status_callback:
                    status_callback("Please perform the manual steps in Steam (set Proton, launch shortcut, then close MO2)...")
                self.logger.info("Prompting user to perform manual Steam/Proton steps and launch shortcut.")
                print("\n───────────────────────────────────────────────────────────────────")
                print(f"{COLOR_INFO}Manual Steps Required:{COLOR_RESET} Please follow the on-screen instructions to set Proton Experimental and launch the shortcut from Steam.")
                print("───────────────────────────────────────────────────────────────────")
                input(f"{COLOR_PROMPT}Once you have completed ALL the steps above, press Enter to continue...{COLOR_RESET}")
                self.logger.info("User confirmed completion of manual steps.")
        # Step 3: Download and apply curated user.reg.modlist and system.reg.modlist
        if status_callback:
            status_callback(f"{self._get_progress_timestamp()} Applying curated registry files for modlist configuration")
        self.logger.info("Step 3: Downloading and applying curated user.reg.modlist and system.reg.modlist...")
        try:
            prefix_path_str = self.path_handler.find_compat_data(str(self.appid))
            if not prefix_path_str or not os.path.isdir(prefix_path_str):
                raise Exception("Could not determine Wine prefix path for this modlist. Please ensure you have launched the shortcut from Steam at least once.")
            user_reg_url = "https://raw.githubusercontent.com/Omni-guides/Wabbajack-Modlist-Linux/refs/heads/main/files/user.reg.modlist"
            user_reg_dest = Path(prefix_path_str) / "user.reg"
            response = requests.get(user_reg_url, verify=True)
            response.raise_for_status()
            with open(user_reg_dest, "wb") as f:
                f.write(response.content)
            self.logger.info(f"Curated user.reg.modlist downloaded and applied to {user_reg_dest}")
            system_reg_url = "https://raw.githubusercontent.com/Omni-guides/Wabbajack-Modlist-Linux/refs/heads/main/files/system.reg.modlist"
            system_reg_dest = Path(prefix_path_str) / "system.reg"
            response = requests.get(system_reg_url, verify=True)
            response.raise_for_status()
            with open(system_reg_dest, "wb") as f:
                f.write(response.content)
            self.logger.info(f"Curated system.reg.modlist downloaded and applied to {system_reg_dest}")
        except Exception as e:
            self.logger.error(f"Failed to download or apply curated user.reg.modlist or system.reg.modlist: {e}")
            print(f"{COLOR_ERROR}Error: Failed to download or apply curated user.reg.modlist or system.reg.modlist. {e}{COLOR_RESET}")
            return False
        self.logger.info("Step 3: Curated user.reg.modlist and system.reg.modlist applied successfully.")

        # Step 4: Install Wine Components
        if status_callback:
            status_callback(f"{self._get_progress_timestamp()} Installing Wine components (this may take a while)")
        self.logger.info("Step 4: Installing Wine components (this may take a while)...")
        
        # Use canonical logic for all modlists/games
        components = self.get_modlist_wine_components(self.game_name, self.game_var_full)
        
        # DISABLED: Special game wine component routing - now using registry injection approach
        # special_game_type = self.detect_special_game_type(self.modlist_dir)
        # if special_game_type == "fnv":
        #     target_appid = "22380"  # Vanilla Fallout New Vegas AppID
        # elif special_game_type == "enderal":
        #     target_appid = "976620"  # Enderal: Forgotten Stories Special Edition AppID  
        # else:
        #     target_appid = self.appid  # Normal modlist AppID
        
        # All modlists now use their own AppID for wine components
        target_appid = self.appid
        
        if not self.protontricks_handler.install_wine_components(target_appid, self.game_var_full, specific_components=components):
            self.logger.error("Failed to install Wine components. Configuration aborted.")
            print("Error: Failed to install necessary Wine components.")
            return False # Abort on failure
        self.logger.info("Step 4: Installing Wine components... Done")

        # Step 5: Ensure permissions of Modlist directory
        if status_callback:
            status_callback(f"{self._get_progress_timestamp()} Setting ownership and permissions for modlist directory")
        self.logger.info("Step 5: Setting ownership and permissions for modlist directory...")
        # Convert modlist_dir string to Path object for the method
        modlist_path_obj = Path(self.modlist_dir)
        if not self.filesystem_handler.set_ownership_and_permissions_sudo(modlist_path_obj):
            self.logger.error("Failed to set ownership/permissions for modlist directory. Configuration aborted.")
            print("Error: Failed to set permissions for the modlist directory.")
            return False # Abort on failure
        self.logger.info("Step 5: Setting ownership and permissions... Done")

        # Step 6: Backup ModOrganizer.ini
        if status_callback:
            status_callback(f"{self._get_progress_timestamp()} Backing up ModOrganizer.ini")
        self.logger.info(f"Step 6: Backing up {self.modlist_ini}...")
        modlist_ini_path_obj = Path(self.modlist_ini)
        backup_path = self.filesystem_handler.backup_file(modlist_ini_path_obj)
        if not backup_path:
            self.logger.error("Failed to back up ModOrganizer.ini. Configuration aborted.")
            print("Error: Failed to back up ModOrganizer.ini.")
            return False # Abort on failure
        self.logger.info(f"ModOrganizer.ini backed up to: {backup_path}")
        self.logger.info("Step 6: Backing up ModOrganizer.ini... Done")

        # Step 7a: Detect Stock Game/Game Root path
        if status_callback:
            status_callback(f"{self._get_progress_timestamp()} Detecting stock game path")
        # This method sets self.stock_game_path if found
        if not self._detect_stock_game_path():
            self.logger.error("Failed during stock game path detection.")
            print("Error: Failed during stock game path detection.")
            return False

        # Step 7b: Detect Steam Library Info (Needed for Step 8)
        if status_callback:
            status_callback(f"{self._get_progress_timestamp()} Detecting Steam Library info")
        self.logger.info("Step 7b: Detecting Steam Library info...")
        if not self._detect_steam_library_info():
             self.logger.error("Failed to detect necessary Steam Library information.")
             print("Error: Could not find Steam library information.")
             return False
        self.logger.info("Step 7b: Detecting Steam Library info... Done")

        # Step 8: Update ModOrganizer.ini Paths (gamePath, Binary, workingDirectory)
        if status_callback:
            status_callback(f"{self._get_progress_timestamp()} Updating ModOrganizer.ini paths")
        self.logger.info("Step 8: Updating gamePath, Binary, and workingDirectory paths in ModOrganizer.ini...")
        
        # Update gamePath using replace_gamepath method
        modlist_dir_path_obj = Path(self.modlist_dir)
        modlist_ini_path_obj = Path(self.modlist_ini)
        stock_game_path_obj = Path(self.stock_game_path) if self.stock_game_path else None
        # Only call replace_gamepath if we have a valid stock game path
        if stock_game_path_obj:
            if not self.path_handler.replace_gamepath(
                modlist_ini_path=modlist_ini_path_obj, 
                new_game_path=stock_game_path_obj,
                modlist_sdcard=self.modlist_sdcard
            ):
                self.logger.error("Failed to update gamePath in ModOrganizer.ini. Configuration aborted.")
                print("Error: Failed to update game path in ModOrganizer.ini.")
                return False  # Abort on failure
        else:
            self.logger.info("No stock game path found, skipping gamePath update - edit_binary_working_paths will handle all path updates.")
            self.logger.info("Using unified path manipulation to avoid duplicate processing.")
        
        # Conditionally update binary and working directory paths 
        # Skip for jackify-engine workflows since paths are already correct
        if not getattr(self, 'engine_installed', False):
            # Convert steamapps/common path to library root path
            steam_libraries = None
            if self.steam_library:
                # self.steam_library is steamapps/common, need to go up 2 levels to get library root
                steam_library_root = Path(self.steam_library).parent.parent
                steam_libraries = [steam_library_root]
                self.logger.debug(f"Using Steam library root: {steam_library_root}")
            
            if not self.path_handler.edit_binary_working_paths(
                modlist_ini_path=modlist_ini_path_obj,
                modlist_dir_path=modlist_dir_path_obj,
                modlist_sdcard=self.modlist_sdcard,
                steam_libraries=steam_libraries
            ):
                self.logger.error("Failed to update binary and working directory paths in ModOrganizer.ini. Configuration aborted.")
                print("Error: Failed to update binary and working directory paths in ModOrganizer.ini.")
                return False  # Abort on failure
        else:
            self.logger.debug("Skipping path manipulation - jackify-engine already set correct paths in ModOrganizer.ini")
        self.logger.info("Step 8: Updating ModOrganizer.ini paths... Done")

        # Step 9: Update Resolution Settings (if applicable)
        if hasattr(self, 'selected_resolution') and self.selected_resolution:
            if status_callback:
                status_callback(f"{self._get_progress_timestamp()} Updating resolution settings")
            # Ensure resolution_handler call uses correct args if needed
            # Assuming it uses modlist_dir (str) and game_var_full (str)
            # Construct vanilla game directory path for fallback
            vanilla_game_dir = None
            if self.steam_library and self.game_var_full:
                vanilla_game_dir = str(Path(self.steam_library) / "steamapps" / "common" / self.game_var_full)
                
            if not self.resolution_handler.update_ini_resolution(
                modlist_dir=self.modlist_dir, 
                game_var=self.game_var_full, 
                set_res=self.selected_resolution,
                vanilla_game_dir=vanilla_game_dir
            ):
                self.logger.warning("Failed to update resolution settings in some INI files.")
                print("Warning: Failed to update resolution settings.")
            self.logger.info("Step 9: Updating resolution in INI files... Done")
        else:
            self.logger.info("Step 9: Skipping resolution update (no resolution selected).")

        # Step 10: Create dxvk.conf (skip for special games using vanilla compatdata)
        special_game_type = self.detect_special_game_type(self.modlist_dir)
        self.logger.debug(f"DXVK step - modlist_dir='{self.modlist_dir}', special_game_type='{special_game_type}'")
        
        # Force check specific files for debugging
        nvse_path = Path(self.modlist_dir) / "nvse_loader.exe" if self.modlist_dir else None
        enderal_path = Path(self.modlist_dir) / "Enderal Launcher.exe" if self.modlist_dir else None
        self.logger.debug(f"nvse_loader.exe exists: {nvse_path.exists() if nvse_path else 'N/A'}")
        self.logger.debug(f"Enderal Launcher.exe exists: {enderal_path.exists() if enderal_path else 'N/A'}")
        
        if special_game_type:
            self.logger.info(f"Step 10: Skipping dxvk.conf creation for {special_game_type.upper()} (uses vanilla compatdata)")
            if status_callback:
                status_callback(f"{self._get_progress_timestamp()} Skipping dxvk.conf for {special_game_type.upper()} modlist")
        else:
            if status_callback:
                status_callback(f"{self._get_progress_timestamp()} Creating dxvk.conf file")
            self.logger.info("Step 10: Creating dxvk.conf file...")
            # Assuming create_dxvk_conf still uses string paths
            # Construct vanilla game directory path for fallback
            vanilla_game_dir = None
            if self.steam_library and self.game_var_full:
                vanilla_game_dir = str(Path(self.steam_library) / "steamapps" / "common" / self.game_var_full)
                
            if not self.path_handler.create_dxvk_conf(
                modlist_dir=self.modlist_dir, 
                modlist_sdcard=self.modlist_sdcard, 
                steam_library=str(self.steam_library) if self.steam_library else None, # Pass as string or None 
                basegame_sdcard=self.basegame_sdcard, 
                game_var_full=self.game_var_full,
                vanilla_game_dir=vanilla_game_dir
            ):
                self.logger.warning("Failed to create dxvk.conf file.")
                print("Warning: Failed to create dxvk.conf file.")
            self.logger.info("Step 10: Creating dxvk.conf... Done")

        # Step 11a: Small Tasks - Delete Plugin
        if status_callback:
            status_callback(f"{self._get_progress_timestamp()} Deleting incompatible MO2 plugin")
        self.logger.info("Step 11a: Deleting incompatible MO2 plugin (FixGameRegKey.py)...")
        plugin_path = Path(self.modlist_dir) / "plugins" / "FixGameRegKey.py"
        if plugin_path.exists():
            try:
                plugin_path.unlink()
                self.logger.info("FixGameRegKey.py plugin deleted successfully.")
            except Exception as e:
                self.logger.warning(f"Failed to delete FixGameRegKey.py plugin: {e}")
                print("Warning: Failed to delete incompatible plugin file.")
        else:
            self.logger.debug("FixGameRegKey.py plugin not found (this is normal).")
        self.logger.info("Step 11a: Plugin deletion check complete.")

        # Step 11b: Download Font
        if status_callback:
            status_callback(f"{self._get_progress_timestamp()} Downloading required font")
        prefix_path_str = self.path_handler.find_compat_data(str(self.appid))
        if prefix_path_str:
            prefix_path = Path(prefix_path_str)
            fonts_dir = prefix_path / "drive_c" / "windows" / "Fonts"
            font_url = "https://github.com/mrbvrz/segoe-ui-linux/raw/refs/heads/master/font/seguisym.ttf"
            font_dest_path = fonts_dir / "seguisym.ttf"
            
            # Pass quiet=True to suppress print during configuration steps
            if not self.filesystem_handler.download_file(font_url, font_dest_path, quiet=True):
                self.logger.warning(f"Failed to download {font_url} to {font_dest_path}")
                print("Warning: Failed to download necessary font file (seguisym.ttf).")
                # Continue anyway, not critical for all lists
            else:
                self.logger.info("Font downloaded successfully.")
        else:
            self.logger.error("Could not get WINEPREFIX path, skipping font download.")
            print("Warning: Could not determine Wine prefix path, skipping font download.")

        # Step 12: Modlist-specific steps
        if status_callback:
            status_callback(f"{self._get_progress_timestamp()} Checking for modlist-specific steps")
            status_callback("")  # Blank line after final Prefix Configuration step
        self.logger.info("Step 12: Checking for modlist-specific steps...")
        # ... (rest of the inline logic for step 12) ...

        # Step 13: Launch options for special games are now set during automated prefix workflow (before Steam restart)
        # This ensures proper timing and avoids the need for a second Steam restart
        special_game_type = self.detect_special_game_type(self.modlist_dir)
        if special_game_type:
            self.logger.info(f"Step 13: Launch options for {special_game_type.upper()} were set during automated workflow")
        else:
            self.logger.debug("Step 13: No special launch options needed for this modlist type")

        # Do not call status_callback here, the final message is handled in menu_handler
        # if status_callback:
        #     status_callback("Configuration completed successfully!")
            
        self.logger.info("Configuration steps completed successfully.")
        return True # Return True on success

    def _detect_steam_library_info(self) -> bool:
        """Detects Steam Library path and whether it's on an SD card."""
        self.logger.debug("Detecting Steam Library path...")
        steam_lib_path_str = PathHandler.find_steam_library()
        
        if not steam_lib_path_str:
            self.logger.error("PathHandler.find_steam_library() failed to find a Steam library.")
            self.steam_library = None
            self.basegame_sdcard = False # Assume not on SD if path not found
            return False # Indicate failure
            
        self.steam_library = steam_lib_path_str
        self.logger.info(f"Detected Steam Library: {self.steam_library}")
        
        # Check if the base game library is on SD card
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
            "Game Root",
            "STOCK GAME",
            "Stock Game Folder",
            "Stock Folder",
            "Skyrim Stock",
            Path("root/Skyrim Special Edition") # Special case for some lists
            # Add other common names if needed
        ]

        found_path = None
        for name in common_names:
            potential_path = modlist_path / name
            if potential_path.is_dir():
                found_path = str(potential_path)
                self.logger.info(f"Found potential stock game directory: {found_path}")
                break # Found the first match
        
        if found_path:
            self.stock_game_path = found_path
            # Suppress print during configuration
            # print(f"Step 7a: Found stock game directory: {os.path.basename(found_path)}") 
            return True
        else:
            self.stock_game_path = None
            self.logger.info("No common Stock Game/Game Root directory found. Will assume vanilla game path is needed for some operations.")
            # Do not print this warning to the user
            # print("Step 7a: No common Stock Game/Game Root directory found.") 
            # Still return True, as the check completed. Lack of this dir isn't always an error.
            return True 

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

        # Add a short delay to allow Steam to potentially finish writing changes
        self.logger.debug("Waiting 2 seconds before reading config.vdf...")
        time.sleep(2)

        try:
            self.logger.debug(f"Attempting to load VDF file: {config_vdf_path}")
            # CORRECTION: Use the vdf library directly here, not VDFHandler
            with open(str(config_vdf_path), 'r') as f:
                 config_data = vdf.load(f, mapper=vdf.VDFDict)

            # --- Write full config.vdf to a debug file ---
            import json
            debug_dump_path = os.path.expanduser("~/dev/Jackify/configvdf_dump.txt")
            with open(debug_dump_path, "w") as dump_f:
                json.dump(config_data, dump_f, indent=2)
            self.logger.info(f"Full config.vdf dumped to {debug_dump_path}")

            # --- Log only the relevant section for this AppID ---
            steam_config_section = config_data.get('InstallConfigStore', {}).get('Software', {}).get('Valve', {}).get('Steam', {})
            compat_mapping = steam_config_section.get('CompatToolMapping', {})
            app_mapping = compat_mapping.get(appid_to_check, {})
            self.logger.debug("───────────────────────────────────────────────────────────────────")
            self.logger.debug(f"Config.vdf entry for AppID {appid_to_check} (CompatToolMapping):")
            self.logger.debug(json.dumps({appid_to_check: app_mapping}, indent=2))
            self.logger.debug("───────────────────────────────────────────────────────────────────")
            self.logger.debug(f"Steam config section from VDF: {json.dumps(steam_config_section, indent=2)}")
            # --- End Debugging ---
            
            # Navigate the structure: Software -> Valve -> Steam -> CompatToolMapping -> appid_to_check -> Name
            compat_mapping = steam_config_section.get('CompatToolMapping', {})
            app_mapping = compat_mapping.get(appid_to_check, {})
            proton_tool_name = app_mapping.get('name') # CORRECTED: Use lowercase 'name'
            self.proton_ver = proton_tool_name # Store detected version
            
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
             # This means we found compatdata but not pfx inside any of them
             self.logger.error(f"Wine prefix directory (pfx) not found within any located compatdata directory for AppID {appid_to_check}.")
             return False, 'prefix_missing'

        # All checks passed
        self.logger.info(f"Proton setup verification successful for AppID {appid_to_check}.")
        return True, 'ok'

    def run_modlist_configuration_phase(self, context: dict = None) -> bool:
        """
        Main entry point to run the full modlist configuration sequence.
        This orchestrates all the individual steps.
        """
        self.logger.info(f"Starting configuration phase for modlist: {self.game_name}")
        # Call the private method that contains the actual steps
        # Pass along the status_callback if it was provided in the context
        status_callback = context.get('status_callback') if context else None
        return self._execute_configuration_steps(status_callback=status_callback)

    def set_steam_grid_images(self, appid: str, modlist_dir: str):
        """
        Copies hero, logo, and poster images from the modlist's SteamIcons directory
        to the grid directory of all non-zero Steam user directories, named after the new AppID.
        """
        steam_icons_dir = Path(modlist_dir) / "SteamIcons"
        if not steam_icons_dir.is_dir():
            self.logger.info(f"No SteamIcons directory found at {steam_icons_dir}, skipping grid image copy.")
            return

        # Find all non-zero Steam user directories
        userdata_base = Path.home() / ".steam/steam/userdata"
        if not userdata_base.is_dir():
            self.logger.error(f"Steam userdata directory not found at {userdata_base}")
            return

        for user_dir in userdata_base.iterdir():
            if not user_dir.is_dir() or user_dir.name == "0":
                continue
            grid_dir = user_dir / "config/grid"
            grid_dir.mkdir(parents=True, exist_ok=True)

            images = [
                ("grid-hero.png", f"{appid}_hero.png"),
                ("grid-logo.png", f"{appid}_logo.png"),
                ("grid-tall.png", f"{appid}.png"),
                ("grid-tall.png", f"{appid}p.png"),
            ]

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
                    self.logger.warning(f"Image {src_path} not found; skipping.")

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
        if "skyrim" in game or "fallout4" in game or "starfield" in game or "oblivion_remastered" in game:
            extras += ["d3dcompiler_47", "d3dx11_43", "d3dcompiler_43", "dotnet6", "dotnet7"]
        elif "falloutnewvegas" in game or "fnv" in game or "oblivion" in game:
            extras += ["d3dx9_43", "d3dx9"]
        # Add modlist-specific extras
        modlist_lower = modlist_name.lower().replace(" ", "") if modlist_name else ""
        for key, components in self.MODLIST_WINE_COMPONENTS.items():
            if key in modlist_lower:
                extras += components
        # Remove duplicates while preserving order
        seen = set()
        full_list = [x for x in default_components + extras if not (x in seen or seen.add(x))]
        return full_list

    def _is_steam_deck(self):
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

    def _prompt_or_set_resolution(self):
        # If on Steam Deck, set 1280x800 automatically
        if self._is_steam_deck():
            self.selected_resolution = "1280x800"
            self.logger.info("Steam Deck detected: setting resolution to 1280x800.")
        else:
            print("Do you wish to set the display resolution? (This can be changed manually later)")
            response = input("Set resolution? (y/N): ").strip().lower()
            if response == 'y':
                while True:
                    user_res = input("Enter resolution (e.g., 1920x1080): ").strip()
                    if re.match(r'^[0-9]+x[0-9]+$', user_res):
                        self.selected_resolution = user_res
                        self.logger.info(f"User selected resolution: {user_res}")
                        break
                    else:
                        print("Invalid format. Please use format: 1920x1080")
            else:
                self.selected_resolution = None
                self.logger.info("Resolution setup skipped by user.")

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

        # Check ModOrganizer.ini for indicators (nvse/enderal) as an early, robust signal
        try:
            mo2_ini = modlist_path / "ModOrganizer.ini"
            if mo2_ini.exists():
                try:
                    content = mo2_ini.read_text(errors='ignore').lower()
                    if 'nvse' in content or 'nvse_loader' in content or 'fallout new vegas' in content or 'falloutnv' in content:
                        self.logger.info("Detected FNV via ModOrganizer.ini markers")
                        return "fnv"
                    # Look for Enderal-specific patterns, not just the word "enderal"
                    if any(pattern in content for pattern in ['enderal launcher', 'enderal.exe', 'enderal launcher.exe', 'enderalsteam']):
                        self.logger.info("Detected Enderal via ModOrganizer.ini markers")
                        return "enderal"
                except Exception as e:
                    self.logger.debug(f"Failed reading ModOrganizer.ini for detection: {e}")
        except Exception:
            pass

        # Check for FNV (Fallout New Vegas) and Enderal launchers in common locations
        candidates = [modlist_path]
        try:
            # Include common stock game subfolders if present
            from .path_handler import STOCK_GAME_FOLDERS
            for folder_name in STOCK_GAME_FOLDERS:
                sub = modlist_path / folder_name
                if sub.exists() and sub.is_dir():
                    candidates.append(sub)
        except Exception:
            # If import fails, continue with root-only
            pass

        for base in candidates:
            nvse_loader = base / "nvse_loader.exe"
            if nvse_loader.exists():
                self.logger.info(f"Detected FNV modlist: found nvse_loader.exe in '{base}'")
                return "fnv"
            enderal_launcher = base / "Enderal Launcher.exe"
            if enderal_launcher.exists():
                self.logger.info(f"Detected Enderal modlist: found Enderal Launcher.exe in '{base}'")
                return "enderal"

        # As a final heuristic, use known game type if available in handler state
        try:
            game_type = getattr(self, 'game_var', None)
            if isinstance(game_type, str):
                gt = game_type.strip().lower()
                if 'fallout new vegas' in gt or gt == 'fnv':
                    self.logger.info("Heuristic detection: game_var indicates FNV")
                    return "fnv"
                if 'enderal' in gt:
                    self.logger.info("Heuristic detection: game_var indicates Enderal")
                    return "enderal"
        except Exception:
            pass
            
        # Not a special game type
        self.logger.debug("No special game type detected - standard workflow will be used")
        return None

# (Ensure EOF is clean and no extra incorrect methods exist below) 