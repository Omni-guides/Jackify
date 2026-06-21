"""NXM protocol handler registration.

Updates (or creates) the Jackify .desktop file to include
x-scheme-handler/nxm in its MimeType, then registers it with xdg.
"""

import logging
import os
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_DESKTOP_FILE = Path.home() / ".local" / "share" / "applications" / "com.jackify.app.desktop"
_NXM_MIME = "x-scheme-handler/nxm"


def ensure_nxm_registered() -> bool:
    """Add nxm:// handler to the existing Jackify .desktop file if not present.

    Safe to call on every launch - no-ops when already registered.
    Returns True on success.
    """
    try:
        if not _DESKTOP_FILE.exists():
            if not _create_desktop_file():
                return False

        content = _DESKTOP_FILE.read_text()
        if _NXM_MIME in content:
            logger.debug("nxm:// already registered in desktop file")
            return True

        # Add nxm to existing MimeType= line
        updated = False
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if line.strip().startswith("MimeType="):
                if not line.rstrip().endswith(";"):
                    lines[i] = line.rstrip() + ";"
                lines[i] = lines[i] + f"{_NXM_MIME};"
                updated = True
                break

        if not updated:
            # No MimeType line - append one
            lines.append(f"MimeType={_NXM_MIME};")

        _DESKTOP_FILE.write_text("\n".join(lines) + "\n")
        logger.info("Added nxm:// to desktop file MimeType")

        _run_xdg_registration()
        return True

    except Exception as e:
        logger.warning("Failed to register nxm:// protocol: %s", e)
        return False


def _create_desktop_file() -> bool:
    """Create a minimal .desktop file with both jackify:// and nxm:// handlers."""
    try:
        env = os.environ
        is_appimage = (
            "APPIMAGE" in env or "APPDIR" in env or
            (sys.argv[0] and sys.argv[0].endswith(".AppImage"))
        )
        if is_appimage:
            exec_path = env.get("APPIMAGE") or str(Path(sys.argv[0]).resolve())
            exec_line = f'Exec="{exec_path}" %u'
        else:
            src_dir = Path(__file__).resolve().parent.parent.parent.parent
            exec_path = f'bash -c \'cd "{src_dir}" && "{sys.executable}" -m jackify.frontends.gui "$@"\' --'
            exec_line = f"Exec={exec_path} %u"

        _DESKTOP_FILE.parent.mkdir(parents=True, exist_ok=True)
        _DESKTOP_FILE.write_text(
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=Jackify\n"
            "Comment=Wabbajack modlist manager for Linux\n"
            f"{exec_line}\n"
            "Icon=com.jackify.app\n"
            "Terminal=false\n"
            "Categories=Game;Utility;\n"
            f"MimeType=x-scheme-handler/jackify;{_NXM_MIME};\n"
        )
        logger.info("Created desktop file at %s", _DESKTOP_FILE)
        return True
    except Exception as e:
        logger.warning("Failed to create desktop file: %s", e)
        return False


def _run_xdg_registration() -> None:
    apps_dir = _DESKTOP_FILE.parent
    for cmd in [
        ["update-desktop-database", str(apps_dir)],
        ["xdg-mime", "default", _DESKTOP_FILE.name, _NXM_MIME],
        ["xdg-settings", "set", "default-url-scheme-handler", "nxm", _DESKTOP_FILE.name],
    ]:
        try:
            subprocess.run(cmd, capture_output=True, timeout=10)
        except Exception as e:
            logger.debug("xdg command %s failed (non-fatal): %s", cmd[0], e)

    # mimeapps.list fallback for DEs that ignore xdg-settings
    mimeapps = Path.home() / ".config" / "mimeapps.list"
    try:
        content = mimeapps.read_text() if mimeapps.exists() else "[Default Applications]\n"
        if f"{_NXM_MIME}=" not in content:
            if "[Default Applications]" not in content:
                content = "[Default Applications]\n" + content
            lines = content.split("\n")
            for i, line in enumerate(lines):
                if line.strip() == "[Default Applications]":
                    lines.insert(i + 1, f"{_NXM_MIME}={_DESKTOP_FILE.name}")
                    break
            mimeapps.parent.mkdir(parents=True, exist_ok=True)
            mimeapps.write_text("\n".join(lines))
            logger.info("Added nxm handler to mimeapps.list")
    except Exception as e:
        logger.debug("mimeapps.list update failed (non-fatal): %s", e)
