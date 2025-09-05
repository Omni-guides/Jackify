import logging
import os
import subprocess
import zipfile
import tarfile
from pathlib import Path
import yaml # Assuming PyYAML is installed
from typing import Dict, Optional, List
import requests

# Import necessary handlers from the current Jackify structure
from .path_handler import PathHandler
from .vdf_handler import VDFHandler # Keeping just in case
from .filesystem_handler import FileSystemHandler
from .config_handler import ConfigHandler
# Import color constants needed for print statements in this module
from .ui_colors import COLOR_ERROR, COLOR_SUCCESS, COLOR_WARNING, COLOR_RESET, COLOR_INFO, COLOR_PROMPT, COLOR_SELECTION
# Standard logging (no file handler) - LoggingHandler import removed
from .status_utils import show_status, clear_status
from .subprocess_utils import get_clean_subprocess_env

logger = logging.getLogger(__name__)

# Define default Hoolamike AppIDs for relevant games
TARGET_GAME_APPIDS = {
    'Fallout 3': '22370', # GOTY Edition
    'Fallout New Vegas': '22380', # Base game
    'Skyrim Special Edition': '489830',
    'Oblivion': '22330', # GOTY Edition
    'Fallout 4': '377160'
}

# Define the expected name of the native Hoolamike executable
HOOLAMIKE_EXECUTABLE_NAME = "hoolamike" # Assuming this is the binary name
# Keep consistent with logs directory - use ~/Jackify/ for user-visible managed components
JACKIFY_BASE_DIR = Path.home() / "Jackify"
# Use Jackify base directory for ALL Hoolamike-related files to centralize management
DEFAULT_HOOLAMIKE_APP_INSTALL_DIR = JACKIFY_BASE_DIR / "Hoolamike"
HOOLAMIKE_CONFIG_DIR = DEFAULT_HOOLAMIKE_APP_INSTALL_DIR
HOOLAMIKE_CONFIG_FILENAME = "hoolamike.yaml"
# Default dirs for other components
DEFAULT_HOOLAMIKE_DOWNLOADS_DIR = JACKIFY_BASE_DIR / "Mod_Downloads"
DEFAULT_MODLIST_INSTALL_BASE_DIR = Path.home() / "ModdedGames"

class HoolamikeHandler:
    """Handles discovery, configuration, and execution of Hoolamike tasks.
    Assumes Hoolamike is a native Linux CLI application.
    """

    def __init__(self, steamdeck: bool, verbose: bool, filesystem_handler: FileSystemHandler, config_handler: ConfigHandler, menu_handler=None):
        """Initialize the handler and perform initial discovery."""
        self.steamdeck = steamdeck
        self.verbose = verbose
        self.path_handler = PathHandler()
        self.filesystem_handler = filesystem_handler
        self.config_handler = config_handler
        self.menu_handler = menu_handler
        # Use standard logging (no file handler)
        self.logger = logging.getLogger(__name__)

        # --- Discovered/Managed State --- 
        self.game_install_paths: Dict[str, Path] = {}
        # Allow user override for Hoolamike app install path later
        self.hoolamike_app_install_path: Path = DEFAULT_HOOLAMIKE_APP_INSTALL_DIR
        self.hoolamike_executable_path: Optional[Path] = None # Path to the binary
        self.hoolamike_installed: bool = False
        self.hoolamike_config_path: Path = HOOLAMIKE_CONFIG_DIR / HOOLAMIKE_CONFIG_FILENAME
        self.hoolamike_config: Optional[Dict] = None

        # Load Hoolamike install path from Jackify config if it exists
        saved_path_str = self.config_handler.get('hoolamike_install_path')
        if saved_path_str and Path(saved_path_str).is_dir(): # Basic check if path exists
            self.hoolamike_app_install_path = Path(saved_path_str)
            self.logger.info(f"Loaded Hoolamike install path from Jackify config: {self.hoolamike_app_install_path}")

        self._load_hoolamike_config()
        self._run_discovery()

    def _ensure_hoolamike_dirs_exist(self):
        """Ensure base directories for Hoolamike exist."""
        try:
            HOOLAMIKE_CONFIG_DIR.mkdir(parents=True, exist_ok=True) # Separate Hoolamike config
            self.hoolamike_app_install_path.mkdir(parents=True, exist_ok=True) # Install dir (~/Jackify/Hoolamike)
            # Default downloads dir also needs to exist if we reference it
            DEFAULT_HOOLAMIKE_DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            self.logger.error(f"Error creating Hoolamike directories: {e}", exc_info=True)
            # Decide how to handle this - maybe raise an exception?

    def _check_hoolamike_installation(self):
        """Check if Hoolamike executable exists at the expected location.
        Prioritizes path stored in config if available.
        """
        potential_exe_path = self.hoolamike_app_install_path / HOOLAMIKE_EXECUTABLE_NAME
        check_path = None 
        if potential_exe_path.is_file() and os.access(potential_exe_path, os.X_OK):
            check_path = potential_exe_path
            self.logger.info(f"Found Hoolamike at current path: {check_path}")
        else:
            self.logger.info(f"Hoolamike executable ({HOOLAMIKE_EXECUTABLE_NAME}) not found or not executable at current path {self.hoolamike_app_install_path}.")

        # Update state based on whether we found a valid path
        if check_path:
            self.hoolamike_installed = True
            self.hoolamike_executable_path = check_path
        else:
            self.hoolamike_installed = False
            self.hoolamike_executable_path = None

    def _generate_default_config(self) -> Dict:
        """Generates the default configuration dictionary."""
        self.logger.info("Generating default Hoolamike config structure.")
        # Detection is now handled separately after loading config
        detected_paths = self.path_handler.find_game_install_paths(TARGET_GAME_APPIDS)

        config = {
            "downloaders": {
                "downloads_directory": str(DEFAULT_HOOLAMIKE_DOWNLOADS_DIR),
                "nexus": {"api_key": "YOUR_API_KEY_HERE"}
            },
            "installation": {
                "wabbajack_file_path": "", # Placeholder, set per-run
                "installation_path": "" # Placeholder, set per-run
            },
            "games": { # Only include detected games with consistent formatting (no spaces)
                self._format_game_name(game_name): {"root_directory": str(path)}
                for game_name, path in detected_paths.items()
            },
            "fixup": {
                "game_resolution": "1920x1080"
            },
            "extras": {
                "tale_of_two_wastelands": {
                    "path_to_ttw_mpi_file": "", # Placeholder
                    "variables": {
                        "DESTINATION": "" # Placeholder
                    }
                }
            }
        }
        # Add comment if no games detected
        if not detected_paths:
             # This won't appear in YAML, logic adjusted below
             pass 
        return config

    def _format_game_name(self, game_name: str) -> str:
        """Formats game name for Hoolamike configuration (removes spaces).
        
        Hoolamike expects game names without spaces like: Fallout3, FalloutNewVegas, SkyrimSpecialEdition
        """
        # Handle specific game name formats that Hoolamike expects
        game_name_map = {
            "Fallout 3": "Fallout3",
            "Fallout New Vegas": "FalloutNewVegas",
            "Skyrim Special Edition": "SkyrimSpecialEdition",
            "Fallout 4": "Fallout4",
            "Oblivion": "Oblivion"  # No change needed
        }
        
        # Use predefined mapping if available
        if game_name in game_name_map:
            return game_name_map[game_name]
        
        # Otherwise, just remove spaces as fallback
        return game_name.replace(" ", "")

    def _load_hoolamike_config(self):
        """Load hoolamike.yaml if it exists, or generate a default one."""
        self._ensure_hoolamike_dirs_exist() # Ensure parent dir exists

        if self.hoolamike_config_path.is_file():
            self.logger.info(f"Found existing hoolamike.yaml at {self.hoolamike_config_path}. Loading...")
            try:
                with open(self.hoolamike_config_path, 'r', encoding='utf-8') as f:
                    self.hoolamike_config = yaml.safe_load(f)
                if not isinstance(self.hoolamike_config, dict):
                    self.logger.warning(f"Failed to parse hoolamike.yaml as a dictionary. Generating default.")
                    self.hoolamike_config = self._generate_default_config()
                    self.save_hoolamike_config() # Save the newly generated default
                else:
                    self.logger.info("Successfully loaded hoolamike.yaml configuration.")
                    # Game path merging is handled in _run_discovery now
            except yaml.YAMLError as e:
                self.logger.error(f"Error parsing hoolamike.yaml: {e}. The file may be corrupted.")
                # Don't automatically overwrite - let user decide
                self.hoolamike_config = None
                return False
            except Exception as e:
                self.logger.error(f"Error reading hoolamike.yaml: {e}.", exc_info=True)
                # Don't automatically overwrite - let user decide
                self.hoolamike_config = None
                return False
        else:
            self.logger.info(f"hoolamike.yaml not found at {self.hoolamike_config_path}. Generating default configuration.")
            self.hoolamike_config = self._generate_default_config()
            self.save_hoolamike_config()
        
        return True

    def save_hoolamike_config(self):
         """Saves the current configuration dictionary to hoolamike.yaml."""
         if self.hoolamike_config is None:
             self.logger.error("Cannot save config, internal config dictionary is None.")
             return False
         
         self._ensure_hoolamike_dirs_exist() # Ensure parent dir exists
         self.logger.info(f"Saving configuration to {self.hoolamike_config_path}")
         try:
             with open(self.hoolamike_config_path, 'w', encoding='utf-8') as f:
                # Add comments conditionally
                f.write("# Configuration file created or updated by Jackify\n")
                if not self.hoolamike_config.get("games"):
                    f.write("# No games were detected by Jackify. Add game paths manually if needed.\n")
                # Dump the actual YAML
                yaml.dump(self.hoolamike_config, f, default_flow_style=False, sort_keys=False)
             self.logger.info("Configuration saved successfully.")
             return True
         except Exception as e:
             self.logger.error(f"Error saving hoolamike.yaml: {e}", exc_info=True)
             return False

    def _run_discovery(self):
        """Execute all discovery steps."""
        self.logger.info("Starting Hoolamike feature discovery phase...")

        # Detect game paths and update internal state + config
        self._detect_and_update_game_paths()
        
        self.logger.info("Hoolamike discovery phase complete.")

    def _detect_and_update_game_paths(self):
        """Detect game install paths and update state and config."""
        self.logger.info("Detecting game install paths...")
        # Always run detection
        detected_paths = self.path_handler.find_game_install_paths(TARGET_GAME_APPIDS)
        self.game_install_paths = detected_paths # Update internal state
        self.logger.info(f"Detected game paths: {detected_paths}")

        # Update the loaded config if it exists
        if self.hoolamike_config is not None:
            self.logger.debug("Updating loaded hoolamike.yaml with detected game paths.")
            if "games" not in self.hoolamike_config or not isinstance(self.hoolamike_config.get("games"), dict):
                self.hoolamike_config["games"] = {} # Ensure games section exists
            
            # Define a unified format for game names in config - no spaces
            # Clear existing entries first to avoid duplicates
            self.hoolamike_config["games"] = {}
            
            # Add detected paths with proper formatting - no spaces
            for game_name, detected_path in detected_paths.items():
                formatted_name = self._format_game_name(game_name)
                self.hoolamike_config["games"][formatted_name] = {"root_directory": str(detected_path)}
                
            self.logger.info(f"Updated config with {len(detected_paths)} game paths using correct naming format (no spaces)")
        else:
            self.logger.warning("Cannot update game paths in config because config is not loaded.")

    # --- Methods for Hoolamike Tasks (To be implemented later) ---
    # TODO: Update these methods to accept necessary parameters and update/save config

    def install_update_hoolamike(self, context=None) -> bool:
        """Install or update Hoolamike application.
        
        Returns:
            bool: True if installation/update was successful or process was properly cancelled,
                  False if a critical error occurred.
        """
        self.logger.info("Starting Hoolamike Installation/Update...")
        print("\nStarting Hoolamike Installation/Update...")
        
        # 1. Prompt user to install/reinstall/update
        try:
            # Check if Hoolamike is already installed at the expected path
            self._check_hoolamike_installation()
            if self.hoolamike_installed:
                self.logger.info(f"Hoolamike appears to be installed at: {self.hoolamike_executable_path}")
                print(f"{COLOR_INFO}Hoolamike is already installed at:{COLOR_RESET}")
                print(f"  {self.hoolamike_executable_path}")
                # Use a menu-style prompt for reinstall/update
                print(f"\n{COLOR_PROMPT}Choose an action for Hoolamike:{COLOR_RESET}")
                print(f"  1. Reinstall/Update Hoolamike")
                print(f"  2. Keep existing installation (return to menu)")
                while True:
                    choice = input(f"Select an option [1-2]: ").strip()
                    if choice == '1':
                        self.logger.info("User chose to reinstall/update Hoolamike.")
                        break
                    elif choice == '2' or choice.lower() == 'q':
                        self.logger.info("User chose to keep existing Hoolamike installation.")
                        print("Skipping Hoolamike installation/update.")
                        return True
                    else:
                        print(f"{COLOR_WARNING}Invalid choice. Please enter 1 or 2.{COLOR_RESET}")
            # 2. Get installation directory from user (allow override)
            self.logger.info(f"Default install path: {self.hoolamike_app_install_path}")
            print("\nHoolamike Installation Directory:")
            print(f"Default: {self.hoolamike_app_install_path}")
            install_dir = self.menu_handler.get_directory_path(
                prompt_message=f"Specify where to install Hoolamike (or press Enter for default)",
                default_path=self.hoolamike_app_install_path,
                create_if_missing=True,
                no_header=True
            )
            if install_dir is None:
                self.logger.warning("User cancelled Hoolamike installation path selection.")
                print("Installation cancelled.")
                return True
            # Check if hoolamike already exists at this specific path
            potential_existing_exe = install_dir / HOOLAMIKE_EXECUTABLE_NAME
            if potential_existing_exe.is_file() and os.access(potential_existing_exe, os.X_OK):
                self.logger.info(f"Hoolamike executable found at the chosen path: {potential_existing_exe}")
                print(f"{COLOR_INFO}Hoolamike appears to already be installed at:{COLOR_RESET}")
                print(f"  {install_dir}")
                # Use menu-style prompt for overwrite
                print(f"{COLOR_PROMPT}Choose an action for the existing installation:{COLOR_RESET}")
                print(f"  1. Download and overwrite (update)")
                print(f"  2. Keep existing installation (return to menu)")
                while True:
                    overwrite_choice = input(f"Select an option [1-2]: ").strip()
                    if overwrite_choice == '1':
                        self.logger.info("User chose to update (overwrite) existing Hoolamike installation.")
                        break
                    elif overwrite_choice == '2' or overwrite_choice.lower() == 'q':
                        self.logger.info("User chose to keep existing Hoolamike installation at chosen path.")
                        print("Update cancelled. Using existing installation for this session.")
                        self.hoolamike_app_install_path = install_dir
                        self.hoolamike_executable_path = potential_existing_exe
                        self.hoolamike_installed = True
                        return True
                    else:
                        print(f"{COLOR_WARNING}Invalid choice. Please enter 1 or 2.{COLOR_RESET}")
            # Proceed with install/update
            self.logger.info(f"Proceeding with installation to directory: {install_dir}")
            self.hoolamike_app_install_path = install_dir
            # Get latest release info from GitHub
            release_url = "https://api.github.com/repos/Niedzwiedzw/hoolamike/releases/latest"
            download_url = None
            asset_name = None
            try:
                self.logger.info(f"Fetching latest release info from {release_url}")
                show_status("Fetching latest Hoolamike release info...")
                response = requests.get(release_url, timeout=15, verify=True)
                response.raise_for_status()
                release_data = response.json()
                self.logger.debug(f"GitHub Release Data: {release_data}")
                linux_tar_asset = None
                linux_zip_asset = None
                for asset in release_data.get('assets', []):
                    name = asset.get('name', '').lower()
                    self.logger.debug(f"Checking asset: {name}")
                    is_linux = 'linux' in name
                    is_x64 = 'x86_64' in name or 'amd64' in name
                    is_incompatible_arch = 'arm' in name or 'aarch64' in name or 'darwin' in name
                    if is_linux and is_x64 and not is_incompatible_arch:
                        if name.endswith(('.tar.gz', '.tgz')):
                            linux_tar_asset = asset
                            self.logger.debug(f"Found potential tar asset: {name}")
                            break
                        elif name.endswith('.zip') and not linux_tar_asset:
                            linux_zip_asset = asset
                            self.logger.debug(f"Found potential zip asset: {name}")
                chosen_asset = linux_tar_asset or linux_zip_asset
                if not chosen_asset:
                    clear_status()
                    self.logger.error("Could not find a suitable Linux x86_64 download asset (tar.gz/zip) in the latest release.")
                    print(f"{COLOR_ERROR}Error: Could not find a linux x86_64 download asset in the latest Hoolamike release.{COLOR_RESET}")
                    return False
                download_url = chosen_asset.get('browser_download_url')
                asset_name = chosen_asset.get('name')
                if not download_url or not asset_name:
                    clear_status()
                    self.logger.error(f"Chosen asset is missing URL or name: {chosen_asset}")
                    print(f"{COLOR_ERROR}Error: Found asset but could not get download details.{COLOR_RESET}")
                    return False
                self.logger.info(f"Found asset '{asset_name}' for download: {download_url}")
                clear_status()
            except requests.exceptions.RequestException as e:
                clear_status()
                self.logger.error(f"Failed to fetch release info from GitHub: {e}")
                print(f"Error: Failed to contact GitHub to check for Hoolamike updates: {e}")
                return False
            except Exception as e:
                clear_status()
                self.logger.error(f"Error parsing release info: {e}", exc_info=True)
                print("Error: Failed to understand release information from GitHub.")
                return False
            # Download the asset
            show_status(f"Downloading {asset_name}...")
            temp_download_path = self.hoolamike_app_install_path / asset_name
            if not self.filesystem_handler.download_file(download_url, temp_download_path, overwrite=True, quiet=True):
                clear_status()
                self.logger.error(f"Failed to download {asset_name} from {download_url}")
                print(f"{COLOR_ERROR}Error: Failed to download Hoolamike asset.{COLOR_RESET}")
                return False
            clear_status()
            self.logger.info(f"Downloaded {asset_name} successfully to {temp_download_path}")
            show_status("Extracting Hoolamike archive...")
            # Extract the asset
            try:
                if asset_name.lower().endswith(('.tar.gz', '.tgz')):
                    self.logger.debug(f"Extracting tar file: {temp_download_path}")
                    with tarfile.open(temp_download_path, 'r:*') as tar:
                        tar.extractall(path=self.hoolamike_app_install_path)
                    self.logger.info("Extracted tar file successfully.")
                elif asset_name.lower().endswith('.zip'):
                    self.logger.debug(f"Extracting zip file: {temp_download_path}")
                    with zipfile.ZipFile(temp_download_path, 'r') as zip_ref:
                        zip_ref.extractall(self.hoolamike_app_install_path)
                    self.logger.info("Extracted zip file successfully.")
                else:
                    clear_status()
                    self.logger.error(f"Unknown archive format for asset: {asset_name}")
                    print(f"{COLOR_ERROR}Error: Unknown file type '{asset_name}'. Cannot extract.{COLOR_RESET}")
                    return False
                clear_status()
                print("Extraction complete. Setting permissions...")
            except (tarfile.TarError, zipfile.BadZipFile, EOFError) as e:
                clear_status()
                self.logger.error(f"Failed to extract archive {temp_download_path}: {e}", exc_info=True)
                print(f"{COLOR_ERROR}Error: Failed to extract downloaded file: {e}{COLOR_RESET}")
                return False
            except Exception as e:
                clear_status()
                self.logger.error(f"An unexpected error occurred during extraction: {e}", exc_info=True)
                print(f"{COLOR_ERROR}An unexpected error occurred during extraction.{COLOR_RESET}")
                return False
            finally:
                # Clean up downloaded archive
                if temp_download_path.exists():
                    try:
                        temp_download_path.unlink()
                        self.logger.debug(f"Removed temporary download file: {temp_download_path}")
                    except OSError as e:
                        self.logger.warning(f"Could not remove temporary download file {temp_download_path}: {e}")
            # Set execute permissions on the binary
            executable_path = self.hoolamike_app_install_path / HOOLAMIKE_EXECUTABLE_NAME
            if executable_path.is_file():
                try:
                    show_status("Setting permissions on Hoolamike executable...")
                    os.chmod(executable_path, 0o755)
                    self.logger.info(f"Set execute permissions (+x) on {executable_path}")
                    clear_status()
                    print("Permissions set successfully.")
                except OSError as e:
                    clear_status()
                    self.logger.error(f"Failed to set execute permission on {executable_path}: {e}")
                    print(f"{COLOR_ERROR}Error: Could not set execute permission on Hoolamike executable.{COLOR_RESET}")
                else:
                    clear_status()
                    self.logger.error(f"Hoolamike executable not found after extraction at {executable_path}")
                    print(f"{COLOR_ERROR}Error: Hoolamike executable missing after extraction!{COLOR_RESET}")
                    return False
            # Update self.hoolamike_installed and self.hoolamike_executable_path state
            self.logger.info("Refreshing Hoolamike installation status...")
            self._check_hoolamike_installation()
            if not self.hoolamike_installed:
                self.logger.error("Hoolamike check failed after apparent successful install/extract.")
                print(f"{COLOR_ERROR}Error: Installation completed, but failed final verification check.{COLOR_RESET}")
                return False
            # Save install path to Jackify config
            self.logger.info(f"Saving Hoolamike install path to Jackify config: {self.hoolamike_app_install_path}")
            self.config_handler.set('hoolamike_install_path', str(self.hoolamike_app_install_path))
            if not self.config_handler.save_config():
                self.logger.warning("Failed to save Jackify config file after updating Hoolamike path.")
                # Non-fatal, but warn user?
                print(f"{COLOR_WARNING}Warning: Could not save installation path to main Jackify config file.{COLOR_RESET}")
            print(f"{COLOR_SUCCESS}Hoolamike installation/update successful!{COLOR_RESET}")
            self.logger.info("Hoolamike install/update process completed successfully.")
            return True
        except Exception as e:
            self.logger.error(f"Error during Hoolamike installation/update: {e}", exc_info=True)
            print(f"{COLOR_ERROR}Error: An unexpected error occurred during Hoolamike installation/update: {e}{COLOR_RESET}")
            return False

    def install_modlist(self, wabbajack_path=None, install_path=None, downloads_path=None, premium=False, api_key=None, game_resolution=None, context=None):
        """
        Install a Wabbajack modlist using Hoolamike, following Jackify's Discovery/Configuration/Confirmation pattern.
        """
        self.logger.info("Starting Hoolamike modlist install (Discovery Phase)")
        self._check_hoolamike_installation()
        menu = self.menu_handler
        print(f"\n{'='*60}")
        print(f"{COLOR_INFO}Hoolamike Modlist Installation{COLOR_RESET}")
        print(f"{'='*60}\n")

        # --- Discovery Phase ---
        # 1. Auto-detect games (robust, multi-library)
        detected_games = self.path_handler.find_vanilla_game_paths()
        # 2. Prompt for .wabbajack file (custom prompt, only accept .wabbajack, q to exit, with tab-completion)
        print()
        while not wabbajack_path:
            print(f"{COLOR_WARNING}This option requires a Nexus Mods Premium account for automatic downloads.{COLOR_RESET}")
            print(f"If you don't have a premium account, please use the '{COLOR_SELECTION}Non-Premium Installation{COLOR_RESET}' option from the previous menu instead.\n")
            print(f"Before continuing, you'll need a .wabbajack file. You can usually find these at:")
            print(f"  1. {COLOR_INFO}https://build.wabbajack.org/authored_files{COLOR_RESET} - Official Wabbajack modlist repository")
            print(f"  2. {COLOR_INFO}https://www.nexusmods.com/{COLOR_RESET} - Some modlist authors publish on Nexus Mods")
            print(f"  3. Various Discord communities for specific modlists\n")
            print(f"{COLOR_WARNING}NOTE: Download the .wabbajack file first, then continue. Enter 'q' to exit.{COLOR_RESET}\n")
            # Use menu.get_existing_file_path for tab-completion
            candidate = menu.get_existing_file_path(
                prompt_message="Enter the path to your .wabbajack file (or 'q' to cancel):",
                extension_filter=".wabbajack",
                no_header=True
            )
            if candidate is None:
                print(f"{COLOR_WARNING}Cancelled by user.{COLOR_RESET}")
                return False
            # If user literally typed 'q', treat as cancel
            if str(candidate).strip().lower() == 'q':
                print(f"{COLOR_WARNING}Cancelled by user.{COLOR_RESET}")
                return False
            wabbajack_path = candidate
        # 3. Prompt for install directory
        print()
        while True:
            install_path_result = menu.get_directory_path(
                prompt_message="Select the directory where the modlist should be installed:",
                default_path=DEFAULT_MODLIST_INSTALL_BASE_DIR / wabbajack_path.stem,
                create_if_missing=True,
                no_header=False
            )
            if not install_path_result:
                print(f"{COLOR_WARNING}Cancelled by user.{COLOR_RESET}")
                return False
            # Handle tuple (path, should_create)
            if isinstance(install_path_result, tuple):
                install_path, install_should_create = install_path_result
            else:
                install_path, install_should_create = install_path_result, False
            # Check if directory exists and is not empty
            if install_path.exists() and any(install_path.iterdir()):
                print(f"{COLOR_WARNING}Warning: The selected directory '{install_path}' already exists and is not empty. Its contents may be overwritten!{COLOR_RESET}")
                confirm = input(f"{COLOR_PROMPT}This directory is not empty and may be overwritten. Proceed? (y/N): {COLOR_RESET}").strip().lower()
                if not confirm.startswith('y'):
                    print(f"{COLOR_INFO}Please select a different directory.\n{COLOR_RESET}")
                    continue
            break
        # 4. Prompt for downloads directory
        print()
        if not downloads_path:
            downloads_path_result = menu.get_directory_path(
                prompt_message="Select the directory for mod downloads:",
                default_path=DEFAULT_HOOLAMIKE_DOWNLOADS_DIR,
                create_if_missing=True,
                no_header=False
            )
            if not downloads_path_result:
                print(f"{COLOR_WARNING}Cancelled by user.{COLOR_RESET}")
                return False
            # Handle tuple (path, should_create)
            if isinstance(downloads_path_result, tuple):
                downloads_path, downloads_should_create = downloads_path_result
            else:
                downloads_path, downloads_should_create = downloads_path_result, False
        else:
            downloads_should_create = False
        # 5. Nexus API key
        print()
        current_api_key = self.hoolamike_config.get('downloaders', {}).get('nexus', {}).get('api_key') if self.hoolamike_config else None
        if not current_api_key or current_api_key == 'YOUR_API_KEY_HERE':
            api_key = menu.get_nexus_api_key(current_api_key)
            if not api_key:
                print(f"{COLOR_WARNING}Cancelled by user.{COLOR_RESET}")
                return False
        else:
            api_key = current_api_key

        # --- Summary & Confirmation ---
        print(f"\n{'-'*60}")
        print(f"{COLOR_INFO}Summary of configuration:{COLOR_RESET}")
        print(f"- Wabbajack file: {wabbajack_path}")
        print(f"- Install directory: {install_path}")
        print(f"- Downloads directory: {downloads_path}")
        print(f"- Nexus API key: [{'Set' if api_key else 'Not Set'}]")
        print("- Games:")
        for game in ["Fallout 3", "Fallout New Vegas", "Skyrim Special Edition", "Oblivion", "Fallout 4"]:
            found = detected_games.get(game)
            print(f"    {game}: {found if found else 'Not Found'}")
        print(f"{'-'*60}")
        print(f"{COLOR_WARNING}Proceed with these settings and start Hoolamike install? (Warning: This can take MANY HOURS){COLOR_RESET}")
        confirm = input(f"{COLOR_PROMPT}[Y/n]: {COLOR_RESET}").strip().lower()
        if confirm and not confirm.startswith('y'):
            print(f"{COLOR_WARNING}Cancelled by user.{COLOR_RESET}")
            return False
        # --- Actually create directories if needed ---
        if install_should_create and not install_path.exists():
            try:
                install_path.mkdir(parents=True, exist_ok=True)
                print(f"{COLOR_SUCCESS}Install directory created: {install_path}{COLOR_RESET}")
            except Exception as e:
                print(f"{COLOR_ERROR}Failed to create install directory: {e}{COLOR_RESET}")
                return False
        if downloads_should_create and not downloads_path.exists():
            try:
                downloads_path.mkdir(parents=True, exist_ok=True)
                print(f"{COLOR_SUCCESS}Downloads directory created: {downloads_path}{COLOR_RESET}")
            except Exception as e:
                print(f"{COLOR_ERROR}Failed to create downloads directory: {e}{COLOR_RESET}")
                return False

        # --- Configuration Phase ---
        # Prepare config dict
        config = {
            "downloaders": {
                "downloads_directory": str(downloads_path),
                "nexus": {"api_key": api_key}
            },
            "installation": {
                "wabbajack_file_path": str(wabbajack_path),
                "installation_path": str(install_path)
            },
            "games": {
                self._format_game_name(game): {"root_directory": str(path)}
                for game, path in detected_games.items()
            },
            "fixup": {
                "game_resolution": "1920x1080"
            },
            # Resolution intentionally omitted
            # "extras": {},
            # No 'jackify_managed' key here
        }
        self.hoolamike_config = config
        if not self.save_hoolamike_config():
            print(f"{COLOR_ERROR}Failed to save hoolamike.yaml. Aborting.{COLOR_RESET}")
            return False

        # --- Run Hoolamike ---
        print(f"\n{COLOR_INFO}Starting Hoolamike...{COLOR_RESET}")
        print(f"{COLOR_INFO}Streaming output below. Press Ctrl+C to cancel and return to Jackify menu.{COLOR_RESET}\n")
        # Defensive: Ensure executable path is set and valid
        if not self.hoolamike_executable_path or not Path(self.hoolamike_executable_path).is_file():
            print(f"{COLOR_ERROR}Error: Hoolamike executable not found or not set. Please (re)install Hoolamike from the menu before continuing.{COLOR_RESET}")
            input(f"{COLOR_PROMPT}Press Enter to return to the Hoolamike menu...{COLOR_RESET}")
            return False
        try:
            cmd = [str(self.hoolamike_executable_path), "install"]
            ret = subprocess.call(cmd, cwd=str(self.hoolamike_app_install_path), env=get_clean_subprocess_env())
            if ret == 0:
                print(f"\n{COLOR_SUCCESS}Hoolamike completed successfully!{COLOR_RESET}")
                input(f"{COLOR_PROMPT}Press Enter to return to the Hoolamike menu...{COLOR_RESET}")
                return True
            else:
                print(f"\n{COLOR_ERROR}Hoolamike process failed with exit code {ret}.{COLOR_RESET}")
                input(f"{COLOR_PROMPT}Press Enter to return to the Hoolamike menu...{COLOR_RESET}")
                return False
        except KeyboardInterrupt:
            print(f"\n{COLOR_WARNING}Hoolamike install interrupted by user. Returning to menu.{COLOR_RESET}")
            input(f"{COLOR_PROMPT}Press Enter to return to the Hoolamike menu...{COLOR_RESET}")
            return False
        except Exception as e:
            print(f"\n{COLOR_ERROR}Error running Hoolamike: {e}{COLOR_RESET}")
            input(f"{COLOR_PROMPT}Press Enter to return to the Hoolamike menu...{COLOR_RESET}")
            return False

    def install_ttw(self, ttw_mpi_path=None, ttw_output_path=None, context=None):
        """Install Tale of Two Wastelands (TTW) using Hoolamike.
        
        Args:
            ttw_mpi_path: Path to the TTW installer .mpi file
            ttw_output_path: Target installation directory for TTW
            
        Returns:
            bool: True if successful, False otherwise
        """
        self.logger.info(f"Starting Tale of Two Wastelands installation via Hoolamike")
        self._check_hoolamike_installation()
        menu = self.menu_handler
        print(f"\n{'='*60}")
        print(f"{COLOR_INFO}Hoolamike: Tale of Two Wastelands Installation{COLOR_RESET}")
        print(f"{'='*60}\n")
        print(f"This feature will install Tale of Two Wastelands (TTW) using Hoolamike.")
        print(f"Requirements:")
        print(f"  • Fallout 3 and Fallout New Vegas must be installed and detected.")
        print(f"  • You must provide the path to your TTW .mpi installer file.")
        print(f"  • You must select an output directory for the TTW install.\n")

        # Ensure config is loaded
        if self.hoolamike_config is None:
            loaded = self._load_hoolamike_config()
            if not loaded or self.hoolamike_config is None:
                self.logger.error("Failed to load or generate hoolamike.yaml configuration.")
                print(f"{COLOR_ERROR}Error: Could not load or generate Hoolamike configuration. Aborting TTW install.{COLOR_RESET}")
                return False
        
        # Verify required games are in configuration
        required_games = ['Fallout 3', 'Fallout New Vegas']
        detected_games = self.path_handler.find_vanilla_game_paths()
        missing_games = [game for game in required_games if game not in detected_games]
        if missing_games:
            self.logger.error(f"Missing required games for TTW installation: {', '.join(missing_games)}")
            print(f"{COLOR_ERROR}Error: The following required games were not found: {', '.join(missing_games)}{COLOR_RESET}")
            print("TTW requires both Fallout 3 and Fallout New Vegas to be installed.")
            return False

        # Prompt for TTW .mpi file
        print(f"{COLOR_INFO}Please provide the path to your TTW .mpi installer file.{COLOR_RESET}")
        print(f"You can download this from: {COLOR_INFO}https://mod.pub/ttw/133/files{COLOR_RESET}")
        print(f"(Extract the .mpi file from the downloaded archive.)\n")
        while not ttw_mpi_path:
            candidate = menu.get_existing_file_path(
                prompt_message="Enter the path to your TTW .mpi file (or 'q' to cancel):",
                extension_filter=".mpi",
                no_header=True
            )
            if candidate is None:
                print(f"{COLOR_WARNING}Cancelled by user.{COLOR_RESET}")
                return False
            if str(candidate).strip().lower() == 'q':
                print(f"{COLOR_WARNING}Cancelled by user.{COLOR_RESET}")
                return False
            ttw_mpi_path = candidate

        # Prompt for output directory
        print(f"\n{COLOR_INFO}Please select the output directory where TTW will be installed.{COLOR_RESET}")
        print(f"(This should be an empty or new directory.)\n")
        while not ttw_output_path:
            ttw_output_path = menu.get_directory_path(
                prompt_message="Select the TTW output directory:",
                default_path=self.hoolamike_app_install_path / "TTW_Output",
                create_if_missing=True,
                no_header=False
            )
            if not ttw_output_path:
                print(f"{COLOR_WARNING}Cancelled by user.{COLOR_RESET}")
                return False
            if ttw_output_path.exists() and any(ttw_output_path.iterdir()):
                print(f"{COLOR_WARNING}Warning: The selected directory '{ttw_output_path}' already exists and is not empty. Its contents may be overwritten!{COLOR_RESET}")
                confirm = input(f"{COLOR_PROMPT}This directory is not empty and may be overwritten. Proceed? (y/N): {COLOR_RESET}").strip().lower()
                if not confirm.startswith('y'):
                    print(f"{COLOR_INFO}Please select a different directory.\n{COLOR_RESET}")
                    ttw_output_path = None
                    continue

        # --- Summary & Confirmation ---
        print(f"\n{'-'*60}")
        print(f"{COLOR_INFO}Summary of configuration:{COLOR_RESET}")
        print(f"- TTW .mpi file: {ttw_mpi_path}")
        print(f"- Output directory: {ttw_output_path}")
        print("- Games:")
        for game in required_games:
            found = detected_games.get(game)
            print(f"    {game}: {found if found else 'Not Found'}")
        print(f"{'-'*60}")
        print(f"{COLOR_WARNING}Proceed with these settings and start TTW installation? (This can take MANY HOURS){COLOR_RESET}")
        confirm = input(f"{COLOR_PROMPT}[Y/n]: {COLOR_RESET}").strip().lower()
        if confirm and not confirm.startswith('y'):
            print(f"{COLOR_WARNING}Cancelled by user.{COLOR_RESET}")
            return False

        # --- Always re-detect games before updating config ---
        detected_games = self.path_handler.find_vanilla_game_paths()
        if not detected_games:
            print(f"{COLOR_ERROR}No supported games were detected on your system. TTW requires Fallout 3 and Fallout New Vegas to be installed.{COLOR_RESET}")
            return False
        # Update the games section with correct keys
        if self.hoolamike_config is None:
            self.hoolamike_config = {}
        self.hoolamike_config['games'] = {
            self._format_game_name(game): {"root_directory": str(path)}
            for game, path in detected_games.items()
        }

        # Update TTW configuration
        self._update_hoolamike_config_for_ttw(ttw_mpi_path, ttw_output_path)
        if not self.save_hoolamike_config():
            self.logger.error("Failed to save hoolamike.yaml configuration.")
            print(f"{COLOR_ERROR}Error: Failed to save Hoolamike configuration.{COLOR_RESET}")
            print("Attempting to continue anyway...")

        # Construct command to execute
        cmd = [
            str(self.hoolamike_executable_path),
            "tale-of-two-wastelands"
        ]
        self.logger.info(f"Executing Hoolamike command: {' '.join(cmd)}")
        print(f"\n{COLOR_INFO}Executing Hoolamike for TTW Installation...{COLOR_RESET}")
        print(f"Command: {' '.join(cmd)}")
        print(f"{COLOR_INFO}Streaming output below. Press Ctrl+C to cancel and return to Jackify menu.{COLOR_RESET}\n")
        try:
            ret = subprocess.call(cmd, cwd=str(self.hoolamike_app_install_path), env=get_clean_subprocess_env())
            if ret == 0:
                self.logger.info("TTW installation completed successfully.")
                print(f"\n{COLOR_SUCCESS}TTW installation completed successfully!{COLOR_RESET}")
                input(f"{COLOR_PROMPT}Press Enter to return to the Hoolamike menu...{COLOR_RESET}")
                return True
            else:
                self.logger.error(f"TTW installation process returned non-zero exit code: {ret}")
                print(f"\n{COLOR_ERROR}Error: TTW installation failed with exit code {ret}.{COLOR_RESET}")
                input(f"{COLOR_PROMPT}Press Enter to return to the Hoolamike menu...{COLOR_RESET}")
                return False
        except Exception as e:
            self.logger.error(f"Error executing Hoolamike TTW installation: {e}", exc_info=True)
            print(f"\n{COLOR_ERROR}Error executing Hoolamike TTW installation: {e}{COLOR_RESET}")
            input(f"{COLOR_PROMPT}Press Enter to return to the Hoolamike menu...{COLOR_RESET}")
            return False

    def _update_hoolamike_config_for_ttw(self, ttw_mpi_path: Path, ttw_output_path: Path):
        """Update the Hoolamike configuration with settings for TTW installation."""
        # Ensure extras and TTW sections exist
        if "extras" not in self.hoolamike_config:
            self.hoolamike_config["extras"] = {}
            
        if "tale_of_two_wastelands" not in self.hoolamike_config["extras"]:
            self.hoolamike_config["extras"]["tale_of_two_wastelands"] = {
                "variables": {}
            }
            
        # Update TTW configuration
        ttw_config = self.hoolamike_config["extras"]["tale_of_two_wastelands"]
        ttw_config["path_to_ttw_mpi_file"] = str(ttw_mpi_path)
        
        # Ensure variables section exists
        if "variables" not in ttw_config:
            ttw_config["variables"] = {}
            
        # Set destination variable
        ttw_config["variables"]["DESTINATION"] = str(ttw_output_path)
        
        # Set USERPROFILE to a Jackify-managed directory for TTW
        userprofile_path = str(self.hoolamike_app_install_path / "USERPROFILE")
        if "variables" not in self.hoolamike_config["extras"]["tale_of_two_wastelands"]:
            self.hoolamike_config["extras"]["tale_of_two_wastelands"]["variables"] = {}
        self.hoolamike_config["extras"]["tale_of_two_wastelands"]["variables"]["USERPROFILE"] = userprofile_path
        
        # Make sure game paths are set correctly
        for game in ['Fallout 3', 'Fallout New Vegas']:
            if game in self.game_install_paths:
                game_key = game.replace(' ', '').lower()
                
                if "games" not in self.hoolamike_config:
                    self.hoolamike_config["games"] = {}
                    
                if game not in self.hoolamike_config["games"]:
                    self.hoolamike_config["games"][game] = {}
                    
                self.hoolamike_config["games"][game]["root_directory"] = str(self.game_install_paths[game])
                
        self.logger.info("Updated Hoolamike configuration with TTW settings.")

    def reset_config(self):
        """Resets the hoolamike.yaml to default settings, backing up any existing file."""
        if self.hoolamike_config_path.is_file():
            # Create a backup with timestamp
            import datetime
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = self.hoolamike_config_path.with_suffix(f".{timestamp}.bak")
            try:
                import shutil
                shutil.copy2(self.hoolamike_config_path, backup_path)
                self.logger.info(f"Created backup of existing config at {backup_path}")
                print(f"{COLOR_INFO}Created backup of existing config at {backup_path}{COLOR_RESET}")
            except Exception as e:
                self.logger.error(f"Failed to create backup of config: {e}")
                print(f"{COLOR_WARNING}Warning: Failed to create backup of config: {e}{COLOR_RESET}")
        
        # Generate and save a fresh default config
        self.logger.info("Generating new default configuration")
        self.hoolamike_config = self._generate_default_config()
        if self.save_hoolamike_config():
            self.logger.info("Successfully reset config to defaults")
            print(f"{COLOR_SUCCESS}Successfully reset configuration to defaults.{COLOR_RESET}")
            return True
        else:
            self.logger.error("Failed to save new default config")
            print(f"{COLOR_ERROR}Failed to save new default configuration.{COLOR_RESET}")
            return False

    def edit_hoolamike_config(self):
        """Opens the hoolamike.yaml file in a chosen editor, with a 0 option to return to menu."""
        self.logger.info("Task: Edit Hoolamike Config started...")
        self._check_hoolamike_installation()
        if not self.hoolamike_installed:
            self.logger.warning("Cannot edit config - Hoolamike not installed")
            print(f"\n{COLOR_WARNING}Hoolamike is not installed through Jackify yet.{COLOR_RESET}")
            print(f"Please use option 1 from the Hoolamike menu to install Hoolamike first.")
            print(f"This will ensure that Jackify can properly manage the Hoolamike configuration.")
            return False
        if self.hoolamike_config is None:
            self.logger.warning("Config is not loaded properly. Will attempt to fix or create.")
            print(f"\n{COLOR_WARNING}Configuration file may be corrupted or not accessible.{COLOR_RESET}")
            print("Options:")
            print("1. Reset to default configuration (backup will be created)")
            print("2. Try to edit the file anyway (may be corrupted)")
            print("0. Cancel and return to menu")
            choice = input("\nEnter your choice (0-2): ").strip()
            if choice == "1":
                if not self.reset_config():
                    self.logger.error("Failed to reset configuration")
                    print(f"{COLOR_ERROR}Failed to reset configuration. See logs for details.{COLOR_RESET}")
                    return
            elif choice == "2":
                self.logger.warning("User chose to edit potentially corrupted config")
                # Continue to editing
            elif choice == "0":
                self.logger.info("User cancelled editing corrupted config")
                print("Edit cancelled.")
                return
            else:
                self.logger.info("User cancelled editing corrupted config")
                print("Edit cancelled.")
                return
        if not self.hoolamike_config_path.exists():
            self.logger.warning(f"Hoolamike config file does not exist at {self.hoolamike_config_path}. Generating default before editing.")
            self.hoolamike_config = self._generate_default_config()
            self.save_hoolamike_config()
            if not self.hoolamike_config_path.exists():
                 self.logger.error("Failed to create config file for editing.")
                 print("Error: Could not create configuration file.")
                 return
        available_editors = ["nano", "vim", "vi", "gedit", "kate", "micro"]
        preferred_editor = os.environ.get("EDITOR")
        found_editors = {}
        import shutil
        for editor_name in available_editors:
            editor_path = shutil.which(editor_name)
            if editor_path and editor_path not in found_editors.values():
                found_editors[editor_name] = editor_path
        if preferred_editor:
            preferred_editor_path = shutil.which(preferred_editor)
            if preferred_editor_path and preferred_editor_path not in found_editors.values():
                display_name = os.path.basename(preferred_editor) if '/' in preferred_editor else preferred_editor
                if display_name not in found_editors:
                    found_editors[display_name] = preferred_editor_path
        if not found_editors:
            self.logger.error("No suitable text editors found on the system.")
            print(f"{COLOR_ERROR}Error: No common text editors (nano, vim, gedit, kate, micro) found.{COLOR_RESET}")
            return
        sorted_editor_names = sorted(found_editors.keys())
        print("\nSelect an editor to open the configuration file:")
        print(f"(System default EDITOR is: {preferred_editor if preferred_editor else 'Not set'})")
        for i, name in enumerate(sorted_editor_names):
            print(f" {i + 1}. {name}")
        print(f" 0. Return to Hoolamike Menu")
        while True:
            try:
                choice = input(f"Enter choice (0-{len(sorted_editor_names)}): ").strip()
                if choice == "0":
                    print("Edit cancelled.")
                    return
                choice_index = int(choice) - 1
                if 0 <= choice_index < len(sorted_editor_names):
                    chosen_name = sorted_editor_names[choice_index]
                    editor_to_use_path = found_editors[chosen_name]
                    break
                else:
                    print("Invalid choice.")
            except ValueError:
                print("Invalid input. Please enter a number.")
            except KeyboardInterrupt:
                print("\nEdit cancelled.")
                return
        if editor_to_use_path:
            self.logger.info(f"Launching editor '{editor_to_use_path}' for {self.hoolamike_config_path}")
            try:
                process = subprocess.Popen([editor_to_use_path, str(self.hoolamike_config_path)])
                process.wait()
                self.logger.info(f"Editor '{editor_to_use_path}' closed. Reloading config...")
                if not self._load_hoolamike_config():
                    self.logger.error("Failed to load config after editing. It may still be corrupted.")
                    print(f"{COLOR_ERROR}Warning: The configuration file could not be parsed after editing.{COLOR_RESET}")
                    print("You may need to fix it manually or reset it to defaults.")
                    return False
                else:
                    self.logger.info("Successfully reloaded config after editing.")
                    print(f"{COLOR_SUCCESS}Configuration file successfully updated.{COLOR_RESET}")
                    return True
            except FileNotFoundError:
                self.logger.error(f"Editor '{editor_to_use_path}' not found unexpectedly.")
                print(f"{COLOR_ERROR}Error: Editor command '{editor_to_use_path}' not found.{COLOR_RESET}")
            except Exception as e:
                self.logger.error(f"Error launching or waiting for editor: {e}")
                print(f"{COLOR_ERROR}An error occurred while launching the editor: {e}{COLOR_RESET}")

# Example usage (for testing, remove later)
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    print("Running HoolamikeHandler discovery...")
    handler = HoolamikeHandler(steamdeck=False, verbose=True)
    print("\n--- Discovery Results ---")
    print(f"Game Paths: {handler.game_install_paths}")
    print(f"Hoolamike App Install Path: {handler.hoolamike_app_install_path}")
    print(f"Hoolamike Executable: {handler.hoolamike_executable_path}")
    print(f"Hoolamike Installed: {handler.hoolamike_installed}")
    print(f"Hoolamike Config Path: {handler.hoolamike_config_path}")
    config_loaded = isinstance(handler.hoolamike_config, dict)
    print(f"Hoolamike Config Loaded: {config_loaded}")
    if config_loaded:
         print(f"  Downloads Dir: {handler.hoolamike_config.get('downloaders', {}).get('downloads_directory')}")
         print(f"  API Key Set: {'Yes' if handler.hoolamike_config.get('downloaders', {}).get('nexus', {}).get('api_key') != 'YOUR_API_KEY_HERE' else 'No'}")
    print("-------------------------")
    # Test edit config (example)
    # handler.edit_hoolamike_config() 