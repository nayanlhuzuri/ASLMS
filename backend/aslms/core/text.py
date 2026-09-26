"""Text normalisation shared by parsing, matching and search."""

from __future__ import annotations

import re
import unicodedata

_PUNCT = re.compile(r"[^\w\s/]")
_SPACE = re.compile(r"\s+")
CASE_NO_SPLIT = re.compile(r"^\s*(?P<type>.+?)\s*/\s*0*(?P<no>\d+)\s*/\s*(?P<year>\d{4})\s*$")
CNR_RE = re.compile(r"^[A-Z]{4}\d{12}$")


def normalise_name(text: str | None) -> str:
    """Upper-case, strip accents and punctuation, collapse spaces. 'The State of Assam & Ors.' → 'THE STATE OF ASSAM ORS'."""
    if not text:
        return ""
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    t = _PUNCT.sub(" ", t.upper())
    return _SPACE.sub(" ", t).strip()


def split_case_no(text: str | None) -> tuple[str | None, int | None, int | None]:
    """'WP(C)/0994/2020' → ('WP(C)', 994, 2020); anything else → (None, None, None)."""
    if not text:
        return None, None, None
    m = CASE_NO_SPLIT.match(text)
    if not m:
        return None, None, None
    return m.group("type").strip().upper(), int(m.group("no")), int(m.group("year"))


def canonical_case_no(text: str | None) -> str | None:
    t, n, y = split_case_no(text)
    return f"{t}/{n}/{y}" if t else (text.strip().upper() if text else None)


def is_cnr(text: str | None) -> bool:
    return bool(text and CNR_RE.match(text.strip().upper()))
