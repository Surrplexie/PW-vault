"""
Background browser watcher.

Uses pure ctypes (no pywin32) to inspect the active foreground window
every INTERVAL seconds.  When the active window is a known browser and its
domain changes, fires the on_change callback on the Tk main thread via
tk.after().

Supported browsers (by window class):
  Chrome, Edge, Brave, Opera GX  → "Chrome_WidgetWin_1"
  Firefox, Waterfox               → "MozillaWindowClass"
"""

from __future__ import annotations

import ctypes
import re
import threading
import time
from typing import Callable

# ── Win32 helpers (no pywin32 required) ───────────────────────────────────────

_u32 = ctypes.windll.user32


def _class_name(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    _u32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _window_text(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(512)
    _u32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


def foreground_hwnd() -> int:
    return _u32.GetForegroundWindow()


# ── Browser class names ────────────────────────────────────────────────────────

BROWSER_CLASSES = frozenset({
    "Chrome_WidgetWin_1",     # Chrome, Edge, Brave, Vivaldi, Opera GX
    "MozillaWindowClass",     # Firefox, Waterfox, Librewolf
    "ApplicationFrameWindow", # Edge (legacy UWP wrapper, rare)
})

# ── Domain extraction ─────────────────────────────────────────────────────────

# Matches bare domain.tld or subdomain.domain.tld inside a title string.
# We intentionally skip single-word "domains" to avoid false positives.
_DOMAIN_RE = re.compile(
    r"\b([a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?"
    r"\.[a-zA-Z]{2,}(?:\.[a-zA-Z]{2,})?)\b"
)

# Title separators used by browsers  e.g. "GitHub – Google Chrome"
_SEP_RE = re.compile(r"\s+[–—|·•]\s+|\s+-\s+")


def domain_from_title(title: str) -> str | None:
    """
    Extract the most likely domain from a browser window title.

    Strategies (in order):
      1. Direct domain.tld regex match — most reliable for "Sign in to github.com - …"
      2. Split on separators and inspect penultimate chunk
      3. Return cleaned first segment
    """
    if not title:
        return None

    # Strategy 1: look for a plain domain.tld anywhere in the title
    for m in _DOMAIN_RE.finditer(title):
        cand = m.group(1).lower()
        # skip generic words that look like domains ("ok.to", "a.m", etc.)
        if "." in cand and len(cand) > 4:
            return cand

    # Strategy 2: split on dash/pipe separators
    parts = [p.strip() for p in _SEP_RE.split(title)]
    if len(parts) >= 2:
        # Browser name is always last; site name is typically second-to-last
        candidate = parts[-2].lower()
        if candidate:
            return candidate

    return None


# ── Watcher thread ─────────────────────────────────────────────────────────────

class BrowserWatcher(threading.Thread):
    """
    Daemon thread that polls the foreground window and fires *on_change*
    (via tk.after so it runs on the main thread) when the browser domain
    changes.

    Parameters
    ----------
    after_fn   : tk root.after function for thread-safe UI callbacks
    on_change  : callable(domain: str, hwnd: int)
    on_clear   : callable() — fired when the browser loses focus
    interval   : polling interval in seconds (default 1.5)
    """

    def __init__(
        self,
        after_fn: Callable,
        on_change: Callable[[str, int], None],
        on_clear: Callable[[], None],
        interval: float = 1.5,
    ) -> None:
        super().__init__(daemon=True, name="BrowserWatcher")
        self._after    = after_fn
        self._on_change = on_change
        self._on_clear  = on_clear
        self._interval  = interval
        self._running   = True
        self._last_domain: str | None = None
        self._last_hwnd: int = 0
        self.current_hwnd: int = 0

    def run(self) -> None:
        while self._running:
            try:
                self._tick()
            except Exception:
                pass
            time.sleep(self._interval)

    def stop(self) -> None:
        self._running = False

    def _tick(self) -> None:
        hwnd  = foreground_hwnd()
        cls   = _class_name(hwnd)
        if cls not in BROWSER_CLASSES:
            # Active window is not a browser — clear if we had a domain
            if self._last_domain is not None:
                self._last_domain = None
                self._after(0, self._on_clear)
            return

        title  = _window_text(hwnd)
        domain = domain_from_title(title)
        if not domain:
            return

        self.current_hwnd = hwnd
        if domain != self._last_domain:
            self._last_domain = domain
            self._after(0, lambda d=domain, h=hwnd: self._on_change(d, h))
