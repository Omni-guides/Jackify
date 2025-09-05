"""
Modlist Data Models

Data structures for passing modlist context between frontend and backend.
"""

from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass


@dataclass
class ModlistContext:
    """Context object for modlist operations."""
    name: str
    install_dir: Path
    download_dir: Path
    game_type: str
    nexus_api_key: str
    modlist_value: Optional[str] = None
    modlist_source: Optional[str] = None  # 'identifier' or 'file'
    resolution: Optional[str] = None
    mo2_exe_path: Optional[Path] = None
    skip_confirmation: bool = False
    engine_installed: bool = False  # True if installed via jackify-engine
    
    def __post_init__(self):
        """Convert string paths to Path objects."""
        if isinstance(self.install_dir, str):
            self.install_dir = Path(self.install_dir)
        if isinstance(self.download_dir, str):
            self.download_dir = Path(self.download_dir)
        if isinstance(self.mo2_exe_path, str):
            self.mo2_exe_path = Path(self.mo2_exe_path)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for legacy compatibility."""
        return {
            'modlist_name': self.name,
            'install_dir': str(self.install_dir),
            'download_dir': str(self.download_dir),
            'game_type': self.game_type,
            'nexus_api_key': self.nexus_api_key,
            'modlist_value': self.modlist_value,
            'modlist_source': self.modlist_source,
            'resolution': self.resolution,
            'mo2_exe_path': str(self.mo2_exe_path) if self.mo2_exe_path else None,
            'skip_confirmation': self.skip_confirmation,
            'engine_installed': self.engine_installed,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ModlistContext':
        """Create from dictionary for legacy compatibility."""
        return cls(
            name=data.get('modlist_name', ''),
            install_dir=Path(data.get('install_dir', '')),
            download_dir=Path(data.get('download_dir', '')),
            game_type=data.get('game_type', ''),
            nexus_api_key=data.get('nexus_api_key', ''),
            modlist_value=data.get('modlist_value'),
            modlist_source=data.get('modlist_source'),
            resolution=data.get('resolution'),
            mo2_exe_path=Path(data['mo2_exe_path']) if data.get('mo2_exe_path') else None,
            skip_confirmation=data.get('skip_confirmation', False),
            engine_installed=data.get('engine_installed', False),
        )


@dataclass
class ModlistInfo:
    """Information about a modlist from the engine."""
    id: str
    name: str
    game: str
    description: Optional[str] = None
    version: Optional[str] = None
    size: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        result = {
            'id': self.id,
            'name': self.name,
            'game': self.game,
            'description': self.description,
            'version': self.version,
            'size': self.size,
        }
        
        # Include any dynamically added attributes
        if hasattr(self, 'machine_url'):
            result['machine_url'] = self.machine_url
        if hasattr(self, 'download_size'):
            result['download_size'] = self.download_size
        if hasattr(self, 'install_size'):
            result['install_size'] = self.install_size
        if hasattr(self, 'total_size'):
            result['total_size'] = self.total_size
        if hasattr(self, 'status_down'):
            result['status_down'] = self.status_down
        if hasattr(self, 'status_nsfw'):
            result['status_nsfw'] = self.status_nsfw
            
        return result 