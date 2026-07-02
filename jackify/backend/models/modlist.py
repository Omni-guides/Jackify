"""
Modlist Data Models

Data structures for passing modlist context between frontend and backend.
"""

from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass

from jackify.backend.models.game_types import normalize_game_name


@dataclass
class ModlistContext:
    """Context object for modlist operations."""
    name: str
    install_dir: Path
    game_type: str
    nexus_api_key: str
    download_dir: Optional[Path] = None
    modlist_value: Optional[str] = None
    modlist_source: Optional[str] = None  # 'identifier' or 'file'
    resolution: Optional[str] = None
    mo2_exe_path: Optional[Path] = None
    skip_confirmation: bool = False
    engine_installed: bool = False  # True if installed via jackify-engine
    enb_detected: bool = False  # True if ENB was detected during configuration
    
    def __post_init__(self):
        """Convert string paths to Path objects."""
        if isinstance(self.install_dir, str):
            self.install_dir = Path(self.install_dir)
        if self.download_dir is not None and isinstance(self.download_dir, str):
            self.download_dir = Path(self.download_dir) if self.download_dir else None
        if isinstance(self.mo2_exe_path, str):
            self.mo2_exe_path = Path(self.mo2_exe_path)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for legacy compatibility."""
        return {
            'modlist_name': self.name,
            'install_dir': str(self.install_dir),
            'download_dir': str(self.download_dir) if self.download_dir else None,
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
        raw_dl = data.get('download_dir')
        download_dir = Path(raw_dl) if raw_dl and raw_dl != 'None' else None
        return cls(
            name=data.get('modlist_name', ''),
            install_dir=Path(data.get('install_dir', '')),
            download_dir=download_dir,
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


def build_modlist_context(
    name: str,
    install_dir,
    game_type: str,
    nexus_api_key: str = '',
    download_dir=None,
    modlist_value: Optional[str] = None,
    modlist_source: Optional[str] = None,
    resolution: Optional[str] = None,
    mo2_exe_path=None,
    skip_confirmation: bool = False,
    engine_installed: bool = False,
    enb_detected: bool = False,
) -> ModlistContext:
    """Canonical factory for ModlistContext.

    Normalises game_type via game_types.normalize_game_name so both frontends
    produce consistent canonical strings.  Falls back to the raw value when the
    name is not in the known map (unknown/custom game types).
    """
    canonical = normalize_game_name(game_type)
    return ModlistContext(
        name=name,
        install_dir=install_dir,
        game_type=canonical if canonical else game_type,
        nexus_api_key=nexus_api_key,
        download_dir=download_dir,
        modlist_value=modlist_value,
        modlist_source=modlist_source,
        resolution=resolution,
        mo2_exe_path=mo2_exe_path,
        skip_confirmation=skip_confirmation,
        engine_installed=engine_installed,
        enb_detected=enb_detected,
    )