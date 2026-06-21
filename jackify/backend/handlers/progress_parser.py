"""
Progress Parser

Parses jackify-engine text output to extract structured progress information.
This is an R&D implementation - experimental and subject to change.
"""

import os
import re
from typing import Optional, Tuple
from dataclasses import dataclass

from jackify.shared.progress_models import (
    InstallationProgress,
    InstallationPhase,
    FileProgress,
    OperationType
)

from .progress_parser_phase import ProgressParserPhaseMixin
from .progress_parser_files import ProgressParserFilesMixin
from .progress_parser_extraction import ProgressParserExtractionMixin
from .progress_state_processing import ProgressStateProcessingMixin
from .progress_state_metrics import ProgressStateMetricsMixin


@dataclass
class ParsedLine:
    """Result of parsing a single line of output."""
    has_progress: bool = False
    phase: Optional[InstallationPhase] = None
    phase_name: Optional[str] = None
    file_progress: Optional[FileProgress] = None
    completed_filename: Optional[str] = None  # Filename that just completed
    overall_percent: Optional[float] = None
    step_info: Optional[Tuple[int, int]] = None  # (current, total)
    data_info: Optional[Tuple[int, int]] = None  # (current_bytes, total_bytes)
    speed_info: Optional[Tuple[str, float]] = None  # (operation, speed_bytes_per_sec)
    file_counter: Optional[Tuple[int, int]] = None  # (current_file, total_files) for Extracting phase
    message: str = ""


class ProgressParser(ProgressParserPhaseMixin, ProgressParserFilesMixin, ProgressParserExtractionMixin):
    """
    Parses jackify-engine output to extract progress information.
    
    This parser uses pattern matching to extract:
    - Installation phases
    - File-level progress
    - Overall progress percentages
    - Step counts
    - Data sizes
    - Operation speeds
    """
    
    def __init__(self):
        """Initialize parser with pattern definitions."""
        # Phase detection patterns
        self.phase_patterns = [
            (r'===?\s*(.+?)\s*===?', self._extract_phase_from_section),
            (r'\[.*?\]\s*(?:Installing|Downloading|Extracting|Validating|Processing)', self._extract_phase_from_action),
            (r'(?:Starting|Beginning)\s+(.+?)(?:\s+phase|\.|$)', re.IGNORECASE),
        ]
        
        # File progress patterns
        self.file_patterns = [
            # Pattern: "Installing: filename.7z (42%)"
            (r'(?:Installing|Downloading|Extracting|Validating):\s*(.+?)\s*\((\d+(?:\.\d+)?)%\)', self._parse_file_with_percent),
            # Pattern: "filename.7z: 42%"
            (r'(.+?\.(?:7z|zip|rar|bsa|dds)):\s*(\d+(?:\.\d+)?)%', self._parse_file_with_percent),
            # Pattern: "filename.7z [45.2MB/s]"
            (r'(.+?\.(?:7z|zip|rar|bsa|dds))\s*\[([^\]]+)\]', self._parse_file_with_speed),
        ]
        
        # Overall progress patterns (stored as regex patterns, not tuples with callbacks)
        # Wabbajack format: "[12/14] Installing files (1.1GB/56.3GB)"
        self.overall_patterns = [
            # Pattern: "Progress: 85%" or "85%"
            (r'(?:Progress|Overall):\s*(\d+(?:\.\d+)?)%', re.IGNORECASE),
            (r'^(\d+(?:\.\d+)?)%\s*(?:complete|done|progress)', re.IGNORECASE),
        ]
        
        # Wabbajack status update format: "[12/14] StatusText (current/total)"
        # Primary format
        self.wabbajack_status_pattern = re.compile(
            r'\[(\d+)/(\d+)\]\s+(.+?)\s+\(([^)]+)\)',
            re.IGNORECASE
        )
        
        # Alternative format: "[timestamp] StatusText (current/total) - speed [- Xunit remaining]"
        # Example: "[00:00:10] Downloading Mod Archives (17/214) - 6.8MB/s"
        # Example (engine 0.4.8+): "[00:00:10] Downloading Mod Archives (17/214) - 6.8MB/s - 23.1GB remaining"
        # Timestamp prefix is now optional - engine no longer emits [HH:MM:SS].
        self.timestamp_status_pattern = re.compile(
            r'(?:\[[^\]]+\]\s+)?(.+?)\s+\((\d+)/(\d+)\)\s*-\s*([^\s]+)(?:\s*-\s*([\d.]+)\s*(B|KB|MB|GB|TB)\s+remaining)?',
            re.IGNORECASE
        )
        
        # Data size patterns
        self.data_patterns = [
            # Pattern: "1.1GB/56.3GB" or "(1.1GB/56.3GB)"
            (r'\(?(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)\s*/\s*(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)\)?', re.IGNORECASE),
            # Pattern: "Processing 1.1GB of 56.3GB"
            (r'Processing\s+(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)\s+of\s+(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)', re.IGNORECASE),
        ]
        
        # Speed patterns
        self.speed_patterns = [
            # Pattern: "267.3MB/s" or "45.2 MB/s"
            (r'(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)\s*/s', re.IGNORECASE),
            # Pattern: "at 267.3MB/s" or "speed: 45.2 MB/s"
            (r'(?:at|speed:?)\s+(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)\s*/s', re.IGNORECASE),
        ]
        
        # File filter - only display meaningful artifacts in the UI
        self.allowed_extensions = {
            '.7z', '.zip', '.rar', '.bsa', '.ba2', '.dds', '.wabbajack',
            '.exe', '.esp', '.esm', '.esl', '.bin', '.dll', '.pak',
            '.tar', '.gz', '.xz', '.bz2', '.z01', '.z02', '.cab', '.msi'
        }
    
    def should_display_file(self, filename: str) -> bool:
        """Public helper so other components can reuse the filter."""
        return self._should_display_file(filename)
    
    def _should_display_file(self, filename: str) -> bool:
        """Determine whether a filename is worth showing in the UI."""
        if not filename:
            return False
        base = os.path.basename(filename.strip())
        if not base:
            return False
        # Special case: allow ".wabbajack" and "Downloading .wabbajack file"
        if base == ".wabbajack" or base == "Downloading .wabbajack file":
            return True
        # Skip temporary/generated files (e.g., #zcbe$123.txt)
        if base.startswith('#'):
            return False
        name, ext = os.path.splitext(base)
        if not ext:
            return False
        if ext.lower() not in self.allowed_extensions:
            return False
        # Also skip generic filenames that are clearly tooling artifacts
        if name.lower() in {'empty', 'script', 'one', 'two', 'three'}:
            return False
        return True
    
    def parse_line(self, line: str) -> ParsedLine:
        """
        Parse a single line of output and extract progress information.
        
        Args:
            line: Raw line from jackify-engine output
            
        Returns:
            ParsedLine with extracted information
        """
        result = ParsedLine(message=line.strip())

        if not line.strip():
            return result

        # Suppress internal engine lines that are not user-facing
        _suppress_prefixes = (
            "Refreshing OAuth Token",
        )
        if any(line.strip().startswith(p) for p in _suppress_prefixes):
            return ParsedLine()

        # Try to extract phase information
        phase_info = self._extract_phase(line)
        if phase_info:
            result.phase, result.phase_name = phase_info
            result.has_progress = True
        
        # Try to extract file progress
        file_prog = self._extract_file_progress(line)
        if file_prog:
            result.file_progress = file_prog
            result.has_progress = True
            if '[FILE_PROGRESS]' in line:
                result.message = ""
            # Check if file counter was attached (for extraction or install phases)
            if hasattr(file_prog, '_file_counter'):
                result.file_counter = file_prog._file_counter
                delattr(file_prog, '_file_counter')  # Clean up temp attribute
        
        # Try to extract overall progress
        overall = self._extract_overall_progress(line)
        if overall is not None:
            result.overall_percent = overall
            result.has_progress = True
        
        # Try to extract Wabbajack status format first: "[12/14] StatusText (1.1GB/56.3GB)"
        # BUT skip if this is a .wabbajack download line (handled by specific pattern below)
        wabbajack_match = self.wabbajack_status_pattern.search(line)
        if wabbajack_match:
            status_text = wabbajack_match.group(3).strip().lower()
            # Skip if this is a .wabbajack download - let the specific pattern handle it
            if '.wabbajack' in status_text or 'downloading .wabbajack' in status_text:
                # Don't process this as generic status - let .wabbajack pattern handle it
                pass
            else:
                # Extract step info
                current_step = int(wabbajack_match.group(1))
                max_steps = int(wabbajack_match.group(2))
                result.step_info = (current_step, max_steps)
                
                # Extract status text (phase name)
                phase_info = self._extract_phase_from_text(status_text)
                if phase_info:
                    result.phase, result.phase_name = phase_info
                
                # Extract data info from parentheses
                data_str = wabbajack_match.group(4).strip()
                data_info = self._parse_data_string(data_str)
                if data_info:
                    result.data_info = data_info
                
                result.has_progress = True
        
        # Try alternative format: "[timestamp] StatusText (current/total) - speed"
        # Example: "[00:00:10] Downloading Mod Archives (17/214) - 6.8MB/s"
        timestamp_match = self.timestamp_status_pattern.search(line)
        if timestamp_match:
            # Extract status text (phase name)
            status_text = timestamp_match.group(1).strip()
            phase_info = self._extract_phase_from_text(status_text)
            if phase_info:
                result.phase, result.phase_name = phase_info
            
            # Extract step info (current/total in parentheses)
            current_step = int(timestamp_match.group(2))
            max_steps = int(timestamp_match.group(3))
            result.step_info = (current_step, max_steps)
            
            # Extract speed
            speed_str = timestamp_match.group(4).strip()
            speed_info = self._parse_speed_from_string(speed_str)
            if speed_info:
                operation = self._detect_operation_from_line(status_text)
                result.speed_info = (operation.value, speed_info)

            # Extract remaining size if present (engine 0.4.8+: "- 23.1GB remaining")
            remaining_val = timestamp_match.group(5)
            remaining_unit = timestamp_match.group(6)
            if remaining_val and remaining_unit:
                remaining_bytes = self._convert_to_bytes(float(remaining_val), remaining_unit)
                if remaining_bytes > 0 and max_steps > 0 and current_step < max_steps:
                    fraction_done = current_step / max_steps
                    # Estimate total from remaining and fraction; clamp denominator to avoid div/0 near completion
                    estimated_total = remaining_bytes / max(1.0 - fraction_done, 0.01)
                    data_processed = int(estimated_total - remaining_bytes)
                    result.data_info = (max(0, data_processed), int(estimated_total))
                elif remaining_bytes > 0:
                    result.data_info = (0, int(remaining_bytes))

            # Calculate overall percentage from step progress
            if max_steps > 0:
                result.overall_percent = (current_step / max_steps) * 100.0

            result.has_progress = True
        
        # Try .wabbajack download format: "[timestamp] Downloading .wabbajack (size/size) - speed"
        # Example: "[00:02:08] Downloading .wabbajack (739.2/1947.2MB) - 6.0MB/s"
        # Also handles: "[00:02:08] Downloading modlist.wabbajack (739.2/1947.2MB) - 6.0MB/s"
        # Timestamp prefix is optional in newer engine output.
        wabbajack_download_pattern = re.compile(
            r'(?:\[[^\]]+\]\s+)?Downloading\s+([^\s]+\.wabbajack|\.wabbajack)\s+\(([^)]+)\)\s*-\s*([^\s]+)',
            re.IGNORECASE
        )
        wabbajack_match = wabbajack_download_pattern.search(line)
        if wabbajack_match:
            # Extract filename (group 1)
            filename = wabbajack_match.group(1).strip()
            if filename == ".wabbajack":
                # Try to extract actual filename from message if available
                filename_match = re.search(r'([A-Za-z0-9_\-\.]+\.wabbajack)', line, re.IGNORECASE)
                if filename_match:
                    filename = filename_match.group(1)
                else:
                    # Use display message as filename
                    filename = "Downloading .wabbajack file"
            
            # Extract data info from parentheses (e.g., "49.7/1947.2MB" or "739.2MB/1947.2MB")
            # Format can be: "current/totalUnit" or "currentUnit/totalUnit"
            data_str = wabbajack_match.group(2).strip()
            data_info = None
            
            # Try standard format first (both have units)
            data_info = self._extract_data_info(f"({data_str})")
            
            # If that fails, try format where only second number has unit: "49.7/1947.2MB"
            if not data_info:
                pattern = r'(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)?\s*/\s*(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)'
                match = re.search(pattern, data_str, re.IGNORECASE)
                if match:
                    current_val = float(match.group(1))
                    current_unit = match.group(2) if match.group(2) else match.group(4)  # Use second unit if first missing
                    total_val = float(match.group(3))
                    total_unit = match.group(4)
                    
                    current_bytes = self._convert_to_bytes(current_val, current_unit)
                    total_bytes = self._convert_to_bytes(total_val, total_unit)
                    data_info = (current_bytes, total_bytes)
            
            if data_info:
                result.data_info = data_info
                # Calculate percent from data
                current_bytes, total_bytes = data_info
                if total_bytes > 0:
                    result.overall_percent = (current_bytes / total_bytes) * 100.0
            
            # Extract speed (group 3)
            speed_str = wabbajack_match.group(3).strip()
            speed_info = self._parse_speed_from_string(speed_str)
            if speed_info:
                result.speed_info = ("download", speed_info)
            
            # Set phase
            result.phase = InstallationPhase.DOWNLOAD
            phase_target = filename
            if phase_target.lower().startswith("downloading "):
                phase_target = phase_target[len("downloading "):].strip()
            result.phase_name = f"Downloading {phase_target}"
            
            # Create FileProgress entry for .wabbajack file
            if data_info:
                current_bytes, total_bytes = data_info
                percent = (current_bytes / total_bytes) * 100.0 if total_bytes > 0 else 0.0
                file_progress = FileProgress(
                    filename=filename,
                    operation=OperationType.DOWNLOAD,
                    percent=percent,
                    current_size=current_bytes,
                    total_size=total_bytes,
                    speed=speed_info if speed_info else -1.0
                )
                result.file_progress = file_progress
            
            result.has_progress = True
        
        # Try to extract install progress format:
        # "Installing files X/Y (GB/GB) - Converting textures: N/M"
        install_match = re.match(
            r'Installing files\s+(\d+)/(\d+)\s+\(([^)]+)\)(?:\s*-\s*Converting textures:\s*(\d+)/(\d+))?',
            line.strip(), re.IGNORECASE)
        if install_match:
            result.phase = InstallationPhase.INSTALL
            result.step_info = (int(install_match.group(1)), int(install_match.group(2)))
            data_info = self._parse_data_string(install_match.group(3))
            if data_info:
                result.data_info = data_info
                current_bytes, total_bytes = data_info
                if total_bytes > 0:
                    result.overall_percent = (current_bytes / total_bytes) * 100.0
            if install_match.group(4) and install_match.group(5):
                fp = FileProgress(
                    filename='_tex',
                    operation=OperationType.INSTALL,
                    percent=0.0,
                    speed=-1.0
                )
                fp._texture_counter = (int(install_match.group(4)), int(install_match.group(5)))
                fp._hidden = True
                result.file_progress = fp
            result.has_progress = True

        # Conversion-only status line (without "Installing files ...")
        conversion_match = re.search(r'Converting textures:\s*(\d+)/(\d+)', line, re.IGNORECASE)
        if conversion_match and not install_match:
            if not result.phase:
                result.phase = InstallationPhase.INSTALL
            if not result.phase_name:
                result.phase_name = "Converting textures"
            fp = FileProgress(
                filename='_tex',
                operation=OperationType.INSTALL,
                percent=0.0,
                speed=-1.0
            )
            fp._texture_counter = (int(conversion_match.group(1)), int(conversion_match.group(2)))
            fp._hidden = True
            result.file_progress = fp
            result.has_progress = True

        # Try to extract step information (fallback)
        if not result.step_info:
            step_info = self._extract_step_info(line)
            if step_info:
                result.step_info = step_info
                result.has_progress = True
        
        # Try to extract data size information (fallback)
        if not result.data_info:
            data_info = self._extract_data_info(line)
            if data_info:
                result.data_info = data_info
                result.has_progress = True
        
        # Try to extract speed information
        speed_info = self._extract_speed_info(line)
        if speed_info:
            result.speed_info = speed_info
            result.has_progress = True
        
        # Try to detect file completion
        completed_file = self._extract_completed_file(line)
        if completed_file:
            result.completed_filename = completed_file
            result.has_progress = True
        
        return result


class ProgressStateManager(ProgressStateProcessingMixin, ProgressStateMetricsMixin):
    """
    Manages installation progress state by accumulating parsed information.
    
    This class maintains the current state of installation progress and
    updates it as new lines are parsed.
    """
    
    def __init__(self):
        """Initialize state manager."""
        self.state = InstallationProgress()
        self.parser = ProgressParser()
        self._file_history = {}
        self._wabbajack_entry_name = None
        self._synthetic_flag = "_synthetic_wabbajack"
        self._previous_phase = None  # Track phase changes to reset stale data
        # Track total download size from all files seen during download phase
        self._download_files_seen = {}  # filename -> (total_size, max_current_size)
        self._download_total_bytes = 0  # Running total of all file sizes seen
        self._download_processed_bytes = 0  # Running total of bytes processed
        self._has_real_wabbajack = False

    def get_state(self) -> InstallationProgress:
        """Get current progress state."""
        return self.state

    def reset(self):
        """Reset progress state."""
        self.state = InstallationProgress()
        self._file_history = {}
        self._wabbajack_entry_name = None
        self._synthetic_flag = "_synthetic_wabbajack"
        self._has_real_wabbajack = False
