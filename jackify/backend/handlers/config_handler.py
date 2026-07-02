#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Configuration Handler Module
Handles application settings and configuration
"""

import os
import sys
import json
import logging
import shutil
import re
from pathlib import Path
from typing import Optional

from .config_handler_encryption import ConfigEncryptionMixin
from .config_handler_directories import ConfigDirectoriesMixin
from .config_handler_proton import ConfigProtonMixin
from jackify.shared.steam_utils import (
    STEAM_PREFERENCE_AUTO,
    resolve_preferred_steam_installation,
)

logger = logging.getLogger(__name__)


class ConfigHandler(ConfigEncryptionMixin, ConfigDirectoriesMixin, ConfigProtonMixin):
    """
    Handles application configuration and settings
    Singleton pattern ensures all code shares the same instance
    """
    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ConfigHandler, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        """Initialize configuration handler with default settings"""
        # Only initialize once (singleton pattern)
        if ConfigHandler._initialized:
            return
        ConfigHandler._initialized = True

        self._dirty_keys: set = set()

        self.config_dir = os.path.expanduser("~/.config/jackify")
        self.config_file = os.path.join(self.config_dir, "config.json")
        self.settings = {
            "version": "0.2.0",
            "last_selected_modlist": None,
            "steam_libraries": [],
            "resolution": None,
            "protontricks_path": None,
            "steam_path": None,
            "steam_install_preference": STEAM_PREFERENCE_AUTO,  # auto|flatpak|native
            "nexus_api_key": None,  # Base64 encoded API key
            "default_install_parent_dir": None,  # Parent directory for modlist installations
            "default_download_parent_dir": None,  # Parent directory for downloads
            "modlist_install_base_dir": os.path.expanduser("~/Games"),  # Configurable base directory for modlist installations
            "modlist_downloads_base_dir": os.path.expanduser("~/Games/Modlist_Downloads"),  # Configurable base directory for downloads
            "jackify_data_dir": None,  # Configurable Jackify data directory (default: ~/Jackify)
            "use_winetricks_for_components": True,  # DEPRECATED: Migrated to component_installation_method. Kept for backward compatibility.
            "component_installation_method": "winetricks",  # "winetricks" (default) or "system_protontricks"
            "game_proton_path": None,  # Proton version for game shortcuts (can be any Proton 9+), separate from install proton
            "proton_path": None,  # Install Proton path (for jackify-engine) - None means auto-detect
            "proton_version": None,  # Install Proton version name - None means auto-detect
            "steam_restart_strategy": "jackify",  # "jackify" (default) or "simple"
            "manual_download_concurrent_limit": 2,  # Shared GUI/CLI default for manual download browser tabs
            "manual_download_watch_directory": None,  # Optional override for manual-download watcher folder
            "window_width": None,  # Saved window width (None = use dynamic sizing)
            "window_height": None,  # Saved window height (None = use dynamic sizing)
        }
        
        # Load configuration if exists
        self._load_config()

        # Perform version migrations
        self._migrate_config()

        # Normalize/repair Proton selections on every startup so stale deleted versions
        # cannot break workflows.
        self.normalize_proton_paths_on_boot()

        # If steam_path is not set, detect it
        if not self.settings["steam_path"]:
            self.settings["steam_path"] = self._detect_steam_path()
        
        # If jackify_data_dir is not set, initialize it to default
        if not self.settings.get("jackify_data_dir"):
            self.settings["jackify_data_dir"] = os.path.expanduser("~/Jackify")
            # Save the updated settings
            self.save_config()
    
    def _detect_steam_path(self):
        """
        Detect the Steam installation path
        
        Returns:
            str: Path to the Steam installation or None if not found
        """
        logger.info("Detecting Steam installation path...")
        preference = self.settings.get("steam_install_preference", STEAM_PREFERENCE_AUTO)
        install_type, install_root = resolve_preferred_steam_installation(preference=preference)
        if install_root:
            logger.info(
                "Selected Steam installation: %s (%s)",
                install_type,
                install_root,
            )
            return str(install_root)

        logger.error("Steam installation not found")
        return None
    
    def _load_config(self):
        """
        Load configuration from file and update in-memory cache.
        For legacy compatibility with initialization code.
        """
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

    def _migrate_config(self):
        """
        Migrate configuration between versions
        Handles breaking changes and data format updates
        """
        current_version = self.settings.get("version", "0.0.0")
        target_version = "0.2.0"

        if current_version == target_version:
            return

        logger.info(f"Migrating config from {current_version} to {target_version}")

        # Migration: v0.0.x -> v0.2.0
        # Encryption changed from cryptography (Fernet) to pycryptodomex (AES-GCM)
        # Old encrypted API keys cannot be decrypted, must be re-entered
        from packaging import version
        if version.parse(current_version) < version.parse("0.2.0"):
            # Clear old encrypted credentials
            if self.settings.get("nexus_api_key"):
                logger.warning("Clearing saved API key due to encryption format change")
                logger.warning("Please re-enter your Nexus API key in Settings")
                self.settings["nexus_api_key"] = None

            # Clear OAuth token file (different encryption format)
            oauth_token_file = Path(self.config_dir) / "nexus-oauth.json"
            if oauth_token_file.exists():
                logger.warning("Clearing saved OAuth token due to encryption format change")
                logger.warning("Please re-authorize with Nexus Mods")
                try:
                    oauth_token_file.unlink()
                except Exception as e:
                    logger.error(f"Failed to remove old OAuth token: {e}")

            # Remove obsolete keys
            obsolete_keys = [
                "hoolamike_install_path",
                "hoolamike_version",
                "api_key_fallback_enabled",
                "proton_version",  # Display string only, path stored in proton_path
                "game_proton_version"  # Display string only, path stored in game_proton_path
            ]

            removed_count = 0
            for key in obsolete_keys:
                if key in self.settings:
                    del self.settings[key]
                    removed_count += 1

            if removed_count > 0:
                logger.info(f"Removed {removed_count} obsolete config keys")

            # Update version
            self.settings["version"] = target_version
            self.save_config()
            logger.info("Config migration completed")

    def _read_config_from_disk(self):
        """
        Read configuration directly from disk without caching.
        Returns merged config (defaults + saved values).
        """
        try:
            config = self.settings.copy()  # Start with defaults
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r') as f:
                    saved_config = json.load(f)
                    config.update(saved_config)
            return config
        except Exception as e:
            # Use logger.warning instead of print to stderr - logger is initialized before config access
            logger.warning(f"Error reading configuration from disk: {e}")
            return self.settings.copy()

    def reload_config(self):
        """Reload configuration from disk to pick up external changes"""
        self._load_config()
    
    def _create_config_dir(self):
        """Create configuration directory if it doesn't exist"""
        try:
            os.makedirs(self.config_dir, exist_ok=True)
            logger.debug(f"Created configuration directory: {self.config_dir}")
        except Exception as e:
            logger.error(f"Error creating configuration directory: {e}")
    
    def save_config(self):
        """Save current configuration to file.

        Reads disk state, overlays only dirty keys, then writes atomically.
        This prevents concurrent callers from clobbering each other's saves.
        """
        import tempfile
        try:
            self._create_config_dir()
            # When dirty keys exist, read disk and overlay only those keys so concurrent
            # callers don't clobber each other. When no keys are dirty (migration/bootstrap
            # code that mutates self.settings directly), fall back to writing all settings.
            if self._dirty_keys:
                try:
                    if os.path.exists(self.config_file):
                        with open(self.config_file, 'r') as f:
                            on_disk = json.load(f)
                    else:
                        on_disk = self.settings.copy()
                except Exception:
                    on_disk = self.settings.copy()
                for key in self._dirty_keys:
                    on_disk[key] = self.settings[key]
            else:
                on_disk = self.settings.copy()
            fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(self.config_file), prefix='.config_tmp_')
            try:
                with os.fdopen(fd, 'w') as f:
                    json.dump(on_disk, f, indent=2)
                os.chmod(tmp_path, 0o600)
                os.replace(tmp_path, self.config_file)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
            self._dirty_keys.clear()
            logger.debug("Saved configuration to file")
            return True
        except Exception as e:
            logger.error(f"Error saving configuration: {e}")
            return False
    
    def get(self, key, default=None):
        """Return configuration value, preferring any unsaved in-memory value."""
        if key in self._dirty_keys:
            return self.settings.get(key, default)
        config = self._read_config_from_disk()
        return config.get(key, default)
    
    def set(self, key, value):
        """Set a configuration value (marks key dirty until save_config is called)."""
        self.settings[key] = value
        self._dirty_keys.add(key)
        return True

    def update(self, settings_dict):
        """Update multiple configuration values (marks all keys dirty)."""
        self.settings.update(settings_dict)
        self._dirty_keys.update(settings_dict.keys())
        return True
    
    def add_steam_library(self, path):
        """Add a Steam library path to configuration"""
        if path not in self.settings["steam_libraries"]:
            self.settings["steam_libraries"].append(path)
            self._dirty_keys.add("steam_libraries")
            logger.debug(f"Added Steam library: {path}")
            return True
        return False

    def remove_steam_library(self, path):
        """Remove a Steam library path from configuration"""
        if path in self.settings["steam_libraries"]:
            self.settings["steam_libraries"].remove(path)
            self._dirty_keys.add("steam_libraries")
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



 
