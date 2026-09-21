"""Archive extraction helpers for tool_registry.

Split out to keep tool_registry.py under the project's file-size guardrail.
"""

import logging
import os
import subprocess
import tarfile
import zipfile
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

_ZIP_MAGICS = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
_SEVENZIP_MAGIC = b"7z\xbc\xaf\x27\x1c"
_GZIP_MAGIC = b"\x1f\x8b"


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


def _sniff_archive_type(file_path: Path) -> Optional[str]:
    """Identify the archive format from its magic bytes.

    A mod's uploaded file can keep a misleading extension (e.g. a Nexus file
    named .zip whose actual content is a 7z archive) - trusting the extension
    alone made extraction fail with a raw "File is not a zip file" exception
    (issue #239). Returns None if the header doesn't match a known format.
    """
    try:
        with open(file_path, "rb") as f:
            header = f.read(8)
    except OSError:
        return None
    if header.startswith(_ZIP_MAGICS):
        return "zip"
    if header.startswith(_SEVENZIP_MAGIC):
        return "7z"
    if header.startswith(_GZIP_MAGIC):
        return "tar.gz"
    return None


def _extract_archive(file_path: Path, target_dir: Path, delete_archive: bool = True) -> Tuple[bool, str]:
    """Extract an archive or chmod an AppImage in place.

    The archive format is identified from its content first, falling back to
    the file extension only when the content is unrecognized (e.g. an
    AppImage, whose ELF header isn't an archive signature).

    Deletes the archive after successful extraction unless delete_archive=False.
    Never deletes the archive on failure.
    """
    name_lower = file_path.name.lower()
    archive_type = _sniff_archive_type(file_path)
    if archive_type is None:
        if name_lower.endswith(".tar.gz") or name_lower.endswith(".tgz"):
            archive_type = "tar.gz"
        elif name_lower.endswith(".zip"):
            archive_type = "zip"
        elif name_lower.endswith(".7z"):
            archive_type = "7z"
        elif name_lower.endswith(".appimage"):
            file_path.chmod(0o755)
            return True, ""
        else:
            return False, f"Unsupported format: {file_path.name}"

    extracted = False
    try:
        if archive_type == "tar.gz":
            with tarfile.open(file_path, "r:gz") as tf:
                tf.extractall(path=target_dir)
            extracted = True
        elif archive_type == "zip":
            with zipfile.ZipFile(file_path, "r") as zf:
                zf.extractall(path=target_dir)
            extracted = True
        elif archive_type == "7z":
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
    except (zipfile.BadZipFile, tarfile.TarError) as e:
        logger.error("Archive extraction failed for %s: %s", file_path.name, e)
        return False, (
            f"{file_path.name} doesn't look like a valid archive. It may be corrupted "
            "or an incomplete download - try downloading it again."
        )
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
