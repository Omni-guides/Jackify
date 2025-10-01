"""
ValidationHandler module for managing validation operations.
This module handles input validation, path validation, and configuration validation.
"""

import os
import logging
import re
import shutil
import vdf
from pathlib import Path
from typing import Optional, Dict, List, Tuple, Any

class ValidationHandler:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
    def validate_path(self, path: Path, must_exist: bool = True) -> Tuple[bool, str]:
        """Validate a path."""
        try:
            if not isinstance(path, Path):
                return False, "Path must be a Path object"
                
            if must_exist and not path.exists():
                return False, f"Path does not exist: {path}"
                
            if not os.access(path, os.R_OK | os.W_OK):
                return False, f"Path is not accessible: {path}"
                
            return True, "Path is valid"
        except Exception as e:
            self.logger.error(f"Failed to validate path {path}: {e}")
            return False, str(e)
        
    def validate_input(self, value: Any, rules: Dict) -> Tuple[bool, str]:
        """Validate user input against rules."""
        try:
            # Check required
            if rules.get('required', False) and not value:
                return False, "Value is required"
                
            # Check type
            if 'type' in rules and not isinstance(value, rules['type']):
                return False, f"Value must be of type {rules['type'].__name__}"
                
            # Check min/max length for strings
            if isinstance(value, str):
                if 'min_length' in rules and len(value) < rules['min_length']:
                    return False, f"Value must be at least {rules['min_length']} characters"
                if 'max_length' in rules and len(value) > rules['max_length']:
                    return False, f"Value must be at most {rules['max_length']} characters"
                    
            # Check min/max value for numbers
            if isinstance(value, (int, float)):
                if 'min_value' in rules and value < rules['min_value']:
                    return False, f"Value must be at least {rules['min_value']}"
                if 'max_value' in rules and value > rules['max_value']:
                    return False, f"Value must be at most {rules['max_value']}"
                    
            # Check pattern for strings
            if isinstance(value, str) and 'pattern' in rules:
                if not re.match(rules['pattern'], value):
                    return False, f"Value must match pattern: {rules['pattern']}"
                    
            # Check custom validation function
            if 'validate' in rules and callable(rules['validate']):
                result = rules['validate'](value)
                if isinstance(result, tuple):
                    return result
                elif not result:
                    return False, "Custom validation failed"
                    
            return True, "Input is valid"
        except Exception as e:
            self.logger.error(f"Failed to validate input: {e}")
            return False, str(e)
        
    def validate_config(self, config: Dict, schema: Dict) -> Tuple[bool, List[str]]:
        """Validate configuration against a schema."""
        try:
            errors = []
            
            # Check required fields
            for field, rules in schema.items():
                if rules.get('required', False) and field not in config:
                    errors.append(f"Missing required field: {field}")
                    
            # Check field types and values
            for field, value in config.items():
                if field not in schema:
                    errors.append(f"Unknown field: {field}")
                    continue
                    
                rules = schema[field]
                if 'type' in rules and not isinstance(value, rules['type']):
                    errors.append(f"Invalid type for {field}: expected {rules['type'].__name__}")
                    
                if isinstance(value, str):
                    if 'min_length' in rules and len(value) < rules['min_length']:
                        errors.append(f"{field} must be at least {rules['min_length']} characters")
                    if 'max_length' in rules and len(value) > rules['max_length']:
                        errors.append(f"{field} must be at most {rules['max_length']} characters")
                    if 'pattern' in rules and not re.match(rules['pattern'], value):
                        errors.append(f"{field} must match pattern: {rules['pattern']}")
                        
                if isinstance(value, (int, float)):
                    if 'min_value' in rules and value < rules['min_value']:
                        errors.append(f"{field} must be at least {rules['min_value']}")
                    if 'max_value' in rules and value > rules['max_value']:
                        errors.append(f"{field} must be at most {rules['max_value']}")
                        
                if 'validate' in rules and callable(rules['validate']):
                    result = rules['validate'](value)
                    if isinstance(result, tuple):
                        if not result[0]:
                            errors.append(f"{field}: {result[1]}")
                    elif not result:
                        errors.append(f"Custom validation failed for {field}")
                        
            return len(errors) == 0, errors
        except Exception as e:
            self.logger.error(f"Failed to validate config: {e}")
            return False, [str(e)]
        
    def validate_dependencies(self, dependencies: List[str]) -> Tuple[bool, List[str]]:
        """Validate system dependencies."""
        try:
            missing = []
            for dep in dependencies:
                if not shutil.which(dep):
                    missing.append(dep)
            return len(missing) == 0, missing
        except Exception as e:
            self.logger.error(f"Failed to validate dependencies: {e}")
            return False, [str(e)]
        
    def validate_game_installation(self, game_type: str, path: Path) -> Tuple[bool, str]:
        """Validate a game installation."""
        try:
            # Check if path exists
            if not path.exists():
                return False, f"Game path does not exist: {path}"
                
            # Check if path is accessible
            if not os.access(path, os.R_OK | os.W_OK):
                return False, f"Game path is not accessible: {path}"
                
            # Check for game-specific files
            if game_type == 'skyrim':
                if not (path / 'SkyrimSE.exe').exists():
                    return False, "SkyrimSE.exe not found"
            elif game_type == 'fallout4':
                if not (path / 'Fallout4.exe').exists():
                    return False, "Fallout4.exe not found"
            elif game_type == 'falloutnv':
                if not (path / 'FalloutNV.exe').exists():
                    return False, "FalloutNV.exe not found"
            elif game_type == 'oblivion':
                if not (path / 'Oblivion.exe').exists():
                    return False, "Oblivion.exe not found"
            else:
                return False, f"Unknown game type: {game_type}"
                
            return True, "Game installation is valid"
        except Exception as e:
            self.logger.error(f"Failed to validate game installation: {e}")
            return False, str(e)
        
    def validate_modlist(self, modlist_path: Path) -> Tuple[bool, List[str]]:
        """Validate a modlist installation."""
        try:
            errors = []
            
            # Check if path exists
            if not modlist_path.exists():
                errors.append(f"Modlist path does not exist: {modlist_path}")
                return False, errors
                
            # Check if path is accessible
            if not os.access(modlist_path, os.R_OK | os.W_OK):
                errors.append(f"Modlist path is not accessible: {modlist_path}")
                return False, errors
                
            # Check for ModOrganizer.ini
            if not (modlist_path / 'ModOrganizer.ini').exists():
                errors.append("ModOrganizer.ini not found")
                
            # Check for mods directory
            if not (modlist_path / 'mods').exists():
                errors.append("mods directory not found")
                
            # Check for profiles directory
            if not (modlist_path / 'profiles').exists():
                errors.append("profiles directory not found")
                
            return len(errors) == 0, errors
        except Exception as e:
            self.logger.error(f"Failed to validate modlist: {e}")
            return False, [str(e)]
        
    def validate_wine_prefix(self, app_id: str) -> Tuple[bool, str]:
        """Validate a Wine prefix."""
        try:
            # Check if prefix exists
            prefix_path = Path.home() / '.steam' / 'steam' / 'steamapps' / 'compatdata' / app_id / 'pfx'
            if not prefix_path.exists():
                return False, f"Wine prefix does not exist: {prefix_path}"
                
            # Check if prefix is accessible
            if not os.access(prefix_path, os.R_OK | os.W_OK):
                return False, f"Wine prefix is not accessible: {prefix_path}"
                
            # Check for system.reg
            if not (prefix_path / 'system.reg').exists():
                return False, "system.reg not found"
                
            return True, "Wine prefix is valid"
        except Exception as e:
            self.logger.error(f"Failed to validate Wine prefix: {e}")
            return False, str(e)
        
    def validate_steam_shortcut(self, app_id: str) -> Tuple[bool, str]:
        """Validate a Steam shortcut."""
        try:
            # Use native Steam service to get proper shortcuts.vdf path with multi-user support
            from jackify.backend.services.native_steam_service import NativeSteamService
            steam_service = NativeSteamService()
            shortcuts_path = steam_service.get_shortcuts_vdf_path()

            if not shortcuts_path:
                return False, "Could not determine shortcuts.vdf path (no active Steam user found)"

            if not shortcuts_path.exists():
                return False, "shortcuts.vdf not found"

            # Check if shortcuts.vdf is accessible
            if not os.access(shortcuts_path, os.R_OK | os.W_OK):
                return False, "shortcuts.vdf is not accessible"

            # Parse shortcuts.vdf using VDFHandler
            shortcuts_data = VDFHandler.load(str(shortcuts_path), binary=True)
                
            # Check if shortcut exists
            for shortcut in shortcuts_data.get('shortcuts', {}).values():
                if str(shortcut.get('appid')) == app_id:
                    return True, "Steam shortcut is valid"
                    
            return False, f"Steam shortcut not found: {app_id}"
        except Exception as e:
            self.logger.error(f"Failed to validate Steam shortcut: {e}")
            return False, str(e)
        
    def validate_resolution(self, resolution: str) -> Tuple[bool, str]:
        """Validate a resolution string."""
        try:
            # Check format
            if not re.match(r'^\d+x\d+$', resolution):
                return False, "Resolution must be in format WIDTHxHEIGHT"
                
            # Parse dimensions
            width, height = map(int, resolution.split('x'))
            
            # Check minimum dimensions
            if width < 640 or height < 480:
                return False, "Resolution must be at least 640x480"
                
            # Check maximum dimensions
            if width > 7680 or height > 4320:
                return False, "Resolution must be at most 7680x4320"
                
            return True, "Resolution is valid"
        except Exception as e:
            self.logger.error(f"Failed to validate resolution: {e}")
            return False, str(e)
        
    def validate_permissions(self, path: Path, required_permissions: int) -> Tuple[bool, str]:
        """Validate file or directory permissions."""
        try:
            # Get current permissions
            current_permissions = os.stat(path).st_mode & 0o777
            
            # Check if current permissions include required permissions
            if current_permissions & required_permissions != required_permissions:
                return False, f"Missing required permissions: {required_permissions:o}"
                
            return True, "Permissions are valid"
        except Exception as e:
            self.logger.error(f"Failed to validate permissions: {e}")
            return False, str(e) 