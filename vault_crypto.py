"""Encrypt vault JSON with a master password (PBKDF2-HMAC-SHA256 + Fernet)."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from typing import Any

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


def _derive_key(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480_000,
    )
    return base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))


def encrypt_blob(password: str, plaintext: bytes) -> bytes:
    salt = os.urandom(16)
    key = _derive_key(password, salt)
    token = Fernet(key).encrypt(plaintext)
    return b"VAULT1" + salt + token


def decrypt_blob(password: str, blob: bytes) -> bytes:
    if not blob.startswith(b"VAULT1"):
        raise ValueError("Not a VaultPass file or corrupt header.")
    salt = blob[6:22]
    token = blob[22:]
    key = _derive_key(password, salt)
    return Fernet(key).decrypt(token)


def encrypt_vault(password: str, data: dict[str, Any]) -> bytes:
    raw = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    return encrypt_blob(password, raw)


def decrypt_vault(password: str, blob: bytes) -> dict[str, Any]:
    raw = decrypt_blob(password, blob)
    return json.loads(raw.decode("utf-8"))
