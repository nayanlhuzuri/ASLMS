"""Next dates read from the stored text of a court order by rule (design `next-date-extraction`, decision 3 and the
owner's decisions of 17 Oct 2026). Pure: no database, no network, no AI (AI goes only through SourceTrace, and
periods read by SourceTrace are row 37).

Since the owner's second decision of 17 Oct 2026 (option B) the rules only choose which date to suggest and whether
the reading is unclear: every dated reading has `needs_review = True`, and `next_dates.read_order` makes a date firm
only when it equals the court's own date for the case (Current Status / the dossier's next date, or a cause-list
listing). `list_on_date` still names a plain direction ("List on <date>"), `qualified_date` any other written date.

`read_order_text(text, order_date)` returns one `Reading`:
- the text is capped at its last `MAX_TEXT` characters (the direction closes an order), whitespace is collapsed, spaced
  date separators (`31.08 .2026`) are joined, and it is split into sentences (a full stop, semicolon, `?` or `!`
  followed by a space and a capital letter, digit or bracket; abbreviations only split a sentence into harmless
  pieces);
- each written date belongs to the nearest listing verb before it (within `NEAR` characters, in the same clause: no
  `;` between); not a listing date: the noun "list" ("a list of documents", "the cause list"), "come up with", a
  deadline (the date follows `by|within|till|until|before|up to|upto|prior to`, or `ends|expires|lapses` stands
  between), a fixed time limit ("the time fixed for filing ..."), a date the verb only reports ("which is fixed on",
  "has been listed on", "which stands fixed on", "which will come up on", "has been adjourned to", "the connected
  appeal fixed on", "the connected case fixed on", "the connected case stands fixed on", "WA 5/2026 listed for", "is
  slated / likely to be listed on"), a negation ("shall not be listed on"), a counsel's prayer not granted in the
  sentence ("learned counsel prays that the matter be listed on"), another act or actor between the verb
  and the date ("list after 2 weeks, and the respondents to file their reply on <date>", "with liberty to mention on
  <date>", "the interim order is extended to <date>"), and a date after a period that does not spell the period out
  ("list after 2 weeks ... on <date>"; but "after 2 weeks, i.e. on <date>" is a date to confirm);
- `list_on_date` (a plain direction; firm only when the court's date agrees): only a plain direction, the verb, then only the matter listed and how
  ("this matter again before the Division Bench for hearing", "these cases along with WP(C) 12/2026"), then `on` /
  `for` (or nothing: "Fix 20.11.2026 for hearing", "adjourned to 06.04.2026", "Next date: 20.11.2026") and one date
  in the window (order date, order date + `max_ahead_days`], with no other date after the order date in the sentence
  and no listing after a period anywhere in the order;
- *a date to confirm* (`qualified_date`, `specific`, reviewed): any other listing date — after `after`, `on or after`,
  `from`, `not before`, `commencing`, `subsequent to`, "tomorrow, i.e.", ..., followed by `onwards` / `or
  thereafter` / `or any date thereafter` / `or on any subsequent date`, after a period it spells out, or in an order that also lists after a period;
- *unclear* (`conflicting_dates`): two or more different listing dates in the order, another date after the order date
  in the sentence of a listing date, or a date the sentence reports for another matter inside a direction — unless a
  period in that sentence gives the direction ("List after 3 weeks since the connected appeal is fixed on <date>");
  this stops the reading whatever else matches;
- *period*: a listing verb (or `adjourned for|by`) followed in its sentence by `after|for (further) N
  day(s)|week(s)|fortnight|month(s)`, `adjourned by N ...`, `on the expiry of N ...`, `on completion of N ...`, or
  only the matter and the period ("List the matter 2 weeks hence"); N in digits, words up to ninety-nine or both
  ("30 (thirty) days", "3 (three weeks)") (`list_after_period`); "after the returnable date" with `returnable within N
  ...` (`after_returnable_period`) or with `returnable on <date>` (`specific`, `returnable_date`); counted from the
  order date (calendar months clamped to the month's end, a fortnight 14 days, no weekend or holiday adjustment) and
  always reviewed;
- `returnable on|by <date>` alone → `specific` (`returnable_date`, reviewed); `returnable within N ...` with no
  listing direction → `period` (`returnable_period`);
- a listing direction left without a countable date → `unclear` (`no_countable_date`); a direction that sets no
  date by design (`sine die`, `in due course`, `before any other bench`) or none at all → `none`; no text → `no_text`.

Every pattern is bounded (no nested quantifiers); dates are found once per sentence and matched to verbs by
position, so a hostile 500,000-character text reads in linear time."""

from __future__ import annotations

import bisect
import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta

RULES_VERSION = 1
MAX_TEXT = 500_000
MAX_AHEAD_DAYS = 548
NEAR = 80  # a date belongs to a listing verb when it starts within this many characters after it
PHRASE_MAX = 400

SPECIFIC, PERIOD, UNCLEAR, NONE, NO_TEXT = "specific", "period", "unclear", "none", "no_text"
LIST_ON_DATE = "list_on_date"
RETURNABLE_DATE = "returnable_date"
QUALIFIED_DATE = "qualified_date"
LIST_AFTER_PERIOD = "list_after_period"
AFTER_RETURNABLE_PERIOD = "after_returnable_period"
RETURNABLE_PERIOD = "returnable_period"
CONFLICTING_DATES = "conflicting_dates"
NO_COUNTABLE_DATE = "no_countable_date"

CONFIDENCE = {
    LIST_ON_DATE: 1.0,
    RETURNABLE_DATE: 0.8,
    QUALIFIED_DATE: 0.8,
    LIST_AFTER_PERIOD: 0.6,
    AFTER_RETURNABLE_PERIOD: 0.6,
    RETURNABLE_PERIOD: 0.6,
}

_ONES = ("one", "two", "three", "four", "five", "six", "seven", "eight", "nine")
_TEENS = (
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
)
_TENS = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
WORD_NUMBERS = {
    "a": 1,
    "an": 1,
    **{w: i for i, w in enumerate(_ONES, start=1)},
    **{w: i for i, w in enumerate(_TEENS, start=10)},
    **_TENS,
}
MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

_WS = re.compile(r"\s+")
# the page header of the court's PDFs ("Page No.# 2/2"), which can fall between "on" and the date it introduces
_PAGE_HEADER = re.compile(r"\s?\bpage\sno\.?\s?#?\s?\d{1,4}\s?/\s?\d{1,4}\b", re.IGNORECASE)
# a numeric date written with single spaces around its separators (`31.08 .2026`, `14 .10. 2026`)
_SPACED_DATE = re.compile(r"\b(\d{1,2}) ?([./-]) ?(\d{1,2}) ?([./-]) ?(\d{4}|\d{2})\b")
# not after "No." / "Nos." ("along with WP(C) No. 1234/2026 on <date>" is one sentence)
_SPLIT = re.compile(r"(?<!\b[Nn]o\.)(?<!\b[Nn]os\.)(?<=[.;?!])\s+(?=[A-Z0-9(\[\"'])")
_MONTH = "|".join(sorted(MONTHS, key=len, reverse=True))
_NUMERIC_DATE = re.compile(r"(?<![\d./-])(\d{1,2})[./-](\d{1,2})[./-](\d{4}|\d{2})(?![\d])")
_DAY_MONTH_DATE = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s(?:of\s)?({_MONTH})\.?,?\s?(\d{{4}})\b")
_MONTH_DAY_DATE = re.compile(rf"\b({_MONTH})\.?\s(\d{{1,2}})(?:st|nd|rd|th)?,?\s?(\d{{4}})\b")

LISTING_VERB = re.compile(
    r"\b(?:"
    r"re-?list(?:ed|ing)?|list(?:ed|ing)?|re-?notif(?:y|ied)|adjourned\sto|stands?\sover\sto|stood\sover\sto"
    r"|fix(?:ed|ing)?|come\sup(?!\swith\b)|posted\s(?:on|to)|re-?post(?:ed)?\s(?:on|to)|deferred\sto\sbe\slisted|taken\sup\son"
    r"|placed\son|put\sup(?!\swith\b)"
    r")\b"
    r"|\bnext\sdate\s?:"
)
_FIX = re.compile(r"\bfix(?:ed|ing)?\b")
# a fix / put-up verb names a listing date only with "on" or "for" before it, or with the date right after it
_NEEDS_ON_FOR = re.compile(r"fix(?:ed|ing)?|put\sup")
_ON_OR_FOR = re.compile(r"\b(?:on|for)\b")
# a plain direction (owner's decision of 17 Oct 2026, point 4; review of 17 Oct 2026): between the listing verb and
# the date stand only the matter listed and how ("this matter again", "the matter before the Division Bench for
# hearing", "these cases along with WP(C) 12/2026", words of `_PLAIN_WORDS` and case numbers), then "on", "on the",
# "for", "on <weekday>, i.e." or nothing ("Fix 20.11.2026 for hearing", "adjourned to 06.04.2026", "Next date:
# 20.11.2026"). Not "to": the verbs that take it ("adjourned to", "stands over to", "posted to") end with it, and
# "extended to", "subsequent to" are no listing.
_WEEKDAY = r"(?:monday|tuesday|wednesday|thursday|friday|saturday)"
_PLAIN_TAIL = re.compile(
    rf"(?:\b(?:on(?:\sthe)?|for)\s|\bon\s{_WEEKDAY}(?:\snext)?,?\s(?:i\.\s?e\.?,?\s|viz\.?,?\s)?)$"
)
_PLAIN_WORDS = frozenset(
    "this the these those all both it them same said instant present matter matters mater case cases appeal appeals"
    " petition petitions application applications writ interlocutory connected again accordingly together singly"
    " separately also before lawazima court division single appropriate regular bench for hearing admission motion"
    " consideration order orders final further disposal determination under heading in column along alongwith with"
    " lcr of and positively preferably once part-heard no no. nos nos. review criminal civil contempt series batch two"
    " ias i.a.s i.a.s. a an without fail".split()
)
# a case number in the words before the date ("along with WP(C) 12/2026", "AB/1353/2026", "WP(C)No.4409/2022")
_CASE_NO_TOKEN = re.compile(r"[a-z().\[\]/-]{0,24}\d{1,6}/\d{2,4}|[a-z]{1,8}\([a-z.]{1,8}\)\.?")
_CASE_TYPES = frozenset(
    "wa wp ab rsa rfa mfa mac pil ia i.a. i.a crl.a. crl.a crl.rev.p. crl.pet. cont.cas cont.cas. review.pet.".split()
)
_TOKEN_TRIM = re.compile(r"^[^a-z0-9(\[]+|[^a-z0-9)\].]+$")
# "not before" the date (point 2): "onwards" or "or thereafter" just after it
_QUALIFIER_AFTER = re.compile(
    r"\s?,?\s?(?:onwards?|or\s(?:there)?after|or\slater"
    # "or any date thereafter", "or on any subsequent date", "or on a later date" (owner's decision of 17 Oct 2026)
    r"|or\s(?:on\s)?(?:any|a)\s(?:(?:subsequent|later|other|convenient|next)\s)?dates?(?:\s(?:there)?after)?)\b"
)
# the date's own "after" ("list the matter after 15.12.2026", "after the vacation, i.e. after 02.01.2027")
_AFTER_TAIL = re.compile(r"\b(?:on\sor\s)?after\s(?:the\s)?$")
# a direction after a period before the date: the date is not that direction's unless the court spells it out
# ("after 2 weeks, i.e. on 25.09.2026", "after 2 weeks, on 14.05.2026", read as a date to confirm); after anything
# else ("after receipt of the records on <date>", "thereafter on <date>") the date is only a date to confirm
_AFTER_IN_GAP = re.compile(r"\b(?:after|thereafter)\b")
_SPELLED_OUT = re.compile(
    r"\s?(?:,\s?)?(?:\(?(?:i\.\s?e\.?|that\sis|viz\.?)\s?,?\s?)?(?:on\s(?:the\s)?|fixing\s)?"
)
# another act or actor between the verb and the date ("list after 2 weeks, and the respondents to file their reply
# on <date>", "with liberty to mention on <date>", "the interim order is extended up to <date>"): the date is theirs
_FOREIGN_IN_GAP = re.compile(
    r"\b(?:liberty|leave|shall|may|will|must|should|would|can|could|to\s(?!be\b)[a-z]+|petitioners?|respondents?"
    r"|appellants?|applicants?|parties|party|counsel|interim|stay|extended|extension|file|filing|filed|appear\w*"
    r"|mention\w*|produce|submit\w*|complian\w*|comply|deposit\w*|pay|payment)\b"
)
# list / fix / post verbs that report another matter's date rather than direct this one ("which is fixed on",
# "has been listed on", "is now posted on", "scheduled to be listed on", "WA 5/2026, which stands fixed on", "the
# next date of listing ... is on")
_REPORTING_VERB = re.compile(r"(?:re-?)?list|fix|post")
_REPORTED = re.compile(
    r"\b(?:is|are|was|were|been|already|(?<!shall\s)(?<!will\s)(?<!must\s)(?<!may\s)now|scheduled|tentatively"
    r"|presently|currently|which|slated|likely|expected|due|proposed|anticipated)\s(?:[a-z]+\s){0,2}$"
    # "WA 5/2026, which stands fixed on"; not "the matter stands posted on", "stands adjourned and list ... on"
    r"|(?<!matter\s)(?<!matters\s)(?<!case\s)(?<!cases\s)\b(?:stands?|stood)\s$"
    # but another matter's "stands fixed": "the connected case stands fixed on" (second review of 17 Oct 2026)
    r"|\b(?:connected|other|another|analogous|tagged|companion|related|leading|main)\s(?:cases?|matters?)\s"
    r"(?:stands?|stood)\s$"
)
# the other listing verbs report only after "has / have / had (been)", "was / were", "which ..." or "likely /
# slated / expected / scheduled to" ("WA 5/2026, which will come up on <date>", "has been adjourned to <date>", "is
# likely to come up on <date>"); "this case is adjourned to <date>" directs
_OTHER_REPORTING_VERB = re.compile(r"come\sup|adjourned|stands?\sover|stood\sover|taken\sup|placed|re-?notif")
_REPORTED_OTHER = re.compile(
    r"(?:\b(?:has|have|had)\s(?:been\s)?|\b(?:was|were)\s"
    r"|\b(?:which|slated|likely|expected|scheduled|due|proposed|anticipated)\s(?:[a-z]+\s){0,2})$"
)
# a listing the court does not direct: "shall not be listed on", "could not be taken up on" (owner's decision of 17
# Oct 2026 (second), point 4: negations)
_NEGATED = re.compile(r"\b(?:not|never|neither|nor)\s(?:[a-z]+\s){0,2}$")
# a party's or counsel's prayer before the verb, in the same sentence, that the court has not granted before it
# ("learned counsel prays that the matter be listed on <date>"; not "as prayed for", not "prays for time, which is
# allowed, and list on <date>"): the date is the prayer's, not the court's
_PRAYER = re.compile(
    # verbs only: "at the request of the counsel, list ..." is the court's direction
    r"(?<!\bas\s)\b(?:prays|prayed|praying|seeks|sought|seeking|requests|requested|requesting"
    r"|(?:submits?|submitted|urges?|urged|contends?|contended)\sthat)\b"
)
_GRANTED = re.compile(r"\b(?:allowed|allowing|granted|granting|accepted|acceded|considered|accordingly)\b")
# a gerund reports only after "of" ("the next date of listing"); "this Court is fixing the matter on" directs
_OF = re.compile(r"\bof\s$")
REPORT_LOOKBACK = 40
# a past participle right after another proceeding it reports on ("the connected appeal fixed on", "WA 5/2026 listed
# for", "the connected case fixed on"); not after a bare "matter" or "case" ("Matter listed again on <date>" is this
# case's own direction), and never "listed again"
_PARTICIPLE = re.compile(r"(?:re-?)?(?:listed|fixed|posted)")
_AGAIN = re.compile(r"\sagain\b")
_REPORTED_NOUN = re.compile(
    r"(?:\b(?:appeals?|petitions?|applications?|suits?|revisions?|references?"
    r"|(?:connected|other|another|analogous|tagged|companion|related|leading|main)\s(?:cases?|matters?))"
    r"|\d{1,6}\s?/\s?\d{2,4}|\d{1,6}\sof\s\d{4}),?\s$"
)
# the noun "list" ("a list of documents", "the cause list", "list of dates") is not a direction to list
_LIST_WORD = re.compile(r"(?:re-?)?list")
_LIST_NOUN_BEFORE = re.compile(
    r"\b(?:a|an|the|its|their|his|her|such|any|which|whose|said|same|cause|daily|weekly"
    r"|supplementary|additional|fresh|revised|separate|detailed|complete|full)\s$"
)
_OF_AFTER = re.compile(r"\sof\b")
# a deadline, not a hearing: the date follows "by", "within", "till", "until", "before", "up to", "upto" or "prior
# to" ("file ... by <date>", "come up ... by <date>", "extended up to <date>"), or the words between say a time
# "ends", "expires" or "lapses" on it
_DEADLINE_BEFORE_DATE = re.compile(
    r"\b(?:by|within|till|until|(?<!\bnot\s)before|up\s?to|prior\sto)\s(?:the\s)?$"
)
_DEADLINE_WORD = re.compile(r"\b(?:ends?|ending|expires?|expiring|expiry|lapses?|lapsing|elapses?)\b")
# "the time fixed for filing ...", "the period fixed ...": what is fixed is a time limit, not a hearing
_TIME_LIMIT_BEFORE = re.compile(r"\b(?:time|period|deadline|limit|limitation)\s(?:[a-z-]+\s){0,2}$")
_FIXED_FOR_ACT = re.compile(
    r"\sfor\s(?:the\s)?(?:filing|submitting|submission|depositing|deposit|paying|payment|complying|compliance"
    r"|furnishing)\b"
)
# a direction to list (not "the matter was listed today", "cause list", "list of dates")
DIRECTION = re.compile(
    r"\b(?:"
    r"(?<!cause\s)list\s(?:this|the|these|those|all|both|it|them|that|on|after|in|before|again|for|along|accordingly"
    r"|from|not|within|during|thereafter|next|immediately)\b"
    r"|(?:be|been|being)\slisted\b|listed\sagain\b|re-?list|re-?notif|adjourned\s(?:to|for|by|till|until|sine)\b"
    r"|stands?\sover\b|stood\sover\b|come\sup\b(?!\swith\b)|posted\s(?:on|to|for|after)\b|re-?post(?:ed)?\s(?:on|to|for|after)\b"
    r"|fix(?:ed|ing)?\s(?:the|this|these)\s(?:matter|case|appeal|petition)s?\b|taken\sup\s(?:on|after)\b"
    r"|fix(?:ed)?\s(?=\d)|put\sup\s(?:on|for|after|again|before|the|this|these|it|in|from|not)\b|next\sdate\s?:"
    r")"
)
NO_DATE_BY_DESIGN = re.compile(
    r"\b(?:sine\sdie|in\sdue\scourse"
    r"|before\s(?:any\sother|another|an\sappropriate|the\sappropriate|appropriate|the\sregular|regular)\sbench)\b"
)
# a number of days / weeks / months: digits, words up to ninety-nine ("twenty one", "thirty-five"), or both ("2
# (two)", "4(four)", "30 (thirty)", "2 [two]", "3 (three weeks)"); owner's decision of 17 Oct 2026 (second), point 3
_WORDS_1_19 = "|".join(sorted((*_ONES, *_TEENS), key=len, reverse=True))
_NUM = rf"(?:\d{{1,3}}|(?:{'|'.join(_TENS)})(?:[\s-](?:{'|'.join(_ONES)}))?|{_WORDS_1_19}|an|a)(?![a-z])"
_UNIT = r"(?:days?|weeks?|fortnights?|months?)"
_QTY = (
    rf"(?P<a>{_NUM})\s?(?:"
    rf"[(\[]\s?(?P<b>{_NUM})\s?[)\]]\s?(?:more\s)?(?P<u1>{_UNIT})\b"
    rf"|[(\[]\s?(?P<c>{_NUM})\s(?P<u2>{_UNIT})\s?[)\]]"
    rf"|(?:more\s)?(?P<u3>{_UNIT})\b"
    r")"
)
PERIOD_PHRASE = re.compile(
    # "after", "for", "adjourned by", "on the expiry of", "on completion of", "after the lapse of" N units
    r"(?:\b(?:(?:after|on|upon)\s(?:the\s)?(?:expiry|completion|lapse)\sof|after|for|(?<=adjourned\s)by)\s"
    # "List the matter 2 weeks hence": only the matter between the verb and the period
    r"|\b(?:re-?)?list\s(?:(?:this|the|these|those|all|both|it|them)\s)?"
    r"(?:(?:matters?|cases?|appeals?|petitions?|applications?)\s)?(?:again\s)?)"
    rf"(?:a\s)?(?:further\s)?(?:period\sof\s)?{_QTY}"
)
ADJOURNED_FOR = re.compile(r"\badjourned\s(?:for|by)\b")
AFTER_RETURNABLE = re.compile(r"\bafter\s(?:the\s)?returnable\sdate\b")
RETURNABLE_WITHIN = re.compile(rf"\breturnable\s(?:with)?in\s(?:a\s)?(?:period\sof\s)?{_QTY}")
RETURNABLE_ON = re.compile(r"\breturnable\s(?:on|by)\s")


@dataclass(frozen=True)
class Reading:
    status: str
    date: date | None = None
    rule: str | None = None
    phrase: str | None = None
    needs_review: bool = False
    confidence: float = 0.0


@dataclass(frozen=True)
class _Sentence:
    raw: str
    low: str


# ------------------------------------------------------------------------------------------------ helpers


def _number(word: str | None) -> int | None:
    if word is None:
        return None
    w = word.lower()
    if w.isdigit():
        return int(w)
    parts = re.split(r"[\s-]", w)
    if len(parts) == 2 and parts[0] in _TENS:  # "twenty one", "thirty-five"
        unit = WORD_NUMBERS.get(parts[1])
        return _TENS[parts[0]] + unit if unit is not None and 1 <= unit <= 9 else None
    return WORD_NUMBERS.get(w)


def _make_date(y: int, m: int, d: int) -> date | None:
    if y < 100:
        y += 2000
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _date_spans(low: str) -> list[tuple[int, int, date | None]]:
    """(start, end, date) of every written date of a lower-case sentence, sorted by start; an impossible date
    (31.02) keeps its place with None."""
    out: list[tuple[int, int, date | None]] = []
    for m in _NUMERIC_DATE.finditer(low):
        out.append((m.start(), m.end(), _make_date(int(m.group(3)), int(m.group(2)), int(m.group(1)))))
    for m in _DAY_MONTH_DATE.finditer(low):
        out.append((m.start(), m.end(), _make_date(int(m.group(3)), MONTHS[m.group(2)], int(m.group(1)))))
    for m in _MONTH_DAY_DATE.finditer(low):
        out.append((m.start(), m.end(), _make_date(int(m.group(3)), MONTHS[m.group(1)], int(m.group(2)))))
    out.sort(key=lambda t: t[0])
    return out


def parse_dates(sentence: str) -> list[date]:
    """Every valid date written in `sentence` (day-month order; two-digit years as 20yy), in text order."""
    low = _join_dates(_WS.sub(" ", sentence or "")).lower()
    return [d for _, _, d in _date_spans(low) if d is not None]


def count_period(order_date: date, n: int, unit: str) -> date:
    """`n` days, weeks, fortnights or calendar months after `order_date` (months clamped to the month's end)."""
    u = unit.lower().rstrip("s")
    if u == "day":
        return order_date + timedelta(days=n)
    if u == "week":
        return order_date + timedelta(weeks=n)
    if u == "fortnight":
        return order_date + timedelta(days=14 * n)
    if u == "month":
        months = order_date.month - 1 + n
        y, m = order_date.year + months // 12, months % 12 + 1
        return date(y, m, min(order_date.day, calendar.monthrange(y, m)[1]))
    raise ValueError(f"unknown unit {unit!r}")


def _join_dates(text: str) -> str:
    return _SPACED_DATE.sub(lambda m: "".join(m.groups()), text)


def _sentences(text: str) -> list[_Sentence]:
    flat = _PAGE_HEADER.sub(" ", _WS.sub(" ", text[-MAX_TEXT:]))  # the direction closes an order
    flat = _join_dates(_WS.sub(" ", flat).strip())
    return [_Sentence(s, s.lower()) for s in _SPLIT.split(flat) if s]


def _phrase(s: _Sentence, at: int = 0) -> str:
    if len(s.raw) <= PHRASE_MAX:
        return s.raw
    start = max(0, min(at - 100, len(s.raw) - PHRASE_MAX))
    return s.raw[start : start + PHRASE_MAX].strip()


def _in_window(d: date | None, order_date: date, max_ahead_days: int) -> bool:
    return d is not None and order_date < d <= order_date + timedelta(days=max_ahead_days)


@dataclass(frozen=True)
class _Prayers:
    """The prayers of one sentence (`_PRAYER`) and the words that grant one (`_GRANTED`), found once per sentence so
    that each verb is checked by bisection (linear time on hostile text)."""

    prayers: list[int]
    grants: list[int]

    @classmethod
    def of(cls, low: str) -> _Prayers:
        return cls([m.end() for m in _PRAYER.finditer(low)], [m.start() for m in _GRANTED.finditer(low)])

    def before(self, pos: int) -> bool:
        """A prayer before `pos` with no grant between it and `pos`."""
        i = bisect.bisect_right(self.prayers, pos) - 1
        if i < 0:
            return False
        j = bisect.bisect_left(self.grants, self.prayers[i])
        return not (j < len(self.grants) and self.grants[j] < pos)


_NO_PRAYERS = _Prayers([], [])


def _reported(low: str, verb: re.Match[str], prayers: _Prayers = _NO_PRAYERS) -> bool:
    """A listing verb inside a report of some date ("which is fixed on", "has been listed on", "the connected appeal
    fixed on", "is slated to be listed on") or inside a prayer the court has not granted ("learned counsel prays
    that the matter be listed on")."""
    word = verb.group(0)
    lookback = max(0, verb.start() - REPORT_LOOKBACK)
    if prayers.before(verb.start()):
        return True
    if _OTHER_REPORTING_VERB.match(word):
        return _REPORTED_OTHER.search(low, lookback, verb.start()) is not None
    if not _REPORTING_VERB.match(word):
        return False
    if (
        _PARTICIPLE.fullmatch(word)
        and not _AGAIN.match(low, verb.end())
        and _REPORTED_NOUN.search(low, lookback, verb.start())
    ):
        return True
    pattern = _OF if word.endswith("ing") else _REPORTED
    return pattern.search(low, lookback, verb.start()) is not None


def _not_a_listing(low: str, verb: re.Match[str], date_start: int) -> bool:
    """A listing verb and a date that is not the court's listing date: the noun "list", a negation ("shall not be
    listed on <date>"), a deadline ("by <date>", "ends on <date>"), or a time limit that is "fixed"."""
    word = verb.group(0)
    lookback = max(0, verb.start() - REPORT_LOOKBACK)
    if _NEGATED.search(low, lookback, verb.start()):
        return True
    if _LIST_WORD.fullmatch(word) and (
        _OF_AFTER.match(low, verb.end()) or _LIST_NOUN_BEFORE.search(low, lookback, verb.start())
    ):
        return True
    gap = low[verb.end() : date_start]
    if _DEADLINE_BEFORE_DATE.search(gap) or _DEADLINE_WORD.search(gap):
        return True
    return bool(
        _FIX.fullmatch(word)
        and (_TIME_LIMIT_BEFORE.search(low, lookback, verb.start()) or _FIXED_FOR_ACT.match(low, verb.end()))
    )


def _period_of(m: re.Match[str]) -> tuple[int, str] | None:
    """(n, unit) of a period match; `2 (two)` and `two (2)` must agree when both are given."""
    a, b = _number(m.group("a")), _number(m.group("b") or m.group("c"))
    unit = m.group("u1") or m.group("u2") or m.group("u3")
    if a is None or (b is not None and b != a) or a < 1:
        return None
    return a, unit


# ------------------------------------------------------------------------------------------------ the reader


@dataclass
class _Dates:
    """The listing dates of one sentence: (date, verb position, firm) candidates, and whether the sentence reports a
    date after the order date for something else ("the connected appeal is fixed on <date>")."""

    candidates: list[tuple[date, int, bool]]
    reported: bool


def _sentence_dates(
    low: str,
    spans: list[tuple[int, int, date | None]],
    verbs: list[re.Match[str]],
    order_date: date,
    max_ahead_days: int,
    prayers: _Prayers = _NO_PRAYERS,
) -> _Dates:
    """Each date belongs to the nearest listing verb before it (owner's decision of 17 Oct 2026, point 3)."""
    ends = [v.end() for v in verbs]
    out = _Dates([], False)
    for start, end, d in spans:
        i = bisect.bisect_right(ends, start) - 1
        if i < 0:
            continue
        v = verbs[i]
        gap = low[v.end() : start]
        if len(gap) > NEAR or ";" in gap:  # too far, or another clause ("list after 2 weeks; file by <date>")
            continue
        if _NEEDS_ON_FOR.fullmatch(v.group(0)) and gap.strip() and not _ON_OR_FOR.search(gap):
            continue
        if _reported(low, v, prayers):
            if d is not None and d > order_date:
                out.reported = True
            continue
        if _not_a_listing(low, v, start) or not _in_window(d, order_date, max_ahead_days):
            continue
        kind = _date_kind(gap, _QUALIFIER_AFTER.match(low, end) is not None)
        if kind is not None:
            out.candidates.append((d, v.start(), kind == "firm"))
    return out


def _plain_words(words: str) -> bool:
    """Only the matter listed and how, between the verb and the date ("this matter again before the Division Bench
    for hearing", "these cases along with WP(C) 12/2026")."""
    for raw in words.split():
        tok = _TOKEN_TRIM.sub("", raw)
        if not tok or _CASE_NO_TOKEN.fullmatch(tok):
            continue
        if not ({tok, tok.rstrip(".")} & (_PLAIN_WORDS | _CASE_TYPES)):
            return False
    return True


def _date_kind(gap: str, qualified_after: bool) -> str | None:
    """`firm` (a plain direction), `qualified` (a date to confirm) or None (the date is not this direction's) for a
    date whose nearest listing verb is `gap` before it (owner's decision of 17 Oct 2026, points 1, 2 and 4; review
    of 17 Oct 2026)."""
    if _FOREIGN_IN_GAP.search(gap):
        return None  # "list after 2 weeks, and the respondents to file their reply on <date>"
    core = _AFTER_TAIL.sub("", gap)
    period = None
    for period in PERIOD_PHRASE.finditer(core):  # noqa: B007 - the last period before the date
        pass
    if period is not None and not _SPELLED_OUT.fullmatch(core, period.end()):
        return None  # "list after 2 weeks ... on <date>": the period is the direction (point 1)
    if not qualified_after and core == gap and not _AFTER_IN_GAP.search(gap):
        tail = _PLAIN_TAIL.search(gap)
        if _plain_words(gap[: tail.start()] if tail else gap):
            return "firm"
    return "qualified"


def _own_direction(
    low: str, verbs: list[re.Match[str]], prayers: _Prayers = _NO_PRAYERS
) -> re.Match[str] | None:
    """The first direction to list that is not itself a reporting verb ("the case is posted on <date>")."""
    starts = [v.start() for v in verbs]
    for m in DIRECTION.finditer(low):
        i = bisect.bisect_left(starts, m.end()) - 1
        if i >= 0 and verbs[i].end() > m.start() and _reported(low, verbs[i], prayers):
            continue
        return m
    return None


def _sentence_period(
    s: _Sentence,
    verbs: list[re.Match[str]],
    direction: re.Match[str],
    order_date: date,
    max_ahead_days: int,
) -> Reading | None:
    """`list_after_period`: a period after the first listing verb (or `adjourned for|by`) of the sentence."""
    low = s.low
    first_verb = verbs[0].start() if verbs else direction.start()  # "List the matter 2 weeks" starts at it
    adj = ADJOURNED_FOR.search(low)
    if adj is not None:
        first_verb = min(first_verb, adj.start())
    pm = PERIOD_PHRASE.search(low, first_verb)
    if pm is None:
        return None
    p = _period_of(pm)
    if p is None:
        return None
    counted = count_period(order_date, p[0], p[1])
    if not _in_window(counted, order_date, max_ahead_days):
        return None
    return _reading(PERIOD, counted, LIST_AFTER_PERIOD, _phrase(s, direction.start()))


def read_order_text(text: str | None, order_date: date, *, max_ahead_days: int = MAX_AHEAD_DAYS) -> Reading:
    """Decision 3 and the owner's decision of 17 Oct 2026: the reading of one order's text. Never raises on hostile
    text."""
    if text is None or not text.strip():
        return Reading(NO_TEXT, needs_review=True)
    sentences = _sentences(text)

    listing: dict[date, list[tuple[_Sentence, int, bool]]] = {}
    conflicts: list[tuple[_Sentence, int]] = []
    periods: list[Reading] = []
    returnable_dates: list[tuple[date, _Sentence, int]] = []
    returnable_within: list[tuple[int, str, _Sentence, int]] = []
    after_returnable: list[tuple[_Sentence, int]] = []
    undated: list[tuple[_Sentence, int]] = []
    no_date_by_design: list[tuple[_Sentence, int]] = []

    for s in sentences:
        low = s.low
        spans = _date_spans(low)
        starts = [st for st, _, _ in spans]
        verbs = list(LISTING_VERB.finditer(low))
        prayers = _Prayers.of(low)
        found = _sentence_dates(low, spans, verbs, order_date, max_ahead_days, prayers)
        for m in RETURNABLE_ON.finditer(low):
            i = bisect.bisect_left(starts, m.end())
            if (
                i < len(spans)
                and spans[i][0] - m.end() <= 3
                and _in_window(spans[i][2], order_date, max_ahead_days)
            ):
                returnable_dates.append((spans[i][2], s, m.start()))
        for m in RETURNABLE_WITHIN.finditer(low):
            p = _period_of(m)
            if p is not None:
                returnable_within.append((p[0], p[1], s, m.start()))

        if found.reported:
            # another matter's date in the sentence: none of its dates is this case's listing date (point 3)
            own = _own_direction(low, verbs, prayers)
            if found.candidates:
                conflicts.append((s, found.candidates[0][1]))
            elif own is not None:
                period = _sentence_period(s, verbs, own, order_date, max_ahead_days)
                if period is not None:  # "List after 3 weeks since the connected appeal is fixed on <date>"
                    periods.append(period)
                else:
                    conflicts.append((s, own.start()))
            elif (
                any_direction := DIRECTION.search(low)
            ) is not None:  # "this matter is to be listed on <date>"
                undated.append((s, any_direction.start()))
            continue
        if found.candidates:
            future = {d for _, _, d in spans if d is not None and d > order_date}
            if len(future) > 1:  # two different dates in the sentence of a listing date (point 3)
                conflicts.append((s, found.candidates[0][1]))
                continue
            for d, at, firm in found.candidates:
                listing.setdefault(d, []).append((s, at, firm))

        direction = DIRECTION.search(low)
        if direction is None:
            continue
        if NO_DATE_BY_DESIGN.search(low):
            no_date_by_design.append((s, direction.start()))
            continue
        ar = AFTER_RETURNABLE.search(low)
        if ar is not None:
            after_returnable.append((s, ar.start()))
            continue
        period = _sentence_period(s, verbs, direction, order_date, max_ahead_days)
        if period is not None:
            periods.append(period)
            continue
        if not found.candidates:
            undated.append((s, direction.start()))

    # precedence (decision 3; owner's decision of 17 Oct 2026)
    if conflicts or len(listing) > 1:
        if conflicts:
            s, at = conflicts[0]
        else:
            s, at, _ = next(iter(listing.values()))[0]  # the earliest in the text
        return Reading(UNCLEAR, rule=CONFLICTING_DATES, phrase=_phrase(s, at), needs_review=True)
    if len(listing) == 1:
        ((d, mentions),) = listing.items()
        s, at, _ = mentions[0]
        # a direction after a period anywhere in the order ("List after 2 weeks. Let the connected case also be listed
        # on <date>"): the written date is only suggested, the period is always confirmed (review of 17 Oct 2026)
        period_in_order = any(p.rule == LIST_AFTER_PERIOD for p in periods)
        if all(firm for _, _, firm in mentions) and not period_in_order:
            return _reading(SPECIFIC, d, LIST_ON_DATE, _phrase(s, at))
        s, at, _ = next((m for m in mentions if not m[2]), mentions[0])
        return _reading(SPECIFIC, d, QUALIFIED_DATE, _phrase(s, at))
    if after_returnable:
        s, at = after_returnable[-1]
        if returnable_dates:
            d = returnable_dates[-1][0]
            periods.append(_reading(SPECIFIC, d, RETURNABLE_DATE, _phrase(s, at)))
        elif returnable_within:
            n, unit, _, _ = returnable_within[-1]
            counted = count_period(order_date, n, unit)
            if _in_window(counted, order_date, max_ahead_days):
                periods.append(_reading(PERIOD, counted, AFTER_RETURNABLE_PERIOD, _phrase(s, at)))
            else:
                undated.append((s, at))
        else:
            undated.append((s, at))
    if periods:
        return periods[-1]
    if returnable_dates:
        d, s, at = returnable_dates[-1]
        return _reading(SPECIFIC, d, RETURNABLE_DATE, _phrase(s, at))
    if undated:
        s, at = undated[-1]
        return Reading(UNCLEAR, rule=NO_COUNTABLE_DATE, phrase=_phrase(s, at), needs_review=True)
    if returnable_within and not no_date_by_design:
        n, unit, s, at = returnable_within[-1]
        counted = count_period(order_date, n, unit)
        if _in_window(counted, order_date, max_ahead_days):
            return _reading(PERIOD, counted, RETURNABLE_PERIOD, _phrase(s, at))
    if no_date_by_design:
        s, at = no_date_by_design[-1]
        return Reading(NONE, phrase=_phrase(s, at))
    return Reading(NONE)


def _reading(status: str, d: date, rule: str, phrase: str) -> Reading:
    return Reading(
        status,
        date=d,
        rule=rule,
        phrase=phrase,
        # the text alone never makes a date firm: the service compares it with the court's own date (owner's
        # decision of 17 Oct 2026 (second), point 1)
        needs_review=True,
        confidence=CONFIDENCE[rule],
    )


# ------------------------------------------------------------------------------------------------ describe
# design next-date-direct, decision 8: the plain words of an "around" date, made from the stored court sentence

AROUND_RULES = frozenset(
    {LIST_AFTER_PERIOD, AFTER_RETURNABLE_PERIOD, RETURNABLE_PERIOD, QUALIFIED_DATE, RETURNABLE_DATE}
)
FALLBACK_WORDS = {
    LIST_AFTER_PERIOD: "counted from the order",
    AFTER_RETURNABLE_PERIOD: "counted from the order",
    RETURNABLE_PERIOD: "counted from the order",
    QUALIFIED_DATE: "not before this date",
    RETURNABLE_DATE: "returnable date of the notice",
}
_QUALIFIER_BEFORE = re.compile(
    r"\b(on\sor\safter|on\sand\safter|not\searlier\sthan|not\sbefore|subsequent\sto|commencing(?:\sfrom|\son)?"
    r"|after|from)\s(?:the\s)?$"
)


def _period_words(n: int, unit: str) -> str:
    u = unit.lower().rstrip("s")
    if u == "fortnight" and n == 1:
        return "after a fortnight"
    return f"after {n} {u}{'' if n == 1 else 's'}"


def describe(rule: str | None, phrase: str | None, order_date: date | None, found: date | None) -> str | None:
    """The words after the date of an around reading: "after 3 weeks", "after 15.12.2026" (the date as written),
    "returnable date of the notice"; a fixed fallback per rule when the words cannot be found in the sentence; None
    for an exact rule (`list_on_date`) or no rule. Pure; every pattern is bounded and the sentence is at most
    `PHRASE_MAX` characters."""
    if rule not in AROUND_RULES:
        return None
    fallback = FALLBACK_WORDS[rule]
    if rule == RETURNABLE_DATE:
        return fallback
    raw = _join_dates(_WS.sub(" ", (phrase or "")[:PHRASE_MAX])).strip()
    low = raw.lower()
    if not low:
        return fallback
    if rule in (LIST_AFTER_PERIOD, AFTER_RETURNABLE_PERIOD, RETURNABLE_PERIOD):
        for pattern in (PERIOD_PHRASE, RETURNABLE_WITHIN):
            for m in pattern.finditer(low):
                p = _period_of(m)
                if p is None:
                    continue
                if order_date is not None and found is not None:
                    try:
                        if count_period(order_date, p[0], p[1]) != found:
                            continue
                    except ValueError:
                        continue
                return _period_words(*p)
        return fallback
    # qualified_date: the qualifier written just before the date the reading found
    same_case = len(raw) == len(low)
    for start, end, d in _date_spans(low):
        if d is None or (found is not None and d != found):
            continue
        q = _QUALIFIER_BEFORE.search(low, max(0, start - 30), start)
        if q is None:
            continue
        written = raw[start:end] if same_case else low[start:end]
        return f"{q.group(1)} {written}"
    return fallback
