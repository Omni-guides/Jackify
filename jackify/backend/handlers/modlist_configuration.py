"""Configuration workflow methods for ModlistHandler (Mixin)."""
from pathlib import Path
import os
import logging
import re
from typing import Optional

from jackify.shared.colors import COLOR_PROMPT, COLOR_RESET, COLOR_INFO, COLOR_ERROR
from .resolution_handler import ResolutionHandler

logger = logging.getLogger(__name__)

# Special game types that still receive Step 15 tool compatibility settings, because they run
# the same engine and tooling as the non-special variants that already get them.
TOOL_COMPAT_VR_TYPES = ('skyrimvr', 'fallout4vr')


class ModlistConfigurationMixin:
    """Mixin providing configuration workflow methods for ModlistHandler."""

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

    def _execute_configuration_steps(self, status_callback=None, defer_playbooks: bool = False):
        """
        Runs the actual configuration steps for the selected modlist.
        Args:
            status_callback (callable, optional): A function to call with status updates during configuration.
            defer_playbooks: True when the caller runs on a background Qt thread and cannot show
                a consent dialog here - Step 17 is skipped entirely and the caller is responsible
                for calling the playbook hook itself once back on the main thread.
        """
        try:
            # Store status_callback for Configuration Summary
            self._current_status_callback = status_callback
            
            self.logger.info("Executing configuration steps...")
            
            # Ensure required context is set
            if not all([self.modlist_dir, self.appid, self.game_var, self.steamdeck is not None]):
                self.logger.error("Cannot execute configuration steps: Missing required context (modlist_dir, appid, game_var, steamdeck status).")
                self.logger.error("Missing required information to start configuration.")
                return False
        except Exception as e:
            self.logger.error(f"Exception in _execute_configuration_steps initialization: {e}", exc_info=True)
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
            self.logger.error("Could not set necessary Protontricks permissions.")
            return False # Abort on failure
        self.logger.info("Step 1: Setting Protontricks permissions... Done")

        # Step 3: Apply targeted registry tweaks (replaces wholesale curated reg file overwrite)
        if status_callback:
            status_callback(f"{self._get_progress_timestamp()} Applying modlist registry configuration")
        self.logger.info("Step 3: Applying modlist registry tweaks...")
        try:
            self._apply_modlist_registry_tweaks()
        except Exception as e:
            self.logger.warning("Modlist registry tweaks failed (non-fatal): %s", e)

        # Step 4: Install Wine Components
        if status_callback:
            status_callback(f"{self._get_progress_timestamp()} Installing Wine components (this may take a while)")
        self.logger.info("Step 4: Installing Wine components (this may take a while)...")
        
        # Use canonical logic for all modlists/games
        components = self.get_modlist_wine_components(self.game_name, self.game_var_full)

        # NSF detection: dotnet48 required for Skyrim SE modlists with NetScriptFramework
        if 'skyrim' in (self.game_var_full or '').lower() and self.modlist_dir:
            nsf_markers = [
                Path(self.modlist_dir) / 'mods' / 'NetScriptFramework' / 'DLLPlugins' / 'NetScriptFramework.Runtime.dll',
                Path(self.modlist_dir) / 'mods' / 'NetScriptFramework' / 'Plugins' / 'CustomSkills.dll',
                Path(self.modlist_dir) / 'mods' / 'NetScriptFramework',
            ]
            if any(m.exists() for m in nsf_markers):
                self._nsf_detected = True
                if 'dotnet48' not in components:
                    self.logger.info("NetScriptFramework detected, adding dotnet48 to component list")
                    components.insert(0, 'dotnet48')

        # Developer/testing override: JACKIFY_SKIP_WINE_COMPONENTS=comp1,comp2 drops those
        # components from this run, for iterating without re-installing slow verbs (e.g.
        # dotnetdesktop6). Unset in normal use, so it has no effect on real installs.
        _skip_env = os.environ.get('JACKIFY_SKIP_WINE_COMPONENTS', '').strip()
        if _skip_env:
            _skip_set = {c.strip() for c in _skip_env.split(',') if c.strip()}
            _removed = [c for c in components if c in _skip_set]
            if _removed:
                components = [c for c in components if c not in _skip_set]
                self.logger.warning("JACKIFY_SKIP_WINE_COMPONENTS active - skipping %s (testing override)", _removed)

        # All modlists now use their own AppID for wine components
        target_appid = self.appid
        
        # Use user's preferred component installation method (respects settings toggle)
        self.logger.debug(f"Getting WINEPREFIX for AppID {target_appid}...")
        wineprefix = self.protontricks_handler.get_wine_prefix_path(target_appid)
        if not wineprefix:
            self.logger.error("Failed to get WINEPREFIX path for component installation.")
            self.logger.error("Could not determine wine prefix location.")
            return False
        self.logger.debug(f"WINEPREFIX obtained: {wineprefix}")

        # Use the winetricks handler which respects the user's toggle setting
        try:
            self.logger.info("Installing Wine components using user's preferred method...")
            self.logger.debug(f"Calling winetricks_handler.install_wine_components with wineprefix={wineprefix}, game_var={self.game_var_full}, components={components}")
            success = self.winetricks_handler.install_wine_components(wineprefix, self.game_var_full, specific_components=components, status_callback=status_callback, appid=str(target_appid) if target_appid else None)
            if success:
                self.logger.info("Wine component installation completed successfully")
                if status_callback:
                    status_callback(f"{self._get_progress_timestamp()} Wine components verified and installed successfully")
            else:
                self.logger.error("Wine component installation failed")
                self.logger.error("Failed to install necessary Wine components.")
                return False
        except Exception as e:
            self.logger.error(f"Wine component installation failed with exception: {e}")
            self.logger.error("Failed to install necessary Wine components.")
            return False
        self.logger.info("Step 4: Installing Wine components... Done")

        # Step 4.5: Apply universal dotnet4.x compatibility registry fixes AFTER wine components
        # Apply after components to avoid overwrite
        if status_callback:
            status_callback(f"{self._get_progress_timestamp()} Applying universal dotnet4.x compatibility fixes")
        self.logger.info("Step 4.5: Applying universal dotnet4.x compatibility registry fixes...")
        registry_success = False
        try:
            registry_success = self._apply_universal_dotnet_fixes()
        except Exception as e:
            error_msg = f"CRITICAL: Registry fixes failed - modlist may have .NET compatibility issues: {e}"
            self.logger.error(error_msg)
            if status_callback:
                status_callback(f"{self._get_progress_timestamp()} ERROR: {error_msg}")
            registry_success = False

        if not registry_success:
            failure_msg = "WARNING: Universal dotnet4.x registry fixes FAILED! This modlist may experience .NET Framework compatibility issues."
            self.logger.error("=" * 80)
            self.logger.error(failure_msg)
            self.logger.error("Consider manually setting mscoree=native in winecfg if problems occur.")
            self.logger.error("=" * 80)
            if status_callback:
                status_callback(f"{self._get_progress_timestamp()} {failure_msg}")
            # Continue but user should be aware of potential issues

        # Step 4.6: Audit final registry state - confirms all writes survived winetricks
        self.logger.info("Step 4.6: Auditing registry state...")
        try:
            self._audit_registry_state()
        except Exception as e:
            self.logger.warning("Registry audit failed (non-fatal): %s", e)

        # Step 4.7: Create Wine prefix Documents directories for USVFS
        # Critical for USVFS profile INI virtualization on first launch
        if status_callback:
            status_callback(f"{self._get_progress_timestamp()} Creating Wine prefix Documents directories for USVFS")
        self.logger.info("Step 4.7: Creating Wine prefix Documents directories for USVFS...")
        try:
            if self.appid:
                # Map detected game type to the key expected by create_required_dirs
                game_name_map = {
                    "skyrim": "skyrimse",
                    "skyrimspecialedition": "skyrimse",
                    "skyrimvr": "skyrimvr",
                    "fallout": "fallout4",
                    "fallout4": "fallout4",
                    "fo4": "fallout4",
                    "fallout4vr": "fallout4vr",
                    "fnv": "falloutnv",
                    "falloutnv": "falloutnv",
                    "oblivion": "oblivion",
                    "oblivion_remastered": "oblivion_remastered",
                    "enderal": "enderalse",
                    "enderalspecialedition": "enderalse",
                    "bg3": "bg3",
                    "baldursgate3": "bg3",
                    "cp2077": "cp2077",
                    "starfield": "starfield",
                }
                game_name = game_name_map.get((self.game_var or '').lower(), None)

                # Fallback: read gameName= directly from ModOrganizer.ini when loader-based
                # detection returned Unknown (e.g. Enderal uses a non-SKSE launcher variant)
                if not game_name and self.modlist_dir:
                    try:
                        from jackify.backend.services.steamgriddb_service import detect_game_type_from_modlist
                        _detected = detect_game_type_from_modlist(str(self.modlist_dir))
                        if _detected:
                            game_name = game_name_map.get(_detected, _detected)
                            self.logger.info(f"Step 4.7: game type resolved via gameName= fallback: {_detected} -> {game_name}")
                    except Exception as _fe:
                        self.logger.debug(f"Step 4.7 fallback detection failed: {_fe}")

                if game_name:
                    appid_str = str(self.appid)
                    if self.filesystem_handler.create_required_dirs(
                        game_name, appid_str, modlist_dir=str(self.modlist_dir) if self.modlist_dir else None
                    ):
                        self.logger.info("Wine prefix Documents directories created successfully for USVFS")
                    else:
                        self.logger.warning("Failed to create Wine prefix Documents directories (non-critical, continuing)")
                else:
                    self.logger.debug(f"Game {self.game_var!r} not in directory creation map, skipping")
            else:
                self.logger.warning("AppID not available, skipping Wine prefix Documents directory creation")
        except Exception as e:
            self.logger.warning(f"Error creating Wine prefix Documents directories: {e} (non-critical, continuing)")
        self.logger.info("Step 4.7: Creating Wine prefix Documents directories... Done")

        # Step 4.8: Configure nxmhandler.ini to suppress MO2 NXM registration popup
        self.logger.info("Step 4.8: Configuring nxmhandler.ini...")
        try:
            self._configure_nxmhandler_ini()
        except Exception as e:
            self.logger.debug(f"nxmhandler.ini configuration failed (non-critical): {e}")
        self.logger.info("Step 4.8: Configuring nxmhandler.ini... Done")

        # Step 4.9: Inject game install path registry entries (FNV/FO3/Enderal/CP2077/BG3).
        # Required so the game launcher and engine can locate the base game when
        # MO2 is running inside the Proton prefix.  Idempotent: safe to run on
        # reinstall or re-configure.
        self.logger.info("Step 4.9: Injecting game registry entries...")
        try:
            compatdata_path = self.path_handler.find_compat_data(str(self.appid))
            if compatdata_path:
                from jackify.backend.services.automated_prefix_service import AutomatedPrefixService
                from jackify.backend.models.configuration import SystemInfo
                from jackify.backend.services.platform_detection_service import PlatformDetectionService
                _svc = AutomatedPrefixService(SystemInfo(
                    is_steamdeck=PlatformDetectionService.get_instance().is_steamdeck
                ))
                _svc._inject_game_registry_entries(str(compatdata_path), self.game_var or '')
            else:
                self.logger.debug("Compatdata path not found for game registry injection, skipping")
        except Exception as e:
            self.logger.warning("Game registry injection failed (non-fatal): %s", e)
        self.logger.info("Step 4.9: Injecting game registry entries... Done")

        # Step 5: Verify ownership of Modlist directory
        if status_callback:
            status_callback(f"{self._get_progress_timestamp()} Verifying modlist directory ownership")
        self.logger.info("Step 5: Verifying ownership of modlist directory...")
        # Convert modlist_dir string to Path object for the method
        modlist_path_obj = Path(self.modlist_dir)
        success, error_msg = self.filesystem_handler.verify_ownership_and_permissions(modlist_path_obj)
        if not success:
            self.logger.error("Ownership verification failed for modlist directory. Configuration aborted.")
            print(f"\n{COLOR_ERROR}{error_msg}{COLOR_RESET}")
            return False # Abort on failure
        self.logger.info("Step 5: Ownership verification... Done")

        # Step 6: Backup ModOrganizer.ini
        if status_callback:
            status_callback(f"{self._get_progress_timestamp()} Backing up ModOrganizer.ini")
        self.logger.info(f"Step 6: Backing up {self.modlist_ini}...")
        modlist_ini_path_obj = Path(self.modlist_ini)
        backup_path = self.filesystem_handler.backup_file(modlist_ini_path_obj)
        if not backup_path:
            self.logger.error("Failed to back up ModOrganizer.ini. Configuration aborted.")
            self.logger.error("Failed to back up ModOrganizer.ini.")
            return False # Abort on failure
        self.logger.info(f"ModOrganizer.ini backed up to: {backup_path}")
        self.logger.info("Step 6: Backing up ModOrganizer.ini... Done")

        # Step 6.1: BG3-specific patches to ModOrganizer.ini and MO2 plugins
        self._patch_bg3_mod_settings_plugin()
        self._set_bg3_rootbuilder_copy_mode()

        # Step 6.5: Handle symlinked downloads directory
        if status_callback:
            status_callback(f"{self._get_progress_timestamp()} Checking for symlinked downloads directory")
        self.logger.info("Step 6.5: Checking for symlinked downloads directory...")
        if not self._handle_symlinked_downloads():
            self.logger.warning("Warning during symlink handling (non-critical)")
        self.logger.info("Step 6.5: Checking for symlinked downloads directory... Done")

        # Step 7a: Detect Stock Game/Game Root path
        if status_callback:
            status_callback(f"{self._get_progress_timestamp()} Detecting stock game path")
        # Sets self.stock_game_path if found
        if not self._detect_stock_game_path():
            self.logger.error("Failed during stock game path detection.")
            self.logger.error("Failed during stock game path detection.")
            return False

        # Step 7b: Detect Steam Library Info (Needed for Step 8)
        if status_callback:
            status_callback(f"{self._get_progress_timestamp()} Detecting Steam Library info")
        self.logger.info("Step 7b: Detecting Steam Library info...")
        if not self._detect_steam_library_info():
             self.logger.error("Failed to detect necessary Steam Library information.")
             self.logger.error("Could not find Steam library information.")
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
                self.logger.error("Failed to update game path in ModOrganizer.ini.")
                return False  # Abort on failure
        else:
            self.logger.info("No stock game path found, skipping gamePath update - edit_binary_working_paths will handle all path updates.")
            self.logger.info("Using unified path manipulation to avoid duplicate processing.")
        
        # Conditionally update binary and working directory paths
        # Skip for jackify-engine workflows since paths are already correct
        # Exception: Always run for SD card installs to fix Z:/run/media/... to D:/... paths

        # DEBUG: Add comprehensive logging to identify Steam Deck SD card path manipulation issues
        engine_installed = getattr(self, 'engine_installed', False)
        self.logger.debug(f"[SD_CARD_DEBUG] ModlistHandler instance: id={id(self)}")
        self.logger.debug(f"[SD_CARD_DEBUG] engine_installed: {engine_installed}")
        self.logger.debug(f"[SD_CARD_DEBUG] modlist_sdcard: {self.modlist_sdcard}")
        self.logger.debug(f"[SD_CARD_DEBUG] steamdeck parameter passed to constructor: {getattr(self, 'steamdeck', 'NOT_SET')}")
        self.logger.debug(f"[SD_CARD_DEBUG] Path manipulation condition: not {engine_installed} or {self.modlist_sdcard} = {not engine_installed or self.modlist_sdcard}")

        if not getattr(self, 'engine_installed', False) or self.modlist_sdcard:
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
                steam_libraries=steam_libraries,
                compat_data_path=getattr(self, 'compat_data_path', None)
            ):
                self.logger.error("Failed to update binary and working directory paths in ModOrganizer.ini. Configuration aborted.")
                self.logger.error("Failed to update binary and working directory paths in ModOrganizer.ini.")
                return False  # Abort on failure
        else:
            self.logger.debug("[SD_CARD_DEBUG] Skipping path manipulation - jackify-engine already set correct paths in ModOrganizer.ini")
            self.logger.debug(f"[SD_CARD_DEBUG] SKIPPED because: engine_installed={engine_installed} and modlist_sdcard={self.modlist_sdcard}")

        if getattr(self, 'download_dir', None):
            if self.path_handler.set_download_directory(
                modlist_ini_path_obj, str(self.download_dir), self.modlist_sdcard
            ):
                self.logger.info("Set download_directory in ModOrganizer.ini (Install flow)")
            else:
                self.logger.warning("Could not set download_directory in ModOrganizer.ini")
        elif modlist_ini_path_obj.is_file():
            # Configure Existing / Configure New flows: no explicit download_dir is set, but the
            # INI may have duplicate or mangled entries from the original Wabbajack install.
            # Read the first valid value, then re-write all occurrences to that value so MO2
            # reads the correct path regardless of which occurrence it picks up last.
            existing_linux = self.path_handler.get_download_directory_linux_path(modlist_ini_path_obj)
            if existing_linux:
                if self.path_handler.set_download_directory(
                    modlist_ini_path_obj, existing_linux, self.modlist_sdcard
                ):
                    self.logger.info("Normalised download_directory entries in ModOrganizer.ini")
                else:
                    self.logger.warning("Could not normalise download_directory in ModOrganizer.ini")
            else:
                self.logger.debug("No existing download_directory value found in ModOrganizer.ini; skipping normalisation")

        # Step 8.5: Align /home vs /var/home basis for Z: paths to match modlist install directory.
        # Kept separate from broad binary-path rewriting so it still runs when
        # engine-installed workflows skip edit_binary_working_paths.
        if not self.path_handler.align_home_path_basis(
            modlist_ini_path=modlist_ini_path_obj,
            modlist_dir_path=modlist_dir_path_obj,
            modlist_sdcard=self.modlist_sdcard,
        ):
            self.logger.error("Failed to align home-path basis in ModOrganizer.ini. Configuration aborted.")
            self.logger.error("Failed to align /home path basis in ModOrganizer.ini.")
            return False

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

            if not ResolutionHandler.update_ini_resolution(
                modlist_dir=self.modlist_dir,
                game_var=self.game_var_full,
                set_res=self.selected_resolution,
                vanilla_game_dir=vanilla_game_dir
            ):
                self.logger.warning("Failed to update resolution settings in some INI files.")
                self.logger.warning("Failed to update resolution settings.")
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
                
            dxvk_created = self.path_handler.create_dxvk_conf(
                modlist_dir=self.modlist_dir, 
                modlist_sdcard=self.modlist_sdcard, 
                steam_library=str(self.steam_library) if self.steam_library else None, # Pass as string or None 
                basegame_sdcard=self.basegame_sdcard, 
                game_var_full=self.game_var_full,
                vanilla_game_dir=vanilla_game_dir,
                stock_game_path=self.stock_game_path
            )
            dxvk_verified = self.path_handler.verify_dxvk_conf_exists(
                modlist_dir=self.modlist_dir,
                steam_library=str(self.steam_library) if self.steam_library else None,
                game_var_full=self.game_var_full,
                vanilla_game_dir=vanilla_game_dir,
                stock_game_path=self.stock_game_path
            )
            if not dxvk_created or not dxvk_verified:
                self.logger.warning("DXVK configuration file is missing or incomplete after post-install steps.")
                self.logger.warning("Failed to verify dxvk.conf file (required for AMD GPUs).")
            self.logger.info("Step 10: Creating dxvk.conf... Done")

        # Step 11a: Small Tasks - Delete Incompatible Plugins
        if status_callback:
            status_callback(f"{self._get_progress_timestamp()} Deleting incompatible MO2 plugins")
        self.logger.info("Step 11a: Deleting incompatible MO2 plugins...")

        # Delete FixGameRegKey.py plugin
        fixgamereg_path = Path(self.modlist_dir) / "plugins" / "FixGameRegKey.py"
        if fixgamereg_path.exists():
            try:
                fixgamereg_path.unlink()
                self.logger.info("FixGameRegKey.py plugin deleted successfully.")
            except Exception as e:
                self.logger.warning(f"Failed to delete FixGameRegKey.py plugin: {e}")
                self.logger.warning("Failed to delete FixGameRegKey.py plugin file.")
        else:
            self.logger.debug("FixGameRegKey.py plugin not found (this is normal).")

        # Delete PageFileManager plugin directory (Linux has no PageFile)
        pagefilemgr_path = Path(self.modlist_dir) / "plugins" / "PageFileManager"
        if pagefilemgr_path.exists():
            try:
                import shutil
                shutil.rmtree(pagefilemgr_path)
                self.logger.info("PageFileManager plugin directory deleted successfully.")
            except Exception as e:
                self.logger.warning(f"Failed to delete PageFileManager plugin directory: {e}")
                self.logger.warning("Failed to delete PageFileManager plugin directory.")
        else:
            self.logger.debug("PageFileManager plugin not found (this is normal).")

        self.logger.info("Step 11a: Incompatible plugin deletion check complete.")


        # Step 11b: Download Font
        if status_callback:
            status_callback(f"{self._get_progress_timestamp()} Downloading required font")
        prefix_path_str = self.path_handler.find_compat_data(str(self.appid))
        if prefix_path_str:
            prefix_path = Path(prefix_path_str)
            fonts_dir = prefix_path / "pfx" / "drive_c" / "windows" / "Fonts"
            font_url = "https://github.com/mrbvrz/segoe-ui-linux/raw/refs/heads/master/font/seguisym.ttf"
            font_dest_path = fonts_dir / "seguisym.ttf"
            
            # Pass quiet=True to suppress print during configuration steps
            if not self.filesystem_handler.download_file(font_url, font_dest_path, quiet=True):
                self.logger.warning(f"Failed to download {font_url} to {font_dest_path}")
                self.logger.warning("Failed to download necessary font file (seguisym.ttf).")
                # Continue anyway, not critical for all lists
            else:
                self.logger.info("Font downloaded successfully.")
        else:
            self.logger.error("Could not get WINEPREFIX path, skipping font download.")
            self.logger.warning("Could not determine Wine prefix path, skipping font download.")

        # Step 12: Modlist-specific steps
        if status_callback:
            status_callback(f"{self._get_progress_timestamp()} Checking for modlist-specific steps")
            status_callback("")  # Blank line after final Prefix Configuration step
        self.logger.info("Step 12: Checking for modlist-specific steps...")

        # Step 13: Launch options for special games are now set during automated prefix workflow (before Steam restart)
        # Avoids a second Steam restart
        special_game_type = self.detect_special_game_type(self.modlist_dir)
        if special_game_type:
            self.logger.info(f"Step 13: Launch options for {special_game_type.upper()} were set during automated workflow")
        else:
            self.logger.debug("Step 13: No special launch options needed for this modlist type")

        if status_callback:
            status_callback(f"{self._get_progress_timestamp()} Finalizing post-install configuration")

        # Do not call status_callback here, the final message is handled in menu_handler
        # if status_callback:
        #     status_callback("Configuration completed successfully!")
            
        self.logger.info("Configuration steps completed successfully.")

        # Step 15: Apply tool compatibility settings (xEdit, Pandora, DLL overrides).
        # Runs for standard Skyrim SE/AE and Fallout 4 modlists (neither is a special
        # type, so both fall through the None branch), plus Enderal SE and the two VR
        # variants. Other special types (FNV, FO3, etc.) are excluded entirely -
        # different engine, none of these fixes apply. Enderal SE shares the Skyrim SE
        # engine and plugin format, so xEdit/Pandora/DLL overrides/Synthesis dotnet+NuGet
        # setup all still apply - only the mscoree AppDefault is skipped for it
        # (apply_engine_mscoree below), since that entry is scoped to SkyrimSE.exe, which
        # is also Enderal's own game process and would crash it.
        # The VR variants run the same engines and tooling as the flat versions, and need no
        # mscoree exception - their processes are SkyrimVR.exe/Fallout4VR.exe.
        _special_type = self.detect_special_game_type(self.modlist_dir)
        _enderal = _special_type == 'enderal'
        _vr = _special_type in TOOL_COMPAT_VR_TYPES
        try:
            from jackify.backend.handlers.config_handler import ConfigHandler
            if ConfigHandler().get('auto_tool_compat', True) and (_special_type is None or _enderal or _vr):
                if status_callback:
                    status_callback(f"{self._get_progress_timestamp()} Applying tool compatibility settings")
                self.logger.info("Step 15: Applying tool compatibility settings...")
                compatdata_path = str(wineprefix).replace("/pfx", "").rstrip("/")
                wine_bin = self._find_wine_binary_for_registry()
                if compatdata_path and wine_bin:
                    from jackify.backend.services.tool_config_service import apply_tool_config
                    # NSF/CSF modlists need the global *mscoree=native that winetricks dotnet48
                    # set: the per-exe scoping this function applies starves NSF's CLR hosting
                    # (verified directly). So preserve the global override for them.
                    # dotnet SDK install also flips the prefix to win11; NSF/CSF was only
                    # verified working on win10 + global-native, so we keep that state and skip
                    # the dotnet SDK/win11 step. Whether Synthesis runs under global-native on an
                    # NSF prefix has not been specifically tested - revisit if a modlist needs live
                    # Synthesis. The NuGet cert Synthesis needs is applied regardless (see
                    # apply_tool_config), since it doesn't touch mscoree or Windows version.
                    _nsf = getattr(self, '_nsf_detected', False)
                    apply_tool_config(
                        compatdata_path,
                        wine_bin,
                        log=lambda msg: status_callback(f"{self._get_progress_timestamp()} {msg}") if status_callback else None,
                        install_dotnet_sdk=not _nsf,
                        install_fxc2_d3dcompiler=True,
                        preserve_global_mscoree=_nsf,
                        apply_engine_mscoree=not _enderal,
                    )
                    self.logger.info("Step 15: Tool compatibility settings applied")
                else:
                    self.logger.warning("Step 15: Could not resolve prefix path or wine binary - skipping tool compat")

                if self.modlist_dir:
                    from jackify.backend.services.synthesis_updater import update_synthesis
                    update_synthesis(
                        str(self.modlist_dir),
                        log=lambda msg: status_callback(f"{self._get_progress_timestamp()} {msg}") if status_callback else None,
                    )
            elif _special_type is not None:
                self.logger.info(f"Step 15: Skipping tool compat for {_special_type} modlist")
        except Exception as e:
            self.logger.warning("Step 15: Tool compatibility settings failed (non-fatal): %s", e)

        # Step 16: Nemesis compatibility setup (symlink + workingDirectory fix)
        try:
            from jackify.backend.services.tool_config_service import setup_nemesis_compatibility
            setup_nemesis_compatibility(
                modlist_dir=self.modlist_dir,
                stock_game_path=self.stock_game_path,
                log=lambda msg: status_callback(f"{self._get_progress_timestamp()} {msg}") if status_callback else None,
            )
        except Exception as e:
            self.logger.warning("Step 16: Nemesis setup failed (non-fatal): %s", e)

        # Step 17: USVFS Linux fix (patched usvfs_x64.dll for faster MO2 load under Wine)
        try:
            if self.modlist_dir:
                from jackify.backend.services.usvfs_patch_service import apply_usvfs_patch
                result = apply_usvfs_patch(
                    Path(self.modlist_dir),
                    log=lambda msg: status_callback(f"{self._get_progress_timestamp()} {msg}") if status_callback else None,
                )
                if result.is_warning:
                    self.logger.warning("Step 17: %s", result.message)
                else:
                    self.logger.info("Step 17: %s", result.message)
        except Exception as e:
            self.logger.warning("Step 17: USVFS Linux fix failed (non-fatal): %s", e)

        try:
            if self.modlist_dir and self.game_name:
                from jackify.backend.services.install_registry import register_install
                register_install(
                    self.modlist_dir, self.game_name,
                    game_type=self.game_var_full, appid=self.appid, configured=True,
                )
        except Exception as e:
            self.logger.debug("Install registry update skipped: %s", e)

        try:
            from jackify import __version__ as _jackify_version
            from jackify.backend.services.jackify_db import gather_environment_fields, record_event
            record_event(
                "configure_completed", "success",
                modlist_name=self.game_name, game_type=self.game_var_full,
                jackify_version=_jackify_version,
                proton_version=getattr(self, 'proton_ver', None),
                **gather_environment_fields(),
            )
        except Exception as e:
            self.logger.debug("JackifyDB record skipped: %s", e)

        # Step 17: Modlist playbooks (community fixes registry) - non-fatal by design, see
        # backend/services/playbook/hook_wiring.py. Deferred to the caller when running on a
        # background Qt thread, since consent may require a dialog this thread cannot show.
        if not defer_playbooks:
            from jackify.backend.services.playbook.hook_wiring import run_configuration_hook
            run_configuration_hook(self)

        return True # Return True on success

    def run_modlist_configuration_phase(self, context: dict = None, defer_playbooks: bool = False) -> bool:
        """
        Main entry point to run the full modlist configuration sequence.
        This orchestrates all the individual steps.
        """
        self.logger.info(f"Starting configuration phase for modlist: {self.game_name}")
        # Call the private method that contains the actual steps
        # Pass along the status_callback if it was provided in the context
        status_callback = context.get('status_callback') if context else None
        return self._execute_configuration_steps(status_callback=status_callback, defer_playbooks=defer_playbooks)

    def _configure_nxmhandler_ini(self) -> None:
        """
        Set noregister=true in nxmhandler.ini in the MO2 install directory.

        MO2 reads this flag on startup and skips the NXM handler registration
        popup when it is true. On Linux, MO2's NXM handler cannot be registered
        usefully via Wine; Jackify will become its own NXM handler in a later cycle.
        Safe to apply on every configuration run - always correct on Linux.
        """
        if not self.modlist_dir:
            return

        nxm_ini_path = os.path.join(self.modlist_dir, "nxmhandler.ini")

        try:
            if os.path.exists(nxm_ini_path):
                with open(nxm_ini_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                if re.search(r'(?im)^\s*noregister\s*=\s*true\s*$', content):
                    self.logger.debug("nxmhandler.ini noregister already true, skipping")
                    return

                # Replace existing noregister=... line if present, otherwise inject after [General]
                if re.search(r'(?im)^\s*noregister\s*=', content):
                    content = re.sub(r'(?im)^\s*noregister\s*=.*$', 'noregister=true', content)
                elif re.search(r'(?im)^\s*\[General\]', content):
                    content = re.sub(r'(?im)(^\s*\[General\]\s*\n)', r'\1noregister=true\n', content)
                else:
                    content += '\n[General]\nnoregister=true\n'

                with open(nxm_ini_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                self.logger.info(f"Set noregister=true in {nxm_ini_path}")
            else:
                # MO2 creates nxmhandler.ini on first run; pre-create with the flag set
                with open(nxm_ini_path, 'w', encoding='utf-8') as f:
                    f.write("[General]\nnoregister=true\n")
                self.logger.info(f"Created nxmhandler.ini with noregister=true: {nxm_ini_path}")
        except Exception as e:
            self.logger.warning(f"Could not configure nxmhandler.ini: {e}")

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

    def _patch_bg3_mod_settings_plugin(self) -> None:
        """
        Fix a bug in the BG3 MO2 plugin (Alvadus/BG3-MO2-Unofficial-Plugin) where
        mods_order_node is conditionally created but unconditionally referenced.
        Bug present in upstream source as of 2026-03; author not yet notified.
        Safe to apply: always creating the ModOrder node is valid BG3 XML regardless of mod count.
        """
        import os
        if not self.modlist_dir:
            return
        plugin_path = os.path.join(
            str(self.modlist_dir),
            "plugins", "basic_games", "games", "baldursgate3", "modSettings.py"
        )
        if not os.path.exists(plugin_path):
            self.logger.debug("BG3 modSettings.py plugin not found, skipping patch")
            return
        try:
            with open(plugin_path, 'r', encoding='utf-8') as f:
                content = f.read()
            buggy = (
                "    if len(mod_settings) > 1:\n"
                "        mods_order_node = ET.SubElement(children, \"node\")\n"
                "        mods_order_node.set(\"id\", \"ModOrder\")"
            )
            fixed = (
                "    mods_order_node = ET.SubElement(children, \"node\")\n"
                "    mods_order_node.set(\"id\", \"ModOrder\")"
            )
            if buggy in content:
                content = content.replace(buggy, fixed)
                with open(plugin_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                self.logger.info("Applied modSettings.py patch for BG3 MO2 plugin")
            elif fixed in content:
                self.logger.debug("BG3 modSettings.py already patched, skipping")
            else:
                self.logger.warning("BG3 modSettings.py patch target not found - plugin may have changed upstream")
        except Exception as e:
            self.logger.warning(f"Could not patch BG3 modSettings.py: {e} (non-critical, continuing)")

    def _set_bg3_rootbuilder_copy_mode(self) -> None:
        """
        Switch Root Builder to copy mode in ModOrganizer.ini for BG3 modlists.
        Link mode (the shipped default) fails on Linux - files are not accessible
        to the game process across the Wine boundary. Copy mode works reliably.
        Applied unconditionally: copy mode is safe regardless of drive layout.
        Detected by presence of RootBuilder keys rather than game_var (unreliable for BG3).
        """
        import os, re
        if not self.modlist_dir:
            return
        mo2_ini = os.path.join(str(self.modlist_dir), "ModOrganizer.ini")
        if not os.path.exists(mo2_ini):
            self.logger.debug("ModOrganizer.ini not found, skipping Root Builder copy mode patch")
            return
        try:
            with open(mo2_ini, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            if 'RootBuilder\\' not in content and 'RootBuilder/' not in content:
                self.logger.debug("Root Builder not present in ModOrganizer.ini, skipping")
                return
            content = re.sub(r'^(RootBuilder\\copyfiles\s*=).*$', r'\1**', content, flags=re.MULTILINE)
            content = re.sub(r'^(RootBuilder\\linkfiles\s*=).*$', r'\1', content, flags=re.MULTILINE)
            with open(mo2_ini, 'w', encoding='utf-8') as f:
                f.write(content)
            self.logger.info("Set Root Builder to copy mode in ModOrganizer.ini")
        except Exception as e:
            self.logger.warning(f"Could not set Root Builder copy mode: {e} (non-critical, continuing)")
