"""
Nexus OAuth callback: _wait_for_callback.

Callback delivery is the jackify:// protocol handler (registered by
NexusOAuthProtocolMixin), which writes code+state to oauth_callback.tmp for this
method to poll. There is no localhost HTTP server in this flow.
"""

import time
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class NexusOAuthCallbackMixin:
    """Mixin providing callback wait logic for NexusOAuthService."""

    def _wait_for_callback(self) -> bool:
        """Wait for OAuth callback via jackify:// protocol handler. Returns True if callback received."""
        callback_file = Path.home() / ".config" / "jackify" / "oauth_callback.tmp"
        if callback_file.exists():
            callback_file.unlink()
        logger.info("Waiting for OAuth callback via jackify:// protocol")
        start_time = time.time()
        last_reminder = 0
        while (time.time() - start_time) < self.CALLBACK_TIMEOUT:
            if callback_file.exists():
                try:
                    lines = callback_file.read_text().strip().split('\n')
                    if len(lines) >= 2:
                        self._auth_code = lines[0]
                        self._auth_state = lines[1]
                        logger.info("OAuth callback received: code=%s...", self._auth_code[:10])
                        callback_file.unlink()
                        return True
                except Exception as e:
                    logger.error("Failed to read callback file: %s", e)
                    return False
            elapsed = time.time() - start_time
            if elapsed - last_reminder > 30:
                logger.info("Still waiting for OAuth callback... (%ss elapsed)", int(elapsed))
                if elapsed > 60:
                    logger.warning(
                        "If you see a blank browser tab, check for browser notifications asking to "
                        "'Open Jackify', or use 'Paste callback URL' in Jackify to paste the URL from the address bar"
                    )
                last_reminder = elapsed
            time.sleep(0.5)
        logger.error("OAuth callback timeout after %s seconds", self.CALLBACK_TIMEOUT)
        logger.error(
            "Protocol handler may not be working. Check:\n"
            "  1. Browser asked 'Open Jackify?' and you clicked Allow\n"
            "  2. No popup blocker notifications\n"
            "  3. Desktop file exists: ~/.local/share/applications/com.jackify.app.desktop"
        )
        return False
