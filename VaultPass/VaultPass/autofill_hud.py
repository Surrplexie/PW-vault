"""
AutofillHUD — borderless, always-on-top, non-focus-stealing overlay.

Key behaviour
-------------
• WS_EX_NOACTIVATE is applied via ctypes after the window maps, so clicking
  any button in the overlay does NOT steal keyboard focus from the browser.
  The browser's currently focused input field stays active.

• ▶ Fill copies the value to the clipboard and injects a Ctrl+V via
  SendInput(), so the value is pasted directly into the focused field.

• The overlay auto-hides after AUTO_HIDE_MS milliseconds of no interaction.

• The header bar can be dragged to reposition the overlay.

• Shows up to MAX_MATCHES entries, each ranked by domain similarity score.
  Fields shown per entry: Username, Email, Password, Phone (if non-null).
"""

from __future__ import annotations

import ctypes
import re
import tkinter as tk
from difflib import SequenceMatcher
from typing import Any

from vault_format import SiteEntry

# ── colours (mirrors main.py palette) ────────────────────────────────────────
BG     = "#1e1e2e"
PANEL  = "#252536"
INPUT  = "#313244"
ACCENT = "#7965c8"
ACTH   = "#6856b8"
FG     = "#cdd6f4"
MUTED  = "#7f849c"
BORDER = "#45475a"
DANGER = "#e06c75"
GREEN  = "#a6e3a1"
YELLOW = "#f9e2af"

HUD_WIDTH    = 340
MAX_MATCHES  = 3
AUTO_HIDE_MS = 20_000

_NULL_VALS = frozenset({"NULL", "NULLAAA", "NULLBBB", "NULLCCC", "NULLDDD", ""})

# Fields to offer for autofill, in priority order
# (label, vault key, is_secret)
FILL_FIELDS = [
    ("Username", "Website Username",     False),
    ("Email",    "Website Email",        False),
    ("Password", "Website Password",     True),
    ("Phone",    "Website Phone Number", False),
]

# ── Win32 constants / helpers ─────────────────────────────────────────────────

GWL_EXSTYLE      = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
GA_ROOT          = 2

INPUT_KEYBOARD  = 1
KEYEVENTF_KEYUP = 0x0002
VK_CONTROL      = 0x11
VK_V            = 0x56


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk",         ctypes.c_ushort),
        ("wScan",       ctypes.c_ushort),
        ("dwFlags",     ctypes.c_ulong),
        ("time",        ctypes.c_ulong),
        ("dwExtraInfo", ctypes.c_ulong),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT), ("_pad", ctypes.c_byte * 32)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("_u", _INPUT_UNION)]


def _send_ctrl_v() -> None:
    """Inject a Ctrl+V key sequence into whatever window is currently focused."""
    def ki(vk: int, flags: int = 0) -> _INPUT:
        return _INPUT(
            type=INPUT_KEYBOARD,
            _u=_INPUT_UNION(ki=_KEYBDINPUT(wVk=vk, dwFlags=flags)),
        )

    seq = [
        ki(VK_CONTROL),
        ki(VK_V),
        ki(VK_V,       KEYEVENTF_KEYUP),
        ki(VK_CONTROL, KEYEVENTF_KEYUP),
    ]
    arr = (_INPUT * 4)(*seq)
    ctypes.windll.user32.SendInput(4, arr, ctypes.sizeof(_INPUT))


def _set_noactivate(hwnd: int) -> None:
    """Make window non-activating — clicking it won't steal keyboard focus."""
    u = ctypes.windll.user32
    root = u.GetAncestor(hwnd, GA_ROOT)
    ex   = u.GetWindowLongW(root, GWL_EXSTYLE)
    u.SetWindowLongW(root, GWL_EXSTYLE, ex | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)


# ── Match scoring ─────────────────────────────────────────────────────────────

def _base(domain: str) -> str:
    """'sub.github.com' → 'github'"""
    parts = domain.lower().replace("www.", "").split(".")
    return parts[-2] if len(parts) >= 2 else parts[0]


def _score(current: str, entry_domain: str) -> float:
    c = current.lower().strip("/")
    e = entry_domain.lower().strip("/")
    if c == e:             return 1.00
    bc, be = _base(c), _base(e)
    if bc == be:           return 0.95
    if bc in be or be in bc: return 0.82
    if c in e or e in c:   return 0.72
    r = SequenceMatcher(None, bc, be).ratio()
    return r if r >= 0.45 else 0.0


def find_matches(
    domain: str,
    entries: list[SiteEntry],
    top_n: int = MAX_MATCHES,
) -> list[tuple[float, SiteEntry]]:
    """Return up to top_n (score, entry) pairs sorted by descending score."""
    results = [
        (s, e)
        for e in entries
        if (s := _score(domain, e.domain)) > 0
    ]
    return sorted(results, key=lambda x: x[0], reverse=True)[:top_n]


def _fill_fields(entry: SiteEntry) -> list[tuple[str, str, bool]]:
    """Return [(label, value, is_secret), ...] for non-null fillable fields."""
    d = dict(entry.lines)
    out = []
    for label, key, secret in FILL_FIELDS:
        val = d.get(key, "")
        if val and val not in _NULL_VALS:
            out.append((label, val, secret))
    return out


# ── HUD window ────────────────────────────────────────────────────────────────

class AutofillHUD:
    """
    Usage
    -----
    hud = AutofillHUD(root)

    # Call from main thread when watcher fires:
    hud.update(domain="github.com", matches=[(0.95, entry)], browser_hwnd=0x1234)

    # Call on vault lock:
    hud.hide()
    """

    def __init__(self, root: tk.Tk) -> None:
        self._root      = root
        self._win: tk.Toplevel | None = None
        self._b_hwnd    = 0
        self._hide_job: str | None = None
        self._dx = self._dy = 0

    # ── public ────────────────────────────────────────────────────────────

    def update(
        self,
        domain: str,
        matches: list[tuple[float, SiteEntry]],
        browser_hwnd: int,
    ) -> None:
        self._b_hwnd = browser_hwnd
        if not matches:
            self.hide()
            return
        self._ensure_window()
        self._rebuild(domain, matches)
        self._win.deiconify()
        self._win.lift()
        self._reset_timer()

    def hide(self) -> None:
        if self._win and self._win.winfo_exists():
            self._win.withdraw()

    def destroy(self) -> None:
        if self._win and self._win.winfo_exists():
            self._win.destroy()
        self._win = None

    # ── window lifecycle ───────────────────────────────────────────────────

    def _ensure_window(self) -> None:
        if self._win and self._win.winfo_exists():
            return
        w = tk.Toplevel(self._root)
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        w.attributes("-alpha", 0.97)
        w.configure(bg=PANEL)
        sw = self._root.winfo_screenwidth()
        w.geometry(f"{HUD_WIDTH}+{sw - HUD_WIDTH - 18}+60")
        w.protocol("WM_DELETE_WINDOW", self.hide)
        self._win = w
        # Apply NOACTIVATE after window is mapped
        w.after(150, lambda: _set_noactivate(w.winfo_id()))

    def _rebuild(self, domain: str, matches: list[tuple[float, SiteEntry]]) -> None:
        for ch in self._win.winfo_children():
            ch.destroy()

        # ── drag-header ────────────────────────────────────────────────────
        hdr = tk.Frame(self._win, bg=BG, cursor="fleur")
        hdr.pack(fill="x")
        hdr.bind("<ButtonPress-1>", self._drag_start)
        hdr.bind("<B1-Motion>",     self._drag_move)

        tk.Label(hdr, text="🔑 AutoFill", bg=BG, fg=ACCENT,
                 font=("Segoe UI", 9, "bold"), padx=8, pady=5).pack(side="left")
        tk.Label(hdr, text=f"↗ {domain}", bg=BG, fg=MUTED,
                 font=("Segoe UI", 8)).pack(side="left")
        tk.Button(hdr, text="✕", bg=BG, fg=MUTED,
                  relief="flat", font=("Segoe UI", 10), bd=0, padx=8, pady=3,
                  activebackground=BG, activeforeground=DANGER,
                  cursor="hand2", command=self.hide).pack(side="right")

        tk.Frame(self._win, bg=BORDER, height=1).pack(fill="x")

        # ── match blocks ───────────────────────────────────────────────────
        for score, ent in matches:
            self._add_match(ent, score)

        # ── footer hint ────────────────────────────────────────────────────
        tk.Frame(self._win, bg=PANEL, height=3).pack()
        tk.Label(self._win,
                 text="▶ Fill = paste into focused browser field  •  fades in 20 s",
                 bg=PANEL, fg=MUTED, font=("Segoe UI", 7),
                 wraplength=HUD_WIDTH - 12, pady=4).pack(fill="x", padx=6)

    def _add_match(self, ent: SiteEntry, score: float) -> None:
        pct = int(score * 100)
        col = GREEN if pct >= 90 else ACCENT if pct >= 72 else MUTED

        # entry header bar
        eh = tk.Frame(self._win, bg=INPUT)
        eh.pack(fill="x", padx=5, pady=(5, 0))
        tk.Label(eh, text=f"  {ent.domain}", bg=INPUT, fg=FG,
                 font=("Segoe UI", 9, "bold"), pady=4, anchor="w").pack(
            side="left", fill="x", expand=True)
        tk.Label(eh, text=f"{pct}% match", bg=INPUT, fg=col,
                 font=("Segoe UI", 7, "bold"), padx=6).pack(side="right")

        fields = _fill_fields(ent)
        if not fields:
            tk.Label(self._win, text="  (no fillable fields)",
                     bg=PANEL, fg=MUTED, font=("Segoe UI", 8),
                     pady=3).pack(anchor="w", padx=8)
        else:
            for label, val, secret in fields:
                self._add_field_row(label, val, secret)

        tk.Frame(self._win, bg=BORDER, height=1).pack(fill="x", padx=5, pady=(4, 0))

    def _add_field_row(self, label: str, val: str, secret: bool) -> None:
        row = tk.Frame(self._win, bg=PANEL)
        row.pack(fill="x", padx=5, pady=1)

        tk.Label(row, text=f"{label}:", bg=PANEL, fg=MUTED,
                 font=("Segoe UI", 8), width=9, anchor="w").pack(side="left")

        disp = "••••••••" if secret else (val if len(val) <= 28 else val[:25] + "…")
        tk.Label(row, text=disp, bg=PANEL, fg=FG,
                 font=("Consolas" if secret else "Segoe UI", 8),
                 anchor="w").pack(side="left", fill="x", expand=True, padx=(2, 4))

        # ▶ Fill — paste into focused browser field (no focus steal)
        tk.Button(row, text="▶ Fill",
                  bg=ACCENT, fg="white",
                  relief="flat", font=("Segoe UI", 7, "bold"),
                  activebackground=ACTH, activeforeground="white",
                  cursor="hand2", bd=0, padx=6, pady=1,
                  command=lambda v=val: self._fill(v)).pack(side="right", padx=(2, 0))

        # Copy — clipboard only
        tk.Button(row, text="Copy",
                  bg=INPUT, fg=FG,
                  relief="flat", font=("Segoe UI", 7),
                  activebackground=BORDER, activeforeground=FG,
                  cursor="hand2", bd=0, padx=6, pady=1,
                  command=lambda v=val: self._copy_only(v)).pack(side="right", padx=(0, 2))

    # ── actions ────────────────────────────────────────────────────────────

    def _copy_only(self, val: str) -> None:
        self._set_clip(val)
        self._reset_timer()

    def _fill(self, val: str) -> None:
        """
        1. Copy val to clipboard (NOACTIVATE means browser still has focus)
        2. After 80 ms (clipboard flush), inject Ctrl+V via SendInput
        The browser's focused input receives the paste — no focus switch needed.
        """
        self._set_clip(val)
        self._win.after(80, _send_ctrl_v)
        self._reset_timer()

    def _set_clip(self, val: str) -> None:
        self._root.clipboard_clear()
        self._root.clipboard_append(val)
        self._root.update()

    # ── drag ──────────────────────────────────────────────────────────────

    def _drag_start(self, e: tk.Event) -> None:
        self._dx, self._dy = e.x_root, e.y_root

    def _drag_move(self, e: tk.Event) -> None:
        nx = self._win.winfo_x() + (e.x_root - self._dx)
        ny = self._win.winfo_y() + (e.y_root - self._dy)
        self._dx, self._dy = e.x_root, e.y_root
        self._win.geometry(f"+{nx}+{ny}")

    # ── auto-hide timer ────────────────────────────────────────────────────

    def _reset_timer(self) -> None:
        if self._hide_job:
            self._root.after_cancel(self._hide_job)
        self._hide_job = self._root.after(AUTO_HIDE_MS, self.hide)
