"""Encrypt vault JSON with a master password (PBKDF2-HMAC-SHA256 + Fernet)."""

from __future__ import annotations

import base64
import json
import os
import shutil
import sys
import time
from pathlib import Path
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


def vault_backup_path(path: Path) -> Path:
    """Return the single rotating backup path for a vault file."""
    path = Path(path)
    return path.with_name(path.name + ".bak")


def _atomic_replace(src: Path, dst: Path) -> None:
    """Replace dst with src; retry briefly on Windows file-lock races."""
    attempts = 8 if sys.platform == "win32" else 1
    last_err: OSError | None = None
    for i in range(attempts):
        try:
            os.replace(src, dst)
            return
        except OSError as err:
            last_err = err
            if i + 1 < attempts:
                time.sleep(0.025 * (i + 1))
    if last_err is not None:
        raise last_err


def _write_backup(path: Path, bak: Path) -> None:
    try:
        shutil.copy2(path, bak)
    except OSError:
        pass


def restore_vault_from_backup(path: Path) -> Path:
    """
    Overwrite ``path`` with its ``.bak`` copy without rotating the backup.

    The backup file is left unchanged so a second restore is still possible.
    """
    path = Path(path)
    bak = vault_backup_path(path)
    if not bak.is_file() or bak.stat().st_size == 0:
        raise FileNotFoundError(f"No backup found at {bak}")
    blob = bak.read_bytes()
    tmp = path.with_name(f"{path.name}.{os.getpid()}.restore.tmp")
    try:
        with open(tmp, "wb") as f:
            f.write(blob)
            f.flush()
            os.fsync(f.fileno())
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_replace(tmp, path)
    except Exception:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise
    return bak


def save_vault_blob(path: Path, blob: bytes) -> None:
    """
    Atomically write encrypted vault bytes.

    Writes to a same-directory temp file, fsyncs, optionally copies the
    previous vault to ``<name>.bak``, then replaces the target in one step.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        with open(tmp, "wb") as f:
            f.write(blob)
            f.flush()
            os.fsync(f.fileno())
        if path.exists() and path.stat().st_size > 0:
            _write_backup(path, vault_backup_path(path))
        _atomic_replace(tmp, path)
    except Exception:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise
