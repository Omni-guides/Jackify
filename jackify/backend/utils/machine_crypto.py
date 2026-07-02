"""Machine-tied AES-GCM encrypt/decrypt helpers.

Key derivation: sha256(hostname:username:machine-id:jackify) -> urlsafe_b64encode.
decrypt() returns None on ANY failure - never returns garbage or plaintext leakage.
"""

import base64
import hashlib
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def get_machine_key() -> bytes:
    """Return the machine-tied 32-byte AES key (base64-encoded for AES-GCM use)."""
    import socket
    import getpass
    try:
        hostname = socket.gethostname()
        username = getpass.getuser()
        machine_id = None
        for id_path in ('/etc/machine-id', '/var/lib/dbus/machine-id'):
            try:
                with open(id_path, 'r') as f:
                    machine_id = f.read().strip()
                    break
            except Exception:
                pass
        key_material = (
            f"{hostname}:{username}:{machine_id}:jackify"
            if machine_id
            else f"{hostname}:{username}:jackify"
        )
    except Exception as e:
        logger.warning("Failed to get machine info for encryption key: %s", e)
        key_material = "jackify:default:key"
    return base64.urlsafe_b64encode(hashlib.sha256(key_material.encode('utf-8')).digest())


def encrypt(plaintext: str) -> str:
    """Encrypt plaintext with AES-GCM.  Returns "" if pycryptodomex is unavailable."""
    try:
        from Cryptodome.Cipher import AES
        from Cryptodome.Random import get_random_bytes
        key = base64.urlsafe_b64decode(get_machine_key())
        nonce = get_random_bytes(12)
        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
        ciphertext, tag = cipher.encrypt_and_digest(plaintext.encode('utf-8'))
        combined = nonce + ciphertext + tag
        return base64.b64encode(combined).decode('utf-8')
    except ImportError:
        logger.warning("pycryptodomex not available - encryption disabled")
        return ""
    except Exception as e:
        logger.error("Encryption failed: %s", e)
        return ""


def decrypt(ciphertext: str) -> Optional[str]:
    """Decrypt ciphertext produced by encrypt().  Returns None on ANY failure."""
    try:
        from Cryptodome.Cipher import AES
        key = base64.urlsafe_b64decode(get_machine_key())
        combined = base64.b64decode(ciphertext.encode('utf-8'))
        if len(combined) < 28:
            return None
        nonce = combined[:12]
        tag = combined[-16:]
        data = combined[12:-16]
        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
        plaintext = cipher.decrypt_and_verify(data, tag)
        return plaintext.decode('utf-8')
    except ImportError:
        logger.warning("pycryptodomex not available - cannot decrypt")
        return None
    except Exception:
        return None
