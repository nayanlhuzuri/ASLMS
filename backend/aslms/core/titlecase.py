"""The Title Case rule of the portal's labels (design `portal-ui-polish-2`, decisions 1 and 2), the same rule as
`frontend/src/lib/titleCase.ts` with the same pinned examples in both test suites.

Labels (navigation entries, tabs, buttons, titles, column headers, field labels, badges) use Title Case: short joining
words stay lower case unless first or last in their segment, acronyms stay in capitals, every other word gets a
capital first letter (a hyphenated word capitalises only its first part). Sentences keep sentence case.

Used only by tests and the seed's own checks: nothing typed by a person is ever re-cased by the server."""

from __future__ import annotations

import re

SMALL_WORDS: frozenset[str] = frozenset(
    {"a", "an", "the", "and", "or", "of", "by", "to", "in", "on", "for", "at", "with"}
)
# lower case -> as written; "apis" keeps its plural s in lower case
ACRONYMS: dict[str, str] = {
    w.lower(): w
    for w in (
        "ASLMS",
        "CNR",
        "NAPIX",
        "PDF",
        "API",
        "APIs",
        "OTP",
        "IST",
        "URL",
        "ID",
        "SMS",
        "CSV",
        "AI",
        "JSON",
        "IP",
        "NJDG",
    )
}

_SEPARATORS = re.compile(r"( · | / | — | – |: )")
_LEADING = "([\"'“‘"
_TRAILING = ")]\"'”’,;.!?"


def _case_word(word: str, first: bool, last: bool) -> str:
    start = 0
    while start < len(word) and word[start] in _LEADING:
        start += 1
    end = len(word)
    while end > start and word[end - 1] in _TRAILING:
        end -= 1
    core = word[start:end]
    if not core:
        return word
    if any(ch.isdigit() for ch in core) or any(ch.isupper() for ch in core[1:]):
        cased = core
    elif core.lower() in ACRONYMS:
        cased = ACRONYMS[core.lower()]
    elif core.lower() in SMALL_WORDS and not first and not last:
        cased = core.lower()
    else:
        cased = core[0].upper() + core[1:]
    return word[:start] + cased + word[end:]


def _case_segment(segment: str) -> str:
    words = segment.split(" ")
    # the first and last words are counted among the words that hold text
    filled = [i for i, w in enumerate(words) if w]
    if not filled:
        return segment
    first, last = filled[0], filled[-1]
    return " ".join(_case_word(w, i == first, i == last) if w else w for i, w in enumerate(words))


def title_case(text: str) -> str:
    """`text` in Title Case by the rule of decision 2."""
    parts = _SEPARATORS.split(text)
    return "".join(part if i % 2 else _case_segment(part) for i, part in enumerate(parts))


def is_title_case(text: str) -> bool:
    return title_case(text) == text
