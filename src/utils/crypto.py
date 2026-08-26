"""AES-256-GCM encryption for credentials and tokens at rest (§6.1).

Key comes from the ENCRYPTION_KEY env var (base64url-encoded 32 bytes).
For production, back this with a secret manager (Vault / AWS SM) instead
of an env var — the cipher interface stays the same.
"""
import base64
import json
import logging
import os
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from src.core.config import get_settings

logger = logging.getLogger(__name__)


class CredentialCipher:
    def __init__(self, key: bytes):
        if len(key) != 32:
            raise ValueError("AES-256 requires a 32-byte key")
        self._aesgcm = AESGCM(key)

    def encrypt(self, payload: Any) -> str:
        """Encrypt any JSON-serializable payload; returns base64 nonce+ciphertext."""
        nonce = os.urandom(12)
        plaintext = json.dumps(payload).encode("utf-8")
        ciphertext = self._aesgcm.encrypt(nonce, plaintext, None)
        return base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")

    def decrypt(self, blob: str) -> Any:
        raw = base64.urlsafe_b64decode(blob.encode("ascii"))
        nonce, ciphertext = raw[:12], raw[12:]
        plaintext = self._aesgcm.decrypt(nonce, ciphertext, None)
        return json.loads(plaintext.decode("utf-8"))


_cipher: CredentialCipher | None = None


def generate_key_b64() -> str:
    """Helper for operators: prints a fresh base64url 32-byte key."""
    return base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")


def get_cipher() -> CredentialCipher:
    global _cipher
    if _cipher is None:
        key_b64 = get_settings().encryption_key
        if key_b64:
            key = base64.urlsafe_b64decode(key_b64.encode("ascii"))
        else:
            logger.warning(
                "ENCRYPTION_KEY is not set; using an ephemeral key. "
                "Encrypted data will NOT survive restarts."
            )
            key = os.urandom(32)
        _cipher = CredentialCipher(key)
    return _cipher
