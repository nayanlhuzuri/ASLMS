"""DB_STANDARD §10 / §12.1: a full dossier fills case_applications, case_lower_courts, case_objections, the act
master link, the legal-heir flags, the §10 scalars and state/district; applying it again changes nothing; a
party that disappears from the dossier keeps its row with `is_current = false`."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aslms.db.seed import run_seed
from aslms.domain.cases import (
    Act,
    Case,
    CaseAct,
    CaseApplication,
    CaseLowerCourt,
    CaseObjection,
    CaseParty,
    District,
    FirstSeenSource,
    LowerCourtLevel,
    PartyRole,
    State,
)
from aslms.services import cases as case_svc
from aslms.services import tracking
from tests.integration.test_tracking import CNR, FakeSource

FIX = Path(__file__).resolve().parents[1] / "fixtures"


def _dossier() -> dict:
    raw = json.loads((FIX / "cnr_dossier_shape.json").read_text(encoding="utf-8"))
    raw.pop("_note", None)
    return raw


def _counts(db: Session) -> dict[str, int]:
    return {
        t.__tablename__: db.scalar(sa.select(sa.func.count()).select_from(t)) or 0
        for t in (CaseParty, CaseAct, CaseApplication, CaseLowerCourt, CaseObjection)
    }


def _tracked_case(db: Session) -> Case:
    run_seed(db)  # Assam and its districts
    court = case_svc.default_court(db)
    case, created = case_svc.resolve_case(
        db, cnr=CNR, case_no_text="WP(C)/1536/2024", court=court, source=FirstSeenSource.CAUSELIST
    )
    assert created
    case.is_tracked = True
    db.commit()
    return case


def test_dossier_fills_every_section_and_is_idempotent(db: Session) -> None:
    case = _tracked_case(db)
    db.add(Act(national_act_code="1950-1", name="Constitution of India"))
    db.commit()
    src = FakeSource(_dossier())
    tracking.first_sight(db, src)
    db.commit()
    db.refresh(case)

    assert case.date_first_list == date(2024, 3, 20)
    assert case.sub_category == "APPOINTMENT"
    assert case.state_id == db.scalar(sa.select(State.id).where(State.name == "Assam"))
    assert case.district_id == db.scalar(sa.select(District.id).where(District.name == "Kamrup Metropolitan"))
    assert (
        case.filing_case_type_id is None
    )  # no case-type master loaded yet; the text is kept in filing_no_text

    parties = {
        (p.role, p.party_no): p for p in db.scalars(sa.select(CaseParty).where(CaseParty.case_id == case.id))
    }
    assert {k for k in parties} == {
        (PartyRole.PETITIONER, 1),
        (PartyRole.PETITIONER, 2),
        (PartyRole.RESPONDENT, 1),
        (PartyRole.RESPONDENT, 2),
    }
    assert parties[(PartyRole.RESPONDENT, 1)].has_legal_heir is True
    assert parties[(PartyRole.PETITIONER, 1)].has_legal_heir is False

    acts = {a.act_name_as_listed: a for a in db.scalars(sa.select(CaseAct).where(CaseAct.case_id == case.id))}
    assert (
        acts["Constitution of India"].act_id is not None
        and acts["Constitution of India"].national_act_code == "1950-1"
    )
    assert acts["Assam Services (Pension) Rules"].act_id is None

    ias = {
        a.ia_number: a
        for a in db.scalars(sa.select(CaseApplication).where(CaseApplication.case_id == case.id))
    }
    assert ias["IA(Civil)/1001/2024"].status == "PENDING" and ias["IA(Civil)/1001/2024"].filing_date == date(
        2024, 5, 2
    )
    lower = {
        c.level: c for c in db.scalars(sa.select(CaseLowerCourt).where(CaseLowerCourt.case_id == case.id))
    }
    assert lower[LowerCourtLevel.APPELLATE].case_no_text == "TS/45/2022"
    assert lower[LowerCourtLevel.TRIAL].decision_date == date(2022, 6, 10)
    obj = db.scalars(sa.select(CaseObjection).where(CaseObjection.case_id == case.id)).all()
    assert len(obj) == 1 and obj[0].compliance_by_date == date(2024, 3, 4)

    before = _counts(db)
    snapshots = db.scalar(sa.select(sa.func.count()).select_from(sa.table("case_snapshots")))
    # apply the same dossier again: nothing new anywhere
    case.is_tracked, case.last_full_refresh_at = True, None
    db.commit()
    tracking.full_refresh(db, FakeSource(_dossier()))
    db.commit()
    assert _counts(db) == before
    assert db.scalar(sa.select(sa.func.count()).select_from(sa.table("case_snapshots"))) == snapshots


def test_party_upsert_keeps_history(db: Session) -> None:
    case = _tracked_case(db)
    tracking.first_sight(db, FakeSource(_dossier()))
    db.commit()
    changed = _dossier()
    changed.pop("pet_extra_party")  # petitioner 2 is gone from the court record
    changed["res_name"] = "THE STATE OF ASSAM AND ORS."
    case.last_full_refresh_at = None
    db.commit()
    tracking.full_refresh(db, FakeSource(changed))
    db.commit()
    rows = {
        (p.role, p.party_no): p for p in db.scalars(sa.select(CaseParty).where(CaseParty.case_id == case.id))
    }
    assert len(rows) == 4, "no party row is ever deleted"
    assert rows[(PartyRole.PETITIONER, 2)].is_current is False
    assert rows[(PartyRole.RESPONDENT, 1)].name == "THE STATE OF ASSAM AND ORS."
    assert rows[(PartyRole.RESPONDENT, 1)].is_current is True
