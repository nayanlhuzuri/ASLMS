"""Gauhati High Court cause-list PDF parser.

The NAPIX Show Cause List PDF (one per bench and list) and the website's court-wide lists (Daily, Supplementary,
Lawazima, Vacation Court) come from the same generator. Layout facts this relies on, checked on the 2025–2026
samples in `docs/specs/samples/` and `data/causelists/`:

- The masthead (`THE GAUHATI HIGH COURT AT GUWAHATI`, `<TYPE> CAUSELIST`, `[ For <weekday>,<d>th <Month> <yyyy>]`)
  opens every court block. `BEFORE:` is followed by the judge lines, then `COURT NO: n` and optional
  bracketed notes (`[DIVISION BENCH-I]`, video-conferencing notices).
- The header row `Sr.No. Case Number | Main Parties | Petitioner Advocate | Respondent Advocate` fixes the
  column x-positions for that block; they are read from the header, never hard-coded.
- The case-number cell carries a hyperlink `…getcasedetails.php?cino=<CNR>`. That link is the only CNR source;
  an entry without a link has `cnr=None` (never guessed).
- `WITH` in the case column marks the next entry as connected to the previous one; it may or may not carry its
  own serial number. Extra lines in the case column (`FIXED`, `(AT 10:30 AM)`, `CAVT. NO…`, `(Filing Number)`,
  `in WA/16001/2023`) are remarks; `in <case>` names the parent case of an application.
- Parties are split at the centred `Versus`. Section headings (`- FOR ORDERS -`, `HEARING`, `ORDERS`) are
  centred lines inside the parties column and start to the right of the column's left edge.
- Counsel codes (`GA, ASSAM`, `SC, REVENUE`, `DY.S.G.I.`) sit in the advocate columns; a code wraps to the next
  line when it ends with `AND`, `OF`, `&`, a comma or a dash.
- A `LEAVE NOTE OF ADVOCATES` block follows a court; it is skipped until the next masthead or `BEFORE:`.
- Entries may continue on the next page without any header; page footers `n/m` and rule lines are dropped.

Every printed row becomes one `Entry` with `seq` (its position in the list, the stable key) and
`printed_sr_no` (the serial as printed, absent on some connected matters). Nothing is normalised away: the raw
column texts are kept beside the derived fields.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pymupdf

CNR_LINK_RE = re.compile(r"cino=([A-Z]{4}\d{12})", re.I)
CASE_NO_RE = re.compile(r"^(?P<no>[A-Za-z][A-Za-z0-9.()&'/ -]*?/\s*\d+\s*/\s*\d{4})(?P<rest>.*)$")
IN_PARENT_RE = re.compile(r"^in\s+(?P<no>[A-Za-z][A-Za-z0-9.()&' -]*?/\s*\d+\s*/\s*\d{4})", re.I)
DATE_RE = re.compile(r"For\s+[A-Za-z]+\s*,\s*(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(\d{4})", re.I)
FOOTER_RE = re.compile(r"^\d+\s*/\s*\d+$")
RULE_RE = re.compile(r"^[-=_ ]+$")
SERIAL_RE = re.compile(r"^\d{1,4}$")
COURT_NO_RE = re.compile(r"COURT\s*NO\s*[:.]?\s*(\S+)", re.I)
CODE_START_RE = re.compile(
    r"^(?:SR\.?\s*)?(?:SC|GA|PP|APP|ADDL\.?\s*PP|CGC|C\.G\.C\.|ASGI|A\.S\.G\.I\.|AG|ADDL\.?\s*AG|"
    r"DY\.?\s*S\.?\s*G\.?\s*I\.?|LEGAL\s+AID\s+COUNSEL|AMICUS\s+CURIAE)\b[,.]?(?:\s|$)",
    re.I,
)
CODE_SUFFIX_RE = re.compile(r"^(?P<adv>.+?),\s*(?P<code>(?:SR\.?\s*)?(?:SC|GA|PP|APP|CGC)\s*,.*)$", re.I)
CONNECTOR_RE = re.compile(r"(?:\bAND|\bOF|&|,|-)\s*$", re.I)
# "(r-" at the end of one line, "1,2,3)" on the next: a respondent annotation split across lines
OPEN_ANNOTATION_RE = re.compile(r"\((?:[rRpP]\s*-?\s*)?$")
SPLIT_ANNOTATION_RE = re.compile(r"^[\d,&\s]+\)$")
TAIL_WORDS = {"DEPT", "DEPT.", "DEPTT", "DEPTT.", "DEPARTMENT", "DEPARTMENT."}
MONTHS = {
    m: i
    for i, m in enumerate(
        "january february march april may june july august september october november december".split(),
        start=1,
    )
}
LIST_TYPES = (
    ("SUPPLEMENTARY", "supplementary"),
    ("LAWAZIMA", "lawazima"),
    ("VACATION", "vacation"),
    ("DAILY", "daily"),
)


@dataclass
class Word:
    x0: float
    x1: float
    text: str


@dataclass
class Line:
    page: int
    y: float
    words: list[Word]

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


@dataclass
class Columns:
    """Row column starts at scale 1 (taken from the header row) and the page origin the generator scales
    about. Some rows are printed on a horizontally scaled grid under an unscaled header (2025 lists: case
    number at x=32, parties at 127, advocates at 242 and 319 under a header at 45/186/356/469), so each entry
    carries its own scale `k`, read from the x-position of its case number."""

    case: float
    parties: float
    pet: float
    res: float
    origin: float = 11.0
    margin: float = 6.0

    def scale_of(self, case_x0: float) -> float:
        k = (case_x0 - self.origin) / (self.case - self.origin)
        return k if 0.5 <= k <= 1.15 else 1.0

    def bounds(self, k: float = 1.0) -> tuple[float, float, float, float]:
        """(case, parties, pet, res) boundaries: a word belongs to the last column whose boundary it passes."""

        def sc(x: float) -> float:
            return self.origin + (x - self.origin) * k - self.margin

        return sc(self.case), sc(self.parties), sc(self.pet), sc(self.res)


@dataclass
class CourtBlock:
    index: int
    judges: list[str] = field(default_factory=list)
    court_no: str | None = None
    notes: list[str] = field(default_factory=list)
    first_page: int = 0
    entry_count: int = 0

    @property
    def bench_text(self) -> str:
        return ", ".join(self.judges)


@dataclass
class Entry:
    seq: int
    printed_sr_no: str | None
    case_no_text: str | None
    cnr: str | None
    page: int
    court_no: str | None
    bench_text: str
    section: str | None
    is_connected: bool
    parent_case_no: str | None
    is_filing_number: bool
    remarks: str | None
    petitioner_text: str | None
    respondent_text: str | None
    pet_advocate_text: str | None
    res_advocate_text: str | None
    pet_advocates: list[str]
    res_advocates: list[str]
    pet_counsel_codes: list[str]
    res_counsel_codes: list[str]
    raw_lines: list[str]

    @property
    def counsel_codes(self) -> list[str]:
        out: list[str] = []
        for c in self.pet_counsel_codes + self.res_counsel_codes:
            if c not in out:
                out.append(c)
        return out

    def as_dict(self) -> dict:
        d = self.__dict__.copy()
        d["counsel_codes"] = self.counsel_codes
        return d


@dataclass
class ParsedCauseList:
    list_type: str | None
    list_type_text: str | None
    list_date: date | None
    page_count: int
    courts: list[CourtBlock]
    entries: list[Entry]
    warnings: list[str]

    @property
    def link_count(self) -> int:
        return sum(1 for e in self.entries if e.cnr)


# ---------------------------------------------------------------------------------------------- extraction


def _lines_of(page: pymupdf.Page, page_no: int) -> list[Line]:
    words = sorted(page.get_text("words"), key=lambda w: (round(w[1]), w[0]))
    lines: list[Line] = []
    for x0, y0, x1, _y1, text, *_ in words:
        text = text.strip()
        if not text:
            continue
        if lines and abs(lines[-1].y - y0) <= 3.0:
            lines[-1].words.append(Word(x0, x1, text))
        else:
            lines.append(Line(page_no, y0, [Word(x0, x1, text)]))
    for ln in lines:
        ln.words.sort(key=lambda w: w.x0)
    return lines


def _links_of(page: pymupdf.Page) -> list[tuple[float, float, float, float, str]]:
    out = []
    for link in page.get_links():
        uri = link.get("uri") or ""
        m = CNR_LINK_RE.search(uri)
        if m:
            r = link["from"]
            out.append((r.x0, r.y0, r.x1, r.y1, m.group(1).upper()))
    return out


def _header_columns(line: Line) -> Columns | None:
    """Column starts from the header row: the rows print the case number 3 points left of `Case`, parties 2
    points left of `Main`, advocates 1 point left of `Petitioner` / `Respondent`."""
    text = line.text
    if "Sr.No" not in text or "Number" not in text:
        return None
    xs: dict[str, float] = {}
    for w in line.words:
        xs.setdefault(w.text, w.x0)
    try:
        return Columns(
            case=xs["Case"] - 3, parties=xs["Main"] - 2, pet=xs["Petitioner"] - 1, res=xs["Respondent"] - 1
        )
    except KeyError:
        return None


def _split(
    line: Line, cols: Columns, k: float = 1.0
) -> tuple[list[Word], list[Word], list[Word], list[Word], list[Word]]:
    b_case, b_parties, b_pet, b_res = cols.bounds(k)
    sr, case, parties, pet, res = [], [], [], [], []
    for w in line.words:
        if w.x0 < b_case:
            (sr if SERIAL_RE.match(w.text) else case).append(w)
        elif w.x0 < b_parties:
            case.append(w)
        elif w.x0 < b_pet:
            parties.append(w)
        elif w.x0 < b_res:
            pet.append(w)
        else:
            res.append(w)
    return sr, case, parties, pet, res


def _row_scale(line: Line, cols: Columns) -> float | None:
    """The scale of a row that starts an entry: from the x-position of its case number (after the serial) or
    of its `WITH`. None for any other line."""
    words = line.words
    if not words:
        return None
    first = words[0]
    b_case, b_parties = cols.bounds(1.0)[:2]
    if SERIAL_RE.match(first.text) and first.x0 < b_case:
        if len(words) < 2:
            return None
        candidate = words[1]
    else:
        candidate = first
    if candidate.x0 >= b_parties:
        return None
    idx = words.index(candidate)
    two = " ".join(w.text for w in words[idx : idx + 2])
    if candidate.text.upper() == "WITH" or CASE_NO_RE.match(candidate.text) or CASE_NO_RE.match(two):
        return cols.scale_of(candidate.x0)
    return None


def _join(words: list[Word]) -> str:
    return " ".join(w.text for w in words)


def _is_masthead(lines: list[Line], idx: int) -> bool:
    """The masthead line is followed by the court's full title in parentheses; a party named
    `THE GAUHATI HIGH COURT AND 9 ORS` is not."""
    for nxt in lines[idx + 1 : idx + 3]:
        t = nxt.text.strip().upper()
        if t:
            return t.startswith("(THE HIGH COURT OF")
    return False


def _is_heading(
    line: Line,
    sr: list[Word],
    case: list[Word],
    parties: list[Word],
    pet: list[Word],
    res: list[Word],
    cols: Columns,
    k: float,
) -> bool:
    """A centred section heading: nothing in the serial column, and either dash-framed (`- FOR ORDERS -`,
    which may run into the advocate columns), or without advocate words and starting well right of the case
    column's left edge but not at the parties column's left edge (party lines are left-aligned there;
    `Versus` is centred but never a heading)."""
    if sr:
        return False
    text = line.text.strip()
    if text.lower() == "versus":
        return False
    if text.startswith("-") and text.endswith("-") and len(text) > 3:
        return True
    b_case, b_parties, _b_pet, _b_res = cols.bounds(k)
    first = line.words[0].x0
    if case and first > b_case + 56:
        # `For Referral to the Special Mediation Drive …`: begins inside the case column but well right of
        # its left edge, where no entry line ever starts (WITH, FIXED, in …, (Filing …) sit at the edge)
        return True
    if pet or res or case or not parties or first <= b_parties + 14:
        return False
    return True


def _clean_heading(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip(" -")).strip()


def _parse_date(text: str) -> date | None:
    m = DATE_RE.search(text)
    if not m:
        return None
    day, month, year = int(m.group(1)), MONTHS.get(m.group(2).lower()), int(m.group(3))
    if not month:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


# ---------------------------------------------------------------------------------------------- advocates


def split_advocates(lines: list[str]) -> tuple[list[str], list[str]]:
    """An advocate column → (advocate names, counsel codes as printed). A code wraps while it ends with a
    connector; a department tail word (`DEPT`) joins the code before it; a respondent annotation split across
    lines (`(r-` / `1,2,3)`) is joined back onto its advocate."""
    advocates: list[str] = []
    codes: list[str] = []
    open_code = False
    last = ""  # "adv" or "code": what the previous line went into
    for raw in lines:
        text = re.sub(r"\s+", " ", raw).strip()
        if not text:
            continue
        if open_code:
            codes[-1] = f"{codes[-1]} {text}"
            open_code = bool(CONNECTOR_RE.search(text))
            continue
        if last == "adv" and (SPLIT_ANNOTATION_RE.match(text) or OPEN_ANNOTATION_RE.search(advocates[-1])):
            sep = "" if advocates[-1].endswith("-") else " "
            advocates[-1] = f"{advocates[-1]}{sep}{text}"
            continue
        if last == "code" and text.upper() in TAIL_WORDS:
            codes[-1] = f"{codes[-1]} {text}"
            continue
        if CODE_START_RE.match(text):
            codes.append(text)
            open_code = bool(CONNECTOR_RE.search(text))
            last = "code"
            continue
        m = CODE_SUFFIX_RE.match(text)
        if m:
            advocates.append(m.group("adv").strip())
            codes.append(m.group("code").strip())
            open_code = bool(CONNECTOR_RE.search(text))
            last = "code"
            continue
        advocates.append(text)
        last = "adv"
    codes = [c.strip().rstrip(",").strip() for c in codes]
    return advocates, codes


# ---------------------------------------------------------------------------------------------- the parser


class _EntryBuilder:
    def __init__(
        self,
        page: int,
        y: float,
        printed_sr_no: str | None,
        connected: bool,
        block: CourtBlock,
        section: str | None,
    ):
        self.page, self.y = page, y
        self.printed_sr_no = printed_sr_no
        self.connected = connected
        self.block, self.section = block, section
        self.case_lines: list[str] = []
        self.party_lines: list[str] = []
        self.pet_lines: list[str] = []
        self.res_lines: list[str] = []
        self.raw: list[str] = []
        self.cnr: str | None = None

    def add(
        self, case: list[Word], parties: list[Word], pet: list[Word], res: list[Word], line: Line
    ) -> None:
        if case:
            self.case_lines.append(_join(case))
        if parties:
            self.party_lines.append(_join(parties))
        if pet:
            self.pet_lines.append(_join(pet))
        if res:
            self.res_lines.append(_join(res))
        self.raw.append(line.text)

    def build(self, seq: int) -> Entry:
        case_no: str | None = None
        remarks: list[str] = []
        parent: str | None = None
        filing = False
        case_lines = list(self.case_lines)
        if case_lines and case_lines[0].strip().upper() == "WITH":
            self.connected = True
            case_lines.pop(0)
        for i, text in enumerate(case_lines):
            t = text.strip()
            if i == 0:
                m = CASE_NO_RE.match(t)
                if m:
                    case_no = re.sub(r"\s*/\s*", "/", m.group("no")).strip()
                    rest = m.group("rest").strip(" ,")
                    if rest:
                        remarks.append(rest)
                    continue
            mp = IN_PARENT_RE.match(t)
            if mp:
                parent = re.sub(r"\s*/\s*", "/", mp.group("no"))
            if t.lower().startswith("(filing number"):
                filing = True
            remarks.append(t)
        pet_text, res_text = None, None
        if self.party_lines:
            try:
                k = next(i for i, t in enumerate(self.party_lines) if t.strip().lower() == "versus")
                pet_text = " ".join(self.party_lines[:k]).strip() or None
                res_text = " ".join(self.party_lines[k + 1 :]).strip() or None
            except StopIteration:
                pet_text = " ".join(self.party_lines).strip() or None
        pet_adv, pet_codes = split_advocates(self.pet_lines)
        res_adv, res_codes = split_advocates(self.res_lines)
        return Entry(
            seq=seq,
            printed_sr_no=self.printed_sr_no,
            case_no_text=case_no,
            cnr=self.cnr,
            page=self.page,
            court_no=self.block.court_no,
            bench_text=self.block.bench_text,
            section=self.section,
            is_connected=self.connected,
            parent_case_no=parent,
            is_filing_number=filing,
            remarks=" | ".join(remarks) or None,
            petitioner_text=pet_text,
            respondent_text=res_text,
            pet_advocate_text="\n".join(self.pet_lines) or None,
            res_advocate_text="\n".join(self.res_lines) or None,
            pet_advocates=pet_adv,
            res_advocates=res_adv,
            pet_counsel_codes=pet_codes,
            res_counsel_codes=res_codes,
            raw_lines=self.raw,
        )


def parse_causelist_pdf(source: bytes | str | Path) -> ParsedCauseList:
    doc = (
        pymupdf.open(stream=source, filetype="pdf")
        if isinstance(source, bytes)
        else pymupdf.open(str(source))
    )
    try:
        return _parse(doc)
    finally:
        doc.close()


def _parse(doc: pymupdf.Document) -> ParsedCauseList:
    warnings: list[str] = []
    lines: list[Line] = []
    links: dict[int, list[tuple[float, float, float, float, str]]] = {}
    for pno, page in enumerate(doc):
        lines.extend(_lines_of(page, pno + 1))
        links[pno + 1] = _links_of(page)

    list_type: str | None = None
    list_type_text: str | None = None
    list_date: date | None = None
    courts: list[CourtBlock] = []
    entries: list[Entry] = []
    builders: list[_EntryBuilder] = []

    state = "preamble"
    block: CourtBlock | None = None
    cols: Columns | None = None
    k = 1.0  # the current row grid's scale (see Columns)
    section: str | None = None
    current: _EntryBuilder | None = None
    pending_with = False

    def flush() -> None:
        nonlocal current
        if current is not None:
            builders.append(current)
            if block is not None:
                block.entry_count += 1
            current = None

    for idx, line in enumerate(lines):
        text = line.text.strip()
        if not text or FOOTER_RE.match(text) or RULE_RE.match(text):
            continue
        upper = text.upper()
        if upper.startswith("THE GAUHATI HIGH COURT") and _is_masthead(lines, idx):
            flush()
            state = "preamble"
            continue
        if upper.startswith("LEAVE NOTE OF ADVOCATES"):
            flush()
            state = "skip"
            continue
        if upper == "BEFORE:":
            flush()
            block = CourtBlock(index=len(courts) + 1, first_page=line.page)
            courts.append(block)
            state = "before"
            section = None
            pending_with = False
            continue
        if state == "skip":
            continue
        if state == "preamble":
            if "CAUSELIST" in upper and list_type is None:
                list_type_text = text
                list_type = next((v for k, v in LIST_TYPES if k in upper), "other")
            if list_date is None:
                list_date = _parse_date(text)
            c = _header_columns(line)
            if c:  # a list without a court block (consolidated lists): entries follow the masthead
                block = CourtBlock(index=len(courts) + 1, first_page=line.page)
                courts.append(block)
                cols, k, state, section, pending_with = c, 1.0, "entries", None, False
            continue
        if state == "before":
            assert block is not None
            m = COURT_NO_RE.search(text)
            if m:
                block.court_no = m.group(1).strip(".]")
                state = "court"
            else:
                block.judges.append(text)
            continue
        if state == "court":
            c = _header_columns(line)
            if c:
                cols, k = c, 1.0
                state = "entries"
            elif block is not None:
                block.notes.append(text)
            continue
        if state != "entries" or cols is None or block is None:
            continue

        k_row = _row_scale(line, cols)
        if k_row is not None:
            k = k_row
        sr, case, parties, pet, res = _split(line, cols, k)
        serial = next((w.text for w in sr if SERIAL_RE.match(w.text)), None)
        case_text = _join(case)

        if serial is not None:
            flush()
            current = _EntryBuilder(line.page, line.y, serial, pending_with, block, section)
            pending_with = False
            current.add(case, parties, pet, res, line)
            continue
        if case and case_text.upper() == "WITH" and not parties and not pet and not res:
            flush()
            pending_with = True
            continue
        if case and CASE_NO_RE.match(case_text) and (current is None or pending_with):
            flush()
            current = _EntryBuilder(line.page, line.y, None, pending_with, block, section)
            pending_with = False
            current.add(case, parties, pet, res, line)
            continue
        if _is_heading(line, sr, case, parties, pet, res, cols, k):
            flush()
            section = _clean_heading(text)
            continue
        if current is None:
            warnings.append(f"p{line.page}: unattached line ignored: {text[:80]}")
            continue
        current.add(case, parties, pet, res, line)
    flush()

    # CNRs from the hyperlinks on the case-number cell
    for b in builders:
        for x0, y0, _x1, y1, cnr in links.get(b.page, []):
            if y0 - 3 <= b.y <= y1 + 1 and (cols is None or x0 < cols.bounds(1.0)[1]):
                b.cnr = cnr
                break
    matched = sum(1 for b in builders if b.cnr)
    total_links = sum(len(v) for v in links.values())
    if total_links != matched:
        warnings.append(f"{total_links} CNR links in the file, {matched} matched to entries")

    for i, b in enumerate(builders, start=1):
        entries.append(b.build(i))
    for e in entries:
        if e.case_no_text is None:
            warnings.append(f"p{e.page}: entry {e.seq} without a case number: {e.raw_lines[:1]}")

    return ParsedCauseList(
        list_type=list_type,
        list_type_text=list_type_text,
        list_date=list_date,
        page_count=len(doc),
        courts=courts,
        entries=entries,
        warnings=warnings,
    )
