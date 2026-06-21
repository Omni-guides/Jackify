"""
Config handler API key encryption and storage.
"""

import os
import base64
import hashlib
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class ConfigEncryptionMixin:
    """Mixin providing encryption and API key storage for ConfigHandler."""

    def _get_encryption_key(self) -> bytes:
        """Generate Fernet-compatible encryption key for API key storage."""
        import socket
        import getpass
        try:
            hostname = socket.gethostname()
            username = getpass.getuser()
            machine_id = None
            try:
                with open('/etc/machine-id', 'r') as f:
                    machine_id = f.read().strip()
            except Exception:
                try:
                    with open('/var/lib/dbus/machine-id', 'r') as f:
                        machine_id = f.read().strip()
                except Exception:
                    pass
            key_material = f"{hostname}:{username}:{machine_id}:jackify" if machine_id else f"{hostname}:{username}:jackify"
        except Exception as e:
            logger.warning("Failed to get machine info for encryption: %s", e)
            key_material = "jackify:default:key"
        key_bytes = hashlib.sha256(key_material.encode('utf-8')).digest()
        return base64.urlsafe_b64encode(key_bytes)

    def _encrypt_api_key(self, api_key: str) -> str:
        """Encrypt API key using AES-GCM."""
        try:
            from Crypto.Cipher import AES
            from Crypto.Random import get_random_bytes
            key = base64.urlsafe_b64decode(self._get_encryption_key())
            nonce = get_random_bytes(12)
            cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
            ciphertext, tag = cipher.encrypt_and_digest(api_key.encode('utf-8'))
            combined = nonce + ciphertext + tag
            return base64.b64encode(combined).decode('utf-8')
        except ImportError:
            logger.warning("pycryptodome not available, using base64 encoding (less secure)")
            return base64.b64encode(api_key.encode('utf-8')).decode('utf-8')
        except Exception as e:
            logger.error("Error encrypting API key: %s", e)
            return ""

    def _decrypt_api_key(self, encrypted_key: str) -> Optional[str]:
        """Decrypt API key using AES-GCM."""
        try:
            from Crypto.Cipher import AES
            if not hasattr(AES, 'MODE_GCM'):
                try:
                    return base64.b64decode(encrypted_key.encode('utf-8')).decode('utf-8')
                except Exception:
                    return None
            key = base64.urlsafe_b64decode(self._get_encryption_key())
            combined = base64.b64decode(encrypted_key.encode('utf-8'))
            nonce = combined[:12]
            tag = combined[-16:]
            ciphertext = combined[12:-16]
            cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
            plaintext = cipher.decrypt_and_verify(ciphertext, tag)
            return plaintext.decode('utf-8')
        except ImportError:
            try:
                return base64.b64decode(encrypted_key.encode('utf-8')).decode('utf-8')
            except Exception:
                return None
        except (AttributeError, Exception):
            try:
                return base64.b64decode(encrypted_key.encode('utf-8')).decode('utf-8')
            except Exception as e:
                logger.error("Error decrypting API key: %s", e)
                return None

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
