"""The matching engine (design `recommend-and-claim`, decisions 1-5): scores every case against every
Department-tier office from the rule tables and writes `case_office_scores` and engine recommendations. It never
writes `case_ownership`: a case belongs to a department only after the department claims it.

- Signals: counsel codes (cause-list entries and current dossier advocates), keywords and name patterns (party
  names), linked cases actively owned by the department, the department's watchlist.
- Partial counsel codes (design `partial-code-match`): a printed code that no active mapping names exactly, compared
  with each department's code as a set of comma-separated parts (respondent markers removed, dots significant). The
  department's code inside the printed one, the printed one inside the department's, or the same parts in another
  form gives a `counsel_code_partial` signal at the global partial weight (a possible match alone). The smaller part
  set must hold a part outside the generic stop-list; an exact match wins, and a department with an exact signal
  loses its partial ones.
- Score per department: the strongest weight within each signal kind, combined by noisy OR
  (`1 - prod(1 - w_kind)`), rounded to 3 decimals. Weights and band thresholds come from the current
  `scoring_settings` version; a rule's own `weight` overrides its kind's setting.
- Rules on a directorate or unit count for its Department-tier ancestor (the second segment of `offices.path`);
  the most specific office of the strongest hit is kept as `suggested_unit`.
- Engine writes carry the system actor (`matching`) and write no audit rows; their record is the events and the
  score rows. A department that dismissed or claimed a case is never re-recommended by the engine.
- A case that has ever had a primary owner gets no engine recommendation for any department, and the engine changes
  no band or score of its open rows (design `ownership-refinements`, decision 13); its scores are still written (the
  "why suggested" signals and the suggest dialog read them) and engine rows below the band still expire. A
  `claimed_elsewhere` row is never re-opened.

Matching runs in Python over the loaded rules; no SQL is built from rule text."""

from __future__ import annotations

import re
import uuid
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Literal

import structlog
from psycopg.errors import DeadlockDetected
from sqlalchemy import exists, func, or_, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from aslms.core.clock import today_ist
from aslms.domain.cases import Case, CaseAdvocate, CaseLink, CaseParty, FirstSeenSource
from aslms.domain.causelists import CURRENT_LIST, Causelist, CauselistEntry
from aslms.domain.ops import JobRun, JobStatus
from aslms.domain.org import Office
from aslms.domain.ownership import (
    CaseOfficeScore,
    CaseOwnership,
    CounselCode,
    OfficeKeyword,
    OfficeNamePattern,
    OfficeWatchlist,
    OwnershipRole,
    OwnershipStatus,
    PatternKind,
    Recommendation,
    RecommendationOrigin,
    RecommendationStatus,
    ScoreBand,
    ScoringSettings,
)
from aslms.domain.reference import EventType, OfficeKind
from aslms.services import scoring_settings as ss
from aslms.services import source_failures
from aslms.services.audit import Actor, snapshot
from aslms.services.cases import emit_event, normalise_name

log = structlog.get_logger(__name__)

ENGINE_VERSION = "2"  # design partial-code-match, decision 17
CNR_RE = re.compile(r"^[A-Z]{4}\d{12}$")
MATCHING_ACTOR = Actor.system("matching")
DEPARTMENT_TIER_KINDS = frozenset({OfficeKind.DEPARTMENT, OfficeKind.CENTRAL, OfficeKind.ADVOCATE_GENERAL})
NEVER_AGAIN = frozenset(
    {
        RecommendationStatus.DISMISSED,
        RecommendationStatus.SUGGESTED_ELSEWHERE,
        RecommendationStatus.CLAIMED,
        RecommendationStatus.CLAIMED_ELSEWHERE,  # design ownership-refinements, decision 9
    }
)
REGEX_MAX = 300

# design partial-code-match, decision 4: a parenthesised respondent-number group, or an unclosed one at the end
ANNOTATION_RE = re.compile(r"\(\s*R[\s.\-]*\d[^)]*\)?")
# decision 5: counsel designations and State names seen in the dev data (25 Oct 2026), plus the owner's examples;
# every active single-part generic State code extends the list at run time
GENERIC_PARTS: frozenset[str] = frozenset(
    {
        "SC",
        "SR. SC",
        "STANDING COUNSEL",
        "GA",
        "SR. GA",
        "SR.GA",
        "SR. GA ADV.",
        "PP",
        "ADDL. PP",
        "AG",
        "ADDL. AG",
        "ADDL AG",
        "SR. AG",
        "CGC",
        "SR. CGC",
        "DY.S.G.I.",
        "AMICUS CURIAE",
        "LEGAL AID COUNSEL",
        "ASSAM",
        "NAGALAND",
        "MIZORAM",
        "AP",
        "A P",
        "MANIPUR",
    }
)
Relation = Literal["contained", "contains", "same_parts"]


# ------------------------------------------------------------------------------------------------ pure helpers


def normalise_counsel_code(code: str | None) -> str:
    """Upper case, whitespace collapsed, no space before and one space after a comma, trailing commas
    stripped: `SC,EDU` and `sc , edu,` become `SC, EDU`."""
    s = " ".join((code or "").upper().split())
    s = re.sub(r"\s*,\s*", ", ", s)
    return s.rstrip(", ").strip()


def normalise_term(value: str | None) -> str:
    """Keywords, exact and prefix patterns and party names: upper case, dots as spaces, whitespace collapsed."""
    return normalise_name(value or "")


def validate_regex(pattern: str) -> re.Pattern[str]:
    """Compiles, at most 300 characters, must not match the empty string. Raises ValueError."""
    if not pattern or len(pattern) > REGEX_MAX:
        raise ValueError(f"a regex pattern is 1 to {REGEX_MAX} characters")
    try:
        rx = re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        raise ValueError(f"the regex does not compile: {exc}") from exc
    if rx.search("") is not None:
        raise ValueError("the regex matches the empty string")
    return rx


def combine(weights_by_kind: dict[str, float]) -> float:
    """Noisy OR over the kinds' strongest weights, rounded to 3 decimals, never above 1."""
    remaining = 1.0
    for w in weights_by_kind.values():
        remaining *= 1.0 - min(max(float(w), 0.0), 1.0)
    return round(min(max(1.0 - remaining, 0.0), 1.0), 3)


def band_of(score: float, settings: ss.Settings) -> ScoreBand | None:
    s = round(float(score), 3)
    if s >= round(settings.threshold_strong, 3):
        return ScoreBand.HIGH
    if s >= round(settings.threshold_possible, 3):
        return ScoreBand.MEDIUM
    return None


def engine_version(settings: ss.Settings) -> str:
    return f"{ENGINE_VERSION}.{settings.version}"


def code_parts(code: str | None) -> frozenset[str]:
    """The comparison form of a counsel code (design partial-code-match, decisions 1 and 4): normalised, respondent
    markers removed, split on commas into a set of stripped, non-empty parts."""
    s = ANNOTATION_RE.sub(" ", normalise_counsel_code(code))
    s = s.strip().rstrip(", ").strip()
    return frozenset(p for p in (t.strip() for t in s.split(",")) if p)


def partial_relation(
    dept_parts: frozenset[str], printed_parts: frozenset[str], generic: frozenset[str] | set[str]
) -> Relation | None:
    """Decision 2. Called only when the two normalised strings differ. The smaller set must hold a part that is not
    generic."""
    if not dept_parts or not printed_parts:
        return None

    def specific(parts: frozenset[str]) -> bool:
        return any(p not in generic for p in parts)

    if dept_parts == printed_parts:
        return "same_parts" if specific(dept_parts) else None
    if dept_parts < printed_parts:
        return "contained" if specific(dept_parts) else None
    if printed_parts < dept_parts:
        return "contains" if specific(printed_parts) else None
    return None


def _list_date_text(value: Any) -> str | None:
    if isinstance(value, date):
        d = value
    else:
        try:
            d = date.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None
    return f"{d.day} {d:%b %Y}"


def partial_reason(dept_code: str, printed: str, relation: str, where: str, ref: Any) -> str:
    """The sentence shown in Case Claim's "Why this is suggested" (decision 13)."""
    ref = ref if isinstance(ref, dict) else {}
    if where == "case_advocates":
        side = ref.get("side")
        place = f"in the case's advocate list ({side} side)" if side else "in the case's advocate list"
    else:
        day = _list_date_text(ref.get("list_date"))
        place = f"on the cause list of {day}" if day else "on a cause list"
    if relation == "contained":
        return f"Code {dept_code} found inside {printed} {place}"
    if relation == "contains":
        return f"Code {printed} {place} is part of {dept_code}"
    return f"Code {printed} {place} has the same parts as {dept_code}"


def _word_regex(term: str) -> re.Pattern[str]:
    return re.compile(r"(?<![A-Z0-9])" + re.escape(term) + r"(?![A-Z0-9])")


# ------------------------------------------------------------------------------------------------ rules


@dataclass(frozen=True)
class Rule:
    id: uuid.UUID | None
    kind: str  # counsel_code / keyword / name_pattern / watchlist
    text: str  # the normalised code, keyword, pattern or CNR
    office_id: uuid.UUID
    office_code: str
    office_depth: int
    department_id: uuid.UUID
    department_code: str
    weight: float  # effective: the rule's override, else the kind's setting
    pattern_kind: str | None = None
    regex: re.Pattern[str] | None = field(default=None, compare=False, hash=False)
    parts: frozenset[str] = frozenset()  # counsel_code rules: the comparison form (design partial-code-match)

    def __post_init__(self) -> None:
        if self.kind == "counsel_code" and not self.parts:
            object.__setattr__(self, "parts", code_parts(self.text))


@dataclass
class RuleSet:
    settings: ss.Settings
    codes: dict[str, Rule] = field(default_factory=dict)
    generic_codes: set[str] = field(default_factory=set)
    keywords: list[Rule] = field(default_factory=list)
    patterns: list[Rule] = field(default_factory=list)
    watch: dict[str, list[Rule]] = field(default_factory=dict)
    departments: dict[uuid.UUID, str] = field(default_factory=dict)  # active Department-tier offices
    # design partial-code-match, decisions 5 and 9: filled on first use from `codes` and `generic_codes`
    generic_parts: frozenset[str] = frozenset()
    partial_index: dict[str, list[Rule]] = field(default_factory=dict)
    _partial_cache: dict[str, list[tuple[Rule, str]]] = field(default_factory=dict, repr=False)
    _prepared: bool = field(default=False, repr=False)

    def _prepare(self) -> None:
        extra: set[str] = set()
        for code in self.generic_codes:
            parts = code_parts(code)
            if len(parts) == 1:
                extra |= parts
        self.generic_parts = GENERIC_PARTS | extra
        index: dict[str, list[Rule]] = defaultdict(list)
        for rule in self.codes.values():
            for part in rule.parts:
                if part not in self.generic_parts:
                    index[part].append(rule)
        self.partial_index = dict(index)
        self._partial_cache = {}
        self._prepared = True

    def partial_matches(self, printed: str) -> list[tuple[Rule, str]]:
        """Every department code rule that partly matches the normalised printed code, with its relation, ordered
        by department code then rule text. Nothing when the printed code is mapped exactly or is a generic code
        (decisions 6 and 7), or when all its parts are generic."""
        if not self._prepared:
            self._prepare()
        if printed in self.codes or printed in self.generic_codes:
            return []
        cached = self._partial_cache.get(printed)
        if cached is not None:
            return cached
        pp = code_parts(printed)
        out: list[tuple[Rule, str]] = []
        if pp and any(p not in self.generic_parts for p in pp):
            candidates: dict[str, Rule] = {}
            for part in pp:
                for rule in self.partial_index.get(part, ()):
                    candidates.setdefault(rule.text, rule)
            for rule in candidates.values():
                if rule.text == printed:
                    continue
                rel = partial_relation(rule.parts, pp, self.generic_parts)
                if rel is not None:
                    out.append((rule, rel))
            out.sort(key=lambda m: (m[0].department_code, m[0].text))
        self._partial_cache[printed] = out
        return out

    @classmethod
    def load(cls, session: Session) -> RuleSet:
        settings = ss.current(session)
        offices = {o.id: o for o in session.scalars(select(Office)).all()}
        by_code = {o.code: o for o in offices.values()}
        departments = {
            o.id: o.code
            for o in offices.values()
            if o.is_active and o.path.count("/") == 1 and OfficeKind(o.kind) in DEPARTMENT_TIER_KINDS
        }

        def resolve(office_id: uuid.UUID) -> tuple[Office, Office] | None:
            office = offices.get(office_id)
            if office is None or not office.is_active:
                return None
            parts = office.path.split("/")
            if len(parts) < 2:
                return None
            dept = by_code.get(parts[1])
            if dept is None or dept.id not in departments:
                return None
            return office, dept

        rs = cls(settings=settings, departments=departments)
        w = settings.weights

        def make(row, kind: str, txt: str, **extra) -> Rule | None:
            r = resolve(row.office_id)
            if r is None:
                return None
            office, dept = r
            weight = float(row.weight) if row.weight is not None else w[kind]
            return Rule(
                id=row.id,
                kind=kind,
                text=txt,
                office_id=office.id,
                office_code=office.code,
                office_depth=office.path.count("/"),
                department_id=dept.id,
                department_code=dept.code,
                weight=round(weight, 3),
                **extra,
            )

        for row in session.scalars(select(CounselCode).where(CounselCode.is_active.is_(True))).all():
            code = normalise_counsel_code(row.code)
            if row.is_generic_state:
                rs.generic_codes.add(code)
                continue
            rule = make(row, "counsel_code", code)
            if rule is not None:
                rs.codes[code] = rule
        for row in session.scalars(select(OfficeKeyword).where(OfficeKeyword.is_active.is_(True))).all():
            kw = normalise_term(row.keyword)
            if kw:
                rule = make(row, "keyword", kw, regex=_word_regex(kw))
                if rule is not None:
                    rs.keywords.append(rule)
        for row in session.scalars(
            select(OfficeNamePattern).where(OfficeNamePattern.is_active.is_(True))
        ).all():
            kind = PatternKind(row.kind)
            if kind == PatternKind.REGEX:
                try:
                    rx = validate_regex(row.pattern)
                except ValueError:
                    log.warning("matching.bad_regex", rule_id=str(row.id))
                    continue
                rule = make(row, "name_pattern", row.pattern, pattern_kind=kind.value, regex=rx)
            else:
                rule = make(row, "name_pattern", normalise_term(row.pattern), pattern_kind=kind.value)
            if rule is not None and rule.text:
                rs.patterns.append(rule)
        for row in session.scalars(select(OfficeWatchlist).where(OfficeWatchlist.is_active.is_(True))).all():
            rule = make(row, "watchlist", row.cnr.upper())
            if rule is not None:
                rs.watch.setdefault(rule.text, []).append(rule)
        rs._prepare()
        return rs


# ------------------------------------------------------------------------------------------------ evidence


@dataclass
class LinkedCase:
    case_id: uuid.UUID
    ref_no: str
    case_no_text: str | None
    owner_office_ids: set[uuid.UUID]


@dataclass
class CaseEvidence:
    cnr: str | None = None
    entry_codes: list[tuple[str, dict]] = field(default_factory=list)  # (normalised code, {list_date, sr_no})
    advocate_codes: list[tuple[str, dict]] = field(default_factory=list)  # (normalised code, {side})
    names: list[tuple[str, str, dict]] = field(default_factory=list)  # (normalised name, where, ref)
    linked: list[LinkedCase] = field(default_factory=list)

    @classmethod
    def gather(cls, session: Session, case: Case) -> CaseEvidence:
        ev = cls(cnr=case.cnr.upper() if case.cnr else None)
        rows = session.execute(
            select(
                CauselistEntry.counsel_codes,
                CauselistEntry.petitioner_text,
                CauselistEntry.respondent_text,
                CauselistEntry.sr_no,
                Causelist.list_date,
            )
            .join(Causelist, Causelist.id == CauselistEntry.causelist_id)
            .where(CauselistEntry.case_id == case.id, CURRENT_LIST)
            .order_by(Causelist.list_date.desc(), CauselistEntry.sr_no)
        ).all()
        for codes, pet, res, sr_no, list_date in rows:
            ref = {"list_date": list_date.isoformat() if list_date else None, "sr_no": sr_no}
            for c in codes or []:
                n = normalise_counsel_code(c)
                if n:
                    ev.entry_codes.append((n, ref))
            for t in (pet, res):
                if t and t.strip():
                    ev.names.append((normalise_term(t), "causelist_entry", ref))
        for side, code in session.execute(
            select(CaseAdvocate.side, CaseAdvocate.counsel_code).where(
                CaseAdvocate.case_id == case.id,
                CaseAdvocate.is_current.is_(True),
                CaseAdvocate.counsel_code.is_not(None),
            )
        ).all():
            n = normalise_counsel_code(code)
            if n:
                ev.advocate_codes.append((n, {"side": getattr(side, "value", side)}))
        for role, party_no, name in session.execute(
            select(CaseParty.role, CaseParty.party_no, CaseParty.name)
            .where(CaseParty.case_id == case.id, CaseParty.is_current.is_(True))
            .order_by(CaseParty.role, CaseParty.party_no)
        ).all():
            ev.names.append(
                (
                    normalise_term(name),
                    "case_parties",
                    {"role": getattr(role, "value", role), "party_no": party_no},
                )
            )
        for fld in ("petitioner_summary", "respondent_summary"):
            t = getattr(case, fld)
            if t and t.strip():
                ev.names.append((normalise_term(t), "case_summary", {"field": fld}))
        ev.linked = _linked_cases(session, case)
        return ev


def linked_case_ids(session: Session, case: Case) -> set[uuid.UUID]:
    """Cases linked to `case` in either direction (`case_links.from_case_id`, `to_case_id` or `to_cnr`)."""
    out: set[uuid.UUID] = set()
    for to_id, to_cnr in session.execute(
        select(CaseLink.to_case_id, CaseLink.to_cnr).where(CaseLink.from_case_id == case.id)
    ).all():
        if to_id is not None:
            out.add(to_id)
        elif to_cnr:
            found = session.scalar(select(Case.id).where(Case.cnr == to_cnr.upper()))
            if found is not None:
                out.add(found)
    conds = [CaseLink.to_case_id == case.id]
    if case.cnr:
        conds.append(CaseLink.to_cnr == case.cnr)
    out.update(session.scalars(select(CaseLink.from_case_id).where(or_(*conds))).all())
    out.discard(case.id)
    return out


def _linked_cases(session: Session, case: Case) -> list[LinkedCase]:
    ids = linked_case_ids(session, case)
    if not ids:
        return []
    owners: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for cid, oid in session.execute(
        select(CaseOwnership.case_id, CaseOwnership.office_id).where(
            CaseOwnership.case_id.in_(ids), CaseOwnership.status == OwnershipStatus.ACTIVE
        )
    ).all():
        owners[cid].add(oid)
    out = []
    for cid, ref_no, case_no in session.execute(
        select(Case.id, Case.ref_no, Case.case_no_text).where(Case.id.in_(ids)).order_by(Case.ref_no)
    ).all():
        if owners.get(cid):
            out.append(LinkedCase(cid, ref_no, case_no, owners[cid]))
    return out


# ------------------------------------------------------------------------------------------------ scoring


@dataclass
class ScoredOffice:
    office_id: uuid.UUID
    office_code: str
    score: float
    signals: list[dict[str, Any]]


@dataclass
class _Hit:
    department_id: uuid.UUID
    department_code: str
    kind: str
    weight: float
    office_code: str
    office_depth: int
    signal: dict[str, Any]


def _signal(rule: Rule, matched: str, where: str, ref: Any) -> dict[str, Any]:
    return {
        "kind": rule.kind,
        "rule_id": str(rule.id) if rule.id else None,
        "rule_office_code": rule.office_code,
        "weight": rule.weight,
        "matched": matched,
        "where": where,
        "ref": ref,
    }


def _name_matches(rule: Rule, name: str) -> bool:
    if rule.kind == "keyword":
        return bool(rule.regex and rule.regex.search(name))
    if rule.pattern_kind == PatternKind.EXACT.value:
        return name == rule.text
    if rule.pattern_kind == PatternKind.PREFIX.value:
        return name.startswith(rule.text)
    return bool(rule.regex and rule.regex.search(name))


def score_case(rules: RuleSet, evidence: CaseEvidence) -> dict[uuid.UUID, ScoredOffice]:
    """Pure: the score and the signals of every department with at least one hit. One signal is kept per
    (kind, rule, where) — the first in evidence order (the most recent listing first)."""
    hits: list[_Hit] = []
    seen: set[tuple] = set()

    def add(rule: Rule, matched: str, where: str, ref: Any) -> None:
        key = (rule.kind, rule.id, rule.text, rule.department_id, where)
        if key in seen:
            return
        seen.add(key)
        hits.append(
            _Hit(
                rule.department_id,
                rule.department_code,
                rule.kind,
                rule.weight,
                rule.office_code,
                rule.office_depth,
                _signal(rule, matched, where, ref),
            )
        )

    w_partial = round(
        rules.settings.weights.get("counsel_code_partial", ss.DEFAULTS.weights["counsel_code_partial"]), 3
    )

    def add_partial(rule: Rule, printed: str, relation: str, where: str, ref: Any) -> None:
        """Design partial-code-match, decisions 9, 10 and 13: the global partial weight, never the rule's
        override."""
        key = ("counsel_code_partial", rule.id, rule.text, rule.department_id, where)
        if key in seen:
            return
        seen.add(key)
        hits.append(
            _Hit(
                rule.department_id,
                rule.department_code,
                "counsel_code_partial",
                w_partial,
                rule.office_code,
                rule.office_depth,
                {
                    "kind": "counsel_code_partial",
                    "rule_id": str(rule.id) if rule.id else None,
                    "rule_office_code": rule.office_code,
                    "weight": w_partial,
                    "matched": rule.text,
                    "printed": printed,
                    "relation": relation,
                    "where": where,
                    "ref": ref,
                    "reason": partial_reason(rule.text, printed, relation, where, ref),
                },
            )
        )

    for codes, where in (
        (evidence.entry_codes, "causelist_entry"),
        (evidence.advocate_codes, "case_advocates"),
    ):
        for code, ref in codes:
            if code in rules.generic_codes:
                continue
            rule = rules.codes.get(code)
            if rule is not None:
                add(rule, code, where, ref)
                continue
            for prule, relation in rules.partial_matches(code):
                add_partial(prule, code, relation, where, ref)
    for name, where, ref in evidence.names:
        if not name:
            continue
        for rule in rules.keywords:
            if _name_matches(rule, name):
                add(rule, rule.text, where, ref)
        for rule in rules.patterns:
            if _name_matches(rule, name):
                add(rule, rule.text, where, ref)
    w_linked = round(rules.settings.weights["linked_case"], 3)
    for lc in evidence.linked:
        for office_id in sorted(lc.owner_office_ids, key=str):
            code = rules.departments.get(office_id)
            if code is None:
                continue
            key = ("linked_case", lc.case_id, office_id)
            if key in seen:
                continue
            seen.add(key)
            hits.append(
                _Hit(
                    office_id,
                    code,
                    "linked_case",
                    w_linked,
                    code,
                    1,
                    {
                        "kind": "linked_case",
                        "rule_id": None,
                        "rule_office_code": code,
                        "weight": w_linked,
                        "matched": lc.case_no_text or lc.ref_no,
                        "where": "case_links",
                        "ref": lc.ref_no,
                    },
                )
            )
    if evidence.cnr:
        for rule in rules.watch.get(evidence.cnr, []):
            add(rule, evidence.cnr, "watchlist", None)

    by_dept: dict[uuid.UUID, list[_Hit]] = defaultdict(list)
    for h in hits:
        by_dept[h.department_id].append(h)
    out: dict[uuid.UUID, ScoredOffice] = {}
    for dept_id, dept_hits in by_dept.items():
        if any(h.kind == "counsel_code" for h in dept_hits):
            # decision 8: one code signal family per department, the exact one
            dept_hits = [h for h in dept_hits if h.kind != "counsel_code_partial"]
        best: dict[str, float] = {}
        for h in dept_hits:
            best[h.kind] = max(best.get(h.kind, 0.0), h.weight)
        score = combine(best)
        if score <= 0:
            continue
        signals = [h.signal for h in dept_hits]
        strongest = max(dept_hits, key=lambda h: (h.weight, h.office_depth))
        if strongest.office_depth > 1:
            signals.append({"kind": "suggested_unit", "office_code": strongest.office_code})
        out[dept_id] = ScoredOffice(dept_id, dept_hits[0].department_code, score, signals)
    return out


# ------------------------------------------------------------------------------------------------ writing


@dataclass
class ScoreReport:
    cases: int = 0
    scores: int = 0
    recommended_new: int = 0
    band_changed: int = 0
    expired: int = 0
    failed: int = 0
    settings_version: int | None = None
    job_run_id: uuid.UUID | None = None

    def add(self, other: ScoreReport) -> None:
        for k in ("cases", "scores", "recommended_new", "band_changed", "expired", "failed"):
            setattr(self, k, getattr(self, k) + getattr(other, k))
        self.settings_version = other.settings_version or self.settings_version

    def as_dict(self) -> dict[str, Any]:
        return {
            "cases": self.cases,
            "scores": self.scores,
            "recommended_new": self.recommended_new,
            "band_changed": self.band_changed,
            "expired": self.expired,
            "failed": self.failed,
            "settings_version": self.settings_version,
        }


def _now() -> datetime:
    return datetime.now(UTC)


def _dec(x: float) -> Decimal:
    return Decimal(str(round(float(x), 3)))


def _rec_event(session: Session, case: Case, rec: Recommendation, office_code: str) -> None:
    emit_event(
        session,
        EventType.RECOMMENDATION_MADE,
        case,
        {
            "recommendation_id": str(rec.id),
            "office_code": office_code,
            "score": float(rec.score),
            "band": ScoreBand(rec.band).value,
            "origin": RecommendationOrigin(rec.origin).value,
        },
        dedupe=f"recommendation_made:{rec.id}:{ScoreBand(rec.band).value}:{_now().isoformat()}",
        scoped=True,
        actor_user_id=rec.actor_user_id,
    )


def _expire(rec: Recommendation, report: ScoreReport) -> None:
    rec.status = RecommendationStatus.EXPIRED
    rec.acted_at = _now()
    report.expired += 1


def apply_scores(
    session: Session,
    case: Case,
    scores: dict[uuid.UUID, ScoredOffice],
    *,
    origin: RecommendationOrigin,
    settings: ss.Settings,
    report: ScoreReport | None = None,
) -> ScoreReport:
    """Writes `case_office_scores` and the engine side of the recommendation lifecycle (decision 5). Takes the case
    row lock first, the lock `ownership._lock` takes, so a claim and an engine pass on one case are serialised: the
    engine either sees the claim or finishes first and the claim's closing step closes what it opened (design
    followups-oct, decision 16)."""
    report = report or ScoreReport()
    report.settings_version = settings.version
    session.execute(select(Case.id).where(Case.id == case.id).with_for_update())
    recs = list(session.scalars(select(Recommendation).where(Recommendation.case_id == case.id)).all())
    if case.merged_into_case_id is not None:
        for rec in recs:
            if (
                rec.status == RecommendationStatus.RECOMMENDED
                and rec.origin != RecommendationOrigin.SUGGESTION
            ):
                _expire(rec, report)
        session.flush()
        return report

    version = engine_version(settings)
    existing = {
        s.office_id: s
        for s in session.scalars(select(CaseOfficeScore).where(CaseOfficeScore.case_id == case.id)).all()
    }
    for office_id, so in scores.items():
        row = existing.pop(office_id, None)
        if row is None:
            session.add(
                CaseOfficeScore(
                    case_id=case.id,
                    office_id=office_id,
                    score=_dec(so.score),
                    signals=so.signals,
                    engine_version=version,
                )
            )
        elif float(row.score) != so.score or row.signals != so.signals or row.engine_version != version:
            row.score, row.signals, row.engine_version = _dec(so.score), so.signals, version
            row.computed_at = _now()
        report.scores += 1
    for row in existing.values():
        session.delete(row)

    # Decision 5: a department that holds the case now, or has *ever* held it (a claim from the pool writes
    # no recommendation row, so a `claimed` status alone would miss it), is never re-opened by the engine.
    ever_owners = set(
        session.scalars(select(CaseOwnership.office_id).where(CaseOwnership.case_id == case.id)).all()
    )
    blocked = {r.office_id for r in recs if r.status in NEVER_AGAIN} | ever_owners
    active = {r.office_id: r for r in recs if r.status == RecommendationStatus.RECOMMENDED}
    actor_cols = snapshot(MATCHING_ACTOR)
    # design ownership-refinements, decision 13: a case that has ever had a primary owner gets no new engine
    # recommendation and no band or score change on its open rows (the same `exists` as `ownership.ever_owned`,
    # which imports this module)
    claimed = bool(
        session.scalar(
            select(
                exists().where(CaseOwnership.case_id == case.id, CaseOwnership.role == OwnershipRole.PRIMARY)
            )
        )
    )

    for office_id, so in scores.items():
        if claimed:
            break
        band = band_of(so.score, settings)
        if band is None:
            continue
        rec = active.get(office_id)
        if rec is not None:
            if rec.origin == RecommendationOrigin.SUGGESTION:
                continue  # a human suggestion keeps its band and score
            if float(rec.score) != so.score:
                rec.score = _dec(so.score)
            if ScoreBand(rec.band) != band:
                rec.band = band
                report.band_changed += 1
                session.flush()
                _rec_event(session, case, rec, so.office_code)
            continue
        if office_id in blocked:
            continue
        rec = Recommendation(
            case_id=case.id,
            office_id=office_id,
            score=_dec(so.score),
            band=band,
            status=RecommendationStatus.RECOMMENDED,
            origin=origin,
            **actor_cols,
        )
        session.add(rec)
        session.flush()
        report.recommended_new += 1
        _rec_event(session, case, rec, so.office_code)

    for office_id, rec in active.items():
        if rec.origin == RecommendationOrigin.SUGGESTION:
            continue
        so = scores.get(office_id)
        if so is None or band_of(so.score, settings) is None:
            _expire(rec, report)
    session.flush()
    return report


def origin_for_dossier(case: Case) -> RecommendationOrigin:
    src = FirstSeenSource(case.first_seen_source)
    if src == FirstSeenSource.CAUSELIST:
        return RecommendationOrigin.CAUSE_LIST
    if src == FirstSeenSource.SEARCH:
        return RecommendationOrigin.SEARCH
    if src == FirstSeenSource.DISCOVERY:  # design department-discovery, decision 9
        return RecommendationOrigin.DISCOVERY
    return RecommendationOrigin.RESCORE


def record_failure(session: Session, kind: str, ref: str, error: str) -> None:
    """The shared `source_failures` upsert (design safety-fixes, decision 10)."""
    source_failures.record(session, kind, ref, error)


def score_cases(
    session: Session,
    case_ids,
    *,
    origin: RecommendationOrigin,
    rules: RuleSet | None = None,
) -> ScoreReport:
    """Scores each case inside its own savepoint; a failure is recorded in `source_failures` (kind
    `scoring`, ref the case `ref_no`) and never propagates."""
    report = ScoreReport()
    # in case-id order, so two engine passes take the case locks in one order (design followups-oct, decision 16)
    ids = sorted(dict.fromkeys(i for i in case_ids if i is not None))
    if not ids:
        return report
    if rules is None:
        rules = RuleSet.load(session)
    report.settings_version = rules.settings.version
    for cid in ids:
        case = session.get(Case, cid)
        if case is None:
            continue
        ref = case.ref_no
        try:
            try:
                _score_one(session, case, rules, origin, report)
            except OperationalError as exc:
                if not isinstance(exc.orig, DeadlockDetected):
                    raise
                # Postgres's deadlock detector chose this case: its savepoint is rolled back; retried once
                log.warning("matching.case_deadlock_retried", case_ref=ref)
                _score_one(session, case, rules, origin, report)
            report.cases += 1
        except Exception as exc:  # noqa: BLE001 — scoring never fails the pipeline item
            report.failed += 1
            log.warning("matching.case_failed", case_ref=ref, error=exc.__class__.__name__)
            try:
                with session.begin_nested():
                    record_failure(session, "scoring", ref, f"{exc.__class__.__name__}: {exc}")
            except Exception:  # noqa: BLE001
                log.exception("matching.failure_not_recorded", case_ref=ref)
    return report


def _score_one(
    session: Session, case: Case, rules: RuleSet, origin: RecommendationOrigin, report: ScoreReport
):
    with session.begin_nested():
        evidence = CaseEvidence.gather(session, case)
        apply_scores(
            session,
            case,
            score_case(rules, evidence),
            origin=origin,
            settings=rules.settings,
            report=report,
        )


# ------------------------------------------------------------------------------------------------ batch rescore

RULE_TABLES = (CounselCode, OfficeKeyword, OfficeNamePattern, OfficeWatchlist, Office, ScoringSettings)


def rules_changed_since(session: Session, ts: datetime | None) -> bool:
    """True when a rule, an office or the scoring settings were created or updated after `ts` (or when no
    rescore has ever succeeded)."""
    if ts is None:
        return True
    for model in RULE_TABLES:
        latest = session.scalar(select(func.greatest(func.max(model.created_at), func.max(model.updated_at))))
        if latest is not None and latest > ts:
            return True
    return False


def last_rescore_start(session: Session) -> datetime | None:
    return session.scalar(
        select(func.max(JobRun.started_at)).where(
            JobRun.job == "rescore", JobRun.status == JobStatus.SUCCEEDED
        )
    )


def rescore_all(session_factory: sessionmaker[Session], *, batch: int = 500) -> ScoreReport:
    """Rescores every non-merged case in batches (one commit per batch) and expires the active engine
    recommendations of merged cases. One `job_runs` row `rescore` with the counters."""
    with session_factory() as s:
        run = JobRun(job="rescore", run_date=today_ist())
        s.add(run)
        s.commit()
        run_id = run.id
    total = ScoreReport(job_run_id=run_id)
    status, error = JobStatus.FAILED, None
    try:
        with session_factory() as s:
            rules = RuleSet.load(s)
        total.settings_version = rules.settings.version
        last_id: uuid.UUID | None = None
        while True:
            with session_factory() as s:
                stmt = (
                    select(Case.id).where(Case.merged_into_case_id.is_(None)).order_by(Case.id).limit(batch)
                )
                if last_id is not None:
                    stmt = stmt.where(Case.id > last_id)
                ids = list(s.scalars(stmt).all())
                if not ids:
                    break
                total.add(score_cases(s, ids, origin=RecommendationOrigin.RESCORE, rules=rules))
                s.commit()
                last_id = ids[-1]
        with session_factory() as s:
            merged = s.scalars(
                select(Case)
                .join(Recommendation, Recommendation.case_id == Case.id)
                .where(
                    Case.merged_into_case_id.is_not(None),
                    Recommendation.status == RecommendationStatus.RECOMMENDED,
                )
                .distinct()
                .order_by(Case.id)
            ).all()
            for case in merged:
                apply_scores(
                    s, case, {}, origin=RecommendationOrigin.RESCORE, settings=rules.settings, report=total
                )
            s.commit()
        status = JobStatus.PARTIAL if total.failed else JobStatus.SUCCEEDED
    except Exception as exc:
        error = f"{exc.__class__.__name__}: {exc}"[:2000]
        raise
    finally:
        with session_factory() as s:
            run = s.get(JobRun, run_id)
            run.status = status
            run.finished_at = _now()
            run.counters = total.as_dict()
            run.error = error
            s.commit()
    return total


def rescore_if_dirty(session_factory: sessionmaker[Session], *, batch: int = 500) -> ScoreReport | None:
    with session_factory() as s:
        dirty = rules_changed_since(s, last_rescore_start(s))
    if not dirty:
        return None
    return rescore_all(session_factory, batch=batch)


def rescore_case(
    session: Session, case: Case, *, origin: RecommendationOrigin = RecommendationOrigin.RESCORE
):
    return score_cases(session, [case.id], origin=origin)


# ------------------------------------------------------------------------------------------------ unmapped codes


@dataclass
class UnmappedCode:
    code: str
    entries: int
    last_listed: date | None
    example_case_ref: str | None
    partial_matches: list[dict[str, str]] = field(default_factory=list)


PARTIAL_MATCHES_SHOWN = 5


def unmapped_codes(
    session: Session, *, limit: int = 200, scope: Callable[[uuid.UUID], bool] | None = None
) -> list[UnmappedCode]:
    """Codes seen in cause-list entries and current dossier advocates with no active mapping (generic codes
    are mappings too), normalised, most frequent first. `entries` counts cause-list entries plus dossier
    advocate rows. Each code carries up to 5 mapped codes it partly matches (design partial-code-match, decision
    16), only those whose office passes `scope` (None: every mapping, for the super admin)."""
    mapped = {
        normalise_counsel_code(c)
        for c in session.scalars(select(CounselCode.code).where(CounselCode.is_active.is_(True))).all()
    }
    agg: dict[str, dict[str, Any]] = {}
    rows = session.execute(
        text(
            """
            SELECT code, count(*) AS n, max(cl.list_date) AS last_listed, min(e.case_id::text) AS example
            FROM causelist_entries e
            JOIN causelists cl ON cl.id = e.causelist_id
            CROSS JOIN LATERAL unnest(e.counsel_codes) AS code
            WHERE cl.superseded_at IS NULL
            GROUP BY code
            """
        )
    ).all()
    for code, n, last_listed, example in rows:
        k = normalise_counsel_code(code)
        if not k or k in mapped:
            continue
        a = agg.setdefault(k, {"n": 0, "last": None, "example": None})
        a["n"] += int(n)
        if last_listed and (a["last"] is None or last_listed > a["last"]):
            a["last"] = last_listed
        a["example"] = a["example"] or example
    for code, n, example in session.execute(
        text(
            """
            SELECT counsel_code, count(*), min(case_id::text) FROM case_advocates
            WHERE is_current AND counsel_code IS NOT NULL GROUP BY counsel_code
            """
        )
    ).all():
        k = normalise_counsel_code(code)
        if not k or k in mapped:
            continue
        a = agg.setdefault(k, {"n": 0, "last": None, "example": None})
        a["n"] += int(n)
        a["example"] = a["example"] or example
    ordered = sorted(agg.items(), key=lambda kv: (-kv[1]["n"], kv[0]))[:limit]
    example_ids = [uuid.UUID(v["example"]) for _, v in ordered if v["example"]]
    refs = (
        dict(session.execute(select(Case.id, Case.ref_no).where(Case.id.in_(example_ids))).all())
        if example_ids
        else {}
    )
    rules = RuleSet.load(session) if ordered else None

    def partly(code: str) -> list[dict[str, str]]:
        found = []
        for rule, relation in rules.partial_matches(code):
            if scope is not None and not scope(rule.office_id):
                continue
            found.append({"code": rule.text, "office_code": rule.office_code, "relation": relation})
            if len(found) == PARTIAL_MATCHES_SHOWN:
                break
        return found

    return [
        UnmappedCode(
            code=k,
            entries=v["n"],
            last_listed=v["last"],
            example_case_ref=refs.get(uuid.UUID(v["example"])) if v["example"] else None,
            partial_matches=partly(k),
        )
        for k, v in ordered
    ]
