"""Directory and download methods for InstallWabbajackHandler (Mixin)."""
import logging
import os
import shutil
from pathlib import Path
from typing import Optional

import requests

from jackify.shared.colors import COLOR_ERROR, COLOR_INFO, COLOR_PROMPT, COLOR_RESET, COLOR_WARNING

logger = logging.getLogger(__name__)

DEFAULT_WABBAJACK_PATH = "~/Wabbajack"
DEFAULT_WABBAJACK_NAME = "Wabbajack"

READLINE_AVAILABLE = False
try:
    import readline
    READLINE_AVAILABLE = True
except ImportError:
    pass
except Exception as e:
    logging.warning(f"Readline import failed: {e}")

try:
    from .menu_handler import simple_path_completer
except ImportError:
    simple_path_completer = None


class WabbajackDirectoryMixin:
    """Mixin providing directory setup and download methods."""

    def _download_file(self, url: str, destination_path: Path) -> bool:
        """Downloads a file from a URL to a destination path.
        Handles temporary file and overwrites destination if download succeeds.

        Args:
            url (str): The URL to download from.
            destination_path (Path): The path to save the downloaded file.

        Returns:
            bool: True if download succeeds, False otherwise.
        """
        self.logger.info(f"Downloading {destination_path.name} from {url}")

        destination_path.parent.mkdir(parents=True, exist_ok=True)

        temp_path = destination_path.with_suffix(destination_path.suffix + ".part")
        self.logger.debug(f"Downloading to temporary path: {temp_path}")

        try:
            with requests.get(url, stream=True, timeout=30, verify=True) as r:
                r.raise_for_status()
                block_size = 8192
                with open(temp_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=block_size):
                        if chunk:
                            f.write(chunk)

            actual_downloaded_size = temp_path.stat().st_size
            self.logger.debug(f"Download finished. Actual size: {actual_downloaded_size} bytes.")

            shutil.move(str(temp_path), str(destination_path))
            self.logger.info(f"Successfully downloaded and moved to {destination_path}")
            return True

        except requests.exceptions.RequestException as e:
            self.logger.error(f"Download failed for {url}: {e}", exc_info=True)
            print(f"\n{COLOR_ERROR}Error downloading {destination_path.name}: {e}{COLOR_RESET}")
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError as unlink_err:
                    self.logger.error(f"Failed to remove partial download {temp_path}: {unlink_err}")
            return False
        except Exception as e:
            self.logger.error(f"An unexpected error occurred during download: {e}", exc_info=True)
            print(f"\n{COLOR_ERROR}An unexpected error occurred during download: {e}{COLOR_RESET}")
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError as unlink_err:
                    self.logger.error(f"Failed to remove partial download {temp_path}: {unlink_err}")
            return False

    def _prepare_install_directory(self) -> bool:
        """
        Ensures the target installation directory exists and is accessible.
        Handles directory creation, prompting the user if outside $HOME.

        Returns:
            bool: True if the directory exists and is ready, False otherwise.
        """
        if not self.install_path:
            self.logger.error("Cannot prepare directory: install_path is not set.")
            return False

        self.logger.info(f"Preparing installation directory: {self.install_path}")

        if self.install_path.exists():
            if self.install_path.is_dir():
                self.logger.info(f"Directory already exists: {self.install_path}")
                if not os.access(self.install_path, os.W_OK | os.X_OK):
                    print(f"{COLOR_ERROR}Error: Directory exists but lacks necessary write/execute permissions.{COLOR_RESET}")
                    return False
                return True
            else:
                print(f"{COLOR_ERROR}Error: The specified path exists but is a file, not a directory.{COLOR_RESET}")
                return False
        else:
            self.logger.info("Directory does not exist. Attempting creation...")
            try:
                home_dir = Path.home()
                is_outside_home = not str(self.install_path.resolve()).startswith(str(home_dir.resolve()))

                if is_outside_home:
                    self.logger.warning(f"Install path {self.install_path} is outside home directory {home_dir}.")
                    print(f"\n{COLOR_PROMPT}The chosen path is outside your home directory and may require manual creation.{COLOR_RESET}")
                    while True:
                        response = input(f"{COLOR_PROMPT}Please create the directory \"{self.install_path}\" manually,\nensure you have write permissions, and then press Enter to continue (or 'q' to quit): {COLOR_RESET}").lower()
                        if response == 'q':
                            self.logger.warning("User aborted manual directory creation.")
                            return False
                        if self.install_path.exists():
                            if self.install_path.is_dir():
                                self.logger.info("Directory created manually by user.")
                                if not os.access(self.install_path, os.W_OK | os.X_OK):
                                    print(f"{COLOR_WARNING}Warning: Directory created, but write/execute permissions might be missing.{COLOR_RESET}")
                                return True
                            else:
                                print(f"{COLOR_ERROR}Error: Path exists now, but it is not a directory. Please fix and try again.{COLOR_RESET}")
                        else:
                            print(f"\n{COLOR_ERROR}Directory still not found. Please create it or enter 'q' to quit.{COLOR_RESET}")
                else:
                    self.logger.info("Path is inside home directory. Creating...")
                    os.makedirs(self.install_path)
                    self.logger.info(f"Successfully created directory: {self.install_path}")
                    if not os.access(self.install_path, os.W_OK | os.X_OK):
                        print(f"{COLOR_WARNING}Warning: Directory created, but lacks write/execute permissions. Subsequent steps might fail.{COLOR_RESET}")
                    return True

            except PermissionError:
                self.logger.error(f"Permission denied when trying to create directory: {self.install_path}", exc_info=True)
                print(f"\n{COLOR_ERROR}Error: Permission denied creating directory.{COLOR_RESET}")
                print(f"{COLOR_INFO}Please check permissions for the parent directory or choose a different location.{COLOR_RESET}")
                return False
            except OSError as e:
                self.logger.error(f"Failed to create directory {self.install_path}: {e}", exc_info=True)
                print(f"\n{COLOR_ERROR}Error creating directory: {e}{COLOR_RESET}")
                return False
            except Exception as e:
                self.logger.error(f"An unexpected error occurred during directory preparation: {e}", exc_info=True)
                print(f"\n{COLOR_ERROR}An unexpected error occurred: {e}{COLOR_RESET}")
                return False

    def _get_wabbajack_install_path(self) -> Optional[Path]:
        """
        Prompts the user for the Wabbajack installation path with tab completion.
        Uses the FileSystemHandler for path validation and completion.

        Returns:
            Optional[Path]: The chosen installation path as a Path object, or None if cancelled.
        """
        self.logger.info("Prompting for Wabbajack installation path.")
        current_path = self.install_path if self.install_path else Path(DEFAULT_WABBAJACK_PATH).expanduser()

        if READLINE_AVAILABLE and simple_path_completer:
            readline.set_completer_delims(' \t\n;')
            readline.parse_and_bind("tab: complete")
            readline.set_completer(simple_path_completer)

        try:
            while True:
                try:
                    prompt_text = f"{COLOR_PROMPT}Enter Wabbajack installation path (default: {current_path}): {COLOR_RESET}"
                    user_input = input(prompt_text).strip()

                    if not user_input:
                        chosen_path_str = str(current_path)
                    else:
                        chosen_path_str = user_input

                    chosen_path = Path(chosen_path_str).expanduser().resolve()

                    if not chosen_path.name:
                        print(f"{COLOR_ERROR}Invalid path. Please enter a valid directory path.{COLOR_RESET}")
                        continue

                    if chosen_path.exists() and not chosen_path.is_dir():
                        print(f"{COLOR_ERROR}Path exists but is not a directory: {chosen_path}{COLOR_RESET}")
                        continue

                    confirm_prompt = f"{COLOR_PROMPT}Install Wabbajack to {chosen_path}? (Y/n/c to cancel): {COLOR_RESET}"
                    confirmation = input(confirm_prompt).lower()

                    if confirmation == 'c':
                        self.logger.info("Wabbajack installation path selection cancelled by user.")
                        return None
                    elif confirmation != 'n':
                        self.install_path = chosen_path
                        self.logger.info(f"Wabbajack installation path set to: {self.install_path}")
                        return self.install_path
                except KeyboardInterrupt:
                    self.logger.info("Wabbajack installation path selection cancelled by user (Ctrl+C).")
                    print("\nPath selection cancelled.")
                    return None
                except Exception as e:
                    self.logger.error(f"Error during path input: {e}", exc_info=True)
                    print(f"{COLOR_ERROR}An unexpected error occurred: {e}{COLOR_RESET}")
                    return None
        finally:
            if READLINE_AVAILABLE:
                readline.set_completer(None)

    def _get_wabbajack_shortcut_name(self) -> Optional[str]:
        """
        Prompts the user for the Wabbajack shortcut name.

        Returns:
            Optional[str]: The name chosen by the user, or None if cancelled.
        """
        self.logger.debug("Getting Wabbajack shortcut name.")

        if self.shortcut_name:
            self.logger.info(f"Using pre-configured shortcut name: {self.shortcut_name}")
            return self.shortcut_name

        chosen_name = DEFAULT_WABBAJACK_NAME

        if self.menu_handler:
            self.logger.debug("Using menu_handler for shortcut name input")
            print(f"\nWabbajack Shortcut Name:")
            name_input = self.menu_handler.get_input_with_default(
                prompt=f"Enter the desired name for the Wabbajack Steam shortcut (default: {chosen_name})",
                default=chosen_name
            )
            if name_input is not None:
                self.logger.info(f"User provided shortcut name: {name_input}")
                return name_input
            else:
                self.logger.info("User cancelled shortcut name input")
                return None

        try:
            print(f"\n{COLOR_PROMPT}Enter the desired name for the Wabbajack Steam shortcut.{COLOR_RESET}")
            name_input = input(f"{COLOR_PROMPT}Name [{chosen_name}]: {COLOR_RESET}").strip()

            if not name_input:
                self.logger.info(f"User did not provide input, using default name: {chosen_name}")
            else:
                chosen_name = name_input
                self.logger.info(f"User provided name: {chosen_name}")

            return chosen_name

        except KeyboardInterrupt:
            print(f"\n{COLOR_ERROR}Input cancelled by user.{COLOR_RESET}")
            self.logger.warning("User cancelled name input.")
            return None
        except Exception as e:
            self.logger.error(f"An unexpected error occurred while getting name input: {e}", exc_info=True)
            return None

    def _download_wabbajack_executable(self) -> bool:
        """
        Downloads the latest Wabbajack.exe to the install directory.
        Checks existence first.

        Returns:
            bool: True on success or if file exists, False otherwise.
        """
        if not self.install_path:
            self.logger.error("Cannot download Wabbajack.exe: install_path is not set.")
            return False

        url = "https://github.com/wabbajack-tools/wabbajack/releases/latest/download/Wabbajack.exe"
        destination = self.install_path / "Wabbajack.exe"

        if destination.is_file():
            self.logger.info(f"Wabbajack.exe already exists at {destination}. Skipping download.")
            return True

        self.logger.info("Wabbajack.exe not found. Downloading...")
        if self._download_file(url, destination):
            try:
                os.chmod(destination, 0o755)
                self.logger.info(f"Set execute permissions on {destination}")
            except Exception as e:
                self.logger.warning(f"Could not set execute permission on {destination}: {e}")
                self.logger.warning("Could not set execute permission on Wabbajack.exe.")
            return True
        else:
            self.logger.error("Failed to download Wabbajack.exe.")
            return False
