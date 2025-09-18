"""
Path utilities for Jackify.

This module provides standardized path resolution for Jackify directories,
supporting configurable data directory while keeping config in a fixed location.
"""

import os
from pathlib import Path
from typing import Optional


def get_jackify_data_dir() -> Path:
    """
    Get the configurable Jackify data directory.
    
    This directory contains:
    - downloaded_mod_lists/
    - logs/ 
    - temporary proton prefixes during installation
    
    Returns:
        Path: The Jackify data directory (always set in config)
    """
    try:
        # Import here to avoid circular imports
        from jackify.backend.handlers.config_handler import ConfigHandler
        
        config_handler = ConfigHandler()
        jackify_data_dir = config_handler.get('jackify_data_dir')
        
        # Config handler now always ensures this is set, but fallback just in case
        if jackify_data_dir:
            return Path(jackify_data_dir).expanduser()
        else:
            return Path.home() / "Jackify"
            
    except Exception:
        # Emergency fallback if config system fails
        return Path.home() / "Jackify"


def get_jackify_logs_dir() -> Path:
    """Get the logs directory within the Jackify data directory."""
    return get_jackify_data_dir() / "logs"


def get_jackify_downloads_dir() -> Path:
    """Get the downloaded modlists directory within the Jackify data directory."""
    return get_jackify_data_dir() / "downloaded_mod_lists"


def get_jackify_config_dir() -> Path:
    """
    Get the Jackify configuration directory (always ~/.config/jackify).
    
    This directory contains:
    - config.json (settings)
    - API keys and credentials
    - Resource settings
    
    Returns:
        Path: Always ~/.config/jackify
    """
    return Path.home() / ".config" / "jackify"