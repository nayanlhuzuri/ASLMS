"""The shared `q` of the lists that are not case lists (design `list-search`, decisions 3 and 6).

One validation for every such list: the query is trimmed, 2 to 100 characters, at most 8 words split on white space
(punctuation stays inside a word, so "WP(C)" is one word). A query that is exactly a date ("12 Oct 2025",
`12-10-2025`, `12/10/2025`, `12.10.2025` or `2025-10-12`) also matches the list's date columns on that day (IST for
timestamps); a year on its own is a word. LIKE wildcards in the query match literally. Each list names the columns
a person reads next to its query and passes them to `condition` (SQL) or `matches` (a list built in Python), so a
search only narrows what the list's own conditions already allow. Pure building: no write, no audit."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, and_, false, func, literal, or_, true

from aslms.core.clock import IST, ist_midnight
from aslms.services.case_filters import LIKE_ESCAPE, like_escape

MIN_CHARS = 2
MAX_CHARS = 100
MAX_WORDS = 8

MONTHS = {
    m: i + 1
    for i, m in enumerate(
        ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
    )
}
_PORTAL_DATE = re.compile(r"^(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})$")
_DMY = re.compile(r"^(\d{1,2})([-/.])(\d{1,2})\2(\d{4})$")
_ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")


class ListSearchError(ValueError):
    """A bad list query or cursor: HTTP 400 with `code` (`bad_q` or `bad_cursor`) and the message."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ListQuery:
    raw: str
    words: tuple[str, ...]
    day: date | None


def _safe_date(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def parse_day(text: str) -> date | None:
    """The day of a query that is exactly one of the five accepted date forms; None otherwise."""
    t = text.strip()
    if m := _PORTAL_DATE.match(t):
        month = MONTHS.get(m.group(2)[:3].lower())
        if month is None or (len(m.group(2)) > 3 and not _full_month(m.group(2), month)):
            return None
        return _safe_date(int(m.group(3)), month, int(m.group(1)))
    if m := _DMY.match(t):
        return _safe_date(int(m.group(4)), int(m.group(3)), int(m.group(1)))
    if m := _ISO.match(t):
        return _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def _full_month(word: str, month: int) -> bool:
    names = (
        "january",
        "february",
        "march",
        "april",
        "may",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
    )
    w = word.lower()
    return w == names[month - 1] or (month == 9 and w == "sept")


def parse(q: str | None) -> ListQuery | None:
    """None for an empty query; `ListSearchError("bad_q")` for one shorter than 2 or longer than 100 characters."""
    raw = (q or "").strip()
    if not raw:
        return None
    if len(raw) < MIN_CHARS:
        raise ListSearchError("bad_q", f"Type at least {MIN_CHARS} letters.")
    if len(raw) > MAX_CHARS:
        raise ListSearchError("bad_q", f"A search is at most {MAX_CHARS} characters.")
    words = tuple(raw.split()[:MAX_WORDS])
    return ListQuery(raw=raw, words=words, day=parse_day(raw))


def _like(col: Any, word: str) -> ColumnElement[bool]:
    return func.coalesce(col, literal("")).ilike(f"%{like_escape(word)}%", escape=LIKE_ESCAPE)


def condition(
    lq: ListQuery | None,
    *,
    text: list[Any] | tuple[Any, ...] = (),
    dates: list[Any] | tuple[Any, ...] = (),
    timestamps: list[Any] | tuple[Any, ...] = (),
) -> ColumnElement[bool]:
    """Every word in at least one `text` column (ILIKE, wildcards literal); with a date query, OR a `dates` column
    equal to the day or a `timestamps` column inside that IST day. `true()` without a query."""
    if lq is None:
        return true()
    word_conds = [or_(*[_like(c, w) for c in text]) if text else false() for w in lq.words]
    cond: ColumnElement[bool] = and_(*word_conds) if word_conds else false()
    if lq.day is not None and (dates or timestamps):
        start, end = ist_midnight(lq.day), ist_midnight(lq.day + timedelta(days=1))
        day_conds = [c == lq.day for c in dates] + [and_(c >= start, c < end) for c in timestamps]
        cond = or_(cond, *day_conds)
    return cond


def _fold(text: str) -> str:
    return text.casefold()


def _day_of(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.astimezone(IST).date() if value.tzinfo else value.date()
    if isinstance(value, date):
        return value
    return None


def matches(
    lq: ListQuery | None, texts: list[Any] | tuple[Any, ...], days: list[Any] | tuple[Any, ...] = ()
) -> bool:
    """`condition` for a list built in Python: every word in one of `texts` (case ignored), or a date query on one
    of `days` (dates, or datetimes read in IST)."""
    if lq is None:
        return True
    folded = [_fold(str(t)) for t in texts if t]
    if all(any(_fold(w) in t for t in folded) for w in lq.words):
        return True
    return lq.day is not None and any(_day_of(d) == lq.day for d in days if d is not None)
