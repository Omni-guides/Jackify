#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Configuration Handler Module
Handles application settings and configuration
"""

import os
import json
import logging
import shutil
import re
import base64
from pathlib import Path

# Initialize logger
logger = logging.getLogger(__name__)


class ConfigHandler:
    """
    Handles application configuration and settings
    """
    
    def __init__(self):
        """Initialize configuration handler with default settings"""
        self.config_dir = os.path.expanduser("~/.config/jackify")
        self.config_file = os.path.join(self.config_dir, "config.json")
        self.settings = {
            "version": "0.0.5",
            "last_selected_modlist": None,
            "steam_libraries": [],
            "resolution": None,
            "protontricks_path": None,
            "steam_path": None,
            "nexus_api_key": None,  # Base64 encoded API key
            "default_install_parent_dir": None,  # Parent directory for modlist installations
            "default_download_parent_dir": None,  # Parent directory for downloads
            "modlist_install_base_dir": os.path.expanduser("~/Games"),  # Configurable base directory for modlist installations
            "modlist_downloads_base_dir": os.path.expanduser("~/Games/Modlist_Downloads")  # Configurable base directory for downloads
        }
        
        # Load configuration if exists
        self._load_config()
        
        # If steam_path is not set, detect it
        if not self.settings["steam_path"]:
            self.settings["steam_path"] = self._detect_steam_path()
            # Save the updated settings
            self.save_config()
    
    def _detect_steam_path(self):
        """
        Detect the Steam installation path
        
        Returns:
            str: Path to the Steam installation or None if not found
        """
        logger.info("Detecting Steam installation path...")
        
        # Common Steam installation paths
        steam_paths = [
            os.path.expanduser("~/.steam/steam"),
            os.path.expanduser("~/.local/share/Steam"),
            os.path.expanduser("~/.steam/root")
        ]
        
        # Check each path
        for path in steam_paths:
            if os.path.exists(path):
                logger.info(f"Found Steam installation at: {path}")
                return path
        
        # If not found in common locations, try to find using libraryfolders.vdf
        libraryfolders_vdf_paths = [
            os.path.expanduser("~/.steam/steam/config/libraryfolders.vdf"),
            os.path.expanduser("~/.local/share/Steam/config/libraryfolders.vdf"),
            os.path.expanduser("~/.steam/root/config/libraryfolders.vdf")
        ]
        
        for vdf_path in libraryfolders_vdf_paths:
            if os.path.exists(vdf_path):
                # Extract the Steam path from the libraryfolders.vdf path
                steam_path = os.path.dirname(os.path.dirname(vdf_path))
                logger.info(f"Found Steam installation at: {steam_path}")
                return steam_path
        
        logger.error("Steam installation not found")
        return None
    
    def _load_config(self):
        """Load configuration from file"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r') as f:
                    saved_config = json.load(f)
                    # Update settings with saved values while preserving defaults
                    self.settings.update(saved_config)
                    logger.debug("Loaded configuration from file")
            else:
                logger.debug("No configuration file found, using defaults")
                self._create_config_dir()
        except Exception as e:
            logger.error(f"Error loading configuration: {e}")
    
    def _create_config_dir(self):
        """Create configuration directory if it doesn't exist"""
        try:
            os.makedirs(self.config_dir, exist_ok=True)
            logger.debug(f"Created configuration directory: {self.config_dir}")
        except Exception as e:
            logger.error(f"Error creating configuration directory: {e}")
    
    def save_config(self):
        """Save current configuration to file"""
        try:
            self._create_config_dir()
            with open(self.config_file, 'w') as f:
                json.dump(self.settings, f, indent=2)
            logger.debug("Saved configuration to file")
            return True
        except Exception as e:
            logger.error(f"Error saving configuration: {e}")
            return False
    
    def get(self, key, default=None):
        """Get a configuration value by key"""
        return self.settings.get(key, default)
    
    def set(self, key, value):
        """Set a configuration value"""
        self.settings[key] = value
        return True
    
    def update(self, settings_dict):
        """Update multiple configuration values"""
        self.settings.update(settings_dict)
        return True
    
    def add_steam_library(self, path):
        """Add a Steam library path to configuration"""
        if path not in self.settings["steam_libraries"]:
            self.settings["steam_libraries"].append(path)
            logger.debug(f"Added Steam library: {path}")
            return True
        return False
    
    def remove_steam_library(self, path):
        """Remove a Steam library path from configuration"""
        if path in self.settings["steam_libraries"]:
            self.settings["steam_libraries"].remove(path)
            logger.debug(f"Removed Steam library: {path}")
            return True
        return False
    
    def set_resolution(self, width, height):
        """Set preferred resolution"""
        resolution = f"{width}x{height}"
        self.settings["resolution"] = resolution
        logger.debug(f"Set resolution to: {resolution}")
        return True
    
    def get_resolution(self):
        """Get preferred resolution"""
        return self.settings.get("resolution")
    
    def set_last_modlist(self, modlist_name):
        """Save the last selected modlist"""
        self.settings["last_selected_modlist"] = modlist_name
        logger.debug(f"Set last selected modlist to: {modlist_name}")
        return True
    
    def get_last_modlist(self):
        """Get the last selected modlist"""
        return self.settings.get("last_selected_modlist")
    
    def set_protontricks_path(self, path):
        """Set the path to protontricks executable"""
        self.settings["protontricks_path"] = path
        logger.debug(f"Set protontricks path to: {path}")
        return True
    
    def get_protontricks_path(self):
        """Get the path to protontricks executable"""
        return self.settings.get("protontricks_path") 
    
    def save_api_key(self, api_key):
        """
        Save Nexus API key with base64 encoding
        
        Args:
            api_key (str): Plain text API key
            
        Returns:
            bool: True if saved successfully, False otherwise
        """
        try:
            if api_key:
                # Encode the API key using base64
                encoded_key = base64.b64encode(api_key.encode('utf-8')).decode('utf-8')
                self.settings["nexus_api_key"] = encoded_key
                logger.debug("API key saved successfully")
            else:
                # Clear the API key if empty
                self.settings["nexus_api_key"] = None
                logger.debug("API key cleared")
            
            return self.save_config()
        except Exception as e:
            logger.error(f"Error saving API key: {e}")
            return False
    
    def get_api_key(self):
        """
        Retrieve and decode the saved Nexus API key
        
        Returns:
            str: Decoded API key or None if not saved
        """
        try:
            encoded_key = self.settings.get("nexus_api_key")
            if encoded_key:
                # Decode the base64 encoded key
                decoded_key = base64.b64decode(encoded_key.encode('utf-8')).decode('utf-8')
                return decoded_key
            return None
        except Exception as e:
            logger.error(f"Error retrieving API key: {e}")
            return None
    
    def has_saved_api_key(self):
        """
        Check if an API key is saved in configuration
        
        Returns:
            bool: True if API key exists, False otherwise
        """
        return self.settings.get("nexus_api_key") is not None
    
    def clear_api_key(self):
        """
        Clear the saved API key from configuration
        
        Returns:
            bool: True if cleared successfully, False otherwise
        """
        try:
            self.settings["nexus_api_key"] = None
            logger.debug("API key cleared from configuration")
            return self.save_config()
        except Exception as e:
            logger.error(f"Error clearing API key: {e}")
            return False
    def save_resolution(self, resolution):
        """
        Save resolution setting to configuration
        
        Args:
            resolution (str): Resolution string (e.g., '1920x1080')
            
        Returns:
            bool: True if saved successfully, False otherwise
        """
        try:
            if resolution and resolution != 'Leave unchanged':
                self.settings["resolution"] = resolution
                logger.debug(f"Resolution saved: {resolution}")
            else:
                # Clear resolution if 'Leave unchanged' or empty
                self.settings["resolution"] = None
                logger.debug("Resolution cleared")
            
            return self.save_config()
        except Exception as e:
            logger.error(f"Error saving resolution: {e}")
            return False
    
    def get_saved_resolution(self):
        """
        Retrieve the saved resolution from configuration
        
        Returns:
            str: Saved resolution or None if not saved
        """
        try:
            resolution = self.settings.get("resolution")
            if resolution:
                logger.debug(f"Retrieved saved resolution: {resolution}")
            else:
                logger.debug("No saved resolution found")
            return resolution
        except Exception as e:
            logger.error(f"Error retrieving resolution: {e}")
            return None
    
    def has_saved_resolution(self):
        """
        Check if a resolution is saved in configuration
        
        Returns:
            bool: True if resolution exists, False otherwise
        """
        return self.settings.get("resolution") is not None
    
    def clear_saved_resolution(self):
        """
        Clear the saved resolution from configuration
        
        Returns:
            bool: True if cleared successfully, False otherwise
        """
        try:
            self.settings["resolution"] = None
            logger.debug("Resolution cleared from configuration")
            return self.save_config()
        except Exception as e:
            logger.error(f"Error clearing resolution: {e}")
            return False

    def set_default_install_parent_dir(self, path):
        """
        Save the parent directory for modlist installations
        
        Args:
            path (str): Parent directory path to save
            
        Returns:
            bool: True if saved successfully, False otherwise
        """
        try:
            if path and os.path.exists(path):
                self.settings["default_install_parent_dir"] = path
                logger.debug(f"Default install parent directory saved: {path}")
                return self.save_config()
            else:
                logger.warning(f"Invalid or non-existent path for install parent directory: {path}")
                return False
        except Exception as e:
            logger.error(f"Error saving install parent directory: {e}")
            return False
    
    def get_default_install_parent_dir(self):
        """
        Retrieve the saved parent directory for modlist installations
        
        Returns:
            str: Saved parent directory path or None if not saved
        """
        try:
            path = self.settings.get("default_install_parent_dir")
            if path and os.path.exists(path):
                logger.debug(f"Retrieved default install parent directory: {path}")
                return path
            else:
                logger.debug("No valid default install parent directory found")
                return None
        except Exception as e:
            logger.error(f"Error retrieving install parent directory: {e}")
            return None
    
    def set_default_download_parent_dir(self, path):
        """
        Save the parent directory for downloads
        
        Args:
            path (str): Parent directory path to save
            
        Returns:
            bool: True if saved successfully, False otherwise
        """
        try:
            if path and os.path.exists(path):
                self.settings["default_download_parent_dir"] = path
                logger.debug(f"Default download parent directory saved: {path}")
                return self.save_config()
            else:
                logger.warning(f"Invalid or non-existent path for download parent directory: {path}")
                return False
        except Exception as e:
            logger.error(f"Error saving download parent directory: {e}")
            return False
    
    def get_default_download_parent_dir(self):
        """
        Retrieve the saved parent directory for downloads
        
        Returns:
            str: Saved parent directory path or None if not saved
        """
        try:
            path = self.settings.get("default_download_parent_dir")
            if path and os.path.exists(path):
                logger.debug(f"Retrieved default download parent directory: {path}")
                return path
            else:
                logger.debug("No valid default download parent directory found")
                return None
        except Exception as e:
            logger.error(f"Error retrieving download parent directory: {e}")
            return None
    
    def has_saved_install_parent_dir(self):
        """
        Check if a default install parent directory is saved in configuration
        
        Returns:
            bool: True if directory exists and is valid, False otherwise
        """
        path = self.settings.get("default_install_parent_dir")
        return path is not None and os.path.exists(path)
    
    def has_saved_download_parent_dir(self):
        """
        Check if a default download parent directory is saved in configuration
        
        Returns:
            bool: True if directory exists and is valid, False otherwise
        """
        path = self.settings.get("default_download_parent_dir")
        return path is not None and os.path.exists(path)
    
    def get_modlist_install_base_dir(self):
        """
        Get the configurable base directory for modlist installations
        
        Returns:
            str: Base directory path for modlist installations
        """
        return self.settings.get("modlist_install_base_dir", os.path.expanduser("~/Games"))
    
    def set_modlist_install_base_dir(self, path):
        """
        Set the configurable base directory for modlist installations
        
        Args:
            path (str): Base directory path to save
            
        Returns:
            bool: True if saved successfully, False otherwise
        """
        try:
            if path:
                self.settings["modlist_install_base_dir"] = path
                logger.debug(f"Modlist install base directory saved: {path}")
                return self.save_config()
            else:
                logger.warning("Invalid path for modlist install base directory")
                return False
        except Exception as e:
            logger.error(f"Error saving modlist install base directory: {e}")
            return False
    
    def get_modlist_downloads_base_dir(self):
        """
        Get the configurable base directory for modlist downloads
        
        Returns:
            str: Base directory path for modlist downloads
        """
        return self.settings.get("modlist_downloads_base_dir", os.path.expanduser("~/Games/Modlist_Downloads"))
    
    def set_modlist_downloads_base_dir(self, path):
        """
        Set the configurable base directory for modlist downloads
        
        Args:
            path (str): Base directory path to save
            
        Returns:
            bool: True if saved successfully, False otherwise
        """
        try:
            if path:
                self.settings["modlist_downloads_base_dir"] = path
                logger.debug(f"Modlist downloads base directory saved: {path}")
                return self.save_config()
            else:
                logger.warning("Invalid path for modlist downloads base directory")
                return False
        except Exception as e:
            logger.error(f"Error saving modlist downloads base directory: {e}")
            return False

 