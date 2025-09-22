#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Resolution Utilities Module
Provides utility functions for handling resolution across GUI and CLI frontends
"""

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


def get_default_resolution() -> str:
    """
    Get the appropriate default resolution based on system detection and user preferences.
    
    Returns:
        str: Resolution string (e.g., '1920x1080', '1280x800')
    """
    try:
        # First try to get saved resolution from config
        from ..backend.services.resolution_service import ResolutionService
        resolution_service = ResolutionService()
        
        saved_resolution = resolution_service.get_saved_resolution()
        if saved_resolution and saved_resolution != 'Leave unchanged':
            logger.debug(f"Using saved resolution: {saved_resolution}")
            return saved_resolution
            
    except Exception as e:
        logger.warning(f"Could not load ResolutionService: {e}")
    
    try:
        # Check for Steam Deck
        if _is_steam_deck():
            logger.debug("Steam Deck detected, using 1280x800")
            return "1280x800"
            
    except Exception as e:
        logger.warning(f"Error detecting Steam Deck: {e}")
    
    # Fallback to common 1080p instead of arbitrary resolution
    logger.debug("Using fallback resolution: 1920x1080")
    return "1920x1080"


def _is_steam_deck() -> bool:
    """
    Detect if running on Steam Deck
    
    Returns:
        bool: True if Steam Deck detected
    """
    try:
        if os.path.exists("/etc/os-release"):
            with open("/etc/os-release", "r") as f:
                content = f.read().lower()
                return "steamdeck" in content or "steamos" in content
    except Exception as e:
        logger.debug(f"Error reading /etc/os-release: {e}")
    
    return False


def get_resolution_fallback(current_resolution: Optional[str]) -> str:
    """
    Get appropriate resolution fallback when current resolution is invalid or None
    
    Args:
        current_resolution: Current resolution value that might be None/invalid
        
    Returns:
        str: Valid resolution string
    """
    if current_resolution and current_resolution != 'Leave unchanged':
        # Validate format
        if _validate_resolution_format(current_resolution):
            return current_resolution
    
    # Use proper default resolution logic
    return get_default_resolution()


def _validate_resolution_format(resolution: str) -> bool:
    """
    Validate resolution format
    
    Args:
        resolution: Resolution string to validate
        
    Returns:
        bool: True if valid WxH format
    """
    import re
    
    if not resolution:
        return False
        
    # Handle Steam Deck format
    clean_resolution = resolution.replace(' (Steam Deck)', '')
    
    # Check WxH format
    if re.match(r'^[0-9]+x[0-9]+$', clean_resolution):
        try:
            width, height = clean_resolution.split('x')
            width_int, height_int = int(width), int(height)
            return 0 < width_int <= 10000 and 0 < height_int <= 10000
        except ValueError:
            return False
    
    return False