"""
Progress Aggregator

Handles aggregation and cleanup of download progress messages to provide
a cleaner, less disorienting user experience when multiple downloads are running.
"""

import re
import time
from typing import Dict, Optional, List, NamedTuple
from collections import defaultdict, deque
from dataclasses import dataclass


@dataclass
class DownloadProgress:
    """Represents progress for a single download."""
    file_name: str
    current_size: int
    total_size: int
    speed: float
    percentage: float
    last_update: float


class ProgressStats(NamedTuple):
    """Aggregated progress statistics."""
    total_files: int
    completed_files: int
    active_files: int
    total_bytes: int
    downloaded_bytes: int
    overall_percentage: float
    average_speed: float


class ProgressAggregator:
    """
    Aggregates download progress from multiple concurrent downloads and provides
    cleaner progress reporting to avoid UI spam.
    """
    
    def __init__(self, update_interval: float = 2.0, max_displayed_downloads: int = 3):
        self.update_interval = update_interval
        self.max_displayed_downloads = max_displayed_downloads
        
        # Track individual download progress
        self._downloads: Dict[str, DownloadProgress] = {}
        self._completed_downloads: set = set()
        
        # Track overall statistics
        self._last_update_time = 0.0
        self._recent_speeds = deque(maxlen=10)  # For speed averaging
        
        # Pattern matching for different progress formats
        self._progress_patterns = [
            # Common download progress patterns
            r'(?:Downloading|Download)\s+(.+?):\s*(\d+)%',
            r'(?:Downloading|Download)\s+(.+?)\s+\[([^\]]+)\]',
            r'\[(\d+)/(\d+)\]\s*(.+?)\s*(\d+)%',
            # Extraction progress patterns  
            r'(?:Extracting|Extract)\s+(.+?):\s*(\d+)%',
            r'(?:Extracting|Extract)\s+(.+?)\s+\[([^\]]+)\]',
        ]
        
    def update_progress(self, message: str) -> Optional[str]:
        """
        Update progress with a new message and return aggregated progress if it's time to update.
        
        Args:
            message: Raw progress message from jackify-engine
            
        Returns:
            Cleaned progress message if update interval has passed, None otherwise
        """
        current_time = time.time()
        
        # Parse the progress message
        parsed = self._parse_progress_message(message)
        if parsed:
            self._downloads[parsed.file_name] = parsed
            
        # Check if it's time for an update
        if current_time - self._last_update_time >= self.update_interval:
            self._last_update_time = current_time
            return self._generate_aggregated_message()
            
        return None
        
    def mark_completed(self, file_name: str):
        """Mark a download as completed."""
        self._completed_downloads.add(file_name)
        if file_name in self._downloads:
            del self._downloads[file_name]
            
    def get_stats(self) -> ProgressStats:
        """Get current aggregated statistics."""
        active_downloads = list(self._downloads.values())
        
        if not active_downloads:
            return ProgressStats(0, len(self._completed_downloads), 0, 0, 0, 0.0, 0.0)
            
        total_files = len(active_downloads) + len(self._completed_downloads)
        total_bytes = sum(d.total_size for d in active_downloads)
        downloaded_bytes = sum(d.current_size for d in active_downloads)
        
        # Calculate overall percentage
        if total_bytes > 0:
            overall_percentage = (downloaded_bytes / total_bytes) * 100
        else:
            overall_percentage = 0.0
            
        # Calculate average speed
        speeds = [d.speed for d in active_downloads if d.speed > 0]
        average_speed = sum(speeds) / len(speeds) if speeds else 0.0
        
        return ProgressStats(
            total_files=total_files,
            completed_files=len(self._completed_downloads),
            active_files=len(active_downloads),
            total_bytes=total_bytes,
            downloaded_bytes=downloaded_bytes,
            overall_percentage=overall_percentage,
            average_speed=average_speed
        )
        
    def _parse_progress_message(self, message: str) -> Optional[DownloadProgress]:
        """Parse a progress message into structured data."""
        # Clean up the message
        clean_message = message.strip()
        
        # Try each pattern
        for pattern in self._progress_patterns:
            match = re.search(pattern, clean_message, re.IGNORECASE)
            if match:
                try:
                    if len(match.groups()) >= 2:
                        file_name = match.group(1).strip()
                        
                        # Extract percentage or progress info
                        progress_str = match.group(2)
                        
                        # Handle different progress formats
                        if progress_str.endswith('%'):
                            percentage = float(progress_str[:-1])
                            # Estimate size based on percentage (we don't have exact sizes)
                            current_size = int(percentage * 1000)  # Arbitrary scaling
                            total_size = 100000
                            speed = 0.0
                        else:
                            # Try to parse size/speed format like "45.2MB/s"
                            percentage = 0.0
                            current_size = 0
                            total_size = 1
                            speed = self._parse_speed(progress_str)
                            
                        return DownloadProgress(
                            file_name=file_name,
                            current_size=current_size,
                            total_size=total_size,
                            speed=speed,
                            percentage=percentage,
                            last_update=time.time()
                        )
                except (ValueError, IndexError):
                    continue
                    
        return None
        
    def _parse_speed(self, speed_str: str) -> float:
        """Parse speed string like '45.2MB/s' into bytes per second."""
        try:
            # Remove '/s' suffix
            speed_str = speed_str.replace('/s', '').strip()
            
            # Extract number and unit
            match = re.match(r'([\d.]+)\s*([KMGT]?B)', speed_str, re.IGNORECASE)
            if not match:
                return 0.0
                
            value = float(match.group(1))
            unit = match.group(2).upper()
            
            # Convert to bytes per second
            multipliers = {
                'B': 1,
                'KB': 1024,
                'MB': 1024 * 1024,
                'GB': 1024 * 1024 * 1024,
                'TB': 1024 * 1024 * 1024 * 1024
            }
            
            return value * multipliers.get(unit, 1)
            
        except (ValueError, AttributeError):
            return 0.0
            
    def _generate_aggregated_message(self) -> str:
        """Generate a clean, aggregated progress message."""
        stats = self.get_stats()
        
        if stats.total_files == 0:
            return "Processing..."
            
        # Get most recent active downloads to display
        recent_downloads = sorted(
            self._downloads.values(),
            key=lambda d: d.last_update,
            reverse=True
        )[:self.max_displayed_downloads]
        
        # Build message components
        components = []
        
        # Overall progress
        if stats.total_files > 1:
            components.append(f"Progress: {stats.completed_files}/{stats.total_files} files")
            if stats.overall_percentage > 0:
                components.append(f"({stats.overall_percentage:.1f}%)")
                
        # Current active downloads
        if recent_downloads:
            if len(recent_downloads) == 1:
                download = recent_downloads[0]
                if download.percentage > 0:
                    components.append(f"Downloading: {download.file_name} ({download.percentage:.1f}%)")
                else:
                    components.append(f"Downloading: {download.file_name}")
            else:
                components.append(f"Downloading {len(recent_downloads)} files")
                
        # Speed info
        if stats.average_speed > 0:
            speed_str = self._format_speed(stats.average_speed)
            components.append(f"@ {speed_str}")
            
        return " - ".join(components) if components else "Processing..."
        
    def _format_speed(self, speed_bytes: float) -> str:
        """Format speed in bytes/sec to human readable format."""
        if speed_bytes < 1024:
            return f"{speed_bytes:.1f} B/s"
        elif speed_bytes < 1024 * 1024:
            return f"{speed_bytes / 1024:.1f} KB/s"
        elif speed_bytes < 1024 * 1024 * 1024:
            return f"{speed_bytes / (1024 * 1024):.1f} MB/s"
        else:
            return f"{speed_bytes / (1024 * 1024 * 1024):.1f} GB/s"
            
    def reset(self):
        """Reset all progress tracking."""
        self._downloads.clear()
        self._completed_downloads.clear()
        self._recent_speeds.clear()
        self._last_update_time = 0.0 