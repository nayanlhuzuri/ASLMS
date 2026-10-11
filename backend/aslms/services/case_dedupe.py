"""One row per case (design `data-load-console`, decisions 13-16).

- **The case number key** (`number_key`): same court, and either the same compact printed number (upper case, no
  white space; the expression `ix_cases_case_no_compact` serves) or the same case type (`case_type_id`), `reg_no`
  and `reg_year`. `find_provisional` finds a provisional row (no CNR, not merged) by it; creation and adoption take
  `lock_number`, a transaction-scoped advisory lock on (court, compact number), so the worker and the API cannot
  create two provisional rows for one printed number at once. A CNR stays unique by its index.
  A number or year of zero or less (NAPIX's `WA/0/0` for a filed but unregistered case), given or printed, and a
  filing number or year of zero or less, make the key unusable: such rows never match, merge or link.
- **Adopt** (`adopt`): a provisional row takes the CNR the court gave for its number.
- **Merge** (`merge_provisional`): a provisional row whose number resolves to a CNR another row holds is merged
  into that row, in one transaction, only when it holds no portal record (claims, custody, stages, notes, drafts,
  documents, manual next dates, transfers, assistant conversations). Its cause-list entries are re-pointed (only
  `case_id` changes), its links move where the holder has no identical one, its active recommendations expire, its
  derived scores go, `office_watchlist.case_id` is filled for the holder, `merged_into_case_id` is set, both search
  vectors are refreshed and the holder rescored; `case_merged` (scoped) and `case.merged` are written. A provisional
  row with portal records is not merged: a `source_failures` row (`case_duplicate`, `<P id>|<C id>`) lists the pair
  for review.
- **Court duplicates** (`link_court_duplicates`): two rows with different CNRs and the same number key, or the same
  filing key (filing type text or id, `filing_no`, `filing_year`), are the court's own duplicate records. Both CNRs
  are kept; the newer row gets one `court_duplicate` link (`source = dedupe`) to the older, `case_linked` on both
  and one `case.court_duplicate_linked` audit row. Never merged.
- `check_cases` runs the rules inline for the cases a dossier apply or a search store touched; `sweep` runs them
  over every case in batches (the 03:00 job, `aslms data-load dedupe`, the console's "Scan now")."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import and_, exists, func, literal, or_, select, text, update
from sqlalchemy.orm import Session

from aslms.domain.alerts import NextDate, NextDateSource
from aslms.domain.assistant import AssistantConversation
from aslms.domain.cases import Case, CaseLink, LinkKind, LinkSource
from aslms.domain.documents import Document
from aslms.domain.ownership import (
    CaseOfficeScore,
    CaseOwnership,
    OfficeWatchlist,
    OwnershipTransfer,
    Recommendation,
    RecommendationOrigin,
    RecommendationStatus,
)
from aslms.domain.reference import EventType
from aslms.domain.workflow import CaseNote, CaseNoteDraft, CaseStage, Custody, CustodyHistory
from aslms.services.audit import Actor, write_audit
from aslms.services.napix_values import as_int, case_no_text

FAILURE_KIND = "case_duplicate"
SYSTEM = Actor.system("dedupe")


# ------------------------------------------------------------------------------------------------ the key


def compact(text_: str | None) -> str | None:
    """`WP (C)/4326/2025` → `WP(C)/4326/2025`: the expression of `ix_cases_case_no_compact`."""
    if not text_:
        return None
    out = re.sub(r"\s", "", text_.upper())
    return out or None


@dataclass(frozen=True)
class NumberKey:
    court_id: uuid.UUID | None
    compact: str | None
    case_type_id: uuid.UUID | None
    reg_no: int | None
    reg_year: int | None

    @property
    def by_type(self) -> bool:
        return self.case_type_id is not None and _positive(self.reg_no) and _positive(self.reg_year)

    @property
    def usable(self) -> bool:
        return bool(self.compact) or self.by_type

    def matches(self, other: NumberKey) -> bool:
        if self.court_id != other.court_id or not (self.usable and other.usable):
            return False
        if self.compact and self.compact == other.compact:
            return True
        return (
            self.by_type
            and other.by_type
            and (self.case_type_id, self.reg_no, self.reg_year)
            == (other.case_type_id, other.reg_no, other.reg_year)
        )


def number_key(
    *,
    court_id: uuid.UUID | None = None,
    case_no_text: str | None = None,
    case_type_text: str | None = None,
    case_type_id: uuid.UUID | None = None,
    reg_no: Any = None,
    reg_year: Any = None,
) -> NumberKey:
    """The key from a printed number and / or the type, number and year (any of them may be missing).

    NAPIX gives a filed but unregistered case `reg_no` 0 and `reg_year` 0 (printed `WA/0/0`): a number or year of
    zero or less, given or printed, makes the key unusable, so such cases never match one another."""
    printed = case_no_text or _case_no_text(case_type_text, reg_no, reg_year)
    no, year = as_int(reg_no), as_int(reg_year)
    printed_no = printed_year = None
    if printed:
        parts = printed.rsplit("/", 2)
        if len(parts) == 3:
            printed_no, printed_year = as_int(parts[1]), as_int(parts[2])
    if any(v is not None and v <= 0 for v in (no, year, printed_no, printed_year)):
        return NumberKey(court_id, None, case_type_id, None, None)
    no = no if no is not None else printed_no
    year = year if year is not None else printed_year
    return NumberKey(court_id, compact(printed), case_type_id, no, year)


def _positive(value: int | None) -> bool:
    return value is not None and value > 0


def _case_no_text(type_text: Any, no: Any, year: Any) -> str | None:
    return case_no_text(type_text, no, year)


def case_key(case: Case) -> NumberKey:
    return number_key(
        court_id=case.court_id,
        case_no_text=case.case_no_text,
        case_type_text=case.case_type_text,
        case_type_id=case.case_type_id,
        reg_no=case.reg_no,
        reg_year=case.reg_year,
    )


COMPACT_EXPR = func.upper(func.regexp_replace(Case.case_no_text, r"\s", "", "g"))


def key_condition(key: NumberKey):
    conds = []
    if key.compact:
        conds.append(COMPACT_EXPR == key.compact)
    if key.by_type:
        conds.append(
            and_(
                Case.case_type_id == key.case_type_id,
                Case.reg_no == key.reg_no,
                Case.reg_year == key.reg_year,
            )
        )
    if not conds:
        return literal(False)
    return and_(Case.court_id == key.court_id, or_(*conds))


def lock_number(session: Session, court_id: uuid.UUID, key: NumberKey) -> None:
    """A transaction-scoped advisory lock on (court, compact number); a key without a printed number locks on the
    type, number and year."""
    token = key.compact or (f"{key.case_type_id}:{key.reg_no}:{key.reg_year}" if key.by_type else None)
    if token is None:
        return
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"case-no:{court_id}:{token}"}
    )


def find_provisional(session: Session, court_id: uuid.UUID, key: NumberKey) -> Case | None:
    """The oldest provisional row (no CNR, not merged) of the court with this key."""
    key = NumberKey(court_id, key.compact, key.case_type_id, key.reg_no, key.reg_year)
    if not key.usable:
        return None
    return session.scalar(
        select(Case)
        .where(key_condition(key), Case.cnr.is_(None), Case.merged_into_case_id.is_(None))
        .order_by(Case.created_at, Case.id)
        .limit(1)
    )


def find_holders(session: Session, key: NumberKey, *, exclude: uuid.UUID | None = None) -> list[Case]:
    """Rows holding a CNR with this key (not merged), oldest first."""
    if not key.usable:
        return []
    stmt = select(Case).where(key_condition(key), Case.cnr.isnot(None), Case.merged_into_case_id.is_(None))
    if exclude is not None:
        stmt = stmt.where(Case.id != exclude)
    return list(session.scalars(stmt.order_by(Case.created_at, Case.id)).all())


def adopt(session: Session, provisional: Case, cnr: str) -> Case:
    """The provisional row takes the court's CNR; it stays provisional until its dossier applies."""
    provisional.cnr = cnr.strip().upper()
    provisional.is_provisional = True
    session.flush()
    return provisional


# ------------------------------------------------------------------------------------------------ merge


@dataclass
class MergeResult:
    provisional_id: uuid.UUID
    holder_id: uuid.UUID
    holder_ref_no: str
    entries: int = 0
    links_moved: int = 0
    recommendations_expired: int = 0


@dataclass
class NeedsReview:
    provisional_id: uuid.UUID
    holder_id: uuid.UUID
    holder_ref_no: str
    records: list[str] = field(default_factory=list)

    @property
    def reason(self) -> str:
        return "portal records on the provisional case: " + ", ".join(self.records)


def portal_records(session: Session, case: Case) -> list[str]:
    """The kinds of portal record the case holds (decision 14); empty when it may be merged."""
    checks = (
        ("case_ownership", select(CaseOwnership.id).where(CaseOwnership.case_id == case.id)),
        ("custody", select(Custody.case_id).where(Custody.case_id == case.id)),
        ("custody_history", select(CustodyHistory.id).where(CustodyHistory.case_id == case.id)),
        ("case_stages", select(CaseStage.id).where(CaseStage.case_id == case.id)),
        ("case_notes", select(CaseNote.id).where(CaseNote.case_id == case.id)),
        ("case_note_drafts", select(CaseNoteDraft.id).where(CaseNoteDraft.case_id == case.id)),
        ("documents", select(Document.id).where(Document.case_id == case.id)),
        (
            "next_dates",
            select(NextDate.id).where(NextDate.case_id == case.id, NextDate.source == NextDateSource.MANUAL),
        ),
        ("ownership_transfers", select(OwnershipTransfer.id).where(OwnershipTransfer.case_id == case.id)),
        (
            "assistant_conversations",
            select(AssistantConversation.id).where(AssistantConversation.case_id == case.id),
        ),
    )
    return [name for name, stmt in checks if session.scalar(select(exists(stmt)))]


def record_review(session: Session, p: Case, c: Case, reason: str) -> None:
    from aslms.services.matching import record_failure

    record_failure(session, FAILURE_KIND, f"{p.id}|{c.id}", reason)


class MergeStale(ValueError):
    """The provisional row gained a CNR or was merged by another transaction while the merge waited for its lock."""


def merge_provisional(
    session: Session, p: Case, c: Case, actor: Actor | None = None
) -> MergeResult | NeedsReview:
    """Decision 14. `p` is provisional (no CNR, not merged); `c` holds the CNR. Writes everything in the caller's
    transaction.

    P's row is locked `FOR UPDATE` and re-read before its portal records are checked. The lock waits for a claim
    (`ownership` locks the case row) and for any uncommitted insert that references P (the foreign key's key-share
    lock conflicts with `FOR UPDATE`), and blocks both until this transaction ends; so a claim, note, document or
    custody row written at the same time is either seen by the check or waits and then finds P merged."""
    from aslms.services import matching
    from aslms.services.cases import emit_event, refresh_search_vector

    if p.id == c.id or p.cnr is not None or p.merged_into_case_id is not None:
        raise ValueError("only an unmerged provisional row without a CNR is merged")
    if c.merged_into_case_id is not None:
        raise ValueError("the holder is itself merged")
    actor = actor or SYSTEM
    session.flush()
    session.execute(select(Case.id).where(Case.id == p.id).with_for_update())
    session.refresh(p)
    if p.cnr is not None or p.merged_into_case_id is not None:
        raise MergeStale(f"case {p.ref_no} changed while it was being merged")
    records = portal_records(session, p)
    if records:
        review = NeedsReview(p.id, c.id, c.ref_no, records)
        record_review(session, p, c, review.reason)
        return review
    result = MergeResult(p.id, c.id, c.ref_no)
    result.entries = int(
        session.execute(
            text("UPDATE causelist_entries SET case_id = :c WHERE case_id = :p"), {"c": c.id, "p": p.id}
        ).rowcount
        or 0
    )
    result.links_moved = int(
        session.execute(
            text(
                """
                UPDATE case_links l SET from_case_id = :c, updated_at = now()
                WHERE l.from_case_id = :p AND NOT EXISTS (
                    SELECT 1 FROM case_links x
                    WHERE x.from_case_id = :c AND x.to_case_no_text = l.to_case_no_text AND x.kind = l.kind)
                """
            ),
            {"c": c.id, "p": p.id},
        ).rowcount
        or 0
    )
    session.execute(
        update(CaseLink).where(CaseLink.to_case_id == p.id).values(to_case_id=c.id),
        execution_options={"synchronize_session": False},
    )
    result.recommendations_expired = int(
        session.execute(
            update(Recommendation)
            .where(Recommendation.case_id == p.id, Recommendation.status == RecommendationStatus.RECOMMENDED)
            .values(status=RecommendationStatus.EXPIRED, acted_at=func.now(), reason="case merged"),
            execution_options={"synchronize_session": False},
        ).rowcount
        or 0
    )
    session.execute(CaseOfficeScore.__table__.delete().where(CaseOfficeScore.case_id == p.id))
    if c.cnr:
        session.execute(
            update(OfficeWatchlist)
            .where(
                or_(
                    and_(OfficeWatchlist.cnr == c.cnr, OfficeWatchlist.case_id.is_(None)),
                    OfficeWatchlist.case_id == p.id,
                )
            )
            .values(case_id=c.id),
            execution_options={"synchronize_session": False},
        )
    p.merged_into_case_id = c.id
    session.flush()
    session.expire_all()
    p = session.get(Case, result.provisional_id)
    c = session.get(Case, result.holder_id)
    refresh_search_vector(session, [p.id, c.id])
    matching.score_cases(session, [c.id], origin=RecommendationOrigin.RESCORE)
    payload = {
        "merged_ref_no": p.ref_no,
        "merged_case_no": p.case_no_text,
        "into_ref_no": c.ref_no,
        "cnr": c.cnr,
        "entries": result.entries,
        "links_moved": result.links_moved,
        "recommendations_expired": result.recommendations_expired,
    }
    emit_event(session, EventType.CASE_MERGED, c, payload, dedupe=f"case_merged:{p.id}", scoped=True)
    write_audit(
        session,
        actor,
        "case.merged",
        "case",
        c.id,
        before={"case_id": str(p.id), "ref_no": p.ref_no, "case_no": p.case_no_text, "cnr": None},
        after=payload,
        case_id=c.id,
    )
    _resolve_review(session, p, c)
    session.flush()
    return result


def _resolve_review(session: Session, p: Case, c: Case) -> None:
    session.execute(
        text(
            "UPDATE source_failures SET resolved_at = now() WHERE kind = :k AND ref = :r AND resolved_at IS NULL"
        ),
        {"k": FAILURE_KIND, "r": f"{p.id}|{c.id}"},
    )


# ------------------------------------------------------------------------------------------------ court duplicates


def filing_condition(case: Case):
    if not (_positive(case.filing_no) and _positive(case.filing_year)):
        return None
    types = []
    if case.filing_case_type_id is not None:
        types.append(Case.filing_case_type_id == case.filing_case_type_id)
    ftext = compact(case.filing_case_type_text)
    if ftext:
        types.append(func.upper(func.regexp_replace(Case.filing_case_type_text, r"\s", "", "g")) == ftext)
    if not types:
        return None
    return and_(
        Case.court_id == case.court_id,
        Case.filing_no == case.filing_no,
        Case.filing_year == case.filing_year,
        or_(*types),
    )


def court_duplicates(session: Session, case: Case) -> list[Case]:
    """Other rows with a different CNR sharing the case's number key or filing key (not merged)."""
    if not case.cnr or case.merged_into_case_id is not None:
        return []
    conds = []
    key = case_key(case)
    if key.usable:
        conds.append(key_condition(key))
    fc = filing_condition(case)
    if fc is not None:
        conds.append(fc)
    if not conds:
        return []
    return list(
        session.scalars(
            select(Case)
            .where(
                or_(*conds),
                Case.id != case.id,
                Case.cnr.isnot(None),
                Case.cnr != case.cnr,
                Case.merged_into_case_id.is_(None),
            )
            .order_by(Case.created_at, Case.id)
        ).all()
    )


def _older_newer(a: Case, b: Case) -> tuple[Case, Case]:
    return (a, b) if (a.created_at, str(a.id)) <= (b.created_at, str(b.id)) else (b, a)


def link_court_duplicates(
    session: Session, case: Case, actor: Actor | None = None, pairs: list | None = None
) -> int:
    """Decision 15: one `court_duplicate` link from the newer row to the older for each duplicate pair of this
    case; idempotent. Returns the links written."""
    from aslms.services.cases import emit_event

    actor = actor or SYSTEM
    n = 0
    rescore: set[uuid.UUID] = set()
    for other in court_duplicates(session, case):
        older, newer = _older_newer(case, other)
        linked = session.scalar(
            select(
                exists().where(
                    CaseLink.kind == LinkKind.COURT_DUPLICATE,
                    or_(
                        and_(CaseLink.from_case_id == newer.id, CaseLink.to_case_id == older.id),
                        and_(CaseLink.from_case_id == older.id, CaseLink.to_case_id == newer.id),
                    ),
                )
            )
        )
        if linked:
            continue
        to_text = older.case_no_text or older.cnr or ""
        taken = session.scalar(
            select(
                exists().where(
                    CaseLink.from_case_id == newer.id,
                    CaseLink.to_case_no_text == to_text,
                    CaseLink.kind == LinkKind.COURT_DUPLICATE,
                )
            )
        )
        if taken:
            to_text = f"{to_text} ({older.cnr})"[:200]
        link = CaseLink(
            from_case_id=newer.id,
            to_case_id=older.id,
            to_cnr=older.cnr,
            to_case_no_text=to_text,
            filing_number_text=older.filing_no_text,
            kind=LinkKind.COURT_DUPLICATE,
            source=LinkSource.DEDUPE,
        )
        session.add(link)
        session.flush()
        payload = {
            "kind": LinkKind.COURT_DUPLICATE.value,
            "from_ref_no": newer.ref_no,
            "from_cnr": newer.cnr,
            "to_ref_no": older.ref_no,
            "to_cnr": older.cnr,
            "case_no": newer.case_no_text,
        }
        for c in (newer, older):
            emit_event(session, EventType.CASE_LINKED, c, payload, dedupe=f"court_duplicate:{link.id}:{c.id}")
        write_audit(
            session,
            actor,
            "case.court_duplicate_linked",
            "case_link",
            link.id,
            after=payload,
            case_id=newer.id,
        )
        if pairs is not None:
            pairs.append(_pair("court", newer, older))
        rescore.update({newer.id, older.id})
        n += 1
    if rescore:
        # the link is a linked-case signal: a department that claimed one is recommended the other (never assigned)
        from aslms.services import matching

        matching.score_cases(session, sorted(rescore), origin=RecommendationOrigin.RESCORE)
    return n


# ------------------------------------------------------------------------------------------------ checks


@dataclass
class DedupeReport:
    merged: int = 0
    needs_review: int = 0
    court_linked: int = 0
    pairs: list[dict[str, Any]] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        return {"merged": self.merged, "needs_review": self.needs_review, "court_linked": self.court_linked}

    def add(self, other: DedupeReport) -> None:
        self.merged += other.merged
        self.needs_review += other.needs_review
        self.court_linked += other.court_linked
        self.pairs.extend(other.pairs)


def _pair(kind: str, a: Case, b: Case) -> dict[str, Any]:
    return {
        "kind": kind,
        "case": {"ref_no": a.ref_no, "cnr": a.cnr, "case_no_text": a.case_no_text},
        "other": {"ref_no": b.ref_no, "cnr": b.cnr, "case_no_text": b.case_no_text},
    }


def _reviewed(session: Session, p: Case, c: Case) -> bool:
    return bool(
        session.scalar(
            text("SELECT 1 FROM source_failures WHERE kind = :k AND ref = :r AND resolved_at IS NULL"),
            {"k": FAILURE_KIND, "r": f"{p.id}|{c.id}"},
        )
    )


def _merge_or_review(
    session: Session, p: Case, c: Case, report: DedupeReport, *, dry_run: bool, actor: Actor | None
) -> None:
    if dry_run:
        records = portal_records(session, p)
        if records:
            report.needs_review += 1
            report.pairs.append(_pair("review", p, c))
        else:
            report.merged += 1
            report.pairs.append(_pair("merge", p, c))
        return
    if _reviewed(session, p, c) and portal_records(session, p):
        return  # already listed for review
    try:
        out = merge_provisional(session, p, c, actor)
    except MergeStale:
        return  # another transaction adopted or merged the row first
    if isinstance(out, NeedsReview):
        report.needs_review += 1
        report.pairs.append(_pair("review", p, c))
    else:
        report.merged += 1
        report.pairs.append(_pair("merge", p, c))


def check_case(
    session: Session, case: Case, *, dry_run: bool = False, actor: Actor | None = None
) -> DedupeReport:
    """The rules for one row: a provisional row sharing its key with a CNR row is merged into the oldest such row;
    a CNR row absorbs the provisional rows sharing its key; a CNR row is linked to its court duplicates."""
    report = DedupeReport()
    if case.merged_into_case_id is not None:
        return report
    key = case_key(case)
    if case.cnr is None:
        holders = find_holders(session, key)
        if holders:
            _merge_or_review(session, case, holders[0], report, dry_run=dry_run, actor=actor)
        return report
    if key.usable:
        for p in list(
            session.scalars(
                select(Case)
                .where(key_condition(key), Case.cnr.is_(None), Case.merged_into_case_id.is_(None))
                .order_by(Case.created_at, Case.id)
            ).all()
        ):
            holders = find_holders(session, case_key(p))
            target = holders[0] if holders else case
            _merge_or_review(session, p, target, report, dry_run=dry_run, actor=actor)
    if dry_run:
        for other in court_duplicates(session, case):
            older, newer = _older_newer(case, other)
            exists_ = session.scalar(
                select(
                    exists().where(
                        CaseLink.kind == LinkKind.COURT_DUPLICATE,
                        CaseLink.from_case_id == newer.id,
                        CaseLink.to_case_id == older.id,
                    )
                )
            )
            if not exists_:
                report.court_linked += 1
                report.pairs.append(_pair("court", newer, older))
    else:
        report.court_linked += link_court_duplicates(session, case, actor, report.pairs)
    return report


def check_cases(
    session: Session, case_ids, *, dry_run: bool = False, actor: Actor | None = None
) -> DedupeReport:
    """Inline after a dossier apply or a search store, for the touched cases (indexed lookups)."""
    report = DedupeReport()
    for cid in dict.fromkeys(i for i in case_ids if i is not None):
        case = session.get(Case, cid)
        if case is None:
            continue
        report.add(check_case(session, case, dry_run=dry_run, actor=actor))
    session.flush()
    return report


def _candidate_ids(session: Session) -> list[uuid.UUID]:
    """Rows that may take part in a duplicate: provisional rows sharing a key with another row, and CNR rows
    sharing a number or filing key with another CNR row."""
    rows = session.execute(
        text(
            r"""
            WITH live AS (
                SELECT id, court_id, cnr, case_type_id, reg_no, reg_year, filing_no, filing_year,
                       filing_case_type_id,
                       upper(regexp_replace(case_no_text, '\s', '', 'g')) AS cno,
                       upper(regexp_replace(filing_case_type_text, '\s', '', 'g')) AS ftype
                FROM cases WHERE merged_into_case_id IS NULL
            ),
            by_no AS (
                SELECT court_id, cno FROM live WHERE cno IS NOT NULL AND cno !~ '/0*/' AND cno !~ '/0+$'
                GROUP BY court_id, cno HAVING count(*) > 1
            ),
            by_type AS (
                SELECT court_id, case_type_id, reg_no, reg_year FROM live
                WHERE case_type_id IS NOT NULL AND reg_no > 0 AND reg_year > 0
                GROUP BY 1, 2, 3, 4 HAVING count(*) > 1
            ),
            by_fil_id AS (
                SELECT court_id, filing_case_type_id, filing_no, filing_year FROM live
                WHERE cnr IS NOT NULL AND filing_case_type_id IS NOT NULL AND filing_no > 0
                  AND filing_year > 0
                GROUP BY 1, 2, 3, 4 HAVING count(DISTINCT cnr) > 1
            ),
            by_fil_text AS (
                SELECT court_id, ftype, filing_no, filing_year FROM live
                WHERE cnr IS NOT NULL AND ftype IS NOT NULL AND filing_no > 0 AND filing_year > 0
                GROUP BY 1, 2, 3, 4 HAVING count(DISTINCT cnr) > 1
            )
            SELECT DISTINCT l.id FROM live l
            WHERE EXISTS (SELECT 1 FROM by_no b WHERE b.court_id = l.court_id AND b.cno = l.cno)
               OR EXISTS (SELECT 1 FROM by_type b WHERE b.court_id = l.court_id AND b.case_type_id = l.case_type_id
                          AND b.reg_no = l.reg_no AND b.reg_year = l.reg_year)
               OR (l.cnr IS NOT NULL AND EXISTS (
                      SELECT 1 FROM by_fil_id b WHERE b.court_id = l.court_id
                      AND b.filing_case_type_id = l.filing_case_type_id
                      AND b.filing_no = l.filing_no AND b.filing_year = l.filing_year))
               OR (l.cnr IS NOT NULL AND EXISTS (
                      SELECT 1 FROM by_fil_text b WHERE b.court_id = l.court_id AND b.ftype = l.ftype
                      AND b.filing_no = l.filing_no AND b.filing_year = l.filing_year))
            """
        )
    ).all()
    return [r[0] for r in rows]


def sweep(
    session: Session, *, dry_run: bool = False, batch: int = 1000, actor: Actor | None = None
) -> DedupeReport:
    """Decision 16: the rules over every case that shares a key with another, in batches: CNR rows first (each
    absorbs the provisional rows of its number and is linked to its court duplicates), then the remaining
    provisional rows (two provisional rows of one number: the younger into the older). A dry run writes nothing and
    reports what a real run would do, each pair once."""
    ids = _candidate_ids(session)
    report = DedupeReport()
    if not ids:
        return report
    meta = {
        cid: (cnr is None, created, str(cid))
        for cid, cnr, created in session.execute(
            select(Case.id, Case.cnr, Case.created_at).where(Case.id.in_(ids))
        ).all()
    }
    ids = sorted(meta, key=lambda i: meta[i])
    seen: set[frozenset] = set()
    claimed: set[str] = set()  # provisional rows already counted in a dry run
    size = max(1, batch)
    for start in range(0, len(ids), size):
        for cid in ids[start : start + size]:
            case = session.get(Case, cid)
            if case is None or case.merged_into_case_id is not None:
                continue
            if case.cnr is None:
                rep = _provisional_pair(session, case, dry_run=dry_run, actor=actor)
            else:
                rep = check_case(session, case, dry_run=dry_run, actor=actor)
            for pair in rep.pairs:
                key = frozenset((pair["kind"], pair["case"]["ref_no"], pair["other"]["ref_no"]))
                if key in seen or (pair["kind"] != "court" and pair["case"]["ref_no"] in claimed):
                    continue
                seen.add(key)
                if pair["kind"] != "court":
                    claimed.add(pair["case"]["ref_no"])
                report.pairs.append(pair)
        session.flush()
    report.merged = sum(1 for p in report.pairs if p["kind"] == "merge")
    report.needs_review = sum(1 for p in report.pairs if p["kind"] == "review")
    report.court_linked = sum(1 for p in report.pairs if p["kind"] == "court")
    return report


def _provisional_pair(session: Session, case: Case, *, dry_run: bool, actor: Actor | None) -> DedupeReport:
    """A provisional row: into the oldest CNR row with its key, else (two provisional rows of one number) the
    younger into the older."""
    report = check_case(session, case, dry_run=dry_run, actor=actor)
    if report.merged or report.needs_review:
        return report
    key = case_key(case)
    if not key.usable:
        return report
    older = session.scalar(
        select(Case)
        .where(
            key_condition(key),
            Case.cnr.is_(None),
            Case.merged_into_case_id.is_(None),
            Case.id != case.id,
            or_(
                Case.created_at < case.created_at, and_(Case.created_at == case.created_at, Case.id < case.id)
            ),
        )
        .order_by(Case.created_at, Case.id)
        .limit(1)
    )
    if older is None:
        return report
    if dry_run:
        records = portal_records(session, case)
        if records:
            report.needs_review += 1
            report.pairs.append(_pair("review", case, older))
        else:
            report.merged += 1
            report.pairs.append(_pair("merge", case, older))
        return report
    _merge_or_review(session, case, older, report, dry_run=False, actor=actor)
    return report
