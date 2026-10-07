"""`aslms seed`: the rows the system needs before any NAPIX data arrives. Idempotent: every row is keyed by its
code and only inserted when missing (administrators edit labels; a second run inserts nothing).

Seeded here: the nine `ref_*` code sets from the Python enums, Secretariat designations, Assam as a state
(LGD 18) with its districts by name (LGD codes are entered later, never guessed), the Gauhati High Court
(NAPIX state code 18, verified live) with its four establishments from the bench master, and the root
Government of Assam office. Department offices, users and counsel codes are created under Administration."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from aslms.domain.courts import Court, CourtLevel, District, HighCourt, State
from aslms.domain.org import Designation, Office
from aslms.domain.reference import (
    REF_TABLES,
    AlertKind,
    DocType,
    EventType,
    OfficeKind,
    RefAlertKind,
    RefCaseStage,
    RefDocType,
    RefEventType,
    RefPermission,
    Stage,
)
from aslms.services import scoring_settings
from aslms.services.access_seed import PERMISSION_LABELS, seed_matrix, seed_super_admin


@dataclass
class SeedReport:
    inserted: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def add(self, table: str, n: int = 1) -> None:
        self.inserted[table] = self.inserted.get(table, 0) + n

    @property
    def total(self) -> int:
        return sum(self.inserted.values())


def _label(code: str) -> str:
    return code.replace("_", " ").strip().capitalize()


STAGE_PHASE = {
    Stage.COUNSEL_BRIEFED: "counsel",
    Stage.AFFIDAVIT_DRAFTED: "counsel",
    Stage.AFFIDAVIT_VETTED: "counsel",
    Stage.APPEAL_UNDER_CONSIDERATION: "appeal",
    Stage.APPEAL_FILED: "appeal",
    Stage.CONTEMPT_NOTICE: "contempt",
    Stage.CONTEMPT_REPLY_FILED: "contempt",
}
DOC_GROUP = {
    DocType.CAUSELIST: "court_record",
    DocType.ORDER: "court_record",
    DocType.JUDGMENT: "court_record",
    DocType.PETITION: "court_filing",
    DocType.AFFIDAVIT: "court_filing",
    DocType.COUNTER_AFFIDAVIT: "court_filing",
    DocType.REJOINDER: "court_filing",
    DocType.WRITTEN_SUBMISSION: "court_filing",
    DocType.REPLY: "court_filing",
    DocType.INTERLOCUTORY_APPLICATION: "court_filing",
    DocType.ANNEXURE: "court_filing",
    DocType.INSTRUCTIONS_TO_COUNSEL: "internal",
    DocType.GOVERNMENT_ORDER: "internal",
}
# labels that differ from the code (design documents-uploads, decision 6; new databases only)
DOC_TYPE_LABELS = {
    DocType.COUNTER_AFFIDAVIT: "Affidavit-in-opposition (counter affidavit)",
    DocType.GOVERNMENT_ORDER: "Government order / notification",
}
ALERT_SEVERITY = {
    AlertKind.HEARING_DUE: "high",
    AlertKind.NEXT_DATE_CHANGED: "high",
    AlertKind.NEW_ORDER: "high",
    AlertKind.COMPLIANCE_DUE: "high",
    AlertKind.OWNERSHIP: "normal",
    AlertKind.NEW_DOCUMENT: "normal",
}
# labels that differ from the code (design alerts-notifications, decision 13; new databases only)
ALERT_KIND_LABELS = {
    AlertKind.OWNERSHIP: "Ownership change",
    AlertKind.NEW_DOCUMENT: "New document",
    AlertKind.ADMIN_TICKET: "Admin ticket",
}
TRACKING_CARD_EVENTS = {
    EventType.CASE_CREATED,
    EventType.CASE_DISPOSED,
    EventType.LISTED,
    EventType.LISTED_SUPPLEMENTARY,
    EventType.NEXT_DATE_CHANGED,
    EventType.STATUS_CHANGED,
    EventType.ORDER_FOUND,
    EventType.ORDER_STORED,
    EventType.CLAIMED,
    EventType.ALLOTTED,
    EventType.CUSTODY_MOVED,
    EventType.STAGE_SET,
    EventType.CASE_TAKEN_OVER,
}


def _extra_columns(model: type, member: enum.Enum) -> dict:
    if model is RefCaseStage:
        return {"phase": STAGE_PHASE.get(member, "main")}
    if model is RefDocType:
        out = {"doc_group": DOC_GROUP.get(member, "internal")}
        if member in DOC_TYPE_LABELS:
            out["label"] = DOC_TYPE_LABELS[member]
        return out
    if model is RefAlertKind:
        out = {"default_severity": ALERT_SEVERITY.get(member, "normal")}
        if member in ALERT_KIND_LABELS:
            out["label"] = ALERT_KIND_LABELS[member]
        return out
    if model is RefPermission:
        label, description = PERMISSION_LABELS[member]
        return {"label": label, "description": description, "module": member.module}
    if model is RefEventType:
        return {"timeline_label": _label(member.value), "is_tracking_card": member in TRACKING_CARD_EVENTS}
    return {}


def seed_ref_tables(session: Session, report: SeedReport) -> None:
    """Inserts missing codes. `ref_permission` rows are upserted on code: their label and description follow
    `PERMISSION_LABELS` (DB_STANDARD §0; label editing by administrators is not built)."""
    for table, (model, enum_cls) in REF_TABLES.items():
        existing = set(session.scalars(select(model.code)).all())
        for order, member in enumerate(enum_cls, start=1):
            if member.value in existing:
                if model is RefPermission:
                    _refresh_permission_label(session, member, report)
                continue
            columns = {"code": member.value, "label": _label(member.value), "sort_order": order * 10}
            columns.update(_extra_columns(model, member))
            session.add(model(**columns))
            report.add(table)
    session.flush()


def _refresh_permission_label(session: Session, member: enum.Enum, report: SeedReport) -> None:
    label, description = PERMISSION_LABELS[member]
    row = session.get(RefPermission, member.value)
    if row is not None and (row.label != label or row.description != description):
        row.label, row.description = label, description
        report.add("ref_permission_relabelled")


DESIGNATIONS = [
    ("CS", "Chief Secretary"),
    ("ACS", "Additional Chief Secretary"),
    ("PS", "Principal Secretary"),
    ("CS_SEC", "Commissioner & Secretary"),
    ("SEC", "Secretary"),
    ("JS", "Joint Secretary"),
    ("DS", "Deputy Secretary"),
    ("US", "Under Secretary"),
    ("DIR", "Director"),
    ("ADDL_DIR", "Additional Director"),
    ("JT_DIR", "Joint Director"),
    ("DY_DIR", "Deputy Director"),
    ("ASST_DIR", "Assistant Director"),
    ("SO", "Section Officer"),
    ("ASO", "Assistant Section Officer"),
    ("LEGAL_OFFICER", "Legal Officer"),
    ("SC", "Standing Counsel"),
    ("GA", "Government Advocate"),
]


def seed_designations(session: Session, report: SeedReport) -> None:
    existing = set(session.scalars(select(Designation.code)).all())
    for order, (code, name) in enumerate(DESIGNATIONS, start=1):
        if code not in existing:
            session.add(Designation(code=code, name=name, sort_order=order * 10))
            report.add("designations")
    session.flush()


ASSAM_LGD_CODE = 18
# Current district names; `ecourts_name` is the spelling the NAPIX district master uses where it differs.
ASSAM_DISTRICTS: list[tuple[str, str | None]] = [
    ("Bajali", None),
    ("Baksa", None),
    ("Barpeta", None),
    ("Biswanath", None),
    ("Bongaigaon", None),
    ("Cachar", None),
    ("Charaideo", None),
    ("Chirang", None),
    ("Darrang", None),
    ("Dhemaji", None),
    ("Dhubri", None),
    ("Dibrugarh", None),
    ("Dima Hasao", None),
    ("Goalpara", None),
    ("Golaghat", None),
    ("Hailakandi", None),
    ("Hojai", None),
    ("Jorhat", None),
    ("Kamrup", None),
    ("Kamrup Metropolitan", "Kamrup(M)"),
    ("Karbi Anglong", None),
    ("Kokrajhar", None),
    ("Lakhimpur", None),
    ("Majuli", None),
    ("Morigaon", None),
    ("Nagaon", None),
    ("Nalbari", None),
    ("Sivasagar", "Sibsagar"),
    ("Sonitpur", None),
    ("South Salmara-Mankachar", None),
    ("Sribhumi", "Karimganj"),
    ("Tamulpur", None),
    ("Tinsukia", None),
    ("Udalguri", None),
    ("West Karbi Anglong", None),
]


def seed_places(session: Session, report: SeedReport) -> State:
    state = session.scalar(select(State).where(State.name == "Assam"))
    if state is None:
        state = State(name="Assam", lgd_code=ASSAM_LGD_CODE)
        session.add(state)
        session.flush()
        report.add("states")
    existing = set(session.scalars(select(District.name).where(District.state_id == state.id)).all())
    for name, ecourts_name in ASSAM_DISTRICTS:
        if name not in existing:
            session.add(District(state_id=state.id, name=name, ecourts_name=ecourts_name))
            report.add("districts")
    session.flush()
    return state


GAUHATI_HC_NAPIX_STATE_CODE = 18  # NAPIX state master, verified live 1 Oct 2026
# est_code, bench master bench_id, bench_name — from docs/specs/samples/bench_master_2026-09-03.json
GAUHATI_HC_COURTS = [
    ("GAHC01", 1, "Principal Seat at Guwahati"),
    ("GAHC02", 2, "Kohima Bench"),
    ("GAHC03", 3, "Aizawl Bench"),
    ("GAHC04", 4, "Itanagar Bench"),
]


def seed_courts(session: Session, report: SeedReport) -> HighCourt:
    hc = session.scalar(select(HighCourt).where(HighCourt.napix_state_code == GAUHATI_HC_NAPIX_STATE_CODE))
    if hc is None:
        hc = HighCourt(napix_state_code=GAUHATI_HC_NAPIX_STATE_CODE, name="Gauhati High Court")
        session.add(hc)
        session.flush()
        report.add("high_courts")
    existing = set(session.scalars(select(Court.est_code)).all())
    for est_code, bench_no, bench_name in GAUHATI_HC_COURTS:
        if est_code not in existing:
            session.add(
                Court(
                    est_code=est_code,
                    name=f"Gauhati High Court, {bench_name}",
                    high_court_id=hc.id,
                    napix_bench_no=bench_no,
                    bench_location=bench_name,
                    court_level=CourtLevel.HC,
                )
            )
            report.add("courts")
    session.flush()
    return hc


ROOT_OFFICE_CODE = "GOA"


def seed_offices(session: Session, report: SeedReport) -> Office:
    root = session.scalar(select(Office).where(Office.code == ROOT_OFFICE_CODE))
    if root is None:
        root = Office(
            code=ROOT_OFFICE_CODE, name="Government of Assam", kind=OfficeKind.STATE, path=ROOT_OFFICE_CODE
        )
        session.add(root)
        session.flush()
        report.add("offices")
    return root


def seed_all(session: Session) -> SeedReport:
    report = SeedReport()
    seed_ref_tables(session, report)
    seed_designations(session, report)
    seed_places(session, report)
    seed_courts(session, report)
    root = seed_offices(session, report)
    seed_matrix(session, report)
    seed_super_admin(session, report, root)
    scoring_settings.seed_default(session, report)
    return report
