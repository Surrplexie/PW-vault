"""Parse and serialize the sample.txt vault template format."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Tuple

SECTION_HEADER_RE = re.compile(r"^===\s*(.+?)\s*===$")


@dataclass
class SiteEntry:
    domain: str
    lines: List[Tuple[str, str]] = field(default_factory=list)
    """Ordered list of (key, value) pairs; keys may include section prefixes."""

    def as_dict(self) -> dict[str, str]:
        return dict(self.lines)


def _parse_tree_line(line: str) -> Tuple[str, str] | None:
    s = line.rstrip("\n")
    if s.startswith("├─ "):
        rest = s[3:]
    elif s.startswith("└─ "):
        rest = s[3:]
    else:
        return None
    if ": " not in rest:
        return None
    key, val = rest.split(": ", 1)
    return key.strip(), val.strip()


def parse_vault_text(text: str) -> Tuple[str, List[SiteEntry]]:
    """
    Split file into preamble (freeform text before first === block) and site entries.
    """
    lines = text.replace("\r\n", "\n").split("\n")
    preamble_lines: List[str] = []
    entries: List[SiteEntry] = []
    i = 0
    # Preamble until first === ... ===
    while i < len(lines):
        line = lines[i]
        m = SECTION_HEADER_RE.match(line.strip())
        if m:
            break
        preamble_lines.append(line)
        i += 1

    preamble = "\n".join(preamble_lines).rstrip() + ("\n" if preamble_lines else "")

    current: SiteEntry | None = None
    section_label: str | None = None

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        m = SECTION_HEADER_RE.match(stripped)
        if m:
            if current:
                entries.append(current)
            current = SiteEntry(domain=m.group(1).strip())
            section_label = None
            i += 1
            continue

        if current is None:
            # Orphan lines after preamble but before any header — keep in preamble
            preamble_lines.append(line)
            preamble = "\n".join(preamble_lines).rstrip() + "\n"
            i += 1
            continue

        parsed = _parse_tree_line(line)
        if parsed:
            key, val = parsed
            if section_label:
                key = f"{section_label} — {key}"
            current.lines.append((key, val))
            i += 1
            continue

        # Subsection title (e.g. "Acc Sec.", "Add. Data.") or blank
        if stripped == "":
            i += 1
            continue

        # Line without tree marker: treat as subsection heading
        section_label = stripped
        i += 1

    if current:
        entries.append(current)

    return preamble.rstrip() + ("\n" if preamble else ""), entries


def serialize_vault_text(preamble: str, entries: List[SiteEntry]) -> str:
    """Rebuild .txt matching the template style."""
    parts: List[str] = []
    pre = preamble.rstrip()
    if pre:
        parts.append(pre)
        if not pre.endswith("\n"):
            parts.append("\n")
        parts.append("\n")

    for idx, ent in enumerate(entries):
        parts.append(f"=== {ent.domain} ===\n")
        # Group keys back into sections where key contains " — "
        section_keys: dict[str, List[Tuple[str, str]]] = {}
        order: List[str] = []
        for key, val in ent.lines:
            if " — " in key:
                sec, subkey = key.split(" — ", 1)
                if sec not in section_keys:
                    section_keys[sec] = []
                    order.append(sec)
                section_keys[sec].append((subkey, val))
            else:
                if "__root__" not in section_keys:
                    section_keys["__root__"] = []
                    order.insert(0, "__root__")
                section_keys.setdefault("__root__", []).append((key, val))

        has_subsections = any(s != "__root__" for s in order)
        first_block = True
        for sec in order:
            rows = section_keys[sec]
            if sec == "__root__":
                for j, (k, v) in enumerate(rows):
                    is_last = j == len(rows) - 1
                    branch = "└─ " if is_last and not has_subsections else "├─ "
                    parts.append(f"{branch}{k}: {v}\n")
                first_block = False
                continue
            parts.append(f"{sec}\n")
            first_block = False
            for j, (k, v) in enumerate(rows):
                branch = "└─ " if j == len(rows) - 1 else "├─ "
                parts.append(f"{branch}{k}: {v}\n")

        if idx < len(entries) - 1:
            parts.append("\n")

    return "".join(parts)
