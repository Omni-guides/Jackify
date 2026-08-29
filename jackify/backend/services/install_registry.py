"""
Install registry: persistent record of every modlist Jackify knows about.

The one genuinely new piece the Lifecycle Dashboard needs - everything else it displays already
exists (jackify_meta.json, update_detection.py, ModlistHandler's Proton lookup). A JSON file at
$jackify_data/installs.json, matching every other piece of Jackify state (tool manifests,
disk caches) rather than introducing a database. See
docs/0.8_work/modlist_lifecycle_dashboard.md sections 2-3.
"""
import datetime
import hashlib
import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional

from jackify.shared.paths import get_jackify_data_dir

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = 1


def compute_install_id(install_dir: str) -> str:
    """Stable id for an install: a hash of its realpath, so a re-mounted drive or a symlinked
    path still resolves to the same entry."""
    real = os.path.realpath(install_dir)
    return hashlib.sha256(real.encode("utf-8")).hexdigest()[:16]


@dataclass
class InstallEntry:
    install_id: str
    install_dir: str
    modlist_name: str
    machine_url: Optional[str] = None
    game_type: Optional[str] = None
    appid: Optional[str] = None
    installed_version: Optional[str] = None
    install_date: Optional[str] = None
    jackify_version: Optional[str] = None
    last_seen: Optional[str] = None
    last_configured: Optional[str] = None
    missing: bool = False
    # "jackify" (installed/configured by this Jackify) or "backfill" (discovered via an existing
    # Steam shortcut - may not be a Jackify install at all, per dashboard decision Q2).
    provenance: str = "jackify"


def _registry_path() -> Path:
    return get_jackify_data_dir() / "installs.json"


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".installs_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load_registry() -> List[InstallEntry]:
    path = _registry_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Install registry unreadable, starting fresh: %s", e)
        return []

    entries = []
    for raw in data.get("installs", []):
        try:
            entries.append(InstallEntry(**raw))
        except TypeError as e:
            logger.warning("Skipping malformed install registry entry: %s", e)
    return entries


def save_registry(entries: List[InstallEntry]) -> None:
    try:
        _atomic_write(_registry_path(), {
            "schema_version": _SCHEMA_VERSION,
            "installs": [asdict(e) for e in entries],
        })
    except Exception as e:
        logger.warning("Failed to save install registry: %s", e)


def register_install(
    install_dir: str,
    modlist_name: str,
    game_type: Optional[str] = None,
    machine_url: Optional[str] = None,
    installed_version: Optional[str] = None,
    install_date: Optional[str] = None,
    jackify_version: Optional[str] = None,
    appid: Optional[str] = None,
    configured: bool = False,
) -> InstallEntry:
    """
    Add or update an install's registry entry.

    Called beside write_modlist_meta() at install and configure completion (population order
    #1 in the design doc) - not a new hook, the same completion points that already write
    jackify_meta.json.
    """
    now = datetime.datetime.now().isoformat(timespec="seconds")

    entries = load_registry()
    install_id = compute_install_id(install_dir)
    existing = next((e for e in entries if e.install_id == install_id), None)
    is_new_entry = existing is None

    if existing is None:
        existing = InstallEntry(
            install_id=install_id,
            install_dir=os.path.realpath(install_dir),
            modlist_name=modlist_name,
        )
        entries.append(existing)

    existing.install_dir = os.path.realpath(install_dir)
    existing.modlist_name = modlist_name
    existing.missing = False
    existing.last_seen = now
    existing.provenance = "jackify"
    if game_type is not None:
        existing.game_type = game_type
    if machine_url is not None:
        existing.machine_url = machine_url
    if installed_version is not None:
        existing.installed_version = installed_version
    if install_date is not None:
        existing.install_date = install_date
    if jackify_version is not None:
        existing.jackify_version = jackify_version
    if appid is not None:
        existing.appid = appid
    if configured:
        existing.last_configured = now

    # jackify_meta.json (written into the install directory itself) is the authoritative,
    # portable record for anything intrinsic to the modlist - it survives a Jackify reinstall
    # or a move to another system, unlike this central registry file. Sync from it last so it
    # always wins over whatever this call site happened to pass in, rather than this registry
    # and jackify_meta.json drifting as two independently-written copies of the same facts.
    from jackify.backend.utils.modlist_meta import read_modlist_meta

    meta = read_modlist_meta(existing.install_dir)
    if meta:
        # modlist_name is the one exception: it is a live display label expected to track
        # whatever Steam actually calls the shortcut (backfill_from_shortcuts() keeps it
        # synced there), not the modlist's original published title. jackify_meta.json is
        # never rewritten after the first install, so re-imposing it here on every call
        # silently undid every later rename - found 2026-08-26 (Tuxborn RC1/Tuxborn drift).
        # Only seed it from meta.json for a genuinely new entry, where nothing else is known.
        if is_new_entry and meta.get("modlist_name"):
            existing.modlist_name = meta["modlist_name"]
        if meta.get("game_type"):
            existing.game_type = meta["game_type"]
        if meta.get("modlist_version"):
            existing.installed_version = meta["modlist_version"]

    save_registry(entries)
    return existing


def mark_missing_installs(entries: Optional[List[InstallEntry]] = None) -> List[InstallEntry]:
    """
    Mark entries whose install_dir no longer exists as missing, without deleting them - a
    modlist on an unmounted SD card must not vanish from the list (population order #3).
    """
    from jackify.backend.handlers.validation_handler import ValidationHandler
    validator = ValidationHandler()

    entries = entries if entries is not None else load_registry()
    changed = False
    for entry in entries:
        # looks_like_modlist_dir(), not a bare is_dir() - the parent folder can survive
        # while its contents are gone (wiped SD card entry, manual cleanup), and that must
        # still count as missing.
        is_missing = not validator.looks_like_modlist_dir(Path(entry.install_dir))
        if is_missing != entry.missing:
            entry.missing = is_missing
            changed = True
    if changed:
        save_registry(entries)
    return entries


def remove_from_registry(install_id: str) -> bool:
    """
    Drop a registry entry only - never touches the install itself.

    Must stay unmistakably distinct from deleting the install (section 5); there is no
    delete-install action in v0.8 at all.
    """
    entries = load_registry()
    remaining = [e for e in entries if e.install_id != install_id]
    if len(remaining) == len(entries):
        return False
    save_registry(remaining)
    return True


def backfill_from_shortcuts() -> int:
    """
    Discover MO2 installs from existing Steam shortcuts not yet in the registry (population
    order #2). Included even when Jackify has no record of installing them (dashboard decision
    Q2) - such entries get provenance="backfill" and are expected to be treated read-only by
    the dashboard (no update/repair, since Jackify does not know how they were built).

    Also re-resolves the stored AppID of entries already known, since the same shortcut scan
    is the authority for it. Entries themselves are never removed here - install_dir is the
    health signal, handled by mark_missing_installs().

    Returns the number of new entries added.
    """
    from jackify.backend.handlers.shortcut_handler import ShortcutHandler
    from jackify.backend.services.platform_detection_service import PlatformDetectionService
    from jackify.backend.utils.modlist_meta import read_modlist_meta

    try:
        platform_service = PlatformDetectionService.get_instance()
        shortcut_handler = ShortcutHandler(steamdeck=platform_service.is_steamdeck, verbose=False)
        shortcuts = shortcut_handler.find_shortcuts_by_exe("ModOrganizer.exe")
    except Exception as e:
        logger.warning("Install registry backfill: shortcut scan failed: %s", e)
        return 0

    entries = load_registry()
    by_id = {e.install_id: e for e in entries}
    added = 0
    reconciled = 0

    for shortcut in shortcuts:
        start_dir = shortcut.get("StartDir", shortcut.get("startdir", "")).strip('"')
        if not start_dir:
            continue

        install_id = compute_install_id(start_dir)
        raw_appid = shortcut.get("appid")
        appid = str(int(raw_appid) & 0xFFFFFFFF) if raw_appid is not None else None

        known = by_id.get(install_id)
        if known is not None:
            # Reconciled from the shortcut scan alone - deliberately NOT gated on
            # os.path.isdir(start_dir). A temporarily unreachable drive (unplugged, unmounted)
            # is exactly when stale metadata matters most: the AppID/name must still catch up
            # once the drive returns, not wait for a directory check that blocks the very case
            # this exists for. Only adding a brand-new entry below needs the directory to
            # exist, to read jackify_meta.json.
            #
            # A non-Steam shortcut's AppID is derived from its exe path and app name, so
            # reconfiguring a modlist recreates the shortcut and mints a new one. Nothing
            # else refreshes it, and a stale AppID breaks every prefix lookup for that card.
            if appid and known.appid != appid:
                logger.info(
                    "Registry AppID for %s changed: %s -> %s",
                    known.modlist_name, known.appid, appid,
                )
                known.appid = appid
                reconciled += 1

            # The Dashboard label must match what Steam actually calls the shortcut - a
            # Configure New run against an already-tracked directory can enter a different
            # name than jackify_meta.json still holds, and nothing else notices the drift.
            # This is display-only: update/gallery matching reads modlist_name straight from
            # jackify_meta.json (update_detection.py), never from this registry.
            shortcut_name = shortcut.get("AppName", shortcut.get("appname", "")).strip()
            if shortcut_name and known.modlist_name != shortcut_name:
                logger.info(
                    "Registry name for install %s changed: %r -> %r",
                    known.install_id, known.modlist_name, shortcut_name,
                )
                known.modlist_name = shortcut_name
                reconciled += 1
            continue

        if not os.path.isdir(start_dir):
            continue

        meta = read_modlist_meta(start_dir) or {}
        name = (
            meta.get("modlist_name")
            or shortcut.get("AppName", shortcut.get("appname", "")).strip()
            or Path(start_dir).name
        )
        entries.append(InstallEntry(
            install_id=install_id,
            install_dir=os.path.realpath(start_dir),
            modlist_name=name,
            game_type=meta.get("game_type") or None,
            installed_version=meta.get("modlist_version"),
            install_date=meta.get("install_date"),
            jackify_version=meta.get("jackify_version"),
            appid=appid,
            provenance="jackify" if meta else "backfill",
        ))
        by_id[install_id] = entries[-1]
        added += 1

    if added or reconciled:
        save_registry(entries)
    return added
