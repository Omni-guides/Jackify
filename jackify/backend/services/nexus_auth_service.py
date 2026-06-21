#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Nexus Authentication Service
Unified service for Nexus authentication using OAuth or API key fallback
"""

import logging
import os
from typing import Optional, Tuple
from .nexus_oauth_service import NexusOAuthService
from ..handlers.oauth_token_handler import OAuthTokenHandler
from .api_key_service import APIKeyService

logger = logging.getLogger(__name__)


class NexusAuthService:
    """
    Unified authentication service for Nexus Mods
    Handles OAuth 2.0 (preferred) with API key fallback (legacy)
    """

    def __init__(self):
        """Initialize authentication service"""
        self.oauth_service = NexusOAuthService()
        self.token_handler = OAuthTokenHandler()
        self.api_key_service = APIKeyService()
        logger.debug("NexusAuthService initialized")

    def get_auth_token(self) -> Optional[str]:
        """
        Get authentication token, preferring OAuth over API key

        Returns:
            Access token or API key, or None if no authentication available
        """
        # Try OAuth first
        oauth_token = self._get_oauth_token()
        if oauth_token:
            logger.debug("Using OAuth token for authentication")
            return oauth_token

        # Fall back to API key
        api_key = self.api_key_service.get_saved_api_key()
        if api_key:
            logger.debug("Using API key for authentication (OAuth not available)")
            return api_key

        logger.warning("No authentication available (neither OAuth nor API key)")
        return None

    def _get_oauth_token(self) -> Optional[str]:
        """
        Get OAuth access token, refreshing if needed

        Returns:
            Valid access token or None
        """
        # Check if we have a stored token
        if not self.token_handler.has_token():
            logger.debug("No OAuth token stored")
            return None

        # Check if token is expired (15 minute buffer for long installs)
        if self.token_handler.is_token_expired(buffer_minutes=15):
            logger.info("OAuth token expiring soon, attempting refresh")

            # Try to refresh
            refresh_token = self.token_handler.get_refresh_token()
            if refresh_token:
                new_token_data = self.oauth_service.refresh_token(refresh_token)

                if new_token_data:
                    # Save refreshed token
                    self.token_handler.save_token({'oauth': new_token_data})
                    logger.info("OAuth token refreshed successfully")
                    return new_token_data.get('access_token')
                else:
                    logger.warning("Token refresh failed, OAuth token invalid")
                    # Delete invalid token
                    self.token_handler.delete_token()
                    return None
            else:
                logger.warning("No refresh token available")
                return None

        # Token is valid, return it
        return self.token_handler.get_access_token()

    def is_authenticated(self) -> bool:
        """
        Check if user is authenticated via OAuth or API key

        Returns:
            True if authenticated
        """
        return self.get_auth_token() is not None

    def get_auth_method(self) -> Optional[str]:
        """
        Get current authentication method

        Returns:
            'oauth', 'api_key', or None
        """
        # Check OAuth first
        oauth_token = self._get_oauth_token()
        if oauth_token:
            return 'oauth'

        # Check API key
        api_key = self.api_key_service.get_saved_api_key()
        if api_key:
            return 'api_key'

        return None

    def get_auth_status(self) -> Tuple[bool, str, Optional[str]]:
        """
        Get detailed authentication status

        Returns:
            Tuple of (authenticated, method, username)
            - authenticated: True if authenticated
            - method: 'oauth', 'oauth_expired', 'api_key', or 'none'
            - username: Username if available (OAuth only), or None
        """
        # Check if OAuth token exists
        if self.token_handler.has_token():
            # Check if refresh token is likely expired (hasn't been refreshed in 30+ days)
            token_info = self.token_handler.get_token_info()
            if token_info.get('refresh_token_likely_expired'):
                logger.warning("Refresh token likely expired (30+ days old), user should re-authorize")
                return False, 'oauth_expired', None

        # Try OAuth
        oauth_token = self._get_oauth_token()
        if oauth_token:
            # Try to get username from userinfo
            user_info = self.oauth_service.get_user_info(oauth_token)
            username = user_info.get('name') if user_info else None
            return True, 'oauth', username
        elif self.token_handler.has_token():
            # Had token but couldn't get valid access token (refresh failed)
            logger.warning("OAuth token refresh failed, token may be invalid")
            return False, 'oauth_expired', None

        # Try API key
        api_key = self.api_key_service.get_saved_api_key()
        if api_key:
            return True, 'api_key', None

        return False, 'none', None

    def authorize_oauth(self, show_browser_message_callback=None) -> bool:
        """
        Perform OAuth authorization flow

        Args:
            show_browser_message_callback: Optional callback for browser messages

        Returns:
            True if authorization successful
        """
        logger.info("Starting OAuth authorization")

        token_data = self.oauth_service.authorize(show_browser_message_callback)

        if token_data:
            # Save token
            success = self.token_handler.save_token({'oauth': token_data})
            if success:
                logger.info("OAuth authorization completed successfully")
                return True
            else:
                logger.error("Failed to save OAuth token")
                return False
        else:
            logger.error("OAuth authorization failed")
            return False

    def revoke_oauth(self) -> bool:
        """
        Revoke OAuth authorization by deleting stored token

        Returns:
            True if revoked successfully
        """
        logger.info("Revoking OAuth authorization")
        return self.token_handler.delete_token()

    def save_api_key(self, api_key: str) -> bool:
        """
        Save API key (legacy fallback)

        Args:
            api_key: Nexus API key

        Returns:
            True if saved successfully
        """
        return self.api_key_service.save_api_key(api_key)

    def validate_api_key(self, api_key: Optional[str] = None) -> Tuple[bool, Optional[str]]:
        """
        Validate API key against Nexus API

        Args:
            api_key: Optional API key to validate (uses stored if not provided)

        Returns:
            Tuple of (valid, username_or_error)
        """
        return self.api_key_service.validate_api_key_works(api_key)

    def ensure_valid_auth(self) -> Optional[str]:
        """
        Ensure we have valid authentication, refreshing if needed
        This should be called before any Nexus operation

        Returns:
            Valid auth token (OAuth access token or API key), or None
        """
        auth_token = self.get_auth_token()

        if not auth_token:
            logger.warning("No authentication available for Nexus operation")

        return auth_token

    def get_auth_for_engine(self) -> Tuple[Optional[str], Optional[str]]:
        """
        Get authentication for jackify-engine with auto-refresh support

        Returns both NEXUS_API_KEY (for backward compat) and NEXUS_OAUTH_INFO (for auto-refresh).
        When NEXUS_OAUTH_INFO is provided, the engine can automatically refresh expired tokens
        during long installations.

        Returns:
            Tuple of (nexus_api_key, nexus_oauth_info_json)
            - nexus_api_key: Access token or API key (for backward compat)
            - nexus_oauth_info_json: Full OAuth state JSON (for auto-refresh) or None
        """
        import json
        import time

        # Check if using OAuth and ensure token is fresh
        if self.token_handler.has_token():
            # Refresh token if expired (15 minute buffer for long installs)
            access_token = self._get_oauth_token()
            if not access_token:
                logger.warning("OAuth token refresh failed, cannot provide auth to engine")
                return (None, None)

            # Load the refreshed token data
            token_data = self.token_handler.load_token()

            if token_data:
                oauth_data = token_data.get('oauth', {})

                # Build NexusOAuthState JSON matching upstream Wabbajack format
                # Engine auto-refreshes tokens during long installations
                nexus_oauth_state = {
                    "oauth": {
                        "access_token": oauth_data.get('access_token'),
                        "token_type": oauth_data.get('token_type', 'Bearer'),
                        "expires_in": oauth_data.get('expires_in', 3600),
                        "refresh_token": oauth_data.get('refresh_token'),
                        "scope": oauth_data.get('scope', 'public openid profile'),
                        "created_at": oauth_data.get('created_at', int(time.time())),
                        "_received_at": token_data.get('_saved_at', int(time.time())) * 10000000 + 116444736000000000  # Convert Unix to Windows FILETIME
                    },
                    "api_key": ""
                }

                nexus_oauth_json = json.dumps(nexus_oauth_state)
                access_token = oauth_data.get('access_token')

                logger.info("Providing OAuth state to engine for auto-refresh capability")
                return (access_token, nexus_oauth_json)

        # Fall back to API key (no auto-refresh support)
        api_key = self.api_key_service.get_saved_api_key()
        if api_key:
            logger.info("Using API key for engine (no auto-refresh)")
            return (api_key, None)

        logger.warning("No authentication available for engine")
        return (None, None)

    def get_token_writeback_path(self) -> 'Path':
        """Return a PID-unique path where the engine should write back refreshed tokens."""
        from pathlib import Path
        from jackify.shared.paths import get_jackify_data_dir
        return get_jackify_data_dir() / f"oauth_writeback_{os.getpid()}.json"

    def apply_token_writeback(self, writeback_path) -> bool:
        """
        Read engine-written token writeback file and update local token store.
        Called after engine process exits. No-op if file does not exist (engine not yet
        supporting writeback, or API key auth was used).
        """
        import json
        from pathlib import Path
        path = Path(writeback_path)
        if not path.exists():
            return False
        try:
            data = json.loads(path.read_text())
            oauth = data.get('oauth', {})
            if oauth.get('access_token') and oauth.get('refresh_token'):
                self.token_handler.save_token({'oauth': oauth})
                logger.info("Applied OAuth token writeback from engine - refresh token rotation preserved")
                return True
            logger.debug("Token writeback file present but contains no usable OAuth data")
            return False
        except Exception as e:
            logger.warning("Failed to apply token writeback: %s", e)
            return False
        finally:
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass

    def clear_all_auth(self) -> bool:
        """
        Clear all authentication (both OAuth and API key)
        Useful for testing or switching accounts

        Returns:
            True if any auth was cleared
        """
        oauth_cleared = self.token_handler.delete_token()
        api_key_cleared = self.api_key_service.clear_api_key()

        if oauth_cleared or api_key_cleared:
            logger.info("Cleared all Nexus authentication")
            return True
        else:
            logger.debug("No authentication to clear")
            return False
