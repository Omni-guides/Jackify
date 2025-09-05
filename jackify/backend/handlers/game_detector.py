"""
GameDetector module for detecting and managing game-related information.
This module handles game type detection, version detection, and game-specific requirements.
"""

import os
import logging
from pathlib import Path
from typing import Optional, Dict, List, Tuple

class GameDetector:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.supported_games = {
            'skyrim': ['Skyrim Special Edition', 'Skyrim'],
            'fallout4': ['Fallout 4'],
            'falloutnv': ['Fallout New Vegas'],
            'oblivion': ['Oblivion'],
            'starfield': ['Starfield'],
            'oblivion_remastered': ['Oblivion Remastered']
        }
        
    def detect_game_type(self, modlist_name: str) -> Optional[str]:
        """Detect the game type from a modlist name."""
        modlist_lower = modlist_name.lower()
        
        # Check for game-specific keywords in modlist name
        # Check for Oblivion Remastered first since "oblivion" is a substring
        if any(keyword in modlist_lower for keyword in ['oblivion remastered', 'oblivionremastered', 'oblivion_remastered']):
            return 'oblivion_remastered'
        elif any(keyword in modlist_lower for keyword in ['skyrim', 'sse', 'skse', 'dragonborn', 'dawnguard']):
            return 'skyrim'
        elif any(keyword in modlist_lower for keyword in ['fallout 4', 'fo4', 'f4se', 'commonwealth']):
            return 'fallout4'
        elif any(keyword in modlist_lower for keyword in ['fallout new vegas', 'fonv', 'fnv', 'new vegas', 'nvse']):
            return 'falloutnv'
        elif any(keyword in modlist_lower for keyword in ['oblivion', 'obse', 'shivering isles']):
            return 'oblivion'
        elif any(keyword in modlist_lower for keyword in ['starfield', 'sf', 'starfieldse']):
            return 'starfield'
        
        self.logger.debug(f"Could not detect game type from modlist name: {modlist_name}")
        return None
        
    def detect_game_version(self, game_type: str, modlist_path: Path) -> Optional[str]:
        """Detect the game version from the modlist path."""
        try:
            # Look for ModOrganizer.ini to get game info
            mo_ini = modlist_path / "ModOrganizer.ini"
            if mo_ini.exists():
                with open(mo_ini, 'r', encoding='utf-8') as f:
                    content = f.read()
                    
                # Extract game version info from MO2 config
                if 'gameName=' in content:
                    for line in content.splitlines():
                        if line.startswith('gameName='):
                            game_name = line.split('=', 1)[1].strip()
                            return game_name
                            
            self.logger.debug(f"Could not detect game version for {game_type} at {modlist_path}")
            return None
            
        except Exception as e:
            self.logger.error(f"Error detecting game version: {e}")
            return None
        
    def detect_game_path(self, game_type: str, modlist_path: Path) -> Optional[Path]:
        """Detect the game installation path."""
        try:
            # Look for ModOrganizer.ini to get game path
            mo_ini = modlist_path / "ModOrganizer.ini"
            if mo_ini.exists():
                with open(mo_ini, 'r', encoding='utf-8') as f:
                    content = f.read()
                    
                # Extract game path from MO2 config
                for line in content.splitlines():
                    if line.startswith('gamePath='):
                        game_path = line.split('=', 1)[1].strip()
                        return Path(game_path) if game_path else None
                        
            self.logger.debug(f"Could not detect game path for {game_type} at {modlist_path}")
            return None
            
        except Exception as e:
            self.logger.error(f"Error detecting game path: {e}")
            return None
        
    def get_game_requirements(self, game_type: str) -> Dict:
        """Get the requirements for a specific game type."""
        requirements = {
            'skyrim': {
                'launcher': 'SKSE',
                'min_proton_version': '6.0',
                'required_dlc': ['Dawnguard', 'Hearthfire', 'Dragonborn'],
                'compatibility_tools': ['protontricks', 'winetricks']
            },
            'fallout4': {
                'launcher': 'F4SE',
                'min_proton_version': '6.0', 
                'required_dlc': [],
                'compatibility_tools': ['protontricks', 'winetricks']
            },
            'falloutnv': {
                'launcher': 'NVSE',
                'min_proton_version': '5.0',
                'required_dlc': [],
                'compatibility_tools': ['protontricks', 'winetricks']
            },
            'oblivion': {
                'launcher': 'OBSE',
                'min_proton_version': '5.0',
                'required_dlc': [],
                'compatibility_tools': ['protontricks', 'winetricks']
            },
            'starfield': {
                'launcher': 'SFSE',
                'min_proton_version': '8.0',
                'required_dlc': [],
                'compatibility_tools': ['protontricks', 'winetricks']
            },
            'oblivion_remastered': {
                'launcher': 'OBSE',
                'min_proton_version': '8.0',
                'required_dlc': [],
                'compatibility_tools': ['protontricks', 'winetricks']
            }
        }
        
        return requirements.get(game_type, {})
        
    def detect_mods(self, modlist_path: Path) -> List[Dict]:
        """Detect installed mods in a modlist."""
        mods = []
        try:
            # Look for mods directory in MO2 structure
            mods_dir = modlist_path / "mods"
            if mods_dir.exists() and mods_dir.is_dir():
                for mod_dir in mods_dir.iterdir():
                    if mod_dir.is_dir():
                        mod_info = {
                            'name': mod_dir.name,
                            'path': str(mod_dir),
                            'enabled': True  # Assume enabled by default
                        }
                        
                        # Check for meta.ini for more details
                        meta_ini = mod_dir / "meta.ini"
                        if meta_ini.exists():
                            try:
                                with open(meta_ini, 'r', encoding='utf-8') as f:
                                    meta_content = f.read()
                                    # Parse basic mod info from meta.ini
                                    for line in meta_content.splitlines():
                                        if line.startswith('modid='):
                                            mod_info['nexus_id'] = line.split('=', 1)[1].strip()
                                        elif line.startswith('version='):
                                            mod_info['version'] = line.split('=', 1)[1].strip()
                            except Exception:
                                pass  # Continue without meta info
                                
                        mods.append(mod_info)
                        
        except Exception as e:
            self.logger.error(f"Error detecting mods: {e}")
            
        return mods
        
    def detect_launcher(self, game_type: str, modlist_path: Path) -> Optional[str]:
        """Detect the game launcher type (SKSE, F4SE, etc)."""
        launcher_map = {
            'skyrim': 'SKSE',
            'fallout4': 'F4SE', 
            'falloutnv': 'NVSE',
            'oblivion': 'OBSE',
            'starfield': 'SFSE',
            'oblivion_remastered': 'OBSE'
        }
        
        expected_launcher = launcher_map.get(game_type)
        if not expected_launcher:
            return None
            
        # Check if launcher executable exists
        launcher_exe = f"{expected_launcher.lower()}_loader.exe"
        if (modlist_path / launcher_exe).exists():
            return expected_launcher
            
        return expected_launcher  # Return expected even if not found
        
    def get_launcher_path(self, launcher_type: str, modlist_path: Path) -> Optional[Path]:
        """Get the path to the game launcher."""
        launcher_exe = f"{launcher_type.lower()}_loader.exe"
        launcher_path = modlist_path / launcher_exe
        
        if launcher_path.exists():
            return launcher_path
            
        return None
        
    def detect_compatibility_requirements(self, game_type: str) -> List[str]:
        """Detect compatibility requirements for a game type."""
        requirements = {
            'skyrim': ['vcrun2019', 'dotnet48', 'dxvk'],
            'fallout4': ['vcrun2019', 'dotnet48', 'dxvk'],
            'falloutnv': ['vcrun2019', 'dotnet48'],
            'oblivion': ['vcrun2019', 'dotnet48'],
            'starfield': ['vcrun2022', 'dotnet6', 'dotnet7', 'dxvk'],
            'oblivion_remastered': ['vcrun2022', 'dotnet6', 'dotnet7', 'dxvk']
        }
        
        return requirements.get(game_type, [])
        
    def validate_game_installation(self, game_type: str, game_path: Path) -> bool:
        """Validate a game installation."""
        if not game_path or not game_path.exists():
            return False
            
        # Check for game-specific executables
        game_executables = {
            'skyrim': ['SkyrimSE.exe', 'Skyrim.exe'],
            'fallout4': ['Fallout4.exe'],
            'falloutnv': ['FalloutNV.exe'],
            'oblivion': ['Oblivion.exe']
        }
        
        executables = game_executables.get(game_type, [])
        for exe in executables:
            if (game_path / exe).exists():
                return True
                
        return False
        
    def get_game_specific_config(self, game_type: str) -> Dict:
        """Get game-specific configuration requirements."""
        configs = {
            'skyrim': {
                'ini_files': ['Skyrim.ini', 'SkyrimPrefs.ini', 'SkyrimCustom.ini'],
                'config_dirs': ['Data', 'Saves'],
                'registry_keys': ['HKEY_LOCAL_MACHINE\\SOFTWARE\\Bethesda Softworks\\Skyrim Special Edition']
            },
            'fallout4': {
                'ini_files': ['Fallout4.ini', 'Fallout4Prefs.ini', 'Fallout4Custom.ini'],
                'config_dirs': ['Data', 'Saves'],
                'registry_keys': ['HKEY_LOCAL_MACHINE\\SOFTWARE\\Bethesda Softworks\\Fallout 4']
            },
            'falloutnv': {
                'ini_files': ['Fallout.ini', 'FalloutPrefs.ini'],
                'config_dirs': ['Data', 'Saves'],
                'registry_keys': ['HKEY_LOCAL_MACHINE\\SOFTWARE\\Bethesda Softworks\\FalloutNV']
            },
            'oblivion': {
                'ini_files': ['Oblivion.ini'],
                'config_dirs': ['Data', 'Saves'],
                'registry_keys': ['HKEY_LOCAL_MACHINE\\SOFTWARE\\Bethesda Softworks\\Oblivion']
            }
        }
        
        return configs.get(game_type, {}) 