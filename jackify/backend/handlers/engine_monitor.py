"""
Engine Performance Monitor

Monitors the jackify-engine process for performance issues like CPU stalls,
memory problems, and excessive I/O wait times.
"""

import time
import threading
import psutil
import logging
import os
from typing import Optional, Dict, Any, Callable
from dataclasses import dataclass
from enum import Enum


class PerformanceState(Enum):
    NORMAL = "normal"
    STALLED = "stalled"
    HIGH_MEMORY = "high_memory"
    HIGH_IO_WAIT = "high_io_wait"
    ZOMBIE = "zombie"


@dataclass
class PerformanceMetrics:
    timestamp: float
    cpu_percent: float
    memory_percent: float
    memory_mb: float
    io_read_mb: float
    io_write_mb: float
    thread_count: int
    fd_count: int
    state: PerformanceState
    
    # Additional diagnostics for engine vs wrapper distinction
    parent_cpu_percent: Optional[float] = None
    parent_memory_mb: Optional[float] = None
    engine_responsive: bool = True
    
    # New: ImageMagick resource usage
    magick_cpu_percent: float = 0.0
    magick_memory_mb: float = 0.0
    
    
class EnginePerformanceMonitor:
    """
    Monitors jackify-engine process performance and detects common stall patterns.
    
    This is designed to help diagnose the issue where extraction starts at 80-100% CPU
    but drops to 2% after ~5 minutes and requires manual kills.
    
    Also monitors parent Python process to distinguish between engine vs wrapper issues.
    """
    
    def __init__(self, 
                 logger: Optional[logging.Logger] = None,
                 stall_threshold: float = 5.0,  # CPU below this % for stall_duration = stall
                 stall_duration: float = 120.0,  # seconds of low CPU = stall
                 memory_threshold: float = 85.0,  # % memory usage threshold
                 sample_interval: float = 5.0):  # seconds between samples
        
        self.logger = logger or logging.getLogger(__name__)
        self.stall_threshold = stall_threshold
        self.stall_duration = stall_duration
        self.memory_threshold = memory_threshold
        self.sample_interval = sample_interval
        
        self._process: Optional[psutil.Process] = None
        self._parent_process: Optional[psutil.Process] = None
        self._monitoring = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._metrics_history: list[PerformanceMetrics] = []
        self._callbacks: list[Callable[[PerformanceMetrics], None]] = []
        
        # Performance state tracking
        self._low_cpu_start_time: Optional[float] = None
        self._last_io_read = 0
        self._last_io_write = 0
        
    def add_callback(self, callback: Callable[[PerformanceMetrics], None]):
        """Add a callback to receive performance metrics updates."""
        self._callbacks.append(callback)
        
    def start_monitoring(self, pid: int) -> bool:
        """Start monitoring the given process ID."""
        try:
            self._process = psutil.Process(pid)
            
            # Also monitor the parent Python process for comparison
            try:
                self._parent_process = psutil.Process(os.getpid())
            except:
                self._parent_process = None
                
            self._monitoring = True
            self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self._monitor_thread.start()
            
            process_name = self._process.name() if self._process else "unknown"
            self.logger.info(f"Started performance monitoring for PID {pid} ({process_name}) "
                           f"(stall threshold: {self.stall_threshold}% CPU for {self.stall_duration}s)")
            return True
            
        except psutil.NoSuchProcess:
            self.logger.error(f"Process {pid} not found")
            return False
        except Exception as e:
            self.logger.error(f"Failed to start monitoring PID {pid}: {e}")
            return False
            
    def stop_monitoring(self):
        """Stop monitoring the process."""
        self._monitoring = False
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=10)
            
    def get_metrics_summary(self) -> Dict[str, Any]:
        """Get a summary of collected metrics."""
        if not self._metrics_history:
            return {}
            
        cpu_values = [m.cpu_percent for m in self._metrics_history]
        memory_values = [m.memory_mb for m in self._metrics_history]
        
        stalled_count = sum(1 for m in self._metrics_history if m.state == PerformanceState.STALLED)
        
        # Engine vs wrapper analysis
        engine_avg_cpu = sum(cpu_values) / len(cpu_values)
        parent_cpu_values = [m.parent_cpu_percent for m in self._metrics_history if m.parent_cpu_percent is not None]
        parent_avg_cpu = sum(parent_cpu_values) / len(parent_cpu_values) if parent_cpu_values else 0
        
        return {
            "total_samples": len(self._metrics_history),
            "monitoring_duration": self._metrics_history[-1].timestamp - self._metrics_history[0].timestamp,
            
            # Engine process metrics
            "engine_avg_cpu_percent": engine_avg_cpu,
            "engine_max_cpu_percent": max(cpu_values),
            "engine_min_cpu_percent": min(cpu_values),
            "engine_avg_memory_mb": sum(memory_values) / len(memory_values),
            "engine_max_memory_mb": max(memory_values),
            
            # Parent process metrics (for comparison)
            "parent_avg_cpu_percent": parent_avg_cpu,
            
            # Stall analysis
            "stalled_samples": stalled_count,
            "stall_percentage": (stalled_count / len(self._metrics_history)) * 100,
            
            # Diagnosis hints
            "likely_engine_issue": engine_avg_cpu < 10 and parent_avg_cpu < 5,
            "likely_wrapper_issue": engine_avg_cpu > 20 and parent_avg_cpu > 50,
        }
        
    def _monitor_loop(self):
        """Main monitoring loop."""
        while self._monitoring:
            try:
                if not self._process or not self._process.is_running():
                    self.logger.warning("Monitored engine process is no longer running")
                    break
                    
                metrics = self._collect_metrics()
                self._metrics_history.append(metrics)
                
                # Notify callbacks
                for callback in self._callbacks:
                    try:
                        callback(metrics)
                    except Exception as e:
                        self.logger.error(f"Error in performance callback: {e}")
                        
                # Log significant events with engine vs wrapper context
                if metrics.state == PerformanceState.STALLED:
                    parent_info = ""
                    if metrics.parent_cpu_percent is not None:
                        parent_info = f", Python wrapper: {metrics.parent_cpu_percent:.1f}% CPU"
                        
                    self.logger.warning(f"🚨 ENGINE STALL DETECTED: jackify-engine CPU at {metrics.cpu_percent:.1f}% "
                                      f"for {self.stall_duration}s+ (Memory: {metrics.memory_mb:.1f}MB, "
                                      f"Threads: {metrics.thread_count}, FDs: {metrics.fd_count}{parent_info})")
                    
                    # Provide diagnosis hint
                    if metrics.parent_cpu_percent and metrics.parent_cpu_percent > 10:
                        self.logger.warning("Warning: Python wrapper still active - likely jackify-engine (.NET) issue")
                    else:
                        self.logger.warning("Warning: Both processes low CPU - possible system-wide issue")
                                      
                elif metrics.state == PerformanceState.HIGH_MEMORY:
                    self.logger.warning(f"HIGH MEMORY USAGE in jackify-engine: {metrics.memory_percent:.1f}% "
                                      f"({metrics.memory_mb:.1f}MB)")
                                      
                time.sleep(self.sample_interval)
                
            except psutil.NoSuchProcess:
                self.logger.info("Monitored engine process terminated")
                break
            except Exception as e:
                self.logger.error(f"Error in monitoring loop: {e}")
                time.sleep(self.sample_interval)
                
    def _collect_metrics(self) -> PerformanceMetrics:
        """Collect current performance metrics."""
        now = time.time()
        
        # Get basic process info for engine
        cpu_percent = self._process.cpu_percent()
        memory_info = self._process.memory_info()
        memory_mb = memory_info.rss / (1024 * 1024)
        memory_percent = self._process.memory_percent()
        
        # Get parent process info for comparison
        parent_cpu_percent = None
        parent_memory_mb = None
        if self._parent_process:
            try:
                parent_cpu_percent = self._parent_process.cpu_percent()
                parent_memory_info = self._parent_process.memory_info()
                parent_memory_mb = parent_memory_info.rss / (1024 * 1024)
            except:
                pass
        
        # Get I/O info
        try:
            io_counters = self._process.io_counters()
            io_read_mb = io_counters.read_bytes / (1024 * 1024)
            io_write_mb = io_counters.write_bytes / (1024 * 1024)
        except (psutil.AccessDenied, AttributeError):
            io_read_mb = 0
            io_write_mb = 0
            
        # Get thread and file descriptor counts
        try:
            thread_count = self._process.num_threads()
        except (psutil.AccessDenied, AttributeError):
            thread_count = 0
            
        try:
            fd_count = self._process.num_fds()
        except (psutil.AccessDenied, AttributeError):
            fd_count = 0
            
        # Determine performance state
        state = self._determine_state(cpu_percent, memory_percent, now)
        
        # New: Aggregate ImageMagick ('magick') child process usage
        magick_cpu = 0.0
        magick_mem = 0.0
        try:
            for child in self._process.children(recursive=True):
                try:
                    if child.name() == 'magick' or 'magick' in ' '.join(child.cmdline()):
                        magick_cpu += child.cpu_percent()
                        magick_mem += child.memory_info().rss / (1024 * 1024)
                except Exception:
                    continue
        except Exception:
            pass
        
        return PerformanceMetrics(
            timestamp=now,
            cpu_percent=cpu_percent,
            memory_percent=memory_percent,
            memory_mb=memory_mb,
            io_read_mb=io_read_mb,
            io_write_mb=io_write_mb,
            thread_count=thread_count,
            fd_count=fd_count,
            state=state,
            parent_cpu_percent=parent_cpu_percent,
            parent_memory_mb=parent_memory_mb,
            engine_responsive=cpu_percent > self.stall_threshold or (now - self._low_cpu_start_time if self._low_cpu_start_time else 0) < self.stall_duration,
            magick_cpu_percent=magick_cpu,
            magick_memory_mb=magick_mem
        )
        
    def _determine_state(self, cpu_percent: float, memory_percent: float, timestamp: float) -> PerformanceState:
        """Determine the current performance state."""
        
        # Check for high memory usage
        if memory_percent > self.memory_threshold:
            return PerformanceState.HIGH_MEMORY
            
        # Check for CPU stall
        if cpu_percent < self.stall_threshold:
            if self._low_cpu_start_time is None:
                self._low_cpu_start_time = timestamp
            elif timestamp - self._low_cpu_start_time >= self.stall_duration:
                return PerformanceState.STALLED
        else:
            # CPU is above threshold, reset stall timer
            self._low_cpu_start_time = None
            
        return PerformanceState.NORMAL


def create_debug_callback(logger: logging.Logger) -> Callable[[PerformanceMetrics], None]:
    """Create a callback that logs detailed performance metrics for debugging."""
    
    def debug_callback(metrics: PerformanceMetrics):
        parent_info = f", Python: {metrics.parent_cpu_percent:.1f}%" if metrics.parent_cpu_percent else ""
        magick_info = f", Magick: {metrics.magick_cpu_percent:.1f}% CPU, {metrics.magick_memory_mb:.1f}MB RAM" if metrics.magick_cpu_percent or metrics.magick_memory_mb else ""
        logger.debug(f"Engine Performance: jackify-engine CPU={metrics.cpu_percent:.1f}%, "
                    f"Memory={metrics.memory_mb:.1f}MB ({metrics.memory_percent:.1f}%), "
                    f"Threads={metrics.thread_count}, FDs={metrics.fd_count}, "
                    f"State={metrics.state.value}{parent_info}{magick_info}")
                    
    return debug_callback


def create_stall_alert_callback(logger: logging.Logger, 
                               alert_func: Optional[Callable[[str], None]] = None
                               ) -> Callable[[PerformanceMetrics], None]:
    """Create a callback that alerts when performance issues are detected."""
    
    def alert_callback(metrics: PerformanceMetrics):
        if metrics.state in [PerformanceState.STALLED, PerformanceState.HIGH_MEMORY]:
            
            # Provide context about engine vs wrapper
            if metrics.state == PerformanceState.STALLED:
                if metrics.parent_cpu_percent and metrics.parent_cpu_percent > 10:
                    issue_type = "jackify-engine (.NET binary) stalled"
                else:
                    issue_type = "system-wide performance issue"
            else:
                issue_type = metrics.state.value.upper()
                
            message = (f"{issue_type} - Engine CPU: {metrics.cpu_percent:.1f}%, "
                      f"Memory: {metrics.memory_mb:.1f}MB")
            
            logger.warning(message)
            if alert_func:
                alert_func(message)
                
    return alert_callback 