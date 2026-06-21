"""Nexus Premium status detection service."""
import hashlib
import time
import logging
from typing import Tuple, Optional

import requests

logger = logging.getLogger(__name__)

NEXUS_VALIDATE_URL = "https://api.nexusmods.com/v1/users/validate.json"
NEXUS_OAUTH_USERINFO_URL = "https://users.nexusmods.com/oauth/userinfo"
_CACHE_TTL_SECONDS = 3600


class NexusPremiumService:
    """Check and cache Nexus Premium status for the authenticated user."""

    def check_premium_status(
        self, auth_token: str, is_oauth: bool = False
    ) -> Tuple[bool, Optional[str]]:
        """
        Query Nexus API for premium status.

        Args:
            auth_token: Nexus API key or OAuth access token.
            is_oauth: True when auth_token is an OAuth Bearer token.

        Returns:
            (is_premium, username) - both None/False on failure.
        """
        cached = self._read_cache(auth_token, is_oauth=is_oauth)
        if cached is not None:
            return cached

        result = self._fetch(auth_token, is_oauth=is_oauth)
        if result[1] is not None:
            self._write_cache(auth_token, result, is_oauth=is_oauth)
        return result

    def _fetch(self, auth_token: str, is_oauth: bool = False) -> Tuple[bool, Optional[str]]:
        try:
            if is_oauth:
                # OAuth path: userinfo endpoint returns membership_roles array.
                # The validate endpoint is for API keys only.
                resp = requests.get(
                    NEXUS_OAUTH_USERINFO_URL,
                    headers={"Authorization": f"Bearer {auth_token}", "Accept": "application/json"},
                    timeout=8,
                )
                resp.raise_for_status()
                data = resp.json()
                roles = data.get("membership_roles") or []
                is_premium = "premium" in roles
                username = data.get("name") or data.get("sub")
            else:
                resp = requests.get(
                    NEXUS_VALIDATE_URL,
                    headers={"apikey": auth_token, "Accept": "application/json"},
                    timeout=8,
                )
                resp.raise_for_status()
                data = resp.json()
                is_premium = bool(data.get("is_premium") or data.get("is_supporter"))
                username = data.get("name")
            logger.debug(f"Nexus user: {username}, premium={is_premium}, roles={data.get('membership_roles')}")
            return is_premium, username
        except Exception as e:
            logger.debug(f"Nexus premium check failed: {e}")
            return False, None

    def _cache_key(self, token: str, is_oauth: bool = False) -> str:
        suffix = "oauth" if is_oauth else "apikey"
        token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()[:12]
        return f"nexus_premium_cache_{token_hash}_{suffix}"

    def _read_cache(self, token: str, is_oauth: bool = False) -> Optional[Tuple[bool, Optional[str]]]:
        try:
            from jackify.backend.handlers.config_handler import ConfigHandler
            cfg = ConfigHandler()
            entry = cfg.get(self._cache_key(token, is_oauth))
            if not entry:
                return None
            if time.time() - entry.get("ts", 0) > _CACHE_TTL_SECONDS:
                return None
            return entry["is_premium"], entry.get("username")
        except Exception:
            return None

    def _write_cache(self, token: str, result: Tuple[bool, Optional[str]], is_oauth: bool = False) -> None:
        try:
            from jackify.backend.handlers.config_handler import ConfigHandler
            cfg = ConfigHandler()
            cfg.set(self._cache_key(token, is_oauth), {
                "is_premium": result[0],
                "username": result[1],
                "ts": time.time(),
            })
        except Exception:
            pass
