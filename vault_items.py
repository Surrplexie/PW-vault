"""
Non-password vault item types: Cards, Addresses, Login-Via groups, Images.
Also handles parsing the freeform preamble from a sample.txt-style file.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field
from typing import Any


# ── dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class CardEntry:
    name: str                      # "Chase Debit", "Amex Platinum"
    card_type: str  = "Debit"      # Debit / Credit / Prepaid / Gift / Other
    number: str     = ""
    expiry: str     = ""           # MM/YY or MM/YYYY
    cvv: str        = ""
    pin: str        = ""
    bank: str       = ""
    notes: str      = ""

    def display_number(self) -> str:
        n = self.number.replace(" ", "").replace("-", "")
        groups = [n[i:i+4] for i in range(0, len(n), 4)]
        return " ".join(groups)

    def masked_number(self) -> str:
        n = self.number.replace(" ", "").replace("-", "")
        if len(n) < 4:
            return "••••"
        return "•••• •••• •••• " + n[-4:]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "card_type": self.card_type,
            "number": self.number, "expiry": self.expiry,
            "cvv": self.cvv, "pin": self.pin,
            "bank": self.bank, "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CardEntry":
        return cls(
            name=d.get("name", "Card"), card_type=d.get("card_type", "Debit"),
            number=d.get("number", ""), expiry=d.get("expiry", ""),
            cvv=d.get("cvv", ""), pin=d.get("pin", ""),
            bank=d.get("bank", ""), notes=d.get("notes", ""),
        )


@dataclass
class AddressEntry:
    label: str                     # "Home", "Work", "Billing"
    line1: str      = ""           # street
    line2: str      = ""           # apt / unit / suite
    city: str       = ""
    state: str      = ""
    zipcode: str    = ""
    country: str    = ""
    notes: str      = ""

    def full_address(self) -> str:
        parts = [self.line1]
        if self.line2:
            parts.append(self.line2)
        city_line = ", ".join(p for p in [self.city, self.state, self.zipcode] if p)
        if city_line:
            parts.append(city_line)
        if self.country:
            parts.append(self.country)
        return "\n".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label, "line1": self.line1, "line2": self.line2,
            "city": self.city, "state": self.state, "zipcode": self.zipcode,
            "country": self.country, "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AddressEntry":
        return cls(
            label=d.get("label", "Address"), line1=d.get("line1", ""),
            line2=d.get("line2", ""), city=d.get("city", ""),
            state=d.get("state", ""), zipcode=d.get("zipcode", ""),
            country=d.get("country", ""), notes=d.get("notes", ""),
        )


@dataclass
class LoginGroup:
    via: str                       # "Apple", "Google"
    email: str      = ""
    sites: list[str] = field(default_factory=list)
    notes: str      = ""

    def display_name(self) -> str:
        return f"via {self.via}  ({self.email})" if self.email else f"via {self.via}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "via": self.via, "email": self.email,
            "sites": list(self.sites), "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "LoginGroup":
        return cls(
            via=d.get("via", ""), email=d.get("email", ""),
            sites=list(d.get("sites", [])), notes=d.get("notes", ""),
        )


@dataclass
class ImageEntry:
    name: str
    category: str   = "ID"        # ID, Card, Document, Other
    mime: str       = "image/png"
    data_b64: str   = ""           # base64-encoded raw bytes
    notes: str      = ""

    def size_kb(self) -> int:
        return len(self.data_b64) * 3 // 4 // 1024

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "category": self.category,
            "mime": self.mime, "data_b64": self.data_b64,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ImageEntry":
        return cls(
            name=d.get("name", "Image"), category=d.get("category", "ID"),
            mime=d.get("mime", "image/png"), data_b64=d.get("data_b64", ""),
            notes=d.get("notes", ""),
        )


# ── preamble parser ───────────────────────────────────────────────────────────

_CARD_HEADER_RE  = re.compile(r"^(debit|credit|prepaid|gift|virtual)?\s*card$", re.I)
_LOGIN_VIA_RE    = re.compile(r"^login via (.+?);\s*(.+)$", re.I)
_CARD_LINE_RE    = re.compile(
    r"^([\d][\d\s\-]{10,21}[\d])\s+(\d{2}/\d{2,4})\s+(\d{3,4})\s*$"
)
_SECTION_HEADERS = {"address", "addresses"}


def _is_section_start(line: str) -> bool:
    s = line.strip().lower()
    return (
        bool(_CARD_HEADER_RE.match(s))
        or bool(_LOGIN_VIA_RE.match(s))
        or s in _SECTION_HEADERS
        or s.startswith("=== ")
    )


def parse_preamble(text: str) -> tuple[
    list[CardEntry], list[AddressEntry], list[LoginGroup], str
]:
    """
    Scan the freeform preamble and extract structured items.

    Returns
    -------
    cards, addresses, login_groups, remaining_text
        remaining_text contains lines that were not consumed by any parser.
    """
    lines = text.replace("\r\n", "\n").split("\n")
    cards: list[CardEntry]       = []
    addresses: list[AddressEntry] = []
    groups: list[LoginGroup]      = []
    remaining: list[str]          = []

    i = 0
    while i < len(lines):
        raw  = lines[i]
        line = raw.strip()

        # ── blank line ──
        if not line:
            remaining.append(raw)
            i += 1
            continue

        # ── card header ──
        if _CARD_HEADER_RE.match(line.lower()):
            card_type_label = line.title().replace(" Card", "").strip() or "Debit"
            i += 1
            # skip blanks, look for number line
            while i < len(lines) and not lines[i].strip():
                i += 1
            if i < len(lines):
                m = _CARD_LINE_RE.match(lines[i].strip())
                if m:
                    raw_num = m.group(1).replace(" ", "").replace("-", "")
                    cards.append(CardEntry(
                        name=f"{card_type_label} Card",
                        card_type=card_type_label,
                        number=raw_num,
                        expiry=m.group(2),
                        cvv=m.group(3),
                    ))
                    i += 1
                    continue
            # no card number found — fall through and keep header as remaining
            remaining.append(raw)
            continue

        # ── address header ──
        if line.lower() in _SECTION_HEADERS:
            i += 1
            addr_idx = 1
            while i < len(lines):
                al = lines[i].strip()
                if not al:
                    i += 1
                    break
                if _is_section_start(al):
                    break
                # split off "Unit: ..." suffix
                line2 = ""
                if ", unit:" in al.lower():
                    idx = al.lower().index(", unit:")
                    line2 = al[idx + 2:].strip()   # "Unit: 303-A"
                    al    = al[:idx].strip()

                parts = [p.strip() for p in al.split(",")]
                if len(parts) >= 3:
                    street   = ", ".join(parts[:-2])
                    city     = parts[-2]
                    sz       = parts[-1].split()
                    state    = " ".join(sz[:-1]) if len(sz) > 1 else parts[-1]
                    zipcode  = sz[-1] if len(sz) > 1 else ""
                elif len(parts) == 2:
                    street, city = parts[0], parts[1]
                    state = zipcode = ""
                else:
                    street = al; city = state = zipcode = ""

                addresses.append(AddressEntry(
                    label=f"Address {addr_idx}",
                    line1=street, line2=line2,
                    city=city, state=state, zipcode=zipcode,
                ))
                addr_idx += 1
                i += 1
            continue

        # ── login via ──
        m = _LOGIN_VIA_RE.match(line)
        if m:
            provider = m.group(1).strip().title()
            email    = m.group(2).strip()
            sites: list[str] = []
            i += 1
            while i < len(lines):
                sl = lines[i].strip()
                if not sl:
                    i += 1
                    break
                if _is_section_start(sl):
                    break
                sites.append(sl)
                i += 1
            groups.append(LoginGroup(via=provider, email=email, sites=sites))
            continue

        remaining.append(raw)
        i += 1

    return cards, addresses, groups, "\n".join(remaining)
