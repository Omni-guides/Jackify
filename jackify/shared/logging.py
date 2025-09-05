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

class LoggingHandler:
    """
    Central logging handler for Jackify.
    - Uses ~/Jackify/logs/ as the log directory.
    - Supports per-function log files (e.g., jackify-install-wabbajack.log).
    - Handles log rotation and log directory creation.
    Usage:
        logger = LoggingHandler().setup_logger('install_wabbajack', 'jackify-install-wabbajack.log')
    """
    def __init__(self):
        self.log_dir = Path.home() / "Jackify" / "logs"
        self.ensure_log_directory()
        
    def ensure_log_directory(self) -> None:
        """Ensure the log directory exists."""
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            print(f"Failed to create log directory: {e}")
            
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

    def setup_logger(self, name: str, log_file: Optional[str] = None, is_general: bool = False) -> logging.Logger:
        """Set up a logger with file and console handlers. Call rotate_log_for_logger before this if you want per-run rotation."""
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
        
        # Add console handler - check debug mode from config
        console_handler = logging.StreamHandler()
        
        # Check if debug mode is enabled
        try:
            from jackify.backend.handlers.config_handler import ConfigHandler
            config_handler = ConfigHandler()
            debug_mode = config_handler.get('debug_mode', False)
            if debug_mode:
                console_handler.setLevel(logging.DEBUG)
            else:
                console_handler.setLevel(logging.ERROR)
        except Exception:
            # Fallback to ERROR level if config can't be loaded
            console_handler.setLevel(logging.ERROR)
        console_handler.setFormatter(console_formatter)
        if not any(isinstance(h, logging.StreamHandler) for h in logger.handlers):
            logger.addHandler(console_handler)
        
        # Add file handler if log_file is specified, or use default for general
        if log_file or is_general:
            file_path = self.log_dir / (log_file if log_file else "jackify-cli.log")
            file_handler = logging.handlers.RotatingFileHandler(
                file_path, mode='a', encoding='utf-8', maxBytes=1024*1024, backupCount=5
            )
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(file_formatter)
            if not any(isinstance(h, logging.handlers.RotatingFileHandler) and getattr(h, 'baseFilename', None) == str(file_path) for h in logger.handlers):
                logger.addHandler(file_handler)
            
        return logger
        
    def rotate_logs(self, max_bytes: int = 1024 * 1024, backup_count: int = 5) -> None:
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
                print(f"Failed to rotate log file {log_file}: {e}")
                
    def cleanup_old_logs(self, days: int = 30) -> None:
        """Clean up log files older than specified days."""
        cutoff = datetime.now().timestamp() - (days * 24 * 60 * 60)
        for log_file in self.get_log_files():
            try:
                if log_file.stat().st_mtime < cutoff:
                    log_file.unlink()
            except Exception as e:
                print(f"Failed to clean up log file {log_file}: {e}")
                
    def get_log_files(self) -> List[Path]:
        """Get a list of all log files."""
        return list(self.log_dir.glob("*.log"))
        
    def get_log_content(self, log_file: Path, lines: int = 100) -> List[str]:
        """Get the last N lines of a log file."""
        try:
            with open(log_file, 'r') as f:
                return f.readlines()[-lines:]
        except Exception as e:
            print(f"Failed to read log file {log_file}: {e}")
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
                print(f"Failed to search log file {log_file}: {e}")
        return results
        
    def export_logs(self, output_dir: Path) -> bool:
        """Export all logs to a directory."""
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            for log_file in self.get_log_files():
                shutil.copy2(log_file, output_dir / log_file.name)
            return True
        except Exception as e:
            print(f"Failed to export logs: {e}")
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
            print(f"Failed to get log stats: {e}")
            
        return stats 

    def get_general_logger(self):
        """Get the general CLI logger (~/Jackify/logs/jackify-cli.log)."""
        return self.setup_logger('jackify_cli', is_general=True) 