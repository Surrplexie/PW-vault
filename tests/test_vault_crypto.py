"""Tests for vault encryption and atomic save."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vault_crypto import (
    decrypt_vault,
    encrypt_vault,
    restore_vault_from_backup,
    save_vault_blob,
    vault_backup_path,
)


class VaultCryptoTests(unittest.TestCase):
    def test_encrypt_decrypt_round_trip(self) -> None:
        data = {"version": 2, "entries": [{"name": "example.com", "fields": {}}]}
        blob = encrypt_vault("test-master-pw", data)
        out = decrypt_vault("test-master-pw", blob)
        self.assertEqual(out, data)

    def test_wrong_password_raises(self) -> None:
        blob = encrypt_vault("correct", {"version": 2})
        with self.assertRaises(Exception):
            decrypt_vault("wrong", blob)


class SaveVaultBlobTests(unittest.TestCase):
    def test_creates_new_vault_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "!vault.vpm"
            blob = b"VAULT1" + b"\x00" * 32
            save_vault_blob(path, blob)
            self.assertTrue(path.exists())
            self.assertEqual(path.read_bytes(), blob)
            self.assertFalse(vault_backup_path(path).exists())

    def test_rotates_backup_on_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "!vault.vpm"
            first = b"VAULT1-first-save"
            second = b"VAULT1-second-save"
            save_vault_blob(path, first)
            save_vault_blob(path, second)

            self.assertEqual(path.read_bytes(), second)
            bak = vault_backup_path(path)
            self.assertTrue(bak.exists())
            self.assertEqual(bak.read_bytes(), first)

    def test_no_partial_file_on_failed_replace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "!vault.vpm"
            save_vault_blob(path, b"VAULT1-initial")

            def _boom(_src, _dst) -> None:
                raise OSError("simulated replace failure")

            with patch("vault_crypto.os.replace", side_effect=_boom):
                with self.assertRaises(OSError):
                    save_vault_blob(path, b"VAULT1-never-written")

            self.assertEqual(path.read_bytes(), b"VAULT1-initial")
            leftovers = list(Path(tmp).glob("*.tmp"))
            self.assertEqual(leftovers, [])

    def test_restore_overwrites_vault_without_rotating_bak(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "!vault.vpm"
            first = b"VAULT1-first-save"
            second = b"VAULT1-second-save"
            save_vault_blob(path, first)
            save_vault_blob(path, second)
            bak = vault_backup_path(path)
            self.assertEqual(bak.read_bytes(), first)

            restore_vault_from_backup(path)

            self.assertEqual(path.read_bytes(), first)
            self.assertEqual(bak.read_bytes(), first)

    def test_restore_missing_backup_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "!vault.vpm"
            save_vault_blob(path, b"VAULT1-only")
            with self.assertRaises(FileNotFoundError):
                restore_vault_from_backup(path)


if __name__ == "__main__":
    unittest.main()
