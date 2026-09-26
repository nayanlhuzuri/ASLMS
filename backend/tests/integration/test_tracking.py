"""The NAPIX-dependent services, driven by a fake court source (no network): first sight, change detection,
orders archive with next-date reading, status refresh, and the daily cycle over a local cause-list folder."""

from __future__ import annotations

import shutil
from datetime import date, timedelta
from pathlib import Path

import pymupdf
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aslms.core.time import now_utc, today_ist
from aslms.domain.alerts import NextDate, NextDateSource
from aslms.domain.cases import Case, CaseParty, FirstSeenSource
from aslms.domain.causelists import CauseList
from aslms.domain.documents import DocumentText, DownloadStatus, Order
from aslms.domain.events import Event, EventType
from aslms.domain.ops import JobRun
from aslms.integration.base import StatusRecord
from aslms.integration.napix.hc import parse_case_record

FIX = Path(__file__).resolve().parents[1] / "fixtures"
CNR = "GAHC010153612024"


def _order_pdf(text: str) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), text, fontsize=11)
    data = doc.tobytes()
    doc.close()
    return data


class FakeSource:
    """Implements the parts of CourtSource the tracker uses. `raw` is what the CNR API would return."""

    def __init__(self, raw: dict, status: StatusRecord | None = None, order_text: str | None = None):
        self.raw, self.status, self.order_text = raw, status, order_text
        self.calls: list[str] = []

    async def case_by_cnr(self, cnr: str):
        self.calls.append(f"cnr:{cnr}")
        return parse_case_record(self.raw, cnr) if cnr == CNR else None

    async def current_status(self, cnrs: list[str]):
        self.calls.append(f"status:{len(cnrs)}")
        return [self.status] if self.status else []

    async def order_pdf(self, cnr: str, order):
        self.calls.append(f"order:{order.order_no}")
        return _order_pdf(self.order_text) if self.order_text else None


def _raw(next_date: str = "2026-10-15", pend: str = "P", orders: dict | None = None) -> dict:
    return {
        "cino": CNR,
        "type_name_reg": "WP(C)",
        "reg_no": "1536",
        "reg_year": "2024",
        "pend_disp": pend,
        "date_next_list": next_date,
        "purpose_name": "ADMISSION",
        "pet_name": "RAM KUMAR",
        "res_name": "THE STATE OF ASSAM",
        "res_extra_party": {"party_no2": "THE DIRECTOR OF SECONDARY EDUCATION"},
        "res_adv": "SC, SEC. EDU.",
        "interimorder": orders or {"o1": {"order_no": "1", "order_date": "2026-09-01"}},
        "historyofcasehearing": {"h1": {"business_date": "2026-09-01", "purpose": "ADMISSION"}},
    }


@pytest.fixture()
def case(db: Session) -> Case:
    from aslms.services import cases as case_svc

    court = case_svc.default_court(db)
    c, created = case_svc.resolve_case(
        db, cnr=CNR, case_no_text="WP(C)/1536/2024", court=court, source=FirstSeenSource.CAUSELIST
    )
    assert created
    c.is_tracked = True
    db.commit()
    return c


def test_first_sight_applies_record_and_is_idempotent(db: Session, case: Case) -> None:
    from aslms.services import tracking

    src = FakeSource(_raw())
    assert tracking.first_sight(db, src) == {"ok": 1, "not_found": 0, "failed": 0}
    db.commit()
    db.refresh(case)
    assert case.next_hearing_date == date(2026, 10, 15) and case.last_full_refresh_at is not None
    parties = db.scalars(
        select(CaseParty.name)
        .where(CaseParty.case_id == case.id)
        .order_by(CaseParty.role, CaseParty.party_no)
    ).all()
    assert parties == ["RAM KUMAR", "THE STATE OF ASSAM", "THE DIRECTOR OF SECONDARY EDUCATION"]
    assert db.scalar(select(func.count()).select_from(Order).where(Order.case_id == case.id)) == 1
    events = set(db.scalars(select(Event.type).where(Event.case_id == case.id)))
    assert {EventType.CASE_CREATED, EventType.HEARING_DATE_CHANGED, EventType.ORDER_RECEIVED} <= events
    # nothing new when the same record comes back
    n_events = db.scalar(select(func.count()).select_from(Event))
    assert tracking.first_sight(db, src)["ok"] == 0  # already fetched → not picked again
    assert tracking.fetch_case(db, src, case) == "ok"
    db.commit()
    assert db.scalar(select(func.count()).select_from(Event)) == n_events


def test_change_detection_emits_status_and_date_events(db: Session, case: Case) -> None:
    from aslms.services import tracking

    tracking.fetch_case(db, FakeSource(_raw()), case)
    db.commit()
    tracking.fetch_case(db, FakeSource(_raw(next_date="2026-11-20", pend="D")), case)
    db.commit()
    changes = db.scalars(
        select(Event)
        .where(
            Event.case_id == case.id,
            Event.type.in_([EventType.STATUS_CHANGED, EventType.HEARING_DATE_CHANGED]),
        )
        .order_by(Event.occurred_at)
    ).all()
    assert [e.type for e in changes][-2:] == [EventType.STATUS_CHANGED, EventType.HEARING_DATE_CHANGED]
    assert changes[-1].payload["to"] == "2026-11-20"


def test_orders_download_extracts_text_and_reads_the_next_date(db: Session, case: Case) -> None:
    from aslms.services import orders, tracking

    src = FakeSource(_raw(), order_text="Heard. List the matter again on 29.10.2026 for hearing.")
    tracking.fetch_case(db, src, case)
    db.commit()
    counts = orders.download_pending(db, src)
    db.commit()
    assert counts == {"downloaded": 1, "not_available": 0, "failed": 0}
    order = db.scalar(select(Order).where(Order.case_id == case.id))
    assert order.download_status == DownloadStatus.DOWNLOADED and order.document_id
    assert "29.10.2026" in db.get(DocumentText, order.document_id).full_text
    nd = db.scalar(
        select(NextDate).where(NextDate.case_id == case.id, NextDate.source == NextDateSource.ORDER_SPECIFIC)
    )
    assert nd.next_date == date(2026, 10, 29) and nd.order_id == order.id
    assert orders.download_pending(db, src)["downloaded"] == 0  # idempotent


def test_period_direction_is_flagged_for_review(db: Session, case: Case) -> None:
    from aslms.services import alerts, orders, tracking

    src = FakeSource(_raw(), order_text="Issue notice, returnable in four weeks. List after two weeks.")
    tracking.fetch_case(db, src, case)
    orders.download_pending(db, src)
    db.commit()
    nd = db.scalar(select(NextDate).where(NextDate.case_id == case.id, NextDate.needs_review.is_(True)))
    assert nd is not None and nd.next_date == date(2026, 9, 15)
    assert alerts.generate(db)["next_date"] == 1


def test_status_refresh(db: Session, case: Case) -> None:
    from aslms.services import tracking

    st = StatusRecord(
        CNR, "pending", today_ist() + timedelta(days=3), "HEARING", None, None, None, {"cino": CNR, "x": 1}
    )
    out = tracking.status_refresh(db, FakeSource(_raw(), status=st))
    db.commit()
    assert out == {"requested": 1, "changed": 1, "missing": 0, "failed": 0}
    db.refresh(case)
    assert (
        case.next_hearing_date == today_ist() + timedelta(days=3) and case.last_status_refresh_at <= now_utc()
    )


def test_daily_cycle_over_local_folder(db: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from aslms.core.config import get_settings
    from aslms.db.session import sync_session
    from aslms.services.daily_cycle import run_daily_cycle

    folder = tmp_path / "01-09-2025"
    folder.mkdir()
    shutil.copy(FIX / "ghc_lawazima_01-09-2025.pdf", folder / "Lawazima_01-09-2025.pdf")
    (folder / "Notices_01-09-2025.pdf").write_bytes(b"%PDF-1.4 notice")  # notices are skipped
    monkeypatch.setenv("CAUSE_LIST_DIR", str(tmp_path))
    get_settings.cache_clear()
    try:
        r1 = run_daily_cycle(sync_session, date(2025, 9, 1))
        r2 = run_daily_cycle(sync_session, date(2025, 9, 1))
    finally:
        get_settings.cache_clear()
    assert r1["ingest"]["entries_new"] == 16 and r1["napix"] == "not configured"
    assert r1["first_sight"] == "skipped: NAPIX not configured"
    assert r2["ingest"]["entries_new"] == 0 and r2["ingest"]["lists"] == 0
    assert db.scalar(select(func.count()).select_from(CauseList)) == 1
    assert db.scalar(select(func.count()).select_from(JobRun)) == 2
