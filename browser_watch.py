"""
Background browser watcher — cross-platform (Windows + Linux/X11).

Windows:
  Uses pure ctypes / Win32 (no pywin32) to inspect the active foreground
  window every INTERVAL seconds.

Linux (X11 / XWayland):
  Uses `xdotool` via subprocess to read the active window class and title.
  Requires:  sudo apt install xdotool   (or equivalent)
  Note: pure Wayland sessions without XWayland are not supported.

Supported browsers:
  Windows → "Chrome_WidgetWin_1"  (Chrome, Edge, Brave, Opera GX, Vivaldi)
            "MozillaWindowClass"  (Firefox, Waterfox, Librewolf)
  Linux   → class keywords: google-chrome, chromium, brave-browser, firefox,
            waterfox, librewolf, microsoft-edge, opera, vivaldi

When the active browser domain changes, fires the on_change callback on the
Tk main thread via tk.after().
"""

from __future__ import annotations

import re
import sys
import threading
import time
from typing import Callable

# ── Domain extraction (shared) ────────────────────────────────────────────────

_DOMAIN_RE = re.compile(
    r"\b([a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?"
    r"\.[a-zA-Z]{2,}(?:\.[a-zA-Z]{2,})?)\b"
)
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

    for m in _DOMAIN_RE.finditer(title):
        cand = m.group(1).lower()
        if "." in cand and len(cand) > 4:
            return cand

    parts = [p.strip() for p in _SEP_RE.split(title)]
    if len(parts) >= 2:
        candidate = parts[-2].lower()
        if candidate:
            return candidate

    return None


# ── Platform-specific: get active window class + title + id ───────────────────

if sys.platform == "win32":
    import ctypes

    _u32 = ctypes.windll.user32

    _WIN_BROWSER_CLASSES = frozenset({
        "Chrome_WidgetWin_1",     # Chrome, Edge, Brave, Vivaldi, Opera GX
        "MozillaWindowClass",     # Firefox, Waterfox, Librewolf
        "ApplicationFrameWindow", # Edge legacy UWP wrapper (rare)
    })

    def _active_window() -> tuple[str, str, int]:
        """Return (wm_class, window_title, hwnd) for the current foreground window."""
        hwnd = _u32.GetForegroundWindow()
        buf_cls = ctypes.create_unicode_buffer(256)
        _u32.GetClassNameW(hwnd, buf_cls, 256)
        buf_txt = ctypes.create_unicode_buffer(512)
        _u32.GetWindowTextW(hwnd, buf_txt, 512)
        return buf_cls.value, buf_txt.value, hwnd

    def _is_browser(cls: str) -> bool:
        return cls in _WIN_BROWSER_CLASSES

else:
    # Linux / macOS — uses xdotool (X11 or XWayland)
    import subprocess

    _LIN_BROWSER_KEYWORDS = (
        "google-chrome", "chromium", "chromium-browser",
        "brave-browser", "firefox", "waterfox", "librewolf",
        "microsoft-edge", "opera", "vivaldi", "epiphany",
    )

    def _xdotool(*args: str) -> str:
        try:
            return subprocess.check_output(
                ["xdotool"] + list(args),
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
        except Exception:
            return ""

    def _active_window() -> tuple[str, str, int]:
        """Return (wm_class, window_title, window_id) for the active X window."""
        wid_str = _xdotool("getactivewindow")
        if not wid_str:
            return "", "", 0
        title = _xdotool("getwindowname", wid_str)
        cls   = _xdotool("getwindowclassname", wid_str)
        try:
            wid = int(wid_str)
        except ValueError:
            wid = 0
        return cls, title, wid

    def _is_browser(cls: str) -> bool:
        c = cls.lower()
        return any(k in c for k in _LIN_BROWSER_KEYWORDS)


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
        self._after     = after_fn
        self._on_change = on_change
        self._on_clear  = on_clear
        self._interval  = interval
        self._running   = True
        self._last_domain: str | None = None
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
        cls, title, wid = _active_window()

        if not _is_browser(cls):
            if self._last_domain is not None:
                self._last_domain = None
                self._after(0, self._on_clear)
            return

        domain = domain_from_title(title)
        if not domain:
            return

        self.current_hwnd = wid
        if domain != self._last_domain:
            self._last_domain = domain
            self._after(0, lambda d=domain, h=wid: self._on_change(d, h))
