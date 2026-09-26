"""Gauhati High Court cause-list PDF parser (Daily, Supplementary, Lawazima, Vacation lists).

Layout facts this relies on (checked on 2024–2026 lists):
- Every court block starts with `BEFORE:`, the judges, `COURT NO: n`, an optional `[BENCH TYPE]`, then a header
  row `Sr.No. Case Number | Main Parties | Petitioner Advocate | Respondent Advocate`. Column x-positions move by
  a few points between files, so column bounds are taken from each header row, not hard-coded.
- The case-number cell of each listed case carries a hyperlink `…getcasedetails.php?cino=<CNR>`. That link is
  the CNR source: identity is exact and never guessed (ground rule 1). A row without a link has `cnr=None`.
- `WITH` above a case number marks a connected matter; it may or may not carry its own serial number.
- `in WA/1649/2024` under an IA names the parent case; `(Filing Number)` marks a filing number; `FIXED` and
  similar tokens are remarks.
- Parties are split by a `Versus` line. Section headings (`- FOR ORDERS -`, `ORDERS`) are centred and sit
  inside the parties column range, so they are recognised by their offset from the column's left edge.
- A `LEAVE NOTE OF ADVOCATES` block follows some courts; it is skipped until the next `BEFORE:`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import pymupdf

from aslms.integration.base import CauseListRow

CNR_RE = re.compile(r"cino=([A-Z]{4}\d{12})", re.I)
CNR_SHAPE = re.compile(r"^[A-Z]{4}\d{12}$")
CASE_NO_RE = re.compile(r"^[A-Za-z][A-Za-z0-9().&'\s-]*?/\s*\d+\s*/\s*\d{4}\b")
DATE_RE = re.compile(r"For\s+\w+\s*,\s*(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(\d{4})", re.I)
FOOTER_RE = re.compile(r"^\d+\s*/\s*\d+$")
RULE_RE = re.compile(r"^[-=_]{8,}$")
COUNSEL_CODE_RE = re.compile(
    r"^(?:SC|GA|PP|ADDL\.?\s*PP|APP|CGC|ASGI|ADDL\.?\s*AG|AG|SR\.?\s*SC|STANDING\s+COUNSEL)\s*,\s*\S.*$", re.I
)
COUNSEL_TOKENS = {"DY.S.G.I.", "DY. S.G.I.", "ASGI", "A.S.G.I.", "LEGAL AID COUNSEL", "C.G.C.", "CGC"}
CODE_CONNECTOR_RE = re.compile(r"(?:\bAND|\bOF|&|,|-)\s*$", re.I)
ADVOCATE_START_RE = re.compile(r"^(?:MR|MS|MRS|DR|MD|SRI|SHRI|SMT|SH|KM|M/S)\b\.?", re.I)
LIST_TYPES = (
    ("SUPPLEMENTARY", "supplementary"),
    ("LAWAZIMA", "lawazima"),
    ("VACATION", "vacation"),
    ("DAILY", "daily"),
)
MONTHS = {
    m: i
    for i, m in enumerate(
        [
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
        ],
        start=1,
    )
}


@dataclass
class ParsedCauseList:
    list_date: date | None
    list_type: str
    title: str | None
    rows: list[CauseListRow]
    page_count: int
    warnings: list[str] = field(default_factory=list)

    @property
    def cnr_rate(self) -> float:
        return sum(1 for r in self.rows if r.cnr) / len(self.rows) if self.rows else 0.0


@dataclass
class _Line:
    """Words of one column on one visual line."""

    page: int
    y: float
    x: float
    col: str  # sr | case | parties | pet | res | wide
    text: str
    rect: tuple[float, float, float, float]

    @property
    def key(self) -> float:
        return self.page * 10_000 + self.y


@dataclass
class _Cols:
    case: float
    parties: float
    pet: float
    res: float

    def of(self, x: float) -> str:
        if x < self.case:
            return "sr"
        if x < self.parties:
            return "case"
        if x < self.pet:
            return "parties"
        if x < self.res:
            return "pet"
        return "res"


@dataclass
class _Entry:
    start: _Line
    printed_sr: str | None
    connected: bool
    court_no: str | None
    bench_text: str | None
    section: str | None
    cnr: str | None
    case_lines: list[str] = field(default_factory=list)
    party_lines: list[tuple[float, str]] = field(default_factory=list)
    pet_lines: list[str] = field(default_factory=list)
    res_lines: list[str] = field(default_factory=list)


def normalise_counsel_code(text: str) -> str:
    t = re.sub(r"\s+", " ", text.strip().upper())
    t = re.sub(r"\s*,\s*", ", ", t)
    return t


def is_counsel_code(text: str) -> bool:
    t = text.strip().upper()
    return bool(COUNSEL_CODE_RE.match(t)) or t in COUNSEL_TOKENS


def merge_advocates(lines: list[str]) -> list[str]:
    """Advocate names wrap over lines ("MR H R A CHOUDHURY(R-" / "1,2,3)", "MR. NAYAN JYOTI" / "KHATANIAR").
    A line continues the previous one when the previous has an open bracket or ends with '-' or ',', when it
    starts with a digit, '(' or lower case, or when it is a single bare word after a long line."""
    out: list[str] = []
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if (
            out
            and not is_counsel_code(line)
            and is_counsel_code(out[-1])
            and CODE_CONNECTOR_RE.search(out[-1])
        ):
            # a wrapped counsel code: "SC, FINANCE AND" / "TAXATION"
            out[-1] = f"{out[-1]} {line}"
            continue
        if out and not is_counsel_code(line) and not is_counsel_code(out[-1]):
            prev = out[-1]
            cont = (
                prev.count("(") > prev.count(")")
                or prev.endswith(("-", ","))
                or line[0].isdigit()
                or line[0] in "(&"
                or line[0].islower()
                or (" " not in line and not ADVOCATE_START_RE.match(line) and len(prev) >= 12)
            )
            if cont:
                out[-1] = f"{prev}{'' if prev.endswith('-') else ' '}{line}"
                continue
        out.append(line)
    return out


def _parse_date(text: str) -> date | None:
    m = DATE_RE.search(text)
    if not m:
        return None
    month = MONTHS.get(m.group(2).lower())
    if not month:
        return None
    try:
        return date(int(m.group(3)), month, int(m.group(1)))
    except ValueError:
        return None


def date_from_filename(path: str | Path) -> date | None:
    m = re.search(r"(\d{2})-(\d{2})-(\d{4})", str(path))
    if not m:
        return None
    try:
        return datetime.strptime(m.group(0), "%d-%m-%Y").date()
    except ValueError:
        return None


def _page_lines(page: pymupdf.Page, pno: int, cols: _Cols | None) -> tuple[list[_Line], _Cols | None]:
    """Groups the page's words into per-column visual lines. Detects the header row to (re)set columns."""
    words = page.get_text("words")
    rows: dict[tuple[int, int], list[tuple]] = {}
    for w in words:
        rows.setdefault((w[5], w[6]), []).append(w)
    # detect the header row on this page: its words sit in separate text lines but share one y
    by_y: dict[int, dict[str, float]] = {}
    for w in words:
        by_y.setdefault(round(w[1]), {}).setdefault(w[4], w[0])
    for xs in by_y.values():
        if {"Main", "Petitioner", "Respondent"} <= set(xs):
            case_x = xs.get("Case", xs["Main"] - 140)
            cols = _Cols(
                case=case_x - 12,
                parties=xs["Main"] - 12,
                pet=xs["Petitioner"] - 16,
                res=xs["Respondent"] - 20,
            )
    out: list[_Line] = []
    for ws in rows.values():
        ws = sorted(ws, key=lambda w: w[0])
        text = " ".join(w[4] for w in ws)
        x0, y0 = ws[0][0], ws[0][1]
        rect = (ws[0][0], min(w[1] for w in ws), ws[-1][2], max(w[3] for w in ws))
        if cols is None:
            out.append(_Line(pno, y0, x0, "wide", text, rect))
            continue
        # a pymupdf line never crosses columns in these files, but be safe: split by column
        buckets: dict[str, list[tuple]] = {}
        for w in ws:
            buckets.setdefault(cols.of(w[0]), []).append(w)
        if len(buckets) > 1 and x0 < cols.case and not ws[0][4].isdigit():
            out.append(_Line(pno, y0, x0, "wide", text, rect))  # full-width text (headers, notes)
            continue
        for col, bw in buckets.items():
            t = " ".join(w[4] for w in bw)
            r = (bw[0][0], min(w[1] for w in bw), bw[-1][2], max(w[3] for w in bw))
            out.append(_Line(pno, bw[0][1], bw[0][0], col, t, r))
    out.sort(key=lambda ln: (ln.y, ln.x))
    return out, cols


def _is_structural(line: _Line, cols: _Cols | None) -> str | None:
    t = line.text.strip()
    u = t.upper()
    if RULE_RE.match(t) or FOOTER_RE.match(t):
        return "rule"
    if u.startswith("BEFORE:"):
        return "before"
    if u.startswith("COURT NO"):
        return "court"
    if u.startswith("SR.NO.") or ("MAIN PARTIES" in u and "ADVOCATE" in u):
        return "header"
    if "LEAVE NOTE" in u:
        return "leave"
    if cols and line.col == "parties" and line.x > cols.parties + 40 and u != "VERSUS":
        if t.startswith("-") or (u == t and not re.search(r"\d", t) and len(t) < 90):
            return "section"
    if cols and line.col in ("case", "parties") and t.startswith("- ") and t.endswith(" -"):
        return "section"
    if u.startswith("[") and u.endswith("]") and line.x < (cols.case if cols else 60):
        return "bench"
    return None


def parse_causelist(path: str | Path | None = None, *, data: bytes | None = None) -> ParsedCauseList:
    doc = pymupdf.open(stream=data, filetype="pdf") if data is not None else pymupdf.open(str(path))
    try:
        return _parse(doc, path)
    finally:
        doc.close()


def _parse(doc: pymupdf.Document, path: str | Path | None) -> ParsedCauseList:
    warnings: list[str] = []
    cols: _Cols | None = None
    all_lines: list[_Line] = []
    links: list[tuple[int, tuple[float, float, float, float], str]] = []
    for pno in range(doc.page_count):
        page = doc[pno]
        lines, cols = _page_lines(page, pno, cols)
        all_lines.extend(lines)
        for lk in page.get_links():
            m = CNR_RE.search(lk.get("uri") or "")
            if m:
                r = lk["from"]
                links.append((pno, (r.x0, r.y0, r.x1, r.y1), m.group(1).upper()))

    head_text = " ".join(ln.text for ln in all_lines[:40])
    list_type = next((v for k, v in LIST_TYPES if k in head_text.upper()), "other")
    title = next((ln.text for ln in all_lines[:10] if "CAUSELIST" in ln.text.upper()), None)
    list_date = _parse_date(head_text) or (date_from_filename(path) if path else None)

    # second pass needs column bounds per line; re-derive them in order
    entries: list[_Entry] = []
    court_no: str | None = None
    bench_text: str | None = None
    judges: dict[float, list[str]] = {}
    section: str | None = None
    skipping = False
    in_before = False
    pending_with = False
    pending_sr: tuple[_Line, str] | None = None
    current: _Entry | None = None
    cols_now: _Cols | None = None

    def close() -> None:
        nonlocal current
        if current is not None:
            entries.append(current)
        current = None

    for ln in all_lines:
        # refresh column bounds when a header row passes
        u = ln.text.upper()
        kind = _is_structural(ln, cols_now or cols)
        if kind == "header":
            cols_now = cols  # bounds already derived per page
            close()
            continue
        if kind == "before":
            close()
            skipping, in_before, judges, section, bench_text = False, True, {}, None, None
            continue
        if skipping:
            continue
        if kind == "leave":
            close()
            skipping = True
            continue
        if kind == "court":
            m = re.search(r"COURT\s*NO\.?\s*:?\s*(\w+)", u)
            court_no = m.group(1) if m else None
            in_before = False
            close()
            continue
        if in_before:
            if u.strip():
                judges.setdefault(round(ln.key), []).append(ln.text.strip())
            continue
        if kind == "bench":
            bench_text = ln.text.strip("[] ")
            continue
        if kind == "rule":
            continue
        if kind == "section":
            close()
            section = ln.text.strip(" -")
            continue
        if ln.col == "wide":
            continue

        if ln.col == "sr":
            if ln.text.strip().isdigit():
                pending_sr = (ln, ln.text.strip())
                # the serial number is printed on the case-number line; attach if an entry starts at this y
                if current and abs(current.start.key - ln.key) < 3 and current.printed_sr is None:
                    current.printed_sr = ln.text.strip()
                    pending_sr = None
            continue

        if ln.col == "case":
            t = ln.text.strip()
            if t.upper() == "WITH":
                close()
                pending_with = True
                continue
            link = _link_for(ln, links)
            sr = pending_sr[1] if pending_sr and abs(pending_sr[0].key - ln.key) < 3 else None
            is_start = (
                CASE_NO_RE.match(t)
                and not t.lower().startswith("in ")
                and not t.upper().startswith("WITH ")
                and (link or sr or pending_with or current is None)
            )
            if is_start:
                close()
                pending_sr = None
                current = _Entry(
                    start=ln,
                    printed_sr=sr,
                    connected=pending_with,
                    court_no=court_no,
                    bench_text=" / ".join(filter(None, [bench_text, _judges(judges)])) or None,
                    section=section,
                    cnr=link,
                )
                pending_with = False
                current.case_lines.append(t)
                continue
            if current:
                current.case_lines.append(t)
            continue

        if current is None:
            continue
        if ln.col == "parties":
            current.party_lines.append((ln.x, ln.text.strip()))
        elif ln.col == "pet":
            current.pet_lines.append(ln.text.strip())
        elif ln.col == "res":
            current.res_lines.append(ln.text.strip())
    close()

    rows: list[CauseListRow] = []
    last_main: int | None = None
    for n, e in enumerate(entries, start=1):
        row = _to_row(n, e, last_main if e.connected else None)
        if not e.connected:
            last_main = n
        rows.append(row)
    if not rows:
        warnings.append("no entries parsed")
    missing = sum(1 for r in rows if not r.cnr)
    if missing:
        warnings.append(f"{missing} of {len(rows)} entries have no CNR hyperlink")
    return ParsedCauseList(list_date, list_type, title, rows, doc.page_count, warnings)


def _judges(judges: dict[float, list[str]]) -> str | None:
    lines = [" ".join(parts) for _, parts in sorted(judges.items())]
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in lines if not ln.upper().startswith("[AT ")]
    return "; ".join(ln for ln in lines if ln) or None


def _link_for(ln: _Line, links: list[tuple[int, tuple[float, float, float, float], str]]) -> str | None:
    x0, y0, x1, y1 = ln.rect
    best: str | None = None
    for pno, (lx0, ly0, lx1, ly1), cnr in links:
        if pno != ln.page:
            continue
        overlap_y = min(y1, ly1) - max(y0, ly0)
        overlap_x = min(x1, lx1) - max(x0, lx0)
        if overlap_y > 1 and overlap_x > 1:
            best = cnr
            break
    return best if best and CNR_SHAPE.match(best) else None


def _to_row(n: int, e: _Entry, connected_to: int | None) -> CauseListRow:
    case_no = e.case_lines[0]
    m = CASE_NO_RE.match(case_no)
    case_no_clean = re.sub(r"\s+", "", m.group(0)) if m else case_no
    extras = [case_no[m.end() :].strip()] if m and case_no[m.end() :].strip() else []
    parent = None
    is_filing = False
    for t in e.case_lines[1:]:
        if t.lower().startswith("in ") and CASE_NO_RE.match(t[3:].strip()):
            parent = re.sub(r"\s+", "", t[3:].strip())
        elif "filing number" in t.lower():
            is_filing = True
        else:
            extras.append(t)

    pet, res, seen_versus = [], [], False
    for _, t in e.party_lines:
        if t.upper() == "VERSUS":
            seen_versus = True
            continue
        (res if seen_versus else pet).append(t)

    pet_adv = merge_advocates(e.pet_lines)
    res_adv = merge_advocates(e.res_lines)
    codes = tuple(dict.fromkeys(normalise_counsel_code(a) for a in pet_adv + res_adv if is_counsel_code(a)))
    return CauseListRow(
        sr_no=n,
        cnr=e.cnr,
        case_no_text=case_no_clean,
        court_no=e.court_no,
        petitioner_text=" ".join(pet) or None,
        respondent_text=" ".join(res) or None,
        pet_advocate_text="\n".join(pet_adv) or None,
        res_advocate_text="\n".join(res_adv) or None,
        with_text=None,
        remarks=" ".join(extras) or None,
        raw={"case_lines": e.case_lines, "page": e.start.page + 1},
        bench_text=e.bench_text,
        section=e.section,
        printed_sr=e.printed_sr,
        connected_to=connected_to,
        parent_case_no_text=parent,
        is_filing_number=is_filing,
        counsel_codes=codes,
    )
