"""TTW integration methods for ModlistInstallCLI (Mixin)."""
import logging
import os
import re
import signal
import shutil
from pathlib import Path

from jackify.shared.colors import COLOR_PROMPT, COLOR_INFO, COLOR_ERROR, COLOR_RESET, COLOR_WARNING
from jackify.shared.paths import get_jackify_logs_dir

logger = logging.getLogger(__name__)


def _strip_ansi_control_codes(text: str) -> str:
    """Strip ANSI escape/control sequences from CLI output lines."""
    return re.sub(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])', '', text or '')


def prompt_ttw_if_eligible(install_dir: str, modlist_name: str) -> None:
    """Standalone TTW prompt usable outside the mixin context (e.g. CLI configure command).

    Detects game type from ModOrganizer.ini, resolves the best available modlist name,
    checks whitelist eligibility, and runs the interactive TTW prompt if applicable.
    """
    try:
        # Detect game type from ModOrganizer.ini
        mo2_ini = Path(install_dir) / "ModOrganizer.ini"
        game_type = "skyrim"
        if mo2_ini.exists():
            content = mo2_ini.read_text(encoding="utf-8", errors="ignore").lower()
            if "nvse_loader.exe" in content or "fallout new vegas" in content:
                game_type = "falloutnv"
            elif "fose_loader.exe" in content or "fallout 3" in content:
                game_type = "fallout3"

        if game_type not in ("falloutnv", "fallout_new_vegas"):
            return

        # Best available name: meta file, then selected_profile, then caller-supplied name
        from jackify.backend.utils.modlist_meta import get_modlist_name
        identified_name = get_modlist_name(install_dir) or modlist_name
        if not identified_name:
            return

        class _Adapter(ModlistInstallCLITTWMixin):
            def __init__(self):
                self.logger = logging.getLogger(__name__)
                self.verbose = False
                self.filesystem_handler = None
                self.config_handler = None

        _Adapter()._check_and_prompt_ttw_integration(install_dir, game_type, identified_name)
    except Exception as e:
        logger.error("TTW post-configure check failed: %s", e, exc_info=True)


class ModlistInstallCLITTWMixin:
    """Mixin providing TTW integration methods."""

    def _check_and_prompt_ttw_integration(self, install_dir: str, game_type: str, modlist_name: str):
        """Check if modlist is eligible for TTW integration and prompt user"""
        try:
            # Check eligibility: FNV game, TTW-compatible modlist, no existing TTW
            if not self._is_ttw_eligible(install_dir, game_type, modlist_name):
                return

            # Prompt user for TTW installation
            print(f"\n{COLOR_PROMPT}═══════════════════════════════════════════════════════════════{COLOR_RESET}")
            print(f"{COLOR_INFO}TTW Integration Available{COLOR_RESET}")
            print(f"{COLOR_PROMPT}═══════════════════════════════════════════════════════════════{COLOR_RESET}")
            print(f"\nThis modlist ({modlist_name}) requires Tale of Two Wastelands (TTW).")
            print(f"TTW combines Fallout 3 and New Vegas into a single game.")
            print(f"\nWould you like to install TTW now?")

            # Some CLI entrypoint signal handlers currently call sys.exit(), which can interrupt
            # this prompt unexpectedly. Temporarily convert SIGINT/SIGTERM to KeyboardInterrupt
            # and keep prompting so users can answer explicitly.
            original_sigint = signal.getsignal(signal.SIGINT)
            original_sigterm = signal.getsignal(signal.SIGTERM)

            def _prompt_signal_handler(signum, frame):
                raise KeyboardInterrupt

            try:
                signal.signal(signal.SIGINT, _prompt_signal_handler)
                signal.signal(signal.SIGTERM, _prompt_signal_handler)

                while True:
                    try:
                        user_input = input(f"{COLOR_PROMPT}Install TTW now? (Y/n): {COLOR_RESET}").strip().lower()
                    except KeyboardInterrupt:
                        print(f"\n{COLOR_WARNING}TTW prompt interrupted. Please type yes or no.{COLOR_RESET}")
                        continue
                    except EOFError:
                        print(f"\n{COLOR_WARNING}No input available. Skipping TTW installation.{COLOR_RESET}")
                        return

                    if user_input == "":
                        user_input = "y"
                    if user_input in ['yes', 'y', 'no', 'n']:
                        break

                    print(f"{COLOR_WARNING}Please answer yes or no.{COLOR_RESET}")
            finally:
                signal.signal(signal.SIGINT, original_sigint)
                signal.signal(signal.SIGTERM, original_sigterm)

            if user_input in ['yes', 'y']:
                self._launch_ttw_installation(modlist_name, install_dir)
            else:
                print(f"{COLOR_INFO}Skipping TTW installation. You can install it later from the main menu.{COLOR_RESET}")

        except Exception as e:
            self.logger.error(f"Error during TTW eligibility check: {e}", exc_info=True)

    def _is_ttw_eligible(self, install_dir: str, game_type: str, modlist_name: str) -> bool:
        """Check if modlist is eligible for TTW integration"""
        try:
            from pathlib import Path

            # Check 1: Must be Fallout New Vegas
            if not game_type or game_type.lower() not in ['falloutnv', 'fallout new vegas', 'fallout_new_vegas']:
                return False

            # Check 2: Must be eligible per a matching playbook's offer_tool_flow step
            from jackify.backend.services.playbook.hook_wiring import modlist_offers_tool_flow
            if not modlist_offers_tool_flow(install_dir, modlist_name, "ttw_install"):
                return False

            # Check 3: TTW must not already be installed
            if self._detect_existing_ttw(install_dir):
                self.logger.info(f"TTW already installed in {install_dir}, skipping prompt")
                return False

            return True

        except Exception as e:
            self.logger.error(f"Error checking TTW eligibility: {e}")
            return False

    def _detect_existing_ttw(self, install_dir: str) -> bool:
        """Detect if TTW is already installed in the modlist"""
        try:
            from pathlib import Path

            install_path = Path(install_dir)

            # Search for TTW indicators in common locations
            search_paths = [
                install_path,
                install_path / "mods",
                install_path / "Stock Game",
                install_path / "Game Root"
            ]

            for search_path in search_paths:
                if not search_path.exists():
                    continue

                # Look for folders containing "tale" and "two" and "wastelands"
                for folder in search_path.iterdir():
                    if not folder.is_dir():
                        continue

                    folder_name_lower = folder.name.lower()
                    if all(keyword in folder_name_lower for keyword in ['tale', 'two', 'wastelands']):
                        # Verify it has the TTW ESM file
                        for file in folder.rglob('*.esm'):
                            if 'taleoftwowastelands' in file.name.lower():
                                self.logger.info(f"Found existing TTW installation: {file}")
                                return True

            return False

        except Exception as e:
            self.logger.error(f"Error detecting existing TTW: {e}")
            return False

    def _launch_ttw_installation(self, modlist_name: str, install_dir: str):
        """Launch TTW installation workflow"""
        try:
            print(f"\n{COLOR_INFO}Starting TTW installation workflow...{COLOR_RESET}")

            # Import TTW installation handler
            from jackify.backend.handlers.ttw_installer_handler import TTWInstallerHandler
            from jackify.backend.handlers.config_handler import ConfigHandler
            from jackify.backend.handlers.filesystem_handler import FileSystemHandler
            from jackify.backend.services.platform_detection_service import PlatformDetectionService
            from pathlib import Path

            is_steamdeck = bool(getattr(self, 'steamdeck', False))
            if not is_steamdeck:
                try:
                    is_steamdeck = PlatformDetectionService.get_instance().is_steamdeck
                except Exception:
                    is_steamdeck = False

            filesystem_handler = getattr(self, 'filesystem_handler', None) or FileSystemHandler()
            config_handler = getattr(self, 'config_handler', None) or ConfigHandler()

            ttw_installer_handler = TTWInstallerHandler(
                steamdeck=is_steamdeck,
                verbose=self.verbose if hasattr(self, 'verbose') else False,
                filesystem_handler=filesystem_handler,
                config_handler=config_handler
            )

            # Check if TTW_Linux_Installer is installed
            ttw_installer_handler._check_installation()

            if not ttw_installer_handler.ttw_installer_installed:
                print(f"{COLOR_INFO}TTW_Linux_Installer is not installed.{COLOR_RESET}")
                user_input = input(f"{COLOR_PROMPT}Install TTW_Linux_Installer? (Y/n): {COLOR_RESET}").strip().lower()
                if user_input == "":
                    user_input = "y"

                if user_input not in ['yes', 'y']:
                    print(f"{COLOR_INFO}TTW installation cancelled.{COLOR_RESET}")
                    return

                # Install TTW_Linux_Installer
                print(f"{COLOR_INFO}Installing TTW_Linux_Installer...{COLOR_RESET}")
                success, message = ttw_installer_handler.install_ttw_installer()

                if not success:
                    print(f"{COLOR_ERROR}Failed to install TTW_Linux_Installer: {message}{COLOR_RESET}")
                    return

                print(f"{COLOR_INFO}TTW_Linux_Installer installed successfully.{COLOR_RESET}")

            # Prompt for TTW .mpi file
            print(f"\n{COLOR_PROMPT}TTW Installer File (.mpi){COLOR_RESET}")
            mpi_path = input(f"{COLOR_PROMPT}Path to TTW .mpi file: {COLOR_RESET}").strip()
            if not mpi_path:
                print(f"{COLOR_WARNING}No .mpi file specified. Cancelling.{COLOR_RESET}")
                return

            mpi_path = Path(mpi_path).expanduser()
            if not mpi_path.exists() or not mpi_path.is_file():
                print(f"{COLOR_ERROR}TTW .mpi file not found: {mpi_path}{COLOR_RESET}")
                return

            # Prompt for TTW installation directory
            print(f"\n{COLOR_PROMPT}TTW Installation Directory{COLOR_RESET}")
            default_ttw_dir = os.path.join(install_dir, 'mods', '[NoDelete] Tale of Two Wastelands')
            print(f"Default: {default_ttw_dir}")
            ttw_install_dir = input(f"{COLOR_PROMPT}TTW install directory (Enter for default): {COLOR_RESET}").strip()

            if not ttw_install_dir:
                ttw_install_dir = default_ttw_dir

            # Run TTW installation
            print(f"\n{COLOR_INFO}Installing TTW using TTW_Linux_Installer...{COLOR_RESET}")
            print(f"{COLOR_INFO}This may take a while (15-30 minutes depending on your system).{COLOR_RESET}")
            phase_state = {"current": "Processing", "last_rendered": ""}
            progress_line_active = {"value": False}

            def _ttw_output_callback(line: str):
                clean = _strip_ansi_control_codes(line or "").strip()
                if not clean:
                    return

                lower = clean.lower()
                rendered = ""

                # Match GUI behavior: explicit Progress: NN% counter line
                progress_match = re.search(r'progress:\s*(\d+)%', lower)
                if progress_match:
                    percent = int(progress_match.group(1))
                    rendered = f"[TTW] {phase_state['current']}: {percent}%"
                else:
                    # Update phase state from milestone-like lines, then echo milestones.
                    if 'manifest' in lower:
                        phase_state["current"] = "Loading manifest"
                    elif any(token in lower for token in ('extract', 'decompress', 'installing', 'copying', 'merge')):
                        phase_state["current"] = clean

                    is_milestone = any(token in lower for token in ('===', 'complete', 'finished', 'starting', 'valid'))
                    is_error = 'error:' in lower
                    is_warning = 'warning:' in lower
                    if is_milestone or is_error or is_warning:
                        rendered = f"[TTW] {clean}"

                if not rendered or rendered == phase_state["last_rendered"]:
                    return
                phase_state["last_rendered"] = rendered
                if re.search(r'^\[TTW\] .+?: \d+%$', rendered):
                    # In-place progress updates for counters/phases.
                    print(f"\r{COLOR_INFO}{rendered}{COLOR_RESET}", end="", flush=True)
                    progress_line_active["value"] = True
                else:
                    # Non-progress milestones/errors get normal line output.
                    if progress_line_active["value"]:
                        print()
                        progress_line_active["value"] = False
                    print(f"{COLOR_INFO}{rendered}{COLOR_RESET}")

            success, message = ttw_installer_handler.install_ttw_backend_with_output_stream(
                Path(mpi_path),
                Path(ttw_install_dir),
                output_callback=_ttw_output_callback,
            )
            if progress_line_active["value"]:
                print()

            if success:
                ttw_output_path = Path(ttw_install_dir)
                ttw_version = ""
                version_match = re.search(r'v?(\d+\.\d+(?:\.\d+)?)', Path(mpi_path).stem, re.IGNORECASE)
                if version_match:
                    ttw_version = version_match.group(1)

                skip_copy = False
                mods_dir = Path(install_dir) / "mods"
                if ttw_output_path.parent == mods_dir:
                    versioned_name = f"[NoDelete] Tale of Two Wastelands {ttw_version}".strip() if ttw_version else "[NoDelete] Tale of Two Wastelands"
                    versioned_path = mods_dir / versioned_name
                    if ttw_output_path != versioned_path and ttw_output_path.exists():
                        if versioned_path.exists():
                            shutil.rmtree(versioned_path)
                        ttw_output_path.rename(versioned_path)
                        ttw_output_path = versioned_path
                    skip_copy = True

                print(f"\n{COLOR_INFO}Integrating TTW into modlist load order...{COLOR_RESET}")
                integration_success = TTWInstallerHandler.integrate_ttw_into_modlist(
                    ttw_output_path=ttw_output_path,
                    modlist_install_dir=Path(install_dir),
                    ttw_version=ttw_version,
                    skip_copy=skip_copy,
                )

                if not integration_success:
                    print(f"{COLOR_ERROR}TTW installed, but integration into modlist failed.{COLOR_RESET}")
                    print(f"{COLOR_ERROR}Please check TTW_Install_workflow.log for details.{COLOR_RESET}")
                    return

                print(f"\n{COLOR_INFO}═══════════════════════════════════════════════════════════════{COLOR_RESET}")
                print(f"{COLOR_INFO}TTW Installation Complete!{COLOR_RESET}")
                print(f"{COLOR_PROMPT}═══════════════════════════════════════════════════════════════{COLOR_RESET}")
                print(f"\nTTW has been installed to: {ttw_output_path}")
                print(f"TTW has been integrated into '{modlist_name}' (modlist.txt + plugins.txt updated).")
                print(f"The modlist '{modlist_name}' is now ready to use with TTW.")
                print(f"Detailed log available at: {get_jackify_logs_dir() / 'TTW_Install_workflow.log'}")
                input(f"\n{COLOR_PROMPT}Press Enter to continue...{COLOR_RESET}")
            else:
                print(f"\n{COLOR_ERROR}TTW installation failed. Check the logs for details.{COLOR_RESET}")
                print(f"{COLOR_ERROR}Error: {message}{COLOR_RESET}")
                print(f"{COLOR_INFO}Detailed log available at: {get_jackify_logs_dir() / 'TTW_Install_workflow.log'}{COLOR_RESET}")
                input(f"\n{COLOR_PROMPT}Press Enter to continue...{COLOR_RESET}")

        except Exception as e:
            self.logger.error(f"Error during TTW installation: {e}", exc_info=True)
            print(f"{COLOR_ERROR}Error during TTW installation: {e}{COLOR_RESET}")
            print(f"{COLOR_INFO}Detailed log available at: {get_jackify_logs_dir() / 'TTW_Install_workflow.log'}{COLOR_RESET}")
            input(f"\n{COLOR_PROMPT}Press Enter to continue...{COLOR_RESET}")
