"""Department scoring engine — pure functions, no database (plan §4).

Signals, each with a weight in [0, 1]:
  counsel_code   standing-counsel code printed in the advocate column, mapped to an office  (strongest, 0.95)
  name_pattern   department name / designation pattern in the party names                   (default 0.80)
  watchlist      the department asked to follow this CNR                                     (default 0.75)
  link_history   a related case is already claimed by the department                         (0.70)
  keyword        department keyword in the party names                                       (default 0.40)
Signals are rolled up from directorates to their department, then combined per department by noisy-OR:
score = 1 − Π(1 − wᵢ). Generic State codes (e.g. `PP, ASSAM`) identify the State, not a department, and add
nothing. The result bands: ≥ strong → high, ≥ possible → medium, below → no recommendation (unclaimed pool)."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field

from aslms.core.text import normalise_name

ENGINE_VERSION = "2026.09.1"
LINK_HISTORY_WEIGHT = 0.70


@dataclass(frozen=True)
class OfficeRef:
    id: uuid.UUID
    code: str
    department_id: uuid.UUID  # the department this office rolls up to (itself for a department)


@dataclass(frozen=True)
class CodeRule:
    code: str
    office: OfficeRef
    weight: float
    is_generic_state: bool = False


@dataclass(frozen=True)
class PatternRule:
    pattern: str
    kind: str  # exact | prefix | regex
    office: OfficeRef
    weight: float


@dataclass(frozen=True)
class KeywordRule:
    keyword: str
    office: OfficeRef
    weight: float


@dataclass
class MatchConfig:
    codes: dict[str, CodeRule] = field(default_factory=dict)  # keyed by normalised code
    patterns: list[PatternRule] = field(default_factory=list)
    keywords: list[KeywordRule] = field(default_factory=list)
    watchlist: dict[str, list[tuple[OfficeRef, float]]] = field(default_factory=dict)  # CNR → offices


@dataclass(frozen=True)
class CaseFacts:
    cnr: str | None
    counsel_codes: tuple[str, ...]
    party_texts: tuple[str, ...]  # petitioner / respondent summaries and party names
    linked_owner_departments: tuple[uuid.UUID, ...] = ()


@dataclass(frozen=True)
class Signal:
    kind: str
    value: str
    weight: float
    office_code: str
    matched_text: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "value": self.value,
            "weight": round(self.weight, 3),
            "office": self.office_code,
            "matched_text": self.matched_text,
        }


@dataclass
class DepartmentScore:
    department_id: uuid.UUID
    score: float
    signals: list[Signal]
    suggested_unit_id: uuid.UUID | None = None  # strongest directorate-level signal, if any


def band_for(score: float, strong: float, possible: float) -> str | None:
    if score >= strong:
        return "high"
    if score >= possible:
        return "medium"
    return None


def _pattern_hit(rule: PatternRule, text: str) -> bool:
    p = normalise_name(rule.pattern)
    if not p:
        return False
    if rule.kind == "exact":
        return re.search(rf"(?<!\w){re.escape(p)}(?!\w)", text) is not None
    if rule.kind == "prefix":
        return any(chunk.startswith(p) for chunk in re.split(r"\bAND\b|,|;", text))
    try:
        return re.search(rule.pattern, text, re.I) is not None
    except re.error:
        return False


def score_case(facts: CaseFacts, cfg: MatchConfig) -> list[DepartmentScore]:
    """Returns one DepartmentScore per department with at least one signal, strongest first."""
    per_dept: dict[uuid.UUID, list[tuple[Signal, OfficeRef]]] = {}

    def add(sig: Signal, office: OfficeRef) -> None:
        per_dept.setdefault(office.department_id, []).append((sig, office))

    for raw in facts.counsel_codes:
        code = raw.strip().upper()
        rule = cfg.codes.get(code)
        if rule and not rule.is_generic_state:
            add(Signal("counsel_code", code, rule.weight, rule.office.code, raw), rule.office)

    texts = [normalise_name(t) for t in facts.party_texts if t]
    for rule in cfg.patterns:
        hit = next((t for t in texts if _pattern_hit(rule, t)), None)
        if hit:
            add(Signal("name_pattern", rule.pattern, rule.weight, rule.office.code, hit[:120]), rule.office)
    for rule in cfg.keywords:
        kw = normalise_name(rule.keyword)
        hit = next((t for t in texts if kw and re.search(rf"(?<!\w){re.escape(kw)}(?!\w)", t)), None)
        if hit:
            add(Signal("keyword", rule.keyword, rule.weight, rule.office.code, hit[:120]), rule.office)

    if facts.cnr:
        for office, weight in cfg.watchlist.get(facts.cnr.upper(), []):
            add(Signal("watchlist", facts.cnr, weight, office.code), office)

    for dept_id in dict.fromkeys(facts.linked_owner_departments):
        per_dept.setdefault(dept_id, []).append(
            (
                Signal("link_history", "related case claimed", LINK_HISTORY_WEIGHT, "linked"),
                OfficeRef(dept_id, "linked", dept_id),
            )
        )

    out: list[DepartmentScore] = []
    for dept_id, items in per_dept.items():
        # one signal per (kind, value): the same code printed twice counts once
        uniq: dict[tuple[str, str], tuple[Signal, OfficeRef]] = {}
        for sig, office in items:
            k = (sig.kind, sig.value)
            if k not in uniq or uniq[k][0].weight < sig.weight:
                uniq[k] = (sig, office)
        prod = 1.0
        for sig, _ in uniq.values():
            prod *= 1.0 - max(0.0, min(1.0, sig.weight))
        score = round(1.0 - prod, 3)
        units = [
            (sig.weight, office.id)
            for sig, office in uniq.values()
            if office.id != dept_id and office.code != "linked"
        ]
        unit = max(units)[1] if units else None
        out.append(DepartmentScore(dept_id, score, [s for s, _ in uniq.values()], unit))
    out.sort(key=lambda d: d.score, reverse=True)
    return out
