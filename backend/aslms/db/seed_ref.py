"""Reference rows (DB_STANDARD §7, §3, §0): the `ref_*` code sets seeded from the Python enums, the
designations master, and the Assam state / district masters.

Idempotent: a row is inserted when its code is missing; on later runs only the machine-facing extras
(`sort_order`, `phase`, `doc_group`, `default_severity`, `is_tracking_card`) are refreshed, never the label or
description, which administrators may edit. `run_seed` reports how many rows each run inserted, so the
acceptance gate's "second run inserts 0 rows" is checkable."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from aslms.domain.alerts import AlertKind, Severity
from aslms.domain.cases import District, State
from aslms.domain.documents import DocGroup, DocType
from aslms.domain.events import EventType
from aslms.domain.org import Designation, OfficeKind, Role
from aslms.domain.reference import (
    RefAlertKind,
    RefCaseStage,
    RefDocType,
    RefEventType,
    RefNoteKind,
    RefOfficeKind,
    RefRecordType,
    RefRequestKind,
    RefRole,
)
from aslms.domain.workflow import STAGE_ORDER, NoteKind, RequestKind, Stage
from aslms.services.refno import RecordType

# ------------------------------------------------------------------------------------------ labels
ROLE_LABELS = {
    Role.STATE_OVERSIGHT: ("State oversight", "CM / Chief Secretary office; read-only across the State"),
    Role.DEPT_HEAD: (
        "Department head",
        "Secretary of the department; sees and directs the department's cases",
    ),
    Role.DEPT_ADMIN: (
        "Department administrator",
        "Nodal officer: claims, allots, manages users and mappings",
    ),
    Role.DEPT_OFFICER: ("Department officer", "Section-level officer; works the cases allotted to them"),
    Role.DIRECTORATE_USER: ("Directorate user", "Directorate / field office; cases allotted to the unit"),
    Role.REFERRAL_REVIEWER: ("Referral reviewer", "Gives views on cases referred to their department"),
    Role.STANDING_COUNSEL: (
        "Standing counsel",
        "Sees the cases they appear in and what is shared with counsel",
    ),
    Role.CENTRAL_OPERATOR: ("Central operator", "Central Monitoring Cell: data collection and follow-up"),
    Role.AUDITOR: ("Auditor", "Read-only, including the audit log"),
}
OFFICE_KIND_LABELS = {
    OfficeKind.DEPARTMENT: "Department",
    OfficeKind.DIRECTORATE: "Directorate",
    OfficeKind.SECTION: "Section",
    OfficeKind.STATE_OFFICE: "State office",
    OfficeKind.COUNSEL_OFFICE: "Counsel office",
    OfficeKind.CENTRAL_CELL: "Central cell",
}
STAGE_LABELS = {
    Stage.NOTICE_RECEIVED: "Notice received",
    Stage.RECORDS_RECEIVED: "Records received",
    Stage.RESPONSE_MODE_DECIDED: "Response mode decided",
    Stage.INPUTS_AWAITED: "Inputs awaited",
    Stage.INPUTS_RECEIVED: "Inputs received",
    Stage.REFERRAL_VIEWS_AWAITED: "Referral views awaited",
    Stage.INSTRUCTIONS_SENT: "Instructions sent to counsel",
    Stage.AFFIDAVIT_FILED: "Affidavit filed",
    Stage.ORDER_UNDER_EXAMINATION: "Order under examination",
    Stage.COMPLIANCE_IN_PROGRESS: "Compliance in progress",
    Stage.COMPLIED: "Complied",
    Stage.APPEAL_REVIEW_UNDER_CONSIDERATION: "Appeal / review under consideration",
    Stage.APPEAL_REVIEW_INSTRUCTED: "Appeal / review instructed",
    Stage.APPEAL_REVIEW_FILED: "Appeal / review filed",
    Stage.CONTEMPT_NOTICE_RECEIVED: "Contempt notice received",
    Stage.VAKALATNAMA_SENT: "Vakalatnama sent",
    Stage.APPEARANCE_ENTERED: "Appearance entered",
}
STAGE_PHASE = {
    **{s: "main" for s in STAGE_ORDER[: STAGE_ORDER.index(Stage.COMPLIED) + 1]},
    Stage.APPEAL_REVIEW_UNDER_CONSIDERATION: "appeal",
    Stage.APPEAL_REVIEW_INSTRUCTED: "appeal",
    Stage.APPEAL_REVIEW_FILED: "appeal",
    Stage.CONTEMPT_NOTICE_RECEIVED: "contempt",
    Stage.VAKALATNAMA_SENT: "counsel",
    Stage.APPEARANCE_ENTERED: "counsel",
}
REQUEST_KIND_LABELS = {
    RequestKind.RECORDS: ("Records", "Petition, notice, annexures"),
    RequestKind.REPORT: ("Report", "Parawise comments / report from a directorate"),
    RequestKind.INSTRUCTIONS: ("Instructions", "Instructions to standing counsel"),
    RequestKind.VIEWS: ("Views", "Views of a referral department"),
    RequestKind.SIGNATURE: ("Signature", "Affidavit signature"),
    RequestKind.IMPLEMENTATION: ("Implementation", "Compliance with a court order"),
    RequestKind.BRIEF: ("Brief", "Brief from standing counsel"),
    RequestKind.OTHER: ("Other", None),
}
NOTE_KIND_LABELS = {
    NoteKind.GENERAL: "Note",
    NoteKind.HANDOVER: "Hand-over note",
    NoteKind.INSTRUCTION: "Instruction",
    NoteKind.OPINION: "Opinion",
    NoteKind.HEARING_NOTE: "Hearing note",
    NoteKind.COMPLIANCE: "Compliance note",
    NoteKind.DECISION: "Decision",
    NoteKind.SYSTEM: "System note",
}
DOC_TYPE_LABELS = {
    DocType.ORDER: "Order",
    DocType.JUDGMENT: "Judgment",
    DocType.CAUSELIST_PDF: "Cause list",
    DocType.WRIT_PETITION: "Writ petition",
    DocType.AFFIDAVIT_IN_OPPOSITION: "Affidavit-in-opposition",
    DocType.REPLY: "Reply",
    DocType.REJOINDER: "Rejoinder",
    DocType.IA: "Interlocutory application",
    DocType.ANNEXURE: "Annexure",
    DocType.COMPLIANCE_REPORT: "Compliance report",
    DocType.PARAWISE_COMMENTS: "Parawise comments",
    DocType.INSTRUCTIONS_TO_COUNSEL: "Instructions to counsel",
    DocType.OTHER: "Other",
}
ALERT_KIND_LABELS = {
    AlertKind.HEARING: ("Hearing", Severity.NORMAL),
    AlertKind.NEXT_DATE: ("Next date", Severity.HIGH),
    AlertKind.COMPLIANCE: ("Compliance due", Severity.NORMAL),
    AlertKind.ORDER_RECEIVED: ("Order received", Severity.NORMAL),
    AlertKind.UNCLAIMED_FOLLOWUP: ("Unclaimed case follow-up", Severity.NORMAL),
    AlertKind.REQUEST_DUE: ("Request due", Severity.HIGH),
    AlertKind.DATA_HEALTH: ("Data collection", Severity.HIGH),
}
EVENT_LABELS: dict[EventType, tuple[str, str]] = {
    EventType.LISTED: ("Listed", "calendar"),
    EventType.LISTED_SUPPLEMENTARY: ("Listed (supplementary)", "calendar"),
    EventType.NOT_LISTED_AS_EXPECTED: ("Not listed as expected", "alert"),
    EventType.HEARING_DATE_CHANGED: ("Hearing date changed", "calendar"),
    EventType.STATUS_CHANGED: ("Status changed", "flag"),
    EventType.ORDER_RECEIVED: ("Order received", "file"),
    EventType.CASE_CREATED: ("Case first seen", "plus"),
    EventType.CASE_REFRESHED: ("Court record refreshed", "refresh"),
    EventType.CASE_MERGED: ("Case merged", "merge"),
    EventType.CASE_LINKED: ("Linked case", "link"),
    EventType.RECOMMENDATION_MADE: ("Recommended to a department", "inbox"),
    EventType.RECOMMENDATION_DISMISSED: ("Recommendation dismissed", "inbox"),
    EventType.CASE_CLAIMED: ("Claimed", "check"),
    EventType.OWNERSHIP_TRANSFER_REQUESTED: ("Transfer requested", "arrow"),
    EventType.OWNERSHIP_TRANSFERRED: ("Transferred", "arrow"),
    EventType.OWNERSHIP_RELEASED: ("Released", "arrow"),
    EventType.WATCHER_ADDED: ("Watcher added", "eye"),
    EventType.DOCUMENT_UPLOADED: ("Document uploaded", "upload"),
    EventType.NEXT_DATE_EXTRACTED: ("Next date recorded", "calendar"),
    EventType.ALERT_RAISED: ("Alert raised", "bell"),
    EventType.CUSTODY_MOVED: ("Custody moved", "move"),
    EventType.REQUEST_SENT: ("Request sent", "send"),
    EventType.REQUEST_ANSWERED: ("Request answered", "reply"),
    EventType.REQUEST_WITHDRAWN: ("Request withdrawn", "undo"),
    EventType.STAGE_CHANGED: ("Stage changed", "steps"),
    EventType.NOTE_ADDED: ("Note added", "note"),
    EventType.FILE_ADDED: ("File added", "paperclip"),
    EventType.DOCUMENT_INGESTED: ("Sent to SourceTrace", "database"),
    EventType.SOURCE_FAILED: ("Data source failed", "alert"),
}
RECORD_TYPE_LABELS = {
    RecordType.CASE: "Case",
    RecordType.REQ: "Request",
    RecordType.NOTE: "Note",
    RecordType.DOC: "Document",
    RecordType.TRF: "Ownership transfer",
    RecordType.NXT: "Next date (manual)",
    RecordType.ALR: "Alert",
}

# (code, name) — the Assam Secretariat designations the portal starts with; administrators add the rest
DESIGNATIONS: tuple[tuple[str, str], ...] = (
    ("COMM_SECY", "Commissioner and Secretary"),
    ("PRINCIPAL_SECY", "Principal Secretary"),
    ("SECY", "Secretary"),
    ("JOINT_SECY", "Joint Secretary"),
    ("DEPUTY_SECY", "Deputy Secretary"),
    ("UNDER_SECY", "Under Secretary"),
    ("SECTION_OFFICER", "Section Officer"),
    ("ASST_SECTION_OFFICER", "Assistant Section Officer"),
    ("DIRECTOR", "Director"),
    ("JOINT_DIRECTOR", "Joint Director"),
    ("DEPUTY_DIRECTOR", "Deputy Director"),
    ("ASST_DIRECTOR", "Assistant Director"),
    ("LEGAL_OFFICER", "Legal Officer"),
    ("STANDING_COUNSEL", "Standing Counsel"),
    ("ADDL_STANDING_COUNSEL", "Additional Standing Counsel"),
    ("GOVT_ADVOCATE", "Government Advocate"),
    ("OPERATOR", "Operator, Central Monitoring Cell"),
    ("AUDITOR", "Auditor"),
)

# Assam (LGD state code 18) and its districts as the Local Government Directory lists them (Karimganj was
# renamed Sribhumi in November 2024). The LGD district codes are entered by the administrator from
# lgdirectory.gov.in — they are identifiers and are never guessed (ground rule 1).
ASSAM_LGD_CODE = 18
ASSAM_DISTRICTS: tuple[str, ...] = (
    "Bajali",
    "Baksa",
    "Barpeta",
    "Biswanath",
    "Bongaigaon",
    "Cachar",
    "Charaideo",
    "Chirang",
    "Darrang",
    "Dhemaji",
    "Dhubri",
    "Dibrugarh",
    "Dima Hasao",
    "Goalpara",
    "Golaghat",
    "Hailakandi",
    "Hojai",
    "Jorhat",
    "Kamrup",
    "Kamrup Metropolitan",
    "Karbi Anglong",
    "Kokrajhar",
    "Lakhimpur",
    "Majuli",
    "Morigaon",
    "Nagaon",
    "Nalbari",
    "Sivasagar",
    "Sonitpur",
    "South Salmara-Mankachar",
    "Sribhumi",
    "Tamulpur",
    "Tinsukia",
    "Udalguri",
    "West Karbi Anglong",
)


def _humanise(code: str) -> str:
    return code.replace("_", " ").capitalize()


def _upsert_ref(session: Session, model: type, rows: list[dict[str, Any]]) -> int:
    """Insert missing codes; refresh only the machine-facing extras of existing rows."""
    existing = {r.code: r for r in session.scalars(select(model))}
    inserted = 0
    for row in rows:
        cur = existing.get(row["code"])
        if cur is None:
            session.add(model(**row))
            inserted += 1
            continue
        for k, v in row.items():
            if k not in ("code", "label", "description") and getattr(cur, k) != v:
                setattr(cur, k, v)
    session.flush()
    return inserted


def seed_ref_tables(session: Session) -> int:
    from aslms.services.documents import COURT_FILING_TYPES, INTERNAL_TYPES
    from aslms.services.events import TRACKING_CARD_TYPES

    n = 0
    n += _upsert_ref(
        session,
        RefRole,
        [
            {"code": r.value, "label": ROLE_LABELS[r][0], "description": ROLE_LABELS[r][1], "sort_order": i}
            for i, r in enumerate(Role)
        ],
    )
    n += _upsert_ref(
        session,
        RefOfficeKind,
        [
            {"code": k.value, "label": OFFICE_KIND_LABELS[k], "sort_order": i}
            for i, k in enumerate(OfficeKind)
        ],
    )
    n += _upsert_ref(
        session,
        RefCaseStage,
        [
            {"code": s.value, "label": STAGE_LABELS[s], "sort_order": i, "phase": STAGE_PHASE[s]}
            for i, s in enumerate(STAGE_ORDER)
        ],
    )
    n += _upsert_ref(
        session,
        RefRequestKind,
        [
            {
                "code": k.value,
                "label": REQUEST_KIND_LABELS[k][0],
                "description": REQUEST_KIND_LABELS[k][1],
                "sort_order": i,
            }
            for i, k in enumerate(RequestKind)
        ],
    )
    n += _upsert_ref(
        session,
        RefNoteKind,
        [{"code": k.value, "label": NOTE_KIND_LABELS[k], "sort_order": i} for i, k in enumerate(NoteKind)],
    )

    def doc_group(t: DocType) -> str:
        if t in COURT_FILING_TYPES:
            return DocGroup.COURT_FILING.value
        if t in INTERNAL_TYPES:
            return DocGroup.INTERNAL.value
        if t in (DocType.ORDER, DocType.JUDGMENT, DocType.CAUSELIST_PDF):
            return DocGroup.COURT_RECORD.value
        return DocGroup.COURT_FILING.value  # `other`: the uploader says whether it is internal

    n += _upsert_ref(
        session,
        RefDocType,
        [
            {"code": t.value, "label": DOC_TYPE_LABELS[t], "sort_order": i, "doc_group": doc_group(t)}
            for i, t in enumerate(DocType)
        ],
    )
    n += _upsert_ref(
        session,
        RefAlertKind,
        [
            {
                "code": k.value,
                "label": ALERT_KIND_LABELS[k][0],
                "sort_order": i,
                "default_severity": ALERT_KIND_LABELS[k][1].value,
            }
            for i, k in enumerate(AlertKind)
        ],
    )
    n += _upsert_ref(
        session,
        RefEventType,
        [
            {
                "code": e.value,
                "label": EVENT_LABELS.get(e, (_humanise(e.value), None))[0],
                "timeline_label": EVENT_LABELS.get(e, (_humanise(e.value), None))[0],
                "icon_key": EVENT_LABELS.get(e, (None, None))[1],
                "is_tracking_card": e in TRACKING_CARD_TYPES,
                "sort_order": i,
            }
            for i, e in enumerate(EventType)
        ],
    )
    n += _upsert_ref(
        session,
        RefRecordType,
        [
            {"code": t.value, "label": RECORD_TYPE_LABELS[t], "sort_order": i}
            for i, t in enumerate(RecordType)
        ],
    )
    return n


def seed_designations(session: Session) -> int:
    existing = {d.code for d in session.scalars(select(Designation))}
    inserted = 0
    for i, (code, name) in enumerate(DESIGNATIONS):
        if code not in existing:
            session.add(Designation(code=code, name=name, sort_order=i))
            inserted += 1
    session.flush()
    return inserted


def seed_assam(session: Session) -> int:
    """Assam and its districts. `ecourts_code` for the state follows NAPIX_STATE_CODE via `master_sync`."""
    inserted = 0
    state = session.scalar(select(State).where(State.lgd_code == ASSAM_LGD_CODE))
    if state is None:
        state = State(lgd_code=ASSAM_LGD_CODE, name="Assam")
        session.add(state)
        session.flush()
        inserted += 1
    existing = {d.name for d in session.scalars(select(District).where(District.state_id == state.id))}
    for name in ASSAM_DISTRICTS:
        if name not in existing:
            session.add(District(state_id=state.id, name=name))
            inserted += 1
    session.flush()
    return inserted


def ref_row_counts(session: Session) -> dict[str, tuple[int, int]]:
    """table -> (rows, enum size); the gate's step 3 check."""
    from sqlalchemy import func

    pairs = [
        (RefRole, Role),
        (RefOfficeKind, OfficeKind),
        (RefCaseStage, Stage),
        (RefRequestKind, RequestKind),
        (RefNoteKind, NoteKind),
        (RefDocType, DocType),
        (RefAlertKind, AlertKind),
        (RefEventType, EventType),
        (RefRecordType, RecordType),
    ]
    return {
        m.__tablename__: (session.scalar(select(func.count()).select_from(m)) or 0, len(e)) for m, e in pairs
    }
