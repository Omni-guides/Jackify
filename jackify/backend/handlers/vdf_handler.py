#!/usr/bin/env python3
"""
VDFHandler module for safely handling VDF files.
This module provides wrappers around the VDF library with additional safety checks.
"""

import os
import logging
import vdf
from pathlib import Path
from typing import Dict, Any, Optional

# Initialize logger
logger = logging.getLogger(__name__)

# List of protected VDF files that should never be modified
PROTECTED_VDF_FILES = [
    "libraryfolders.vdf",
    "config.vdf",
    "loginusers.vdf",
    "registry.vdf",
    "localconfig.vdf",
    "remotecache.vdf",
    "sharedconfig.vdf",
    "appinfo.vdf",
    "packageinfo.vdf",
    "appmanifest_*.acf"
]

# Critical Steam directories we should never modify
CRITICAL_STEAM_DIRS = [
    "appcache",
    "controller_base",
    "config",
    "logs",
    "package",
    "public",
    "resource",
    "steam",
    "steamapps",
    "tenfoot"
]

class VDFHandler:
    """
    Safe handler for VDF operations with protection against modifying critical Steam files.
    """
    
    @staticmethod
    def is_protected_file(file_path: str) -> bool:
        """
        Check if a file is protected from modification.
        
        Args:
            file_path: Path to the VDF file
            
        Returns:
            bool: True if the file is protected, False otherwise
        """
        file_name = os.path.basename(file_path)
        
        # Special exception for shortcuts.vdf - we always want to be able to modify this
        if file_name == "shortcuts.vdf":
            return False
        
        # Check exact filename match
        if file_name in PROTECTED_VDF_FILES:
            return True
            
        # Check pattern match (for appmanifest_*.acf)
        for pattern in PROTECTED_VDF_FILES:
            if '*' in pattern and pattern.replace('*', '') in file_name:
                return True
                
        # Check if file is in critical Steam directories
        for dir_name in CRITICAL_STEAM_DIRS:
            if f"/{dir_name}/" in file_path or f"\\{dir_name}\\" in file_path:
                return True
                
        return False
    
    @staticmethod
    def load(file_path: str, binary: bool = True) -> Dict[str, Any]:
        """
        Safely load a VDF file.
        
        Args:
            file_path: Path to the VDF file
            binary: Whether the file is binary VDF format
            
        Returns:
            Dict: Parsed VDF data
            
        Raises:
            ValueError: If the file is protected and being loaded for writing
        """
        # Always create a backup before reading critical files
        if VDFHandler.is_protected_file(file_path):
            backup_path = f"{file_path}.bak"
            if not os.path.exists(backup_path):
                try:
                    import shutil
                    shutil.copy2(file_path, backup_path)
                    logger.debug(f"Created backup of {os.path.basename(file_path)} at {backup_path}")
                except Exception as e:
                    logger.error(f"Failed to create backup of {file_path}: {e}")
        
        # Load the VDF file
        try:
            if binary:
                # Use ValvePython/vdf library for binary files
                logger.debug(f"Attempting to load binary VDF with ValvePython/vdf: {file_path}")
                if not os.path.exists(file_path):
                    logger.error(f"Binary VDF file not found: {file_path}")
                    return None
                with open(file_path, 'rb') as f_vdf:
                    return vdf.binary_loads(f_vdf.read())
            else:
                # Handle text VDF files (e.g., config.vdf)
                logger.debug(f"Attempting to load text VDF with ValvePython/vdf: {file_path}")
                if not os.path.exists(file_path):
                    logger.error(f"Text VDF file not found: {file_path}")
                    return None
                with open(file_path, 'r', encoding='utf-8') as f_text:
                    return vdf.load(f_text)
                    
        except FileNotFoundError:
            # This might be redundant due to os.path.exists checks, but keep for safety
            logger.error(f"VDF file not found during load operation: {file_path}")
            return None
        except PermissionError:
             logger.error(f"Permission denied when trying to read VDF file: {file_path}")
             return None
        except Exception as e:
            # Catch any other unexpected errors (including parsing errors from vdf.binary_loads)
            logger.error(f"Unexpected error loading VDF file {file_path}: {e}", exc_info=True)
            return None # Return None instead of {}
    
    @staticmethod
    def save(file_path: str, data: Dict[str, Any], binary: bool = True) -> bool:
        """
        Safely save a VDF file with protection for critical files.
        
        Args:
            file_path: Path to the VDF file
            data: VDF data to save
            binary: Whether to save in binary VDF format
            
        Returns:
            bool: True if save was successful, False otherwise
            
        Raises:
            ValueError: If attempting to modify a protected file
        """
        # Normalize path for consistent checks
        file_path = os.path.normpath(file_path)
        
        # FIRST LINE OF DEFENSE: Prevent modification of protected files
        if VDFHandler.is_protected_file(file_path):
            error_msg = f"CRITICAL SAFETY ERROR: Attempted to modify protected Steam file: {file_path}"
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        # SECOND LINE OF DEFENSE: Only allow saving to shortcuts.vdf
        file_name = os.path.basename(file_path)
        if file_name != "shortcuts.vdf":
            error_msg = f"CRITICAL SAFETY ERROR: Only shortcuts.vdf can be modified, attempted: {file_path}"
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        # THIRD LINE OF DEFENSE: Create backup before saving
        if os.path.exists(file_path):
            # Create timestamped backup
            timestamp = Path(file_path).stat().st_mtime
            backup_path = f"{file_path}.{int(timestamp)}.bak"
            
            # Also create a simple .bak file if it doesn't exist
            simple_backup = f"{file_path}.bak"
            
            try:
                import shutil
                # Create timestamped backup
                shutil.copy2(file_path, backup_path)
                logger.info(f"Created timestamped backup of {file_name} at {backup_path}")
                
                # Create simple backup if it doesn't exist
                if not os.path.exists(simple_backup):
                    shutil.copy2(file_path, simple_backup)
                    logger.info(f"Created backup of {file_name} at {simple_backup}")
            except Exception as e:
                logger.error(f"Failed to create backup before modifying {file_path}: {e}")
                return False
        
        # Save the file
        try:
            # Additional safety: Verify we're only saving to shortcuts.vdf again
            if not file_name == "shortcuts.vdf":
                raise ValueError(f"Final safety check failed: Attempted to save to non-shortcuts file: {file_path}")
                
            if binary:
                with open(file_path, 'wb') as f:
                    vdf.binary_dumps(data, f)
            else:
                with open(file_path, 'w', encoding='utf-8') as f:
                    vdf.dump(data, f, pretty=True)
                    
            logger.info(f"Successfully saved changes to {file_path}")
            return True
        except Exception as e:
            logger.error(f"Error saving VDF file {file_path}: {e}")
            return False

    @staticmethod
    def update_shortcuts(shortcuts_path: str, update_function) -> bool:
        """
        Safely update shortcuts.vdf using a callback function.
        
        Args:
            shortcuts_path: Path to the shortcuts.vdf file
            update_function: Callback function that takes shortcuts data and returns updated data
                             Signature: function(shortcuts_data) -> updated_shortcuts_data
        
        Returns:
            bool: True if update was successful, False otherwise
        """
        try:
            # Check that we're only operating on shortcuts.vdf
            if os.path.basename(shortcuts_path) != "shortcuts.vdf":
                error_msg = f"Can only update shortcuts.vdf, not: {shortcuts_path}"
                logger.error(error_msg)
                raise ValueError(error_msg)
            
            # Load the shortcuts file
            logger.info(f"Loading shortcuts from: {shortcuts_path}")
            shortcuts_data = VDFHandler.load(shortcuts_path, binary=True)
            
            if not shortcuts_data:
                logger.error(f"Failed to load shortcuts data from {shortcuts_path}")
                return False
            
            # Apply the update function
            logger.info("Applying updates to shortcuts data")
            updated_data = update_function(shortcuts_data)
            
            if updated_data is None:
                logger.error("Update function returned None")
                return False
            
            # Save the updated data
            logger.info(f"Saving updated shortcuts to: {shortcuts_path}")
            return VDFHandler.save(shortcuts_path, updated_data, binary=True)
            
        except Exception as e:
            logger.error(f"Error updating shortcuts: {e}")
            return False 