"""The readings of State Insights by rule (design `state-insights`, decisions 5 to 10 and 22): pure functions, no
database, no network and no model.

Every reading is a regular expression over upper-cased text with collapsed whitespace and `&` read as `AND`
(`clean`), written once here and unit-tested on real examples from the dev data. `READER_VERSION` is stored on every
fact row; a change of version makes every row dirty (decision 12), so a change to any rule below bumps it.

- the State tests: `STATE_PARTY_RE` (a State of Assam or Government of Assam party), `SERVICE_TAG_RE` (a respondent
  named with a service tag, decision 6 `officer`), `is_government_code` (decision 6 `counsel`);
- the cause title: `respondent_side`, `department_phrases`, `normalise_phrase` and `office_name_core` (decisions 8
  and 9); `POSTS` and `posts` (decision 10); `writ_reference` (the original writ of a contempt case, decision 10);
- the court's values: `parse_category` (decision 15), `outcome_key` with `OUTCOMES` (decision 22);
- the bands: `hearing_band` (the Python twin of the portal's `hearingBand`, with the 8-to-30 split) and `age_key`
  over `reporting_common.AGE_BANDS`."""

from __future__ import annotations

import re
import unicodedata
from datetime import date

from aslms.core.clock import today_ist
from aslms.services.matching import ANNOTATION_RE, normalise_counsel_code
from aslms.services.reporting_common import AGE_BANDS, AGE_UNKNOWN, age_band

# "2": the phrase normal form keeps only the characters a cause-title mapping accepts (design
# state-insights-review-advisories, decision 4)
READER_VERSION = "2"

# ------------------------------------------------------------------------------------------------ text

PAGE_MARK_RE = re.compile(r"PAGE\s+NO\.?\s*#?\s*\d+\s*/\s*\d+", re.I)


def clean(text: str | None) -> str:
    """Upper case, `&` read as ` AND `, the printed page marks (`Page No.# 2/5`) dropped, whitespace collapsed."""
    s = (text or "").upper().replace("&", " AND ")
    s = PAGE_MARK_RE.sub(" ", s)
    return " ".join(s.split())


# ------------------------------------------------------------------------------------------------ State tests

# decision 6 `party`: the mock's pattern with the M of GOVERNMENT optional too, so `GOVT. OF ASSAM` reads
STATE_PARTY_RE = re.compile(r"\b(?:STATE\s+OF\s+ASSAM|GO?VE?R?N?M?E?N?T\.?\s*OF\s+ASSAM)\b", re.I)
# decision 6 `officer`: a government service tag after a comma or a space, as a whole word
SERVICE_TAG_RE = re.compile(r"(?:^|[,\s])(?:IAS|IPS|IFS|ACS|APS|AFS)\b", re.I)
# decision 6 `counsel`: the government designation forms of `matching.GENERIC_PARTS`
GOVERNMENT_CODE_FIRST_PARTS: frozenset[str] = frozenset(
    {"GA", "SR. GA", "SR.GA", "SR. GA ADV.", "PP", "ADDL. PP", "AG", "ADDL. AG", "ADDL AG", "SR. AG"}
)
STATE_NAME_PART = "ASSAM"


def names_state(text: str | None) -> bool:
    return bool(STATE_PARTY_RE.search(text or ""))


def has_service_tag(text: str | None) -> bool:
    return bool(SERVICE_TAG_RE.search(text or ""))


def code_parts_ordered(code: str | None) -> list[str]:
    """A printed code normalised (`matching.normalise_counsel_code`), its respondent marks removed, split on commas in
    printed order."""
    s = ANNOTATION_RE.sub(" ", normalise_counsel_code(code))
    s = " ".join(s.split()).strip().rstrip(",").strip()
    return [p for p in (t.strip() for t in s.split(",")) if p]


def is_government_code(
    code: str | None, mapped: set[str] | frozenset[str], generic: set[str] | frozenset[str]
) -> bool:
    """Decision 6 `counsel`: an active generic State code, a code mapped exactly to a department (active, not generic),
    or a government designation form (first part in `GOVERNMENT_CODE_FIRST_PARTS`, with no other part or with the last
    part `ASSAM`). `mapped` and `generic` hold normalised codes. An unmapped `SC, <office>` code does not count."""
    norm = normalise_counsel_code(code)
    if not norm:
        return False
    if norm in generic or norm in mapped:
        return True
    parts = code_parts_ordered(norm)
    if not parts or parts[0] not in GOVERNMENT_CODE_FIRST_PARTS:
        return False
    return len(parts) == 1 or parts[-1] == STATE_NAME_PART


# ------------------------------------------------------------------------------------------------ the cause title

VERSUS_RE = re.compile(r"\bVERSUS\b|\bV/S\b|\bVS\.?(?=\s)")
DEPT_WORD_RE = re.compile(r"\bDEPARTMENT\b|\bDEPTT?\b\.?|\bDEPTT\b")
# decision 8, form `DEPARTMENT OF <X>`: X stops at a comma, a full stop, `;`, `(`, DISPUR, GOVERNMENT, GOVT, AND ANR /
# AND ORS or the end (and `ASSAM` as its last word is dropped)
OF_FORM_STOP_RE = re.compile(
    r"[,.;:(]|\bDISPUR\b|\bGOVERNMENT\b|\bGOVT\b|\bAND\s+ANR\b|\bAND\s+ORS\b|\bDEPARTMENT\b"
)
# decision 8, form `<X> DEPARTMENT`: X starts after a comma, the start, or `GOVT. OF ASSAM,` / `GOVERNMENT OF ASSAM,`;
# a party number (`2:`), `;` and `:` also separate (Deviation 3 of the design note)
SUFFIX_FORM_START_RE = re.compile(
    r"[,;:]|\bGO?VE?R?N?M?E?N?T\.?\s*OF\s+ASSAM\b|\b\d{1,3}\s*[:.)]\s|\bAND\s+ANR\b|\bAND\s+ORS\b|\bDEPARTMENT\b"
)
SECTION_MARK_RE = re.compile(r"\(\s*[A-Z]\s*\)")
STOP_WORDS = frozenset({"THE", "SAID", "CONCERNED", "STATE", "GOVERNMENT", "SAME"})
PHRASE_MIN, PHRASE_MAX = 3, 80
# the characters a cause-title mapping accepts, shared by `PHRASE_RE` and `ck_office_title_names_phrase` (`&` never
# reaches a normalised phrase: `clean` reads it as AND)
PHRASE_ALLOWED = "A-Z0-9 ()&.,/-"
PHRASE_RE = re.compile(rf"^[A-Z0-9][{PHRASE_ALLOWED}]{{2,199}}$")
# decision 4 of state-insights-review-advisories: the folds of the normal form
DASHES = dict.fromkeys(map(ord, "‐‑‒–—―−"), "-")
QUOTES = dict.fromkeys(map(ord, "'`´‘’‚‛“”„‟\""), None)
BRACKETS = {ord("["): "(", ord("{"): "(", ord("]"): ")", ord("}"): ")"}
REFUSED_RE = re.compile(r"[^A-Z0-9 ().,/-]")
LEADING_RE = re.compile(r"^[^A-Z0-9]+")


def respondent_side(title_text: str | None) -> str:
    """The part of a cause title after the first `VERSUS` (`V/S`, `VS.`), cleaned; "" when it has none."""
    s = clean(title_text)
    m = VERSUS_RE.search(s)
    return s[m.end() :].strip() if m else ""


def fold_phrase_characters(s: str) -> str:
    """Decision 4 of state-insights-review-advisories, steps 1 to 5: accents dropped (NFKD without combining marks),
    typographic dashes as `-`, apostrophes and quotation marks removed with no space (`P.W.D.'S` gives `P.W.D.S`),
    `[` `{` as `(` and `]` `}` as `)`, every other character outside `A-Z 0-9 space ( ) . , / -` a space."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.translate(DASHES).translate(QUOTES).translate(BRACKETS).upper()
    return REFUSED_RE.sub(" ", s)


def normalise_phrase(text: str | None) -> str:
    """Decision 8's normal form: cleaned, only the characters a mapping accepts (`fold_phrase_characters`), a leading
    THE dropped, single-letter section marks such as `(B)` dropped, edge punctuation stripped, whitespace collapsed,
    and nothing before the first letter or digit. Idempotent; a phrase that already passes `PHRASE_RE` is unchanged."""
    s = fold_phrase_characters(clean(text))
    while True:  # to a fixed point, so a second pass never changes the result
        before = s
        s = SECTION_MARK_RE.sub(" ", s)
        s = " ".join(s.split()).strip(" ,.;:-/")
        while s.startswith("THE "):
            s = s[4:].strip()
        s = LEADING_RE.sub("", s).strip(" ,.;:-/")
        if s == before:
            return s


def _keep(phrase: str) -> bool:
    return (
        PHRASE_MIN <= len(phrase) <= PHRASE_MAX
        and phrase not in STOP_WORDS
        and bool(re.search(r"[A-Z]", phrase))
        and valid_phrase(phrase)
    )


def department_phrases(text: str | None) -> list[str]:
    """Decision 8: the department phrases of a respondent text, normalised, in order of first appearance, each once.
    `DEPTT.`, `DEPTT`, `DEPT.` and `DEPARTMENT` read alike."""
    s = DEPT_WORD_RE.sub(" DEPARTMENT ", clean(text))
    s = " ".join(s.split())
    out: list[str] = []
    for m in re.finditer(r"\bDEPARTMENT\b", s):
        after = s[m.end() :]
        of = re.match(r"\s+OF\s+", after)
        if of:
            rest = after[of.end() :]
            stop = OF_FORM_STOP_RE.search(rest)
            raw = rest[: stop.start()] if stop else rest
            raw = re.sub(r"\s+ASSAM$", "", raw.strip())
        else:
            before = s[: m.start()]
            starts = list(SUFFIX_FORM_START_RE.finditer(before))
            raw = before[starts[-1].end() :] if starts else before
        phrase = normalise_phrase(raw)
        if _keep(phrase) and phrase not in out:
            out.append(phrase)
    return out


CORE_DROP_RE = re.compile(r"\bDEPARTMENT\s+OF\b|\bDEPARTMENT\b|\bDEPTT\b|\bDEPT\b|\bTHE\b")


def office_name_core(name: str | None) -> str:
    """Decision 9: the core of a department's name (or of a phrase): upper case, `&` as AND, DEPARTMENT OF, DEPARTMENT,
    DEPTT, DEPT and THE removed, punctuation dropped, whitespace collapsed. "Finance Department" → `FINANCE`."""
    s = clean(name)
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    s = CORE_DROP_RE.sub(" ", s)
    return " ".join(s.split())


def valid_phrase(phrase: str) -> bool:
    """A normalised phrase that `office_title_names` accepts (`ck_office_title_names_phrase`)."""
    return bool(PHRASE_RE.match(phrase))


# ------------------------------------------------------------------------------------------------ posts

POST_LABELS: dict[str, str] = {
    "addl_chief_secretary": "Additional Chief Secretary",
    "principal_secretary": "Principal Secretary",
    "commissioner_secretary": "Commissioner and Secretary",
    "secretary": "Other Secretary",
    "dgp": "Director General of Police",
    "director": "Director",
    "deputy_commissioner": "Deputy Commissioner",
    "superintendent_police": "Superintendent of Police",
    "chief_engineer": "Chief Engineer",
    "executive_engineer": "Executive Engineer",
    "inspector_schools": "Inspector of Schools",
    "deeo": "District Elementary Education Officer",
    "circle_officer": "Circle Officer",
    "chief_executive": "Chief Executive or Managing Director",
}
POSTS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("addl_chief_secretary", re.compile(r"\b(?:ADDL\.?|ADDITIONAL)\s*CHIEF\s+SECRETARY\b")),
    ("principal_secretary", re.compile(r"\bPRINCIPAL\s+SECRETARY\b")),
    ("commissioner_secretary", re.compile(r"\bCOMMISSIONER\s*(?:AND|-?\s*CUM\s*-?)\s*SECRETARY\b")),
    ("secretary", re.compile(r"\bSECRETARY\b")),
    ("dgp", re.compile(r"\bDIRECTOR\s+GENERAL\s+OF\s+POLICE\b|\bDGP\b")),
    ("director", re.compile(r"(?<!MANAGING )\bDIRECTOR\b(?!\s+GENERAL\s+OF\s+POLICE)")),
    ("deputy_commissioner", re.compile(r"\bDEPUTY\s+COMMISSIONER\b")),
    ("superintendent_police", re.compile(r"\bSUPERINTENDENT\s+OF\s+POLICE\b")),
    ("chief_engineer", re.compile(r"\bCHIEF\s+ENGINEER\b")),
    ("executive_engineer", re.compile(r"\bEXECUTIVE\s+ENGINEER\b")),
    ("inspector_schools", re.compile(r"\bINSPECTOR\s+OF\s+SCHOOLS\b")),
    ("deeo", re.compile(r"\bELEMENTARY\s+EDUCATION\s+OFFICER\b|\bDEEO\b")),
    ("circle_officer", re.compile(r"\bCIRCLE\s+OFFICER\b")),
    ("chief_executive", re.compile(r"\bCHIEF\s+EXECUTIVE\b|\bMANAGING\s+DIRECTOR\b")),
)
POST_CODES: tuple[str, ...] = tuple(code for code, _ in POSTS)
_NAMED_SECRETARIES = ("addl_chief_secretary", "principal_secretary", "commissioner_secretary")


def posts(text: str | None) -> list[str]:
    """Decision 10: every post named in a respondent text, in `POSTS` order. "Other Secretary" is a whole-word
    SECRETARY outside the three named secretaries."""
    s = clean(text)
    found: list[str] = []
    rules = dict(POSTS)
    masked = s
    for code in _NAMED_SECRETARIES:
        if rules[code].search(s):
            found.append(code)
            masked = rules[code].sub(lambda m: " " * len(m.group(0)), masked)
    for code, rx in POSTS:
        if code in _NAMED_SECRETARIES:
            continue
        if rx.search(masked if code == "secretary" else s):
            found.append(code)
    return [c for c in POST_CODES if c in found]


# ------------------------------------------------------------------------------------------------ the original writ

WRIT_RE = re.compile(
    r"(?<![A-Z0-9])(?P<kind>W\.?\s*P\.?\s*\(\s*C\s*\)|W\.?\s*P\.?\s*\(\s*CRL\.?\s*\)|W\.?\s*A\.?)"
    r"\s*/?\s*(?:NO\.?\s*)?(?P<no>\d{1,6})\s*(?:/|\bOF\b)\s*(?P<year>\d{4})(?!\d)"
)
WRIT_KINDS = {"WP(C)": "WP(C)", "WP(CRL)": "WP(Crl)", "WA": "WA"}
WRIT_TYPE_COMPACT = {"WP(C)": "WP(C)", "WP(Crl)": "WP(CRL)", "WA": "WA"}
WRIT_TEXT_RE = re.compile(r"^(?P<kind>WP\(C\)|WP\(Crl\)|WA) (?P<no>\d{1,6})/(?P<year>\d{4})$")
WRIT_MIN_YEAR = 1950


def writ_reference(text: str | None, *, today: date | None = None) -> str | None:
    """Decision 10: the first writ number in `text` (`W.P.(C) No. 4326 of 2025`, `WP(C) 123/2020`, `WA 45/2019`,
    `W.P.(Crl.) 7/2021`), written `WP(C) 4326/2025`; a year before 1950 or after the current year is refused. Nothing
    is invented: None when no number reads."""
    s = clean(text)
    max_year = (today or today_ist()).year
    for m in WRIT_RE.finditer(s):
        kind = re.sub(r"[\s.]", "", m.group("kind"))
        label = WRIT_KINDS.get(kind)
        year = int(m.group("year"))
        if label is None or not (WRIT_MIN_YEAR <= year <= max_year):
            continue
        return f"{label} {int(m.group('no'))}/{year}"
    return None


def writ_parts(writ_text: str) -> tuple[str, int, int] | None:
    """(the case type's compact name, reg_no, reg_year) of a `writ_reference` text, for the lookup of the held case."""
    m = WRIT_TEXT_RE.match(writ_text or "")
    if not m:
        return None
    return WRIT_TYPE_COMPACT[m.group("kind")], int(m.group("no")), int(m.group("year"))


# ------------------------------------------------------------------------------------------------ court values

CATEGORY_RE = re.compile(r"^\s*(?P<code>\d{5})\s*-\s*(?P<label>.+?)(?:\s*\(\s*\d+\s*\))?\s*$", re.S)
CATEGORY_LABEL_MAX = 300


def parse_category(text: str | None) -> tuple[int, str] | None:
    """Decision 15: `10245 - Label ( 12 )` gives `(10245, "Label")`; a value without a five-digit code (`( 20240 )`)
    gives None."""
    m = CATEGORY_RE.match(text or "")
    if not m:
        return None
    code = int(m.group("code"))
    if not 1 <= code <= 99999:
        return None
    label = " ".join(m.group("label").split())[:CATEGORY_LABEL_MAX]
    return (code, label) if label else None


# decision 22: the outcome buckets, in the order the rule tries them
OUTCOMES: tuple[tuple[str, str], ...] = (
    ("withdrawn", "Withdrawn"),
    ("infructuous", "Infructuous"),
    ("dismissed_default", "Dismissed for Default"),
    ("dismissed", "Dismissed"),
    ("rejected", "Rejected"),
    ("allowed", "Allowed"),
    ("disposed_of", "Disposed Of"),
    ("closed", "Closed"),
    ("other", "Other"),
)
OUTCOME_KEYS = tuple(k for k, _ in OUTCOMES)
OUTCOME_RULES: tuple[tuple[str, str], ...] = (
    ("withdrawn", r"withdraw"),
    ("infructuous", r"infr[au]ctuous"),
    ("dismissed_default", r"non[\s-]*prosecution|default"),
    ("dismissed", r"dismiss"),
    ("rejected", r"reject"),
    ("allowed", r"allow"),
    ("disposed_of", r"disposed"),
    ("closed", r"closed"),
)


def outcome_key(disposal_type: str | None) -> str:
    """Decision 22: the outcome bucket of the court's `disposal_type` (withdrawal → Withdrawn; infructuous →
    Infructuous; non-prosecution or default → Dismissed for Default; dismiss → Dismissed; reject → Rejected; allow →
    Allowed; disposed → Disposed Of; closed → Closed; else Other)."""
    s = (disposal_type or "").lower()
    for key, rx in OUTCOME_RULES:
        if re.search(rx, s):
            return key
    return "other"


def outcome_case_sql(col: str) -> str:
    """`outcome_key` in SQL over a text column (the same rules, the same order)."""
    whens = " ".join(f"WHEN lower(coalesce({col}, '')) ~ '{rx}' THEN '{key}'" for key, rx in OUTCOME_RULES)
    return f"(CASE {whens} ELSE 'other' END)"


# ------------------------------------------------------------------------------------------------ bands

HEARING_BANDS: tuple[tuple[str, str], ...] = (
    ("today", "Today"),
    ("tomorrow", "Tomorrow"),
    ("days_2_7", "In 2 to 7 Days"),
    ("days_8_30", "In 8 to 30 Days"),
    ("later", "Later"),
    ("passed", "Date Passed"),
    ("none", "No Date Yet"),
    ("disposed", "Disposed"),
)
HEARING_BAND_KEYS = tuple(k for k, _ in HEARING_BANDS)
SOON_DAYS = 7
MONTH_DAYS = 30


def hearing_band(next_on: date | None, status: str | None, today: date) -> str:
    """The row 190 rule in whole IST days (`hearingBand` of the portal) with the later band split at 30 days: disposed;
    no date; passed; today; tomorrow; 2 to 7 days; 8 to 30 days; later."""
    if status == "disposed":
        return "disposed"
    if next_on is None:
        return "none"
    days = (next_on - today).days
    if days < 0:
        return "passed"
    if days == 0:
        return "today"
    if days == 1:
        return "tomorrow"
    if days <= SOON_DAYS:
        return "days_2_7"
    if days <= MONTH_DAYS:
        return "days_8_30"
    return "later"


def age_key(start: date | None, end: date) -> str:
    """The NJDG band of `reporting_common.AGE_BANDS` of a case dated `start`, measured at `end` (today for a pending
    case, the disposal date for a disposed one)."""
    return age_band(start, end)


AGE_LABELS: dict[str, str] = {k: label for k, label, _l, _h in AGE_BANDS} | {AGE_UNKNOWN[0]: AGE_UNKNOWN[1]}
