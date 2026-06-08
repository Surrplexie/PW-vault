"""
AutofillHUD — borderless, always-on-top, non-focus-stealing overlay.
Cross-platform: Windows (Win32) and Linux (X11 / XWayland via xdotool).

Key behaviour
-------------
• The overlay does NOT steal keyboard focus from the browser.
  Windows: WS_EX_NOACTIVATE is applied via ctypes after the window maps.
  Linux:   overrideredirect(True) + xdotool handles injection without focus grab.

• ▶ Fill copies the value to the clipboard then injects Ctrl+V into the
  focused browser field:
    Windows → SendInput() Win32 API
    Linux   → xdotool key ctrl+v  (requires: sudo apt install xdotool)

• The overlay auto-hides after AUTO_HIDE_MS milliseconds of no interaction.

• The header bar can be dragged to reposition the overlay.

• Shows up to MAX_MATCHES entries, each ranked by domain similarity score.
  Fields shown per entry: Username, Email, Password, Phone (if non-null).
"""

from __future__ import annotations

import re
import sys
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

# ── Platform-specific: key injection + no-activate ───────────────────────────

if sys.platform == "win32":
    import ctypes

    GWL_EXSTYLE      = -20
    WS_EX_NOACTIVATE = 0x08000000
    WS_EX_TOOLWINDOW = 0x00000080
    GA_ROOT          = 2
    INPUT_KEYBOARD   = 1
    KEYEVENTF_KEYUP  = 0x0002
    VK_CONTROL       = 0x11
    VK_V             = 0x56

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

    def _inject_paste() -> None:
        """Inject Ctrl+V into the currently focused window via Win32 SendInput."""
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

    def _apply_noactivate(hwnd: int) -> None:
        """Make window non-activating so clicking it won't steal keyboard focus."""
        u    = ctypes.windll.user32
        root = u.GetAncestor(hwnd, GA_ROOT)
        ex   = u.GetWindowLongW(root, GWL_EXSTYLE)
        u.SetWindowLongW(root, GWL_EXSTYLE, ex | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)

    def _focus_window(hwnd: int) -> None:
        """Bring *hwnd* to the foreground so SendInput reaches the browser field."""
        if not hwnd:
            return
        u   = ctypes.windll.user32
        k32 = ctypes.windll.kernel32
        fg  = u.GetForegroundWindow()
        if fg == hwnd:
            return
        fg_tid = u.GetWindowThreadProcessId(fg, None)
        cur_tid = k32.GetCurrentThreadId()
        attached = False
        if fg_tid != cur_tid:
            attached = bool(u.AttachThreadInput(cur_tid, fg_tid, True))
        try:
            u.SetForegroundWindow(hwnd)
        finally:
            if attached:
                u.AttachThreadInput(cur_tid, fg_tid, False)

else:
    # Linux / X11 — xdotool handles paste injection; overrideredirect handles focus
    import subprocess

    def _inject_paste() -> None:
        """Inject Ctrl+V into the currently focused X window via xdotool."""
        try:
            subprocess.Popen(
                ["xdotool", "key", "ctrl+v"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            pass  # xdotool not installed — fill silently degrades to copy-only

    def _apply_noactivate(_hwnd: int) -> None:
        """No-op on Linux: overrideredirect(True) already prevents focus stealing."""
        pass

    def _focus_window(_hwnd: int) -> None:
        """No-op on Linux: xdotool targets the X11 focus window directly."""
        pass


# ── Match scoring ─────────────────────────────────────────────────────────────

_TLD_RE = re.compile(
    r"\.(com|net|org|io|co|edu|gov|info|biz|app|dev|uk|ca|de|fr|au|nz|eu|tv|me|us)$"
)
_SKIP_TOKENS = frozenset({
    "www", "com", "net", "org", "io", "co", "login", "sign", "account", "accounts",
    "welcome", "home", "page", "the", "and", "for", "to", "in", "on",
})


def _base(domain: str) -> str:
    """'sub.github.com' → 'github',  'paradox' → 'paradox'"""
    s = domain.lower().replace("www.", "").strip("/")
    if "." in s:
        parts = s.split(".")
        return parts[-2] if len(parts) >= 2 else parts[0]
    return s


def _entry_names(entry_domain: str) -> set[str]:
    """All comparable name tokens for a vault entry domain."""
    e = entry_domain.lower().strip("/")
    names = {e, _base(e)}
    if "." in e:
        names.add(e.split(".")[0])
    return {n for n in names if n}


def _page_tokens(page: str) -> set[str]:
    """Keywords extracted from a browser title / hostname fragment."""
    s = page.lower().replace("www.", "").strip("/")
    tokens: set[str] = set()
    for part in re.split(r"[\s/._\-+]+", s):
        part = _TLD_RE.sub("", part)
        if len(part) >= 3 and part not in _SKIP_TOKENS:
            tokens.add(part)
    if "." in s:
        tokens.add(_base(s))
    else:
        tokens.add(s)
    return {t for t in tokens if t}


def _score(current: str, entry_domain: str) -> float:
    c = current.lower().strip("/")
    e = entry_domain.lower().strip("/")
    if c == e:
        return 1.00

    names = _entry_names(entry_domain)
    page = _page_tokens(current)
    for token in page:
        for name in names:
            if token == name:
                return 0.95
            if token in name or name in token:
                return 0.85

    bc, be = _base(c), _base(e)
    if bc == be:
        return 0.95
    if bc in be or be in bc:
        return 0.82
    if c in e or e in c:
        return 0.72
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
        self._root             = root
        self._win: tk.Toplevel | None = None
        self._b_hwnd           = 0
        self._hide_job: str | None = None
        self._dx = self._dy = 0
        self._visible          = False
        self._dismissed_domain: str | None = None
        self._current_domain: str | None = None

    # ── public ────────────────────────────────────────────────────────────

    def update(
        self,
        domain: str,
        matches: list[tuple[float, SiteEntry]],
        browser_hwnd: int,
        *,
        force: bool = False,
    ) -> None:
        self._b_hwnd = browser_hwnd
        self._current_domain = domain
        if not matches:
            self.hide()
            return
        if not force and self._dismissed_domain == domain:
            return
        self._ensure_window()
        self._rebuild(domain, matches)
        self._place_window()
        self._win.deiconify()
        self._win.lift()
        self._visible = True
        self._reset_timer()

    def hide(self, *, dismissed: bool = False) -> None:
        if dismissed and self._current_domain:
            self._dismissed_domain = self._current_domain
        self._visible = False
        self._cancel_timer()
        if self._win and self._win.winfo_exists():
            self._win.withdraw()

    def show(self) -> None:
        """Re-show after the user dismissed the overlay for the current domain."""
        self._dismissed_domain = None

    def is_visible(self) -> bool:
        return bool(self._visible and self._win and self._win.winfo_exists())

    def destroy(self) -> None:
        self._cancel_timer()
        if self._win and self._win.winfo_exists():
            self._win.destroy()
        self._win = None
        self._visible = False

    # ── window lifecycle ───────────────────────────────────────────────────

    def _ensure_window(self) -> None:
        if self._win and self._win.winfo_exists():
            return
        w = tk.Toplevel(self._root)
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        w.attributes("-alpha", 0.97)
        w.configure(bg=PANEL)
        w.protocol("WM_DELETE_WINDOW", self.hide)
        self._win = w
        w.after(150, lambda: _apply_noactivate(w.winfo_id()))

    def _place_window(self) -> None:
        """Size and position the HUD (requires valid WxH+X+Y — not WIDTH+X+Y)."""
        w = self._win
        w.update_idletasks()
        h = max(w.winfo_reqheight(), 120)
        sw = self._root.winfo_screenwidth()
        x = max(8, sw - HUD_WIDTH - 18)
        w.geometry(f"{HUD_WIDTH}x{h}+{x}+60")

    def _rebuild(self, domain: str, matches: list[tuple[float, SiteEntry]]) -> None:
        for ch in self._win.winfo_children():
            ch.destroy()

        # ── drag-header ────────────────────────────────────────────────────
        hdr = tk.Frame(self._win, bg=BG, cursor="fleur")
        hdr.pack(fill="x")
        hdr.bind("<ButtonPress-1>", self._drag_start)
        hdr.bind("<B1-Motion>",     self._drag_move)

        tk.Label(hdr, text="AutoFill", bg=BG, fg=ACCENT,
                 font=("Segoe UI", 9, "bold"), padx=8, pady=5).pack(side="left")
        tk.Label(hdr, text=f"  {domain}", bg=BG, fg=MUTED,
                 font=("Segoe UI", 8)).pack(side="left")
        tk.Button(hdr, text="✕", bg=BG, fg=MUTED,
                  relief="flat", font=("Segoe UI", 10), bd=0, padx=8, pady=3,
                  activebackground=BG, activeforeground=DANGER,
                  cursor="hand2",
                  command=lambda: self.hide(dismissed=True)).pack(side="right")

        tk.Frame(self._win, bg=BORDER, height=1).pack(fill="x")

        # ── match blocks ───────────────────────────────────────────────────
        for score, ent in matches:
            self._add_match(ent, score)

        # ── footer hint ────────────────────────────────────────────────────
        tk.Frame(self._win, bg=PANEL, height=3).pack()
        tk.Label(self._win,
                 text="Fill = paste into focused browser field  |  auto-hides in 20 s",
                 bg=PANEL, fg=MUTED, font=("Segoe UI", 7),
                 wraplength=HUD_WIDTH - 12, pady=4).pack(fill="x", padx=6)

    def _add_match(self, ent: SiteEntry, score: float) -> None:
        pct = int(score * 100)
        col = GREEN if pct >= 90 else ACCENT if pct >= 72 else MUTED

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

        tk.Button(row, text="Fill",
                  bg=ACCENT, fg="white",
                  relief="flat", font=("Segoe UI", 7, "bold"),
                  activebackground=ACTH, activeforeground="white",
                  cursor="hand2", bd=0, padx=6, pady=1,
                  command=lambda v=val: self._fill(v)).pack(side="right", padx=(2, 0))

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
        1. Copy val to clipboard
        2. Restore browser focus (needed after clicking the overlay)
        3. Inject Ctrl+V into the focused browser field
        """
        self._set_clip(val)
        hwnd = self._b_hwnd

        def _paste() -> None:
            _focus_window(hwnd)
            self._win.after(60, _inject_paste)

        self._win.after(80, _paste)
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

    def _cancel_timer(self) -> None:
        if self._hide_job and self._win and self._win.winfo_exists():
            self._win.after_cancel(self._hide_job)
        self._hide_job = None

    def _reset_timer(self) -> None:
        self._cancel_timer()
        if self._win and self._win.winfo_exists():
            self._hide_job = self._win.after(AUTO_HIDE_MS, self._auto_hide)

    def _auto_hide(self) -> None:
        self._hide_job = None
        self.hide()
