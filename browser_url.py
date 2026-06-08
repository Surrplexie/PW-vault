"""
Read the current tab URL from a Chromium / Firefox browser window (Windows).

Uses UI Automation to read the address bar — the only reliable way to get
``access.pokemon.com/login`` when the tab title is just "Pokémon Trainer Central".

Falls back gracefully when uiautomation is not installed (title-only matching).
"""

from __future__ import annotations

import re
import sys
from urllib.parse import urlparse

# Chromium-based browsers name the omnibox consistently.
_OMNIBOX_NAMES = (
    "Address and search bar",
    "Address bar",
    "Search or enter address",
)

_HOST_RE = re.compile(
    r"^([a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)+)"
)


def hostname_from_url(url: str) -> str | None:
    """``https://access.pokemon.com/login?x=1`` → ``access.pokemon.com``"""
    if not url:
        return None
    s = url.strip()
    if not s:
        return None
    if not s.startswith(("http://", "https://")):
        # Address bar often omits the scheme
        if "://" not in s and "." in s.split("/")[0]:
            s = "https://" + s
        else:
            m = _HOST_RE.match(s)
            return m.group(1).lower() if m else None
    try:
        host = urlparse(s).hostname
        return host.lower() if host else None
    except Exception:
        return None


def _looks_like_url(val: str) -> bool:
    v = val.strip().lower()
    return v.startswith(("http://", "https://")) or (
        "." in v.split("/")[0] and " " not in v.split("/")[0]
    )


if sys.platform == "win32":
    def url_from_browser(hwnd: int) -> str | None:
        """Return the address-bar URL for *hwnd*, or None if unavailable."""
        if not hwnd:
            return None
        try:
            import uiautomation as auto
        except ImportError:
            return None
        try:
            root = auto.ControlFromHandle(hwnd)
            if not root:
                return None
            for depth in (12, 18):
                for name in _OMNIBOX_NAMES:
                    edit = root.EditControl(searchDepth=depth, Name=name)
                    if edit.Exists(0, 0):
                        val = edit.GetValuePattern().Value
                        if val and _looks_like_url(val):
                            return val.strip()
            # Last resort: any shallow Edit whose value looks like a URL
            for edit in _walk_edits(root, max_depth=14):
                try:
                    val = edit.GetValuePattern().Value
                except Exception:
                    continue
                if val and _looks_like_url(val):
                    return val.strip()
        except Exception:
            pass
        return None

    def _walk_edits(control, max_depth: int, depth: int = 0):
        if depth > max_depth:
            return
        try:
            import uiautomation as auto
            if isinstance(control, auto.EditControl):
                yield control
            for child in control.GetChildren():
                yield from _walk_edits(child, max_depth, depth + 1)
        except Exception:
            return

else:
    def url_from_browser(_hwnd: int) -> str | None:
        return None


def resolve_domain(title: str, hwnd: int = 0) -> str | None:
    """
    Best-effort domain for vault matching.

    Prefers the address-bar hostname (works on login pages), then falls back
    to parsing the window title.
    """
    from browser_watch import domain_from_title

    if sys.platform == "win32" and hwnd:
        host = hostname_from_url(url_from_browser(hwnd) or "")
        if host:
            return host
    return domain_from_title(title)
