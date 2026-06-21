"""
Engine Invoker

Resolves the active install engine and builds the appropriate subprocess command.
Keeps engine-specific CLI differences isolated from install workflow code.
"""
import logging
import os
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


def get_active_engine_id() -> str:
    from jackify.backend.services.tool_registry import get_active_engine_id as _get
    return _get()


def is_clf3_active() -> bool:
    return get_active_engine_id() == "clf3"


def ensure_engine_available(engine_id: str = "jackify-engine") -> Tuple[bool, str]:
    """
    Check that the given engine binary is present and download it if not.
    Returns (True, path) on success, (False, error_message) on failure.
    Call this at startup before the first install attempt.
    """
    from jackify.backend.services.tool_registry import ToolRegistry
    path = get_engine_path(engine_id)
    if path:
        return True, path
    logger.info("Engine %s not found, attempting download via Tools Hub", engine_id)
    ok, msg = ToolRegistry().install(engine_id)
    if not ok:
        return False, msg
    path = get_engine_path(engine_id)
    if not path:
        return False, f"{engine_id} downloaded but binary not found after install"
    return True, path


def get_engine_path(engine_id: str) -> Optional[str]:
    """Return the filesystem path to the engine binary for the given engine_id."""
    from jackify.backend.services.tool_registry import ToolRegistry
    path = ToolRegistry().get_binary_path(engine_id)
    if path and path.is_file():
        return str(path)

    if engine_id == "jackify-engine":
        from jackify.backend.core.modlist_operations import get_jackify_engine_path
        return get_jackify_engine_path()

    logger.warning("Engine binary not found for engine_id=%s", engine_id)
    return None


def get_active_engine_path() -> Optional[str]:
    """Return the binary path for the currently active engine."""
    return get_engine_path(get_active_engine_id())


def resolve_game_dir(game_type: Optional[str], modlist_path: Optional[str] = None) -> Optional[str]:
    """
    Resolve the vanilla game installation directory for CLF3's --game argument.
    Searches Steam and Heroic-managed stores in order.
    Returns None if the path cannot be determined.
    Use resolve_game_location() when the store identity is also needed.
    """
    result = resolve_game_location(game_type)
    return result[0] if result else None


def resolve_game_location(game_type: Optional[str]) -> Optional[tuple]:
    """
    Return (path_str, store) for the detected game installation, or None.
    store is one of: 'steam', 'gog', 'epic', 'unknown'.
    """
    if not game_type:
        return None
    try:
        from jackify.backend.handlers.vanilla_game_finder import VanillaGameFinder
        result = VanillaGameFinder().find(game_type)
        if result:
            path, store = result
            return str(path), store
    except Exception as e:
        logger.debug("Game dir detection failed for %s: %s", game_type, e)
    return None


def build_install_command(
    engine_id: str,
    engine_path: str,
    wabbajack: str,
    install_dir: str,
    downloads_dir: str,
    game_dir: Optional[str] = None,
    install_mode: str = "online",
    debug: bool = False,
) -> List[str]:
    """Build the subprocess install command for the given engine."""
    if engine_id == "clf3":
        return _build_clf3_command(engine_path, wabbajack, install_dir, downloads_dir, game_dir)
    return _build_jackify_engine_command(engine_path, wabbajack, install_dir, downloads_dir, install_mode, debug, game_dir)


def _build_jackify_engine_command(
    engine_path: str,
    wabbajack: str,
    install_dir: str,
    downloads_dir: str,
    install_mode: str,
    debug: bool,
    game_dir: Optional[str] = None,
) -> List[str]:
    cmd = [engine_path, "install", "--show-file-progress"]
    if wabbajack.endswith(".wabbajack") and os.path.isfile(wabbajack):
        cmd += ["-w", wabbajack]
    else:
        cmd += ["-m", wabbajack]
    cmd += ["-o", install_dir, "-d", downloads_dir]
    if game_dir:
        cmd += ["-g", game_dir]
    if debug:
        cmd.append("--debug")
    return cmd


def _read_resource_settings() -> dict:
    """Read resource_settings.json from the Jackify config dir; return empty dict on any failure."""
    try:
        from jackify.shared.paths import get_jackify_config_dir
        import json
        path = get_jackify_config_dir() / "resource_settings.json"
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _clf3_default_workers() -> int:
    """Default worker count matching jackify-engine: full cpu_count."""
    import multiprocessing
    return max(1, multiprocessing.cpu_count() or 4)


def _build_clf3_command(
    engine_path: str,
    wabbajack: str,
    install_dir: str,
    downloads_dir: str,
    game_dir: Optional[str] = None,
) -> List[str]:
    # Positional order: <WABBAJACK_FILE> <DOWNLOADS> <OUTPUT>
    # CLF3 performs its own game detection (Steam + Heroic) with file verification.
    # game_dir is reserved for explicit edge-case overrides only.
    cmd = [engine_path, "install", "--jackify"]
    if os.environ.get("JACKIFY_CLF3_VERBOSE"):
        cmd.append("--verbose")
        logger.info("CLF3 verbose mode enabled (JACKIFY_CLF3_VERBOSE)")
    if game_dir:
        cmd += ["--game", game_dir]

    res = _read_resource_settings()
    default = _clf3_default_workers()

    def _tasks(key: str) -> int:
        val = res.get(key, {}).get("MaxTasks", 0)
        return val if val > 0 else default

    concurrent = _tasks("Downloads")
    install_workers = _tasks("Installer")
    sevenzip_workers = _tasks("File Extractor")

    cmd += [
        "--concurrent", str(concurrent),
        "--install-workers", str(install_workers),
        "--sevenzip-workers", str(sevenzip_workers),
    ]
    logger.debug(
        "CLF3 resource flags: concurrent=%d install_workers=%d sevenzip_workers=%d (from %s)",
        concurrent, install_workers, sevenzip_workers,
        "resource_settings.json" if res else "default (cpu_count)",
    )

    cmd += [wabbajack, downloads_dir, install_dir]
    return cmd
