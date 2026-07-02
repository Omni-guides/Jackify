"""
Config handler API key encryption and storage.
"""

import logging
from typing import Optional

from jackify.backend.utils.machine_crypto import encrypt as _encrypt, decrypt as _decrypt

logger = logging.getLogger(__name__)


class ConfigEncryptionMixin:
    """Mixin providing encryption and API key storage for ConfigHandler."""

    def _encrypt_api_key(self, api_key: str) -> str:
        """Encrypt API key using AES-GCM via machine_crypto."""
        return _encrypt(api_key)

    def _decrypt_api_key(self, encrypted_key: str) -> Optional[str]:
        """Decrypt API key.  Returns None on any failure - never returns garbage."""
        return _decrypt(encrypted_key)

    def save_api_key(self, api_key):
        """Save Nexus API key with encryption."""
        try:
            if api_key:
                encrypted_key = self._encrypt_api_key(api_key)
                if not encrypted_key:
                    logger.error("Failed to encrypt API key")
                    return False
                self.settings["nexus_api_key"] = encrypted_key
                logger.debug("API key encrypted and saved successfully")
            else:
                self.settings["nexus_api_key"] = None
                logger.debug("API key cleared")
            return self.save_config()
        except Exception as e:
            logger.error("Error saving API key: %s", e)
            return False

    def get_api_key(self):
        """Retrieve and decrypt the saved Nexus API key. Always reads fresh from disk."""
        try:
            config = self._read_config_from_disk()
            encrypted_key = config.get("nexus_api_key")
            if encrypted_key:
                return self._decrypt_api_key(encrypted_key)
            return None
        except Exception as e:
            logger.error("Error retrieving API key: %s", e)
            return None

    def has_saved_api_key(self):
        """Check if an API key is saved in configuration. Always reads fresh from disk."""
        config = self._read_config_from_disk()
        return config.get("nexus_api_key") is not None

    def clear_api_key(self):
        """Clear the saved API key from configuration."""
        try:
            self.settings["nexus_api_key"] = None
            logger.debug("API key cleared from configuration")
            return self.save_config()
        except Exception as e:
            logger.error("Error clearing API key: %s", e)
            return False
