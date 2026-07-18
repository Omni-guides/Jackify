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
    """Resolve the Proton prefix path for a Steam AppID.

    Delegates to PathHandler.find_compat_data(), which scans all configured
    Steam library folders, not just the default Steam root - users with
    custom/secondary libraries (e.g. on other mounts) can have compatdata
    outside the default install location.
    """
    if not appid:
        return None
    from jackify.backend.handlers.path_handler import PathHandler
    compatdata = PathHandler.find_compat_data(str(appid))
    if compatdata is None:
        return None
    pfx = compatdata / "pfx"
    return pfx if pfx.is_dir() else None


def run_install_verification(pfx: Path, modlist_dir: Path, game_type: str, appid: str = "", modlist_name: str = ""):
    """Run the install verifier and return a Results object, or None on failure."""
    try:
        verifier = _load_verifier()
        return verifier.run_verification(pfx, modlist_dir, game_type, appid, modlist_name)
    except Exception as e:
        logger.warning("Install verifier failed: %s", e, exc_info=True)
        raise
