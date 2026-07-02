"""Prefix setup methods for InstallWabbajackHandler (Mixin)."""
import logging
import os
import pwd
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional, Tuple

from jackify.shared.colors import COLOR_ERROR, COLOR_INFO, COLOR_PROMPT, COLOR_RESET

logger = logging.getLogger(__name__)


class WabbajackPrefixSetupMixin:
    """Mixin providing Wine prefix setup methods."""

    def _find_steam_library_and_vdf_path(self) -> Tuple[Optional[Path], Optional[Path]]:
        """Finds the Steam library root and the path to the real libraryfolders.vdf."""
        self.logger.info("Attempting to find Steam library and libraryfolders.vdf...")
        try:
            if isinstance(self.path_handler, type):
                common_path = self.path_handler.find_steam_library()
            else:
                common_path = self.path_handler.find_steam_library()

            if not common_path or not common_path.is_dir():
                self.logger.error("Could not find Steam library common path.")
                return None, None

            library_root = common_path.parent.parent
            self.logger.debug(f"Deduced library root: {library_root}")

            vdf_path_candidates = [
                library_root / 'config/libraryfolders.vdf',
                library_root / '../config/libraryfolders.vdf'
            ]

            real_vdf_path = None
            for candidate in vdf_path_candidates:
                resolved_candidate = candidate.resolve()
                if resolved_candidate.is_file():
                    real_vdf_path = resolved_candidate
                    self.logger.info(f"Found real libraryfolders.vdf at: {real_vdf_path}")
                    break

            if not real_vdf_path:
                self.logger.error(f"Could not find libraryfolders.vdf within library root: {library_root}")
                return None, None

            return library_root, real_vdf_path

        except Exception as e:
            self.logger.error(f"Error finding Steam library/VDF: {e}", exc_info=True)
            return None, None

    def _link_steam_library_config(self) -> bool:
        """Creates the necessary directory structure and symlinks libraryfolders.vdf."""
        if not self.compatdata_path:
            self.logger.error("Cannot link Steam library: compatdata_path not set.")
            return False

        self.logger.info("Linking Steam library configuration (libraryfolders.vdf)...")

        library_root, real_vdf_path = self._find_steam_library_and_vdf_path()
        if not library_root or not real_vdf_path:
            self.logger.error("Could not locate Steam library or libraryfolders.vdf.")
            return False

        target_dir = self.compatdata_path / 'pfx/drive_c/Program Files (x86)/Steam/config'
        link_path = target_dir / 'libraryfolders.vdf'

        try:
            self.logger.debug(f"Backing up original libraryfolders.vdf: {real_vdf_path}")
            if not self.filesystem_handler.backup_file(real_vdf_path):
                self.logger.warning(f"Failed to backup {real_vdf_path}. Proceeding with caution.")
                self.logger.warning("Failed to create backup of libraryfolders.vdf.")

            self.logger.debug(f"Creating directory: {target_dir}")
            os.makedirs(target_dir, exist_ok=True)

            if link_path.is_symlink():
                self.logger.debug(f"Removing existing symlink at {link_path}")
                link_path.unlink()
            elif link_path.exists():
                self.logger.warning(f"Path {link_path} exists but is not a symlink. Removing it.")
                if link_path.is_dir():
                    shutil.rmtree(link_path)
                else:
                    link_path.unlink()

            self.logger.info(f"Creating symlink from {real_vdf_path} to {link_path}")
            os.symlink(real_vdf_path, link_path)

            if link_path.is_symlink() and link_path.resolve() == real_vdf_path.resolve():
                self.logger.info("Symlink created and verified successfully.")
                return True
            else:
                self.logger.error("Symlink creation failed or verification failed.")
                return False

        except OSError as e:
            self.logger.error(f"OSError during symlink creation: {e}", exc_info=True)
            print(f"{COLOR_ERROR}Error creating Steam library link: {e}{COLOR_RESET}")
            return False
        except Exception as e:
            self.logger.error(f"Unexpected error during symlink creation: {e}", exc_info=True)
            print(f"{COLOR_ERROR}An unexpected error occurred: {e}{COLOR_RESET}")
            return False

    def _create_prefix_library_vdf(self) -> bool:
        """Creates the necessary directory structure and copies a modified libraryfolders.vdf."""
        if not self.compatdata_path:
            self.logger.error("Cannot create prefix VDF: compatdata_path not set.")
            return False

        self.logger.info("Creating modified libraryfolders.vdf in prefix...")

        library_root, real_vdf_path = self._find_steam_library_and_vdf_path()
        if not real_vdf_path:
            self.logger.error("Could not locate real libraryfolders.vdf.")
            return False

        self.logger.debug(f"Backing up original libraryfolders.vdf: {real_vdf_path}")
        if not self.filesystem_handler.backup_file(real_vdf_path):
            self.logger.warning(f"Failed to backup {real_vdf_path}. Proceeding with caution.")
            self.logger.warning("Failed to create backup of libraryfolders.vdf.")

        target_dir = self.compatdata_path / 'pfx/drive_c/Program Files (x86)/Steam/config'
        target_vdf_path = target_dir / 'libraryfolders.vdf'

        try:
            self.logger.debug(f"Reading content from {real_vdf_path}")
            vdf_content = real_vdf_path.read_text(encoding='utf-8')

            path_pattern = re.compile(r'("path"\s*")([^"]+)(")')

            def replace_path(match):
                prefix, linux_path_str, suffix = match.groups()
                self.logger.debug(f"Found path entry to convert: {linux_path_str}")
                try:
                    linux_path = Path(linux_path_str)
                    if self.filesystem_handler.is_sd_card(linux_path):
                        relative_sd_path_str = self.filesystem_handler._strip_sdcard_path_prefix(linux_path)
                        wine_path = "D:\\" + relative_sd_path_str.replace('/', '\\')
                        self.logger.debug(f"  Converted SD card path: {linux_path_str} -> {wine_path}")
                    else:
                        wine_path = "Z:\\" + linux_path_str.strip('/').replace('/', '\\')
                        self.logger.debug(f"  Converted standard path: {linux_path_str} -> {wine_path}")

                    wine_path_vdf_escaped = wine_path.replace('\\', '\\\\')
                    return f'{prefix}{wine_path_vdf_escaped}{suffix}'
                except Exception as e:
                    self.logger.error(f"Error converting path '{linux_path_str}': {e}. Keeping original.")
                    return match.group(0)

            modified_content = path_pattern.sub(replace_path, vdf_content)

            if modified_content != vdf_content:
                self.logger.info("Successfully converted Linux paths to Wine paths in VDF content.")
            else:
                self.logger.warning("VDF content unchanged after conversion attempt. Did it contain Linux paths?")

            self.logger.debug(f"Ensuring target directory exists: {target_dir}")
            os.makedirs(target_dir, exist_ok=True)

            self.logger.info(f"Writing modified VDF content to {target_vdf_path}")
            target_vdf_path.write_text(modified_content, encoding='utf-8')

            if target_vdf_path.is_file():
                self.logger.info("Prefix libraryfolders.vdf created successfully.")
                return True
            else:
                self.logger.error("Failed to create prefix libraryfolders.vdf.")
                return False

        except Exception as e:
            self.logger.error(f"Error processing or writing prefix libraryfolders.vdf: {e}", exc_info=True)
            print(f"{COLOR_ERROR}An error occurred configuring the Steam library in the prefix: {e}{COLOR_RESET}")
            return False

    def _create_dotnet_cache_dir(self) -> bool:
        """Creates the dotnet_bundle_extract cache directory."""
        if not self.install_path:
            self.logger.error("Cannot create dotnet cache dir: install_path not set.")
            return False

        try:
            username = pwd.getpwuid(os.getuid()).pw_name
        except Exception as e:
            self.logger.error(f"Could not determine username: {e}")
            self.logger.error("Could not determine username to create cache directory.")
            return False

        cache_dir = self.install_path / 'home' / username / '.cache' / 'dotnet_bundle_extract'
        self.logger.info(f"Creating dotnet bundle cache directory: {cache_dir}")

        try:
            os.makedirs(cache_dir, exist_ok=True)
            self.logger.info("dotnet cache directory created successfully.")
            return True
        except OSError as e:
            self.logger.error(f"Failed to create dotnet cache directory {cache_dir}: {e}", exc_info=True)
            print(f"{COLOR_ERROR}Error creating dotnet cache directory: {e}{COLOR_RESET}")
            return False
        except Exception as e:
            self.logger.error(f"Unexpected error creating dotnet cache directory: {e}", exc_info=True)
            print(f"{COLOR_ERROR}An unexpected error occurred: {e}{COLOR_RESET}")
            return False

    def _check_and_prompt_flatpak_overrides(self):
        """Checks if Flatpak Steam needs filesystem overrides and prompts the user to apply them."""
        self.logger.info("Checking for necessary Flatpak Steam filesystem overrides...")
        is_flatpak_steam = False
        if self.compatdata_path and ".var/app/com.valvesoftware.Steam" in str(self.compatdata_path):
            is_flatpak_steam = True
            self.logger.debug("Flatpak Steam detected based on compatdata path.")

        if not is_flatpak_steam:
            self.logger.info("Flatpak Steam not detected, skipping override check.")
            return

        paths_to_check = []
        if self.install_path:
            paths_to_check.append(self.install_path)

        try:
            all_libs = self.path_handler.get_all_steam_libraries()
            paths_to_check.extend(all_libs)
        except Exception as e:
            self.logger.warning(f"Could not get all Steam libraries to check for overrides: {e}")

        needed_overrides = set()
        home_dir = Path.home()
        flatpak_steam_data_dir = home_dir / ".var/app/com.valvesoftware.Steam"

        for path in paths_to_check:
            if not path:
                continue
            resolved_path = path.resolve()
            is_outside_home = not str(resolved_path).startswith(str(home_dir))
            is_outside_flatpak_data = not str(resolved_path).startswith(str(flatpak_steam_data_dir))

            if is_outside_home and is_outside_flatpak_data:
                parent_to_add = resolved_path.parent
                while parent_to_add != parent_to_add.parent and len(str(parent_to_add)) > 1 and parent_to_add.name != 'home':
                    if parent_to_add.is_dir():
                        needed_overrides.add(str(parent_to_add))
                        self.logger.debug(f"Path {resolved_path} is outside sandbox. Adding parent {parent_to_add} to needed overrides.")
                        break
                    parent_to_add = parent_to_add.parent

        if not needed_overrides:
            self.logger.info("No external paths requiring Flatpak overrides detected.")
            return

        override_commands = []
        for path_str in sorted(list(needed_overrides)):
            override_commands.append(f"flatpak override --user --filesystem=\"{path_str}\" com.valvesoftware.Steam")

        command_display = "\n".join([f"  {cmd}" for cmd in override_commands])

        print(f"\n{COLOR_PROMPT}--- Flatpak Steam Permissions ---{COLOR_RESET}")
        print("Jackify has detected that you are using Flatpak Steam and have paths")
        print("(e.g., Wabbajack install location or other Steam libraries) outside")
        print("the standard Flatpak sandbox. For Wabbajack to access these locations,")
        print("Steam needs the following filesystem permissions:")
        print(f"{COLOR_INFO}{command_display}{COLOR_RESET}")
        print("───────────────────────────────────────────────────────────────────")

        try:
            confirm = input(f"{COLOR_PROMPT}Do you want Jackify to apply these permissions now? (y/N): {COLOR_RESET}").lower().strip()
            if confirm == 'y':
                self.logger.info("User confirmed applying Flatpak overrides.")
                success_count = 0
                for cmd_str in override_commands:
                    self.logger.info(f"Executing: {cmd_str}")
                    try:
                        cmd_list = cmd_str.split()
                        result = subprocess.run(cmd_list, check=True, capture_output=True, text=True, timeout=30)
                        self.logger.debug(f"Override command successful: {result.stdout}")
                        success_count += 1
                    except FileNotFoundError:
                        print(f"{COLOR_ERROR}Error: 'flatpak' command not found. Cannot apply override.{COLOR_RESET}")
                        break
                    except subprocess.TimeoutExpired:
                        print(f"{COLOR_ERROR}Error: Flatpak override command timed out.{COLOR_RESET}")
                    except subprocess.CalledProcessError as e:
                        self.logger.error(f"Flatpak override failed: {cmd_str}. Error: {e.stderr}")
                        print(f"{COLOR_ERROR}Error applying override: {cmd_str}\n{e.stderr}{COLOR_RESET}")
                    except Exception as e:
                        self.logger.error(f"Unexpected error applying override {cmd_str}: {e}")
                        print(f"{COLOR_ERROR}An unexpected error occurred: {e}{COLOR_RESET}")

                if success_count == len(override_commands):
                    print(f"{COLOR_INFO}Successfully applied necessary Flatpak permissions.{COLOR_RESET}")
                else:
                    print(f"{COLOR_ERROR}Applied {success_count}/{len(override_commands)} permissions. Some overrides may have failed. Check logs.{COLOR_RESET}")
            else:
                self.logger.info("User declined applying Flatpak overrides.")
                print("Permissions not applied. You may need to run the override command(s) manually")
                print("if Wabbajack has issues accessing files or game installations.")

        except KeyboardInterrupt:
            print("\nOperation cancelled by user.")
            self.logger.warning("User cancelled during Flatpak override prompt.")
        except Exception as e:
            self.logger.error(f"Error during Flatpak override prompt/execution: {e}")

    def _disable_prefix_decoration(self) -> bool:
        """Disables window manager decoration in the Wine prefix using protontricks -c."""
        if not self.final_appid:
            self.logger.error("Cannot disable decoration: final_appid not set.")
            return False

        self.logger.info(f"Disabling window manager decoration for AppID {self.final_appid} via -c 'wine reg add...'")
        command = 'wine reg add "HKCU\\Software\\Wine\\X11 Driver" /v Decorated /t REG_SZ /d N /f'

        try:
            if not hasattr(self, 'protontricks_handler') or not self.protontricks_handler:
                self.logger.critical("ProtontricksHandler not initialized!")
                self.logger.error("Internal Error: Protontricks handler not available.")
                return False

            result = self.protontricks_handler.run_protontricks(
                '-c',
                command,
                self.final_appid
            )

            if result and result.returncode == 0:
                self.logger.info("Successfully disabled window decoration (command returned 0).")
                time.sleep(1)
                return True
            else:
                err_msg = result.stderr if result else "Command execution failed or returned non-zero"
                if result and not result.stderr and result.stdout:
                    err_msg += f"\nSTDOUT: {result.stdout}"
                self.logger.error(f"Failed to disable window decoration via -c. Error: {err_msg}")
                self.logger.error("Failed to disable window decoration via protontricks -c.")
                return False
        except Exception as e:
            self.logger.error(f"Exception disabling window decoration: {e}", exc_info=True)
            self.logger.error(f"Error disabling window decoration: {e}.")
            return False
