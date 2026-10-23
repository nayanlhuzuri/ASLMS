"""Listed for tomorrow (design alerts-visibility-roles, decisions 8-12): one `listed_tomorrow` alert per owned or
watched case on the next day's cause lists, from the evening window (or forced), with the court and the printed item of
every listing of the day; never for an unowned or merged case; the open hearing alert of that date closed `done` and
never raised or upgraded again by the sweep; the 7-day and 48-hour hearing alerts unchanged before the listing; a late
supplementary list does not alert again; expiry after the grace; `critical`, so an immediate e-mail."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pytest
import sqlalchemy as sa

from aslms.domain.alerts import AlertStatus, Severity
from aslms.domain.cases import Case
from aslms.domain.causelists import Causelist, CauselistEntry, EntrySource, ListSource, ListType
from aslms.domain.courts import Court
from aslms.domain.ops import JobRun
from aslms.domain.org import Channel
from aslms.domain.ownership import CaseOwnership, OwnershipRole
from aslms.domain.reference import AlertKind
from aslms.services import alert_rules as rules
from aslms.services import alerts
from aslms.services import notifications as notif
from aslms.services.mailer import RecordingMailer
from tests.db import alerts_support as h
from tests.db import workflow_support as w
from tests.db.world import USERS, make_case

TODAY = rules.today_ist(h.now_utc())
D = TODAY + timedelta(days=1)


def at(day: date, hh: int, mm: int) -> datetime:
    return datetime.combine(day, time(hh, mm), tzinfo=rules.IST)


EVENING = at(TODAY, 19, 10)
AFTERNOON = at(TODAY, 14, 30)


def listing(
    s, case: Case, list_date: date, *, list_type=ListType.DAILY, court_no="3", printed="14", sr_no=None
):
    court = s.scalar(sa.select(Court).where(Court.est_code == "GAHC01"))
    cl = s.scalar(
        sa.select(Causelist).where(
            Causelist.list_date == list_date,
            Causelist.list_type == list_type,
            Causelist.source == ListSource.GHC_WEBSITE,
        )
    )
    if cl is None:
        cl = Causelist(
            court_id=court.id, list_date=list_date, list_type=list_type, source=ListSource.GHC_WEBSITE
        )
        s.add(cl)
        s.flush()
    n = sr_no or int(s.scalar(sa.select(sa.func.count()).select_from(CauselistEntry)) or 0) + 1
    s.add(
        CauselistEntry(
            causelist_id=cl.id,
            sr_no=n,
            printed_sr_no=printed,
            cnr=case.cnr,
            case_id=case.id,
            case_no_text=case.case_no_text,
            court_no=court_no,
            bench_text="HONOURABLE MR. JUSTICE A",
            petitioner_text="PARTY-MARKER petitioner",
            pet_advocate_text="ADVOCATE-MARKER",
            source=EntrySource.PDF_PARSE,
        )
    )
    s.flush()


def owned(s, world, *, watcher: bool = True, **kw) -> Case:
    """An EDU case allotted to (and held by) off1; HEALTH watches it."""
    case = w.claimed_case(s, world)
    for k, v in kw.items():
        setattr(case, k, v)
    if watcher:
        s.add(
            CaseOwnership(case_id=case.id, office_id=world.offices["HEALTH"].id, role=OwnershipRole.WATCHER)
        )
    s.flush()
    return case


def listed_alerts(s, case: Case) -> list:
    return h.alerts_of(s, case, AlertKind.LISTED_TOMORROW)


def hearing_alerts(s, case: Case) -> list:
    return h.alerts_of(s, case, AlertKind.HEARING_DUE)


def run(s, now=EVENING, **kw) -> dict:
    out = alerts.listed_tomorrow(s, now=now, **kw)
    s.commit()
    return out


@pytest.fixture()
def wide(world):
    w.widen(world)
    return world


def test_owned_and_watched_cases_on_tomorrows_list_alert_once_with_court_and_item(wide):
    world = wide
    with world.Session() as s:
        case = owned(s, world, case_no_text="WP(C)/77/2026")
        listing(s, case, D, court_no="3", printed="14")
        listing(s, make_case(s), TODAY + timedelta(days=2))  # not tomorrow
        s.commit()
        out = run(s)
        assert out["list_date"] == D.isoformat() and out["cases"] == 1 and out["alerts_new"] == 1
        [a] = listed_alerts(s, case)
        assert a.dedupe_key == f"listed_tomorrow:{case.id}:{D.isoformat()}"
        assert Severity(a.severity) == Severity.CRITICAL and a.due_at == rules.hearing_due_at(D)
        assert a.data["hearing_date"] == D.isoformat() and a.data["entries_total"] == 1
        assert a.data["entries"] == [
            {"list_type": "daily", "court_no": "3", "item_no": "14", "bench_text": "HONOURABLE MR. JUSTICE A"}
        ]
        assert a.title == f"Listed tomorrow, {D.strftime('%d %b %Y')}, court 3 item 14: WP(C)/77/2026"
        assert "PARTY-MARKER" not in a.title + a.body and "ADVOCATE-MARKER" not in str(a.data)
        assert h.recipient_emails(s, a) == {USERS["edu_off1"][0], USERS["health_admin"][0]}
        again = run(s, now=EVENING + timedelta(hours=1))
        assert again["cases"] == 1 and again["alerts_new"] == 0 and len(listed_alerts(s, case)) == 1


def test_daily_and_supplementary_listings_make_one_alert_listing_both(wide):
    world = wide
    with world.Session() as s:
        case = owned(s, world)
        listing(s, case, D, list_type=ListType.SUPPLEMENTARY, court_no="5", printed="2")
        listing(s, case, D, list_type=ListType.DAILY, court_no="3", printed=None, sr_no=40)
        s.commit()
        assert run(s)["entries_seen"] == 2
        [a] = listed_alerts(s, case)
        assert [(e["list_type"], e["court_no"], e["item_no"]) for e in a.data["entries"]] == [
            ("daily", "3", "40"),  # no printed number: the serial number
            ("supplementary", "5", "2"),
        ]
        assert "+1 more" in a.title
        assert a.body.endswith("court 3, item 40; supplementary list: court 5, item 2.")


def test_unowned_listed_case_raises_nothing(wide):
    world = wide
    with world.Session() as s:
        unowned = make_case(s)
        listing(s, unowned, D)
        watched_only = make_case(s)
        s.add(
            CaseOwnership(
                case_id=watched_only.id, office_id=world.offices["HEALTH"].id, role=OwnershipRole.WATCHER
            )
        )
        listing(s, watched_only, D)
        s.commit()
        out = run(s)
        assert out["cases"] == 1 and out["skipped_unowned"] == 1 and out["alerts_new"] == 0
        assert listed_alerts(s, unowned) == [] and listed_alerts(s, watched_only) == []


def test_before_window_nothing_and_force_runs(wide):
    world = wide
    with world.Session() as s:
        case = owned(s, world)
        listing(s, case, D)
        s.commit()
        assert run(s, now=AFTERNOON) == {"skipped": "before_window"}
        assert run(s, now=at(TODAY, 18, 29)) == {"skipped": "before_window"}
        assert listed_alerts(s, case) == []
        assert run(s, now=AFTERNOON, force=True)["alerts_new"] == 1
        assert len(listed_alerts(s, case)) == 1
        counters = alerts.sweep_dates(s, now=AFTERNOON)
        s.commit()
        assert counters["listed_skipped"] == "before_window"


def test_open_hearing_due_closed_done_listed(wide):
    world = wide
    with world.Session() as s:
        case = owned(s, world, next_hearing_date=D)
        s.commit()
        alerts.sweep_dates(s, now=AFTERNOON)
        s.commit()
        [hearing] = hearing_alerts(s, case)
        assert AlertStatus(hearing.status) == AlertStatus.OPEN
        listing(s, case, D)
        s.commit()
        out = run(s)
        assert out["hearing_closed"] == 1
        s.refresh(hearing)
        assert AlertStatus(hearing.status) == AlertStatus.DONE
        assert hearing.data["closed_reason"] == "listed_tomorrow"


def test_sweep_does_not_raise_or_upgrade_hearing_due_after_listing(wide):
    world = wide
    with world.Session() as s:
        case = owned(s, world, next_hearing_date=D)
        listing(s, case, D)
        s.commit()
        counters = alerts.sweep_dates(s, now=EVENING)  # the same sweep raises the listing first
        s.commit()
        assert counters["listed_alerts_new"] == 1 and counters["listed_cases"] == 1
        assert len(listed_alerts(s, case)) == 1 and hearing_alerts(s, case) == []
        run_row = s.scalar(
            sa.select(JobRun).where(JobRun.job == alerts.JOB_DATES).order_by(JobRun.started_at.desc())
        )
        assert run_row.counters["listed_alerts_new"] == 1
        alerts.sweep_dates(s, now=at(D, 0, 10))  # the morning of D
        s.commit()
        assert hearing_alerts(s, case) == []


def test_hearing_alerts_before_the_listing_unchanged(wide):
    world = wide
    with world.Session() as s:
        soon = owned(s, world, next_hearing_date=TODAY + timedelta(days=4))
        near = owned(s, world, next_hearing_date=D)
        s.commit()
        alerts.sweep_dates(s, now=AFTERNOON)
        s.commit()
        [a] = hearing_alerts(s, soon)
        assert Severity(a.severity) == Severity.HIGH
        [b] = hearing_alerts(s, near)
        assert Severity(b.severity) == Severity.CRITICAL
        assert listed_alerts(s, soon) == [] and listed_alerts(s, near) == []


def test_late_supplementary_after_alert_does_not_realert(wide):
    world = wide
    with world.Session() as s:
        case = owned(s, world)
        listing(s, case, D)
        s.commit()
        run(s)
        [a] = listed_alerts(s, case)
        before = len(h.notifications_of(s, a))
        listing(s, case, D, list_type=ListType.SUPPLEMENTARY, court_no="7", printed="1")
        s.commit()
        out = run(s, now=EVENING + timedelta(hours=2))
        assert out["alerts_new"] == 0 and out["entries_seen"] == 2
        s.refresh(a)
        assert a.data["entries_total"] == 1 and len(h.notifications_of(s, a)) == before


def test_listed_alert_expires_after_grace(wide):
    world = wide
    with world.Session() as s:
        case = owned(s, world)
        listing(s, case, D)
        s.commit()
        run(s)
        counters = alerts.sweep_dates(s, now=rules.hearing_due_at(D) + timedelta(hours=11))
        s.commit()
        [a] = listed_alerts(s, case)
        assert AlertStatus(a.status) == AlertStatus.OPEN and counters["closed_listed"] == 0
        counters = alerts.sweep_dates(s, now=rules.hearing_due_at(D) + timedelta(hours=13))
        s.commit()
        s.refresh(a)
        assert AlertStatus(a.status) == AlertStatus.EXPIRED and a.data["closed_reason"] == "passed"
        assert counters["closed_listed"] == 1


def test_merged_case_skipped(wide):
    world = wide
    with world.Session() as s:
        survivor = owned(s, world)
        merged = owned(s, world)
        merged.merged_into_case_id = survivor.id
        listing(s, merged, D)
        s.commit()
        out = run(s)
        assert out["entries_seen"] == 0 and listed_alerts(s, merged) == []


def test_severity_critical_sends_immediate_mail(wide):
    world = wide
    with world.Session() as s:
        case = owned(s, world, watcher=False, case_no_text="WP(C)/88/2026", petitioner_summary="PARTY-MARKER")
        listing(s, case, D, court_no="3", printed="14")
        s.commit()
        run(s)
        [a] = listed_alerts(s, case)
        assert [n for n in h.notifications_of(s, a, Channel.EMAIL)]  # critical: e-mailed at once
        mailer = RecordingMailer()
        notif.send_pending(s, mailer, now=max(EVENING, h.now_utc()) + timedelta(minutes=1))
        s.commit()
        [mail] = [m for m in mailer.sent if "Listed tomorrow" in m.subject]
        assert mail.to == USERS["edu_off1"][0]
        assert mail.subject.startswith("[ASLMS CRITICAL] Listed tomorrow")
        assert "court 3, item 14" in mail.text
        assert "PARTY-MARKER" not in mail.subject + mail.text and "ADVOCATE-MARKER" not in mail.text
