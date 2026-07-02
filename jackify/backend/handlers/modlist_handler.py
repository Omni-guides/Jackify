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
from .filesystem_handler import FileSystemHandler
from .protontricks_handler import ProtontricksHandler
from .shortcut_handler import ShortcutHandler
from .resolution_handler import ResolutionHandler

# Import our safe VDF handler
from .vdf_handler import VDFHandler
from .modlist_detection import ModlistDetectionMixin
from .modlist_configuration import ModlistConfigurationMixin
from .modlist_wine_ops import ModlistWineOpsMixin

# Import colors from the new central location
from jackify.shared.colors import COLOR_PROMPT, COLOR_RESET, COLOR_INFO, COLOR_SELECTION, COLOR_ERROR

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

class ModlistHandler(ModlistDetectionMixin, ModlistConfigurationMixin, ModlistWineOpsMixin):
    """
    Handles operations related to modlist detection and configuration
    """
    
    MODLIST_SPECIFIC_COMPONENTS: dict = {}

    MODLIST_WINE_COMPONENTS: dict = {}
    
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
        # Use standard logging (propagate to root logger so messages appear in logs)
        self.logger = logging.getLogger(__name__)
        self.logger.propagate = True
        self.steamdeck = steamdeck

        # DEBUG: Log ModlistHandler instantiation details for SD card path debugging
        import traceback
        caller_info = traceback.extract_stack()[-2]  # Get caller info
        self.logger.debug(f"[SD_CARD_DEBUG] ModlistHandler created: id={id(self)}, steamdeck={steamdeck}")
        self.logger.debug(f"[SD_CARD_DEBUG] Created from: {caller_info.filename}:{caller_info.lineno} in {caller_info.name}()")
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
        self.protontricks_handler = ProtontricksHandler(self.steamdeck, logger=self.logger)
        # Initialize winetricks handler for wine component installation
        from .winetricks_handler import WinetricksHandler
        self.winetricks_handler = WinetricksHandler(logger=self.logger)
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
        
        # Determine if modlist is on SD card (Steam Deck only)
        # On non-Steam Deck systems, /media mounts should use Z: drive, not D: drive
        is_on_sdcard_path = str(self.modlist_dir).startswith("/run/media") or str(self.modlist_dir).startswith("/media")

        # Log SD card detection for debugging
        self.logger.debug(f"SD card detection: modlist_dir={self.modlist_dir}, is_sdcard_path={is_on_sdcard_path}, steamdeck={self.steamdeck}")

        if is_on_sdcard_path and self.steamdeck:
             self.modlist_sdcard = True
             self.logger.info("Modlist appears to be on an SD card (Steam Deck).")
             self.logger.debug(f"Set modlist_sdcard=True")
        else:
             self.modlist_sdcard = False
             self.logger.debug(f"Set modlist_sdcard=False (is_on_sdcard_path={is_on_sdcard_path}, steamdeck={self.steamdeck})")
             if is_on_sdcard_path and not self.steamdeck:
                 self.logger.info("Modlist on /media mount detected on non-Steam Deck system - using Z: drive mapping.")

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

        # Store download_dir when known (Install a Modlist flow); Configure New/Existing leave None
        self.download_dir = modlist_info.get('download_dir')
        if self.download_dir:
            self.logger.debug(f"  Download dir (for MO2): {self.download_dir}")


        # Call internal detection methods to populate more state
        if not self._detect_game_variables():
            self.logger.warning("Failed to auto-detect game type after setting context.")
            # Decide if failure to detect game should make set_modlist return False
            # return False 

        return True

 