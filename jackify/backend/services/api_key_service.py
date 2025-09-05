#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API Key Service Module
Centralized service for managing Nexus API keys across CLI and GUI frontends
"""

import logging
from typing import Optional, Tuple
from ..handlers.config_handler import ConfigHandler

# Initialize logger
logger = logging.getLogger(__name__)


class APIKeyService:
    """
    Centralized service for managing Nexus API keys
    Handles saving, loading, and validation of API keys
    """
    
    def __init__(self):
        """Initialize the API key service"""
        self.config_handler = ConfigHandler()
        logger.debug("APIKeyService initialized")
    
    def save_api_key(self, api_key: str) -> bool:
        """
        Save an API key to configuration
        
        Args:
            api_key (str): The API key to save
            
        Returns:
            bool: True if saved successfully, False otherwise
        """
        try:
            # Validate API key format (basic check)
            if not self._validate_api_key_format(api_key):
                logger.warning("Invalid API key format provided")
                return False
            
            # Check if we can write to config directory
            import os
            config_dir = os.path.dirname(self.config_handler.config_file)
            if not os.path.exists(config_dir):
                try:
                    os.makedirs(config_dir, exist_ok=True)
                    logger.debug(f"Created config directory: {config_dir}")
                except PermissionError:
                    logger.error(f"Permission denied creating config directory: {config_dir}")
                    return False
                except Exception as dir_error:
                    logger.error(f"Error creating config directory: {dir_error}")
                    return False
            
            # Check write permissions
            if not os.access(config_dir, os.W_OK):
                logger.error(f"No write permission for config directory: {config_dir}")
                return False
            
            success = self.config_handler.save_api_key(api_key)
            if success:
                logger.info("API key saved successfully")
                # Verify the save worked by reading it back
                saved_key = self.config_handler.get_api_key()
                if saved_key != api_key:
                    logger.error("API key save verification failed - key mismatch")
                    return False
            else:
                logger.error("Failed to save API key via config handler")
            
            return success
        except Exception as e:
            logger.error(f"Error in save_api_key: {e}")
            return False
    
    def get_saved_api_key(self) -> Optional[str]:
        """
        Retrieve the saved API key from configuration
        
        Returns:
            str: The decoded API key or None if not saved
        """
        try:
            api_key = self.config_handler.get_api_key()
            if api_key:
                logger.debug("Retrieved saved API key")
            else:
                logger.debug("No saved API key found")
            return api_key
        except Exception as e:
            logger.error(f"Error retrieving API key: {e}")
            return None
    
    def has_saved_api_key(self) -> bool:
        """
        Check if an API key is saved in configuration
        
        Returns:
            bool: True if API key exists, False otherwise
        """
        try:
            return self.config_handler.has_saved_api_key()
        except Exception as e:
            logger.error(f"Error checking for saved API key: {e}")
            return False
    
    def clear_saved_api_key(self) -> bool:
        """
        Clear the saved API key from configuration
        
        Returns:
            bool: True if cleared successfully, False otherwise
        """
        try:
            success = self.config_handler.clear_api_key()
            if success:
                logger.info("API key cleared successfully")
            else:
                logger.error("Failed to clear API key")
            return success
        except Exception as e:
            logger.error(f"Error clearing API key: {e}")
            return False
    
    def get_api_key_for_session(self, provided_key: Optional[str] = None, 
                               use_saved: bool = True) -> Tuple[Optional[str], str]:
        """
        Get the API key to use for a session, with priority logic
        
        Args:
            provided_key (str, optional): API key provided by user for this session
            use_saved (bool): Whether to use saved API key if no key provided
            
        Returns:
            tuple: (api_key, source) where source is 'provided', 'saved', or 'none'
        """
        try:
            # Priority 1: Use provided key if given
            if provided_key and self._validate_api_key_format(provided_key):
                logger.debug("Using provided API key for session")
                return provided_key, 'provided'
            
            # Priority 2: Use saved key if enabled and available
            if use_saved and self.has_saved_api_key():
                saved_key = self.get_saved_api_key()
                if saved_key:
                    logger.debug("Using saved API key for session")
                    return saved_key, 'saved'
            
            # No valid API key available
            logger.debug("No valid API key available for session")
            return None, 'none'
            
        except Exception as e:
            logger.error(f"Error getting API key for session: {e}")
            return None, 'none'
    
    def _validate_api_key_format(self, api_key: str) -> bool:
        """
        Validate basic API key format
        
        Args:
            api_key (str): API key to validate
            
        Returns:
            bool: True if format appears valid, False otherwise
        """
        if not api_key or not isinstance(api_key, str):
            return False
        
        # Basic validation: should be alphanumeric string of reasonable length
        # Nexus API keys are typically 32+ characters, alphanumeric with some special chars
        api_key = api_key.strip()
        if len(api_key) < 10:  # Too short to be valid
            return False
        
        if len(api_key) > 200:  # Unreasonably long
            return False
        
        # Should contain some alphanumeric characters
        if not any(c.isalnum() for c in api_key):
            return False
        
        return True
    
    def get_api_key_display(self, api_key: str, mask_after_chars: int = 4) -> str:
        """
        Get a masked version of the API key for display purposes
        
        Args:
            api_key (str): The API key to mask
            mask_after_chars (int): Number of characters to show before masking
            
        Returns:
            str: Masked API key for display
        """
        if not api_key:
            return ""
        
        if len(api_key) <= mask_after_chars:
            return "*" * len(api_key)
        
        visible_part = api_key[:mask_after_chars]
        masked_part = "*" * (len(api_key) - mask_after_chars)
        return visible_part + masked_part
    
    def validate_api_key_works(self, api_key: str) -> Tuple[bool, str]:
        """
        Validate that an API key actually works with Nexus API
        Tests the key against the Nexus Mods validation endpoint
        
        Args:
            api_key (str): API key to validate
            
        Returns:
            tuple: (is_valid, message)
        """
        # First check format
        if not self._validate_api_key_format(api_key):
            return False, "API key format is invalid"
        
        try:
            import requests
            import time
            
            # Nexus API validation endpoint
            url = "https://api.nexusmods.com/v1/users/validate.json"
            headers = {
                'apikey': api_key,
                'User-Agent': 'Jackify/1.0'  # Required by Nexus API
            }
            
            # Set a reasonable timeout
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                # API key is valid
                try:
                    data = response.json()
                    username = data.get('name', 'Unknown')
                    # Don't log the actual API key - use masking
                    masked_key = self.get_api_key_display(api_key)
                    logger.info(f"API key validation successful for user: {username} (key: {masked_key})")
                    return True, f"API key valid for user: {username}"
                except Exception as json_error:
                    logger.warning(f"API key valid but couldn't parse user info: {json_error}")
                    return True, "API key is valid"
            elif response.status_code == 401:
                # Invalid API key
                logger.warning("API key validation failed: Invalid key")
                return False, "Invalid API key"
            elif response.status_code == 429:
                # Rate limited
                logger.warning("API key validation rate limited")
                return False, "Rate limited - try again later"
            else:
                # Other error
                logger.warning(f"API key validation failed with status {response.status_code}")
                return False, f"Validation failed (HTTP {response.status_code})"
                
        except requests.exceptions.Timeout:
            logger.warning("API key validation timed out")
            return False, "Validation timed out - check connection"
        except requests.exceptions.ConnectionError:
            logger.warning("API key validation connection error")
            return False, "Connection error - check internet"
        except Exception as e:
            logger.error(f"API key validation error: {e}")
            return False, f"Validation error: {str(e)}" 