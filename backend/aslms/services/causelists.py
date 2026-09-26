"""Cause-list ingestion: rows (from NAPIX Cause List Details or the PDF parser) → cause list + entries → cases
→ links, hearings, next dates, events → scores and recommendations. Idempotent at every step (ground rule 4):
the document dedupes on sha256, the list on its unique key, entries on (list, source, sr_no), events on
dedupe_key; re-running a day creates nothing new."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from aslms.core.time import now_utc
from aslms.domain.alerts import NextDateSource
from aslms.domain.cases import (
    AdvocateSide,
    Case,
    CaseHearing,
    FirstSeenSource,
    HearingSource,
    LinkKind,
    LinkSource,
)
from aslms.domain.causelists import (
    CauseList,
    CauseListEntry,
    CauseListReconciliation,
    CauseListSource,
    EntrySource,
    FetchStatus,
    ListType,
    ParseStatus,
    ResolutionStatus,
)
from aslms.domain.documents import DocType, DocumentKind
from aslms.domain.events import EventType
from aslms.domain.reference import Court
from aslms.integration.base import CauseListRow
from aslms.integration.ghc.causelist_pdf import ParsedCauseList, parse_causelist
from aslms.services import cases as case_svc
from aslms.services import events, ownership, storage


@dataclass
class IngestStats:
    lists: int = 0
    entries_new: int = 0
    entries_seen: int = 0
    cases_new: int = 0
    provisional: int = 0
    with_cnr: int = 0
    recommendations: int = 0
    new_cnrs: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def merge(self, other: IngestStats) -> None:
        for k in (
            "lists",
            "entries_new",
            "entries_seen",
            "cases_new",
            "provisional",
            "with_cnr",
            "recommendations",
        ):
            setattr(self, k, getattr(self, k) + getattr(other, k))
        self.new_cnrs += other.new_cnrs
        self.warnings += other.warnings

    def as_dict(self) -> dict[str, object]:
        return {
            k: getattr(self, k)
            for k in (
                "lists",
                "entries_new",
                "entries_seen",
                "cases_new",
                "provisional",
                "with_cnr",
                "recommendations",
            )
        } | {"new_cnrs": len(self.new_cnrs), "warnings": self.warnings[:20]}


def upsert_causelist(
    session: Session,
    *,
    court: Court,
    list_date: date,
    list_type: ListType,
    source: CauseListSource,
    bench_id: str = "",
    napix_causelist_id: str = "",
    label: str | None = None,
    document_id: uuid.UUID | None = None,
    raw: dict | None = None,
) -> CauseList:
    stmt = (
        insert(CauseList)
        .values(
            court_id=court.id,
            list_date=list_date,
            bench_id=bench_id,
            napix_causelist_id=napix_causelist_id,
            list_type=list_type,
            source=source,
            label=label,
            document_id=document_id,
            fetch_status=FetchStatus.FETCHED,
            fetched_at=now_utc(),
            raw=raw,
        )
        .on_conflict_do_update(
            index_elements=["court_id", "list_date", "bench_id", "napix_causelist_id", "source"],
            set_={"fetched_at": now_utc(), "fetch_status": FetchStatus.FETCHED},
        )
        .returning(CauseList.id)
    )
    cl_id = session.execute(stmt).scalar_one()
    return session.get(CauseList, cl_id)


def ingest_rows(
    session: Session,
    causelist: CauseList,
    rows: list[CauseListRow],
    entry_source: EntrySource,
    *,
    rescore: bool = True,
) -> IngestStats:
    stats = IngestStats(lists=1)
    court = session.get(Court, causelist.court_id)
    supplementary = causelist.list_type == ListType.SUPPLEMENTARY
    by_sr: dict[int, Case] = {}
    touched: dict[uuid.UUID, Case] = {}

    for row in rows:
        stats.entries_seen += 1
        case, created = case_svc.resolve_case(
            session,
            cnr=row.cnr,
            case_no_text=row.case_no_text,
            court=court,
            source=FirstSeenSource.CAUSELIST,
            is_filing_number=row.is_filing_number,
            petitioner=row.petitioner_text,
            respondent=row.respondent_text,
        )
        by_sr[row.sr_no] = case
        touched[case.id] = case
        if created:
            stats.cases_new += 1
            if case.cnr:
                stats.new_cnrs.append(case.cnr)
        if case.is_provisional:
            stats.provisional += 1
        if row.cnr:
            stats.with_cnr += 1
        if not case.petitioner_summary and row.petitioner_text:
            case.petitioner_summary = row.petitioner_text
        if not case.respondent_summary and row.respondent_text:
            case.respondent_summary = row.respondent_text

        entry_id = session.execute(
            insert(CauseListEntry)
            .values(
                causelist_id=causelist.id,
                sr_no=row.sr_no,
                court_no=row.court_no,
                cnr=row.cnr,
                case_id=case.id,
                case_no_text=row.case_no_text,
                petitioner_text=row.petitioner_text,
                respondent_text=row.respondent_text,
                pet_advocate_text=row.pet_advocate_text,
                res_advocate_text=row.res_advocate_text,
                counsel_codes=list(row.counsel_codes),
                with_text=row.with_text,
                remarks=row.remarks,
                source=entry_source,
                resolution_status=ResolutionStatus.PROVISIONAL
                if case.is_provisional
                else ResolutionStatus.RESOLVED,
                raw=row.raw
                | {
                    "section": row.section,
                    "bench": row.bench_text,
                    "printed_sr": row.printed_sr,
                    "connected_to": row.connected_to,
                    "parent": row.parent_case_no_text,
                },
            )
            .on_conflict_do_nothing(index_elements=["causelist_id", "source", "sr_no"])
            .returning(CauseListEntry.id)
        ).scalar_one_or_none()
        if entry_id:
            stats.entries_new += 1

        if row.pet_advocate_text:
            case_svc.add_advocates(session, case, AdvocateSide.PETITIONER, row.pet_advocate_text.split("\n"))
        if row.res_advocate_text:
            case_svc.add_advocates(session, case, AdvocateSide.RESPONDENT, row.res_advocate_text.split("\n"))

        session.execute(
            insert(CaseHearing)
            .values(
                case_id=case.id,
                business_date=causelist.list_date,
                purpose=(row.section or "")[:300],
                bench_text=row.bench_text,
                source=HearingSource.CAUSELIST,
                raw={"court_no": row.court_no, "list_type": causelist.list_type.value, "sr": row.printed_sr},
            )
            .on_conflict_do_nothing(index_elements=["case_id", "business_date", "purpose"])
        )
        case_svc.record_next_date(session, case, causelist.list_date, NextDateSource.CAUSELIST)
        if causelist.list_date >= (case.next_hearing_date or date.min) and case.status.value != "disposed":
            case.next_hearing_date = causelist.list_date
            case.next_purpose = row.section or case.next_purpose
        events.emit(
            session,
            EventType.LISTED_SUPPLEMENTARY if supplementary else EventType.LISTED,
            f"listed:{case.id}:{causelist.list_date}:{causelist.list_type.value}",
            case_id=case.id,
            occurred_at=now_utc(),
            payload={
                "list_date": causelist.list_date.isoformat(),
                "list_type": causelist.list_type.value,
                "court_no": row.court_no,
                "section": row.section,
                "sr": row.printed_sr,
                "bench": row.bench_text,
            },
        )
        if row.parent_case_no_text:
            case_svc.add_link(session, case, row.parent_case_no_text, LinkKind.IA_IN, LinkSource.CAUSELIST)

    # connected matters: link each WITH row to its main entry, both ways discoverable through case_links
    for row in rows:
        if row.connected_to and row.connected_to in by_sr:
            main, sub = by_sr[row.connected_to], by_sr[row.sr_no]
            if main.id != sub.id and main.case_no_text:
                case_svc.add_link(
                    session, sub, main.case_no_text, LinkKind.WITH, LinkSource.CAUSELIST, to_cnr=main.cnr
                )

    session.flush()
    for case in touched.values():
        case_svc.link_pending_targets(session, case)
        case_svc.refresh_search_vector(session, case.id)
    causelist.entry_count = len(rows)
    causelist.parse_status = ParseStatus.PARSED if rows else ParseStatus.FAILED

    if rescore and touched:
        cfg = ownership.load_config(session)
        for case in touched.values():
            stats.recommendations += sum(1 for r in ownership.rescore(session, case, cfg) if r["band"])
    return stats


def ingest_pdf(
    session: Session,
    data: bytes,
    *,
    source: CauseListSource,
    filename: str | None = None,
    court: Court | None = None,
    list_date: date | None = None,
    rescore: bool = True,
) -> tuple[IngestStats, ParsedCauseList | None]:
    """Stores the PDF, parses it, ingests the rows. Re-ingesting the same bytes is a no-op."""
    court = court or case_svc.default_court(session)
    doc, created = storage.store_system_document(
        session,
        data,
        kind=DocumentKind.CAUSELIST,
        doc_type=DocType.CAUSELIST_PDF,
        filename=filename,
        doc_date=list_date,
    )
    existing = session.scalar(select(CauseList).where(CauseList.document_id == doc.id))
    if existing and existing.parse_status == ParseStatus.PARSED and not created:
        return IngestStats(), None
    parsed = parse_causelist(filename, data=data)
    d = parsed.list_date or list_date
    if d is None:
        st = IngestStats()
        st.warnings.append(f"{filename}: no list date found")
        return st, parsed
    lt = ListType(parsed.list_type) if parsed.list_type in ListType._value2member_map_ else ListType.OTHER
    cl = upsert_causelist(
        session,
        court=court,
        list_date=d,
        list_type=lt,
        source=source,
        napix_causelist_id=f"file:{doc.sha256[:16]}",
        label=parsed.title or filename,
        document_id=doc.id,
        raw={"filename": filename, "pages": parsed.page_count, "warnings": parsed.warnings},
    )
    stats = ingest_rows(session, cl, parsed.rows, EntrySource.PDF_PARSE, rescore=rescore)
    stats.warnings += [f"{filename}: {w}" for w in parsed.warnings]
    doc.doc_date = d
    return stats, parsed


def reconcile(session: Session, list_date: date) -> dict[str, int]:
    """Compares NAPIX Cause List Details rows with PDF rows for a date (per CNR). Answers the plan's open
    question — is Cause List Details complete? — and feeds the data-collection health report."""
    rows = session.execute(
        select(CauseListEntry.cnr, CauseListEntry.source, CauseList.id)
        .join(CauseList, CauseList.id == CauseListEntry.causelist_id)
        .where(CauseList.list_date == list_date, CauseListEntry.cnr.isnot(None))
    ).all()
    napix = {r.cnr for r in rows if r.source == EntrySource.NAPIX_DETAILS}
    pdf: dict[str, uuid.UUID] = {}
    for r in rows:
        if r.source == EntrySource.PDF_PARSE:
            pdf.setdefault(r.cnr, r.id)
    if not napix or not pdf:
        return {"napix": len(napix), "pdf": len(pdf), "only_napix": 0, "only_pdf": 0}
    any_napix_list = next(r.id for r in rows if r.source == EntrySource.NAPIX_DETAILS)
    for cnr in napix | set(pdf):
        session.execute(
            insert(CauseListReconciliation)
            .values(
                causelist_id=pdf.get(cnr, any_napix_list), cnr=cnr, in_napix=cnr in napix, in_pdf=cnr in pdf
            )
            .on_conflict_do_update(
                index_elements=["causelist_id", "cnr"], set_={"in_napix": cnr in napix, "in_pdf": cnr in pdf}
            )
        )
    return {
        "napix": len(napix),
        "pdf": len(pdf),
        "only_napix": len(napix - set(pdf)),
        "only_pdf": len(set(pdf) - napix),
    }
