"""Swap MO2's usvfs_x64.dll for a Wine short-name patched build matching its own USVFS version.

The patched DLLs report DOS/8.3 short-name fields as absent when running under Wine while
keeping standard behaviour on native Windows. Upstream-measured loading-time reductions range
from approximately 12-45%, depending on the modlist, hardware and Wine/Proton configuration.

Not a critical step: it must never fail an install. Every failure path returns a result
flagged as a warning and leaves the original DLL untouched.

Exact-hash allowlist, not version-gated. `_SUPPORTED_BUILDS` maps a known-original DLL's
SHA-256 to the maintainer-tested patched build for that exact version (see
`Omni-guides/usvfs` release `wine-shortname-optimization.1`). A DLL not byte-identical to one
of these originals is left untouched, never patched - a self-reported MO2/usvfs version string
is not trusted, and a patch built against one USVFS version is never applied over another.

This replaces two earlier, narrower designs: a single pinned patched build applied regardless
of the modlist's source USVFS version (force-upgraded a 0.5.6.1 install to 0.5.7.2's patch and
crashed a real modlist with Community Shaders - see docs/PlanOfAction.md's "USVFS Fix Applied
Too Broadly" entry), and before that a byte-scan for one specific incompatible export name. The
exact-hash allowlist subsumes both: any DLL the byte-scan would have flagged, and any version
the single-pinned-build design would have force-upgraded, is not in `_SUPPORTED_BUILDS` and is
left alone.

Unrecognized versions are logged at warning with the `JACKIFY-USVFS-UNSUPPORTED` tag so a
support report can be grepped for; the install completes normally either way.
"""

import hashlib
import logging
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

USVFS_REPO = "Omni-guides/usvfs"
USVFS_RELEASE_TAG = "wine-shortname-optimization.1"
USVFS_DLL_NAME = "usvfs_x64.dll"
USVFS_SUMS_NAME = "SHA256SUMS.txt"
BACKUP_SUFFIX = ".jackify-backup"

CONFIG_KEY = "usvfs_linux_fix"

STATUS_APPLIED = "applied"
STATUS_ALREADY_PATCHED = "already_patched"
STATUS_DISABLED = "disabled"
STATUS_MISSING_DLL = "missing_dll"
STATUS_FAILED = "failed"
STATUS_UNSUPPORTED_BUILD = "unsupported_build"
STATUS_UNSUPPORTED_GAME = "unsupported_game_type"

_WARNING_STATUSES = {STATUS_MISSING_DLL, STATUS_FAILED, STATUS_UNSUPPORTED_BUILD}

# Games this patch is currently scoped to: Skyrim SE, Fallout 4, and their VR variants.
# FNV/Oblivion/etc are 32-bit games not yet tested against this patch - left untouched
# until confirmed safe. Covers both game-type key spellings used across the codebase
# (steamgriddb_service's "fo4"/"skyrim" vs verify_install's "fallout4"/"skyrim").
_SUPPORTED_GAME_TYPES = {"skyrim", "skyrimse", "skyrimvr", "fo4", "fallout4", "fallout4vr"}


def is_supported_game_type(game_type: Optional[str]) -> bool:
    """Whether the USVFS Linux fix applies to this game type at all."""
    return bool(game_type) and game_type.lower() in _SUPPORTED_GAME_TYPES

# Maintainer-verified original -> patched pairings, Omni-guides/usvfs release
# "wine-shortname-optimization.1". Each patched DLL is only ever applied over the exact
# original it was built and tested against.
_SUPPORTED_BUILDS = {
    "e2b766f418575021b9d350f384195ce6f23173169b37222cdef3d7fe5495f8b5": {
        "version": "0.5.6.1",
        "asset_name": "usvfs_x64-v0.5.6.1.dll",
        "patched_sha256": "d6bced794498f4129fac7df05f550252d74beb2cfde109cbdeee3902c07640bb",
    },
    "7ee7758433ab76713900e661056be8074b9c567971fde38fd0e514c76895e274": {
        "version": "0.5.7.2",
        "asset_name": "usvfs_x64-v0.5.7.2.dll",
        "patched_sha256": "7454334c1ea246a68ff8da492b5d63dae8cd2f1298f2d7105c920b5f593352aa",
    },
}
_PATCHED_HASHES = {build["patched_sha256"] for build in _SUPPORTED_BUILDS.values()}

# PE VERSIONINFO key names to try, in order, for the unsupported-build report only - never
# used for matching logic, which is hash-only (see module docstring).
_PE_VERSION_KEYS = ("ProductVersion", "FileVersion")


def _sha256_of(path: Path) -> str:
    sha256 = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            sha256.update(chunk)
    return sha256.hexdigest().lower()


def dll_sha256(path: Path) -> Optional[str]:
    """SHA-256 of a DLL on disk, or None if it can't be read. Public - also used by the
    install verifier to surface the hash in an unsupported-build report."""
    try:
        return _sha256_of(path)
    except OSError as e:
        logger.debug("Could not hash %s: %s", path, e)
        return None


def _pe_version_string(path: Optional[Path]) -> Optional[str]:
    """Best-effort ProductVersion/FileVersion from a PE file's VERSIONINFO resource, for the
    unsupported-build report message only - never used for matching logic, which stays
    hash-only. The Windows version resource's string table is UTF-16LE; decoding the whole
    file that way and regexing for the key is the same "byte-scan, not a structural parser"
    idiom the retired legacy-export check used, just against the version resource instead of
    the export table. None if the file is unreadable or neither key is found."""
    if path is None:
        return None
    try:
        data = path.read_bytes()
    except OSError:
        return None
    text = data.decode("utf-16-le", errors="ignore")
    for key in _PE_VERSION_KEYS:
        match = re.search(re.escape(key) + r"\x00*([0-9]+(?:\.[0-9]+){1,3})", text)
        if match:
            return match.group(1)
    return None


def find_mo2_exe(modlist_dir: Path) -> Optional[Path]:
    """Locate ModOrganizer.exe in an MO2 directory. Mirrors find_usvfs_dll()."""
    modlist_dir = Path(modlist_dir)
    for candidate in (modlist_dir / "ModOrganizer.exe", modlist_dir / "files" / "ModOrganizer.exe"):
        if candidate.is_file():
            return candidate
    return None


def build_unsupported_build_report(modlist_dir: Path, dll_path: Path) -> str:
    """The message shown for a DLL matching no known original: MO2 and USVFS versions are
    best-effort (see _pe_version_string) and show as "unknown" rather than blocking the
    message; the hash is always available since it's how the build was found unsupported."""
    mo2_version = _pe_version_string(find_mo2_exe(modlist_dir)) or "unknown"
    dll_version = _pe_version_string(dll_path) or "unknown"
    dll_hash = dll_sha256(dll_path) or "unreadable"
    return (
        "USVFS Performance Patch not applied - this modlist's USVFS build isn't in "
        "Jackify's supported list yet. This does not affect the install or the game but "
        "you could be missing out on improved loading times. Please report the modlist "
        f"name/version, MO2 version {mo2_version} and this DLL's Version {dll_version} "
        f"and SHA-256 ({dll_hash}) so support can be added."
    )


def _match_supported_build(dll_path: Path) -> Optional[dict]:
    """The `_SUPPORTED_BUILDS` entry for this DLL's exact current content, or None if its
    hash matches neither known original."""
    current_hash = dll_sha256(dll_path)
    if current_hash is None:
        return None
    return _SUPPORTED_BUILDS.get(current_hash)


@dataclass
class UsvfsPatchResult:
    status: str
    message: str

    @property
    def is_warning(self) -> bool:
        return self.status in _WARNING_STATUSES

    @property
    def ok(self) -> bool:
        return self.status in (STATUS_APPLIED, STATUS_ALREADY_PATCHED)


def is_enabled() -> bool:
    """Settings opt-out. Applies to the install and configure workflows only."""
    try:
        from jackify.backend.handlers.config_handler import ConfigHandler
        return bool(ConfigHandler().get(CONFIG_KEY, True))
    except Exception as e:
        logger.debug("Could not read %s setting, defaulting to enabled: %s", CONFIG_KEY, e)
        return True


def find_usvfs_dll(modlist_dir: Path) -> Optional[Path]:
    """Locate usvfs_x64.dll in an MO2 directory.

    Mirrors how verify_install locates ModOrganizer.exe - some modlists nest the MO2
    install under files/.
    """
    modlist_dir = Path(modlist_dir)
    for candidate in (modlist_dir / USVFS_DLL_NAME, modlist_dir / "files" / USVFS_DLL_NAME):
        if candidate.is_file():
            return candidate
    return None


def is_already_patched(dll_path: Path) -> bool:
    """True if Jackify has already swapped this DLL (a backup sits alongside it), or the
    DLL's own hash is already one of the known patched builds - a modlist can ship
    pre-patched, or the backup marker can be lost across a reinstall."""
    if Path(str(dll_path) + BACKUP_SUFFIX).is_file():
        return True
    return dll_sha256(dll_path) in _PATCHED_HASHES


def is_modlist_patched(modlist_dir: Path) -> bool:
    """Whether this modlist's usvfs has been swapped. Used by the verifier."""
    dll = find_usvfs_dll(modlist_dir)
    return bool(dll and is_already_patched(dll))


def is_unsupported_build(dll_path: Path) -> bool:
    """Public wrapper for cross-module callers (e.g. the install verifier) that need to
    know whether a modlist's usvfs_x64.dll would be skipped as an unrecognized build.
    Caller must have already ruled out is_already_patched()."""
    return _match_supported_build(dll_path) is None


def apply_usvfs_patch(
    modlist_dir: Path,
    log: Optional[Callable[[str], None]] = None,
    force: bool = False,
) -> UsvfsPatchResult:
    """Replace the modlist's usvfs_x64.dll with the patched build matching its own version.

    force bypasses the Settings toggle for a deliberate standalone run.
    Never raises: all failures come back as a result flagged is_warning.
    """
    def _log(msg: str) -> None:
        logger.info(msg)
        if log:
            log(msg)

    try:
        if not force and not is_enabled():
            return UsvfsPatchResult(STATUS_DISABLED, "USVFS Linux fix disabled in Settings")

        from jackify.backend.services.steamgriddb_service import detect_game_type_from_modlist
        game_type = detect_game_type_from_modlist(str(modlist_dir))
        if not is_supported_game_type(game_type):
            return UsvfsPatchResult(
                STATUS_UNSUPPORTED_GAME,
                "USVFS Linux fix only applies to Skyrim and Fallout 4 modlists "
                "(including VR) at this time - skipped",
            )

        dll_path = find_usvfs_dll(modlist_dir)
        if dll_path is None:
            # Absence means the install went wrong without being flagged. Do not create it.
            msg = f"{USVFS_DLL_NAME} not found in modlist directory - skipping USVFS Linux fix"
            logger.warning(msg)
            return UsvfsPatchResult(STATUS_MISSING_DLL, msg)

        if is_already_patched(dll_path):
            return UsvfsPatchResult(
                STATUS_ALREADY_PATCHED, "USVFS Linux fix already applied"
            )

        build = _match_supported_build(dll_path)
        if build is None:
            logger.warning(
                "JACKIFY-USVFS-UNSUPPORTED: %s hash %s does not match a supported USVFS build",
                USVFS_DLL_NAME, dll_sha256(dll_path) or "unreadable",
            )
            msg = build_unsupported_build_report(modlist_dir, dll_path)
            return UsvfsPatchResult(STATUS_UNSUPPORTED_BUILD, msg)

        _log(f"Applying USVFS Linux fix (USVFS {build['version']})")
        return _download_and_swap(dll_path, build, _log)

    except Exception as e:
        msg = f"USVFS Linux fix failed: {e}"
        logger.warning(msg, exc_info=True)
        return UsvfsPatchResult(STATUS_FAILED, msg)


def _download_and_swap(dll_path: Path, build: dict, log: Callable[[str], None]) -> UsvfsPatchResult:
    from jackify.backend.handlers.filesystem_handler import FileSystemHandler
    from jackify.backend.services.tool_registry import (
        _verify_sha256_sums,
        fetch_latest_release_info,
    )

    release = fetch_latest_release_info(USVFS_REPO, pinned_version=USVFS_RELEASE_TAG)
    if not release:
        return UsvfsPatchResult(
            STATUS_FAILED,
            f"Could not fetch usvfs release {USVFS_RELEASE_TAG} from GitHub",
        )

    asset_name = build["asset_name"]
    assets = {a.get("name", ""): a for a in release.get("assets", [])}
    dll_asset = assets.get(asset_name)
    sums_asset = assets.get(USVFS_SUMS_NAME)
    if not dll_asset or not dll_asset.get("browser_download_url"):
        return UsvfsPatchResult(
            STATUS_FAILED, f"Release {USVFS_RELEASE_TAG} has no {asset_name} asset"
        )
    if not sums_asset or not sums_asset.get("browser_download_url"):
        # The hash is the only guard against shipping a corrupt DLL into MO2
        return UsvfsPatchResult(
            STATUS_FAILED, f"Release {USVFS_RELEASE_TAG} has no {USVFS_SUMS_NAME} asset"
        )

    fs = FileSystemHandler()
    temp_dir = Path(tempfile.mkdtemp(prefix="jackify-usvfs-"))
    try:
        new_dll = temp_dir / asset_name
        sums_path = temp_dir / USVFS_SUMS_NAME

        if not fs.download_file(
            dll_asset["browser_download_url"], new_dll, overwrite=True, quiet=True
        ):
            return UsvfsPatchResult(STATUS_FAILED, f"Failed to download {asset_name}")
        if not fs.download_file(
            sums_asset["browser_download_url"], sums_path, overwrite=True, quiet=True
        ):
            return UsvfsPatchResult(STATUS_FAILED, f"Failed to download {USVFS_SUMS_NAME}")

        verified, err = _verify_sha256_sums(sums_path, new_dll)
        if not verified:
            return UsvfsPatchResult(
                STATUS_FAILED, f"Patched {asset_name} failed verification: {err}"
            )
        log(f"Verified patched {asset_name}")

        return _swap_in_place(dll_path, new_dll, build["patched_sha256"], log)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _swap_in_place(
    dll_path: Path, new_dll: Path, expected_patched_sha256: str, log: Callable[[str], None]
) -> UsvfsPatchResult:
    """Back up the original, move the verified DLL into place, then re-verify the
    installed file's hash. The backup is what marks the modlist as patched, so it is taken
    before the swap and restored if the swap or the post-install verification fails -
    otherwise a failure could leave MO2 with no usvfs at all.
    """
    backup_path = Path(str(dll_path) + BACKUP_SUFFIX)
    try:
        shutil.move(str(dll_path), str(backup_path))
    except Exception as e:
        return UsvfsPatchResult(STATUS_FAILED, f"Could not back up {USVFS_DLL_NAME}: {e}")

    def _restore(reason: str) -> UsvfsPatchResult:
        try:
            shutil.move(str(backup_path), str(dll_path))
            logger.warning("USVFS swap failed (%s), original %s restored", reason, USVFS_DLL_NAME)
        except Exception as restore_error:
            logger.error(
                "USVFS swap failed (%s) and the original could not be restored - "
                "it is at %s: %s", reason, backup_path, restore_error
            )
        return UsvfsPatchResult(STATUS_FAILED, f"Could not install patched {USVFS_DLL_NAME}: {reason}")

    try:
        shutil.move(str(new_dll), str(dll_path))
    except Exception as e:
        return _restore(str(e))

    installed_hash = dll_sha256(dll_path)
    if installed_hash != expected_patched_sha256:
        return _restore(f"installed hash mismatch: {installed_hash}")

    log(f"USVFS Linux fix applied (original saved as {backup_path.name})")
    return UsvfsPatchResult(STATUS_APPLIED, "USVFS Linux fix applied")
