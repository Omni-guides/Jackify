#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Nexus OAuth Service
Handles OAuth 2.0 authentication flow with Nexus Mods using PKCE
"""

import os
import base64
import hashlib
import secrets
import webbrowser
import urllib.parse
import requests
import json
import logging
import time
import subprocess
from typing import Optional, Tuple, Dict

from .nexus_oauth_protocol import NexusOAuthProtocolMixin
from .nexus_oauth_callback import NexusOAuthCallbackMixin

logger = logging.getLogger(__name__)


class NexusOAuthService(NexusOAuthProtocolMixin, NexusOAuthCallbackMixin):
    """
    Handles OAuth 2.0 authentication with Nexus Mods
    Uses PKCE flow with system browser and localhost callback
    """

    # OAuth Configuration
    CLIENT_ID = "jackify"
    AUTH_URL = "https://users.nexusmods.com/oauth/authorize"
    TOKEN_URL = "https://users.nexusmods.com/oauth/token"
    USERINFO_URL = "https://users.nexusmods.com/oauth/userinfo"
    SCOPES = "public openid profile"

    # Redirect configuration (custom protocol scheme - no SSL cert needed!)
    # Requires jackify:// protocol handler to be registered with OS
    REDIRECT_URI = "jackify://oauth/callback"

    # Callback timeout (5 minutes)
    CALLBACK_TIMEOUT = 300

    def __init__(self):
        """Initialize OAuth service"""
        self._auth_code = None
        self._auth_state = None
        self._auth_error = None

        # Ensure jackify:// protocol is registered on first use
        self._ensure_protocol_registered()

    def _generate_pkce_params(self) -> Tuple[str, str, str]:
        """
        Generate PKCE code verifier, challenge, and state

        Returns:
            Tuple of (code_verifier, code_challenge, state)
        """
        # Generate code verifier (43-128 characters, base64url encoded)
        code_verifier = base64.urlsafe_b64encode(
            os.urandom(32)
        ).decode('utf-8').rstrip('=')

        # Generate code challenge (SHA256 hash of verifier, base64url encoded)
        code_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode('utf-8')).digest()
        ).decode('utf-8').rstrip('=')

        # Generate state for CSRF protection
        state = secrets.token_urlsafe(32)

        return code_verifier, code_challenge, state

    def _build_authorization_url(self, code_challenge: str, state: str) -> str:
        """
        Build the Nexus OAuth 2.0 authorisation URL with PKCE parameters.
        """
        params = {
            "response_type": "code",
            "client_id": self.CLIENT_ID,
            "redirect_uri": self.REDIRECT_URI,
            "scope": self.SCOPES,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        query = urllib.parse.urlencode(params)
        return f"{self.AUTH_URL}?{query}"

    def _send_desktop_notification(self, title: str, message: str) -> None:
        """Send a desktop notification via notify-send (Linux). No-op on failure."""
        try:
            subprocess.run(
                ["notify-send", title, message],
                capture_output=True,
                timeout=5,
                env={k: v for k, v in os.environ.items() if k not in ("LD_LIBRARY_PATH", "PYTHONPATH", "QT_PLUGIN_PATH")},
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            logger.debug("Desktop notification skipped: %s", e)
        except Exception as e:
            logger.debug("Desktop notification failed: %s", e)

    def _exchange_code_for_token(
        self,
        auth_code: str,
        code_verifier: str
    ) -> Optional[Dict]:
        """
        Exchange authorization code for access token

        Args:
            auth_code: Authorization code from callback
            code_verifier: PKCE code verifier

        Returns:
            Token response dict or None on failure
        """
        data = {
            'grant_type': 'authorization_code',
            'client_id': self.CLIENT_ID,
            'redirect_uri': self.REDIRECT_URI,
            'code': auth_code,
            'code_verifier': code_verifier
        }

        try:
            response = requests.post(self.TOKEN_URL, data=data, timeout=10)

            if response.status_code == 200:
                token_data = response.json()
                logger.info("Successfully exchanged authorization code for token")
                return token_data
            else:
                logger.error(f"Token exchange failed: {response.status_code} - {response.text}")
                return None

        except requests.RequestException as e:
            logger.error(f"Token exchange request failed: {e}")
            return None

    def refresh_token(self, refresh_token: str) -> Optional[Dict]:
        """
        Refresh an access token using refresh token

        Args:
            refresh_token: Refresh token from previous authentication

        Returns:
            New token response dict or None on failure
        """
        data = {
            'grant_type': 'refresh_token',
            'client_id': self.CLIENT_ID,
            'refresh_token': refresh_token
        }

        try:
            response = requests.post(self.TOKEN_URL, data=data, timeout=10)

            if response.status_code == 200:
                token_data = response.json()
                logger.info("Successfully refreshed access token")
                return token_data
            else:
                logger.error(f"Token refresh failed: {response.status_code} - {response.text}")
                return None

        except requests.RequestException as e:
            logger.error(f"Token refresh request failed: {e}")
            return None

    def get_user_info(self, access_token: str) -> Optional[Dict]:
        """
        Get user information using access token

        Args:
            access_token: OAuth access token

        Returns:
            User info dict or None on failure
        """
        headers = {
            'Authorization': f'Bearer {access_token}'
        }

        try:
            response = requests.get(self.USERINFO_URL, headers=headers, timeout=10)

            if response.status_code == 200:
                user_info = response.json()
                logger.info(f"Retrieved user info for: {user_info.get('name', 'unknown')}")
                return user_info
            else:
                logger.error(f"User info request failed: {response.status_code}")
                return None

        except requests.RequestException as e:
            logger.error(f"User info request failed: {e}")
            return None

    def authorize(self, show_browser_message_callback=None) -> Optional[Dict]:
        """
        Perform full OAuth authorization flow

        Args:
            show_browser_message_callback: Optional callback to display message about browser opening

        Returns:
            Token response dict or None on failure
        """
        logger.info("Starting Nexus OAuth authorization flow")

        # Reset state
        self._auth_code = None
        self._auth_state = None
        self._auth_error = None

        # Generate PKCE parameters
        code_verifier, code_challenge, state = self._generate_pkce_params()
        logger.debug(f"Generated PKCE parameters (state: {state[:10]}...)")

        # Build authorization URL
        auth_url = self._build_authorization_url(code_challenge, state)

        # Open browser
        logger.info("Opening browser for authorisation")

        try:
            # When running from AppImage, we need to clean the environment to avoid
            # library conflicts with system tools (xdg-open, kde-open, etc.)
            import os
            import subprocess

            env = os.environ.copy()

            # Remove AppImage-specific environment variables that can cause conflicts
            # These variables inject AppImage's bundled libraries into child processes
            appimage_vars = [
                'LD_LIBRARY_PATH',
                'PYTHONPATH',
                'PYTHONHOME',
                'QT_PLUGIN_PATH',
                'QML2_IMPORT_PATH',
            ]

            # Check if we're running from AppImage
            if 'APPIMAGE' in env or 'APPDIR' in env:
                logger.debug("Running from AppImage - cleaning environment for browser launch")
                for var in appimage_vars:
                    if var in env:
                        del env[var]
                        logger.debug(f"Removed {var} from browser environment")

            # Use Popen instead of run to avoid waiting for browser to close
            # xdg-open may not return until the browser closes, which could be never
            try:
                process = subprocess.Popen(
                    ['xdg-open', auth_url],
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True  # Detach from parent process
                )
                # Give it a moment to fail if it's going to fail
                import time
                time.sleep(0.5)

                # Check if process is still running or has exited successfully
                poll_result = process.poll()
                if poll_result is None:
                    # Process still running - browser is opening/open
                    logger.info("Browser opened successfully via xdg-open (process running)")
                    browser_opened = True
                elif poll_result == 0:
                    # Process exited successfully
                    logger.info("Browser opened successfully via xdg-open (exit code 0)")
                    browser_opened = True
                else:
                    # Process exited with error
                    logger.warning(f"xdg-open exited with code {poll_result}, trying webbrowser module")
                    if webbrowser.open(auth_url):
                        logger.info("Browser opened successfully via webbrowser module")
                        browser_opened = True
                    else:
                        logger.warning("webbrowser.open returned False")
                        browser_opened = False
            except FileNotFoundError:
                # xdg-open not found - try webbrowser module
                logger.warning("xdg-open not found, trying webbrowser module")
                if webbrowser.open(auth_url):
                    logger.info("Browser opened successfully via webbrowser module")
                    browser_opened = True
                else:
                    logger.warning("webbrowser.open returned False")
                    browser_opened = False
        except Exception as e:
            logger.error(f"Error opening browser: {e}")
            browser_opened = False

        # Send desktop notification
        self._send_desktop_notification(
            "Jackify - Nexus Authorisation",
            "Please check your browser to authorise Jackify"
        )

        # Show message via callback if provided (AFTER browser opens)
        if show_browser_message_callback:
            if browser_opened:
                show_browser_message_callback(
                    "Browser opened for Nexus authorisation.\n\n"
                    "After clicking 'Authorize', your browser may ask to\n"
                    "open Jackify or show a popup blocker notification.\n\n"
                    "Please click 'Open' or 'Allow' to complete authorization."
                )
            else:
                show_browser_message_callback(
                    f"Could not open browser automatically.\n\n"
                    f"Please open this URL manually:\n{auth_url}"
                )

        try:
            # Wait for callback via jackify:// protocol
            if not self._wait_for_callback():
                return None

            # Check for errors
            if self._auth_error:
                logger.error(f"Authorization failed: {self._auth_error}")
                return None

            if not self._auth_code:
                logger.error("No authorization code received")
                return None

            # Verify state matches
            if self._auth_state != state:
                logger.error("State mismatch - possible CSRF attack")
                return None

            logger.info("Authorization code received, exchanging for token")

            # Exchange code for token
            token_data = self._exchange_code_for_token(self._auth_code, code_verifier)

            if token_data:
                logger.info("OAuth authorization flow completed successfully")
            else:
                logger.error("Failed to exchange authorization code for token")

            return token_data
        finally:
            self._auth_state = None
