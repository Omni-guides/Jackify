"""
AppImage utilities for self-updating functionality.

This module provides utilities for detecting if Jackify is running as an AppImage
and getting the path to the current AppImage file.
"""

import os
import sys
from pathlib import Path
from typing import Optional


def is_appimage() -> bool:
    """
    Check if Jackify is currently running as an AppImage.
    
    Returns:
        bool: True if running as AppImage, False otherwise
    """
    return 'APPIMAGE' in os.environ


def get_appimage_path() -> Optional[Path]:
    """
    Get the path to the current AppImage file.
    
    This uses the APPIMAGE environment variable set by the AppImage runtime.
    This is the standard, reliable method for AppImage path detection.
    
    Returns:
        Optional[Path]: Path to the AppImage file if running as AppImage, None otherwise
    """
    if not is_appimage():
        return None
    
    appimage_path = os.environ.get('APPIMAGE')
    if appimage_path and os.path.exists(appimage_path):
        return Path(appimage_path)
    
    return None


def can_self_update() -> bool:
    """
    Check if self-updating is possible.
    
    Returns:
        bool: True if self-updating is possible, False otherwise
    """
    appimage_path = get_appimage_path()
    if not appimage_path:
        return False
    
    # Check if we can write to the AppImage file (for replacement)
    try:
        return os.access(appimage_path, os.W_OK)
    except (OSError, PermissionError):
        return False


def get_appimage_info() -> dict:
    """
    Get information about the current AppImage.
    
    Returns:
        dict: Information about the AppImage including path, writability, etc.
    """
    appimage_path = get_appimage_path()
    
    info = {
        'is_appimage': is_appimage(),
        'path': appimage_path,
        'can_update': can_self_update(),
        'size_mb': None,
        'writable': False
    }
    
    if appimage_path and appimage_path.exists():
        try:
            stat = appimage_path.stat()
            info['size_mb'] = round(stat.st_size / (1024 * 1024), 1)
            info['writable'] = os.access(appimage_path, os.W_OK)
        except (OSError, PermissionError):
            pass
    
    return info