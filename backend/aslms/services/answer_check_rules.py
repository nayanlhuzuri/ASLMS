"""The rule tables of the sentence checks (design `research-index`, decisions 24 to 27). Pure data and compiled
patterns: no database, no network, no model."""

from __future__ import annotations

import re

from aslms.services import order_parse_rules as R

CHECKS_VERSION = 1

# decision 24: no sentence end after these (compared lower-cased, with their full stop)
ABBREVIATIONS = frozenset(
    {
        "no.",
        "nos.",
        "sri.",
        "smt.",
        "dr.",
        "mr.",
        "mrs.",
        "ms.",
        "vs.",
        "v.",
        "u/s.",
        "i.e.",
        "e.g.",
        "viz.",
        "rs.",
        "hon'ble.",
        "art.",
        "sec.",
        "cl.",
        "para.",
        "paras.",
        "pp.",
        "p.",
        "shri.",
        "ors.",
        "anr.",
        "govt.",
        "dept.",
        "etc.",
    }
)

QUOTES_OPEN = '"“'
QUOTES_ANY = "\"“”'‘’"
MARKER = re.compile(r"\[S(\d+)\]")
MARKERS_AT = re.compile(r"(?:[ \t]*\[S\d+\])+")
QUOTED = re.compile(r"[\"“]([^\"“”]{1,2000}?)[\"”]")
WORD = re.compile(r"[A-Za-z0-9]+(?:'[A-Za-z]+)?")

# decision 27: dates
MONTHS = {
    m: i
    for i, names in enumerate(
        (
            ("january", "jan"),
            ("february", "feb"),
            ("march", "mar"),
            ("april", "apr"),
            ("may",),
            ("june", "jun"),
            ("july", "jul"),
            ("august", "aug"),
            ("september", "sep", "sept"),
            ("october", "oct"),
            ("november", "nov"),
            ("december", "dec"),
        ),
        start=1,
    )
    for m in names
}
_MONTH = r"(?P<mon>" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\.?"
DATE_NUMERIC = re.compile(r"\b" + R.DATE + r"\b")
DATE_DMY_WORDS = re.compile(
    r"\b(?P<d>\d{1,2})(?:st|nd|rd|th)?\s+(?:day\s+of\s+)?" + _MONTH + r",?\s+(?P<y>(?:19|20)\d{2})\b", re.I
)
DATE_MDY_WORDS = re.compile(
    r"\b" + _MONTH + r"\s+(?P<d>\d{1,2})(?:st|nd|rd|th)?,?\s+(?P<y>(?:19|20)\d{2})\b", re.I
)

# decision 27: numbers of two or more digits, or any number with a unit
UNIT = r"(?:%|per\s*cent|days?|weeks?|months?|years?)"
AMOUNT = re.compile(r"\bRs\.?\s*(?P<n>\d[\d,]*(?:\.\d+)?)", re.I)
NUMBER_UNIT = re.compile(r"\b(?P<n>\d+(?:\.\d+)?)\s*" + UNIT + r"\b", re.I)
NUMBER = re.compile(r"(?<![\w/.])(?P<n>\d[\d,]*\d|\d{2,})(?![\w/])")
NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
    "hundred": 100,
}
NUMBER_WORDS_RE = re.compile(
    r"\b(?P<t>twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)[\s-](?P<u>one|two|three|four|five|six|seven|"
    r"eight|nine)\b|\b(?P<w>" + "|".join(NUMBER_WORDS) + r")\b",
    re.I,
)

# decision 27: printed case numbers (`WP(C)/7013/2024`, `W.P.(C) No. 7013 of 2024`, `Crl.A. 12/2020`) and CNRs
CASE_NO_RE = re.compile(
    r"\b(?P<t>[A-Z][A-Za-z.]{0,12}(?:\s?\([A-Za-z.]{1,6}\))?(?:\s?[A-Za-z.]{1,6})?)\.?[\s/]*"
    r"(?:No\.?\s*)?(?P<n>\d{1,6})\s*(?:/|\s+of\s+)\s*(?P<y>(?:19|20)\d{2})\b"
)
CNR_RE = re.compile(r"\b[A-Z]{4}\d{12}\b")

# decision 27: names
NAME_RUN = re.compile(r"\b(?:[A-Z][A-Za-z'’.-]*\.?)(?:\s+(?:[A-Z][A-Za-z'’.-]*\.?))+")
NAME_STOP = frozenset(
    w.lower()
    for w in (
        "High Court Gauhati Supreme State Assam Government Govt India Union Petitioner Petitioners Respondent "
        "Respondents Appellant Appellants Hon'ble Honble Justice Court Section Sections Article Articles Act Acts Rule "
        "Rules Order Orders Writ Petition Petitions The A An In On Of And Or For To By With At From As This That "
        "These Those It Its He She They Learned Counsel Standing Advocate General Senior Additional Department "
        "Director Commissioner Secretary Principal Deputy Joint Under District Deputy Chief Mr Mrs Ms Dr Sri Smt "
        "Shri Judgment Final Interim Case Cases No Nos Bench Division Single Registry Registrar Deputy Notice "
        "Affidavit Contempt Appeal Review Application Miscellaneous Civil Criminal Code Procedure Constitution "
        "January February March April May June July August September October November December Jan Feb Mar Apr "
        "Jun Jul Aug Sep Sept Oct Nov Dec Monday Tuesday Wednesday Thursday Friday Saturday Sunday "
        "Court's Record Records Details Source Sources Internal Note Notes Filing Dated Page Paragraph Paragraphs "
        "However Accordingly Therefore Thus Also Further Moreover Here There When Where Which Who What If Since "
        "After Before Until Within Upon Under Above Below According Both Each Every No Not Yes Is Are Was Were "
        "Be Been Has Have Had Do Does Did Will Shall May Might Can Could Should Would Must Taxation Service "
        "Education Health Revenue Finance Home Police Board Authority Officer Officers Superintendent "
        "Assam's State's Government's Hon’ble Ors Anr Vs V W.P WP Crl Misc Rs Pay"
    ).split()
)

# decision 27: outcome words, each with the forms that back it
OUTCOME_WORDS: dict[str, tuple[str, ...]] = {
    "partly allowed": ("partly allowed", "partially allowed", "allowed in part", "allowed partly"),
    "disposed of": ("disposed of", "disposed off", "disposal"),
    "allowed": ("allow",),
    "dismissed": ("dismiss",),
    "withdrawn": ("withdraw",),
    "closed": ("close",),
    "quashed": ("quash",),
    "set aside": ("set aside", "set-aside", "setting aside"),
    "stayed": ("stay",),
    "granted": ("grant",),
    "rejected": ("reject",),
    "upheld": ("uph", "uphold"),
    "remanded": ("remand",),
}
OUTCOME_RE = re.compile(
    r"\b(?P<w>partly\s+allowed|disposed\s+of|set\s+aside|allowed|dismissed|withdrawn|closed|quashed|stayed|"
    r"granted|rejected|upheld|remanded)\b",
    re.I,
)
# the rule-read outcome (row 250's `order_outcome`) that backs an outcome word
RULE_OUTCOME = {
    "allowed": "allowed",
    "partly allowed": "partly_allowed",
    "dismissed": "dismissed",
    "disposed of": "disposed_of",
    "withdrawn": "withdrawn",
    "closed": "closed",
}

REPORTERS = tuple(rx for _name, rx in R.REPORTER_PATTERNS)

UNCITED_MAX_WORDS = 12
QUOTE_MIN_WORDS = 3
REMOVED_NOTE = (
    "[Removed by ASLMS: {n} {sentences} whose quotes, dates, numbers, case numbers, names or outcomes were not found in "
    "the records they cite.]"
)
REASONS = ("uncited", "quote", "date", "number", "case_no", "name", "outcome")
