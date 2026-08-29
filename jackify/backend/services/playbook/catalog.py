"""
Catalog schema: dataclasses, parsing/validation, and declarative file selection.

`catalog.json` is the only place a playbook-referenced tool or asset names a URL, a Nexus mod
id, or a command line - playbooks reference catalog entries by id only. This module covers
schema and the `select` file-picker (a direct generalisation of the existing
`run_4gb_patcher()` heuristic in vnv_post_install_service.py). Acquisition itself (actually
downloading via Nexus/URL, extracting, running) is a separate, later piece that integrates with
NexusDownloadService and the manual-download dialog flow.
See docs/0.8_work/modlist_playbook_system.md section 5.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .url_policy import UrlPolicyError, validate_https_allowlisted_url

_VALID_SOURCES = {"nexus", "url", "tool"}


class CatalogValidationError(ValueError):
    """A catalog entry failed structural validation. Callers should log and skip it."""


def _validate_url(url: Any, context: str) -> str:
    try:
        return validate_https_allowlisted_url(url, context)
    except UrlPolicyError as e:
        raise CatalogValidationError(str(e))


@dataclass
class SelectSpec:
    extension: Optional[str] = None
    name_contains: List[str] = field(default_factory=list)
    recursive: bool = False
    fallback: Optional[str] = None  # "first_file" or None


@dataclass
class RunSpec:
    args: List[str] = field(default_factory=list)
    timeout_seconds: int = 60
    progress_pattern: Optional[str] = None
    progress_label: Optional[str] = None
    success_when: Optional[dict] = None


@dataclass
class ManualDownloadSpec:
    title: str
    instructions: str


@dataclass
class CatalogTool:
    id: str
    display_name: str
    source: str  # "nexus" | "url" | "tool"
    revision: int = 1
    game_domain: Optional[str] = None
    mod_id: Optional[int] = None
    file_filter: Optional[str] = None
    url: Optional[str] = None
    sha256: Optional[str] = None
    tool_registry_id: Optional[str] = None
    extract: bool = False
    select: Optional[SelectSpec] = None
    chmod_exec: bool = False
    run: Optional[RunSpec] = None
    run_via_tool: Optional[str] = None
    manual_download: Optional[ManualDownloadSpec] = None


@dataclass
class CatalogAsset:
    id: str
    display_name: str
    source: str  # "url"
    url: Optional[str] = None
    sha256: Optional[str] = None


@dataclass
class Catalog:
    tools: Dict[str, CatalogTool] = field(default_factory=dict)
    assets: Dict[str, CatalogAsset] = field(default_factory=dict)


def _parse_select(data: Optional[dict], context: str) -> Optional[SelectSpec]:
    if data is None:
        return None
    if not isinstance(data, dict):
        raise CatalogValidationError(f"{context}: select must be an object")
    fallback = data.get("fallback")
    if fallback is not None and fallback != "first_file":
        raise CatalogValidationError(f"{context}: unsupported select.fallback: {fallback!r}")
    return SelectSpec(
        extension=data.get("extension"),
        name_contains=list(data.get("name_contains", [])),
        recursive=bool(data.get("recursive", False)),
        fallback=fallback,
    )


def _parse_run(data: Optional[dict], context: str) -> Optional[RunSpec]:
    if data is None:
        return None
    if not isinstance(data, dict):
        raise CatalogValidationError(f"{context}: run must be an object")
    return RunSpec(
        args=list(data.get("args", [])),
        timeout_seconds=int(data.get("timeout_seconds", 60)),
        progress_pattern=data.get("progress_pattern"),
        progress_label=data.get("progress_label"),
        success_when=data.get("success_when"),
    )


def _parse_manual_download(data: Optional[dict], context: str) -> Optional[ManualDownloadSpec]:
    if data is None:
        return None
    if not isinstance(data, dict) or "title" not in data or "instructions" not in data:
        raise CatalogValidationError(f"{context}: manual_download must have title and instructions")
    return ManualDownloadSpec(title=data["title"], instructions=data["instructions"])


def _parse_tool(tool_id: str, data: dict) -> CatalogTool:
    context = f"catalog tool {tool_id!r}"
    if not isinstance(data, dict):
        raise CatalogValidationError(f"{context}: must be an object")

    source = data.get("source")
    if source not in _VALID_SOURCES:
        raise CatalogValidationError(f"{context}: invalid source {source!r}")

    if "display_name" not in data:
        raise CatalogValidationError(f"{context}: missing display_name")

    manual_download = _parse_manual_download(data.get("manual_download"), context)

    if source == "nexus":
        if not data.get("game_domain") or not data.get("mod_id"):
            raise CatalogValidationError(f"{context}: nexus source requires game_domain and mod_id")
        # Enforced by CI upstream too, but checked here as defense in depth: without this, a
        # non-Premium user hits a dead end with no way to supply the file manually.
        if manual_download is None:
            raise CatalogValidationError(f"{context}: nexus source must declare manual_download")
    elif source == "url":
        _validate_url(data.get("url"), context)
        if not data.get("sha256"):
            raise CatalogValidationError(f"{context}: url source requires sha256")
    elif source == "tool":
        if not data.get("tool_registry_id"):
            raise CatalogValidationError(f"{context}: tool source requires tool_registry_id")

    return CatalogTool(
        id=tool_id,
        display_name=data["display_name"],
        source=source,
        revision=int(data.get("revision", 1)),
        game_domain=data.get("game_domain"),
        mod_id=data.get("mod_id"),
        file_filter=data.get("file_filter"),
        url=data.get("url"),
        sha256=data.get("sha256"),
        tool_registry_id=data.get("tool_registry_id"),
        extract=bool(data.get("extract", False)),
        select=_parse_select(data.get("select"), context),
        chmod_exec=bool(data.get("chmod_exec", False)),
        run=_parse_run(data.get("run"), context),
        run_via_tool=data.get("run_via_tool"),
        manual_download=manual_download,
    )


def _parse_asset(asset_id: str, data: dict) -> CatalogAsset:
    context = f"catalog asset {asset_id!r}"
    if not isinstance(data, dict):
        raise CatalogValidationError(f"{context}: must be an object")
    if data.get("source") != "url":
        raise CatalogValidationError(f"{context}: assets must have source 'url'")
    if "display_name" not in data:
        raise CatalogValidationError(f"{context}: missing display_name")

    _validate_url(data.get("url"), context)
    if not data.get("sha256"):
        raise CatalogValidationError(f"{context}: requires sha256 (assets are always hash-pinned)")

    return CatalogAsset(
        id=asset_id,
        display_name=data["display_name"],
        source="url",
        url=data["url"],
        sha256=data["sha256"],
    )


def parse_catalog(data: dict) -> Catalog:
    """
    Parse and validate catalog.json.

    Raises CatalogValidationError on any problem; unlike playbooks (one bad file skipped, rest
    proceed), the whole catalog is one file with one merge review, so an invalid catalog fails
    sync entirely rather than silently dropping entries - callers should keep the previous
    working catalog rather than apply a partially-parsed one.
    """
    if not isinstance(data, dict):
        raise CatalogValidationError("catalog must be a JSON object")

    tools_data = data.get("tools", {})
    assets_data = data.get("assets", {})
    if not isinstance(tools_data, dict) or not isinstance(assets_data, dict):
        raise CatalogValidationError("catalog 'tools' and 'assets' must be objects")

    tools = {tool_id: _parse_tool(tool_id, entry) for tool_id, entry in tools_data.items()}
    assets = {asset_id: _parse_asset(asset_id, entry) for asset_id, entry in assets_data.items()}
    return Catalog(tools=tools, assets=assets)


def select_file(search_dir: Path, select: Optional[SelectSpec]) -> Optional[Path]:
    """
    Pick a file out of `search_dir` per a catalog entry's `select` spec.

    Direct generalisation of the existing run_4gb_patcher() heuristic: gather candidate files
    (recursively if requested), narrow by extension, then take the first file (in listing
    order) whose name contains any of the name_contains substrings - matching the existing
    "for f in executables: if any(needle in f.name...): break" behaviour exactly, not a
    per-needle-priority search. Falls back to the first remaining candidate only if
    fallback == "first_file".
    """
    if not search_dir.is_dir():
        return None

    recursive = bool(select and select.recursive)
    walker = search_dir.rglob("*") if recursive else search_dir.glob("*")
    candidates = sorted(p for p in walker if p.is_file())

    if select and select.extension:
        ext = select.extension.lower()
        candidates = [p for p in candidates if p.suffix.lower() == ext]

    if select and select.name_contains:
        needles = [n.lower() for n in select.name_contains]
        match = next((p for p in candidates if any(n in p.name.lower() for n in needles)), None)
        if match is not None:
            return match
    elif len(candidates) == 1:
        return candidates[0]

    if select and select.fallback == "first_file" and candidates:
        return candidates[0]

    return None


def asset_cache_dir(catalog_id: str) -> Path:
    """Shared download cache location for a catalog entry, keyed by id (section 5, item 1)."""
    from jackify.shared.paths import get_jackify_data_dir
    return get_jackify_data_dir() / "playbooks" / "assets" / catalog_id
