"""VaultPass — offline vault  (passwords · cards · addresses · login groups · images)."""

from __future__ import annotations

import base64
import io
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

try:
    from PIL import Image, ImageTk
    PIL_OK = True
except ImportError:
    PIL_OK = False

from vault_crypto import decrypt_vault, encrypt_vault
from vault_format import SiteEntry, parse_vault_text, serialize_vault_text
from vault_items import (
    AddressEntry, CardEntry, ImageEntry, LoginGroup, parse_preamble,
)
from vault_search import build_matcher, describe_query, score_entry
from browser_watch import BrowserWatcher
from autofill_hud import AutofillHUD, find_matches as hud_find_matches

# ── palette ───────────────────────────────────────────────────────────────────
BG      = "#1e1e2e"
PANEL   = "#252536"
INPUT   = "#313244"
ACCENT  = "#7965c8"
ACTH    = "#6856b8"
FG      = "#cdd6f4"
MUTED   = "#7f849c"
BORDER  = "#45475a"
DANGER  = "#e06c75"
DANGERH = "#c0545e"
GREEN   = "#a6e3a1"
YELLOW  = "#f9e2af"

APP_NAME        = "VaultPass"
CLIP_CLEAR_SECS = 30

TABS = [
    ("passwords", "🔑", "Passwords"),
    ("cards",     "💳", "Cards"),
    ("addresses", "🏠", "Addresses"),
    ("logins",    "🔗", "Login Via"),
    ("images",    "🖼", "Images"),
]

# Template fields for password entries
TEMPLATE_FIELDS: list[tuple[str, bool]] = [
    ("Website Login Using",           False),
    ("Account Type",                  False),
    ("Website Username",              False),
    ("Website Password",              True),
    ("Website Email",                 False),
    ("Website Phone Number",          False),
    ("Acc Sec. — 2FA (Two-Factor)",   False),
    ("Acc Sec. — Phrase/Seed",        True),
    ("Acc Sec. — Linked Accounts",    False),
    ("Acc Sec. — Extended Recovery",  True),
    ("Add. Data. — Slot A",           False),
    ("Add. Data. — Slot B",           False),
    ("Add. Data. — Slot C",           False),
]
_SENSITIVE = ("password", "phrase", "seed", "recovery", "secret", "token", "key",
              "cvv", "pin", "number")
_NULL_VALS = frozenset({"NULL", "NULLAAA", "NULLBBB", "NULLCCC", "NULLDDD", ""})

MAX_IMAGE_KB = 1024   # warn above this


def _is_sensitive(key: str) -> bool:
    k = key.lower()
    return any(s in k for s in _SENSITIVE)


def default_vault_path() -> Path:
    base = (
        Path(sys.executable).resolve().parent
        if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parent
    )
    old_path = base / "vault.vpm"
    new_path = base / "!vault.vpm"
    # Migrate: keep old file if it exists and the new name hasn't been created yet
    if old_path.exists() and not new_path.exists():
        return old_path
    return new_path


def _safe_attr(key: str) -> str:
    return re.sub(r"\W+", "_", key)


import re as _re_module
re = _re_module   # keep short alias


# ── theme ─────────────────────────────────────────────────────────────────────

def apply_theme(root: tk.Tk) -> None:
    root.configure(bg=BG)
    s = ttk.Style(root)
    s.theme_use("clam")
    s.configure(".", background=BG, foreground=FG,
                troughcolor=PANEL, focuscolor=ACCENT,
                bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER,
                relief="flat")
    s.configure("TFrame",         background=BG)
    s.configure("Panel.TFrame",   background=PANEL)
    s.configure("TLabel",         background=BG, foreground=FG, font=("Segoe UI", 10))
    s.configure("Title.TLabel",   background=BG, foreground=FG, font=("Segoe UI", 18, "bold"))
    s.configure("Sub.TLabel",     background=BG, foreground=MUTED, font=("Segoe UI", 9))
    s.configure("TEntry",
        fieldbackground=INPUT, foreground=FG, insertcolor=FG,
        bordercolor=BORDER, padding=(6, 4), font=("Segoe UI", 10))
    s.map("TEntry", bordercolor=[("focus", ACCENT)])
    s.configure("TButton",
        background=PANEL, foreground=FG, bordercolor=BORDER,
        padding=(10, 5), font=("Segoe UI", 10))
    s.map("TButton", background=[("active", BORDER)])
    s.configure("Accent.TButton",
        background=ACCENT, foreground="white", bordercolor=ACCENT, padding=(10, 5))
    s.map("Accent.TButton", background=[("active", ACTH)])
    s.configure("Danger.TButton",
        background=DANGER, foreground="white", bordercolor=DANGER, padding=(10, 5))
    s.map("Danger.TButton", background=[("active", DANGERH)])
    s.configure("Small.TButton",
        background=PANEL, foreground=FG, bordercolor=BORDER,
        padding=(5, 2), font=("Segoe UI", 8))
    s.map("Small.TButton", background=[("active", ACCENT)])
    s.configure("Treeview",
        background=PANEL, foreground=FG, fieldbackground=PANEL,
        bordercolor=BORDER, rowheight=28, font=("Segoe UI", 10))
    s.configure("Treeview.Heading",
        background=BG, foreground=MUTED, font=("Segoe UI", 9))
    s.map("Treeview", background=[("selected", ACCENT)], foreground=[("selected", "white")])
    s.configure("TScrollbar",
        background=PANEL, troughcolor=BG, bordercolor=BG,
        arrowcolor=MUTED, gripcount=0, width=8)
    s.configure("TLabelframe",       background=PANEL, bordercolor=BORDER)
    s.configure("TLabelframe.Label", background=PANEL, foreground=MUTED, font=("Segoe UI", 9))


# ── shared detail helpers ─────────────────────────────────────────────────────

def _detail_btn(parent: tk.Widget, text: str, cmd, bg: str = ACCENT) -> tk.Button:
    hover = ACTH if bg == ACCENT else DANGERH
    return tk.Button(parent, text=text, bg=bg, fg="white",
                     relief="flat", font=("Segoe UI", 9),
                     activebackground=hover, activeforeground="white",
                     cursor="hand2", bd=0, padx=10, pady=4, command=cmd)


def _copy_btn(parent: tk.Widget, val: str, copy_fn) -> tk.Button:
    return tk.Button(parent, text="Copy", bg=INPUT, fg=FG,
                     relief="flat", font=("Segoe UI", 8),
                     activebackground=ACCENT, activeforeground="white",
                     cursor="hand2", bd=0, padx=8, pady=2,
                     command=lambda: copy_fn(val))


def _field_row(parent: tk.Widget, key: str, val: str, copy_fn,
               show_copy: bool = True, secret: bool = False,
               shows_dict: dict | None = None) -> None:
    """Render one key/value row in the detail panel."""
    row = tk.Frame(parent, bg=PANEL)
    row.pack(fill="x", pady=3)
    tk.Label(row, text=key + ":", bg=PANEL, fg=MUTED,
             font=("Segoe UI", 9), width=24, anchor="w").pack(side="left")
    disp = ("••••••••" if secret else val)
    lbl = tk.Label(row, text=disp, bg=PANEL, fg=FG,
                   font=("Consolas" if secret else "Segoe UI", 10), anchor="w",
                   wraplength=380)
    lbl.pack(side="left", fill="x", expand=True)
    if secret and shows_dict is not None:
        def _toggle(k=key, lb=lbl, v=val) -> None:
            shows_dict[k] = not shows_dict.get(k, False)
            lb.config(text=v if shows_dict[k] else "••••••••")
        tk.Button(row, text="👁", bg=PANEL, fg=MUTED,
                  relief="flat", font=("Segoe UI", 9),
                  activebackground=BORDER, activeforeground=FG,
                  cursor="hand2", bd=0, padx=4,
                  command=_toggle).pack(side="right", padx=(0, 2))
    if show_copy and val not in _NULL_VALS:
        _copy_btn(row, val, copy_fn).pack(side="right")


# ── dialogs ───────────────────────────────────────────────────────────────────

class _ScrollDialog(tk.Toplevel):
    """Base dialog with a scrollable inner frame."""
    def __init__(self, parent: tk.Tk, title: str, w: int = 500, h: int = 560) -> None:
        super().__init__(parent)
        self.configure(bg=BG)
        self.title(title)
        self.geometry(f"{w}x{h}")
        self.minsize(380, 400)
        self.grab_set()
        self.result: Any = None
        # scrollable body
        container = ttk.Frame(self, style="Panel.TFrame", padding=(12, 8))
        container.pack(fill="both", expand=True)
        canvas = tk.Canvas(container, bg=PANEL, highlightthickness=0)
        sb = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(canvas, bg=PANEL)
        win = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>",
                   lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfig(win, width=e.width))
        canvas.bind("<MouseWheel>",
                    lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))
        self.inner = inner
        # button bar
        self._bar = ttk.Frame(self, padding=(12, 6))
        self._bar.pack(fill="x")

    def _add_save_cancel(self, save_cmd) -> None:
        ttk.Separator(self, orient="horizontal").pack(fill="x")
        ttk.Button(self._bar, text="Cancel", command=self.destroy).pack(
            side="right", padx=(6, 0))
        ttk.Button(self._bar, text="Save", style="Accent.TButton",
                   command=save_cmd).pack(side="right")

    def _row(self, label: str, var: tk.StringVar,
             show: str = "", width: int = 38, parent=None) -> ttk.Entry:
        p = parent or self.inner
        tk.Label(p, text=label, bg=PANEL, fg=MUTED,
                 font=("Segoe UI", 9)).pack(anchor="w", pady=(6, 1))
        e = ttk.Entry(p, textvariable=var, show=show, width=width)
        e.pack(fill="x", padx=2)
        return e

    def _dropdown(self, label: str, var: tk.StringVar, choices: list[str]) -> None:
        tk.Label(self.inner, text=label, bg=PANEL, fg=MUTED,
                 font=("Segoe UI", 9)).pack(anchor="w", pady=(6, 1))
        cb = ttk.Combobox(self.inner, textvariable=var,
                          values=choices, state="readonly")
        cb.pack(fill="x", padx=2)


class EntryDialog(_ScrollDialog):
    """Add / edit a password SiteEntry."""

    def __init__(self, parent: tk.Tk, existing: SiteEntry | None = None) -> None:
        super().__init__(parent, "Edit entry" if existing else "New entry", 520, 620)
        self._shows: dict[str, bool] = {}
        self._sec_entries: dict[str, ttk.Entry] = {}
        self._field_vars: list[tuple[str, tk.StringVar]] = []
        self._build(existing)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _build(self, existing: SiteEntry | None) -> None:
        tk.Label(self.inner, text="Domain / Site name",
                 bg=PANEL, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w", pady=(4, 1))
        self.domain_var = tk.StringVar(value=existing.domain if existing else "")
        de = ttk.Entry(self.inner, textvariable=self.domain_var)
        de.pack(fill="x", padx=2, pady=(0, 6)); de.focus()

        existing_dict = dict(existing.lines) if existing else {}
        last_section: str | None = None

        for key, is_secret in TEMPLATE_FIELDS:
            section = key.split(" — ")[0] if " — " in key else None
            display = key.split(" — ")[1] if " — " in key else key

            if section and section != last_section:
                sf = tk.Frame(self.inner, bg=PANEL)
                sf.pack(fill="x", pady=(10, 2))
                tk.Frame(sf, bg=ACCENT, height=1).pack(fill="x")
                tk.Label(sf, text=section, bg=PANEL, fg=MUTED,
                         font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(3, 0))
                last_section = section

            tk.Label(self.inner, text=display, bg=PANEL, fg=MUTED,
                     font=("Segoe UI", 9)).pack(anchor="w", pady=(5, 1))
            er = tk.Frame(self.inner, bg=PANEL)
            er.pack(fill="x")
            var = tk.StringVar(value=existing_dict.get(key, "NULL"))
            ent = ttk.Entry(er, textvariable=var,
                            show="•" if is_secret else "")
            ent.pack(side="left", fill="x", expand=True, padx=2)
            if is_secret:
                self._shows[key] = False
                self._sec_entries[key] = ent
                ttk.Button(er, text="👁", style="Small.TButton", width=3,
                           command=lambda k=key: self._toggle(k)).pack(
                    side="left", padx=(4, 0))
                # 🎲 generate button — fills this field with a fresh password
                ttk.Button(er, text="🎲", style="Small.TButton", width=3,
                           command=lambda v=var: self._open_gen(v)).pack(
                    side="left", padx=(2, 0))
            self._field_vars.append((key, var))

        if existing:
            template_keys = {k for k, _ in TEMPLATE_FIELDS}
            for key, val in existing.lines:
                if key not in template_keys:
                    tk.Label(self.inner, text=f"[custom] {key}",
                             bg=PANEL, fg=MUTED,
                             font=("Segoe UI", 9)).pack(anchor="w", pady=(5, 1))
                    var = tk.StringVar(value=val)
                    ttk.Entry(self.inner, textvariable=var).pack(fill="x", padx=2)
                    self._field_vars.append((key, var))

        self._add_save_cancel(self._save)

    def _toggle(self, key: str) -> None:
        self._shows[key] = not self._shows.get(key, False)
        self._sec_entries[key].configure(show="" if self._shows[key] else "•")

    def _open_gen(self, var: tk.StringVar) -> None:
        def _use(pw: str) -> None:
            var.set(pw)
        PasswordGenDialog(self, on_use=_use)

    def _save(self) -> None:
        domain = self.domain_var.get().strip()
        if not domain:
            messagebox.showwarning("VaultPass", "Domain is required.", parent=self)
            return
        lines = [(k, v.get().strip() or "NULL") for k, v in self._field_vars]
        self.result = SiteEntry(domain=domain, lines=lines)
        self.destroy()


class CardDialog(_ScrollDialog):
    """Add / edit a CardEntry."""

    def __init__(self, parent: tk.Tk, existing: CardEntry | None = None) -> None:
        super().__init__(parent, "Edit card" if existing else "New card", 460, 480)
        e = existing
        self._vars: dict[str, tk.StringVar] = {
            "name":      tk.StringVar(value=e.name      if e else ""),
            "card_type": tk.StringVar(value=e.card_type if e else "Debit"),
            "number":    tk.StringVar(value=e.number    if e else ""),
            "expiry":    tk.StringVar(value=e.expiry    if e else ""),
            "cvv":       tk.StringVar(value=e.cvv       if e else ""),
            "pin":       tk.StringVar(value=e.pin       if e else ""),
            "bank":      tk.StringVar(value=e.bank      if e else ""),
            "notes":     tk.StringVar(value=e.notes     if e else ""),
        }
        self._row("Card label (nickname)",  self._vars["name"])
        self._dropdown("Card type", self._vars["card_type"],
                       ["Debit", "Credit", "Prepaid", "Gift", "Other"])
        self._row("Card number",            self._vars["number"], show="•")
        self._row("Expiry  (MM/YY)",        self._vars["expiry"])
        self._row("CVV / Security code",    self._vars["cvv"],    show="•")
        self._row("PIN",                    self._vars["pin"],    show="•")
        self._row("Bank / Issuer",          self._vars["bank"])
        self._row("Notes",                  self._vars["notes"])
        self._add_save_cancel(self._save)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _save(self) -> None:
        name = self._vars["name"].get().strip()
        if not name:
            messagebox.showwarning("VaultPass", "Card label is required.", parent=self)
            return
        self.result = CardEntry(
            name=name,
            card_type=self._vars["card_type"].get(),
            number=self._vars["number"].get().strip().replace(" ", "").replace("-", ""),
            expiry=self._vars["expiry"].get().strip(),
            cvv=self._vars["cvv"].get().strip(),
            pin=self._vars["pin"].get().strip(),
            bank=self._vars["bank"].get().strip(),
            notes=self._vars["notes"].get().strip(),
        )
        self.destroy()


class AddressDialog(_ScrollDialog):
    """Add / edit an AddressEntry."""

    def __init__(self, parent: tk.Tk, existing: AddressEntry | None = None) -> None:
        super().__init__(parent, "Edit address" if existing else "New address", 460, 460)
        e = existing
        self._vars: dict[str, tk.StringVar] = {
            "label":   tk.StringVar(value=e.label   if e else "Home"),
            "line1":   tk.StringVar(value=e.line1   if e else ""),
            "line2":   tk.StringVar(value=e.line2   if e else ""),
            "city":    tk.StringVar(value=e.city    if e else ""),
            "state":   tk.StringVar(value=e.state   if e else ""),
            "zipcode": tk.StringVar(value=e.zipcode if e else ""),
            "country": tk.StringVar(value=e.country if e else ""),
            "notes":   tk.StringVar(value=e.notes   if e else ""),
        }
        self._dropdown("Label", self._vars["label"],
                       ["Home", "Work", "Billing", "Shipping", "Other"])
        self._row("Street address (line 1)",  self._vars["line1"])
        self._row("Apt / Unit / Suite (line 2)", self._vars["line2"])
        self._row("City",    self._vars["city"])
        self._row("State / Province", self._vars["state"])
        self._row("ZIP / Postal code", self._vars["zipcode"])
        self._row("Country", self._vars["country"])
        self._row("Notes",   self._vars["notes"])
        self._add_save_cancel(self._save)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _save(self) -> None:
        line1 = self._vars["line1"].get().strip()
        if not line1:
            messagebox.showwarning("VaultPass", "Street address is required.", parent=self)
            return
        self.result = AddressEntry(
            label=self._vars["label"].get().strip() or "Address",
            line1=line1,
            line2=self._vars["line2"].get().strip(),
            city=self._vars["city"].get().strip(),
            state=self._vars["state"].get().strip(),
            zipcode=self._vars["zipcode"].get().strip(),
            country=self._vars["country"].get().strip(),
            notes=self._vars["notes"].get().strip(),
        )
        self.destroy()


class LoginGroupDialog(_ScrollDialog):
    """Add / edit a LoginGroup."""

    def __init__(self, parent: tk.Tk, existing: LoginGroup | None = None) -> None:
        super().__init__(parent, "Edit login group" if existing else "New login group",
                         480, 480)
        e = existing
        self._via_var   = tk.StringVar(value=e.via   if e else "")
        self._email_var = tk.StringVar(value=e.email if e else "")
        self._notes_var = tk.StringVar(value=e.notes if e else "")
        self._row("Provider / method  (e.g. Apple, Google, Email)",
                  self._via_var)
        self._row("Email / account used", self._email_var)
        tk.Label(self.inner, text="Sites that use this login  (one per line)",
                 bg=PANEL, fg=MUTED, font=("Segoe UI", 9)).pack(
            anchor="w", pady=(8, 1))
        self._sites_txt = tk.Text(self.inner, bg=INPUT, fg=FG,
                                  insertbackground=FG, relief="flat",
                                  font=("Segoe UI", 10), height=10, wrap="word",
                                  bd=0, highlightthickness=1,
                                  highlightbackground=BORDER,
                                  highlightcolor=ACCENT)
        if e:
            self._sites_txt.insert("1.0", "\n".join(e.sites))
        self._sites_txt.pack(fill="x", padx=2)
        self._row("Notes", self._notes_var)
        self._add_save_cancel(self._save)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _save(self) -> None:
        via = self._via_var.get().strip()
        if not via:
            messagebox.showwarning("VaultPass", "Provider name is required.", parent=self)
            return
        raw_sites = self._sites_txt.get("1.0", "end-1c")
        sites = [s.strip() for s in raw_sites.splitlines() if s.strip()]
        self.result = LoginGroup(
            via=via, email=self._email_var.get().strip(),
            sites=sites, notes=self._notes_var.get().strip(),
        )
        self.destroy()


class ImageDialog(_ScrollDialog):
    """Add / edit an ImageEntry (pick file + store base64)."""

    CATEGORIES = ["ID", "Card", "License", "Passport", "Insurance",
                  "Document", "Screenshot", "Other"]

    def __init__(self, parent: tk.Tk, existing: ImageEntry | None = None) -> None:
        super().__init__(parent, "Edit image" if existing else "Add image", 480, 400)
        self._data_b64 = existing.data_b64 if existing else ""
        self._mime     = existing.mime     if existing else "image/png"
        e = existing
        self._name_var  = tk.StringVar(value=e.name     if e else "")
        self._cat_var   = tk.StringVar(value=e.category if e else "ID")
        self._notes_var = tk.StringVar(value=e.notes    if e else "")

        self._row("Image name / label", self._name_var)
        self._dropdown("Category", self._cat_var, self.CATEGORIES)

        # pick file button + status label
        pick_row = tk.Frame(self.inner, bg=PANEL)
        pick_row.pack(fill="x", pady=(8, 2))
        tk.Button(pick_row, text="📂 Pick image file…",
                  bg=ACCENT, fg="white", relief="flat",
                  font=("Segoe UI", 9), activebackground=ACTH,
                  cursor="hand2", bd=0, padx=10, pady=4,
                  command=self._pick_file).pack(side="left")
        self._file_lbl = tk.Label(pick_row,
                                  text="(loaded)" if self._data_b64 else "(no file)",
                                  bg=PANEL, fg=MUTED, font=("Segoe UI", 8))
        self._file_lbl.pack(side="left", padx=(8, 0))

        # preview
        self._preview_lbl = tk.Label(self.inner, bg=PANEL)
        self._preview_lbl.pack(pady=(4, 0))
        if self._data_b64:
            self._show_preview()

        self._row("Notes", self._notes_var)
        self._add_save_cancel(self._save)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _pick_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Pick image",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.gif *.bmp *.webp"),
                       ("All", "*.*")],
            parent=self,
        )
        if not path:
            return
        p = Path(path)
        raw = p.read_bytes()
        kb = len(raw) // 1024
        if kb > MAX_IMAGE_KB:
            if not messagebox.askyesno(
                "Large image",
                f"Image is {kb} KB.  It will be stored inside the encrypted vault.\n"
                "Continue?",
                parent=self,
            ):
                return
        # determine mime
        ext = p.suffix.lower()
        self._mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                      ".gif": "image/gif",  ".bmp": "image/bmp",
                      ".webp": "image/webp"}.get(ext, "image/png")
        if not self._name_var.get():
            self._name_var.set(p.stem)
        self._data_b64 = base64.b64encode(raw).decode("ascii")
        self._file_lbl.config(text=f"{p.name}  ({kb} KB)", fg=GREEN)
        self._show_preview()

    def _show_preview(self) -> None:
        if not self._data_b64:
            return
        try:
            raw  = base64.b64decode(self._data_b64)
            if PIL_OK:
                img = Image.open(io.BytesIO(raw))
                img.thumbnail((320, 180))
                self._photo = ImageTk.PhotoImage(img)
            else:
                self._photo = tk.PhotoImage(data=self._data_b64)
            self._preview_lbl.config(image=self._photo)
        except Exception:
            self._preview_lbl.config(text="(preview unavailable)", fg=MUTED)

    def _save(self) -> None:
        name = self._name_var.get().strip()
        if not name:
            messagebox.showwarning("VaultPass", "Image name is required.", parent=self)
            return
        if not self._data_b64:
            messagebox.showwarning("VaultPass", "Please pick an image file.", parent=self)
            return
        self.result = ImageEntry(
            name=name, category=self._cat_var.get(),
            mime=self._mime, data_b64=self._data_b64,
            notes=self._notes_var.get().strip(),
        )
        self.destroy()


class PasswordGenDialog(tk.Toplevel):
    """
    Standalone password generator built on the pwdgen.py algorithm.

    Parameters
    ----------
    on_use : optional callable(str) — if supplied, a "✓ Use" button appears
             that calls on_use(password) and closes the dialog.
    """

    HISTORY_MAX = 8

    def __init__(self, parent: tk.Widget, on_use=None) -> None:
        super().__init__(parent)
        self.configure(bg=BG)
        self.title("Password Generator")
        self.geometry("460x560")
        self.resizable(False, True)
        self.grab_set()
        self._on_use      = on_use
        self._history:  list[str] = []
        self._current   = ""
        self._show_pw   = False
        self._build()
        self._generate()
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    # ── build ─────────────────────────────────────────────────────────────

    def _build(self) -> None:
        # ── password display box ───────────────────────────────────────────
        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", padx=16, pady=(14, 4))

        tk.Label(top, text="Generated password", bg=BG, fg=MUTED,
                 font=("Segoe UI", 9)).pack(anchor="w")

        pw_wrap = tk.Frame(top, bg=INPUT, highlightthickness=1,
                           highlightbackground=BORDER, highlightcolor=ACCENT)
        pw_wrap.pack(fill="x", pady=(4, 0))

        self._pw_var = tk.StringVar()
        self._pw_entry = tk.Entry(
            pw_wrap, textvariable=self._pw_var,
            bg=INPUT, fg=GREEN, insertbackground=FG,
            relief="flat", font=("Consolas", 13, "bold"),
            show="•", state="readonly", readonlybackground=INPUT,
            bd=0, highlightthickness=0)
        self._pw_entry.pack(side="left", fill="x", expand=True, ipady=10, padx=(8, 0))

        tk.Button(pw_wrap, text="👁", bg=INPUT, fg=MUTED,
                  relief="flat", font=("Segoe UI", 11),
                  activebackground=INPUT, activeforeground=FG,
                  cursor="hand2", bd=0, padx=6,
                  command=self._toggle_show).pack(side="right")

        # strength bar
        self._strength_var = tk.StringVar(value="")
        self._strength_lbl = tk.Label(top, textvariable=self._strength_var,
                                      bg=BG, font=("Segoe UI", 8))
        self._strength_lbl.pack(anchor="w", pady=(4, 0))

        # ── action row ─────────────────────────────────────────────────────
        act = tk.Frame(top, bg=BG)
        act.pack(fill="x", pady=(8, 4))
        tk.Button(act, text="🔄 Regenerate", bg=ACCENT, fg="white",
                  relief="flat", font=("Segoe UI", 9, "bold"),
                  activebackground=ACTH, activeforeground="white",
                  cursor="hand2", bd=0, padx=12, pady=5,
                  command=self._generate).pack(side="left")
        tk.Button(act, text="Copy", bg=INPUT, fg=FG,
                  relief="flat", font=("Segoe UI", 9),
                  activebackground=BORDER, activeforeground=FG,
                  cursor="hand2", bd=0, padx=12, pady=5,
                  command=lambda: self._copy_val(self._current)).pack(
            side="left", padx=(8, 0))
        if self._on_use:
            tk.Button(act, text="✓ Use this password", bg=GREEN, fg=BG,
                      relief="flat", font=("Segoe UI", 9, "bold"),
                      activebackground="#85c485", activeforeground=BG,
                      cursor="hand2", bd=0, padx=12, pady=5,
                      command=lambda: self._use(self._current)).pack(side="right")

        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", padx=16, pady=(4, 0))

        # ── options panel ──────────────────────────────────────────────────
        opts = tk.Frame(self, bg=BG)
        opts.pack(fill="x", padx=16, pady=8)

        # length slider
        len_row = tk.Frame(opts, bg=BG)
        len_row.pack(fill="x", pady=(0, 6))
        tk.Label(len_row, text="Length", bg=BG, fg=MUTED,
                 font=("Segoe UI", 9), width=12, anchor="w").pack(side="left")
        self._len_var = tk.IntVar(value=18)
        self._len_lbl = tk.Label(len_row, text="18", bg=BG, fg=FG,
                                  font=("Segoe UI", 9, "bold"), width=3)
        self._len_lbl.pack(side="right")
        ttk.Scale(len_row, from_=6, to=64, variable=self._len_var,
                  orient="horizontal",
                  command=lambda _: self._on_opt()).pack(
            side="left", fill="x", expand=True, padx=(8, 0))

        # character-type checkboxes
        self._use_upper   = tk.BooleanVar(value=True)
        self._use_lower   = tk.BooleanVar(value=True)
        self._use_digits  = tk.BooleanVar(value=True)
        self._use_symbols = tk.BooleanVar(value=True)
        cb_row = tk.Frame(opts, bg=BG)
        cb_row.pack(fill="x", pady=(0, 6))
        for label, var in [
            ("A-Z",  self._use_upper),
            ("a-z",  self._use_lower),
            ("0-9",  self._use_digits),
            ("!@#",  self._use_symbols),
        ]:
            tk.Checkbutton(cb_row, text=label, variable=var,
                           bg=BG, fg=FG, selectcolor=INPUT,
                           activebackground=BG, activeforeground=FG,
                           font=("Segoe UI", 9), cursor="hand2",
                           command=self._on_opt).pack(side="left", padx=(0, 12))

        # exclude characters
        ex_row = tk.Frame(opts, bg=BG)
        ex_row.pack(fill="x", pady=(0, 6))
        tk.Label(ex_row, text="Exclude chars", bg=BG, fg=MUTED,
                 font=("Segoe UI", 9), width=12, anchor="w").pack(side="left")
        self._excl_var = tk.StringVar(value="")
        tk.Entry(ex_row, textvariable=self._excl_var,
                 bg=INPUT, fg=FG, insertbackground=FG,
                 relief="flat", font=("Consolas", 10), width=20,
                 bd=0, highlightthickness=1,
                 highlightbackground=BORDER,
                 highlightcolor=ACCENT).pack(side="left", padx=(8, 0), ipady=3)
        tk.Label(ex_row, text="e.g. 0O1lI", bg=BG, fg=MUTED,
                 font=("Segoe UI", 8)).pack(side="left", padx=(6, 0))
        self._excl_var.trace_add("write", lambda *_: self._on_opt())

        # presets
        pre_row = tk.Frame(opts, bg=BG)
        pre_row.pack(fill="x")
        tk.Label(pre_row, text="Presets", bg=BG, fg=MUTED,
                 font=("Segoe UI", 9), width=12, anchor="w").pack(side="left")
        for name, cfg in [
            ("Strong 18",   dict(n=18, U=True,  L=True,  D=True,  S=True)),
            ("Alphanum 14", dict(n=14, U=True,  L=True,  D=True,  S=False)),
            ("PIN 6",       dict(n=6,  U=False, L=False, D=True,  S=False)),
            ("Symbols 24",  dict(n=24, U=True,  L=True,  D=True,  S=True)),
        ]:
            tk.Button(pre_row, text=name, bg=PANEL, fg=FG,
                      relief="flat", font=("Segoe UI", 8),
                      activebackground=ACCENT, activeforeground="white",
                      cursor="hand2", bd=0, padx=6, pady=2,
                      command=lambda c=cfg: self._preset(c)).pack(
                side="left", padx=(6, 0))

        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", padx=16, pady=(4, 0))

        # ── history ────────────────────────────────────────────────────────
        hist_outer = tk.Frame(self, bg=BG)
        hist_outer.pack(fill="both", expand=True, padx=16, pady=(8, 10))
        tk.Label(hist_outer, text="Recent  (click to copy or use)",
                 bg=BG, fg=MUTED, font=("Segoe UI", 8)).pack(anchor="w")
        self._hist_frame = tk.Frame(hist_outer, bg=BG)
        self._hist_frame.pack(fill="x", pady=(4, 0))

    # ── generation core (same algorithm as pwdgen.py) ─────────────────────

    def _generate(self, add_to_history: bool = True) -> None:
        import secrets as _sec, string as _str

        length  = self._len_var.get()
        exclude = self._excl_var.get()

        def filt(chars: str) -> str:
            return "".join(c for c in chars if c not in exclude)

        pools:     list[str] = []
        guaranteed: list[str] = []

        for flag, chars in [
            (self._use_upper.get(),   _str.ascii_uppercase),
            (self._use_lower.get(),   _str.ascii_lowercase),
            (self._use_digits.get(),  _str.digits),
            (self._use_symbols.get(), _str.punctuation),
        ]:
            if flag:
                c = filt(chars)
                if c:
                    pools.append(c)
                    guaranteed.append(_sec.choice(c))

        if not pools:
            self._pw_var.set("(select a character type)")
            self._strength_var.set("")
            return

        pool      = "".join(pools)
        remaining = [_sec.choice(pool) for _ in range(max(0, length - len(guaranteed)))]
        final     = guaranteed + remaining
        _sec.SystemRandom().shuffle(final)
        pw = "".join(final)

        self._current = pw
        self._pw_var.set(pw)
        self._pw_entry.config(show="" if self._show_pw else "•")
        self._update_strength(pw)

        if add_to_history and pw:
            self._history.insert(0, pw)
            self._history = self._history[:self.HISTORY_MAX]
            self._rebuild_history()

    def _on_opt(self) -> None:
        v = self._len_var.get()
        self._len_lbl.config(text=str(v))
        self._generate(add_to_history=False)

    def _preset(self, cfg: dict) -> None:
        self._len_var.set(cfg["n"])
        self._use_upper.set(cfg["U"])
        self._use_lower.set(cfg["L"])
        self._use_digits.set(cfg["D"])
        self._use_symbols.set(cfg["S"])
        self._len_lbl.config(text=str(cfg["n"]))
        self._generate()

    # ── strength meter ─────────────────────────────────────────────────────

    def _update_strength(self, pw: str) -> None:
        if not pw or "(select" in pw:
            self._strength_var.set("")
            return
        score = sum([
            len(pw) >= 12,
            len(pw) >= 18,
            any(c.isupper()  for c in pw),
            any(c.islower()  for c in pw),
            any(c.isdigit()  for c in pw),
            any(not c.isalnum() for c in pw),
        ])
        label, col = [
            ("Very Weak",   DANGER),
            ("Weak",        DANGER),
            ("Fair",        YELLOW),
            ("Moderate",    YELLOW),
            ("Strong",      GREEN),
            ("Strong",      GREEN),
            ("Very Strong", GREEN),
        ][min(score, 6)]
        bar = "█" * score + "░" * (6 - score)
        self._strength_var.set(f"Strength  {bar}  {label}  ({len(pw)} chars)")
        self._strength_lbl.config(fg=col)

    # ── history ────────────────────────────────────────────────────────────

    def _rebuild_history(self) -> None:
        for w in self._hist_frame.winfo_children():
            w.destroy()
        for pw in self._history:
            row = tk.Frame(self._hist_frame, bg=BG)
            row.pack(fill="x", pady=1)
            disp = pw if self._show_pw else "••••••••"
            tk.Label(row, text=disp, bg=BG, fg=MUTED,
                     font=("Consolas", 8), width=28, anchor="w").pack(side="left")
            tk.Button(row, text="Copy", bg=PANEL, fg=FG,
                      relief="flat", font=("Segoe UI", 7),
                      activebackground=ACCENT, activeforeground="white",
                      cursor="hand2", bd=0, padx=6, pady=1,
                      command=lambda v=pw: self._copy_val(v)).pack(
                side="left", padx=(4, 0))
            if self._on_use:
                tk.Button(row, text="Use", bg=PANEL, fg=FG,
                          relief="flat", font=("Segoe UI", 7),
                          activebackground=GREEN, activeforeground=BG,
                          cursor="hand2", bd=0, padx=6, pady=1,
                          command=lambda v=pw: self._use(v)).pack(
                    side="left", padx=(2, 0))

    def _toggle_show(self) -> None:
        self._show_pw = not self._show_pw
        self._pw_entry.config(show="" if self._show_pw else "•")
        self._rebuild_history()

    def _copy_val(self, val: str) -> None:
        if val and "(select" not in val:
            self.clipboard_clear()
            self.clipboard_append(val)
            self.update()

    def _use(self, val: str) -> None:
        if val and self._on_use and "(select" not in val:
            self._on_use(val)
            self.destroy()


class ChangePwDialog(tk.Toplevel):
    def __init__(self, parent: tk.Tk, current_pw: str) -> None:
        super().__init__(parent)
        self.configure(bg=BG)
        self.title("Change master password")
        self.geometry("400x260")
        self.resizable(False, False)
        self.grab_set()
        self.result: str | None = None
        self._cpw = current_pw
        self._build()

    def _build(self) -> None:
        f = ttk.Frame(self, padding=20); f.pack(fill="both", expand=True)
        ttk.Label(f, text="Current password").pack(anchor="w")
        self._cur = ttk.Entry(f, show="•"); self._cur.pack(fill="x", pady=(2, 12))
        ttk.Label(f, text="New password").pack(anchor="w")
        self._new = ttk.Entry(f, show="•"); self._new.pack(fill="x", pady=(2, 4))
        ttk.Label(f, text="Confirm new password").pack(anchor="w")
        self._conf = ttk.Entry(f, show="•"); self._conf.pack(fill="x", pady=(2, 16))
        row = ttk.Frame(f); row.pack(fill="x")
        ttk.Button(row, text="Cancel", command=self.destroy).pack(side="right", padx=(6,0))
        ttk.Button(row, text="Change", style="Accent.TButton",
                   command=self._change).pack(side="right")
        self._cur.focus()

    def _change(self) -> None:
        if self._cur.get() != self._cpw:
            messagebox.showerror("VaultPass", "Current password incorrect.", parent=self); return
        pw = self._new.get()
        if len(pw) < 4:
            messagebox.showwarning("VaultPass", "New password must be ≥ 4 chars.", parent=self); return
        if pw != self._conf.get():
            messagebox.showerror("VaultPass", "Passwords do not match.", parent=self); return
        self.result = pw; self.destroy()


# ── main app ──────────────────────────────────────────────────────────────────

class VaultApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        apply_theme(self)
        self.title(APP_NAME)
        self.geometry("1060x700")
        self.minsize(800, 540)

        self._vault_path  = default_vault_path()
        self._master_pw: str | None = None
        self._preamble    = ""

        # data stores per tab
        self._passwords: list[SiteEntry]    = []
        self._cards:     list[CardEntry]    = []
        self._addresses: list[AddressEntry] = []
        self._logins:    list[LoginGroup]   = []
        self._images:    list[ImageEntry]   = []

        self._active_tab  = "passwords"
        self._filtered:   list[int] = []
        self._sel_idx:    int = -1
        self._sort_mode   = "az"
        self._shows:      dict[str, bool] = {}
        self._clip_job:   str | None = None

        self._tab_btns:   dict[str, tk.Button] = {}
        self._listboxes:  dict[str, tk.Listbox] = {}
        self._list_frames: dict[str, tk.Frame]  = {}

        # autofill subsystem (created on first unlock)
        self._watcher: BrowserWatcher | None = None
        self._hud:     AutofillHUD    | None = None
        self._autofill_enabled = True

        self._build_menu()
        self._unlock_frame = self._build_unlock_screen()
        self._main_frame   = self._build_main_screen()
        self._show_unlock()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── properties ────────────────────────────────────────────────────────

    def _store(self) -> list:
        """Return the list for the active tab."""
        return {
            "passwords": self._passwords,
            "cards":     self._cards,
            "addresses": self._addresses,
            "logins":    self._logins,
            "images":    self._images,
        }[self._active_tab]

    # ── menu ──────────────────────────────────────────────────────────────

    def _build_menu(self) -> None:
        bar = tk.Menu(self, bg=PANEL, fg=FG, activebackground=ACCENT,
                      activeforeground="white", tearoff=0)
        f = tk.Menu(bar, bg=PANEL, fg=FG, activebackground=ACCENT,
                    activeforeground="white", tearoff=0)
        f.add_command(label="Open vault…",             command=self._menu_open)
        f.add_command(label="Import plain text…",      command=self._import_plain)
        f.add_command(label="Export plain text…",      command=self._export_plain)
        f.add_separator()
        f.add_command(label="🎲 Password Generator…  Ctrl+G",
                      command=self._open_gen_standalone)
        f.add_separator()
        f.add_command(label="Change master password…", command=self._change_password)
        f.add_separator()
        f.add_command(label="Exit",                    command=self._on_close)
        bar.add_cascade(label="File", menu=f)
        h = tk.Menu(bar, bg=PANEL, fg=FG, activebackground=ACCENT,
                    activeforeground="white", tearoff=0)
        h.add_command(label="About", command=self._about)
        bar.add_cascade(label="Help", menu=h)
        self.config(menu=bar)
        self.bind_all("<Control-s>", lambda _e: self._autosave())
        self.bind_all("<Control-n>", lambda _e: self._add_item())
        self.bind_all("<Control-f>", lambda _e: self._focus_search())
        self.bind_all("<Control-g>", lambda _e: self._open_gen_standalone())
        self.bind_all("<Escape>",    lambda _e: self._on_escape())

    # ── unlock screen ─────────────────────────────────────────────────────

    def _build_unlock_screen(self) -> ttk.Frame:
        f = ttk.Frame(self)
        c = ttk.Frame(f)
        c.place(relx=0.5, rely=0.5, anchor="center")
        ttk.Label(c, text="🔒  VaultPass", style="Title.TLabel").pack(pady=(0, 4))
        ttk.Label(c, text="Your offline encrypted vault",
                  style="Sub.TLabel").pack(pady=(0, 24))
        ttk.Label(c, text="Master password").pack(anchor="w")
        self._pw_var = tk.StringVar()
        pw = ttk.Entry(c, textvariable=self._pw_var, show="•", width=36)
        pw.pack(fill="x", pady=(4, 4))
        pw.bind("<Return>", lambda _e: self._try_unlock())
        self._pw_entry_ref = pw
        self._pw_hint = ttk.Label(c, text="", style="Sub.TLabel", foreground=DANGER)
        self._pw_hint.pack(anchor="w", pady=(0, 12))
        ttk.Button(c, text="Unlock", style="Accent.TButton",
                   command=self._try_unlock).pack(anchor="w")
        ttk.Label(c, text=f"\nVault: {self._vault_path}",
                  style="Sub.TLabel").pack(anchor="w", pady=(16, 0))
        return f

    # ── main screen ───────────────────────────────────────────────────────

    def _build_main_screen(self) -> ttk.Frame:
        root = ttk.Frame(self)

        # toolbar
        tb = tk.Frame(root, bg=PANEL, height=46)
        tb.pack(fill="x"); tb.pack_propagate(False)
        tk.Label(tb, text="  🔒 VaultPass", bg=PANEL, fg=FG,
                 font=("Segoe UI", 13, "bold")).pack(side="left", padx=(8, 0))
        ttk.Button(tb, text="🎲 Gen PW", command=self._open_gen_standalone,
                   style="Small.TButton").pack(side="right", padx=4, pady=6)

        self._autofill_btn_var = tk.StringVar(value="AutoFill ON")
        self._autofill_btn = ttk.Button(
            tb, textvariable=self._autofill_btn_var,
            command=self._toggle_autofill, style="Small.TButton")
        self._autofill_btn.pack(side="right", padx=4, pady=6)

        for text, cmd in [
            ("Lock",       self._lock),
            ("Change PW",  self._change_password),
            ("Export txt", self._export_plain),
            ("Import txt", self._import_plain),
        ]:
            ttk.Button(tb, text=text, command=cmd,
                       style="Small.TButton").pack(side="right", padx=4, pady=6)

        tk.Frame(root, bg=BORDER, height=1).pack(fill="x")

        body = ttk.Frame(root)
        body.pack(fill="both", expand=True)

        # ── left panel ────────────────────────────────────────────────────
        left = tk.Frame(body, bg=PANEL, width=240)
        left.pack(side="left", fill="y"); left.pack_propagate(False)

        # tab buttons
        tab_bar = tk.Frame(left, bg=PANEL)
        tab_bar.pack(fill="x", pady=(6, 0), padx=6)
        for tid, icon, label in TABS:
            btn = tk.Button(
                tab_bar, text=f"{icon}\n{label}",
                bg=PANEL, fg=MUTED,
                relief="flat", font=("Segoe UI", 7),
                activebackground=INPUT, activeforeground=FG,
                cursor="hand2", bd=0, padx=2, pady=4, width=6,
                command=lambda t=tid: self._switch_tab(t),
            )
            btn.pack(side="left", expand=True, fill="x")
            self._tab_btns[tid] = btn
        tk.Frame(left, bg=ACCENT, height=2).pack(fill="x", padx=6, pady=(2, 0))

        # search bar
        sh = tk.Frame(left, bg=PANEL)
        sh.pack(fill="x", padx=10, pady=(6, 0))
        tk.Label(sh, text="Search", bg=PANEL, fg=MUTED,
                 font=("Segoe UI", 8)).pack(side="left")
        self._sort_btn = tk.Button(
            sh, text="A→Z", bg=PANEL, fg=MUTED,
            relief="flat", font=("Segoe UI", 8),
            activebackground=INPUT, activeforeground=FG,
            cursor="hand2", bd=0, padx=4,
            command=self._cycle_sort)
        self._sort_btn.pack(side="right")

        se_wrap = tk.Frame(left, bg=INPUT, highlightthickness=1,
                           highlightbackground=BORDER, highlightcolor=ACCENT)
        se_wrap.pack(fill="x", padx=10, pady=(2, 2))
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._filter())
        self._search_entry = tk.Entry(
            se_wrap, textvariable=self._search_var,
            bg=INPUT, fg=FG, insertbackground=FG,
            relief="flat", font=("Segoe UI", 10), bd=0, highlightthickness=0)
        self._search_entry.pack(side="left", fill="x", expand=True, ipady=5, padx=(6, 0))
        self._search_entry.bind("<Down>",   lambda _e: self._search_arrow(+1))
        self._search_entry.bind("<Up>",     lambda _e: self._search_arrow(-1))
        self._search_entry.bind("<Return>", lambda _e: self._search_arrow(0))
        tk.Button(se_wrap, text="✕", bg=INPUT, fg=MUTED,
                  relief="flat", font=("Segoe UI", 9),
                  activebackground=INPUT, activeforeground=DANGER,
                  cursor="hand2", bd=0, padx=6,
                  command=self._clear_search).pack(side="right")

        # syntax hint toggle
        hint_wrap = tk.Frame(left, bg=PANEL)
        hint_wrap.pack(fill="x", padx=10)
        self._hint_visible = False
        self._hint_toggle = tk.Label(
            hint_wrap, text="? syntax", bg=PANEL, fg=MUTED,
            font=("Segoe UI", 7), cursor="hand2")
        self._hint_toggle.pack(anchor="w")
        self._hint_toggle.bind("<Button-1>", lambda _e: self._toggle_hint())
        self._hint_frame = tk.Frame(left, bg=INPUT)
        tk.Label(self._hint_frame,
                 text=('email:gmail   field\n"exact phrase"   quotes\ngit OR lab   either\n'
                       '-term   exclude\npass:*   field set\nuser:me 2fa:yes   AND'),
                 bg=INPUT, fg=MUTED, font=("Courier New", 7),
                 justify="left", anchor="w", padx=8, pady=5).pack(fill="x")

        self._qdesc_var = tk.StringVar(value="")
        tk.Label(left, textvariable=self._qdesc_var, bg=PANEL, fg=ACCENT,
                 font=("Segoe UI", 7), wraplength=210,
                 justify="left", anchor="w").pack(fill="x", padx=10, pady=(0, 2))

        tk.Frame(left, bg=BORDER, height=1).pack(fill="x", padx=10)

        # list container — one Listbox per tab stacked here
        list_container = tk.Frame(left, bg=PANEL)
        list_container.pack(fill="both", expand=True, padx=2)
        for tid, _, _ in TABS:
            frm = tk.Frame(list_container, bg=PANEL)
            sb  = ttk.Scrollbar(frm, orient="vertical")
            lb  = tk.Listbox(
                frm, yscrollcommand=sb.set,
                bg=PANEL, fg=FG, selectbackground=ACCENT, selectforeground="white",
                relief="flat", bd=0, activestyle="none",
                font=("Segoe UI", 10), cursor="hand2",
            )
            sb.configure(command=lb.yview)
            sb.pack(side="right", fill="y")
            lb.pack(fill="both", expand=True)
            lb.bind("<<ListboxSelect>>", lambda e, t=tid: self._on_list_select(t, e))
            self._listboxes[tid]   = lb
            self._list_frames[tid] = frm

        # add / delete
        tk.Frame(left, bg=BORDER, height=1).pack(fill="x", padx=10)
        bw = tk.Frame(left, bg=PANEL)
        bw.pack(fill="x", padx=10, pady=8)
        tk.Button(bw, text="＋ Add", bg=ACCENT, fg="white",
                  relief="flat", font=("Segoe UI", 9, "bold"),
                  activebackground=ACTH, activeforeground="white",
                  cursor="hand2", bd=0, padx=8, pady=4,
                  command=self._add_item).pack(side="left", fill="x", expand=True)
        tk.Frame(bw, bg=PANEL, width=6).pack(side="left")
        tk.Button(bw, text="✕ Del", bg=DANGER, fg="white",
                  relief="flat", font=("Segoe UI", 9, "bold"),
                  activebackground=DANGERH, activeforeground="white",
                  cursor="hand2", bd=0, padx=8, pady=4,
                  command=self._delete_item).pack(side="left", fill="x", expand=True)

        # ── right panel ───────────────────────────────────────────────────
        right = tk.Frame(body, bg=PANEL)
        right.pack(side="left", fill="both", expand=True)
        tk.Frame(right, bg=BORDER, width=1).pack(side="left", fill="y")

        self._detail_root = tk.Frame(right, bg=PANEL)
        self._detail_root.pack(fill="both", expand=True)
        self._empty_lbl = tk.Label(
            self._detail_root,
            text="Select an entry or press  ＋ Add  to get started.",
            bg=PANEL, fg=MUTED, font=("Segoe UI", 11))
        self._empty_lbl.place(relx=0.5, rely=0.5, anchor="center")

        self._detail_canvas = tk.Canvas(self._detail_root, bg=PANEL, highlightthickness=0)
        self._detail_sb = ttk.Scrollbar(self._detail_root, orient="vertical",
                                        command=self._detail_canvas.yview)
        self._detail_canvas.configure(yscrollcommand=self._detail_sb.set)
        self._detail_inner = tk.Frame(self._detail_canvas, bg=PANEL)
        win_id = self._detail_canvas.create_window((0, 0), window=self._detail_inner,
                                                   anchor="nw")
        self._detail_inner.bind(
            "<Configure>",
            lambda _e: self._detail_canvas.configure(
                scrollregion=self._detail_canvas.bbox("all")))
        self._detail_canvas.bind(
            "<Configure>",
            lambda e: self._detail_canvas.itemconfig(win_id, width=e.width))
        self._detail_canvas.bind("<MouseWheel>", self._on_scroll)
        self._detail_inner.bind("<MouseWheel>", self._on_scroll)

        # status bar
        self._status_var = tk.StringVar(value="Ready")
        sb_bar = tk.Frame(root, bg=PANEL, height=24)
        sb_bar.pack(fill="x", side="bottom")
        tk.Frame(sb_bar, bg=BORDER, height=1).pack(fill="x")
        tk.Label(sb_bar, textvariable=self._status_var, bg=PANEL, fg=MUTED,
                 font=("Segoe UI", 8), anchor="w").pack(side="left", padx=12, pady=2)

        # activate first tab
        self._switch_tab("passwords", initial=True)
        return root

    # ── tab switching ─────────────────────────────────────────────────────

    def _switch_tab(self, tab_id: str, initial: bool = False) -> None:
        if not initial:
            self._list_frames[self._active_tab].pack_forget()
        self._active_tab = tab_id
        self._list_frames[tab_id].pack(fill="both", expand=True)
        for tid, btn in self._tab_btns.items():
            if tid == tab_id:
                btn.config(bg=INPUT, fg=FG)
            else:
                btn.config(bg=PANEL, fg=MUTED)
        self._clear_detail()
        self._search_var.set("")
        self._filter()

    # ── visibility ────────────────────────────────────────────────────────

    def _show_unlock(self) -> None:
        self._main_frame.pack_forget()
        self._unlock_frame.pack(fill="both", expand=True)
        self._pw_var.set("")
        self._pw_hint.config(text="")
        self._pw_entry_ref.focus()

    def _show_main(self) -> None:
        self._unlock_frame.pack_forget()
        self._main_frame.pack(fill="both", expand=True)
        self._switch_tab("passwords", initial=False)
        self._start_autofill()

    # ── unlock / lock ─────────────────────────────────────────────────────

    def _try_unlock(self) -> None:
        pw = self._pw_var.get()
        if not pw:
            self._pw_hint.config(text="Password cannot be empty."); return
        path = self._vault_path
        if path.exists():
            try:
                data = decrypt_vault(pw, path.read_bytes())
            except Exception:
                self._pw_hint.config(text="Wrong password or damaged vault."); return
            self._master_pw  = pw
            self._preamble   = data.get("preamble", "")
            self._passwords  = [_pw_from(x) for x in data.get("entries", [])]
            self._cards      = [CardEntry.from_dict(x) for x in data.get("cards", [])]
            self._addresses  = [AddressEntry.from_dict(x) for x in data.get("addresses", [])]
            self._logins     = [LoginGroup.from_dict(x) for x in data.get("logins", [])]
            self._images     = [ImageEntry.from_dict(x) for x in data.get("images", [])]
        else:
            self._master_pw = pw
            self._autosave_silent()
        self._show_main()

    def _lock(self) -> None:
        self._autosave_silent()
        self._master_pw = None
        self._stop_autofill()
        self._clear_detail()
        self._show_unlock()

    # ── search helpers ────────────────────────────────────────────────────

    def _clear_search(self) -> None:
        self._search_var.set("")
        self._search_entry.focus()

    def _focus_search(self) -> None:
        self._search_entry.focus()
        self._search_entry.select_range(0, tk.END)

    def _on_escape(self) -> None:
        if self._search_var.get():
            self._clear_search()
        else:
            self._listboxes[self._active_tab].focus()

    def _search_arrow(self, direction: int) -> None:
        lb = self._listboxes[self._active_tab]
        n  = lb.size()
        if not n:
            return
        sel = lb.curselection()
        cur = sel[0] if sel else -1
        nxt = max(0, min(n - 1, cur + direction))
        lb.selection_clear(0, tk.END)
        lb.selection_set(nxt); lb.see(nxt)
        if self._filtered:
            self._load_detail(self._filtered[nxt])

    def _cycle_sort(self) -> None:
        modes = ("az", "za", "best")
        lbls  = ("A→Z", "Z→A", "★ Best")
        i = (modes.index(self._sort_mode) + 1) % len(modes)
        self._sort_mode = modes[i]
        self._sort_btn.config(text=lbls[i])
        self._filter()

    def _toggle_hint(self) -> None:
        self._hint_visible = not self._hint_visible
        if self._hint_visible:
            self._hint_frame.pack(fill="x", padx=10, pady=(0, 4))
            self._hint_toggle.config(text="▲ syntax")
        else:
            self._hint_frame.pack_forget()
            self._hint_toggle.config(text="? syntax")

    # ── filtering ─────────────────────────────────────────────────────────

    def _filter(self, select_label: str | None = None) -> None:
        q     = self._search_var.get().strip()
        tab   = self._active_tab
        store = self._store()
        lb    = self._listboxes[tab]

        self._qdesc_var.set(describe_query(q) if q else "")

        if tab == "passwords":
            matcher = build_matcher(q)
            matched = [i for i, e in enumerate(store) if matcher(e)]
        else:
            ql = q.lower()
            matched = [i for i, e in enumerate(store)
                       if not ql or ql in _item_haystack(e).lower()]

        # sort
        def _label(i: int) -> str:
            return _item_label(store[i]).lower()

        if self._sort_mode == "az":
            matched.sort(key=_label)
        elif self._sort_mode == "za":
            matched.sort(key=_label, reverse=True)
        elif self._sort_mode == "best" and q and tab == "passwords":
            matched.sort(key=lambda i: score_entry(q, store[i]), reverse=True)
        else:
            matched.sort(key=_label)

        self._filtered = matched
        lb.delete(0, tk.END)
        select_at: int | None = None

        for pos, idx in enumerate(self._filtered):
            lbl = _item_label(store[idx])
            lb.insert(tk.END, f"  {lbl}")
            if q and lbl.lower() == q.strip('"').lower():
                lb.itemconfig(pos, fg=GREEN)
            elif q and q.strip('"').lower() in lbl.lower():
                lb.itemconfig(pos, fg=ACCENT)
            else:
                lb.itemconfig(pos, fg=FG)
            if select_label and lbl == select_label:
                select_at = pos

        if select_at is not None:
            lb.selection_set(select_at); lb.see(select_at)
            self._load_detail(self._filtered[select_at])
        elif self._filtered:
            lb.selection_set(0)
            self._load_detail(self._filtered[0])
        else:
            self._clear_detail()

        icons = {"passwords":"🔑","cards":"💳","addresses":"🏠",
                 "logins":"🔗","images":"🖼"}
        self._set_status(
            f"{icons[tab]} {len(store)} total  •  {len(self._filtered)} shown"
            + (f"  •  query: {q}" if q else "")
        )

    def _on_list_select(self, tab_id: str, _evt: object = None) -> None:
        if tab_id != self._active_tab:
            return
        sel = self._listboxes[tab_id].curselection()
        if not sel or not self._filtered:
            return
        idx = self._filtered[sel[0]]
        self._load_detail(idx)

    # ── detail panel ─────────────────────────────────────────────────────

    def _clear_detail(self) -> None:
        for w in self._detail_inner.winfo_children():
            w.destroy()
        self._detail_canvas.pack_forget()
        self._detail_sb.pack_forget()
        self._empty_lbl.place(relx=0.5, rely=0.5, anchor="center")
        self._sel_idx = -1

    def _open_detail_canvas(self) -> tk.Frame:
        self._empty_lbl.place_forget()
        self._detail_sb.pack(side="right", fill="y")
        self._detail_canvas.pack(side="left", fill="both", expand=True)
        for w in self._detail_inner.winfo_children():
            w.destroy()
        self._shows = {}
        pad = tk.Frame(self._detail_inner, bg=PANEL)
        pad.pack(fill="both", expand=True, padx=16, pady=16)
        return pad

    def _load_detail(self, idx: int) -> None:
        self._sel_idx = idx
        tab   = self._active_tab
        store = self._store()
        if idx < 0 or idx >= len(store):
            self._clear_detail(); return
        item = store[idx]
        pad  = self._open_detail_canvas()
        {
            "passwords": self._detail_password,
            "cards":     self._detail_card,
            "addresses": self._detail_address,
            "logins":    self._detail_login,
            "images":    self._detail_image,
        }[tab](pad, item)

    def _top_bar(self, pad: tk.Frame, title: str, badge: str = "",
                 badge_color: str = ACCENT) -> None:
        top = tk.Frame(pad, bg=PANEL)
        top.pack(fill="x", pady=(0, 4))
        tk.Label(top, text=title, bg=PANEL, fg=FG,
                 font=("Segoe UI", 15, "bold"),
                 wraplength=480, justify="left").pack(side="left", anchor="w")
        if badge:
            tk.Label(top, text=f" {badge} ", bg=badge_color, fg="white",
                     font=("Segoe UI", 8, "bold"),
                     padx=4, pady=2).pack(side="left", padx=(8, 0), anchor="center")
        _detail_btn(top, "✕ Del", self._delete_item, bg=DANGER).pack(
            side="right")
        _detail_btn(top, "✏ Edit", self._edit_item).pack(
            side="right", padx=(0, 6))
        tk.Frame(pad, bg=BORDER, height=1).pack(fill="x", pady=(4, 12))

    def _detail_password(self, pad: tk.Frame, ent: SiteEntry) -> None:
        self._top_bar(pad, ent.domain, "🔑 PASSWORD")
        last_section: str | None = None
        for key, val in ent.lines:
            sec = key.split(" — ")[0] if " — " in key else None
            disp = key.split(" — ")[1] if " — " in key else key
            if sec and sec != last_section:
                sf = tk.Frame(pad, bg=PANEL)
                sf.pack(fill="x", pady=(8, 4))
                tk.Label(sf, text=sec, bg=PANEL, fg=MUTED,
                         font=("Segoe UI", 8, "bold")).pack(side="left")
                tk.Frame(sf, bg=BORDER, height=1).pack(
                    side="left", fill="x", expand=True, padx=(8, 0), pady=4)
                last_section = sec
            _field_row(pad, disp, val, self._copy,
                       show_copy=val not in _NULL_VALS,
                       secret=_is_sensitive(key),
                       shows_dict=self._shows)

    def _detail_card(self, pad: tk.Frame, c: CardEntry) -> None:
        badge_colors = {"Debit": "#4a90e2", "Credit": "#e24a4a",
                        "Prepaid": "#4ae296", "Gift": YELLOW}
        self._top_bar(pad, c.name,
                      f"💳 {c.card_type.upper()}",
                      badge_colors.get(c.card_type, ACCENT))
        # masked number preview
        mn = tk.Frame(pad, bg=INPUT)
        mn.pack(fill="x", pady=(0, 12))
        self._masked_lbl = tk.Label(mn, text=c.masked_number(),
                                    bg=INPUT, fg=FG,
                                    font=("Courier New", 14, "bold"), padx=12, pady=8)
        self._masked_lbl.pack(side="left")
        # show-full toggle
        _full = {"on": False, "num": c.display_number(), "masked": c.masked_number()}
        def _toggle_num() -> None:
            _full["on"] = not _full["on"]
            self._masked_lbl.config(
                text=_full["num"] if _full["on"] else _full["masked"])
        tk.Button(mn, text="👁", bg=INPUT, fg=MUTED,
                  relief="flat", font=("Segoe UI", 11),
                  activebackground=INPUT, activeforeground=FG,
                  cursor="hand2", bd=0, padx=8,
                  command=_toggle_num).pack(side="left")
        _copy_btn(mn, c.number, self._copy).pack(side="right", padx=8, pady=6)

        for label, val, secret in [
            ("Expiry",  c.expiry, False),
            ("CVV",     c.cvv,    True),
            ("PIN",     c.pin,    True),
            ("Bank",    c.bank,   False),
            ("Notes",   c.notes,  False),
        ]:
            if val:
                _field_row(pad, label, val, self._copy,
                           show_copy=bool(val), secret=secret,
                           shows_dict=self._shows)

    def _detail_address(self, pad: tk.Frame, a: AddressEntry) -> None:
        self._top_bar(pad, a.label, "🏠 ADDRESS")
        # formatted block
        block = a.full_address()
        addr_frame = tk.Frame(pad, bg=INPUT)
        addr_frame.pack(fill="x", pady=(0, 12))
        tk.Label(addr_frame, text=block, bg=INPUT, fg=FG,
                 font=("Segoe UI", 11), justify="left",
                 padx=12, pady=8).pack(side="left")
        _copy_btn(addr_frame, block, self._copy).pack(
            side="right", padx=8, pady=8, anchor="n")
        for label, val in [
            ("Street",  a.line1),
            ("Apt/Unit",a.line2),
            ("City",    a.city),
            ("State",   a.state),
            ("ZIP",     a.zipcode),
            ("Country", a.country),
            ("Notes",   a.notes),
        ]:
            if val:
                _field_row(pad, label, val, self._copy)

    def _detail_login(self, pad: tk.Frame, g: LoginGroup) -> None:
        self._top_bar(pad, f"Login via {g.via}", "🔗 LOGIN GROUP")
        if g.email:
            _field_row(pad, "Account email", g.email, self._copy)
        if g.notes:
            _field_row(pad, "Notes", g.notes, self._copy, show_copy=False)
        tk.Label(pad, text=f"Sites using this login  ({len(g.sites)})",
                 bg=PANEL, fg=MUTED, font=("Segoe UI", 9, "bold")).pack(
            anchor="w", pady=(12, 4))
        for site in g.sites:
            row = tk.Frame(pad, bg=PANEL)
            row.pack(fill="x", pady=2)
            tk.Label(row, text="•", bg=PANEL, fg=ACCENT,
                     font=("Segoe UI", 11)).pack(side="left", padx=(0, 8))
            tk.Label(row, text=site, bg=PANEL, fg=FG,
                     font=("Segoe UI", 10), anchor="w").pack(
                side="left", fill="x", expand=True)
            _copy_btn(row, site, self._copy).pack(side="right")

    def _detail_image(self, pad: tk.Frame, img: ImageEntry) -> None:
        cat_colors = {"ID": "#4a90e2", "Card": "#e24a4a",
                      "License": "#9ce24a", "Passport": "#4ae2c8",
                      "Insurance": YELLOW}
        self._top_bar(pad, img.name,
                      f"🖼 {img.category.upper()}",
                      cat_colors.get(img.category, ACCENT))
        # image display
        if img.data_b64:
            try:
                raw = base64.b64decode(img.data_b64)
                if PIL_OK:
                    pil_img = Image.open(io.BytesIO(raw))
                    pil_img.thumbnail((520, 340))
                    self._photo_ref = ImageTk.PhotoImage(pil_img)
                else:
                    self._photo_ref = tk.PhotoImage(data=img.data_b64)
                img_lbl = tk.Label(pad, image=self._photo_ref,
                                   bg=PANEL, cursor="hand2")
                img_lbl.pack(anchor="w", pady=(0, 12))
            except Exception as ex:
                tk.Label(pad, text=f"(cannot display image: {ex})",
                         bg=PANEL, fg=MUTED).pack(anchor="w")
        # save-out button
        def _save_image() -> None:
            ext = {"image/jpeg": ".jpg", "image/gif": ".gif",
                   "image/bmp": ".bmp"}.get(img.mime, ".png")
            p = filedialog.asksaveasfilename(
                title="Save image",
                defaultextension=ext,
                initialfile=img.name + ext,
                filetypes=[("Image", f"*{ext}"), ("All", "*.*")],
            )
            if p:
                Path(p).write_bytes(base64.b64decode(img.data_b64))
                messagebox.showinfo("VaultPass", f"Saved to {p}")
        row = tk.Frame(pad, bg=PANEL); row.pack(fill="x", pady=(0, 8))
        tk.Button(row, text="💾 Save image to file…",
                  bg=INPUT, fg=FG, relief="flat", font=("Segoe UI", 9),
                  activebackground=ACCENT, activeforeground="white",
                  cursor="hand2", bd=0, padx=10, pady=4,
                  command=_save_image).pack(side="left")
        tk.Label(row, text=f"  {img.size_kb()} KB  •  {img.mime}",
                 bg=PANEL, fg=MUTED, font=("Segoe UI", 8)).pack(side="left")
        if img.notes:
            _field_row(pad, "Notes", img.notes, self._copy, show_copy=False)

    def _on_scroll(self, e: tk.Event) -> None:
        self._detail_canvas.yview_scroll(int(-1*(e.delta/120)), "units")

    # ── CRUD ──────────────────────────────────────────────────────────────

    def _add_item(self) -> None:
        if not self._master_pw: return
        dlg_cls = {
            "passwords": EntryDialog,
            "cards":     CardDialog,
            "addresses": AddressDialog,
            "logins":    LoginGroupDialog,
            "images":    ImageDialog,
        }[self._active_tab]
        dlg = dlg_cls(self)
        self.wait_window(dlg)
        if dlg.result:
            self._store().append(dlg.result)
            self._autosave_silent()
            self._filter(select_label=_item_label(dlg.result))
            self._set_status(f"Added '{_item_label(dlg.result)}'")

    def _edit_item(self) -> None:
        idx = self._sel_idx
        if idx < 0: return
        store = self._store()
        existing = store[idx]
        dlg_cls = {
            "passwords": EntryDialog,
            "cards":     CardDialog,
            "addresses": AddressDialog,
            "logins":    LoginGroupDialog,
            "images":    ImageDialog,
        }[self._active_tab]
        dlg = dlg_cls(self, existing=existing)
        self.wait_window(dlg)
        if dlg.result:
            store[idx] = dlg.result
            self._autosave_silent()
            self._filter(select_label=_item_label(dlg.result))

    def _delete_item(self) -> None:
        idx = self._sel_idx
        if idx < 0: return
        store = self._store()
        lbl = _item_label(store[idx])
        if not messagebox.askyesno("Delete", f"Delete '{lbl}'?", parent=self): return
        store.pop(idx)
        self._sel_idx = -1
        self._autosave_silent()
        self._clear_detail()
        self._filter()
        self._set_status(f"Deleted '{lbl}'")

    # ── clipboard ─────────────────────────────────────────────────────────

    def _copy(self, val: str) -> None:
        if self._clip_job:
            self.after_cancel(self._clip_job)
        self.clipboard_clear()
        self.clipboard_append(val)
        self.update()
        def _clear() -> None:
            self.clipboard_clear(); self._clip_job = None
        self._clip_job = self.after(CLIP_CLEAR_SECS * 1000, _clear)
        self._set_status(f"Copied!  Clipboard clears in {CLIP_CLEAR_SECS}s")

    # ── save / load ───────────────────────────────────────────────────────

    def _vault_dict(self) -> dict[str, Any]:
        return {
            "version":   2,
            "preamble":  self._preamble,
            "entries":   [_pw_to(e)               for e in self._passwords],
            "cards":     [c.to_dict()              for c in self._cards],
            "addresses": [a.to_dict()              for a in self._addresses],
            "logins":    [g.to_dict()              for g in self._logins],
            "images":    [i.to_dict()              for i in self._images],
        }

    def _autosave_silent(self) -> None:
        if not self._master_pw: return
        blob = encrypt_vault(self._master_pw, self._vault_dict())
        self._vault_path.parent.mkdir(parents=True, exist_ok=True)
        self._vault_path.write_bytes(blob)

    def _autosave(self) -> None:
        if not self._master_pw: return
        self._autosave_silent()
        self._set_status("Saved.")

    # ── file actions ─────────────────────────────────────────────────────

    def _menu_open(self) -> None:
        p = filedialog.askopenfilename(
            title="Open vault",
            filetypes=[("VaultPass", "*.vpm"), ("All", "*.*")])
        if p:
            self._vault_path = Path(p)
            self._master_pw  = None
            self._show_unlock()

    def _import_plain(self) -> None:
        if not self._master_pw: return
        p = filedialog.askopenfilename(
            title="Import plain text",
            filetypes=[("Text", "*.txt"), ("All", "*.*")])
        if not p: return
        try:
            text = Path(p).read_text(encoding="utf-8")
            preamble, pw_entries = parse_vault_text(text)
            cards, addrs, logins, remaining = parse_preamble(preamble)

            replace = messagebox.askyesno(
                "Import",
                f"Found:\n"
                f"  • {len(pw_entries)} password entries\n"
                f"  • {len(cards)} cards\n"
                f"  • {len(addrs)} addresses\n"
                f"  • {len(logins)} login groups\n\n"
                "Replace all existing data?  (No = merge)",
            )
            if replace:
                self._preamble   = remaining
                self._passwords  = pw_entries
                self._cards      = cards
                self._addresses  = addrs
                self._logins     = logins
            else:
                existing_pw_domains = {e.domain for e in self._passwords}
                self._passwords += [e for e in pw_entries
                                    if e.domain not in existing_pw_domains]
                existing_card_names = {c.name for c in self._cards}
                self._cards    += [c for c in cards if c.name not in existing_card_names]
                existing_addr   = {a.label for a in self._addresses}
                for a in addrs:
                    if a.label in existing_addr:
                        a.label = a.label + " (imported)"
                self._addresses += addrs
                self._logins    += logins

            self._autosave_silent()
            self._switch_tab("passwords", initial=False)
            messagebox.showinfo("Import", "Done! All data imported and saved.")
        except Exception as ex:
            messagebox.showerror("Import failed", str(ex))

    def _confirm_password(self, prompt: str = "Re-enter master password to continue:") -> bool:
        """Show a modal password-confirmation dialog. Returns True only on correct match."""
        dlg = tk.Toplevel(self)
        dlg.configure(bg=BG)
        dlg.title("Confirm identity")
        dlg.geometry("360x180")
        dlg.resizable(False, False)
        dlg.grab_set()
        dlg.transient(self)
        confirmed = tk.BooleanVar(value=False)

        ttk.Frame(dlg, height=10).pack()
        ttk.Label(dlg, text=prompt, style="Sub.TLabel",
                  wraplength=320).pack(padx=20, anchor="w")
        pw_var = tk.StringVar()
        err_var = tk.StringVar()

        pw_e = ttk.Entry(dlg, textvariable=pw_var, show="•", width=34)
        pw_e.pack(padx=20, pady=(6, 2), fill="x")

        tk.Label(dlg, textvariable=err_var, bg=BG, fg=DANGER,
                 font=("Segoe UI", 8)).pack(anchor="w", padx=20)

        def _ok() -> None:
            if pw_var.get() == self._master_pw:
                confirmed.set(True)
                dlg.destroy()
            else:
                err_var.set("Incorrect password.")
                pw_var.set("")
                pw_e.focus()

        pw_e.bind("<Return>", lambda _e: _ok())
        bar = ttk.Frame(dlg); bar.pack(fill="x", padx=20, pady=(8, 0))
        ttk.Button(bar, text="Cancel", command=dlg.destroy).pack(side="right", padx=(6, 0))
        ttk.Button(bar, text="Confirm", style="Accent.TButton",
                   command=_ok).pack(side="right")
        pw_e.focus()
        self.wait_window(dlg)
        return confirmed.get()

    def _export_plain(self) -> None:
        if not self._master_pw:
            return

        # ── step 1: re-enter master password ──────────────────────────────
        if not self._confirm_password(
            "Exporting creates an unencrypted file.\n"
            "Re-enter your master password to authorise:"
        ):
            self._set_status("Export cancelled.")
            return

        # ── step 2: choose whether sensitive fields are hidden ─────────────
        hide_sensitive = messagebox.askyesno(
            "Export mode",
            "Hide sensitive fields in the exported file?\n\n"
            "Yes  →  Passwords, phrases, recovery codes replaced with [HIDDEN]\n"
            "No   →  Export everything in plain text  ⚠ store securely",
            icon="warning",
        )

        # ── step 3: pick save path ─────────────────────────────────────────
        p = filedialog.asksaveasfilename(
            title="Export plain text",
            defaultextension=".txt",
            filetypes=[("Text", "*.txt")],
        )
        if not p:
            return

        # ── step 4: build output, optionally masking sensitive values ──────
        try:
            if hide_sensitive:
                from vault_format import SiteEntry as _SE
                masked: list[_SE] = []
                for ent in self._passwords:
                    lines = [
                        (k, "[HIDDEN]" if _is_sensitive(k) else v)
                        for k, v in ent.lines
                    ]
                    masked.append(_SE(domain=ent.domain, lines=lines))
                out = serialize_vault_text(self._preamble, masked)
                suffix = "  •  Sensitive fields are replaced with [HIDDEN]."
            else:
                out = serialize_vault_text(self._preamble, self._passwords)
                suffix = "  •  All fields exported in plain text."

            Path(p).write_text(out, encoding="utf-8")
            messagebox.showwarning(
                "Export complete",
                f"Saved to:\n{p}\n\n"
                "⚠  This file is NOT encrypted.\n"
                "Delete or secure it after use.\n"
                f"{suffix}\n\n"
                "Cards, addresses and images are never exported."
            )
            self._set_status(f"Exported to {p}")
        except OSError as ex:
            messagebox.showerror("Export failed", str(ex))

    def _change_password(self) -> None:
        if not self._master_pw: return
        dlg = ChangePwDialog(self, self._master_pw)
        self.wait_window(dlg)
        if dlg.result:
            self._master_pw = dlg.result
            self._autosave_silent()
            self._set_status("Master password changed.")

    # ── misc ──────────────────────────────────────────────────────────────

    def _open_gen_standalone(self) -> None:
        """Open the password generator as a standalone tool (no callback)."""
        PasswordGenDialog(self)

    def _set_status(self, msg: str) -> None:
        self._status_var.set(msg)

    def _about(self) -> None:
        messagebox.showinfo(APP_NAME,
            "VaultPass  •  offline encrypted vault\n\n"
            "Tabs:  🔑 Passwords  💳 Cards  🏠 Addresses  🔗 Login Via  🖼 Images\n\n"
            "• PBKDF2-HMAC-SHA256 (480k iter) + AES-Fernet\n"
            f"• Clipboard auto-clears after {CLIP_CLEAR_SECS}s\n"
            "• Ctrl+N  add  |  Ctrl+F  search  |  Ctrl+S  save\n"
            "• Import: parses cards, addresses & login groups from plain .txt")

    # ── autofill subsystem ────────────────────────────────────────────────

    def _start_autofill(self) -> None:
        if not self._autofill_enabled:
            return
        if self._hud is None:
            self._hud = AutofillHUD(self)
        if self._watcher is None or not self._watcher.is_alive():
            self._watcher = BrowserWatcher(
                after_fn=self.after,
                on_change=self._on_browser_domain,
                on_clear=self._on_browser_gone,
            )
            self._watcher.start()
        self._autofill_btn_var.set("AutoFill ON")

    def _stop_autofill(self) -> None:
        if self._watcher:
            self._watcher.stop()
            self._watcher = None
        if self._hud:
            self._hud.hide()

    def _toggle_autofill(self) -> None:
        self._autofill_enabled = not self._autofill_enabled
        if self._autofill_enabled:
            self._start_autofill()
            self._set_status("AutoFill enabled — watches browser for matching domains.")
        else:
            self._stop_autofill()
            self._autofill_btn_var.set("AutoFill OFF")
            self._set_status("AutoFill disabled.")

    def _on_browser_domain(self, domain: str, hwnd: int) -> None:
        """Called on main thread when active browser domain changes."""
        if not self._autofill_enabled or not self._master_pw:
            return
        matches = hud_find_matches(domain, self._passwords)
        if self._hud:
            self._hud.update(domain, matches, hwnd)
        if matches:
            self._set_status(
                f"🔑 AutoFill: {len(matches)} match(es) for '{domain}' — "
                "focus a field in the browser, then click ▶ Fill"
            )

    def _on_browser_gone(self) -> None:
        """Called when the browser is no longer the foreground window."""
        if self._hud:
            self._hud.hide()

    def _on_close(self) -> None:
        self._autosave_silent()
        self._stop_autofill()
        self.destroy()


# ── helpers outside class ─────────────────────────────────────────────────────

def _pw_to(e: SiteEntry) -> dict[str, Any]:
    return {"domain": e.domain, "lines": [[a, b] for a, b in e.lines]}


def _pw_from(d: dict[str, Any]) -> SiteEntry:
    return SiteEntry(domain=d["domain"], lines=[tuple(x) for x in d.get("lines", [])])


def _item_label(item: Any) -> str:
    if isinstance(item, SiteEntry):   return item.domain
    if isinstance(item, CardEntry):   return item.name
    if isinstance(item, AddressEntry):return item.label
    if isinstance(item, LoginGroup):  return item.display_name()
    if isinstance(item, ImageEntry):  return item.name
    return str(item)


def _item_haystack(item: Any) -> str:
    if isinstance(item, SiteEntry):
        return item.domain + " " + " ".join(v for _, v in item.lines)
    if isinstance(item, CardEntry):
        return f"{item.name} {item.card_type} {item.bank} {item.notes}"
    if isinstance(item, AddressEntry):
        return f"{item.label} {item.line1} {item.line2} {item.city} {item.state} {item.zipcode} {item.country} {item.notes}"
    if isinstance(item, LoginGroup):
        return f"{item.via} {item.email} {' '.join(item.sites)} {item.notes}"
    if isinstance(item, ImageEntry):
        return f"{item.name} {item.category} {item.notes}"
    return ""


def main() -> None:
    app = VaultApp()
    app.mainloop()


if __name__ == "__main__":
    main()
