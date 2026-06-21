"""
Progress Data Models

Shared data models for representing installation progress state.
Used by both parser and GUI components.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from enum import Enum
import time


class InstallationPhase(Enum):
    """Installation phases that can be detected."""
    UNKNOWN = "unknown"
    INITIALIZATION = "initialization"
    DOWNLOAD = "download"
    EXTRACT = "extract"
    VALIDATE = "validate"
    INSTALL = "install"
    FINALIZE = "finalize"


class OperationType(Enum):
    """Types of operations being performed on files."""
    DOWNLOAD = "download"
    EXTRACT = "extract"
    VALIDATE = "validate"
    INSTALL = "install"
    UNKNOWN = "unknown"


@dataclass
class FileProgress:
    """Represents progress for a single file operation."""
    filename: str
    operation: OperationType
    percent: float = 0.0  # 0-100
    current_size: int = 0  # Bytes processed
    total_size: int = 0  # Total bytes (0 if unknown)
    speed: float = -1.0  # Bytes per second (-1 = not provided by engine)
    last_update: float = field(default_factory=time.time)
    
    def __post_init__(self):
        """Ensure percent is in valid range."""
        self.percent = max(0.0, min(100.0, self.percent))
    
    @property
    def is_complete(self) -> bool:
        """Check if file operation is complete."""
        return self.percent >= 100.0 or (self.total_size > 0 and self.current_size >= self.total_size)
    
    @property
    def size_display(self) -> str:
        """Get human-readable size display."""
        if self.total_size > 0:
            return f"{self._format_bytes(self.current_size)}/{self._format_bytes(self.total_size)}"
        elif self.current_size > 0:
            return f"{self._format_bytes(self.current_size)}"
        else:
            return ""
    
    @property
    def speed_display(self) -> str:
        """Get human-readable speed display."""
        if self.speed <= 0:
            return ""
        return f"{self._format_bytes(int(self.speed))}/s"
    
    @staticmethod
    def _format_bytes(bytes_val: int) -> str:
        """Format bytes to human-readable format."""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_val < 1024.0:
                return f"{bytes_val:.1f}{unit}"
            bytes_val /= 1024.0
        return f"{bytes_val:.1f}PB"


@dataclass
class InstallationProgress:
    """Complete installation progress state."""
    phase: InstallationPhase = InstallationPhase.UNKNOWN
    phase_name: str = ""  # Human-readable phase name
    phase_step: int = 0  # Current step in phase
    phase_max_steps: int = 0  # Total steps in phase (0 if unknown)
    overall_percent: float = 0.0  # 0-100 overall progress
    data_processed: int = 0  # Bytes processed
    data_total: int = 0  # Total bytes (0 if unknown)
    active_files: List[FileProgress] = field(default_factory=list)
    speeds: Dict[str, float] = field(default_factory=dict)  # Speed by operation type
    speed_timestamps: Dict[str, float] = field(default_factory=dict)  # Last time each speed updated
    timestamp: float = field(default_factory=time.time)
    message: str = ""  # Current status message
    texture_conversion_current: int = 0  # Current texture being converted
    texture_conversion_total: int = 0  # Total textures to convert
    bsa_building_current: int = 0  # Current BSA being built
    bsa_building_total: int = 0  # Total BSAs to build
    # ETA smoothing: track speed and data history for stable ETA calculation
    _speed_history: List[Tuple[float, float]] = field(default_factory=list)  # [(timestamp, speed_bytes_per_sec), ...]
    _data_history: List[Tuple[float, int]] = field(default_factory=list)  # [(timestamp, data_processed_bytes), ...]
    _last_eta_update: float = 0.0  # Last time ETA was calculated/displayed
    _smoothed_eta_seconds: float = -1.0  # Cached smoothed ETA value
    
    def __post_init__(self):
        """Ensure percent is in valid range."""
        self.overall_percent = max(0.0, min(100.0, self.overall_percent))
    
    @property
    def phase_progress_text(self) -> str:
        """Get phase progress text like '[12/14]'."""
        if self.phase_max_steps > 0 and self.phase_step > 0:
            return f"[{self.phase_step}/{self.phase_max_steps}]"
        elif self.phase_step > 0:
            return f"[{self.phase_step}]"
        else:
            return ""
    
    @property
    def data_progress_text(self) -> str:
        """Get data progress text like '1.1GB/56.3GB'."""
        if self.data_total > 0:
            return f"{FileProgress._format_bytes(self.data_processed)}/{FileProgress._format_bytes(self.data_total)}"
        elif self.data_processed > 0:
            return f"{FileProgress._format_bytes(self.data_processed)}"
        else:
            return ""
    
    @property
    def total_download_size_gb(self) -> float:
        """Get total download size in GB (0 if unknown)."""
        if self.data_total > 0:
            return self.data_total / (1024.0 ** 3)
        return 0.0
    
    @property
    def remaining_download_size_gb(self) -> float:
        """Get remaining download size in GB (0 if unknown or complete)."""
        if self.data_total > 0 and self.data_processed < self.data_total:
            return (self.data_total - self.data_processed) / (1024.0 ** 3)
        return 0.0
    
    def _update_speed_history(self, operation: str, speed: float):
        """Update speed history for ETA smoothing."""
        if operation.lower() != 'download':
            return
        
        current_time = time.time()
        
        # Add current speed to history
        self._speed_history.append((current_time, speed))
        
        # Keep only last 60 seconds of history
        cutoff_time = current_time - 60.0
        self._speed_history = [(t, s) for t, s in self._speed_history if t >= cutoff_time]
    
    def _update_data_history(self):
        """Update data history for calculating average speed from data processed over time."""
        if self.data_processed <= 0:
            return
        
        current_time = time.time()
        
        # Only add if data has changed or enough time has passed (avoid spam)
        if self._data_history:
            last_time, last_data = self._data_history[-1]
            # Only add if data changed by at least 1MB or 5 seconds passed
            if self.data_processed == last_data and (current_time - last_time) < 5.0:
                return
        
        self._data_history.append((current_time, self.data_processed))
        
        # Keep only last 60 seconds
        cutoff_time = current_time - 60.0
        self._data_history = [(t, d) for t, d in self._data_history if t >= cutoff_time]
    
    def _get_average_speed(self, window_seconds: float = 30.0) -> float:
        """
        Get average download speed over the last N seconds.
        Uses both speed history and data history for more accurate calculation.
        
        Args:
            window_seconds: Time window to average over (default 30 seconds)
            
        Returns:
            Average speed in bytes per second, or -1 if insufficient data
        """
        current_time = time.time()
        cutoff_time = current_time - window_seconds
        
        # Method 1: Use speed history if available
        recent_speeds = [s for t, s in self._speed_history if t >= cutoff_time]
        if len(recent_speeds) >= 3:  # Need at least 3 samples
            return sum(recent_speeds) / len(recent_speeds)
        
        # Method 2: Calculate from data history (more accurate for varying speeds)
        recent_data = [(t, d) for t, d in self._data_history if t >= cutoff_time]
        if len(recent_data) >= 2:
            # Calculate average speed from data processed over time
            oldest = recent_data[0]
            newest = recent_data[-1]
            time_diff = newest[0] - oldest[0]
            data_diff = newest[1] - oldest[1]
            if time_diff > 0:
                return data_diff / time_diff
        
        # Fallback: Use current instantaneous speed
        return self.get_speed('download')
    
    def get_eta_seconds(self, use_smoothing: bool = True) -> float:
        """
        Calculate estimated time remaining in seconds.
        Uses smoothed/averaged speed to prevent wild fluctuations.
        
        Args:
            use_smoothing: If True, use averaged speed over last 30 seconds (default True)
            
        Returns:
            ETA in seconds, or -1 if ETA cannot be calculated
        """
        # Only calculate ETA during download phase
        if self.phase != InstallationPhase.DOWNLOAD:
            return -1.0
        
        # Need both remaining data and current speed
        if self.data_total <= 0 or self.data_processed >= self.data_total:
            return -1.0
        
        # Update data history for speed calculation
        self._update_data_history()
        
        remaining_bytes = self.data_total - self.data_processed
        
        # Get speed (smoothed or instantaneous)
        if use_smoothing:
            download_speed = self._get_average_speed(window_seconds=30.0)
        else:
            download_speed = self.get_speed('download')
        
        if download_speed <= 0:
            return -1.0
        
        # Calculate ETA
        eta_seconds = remaining_bytes / download_speed
        
        # Apply exponential smoothing to ETA itself to prevent wild jumps
        # Only update if we have a previous value and the change isn't too extreme
        if use_smoothing and self._smoothed_eta_seconds > 0:
            # If new ETA is wildly different (>50% change), use weighted average
            # Prevent temporary speed drops from causing huge ETA jumps
            change_ratio = abs(eta_seconds - self._smoothed_eta_seconds) / max(self._smoothed_eta_seconds, 1.0)
            if change_ratio > 0.5:
                # Large change - use 70% old, 30% new (smooth transition)
                eta_seconds = 0.7 * self._smoothed_eta_seconds + 0.3 * eta_seconds
            else:
                # Small change - use 85% old, 15% new (quick but stable)
                eta_seconds = 0.85 * self._smoothed_eta_seconds + 0.15 * eta_seconds
        
        # Update cached value
        self._smoothed_eta_seconds = eta_seconds
        
        return eta_seconds
    
    @staticmethod
    def _format_eta(seconds: float) -> str:
        """Format ETA seconds into human-readable string like '2h 15m' or '45m 30s'."""
        if seconds < 0:
            return ""
        
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        
        if hours > 0:
            return f"{hours}h {minutes:02d}m"
        elif minutes > 0:
            return f"{minutes}m {secs:02d}s"
        else:
            return f"{secs}s"
    
    @property
    def eta_display(self) -> str:
        """
        Get formatted ETA display string.
        Only updates every 5 seconds to prevent UI flicker from rapid changes.
        """
        current_time = time.time()
        
        # Only recalculate ETA every 5 seconds to prevent wild fluctuations in display
        if current_time - self._last_eta_update < 5.0 and self._smoothed_eta_seconds > 0:
            # Use cached value if recently calculated
            eta_seconds = self._smoothed_eta_seconds
        else:
            # Recalculate with smoothing
            eta_seconds = self.get_eta_seconds(use_smoothing=True)
            self._last_eta_update = current_time
        
        if eta_seconds < 0:
            return ""
        return self._format_eta(eta_seconds)
    
    def get_overall_speed_display(self) -> str:
        """Get overall speed display from aggregate speeds reported by engine."""
        def _fresh_speed(op_key: str) -> float:
            """Return speed if recently updated, else 0."""
            if op_key not in self.speeds:
                return 0.0
            updated_at = self.speed_timestamps.get(op_key, 0.0)
            if updated_at == 0.0:
                return 0.0
            if time.time() - updated_at > 2.0:
                return 0.0
            return max(0.0, self.speeds.get(op_key, 0.0))

        # CRITICAL FIX: Use aggregate speeds from engine status lines
        # The engine reports accurate total speeds in lines like:
        # "[00:00:10] Downloading Mod Archives (17/214) - 6.8MB/s"
        # These aggregate speeds are stored in self.speeds dict and are the source of truth
        # DO NOT sum individual file speeds - that inflates the total incorrectly

        # Try to get speed for current phase first
        phase_operation_map = {
            InstallationPhase.DOWNLOAD: 'download',
            InstallationPhase.EXTRACT: 'extract',
            InstallationPhase.VALIDATE: 'validate',
            InstallationPhase.INSTALL: 'install',
        }
        active_op = phase_operation_map.get(self.phase)
        if active_op:
            op_speed = _fresh_speed(active_op)
            if op_speed > 0:
                return FileProgress._format_bytes(int(op_speed)) + "/s"

        # Otherwise check other operations in priority order
        for op_key in ['download', 'extract', 'validate', 'install']:
            op_speed = _fresh_speed(op_key)
            if op_speed > 0:
                return FileProgress._format_bytes(int(op_speed)) + "/s"

        return ""
    
    def get_phase_label(self) -> str:
        """Return a short, stable label for the current phase."""
        # During install+texture conversion, keep a stable combined label to avoid
        # rapid banner flipping between install and conversion text.
        if self.phase == InstallationPhase.INSTALL and self.texture_conversion_total > 0:
            has_install_counter = self.phase_max_steps > 0 and self.phase_max_steps != self.texture_conversion_total
            if has_install_counter:
                return "Installing + Converting Textures"
            return "Converting Textures"

        # Check for specific operations first (more specific than generic phase labels)
        if self.phase_name:
            phase_lower = self.phase_name.lower()
            # Check for texture conversion (very specific)
            if 'converting' in phase_lower and 'texture' in phase_lower:
                return "Converting Textures"
            # Check for BSA building
            if 'bsa' in phase_lower or ('building' in phase_lower and self.phase == InstallationPhase.INSTALL):
                return "Building BSAs"
            if ('extract' in phase_lower or 'queu' in phase_lower) and self.phase == InstallationPhase.INSTALL:
                return "Queuing Archives"

        # For FINALIZE and INITIALIZATION phases, prefer phase_name over the generic label.
        # INITIALIZATION cycles through many short sections ("Configuring Installer",
        # "Looking for unmodified files", etc.) that are more informative than "Preparing".
        if self.phase in (InstallationPhase.FINALIZE, InstallationPhase.INITIALIZATION) and self.phase_name:
            return self.phase_name
        if self.phase == InstallationPhase.DOWNLOAD and self.phase_name:
            return self.phase_name

        phase_labels = {
            InstallationPhase.DOWNLOAD: "Downloading",
            InstallationPhase.EXTRACT: "Extracting",
            InstallationPhase.VALIDATE: "Validating",
            InstallationPhase.INSTALL: "Installing",
            InstallationPhase.FINALIZE: "Finalising",
            InstallationPhase.INITIALIZATION: "Preparing",
        }
        if self.phase in phase_labels:
            return phase_labels[self.phase]
        if self.phase_name:
            return self.phase_name
        if self.phase != InstallationPhase.UNKNOWN:
            return self.phase.value.title()
        return ""
    
    @property
    def display_text(self) -> str:
        """Get formatted display text for progress indicator."""
        parts = []

        # Phase name
        phase_label = self.get_phase_label()
        if phase_label:
            parts.append(phase_label)

        # For BSA building, show BSA count instead of generic phase progress or data progress
        if self.bsa_building_total > 0:
            # BSA building in progress - show BSA count
            parts.append(f"[{self.bsa_building_current}/{self.bsa_building_total}]")
            # Don't show data progress during BSA building (it's usually complete at 100%)
        else:
            # Normal phase - show phase progress
            phase_prog = self.phase_progress_text
            # For download phase, hide zero-step counters (e.g. [0/2]) because
            # they are confusing when byte/speed progress is already active.
            if self.phase == InstallationPhase.DOWNLOAD and self.phase_step <= 0:
                phase_prog = ""
            # If current step reflects texture counters, don't duplicate that as
            # the primary install counter.
            if self.phase == InstallationPhase.INSTALL and self.texture_conversion_total > 0:
                if self.phase_max_steps > 0 and self.phase_max_steps == self.texture_conversion_total:
                    phase_prog = ""
            if phase_prog:
                parts.append(phase_prog)

            # Data progress (but not during BSA building)
            data_prog = self.data_progress_text
            if data_prog:
                # Some engine versions report a changing remaining total while keeping
                # processed bytes at 0. Avoid showing misleading "(0B/YYY)" pairs.
                if self.phase == InstallationPhase.DOWNLOAD and self.data_total > 0 and self.data_processed <= 0:
                    data_prog = ""

            if data_prog:
                # Don't show if it's 100% complete (adds no value)
                if self.data_total > 0 and self.data_processed < self.data_total:
                    parts.append(f"({data_prog})")
                elif self.data_total == 0 and self.data_processed > 0:
                    # Show partial progress even without total
                    parts.append(f"({data_prog})")
            if self.phase == InstallationPhase.INSTALL and self.texture_conversion_total > 0:
                tex_total = self.texture_conversion_total
                tex_current = max(0, min(self.texture_conversion_current, tex_total))
                parts.append(f"Converting textures: {tex_current}/{tex_total}")

        # Overall speed (if available, but not during BSA building)
        if self.bsa_building_total == 0:
            speed_display = self.get_overall_speed_display()
            if speed_display:
                parts.append(f"- {speed_display}")
        
        # Overall percentage removed - redundant with progress bar display
        
        return " ".join(parts) if parts else "Processing..."
    
    def get_speed(self, operation: str) -> float:
        """Get speed for a specific operation type."""
        return self.speeds.get(operation.lower(), 0.0)
    
    def add_file(self, file_progress: FileProgress):
        """Add or update a file in active files list."""
        # Don't re-add files that are already at 100% unless they're being actively updated
        # Prevent completed files from cluttering the list
        if file_progress.percent >= 100.0:
            # Check if this file already exists at 100%
            existing = None
            for f in self.active_files:
                if f.filename == file_progress.filename:
                    existing = f
                    break
            
            if existing and existing.percent >= 100.0:
                # File is already at 100% - only update if it's very recent (within 0.5s)
                # Completion notification refreshes the timestamp
                if time.time() - existing.last_update < 0.5:
                    existing.last_update = time.time()
                # Otherwise, don't re-add it - let remove_completed_files handle cleanup
                return
        
        # Remove existing entry for same filename if present
        existing = None
        for f in self.active_files:
            if f.filename == file_progress.filename:
                existing = f
                break
        
        if existing:
            # Update existing entry (preserve original add time for minimum display)
            existing.operation = file_progress.operation
            existing.percent = file_progress.percent
            existing.current_size = file_progress.current_size
            existing.total_size = file_progress.total_size
            existing.speed = file_progress.speed
            existing.last_update = time.time()
            # If file just reached 100%, ensure we keep it visible for minimum time
            if file_progress.percent >= 100.0 and existing.percent < 100.0:
                # File just completed - ensure it stays visible
                existing.last_update = time.time()
        else:
            # Add new entry - set initial timestamp
            file_progress.last_update = time.time()
            self.active_files.append(file_progress)
        
        # Update timestamp
        self.timestamp = time.time()
    
    def remove_completed_files(self, stale_seconds: float = 0.5, stale_incomplete_seconds: float = 30.0):
        """
        Remove files that are marked as complete, or files that haven't been updated in a while.
        
        Args:
            stale_seconds: Keep completed files for this many seconds before removing (allows brief display at 100%)
                          Reduced to 0.5s so tiny files that complete instantly still appear briefly
            stale_incomplete_seconds: Remove incomplete files that haven't been updated in this many seconds (handles stuck files)
        """
        current_time = time.time()
        self.active_files = [
            f for f in self.active_files 
            # Keep files that are:
            # 1. Not complete AND updated recently (active files)
            # 2. Complete AND updated very recently (show at 100% briefly so users can see all files, even tiny ones)
            if (not f.is_complete and (current_time - f.last_update) < stale_incomplete_seconds) or \
               (f.is_complete and (current_time - f.last_update) < stale_seconds)
        ]
    
    def update_speed(self, operation: str, speed: float):
        """Update speed for an operation type."""
        op_key = operation.lower()
        self.speeds[op_key] = max(0.0, speed)
        self.speed_timestamps[op_key] = time.time()
        self.timestamp = time.time()
        
        # Update speed history for ETA smoothing
        if speed > 0:
            self._update_speed_history(op_key, speed)
