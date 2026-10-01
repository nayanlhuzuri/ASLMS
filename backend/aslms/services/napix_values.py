"""Reading NAPIX values: dates come as `yyyy-mm-dd`, `""`, `null`, the sentinel `5000-01-01` (Current Status
for "no next date") or `Next Date Not Given`; numbers come as int or numeric string; nested blocks as
`case1…`, `sr_no1…`, `party_no1…` dicts or as JSON lists (empty ones as `[]`)."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

NO_DATE = {"", "5000-01-01", "0000-00-00", "1900-01-01"}
TRAILING_NUMBER = re.compile(r"(\d+)$")


def as_date(v: Any) -> date | None:
    if v is None:
        return None
    s = str(v).strip()
    if s in NO_DATE or not s[:1].isdigit():
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s[:19] if fmt.endswith("%S") else s[:10], fmt).date()
        except ValueError:
            continue
    return None


def as_int(v: Any) -> int | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    s = str(v).strip()
    if not s:
        return None
    m = re.match(r"^-?\d+", s)
    return int(m.group(0)) if m else None


def as_text(v: Any, limit: int | None = None) -> str | None:
    if v is None:
        return None
    s = re.sub(r"\s+", " ", str(v)).strip()
    if not s:
        return None
    return s[:limit] if limit else s


def as_bool_yn(v: Any) -> bool | None:
    s = as_text(v)
    if s is None:
        return None
    return s.upper() in {"Y", "YES", "1", "TRUE"}


def block_items(v: Any) -> list[tuple[int, dict[str, Any]]]:
    """`{"sr_no1": {...}, "sr_no2": {...}}` or `[{...}, {...}]` → [(1, {...}), (2, {...})] in number order."""
    if not v:
        return []
    if isinstance(v, list):
        return [(i, x) for i, x in enumerate(v, start=1) if isinstance(x, dict)]
    if isinstance(v, dict):
        out = []
        for k, x in v.items():
            if not isinstance(x, dict):
                continue
            m = TRAILING_NUMBER.search(k)
            out.append((int(m.group(1)) if m else len(out) + 1, x))
        return sorted(out, key=lambda t: t[0])
    return []


def numbered_values(v: Any, prefix: str) -> list[tuple[int, str]]:
    """`{"party_no1": "A", "party_no2": "B"}` → [(1, "A"), (2, "B")]; `[]` → []."""
    if not isinstance(v, dict):
        return []
    out = []
    for k, x in v.items():
        if not k.startswith(prefix):
            continue
        m = TRAILING_NUMBER.search(k)
        t = as_text(x)
        if m and t:
            out.append((int(m.group(1)), t))
    return sorted(out, key=lambda t: t[0])


def leading_code(v: Any) -> int | None:
    """`10160 - Other land matters…` → 10160."""
    s = as_text(v)
    if not s:
        return None
    m = re.match(r"^(\d+)\s*-", s)
    return int(m.group(1)) if m else None


def case_no_text(type_name: Any, no: Any, year: Any) -> str | None:
    t, n, y = as_text(type_name), as_int(no), as_int(year)
    if t and n is not None and y is not None:
        return f"{t}/{n}/{y}"
    return None
