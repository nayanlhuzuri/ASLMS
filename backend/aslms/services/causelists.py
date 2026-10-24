"""Pipeline stage 2: one cause-list day. NAPIX first (Cause List Bench → one `causelist_bench_days` row per
bench → Cause List Details → one `causelists` row per list → Show Cause List PDF stored in `documents` → parsed
→ `causelist_entries` → `cases` and `fetch_queue` dossier rows); the website PDFs on disk (`CAUSELIST_DIR/
<dd-mm-yyyy>/<Type>_<date>.pdf`) when the gateway has no list for the date. Re-running a day creates nothing
new: lists, documents (sha256) and entries have unique keys.

A corrected list re-issued under the same list number (design `court-data-freshness`, decisions 7-15): the evening
recheck (`recheck_day`, queue kind `causelist_recheck`) calls Show Cause List again for each held NAPIX list of the
date. Same bytes: unchanged. Different bytes whose parsed entries differ from the current version's fingerprint: a new
version (`version + 1`, `supersedes_id`; the old row only gains `superseded_at`, its entries never change), then the
cases, recommendations, next dates and timeline react (`_listing_changes`). Every reader reads the current version
(`CURRENT_LIST`). A day run and a recheck of the same date never run at once (`day_lock`)."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from aslms.core.errors import NapixNotFound
from aslms.domain.cases import Case, FirstSeenSource
from aslms.domain.causelists import (
    CURRENT_LIST,
    Causelist,
    CauselistBenchDay,
    CauselistEntry,
    EntrySource,
    FetchStatus,
    ListSource,
    ListType,
    ParseStatus,
    ResolutionStatus,
)
from aslms.domain.courts import Bench, Court
from aslms.domain.documents import (
    DocGroup,
    DocKind,
    Document,
    ScanStatus,
    SourcetraceStatus,
    TextStatus,
    Visibility,
)
from aslms.domain.ops import FetchKind, FetchLane
from aslms.domain.ownership import RecommendationOrigin
from aslms.domain.reference import DocType, EventType
from aslms.integration.base import CauseListRef
from aslms.integration.napix.hc import NapixHighCourt
from aslms.parsing.causelist_pdf import Entry, ParsedCauseList, parse_causelist_pdf
from aslms.services import matching, queue, source_failures
from aslms.services.cases import emit_event, get_or_create_case, refresh_search_vector
from aslms.services.load_policy import QueueOrigin
from aslms.services.storage import LocalStore

# `CURRENT_LIST` / `CURRENT_LIST_SQL` (domain): every reader of `causelists` / `causelist_entries` adds it, except the
# named exceptions (an explicit earlier version, the case's listings, the file download, load and backup counts, the
# dedupe merge); `tests/unit/test_court_data_freshness_unit.py` enforces it (design court-data-freshness, decision 12)
REISSUE_FAILURE = "causelist_reissue"
# the stored-form fields of an entry that make its fingerprint (decision 10); `raw_lines` are left out
FINGERPRINT_FIELDS = (
    "printed_sr_no",
    "court_no",
    "bench_text",
    "section",
    "cnr",
    "case_no_text",
    "is_connected",
    "petitioner_text",
    "respondent_text",
    "pet_advocate_text",
    "res_advocate_text",
    "counsel_codes",
    "with_text",
    "remarks",
)

LIST_TYPE_WORDS = (
    ("SUPPLEMENTARY", ListType.SUPPLEMENTARY),
    ("LAWAZIMA", ListType.LAWAZIMA),
    ("VACATION", ListType.VACATION),
    ("DAILY", ListType.DAILY),
)
WEBSITE_FILE_RE = re.compile(r"^(Daily|Supplementary|Lawazima)_(\d{2}-\d{2}-\d{4})(.*)\.pdf$", re.I)


def list_type_of(text: str | None, parsed: ParsedCauseList | None = None) -> ListType:
    t = (text or "").upper()
    for word, lt in LIST_TYPE_WORDS:
        if word in t:
            return lt
    if parsed and parsed.list_type:
        try:
            return ListType(parsed.list_type)
        except ValueError:
            pass
    return ListType.OTHER


@dataclass
class DayReport:
    list_date: date
    source: str = "none"
    benches: int = 0
    lists: int = 0
    lists_fetched: int = 0
    documents_new: int = 0
    entries: int = 0
    entries_new: int = 0
    cases_new: int = 0
    queued: int = 0
    skipped_reason: str | None = None
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        d = self.__dict__.copy()
        d["list_date"] = self.list_date.isoformat()
        d["warnings"] = self.warnings[:50]
        return d


def _now() -> datetime:
    return datetime.now(UTC)


def day_lock(session: Session, list_date: date) -> None:
    """One writer per cause-list date (decision 15): the day run and the recheck of a date take this transaction-level
    advisory lock, so two workers never create two versions or race a parse. Safe under PgBouncer transaction pooling."""
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"causelist-day:{list_date.isoformat()}"}
    )


def _fp_value(row: Any, name: str) -> Any:
    v = row.get(name) if isinstance(row, dict) else getattr(row, name, None)
    if name == "counsel_codes":
        return list(v or [])
    if name == "is_connected":
        return bool(v)
    return v


def entries_fingerprint(rows) -> str:
    """The sha256 of the ordered entries in their stored form (`CauselistEntry` rows, or dicts with the same keys), over
    `FINGERPRINT_FIELDS` (decision 10). Key order inside a dict and `raw_lines` do not count."""
    payload = [{name: _fp_value(r, name) for name in FINGERPRINT_FIELDS} for r in rows]
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def parsed_fingerprint(parsed: ParsedCauseList) -> str:
    """The fingerprint of a parse, after the truncation `_entry_row` applies."""
    return entries_fingerprint([entry_values(e) for e in parsed.entries])


def stored_entries(session: Session, causelist_id: uuid.UUID) -> list[CauselistEntry]:
    return list(
        session.scalars(
            select(CauselistEntry)
            .where(CauselistEntry.causelist_id == causelist_id)
            .order_by(CauselistEntry.sr_no, CauselistEntry.source)
        ).all()
    )


def stored_fingerprint(session: Session, cl: Causelist) -> str:
    """The list's fingerprint, computed once from its stored entries for rows parsed before migration 0023."""
    if cl.entries_sha256 is None:
        cl.entries_sha256 = entries_fingerprint(stored_entries(session, cl.id))
    return cl.entries_sha256


def store_pdf(
    session: Session, store: LocalStore, data: bytes, *, doc_date: date, description: str
) -> tuple[Document, bool]:
    stored = store.put(data, "application/pdf")
    doc = session.scalar(
        select(Document).where(Document.sha256 == stored.sha256, Document.kind == DocKind.CAUSELIST)
    )
    if doc is not None:
        return doc, False
    doc = Document(
        sha256=stored.sha256,
        storage_key=stored.key,
        mime="application/pdf",
        size_bytes=stored.size,
        kind=DocKind.CAUSELIST,
        doc_type=DocType.CAUSELIST,
        doc_group=DocGroup.COURT_RECORD,
        doc_date=doc_date,
        description=description,
        visibility=Visibility.CASE_SCOPE,
        virus_scan_status=ScanStatus.SKIPPED,
        text_status=TextStatus.NONE,
        sourcetrace_status=SourcetraceStatus.NOT_APPLICABLE,
    )
    session.add(doc)
    session.flush()
    return doc, True


def _get_or_create_list(
    session: Session,
    court: Court,
    list_date: date,
    *,
    bench_id: int | None,
    napix_causelist_id: int | None,
    source: ListSource,
    list_type: ListType,
) -> Causelist:
    stmt = select(Causelist).where(
        CURRENT_LIST,
        Causelist.court_id == court.id,
        Causelist.list_date == list_date,
        Causelist.source == source,
        Causelist.list_type == list_type,
        (Causelist.bench_id == bench_id) if bench_id is not None else Causelist.bench_id.is_(None),
        (Causelist.napix_causelist_id == napix_causelist_id)
        if napix_causelist_id is not None
        else Causelist.napix_causelist_id.is_(None),
    )
    cl = session.scalar(stmt)
    if cl is None:
        cl = Causelist(
            court_id=court.id,
            list_date=list_date,
            bench_id=bench_id,
            napix_causelist_id=napix_causelist_id,
            source=source,
            list_type=list_type,
        )
        session.add(cl)
        session.flush()
    return cl


def apply_entries(
    session: Session,
    court: Court,
    causelist: Causelist,
    parsed: ParsedCauseList,
    *,
    origin: QueueOrigin | None = None,
    report: DayReport,
) -> None:
    """Parsed rows → `causelist_entries` (immutable, keyed by position) → cases → dossier queue rows, then the
    matching engine scores every case the new rows touched (inline, one savepoint per case; a scoring error is
    recorded in `source_failures` and never fails the list). The dossier rows take the lane and priority of the
    origin (design `data-load-console`, decision 1); the default is the daily cycle with this list's date."""
    origin = origin or QueueOrigin(FetchLane.DAILY, causelist.list_date)
    if origin.list_date is None:
        origin = replace(origin, list_date=causelist.list_date)
    existing = {
        (e.source, e.sr_no)
        for e in session.scalars(
            select(CauselistEntry).where(CauselistEntry.causelist_id == causelist.id)
        ).all()
    }
    source = EntrySource.PDF_PARSE
    touched: list[uuid.UUID] = []
    for entry in parsed.entries:
        report.entries += 1
        if (source, entry.seq) in existing:
            continue
        case = None
        if entry.cnr or entry.case_no_text:
            case, created = get_or_create_case(
                session,
                court,
                cnr=entry.cnr,
                case_no=entry.case_no_text,
                source=FirstSeenSource.CAUSELIST,
            )
            if created:
                report.cases_new += 1
            if case.is_provisional:
                ref = case.cnr or f"{court.est_code}|{entry.case_no_text}"
                if queue.enqueue(
                    session,
                    FetchKind.DOSSIER,
                    ref,
                    origin.dossier_priority(),
                    lane=origin.lane,
                    list_date=origin.list_date,
                    requested_by=origin.requested_by,
                ):
                    report.queued += 1
        session.add(_entry_row(causelist, entry, source, case.id if case else None))
        report.entries_new += 1
        if case is not None:
            touched.append(case.id)
    causelist.entry_count = max(causelist.entry_count or 0, len(parsed.entries))
    causelist.parse_status = ParseStatus.PARSED if parsed.entries else ParseStatus.EMPTY
    causelist.entries_sha256 = parsed_fingerprint(parsed)  # decision 10: written at every parse
    causelist.error = None
    session.flush()
    if touched:
        refresh_search_vector(session, touched)
        matching.score_cases(session, touched, origin=RecommendationOrigin.CAUSE_LIST)
        # a listing of the case on a date its order suggested makes that date firm (next-date-extraction)
        from aslms.services import next_dates

        next_dates.match_after_court_change(session, touched)


def entry_values(e: Entry) -> dict[str, Any]:
    """The stored form of a parsed row's printed fields (the truncation the columns need)."""
    return {
        "sr_no": e.seq,
        "printed_sr_no": e.printed_sr_no,
        "court_no": (e.court_no or None) and e.court_no[:20],
        "bench_text": e.bench_text or None,
        "section": (e.section or None) and e.section[:200],
        "cnr": e.cnr,
        "case_no_text": (e.case_no_text or None) and e.case_no_text[:200],
        "is_connected": e.is_connected,
        "petitioner_text": e.petitioner_text,
        "respondent_text": e.respondent_text,
        "pet_advocate_text": e.pet_advocate_text,
        "res_advocate_text": e.res_advocate_text,
        "counsel_codes": [c[:60] for c in e.counsel_codes],
        "with_text": e.parent_case_no,
        "remarks": e.remarks,
    }


def _entry_row(
    causelist: Causelist, e: Entry, source: EntrySource, case_id: uuid.UUID | None
) -> CauselistEntry:
    return CauselistEntry(
        causelist_id=causelist.id,
        **entry_values(e),
        case_id=case_id,
        source=source,
        resolution_status=ResolutionStatus.RESOLVED
        if e.cnr
        else (ResolutionStatus.PROVISIONAL if e.case_no_text else ResolutionStatus.UNRESOLVED),
        raw={k: v for k, v in e.as_dict().items() if k != "raw_lines"} | {"raw_lines": e.raw_lines},
    )


# ------------------------------------------------------------------------------------------------ NAPIX path


async def load_day_from_napix(
    session: Session,
    hc: NapixHighCourt,
    court: Court,
    list_date: date,
    store: LocalStore,
    *,
    origin: QueueOrigin | None = None,
    report: DayReport,
) -> bool:
    """False when the gateway has no benches for the date (holiday, or outside its window)."""
    try:
        benches = await hc.causelist_benches(list_date)
    except NapixNotFound:
        benches = []
    if not benches:
        return False
    report.source = "napix"
    report.benches = len(benches)
    for b in benches:
        bid = int(b.bench_id)
        bench_day = session.scalar(
            select(CauselistBenchDay).where(
                CauselistBenchDay.court_id == court.id,
                CauselistBenchDay.list_date == list_date,
                CauselistBenchDay.bench_id == bid,
            )
        )
        if bench_day is None:
            session.add(
                CauselistBenchDay(
                    court_id=court.id,
                    list_date=list_date,
                    bench_id=bid,
                    judge_names_as_listed=b.judge_name,
                    raw=b.raw,
                )
            )
        bench = session.scalar(select(Bench).where(Bench.court_id == court.id, Bench.bench_id == bid))
        if bench is None:
            bench = Bench(court_id=court.id, bench_id=bid, judge_names=b.judge_name)
            session.add(bench)
        else:
            bench.judge_names = b.judge_name or bench.judge_names
            bench.last_seen = _now()
        session.flush()
        try:
            details = await hc.causelist_details(list_date, b.bench_id)
        except NapixNotFound:
            details = []
        refs = hc.causelist_refs(list_date, b.bench_id, details)
        for ref in refs:
            await _load_napix_list(session, hc, court, list_date, store, b.judge_name, ref, origin, report)
    return True


async def _load_napix_list(
    session: Session,
    hc: NapixHighCourt,
    court: Court,
    list_date: date,
    store: LocalStore,
    judge_name: str | None,
    ref: CauseListRef,
    origin: QueueOrigin | None,
    report: DayReport,
) -> None:
    raw = ref.raw if isinstance(ref.raw, dict) else {}
    lt = list_type_of(ref.list_type)
    cl = _get_or_create_list(
        session,
        court,
        list_date,
        bench_id=int(ref.bench_id),
        napix_causelist_id=int(ref.causelist_id)
        if ref.causelist_id and str(ref.causelist_id).isdigit()
        else None,
        source=ListSource.NAPIX,
        list_type=lt,
    )
    cl.list_type_text = (ref.list_type or "").strip()[:100] or None
    cl.bench_label = raw.get("bench") or judge_name
    cl.raw = raw or cl.raw
    report.lists += 1
    if cl.parse_status == ParseStatus.PARSED:
        return
    if cl.document_id is None:
        try:
            pdf = await hc.show_causelist(ref)
        except NapixNotFound:
            cl.fetch_status, cl.error = FetchStatus.NOT_AVAILABLE, "628 no record"
            report.warnings.append(f"bench {ref.bench_id} list {ref.causelist_id}: no PDF (628)")
            return
        if not isinstance(pdf, bytes):
            cl.fetch_status, cl.error = FetchStatus.FAILED, f"not a PDF: {str(pdf)[:200]}"
            report.warnings.append(f"bench {ref.bench_id} list {ref.causelist_id}: {cl.error}")
            return
        doc, new = store_pdf(
            session,
            store,
            pdf,
            doc_date=list_date,
            description=f"Cause list {list_date} bench {ref.bench_id} list {ref.causelist_id} (NAPIX)",
        )
        cl.document_id, cl.fetch_status, cl.fetched_at = doc.id, FetchStatus.FETCHED, _now()
        report.lists_fetched += 1
        report.documents_new += int(new)
        data = pdf
    else:
        data = store.get(session.get(Document, cl.document_id).storage_key)
    _parse_into(session, court, cl, data, origin, report)


def _parse_into(
    session: Session, court: Court, cl: Causelist, data: bytes, origin: QueueOrigin | None, report: DayReport
) -> None:
    try:
        parsed = parse_causelist_pdf(data)
    except Exception as exc:  # noqa: BLE001 — a bad file is recorded, never lost
        cl.parse_status, cl.error = ParseStatus.FAILED, f"{exc.__class__.__name__}: {exc}"[:500]
        report.warnings.append(f"list {cl.id}: parse failed: {cl.error}")
        return
    if cl.list_type == ListType.OTHER and parsed.list_type:
        cl.list_type = list_type_of(None, parsed)
    cl.list_type_text = cl.list_type_text or parsed.list_type_text
    if parsed.list_date and parsed.list_date != cl.list_date:
        report.warnings.append(f"list {cl.id}: PDF is dated {parsed.list_date}, expected {cl.list_date}")
    report.warnings.extend(f"list {cl.id}: {w}" for w in parsed.warnings[:20])
    apply_entries(session, court, cl, parsed, origin=origin, report=report)


# ------------------------------------------------------------------------------------------------ website path


def website_files(causelist_dir: Path, list_date: date) -> list[tuple[Path, ListType]]:
    folder = causelist_dir / list_date.strftime("%d-%m-%Y")
    if not folder.is_dir():
        return []
    out = []
    for f in sorted(folder.iterdir()):
        m = WEBSITE_FILE_RE.match(f.name)
        if not m:
            continue
        kind = m.group(1).lower()
        suffix = m.group(3) or ""
        lt = (
            ListType(kind)
            if kind != "daily"
            else (ListType.VACATION if "vacation" in suffix.lower() else ListType.DAILY)
        )
        out.append((f, lt))
    return out


def load_day_from_website(
    session: Session,
    court: Court,
    list_date: date,
    store: LocalStore,
    causelist_dir: Path,
    *,
    origin: QueueOrigin | None = None,
    report: DayReport,
) -> bool:
    files = website_files(causelist_dir, list_date)
    if not files:
        return False
    report.source = "ghc_website"
    seen_sha: set[str] = set()
    for path, lt in files:
        data = path.read_bytes()
        doc, new = store_pdf(
            session,
            store,
            data,
            doc_date=list_date,
            description=f"Cause list {list_date} {path.name} (GHC website)",
        )
        if doc.sha256 in seen_sha:
            continue  # a duplicate download ("… (1).pdf")
        seen_sha.add(doc.sha256)
        cl = _get_or_create_list(
            session,
            court,
            list_date,
            bench_id=None,
            napix_causelist_id=None,
            source=ListSource.GHC_WEBSITE,
            list_type=lt,
        )
        cl.label = path.name[:200]
        report.lists += 1
        if cl.document_id is None:
            cl.document_id, cl.fetch_status, cl.fetched_at = doc.id, FetchStatus.FETCHED, _now()
            report.lists_fetched += 1
            report.documents_new += int(new)
        if cl.parse_status == ParseStatus.PARSED:
            continue
        _parse_into(session, court, cl, data, origin, report)
    return True


async def load_causelist_day(
    session: Session,
    hc: NapixHighCourt | None,
    court: Court,
    list_date: date,
    *,
    store: LocalStore,
    causelist_dir: Path | None,
    origin: QueueOrigin | None = None,
) -> DayReport:
    report = DayReport(list_date=list_date)
    day_lock(session, list_date)
    found = False
    if hc is not None:
        found = await load_day_from_napix(session, hc, court, list_date, store, origin=origin, report=report)
    if not found and causelist_dir is not None:
        found = load_day_from_website(
            session, court, list_date, store, causelist_dir, origin=origin, report=report
        )
    if not found:
        report.skipped_reason = "no cause list for this date (NAPIX empty, no website PDF on disk)"
    session.flush()
    return report


# ------------------------------------------------------------------------------------------------ the recheck


@dataclass
class RecheckReport:
    """The result of one `causelist_recheck` item (design court-data-freshness, "Services")."""

    list_date: date
    candidates: int = 0
    called: int = 0
    unchanged: int = 0
    same_entries: int = 0
    versions_new: int = 0
    unparsed: int = 0
    not_available: int = 0
    failed: int = 0
    skipped_fresh: int = 0
    cases_changed: int = 0
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        d = self.__dict__.copy()
        d["list_date"] = self.list_date.isoformat()
        d["warnings"] = self.warnings[:50]
        return d


def recheck_candidates(session: Session, court: Court, list_date: date) -> list[Causelist]:
    """The current versions of the date's NAPIX lists that hold a stored PDF and were fetched (decision 8); lists
    without a PDF, a 628 or a failed fetch stay with the day row, which already retries them."""
    return list(
        session.scalars(
            select(Causelist)
            .where(
                CURRENT_LIST,
                Causelist.court_id == court.id,
                Causelist.list_date == list_date,
                Causelist.source == ListSource.NAPIX,
                Causelist.document_id.is_not(None),
                Causelist.fetch_status == FetchStatus.FETCHED,
                Causelist.bench_id.is_not(None),
            )
            .order_by(Causelist.bench_id, Causelist.napix_causelist_id)
        ).all()
    )


def _list_ref(cl: Causelist) -> CauseListRef:
    """The Show Cause List reference rebuilt from the stored row: all `hc.show_causelist` sends (decision 8)."""
    return CauseListRef(
        cl.list_date,
        str(cl.bench_id),
        str(cl.napix_causelist_id) if cl.napix_causelist_id is not None else None,
        cl.list_type_text,
        raw=cl.raw if isinstance(cl.raw, dict) else {},
    )


def _resolve_reissue(session: Session, cl: Causelist) -> int:
    """A recheck that ended "unchanged", "same entries" or in a new version resolves the list's open re-issue failures."""
    return source_failures.resolve_prefix(session, REISSUE_FAILURE, f"{cl.id}|")


async def recheck_day(
    session: Session,
    hc: NapixHighCourt,
    court: Court,
    list_date: date,
    store: LocalStore,
    *,
    now: datetime | None = None,
    fresh_minutes: int = 180,
    origin: QueueOrigin | None = None,
) -> RecheckReport:
    """Show Cause List again for each candidate list of the date not fetched or checked in the last `fresh_minutes`
    (decisions 8-11), under the date's lock (decision 15). No Cause List Bench or Details call.

    Each list's work is committed as it ends and the date's lock taken again in the next transaction (a
    transaction-level lock, safe under PgBouncer transaction pooling): an error on a later list, which the runner
    rolls back, keeps the stamps, versions and events of the lists before it, and the retried item calls only the
    lists not yet checked (decision 8). The caller commits the last, empty transaction with its own work."""
    now = now or _now()
    report = RecheckReport(list_date=list_date)
    day_lock(session, list_date)
    origin = origin or QueueOrigin(FetchLane.DAILY, list_date)
    if origin.list_date is None:
        origin = replace(origin, list_date=list_date)
    fresh_since = now - timedelta(minutes=fresh_minutes)
    candidates = recheck_candidates(session, court, list_date)
    report.candidates = len(candidates)
    for cl in candidates:
        session.refresh(
            cl
        )  # read again under this transaction's lock (sessions keep attributes across commits)
        if cl.superseded_at is not None:
            report.skipped_fresh += 1  # replaced meanwhile: its successor was fetched just now
            continue
        await _recheck_list(
            session, hc, court, cl, store, report, now=now, fresh_since=fresh_since, origin=origin
        )
        session.flush()
        session.commit()
        day_lock(session, list_date)
    session.flush()
    return report


async def _recheck_list(
    session: Session,
    hc: NapixHighCourt,
    court: Court,
    cl: Causelist,
    store: LocalStore,
    report: RecheckReport,
    *,
    now: datetime,
    fresh_since: datetime,
    origin: QueueOrigin,
) -> None:
    """One candidate list of `recheck_day` (decisions 8-13)."""
    seen = max((t for t in (cl.fetched_at, cl.last_checked_at) if t is not None), default=None)
    if seen is not None and seen > fresh_since:
        report.skipped_fresh += 1
        return
    report.called += 1
    try:
        pdf = await hc.show_causelist(_list_ref(cl))
    except NapixNotFound:
        # a 628 on a held list changes nothing: a withdrawal is never inferred (decision 11)
        report.not_available += 1
        cl.last_checked_at = now
        return
    if not isinstance(pdf, bytes) or not pdf:
        report.failed += 1
        report.warnings.append(f"list {cl.id}: not a PDF: {str(pdf)[:200]}")
        cl.last_checked_at = now
        return
    sha = hashlib.sha256(pdf).hexdigest()
    current_doc = session.get(Document, cl.document_id)
    if current_doc is not None and current_doc.sha256 == sha:
        report.unchanged += 1
        cl.last_checked_at = now
        stored_fingerprint(session, cl)
        _resolve_reissue(session, cl)
        return
    try:
        parsed = parse_causelist_pdf(pdf)
        problem = None if parsed.entries else "no entries"
    except Exception as exc:  # noqa: BLE001 — a bad download never replaces a good list (decision 11)
        parsed, problem = None, f"{exc.__class__.__name__}: {exc}"[:500]
    if problem is not None:
        report.unparsed += 1
        report.warnings.append(f"list {cl.id}: re-issued PDF kept out: {problem}")
        source_failures.record(
            session, REISSUE_FAILURE, f"{cl.id}|{sha}", f"re-issued PDF not used: {problem}", "parse"
        )
        cl.last_checked_at = now
        return
    if parsed_fingerprint(parsed) == stored_fingerprint(session, cl):
        # a difference in the file only (owner check (c)): no version, no document
        report.same_entries += 1
        cl.last_checked_at = now
        _resolve_reissue(session, cl)
        return
    new = _new_version(session, court, cl, pdf, parsed, store, origin=origin, now=now)
    report.versions_new += 1
    report.cases_changed += _listing_changes(session, cl, new, report)
    _resolve_reissue(session, cl)


def _new_version(
    session: Session,
    court: Court,
    cl: Causelist,
    pdf: bytes,
    parsed: ParsedCauseList,
    store: LocalStore,
    *,
    origin: QueueOrigin,
    now: datetime,
) -> Causelist:
    """Decision 9: the PDF stored (dedupe by sha256), the current row superseded, then the new version inserted with
    its own document and entries (through `apply_entries`, which also scores its cases and matches next dates)."""
    doc, _new = store_pdf(
        session,
        store,
        pdf,
        doc_date=cl.list_date,
        description=(
            f"Cause list {cl.list_date} bench {cl.bench_id} list {cl.napix_causelist_id} (NAPIX), "
            f"corrected version {cl.version + 1}"
        ),
    )
    cl.superseded_at = now
    cl.last_checked_at = now
    session.flush()  # the partial unique index allows one current version: the old row steps aside first
    new = Causelist(
        court_id=cl.court_id,
        list_date=cl.list_date,
        bench_id=cl.bench_id,
        napix_causelist_id=cl.napix_causelist_id,
        list_type=cl.list_type,
        list_type_text=cl.list_type_text or parsed.list_type_text,
        bench_label=cl.bench_label,
        label=cl.label,
        source=cl.source,
        document_id=doc.id,
        fetch_status=FetchStatus.FETCHED,
        fetched_at=now,
        last_checked_at=now,
        raw=cl.raw,
        version=cl.version + 1,
        supersedes_id=cl.id,
    )
    session.add(new)
    session.flush()
    apply_entries(session, court, new, parsed, origin=origin, report=DayReport(list_date=cl.list_date))
    return new


def _placements(entries) -> dict[uuid.UUID, list[dict[str, Any]]]:
    out: dict[uuid.UUID, list[dict[str, Any]]] = {}
    for e in entries:
        if e.case_id is None:
            continue
        out.setdefault(e.case_id, []).append(
            {"court_no": e.court_no, "printed_sr_no": e.printed_sr_no, "section": e.section}
        )
    return out


def _listing_changes(session: Session, old: Causelist, new: Causelist, report: RecheckReport) -> int:
    """Decision 13: one `listing_changed` event per case whose placement changed (added, removed or moved), then the
    cases printed only in the old version rescored (origin `rescore`: an engine recommendation whose only signal was
    there falls below its band and expires) and the next dates of both versions' cases matched again. Human
    suggestions, claims and ownership are never touched. Returns the number of cases whose placement changed."""
    before = _placements(stored_entries(session, old.id))
    after = _placements(stored_entries(session, new.id))
    changed = 0
    for case_id in list(dict.fromkeys([*before, *after])):
        b, a = before.get(case_id, []), after.get(case_id, [])
        if b == a:
            continue
        change = "added" if not b else ("removed" if not a else "moved")
        case = session.get(Case, case_id)
        if case is None:
            continue
        emit_event(
            session,
            EventType.LISTING_CHANGED,
            case,
            {
                "list_date": new.list_date.isoformat(),
                "bench_id": new.bench_id,
                "causelist_id": str(new.id),
                "version_from": old.version,
                "version_to": new.version,
                "change": change,
                "before": b,
                "after": a,
            },
            dedupe=f"listing_changed:{new.id}:{case_id}",
        )
        changed += 1
    session.flush()
    old_only = [c for c in before if c not in after]
    if old_only:
        matching.score_cases(session, old_only, origin=RecommendationOrigin.RESCORE)
    from aslms.services import next_dates

    next_dates.match_after_court_change(session, [*before, *after])
    if changed:
        report.warnings.append(f"list {old.id}: version {new.version} changed {changed} case(s)")
    return changed
