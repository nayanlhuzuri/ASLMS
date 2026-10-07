"""The two generators (design alerts-notifications, decisions 1–13, 15): the event scan's window and
idempotence, one alert per court event for owned cases only and only for recent court dates, the date sweep
(hearing alerts and their upgrade to critical, expiry when the date changes, cause-list listings, compliance,
requests, recommendations decided, aged informational alerts), the ownership and new-document alerts, and
the reference numbers (a re-run allocates no serial)."""

from __future__ import annotations

from datetime import timedelta

import sqlalchemy as sa

from aslms.domain.alerts import Alert, AlertStatus, NextDate, NextDateSource, ReviewStatus, Severity
from aslms.domain.cases import Case, CaseObjection, CaseStatus
from aslms.domain.events import Event
from aslms.domain.org import Channel
from aslms.domain.ownership import RecommendationStatus, ScoreBand
from aslms.domain.reference import AlertKind, EventType, RecordType, RefSequence
from aslms.domain.workflow import RequestStatus
from aslms.services import alert_rules as rules
from aslms.services import alerts
from aslms.services import ownership as own
from tests import samplefiles as sf
from tests.db import alerts_support as h
from tests.db import docs_support as ds
from tests.db.test_case_visibility import entry_with_codes
from tests.db.world import make_case

NOW = h.now_utc()
TODAY = rules.today_ist(NOW)


def d(n: int):
    return TODAY + timedelta(days=n)


def serial(s, record_type=RecordType.ALR.value) -> int:
    return int(
        s.scalar(
            sa.select(sa.func.coalesce(sa.func.sum(RefSequence.last_value), 0)).where(
                RefSequence.record_type == record_type
            )
        )
    )


# ------------------------------------------------------------------------------------------------ the window


def test_event_scan_window_and_idempotence(world):
    with world.Session() as s:
        case = make_case(s)
        h.claim(s, world, "edu_admin", case)
        h.event(  # before the first run's overlap: never back-filled
            s,
            case,
            EventType.ORDER_STORED,
            {"cnr": case.cnr, "order_no": "old", "order_date": d(-1), "document_id": None},
            created_at=h.now_utc() - timedelta(hours=2),
        )
        h.order_stored_event(s, case, order_no="new", order_date=d(-1))
        s.commit()
        t1 = h.now_utc()
        c1 = alerts.scan_events(s, now=t1)
        s.commit()
        assert c1["events_read"] == 1 and c1["alerts_new"] == 1 and c1["skipped_old"] == 0
        assert len(h.alerts_of(s, case)) == 1
        # an event that committed "late", inside the overlap of the first run, is processed by the next run
        h.event(
            s,
            case,
            EventType.ORDER_STORED,
            {"cnr": case.cnr, "order_no": "late", "order_date": d(-2), "document_id": None},
            created_at=t1 - timedelta(minutes=5),
        )
        s.commit()
        c2 = alerts.scan_events(s, now=t1 + timedelta(minutes=10))
        s.commit()
        assert c2["events_read"] == 2 and c2["alerts_new"] == 1 and c2["alerts_upgraded"] == 0
        assert c2["window_from"] == (t1 - timedelta(minutes=30)).isoformat()
        assert {a.dedupe_key for a in h.alerts_of(s, case)} == {
            f"new_order:{case.id}:new:{d(-1)}",
            f"new_order:{case.id}:late:{d(-2)}",
        }
        # a third run inside the overlap again: nothing new, no serial burnt
        before = serial(s)
        c3 = alerts.scan_events(s, now=t1 + timedelta(minutes=11))
        s.commit()
        assert c3["alerts_new"] == 0 and serial(s) == before
        # each new alert left one alert_raised event and one in-app notification per recipient
        raised = s.scalars(
            sa.select(Event).where(Event.case_id == case.id, Event.type == EventType.ALERT_RAISED)
        ).all()
        assert len(raised) == 2 and raised[0].payload["office_code"] == "EDU"
        for a in h.alerts_of(s, case):
            assert h.recipient_emails(s, a) == {"admin.edu@example.org", "head.edu@example.org"}


# ------------------------------------------------------------------------------------------------ new order


def test_new_order_only_for_owned_cases_with_recent_orders(world):
    with world.Session() as s:
        owned = make_case(s)
        h.claim(s, world, "edu_admin", owned, officer_user_id=world.users["edu_off1"].id)
        unowned = make_case(s)
        h.order_stored_event(s, owned, order_no="1", order_date=d(-3))
        h.order_stored_event(s, owned, order_no="2", order_date=d(-15))  # 2025-style old order
        h.order_stored_event(s, unowned, order_no="1", order_date=d(-1))
        s.commit()
        c = alerts.scan_events(s, now=h.now_utc())
        s.commit()
        # the claim with an officer also emitted `allotted` (an ownership alert); the orders: one new
        assert c["alerts_new"] == 2 and c["skipped_old"] == 1 and c["skipped_unowned"] == 1
        (a,) = h.alerts_of(s, owned, AlertKind.NEW_ORDER)
        assert a.kind == AlertKind.NEW_ORDER and a.severity == Severity.HIGH and a.status == AlertStatus.OPEN
        assert a.ref_no.startswith("ASLMS/GOA/ALR/") and a.data["order_no"] == "1"
        assert "New order of" in a.title and owned.case_no_text in a.title
        assert h.recipient_emails(s, a) == {"off1.edu@example.org"}
        assert h.alerts_of(s, unowned) == []


# ------------------------------------------------------------------------------------------------ next date / status


def test_next_date_changed_rules(world):
    with world.Session() as s:
        case = make_case(s)
        h.claim(s, world, "edu_admin", case)
        h.next_date_event(s, case, d(3), d(10))  # a change → alert
        h.next_date_event(s, case, None, d(12))  # a first date → none
        h.next_date_event(s, case, d(1), d(-2))  # new date in the past → none
        s.commit()
        c = alerts.scan_events(s, now=h.now_utc())
        s.commit()
        assert c["alerts_new"] == 1 and c["skipped_other"] == 1 and c["skipped_old"] == 1
        (a,) = h.alerts_of(s, case)
        assert a.kind == AlertKind.NEXT_DATE_CHANGED and a.severity == Severity.HIGH
        assert a.data == {"hearing_date": str(d(10)), "previous_date": str(d(3))}
        assert a.due_at == rules.hearing_due_at(d(10))


def test_status_changed_rules(world):
    with world.Session() as s:
        a_case = make_case(s)
        b_case = make_case(s, status=CaseStatus.DISPOSED)
        b_case.disposal_date = d(-2)
        old_case = make_case(s, status=CaseStatus.DISPOSED)
        old_case.disposal_date = d(-40)
        for c in (a_case, b_case, old_case):
            h.claim(s, world, "edu_admin", c)
        h.event(
            s, a_case, EventType.STATUS_CHANGED, {"cnr": a_case.cnr, "next_purpose": ["HEARING", "ORDERS"]}
        )
        h.event(s, b_case, EventType.CASE_DISPOSED, {"cnr": b_case.cnr, "status": ["pending", "disposed"]})
        h.event(
            s, old_case, EventType.CASE_DISPOSED, {"cnr": old_case.cnr, "status": ["pending", "disposed"]}
        )
        h.event(s, a_case, EventType.STATUS_CHANGED, {"cnr": a_case.cnr, "status": ["unknown", "pending"]})
        s.commit()
        c = alerts.scan_events(s, now=h.now_utc())
        s.commit()
        assert c["alerts_new"] == 2 and c["skipped_other"] == 1 and c["skipped_old"] == 1
        (b_alert,) = h.alerts_of(s, b_case)
        assert b_alert.kind == AlertKind.STATUS_CHANGED and b_alert.severity == Severity.HIGH
        assert b_alert.title.startswith("Case disposed on")
        (a_alert,) = h.alerts_of(s, a_case)
        assert a_alert.severity == Severity.NORMAL and a_alert.data["status"] == "pending"


# ------------------------------------------------------------------------------------------------ hearings


def test_hearing_alert_upgrade_and_expiry(world):
    with world.Session() as s:
        case = make_case(s, next_hearing=d(3))
        h.claim(s, world, "edu_admin", case, officer_user_id=world.users["edu_off1"].id)
        s.commit()
        c = alerts.sweep_dates(s, now=NOW)
        s.commit()
        assert c["alerts_new"] == 1 and c["hearings_seen"] == 1
        (a,) = h.alerts_of(s, case)
        assert a.kind == AlertKind.HEARING_DUE and a.severity == Severity.HIGH
        assert a.due_at == rules.hearing_due_at(d(3)) and a.data["source"] == "current_status"
        assert len(h.notifications_of(s, a, Channel.IN_APP)) == 1
        assert h.notifications_of(s, a, Channel.EMAIL) == []  # high: digest only by default
        # 46 hours before the sitting: the same alert, upgraded, notified again (now by e-mail too)
        later = a.due_at - timedelta(hours=46)
        c2 = alerts.sweep_dates(s, now=later)
        s.commit()
        s.refresh(a)
        assert c2["alerts_upgraded"] == 1 and c2["alerts_new"] == 0
        assert a.severity == Severity.CRITICAL and len(h.alerts_of(s, case)) == 1
        in_app = h.notifications_of(s, a, Channel.IN_APP)
        assert [n.severity for n in in_app] == [Severity.HIGH, Severity.CRITICAL]
        assert len(h.notifications_of(s, a, Channel.EMAIL)) == 1
        # a third sweep at the same severity changes nothing
        assert alerts.sweep_dates(s, now=later + timedelta(hours=1))["alerts_upgraded"] == 0
        s.commit()
        # the court moves the date: the old alert expires, a new one is raised for the new date
        s.get(Case, case.id).next_hearing_date = d(5)
        s.commit()
        c3 = alerts.sweep_dates(s, now=NOW)
        s.commit()
        s.refresh(a)
        assert c3["closed_hearing"] == 1 and c3["alerts_new"] == 1
        assert a.status == AlertStatus.EXPIRED and a.data["closed_reason"] == "date_changed" and a.closed_at
        new = [x for x in h.alerts_of(s, case) if x.id != a.id]
        assert len(new) == 1 and new[0].data["hearing_date"] == str(d(5))
        # twelve hours after the sitting the alert expires as passed
        c4 = alerts.sweep_dates(s, now=new[0].due_at + timedelta(hours=13))
        s.commit()
        s.refresh(new[0])
        assert c4["closed_hearing"] == 1 and new[0].data["closed_reason"] == "passed"


def test_hearing_from_cause_list_and_manual_next_date(world):
    with world.Session() as s:
        listed = make_case(s)
        h.claim(s, world, "edu_admin", listed)
        entry_with_codes(s, listed, ["SC, EDU"], list_date=d(1))
        manual = make_case(s)
        h.claim(s, world, "edu_admin", manual)
        s.add(
            NextDate(
                case_id=manual.id,
                next_date=d(2),
                source=NextDateSource.MANUAL,
                review_status=ReviewStatus.NOT_NEEDED,
            )
        )
        pending_review = make_case(s)
        h.claim(s, world, "edu_admin", pending_review)
        s.add(
            NextDate(
                case_id=pending_review.id,
                next_date=d(2),
                source=NextDateSource.ORDER_PERIOD,
                needs_review=True,
                review_status=ReviewStatus.PENDING,
            )
        )
        unowned = make_case(s)
        entry_with_codes(s, unowned, ["SC, EDU"], list_date=d(1))
        s.commit()
        c = alerts.sweep_dates(s, now=NOW)
        s.commit()
        assert c["alerts_new"] == 2
        (a,) = h.alerts_of(s, listed)
        assert a.data["source"] == "causelist" and a.data["item_no"] and "cause list" in a.body
        assert a.severity == Severity.CRITICAL  # tomorrow is within 48 hours
        (m,) = h.alerts_of(s, manual)
        assert m.data["source"] == "next_date"
        assert h.alerts_of(s, pending_review) == [] and h.alerts_of(s, unowned) == []


# ------------------------------------------------------------------------------------------------ compliance / requests


def test_compliance_and_request_alerts(world):
    with world.Session() as s:
        case = make_case(s)
        h.claim(s, world, "edu_admin", case, officer_user_id=world.users["edu_off1"].id)
        s.add(CaseObjection(case_id=case.id, seq=1, scrutiny_date=d(-10), compliance_by_date=d(5)))
        far = make_case(s)
        h.claim(s, world, "edu_admin", far)
        s.add(CaseObjection(case_id=far.id, seq=1, scrutiny_date=d(-10), compliance_by_date=d(20)))
        edu, dse = world.office(s, "EDU"), world.office(s, "EDU-DSE")
        soon = h.request_to(s, case, from_office=edu, to_office=dse, due=d(2))
        overdue = h.request_to(
            s, case, from_office=edu, to_office=edu, to_user=world.user(s, "edu_off2"), due=d(-1)
        )
        later = h.request_to(s, case, from_office=edu, to_office=dse, due=d(9))
        s.commit()
        c = alerts.sweep_dates(s, now=NOW)
        s.commit()
        assert c["alerts_new"] == 3
        comp = h.alerts_of(s, case, AlertKind.COMPLIANCE_DUE)
        assert len(comp) == 1 and comp[0].severity == Severity.HIGH
        assert comp[0].dedupe_key == f"compliance_due:{case.id}:{d(-10)}"
        assert h.alerts_of(s, far) == []
        reqs = {a.data["request_id"]: a for a in h.alerts_of(s, case, AlertKind.REQUEST_DUE)}
        assert set(reqs) == {str(soon.id), str(overdue.id)} and str(later.id) not in reqs
        assert reqs[str(soon.id)].severity == Severity.HIGH
        assert h.recipient_emails(s, reqs[str(soon.id)]) == {"user.dse@example.org"}
        assert reqs[str(overdue.id)].severity == Severity.CRITICAL
        assert reqs[str(overdue.id)].title.startswith("Request overdue since")
        assert h.recipient_emails(s, reqs[str(overdue.id)]) == {"off2.edu@example.org"}
        assert "report please" not in (reqs[str(soon.id)].body or "")  # the subject is not repeated
        # two days before the compliance date it becomes critical; the answered request's alert is done
        soon.status = RequestStatus.ANSWERED
        s.commit()
        c2 = alerts.sweep_dates(s, now=NOW + timedelta(days=3))
        s.commit()
        s.refresh(comp[0])
        assert comp[0].severity == Severity.CRITICAL and c2["closed_request"] == 1
        done = s.get(Alert, reqs[str(soon.id)].id)
        assert done.status == AlertStatus.DONE and done.data["closed_reason"] == "request_answered"
        # 31 days after the compliance date the alert expires
        c3 = alerts.sweep_dates(s, now=NOW + timedelta(days=5 + 31))
        s.commit()
        s.refresh(comp[0])
        assert c3["closed_compliance"] == 1 and comp[0].status == AlertStatus.EXPIRED


# ------------------------------------------------------------------------------------------------ recommendations


def test_recommendation_alerts_strong_matches_only(world):
    with world.Session() as s:
        strong = make_case(s, next_hearing=d(4))
        medium = make_case(s)
        disposed = make_case(s, status=CaseStatus.DISPOSED)
        r1 = h.recommend(s, world, strong, "EDU")
        r2 = h.recommend(s, world, medium, "EDU", score=0.6, band=ScoreBand.MEDIUM)
        r3 = h.recommend(s, world, disposed, "EDU")
        for case, rec in ((strong, r1), (medium, r2), (disposed, r3)):
            h.event(
                s,
                case,
                EventType.RECOMMENDATION_MADE,
                {
                    "recommendation_id": str(rec.id),
                    "office_code": "EDU",
                    "score": float(rec.score),
                    "band": rec.band.value,
                },
                scoped=True,
            )
        s.commit()
        c = alerts.scan_events(s, now=h.now_utc())
        s.commit()
        assert c["alerts_new"] == 1 and c["skipped_other"] == 2
        (a,) = h.alerts_of(s, strong)
        assert a.kind == AlertKind.RECOMMENDATION and a.severity == Severity.HIGH  # hearing within 7 days
        assert a.office_id == world.offices["EDU"].id
        # only the department's cases.claim holders (dept admin, dept head), not its officers
        assert h.recipient_emails(s, a) == {"admin.edu@example.org", "head.edu@example.org"}
        assert h.alerts_of(s, medium) == [] and h.alerts_of(s, disposed) == []
        # claimed afterwards → the sweep closes the alert as done
        h.claim(s, world, "edu_admin", strong)
        s.commit()
        assert s.get(type(r1), r1.id).status == RecommendationStatus.CLAIMED
        c2 = alerts.sweep_dates(s, now=NOW)
        s.commit()
        s.refresh(a)
        assert c2["closed_recommendation"] == 1
        assert a.status == AlertStatus.DONE and a.data["closed_reason"] == "recommendation_claimed"


# ------------------------------------------------------------------------------------------------ ownership


def test_ownership_alerts(world):
    with world.Session() as s:
        case = make_case(s)
        h.claim(s, world, "edu_admin", case)
        s.commit()
        alerts.scan_events(s, now=h.now_utc())  # the claim itself raises nothing
        s.commit()
        assert h.alerts_of(s, case) == []
        h.allot(s, world, "edu_admin", case, officer_user_id=world.users["edu_off1"].id)
        s.commit()
        alerts.scan_events(s, now=h.now_utc())
        s.commit()
        (allotted,) = h.alerts_of(s, case)
        assert allotted.kind == AlertKind.OWNERSHIP and allotted.data["event"] == "allotted"
        assert allotted.title.startswith("Case allotted") and allotted.severity == Severity.NORMAL
        assert h.recipient_emails(s, allotted) == {"off1.edu@example.org"}
        # take-over by off2: the previous officer is told, the taker is not
        actor, off2 = world.actor(s, "edu_off2")
        own.take_over(s, actor, off2, case, reason="leave")
        s.commit()
        alerts.scan_events(s, now=h.now_utc())
        s.commit()
        taken = [a for a in h.alerts_of(s, case) if a.data.get("event") == "case_taken_over"]
        assert len(taken) == 1 and h.recipient_emails(s, taken[0]) == {"off1.edu@example.org"}
        assert "Edu Off2" in taken[0].title
        # a transfer request goes to the receiving department's deciders
        actor, admin = world.actor(s, "edu_admin")
        own.request_transfer(s, actor, admin, case, to_office_code="HEALTH", reason="theirs")
        s.commit()
        alerts.scan_events(s, now=h.now_utc())
        s.commit()
        (req,) = [a for a in h.alerts_of(s, case) if a.data.get("event") == "transfer_requested"]
        assert req.severity == Severity.HIGH and req.office_id == world.offices["HEALTH"].id
        assert h.recipient_emails(s, req) == {"admin.health@example.org"}
        # a re-run raises nothing new
        assert alerts.scan_events(s, now=h.now_utc())["alerts_new"] == 0


# ------------------------------------------------------------------------------------------------ documents


def test_new_document_alert_respects_document_visibility(world, tmp_path):
    api = ds.make_api(world, tmp_path)
    with world.Session() as s:
        case = make_case(s)
        h.claim(s, world, "edu_admin", case, unit_code="EDU-DSE", officer_user_id=world.users["edu_off1"].id)
        s.commit()
        case_id = str(case.id)
    dse = ds.login(api, "dse_user")
    assert (
        ds.upload(
            api,
            dse,
            case_id,
            sf.text_pdf(["Private memo"]),
            visibility="private_to_office",
            doc_type="legal_opinion",
            description="Opinion on the matter",
        ).status_code
        == 201
    )
    assert (
        ds.upload(
            api,
            dse,
            case_id,
            sf.text_pdf(["Shared filing"]),
            visibility="case_scope",
            description="Affidavit as filed",
            doc_type="affidavit",
        ).status_code
        == 201
    )
    with world.Session() as s:
        c = alerts.scan_events(s, now=h.now_utc())
        s.commit()
        assert c["alerts_new"] == 3 and c["alerts_without_recipients"] == 1  # + the allotment notice
        private, shared = h.alerts_of(s, s.get(Case, case_id), AlertKind.NEW_DOCUMENT)
        assert private.kind == AlertKind.NEW_DOCUMENT and h.recipient_emails(s, private) == set()
        assert h.recipient_emails(s, shared) == {"off1.edu@example.org"}  # the uploader is never notified
        assert "Opinion on the matter" not in private.title + (private.body or "")
        assert "Affidavit as filed" not in shared.title + (shared.body or "")
        assert "Affidavit" in shared.title


# ------------------------------------------------------------------------------------------------ aged


def test_informational_alerts_expire_after_fourteen_days(world):
    with world.Session() as s:
        case = make_case(s)
        h.claim(s, world, "edu_admin", case)
        h.order_stored_event(s, case, order_no="1", order_date=d(-1))
        s.commit()
        alerts.scan_events(s, now=h.now_utc())
        s.commit()
        (a,) = h.alerts_of(s, case)
        assert alerts.sweep_dates(s, now=NOW + timedelta(days=13))["closed_info"] == 0
        c = alerts.sweep_dates(s, now=NOW + timedelta(days=15))
        s.commit()
        s.refresh(a)
        assert c["closed_info"] == 1 and a.status == AlertStatus.EXPIRED and a.data["closed_reason"] == "aged"
