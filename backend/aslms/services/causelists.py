"""Pipeline stage 2: one cause-list day. NAPIX first (Cause List Bench → one `causelist_bench_days` row per
bench → Cause List Details → one `causelists` row per list → Show Cause List PDF stored in `documents` → parsed
→ `causelist_entries` → `cases` and `fetch_queue` dossier rows); the website PDFs on disk (`CAUSELIST_DIR/
<dd-mm-yyyy>/<Type>_<date>.pdf`) when the gateway has no list for the date. Re-running a day creates nothing
new: lists, documents (sha256) and entries have unique keys."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from aslms.core.errors import NapixNotFound
from aslms.domain.cases import FirstSeenSource
from aslms.domain.causelists import (
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
from aslms.domain.ops import FetchKind
from aslms.domain.ownership import RecommendationOrigin
from aslms.domain.reference import DocType
from aslms.integration.base import CauseListRef
from aslms.integration.napix.hc import NapixHighCourt
from aslms.parsing.causelist_pdf import Entry, ParsedCauseList, parse_causelist_pdf
from aslms.services import matching, queue
from aslms.services.cases import get_or_create_case, refresh_search_vector
from aslms.services.storage import LocalStore

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


def store_pdf(
    session: Session, store: LocalStore, data: bytes, *, doc_date: date, description: str
) -> tuple[Document, bool]:
    stored = store.put(data, "application/pdf")
    doc = session.scalar(select(Document).where(Document.sha256 == stored.sha256))
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
    dossier_priority: int,
    report: DayReport,
) -> None:
    """Parsed rows → `causelist_entries` (immutable, keyed by position) → cases → dossier queue rows, then the
    matching engine scores every case the new rows touched (inline, one savepoint per case; a scoring error is
    recorded in `source_failures` and never fails the list)."""
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
                if queue.enqueue(session, FetchKind.DOSSIER, ref, dossier_priority):
                    report.queued += 1
        session.add(_entry_row(causelist, entry, source, case.id if case else None))
        report.entries_new += 1
        if case is not None:
            touched.append(case.id)
    causelist.entry_count = max(causelist.entry_count or 0, len(parsed.entries))
    causelist.parse_status = ParseStatus.PARSED if parsed.entries else ParseStatus.EMPTY
    causelist.error = None
    session.flush()
    if touched:
        refresh_search_vector(session, touched)
        matching.score_cases(session, touched, origin=RecommendationOrigin.CAUSE_LIST)


def _entry_row(
    causelist: Causelist, e: Entry, source: EntrySource, case_id: uuid.UUID | None
) -> CauselistEntry:
    return CauselistEntry(
        causelist_id=causelist.id,
        sr_no=e.seq,
        printed_sr_no=e.printed_sr_no,
        court_no=(e.court_no or None) and e.court_no[:20],
        bench_text=e.bench_text or None,
        section=(e.section or None) and e.section[:200],
        cnr=e.cnr,
        case_id=case_id,
        case_no_text=(e.case_no_text or None) and e.case_no_text[:200],
        is_connected=e.is_connected,
        petitioner_text=e.petitioner_text,
        respondent_text=e.respondent_text,
        pet_advocate_text=e.pet_advocate_text,
        res_advocate_text=e.res_advocate_text,
        counsel_codes=[c[:60] for c in e.counsel_codes],
        with_text=e.parent_case_no,
        remarks=e.remarks,
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
    dossier_priority: int,
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
            await _load_napix_list(
                session, hc, court, list_date, store, b.judge_name, ref, dossier_priority, report
            )
    return True


async def _load_napix_list(
    session: Session,
    hc: NapixHighCourt,
    court: Court,
    list_date: date,
    store: LocalStore,
    judge_name: str | None,
    ref: CauseListRef,
    dossier_priority: int,
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
    _parse_into(session, court, cl, data, dossier_priority, report)


def _parse_into(
    session: Session, court: Court, cl: Causelist, data: bytes, dossier_priority: int, report: DayReport
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
    apply_entries(session, court, cl, parsed, dossier_priority=dossier_priority, report=report)


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
    dossier_priority: int,
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
        _parse_into(session, court, cl, data, dossier_priority, report)
    return True


async def load_causelist_day(
    session: Session,
    hc: NapixHighCourt | None,
    court: Court,
    list_date: date,
    *,
    store: LocalStore,
    causelist_dir: Path | None,
    dossier_priority: int = queue.PRIORITY["dossier_new"],
) -> DayReport:
    report = DayReport(list_date=list_date)
    found = False
    if hc is not None:
        found = await load_day_from_napix(
            session, hc, court, list_date, store, dossier_priority=dossier_priority, report=report
        )
    if not found and causelist_dir is not None:
        found = load_day_from_website(
            session, court, list_date, store, causelist_dir, dossier_priority=dossier_priority, report=report
        )
    if not found:
        report.skipped_reason = "no cause list for this date (NAPIX empty, no website PDF on disk)"
    session.flush()
    return report
