"""
Configuration Data Models

Data structures for configuration context between frontend and backend.
"""

from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass


@dataclass
class ConfigurationContext:
    """Context object for modlist configuration operations."""
    modlist_name: str
    install_dir: Path
    mo2_exe_path: Optional[Path] = None
    resolution: Optional[str] = None
    download_dir: Optional[Path] = None
    nexus_api_key: Optional[str] = None
    modlist_value: Optional[str] = None
    modlist_source: Optional[str] = None
    skip_confirmation: bool = False
    
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
            'name': self.modlist_name,
            'path': str(self.install_dir),
            'mo2_exe_path': str(self.mo2_exe_path) if self.mo2_exe_path else None,
            'resolution': self.resolution,
            'download_dir': str(self.download_dir) if self.download_dir else None,
            'nexus_api_key': self.nexus_api_key,
            'modlist_value': self.modlist_value,
            'modlist_source': self.modlist_source,
            'skip_confirmation': self.skip_confirmation,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ConfigurationContext':
        """Create from dictionary for legacy compatibility."""
        return cls(
            modlist_name=data.get('name', data.get('modlist_name', '')),
            install_dir=Path(data.get('path', data.get('install_dir', ''))),
            mo2_exe_path=Path(data['mo2_exe_path']) if data.get('mo2_exe_path') else None,
            resolution=data.get('resolution'),
            download_dir=Path(data['download_dir']) if data.get('download_dir') else None,
            nexus_api_key=data.get('nexus_api_key'),
            modlist_value=data.get('modlist_value'),
            modlist_source=data.get('modlist_source'),
            skip_confirmation=data.get('skip_confirmation', False),
        )


@dataclass
class SystemInfo:
    """System information context."""
    is_steamdeck: bool
    steam_root: Optional[Path] = None
    steam_user_id: Optional[str] = None
    proton_version: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'is_steamdeck': self.is_steamdeck,
            'steam_root': str(self.steam_root) if self.steam_root else None,
            'steam_user_id': self.steam_user_id,
            'proton_version': self.proton_version,
        } 