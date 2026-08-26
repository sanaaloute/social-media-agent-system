"""AES-256-GCM credential cipher roundtrip and tamper resistance (§6.1)."""
import pytest
from cryptography.exceptions import InvalidTag

from src.utils.crypto import CredentialCipher, generate_key_b64, get_cipher
import base64


def test_roundtrip_dict():
    cipher = get_cipher()
    payload = {"access_token": "abc123", "refresh_token": "xyz", "expires": 3600}
    blob = cipher.encrypt(payload)
    assert isinstance(blob, str)
    assert blob != str(payload)
    assert cipher.decrypt(blob) == payload


def test_roundtrip_unicode():
    cipher = get_cipher()
    payload = {"note": "héllo wörld — 你好"}
    assert cipher.decrypt(cipher.encrypt(payload)) == payload


def test_tampered_blob_rejected():
    cipher = get_cipher()
    blob = cipher.encrypt({"k": "v"})
    raw = bytearray(base64.urlsafe_b64decode(blob.encode("ascii")))
    raw[-1] ^= 0xFF  # flip a bit in the ciphertext
    tampered = base64.urlsafe_b64encode(bytes(raw)).decode("ascii")
    with pytest.raises(InvalidTag):
        cipher.decrypt(tampered)


def test_key_must_be_32_bytes():
    with pytest.raises(ValueError):
        CredentialCipher(b"too-short")


def test_generate_key_b64_is_valid():
    key = base64.urlsafe_b64decode(generate_key_b64().encode("ascii"))
    assert len(key) == 32
