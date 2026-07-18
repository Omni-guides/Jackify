"""
TTW installer backend: install_ttw_backend, start_ttw_installation, cleanup, stream output, integrate.
"""

import os
import signal
import subprocess
from pathlib import Path
from typing import Optional, Tuple

from .logging_handler import LoggingHandler
from .subprocess_utils import get_clean_subprocess_env


class TTWInstallerBackendMixin:
    """Mixin providing TTW installation process and integration for TTWInstallerHandler."""

    def install_ttw_backend(self, ttw_mpi_path: Path, ttw_output_path: Path) -> Tuple[bool, str]:
        """Install TTW using TTW_Linux_Installer."""
        self.logger.info("Starting Tale of Two Wastelands installation via TTW_Linux_Installer")
        if not ttw_mpi_path or not ttw_output_path:
            return False, "Missing required parameters: ttw_mpi_path and ttw_output_path are required"
        ttw_mpi_path = Path(ttw_mpi_path)
        ttw_output_path = Path(ttw_output_path)
        if not ttw_mpi_path.exists():
            return False, f"TTW .mpi file not found: {ttw_mpi_path}"
        if not ttw_mpi_path.is_file():
            return False, f"TTW .mpi path is not a file: {ttw_mpi_path}"
        if ttw_mpi_path.suffix.lower() != '.mpi':
            return False, f"TTW path does not have .mpi extension: {ttw_mpi_path}"
        if not ttw_output_path.exists():
            try:
                ttw_output_path.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                return False, f"Failed to create output directory: {e}"
        if not self.ttw_installer_installed:
            self.logger.info("TTW_Linux_Installer not found, attempting to install...")
            success, message = self.install_ttw_installer()
            if not success:
                return False, f"TTW_Linux_Installer not installed and auto-install failed: {message}"
        if not self.ttw_installer_executable_path or not self.ttw_installer_executable_path.is_file():
            return False, "TTW_Linux_Installer executable not found"
        required_games = ['Fallout 3', 'Fallout New Vegas']
        detected_games = self.path_handler.find_vanilla_game_paths()
        missing_games = [game for game in required_games if game not in detected_games]
        if missing_games:
            return False, f"Missing required games: {', '.join(missing_games)}. TTW requires both Fallout 3 and Fallout New Vegas."
        fallout3_path = detected_games.get('Fallout 3')
        falloutnv_path = detected_games.get('Fallout New Vegas')
        if not fallout3_path or not falloutnv_path:
            return False, "Could not detect Fallout 3 or Fallout New Vegas installation paths"
        cmd = [
            str(self.ttw_installer_executable_path),
            "install",
            "--fo3", str(fallout3_path),
            "--fnv", str(falloutnv_path),
            "--mpi", str(ttw_mpi_path),
            "--dest", str(ttw_output_path),
        ]
        self.logger.info("Executing TTW_Linux_Installer: %s", ' '.join(cmd))
        try:
            env = get_clean_subprocess_env()
            exe_dir = str(self.ttw_installer_executable_path.parent)
            process = subprocess.Popen(
                cmd, cwd=exe_dir, env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, universal_newlines=True
            )
            error_context: list = []
            capturing_explanation = False
            if process.stdout:
                for line in process.stdout:
                    line = line.rstrip()
                    if line:
                        self.logger.info("TTW_Linux_Installer: %s", line)
                        lower = line.lower()
                        if 'failed' in lower or 'cannot continue' in lower or 'error:' in lower:
                            error_context.append(line.strip())
                            capturing_explanation = True
                        elif capturing_explanation and line.startswith(' '):
                            error_context.append(line.strip())
                        else:
                            capturing_explanation = False
            process.wait()
            ret = process.returncode
            if ret == 0:
                self.logger.info("TTW installation completed successfully.")
                return True, "TTW installation completed successfully!"
            self.logger.error("TTW installation process returned non-zero exit code: %s", ret)
            if error_context:
                return False, "TTW installation failed:\n" + "\n".join(error_context)
            return False, f"TTW installation failed with exit code {ret}"
        except Exception as e:
            self.logger.error("Error executing TTW_Linux_Installer: %s", e, exc_info=True)
            return False, f"Error executing TTW_Linux_Installer: {e}"
        finally:
            from jackify.shared.paths import cleanup_stale_tmp
            cleanup_stale_tmp()

    def start_ttw_installation(self, ttw_mpi_path: Path, ttw_output_path: Path, output_file: Path):
        """Start TTW installation process (non-blocking). Returns (process, error_message)."""
        self.logger.info("Starting TTW installation (non-blocking mode)")
        if not ttw_mpi_path or not ttw_output_path:
            return None, "Missing required parameters: ttw_mpi_path and ttw_output_path are required"
        ttw_mpi_path = Path(ttw_mpi_path)
        ttw_output_path = Path(ttw_output_path)
        if not ttw_mpi_path.exists():
            return None, f"TTW .mpi file not found: {ttw_mpi_path}"
        if not ttw_mpi_path.is_file():
            return None, f"TTW .mpi path is not a file: {ttw_mpi_path}"
        if ttw_mpi_path.suffix.lower() != '.mpi':
            return None, f"TTW path does not have .mpi extension: {ttw_mpi_path}"
        if not ttw_output_path.exists():
            try:
                ttw_output_path.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                return None, f"Failed to create output directory: {e}"
        if not self.ttw_installer_installed:
            self.logger.info("TTW_Linux_Installer not found, attempting to install...")
            success, message = self.install_ttw_installer()
            if not success:
                return None, f"TTW_Linux_Installer not installed and auto-install failed: {message}"
        if not self.ttw_installer_executable_path or not self.ttw_installer_executable_path.is_file():
            return None, "TTW_Linux_Installer executable not found"
        required_games = ['Fallout 3', 'Fallout New Vegas']
        detected_games = self.path_handler.find_vanilla_game_paths()
        missing_games = [game for game in required_games if game not in detected_games]
        if missing_games:
            return None, f"Missing required games: {', '.join(missing_games)}. TTW requires both Fallout 3 and Fallout New Vegas."
        fallout3_path = detected_games.get('Fallout 3')
        falloutnv_path = detected_games.get('Fallout New Vegas')
        if not fallout3_path or not falloutnv_path:
            return None, "Could not detect Fallout 3 or Fallout New Vegas installation paths"
        cmd = [
            str(self.ttw_installer_executable_path),
            "install",
            "--fo3", str(fallout3_path),
            "--fnv", str(falloutnv_path),
            "--mpi", str(ttw_mpi_path),
            "--dest", str(ttw_output_path),
        ]
        self.logger.info("Executing TTW_Linux_Installer: %s", ' '.join(cmd))
        try:
            env = get_clean_subprocess_env()
            output_fh = open(output_file, 'w', encoding='utf-8', buffering=1)
            exe_dir = str(self.ttw_installer_executable_path.parent)
            process = subprocess.Popen(
                cmd, cwd=exe_dir, env=env,
                stdout=output_fh, stderr=subprocess.STDOUT, bufsize=1,
                start_new_session=True,
            )
            self.logger.info("TTW_Linux_Installer process started (PID: %s), output to %s", process.pid, output_file)
            process._output_fh = output_fh
            return process, None
        except Exception as e:
            self.logger.error("Error starting TTW_Linux_Installer: %s", e, exc_info=True)
            return None, f"Error starting TTW_Linux_Installer: {e}"

    @staticmethod
    def cleanup_ttw_process(process):
        """Terminate the TTW process group, then clean up file handles."""
        if process:
            if hasattr(process, '_output_fh'):
                try:
                    process._output_fh.close()
                except Exception:
                    pass
            if process.poll() is None:
                try:
                    pgid = os.getpgid(process.pid)
                    os.killpg(pgid, signal.SIGTERM)
                    process.wait(timeout=5)
                except Exception:
                    try:
                        pgid = os.getpgid(process.pid)
                        os.killpg(pgid, signal.SIGKILL)
                    except Exception:
                        try:
                            process.kill()
                        except Exception:
                            pass
        from jackify.shared.paths import cleanup_stale_tmp
        cleanup_stale_tmp()

    def install_ttw_backend_with_output_stream(self, ttw_mpi_path: Path, ttw_output_path: Path, output_callback=None):
        """Install TTW with streaming output (DEPRECATED - use start_ttw_installation instead)."""
        self.logger.info("Starting Tale of Two Wastelands installation via TTW_Linux_Installer (with output stream)")
        if not ttw_mpi_path or not ttw_output_path:
            return False, "Missing required parameters: ttw_mpi_path and ttw_output_path are required"
        ttw_mpi_path = Path(ttw_mpi_path)
        ttw_output_path = Path(ttw_output_path)
        if not ttw_mpi_path.exists():
            return False, f"TTW .mpi file not found: {ttw_mpi_path}"
        if not ttw_mpi_path.is_file():
            return False, f"TTW .mpi path is not a file: {ttw_mpi_path}"
        if ttw_mpi_path.suffix.lower() != '.mpi':
            return False, f"TTW path does not have .mpi extension: {ttw_mpi_path}"
        if not ttw_output_path.exists():
            try:
                ttw_output_path.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                return False, f"Failed to create output directory: {e}"
        if not self.ttw_installer_installed:
            if output_callback:
                output_callback("TTW_Linux_Installer not found, installing...")
            self.logger.info("TTW_Linux_Installer not found, attempting to install...")
            success, message = self.install_ttw_installer()
            if not success:
                return False, f"TTW_Linux_Installer not installed and auto-install failed: {message}"
        if not self.ttw_installer_executable_path or not self.ttw_installer_executable_path.is_file():
            return False, "TTW_Linux_Installer executable not found"
        required_games = ['Fallout 3', 'Fallout New Vegas']
        detected_games = self.path_handler.find_vanilla_game_paths()
        missing_games = [game for game in required_games if game not in detected_games]
        if missing_games:
            return False, f"Missing required games: {', '.join(missing_games)}. TTW requires both Fallout 3 and Fallout New Vegas."
        fallout3_path = detected_games.get('Fallout 3')
        falloutnv_path = detected_games.get('Fallout New Vegas')
        if not fallout3_path or not falloutnv_path:
            return False, "Could not detect Fallout 3 or Fallout New Vegas installation paths"
        cmd = [
            str(self.ttw_installer_executable_path),
            "install",
            "--fo3", str(fallout3_path),
            "--fnv", str(falloutnv_path),
            "--mpi", str(ttw_mpi_path),
            "--dest", str(ttw_output_path),
        ]
        self.logger.info("Executing TTW_Linux_Installer: %s", ' '.join(cmd))
        try:
            env = get_clean_subprocess_env()
            exe_dir = str(self.ttw_installer_executable_path.parent)
            process = subprocess.Popen(
                cmd, cwd=exe_dir, env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, universal_newlines=True
            )
            error_context: list = []
            capturing_explanation = False
            if process.stdout:
                for line in process.stdout:
                    line = line.rstrip()
                    if line:
                        self.logger.info("TTW_Linux_Installer: %s", line)
                        if output_callback:
                            output_callback(line)
                        lower = line.lower()
                        if 'failed' in lower or 'cannot continue' in lower or 'error:' in lower:
                            error_context.append(line.strip())
                            capturing_explanation = True
                        elif capturing_explanation and line.startswith(' '):
                            error_context.append(line.strip())
                        else:
                            capturing_explanation = False
            process.wait()
            ret = process.returncode
            if ret == 0:
                self.logger.info("TTW installation completed successfully.")
                return True, "TTW installation completed successfully!"
            self.logger.error("TTW installation process returned non-zero exit code: %s", ret)
            if error_context:
                return False, "TTW installation failed:\n" + "\n".join(error_context)
            return False, f"TTW installation failed with exit code {ret}"
        except Exception as e:
            self.logger.error("Error executing TTW_Linux_Installer: %s", e, exc_info=True)
            return False, f"Error executing TTW_Linux_Installer: {e}"
        finally:
            from jackify.shared.paths import cleanup_stale_tmp
            cleanup_stale_tmp()

    @staticmethod
    def integrate_ttw_into_modlist(ttw_output_path: Path, modlist_install_dir: Path, ttw_version: str, skip_copy: bool = False) -> bool:
        """Integrate TTW output into a modlist's MO2 structure."""
        import shutil
        logging_handler = LoggingHandler()
        logging_handler.rotate_log_for_logger('ttw-install', 'TTW_Install_workflow.log')
        logger = logging_handler.setup_logger('ttw-install', 'TTW_Install_workflow.log')
        try:
            if not ttw_output_path.exists():
                logger.error("TTW output path does not exist: %s", ttw_output_path)
                return False
            mods_dir = modlist_install_dir / "mods"
            profiles_dir = modlist_install_dir / "profiles"
            if not mods_dir.exists() or not profiles_dir.exists():
                logger.error("Invalid modlist directory structure: %s", modlist_install_dir)
                return False
            mod_folder_name = f"[NoDelete] Tale of Two Wastelands {ttw_version}" if ttw_version else "[NoDelete] Tale of Two Wastelands"
            target_mod_dir = mods_dir / mod_folder_name
            if skip_copy:
                # TTW was installed directly to target_mod_dir - no copy needed
                logger.info("TTW already at target location, skipping copy: %s", target_mod_dir)
            else:
                logger.info("Copying TTW output to %s", target_mod_dir)
                if target_mod_dir.exists():
                    logger.info("Removing existing TTW mod at %s", target_mod_dir)
                    shutil.rmtree(target_mod_dir)
                shutil.copytree(ttw_output_path, target_mod_dir)
                logger.info("TTW output copied successfully")
            ttw_esms = [
                "Fallout3.esm", "Anchorage.esm", "ThePitt.esm", "BrokenSteel.esm",
                "PointLookout.esm", "Zeta.esm", "TaleOfTwoWastelands.esm", "YUPTTW.esm"
            ]
            for profile_dir in profiles_dir.iterdir():
                if not profile_dir.is_dir():
                    continue
                profile_name = profile_dir.name
                logger.info("Processing profile: %s", profile_name)
                modlist_file = profile_dir / "modlist.txt"
                if modlist_file.exists():
                    with open(modlist_file, 'r', encoding='utf-8') as f:
                        lines = f.readlines()
                    separator_found = False
                    ttw_mod_line = f"+{mod_folder_name}\n"
                    new_lines = []
                    for line in lines:
                        stripped = line.strip()
                        if stripped.startswith('+') and '[nodelete]' in stripped.lower():
                            if ('tale of two wastelands' in stripped.lower() and 'quick start' not in stripped.lower() and
                                'loading wheel' not in stripped.lower()) or stripped.lower().startswith('+[nodelete] ttw '):
                                logger.info("Removing existing TTW mod entry: %s", stripped)
                                continue
                        if "put tale of two wastelands mod here" in line.lower() and "_separator" in line.lower():
                            new_lines.append(ttw_mod_line)
                            separator_found = True
                            logger.info("Inserted TTW mod before separator: %s", line.strip())
                        new_lines.append(line)
                    if not separator_found:
                        new_lines.append(ttw_mod_line)
                        logger.warning("No TTW separator found in %s, appended to end", profile_name)
                    with open(modlist_file, 'w', encoding='utf-8') as f:
                        f.writelines(new_lines)
                    logger.info("Updated modlist.txt for %s", profile_name)
                else:
                    logger.warning("modlist.txt not found for profile %s", profile_name)
                plugins_file = profile_dir / "plugins.txt"
                if plugins_file.exists():
                    with open(plugins_file, 'r', encoding='utf-8') as f:
                        lines = f.readlines()
                    ttw_esm_set = set(esm.lower() for esm in ttw_esms)
                    lines = [line for line in lines if line.strip().lower() not in ttw_esm_set]
                    insert_index = None
                    for i, line in enumerate(lines):
                        if line.strip().lower() == "caravanpack.esm":
                            insert_index = i + 1
                            break
                    if insert_index is not None:
                        for esm in reversed(ttw_esms):
                            lines.insert(insert_index, f"{esm}\n")
                    else:
                        logger.warning("CaravanPack.esm not found in %s, appending TTW ESMs to end", profile_name)
                        for esm in ttw_esms:
                            lines.append(f"{esm}\n")
                    with open(plugins_file, 'w', encoding='utf-8') as f:
                        f.writelines(lines)
                    logger.info("Updated plugins.txt for %s", profile_name)
                else:
                    logger.warning("plugins.txt not found for profile %s", profile_name)
            logger.info("TTW integration completed successfully")
            return True
        except Exception as e:
            logger.error("Error integrating TTW into modlist: %s", e, exc_info=True)
            return False
