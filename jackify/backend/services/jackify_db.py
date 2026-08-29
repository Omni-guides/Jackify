"""
JackifyDB: local-only, append-only history of install/configure/update events, for a future
compatibility database. No network transmission in v0.8 - not disabled, not behind a flag,
absent entirely. See docs/0.8_work/jackifydb_data_foundation.md.

Anonymity is structural, not a filter: `record_event()`'s parameters are the complete allowlist
of what can ever be recorded. There is no path, error-message, or identifier parameter to leak -
a caller cannot pass one in because none exists, rather than relying on scrubbing after the
fact.
"""
import dataclasses
import datetime
import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from jackify.shared.paths import get_jackify_data_dir

logger = logging.getLogger(__name__)

_RECORD_VERSION = 1
_MAX_RECORDS = 1000
_MAX_FILE_BYTES = 5 * 1024 * 1024

_VALID_EVENTS = {"install_completed", "configure_completed", "update_completed"}
_VALID_OUTCOMES = {"success", "failure"}
_FAILURE_REASONS = {
    "network", "disk_space", "engine_crash", "user_cancelled", "hash_mismatch",
    "download_failed", "unknown",
}


@dataclass
class DbRecord:
    """The complete, explicit allowlist of fields a record can ever contain (section 4). Never
    populated from **kwargs or an existing object's __dict__ - only from record_event()'s own
    typed, named parameters."""
    record_version: int
    event: str
    timestamp: str
    outcome: str
    modlist_name: Optional[str] = None
    modlist_version: Optional[str] = None
    machine_url: Optional[str] = None
    game_type: Optional[str] = None
    install_mode: Optional[str] = None
    engine: Optional[str] = None
    engine_version: Optional[str] = None
    jackify_version: Optional[str] = None
    proton_version: Optional[str] = None
    components: List[str] = field(default_factory=list)
    steamdeck: Optional[bool] = None
    distro_id: Optional[str] = None
    kernel_major: Optional[str] = None
    glibc: Optional[str] = None
    duration_seconds: Optional[int] = None
    modules_applied: List[str] = field(default_factory=list)
    failure_phase: Optional[str] = None
    failure_reason: Optional[str] = None


def _db_path() -> Path:
    return get_jackify_data_dir() / "db" / "records.jsonl"


def _now_utc_seconds() -> str:
    """Second precision, UTC, no offset - finer timestamps or a local offset are a coarse
    location signal (section 4)."""
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _recording_enabled() -> bool:
    try:
        from jackify.backend.handlers.config_handler import ConfigHandler
        return ConfigHandler().get("jackify_db_enabled", True)
    except Exception:
        return True


def record_event(
    event: str,
    outcome: str,
    modlist_name: Optional[str] = None,
    modlist_version: Optional[str] = None,
    machine_url: Optional[str] = None,
    game_type: Optional[str] = None,
    install_mode: Optional[str] = None,
    engine: Optional[str] = None,
    engine_version: Optional[str] = None,
    jackify_version: Optional[str] = None,
    proton_version: Optional[str] = None,
    components: Optional[List[str]] = None,
    steamdeck: Optional[bool] = None,
    distro_id: Optional[str] = None,
    kernel_major: Optional[str] = None,
    glibc: Optional[str] = None,
    duration_seconds: Optional[int] = None,
    modules_applied: Optional[List[str]] = None,
    failure_phase: Optional[str] = None,
    failure_reason: Optional[str] = None,
) -> None:
    """
    Append one record.

    Failure-isolated by design: any error here is caught, logged at debug, and never raised - a
    data-collection feature must never be able to turn a clean install/configure error into a
    confusing one (section 5). No-ops entirely when recording is disabled (settings toggle,
    default on) - not a smaller record, no record at all.
    """
    try:
        if not _recording_enabled():
            return
        if event not in _VALID_EVENTS:
            logger.debug("jackify_db: unknown event %r, skipping", event)
            return
        if outcome not in _VALID_OUTCOMES:
            logger.debug("jackify_db: unknown outcome %r, skipping", outcome)
            return
        if failure_reason is not None and failure_reason not in _FAILURE_REASONS:
            failure_reason = "unknown"

        record = DbRecord(
            record_version=_RECORD_VERSION, event=event, timestamp=_now_utc_seconds(),
            outcome=outcome, modlist_name=modlist_name, modlist_version=modlist_version,
            machine_url=machine_url, game_type=game_type, install_mode=install_mode,
            engine=engine, engine_version=engine_version, jackify_version=jackify_version,
            proton_version=proton_version, components=list(components or []),
            steamdeck=steamdeck, distro_id=distro_id, kernel_major=kernel_major, glibc=glibc,
            duration_seconds=duration_seconds, modules_applied=list(modules_applied or []),
            failure_phase=failure_phase, failure_reason=failure_reason,
        )
        _append_record(record)
    except Exception as e:
        logger.debug("jackify_db: record_event failed (non-fatal): %s", e)


def _append_record(record: DbRecord) -> None:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(dataclasses.asdict(record))
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    _trim_if_needed(path)


def _trim_if_needed(path: Path) -> None:
    """Cap at 1000 records or 5MB, whichever first; oldest trimmed (section 6)."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return

    if path.stat().st_size <= _MAX_FILE_BYTES and len(lines) <= _MAX_RECORDS:
        return

    trimmed = lines[-_MAX_RECORDS:]
    while trimmed and sum(len(l) + 1 for l in trimmed) > _MAX_FILE_BYTES:
        trimmed.pop(0)

    _atomic_write_lines(path, trimmed)


def _atomic_write_lines(path: Path, lines: List[str]) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".records_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            for line in lines:
                fh.write(line + "\n")
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load_records() -> List[dict]:
    """All currently-stored records, oldest first - for the settings 'View recorded data' panel."""
    path = _db_path()
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def delete_all_records() -> bool:
    """Settings 'Delete recorded data' action."""
    path = _db_path()
    try:
        if path.exists():
            path.unlink()
        return True
    except OSError as e:
        logger.warning("jackify_db: failed to delete records: %s", e)
        return False


def gather_environment_fields() -> dict:
    """
    Best-effort steamdeck/distro_id/kernel_major/glibc fields for a record - the coarse,
    population-level signals section 4 explicitly defends as non-identifying, gathered fresh
    at each call site rather than cached, since it's cheap and this isn't a hot path.
    """
    fields = {"steamdeck": None, "distro_id": None, "kernel_major": None, "glibc": None}
    try:
        from jackify.backend.services.platform_detection_service import PlatformDetectionService
        fields["steamdeck"] = PlatformDetectionService.get_instance().is_steamdeck
    except Exception as e:
        logger.debug("jackify_db: steamdeck detection failed: %s", e)

    try:
        os_release = Path("/etc/os-release")
        if os_release.is_file():
            for line in os_release.read_text(encoding="utf-8").splitlines():
                if line.startswith("ID="):
                    fields["distro_id"] = line.split("=", 1)[1].strip().strip('"')
                    break
    except OSError as e:
        logger.debug("jackify_db: distro detection failed: %s", e)

    try:
        import platform as _platform
        release = _platform.release()
        fields["kernel_major"] = ".".join(release.split(".")[:2]) if release else None
    except Exception as e:
        logger.debug("jackify_db: kernel detection failed: %s", e)

    try:
        fields["glibc"] = os.confstr("CS_GNU_LIBC_VERSION").split()[-1]
    except (OSError, ValueError, AttributeError) as e:
        logger.debug("jackify_db: glibc detection failed: %s", e)

    return fields
