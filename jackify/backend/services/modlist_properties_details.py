"""
Field list for the Properties popout's Details section.

Everything here comes from the install registry or from resolving paths on disk. JackifyDB is not
read: its `components`, `engine` and `machine_url` fields are never passed by any `record_event()`
call site, and no record exists for installs predating v0.8.
"""
import datetime
import logging
from pathlib import Path
from typing import Callable, List, NamedTuple, Optional

from .install_registry import InstallEntry

logger = logging.getLogger(__name__)

_ABSENT = "Not recorded"
_VERSION_HINT = (
    "The version Jackify installed. If the modlist has been updated by other means since, "
    "this may not match what is currently on disk."
)
_PROVENANCE_LABELS = {
    "jackify": "Installed by Jackify",
    "backfill": "Found in your Steam library",
}


def _format_timestamp(raw: Optional[str]) -> Optional[str]:
    """Registry ISO timestamp rendered for display. Unparseable values pass through."""
    if not raw:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return raw
    return parsed.strftime("%d %b %Y, %H:%M")


def _describe_path(raw: Optional[str]) -> Optional[str]:
    """Marks a path that no longer resolves - a bare path implies it is still there."""
    if not raw:
        return None
    try:
        if not Path(raw).is_dir():
            return f"{raw}  (not found)"
    except OSError:
        return raw
    return raw


def _describe_prefix_display(raw: Optional[str]) -> Optional[str]:
    """Prefix path for display, truncated to the AppID directory (drops the trailing `/pfx`) -
    the AppID is what users actually recognise; the full WINEPREFIX stays in copy_value for
    anyone who needs the exact path for winetricks/protontricks."""
    if not raw:
        return None
    display_path = raw[:-4] if raw.endswith("/pfx") else raw
    return _describe_path(display_path)


class DetailField(NamedTuple):
    """`display` carries any annotation, `copy_value` is the bare value. They differ for a
    missing path, where copying "(not found)" would be useless.

    `hint`, when set, is shown on both the label and the value's tooltip (appended after the
    copy-value there) - a hint that only reached the small label text is easy to miss."""
    label: str
    display: str
    copy_value: str
    hint: str = ""


def build_detail_fields(
    entry: InstallEntry,
    prefix_resolver: Optional[Callable[[str], Optional[str]]] = None,
) -> List[DetailField]:
    """
    Ordered rows for the Details section.

    `prefix_resolver` maps appid -> prefix path or None, injectable so tests need no Steam
    environment. Every field is always present, with a placeholder when unset, so the layout
    does not reshuffle per modlist.
    """
    if prefix_resolver is None:
        from .dashboard_status import _default_prefix_resolver
        prefix_resolver = _default_prefix_resolver

    prefix_path = None
    if entry.appid:
        try:
            prefix_path = prefix_resolver(entry.appid)
        except Exception as e:
            logger.debug("Prefix lookup failed for appid %s: %s", entry.appid, e)

    fields = [
        ("Install Directory", _describe_path(entry.install_dir), entry.install_dir, ""),
        ("Prefix/Compatdata Path", _describe_prefix_display(prefix_path), prefix_path, ""),
        ("Version Jackify Installed", entry.installed_version, entry.installed_version,
         _VERSION_HINT),
        ("Installed", _format_timestamp(entry.install_date), entry.install_date, ""),
        ("Last Configured", _format_timestamp(entry.last_configured), entry.last_configured, ""),
        ("Steam AppID", entry.appid, entry.appid, ""),
        ("Source", _PROVENANCE_LABELS.get(entry.provenance, entry.provenance),
         entry.provenance, ""),
    ]
    return [
        DetailField(label, display or _ABSENT, copy_value or _ABSENT, hint)
        for label, display, copy_value, hint in fields
    ]
