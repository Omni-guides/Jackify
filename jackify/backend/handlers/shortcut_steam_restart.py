"""Steam restart methods for ShortcutHandler (Mixin)."""
import logging
from typing import Optional, Callable

logger = logging.getLogger(__name__)


class ShortcutSteamRestartMixin:
    """Mixin providing Steam restart methods."""

    def secure_steam_restart(self, status_callback: Optional[Callable[[str], None]] = None) -> bool:
        """Delegate to steam_restart_service (canonical restart path)."""
        try:
            from ..services.steam_restart_service import robust_steam_restart
            return robust_steam_restart(progress_callback=status_callback, timeout=60)
        except ImportError as e:
            self.logger.error("steam_restart_service unavailable: %s", e)
            return False
        except Exception as e:
            self.logger.error("robust_steam_restart failed: %s", e)
            return False
