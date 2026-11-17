"""The order reader (design `order-sections`, decisions 7 to 17): a court order's stored text read into its parts by
rules, with no AI.

Pure: no database, no network, no model and no model library (`re`, `hashlib`, `bisect`, `statistics` only); the
patterns are in `order_parse_rules.py`. The reader never edits `full_text`. Every span is a pair of 0-based code-point
offsets, end exclusive: `src` into `full_text`, `txt` into the cleaned `body_text`; Python indexes and PostgreSQL
`substr(full_text, s + 1, e - s)` agree. Pages are PDF pages (1-based): the printed `Page No.# n/N` before a position
when the markers are present, else the form feeds before it plus 1.

- `parse(full_text, order_date=, napix_kind=)` returns a `Parsed` (every column of `order_sections` except the keys and
  the hashes of the source). It never raises on court text; an unexpected exception is a bug, recorded by the caller.
- `next_date_span(body_text, phrase)` finds the stored next-date sentence in the cleaned body (decision 19)."""

from __future__ import annotations

import bisect
import hashlib
import re
import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from aslms.services import order_parse_rules as R

INTERIM, FINAL, JUDGMENT = "interim", "final", "judgment"
TEMPLATE, WHOLE = "template", "whole"


# ------------------------------------------------------------------------------------------------ data


@dataclass(frozen=True)
class Line:
    """One line of `full_text`: `start` and `end` (without the newline) are offsets into the text."""

    i: int
    start: int
    end: int
    raw: str

    @property
    def text(self) -> str:
        return self.raw.replace("\f", "")

    @property
    def blank(self) -> bool:
        return not self.text.strip()


@dataclass
class PageMap:
    """Decision 9: the page a position falls on."""

    feeds: list[int]
    marks: list[tuple[int, int]]  # (offset of the marker line, printed page number)
    differ: bool

    def page(self, pos: int) -> int:
        if self.marks:
            i = bisect.bisect_right([m[0] for m in self.marks], pos) - 1
            if i >= 0:
                return self.marks[i][1]
            # before the first printed marker (version 2, design `order-sections-review-advisories`, decision 4): the
            # first marker's number less the form feeds between the position and that marker, never below 1
            first_at, first_no = self.marks[0]
            between = bisect.bisect_right(self.feeds, first_at) - bisect.bisect_right(self.feeds, pos)
            return max(1, first_no - between)
        return bisect.bisect_right(self.feeds, pos) + 1


@dataclass
class Spans:
    """Decisions 7 and 8: what was found, as line indexes and offsets."""

    layout: str = WHOLE
    spans: dict[str, list[int]] = field(default_factory=dict)
    linked_cases: list[dict[str, Any]] = field(default_factory=list)
    printed_cnr: str | None = None
    printed_case_no: str | None = None
    printed_date: date | None = None
    printed_reserved_on: date | None = None
    printed_pronounced_on: date | None = None
    neutral_citation: str | None = None
    heading: str | None = None
    oral: bool = False
    cav: bool = False
    author: str | None = None
    registrar: bool = False
    body: tuple[int, int] = (0, 0)
    dropped: set[int] = field(default_factory=set)  # lines never part of the body (header, markers, sign-off)


@dataclass
class Paragraph:
    i: int
    label: str | None
    src: tuple[int, int]
    txt: tuple[int, int]
    page: int = 1
    page_to: int = 1
    part: str = R.PART_BODY

    def as_dict(self) -> dict[str, Any]:
        return {
            "i": self.i,
            "label": self.label,
            "page": self.page,
            "page_to": self.page_to,
            "src": list(self.src),
            "txt": list(self.txt),
            "part": self.part,
        }


@dataclass
class Parsed:
    """Every column of `order_sections` the text gives (decision 15 for the flags)."""

    text_chars: int
    parser_version: int
    layout: str
    form: str
    heading: str | None
    oral: bool
    cav: bool
    printed_cnr: str | None
    printed_case_no: str | None
    printed_date: date | None
    printed_reserved_on: date | None
    printed_pronounced_on: date | None
    neutral_citation: str | None
    author: str | None
    registrar: bool
    procedural: bool
    outcome: str | None
    spans: dict[str, list[int]]
    linked_cases: list[dict[str, Any]]
    body_text: str
    body_sha256: str
    paragraphs: list[dict[str, Any]]
    parts: list[dict[str, Any]]
    facts: dict[str, Any]
    flags: list[str]

    def columns(self) -> dict[str, Any]:
        return dict(self.__dict__)


# ------------------------------------------------------------------------------------------------ small helpers


def _lines(text: str) -> list[Line]:
    out: list[Line] = []
    pos = 0
    n = len(text)
    i = 0
    while pos <= n:
        nl = text.find("\n", pos)
        end = n if nl < 0 else nl
        out.append(Line(i, pos, end, text[pos:end]))
        i += 1
        if nl < 0:
            break
        pos = nl + 1
    return out


def _date(d: str, m: str, y: str) -> date | None:
    try:
        return date(int(y), int(m), int(d))
    except ValueError:
        return None


def _date_of(match: re.Match[str] | None) -> date | None:
    return _date(match.group("d"), match.group("m"), match.group("y")) if match else None


def _collapse(s: str) -> str:
    return " ".join(s.split())


def _clip(s: str, n: int) -> str:
    s = _collapse(s)
    return s[:n]


def body_hash(body_text: str) -> str:
    """Decision 16: SHA-256 of the body with whitespace runs collapsed to one space and trimmed; case and punctuation
    kept, so two bodies with one hash have the same words character for character."""
    return hashlib.sha256(_collapse(body_text).encode("utf-8")).hexdigest()


# ------------------------------------------------------------------------------------------------ pages (9)


def pages(text: str) -> PageMap:
    feeds = [m.start() for m in re.finditer("\f", text)]
    marks: list[tuple[int, int]] = []
    for m in R.PAGE_MARK.finditer(text):
        try:
            marks.append((m.start(), int(m.group(1) or m.group(2))))
        except ValueError:  # pragma: no cover - the pattern holds digits only
            continue
    differ = any(n != bisect.bisect_right(feeds, pos) + 1 for pos, n in marks)
    return PageMap(feeds, marks, differ)


# ------------------------------------------------------------------------------------------------ locate (7, 8)


def _next_nonblank(lines: list[Line], i: int, limit: int, skip: set[int] | None = None) -> list[int]:
    """Up to `limit` indexes of non-blank lines from `i` on, page markers skipped."""
    out: list[int] = []
    j = i
    while j < len(lines) and len(out) < limit:
        ln = lines[j]
        if not ln.blank and not R.PAGE_MARK.match(ln.raw) and (skip is None or j not in skip):
            out.append(j)
        j += 1
    return out


def _is_coram(lines: list[Line], j: int) -> tuple[bool, bool]:
    """(is a coram marker, the bench is on the same line)."""
    t = lines[j].text
    if R.CORAM_MARK.match(t):
        word = re.sub(r"[^A-Za-z]", "", t).upper()
        if word == "BEFORE":
            return True, False
        # CORAM / PRESENT alone: only when a judge's line follows
        nxt = _next_nonblank(lines, j + 1, 1)
        return (bool(nxt) and bool(R.JUDGE_LINE.search(lines[nxt[0]].text))), False
    m = R.CORAM_INLINE.match(t)
    if m and R.JUDGE_LINE.search(m.group(1)):
        return True, True
    return False, False


def locate(text: str, pm: PageMap) -> Spans:  # noqa: C901 - one walk down the template, step by step
    lines = _lines(text)
    sp = Spans()
    n = len(lines)
    for ln in lines:
        if R.PAGE_MARK.match(ln.raw):
            sp.dropped.add(ln.i)

    def span(name: str, first: int, last: int) -> None:
        sp.spans[name] = [lines[first].start + _lead(lines[first]), lines[last].end - _trail(lines[last])]

    # (2) the CNR line, then `undefined` or the neutral citation; (3) the court header
    header_last = -1
    for j in range(min(n, R.HEADER_SCAN_LINES)):
        m = R.CNR_LINE.match(lines[j].text)
        if m:
            sp.printed_cnr = m.group(1).upper()
            span("cnr", j, j)
            sp.dropped.add(j)
            header_last = max(header_last, j)
            break
    for j in range(min(n, R.HEADER_SCAN_LINES + 4)):
        t = lines[j].text
        if R.UNDEFINED.match(t):
            sp.dropped.add(j)
            header_last = max(header_last, j)
        else:
            m = R.NEUTRAL_CITATION.match(t)
            if m and sp.neutral_citation is None:
                sp.neutral_citation = m.group(1).upper()[:40]
                sp.dropped.add(j)
                header_last = max(header_last, j)
    for j in range(n):  # the court header, repeated or not, is never body
        t = lines[j].text
        if R.COURT_HEADER.match(t) or (R.COURT_HEADER_SUB.match(t) and j < R.HEADER_SCAN_LINES * 4):
            sp.dropped.add(j)
            if j < R.HEADER_SCAN_LINES + 4:
                header_last = max(header_last, j)
        elif R.TRAILER.match(t):
            sp.dropped.add(j)
    # (4) Case No.
    case_i = None
    for j in range(min(n, R.CASE_NO_SCAN_LINES)):
        m = R.CASE_NO.match(lines[j].text)
        if m:
            case_i = j
            value = _collapse(m.group(1))
            sp.printed_case_no = value[: R.CASE_NO_MAX] or None
            span("case_no", j, j)
            header_last = max(header_last, j)
            break
    if header_last >= 0:
        span("header", 0, header_last)

    # (8) the coram marker, after the case number (or the header)
    start = (case_i if case_i is not None else header_last) + 1
    coram_i = coram_last = None
    for j in range(max(start, 0), n):
        is_marker, inline = _is_coram(lines, j)
        if not is_marker:
            continue
        coram_i = coram_last = j
        if not inline:
            for k in _next_nonblank(lines, j + 1, 6):
                if R.JUDGE_LINE.search(lines[k].text) and not R.HEADING.match(lines[k].text):
                    coram_last = k
                else:
                    break
        break
    if coram_i is not None:
        span("coram", coram_i, coram_last)
        coram_text = " ".join(lines[k].text for k in range(coram_i, coram_last + 1))
        sp.registrar = bool(R.REGISTRAR_CORAM.search(coram_text)) and not re.search(
            r"\bJUSTICE\b", coram_text, re.I
        )

    # (5) the cause title, (6) the advocates, (7) the linked cases: between the case number and the coram
    title_end_i = coram_i if coram_i is not None else n
    stops = []
    for j in range(max(start, 0), title_end_i):
        t = lines[j].text
        if R.ADVOCATES.match(t) or R.LINKED_CASE.match(t) or R.JUDGMENT_DATE_LINE.match(t):
            stops.append(j)
    if case_i is not None and (stops or coram_i is not None):
        first_stop = stops[0] if stops else coram_i
        body_lines = [k for k in range(case_i + 1, first_stop) if not lines[k].blank and k not in sp.dropped]
        if body_lines:
            span("cause_title", body_lines[0], body_lines[-1])
    linked = [j for j in range(max(start, 0), title_end_i) if R.LINKED_CASE.match(lines[j].text)]
    adv_first = next((j for j in range(max(start, 0), title_end_i) if R.ADVOCATES.match(lines[j].text)), None)
    if adv_first is not None and (not linked or adv_first < linked[0]):
        adv_stop = linked[0] if linked else title_end_i
        date_lines = [j for j in range(adv_first, adv_stop) if R.JUDGMENT_DATE_LINE.match(lines[j].text)]
        if date_lines:
            adv_stop = date_lines[0]
        adv = [k for k in range(adv_first, adv_stop) if not lines[k].blank and k not in sp.dropped]
        if adv:
            span("advocates", adv[0], adv[-1])
    for idx, j in enumerate(linked):
        if idx + 1 < len(linked):
            block_end = linked[idx + 1]
        elif coram_i is not None:
            block_end = title_end_i
        else:  # no coram bounds the last block (version 2): it ends where the block ends, or is cut to its line
            block_end = _linked_block_end(lines, j, sp.dropped)
        content = [k for k in range(j, block_end) if not lines[k].blank and k not in sp.dropped]
        last = content[-1] if content else j
        title_lines: list[int] = []
        for k in content[1:]:
            t = lines[k].text
            if R.ADVOCATES.match(t) or R.RULE_LINE.match(t) or R.JUDGMENT_DATE_LINE.match(t):
                break
            title_lines.append(k)
        case_no = _collapse(R.LINKED_CASE.match(lines[j].text).group(1))[: R.CASE_NO_MAX] or None
        sp.linked_cases.append(
            {
                "case_no": case_no,
                "src": [lines[j].start + _lead(lines[j]), lines[last].end - _trail(lines[last])],
                "title": (
                    [lines[title_lines[0]].start + _lead(lines[title_lines[0]]),
                     lines[title_lines[-1]].end - _trail(lines[title_lines[-1]])]
                    if title_lines
                    else None
                ),
            }
        )  # fmt: skip

    # (10) the heading, (9) the judgment dates, (11) the date, (12) the author
    heading_i = heading_last = None
    after = (coram_last + 1) if coram_last is not None else None
    if after is not None:
        for k in _next_nonblank(lines, after, R.HEADING_SCAN_LINES):
            t = lines[k].text
            if R.JUDGMENT_DATE_LINE.match(t):
                continue
            vertical = _vertical_heading(lines, k)
            if vertical is not None:
                heading_i = k
                sp.heading = vertical[0]
                heading_last = vertical[1]
                break
            hm = R.HEADING.match(t)
            if hm:
                heading_i = k
                sp.heading = _heading_text(hm.group("h"))
                if hm.group("date"):
                    sp.printed_date = _date_of(hm)
                sp.oral = bool(R.ORAL.search(hm.group("rest") or ""))
                sp.cav = bool(R.CAV.search(hm.group("rest") or ""))
                if hm.group("author"):
                    sp.author = _author(hm.group("author")[1:-1])
                heading_last = k
                break
    # the judgment-date block anywhere between the case number and a few lines after the heading
    block_stop = (heading_i + R.DATE_SCAN_LINES + 2) if heading_i is not None else min(n, title_end_i + 12)
    jd = [j for j in range(max(start, 0), min(n, block_stop)) if R.JUDGMENT_DATE_LINE.match(lines[j].text)]
    for j in jd:
        t = lines[j].text
        d = _date_of(R.JUDGMENT_DATE_LINE.match(t))
        if R.RESERVED_WORDS.search(t):
            sp.printed_reserved_on = sp.printed_reserved_on or d
        elif R.PRONOUNCED_WORDS.search(t) and not R.OPERATIVE_WORDS.search(t):
            sp.printed_pronounced_on = sp.printed_pronounced_on or d
    if jd:
        span("judgment_dates", jd[0], jd[-1])
    body_start_i = None
    if heading_i is not None:
        span("heading", heading_i, heading_last)
        body_start_i = _after_heading(lines, heading_last, sp, span)
    elif coram_last is not None:
        # no printed heading, the order date straight after the bench (older and division-bench orders): still the
        # court's template, with no heading (Deviations of the design note)
        after_date = _after_heading(lines, coram_last, sp, span)
        if sp.printed_date is not None:
            body_start_i = after_date
    # (14) the trailer and the sign-off, from the end
    end_i = n - 1
    while end_i >= 0 and (lines[end_i].blank or R.PAGE_MARK.match(lines[end_i].raw)):
        end_i -= 1
    signoff_first = None
    j = end_i
    # the trailer is the last line, or a few lines before a digital signature's block
    for k in range(end_i, max(end_i - R.TRAILER_SCAN_LINES, -1), -1):
        if R.TRAILER.match(lines[k].text):
            signoff_first, j = k, k - 1
            break
    floor = body_start_i if body_start_i is not None else (coram_last + 1 if coram_last is not None else 0)
    while j >= floor:
        ln = lines[j]
        if ln.blank or R.PAGE_MARK.match(ln.raw):
            j -= 1
            continue
        if R.SIGNOFF_LINE.match(ln.text) and R.SIGNOFF_WORD.search(ln.text):
            signoff_first = j
            j -= 1
            continue
        break
    if signoff_first is not None:
        sp.spans["signoff"] = [lines[signoff_first].start + _lead(lines[signoff_first]), len(text.rstrip())]
        for k in range(signoff_first, n):
            sp.dropped.add(k)
    body_end = lines[signoff_first].start if signoff_first is not None else len(text)

    # (13) the body; the layout (8)
    if coram_i is not None and body_start_i is not None:
        sp.layout = TEMPLATE
        bs = lines[body_start_i].start if body_start_i is not None and body_start_i < n else body_end
    else:
        sp.layout = WHOLE
        bs = 0
        # decision 8: an off-template order keeps no cause title, advocates or coram span (row 258 skips such a title
        # rather than guess), even when a coram marker was found
        for name in ("cause_title", "advocates", "coram"):
            sp.spans.pop(name, None)
    bs = min(bs, body_end)
    sp.body = (bs, body_end)
    if body_end > bs:
        trimmed = _trim(text, bs, body_end)
        if trimmed:
            sp.spans["body"] = list(trimmed)

    # (11) the date of an off-template order, and the judgment's fallbacks: the pronouncement line, a closing `Date:`
    if sp.printed_date is None and sp.heading and R.JUDGMENT_WORD.search(sp.heading):
        if sp.printed_pronounced_on is not None:
            sp.printed_date = sp.printed_pronounced_on
        else:
            stop = signoff_first if signoff_first is not None else n
            for k in range(stop - 1, max(stop - R.CLOSING_DATE_LINES, 0) - 1, -1):
                dm = R.DATE_LINE.match(lines[k].text)
                if dm and re.search(r"\bDate", lines[k].text, re.I):
                    sp.printed_date = _date_of(R.DATE_RE.search(lines[k].text))
                    span("date", k, k)
                    break
    return sp


def _linked_block_end(lines: list[Line], j: int, dropped: set[int]) -> int:
    """Version 2 (design `order-sections-review-advisories`, decision 3): the end (exclusive line index) of the last
    `Linked Case :` block at line `j` when no coram line bounds it. The block ends before the first heading,
    judgment-date line, coram marker or further `Linked Case :` line, or after the last line of its advocates run: the
    first `Advocate for` line, then further advocates lines, rule lines and continuation lines (a non-blank line
    directly after a line of the run, with no blank line between, that is not a paragraph start, a heading or a date
    line; blank lines next to a page break do not count). When neither comes within `LINKED_BLOCK_MAX_LINES`
    non-blank lines the block is cut to its own line (`j + 1`), so its title is null."""
    last = j
    in_run = False
    blank = False
    near_page = False
    seen = 0
    for k in range(j + 1, len(lines)):
        ln = lines[k]
        page_line = bool(R.PAGE_MARK.match(ln.raw))
        if page_line or "" in ln.raw:
            near_page, blank = True, False
            if page_line or ln.blank:
                continue
        if k in dropped:
            continue
        if ln.blank:
            if not near_page:
                blank = True
            continue
        t = ln.text
        if (
            R.HEADING.match(t)
            or _vertical_heading(lines, k) is not None
            or R.JUDGMENT_DATE_LINE.match(t)
            or R.CORAM_MARK.match(t)
            or R.LINKED_CASE.match(t)
        ):
            return last + 1  # (a)
        if in_run and not (R.ADVOCATES.match(t) or R.RULE_LINE.match(t)):
            if blank or R.PARA_START.match(t) or R.DATE_LINE.match(t):
                return last + 1  # (b) the advocates run has ended
        if seen >= R.LINKED_BLOCK_MAX_LINES:
            return j + 1  # (c) not bounded within the cap: cut to its own line
        in_run = in_run or bool(R.ADVOCATES.match(t))
        last = k
        seen += 1
        blank = near_page = False
    return last + 1 if in_run else j + 1


def _after_heading(lines: list[Line], k0: int, sp: Spans, span, *, author: bool = True) -> int:
    """(11) and (12): the order date (`dd.mm.yyyy`, `Date : dd.mm.yyyy`, or broken across two lines) and the author in
    the few non-blank lines after the heading (or after the coram of an off-template order). Returns the index of the
    first line after them."""
    after = k0 + 1
    nxt = _next_nonblank(lines, k0 + 1, R.DATE_SCAN_LINES)
    pos = 0
    while pos < len(nxt):
        k = nxt[pos]
        t = lines[k].text
        if R.JUDGMENT_DATE_LINE.match(t):
            after, pos = k + 1, pos + 1
            continue
        if sp.printed_date is None:
            if R.DATE_LINE.match(t):
                sp.printed_date = _date_of(R.DATE_RE.search(t))
                span("date", k, k)
                after, pos = k + 1, pos + 1
                continue
            if R.DATE_HEAD.match(t) and pos + 1 < len(nxt) and R.DATE_TAIL.match(lines[nxt[pos + 1]].text):
                k2 = nxt[pos + 1]
                sp.printed_date = _date_of(R.DATE_RE.search(re.sub(r"\s+", "", t + lines[k2].text)))
                span("date", k, k2)
                after, pos = k2 + 1, pos + 2
                continue
        if author and sp.author is None:
            am = R.AUTHOR.match(t)
            if am and R.AUTHOR_JUDGE.search(am.group(1)):
                sp.author = _author(am.group(1))
                span("author", k, k)
                after, pos = k + 1, pos + 1
                continue
            pm_ = R.AUTHOR_PER.match(t)
            if pm_:
                sp.author = _author(pm_.group(1))
                span("author", k, k)
                after, pos = k + 1, pos + 1
                continue
        break
    return after


def _vertical_heading(lines: list[Line], k: int) -> tuple[str, int] | None:
    """A heading printed a letter or two per line: (the word, the index of its last line)."""
    if not R.VERTICAL_PIECE.match(lines[k].text):
        return None
    letters = ""
    for j in _next_nonblank(lines, k, 8):
        if not R.VERTICAL_PIECE.match(lines[j].text):
            break
        letters += re.sub(r"\s+", "", lines[j].text).upper()
        if letters in R.VERTICAL_WORDS:
            return letters, j
    return None


def _heading_text(h: str) -> str | None:
    """The heading as printed, whitespace collapsed, a spaced-out word (`O R D E R`) closed up."""
    out: list[str] = []
    run = ""
    for tok in h.split():
        if len(tok) == 1 and tok.isalpha():
            run += tok
            continue
        if run:
            out.append(run)
            run = ""
        out.append(tok)
    if run:
        out.append(run)
    return " ".join(out)[: R.HEADING_MAX] or None


def _lead(ln: Line) -> int:
    return len(ln.raw) - len(ln.raw.lstrip())


def _trail(ln: Line) -> int:
    return len(ln.raw) - len(ln.raw.rstrip())


def _trim(text: str, s: int, e: int) -> tuple[int, int] | None:
    while s < e and text[s].isspace():
        s += 1
    while e > s and text[e - 1].isspace():
        e -= 1
    return (s, e) if e > s else None


def _author(s: str) -> str | None:
    s = _collapse(s)
    return s[: R.AUTHOR_MAX] or None


# ------------------------------------------------------------------------------------------------ clean (10, 11)


@dataclass
class _Logical:
    """A cleaned line of the body: its characters with the `full_text` offset of each."""

    chars: list[str]
    src: list[int]

    @property
    def text(self) -> str:
        return "".join(self.chars)


def _clean_line(text: str, ln: Line, lo: int, hi: int) -> _Logical | None:
    """The line's characters within [lo, hi), whitespace runs collapsed to one space, trimmed, form feeds dropped."""
    s = max(ln.start, lo)
    e = min(ln.end, hi)
    chars: list[str] = []
    src: list[int] = []
    pending_space = -1
    for pos in range(s, e):
        ch = text[pos]
        if ch.isspace():
            if chars and pending_space < 0:
                pending_space = pos
            continue
        if pending_space >= 0:
            chars.append(" ")
            src.append(pending_space)
            pending_space = -1
        chars.append(ch)
        src.append(pos)
    return _Logical(chars, src) if chars else None


def clean(text: str, sp: Spans, pm: PageMap) -> tuple[str, list[int], list[Paragraph]]:  # noqa: C901
    """Decision 10 with decision 11: the body region's lines, without page markers, the header lines, the sign-off and
    the trailer, rejoined into paragraphs separated by a blank line. Returns `body_text`, the map from every
    `body_text` position to its `full_text` position, and the paragraphs with their `src` and `txt` spans."""
    bs, be = sp.body
    if be <= bs:
        return "", [], []
    lines = [ln for ln in _lines(text) if ln.end > bs and ln.start < be]
    items: list[tuple[str, Any]] = []  # ("text", _Logical) | ("blank", None) | ("page", None)
    for ln in lines:
        if R.PAGE_MARK.match(ln.raw):
            items.append(("page", None))
            continue
        if ln.i in sp.dropped:
            continue
        lg = _clean_line(text, ln, bs, be)
        items.append(("blank", None) if lg is None else ("text", lg))
    texts = [lg for kind, lg in items if kind == "text"]
    if not texts:
        return "", [], []
    numbered = sum(1 for lg in texts if R.PARA_START.match(lg.text)) >= 1
    median = statistics.median(len(lg.text) for lg in texts)

    paras: list[tuple[str | None, list[str], list[int]]] = []
    prev: _Logical | None = None
    blank = False
    near_page = False
    for kind, lg in items:
        if kind == "page":
            near_page = True
            blank = False
            continue
        if kind == "blank":
            if not near_page:
                blank = True
            continue
        t = lg.text
        label = None
        new = prev is None
        if not new:
            pt = prev.text
            num = R.PARA_START.match(t)
            sub = R.SUBLIST_START.match(t)
            if num and not R.REFERENCE_END.search(pt):
                new, label = True, num.group("label")
            elif sub and R.LIST_INTRO_END.search(pt):
                new, label = True, sub.group("label")
            elif blank and R.SENTENCE_END.search(pt):
                new = True
            elif not numbered and R.SHORT_LINE_END.search(pt) and len(pt) < R.SHORT_LINE_SHARE * median:
                new = True
        else:
            num = R.PARA_START.match(t)
            label = num.group("label") if num else None
        if new:
            paras.append((label, list(lg.chars), list(lg.src)))
        else:
            _, chars, src = paras[-1]
            if not (chars and chars[-1] == "-"):
                chars.append(" ")
                src.append(src[-1] + 1)
            chars.extend(lg.chars)
            src.extend(lg.src)
        prev = lg
        blank = False
        near_page = False

    body_chars: list[str] = []
    omap: list[int] = []
    out: list[Paragraph] = []
    for idx, (label, chars, src) in enumerate(paras):
        if body_chars:
            body_chars.extend("\n\n")
            omap.extend((omap[-1] + 1, omap[-1] + 1))
        t0 = len(body_chars)
        body_chars.extend(chars)
        omap.extend(src)
        t1 = len(body_chars)
        s0, s1 = src[0], src[-1] + 1
        out.append(
            Paragraph(
                i=idx,
                label=_clip(label, 12) if label else None,
                src=(s0, s1),
                txt=(t0, t1),
                page=pm.page(s0),
                page_to=pm.page(s1 - 1),
            )
        )
    return "".join(body_chars), omap, out


# ------------------------------------------------------------------------------------------------ parts (12)


def _para_text(body_text: str, p: Paragraph) -> str:
    t = body_text[p.txt[0] : p.txt[1]]
    if p.label and t.startswith(p.label):
        t = t[len(p.label) :]
    return t.lstrip(" .-:")


def _marker(text: str, *, first: bool, late: bool) -> str | None:
    """The part a paragraph opens, if any: a heading word, else (among the first paragraphs) the opening formula, else
    a standard phrase near its start; a conclusion phrase counts only in the later half of the body ("Accordingly"
    and "in view of the above" open many paragraphs mid-judgment)."""
    head = text[: R.PHRASE_WINDOW]
    for part, rx in R.PART_HEADINGS:
        if rx.match(head):
            return part
    if first and R.OPENING_PHRASES.match(head):
        return R.PART_OPENING
    for part, rx in R.PART_PHRASES:
        if part == "conclusion" and not late:
            continue
        if rx.search(head):
            return part
    return None


def parts(body_text: str, paras: list[Paragraph], form: str, pm: PageMap) -> list[dict[str, Any]]:
    """Decision 12: an interim order's body is one part; a judgment's or final order's paragraphs are grouped, in
    order, by their opening heading or standard phrase, each inheriting the previous part otherwise. Without a marker
    (other than the opening) the whole body is one `body` part. A part never cuts a paragraph. Paragraphs before the
    first marker are the `opening` when the first carries the "Heard" formula, else the `facts`."""
    if not paras:
        return []
    names: list[str] = [R.PART_BODY] * len(paras)
    if form != INTERIM:
        half = len(body_text) * R.CONCLUSION_FROM_SHARE
        found = [
            _marker(_para_text(body_text, p), first=p.i < R.OPENING_PARAGRAPHS, late=p.txt[0] >= half)
            for p in paras
        ]
        if any(f not in (None, R.PART_OPENING) for f in found):
            current = R.PART_OPENING if found[0] == R.PART_OPENING else "facts"
            for k, f in enumerate(found):
                if f is not None:
                    current = f
                elif current == R.PART_OPENING:
                    current = "facts"  # the opening is only the "Heard" and appearance paragraphs themselves
                names[k] = current
    for p, name in zip(paras, names, strict=True):
        p.part = name
    out: list[dict[str, Any]] = []
    for p in paras:
        if out and out[-1]["part"] == p.part:
            last = out[-1]
            last["last"] = p.i
            last["src"][1] = p.src[1]
            last["txt"][1] = p.txt[1]
        else:
            out.append(
                {
                    "part": p.part,
                    "first": p.i,
                    "last": p.i,
                    "page": p.page,
                    "src": [p.src[0], p.src[1]],
                    "txt": [p.txt[0], p.txt[1]],
                }
            )
    return out


# ------------------------------------------------------------------------------------------------ facts (17)


def _sentences(body: str) -> list[tuple[int, int]]:
    """Sentence spans of the body: a full stop, `?` or `!` followed by space and not lower case, unless it ends an
    abbreviation or an initial; a blank line always ends one."""
    out: list[tuple[int, int]] = []
    start = 0
    for m in re.finditer(r"[.?!](?=\s)|\n\n", body):
        pos = m.start()
        if m.group() == "\n\n":
            end = pos
        else:
            if m.group() == ".":
                k = pos
                while k > 0 and not body[k - 1].isspace() and body[k - 1] not in "([":
                    k -= 1
                token = body[k:pos].lower().strip("\"'(")
                if token in R.ABBREVIATIONS or len(token) == 1 or re.fullmatch(r"(?:[a-z]\.)+[a-z]?", token):
                    continue
            nxt = re.match(r"\s*(\S)", body[pos + 1 :])
            if nxt and nxt.group(1).islower():
                continue
            end = pos + 1
        s, e = start, end
        while s < e and body[s].isspace():
            s += 1
        if e > s:
            out.append((s, e))
        start = end
    s, e = start, len(body)
    while s < e and body[s].isspace():
        s += 1
    while e > s and body[e - 1].isspace():
        e -= 1
    if e > s:
        out.append((s, e))
    return out


def _sentence_of(sentences: list[tuple[int, int]], pos: int) -> tuple[int, int]:
    starts = [s for s, _ in sentences]
    i = bisect.bisect_right(starts, pos) - 1
    return sentences[max(i, 0)] if sentences else (0, 0)


class _Locator:
    """`txt` → `src` and page for a span of the body."""

    def __init__(self, omap: list[int], pm: PageMap) -> None:
        self.omap = omap
        self.pm = pm

    def item(self, s: int, e: int) -> dict[str, Any]:
        src0 = self.omap[s]
        src1 = self.omap[e - 1] + 1
        return {"page": self.pm.page(src0), "src": [src0, src1], "txt": [s, e]}


def outcome(body: str, sentences: list[tuple[int, int]], loc: _Locator) -> dict[str, Any] | None:
    """Decision 17: the outcome of the main matter, from the last sentence in the body whose subject is the main
    matter (never an interlocutory application, a Misc. Case or an I.A.)."""
    best: tuple[int, str, tuple[int, int]] | None = None
    for s, e in sentences:
        sentence = body[s:e]
        found: tuple[int, str] | None = None
        for value, rx in R.OUTCOME_PATTERNS:
            for m in rx.finditer(sentence):
                if R.NEGATION.search(m.group("gap") or "") or R.NEGATION.search(
                    sentence[m.end("gap") : m.start("verb")]
                ):
                    continue
                before = sentence[max(0, m.start("subj") - R.SUBJECT_LOOKBACK) : m.start("subj")]
                if R.INTERLOCUTORY.search(before) or R.INTERLOCUTORY.search(m.group("subj")):
                    continue
                if found is None or m.start() >= found[0]:
                    found = (m.start(), value)
                break
            if found is not None and found[1] == value:
                break
        wm = R.WITHDRAW_PATTERN.search(sentence)
        if wm and not R.INTERLOCUTORY.search(
            sentence[max(0, wm.start("subj") - R.SUBJECT_LOOKBACK) : wm.start("subj")]
        ):
            found = (wm.start(), "withdrawn")
        if found is not None:
            best = (s, found[1], (s, e))
    if best is None:
        return None
    s, value, (a, b) = best
    b = min(b, a + R.OUTCOME_TEXT_MAX)
    return {"value": value, "text": body[a:b], **loc.item(a, b)}


def _add_months(d: date, n: int) -> date:
    month = d.month - 1 + n
    year = d.year + month // 12
    month = month % 12 + 1
    for day in (d.day, 30, 29, 28):
        try:
            return date(year, month, day)
        except ValueError:
            continue
    return date(year, month, 28)  # pragma: no cover


def _period(sentence: str, base: date | None) -> tuple[dict[str, Any] | None, str | None]:
    m = R.PERIOD.search(sentence)
    if not m:
        return None, None
    raw_n = m.group("n").lower()
    n = int(raw_n) if raw_n.isdigit() else R.NUMBER_WORDS.get(raw_n)
    if not n:
        return None, None
    unit = m.group("unit").lower().rstrip("s") + "s"
    frm_text = (m.group("from") or "").strip()
    if not frm_text:
        frm = "none"
    elif R.FROM_ORDER_DATE.match(frm_text):
        frm = "order_date"
    elif R.FROM_RECEIPT.search(frm_text):
        frm = "receipt_of_copy"
    else:
        frm = "other"
    due = None
    if frm == "order_date" and base is not None:
        if unit == "days":
            due = base + timedelta(days=n)
        elif unit == "weeks":
            due = base + timedelta(weeks=n)
        else:
            due = _add_months(base, n)
    return (
        {"n": n, "unit": unit, "from": frm, "phrase": _collapse(m.group(0))[:300]},
        due.isoformat() if due else None,
    )


def directions(
    body: str, sentences: list[tuple[int, int]], loc: _Locator, base: date | None
) -> list[dict[str, Any]]:
    """Decision 17: sentences directing a respondent, the State or an authority, each with its addressee, its kind
    (`procedural` when the act is filing, producing records or obtaining instructions) and its time limit."""
    out: list[dict[str, Any]] = []
    for s, e in sentences:
        sentence = body[s:e]
        addressee = None
        for am in R.ADDRESSEES.finditer(sentence):
            tail = sentence[am.end() : am.end() + R.DIRECTION_SPAN]
            vm = R.DIRECTION_VERBS.search(tail)
            if vm and not re.search(r"[.;]\s", tail[: vm.start()]):
                addressee = am.group(0)
                break
            head = sentence[max(0, am.start() - 24) : am.start()]
            if R.DIRECT_ADDRESSEE.search(head) and re.match(r"[^.;]{0,120}?\bto\b", sentence[am.end() :]):
                addressee = am.group(0)
                break
        if addressee is None:
            continue
        b = min(e, s + R.DIRECTION_TEXT_MAX)
        text = body[s:b]
        period, due = _period(text, base)
        out.append(
            {
                "kind": "procedural" if R.PROCEDURAL_DIRECTION_ACTS.search(text) else "compliance",
                "text": text,
                "addressee": _clip(addressee, R.ADDRESSEE_MAX),
                "period": period,
                "due_on": due,
                **loc.item(s, b),
            }
        )
    return out


def _act_key(act: str) -> str:
    key = re.sub(r"[^a-z0-9]+", " ", act.lower().replace(".", "")).strip()
    return re.sub(r"^the\s+", "", key)


def acts(body: str, loc: _Locator) -> list[dict[str, Any]]:
    """Decision 17: acts and provisions cited, one item per (act, kind) with every provision as printed, the first
    occurrence and a count."""
    found: list[tuple[int, int, str, str, str]] = []
    taken: list[tuple[int, int]] = []
    for kind, rx in R.ACT_PATTERNS:
        for m in rx.finditer(body):
            if any(a < m.end() and m.start() < b for a, b in taken):
                continue
            taken.append((m.start(), m.end()))
            found.append((m.start(), m.end(), kind, _collapse(m.group("act")), _collapse(m.group("prov"))))
    found.sort()
    items: dict[tuple[str, str], dict[str, Any]] = {}
    for s, e, kind, act, prov in found:
        key = (_act_key(act), kind)
        item = items.get(key)
        if item is None:
            items[key] = {
                "act": act,
                "act_key": key[0],
                "provisions": [prov],
                "kind": kind,
                "count": 1,
                **loc.item(s, e),
            }
        else:
            item["count"] += 1
            if prov not in item["provisions"]:
                item["provisions"].append(prov)
    return list(items.values())


def judgments(body: str, loc: _Locator) -> list[dict[str, Any]]:
    """Decision 17: earlier judgments cited, by the reporter patterns seen in the data, with the printed "X v. Y"
    standing immediately before the citation when there is one."""
    found: list[tuple[int, int, str, str, int]] = []
    taken: list[tuple[int, int]] = []
    for reporter, rx in R.REPORTER_PATTERNS:
        for m in rx.finditer(body):
            if any(a < m.end() and m.start() < b for a, b in taken):
                continue
            taken.append((m.start(), m.end()))
            found.append((m.start(), m.end(), reporter, _collapse(m.group(0)), int(m.group("year"))))
    found.sort()
    items: dict[str, dict[str, Any]] = {}
    for s, e, reporter, citation, year in found:
        item = items.get(citation)
        if item is not None:
            item["count"] += 1
            continue
        before = body[max(0, s - R.CASE_NAME_LOOKBACK) : s]
        cm = R.CASE_NAME.search(before)
        name = _collapse(cm.group("name")) if cm else None
        if name and any(rx.search(name) for _, rx in R.REPORTER_PATTERNS):
            name = None  # the "name" runs over an earlier citation: not a case name standing before this one
        items[citation] = {
            "citation": citation,
            "reporter": reporter,
            "year": year,
            "case_name": name if name and len(name) <= R.CASE_NAME_MAX else None,
            "count": 1,
            **loc.item(s, e),
        }
    return list(items.values())


# ------------------------------------------------------------------------------------------------ tags (14, 15)


def form(heading: str | None, napix_kind: str | None, has_outcome: bool) -> str:
    """Decision 14: `judgment` by the heading or NAPIX, else `final` by NAPIX or a read outcome, else `interim`."""
    if (heading and R.JUDGMENT_WORD.search(heading)) or napix_kind == JUDGMENT:
        return JUDGMENT
    if napix_kind == FINAL or has_outcome:
        return FINAL
    return INTERIM


def procedural(
    *, form_: str, registrar: bool, has_outcome: bool, facts: dict[str, Any], body_text: str
) -> bool:
    """Decision 15: a registrar's order, or an interim order with no outcome, no compliance direction, no act or
    judgment cited, no substantive phrase and a short body."""
    if registrar:
        return True
    if form_ != INTERIM:
        return False
    return (
        not has_outcome
        and not any(d["kind"] == "compliance" for d in facts["directions"])
        and not facts["acts"]
        and not facts["judgments"]
        and not R.SUBSTANTIVE_PHRASES.search(body_text)
        and len(body_text) <= R.PROCEDURAL_MAX_CHARS
    )


def flags(sp: Spans, pm: PageMap, body_text: str, capped: bool) -> list[str]:
    out: list[str] = []
    if sp.layout == WHOLE:
        out.append("off_template")
    if sp.printed_cnr is None:
        out.append("no_cnr_line")
    if sp.printed_case_no is None:
        out.append("no_case_no")
    if sp.printed_date is None:
        out.append("no_date")
    if pm.differ:
        out.append("page_marks_differ")
    if not body_text:
        out.append("empty_body")
    if capped:
        out.append("capped")
    return out


# ------------------------------------------------------------------------------------------------ parse


def parse(full_text: str, *, order_date: date | None = None, napix_kind: str | None = None) -> Parsed:
    """The whole reading of one order's text (decisions 7 to 17)."""
    full_text = full_text or ""
    text_chars = len(full_text)
    capped = text_chars > R.MAX_PARSE_CHARS
    text = full_text[: R.MAX_PARSE_CHARS] if capped else full_text
    pm = pages(text)
    sp = locate(text, pm)
    body_text, omap, paras = clean(text, sp, pm)
    loc = _Locator(omap, pm)
    sentences = _sentences(body_text) if body_text else []
    base = order_date or sp.printed_date
    found_outcome = outcome(body_text, sentences, loc) if body_text else None
    the_form = form(sp.heading, napix_kind, found_outcome is not None)
    if the_form == INTERIM:
        found_outcome = None  # unreachable (an outcome makes the order final), kept for the CHECK
    facts = {
        "outcome": found_outcome,
        "directions": directions(body_text, sentences, loc, base) if body_text else [],
        "acts": acts(body_text, loc) if body_text else [],
        "judgments": judgments(body_text, loc) if body_text else [],
    }
    the_parts = parts(body_text, paras, the_form, pm)
    is_procedural = procedural(
        form_=the_form,
        registrar=sp.registrar,
        has_outcome=found_outcome is not None,
        facts=facts,
        body_text=body_text,
    )
    return Parsed(
        text_chars=text_chars,
        parser_version=R.PARSER_VERSION,
        layout=sp.layout,
        form=the_form,
        heading=sp.heading,
        oral=sp.oral,
        cav=sp.cav,
        printed_cnr=sp.printed_cnr,
        printed_case_no=sp.printed_case_no,
        printed_date=sp.printed_date,
        printed_reserved_on=sp.printed_reserved_on,
        printed_pronounced_on=sp.printed_pronounced_on,
        neutral_citation=sp.neutral_citation,
        author=sp.author,
        registrar=sp.registrar,
        procedural=is_procedural,
        outcome=found_outcome["value"] if found_outcome else None,
        spans=sp.spans,
        linked_cases=sp.linked_cases,
        body_text=body_text,
        body_sha256=body_hash(body_text),
        paragraphs=[p.as_dict() for p in paras],
        parts=the_parts,
        facts=facts,
        flags=flags(sp, pm, body_text, capped),
    )


# ------------------------------------------------------------------------------------------------ the next date (19)


def next_date_span(body_text: str, phrase: str | None) -> tuple[int, int] | None:
    """Decision 19: the stored next-date sentence found in the cleaned body by its words, tolerant of whitespace and
    punctuation (the reader's joined dates and stripped page headers still match); None when it is not there."""
    if not body_text or not phrase:
        return None
    words = re.findall(r"\w+", phrase)
    if not words:
        return None
    rx = re.compile(r"\W*".join(re.escape(w) for w in words), re.IGNORECASE)
    m = rx.search(body_text)
    return (m.start(), m.end()) if m else None
