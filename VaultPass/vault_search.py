"""
VaultPass search engine.

Supported syntax
----------------
  github                 → substring anywhere (domain + all values)
  "my exact phrase"      → literal phrase (spaces included)
  domain:github          → match only in site domain
  email:gmail            → match in email field
  pass:hunter            → match in password field
  2fa:yes                → match in 2FA field
  phrase:word            → match in Phrase/Seed field
  field:*                → field has a real value (not NULL / empty)
  -word                  → exclude entries that match word  (NOT)
  NOT word               → same as -word
  word1 word2            → AND  (both must match, default for spaces)
  word1 OR word2         → OR   (either must match)
  word1 | word2          → same as OR
  domain:git email:me    → AND across different fields
  github OR gitlab       → either domain
  pass:* -2fa:yes        → has a password AND does not have 2fa:yes

Field aliases
-------------
  domain / site / url
  email / mail
  user / username / login
  pass / pw / password
  phone
  2fa / mfa / otp
  phrase / seed
  recovery
  type
  linked
  slot / slot-a / slot-b / slot-c
"""

from __future__ import annotations

import shlex
from typing import Callable

from vault_format import SiteEntry

# ── field aliases ─────────────────────────────────────────────────────────────
# maps alias → list of substrings to match against key names (case-insensitive)
_FIELD_ALIASES: dict[str, list[str]] = {
    "domain":    ["__domain__"],
    "site":      ["__domain__"],
    "url":       ["__domain__"],
    "email":     ["website email"],
    "mail":      ["website email"],
    "user":      ["website username"],
    "username":  ["website username"],
    "login":     ["website login using", "website username"],
    "pass":      ["website password"],
    "pw":        ["website password"],
    "password":  ["website password"],
    "phone":     ["website phone"],
    "2fa":       ["2fa"],
    "mfa":       ["2fa"],
    "otp":       ["2fa"],
    "phrase":    ["phrase/seed"],
    "seed":      ["phrase/seed"],
    "recovery":  ["extended recovery"],
    "type":      ["account type"],
    "linked":    ["linked accounts"],
    "slot":      ["slot a", "slot b", "slot c"],
    "slot-a":    ["slot a"],
    "slot-b":    ["slot b"],
    "slot-c":    ["slot c"],
}

_NULL_VALUES = frozenset({"null", "nullaaa", "nullbbb", "nullccc", "nullddd", ""})


# ── haystack builder ─────────────────────────────────────────────────────────

def _build_haystack(entry: SiteEntry) -> dict[str, str]:
    """Return {normalised_key: normalised_value} for an entry."""
    hs: dict[str, str] = {"__domain__": entry.domain.lower()}
    for key, val in entry.lines:
        # keep section prefix in key so 'slot a' still matches 'Add. Data. — Slot A'
        hs[key.lower()] = val.lower()
    return hs


# ── low-level matchers ────────────────────────────────────────────────────────

def _anywhere(term: str, hs: dict[str, str]) -> bool:
    """True when term appears in any field value or the domain."""
    return any(term in v for v in hs.values())


def _field_match(alias: str, value: str, hs: dict[str, str]) -> bool:
    """True when value matches the field(s) identified by alias."""
    targets = _FIELD_ALIASES.get(alias)
    if not targets:
        # fall back to loose key scan for unknown aliases
        for k, v in hs.items():
            if alias in k:
                if value == "*":
                    return v not in _NULL_VALUES
                return value in v
        return False

    for target in targets:
        for k, v in hs.items():
            if target in k:
                if value == "*":
                    return v not in _NULL_VALUES
                return value in v
    return False


# ── tokeniser ─────────────────────────────────────────────────────────────────

def _tokenise(query: str) -> list[tuple[str, str]]:
    """
    Returns a flat list of (kind, value) tokens where kind is one of:
      MATCH   – positive term (plain word, quoted phrase, or field:value)
      NOT     – negative term
      OR      – OR operator (value is "")
    """
    q = query.strip()
    if not q:
        return []

    try:
        raw = shlex.split(q, posix=True)
    except ValueError:
        raw = q.split()

    tokens: list[tuple[str, str]] = []
    i = 0
    while i < len(raw):
        tok = raw[i].lower()
        if tok in ("or", "|"):
            tokens.append(("OR", ""))
            i += 1
        elif tok == "not" and i + 1 < len(raw):
            tokens.append(("NOT", raw[i + 1].lower()))
            i += 2
        elif tok.startswith("-") and len(tok) > 1:
            tokens.append(("NOT", tok[1:]))
            i += 1
        else:
            tokens.append(("MATCH", tok))
            i += 1
    return tokens


# ── expression builder ────────────────────────────────────────────────────────

def _split_or_groups(tokens: list[tuple[str, str]]) -> list[list[tuple[str, str]]]:
    """Split token list on OR operators → list of AND groups."""
    groups: list[list[tuple[str, str]]] = []
    current: list[tuple[str, str]] = []
    for kind, val in tokens:
        if kind == "OR":
            groups.append(current)
            current = []
        else:
            current.append((kind, val))
    groups.append(current)
    return [g for g in groups if g]


def _match_token(kind: str, val: str, hs: dict[str, str]) -> bool:
    """Evaluate a single (MATCH|NOT, value) token against a haystack."""
    if ":" in val:
        alias, _, term = val.partition(":")
        positive = _field_match(alias, term, hs)
    else:
        positive = _anywhere(val, hs)
    return positive if kind == "MATCH" else not positive


def build_matcher(query: str) -> Callable[[SiteEntry], bool]:
    """
    Compile *query* into a fast match function.

    Returns ``lambda entry -> bool``.  Empty / blank query matches everything.
    """
    tokens = _tokenise(query)
    if not tokens:
        return lambda _e: True

    groups = _split_or_groups(tokens)

    def matcher(entry: SiteEntry) -> bool:
        hs = _build_haystack(entry)
        # OR logic: entry matches if ANY AND-group is fully satisfied
        for group in groups:
            if all(_match_token(k, v, hs) for k, v in group):
                return True
        return False

    return matcher


# ── relevance scoring ─────────────────────────────────────────────────────────

def score_entry(query: str, entry: SiteEntry) -> int:
    """
    Return a relevance score (higher = better).  Used for sort-by-relevance.

    Scoring tiers
    -------------
    100  exact full domain match
     80  domain starts with query
     60  domain contains query
     40  username or email contains query
     20  any other field value contains query
    """
    q = query.strip().lower()
    if not q or ":" in q:
        # field queries: just return alphabetical order value
        return 0

    # strip quotes for scoring
    q_bare = q.strip('"').strip("'")
    domain  = entry.domain.lower()
    score   = 0

    if q_bare == domain:
        score += 100
    elif domain.startswith(q_bare):
        score += 80
    elif q_bare in domain:
        score += 60

    for key, val in entry.lines:
        kl = key.lower()
        vl = val.lower()
        if q_bare in vl and vl not in _NULL_VALUES:
            if "username" in kl or "email" in kl:
                score += 40
            else:
                score += 20

    return score


# ── human-readable query description ─────────────────────────────────────────

def describe_query(query: str) -> str:
    """Return a short plain-English description of what the query does."""
    q = query.strip()
    if not q:
        return ""
    tokens = _tokenise(q)
    if not tokens:
        return ""

    parts: list[str] = []
    for kind, val in tokens:
        if kind == "OR":
            parts.append("OR")
        elif kind == "NOT":
            parts.append(f'excluding "{val}"')
        elif ":" in val:
            alias, _, term = val.partition(":")
            if term == "*":
                parts.append(f"{alias} is set")
            else:
                parts.append(f'{alias} contains "{term}"')
        elif val.startswith('"') or " " in val:
            parts.append(f'exact phrase "{val}"')
        else:
            parts.append(f'"{val}"')

    return "  ·  " + "  AND  ".join(p for p in parts if p != "OR")
