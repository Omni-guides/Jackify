"""
Third-party tool registry: install, update, downgrade, and uninstall.

Tool state is stored at $jackify_data_dir/tools/<tool_id>/manifest.json.
TTW_Linux_Installer installs into $jackify_data_dir/tools/ttw_installer/ and
delegates the download/extract to TTWInstallerHandler.
"""

import json
import logging
import os
import re
import tarfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

from jackify.shared.paths import get_jackify_data_dir

logger = logging.getLogger(__name__)

TOOLS_BASE_DIR = get_jackify_data_dir() / "tools"
GITHUB_API = "https://api.github.com/repos/{repo}/releases/{ref}"

@dataclass
class ToolDefinition:
    tool_id: str
    display_name: str
    description: str
    asset_patterns: List[str]   # ordered list of regex patterns to match release asset filename
    tier: int                   # 1 = Jackify invokes it, 2 = user runs it themselves
    github_repo: Optional[str] = None   # e.g. "SulfurNitride/CLF3"; None for Nexus-only tools
    executable_names: List[str] = field(default_factory=list)
    pinned_version: Optional[str] = None   # None = always use latest
    can_uninstall: bool = True             # False for tools Jackify hard-depends on
    can_downgrade: bool = True             # False for pinned tools where version must not change
    is_engine: bool = False                # Engine cards show Set Active instead of Launch
    can_launch: bool = False               # Tool has a launchable binary the user runs directly
    nexus_mod_id: Optional[int] = None    # Nexus mod ID; premium users download from Nexus first
    nexus_game_domain: str = "site"       # Nexus game domain for site-wide tools
    nexus_file_filter: Optional[str] = None  # Substring filter to pick the right Nexus file
    hidden: bool = False                  # Set true in manifest to suppress display and installs
    include_prereleases: bool = False     # If True, newest release by date (inc. pre-releases) is used

    @property
    def upstream_url(self) -> Optional[str]:
        if self.github_repo:
            return f"https://github.com/{self.github_repo}"
        if self.nexus_mod_id:
            return f"https://www.nexusmods.com/{self.nexus_game_domain}/mods/{self.nexus_mod_id}"
        return None


@dataclass
class ToolStatus:
    definition: ToolDefinition
    installed: bool
    installed_version: Optional[str]
    previous_version: Optional[str]
    binary_path: Optional[Path]
    latest_version: Optional[str] = None
    update_available: bool = False

    @property
    def can_downgrade(self) -> bool:
        return (
            self.installed
            and self.definition.can_downgrade
            and self.definition.pinned_version is None
        )


TOOL_DEFINITIONS: List[ToolDefinition] = [
    ToolDefinition(
        tool_id="jackify-engine",
        display_name="jackify-engine",
        description="Native Wabbajack-matched file handler. The proven, stable engine for modlist installs.",
        github_repo="Omni-guides/dev-jackify-engine",
        asset_patterns=[r"jackify-engine.*linux.*x64.*\.tar\.gz", r"jackify-engine.*\.tar\.gz", r"jackify-engine.*\.zip"],
        executable_names=["jackify-engine"],
        tier=1,
        can_uninstall=False,
        is_engine=True,
    ),
    ToolDefinition(
        tool_id="clf3",
        display_name="CLF3",
        description="Rust-based Wabbajack file handler. Faster installs, slightly slower modlist updates than jackify-engine.",
        github_repo="SulfurNitride/CLF3",
        asset_patterns=[r"clf3.*linux.*x86_64.*\.tar\.gz", r"clf3.*\.tar\.gz", r"clf3.*\.zip"],
        executable_names=["clf3"],
        tier=1,
        can_uninstall=True,
        is_engine=True,
        include_prereleases=True,
    ),
    ToolDefinition(
        tool_id="ttw_installer",
        display_name="TTW Linux Installer",
        description="Automates Tale of Two Wastelands installation on Linux. Required for the TTW workflow.",
        github_repo="SulfurNitride/TTW_Linux_Installer",
        asset_patterns=[r"mpi-installer-linux.*\.(zip|tar\.gz)"],
        executable_names=["mpi_installer"],
        tier=1,
        can_uninstall=True,
        can_launch=True,
        pinned_version="0.2.0",  # must match TTW_INSTALLER_PINNED_VERSION in ttw_installer_handler.py
        nexus_mod_id=1657,
        nexus_file_filter="mpi",
    ),
    ToolDefinition(
        tool_id="radium",
        display_name="Radium Textures",
        description="Rust alternative to VRAMr for Skyrim and Fallout 4 texture optimisation. Run directly against mod files.",
        github_repo=None,
        asset_patterns=[r"radium.*linux.*x86_64", r"radium.*\.tar\.gz", r"radium.*\.zip"],
        executable_names=["radium-textures", "radium"],
        tier=2,
        can_launch=True,
        nexus_mod_id=1660,
    ),
]

_TOOL_MAP: Dict[str, ToolDefinition] = {t.tool_id: t for t in TOOL_DEFINITIONS}

ENGINE_TOOL_IDS: List[str] = [t.tool_id for t in TOOL_DEFINITIONS if t.is_engine]
_DEFAULT_ENGINE = "jackify-engine"
_ACTIVE_ENGINE_CONFIG_KEY = "active_engine"


def get_active_engine_id() -> str:
    try:
        from jackify.backend.handlers.config_handler import ConfigHandler
        val = ConfigHandler().get(_ACTIVE_ENGINE_CONFIG_KEY, _DEFAULT_ENGINE)
        return val if val in ENGINE_TOOL_IDS else _DEFAULT_ENGINE
    except Exception:
        return _DEFAULT_ENGINE

def set_active_engine_id(tool_id: str) -> None:
    if tool_id not in ENGINE_TOOL_IDS:
        raise ValueError(f"Not an engine: {tool_id}")
    try:
        from jackify.backend.handlers.config_handler import ConfigHandler
        cfg = ConfigHandler()
        cfg.set(_ACTIVE_ENGINE_CONFIG_KEY, tool_id)
        cfg.save_config()
    except Exception as e:
        logger.warning("Could not persist active engine selection: %s", e)


# -- remote manifest ---------------------------------------------------------
TOOL_MANIFEST_URL = "https://raw.githubusercontent.com/Omni-guides/Jackify/main/manifests/tools_manifest.json"
_BUNDLED_MANIFEST_PATH = Path(__file__).parent / "tools_manifest.json"


def _disk_cache_path() -> Path:
    from jackify.shared.paths import get_jackify_data_dir
    return get_jackify_data_dir() / "manifests" / "tools_manifest.json"


def _save_disk_cache(entries: list) -> None:
    import tempfile
    path = _disk_cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tools_manifest_", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(entries, fh, indent=2)
        os.replace(tmp, path)
    except Exception as e:
        logger.debug("Tool manifest disk save failed: %s", e)


def _load_disk_cache() -> Optional[List[ToolDefinition]]:
    path = _disk_cache_path()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            entries = json.load(fh)
        if isinstance(entries, list):
            return _parse_manifest_entries(entries)
    except Exception:
        pass
    return None


def _parse_manifest_entries(entries: list) -> Optional[List[ToolDefinition]]:
    definitions = []
    for entry in entries:
        try:
            definitions.append(ToolDefinition(
                tool_id=entry["tool_id"],
                display_name=entry["display_name"],
                description=entry["description"],
                github_repo=entry.get("github_repo"),
                asset_patterns=entry["asset_patterns"],
                tier=entry.get("tier", 2),
                executable_names=entry.get("executable_names", []),
                pinned_version=entry.get("pinned_version"),
                can_uninstall=entry.get("can_uninstall", True),
                can_downgrade=entry.get("can_downgrade", True),
                is_engine=entry.get("is_engine", False),
                can_launch=entry.get("can_launch", False),
                nexus_mod_id=entry.get("nexus_mod_id"),
                nexus_game_domain=entry.get("nexus_game_domain", "site"),
                nexus_file_filter=entry.get("nexus_file_filter"),
                hidden=entry.get("hidden", False),
            ))
        except (KeyError, TypeError) as e:
            logger.warning("Skipping malformed manifest entry: %s", e)
    return definitions if definitions else None


def _load_bundled_manifest() -> Optional[List[ToolDefinition]]:
    try:
        with open(_BUNDLED_MANIFEST_PATH, "r", encoding="utf-8") as fh:
            entries = json.load(fh)
        if not isinstance(entries, list):
            return None
        return _parse_manifest_entries(entries)
    except Exception as e:
        logger.debug("Bundled manifest load failed: %s", e)
        return None


_manifest_cache: Optional[List[ToolDefinition]] = _load_bundled_manifest()


def fetch_remote_manifest() -> Optional[List[ToolDefinition]]:
    """Fetch the remote tool manifest. Returns parsed definitions or None on failure."""
    try:
        resp = requests.get(TOOL_MANIFEST_URL, timeout=8, verify=True)
        resp.raise_for_status()
        entries = resp.json()
        if not isinstance(entries, list):
            return None
        _save_disk_cache(entries)
        return _parse_manifest_entries(entries)
    except Exception as e:
        logger.debug("Tool manifest fetch failed: %s", e)
        return None


def get_effective_definitions() -> List[ToolDefinition]:
    """Remote manifest definitions if fetched this session, else disk cache, else bundled."""
    if _manifest_cache is not None:
        return [d for d in _manifest_cache if not d.hidden]
    disk = _load_disk_cache()
    if disk is not None:
        return [d for d in disk if not d.hidden]
    return [d for d in TOOL_DEFINITIONS if not d.hidden]


def apply_remote_manifest(definitions: List[ToolDefinition]) -> None:
    """Store fetched manifest as session cache and rebuild the tool map."""
    global _manifest_cache, _TOOL_MAP
    _manifest_cache = definitions
    _TOOL_MAP = {t.tool_id: t for t in definitions}


def _manifest_path(tool_id: str) -> Path:
    return TOOLS_BASE_DIR / tool_id / "manifest.json"



def _read_manifest(tool_id: str) -> dict:
    mp = _manifest_path(tool_id)
    if mp.exists():
        try:
            return json.loads(mp.read_text())
        except Exception:
            pass
    return {}


def _write_manifest(tool_id: str, data: dict) -> None:
    mp = _manifest_path(tool_id)
    mp.parent.mkdir(parents=True, exist_ok=True)
    mp.write_text(json.dumps(data, indent=2))


def _ttw_status_from_config() -> Tuple[bool, Optional[str], Optional[Path]]:
    try:
        search_dirs = [
            TOOLS_BASE_DIR / "ttw_installer",
            get_jackify_data_dir() / "TTW_Linux_Installer",  # legacy location
        ]
        for tool_dir in search_dirs:
            exe = tool_dir / "mpi_installer"
            if exe.is_file():
                manifest = _read_manifest("ttw_installer")
                version = manifest.get("installed_version")
                return True, version, exe
        return False, None, None
    except Exception as e:
        logger.debug("TTW status check failed: %s", e)
        return False, None, None


def fetch_latest_release_info(github_repo: str, pinned_version: Optional[str] = None) -> Optional[dict]:
    """Fetch release metadata from GitHub API. Returns parsed JSON or None on failure."""
    if pinned_version:
        tags = [pinned_version, f"v{pinned_version}"] if not pinned_version.startswith("v") else [pinned_version]
        for tag in tags:
            url = GITHUB_API.format(repo=github_repo, ref=f"tags/{tag}")
            try:
                resp = requests.get(url, timeout=10, verify=True)
                if resp.status_code == 200:
                    return resp.json()
            except Exception as e:
                logger.debug("GitHub fetch error for %s@%s: %s", github_repo, tag, e)
        return None
    url = GITHUB_API.format(repo=github_repo, ref="latest")
    try:
        resp = requests.get(url, timeout=10, verify=True)
        resp.raise_for_status()
        data = resp.json()
        tag = data.get("tag_name") or data.get("name", "unknown")
        logger.info("Latest release for %s: %s", github_repo, tag)
        return data
    except Exception as e:
        logger.debug("GitHub fetch error for %s: %s", github_repo, e)
        return None


def fetch_release_list(github_repo: str, max_count: int = 10) -> List[dict]:
    """Return a list of release dicts (tag_name, name, published_at) from GitHub, newest first."""
    url = f"https://api.github.com/repos/{github_repo}/releases?per_page={max_count}"
    try:
        resp = requests.get(url, timeout=10, verify=True)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.warning("Release list fetch failed for %s: %s", github_repo, e)
        return []


def _find_asset(release_data: dict, asset_patterns: List[str]) -> Optional[dict]:
    assets = release_data.get("assets", [])
    for pattern in asset_patterns:
        for asset in assets:
            if re.search(pattern, asset.get("name", ""), re.IGNORECASE):
                return asset
    return None


def _find_sums_asset(release_data: dict, asset_name: str) -> Optional[dict]:
    """Find a .SHA256SUMS release asset that covers the given filename."""
    assets = release_data.get("assets", [])
    stem = asset_name.rsplit(".", 2)[0] if asset_name.endswith(".tar.gz") else Path(asset_name).stem
    for asset in assets:
        name = asset.get("name", "")
        if name.endswith(".SHA256SUMS") and stem in name:
            return asset
    for asset in assets:
        if asset.get("name", "").endswith(".SHA256SUMS"):
            return asset
    return None


def _verify_sha256_sums(sums_path: Path, target_path: Path) -> Tuple[bool, str]:
    """Parse a SHA256SUMS file and verify target_path. Format: 'hash  filename'."""
    import hashlib
    try:
        expected_hash = None
        for line in sums_path.read_text().strip().splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[1] == target_path.name:
                expected_hash = parts[0].lower()
                break
        if not expected_hash:
            return False, f"No entry for {target_path.name} in SHA256SUMS file"
        sha256 = hashlib.sha256()
        with open(target_path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                sha256.update(chunk)
        actual = sha256.hexdigest().lower()
        if actual != expected_hash:
            return False, f"SHA256 mismatch for {target_path.name}"
        return True, ""
    except Exception as e:
        return False, f"SHA256 verification error: {e}"


def _find_7z_binary() -> Optional[str]:
    """Return path to 7z binary: bundled first, then system."""
    import shutil
    candidates = [
        Path(__file__).parent.parent.parent / "tools" / "7z",
    ]
    appdir = os.environ.get("APPDIR")
    if appdir:
        candidates.insert(0, Path(appdir) / "opt" / "jackify" / "tools" / "7z")
    for c in candidates:
        if c.is_file() and os.access(c, os.X_OK):
            return str(c)
    return shutil.which("7z") or shutil.which("7zz")


def _extract_archive(file_path: Path, target_dir: Path, delete_archive: bool = True) -> Tuple[bool, str]:
    """Extract an archive or chmod an AppImage in place.

    Deletes the archive after successful extraction unless delete_archive=False.
    Never deletes the archive on failure.
    """
    import subprocess
    name_lower = file_path.name.lower()
    extracted = False
    try:
        if name_lower.endswith(".tar.gz") or name_lower.endswith(".tgz"):
            with tarfile.open(file_path, "r:gz") as tf:
                tf.extractall(path=target_dir)
            extracted = True
        elif name_lower.endswith(".zip"):
            with zipfile.ZipFile(file_path, "r") as zf:
                zf.extractall(path=target_dir)
            extracted = True
        elif name_lower.endswith(".7z"):
            sevenzip = _find_7z_binary()
            if not sevenzip:
                return False, "7z binary not found - cannot extract .7z archive"
            result = subprocess.run(
                [sevenzip, "x", str(file_path), f"-o{target_dir}", "-y"],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                return False, f"7z extraction failed: {result.stderr.strip() or result.stdout.strip()}"
            extracted = True
        elif name_lower.endswith(".appimage"):
            file_path.chmod(0o755)
        else:
            return False, f"Unsupported format: {file_path.name}"
    finally:
        if extracted and delete_archive:
            try:
                file_path.unlink(missing_ok=True)
            except Exception:
                pass
    if extracted:
        _chmod_elf_binaries(target_dir)
    return True, ""


def _extract_nested_archives(directory: Path) -> None:
    """Extract any zip/tar.gz/7z files sitting directly inside directory, then delete them."""
    for child in list(directory.iterdir()):
        if not child.is_file():
            continue
        name_lower = child.name.lower()
        if any(name_lower.endswith(ext) for ext in (".zip", ".tar.gz", ".tgz", ".7z")):
            ok, err = _extract_archive(child, directory, delete_archive=True)
            if not ok:
                logger.warning("Nested archive extraction failed for %s: %s", child.name, err)


def _chmod_elf_binaries(directory: Path) -> None:
    """Set executable bit on any ELF binaries found in directory tree."""
    ELF_MAGIC = b'\x7fELF'
    for f in directory.rglob("*"):
        if not f.is_file():
            continue
        try:
            with open(f, 'rb') as fh:
                magic = fh.read(4)
            if magic == ELF_MAGIC:
                f.chmod(f.stat().st_mode | 0o111)
        except Exception:
            pass


def _download_and_extract(
    tool_id: str,
    asset: dict,
    target_dir: Path,
    sums_asset: Optional[dict] = None,
) -> Tuple[bool, str]:
    """Download a GitHub release asset, optionally verify SHA256, then extract."""
    from jackify.backend.handlers.filesystem_handler import FileSystemHandler
    fs = FileSystemHandler()
    asset_name = asset.get("name", "")
    download_url = asset.get("browser_download_url", "")
    if not download_url:
        return False, "Asset has no download URL"
    temp_path = target_dir / asset_name
    logger.info("Downloading %s", asset_name)
    if not fs.download_file(download_url, temp_path, overwrite=True, quiet=True):
        return False, f"Download failed: {asset_name}"
    if sums_asset:
        sums_url = sums_asset.get("browser_download_url", "")
        sums_path = target_dir / sums_asset.get("name", "SHA256SUMS")
        if sums_url and fs.download_file(sums_url, sums_path, overwrite=True, quiet=True):
            ok, err = _verify_sha256_sums(sums_path, temp_path)
            try:
                sums_path.unlink(missing_ok=True)
            except Exception:
                pass
            if not ok:
                try:
                    temp_path.unlink(missing_ok=True)
                except Exception:
                    pass
                return False, err
            logger.info("SHA256 verified for %s", asset_name)
        else:
            logger.warning("SHA256SUMS download failed for %s, skipping verification", asset_name)
    return _extract_archive(temp_path, target_dir)


_NEXUS_NOT_ELIGIBLE = "NEXUS_NOT_ELIGIBLE"


def _try_nexus_download(defn: ToolDefinition, target_dir: Path) -> Tuple[bool, Optional[Path], str, Optional[str]]:
    """Attempt Nexus CDN download for premium users.

    Returns (success, file_path, message, version).
    message is _NEXUS_NOT_ELIGIBLE when the user is not authenticated or not premium,
    indicating a manual download dialog should be offered. Any other failure message
    means the user is premium but the download itself failed.
    version is the Nexus file version string on success, None otherwise.
    """
    if not defn.nexus_mod_id:
        return False, None, _NEXUS_NOT_ELIGIBLE, None
    try:
        from jackify.backend.services.nexus_auth_service import NexusAuthService
        from jackify.backend.services.nexus_premium_service import NexusPremiumService
        from jackify.backend.services.nexus_download_service import NexusDownloadService
        auth = NexusAuthService()
        token = auth.get_auth_token()
        if not token:
            return False, None, _NEXUS_NOT_ELIGIBLE, None
        is_oauth = auth.get_auth_method() == "oauth"
        is_premium, _ = NexusPremiumService().check_premium_status(token, is_oauth=is_oauth)
        if not is_premium:
            return False, None, _NEXUS_NOT_ELIGIBLE, None
        svc = NexusDownloadService(token)
        nexus_version = svc.get_latest_file_version(
            defn.nexus_game_domain, defn.nexus_mod_id,
            file_name_filter=defn.nexus_file_filter,
        )
        ok, path, msg = svc.download_latest_file(
            defn.nexus_game_domain, defn.nexus_mod_id, target_dir,
            file_name_filter=defn.nexus_file_filter,
        )
        return ok, path, msg, nexus_version if ok else None
    except Exception as e:
        logger.warning("Nexus download failed for %s: %s", defn.tool_id, e)
        return False, None, str(e), None


def _find_executable(tool_def: ToolDefinition, search_dir: Path) -> Optional[Path]:
    for exe_name in tool_def.executable_names:
        direct = search_dir / exe_name
        if direct.is_file():
            return direct
        for found in search_dir.rglob(exe_name):
            if found.is_file():
                return found
        for found in search_dir.rglob(f"{exe_name}*.AppImage"):
            if found.is_file():
                return found
    return None


class ToolRegistry:
    """Read/write interface to the managed tool store."""

    def get_status(self, tool_id: str) -> Optional[ToolStatus]:
        defn = _TOOL_MAP.get(tool_id)
        if defn is None:
            return None
        return self._build_status(defn)

    def get_all_statuses(self) -> List[ToolStatus]:
        return [self._build_status(d) for d in get_effective_definitions()]

    def _check_latest_nexus_version(self, defn: ToolDefinition) -> Optional[str]:
        try:
            from jackify.backend.services.nexus_auth_service import NexusAuthService
            from jackify.backend.services.nexus_download_service import NexusDownloadService
            auth = NexusAuthService()
            token = auth.get_auth_token()
            if not token:
                return None
            return NexusDownloadService(token).get_latest_file_version(
                defn.nexus_game_domain, defn.nexus_mod_id,
                file_name_filter=defn.nexus_file_filter,
            )
        except Exception as e:
            logger.debug("Nexus version check failed for %s: %s", defn.tool_id, e)
            return None

    def check_latest_version(self, tool_id: str) -> Optional[str]:
        defn = _TOOL_MAP.get(tool_id)
        if defn is None:
            return None
        if defn.pinned_version:
            return defn.pinned_version
        if not defn.github_repo:
            if defn.nexus_mod_id:
                return self._check_latest_nexus_version(defn)
            return None
        if defn.include_prereleases:
            releases = fetch_release_list(defn.github_repo, max_count=5)
            if releases:
                data = releases[0]
                return data.get("tag_name") or data.get("name")
            return None
        data = fetch_latest_release_info(defn.github_repo)
        if data:
            return data.get("tag_name") or data.get("name")
        return None

    def install(self, tool_id: str, version: Optional[str] = None) -> Tuple[bool, str]:
        defn = _TOOL_MAP.get(tool_id)
        if defn is None:
            return False, f"Unknown tool: {tool_id}"
        if defn.hidden:
            return False, f"{defn.display_name} is not available for install"
        if tool_id == "ttw_installer":
            return self._install_ttw()

        install_dir = TOOLS_BASE_DIR / tool_id
        install_dir.mkdir(parents=True, exist_ok=True)

        pin = version or defn.pinned_version
        nexus_ok, nexus_path, nexus_msg, nexus_version = _try_nexus_download(defn, install_dir) if not version else (False, None, _NEXUS_NOT_ELIGIBLE, None)
        if nexus_ok and nexus_path:
            ok, err = _extract_archive(nexus_path, install_dir)
            if ok:
                _extract_nested_archives(install_dir)
            tag = pin or nexus_version or "nexus"
        elif not defn.github_repo:
            if nexus_msg == _NEXUS_NOT_ELIGIBLE:
                nexus_url = (
                    f"https://www.nexusmods.com/{defn.nexus_game_domain}/mods/{defn.nexus_mod_id}"
                    if defn.nexus_mod_id else ""
                )
                return False, f"NEXUS_MANUAL_REQUIRED:{nexus_url}"
            return False, nexus_msg or f"Failed to download {defn.display_name} from Nexus"
        else:
            if defn.include_prereleases and not pin:
                releases = fetch_release_list(defn.github_repo, max_count=5)
                data = releases[0] if releases else None
            else:
                data = fetch_latest_release_info(defn.github_repo, pin)
            if not data:
                return False, f"Could not fetch release info for {defn.display_name}"
            asset = _find_asset(data, defn.asset_patterns)
            if not asset:
                all_names = [a.get("name", "") for a in data.get("assets", [])]
                return False, f"No matching asset found. Available: {', '.join(all_names)}"
            tag = data.get("tag_name") or data.get("name", "unknown")
            sums_asset = _find_sums_asset(data, asset.get("name", ""))
            ok, err = _download_and_extract(tool_id, asset, install_dir, sums_asset=sums_asset)

        if not ok:
            return False, err

        exe_path = _find_executable(defn, install_dir)
        if exe_path:
            try:
                os.chmod(exe_path, 0o755)
            except Exception:
                pass

        manifest = _read_manifest(tool_id)
        _write_manifest(tool_id, {
            "installed_version": tag,
            "previous_version": manifest.get("installed_version"),
            "binary_path": str(exe_path) if exe_path else None,
            "install_dir": str(install_dir),
        })

        logger.info("Installed %s %s", defn.display_name, tag)
        return True, f"{defn.display_name} {tag} installed"

    def install_from_archive(self, tool_id: str, archive_path: Path) -> Tuple[bool, str]:
        """Install a tool from a locally downloaded archive (manual download fallback)."""
        defn = _TOOL_MAP.get(tool_id)
        if defn is None:
            return False, f"Unknown tool: {tool_id}"

        install_dir = TOOLS_BASE_DIR / tool_id
        install_dir.mkdir(parents=True, exist_ok=True)

        ok, err = _extract_archive(archive_path, install_dir, delete_archive=False)
        if not ok:
            return False, err

        _extract_nested_archives(install_dir)
        exe_path = _find_executable(defn, install_dir)
        if exe_path:
            try:
                os.chmod(exe_path, 0o755)
            except Exception:
                pass

        manifest = _read_manifest(tool_id)
        _write_manifest(tool_id, {
            "installed_version": "manual",
            "previous_version": manifest.get("installed_version"),
            "binary_path": str(exe_path) if exe_path else None,
            "install_dir": str(install_dir),
        })

        logger.info("Installed %s from local archive %s", defn.display_name, archive_path.name)
        return True, f"{defn.display_name} installed"

    def update(self, tool_id: str) -> Tuple[bool, str]:
        defn = _TOOL_MAP.get(tool_id)
        if defn is None:
            return False, f"Unknown tool: {tool_id}"

        if tool_id == "ttw_installer":
            return self._install_ttw()

        manifest = _read_manifest(tool_id)
        current_dir = TOOLS_BASE_DIR / tool_id
        prev_dir = TOOLS_BASE_DIR / tool_id / "_previous"

        # Back up current install before overwriting
        if current_dir.exists() and manifest.get("installed_version"):
            import shutil
            try:
                if prev_dir.exists():
                    shutil.rmtree(prev_dir)
                # Copy current files (excluding _previous subdir) to _previous
                prev_dir.mkdir(parents=True, exist_ok=True)
                for item in current_dir.iterdir():
                    if item.name == "_previous":
                        continue
                    dest = prev_dir / item.name
                    if item.is_file():
                        shutil.copy2(item, dest)
                    elif item.is_dir():
                        shutil.copytree(item, dest)
            except Exception as e:
                logger.warning("Could not back up previous version of %s: %s", tool_id, e)

        ok, msg = self.install(tool_id)
        if ok and manifest.get("installed_version"):
            # Preserve previous_version in manifest (install() sets it from current manifest)
            updated_manifest = _read_manifest(tool_id)
            updated_manifest["previous_version"] = manifest.get("installed_version")
            _write_manifest(tool_id, updated_manifest)
        return ok, msg

    def downgrade(self, tool_id: str) -> Tuple[bool, str]:
        """Swap current install with the backed-up previous version."""
        defn = _TOOL_MAP.get(tool_id)
        if defn is None:
            return False, f"Unknown tool: {tool_id}"
        if tool_id == "ttw_installer":
            return False, "Downgrade not supported for TTW Linux Installer via this interface"

        import shutil
        current_dir = TOOLS_BASE_DIR / tool_id
        prev_dir = TOOLS_BASE_DIR / tool_id / "_previous"

        if not prev_dir.exists():
            return False, f"No previous version stored for {defn.display_name}"

        manifest = _read_manifest(tool_id)
        current_version = manifest.get("installed_version")
        previous_version = manifest.get("previous_version")

        # Swap: move current out, move previous in
        swap_dir = TOOLS_BASE_DIR / tool_id / "_swap"
        try:
            if swap_dir.exists():
                shutil.rmtree(swap_dir)
            swap_dir.mkdir(parents=True)
            for item in current_dir.iterdir():
                if item.name in ("_previous", "_swap"):
                    continue
                shutil.move(str(item), str(swap_dir / item.name))
            for item in prev_dir.iterdir():
                shutil.move(str(item), str(current_dir / item.name))
            # Put what was current into _previous
            if prev_dir.exists():
                shutil.rmtree(prev_dir)
            prev_dir.mkdir()
            for item in swap_dir.iterdir():
                shutil.move(str(item), str(prev_dir / item.name))
            shutil.rmtree(swap_dir, ignore_errors=True)
        except Exception as e:
            return False, f"Downgrade failed: {e}"

        exe_path = _find_executable(defn, current_dir)
        if exe_path:
            try:
                os.chmod(exe_path, 0o755)
            except Exception:
                pass

        _write_manifest(tool_id, {
            "installed_version": previous_version,
            "previous_version": current_version,
            "binary_path": str(exe_path) if exe_path else None,
            "install_dir": str(current_dir),
        })
        logger.info("Downgraded %s from %s to %s", defn.display_name, current_version, previous_version)
        return True, f"{defn.display_name} downgraded to {previous_version}"

    def uninstall(self, tool_id: str) -> Tuple[bool, str]:
        defn = _TOOL_MAP.get(tool_id)
        if defn is None:
            return False, f"Unknown tool: {tool_id}"
        if not defn.can_uninstall:
            return False, f"{defn.display_name} cannot be uninstalled - Jackify depends on it"

        import shutil
        tool_dir = TOOLS_BASE_DIR / tool_id
        if tool_dir.exists():
            try:
                shutil.rmtree(tool_dir)
            except Exception as e:
                return False, f"Uninstall failed: {e}"

        logger.info("Uninstalled %s", defn.display_name)
        return True, f"{defn.display_name} uninstalled"

    def get_binary_path(self, tool_id: str) -> Optional[Path]:
        if tool_id == "ttw_installer":
            _, _, binary = _ttw_status_from_config()
            return binary
        manifest = _read_manifest(tool_id)
        bp = manifest.get("binary_path")
        if bp:
            p = Path(bp)
            if p.is_file():
                return p
        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_status(self, defn: ToolDefinition) -> ToolStatus:
        if defn.tool_id == "ttw_installer":
            installed, version, binary = _ttw_status_from_config()
            return ToolStatus(
                definition=defn,
                installed=installed,
                installed_version=version,
                previous_version=None,
                binary_path=binary,
            )
        manifest = _read_manifest(defn.tool_id)
        installed_version = manifest.get("installed_version")
        binary_path_str = manifest.get("binary_path")
        binary_path = Path(binary_path_str) if binary_path_str else None
        installed = installed_version is not None and (binary_path is None or binary_path.is_file())

        if not installed and defn.tool_id == "jackify-engine":
            try:
                from jackify.backend.core.modlist_operations import get_jackify_engine_path
                bundled = Path(get_jackify_engine_path())
                if bundled.is_file():
                    installed = True
                    binary_path = bundled
                    if not installed_version:
                        version_file = bundled.parent / "version.txt"
                        if version_file.is_file():
                            installed_version = version_file.read_text().strip() or None
            except Exception:
                pass

        return ToolStatus(
            definition=defn,
            installed=installed,
            installed_version=installed_version,
            previous_version=manifest.get("previous_version"),
            binary_path=binary_path,
        )

    def _install_ttw(self) -> Tuple[bool, str]:
        """Delegate TTW install to the existing handler, installing into the tools directory."""
        try:
            from jackify.backend.handlers.ttw_installer_handler import TTWInstallerHandler
            from jackify.backend.handlers.filesystem_handler import FileSystemHandler
            from jackify.backend.handlers.config_handler import ConfigHandler
            fs = FileSystemHandler()
            cfg = ConfigHandler()
            handler = TTWInstallerHandler(
                steamdeck=False, verbose=False,
                filesystem_handler=fs, config_handler=cfg,
            )
            install_dir = TOOLS_BASE_DIR / "ttw_installer"
            install_dir.mkdir(parents=True, exist_ok=True)
            ok, msg = handler.install_ttw_installer(install_dir=install_dir)
            if ok:
                version = cfg.get("ttw_installer_version") or "unknown"
                exe_path = _find_executable(_TOOL_MAP["ttw_installer"], install_dir)
                _write_manifest("ttw_installer", {
                    "installed_version": version,
                    "binary_path": str(exe_path) if exe_path else None,
                })
            return ok, msg
        except Exception as e:
            return False, f"TTW install failed: {e}"
