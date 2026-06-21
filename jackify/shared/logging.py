"""
LoggingHandler module for managing logging operations.
This module handles log file creation, rotation, and management.
"""

import os
import logging
import logging.handlers
from pathlib import Path
from typing import Optional, Dict, List
from datetime import datetime
import shutil
import sys

class LoggingHandler:
    """
    Central logging handler for Jackify.
    - Uses configured Jackify data directory for logs (default: ~/Jackify/logs/).
    - Supports per-function log files (e.g., jackify-install-wabbajack.log).
    - Handles log rotation and log directory creation.
    Usage:
        logger = LoggingHandler().setup_logger('install_wabbajack', 'jackify-install-wabbajack.log')
    """
    def __init__(self):
        # Don't cache log_dir - use property to get fresh path each time
        self.ensure_log_directory()
    
    @property
    def log_dir(self):
        """Get the current log directory (may change if config updated)."""
        from jackify.shared.paths import get_jackify_logs_dir
        return get_jackify_logs_dir()
        
    def ensure_log_directory(self) -> None:
        """Ensure the log directory exists."""
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            sys.stderr.write(f"Failed to create log directory: {e}\n")
            
    def rotate_log_file_per_run(self, log_file_path: Path, backup_count: int = 5):
        """Rotate the log file on every run, keeping up to backup_count backups."""
        if log_file_path.exists():
            # Remove the oldest backup if it exists
            oldest = log_file_path.with_suffix(log_file_path.suffix + f'.{backup_count}')
            if oldest.exists():
                oldest.unlink()
            # Shift backups
            for i in range(backup_count - 1, 0, -1):
                src = log_file_path.with_suffix(log_file_path.suffix + f'.{i}')
                dst = log_file_path.with_suffix(log_file_path.suffix + f'.{i+1}')
                if src.exists():
                    src.rename(dst)
            # Move current log to .1
            log_file_path.rename(log_file_path.with_suffix(log_file_path.suffix + '.1'))

    def rotate_log_for_logger(self, name: str, log_file: Optional[str] = None, backup_count: int = 5):
        """
        Rotate the log file for a logger before any logging occurs.
        Must be called BEFORE any log is written or file handler is attached.
        """
        file_path = self.log_dir / (log_file if log_file else "jackify-cli.log")
        self.rotate_log_file_per_run(file_path, backup_count=backup_count)

    def setup_logger(self, name: str, log_file: Optional[str] = None, is_general: bool = False, debug_mode: Optional[bool] = None) -> logging.Logger:
        """Set up a logger with file and console handlers. Call rotate_log_for_logger before this if you want per-run rotation.
        
        Args:
            name: Logger name (empty string for root logger)
            log_file: Optional log file name
            is_general: If True, use default log file name
            debug_mode: Optional debug mode override. If None, reads from config.
        """
        logger = logging.getLogger(name)
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
        
        # Create formatters
        file_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        console_formatter = logging.Formatter(
            '%(levelname)s: %(message)s'
        )
        
        # Add console handler - use provided debug_mode or check config
        console_handler = logging.StreamHandler()
        
        if debug_mode is None:
            # Check if debug mode is enabled from config
            try:
                from jackify.backend.handlers.config_handler import ConfigHandler
                config_handler = ConfigHandler()
                debug_mode = config_handler.get('debug_mode', False)
            except Exception:
                debug_mode = False
        
        if debug_mode:
            console_handler.setLevel(logging.DEBUG)
        else:
            console_handler.setLevel(logging.ERROR)
        console_handler.setFormatter(console_formatter)
        if not any(isinstance(h, logging.StreamHandler) for h in logger.handlers):
            logger.addHandler(console_handler)
        
        # Add file handler if log_file is specified, or use default for general
        if log_file or is_general:
            file_path = self.log_dir / (log_file if log_file else "jackify-cli.log")
            file_handler = logging.handlers.RotatingFileHandler(
                file_path, mode='a', encoding='utf-8', maxBytes=100*1024*1024, backupCount=5
            )
            # File handler always accepts DEBUG - root logger level controls what gets through
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(file_formatter)
            if not any(isinstance(h, logging.handlers.RotatingFileHandler) and getattr(h, 'baseFilename', None) == str(file_path) for h in logger.handlers):
                logger.addHandler(file_handler)
            
        return logger
        
    def rotate_logs(self, max_bytes: int = 100 * 1024 * 1024, backup_count: int = 5) -> None:
        """Rotate log files based on size."""
        for log_file in self.get_log_files():
            try:
                if log_file.stat().st_size > max_bytes:
                    # Create backup
                    backup_path = log_file.with_suffix(f'.{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
                    log_file.rename(backup_path)
                    
                    # Clean up old backups
                    backups = sorted(log_file.parent.glob(f"{log_file.stem}.*.log"))
                    if len(backups) > backup_count:
                        for old_backup in backups[:-backup_count]:
                            old_backup.unlink()
            except Exception as e:
                sys.stderr.write(f"Failed to rotate log file {log_file}: {e}\n")
                
    def cleanup_old_logs(self, days: int = 30) -> None:
        """Clean up log files older than specified days."""
        cutoff = datetime.now().timestamp() - (days * 24 * 60 * 60)
        for log_file in self.get_log_files():
            try:
                if log_file.stat().st_mtime < cutoff:
                    log_file.unlink()
            except Exception as e:
                sys.stderr.write(f"Failed to clean up log file {log_file}: {e}\n")
                
    def get_log_files(self) -> List[Path]:
        """Get a list of all log files."""
        return list(self.log_dir.glob("*.log"))
        
    def get_log_content(self, log_file: Path, lines: int = 100) -> List[str]:
        """Get the last N lines of a log file."""
        try:
            with open(log_file, 'r') as f:
                return f.readlines()[-lines:]
        except Exception as e:
            sys.stderr.write(f"Failed to read log file {log_file}: {e}\n")
            return []
            
    def search_logs(self, pattern: str) -> Dict[Path, List[str]]:
        """Search all log files for a pattern."""
        results = {}
        for log_file in self.get_log_files():
            try:
                with open(log_file, 'r') as f:
                    matches = [line for line in f if pattern in line]
                    if matches:
                        results[log_file] = matches
            except Exception as e:
                sys.stderr.write(f"Failed to search log file {log_file}: {e}\n")
        return results
        
    def export_logs(self, output_dir: Path) -> bool:
        """Export all logs to a directory."""
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            for log_file in self.get_log_files():
                shutil.copy2(log_file, output_dir / log_file.name)
            return True
        except Exception as e:
            sys.stderr.write(f"Failed to export logs: {e}\n")
            return False
            
    def set_log_level(self, level: int) -> None:
        """Set the logging level for all loggers."""
        for logger_name in logging.root.manager.loggerDict:
            logger = logging.getLogger(logger_name)
            logger.setLevel(level)
            
    def get_log_stats(self) -> Dict:
        """Get statistics about log files."""
        stats = {
            'total_files': 0,
            'total_size': 0,
            'largest_file': None,
            'oldest_file': None,
            'newest_file': None
        }
        
        try:
            log_files = self.get_log_files()
            stats['total_files'] = len(log_files)
            
            if log_files:
                stats['total_size'] = sum(f.stat().st_size for f in log_files)
                stats['largest_file'] = max(log_files, key=lambda x: x.stat().st_size)
                stats['oldest_file'] = min(log_files, key=lambda x: x.stat().st_mtime)
                stats['newest_file'] = max(log_files, key=lambda x: x.stat().st_mtime)
                
        except Exception as e:
            sys.stderr.write(f"Failed to get log stats: {e}\n")
            
        return stats 

    def get_general_logger(self):
        """Get the general CLI logger ({jackify_data_dir}/logs/jackify-cli.log)."""
        return self.setup_logger('jackify_cli', is_general=True)

    def setup_application_logging(self, debug_mode: bool = False) -> logging.Logger:
        """Configure the root logger for the application.

        Always-on: jackify.log at INFO level.
        Debug mode only: jackify-debug.log at DEBUG level.
        Console: WARNING in both modes.

        Call once at application startup before any other loggers are created.
        """
        root = logging.getLogger()
        # Clear any handlers set by basicConfig or previous calls
        root.handlers.clear()
        # Root must pass everything through - handlers do the filtering
        root.setLevel(logging.DEBUG)
        root.propagate = False

        file_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        console_formatter = logging.Formatter('%(levelname)s: %(message)s')

        # Always-on application log at INFO - rotate on every startup, keep 5
        app_log_path = self.log_dir / 'jackify.log'
        self.rotate_log_file_per_run(app_log_path)
        app_handler = logging.handlers.RotatingFileHandler(
            app_log_path, mode='a', encoding='utf-8',
            maxBytes=10 * 1024 * 1024, backupCount=5
        )
        app_handler.setLevel(logging.INFO)
        app_handler.setFormatter(file_formatter)
        root.addHandler(app_handler)

        # Debug log only when explicitly enabled
        if debug_mode:
            debug_log_path = self.log_dir / 'jackify-debug.log'
            self.rotate_log_file_per_run(debug_log_path)
            debug_handler = logging.handlers.RotatingFileHandler(
                debug_log_path, mode='a', encoding='utf-8',
                maxBytes=100 * 1024 * 1024, backupCount=5
            )
            debug_handler.setLevel(logging.DEBUG)
            debug_handler.setFormatter(file_formatter)
            root.addHandler(debug_handler)

        # Console: DEBUG in debug mode, ERROR otherwise
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG if debug_mode else logging.ERROR)
        console_handler.setFormatter(console_formatter)
        root.addHandler(console_handler)

        return root