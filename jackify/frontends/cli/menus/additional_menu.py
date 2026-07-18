"""
Additional Tasks Menu Handler for Jackify CLI Frontend
Extracted from src.modules.menu_handler.MenuHandler.show_additional_tasks_menu()
"""

import time

from jackify.shared.colors import (
    COLOR_SELECTION, COLOR_RESET, COLOR_ACTION, COLOR_PROMPT, COLOR_INFO, COLOR_DISABLED, COLOR_WARNING
)
from jackify.shared.ui_utils import print_jackify_banner, print_section_header, clear_screen

class AdditionalMenuHandler:
    """
    Handles the Additional Tasks menu (MO2, NXM Handling & Recovery)
    Extracted from legacy MenuHandler class
    """
    
    def __init__(self):
        self.logger = None  # Will be set by CLI when needed
    
    def _clear_screen(self):
        """Clear the terminal screen with AppImage compatibility"""
        clear_screen()
    
    def show_additional_tasks_menu(self, cli_instance):
        """Show the Additional Tasks & Tools submenu"""
        while True:
            self._clear_screen()
            print_jackify_banner()
            print_section_header("Additional Tasks & Tools")
            print(f"{COLOR_INFO}Modlist tools, diagnostics, and more{COLOR_RESET}\n")

            print(f"{COLOR_SELECTION}1.{COLOR_RESET} Run Install Verifier")
            print(f"   {COLOR_ACTION}→ Check an installed modlist for common configuration problems{COLOR_RESET}")
            print(f"{COLOR_SELECTION}2.{COLOR_RESET} Configure Tool Compatibility")
            print(f"   {COLOR_ACTION}→ Apply Wine registry settings for xEdit, Synthesis, Pandora, Nemesis{COLOR_RESET}")
            print(f"{COLOR_SELECTION}3.{COLOR_RESET} Setup Mod Organizer 2")
            print(f"   {COLOR_ACTION}→ Download and configure a standalone MO2 instance{COLOR_RESET}")
            print(f"{COLOR_SELECTION}4.{COLOR_RESET} Install Wabbajack Application")
            print(f"   {COLOR_ACTION}→ Download the Wabbajack app under Proton - not needed for standard modlist installs{COLOR_RESET}")
            print(f"{COLOR_SELECTION}5.{COLOR_RESET} Create Diagnostic Bundle")
            print(f"   {COLOR_ACTION}→ Package logs and system info for support{COLOR_RESET}")
            print(f"{COLOR_SELECTION}6.{COLOR_RESET} Nexus Mods Authorization")
            print(f"   {COLOR_ACTION}→ Authorise with Nexus using OAuth or manage API key{COLOR_RESET}")
            print(f"{COLOR_SELECTION}0.{COLOR_RESET} Return to Main Menu")
            selection = input(f"\n{COLOR_PROMPT}Enter your selection (0-6): {COLOR_RESET}").strip()

            if selection.lower() == 'q':  # Allow 'q' to re-display menu
                continue
            if selection == "1":
                self._execute_run_verifier()
            elif selection == "2":
                self._execute_configure_tool_compat(cli_instance)
            elif selection == "3":
                self._execute_setup_mo2(cli_instance)
            elif selection == "4":
                self._execute_install_wabbajack(cli_instance)
            elif selection == "5":
                self._execute_diagnostic_bundle()
            elif selection == "6":
                self._execute_nexus_authorization(cli_instance)
            elif selection == "0":
                break
            else:
                print("Invalid selection. Please try again.")
                time.sleep(1)

    def _execute_legacy_recovery_menu(self, cli_instance):
        """LEGACY BRIDGE: Execute recovery menu"""
        # Handled by RecoveryMenuHandler
        from .recovery_menu import RecoveryMenuHandler
        
        recovery_handler = RecoveryMenuHandler()
        recovery_handler.logger = self.logger
        recovery_handler.show_recovery_menu(cli_instance)

    def _execute_ttw_install(self, cli_instance):
        """Execute TTW installation using TTW_Linux_Installer handler"""
        from ....backend.handlers.ttw_installer_handler import TTWInstallerHandler
        from ....backend.models.configuration import SystemInfo
        from ....shared.colors import COLOR_ERROR, COLOR_WARNING, COLOR_SUCCESS, COLOR_INFO, COLOR_PROMPT
        from pathlib import Path

        system_info = SystemInfo(is_steamdeck=cli_instance.system_info.is_steamdeck)
        ttw_installer_handler = TTWInstallerHandler(
            steamdeck=system_info.is_steamdeck,
            verbose=cli_instance.verbose,
            filesystem_handler=cli_instance.filesystem_handler,
            config_handler=cli_instance.config_handler
        )

        # First check if TTW_Linux_Installer is installed
        if not ttw_installer_handler.ttw_installer_installed:
            print(f"\n{COLOR_WARNING}TTW_Linux_Installer is not installed. Installing TTW_Linux_Installer first...{COLOR_RESET}")
            success, message = ttw_installer_handler.install_ttw_installer()
            if not success:
                print(f"{COLOR_ERROR}Failed to install TTW_Linux_Installer. Cannot proceed with TTW installation.{COLOR_RESET}")
                print(f"{COLOR_ERROR}Error: {message}{COLOR_RESET}")
                input("Press Enter to return to menu...")
                return

        # Check for required games
        detected_games = ttw_installer_handler.path_handler.find_vanilla_game_paths()
        required_games = ['Fallout 3', 'Fallout New Vegas']
        missing_games = [game for game in required_games if game not in detected_games]
        if missing_games:
            print(f"\n{COLOR_ERROR}Missing required games: {', '.join(missing_games)}")
            print(f"TTW requires both Fallout 3 and Fallout New Vegas to be installed.{COLOR_RESET}")
            input("Press Enter to return to menu...")
            return

        # Prompt for TTW .mpi file with tab completion
        try:
            import readline
            from ....backend.handlers.completers import path_completer
            READLINE_AVAILABLE = True
        except ImportError:
            READLINE_AVAILABLE = False
        
        print(f"\n{COLOR_PROMPT}TTW Installer File (.mpi){COLOR_RESET}")
        if READLINE_AVAILABLE:
            readline.set_completer_delims(' \t\n;')
            readline.set_completer(path_completer)
            readline.parse_and_bind("tab: complete")
        try:
            mpi_path = input(f"{COLOR_PROMPT}Path to TTW .mpi file: {COLOR_RESET}").strip()
        finally:
            if READLINE_AVAILABLE:
                readline.set_completer(None)
        
        if not mpi_path:
            print(f"{COLOR_WARNING}No .mpi file specified. Cancelling.{COLOR_RESET}")
            input("Press Enter to return to menu...")
            return

        mpi_path = Path(mpi_path).expanduser()
        if not mpi_path.exists() or not mpi_path.is_file():
            print(f"{COLOR_ERROR}TTW .mpi file not found: {mpi_path}{COLOR_RESET}")
            input("Press Enter to return to menu...")
            return

        # Prompt for output directory with tab completion
        print(f"\n{COLOR_PROMPT}TTW Installation Directory{COLOR_RESET}")
        default_output = Path.home() / "ModdedGames" / "TTW"
        if READLINE_AVAILABLE:
            readline.set_completer_delims(' \t\n;')
            readline.set_completer(path_completer)
            readline.parse_and_bind("tab: complete")
        try:
            output_path = input(f"{COLOR_PROMPT}TTW install directory (Enter for default: {default_output}): {COLOR_RESET}").strip()
        finally:
            if READLINE_AVAILABLE:
                readline.set_completer(None)
        
        if not output_path:
            output_path = default_output
        else:
            output_path = Path(output_path).expanduser()

        # Check if output directory already has content - mirror GUI behaviour
        if output_path.exists() and output_path.is_dir():
            try:
                has_files = any(output_path.iterdir())
            except Exception:
                has_files = False
            if has_files:
                print(f"\n{COLOR_WARNING}The TTW output directory already exists and contains files:{COLOR_RESET}")
                print(f"  {output_path}")
                print(f"{COLOR_WARNING}All files in this directory will be deleted before installation.{COLOR_RESET}")
                print(f"{COLOR_WARNING}This action cannot be undone.{COLOR_RESET}")
                confirm = input(f"{COLOR_PROMPT}Delete existing files and continue? (y/N): {COLOR_RESET}").strip().lower()
                if confirm not in ('y', 'yes'):
                    print(f"{COLOR_INFO}TTW installation cancelled.{COLOR_RESET}")
                    input("Press Enter to return to menu...")
                    return
                import shutil
                try:
                    for item in output_path.iterdir():
                        if item.is_dir():
                            shutil.rmtree(item)
                        else:
                            item.unlink()
                except Exception as e:
                    print(f"{COLOR_ERROR}Failed to clear output directory: {e}{COLOR_RESET}")
                    input("Press Enter to return to menu...")
                    return

        # Run TTW installation
        import re

        phase_state = {"current": "Processing", "last_rendered": ""}
        progress_line_active = {"value": False}

        def _strip_ansi(text: str) -> str:
            return re.sub(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])', '', text or '')

        def _ttw_output_callback(line: str):
            clean = _strip_ansi(line or "").strip()
            if not clean:
                return
            lower = clean.lower()
            rendered = ""
            progress_match = re.search(r'progress:\s*(\d+)%', lower)
            if progress_match:
                percent = int(progress_match.group(1))
                rendered = f"[TTW] {phase_state['current']}: {percent}%"
            else:
                if 'manifest' in lower:
                    phase_state["current"] = "Loading manifest"
                elif any(t in lower for t in ('extract', 'decompress', 'installing', 'copying', 'merge')):
                    phase_state["current"] = clean
                is_milestone = any(t in lower for t in ('===', 'complete', 'finished', 'starting', 'valid'))
                is_error = 'error:' in lower
                is_warning = 'warning:' in lower
                if is_milestone or is_error or is_warning:
                    rendered = f"[TTW] {clean}"

            if not rendered or rendered == phase_state["last_rendered"]:
                return
            phase_state["last_rendered"] = rendered
            if re.search(r'^\[TTW\] .+?: \d+%$', rendered):
                print(f"\r{COLOR_INFO}{rendered}{COLOR_RESET}", end="", flush=True)
                progress_line_active["value"] = True
            else:
                if progress_line_active["value"]:
                    print()
                    progress_line_active["value"] = False
                print(f"{COLOR_INFO}{rendered}{COLOR_RESET}")

        print(f"\n{COLOR_INFO}Starting TTW installation workflow...{COLOR_RESET}")
        print(f"{COLOR_INFO}This may take 15-30 minutes.{COLOR_RESET}\n")
        success, message = ttw_installer_handler.install_ttw_backend_with_output_stream(
            mpi_path, output_path, output_callback=_ttw_output_callback
        )
        if progress_line_active["value"]:
            print()

        if success:
            print(f"\n{COLOR_SUCCESS}TTW installation completed successfully!{COLOR_RESET}")
            print(f"{COLOR_INFO}TTW installed to: {output_path}{COLOR_RESET}")
            print(f"{COLOR_INFO}Detailed log available at: ~/Jackify/logs/TTW_Install_workflow.log{COLOR_RESET}")
            input("Press Enter to return to menu...")
        else:
            print(f"\n{COLOR_ERROR}TTW installation failed.{COLOR_RESET}")
            print(f"{COLOR_ERROR}Error: {message}{COLOR_RESET}")
            print(f"{COLOR_INFO}Detailed log available at: ~/Jackify/logs/TTW_Install_workflow.log{COLOR_RESET}")
            input("Press Enter to return to menu...")

    def _execute_nexus_authorization(self, cli_instance):
        """Execute Nexus authorization menu (OAuth or API key)"""
        from ....backend.services.nexus_auth_service import NexusAuthService
        from ....backend.services.api_key_service import APIKeyService
        from ....shared.colors import COLOR_ERROR, COLOR_SUCCESS

        auth_service = NexusAuthService()

        while True:
            self._clear_screen()
            print_jackify_banner()
            print_section_header("Nexus Mods Authorization")

            # Get current auth status
            authenticated, method, username = auth_service.get_auth_status()

            if authenticated:
                if method == 'oauth':
                    print(f"\n{COLOR_SUCCESS}Status: Authorised via OAuth{COLOR_RESET}")
                    if username:
                        print(f"{COLOR_INFO}Logged in as: {username}{COLOR_RESET}")
                elif method == 'api_key':
                    print(f"\n{COLOR_WARNING}Status: Using API Key (Legacy){COLOR_RESET}")
                    print(f"{COLOR_INFO}Consider switching to OAuth for better security{COLOR_RESET}")
            else:
                print(f"\n{COLOR_WARNING}Status: Not Authorised{COLOR_RESET}")
                print(f"{COLOR_INFO}You need to authorize to download mods from Nexus{COLOR_RESET}")

            print(f"\n{COLOR_SELECTION}1.{COLOR_RESET} Authorise with Nexus (OAuth)")
            print(f"   {COLOR_ACTION}→ Opens browser for secure authorization{COLOR_RESET}")

            if method == 'oauth':
                print(f"{COLOR_SELECTION}2.{COLOR_RESET} Revoke OAuth Authorization")
                print(f"   {COLOR_ACTION}→ Remove OAuth token{COLOR_RESET}")

            print(f"{COLOR_SELECTION}3.{COLOR_RESET} Set API Key (Legacy Fallback)")
            print(f"   {COLOR_ACTION}→ Manually enter Nexus API key{COLOR_RESET}")

            if authenticated:
                print(f"{COLOR_SELECTION}4.{COLOR_RESET} Clear All Authentication")
                print(f"   {COLOR_ACTION}→ Remove both OAuth and API key{COLOR_RESET}")

            print(f"{COLOR_SELECTION}0.{COLOR_RESET} Return to Additional Tasks Menu")

            selection = input(f"\n{COLOR_PROMPT}Enter your selection: {COLOR_RESET}").strip()

            if selection == "1":
                # OAuth authorization
                print(f"\n{COLOR_INFO}Starting OAuth authorization...{COLOR_RESET}")
                print(f"{COLOR_WARNING}Your browser will open shortly.{COLOR_RESET}")
                print(f"{COLOR_WARNING}Please check your browser and authorize Jackify.{COLOR_RESET}")
                print(f"\n{COLOR_INFO}Note: Your browser may ask permission to open 'xdg-open' or{COLOR_RESET}")
                print(f"{COLOR_INFO}Jackify's protocol handler - please click 'Open' or 'Allow'.{COLOR_RESET}")

                input(f"\n{COLOR_PROMPT}Press Enter to open browser...{COLOR_RESET}")

                # Perform OAuth authorization
                def show_message(msg):
                    print(f"\n{COLOR_INFO}{msg}{COLOR_RESET}")

                success = auth_service.authorize_oauth(show_browser_message_callback=show_message)

                if success:
                    print(f"\n{COLOR_SUCCESS}OAuth authorization successful!{COLOR_RESET}")
                    # Get username
                    _, _, username = auth_service.get_auth_status()
                    if username:
                        print(f"{COLOR_INFO}Authorised as: {username}{COLOR_RESET}")
                else:
                    print(f"\n{COLOR_ERROR}OAuth authorization failed.{COLOR_RESET}")
                    print(f"{COLOR_INFO}You can try again or use API key as fallback.{COLOR_RESET}")

                input(f"\n{COLOR_PROMPT}Press Enter to continue...{COLOR_RESET}")

            elif selection == "2" and method == 'oauth':
                # Revoke OAuth
                print(f"\n{COLOR_WARNING}Are you sure you want to revoke OAuth authorization?{COLOR_RESET}")
                confirm = input(f"{COLOR_PROMPT}Type 'yes' to confirm: {COLOR_RESET}").strip().lower()

                if confirm == 'yes':
                    if auth_service.revoke_oauth():
                        print(f"\n{COLOR_SUCCESS}OAuth authorization revoked.{COLOR_RESET}")
                    else:
                        print(f"\n{COLOR_ERROR}Failed to revoke OAuth authorization.{COLOR_RESET}")
                else:
                    print(f"\n{COLOR_INFO}Cancelled.{COLOR_RESET}")

                input(f"\n{COLOR_PROMPT}Press Enter to continue...{COLOR_RESET}")

            elif selection == "3":
                # Set API key
                print(f"\n{COLOR_INFO}Enter your Nexus API Key{COLOR_RESET}")
                print(f"{COLOR_INFO}(Get it from: https://www.nexusmods.com/users/myaccount?tab=api){COLOR_RESET}")

                api_key = input(f"\n{COLOR_PROMPT}API Key: {COLOR_RESET}").strip()

                if api_key:
                    if auth_service.save_api_key(api_key):
                        print(f"\n{COLOR_SUCCESS}API key saved successfully.{COLOR_RESET}")

                        # Optionally validate
                        print(f"\n{COLOR_INFO}Validating API key...{COLOR_RESET}")
                        valid, result = auth_service.validate_api_key(api_key)

                        if valid:
                            print(f"{COLOR_SUCCESS}API key validated successfully!{COLOR_RESET}")
                            print(f"{COLOR_INFO}Username: {result}{COLOR_RESET}")
                        else:
                            print(f"{COLOR_WARNING}Warning: API key validation failed: {result}{COLOR_RESET}")
                            print(f"{COLOR_INFO}Key saved, but may not work correctly.{COLOR_RESET}")
                    else:
                        print(f"\n{COLOR_ERROR}Failed to save API key.{COLOR_RESET}")
                else:
                    print(f"\n{COLOR_INFO}Cancelled.{COLOR_RESET}")

                input(f"\n{COLOR_PROMPT}Press Enter to continue...{COLOR_RESET}")

            elif selection == "4" and authenticated:
                # Clear all authentication
                print(f"\n{COLOR_WARNING}Are you sure you want to clear ALL authentication?{COLOR_RESET}")
                print(f"{COLOR_WARNING}This will remove both OAuth token and API key.{COLOR_RESET}")
                confirm = input(f"{COLOR_PROMPT}Type 'yes' to confirm: {COLOR_RESET}").strip().lower()

                if confirm == 'yes':
                    if auth_service.clear_all_auth():
                        print(f"\n{COLOR_SUCCESS}All authentication cleared.{COLOR_RESET}")
                    else:
                        print(f"\n{COLOR_INFO}No authentication to clear.{COLOR_RESET}")
                else:
                    print(f"\n{COLOR_INFO}Cancelled.{COLOR_RESET}")

                input(f"\n{COLOR_PROMPT}Press Enter to continue...{COLOR_RESET}")

            elif selection == "0":
                break
            else:
                print(f"\n{COLOR_ERROR}Invalid selection.{COLOR_RESET}")
                time.sleep(1)

    def _execute_install_wabbajack(self, cli_instance):
        """Execute Wabbajack application installation"""
        from jackify.frontends.cli.commands.install_wabbajack import InstallWabbajackCommand

        command = InstallWabbajackCommand()
        if self.logger:
            self.logger.debug("AdditionalMenuHandler: Executing Install Wabbajack command")
        command.run()

    def _execute_setup_mo2(self, cli_instance):
        """Execute standalone MO2 setup"""
        from jackify.frontends.cli.commands.setup_mo2 import SetupMO2Command

        command = SetupMO2Command()
        if self.logger:
            self.logger.debug("AdditionalMenuHandler: Executing Setup MO2 command")
        command.run()

    def _execute_configure_tool_compat(self, cli_instance):
        """Apply tool compatibility settings to an existing configured modlist prefix."""
        from jackify.backend.handlers.modlist_handler import ModlistHandler
        from jackify.backend.services.tool_config_service import apply_tool_config_for_appid
        from jackify.shared.colors import COLOR_ERROR, COLOR_SUCCESS

        self._clear_screen()
        print_jackify_banner()
        print_section_header("Configure Tool Compatibility")
        print(f"{COLOR_INFO}Discovering configured modlists...{COLOR_RESET}")

        try:
            handler = ModlistHandler()
            discovered = handler.discover_executable_shortcuts("ModOrganizer.exe")
            shortcuts = [
                {"name": m.get("name", "Unknown"), "appid": str(m.get("appid", ""))}
                for m in discovered
                if m.get("appid")
            ]
        except Exception as e:
            print(f"{COLOR_ERROR}Failed to discover modlists: {e}{COLOR_RESET}")
            input("Press Enter to return to menu...")
            return

        if not shortcuts:
            print(f"{COLOR_WARNING}No configured modlists found.{COLOR_RESET}")
            print(f"{COLOR_INFO}Install and configure a modlist first.{COLOR_RESET}")
            input("Press Enter to return to menu...")
            return

        print()
        for i, s in enumerate(shortcuts, 1):
            print(f"{COLOR_SELECTION}{i}.{COLOR_RESET} {s['name']}")
        print(f"{COLOR_SELECTION}0.{COLOR_RESET} Cancel")

        selection = input(f"\n{COLOR_PROMPT}Select modlist (0-{len(shortcuts)}): {COLOR_RESET}").strip()

        if selection == "0" or not selection:
            return

        try:
            idx = int(selection) - 1
            if idx < 0 or idx >= len(shortcuts):
                raise ValueError()
        except ValueError:
            print(f"{COLOR_ERROR}Invalid selection.{COLOR_RESET}")
            input("Press Enter to return to menu...")
            return

        chosen = shortcuts[idx]
        print(f"\n{COLOR_INFO}Applying tool compatibility settings for: {chosen['name']}{COLOR_RESET}")
        print(f"{COLOR_INFO}This may take a few minutes...{COLOR_RESET}\n")

        def _log(msg: str):
            print(f"{COLOR_INFO}{msg}{COLOR_RESET}")

        ok = apply_tool_config_for_appid(chosen["appid"], log=_log)

        if ok:
            print(f"\n{COLOR_SUCCESS}Tool compatibility configured successfully.{COLOR_RESET}")
        else:
            print(f"\n{COLOR_ERROR}Tool compatibility configuration failed. Check logs for details.{COLOR_RESET}")

        input("\nPress Enter to return to menu...")

    def _execute_diagnostic_bundle(self) -> None:
        from jackify.backend.services.diagnostic_service import build_bundle
        from jackify.shared.colors import COLOR_ERROR, COLOR_SUCCESS

        self._clear_screen()
        print_jackify_banner()
        print_section_header("Create Diagnostic Bundle")
        print(f"{COLOR_INFO}Collecting logs, system info, and prefix records...{COLOR_RESET}\n")

        try:
            bundle_path = build_bundle()
        except Exception as exc:
            print(f"{COLOR_ERROR}Failed to create bundle: {exc}{COLOR_RESET}")
            input("Press Enter to return to menu...")
            return

        print(f"{COLOR_SUCCESS}Bundle created:{COLOR_RESET} {bundle_path}")
        print(f"\n{COLOR_INFO}Attach this file when reporting an issue.{COLOR_RESET}")

        input("\nPress Enter to return to menu...")

    def _execute_run_verifier(self) -> None:
        from jackify.backend.services.install_verifier_service import (
            _load_verifier, run_install_verification, resolve_pfx_for_appid,
        )
        from jackify.shared.colors import COLOR_ERROR, COLOR_SUCCESS, COLOR_WARNING
        import threading

        self._clear_screen()
        print_jackify_banner()
        print_section_header("Run Install Verifier")
        print(f"{COLOR_INFO}Discovering configured modlists...{COLOR_RESET}")

        try:
            vmod = _load_verifier()
            modlists = vmod.discover_installed_modlists()
        except Exception as e:
            print(f"{COLOR_ERROR}Failed to discover modlists: {e}{COLOR_RESET}")
            input("Press Enter to return to menu...")
            return

        if not modlists:
            print(f"{COLOR_WARNING}No configured modlists found.{COLOR_RESET}")
            print(f"{COLOR_INFO}Install and configure a modlist first.{COLOR_RESET}")
            input("Press Enter to return to menu...")
            return

        print()
        for i, m in enumerate(modlists, 1):
            print(f"{COLOR_SELECTION}{i}.{COLOR_RESET} {m.get('name', 'Unknown')}")
        print(f"{COLOR_SELECTION}0.{COLOR_RESET} Cancel")

        selection = input(f"\n{COLOR_PROMPT}Select modlist (0-{len(modlists)}): {COLOR_RESET}").strip()

        if selection == "0" or not selection:
            return

        try:
            idx = int(selection) - 1
            if idx < 0 or idx >= len(modlists):
                raise ValueError()
        except ValueError:
            print(f"{COLOR_ERROR}Invalid selection.{COLOR_RESET}")
            input("Press Enter to return to menu...")
            return

        chosen = modlists[idx]
        appid = chosen.get("appid", "")
        modlist_dir = chosen.get("modlist_dir")
        game_type = chosen.get("game_type", "unknown")
        name = chosen.get("name", "Unknown")

        pfx = resolve_pfx_for_appid(appid) if appid else None
        if not pfx or not pfx.is_dir():
            print(f"{COLOR_WARNING}No Wine prefix found for {name}. Cannot run verifier.{COLOR_RESET}")
            input("Press Enter to return to menu...")
            return

        print(f"\n{COLOR_INFO}Running install verification for: {name}{COLOR_RESET}")
        print(f"{COLOR_INFO}This may take a moment...{COLOR_RESET}\n")

        try:
            result_holder = [None]
            def _worker():
                result_holder[0] = run_install_verification(pfx, modlist_dir, game_type, appid, name)
            t = threading.Thread(target=_worker, daemon=True)
            t.start()
            t.join()
            r = result_holder[0]
            if r is None:
                print(f"{COLOR_WARNING}Verifier returned no results.{COLOR_RESET}")
            else:
                passes = r.passes if hasattr(r, 'passes') else []
                warnings = r.warnings if hasattr(r, 'warnings') else []
                failures = r.failures if hasattr(r, 'failures') else []
                total = len(passes) + len(warnings) + len(failures)
                print(f"--- Install Verification: {name} ---")
                print(f"  {len(passes)} passed, {len(warnings)} warnings, {len(failures)} failed (of {total} checks)\n")
                for msg in failures:
                    print(f"{COLOR_ERROR}  [FAIL] {msg}{COLOR_RESET}")
                for msg in warnings:
                    print(f"{COLOR_WARNING}  [WARN] {msg}{COLOR_RESET}")
                if not failures and not warnings:
                    print(f"{COLOR_SUCCESS}  All checks passed.{COLOR_RESET}")
                if passes:
                    show_all = input(f"\n{COLOR_PROMPT}Show all {len(passes)} passed checks? (y/N): {COLOR_RESET}").strip().lower()
                    if show_all in ('y', 'yes'):
                        print()
                        for msg in passes:
                            print(f"{COLOR_DISABLED}  [OK]  {msg}{COLOR_RESET}")
        except Exception as e:
            print(f"{COLOR_ERROR}Verifier error: {e}{COLOR_RESET}")

        input("\nPress Enter to return to menu...")

    def _execute_tools_hub(self, cli_instance) -> None:
        from jackify.frontends.cli.menus.tools_hub_menu import ToolsHubMenuHandler
        ToolsHubMenuHandler().show_tools_hub_menu(cli_instance)
