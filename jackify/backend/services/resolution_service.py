#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Resolution Service Module
Centralized service for managing resolution settings across CLI and GUI frontends
"""

import logging
from typing import Optional
from ..handlers.config_handler import ConfigHandler

# Initialize logger
logger = logging.getLogger(__name__)


class ResolutionService:
    """
    Centralized service for managing resolution settings
    Handles saving, loading, and validation of resolution settings
    """
    
    def __init__(self):
        """Initialize the resolution service"""
        self.config_handler = ConfigHandler()
        logger.debug("ResolutionService initialized")
    
    def save_resolution(self, resolution: str) -> bool:
        """
        Save a resolution setting to configuration
        
        Args:
            resolution (str): The resolution to save (e.g., '1920x1080')
            
        Returns:
            bool: True if saved successfully, False otherwise
        """
        try:
            # Validate resolution format (basic check)
            if not self._validate_resolution_format(resolution):
                logger.warning("Invalid resolution format provided")
                return False
            
            success = self.config_handler.save_resolution(resolution)
            if success:
                logger.info(f"Resolution saved successfully: {resolution}")
            else:
                logger.error("Failed to save resolution")
            
            return success
        except Exception as e:
            logger.error(f"Error in save_resolution: {e}")
            return False
    
    def get_saved_resolution(self) -> Optional[str]:
        """
        Retrieve the saved resolution from configuration
        
        Returns:
            str: The saved resolution or None if not saved
        """
        try:
            resolution = self.config_handler.get_saved_resolution()
            if resolution:
                logger.debug(f"Retrieved saved resolution: {resolution}")
            else:
                logger.debug("No saved resolution found")
            return resolution
        except Exception as e:
            logger.error(f"Error retrieving resolution: {e}")
            return None
    
    def has_saved_resolution(self) -> bool:
        """
        Check if a resolution is saved in configuration
        
        Returns:
            bool: True if resolution exists, False otherwise
        """
        try:
            return self.config_handler.has_saved_resolution()
        except Exception as e:
            logger.error(f"Error checking for saved resolution: {e}")
            return False
    
    def clear_saved_resolution(self) -> bool:
        """
        Clear the saved resolution from configuration
        
        Returns:
            bool: True if cleared successfully, False otherwise
        """
        try:
            success = self.config_handler.clear_saved_resolution()
            if success:
                logger.info("Resolution cleared successfully")
            else:
                logger.error("Failed to clear resolution")
            return success
        except Exception as e:
            logger.error(f"Error clearing resolution: {e}")
            return False
    
    def _validate_resolution_format(self, resolution: str) -> bool:
        """
        Validate resolution format (e.g., '1920x1080' or '1280x800 (Steam Deck)')
        
        Args:
            resolution (str): Resolution string to validate
            
        Returns:
            bool: True if valid format, False otherwise
        """
        import re
        
        if not resolution or resolution == 'Leave unchanged':
            return True  # Allow 'Leave unchanged' as valid
        
        # Handle Steam Deck format: '1280x800 (Steam Deck)'
        if ' (Steam Deck)' in resolution:
            resolution = resolution.replace(' (Steam Deck)', '')
        
        # Check for WxH format (e.g., 1920x1080)
        if re.match(r'^[0-9]+x[0-9]+$', resolution):
            # Extract width and height
            try:
                width, height = resolution.split('x')
                width_int = int(width)
                height_int = int(height)
                
                # Basic sanity checks
                if width_int > 0 and height_int > 0 and width_int <= 10000 and height_int <= 10000:
                    return True
                else:
                    logger.warning(f"Resolution dimensions out of reasonable range: {resolution}")
                    return False
            except ValueError:
                logger.warning(f"Invalid resolution format: {resolution}")
                return False
        else:
            logger.warning(f"Resolution does not match WxH format: {resolution}")
            return False
    
    def get_resolution_index(self, resolution: str, combo_items: list) -> int:
        """
        Get the index of a resolution in a combo box list
        
        Args:
            resolution (str): Resolution to find
            combo_items (list): List of combo box items
            
        Returns:
            int: Index of the resolution, or 0 (Leave unchanged) if not found
        """
        if not resolution:
            return 0  # Default to 'Leave unchanged'
        
        # Handle Steam Deck special case
        if resolution == '1280x800' and '1280x800 (Steam Deck)' in combo_items:
            return combo_items.index('1280x800 (Steam Deck)')
        
        # Try exact match first
        if resolution in combo_items:
            return combo_items.index(resolution)
        
        # Try partial match (e.g., '1920x1080' in '1920x1080 (Steam Deck)')
        for i, item in enumerate(combo_items):
            if resolution in item:
                return i
        
        # Default to 'Leave unchanged'
        return 0
