#!/usr/bin/env python3
"""
Entry point for Jackify GUI Frontend

Usage: python -m jackify.frontends.gui
"""

import sys
from pathlib import Path


def main():
    if len(sys.argv) > 1 and sys.argv[1].startswith('nxm://'):
        handle_nxm_url(sys.argv[1])
        return

    # Check if launched with jackify:// protocol URL (OAuth callback)
    if len(sys.argv) > 1 and sys.argv[1].startswith('jackify://'):
        handle_protocol_url(sys.argv[1])
        return

    # Normal GUI launch
    from jackify.frontends.gui.main import main as gui_main
    gui_main()


def handle_nxm_url(url: str) -> None:
    """Handle an nxm:// launch: hand off to running instance or open the app."""
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
        # A fresh QApplication here means Jackify wasn't already running - main.py's own
        # startup (which normally applies this) never ran, so this standalone dialog would
        # otherwise render with the platform's default (often light) palette instead of
        # Jackify's own theme.
        from jackify.frontends.gui.shared_theme import apply_dark_palette
        apply_dark_palette(app)

    from jackify.backend.services.nxm_ipc import send_to_running_instance
    if send_to_running_instance(url):
        return

    # No running instance - check for installed modlists before launching
    try:
        from jackify.tools.verify_install import discover_installed_modlists
        modlists = discover_installed_modlists()
    except Exception:
        modlists = []

    if not modlists:
        from jackify.frontends.gui.dialogs.nxm_download_dialog import show_no_modlists_error
        show_no_modlists_error()
        return

    from jackify.backend.services.nxm_url import parse_nxm_url
    from jackify.backend.services import nxm_session
    from jackify.frontends.gui.dialogs.nxm_download_dialog import NxmDownloadDialog

    nxm = parse_nxm_url(url)
    auto_start = nxm_session.detect_active_mo2_modlist(modlists)
    if auto_start is None:
        remembered = nxm_session.get_remembered_modlist()
        auto_start = next((m for m in modlists if m["name"] == remembered), None) if remembered else None

    dlg = NxmDownloadDialog(nxm, modlists, auto_start_modlist=auto_start)
    dlg.show()
    app.exec()


def handle_protocol_url(url: str):
    """Handle jackify:// protocol URL (OAuth callback)."""
    from urllib.parse import urlparse, parse_qs

    parsed = urlparse(url)
    full_path = f"/{parsed.netloc}{parsed.path}" if parsed.netloc else parsed.path

    if full_path != '/oauth/callback':
        _log_error(f"Unknown protocol path: {full_path}")
        return

    params = parse_qs(parsed.query)
    code = params.get('code', [None])[0]
    state = params.get('state', [None])[0]
    error = params.get('error', [None])[0]

    if error:
        error_description = params.get('error_description', ['No description'])[0]
        _log_error(f"OAuth error: {error} - {error_description}")
        return

    if not code or not state:
        _log_error("OAuth callback missing required parameters (code or state)")
        return

    callback_file = Path.home() / ".config" / "jackify" / "oauth_callback.tmp"
    try:
        callback_file.parent.mkdir(parents=True, exist_ok=True)
        callback_file.write_text(f"{code}\n{state}")
    except Exception as e:
        _log_error(f"Failed to write OAuth callback file: {e}")


def _log_error(message: str):
    """Write an error entry to protocol_handler.log. Only called on failure."""
    import datetime
    try:
        from jackify.shared.paths import get_jackify_logs_dir
        log_dir = get_jackify_logs_dir()
    except Exception:
        log_dir = Path.home() / ".config" / "jackify" / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "protocol_handler.log"
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(log_file, 'a') as f:
            f.write(f"[{timestamp}] ERROR: {message}\n")
    except Exception:
        pass


if __name__ == "__main__":
    main()
