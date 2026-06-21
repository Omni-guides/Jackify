"""TTW installation worker thread."""
from PySide6.QtCore import QThread, Signal
import os
import signal
import time

from ..utils import strip_ansi_control_codes


class TTWInstallationThread(QThread):
    output_batch_received = Signal(list)
    progress_received = Signal(str)
    installation_finished = Signal(bool, str)

    def __init__(self, mpi_path, install_dir):
        super().__init__()
        self.mpi_path = mpi_path
        self.install_dir = install_dir
        self.cancelled = False
        self.proc = None
        self.output_buffer = []
        self.last_emit_time = 0

    def cancel(self):
        self.cancelled = True
        if self.proc and self.proc.poll() is None:
            try:
                pgid = os.getpgid(self.proc.pid)
                os.killpg(pgid, signal.SIGTERM)
            except Exception:
                try:
                    self.proc.terminate()
                except Exception:
                    pass

    def process_and_buffer_line(self, raw_line):
        """Clean one output line and queue it for batched emit."""
        cleaned = strip_ansi_control_codes(raw_line).strip()

        filtered_chars = []
        for char in cleaned:
            code = ord(char)
            is_emoji = (
                (0x1F300 <= code <= 0x1F9FF) or
                (0x1F600 <= code <= 0x1F64F) or
                (0x2600 <= code <= 0x26FF) or
                (0x2700 <= code <= 0x27BF)
            )
            if not is_emoji:
                filtered_chars.append(char)
        cleaned = ''.join(filtered_chars).strip()

        if cleaned:
            self.output_buffer.append(cleaned)

    def flush_output_buffer(self):
        """Emit buffered lines as a batch."""
        if self.output_buffer:
            self.output_batch_received.emit(self.output_buffer[:])
            self.output_buffer.clear()
            self.last_emit_time = time.time()

    def run(self):
        try:
            from jackify.backend.handlers.ttw_installer_handler import TTWInstallerHandler
            from jackify.backend.handlers.filesystem_handler import FileSystemHandler
            from jackify.backend.handlers.config_handler import ConfigHandler
            from pathlib import Path
            import tempfile

            self.process_and_buffer_line("Initialising TTW installation...")
            self.flush_output_buffer()

            filesystem_handler = FileSystemHandler()
            config_handler = ConfigHandler()
            ttw_handler = TTWInstallerHandler(
                steamdeck=False,
                verbose=False,
                filesystem_handler=filesystem_handler,
                config_handler=config_handler,
            )

            output_file = tempfile.NamedTemporaryFile(
                mode='w+', delete=False, suffix='.ttw_output', encoding='utf-8'
            )
            output_file_path = Path(output_file.name)
            output_file.close()

            self.process_and_buffer_line("Starting TTW installation...")
            self.flush_output_buffer()

            self.proc, error_msg = ttw_handler.start_ttw_installation(
                Path(self.mpi_path),
                Path(self.install_dir),
                output_file_path,
            )

            if not self.proc:
                self.installation_finished.emit(False, error_msg or "Failed to start TTW installation")
                return

            self.process_and_buffer_line("TTW_Linux_Installer process started, monitoring output...")
            self.flush_output_buffer()

            last_position = 0
            BATCH_INTERVAL = 0.3

            while self.proc.poll() is None:
                if self.cancelled:
                    break

                try:
                    with open(output_file_path, 'r', encoding='utf-8', errors='replace') as f:
                        f.seek(last_position)
                        new_lines = f.readlines()
                        last_position = f.tell()

                        for line in new_lines:
                            if self.cancelled:
                                break
                            self.process_and_buffer_line(line.rstrip())

                        if time.time() - self.last_emit_time >= BATCH_INTERVAL:
                            self.flush_output_buffer()
                except Exception:
                    pass

                time.sleep(0.1)

            try:
                with open(output_file_path, 'r', encoding='utf-8', errors='replace') as f:
                    f.seek(last_position)
                    for line in f.readlines():
                        self.process_and_buffer_line(line.rstrip())
                self.flush_output_buffer()
            except Exception:
                pass

            try:
                output_file_path.unlink(missing_ok=True)
            except Exception:
                pass

            ttw_handler.cleanup_ttw_process(self.proc)

            returncode = self.proc.returncode if self.proc else -1
            if self.cancelled:
                self.installation_finished.emit(False, "Installation cancelled by user")
            elif returncode == 0:
                self.installation_finished.emit(True, "TTW installation completed successfully!")
            else:
                self.installation_finished.emit(
                    False,
                    f"TTW installer exited unexpectedly (code {returncode}). "
                    "Review the recent console output for the failing step."
                )

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.installation_finished.emit(False, f"Installation error: {str(e)}")
