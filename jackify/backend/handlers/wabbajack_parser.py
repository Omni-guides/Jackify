"""
Wabbajack file parser for extracting game type information from .wabbajack files.

This module provides efficient parsing of .wabbajack files (which are ZIP archives)
to extract game type information without loading the entire archive.
"""

import json
import logging
import zipfile
from pathlib import Path
from typing import Optional, Dict, Any


class WabbajackParser:
    """Parser for .wabbajack files to extract game type information."""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
        # Mapping from Wabbajack Game enum values to Jackify game types
        self.game_type_mapping = {
            'Starfield': 'starfield',
            'oblivionremastered': 'oblivion_remastered',
            'SkyrimSpecialEdition': 'skyrim',
            'Fallout4': 'fallout4',
            'FalloutNewVegas': 'falloutnv',
            'Oblivion': 'oblivion',
            'Skyrim': 'skyrim',  # Legacy Skyrim
            'Fallout3': 'fallout3',  # For completeness
            'SkyrimVR': 'skyrim',  # Treat as Skyrim
            'Fallout4VR': 'fallout4',  # Treat as Fallout 4
            'Enderal': 'enderal',  # Enderal: Forgotten Stories
            'EnderalSpecialEdition': 'enderal',  # Enderal SE
        }
        
        # List of supported games in Jackify
        self.supported_games = [
            'skyrim', 'fallout4', 'falloutnv', 'oblivion', 
            'starfield', 'oblivion_remastered', 'enderal'
        ]
    
    def parse_wabbajack_game_type(self, wabbajack_path: Path) -> Optional[tuple]:
        """
        Parse a .wabbajack file to extract the game type.
        
        Args:
            wabbajack_path: Path to the .wabbajack file
            
        Returns:
            Tuple containing Jackify game type string (e.g., 'skyrim', 'starfield') and raw game type string
        """
        try:
            if not wabbajack_path.exists():
                self.logger.error(f"Wabbajack file not found: {wabbajack_path}")
                return None
                
            if not wabbajack_path.suffix.lower() == '.wabbajack':
                self.logger.error(f"File is not a .wabbajack file: {wabbajack_path}")
                return None
            
            # Open the .wabbajack file as a ZIP archive
            with zipfile.ZipFile(wabbajack_path, 'r') as zip_file:
                # Look for the modlist file (could be 'modlist' or 'modlist.json')
                modlist_files = [f for f in zip_file.namelist() if f in ['modlist', 'modlist.json']]
                
                if not modlist_files:
                    self.logger.error(f"No modlist file found in {wabbajack_path}")
                    return None
                
                # Extract and parse the modlist file
                modlist_file = modlist_files[0]
                with zip_file.open(modlist_file) as modlist_stream:
                    modlist_data = json.load(modlist_stream)
                
                # Extract the game type
                game_type = modlist_data.get('GameType')
                if not game_type:
                    self.logger.error(f"No GameType found in modlist: {wabbajack_path}")
                    return None
                
                # Map to Jackify game type
                jackify_game_type = self.game_type_mapping.get(game_type)
                if jackify_game_type:
                    self.logger.info(f"Detected game type: {game_type} -> {jackify_game_type}")
                    return jackify_game_type, game_type
                else:
                    self.logger.warning(f"Unknown game type in modlist: {game_type}")
                    return 'unknown', game_type
                    
        except zipfile.BadZipFile:
            self.logger.error(f"Invalid ZIP file: {wabbajack_path}")
            return None
        except json.JSONDecodeError as e:
            self.logger.error(f"Invalid JSON in modlist file: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Error parsing .wabbajack file {wabbajack_path}: {e}")
            return None
    
    def is_supported_game(self, game_type: str) -> bool:
        """
        Check if a game type is supported by Jackify's post-install configuration.
        
        Args:
            game_type: Jackify game type string
            
        Returns:
            True if the game is supported, False otherwise
        """
        return game_type in self.supported_games
    
    def get_supported_games_list(self) -> list:
        """
        Get the list of games supported by Jackify's post-install configuration.
        
        Returns:
            List of supported game names
        """
        return self.supported_games.copy()
    
    def get_supported_games_display_names(self) -> list:
        """
        Get the display names of supported games for user-facing messages.
        
        Returns:
            List of display names for supported games
        """
        display_names = {
            'skyrim': 'Skyrim Special Edition',
            'fallout4': 'Fallout 4', 
            'falloutnv': 'Fallout New Vegas',
            'oblivion': 'Oblivion',
            'starfield': 'Starfield',
            'oblivion_remastered': 'Oblivion Remastered',
            'enderal': 'Enderal'
        }
        return [display_names.get(game, game) for game in self.supported_games]


# Convenience function for easy access
def parse_wabbajack_game_type(wabbajack_path: Path) -> Optional[tuple]:
    """
    Convenience function to parse a .wabbajack file and get the game type.
    
    Args:
        wabbajack_path: Path to the .wabbajack file
        
    Returns:
        Tuple containing Jackify game type string and raw game type string or None if parsing fails
    """
    parser = WabbajackParser()
    return parser.parse_wabbajack_game_type(wabbajack_path) 