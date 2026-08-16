"""Persistent UI settings for VaultPass (no secrets — not stored in the vault)."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

SETTINGS_FILENAME = "vaultpass.settings.json"

CLIP_CLEAR_MIN, CLIP_CLEAR_MAX = 5, 300
HUD_HIDE_MIN, HUD_HIDE_MAX = 5, 120

# 0 = disabled
IDLE_LOCK_CHOICES: tuple[int, ...] = (0, 60, 300, 600, 900, 1800)
IDLE_LOCK_LABELS: dict[int, str] = {
    0: "Off",
    60: "1 minute",
    300: "5 minutes",
    600: "10 minutes",
    900: "15 minutes",
    1800: "30 minutes",
}


def _clamp_int(val: Any, lo: int, hi: int, default: int) -> int:
    try:
        n = int(val)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def _nearest_idle(val: Any) -> int:
    try:
        n = int(val)
    except (TypeError, ValueError):
        return 600
    return min(IDLE_LOCK_CHOICES, key=lambda c: abs(c - n))


@dataclass
class VaultSettings:
    clip_clear_secs: int = 30
    hud_hide_secs: int = 20
    idle_lock_secs: int = 600
    autofill_enabled: bool = True
    last_vault_path: str = ""

    def clamp(self) -> "VaultSettings":
        self.clip_clear_secs = _clamp_int(
            self.clip_clear_secs, CLIP_CLEAR_MIN, CLIP_CLEAR_MAX, 30
        )
        self.hud_hide_secs = _clamp_int(
            self.hud_hide_secs, HUD_HIDE_MIN, HUD_HIDE_MAX, 20
        )
        self.idle_lock_secs = _nearest_idle(self.idle_lock_secs)
        self.autofill_enabled = bool(self.autofill_enabled)
        self.last_vault_path = str(self.last_vault_path or "")
        return self


def settings_path() -> Path:
    base = (
        Path(sys.executable).resolve().parent
        if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parent
    )
    return base / SETTINGS_FILENAME


def load_settings(path: Path | None = None) -> VaultSettings:
    p = path or settings_path()
    if not p.exists():
        return VaultSettings()
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return VaultSettings()
    if not isinstance(raw, dict):
        return VaultSettings()
    known = {f.name for f in fields(VaultSettings)}
    kwargs = {k: raw[k] for k in known if k in raw}
    try:
        return VaultSettings(**kwargs).clamp()
    except (TypeError, ValueError):
        return VaultSettings()


def save_settings(settings: VaultSettings, path: Path | None = None) -> None:
    p = path or settings_path()
    settings.clamp()
    payload = json.dumps(asdict(settings), indent=2) + "\n"
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(p)
