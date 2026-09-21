"""
Nexus OAuth protocol handler registration: _ensure_protocol_registered.
"""

import os
import sys
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class NexusOAuthProtocolMixin:
    """Mixin providing jackify:// protocol registration for NexusOAuthService."""

    def _ensure_protocol_registered(self) -> bool:
        """Ensure jackify:// protocol is registered with the OS."""
        import subprocess
        if not sys.platform.startswith('linux'):
            logger.debug("Protocol registration only needed on Linux")
            return True
        try:
            desktop_file = Path.home() / ".local" / "share" / "applications" / "com.jackify.app.desktop"
            env = os.environ
            is_appimage = (
                'APPIMAGE' in env or 'APPDIR' in env or
                (sys.argv[0] and sys.argv[0].endswith('.AppImage'))
            )
            exec_path_reliable = True
            if is_appimage:
                if 'APPIMAGE' in env:
                    exec_path = env['APPIMAGE']
                    logger.info("Using APPIMAGE env var: %s", exec_path)
                elif sys.argv[0] and Path(sys.argv[0]).exists():
                    exec_path = str(Path(sys.argv[0]).resolve())
                    logger.info("Using resolved sys.argv[0]: %s", exec_path)
                else:
                    exec_path = sys.argv[0]
                    exec_path_reliable = False
                    logger.warning("Using sys.argv[0] as fallback: %s", exec_path)
            else:
                src_dir = Path(__file__).resolve().parent.parent.parent.parent
                exec_path = f'bash -c \'cd "{src_dir}" && "{sys.executable}" -m jackify.frontends.gui "$@"\' --'
                logger.info("DEV mode exec path: %s", exec_path)
                logger.info("Source directory: %s", src_dir)

            expected_exec = f'Exec="{exec_path}" %u' if is_appimage else f'Exec={exec_path} %u'
            needs_write = not desktop_file.exists()
            if not needs_write and exec_path_reliable:
                current_content = desktop_file.read_text()
                if expected_exec not in current_content:
                    needs_write = True
                    logger.info("Desktop file Exec path outdated, updating: %s", exec_path)
            elif not needs_write and not exec_path_reliable:
                logger.warning("Could not reliably determine AppImage path, keeping existing desktop file")

            desktop_file.parent.mkdir(parents=True, exist_ok=True)
            if needs_write and is_appimage:
                desktop_content = f"""[Desktop Entry]
Type=Application
Name=Jackify
Comment=Wabbajack modlist manager for Linux
Exec="{exec_path}" %u
Icon=com.jackify.app
Terminal=false
Categories=Game;Utility;
MimeType=x-scheme-handler/jackify;
"""
            elif needs_write:
                src_dir = Path(__file__).resolve().parent.parent.parent.parent
                desktop_content = f"""[Desktop Entry]
Type=Application
Name=Jackify
Comment=Wabbajack modlist manager for Linux
Exec={exec_path} %u
Icon=com.jackify.app
Terminal=false
Categories=Game;Utility;
MimeType=x-scheme-handler/jackify;
Path={src_dir}
"""
            if needs_write:
                desktop_file.write_text(desktop_content)
                logger.info("Desktop file written: %s", desktop_file)
                logger.info("Exec path: %s", exec_path)
                logger.info("AppImage mode: %s", is_appimage)
            else:
                logger.debug("Desktop file up to date, skipping write")

            mimeapps_path = Path.home() / ".config" / "mimeapps.list"
            mimeapps_updated = False
            try:
                if mimeapps_path.exists():
                    content = mimeapps_path.read_text()
                else:
                    mimeapps_path.parent.mkdir(parents=True, exist_ok=True)
                    content = "[Default Applications]\n"
                if 'x-scheme-handler/jackify=' not in content:
                    if '[Default Applications]' not in content:
                        content = "[Default Applications]\n" + content
                    lines = content.split('\n')
                    for i, line in enumerate(lines):
                        if line.strip() == '[Default Applications]':
                            lines.insert(i + 1, 'x-scheme-handler/jackify=com.jackify.app.desktop')
                            break
                    content = '\n'.join(lines)
                    mimeapps_path.write_text(content)
                    mimeapps_updated = True
                    logger.info("Added jackify handler to mimeapps.list")
            except Exception as e:
                logger.warning("Failed to update mimeapps.list: %s", e)

            if needs_write or mimeapps_updated:
                logger.info("Registering jackify:// protocol handler")
                apps_dir = Path.home() / ".local" / "share" / "applications"
                subprocess.run(['update-desktop-database', str(apps_dir)], capture_output=True, timeout=10)
                subprocess.run(
                    ['xdg-mime', 'default', 'com.jackify.app.desktop', 'x-scheme-handler/jackify'],
                    capture_output=True, timeout=10
                )
                subprocess.run(
                    ['xdg-settings', 'set', 'default-url-scheme-handler', 'jackify', 'com.jackify.app.desktop'],
                    capture_output=True, timeout=10
                )
                logger.info("jackify:// protocol registered successfully")
            else:
                logger.debug("jackify:// protocol already registered, skipping xdg calls")
            return True
        except Exception as e:
            logger.warning("Failed to register jackify:// protocol: %s", e)
            return False
