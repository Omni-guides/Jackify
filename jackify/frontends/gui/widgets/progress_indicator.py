"""
Progress Indicator Widget

Enhanced status banner widget that displays overall installation progress.
R&D NOTE: This is experimental code for investigation purposes.
"""

from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QProgressBar, QSizePolicy
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from jackify.shared.progress_models import InstallationProgress
from ..shared_theme import JACKIFY_COLOR_BLUE


class OverallProgressIndicator(QWidget):
    """
    Enhanced progress indicator widget showing:
    - Phase name
    - Step progress [12/14]
    - Data progress (1.1GB/56.3GB)
    - Overall percentage
    - Optional progress bar
    """
    
    def __init__(self, parent=None, show_progress_bar=True):
        """
        Initialize progress indicator.
        
        Args:
            parent: Parent widget
            show_progress_bar: If True, show visual progress bar in addition to text
        """
        super().__init__(parent)
        self.show_progress_bar = show_progress_bar
        self._setup_ui()
    
    def _setup_ui(self):
        """Set up the UI components."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        
        # Status text label (similar to TTW status banner)
        self.status_label = QLabel("Ready to install")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet(f"""
            background-color: #2a2a2a;
            color: {JACKIFY_COLOR_BLUE};
            padding: 6px 8px;
            border-radius: 4px;
            font-weight: bold;
            font-size: 13px;
        """)
        self.status_label.setMaximumHeight(34)
        self.status_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        
        # Progress bar (optional, shown below or integrated)
        if self.show_progress_bar:
            self.progress_bar = QProgressBar()
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat("%p%")
            # Use white text with shadow/outline effect for readability on both dark and blue backgrounds
            self.progress_bar.setStyleSheet(f"""
                QProgressBar {{
                    border: 1px solid #444;
                    border-radius: 4px;
                    text-align: center;
                    background-color: #1a1a1a;
                    color: #fff;
                    font-weight: bold;
                    height: 20px;
                }}
                QProgressBar::chunk {{
                    background-color: {JACKIFY_COLOR_BLUE};
                    border-radius: 3px;
                }}
            """)
            self.progress_bar.setMaximumHeight(20)
            self.progress_bar.setVisible(True)
        
        # Layout: text on left, progress bar on right (or stacked)
        if self.show_progress_bar:
            # Horizontal layout: status text takes available space, progress bar fixed width
            layout.addWidget(self.status_label, 1)
            layout.addWidget(self.progress_bar, 0)  # Fixed width
            self.progress_bar.setFixedWidth(100)  # Fixed width for progress bar
        else:
            # Just the status label, full width
            layout.addWidget(self.status_label, 1)
        
        # Constrain widget height to prevent unwanted vertical expansion
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMaximumHeight(34)  # Match status label height
    
    def update_progress(self, progress: InstallationProgress):
        """
        Update the progress indicator with new progress state.
        
        Args:
            progress: InstallationProgress object with current state
        """
        # Update status text
        display_text = progress.display_text
        from jackify.shared.progress_models import InstallationPhase, FileProgress
        # CLF3 Status events populate progress.message with detail not captured by display_text.
        # Use the message directly when display_text is just the bare phase label.
        if (
            progress.message
            and progress.message not in ("Processing...", "")
            and display_text in (progress.phase_name, progress.phase.value.title() if progress.phase else "", "Processing...", "")
        ):
            display_text = progress.message
        if not display_text or display_text == "Processing...":
            if progress.phase == InstallationPhase.UNKNOWN:
                # Don't overwrite the banner with "Unknown" for unrecognized section headers;
                # preserve whatever was showing before.
                current = self.status_label.text()
                if current and current not in ("Ready to install", "Unknown", "Processing...", ""):
                    display_text = current
                else:
                    display_text = "Processing..."
            else:
                display_text = progress.phase_name or progress.phase.value.title() or "Processing..."
        if progress.phase == InstallationPhase.DOWNLOAD and progress.phase_max_steps > 0 and progress.phase_step <= 0:
            display_text = display_text.replace(f"[{progress.phase_step}/{progress.phase_max_steps}]", "").replace("  ", " ").strip()

        # Add total download size, remaining size (MB/GB), and ETA for download phase
        if progress.phase == InstallationPhase.DOWNLOAD:
            # Try to get overall download totals - either from data_total or aggregate from active_files
            total_bytes = progress.data_total
            processed_bytes = progress.data_processed
            using_aggregated = False
            
            # If data_total is 0, try to aggregate from active_files
            if total_bytes == 0 and progress.active_files:
                total_bytes = sum(f.total_size for f in progress.active_files if f.total_size > 0)
                processed_bytes = sum(f.current_size for f in progress.active_files if f.current_size > 0)
                using_aggregated = True
            
            # Add remaining download size (MB or GB) if available
            if total_bytes > 0:
                remaining_bytes = total_bytes - processed_bytes
                if remaining_bytes > 0:
                    # Format as MB if less than 1GB, otherwise GB
                    if remaining_bytes < (1024.0 ** 3):
                        remaining_mb = remaining_bytes / (1024.0 ** 2)
                        display_text += f" | {remaining_mb:.1f}MB remaining"
                    else:
                        remaining_gb = remaining_bytes / (1024.0 ** 3)
                        display_text += f" | {remaining_gb:.1f}GB remaining"
                    
                    # Calculate ETA - prefer aggregated calculation for concurrent downloads
                    eta_seconds = -1.0
                    if using_aggregated:
                        # For concurrent downloads: sum all active download speeds (not average)
                        # Combined throughput
                        active_speeds = [f.speed for f in progress.active_files if f.speed > 0]
                        if active_speeds:
                            combined_speed = sum(active_speeds)  # Sum speeds for concurrent downloads
                            if combined_speed > 0:
                                eta_seconds = remaining_bytes / combined_speed
                    else:
                        # Use the standard ETA calculation from progress model
                        eta_seconds = progress.get_eta_seconds(use_smoothing=True)
                    
                    # Format and display ETA
                    if eta_seconds > 0:
                        if eta_seconds < 60:
                            display_text += f" | ETA: {int(eta_seconds)}s"
                        elif eta_seconds < 3600:
                            mins = int(eta_seconds // 60)
                            secs = int(eta_seconds % 60)
                            if secs > 0:
                                display_text += f" | ETA: {mins}m {secs}s"
                            else:
                                display_text += f" | ETA: {mins}m"
                        else:
                            hours = int(eta_seconds // 3600)
                            mins = int((eta_seconds % 3600) // 60)
                            if mins > 0:
                                display_text += f" | ETA: {hours}h {mins}m"
                            else:
                                display_text += f" | ETA: {hours}h"
            else:
                # No total size available - try to show ETA if we have speed info from active files
                if progress.active_files:
                    active_speeds = [f.speed for f in progress.active_files if f.speed > 0]
                    if active_speeds:
                        # Can't calculate accurate ETA without total size, but could show speed
                        pass
                # Fallback to standard ETA if available
                if not using_aggregated:
                    eta_display = progress.eta_display
                    if eta_display:
                        display_text += f" | ETA: {eta_display}"
        
        self.status_label.setText(display_text)
        
        # Update progress bar if enabled
        if self.show_progress_bar and hasattr(self, 'progress_bar'):
            # Calculate progress - prioritize data progress, then step progress, then overall_percent
            display_percent = 0.0
            
            # Check if we're in BSA building phase (detected by phase label)
            from jackify.shared.progress_models import InstallationPhase
            is_bsa_building = progress.get_phase_label() == "Building BSAs"
            
            # Download phase often has byte-level progress before step counters move.
            # Prefer byte progress first to avoid misleading 0% while downloading.
            if progress.phase == InstallationPhase.DOWNLOAD:
                if progress.data_total > 0:
                    display_percent = (progress.data_processed / progress.data_total) * 100.0
                elif progress.active_files:
                    aggregate_total = sum(f.total_size for f in progress.active_files if f.total_size > 0)
                    aggregate_current = sum(f.current_size for f in progress.active_files if f.current_size > 0)
                    if aggregate_total > 0:
                        display_percent = (aggregate_current / aggregate_total) * 100.0
                if display_percent <= 0 and progress.phase_max_steps > 0 and progress.phase_step > 0:
                    display_percent = (progress.phase_step / progress.phase_max_steps) * 100.0
                elif display_percent <= 0 and progress.overall_percent > 0 and progress.overall_percent < 100.0:
                    display_percent = progress.overall_percent
            # For install/extract/BSA phases, prefer step progress, then bytes.
            elif progress.phase in (InstallationPhase.INSTALL, InstallationPhase.EXTRACT) or is_bsa_building:
                if progress.phase_max_steps > 0:
                    display_percent = (progress.phase_step / progress.phase_max_steps) * 100.0
                elif progress.data_total > 0 and progress.data_processed > 0:
                    display_percent = (progress.data_processed / progress.data_total) * 100.0
                elif progress.overall_percent > 0 and progress.overall_percent < 100.0:
                    display_percent = progress.overall_percent
                else:
                    display_percent = 0.0  # Reset if we don't have valid progress
            else:
                # For other phases, prefer data progress, then overall_percent, then step progress
                if progress.data_total > 0 and progress.data_processed > 0:
                    display_percent = (progress.data_processed / progress.data_total) * 100.0
                elif progress.overall_percent > 0:
                    display_percent = progress.overall_percent
                elif progress.phase_max_steps > 0:
                    display_percent = (progress.phase_step / progress.phase_max_steps) * 100.0
            
            # Clamp to avoid transient parser values creating invalid percentages.
            display_percent = max(0.0, min(100.0, display_percent))
            self.progress_bar.setValue(int(display_percent))
            
            # Update tooltip with detailed information
            tooltip_parts = []
            if progress.phase_name:
                tooltip_parts.append(f"Phase: {progress.phase_name}")
            if progress.phase_progress_text:
                tooltip_parts.append(f"Step: {progress.phase_progress_text}")
            if progress.data_progress_text:
                tooltip_parts.append(f"Data: {progress.data_progress_text}")
            
            # Add total download size in GB for download phase
            from jackify.shared.progress_models import InstallationPhase
            if progress.phase == InstallationPhase.DOWNLOAD and progress.data_total > 0:
                total_gb = progress.total_download_size_gb
                remaining_gb = progress.remaining_download_size_gb
                if total_gb > 0:
                    tooltip_parts.append(f"Total Download: {total_gb:.2f}GB")
                if remaining_gb > 0:
                    tooltip_parts.append(f"Remaining: {remaining_gb:.2f}GB")
            
            # Add ETA for download phase
            if progress.phase == InstallationPhase.DOWNLOAD:
                eta_display = progress.eta_display
                if eta_display:
                    tooltip_parts.append(f"Estimated Time Remaining: {eta_display}")
            
            if progress.overall_percent > 0:
                tooltip_parts.append(f"Overall: {progress.overall_percent:.1f}%")
            
            if tooltip_parts:
                self.progress_bar.setToolTip("\n".join(tooltip_parts))
                self.status_label.setToolTip("\n".join(tooltip_parts))
    
    def set_status(self, text: str, percent: int = None):
        """
        Set status text directly without full progress update.

        Args:
            text: Status text to display
            percent: Optional progress percentage (0-100)
        """
        self.status_label.setText(text)
        if percent is not None and self.show_progress_bar and hasattr(self, 'progress_bar'):
            self.progress_bar.setValue(int(percent))

    def reset(self):
        """Reset the progress indicator to initial state."""
        self.status_label.setText("Ready to install")
        if self.show_progress_bar and hasattr(self, 'progress_bar'):
            self.progress_bar.setValue(0)
            self.progress_bar.setToolTip("")
            self.status_label.setToolTip("")
