"""CLI configuration phase orchestration for ModlistInstallCLI (Mixin).

Runs the install engine, then Steam shortcut/prefix setup, then post-configuration
automation - each phase lives in its own mixin (see modlist_operations_engine_cli.py
and modlist_operations_post_install_cli.py); this file just sequences them.
"""
import logging
import os
import time
from pathlib import Path

from jackify.shared.colors import (
    COLOR_PROMPT,
    COLOR_RESET,
    COLOR_INFO,
    COLOR_WARNING,
)

logger = logging.getLogger(__name__)


class ModlistOperationsConfigurationCLIMixin:
    """Mixin providing the CLI configuration phase orchestrator."""

    def configuration_phase(self, gui_mode: bool = False):
        """
        Run the configuration phase: execute the active install engine, then Steam
        setup and post-install automation for supported games.
        """
        print(f"\n{COLOR_PROMPT}--- Configuration Phase: Installing Modlist ---{COLOR_RESET}")
        start_time = time.time()

        engine_result = self._run_install_engine(gui_mode)
        if engine_result is None:
            return
        install_dir_str, download_dir_str = engine_result

        elapsed = int(time.time() - start_time)
        self._finalize_successful_install(install_dir_str, download_dir_str, elapsed)

        self.logger.debug("configuration_phase: Starting post-install game detection...")

        modorganizer_ini = os.path.join(install_dir_str, "ModOrganizer.ini")
        detected_game = None
        self.logger.debug(f"configuration_phase: Looking for ModOrganizer.ini at: {modorganizer_ini}")
        if os.path.isfile(modorganizer_ini):
            self.logger.debug("configuration_phase: Found ModOrganizer.ini, detecting game...")
            from ..handlers.modlist_handler import ModlistHandler
            handler = ModlistHandler({}, steamdeck=self.steamdeck)
            handler.modlist_ini = modorganizer_ini
            handler.modlist_dir = install_dir_str
            if handler._detect_game_variables():
                detected_game = handler.game_var_full
                self.context['detected_game'] = detected_game
                self.logger.debug(f"configuration_phase: Detected game: {detected_game}")
            else:
                self.logger.debug("configuration_phase: Failed to detect game variables")
        else:
            self.logger.debug("configuration_phase: ModOrganizer.ini not found")

        supported_games = ["Skyrim Special Edition", "Fallout 4", "Fallout New Vegas", "Oblivion", "Starfield", "Oblivion Remastered", "Enderal"]
        is_tuxborn = self.context.get('machineid') == 'Tuxborn/Tuxborn'
        self.logger.debug(f"configuration_phase: detected_game='{detected_game}', is_tuxborn={is_tuxborn}")
        self.logger.debug(f"configuration_phase: Checking condition: (detected_game in supported_games) or is_tuxborn")
        self.logger.debug(f"configuration_phase: Result: {(detected_game in supported_games) or is_tuxborn}")

        if (detected_game in supported_games) or is_tuxborn:
            steam_result = self._run_steam_configuration(install_dir_str, is_tuxborn, gui_mode)
            if steam_result is None:
                return
            shortcut_name, app_id, mo2_exe_path, progress_callback = steam_result

            from jackify.backend.services.modlist_service import ModlistService
            from jackify.backend.models.modlist import ModlistContext

            modlist_context = ModlistContext(
                name=shortcut_name,
                install_dir=Path(install_dir_str),
                download_dir=Path(download_dir_str),
                game_type=detected_game or self.context.get('game_type') or 'Unknown',
                nexus_api_key='',
                modlist_value=self.context.get('modlist_value', ''),
                modlist_source=self.context.get('modlist_source', 'identifier'),
                resolution=self.context.get('resolution'),
                mo2_exe_path=Path(mo2_exe_path),
                skip_confirmation=True,
                engine_installed=True
            )

            modlist_context.app_id = app_id

            modlist_service = ModlistService(self.system_info)

            if progress_callback:
                progress_callback("")
                progress_callback("=== Configuration Phase ===")

                print(f"\n{COLOR_INFO}=== Configuration Phase ==={COLOR_RESET}")
                self.logger.info("Running post-installation configuration phase using ModlistService")

            configuration_success = modlist_service.configure_modlist_post_steam(modlist_context)

            if configuration_success:
                self._run_post_configuration_automation(
                    install_dir_str, shortcut_name, app_id, detected_game, modlist_context,
                )
            else:
                print(f"{COLOR_WARNING}Configuration had some issues but completed.{COLOR_RESET}")
                self.logger.warning("Post-installation configuration had issues")
        else:
            print(f"{COLOR_INFO}Modlist installation complete.{COLOR_RESET}")
            if detected_game:
                print(f"{COLOR_WARNING}Detected game '{detected_game}' is not supported for automated Steam configuration.{COLOR_RESET}")
            else:
                print(f"{COLOR_WARNING}Could not detect game type from ModOrganizer.ini for automated configuration.{COLOR_RESET}")
            print(f"{COLOR_INFO}You may need to manually configure the modlist for Steam/Proton.{COLOR_RESET}")
