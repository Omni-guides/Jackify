"""Service for running verify_install.py from Jackify workflows."""

import importlib.util
import logging
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_BUNDLED_PATH = Path(__file__).parent.parent.parent / "tools" / "verify_install.py"


def _load_verifier():
    spec = importlib.util.spec_from_file_location("_verify_install_bundled", _BUNDLED_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot locate bundled verify_install.py at {_BUNDLED_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("_verify_install_bundled", module)
    spec.loader.exec_module(module)
    return module


def resolve_pfx_for_appid(appid: str) -> Optional[Path]:
    """Resolve the Proton prefix path for a Steam AppID."""
    if not appid:
        return None
    steam_roots = [
        Path.home() / ".steam" / "steam",
        Path.home() / ".local" / "share" / "Steam",
        Path.home() / ".steam" / "root",
        Path.home() / ".var" / "app" / "com.valvesoftware.Steam" / "data" / "Steam",
    ]
    for root in steam_roots:
        pfx = root / "steamapps" / "compatdata" / str(appid) / "pfx"
        if pfx.is_dir():
            return pfx
    return None


def run_install_verification(pfx: Path, modlist_dir: Path, game_type: str, appid: str = "", modlist_name: str = ""):
    """Run the install verifier and return a Results object, or None on failure."""
    try:
        verifier = _load_verifier()
        return verifier.run_verification(pfx, modlist_dir, game_type, appid, modlist_name)
    except Exception as e:
        logger.warning("Install verifier failed: %s", e, exc_info=True)
        raise
