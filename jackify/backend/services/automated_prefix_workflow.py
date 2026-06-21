"""Workflow methods for AutomatedPrefixService (Mixin)."""
from pathlib import Path
from typing import Optional, Union, List, Dict, Tuple
import logging
import os
import vdf

logger = logging.getLogger(__name__)

class WorkflowMixin:
    """Mixin providing workflow methods for AutomatedPrefixService."""

    def handle_existing_shortcut_conflict(self, shortcut_name: str, exe_path: str, modlist_install_dir: str) -> Union[bool, List[Dict]]:
        """
        Check for existing shortcut with same name and path, prompt user if found.
        
        Args:
            shortcut_name: Name of the shortcut to create
            exe_path: Path to the executable
            modlist_install_dir: Directory where the modlist is installed
            
        Returns:
            True if we should proceed (no conflict or user chose to replace), False if user cancelled
        """
        try:
            shortcuts_path = self._get_shortcuts_path()
            if not shortcuts_path:
                return True  # No shortcuts file, no conflict
            
            with open(shortcuts_path, 'rb') as f:
                shortcuts_data = vdf.binary_load(f)
            
            shortcuts = shortcuts_data.get('shortcuts', {})
            conflicts = []
            
            # Look for shortcuts with the same name AND path
            for i in range(len(shortcuts)):
                shortcut = shortcuts[str(i)]
                name = shortcut.get('AppName', '')
                shortcut_exe = shortcut.get('Exe', '').strip('"')  # Remove quotes
                shortcut_startdir = shortcut.get('StartDir', '').strip('"')  # Remove quotes
                
                # Check if name matches AND (exe path matches OR startdir matches)
                # Use exact name match instead of partial match to avoid false positives
                name_matches = shortcut_name == name
                exe_matches = shortcut_exe == exe_path
                startdir_matches = shortcut_startdir == modlist_install_dir
                
                if (name_matches and (exe_matches or startdir_matches)):
                    raw_appid = shortcut.get('appid')
                    normalized_appid = None
                    if raw_appid is not None:
                        try:
                            normalized_appid = str(int(raw_appid) & 0xFFFFFFFF)
                        except Exception:
                            normalized_appid = str(raw_appid)
                    conflicts.append({
                        'index': i,
                        'name': name,
                        'exe': shortcut_exe,
                        'startdir': shortcut_startdir,
                        'appid': normalized_appid,
                    })
            
            if conflicts:
                logger.warning(f"Found {len(conflicts)} existing shortcut(s) with same name and path")
                
                # Log details about each conflict for debugging
                for i, conflict in enumerate(conflicts):
                    logger.info(f"Conflict {i+1}: Name='{conflict['name']}', Exe='{conflict['exe']}', StartDir='{conflict['startdir']}'")
                
                # Return the conflict information so the frontend can handle it
                return conflicts
            else:
                logger.debug("No conflicting shortcuts found")
                return True
                
        except Exception as e:
            logger.error(f"Error handling shortcut conflict: {e}")
            return True  # Proceed on error to avoid blocking

    def format_conflict_message(self, conflicts: List[Dict]) -> str:
        """
        Format conflict information into a user-friendly message.
        
        Args:
            conflicts: List of conflict dictionaries from handle_existing_shortcut_conflict
            
        Returns:
            Formatted message for the user
        """
        if not conflicts:
            return "No conflicts found."
        
        message = f"Found {len(conflicts)} existing Steam shortcut(s) with the same name and path:\n\n"
        
        for i, conflict in enumerate(conflicts, 1):
            message += f"{i}. **Name:** {conflict['name']}\n"
            message += f"   **Executable:** {conflict['exe']}\n"
            message += f"   **Start Directory:** {conflict['startdir']}\n\n"
        
        message += "**Options:**\n"
        message += "• **Replace** - Remove the existing shortcut and create a new one\n"
        message += "• **Cancel** - Keep the existing shortcut and stop the installation\n"
        message += "• **Skip** - Continue without creating a Steam shortcut\n\n"
        message += "The existing shortcut will be removed if you choose to replace it."
        
        return message

    def run_working_workflow(self, shortcut_name: str, modlist_install_dir: str,
                            final_exe_path: str, progress_callback=None, steamdeck: Optional[bool] = None,
                            download_dir=None, auto_restart: bool = True) -> Tuple[bool, Optional[Path], Optional[int], Optional[str]]:
        """
        Run the proven working automated prefix creation workflow.

        This implements our tested and working approach:
        1. Create shortcut with native Steam service (pointing to ModOrganizer.exe initially)
        2. Restart Steam using Jackify's robust method
        3. Create Proton prefix invisibly using Proton wrapper with DISPLAY=
        4. Verify everything persists

        Args:
            shortcut_name: Name for the Steam shortcut
            modlist_install_dir: Directory where the modlist is installed
            final_exe_path: Path to ModOrganizer.exe
            progress_callback: Optional callback for progress updates
            steamdeck: Optional Steam Deck detection override
            download_dir: Optional download path; its mountpoint is added to STEAM_COMPAT_MOUNTS
            auto_restart: If True, automatically restart Steam. If False, skip restart step.

        Returns:
            Tuple of (success, prefix_path, appid, last_timestamp)
        """
        logger.info("Starting proven working automated prefix creation workflow")

        if download_dir is None:
            try:
                from jackify.backend.handlers.path_handler import PathHandler
                ini_path = Path(modlist_install_dir) / 'ModOrganizer.ini'
                dl_str = PathHandler().get_download_directory_linux_path(ini_path)
                if dl_str:
                    download_dir = Path(dl_str)
                    logger.debug(f"Resolved download_dir from ini: {download_dir}")
            except Exception as e:
                logger.debug(f"Could not resolve download_dir from ini: {e}")

        try:
            conflict_result = self.handle_existing_shortcut_conflict(
                shortcut_name,
                final_exe_path,
                modlist_install_dir,
            )
            if isinstance(conflict_result, list):
                logger.warning(
                    "Found %d existing shortcut(s) with same name and path before Steam integration",
                    len(conflict_result),
                )
                return ("CONFLICT", conflict_result, None, None)
            if conflict_result is False:
                logger.error("User cancelled due to shortcut conflict")
                return False, None, None, None

            # Show installation complete and configuration start headers only after
            # conflict checks pass, so users do not see Steam integration start
            # messages when Jackify is about to stop for duplicate-shortcut review.
            if progress_callback:
                progress_callback("")
                progress_callback("=" * 64)
                progress_callback("= Installation phase complete =")
                progress_callback("=" * 64)
                progress_callback("")
                progress_callback("=" * 64)
                progress_callback("= Starting Configuration Phase =")
                progress_callback("=" * 64)
                progress_callback("")

            # Reset timing for Steam Integration section (part of Configuration Phase)
            from jackify.shared.timing import start_new_phase
            start_new_phase()

            # Show immediate feedback to user with section header
            if progress_callback:
                progress_callback("")  # Blank line before Steam Integration
                progress_callback("=== Steam Integration ===")
                progress_callback(f"{self._get_progress_timestamp()} Creating Steam shortcut with native service")

            # Registry injection approach for both FNV and Enderal
            from ..handlers.modlist_handler import ModlistHandler
            modlist_handler = ModlistHandler()
            special_game_type = modlist_handler.detect_special_game_type(modlist_install_dir)

            custom_launch_options = None
            if special_game_type in ["fnv", "fo3", "enderal"]:
                logger.info(f"Using registry injection approach for {special_game_type.upper()} modlist")
            elif special_game_type == "cp2077":
                logger.info("Cyberpunk 2077 modlist detected - setting WINEDLLOVERRIDES for Red4ext/CET")
                # version=n,b overrides d3d version detection for REDmod; winmm=n,b required for CET
                custom_launch_options = 'WINEDLLOVERRIDES="version=n,b;winmm=n,b" %command%'
            elif special_game_type == "bg3":
                logger.info("Baldur's Gate 3 modlist detected")
                logger.warning("BG3 modlists require Rootbuilder in COPY mode - verify this in MO2 plugin settings")
            elif special_game_type in ["skyrimvr", "fallout4vr"]:
                game_label = "Skyrim VR" if special_game_type == "skyrimvr" else "Fallout 4 VR"
                logger.warning("%s modlist detected - SteamVR must be installed and running for this modlist to work", game_label)
                logger.warning("%s modlists use Rootbuilder for game root files - ensure Rootbuilder is set to COPY mode in MO2 plugin settings", game_label)
            else:
                logger.debug("Standard modlist - no special game handling needed")

            # Step 0: Shut down Steam before modifying VDF files
            # Required to safely modify shortcuts.vdf and config.vdf without race conditions
            logger.info("Step 0: Shutting down Steam before modifying VDF files")
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Shutting down Steam...")

            from .steam_restart_service import shutdown_steam
            try:
                if not shutdown_steam():
                    logger.warning("Steam shutdown returned False, continuing anyway")
            except Exception as e:
                logger.warning(f"Steam shutdown failed: {e}, continuing anyway")

            logger.info("Step 0 completed: Steam shut down")
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Steam shut down")

            # Pre-fetch SteamGridDB artwork before shortcut creation so the icon field in
            # shortcuts.vdf is populated at write time. Steam caches the icon on first read
            # after restart; setting it after the fact has no effect.
            steamicons_dir = Path(modlist_install_dir) / "SteamIcons"
            if not steamicons_dir.is_dir():
                from ..services.steamgriddb_service import detect_game_type_from_modlist
                _prefetch_game_type = detect_game_type_from_modlist(modlist_install_dir)
                if _prefetch_game_type:
                    try:
                        from ..services.steamgriddb_service import fetch_artwork
                        steamicons_dir.mkdir(parents=True, exist_ok=True)
                        count = fetch_artwork(_prefetch_game_type, steamicons_dir)
                        if count == 0:
                            steamicons_dir.rmdir()
                            logger.debug("SteamGridDB pre-fetch returned no images")
                        else:
                            logger.info(f"Pre-fetched {count} SteamGridDB images to {steamicons_dir}")
                    except Exception as e:
                        logger.debug(f"SteamGridDB pre-fetch failed: {e}")
                        try:
                            if steamicons_dir.is_dir() and not any(steamicons_dir.iterdir()):
                                steamicons_dir.rmdir()
                        except Exception:
                            pass

            # Step 1: Create shortcut with native Steam service (Steam is now shut down)
            logger.info("Step 1: Creating shortcut with native Steam service")
            # Create shortcut using native Steam service with special game launch options
            success, appid = self.create_shortcut_with_native_service(
                shortcut_name, final_exe_path, modlist_install_dir, custom_launch_options, download_dir=download_dir
            )
            if not success:
                logger.error("Failed to create shortcut with native Steam service")
                from jackify.shared.errors import shortcut_write_failed
                raise shortcut_write_failed("create_shortcut_with_native_service returned failure")
            
            logger.info(f"Step 1 completed: Shortcut created with native service, AppID: {appid}")
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Steam shortcut created successfully")
            
            # Apply Steam artwork if available
            try:
                from ..handlers.modlist_handler import ModlistHandler
                modlist_handler = ModlistHandler()
                modlist_handler.set_steam_grid_images(str(appid), modlist_install_dir)
                logger.info(f"Steam artwork applied for shortcut '{shortcut_name}' (AppID: {appid})")
            except Exception as e:
                logger.warning(f"Steam artwork application failed: {e}")
            
            # Step 2: Start Steam (if auto_restart enabled)
            logger.info("Step 2: auto_restart=%s", auto_restart)
            if auto_restart:
                logger.info("Step 2: Starting Steam using Jackify's robust method")
                if progress_callback:
                    progress_callback(f"{self._get_progress_timestamp()} Starting Steam...")

                restart_ok = self.restart_steam()
                logger.info("Step 2: restart_steam() returned %s", restart_ok)
                if not restart_ok:
                    logger.error("Failed to start Steam")
                    from jackify.shared.errors import steam_restart_failed
                    raise steam_restart_failed("Steam did not come back within the expected time")

                logger.info("Step 2 completed: Steam started")
                if progress_callback:
                    progress_callback(f"{self._get_progress_timestamp()} Steam started successfully")
                    progress_callback("[Jackify] Steam restart complete")
            else:
                logger.info("Step 2 skipped: Auto-restart disabled by user")
                if progress_callback:
                    progress_callback(f"{self._get_progress_timestamp()} Steam restart skipped (auto-restart disabled)")
            
            # Step 3: Create Proton prefix invisibly using Proton wrapper
            logger.info("Step 3: Creating Proton prefix invisibly")
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Creating Proton prefix...")
            
            if not self.create_prefix_with_proton_wrapper(appid):
                logger.error("Failed to create Proton prefix")
                from jackify.shared.errors import prefix_creation_failed
                raise prefix_creation_failed("create_prefix_with_proton_wrapper returned failure")
            
            logger.info("Step 3 completed: Proton prefix created")
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Proton prefix created successfully")
            
            # Step 4: Verify everything persists
            logger.info("Step 4: Verifying compatibility tool persists")
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Verifying setup...")
            
            if not self.verify_compatibility_tool_persists(appid):
                logger.warning("Compatibility tool verification failed, but continuing")
            
            logger.info("Step 4 completed: Verification done")
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Setup verification completed")
            
            # Step 5: Inject game registry entries for FNV and Enderal modlists
            # Get prefix path (needed for logging regardless of game type)
            prefix_path = self.get_prefix_path(appid)

            if special_game_type in ["fnv", "fo3", "enderal"]:
                logger.info(f"Step 5: Injecting {special_game_type.upper()} game registry entries")
                if progress_callback:
                    progress_callback(f"{self._get_progress_timestamp()} Injecting {special_game_type.upper()} game registry entries...")

                if prefix_path:
                    self._inject_game_registry_entries(str(prefix_path), special_game_type)
                else:
                    logger.warning("Could not find prefix path for registry injection")
            elif special_game_type == "cp2077":
                logger.info("Step 5: Applying CP2077 DLL overrides to prefix registry")
                if progress_callback:
                    progress_callback(f"{self._get_progress_timestamp()} Configuring CP2077 mod framework DLL overrides...")

                if prefix_path:
                    self._apply_cp2077_dll_overrides(str(prefix_path))
                else:
                    logger.warning("Could not find prefix path for CP2077 DLL override injection")
            else:
                logger.info("Step 5: Skipping registry injection for standard modlist")

            # Step 5.5: Pre-create game-specific directories for all modlists
            logger.info(f"Step 5.5: Creating game-specific user directories")
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Creating game user directories...")

            if prefix_path:
                self._create_game_user_directories(str(prefix_path), special_game_type, modlist_install_dir)
            else:
                logger.warning("Could not find prefix path for directory creation")



            last_timestamp = self._get_progress_timestamp()
            logger.info(f" Working workflow completed successfully! AppID: {appid}, Prefix: {prefix_path}")
            if progress_callback:
                progress_callback(f"{last_timestamp} Steam integration complete")
                progress_callback("")  # Blank line after Steam integration complete


            if progress_callback:
                progress_callback("")  # Extra blank line to span across Configuration Summary
                progress_callback("")  # And one more to create space before Prefix Configuration

            return True, prefix_path, appid, last_timestamp
            
        except Exception as e:
            logger.error(f"Error in working workflow: {e}", exc_info=True)
            if progress_callback:
                progress_callback(f"Error: {str(e)}")
            from jackify.shared.errors import JackifyError, prefix_creation_failed
            if isinstance(e, JackifyError):
                raise
            raise prefix_creation_failed(str(e)) from e

    def continue_workflow_after_conflict_resolution(self, shortcut_name: str, modlist_install_dir: str, 
                                                  final_exe_path: str, appid: int, progress_callback=None) -> Tuple[bool, Optional[Path], Optional[int]]:
        """
        Continue the workflow after a shortcut conflict has been resolved.
        
        Args:
            shortcut_name: Name of the shortcut
            modlist_install_dir: Directory where the modlist is installed
            final_exe_path: Path to the final executable
            appid: The AppID of the shortcut that was created/replaced
            progress_callback: Optional callback for progress updates
            
        Returns:
            Tuple of (success, prefix_path, appid)
        """
        try:
            logger.info("Continuing workflow after conflict resolution")
            
            # Step 2: Restart Steam using Jackify's robust method
            logger.info("Step 2: Restarting Steam using Jackify's robust method")
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Restarting Steam...")
            
            if not self.restart_steam():
                logger.error("Failed to restart Steam")
                return False, None, None, None
            
            logger.info("Step 2 completed: Steam restarted")
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Steam restarted successfully")
            
            # Step 3: Create Proton prefix invisibly using Proton wrapper
            logger.info("Step 3: Creating Proton prefix invisibly")
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Creating Proton prefix...")
            
            if not self.create_prefix_with_proton_wrapper(appid):
                logger.error("Failed to create Proton prefix")
                from jackify.shared.errors import prefix_creation_failed
                raise prefix_creation_failed("create_prefix_with_proton_wrapper returned failure")
            
            logger.info("Step 3 completed: Proton prefix created")
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Proton prefix created successfully")
            
            # Step 4: Verify everything persists
            logger.info("Step 4: Verifying compatibility tool persists")
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Verifying setup...")
            
            if not self.verify_compatibility_tool_persists(appid):
                logger.warning("Compatibility tool verification failed, but continuing")
            
            logger.info("Step 4 completed: Verification done")
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Setup verification completed")
            
            # Get the prefix path
            prefix_path = self.get_prefix_path(appid)
            
            last_timestamp = self._get_progress_timestamp()
            logger.info(f" Workflow completed successfully after conflict resolution! AppID: {appid}, Prefix: {prefix_path}")
            if progress_callback:
                progress_callback(f"{last_timestamp} Automated Steam setup completed successfully!")
            
            return True, prefix_path, appid, last_timestamp
            
        except Exception as e:
            logger.error(f"Error continuing workflow after conflict resolution: {e}")
            if progress_callback:
                progress_callback(f"Error: {str(e)}")
            return False, None, None, None
