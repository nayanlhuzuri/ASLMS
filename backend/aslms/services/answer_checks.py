"""The sentence checks of every local-model answer (design `research-index`, decisions 23 to 29). Pure: no database,
no network, no model; standard library and `aslms.services` rule modules only (a unit test checks it).

`check(answer, sources)` takes the answer after `check_citations` (valid `[Sn]` markers only) and, for each source
number, the exact text given to the model (header and text). Every sentence is split by `split_sentences`; a sentence
is removed when it states a fact without a valid marker (decision 26), or when a quote, a date, a number, a case
number or citation, a name or an outcome word in it is not in the text of the sources it cites (decisions 25 and 27).
The answer is withheld when its first sentence is removed, when more than half are removed, or when no cited sentence
remains (decision 28). Negation is not checked; rules cannot catch a wrong reading of correctly quoted text."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from aslms.services import answer_check_rules as K

LEAD_CHARS = " \t\"“'‘("

# ------------------------------------------------------------------------------------------------ sentences


@dataclass(frozen=True)
class Sentence:
    text: str
    start: int
    end: int


def _token_before(text: str, start: int, i: int) -> str:
    j = i
    while j > start and not text[j - 1].isspace() and text[j - 1] not in "([":
        j -= 1
    return text[j:i].lstrip("\"“'‘")


def _no_end_at(text: str, start: int, i: int) -> bool:
    """A full stop at `i` that ends no sentence: after an abbreviation, an initial, or inside a dotted word."""
    word = _token_before(text, start, i)
    if not word:
        return False
    if (word + ".").lower() in K.ABBREVIATIONS:
        return True
    if len(word) == 1 and word.isalpha():
        return True  # an initial: "A. K. Das"
    if "." in word and all(p.isalpha() for p in word.split(".") if p):
        return True  # "W.P", "Crl.A", "i.e"
    return False


def split_sentences(text: str) -> list[Sentence]:
    """Decision 24: split at `.`, `?` or `!` followed by whitespace and an upper-case letter, a digit, a quote or the
    end, or at a line break; never after an abbreviation or an initial, inside a dotted case number or inside
    brackets. `[Sn]` markers right after a sentence end belong to that sentence."""
    out: list[Sentence] = []
    n = len(text)
    start = 0
    depth = 0
    i = 0

    def emit(a: int, b: int) -> None:
        seg = text[a:b]
        lead = len(seg) - len(seg.lstrip())
        trail = len(seg.rstrip())
        if seg.strip():
            out.append(Sentence(seg.strip(), a + lead, a + trail))

    while i < n:
        ch = text[i]
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        elif ch == "\n":
            emit(start, i)
            start = i + 1
            depth = 0
        elif ch in ".?!" and depth == 0:
            if ch == "." and _no_end_at(text, start, i):
                i += 1
                continue
            j = i + 1
            while j < n and text[j] in "\"”’'":
                j += 1
            m = K.MARKERS_AT.match(text, j)
            if m and m.end() > j:
                j = m.end()
            if j >= n:
                emit(start, n)
                start = n
                i = n
                break
            if text[j].isspace():
                k = j
                while k < n and text[k] in " \t":
                    k += 1
                if (
                    k >= n
                    or text[k] == "\n"
                    or text[k].isupper()
                    or text[k].isdigit()
                    or text[k] in K.QUOTES_ANY
                ):
                    emit(start, j)
                    start = j
                    i = j
                    continue
        i += 1
    if start < n:
        emit(start, n)
    return out


# ------------------------------------------------------------------------------------------------ normalising


def _norm_char(c: str) -> str:
    if c in '“”„"':
        return '"'
    if c in "‘’'`":
        return "'"
    if c in "–—‐‑":
        return "-"
    return c


def normalise(text: str) -> tuple[str, list[int]]:
    """Decision 25's only normalisation: whitespace runs as one space, curly quotes and apostrophes as straight ones,
    en and em dashes as hyphens. Returns the text and, for each of its characters, the original offset."""
    out: list[str] = []
    idx: list[int] = []
    space = False
    for pos, c in enumerate(text):
        if c.isspace():
            if not space and out:
                out.append(" ")
                idx.append(pos)
            space = True
            continue
        space = False
        out.append(_norm_char(c))
        idx.append(pos)
    while out and out[-1] == " ":
        out.pop()
        idx.pop()
    return "".join(out), idx


def compact(text: str) -> str:
    """Case numbers and citations compared as `ix_cases_case_no_compact` compacts them (upper case, no spaces), with
    `No.`, full stops and slashes dropped and ` of ` read as a separator, so `W.P.(C) No. 7013 of 2024`,
    `WP(C) 7013/2024` and `WP(C)/7013/2024` compare equal."""
    t = re.sub(r"\s+of\s+", "/", text, flags=re.I)
    t = re.sub(r"(?<![A-Za-z])Nos?\.?\s*(?=\d)", "", t, flags=re.I)
    return re.sub(r"[\s./]+", "", t).upper()


def contains_compact(needle: str, hay: str) -> bool:
    """`needle` inside `hay` (both compacted), never as part of a longer number (`4SCC1` is not in `4SCC12`)."""
    if not needle:
        return True
    start = 0
    while True:
        at = hay.find(needle, start)
        if at < 0:
            return False
        before = hay[at - 1] if at > 0 else ""
        after = hay[at + len(needle)] if at + len(needle) < len(hay) else ""
        if not (needle[0].isdigit() and before.isdigit()) and not (needle[-1].isdigit() and after.isdigit()):
            return True
        start = at + 1


# ------------------------------------------------------------------------------------------------ token readers


def dates(text: str) -> set[tuple[int, int, int]]:
    """Every date written `12.03.2024`, `12/3/2024`, `12 March 2024`, `12th March, 2024` or `March 12, 2024`."""
    out: set[tuple[int, int, int]] = set()
    for m in K.DATE_NUMERIC.finditer(text):
        out.add((int(m.group("y")), int(m.group("m")), int(m.group("d"))))
    for rx in (K.DATE_DMY_WORDS, K.DATE_MDY_WORDS):
        for m in rx.finditer(text):
            out.add((int(m.group("y")), K.MONTHS[m.group("mon").lower().rstrip(".")], int(m.group("d"))))
    return {d for d in out if 1 <= d[1] <= 12 and 1 <= d[2] <= 31}


def _spans(rx: re.Pattern, text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in rx.finditer(text)]


def _inside(pos: int, spans: list[tuple[int, int]]) -> bool:
    return any(a <= pos < b for a, b in spans)


def case_numbers(text: str) -> list[str]:
    out = [compact(m.group(0)) for m in K.CASE_NO_RE.finditer(text)]
    out += [m.group(0).upper() for m in K.CNR_RE.finditer(text)]
    for rx in K.REPORTERS:
        out += [compact(m.group(0)) for m in rx.finditer(text)]
    return out


def numbers(text: str) -> list[int | float]:
    """Numbers of two or more digits and numbers with a unit, outside dates, case numbers and citations."""
    skip = (
        _spans(K.DATE_NUMERIC, text)
        + _spans(K.DATE_DMY_WORDS, text)
        + _spans(K.DATE_MDY_WORDS, text)
        + _spans(K.CASE_NO_RE, text)
        + _spans(K.CNR_RE, text)
        + [s for rx in K.REPORTERS for s in _spans(rx, text)]
    )
    out: list[int | float] = []
    taken: list[tuple[int, int]] = []
    for rx in (K.AMOUNT, K.NUMBER_UNIT, K.NUMBER):
        for m in rx.finditer(text):
            if _inside(m.start("n"), skip) or _inside(m.start("n"), taken):
                continue
            taken.append((m.start("n"), m.end("n")))
            raw = m.group("n").replace(",", "")
            try:
                out.append(float(raw) if "." in raw else int(raw))
            except ValueError:
                continue
    return out


def source_numbers(text: str) -> set[int | float]:
    """The numbers a source backs: every run of digits (commas removed) and the English words for 1 to 100."""
    out: set[int | float] = set()
    for m in re.finditer(r"\d[\d,]*(?:\.\d+)?", text):
        raw = m.group(0).replace(",", "").rstrip(".")
        try:
            out.add(float(raw) if "." in raw else int(raw))
        except ValueError:
            continue
    for m in K.NUMBER_WORDS_RE.finditer(text):
        if m.group("w"):
            out.add(K.NUMBER_WORDS[m.group("w").lower()])
        else:
            out.add(K.NUMBER_WORDS[m.group("t").lower()] + K.NUMBER_WORDS[m.group("u").lower()])
    return out


def names(text: str) -> list[list[str]]:
    """Runs of two or more capitalised words with at least one word outside `NAME_STOP`: the non-stop words. The first
    word of the sentence is capitalised anyway, so it is left out of a run that starts the sentence."""
    out: list[list[str]] = []
    lead = len(text) - len(text.lstrip(LEAD_CHARS))
    for m in K.NAME_RUN.finditer(text):
        words = [w.strip(".'’-") for w in m.group(0).split()]
        words = [w for w in words if w]
        if len(words) < 2:
            continue
        if m.start() <= lead:
            words = words[1:]
        keep = [w for w in words if w.lower() not in K.NAME_STOP and len(w) > 1 and not w.isdigit()]
        if keep:
            out.append(keep)
    return out


def outcome_words(text: str) -> list[str]:
    return [re.sub(r"\s+", " ", m.group("w").lower()) for m in K.OUTCOME_RE.finditer(text)]


def _has_checkable(text: str) -> bool:
    return bool(dates(text) or numbers(text) or case_numbers(text) or names(text) or outcome_words(text))


# ------------------------------------------------------------------------------------------------ the check


@dataclass
class Checked:
    """The checked answer: the text kept (with the removal note), the removed sentences `(index, reason)`, why the
    whole answer was withheld (None, `first_sentence`, `majority`, `none_cited`), the matched quotes by source label as
    offsets in that source's text, and the counts for `model_info.checks`."""

    text: str
    removed: list[tuple[int, str]] = field(default_factory=list)
    withheld: str | None = None
    quotes: dict[str, list[tuple[int, int]]] = field(default_factory=dict)
    sentences: int = 0
    cited: set[int] = field(default_factory=set)

    @property
    def counts(self) -> dict:
        by = Counter(r for _i, r in self.removed)
        return {
            "version": K.CHECKS_VERSION,
            "sentences": self.sentences,
            "kept": self.sentences - len(self.removed),
            "removed": {r: by.get(r, 0) for r in K.REASONS},
            "withheld": self.withheld,
        }


def _words(text: str) -> list[str]:
    return K.WORD.findall(text)


def _quote_ok(
    quote: str, cited: list[int], sources: dict[int, str], found: dict[str, list[tuple[int, int]]]
) -> bool:
    q, _ = normalise(quote)
    q = q.strip()
    for k in cited:
        norm, idx = normalise(sources[k])
        at = norm.find(q)
        if at >= 0:
            found.setdefault(f"S{k}", []).append((idx[at], idx[at + len(q) - 1] + 1))
            return True
    return False


def _reason(sentence: str, cited: list[int], sources: dict[int, str], rule_outcomes: dict[int, str | None],
            found: dict[str, list[tuple[int, int]]]) -> str | None:  # fmt: skip
    body = K.MARKER.sub(" ", sentence)
    joined = "\n".join(sources[k] for k in cited)
    for m in K.QUOTED.finditer(body):
        if len(_words(m.group(1))) >= K.QUOTE_MIN_WORDS and not _quote_ok(m.group(1), cited, sources, found):
            return "quote"
    src_dates = dates(joined)
    if any(d not in src_dates for d in dates(body)):
        return "date"
    src_nums = source_numbers(joined)
    if any(n not in src_nums for n in numbers(body)):
        return "number"
    src_compact = compact(joined)
    src_cnrs = {m.group(0).upper() for m in K.CNR_RE.finditer(joined)}
    for c in case_numbers(body):
        if not contains_compact(c, src_compact) and c not in src_cnrs:
            return "case_no"
    src_words = {w.lower() for w in re.findall(r"[A-Za-z0-9]+", joined)}
    for run in names(body):
        for w in run:
            parts = [p.lower() for p in re.findall(r"[A-Za-z0-9]+", w)]
            if any(p not in src_words for p in parts):
                return "name"
    low = joined.lower()
    rules = {rule_outcomes.get(k) for k in cited} - {None}
    for word in outcome_words(body):
        forms = K.OUTCOME_WORDS.get(word, (word,))
        if any(f in low for f in forms):
            continue
        if K.RULE_OUTCOME.get(word) in rules:
            continue
        return "outcome"
    return None


def check(
    answer: str,
    sources: dict[int, str],
    *,
    rule_outcomes: dict[int, str | None] | None = None,
) -> Checked:
    """Decisions 23 to 28. `sources` maps each source number to the exact text the model was given (header included);
    `rule_outcomes` maps a court order's source number to its rule-read outcome (row 250), when it has one."""
    rule_outcomes = rule_outcomes or {}
    sents = split_sentences(answer or "")
    out = Checked(text="", sentences=len(sents))
    kept: list[Sentence] = []
    for i, s in enumerate(sents):
        cited = [int(x) for x in K.MARKER.findall(s.text) if int(x) in sources]
        cited = list(dict.fromkeys(cited))
        body = K.MARKER.sub(" ", s.text)
        if not cited:
            quoted = any(len(_words(m.group(1))) >= K.QUOTE_MIN_WORDS for m in K.QUOTED.finditer(body))
            if quoted or _has_checkable(body) or len(_words(body)) > K.UNCITED_MAX_WORDS:
                out.removed.append((i, "uncited"))
                continue
            kept.append(s)
            continue
        found: dict[str, list[tuple[int, int]]] = {}
        reason = _reason(s.text, cited, sources, rule_outcomes, found)
        if reason is not None:
            out.removed.append((i, reason))
            continue
        for label, spans in found.items():
            out.quotes.setdefault(label, []).extend(spans)
        out.cited.update(cited)
        kept.append(s)
    removed_idx = {i for i, _r in out.removed}
    if sents and 0 in removed_idx:
        out.withheld = "first_sentence"
    elif len(out.removed) * 2 > len(sents):
        out.withheld = "majority"
    elif not out.cited:
        out.withheld = "none_cited"
    if out.withheld:
        out.quotes = {}
        return out
    parts: list[str] = []
    prev_end: int | None = None
    for s in kept:
        if prev_end is not None:
            parts.append("\n" if "\n" in answer[prev_end : s.start] else " ")
        parts.append(s.text)
        prev_end = s.end
    text = "".join(parts)
    if out.removed:
        n = len(out.removed)
        text += "\n" + K.REMOVED_NOTE.format(n=n, sentences="sentence" if n == 1 else "sentences")
    out.text = text
    return out


__all__ = ["Checked", "Sentence", "check", "compact", "dates", "normalise", "numbers", "split_sentences"]
