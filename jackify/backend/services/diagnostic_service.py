"""
Diagnostic bundle service - collects logs, system info, and prefix records
into a tar.gz for support reporting.
"""

import json
import logging
import os
import platform
import shutil
import subprocess
import tarfile
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

def build_bundle(output_dir: Optional[Path] = None) -> Path:
    """
    Collect logs, system info, and per-prefix component records into a tar.gz.
    Returns the path to the created bundle file.
    """
    from jackify.shared.paths import get_jackify_logs_dir, get_jackify_data_dir
    from jackify import __version__

    if output_dir is None:
        output_dir = get_jackify_data_dir() / "DiagnosticBundles"
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bundle_name = f"jackify_diagnostic_{timestamp}.tar.gz"
    bundle_path = output_dir / bundle_name

    with tempfile.TemporaryDirectory() as staging_dir:
        staging = Path(staging_dir)

        # System info
        _write_text(staging / "system_info.txt", _collect_system_info(__version__))

        # Logs
        logs_dir = get_jackify_logs_dir()
        log_staging = staging / "logs"
        log_staging.mkdir()
        cutoff = datetime.now().timestamp() - timedelta(days=7).total_seconds()
        if logs_dir.is_dir():
            for log_file in sorted(logs_dir.glob("*.log*")):
                if log_file.is_file() and log_file.stat().st_mtime >= cutoff:
                    try:
                        shutil.copy2(log_file, log_staging / log_file.name)
                    except Exception as exc:
                        logger.debug("Could not copy log %s: %s", log_file.name, exc)

        # Config files (credentials scrubbed)
        _collect_config_files(staging)

        # Per-prefix component records
        _collect_component_records(staging)

        # Modlist shortcut info
        _collect_modlist_info(staging)

        with tarfile.open(bundle_path, "w:gz") as tar:
            tar.add(staging_dir, arcname="jackify_diagnostic")

    logger.info("Diagnostic bundle written: %s", bundle_path)
    return bundle_path


def _collect_system_info(version: str) -> str:
    lines = [
        f"Jackify version: {version}",
        f"Date: {datetime.now().isoformat()}",
        f"Kernel: {platform.release()}",
        f"Machine: {platform.machine()}",
        "",
    ]

    _append_engine_info(lines)

    # Distro
    try:
        import distro
        lines.append(f"Distro: {distro.name(pretty=True)}")
    except ImportError:
        try:
            lines.append(f"Distro: {platform.freedesktop_os_release().get('PRETTY_NAME', 'unknown')}")
        except Exception:
            lines.append("Distro: unknown")

    # glibc
    try:
        glibc = platform.libc_ver()
        lines.append(f"glibc: {glibc[0]} {glibc[1]}")
    except Exception:
        lines.append("glibc: unknown")

    # GPU
    try:
        gpu_out = subprocess.check_output(
            ["lspci", "-mm"],
            stderr=subprocess.DEVNULL,
            timeout=5,
            text=True,
        )
        gpu_lines = [l for l in gpu_out.splitlines() if "VGA" in l or "3D" in l or "Display" in l]
        for gl in gpu_lines[:2]:
            lines.append(f"GPU: {gl.strip()}")
    except Exception:
        lines.append("GPU: unavailable (lspci not found)")

    lines.append("")

    # Steam type
    _append_steam_info(lines)

    return "\n".join(lines)


def _append_steam_info(lines: list) -> None:
    flatpak_steam = Path.home() / ".var/app/com.valvesoftware.Steam"
    native_steam = Path.home() / ".local/share/Steam"

    if flatpak_steam.is_dir():
        lines.append("Steam: Flatpak")
    elif native_steam.is_dir():
        lines.append("Steam: Native")
    else:
        lines.append("Steam: not detected")

    # Proton versions - official builds in steamapps/common, community builds in compatibilitytools.d
    proton_scan = [
        (native_steam / "steamapps/common", "valve"),
        (flatpak_steam / "data/Steam/steamapps/common", "valve"),
        (native_steam / "compatibilitytools.d", "community"),
        (flatpak_steam / "data/Steam/compatibilitytools.d", "community"),
        (Path.home() / ".steam/root/compatibilitytools.d", "community"),
    ]
    proton_versions = []
    seen = set()
    for root, source in proton_scan:
        if not root.is_dir():
            continue
        for entry in sorted(root.iterdir()):
            if entry.is_dir() and entry.name not in seen and "proton" in entry.name.lower():
                seen.add(entry.name)
                proton_versions.append((entry.name, source))

    if proton_versions:
        lines.append("Proton versions:")
        for name, source in sorted(proton_versions):
            lines.append(f"  {name} ({source})")
    else:
        lines.append("Proton versions: none found")


def _append_engine_info(lines: list) -> None:
    try:
        from jackify.backend.services.tool_registry import get_active_engine_id, ENGINE_TOOL_IDS, _read_manifest
        active = get_active_engine_id()
        lines.append(f"Active engine: {active}")
        for tool_id in ENGINE_TOOL_IDS:
            try:
                manifest = _read_manifest(tool_id)
                installed_version = manifest.get("installed_version")
                if installed_version:
                    lines.append(f"  {tool_id}: {installed_version}")
                else:
                    lines.append(f"  {tool_id}: not installed")
            except Exception:
                lines.append(f"  {tool_id}: unknown")
    except Exception as e:
        lines.append(f"Engine info: unavailable ({e})")
    lines.append("")


_CREDENTIAL_KEYS = {"nexus_api_key", "api_key", "access_token", "refresh_token", "token"}
_EXCLUDED_CONFIG_FILES = {"nexus-oauth.json"}


def _collect_config_files(staging: Path) -> None:
    """Copy ~/.config/jackify files, excluding credential files and scrubbing credential fields."""
    config_dir = Path.home() / ".config" / "jackify"
    if not config_dir.is_dir():
        return

    cfg_staging = staging / "config"
    cfg_staging.mkdir()

    for cfg_file in sorted(config_dir.iterdir()):
        if not cfg_file.is_file():
            continue
        if cfg_file.name in _EXCLUDED_CONFIG_FILES:
            continue
        if cfg_file.suffix == ".json":
            try:
                data = json.loads(cfg_file.read_text(encoding="utf-8"))
                _scrub_credentials(data)
                (cfg_staging / cfg_file.name).write_text(
                    json.dumps(data, indent=2), encoding="utf-8"
                )
                continue
            except Exception as exc:
                logger.debug("Could not parse %s for scrubbing: %s", cfg_file.name, exc)
        try:
            shutil.copy2(cfg_file, cfg_staging / cfg_file.name)
        except Exception as exc:
            logger.debug("Could not copy config file %s: %s", cfg_file.name, exc)


def _scrub_credentials(obj: object) -> None:
    """Recursively replace credential field values with '[REDACTED]' in-place."""
    if isinstance(obj, dict):
        for key in list(obj.keys()):
            if key.startswith("nexus_premium_cache_"):
                del obj[key]
            elif any(cred in key.lower() for cred in _CREDENTIAL_KEYS):
                if obj[key] is not None:
                    obj[key] = "[REDACTED]"
            else:
                _scrub_credentials(obj[key])
    elif isinstance(obj, list):
        for item in obj:
            _scrub_credentials(item)


def _collect_component_records(staging: Path) -> None:
    """Find jackify_components.json files in known prefix locations and copy them."""
    steam_compat = Path.home() / ".steam/root/steamapps/compatdata"
    flatpak_compat = Path.home() / ".var/app/com.valvesoftware.Steam/data/Steam/steamapps/compatdata"

    cutoff = datetime.now().timestamp() - timedelta(days=30).total_seconds()
    found = []
    for base in (steam_compat, flatpak_compat):
        if not base.is_dir():
            continue
        try:
            for pfx_dir in base.iterdir():
                record = pfx_dir / "pfx" / "jackify_components.json"
                if record.is_file() and record.stat().st_mtime >= cutoff:
                    found.append((pfx_dir.name, record))
        except PermissionError:
            pass

    if not found:
        return

    comp_staging = staging / "component_records"
    comp_staging.mkdir()
    for appid, record_path in found:
        dest = comp_staging / f"jackify_components_{appid}.json"
        try:
            shutil.copy2(record_path, dest)
        except Exception as exc:
            logger.debug("Could not copy component record for %s: %s", appid, exc)


def _collect_modlist_info(staging: Path) -> None:
    """Collect installed modlist details from Steam shortcuts.vdf and config.vdf."""
    try:
        from jackify.backend.services.install_verifier_service import _load_verifier
        vmod = _load_verifier()
        modlists = vmod.discover_installed_modlists()
    except Exception as exc:
        logger.debug("Could not discover modlists for bundle: %s", exc)
        return

    if not modlists:
        return

    # Build a lookup of launch options keyed by unsigned appid from shortcuts.vdf
    launch_opts: dict = {}
    try:
        for vdf_path in vmod._find_shortcuts_vdf_paths():
            for sc in vmod._parse_shortcuts_vdf(vdf_path):
                raw = sc.get("appid", sc.get("AppID", sc.get("appId")))
                if raw is None:
                    continue
                try:
                    unsigned = str(vmod._signed_to_unsigned(int(raw)))
                except Exception:
                    continue
                lo = sc.get("LaunchOptions", sc.get("launchoptions", ""))
                if lo:
                    launch_opts[unsigned] = lo
    except Exception as exc:
        logger.debug("Could not read launch options from shortcuts.vdf: %s", exc)

    # Read config.vdf once for Proton mappings
    proton_map: dict = {}
    try:
        for root in vmod._find_steam_roots():
            cfg = root / "config" / "config.vdf"
            if cfg.is_file():
                content = cfg.read_text(encoding="utf-8", errors="replace")
                for m in modlists:
                    appid = m.get("appid", "")
                    if appid and appid not in proton_map:
                        tool = vmod._vdf_extract_compat_tool(content, appid)
                        if tool:
                            proton_map[appid] = tool
                break
    except Exception as exc:
        logger.debug("Could not read Proton versions from config.vdf: %s", exc)

    records = []
    for m in modlists:
        appid = m.get("appid", "")
        records.append({
            "name": m.get("name", "Unknown"),
            "appid": appid,
            "install_dir": str(m.get("modlist_dir", "")),
            "game_type": m.get("game_type", "unknown"),
            "proton_version": proton_map.get(appid),
            "launch_options": launch_opts.get(appid),
        })

    _write_text(staging / "modlists.json", json.dumps(records, indent=2))


def _write_text(path: Path, content: str) -> None:
    try:
        path.write_text(content, encoding="utf-8")
    except Exception as exc:
        logger.debug("Could not write %s: %s", path, exc)
