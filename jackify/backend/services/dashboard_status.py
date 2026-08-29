"""
Lifecycle Dashboard status model: `ready` / `update_available` / `not_configured` / `missing` /
`unknown_version`, computed on demand per install (section 4).

`compute_status()` is the pure decision function - fully unit testable. `resolve_all_statuses()`
is the thin orchestration layer that gathers the filesystem/prefix facts and gallery lookups the
decision needs; both the prefix resolver and the gallery version map are injectable so tests
never need a real Steam/protontricks environment.

Gallery lookups must not happen here: `gallery_versions` is built by the caller from the
already-prefetched gallery cache, since the dashboard must not issue a network call on open.
"""
import logging
from pathlib import Path
from typing import Callable, Dict, List, Optional

from packaging.version import InvalidVersion, Version

from .install_registry import InstallEntry
from .update_detection import normalize_version_token

logger = logging.getLogger(__name__)

STATUS_READY = "ready"
STATUS_UPDATE_AVAILABLE = "update_available"
STATUS_NOT_CONFIGURED = "not_configured"
STATUS_MISSING = "missing"
STATUS_UNKNOWN_VERSION = "unknown_version"


def _gallery_is_newer(gallery: str, installed: str) -> bool:
    """True only if the gallery version is a strictly greater ordered version than installed.
    A plain inequality check would flag a local .wabbajack install newer than the gallery's
    listing (e.g. installed 1.2.0, gallery 1.1.3) as an update, which is backwards - the
    "Update Available" badge is a claim about direction, not just difference. Unparseable
    versions return False rather than raising, since "cannot tell" must not present as an
    update either."""
    try:
        return Version(gallery) > Version(installed)
    except InvalidVersion:
        return False


def compute_status(
    entry: InstallEntry,
    dir_exists: bool,
    prefix_exists: bool,
    gallery_version: Optional[str] = None,
) -> str:
    """
    Decide an install's status. Priority order matters: a gone directory or missing
    configuration always wins over a version comparison, since there is nothing installed or
    configured to meaningfully compare in those cases.
    """
    if not dir_exists:
        return STATUS_MISSING
    if not entry.appid or not prefix_exists:
        return STATUS_NOT_CONFIGURED
    if not entry.installed_version:
        return STATUS_UNKNOWN_VERSION

    if gallery_version:
        installed = normalize_version_token(entry.installed_version)
        gallery = normalize_version_token(gallery_version)
        if installed and gallery and installed != gallery and _gallery_is_newer(gallery, installed):
            return STATUS_UPDATE_AVAILABLE

    return STATUS_READY


def _default_prefix_resolver(appid: str) -> Optional[str]:
    try:
        from jackify.backend.handlers.protontricks_handler import ProtontricksHandler
        from jackify.backend.services.platform_detection_service import PlatformDetectionService
        platform_service = PlatformDetectionService.get_instance()
        handler = ProtontricksHandler(steamdeck=platform_service.is_steamdeck)
        # A card whose modlist is installed but not yet configured has no prefix, which is
        # a normal state to poll, not a fault worth an error line per refresh.
        return handler.get_wine_prefix_path(appid, log_missing=False)
    except Exception as e:
        logger.debug("Prefix resolution failed for appid %s: %s", appid, e)
        return None


def get_proton_version_display(appid: str) -> Optional[str]:
    """
    Best-effort Proton version label for a card, reading config.vdf's CompatToolMapping - the
    same first check `ModlistDetectionMixin._detect_proton_version()` does, but as a standalone
    lookup that doesn't need a fully-populated ModlistHandler. Returns None rather than the
    full detector's registry-file fallback chain; good enough for a status card, not a
    replacement for the full detector used during configure.
    """
    try:
        from jackify.backend.handlers.path_handler import PathHandler
        import vdf

        config_vdf_path = PathHandler().find_steam_config_vdf()
        if not config_vdf_path or not config_vdf_path.exists():
            return None
        with open(config_vdf_path, 'r') as f:
            data = vdf.load(f)
        mapping = (
            data.get('InstallConfigStore', {}).get('Software', {})
            .get('Valve', {}).get('Steam', {}).get('CompatToolMapping', {})
        )
        tool_name = mapping.get(str(appid), {}).get('name', '')
        return tool_name or None
    except Exception as e:
        logger.debug("Proton version lookup failed for appid %s: %s", appid, e)
        return None


def resolve_all_statuses(
    entries: List[InstallEntry],
    gallery_versions: Optional[Dict[str, str]] = None,
    prefix_resolver: Optional[Callable[[str], Optional[str]]] = None,
) -> Dict[str, str]:
    """
    Compute status for every entry.

    `gallery_versions` maps machine_url -> latest available version, built by the caller from
    already-prefetched gallery metadata. `prefix_resolver` maps appid -> prefix path or None;
    defaults to a real Protontricks-backed lookup, injectable for tests.

    Returns {install_id: status}.
    """
    gallery_versions = gallery_versions or {}
    resolver = prefix_resolver or _default_prefix_resolver

    from jackify.backend.handlers.validation_handler import ValidationHandler
    validator = ValidationHandler()

    statuses = {}
    for entry in entries:
        # A bare is_dir() check would miss a directory that survives but has had its
        # contents cleared (e.g. a wiped SD card entry, or manual cleanup that left the
        # parent folder behind) - looks_like_modlist_dir() is the same MO2-presence check
        # used elsewhere in the codebase to decide whether a directory is a real install.
        dir_exists = validator.looks_like_modlist_dir(Path(entry.install_dir))
        prefix_exists = bool(dir_exists and entry.appid and resolver(entry.appid))
        gallery_version = gallery_versions.get(entry.machine_url) if entry.machine_url else None
        statuses[entry.install_id] = compute_status(entry, dir_exists, prefix_exists, gallery_version)
    return statuses
