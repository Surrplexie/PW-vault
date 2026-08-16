"""Tests for persistent UI settings."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from vault_settings import VaultSettings, load_settings, save_settings


class VaultSettingsTests(unittest.TestCase):
    def test_defaults(self) -> None:
        s = VaultSettings()
        self.assertEqual(s.clip_clear_secs, 30)
        self.assertEqual(s.hud_hide_secs, 20)
        self.assertEqual(s.idle_lock_secs, 600)
        self.assertTrue(s.autofill_enabled)
        self.assertEqual(s.last_vault_path, "")

    def test_clamp_out_of_range(self) -> None:
        s = VaultSettings(
            clip_clear_secs=9999,
            hud_hide_secs=1,
            idle_lock_secs=123,
        ).clamp()
        self.assertEqual(s.clip_clear_secs, 300)
        self.assertEqual(s.hud_hide_secs, 5)
        self.assertEqual(s.idle_lock_secs, 60)

    def test_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "vaultpass.settings.json"
            original = VaultSettings(
                clip_clear_secs=45,
                hud_hide_secs=12,
                idle_lock_secs=900,
                autofill_enabled=False,
                last_vault_path=r"D:\vaults\!vault.vpm",
            )
            save_settings(original, path)
            loaded = load_settings(path)
            self.assertEqual(loaded.clip_clear_secs, 45)
            self.assertEqual(loaded.hud_hide_secs, 12)
            self.assertEqual(loaded.idle_lock_secs, 900)
            self.assertFalse(loaded.autofill_enabled)
            self.assertEqual(loaded.last_vault_path, r"D:\vaults\!vault.vpm")

    def test_missing_file_returns_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            loaded = load_settings(Path(tmp) / "nope.json")
            self.assertEqual(loaded, VaultSettings())

    def test_corrupt_json_returns_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "vaultpass.settings.json"
            path.write_text("{not json", encoding="utf-8")
            loaded = load_settings(path)
            self.assertEqual(loaded, VaultSettings())

    def test_unknown_keys_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "vaultpass.settings.json"
            path.write_text(
                json.dumps({"clip_clear_secs": 20, "secret": "nope"}),
                encoding="utf-8",
            )
            loaded = load_settings(path)
            self.assertEqual(loaded.clip_clear_secs, 20)
            self.assertFalse(hasattr(loaded, "secret"))


if __name__ == "__main__":
    unittest.main()