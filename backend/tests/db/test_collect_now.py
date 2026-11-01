"""Collect Now carried out at once (design `data-collection-redesign`, decisions 22-33; round 3) through the API: One
Case (details unless fresh, then every missing order PDF, at priority 3), Several Cases and All Cases Listed on a Day
(bulk at priority 5, one at a time), the checks that write nothing, Stop, the requests with their live progress, the
existing buttons at the "now" priority, and the court search refusal naming a bulk request."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
import sqlalchemy as sa

from aslms.core.config import Settings
from aslms.domain.cases import Case
from aslms.domain.causelists import Causelist, CauselistEntry, EntrySource, ListSource, ListType
from aslms.domain.courts import Court
from aslms.domain.documents import DownloadStatus, Order, OrderKind
from aslms.domain.events import AuditLog
from aslms.domain.ops import FetchKind, FetchLane, FetchQueueItem, FetchStatus, NapixCallLog
from aslms.services import case_dedupe, collect, court_search, queue
from aslms.services.audit import Actor
from aslms.services.court_search import CourtSearchUnavailable
from aslms.services.load_policy import NOW_BULK, NOW_ONE
from aslms.services.refno import allocate_case_ref_no
from aslms.services.reporting_common import today_ist
from tests.db import docs_support as ds
from tests.db.world import add_listing, make_case


@pytest.fixture()
def api(world, tmp_path):
    client = ds.make_api(world, tmp_path)
    yield client
    client.__exit__(None, None, None)


def _err(r) -> dict:
    return r.json()["detail"]


def _audits(world, action: str) -> list[AuditLog]:
    with world.Session() as s:
        return list(
            s.scalars(sa.select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.created_at))
        )


def _row(world, kind: FetchKind, ref: str) -> FetchQueueItem | None:
    with world.Session() as s:
        return s.scalar(
            sa.select(FetchQueueItem).where(FetchQueueItem.kind == kind, FetchQueueItem.ref == ref)
        )


def _rows(world) -> list[FetchQueueItem]:
    with world.Session() as s:
        return list(s.scalars(sa.select(FetchQueueItem).order_by(FetchQueueItem.ref)).all())


def _orders(s, case: Case, n: int, *, not_available: int = 0) -> list[Order]:
    """`n` orders of the case without a stored PDF; the first `not_available` marked not available at the court."""
    out = []
    for i in range(n):
        o = Order(
            case_id=case.id,
            order_no=str(i + 1),
            order_date=date(2025, 1, 6) + timedelta(days=i),
            kind=OrderKind.INTERIM,
            download_status=DownloadStatus.NOT_AVAILABLE if i < not_available else DownloadStatus.PENDING,
        )
        s.add(o)
        out.append(o)
    s.flush()
    return out


def _held(s, cnr: str | None = None, *, age: timedelta = timedelta(days=3), **kw) -> Case:
    case = make_case(s, cnr=cnr, **kw)
    case.last_full_refresh_at = datetime.now(UTC) - age
    s.flush()
    return case


# ------------------------------------------------------------------------------------------------ One Case


def test_collect_cases_queues_dossier_and_pdfs_skipping_fresh_dossier(api, world):
    with world.Session() as s:
        old = _held(s, "GAHC010000012025")
        _orders(s, old, 2)
        fresh = _held(s, "GAHC010000022025", age=timedelta(minutes=3))
        _orders(s, fresh, 3, not_available=1)
        old_ref, fresh_ref = old.ref_no, fresh.ref_no
        root_id = world.user(s, "root").id
        s.commit()
    h = ds.login(api, "root")
    r = api.post("/admin/data-load/collect", json={"kind": "cases", "refs": [old_ref, fresh_ref]}, headers=h)
    assert r.status_code == 202, r.text
    out = r.json()
    assert out["kind"] == "cases" and out["priority"] == NOW_ONE and out["to_fetch"] == 2
    assert out["queued"] == 1 and out["already_waiting"] == 0 and out["left_out"] == []
    dossier = _row(world, FetchKind.DOSSIER, "GAHC010000012025")
    assert (dossier.priority, dossier.lane, dossier.requested_by, dossier.status) == (
        NOW_ONE,
        FetchLane.REQUEST,
        root_id,
        FetchStatus.PENDING,
    )
    assert _row(world, FetchKind.DOSSIER, "GAHC010000022025") is None  # details fetched minutes ago
    pdfs = [r for r in _rows(world) if r.kind == FetchKind.ORDER_PDF]
    assert {r.ref.split("|")[0] for r in pdfs} == {"GAHC010000022025"}
    assert len(pdfs) == 2  # the order not available at the court is not asked again
    assert {(p.priority, p.lane, p.requested_by) for p in pdfs} == {(NOW_ONE, FetchLane.REQUEST, root_id)}
    # the progress panel: the dossier waits, the fresh case's details are done and its PDFs wait
    d = api.get(f"/admin/data-load/requests/{out['request_id']}", headers=h).json()
    assert d["kind"] == "cases" and not d["finished"] and not d["bulk"]
    assert d["counts"]["waiting"] == 3 and d["steps"]["details"]["waiting"] == 1
    results = {x["case"]["cnr"]: x for x in d["results"]}
    assert results["GAHC010000022025"]["details"] == "done"
    assert results["GAHC010000022025"]["orders"] == {
        "total": 3,
        "stored": 0,
        "not_available": 1,
        "failed": 0,
        "waiting": 2,
        "retry_at": None,
    }
    assert d["steps"]["orders"]["total"] == 5 and d["steps"]["orders"]["not_available"] == 1
    audit = _audits(world, collect.COLLECT_ACTION)[-1]
    assert audit.after["refs"] == [{"kind": "dossier", "ref": "GAHC010000012025"}]
    assert audit.after["fresh"] == ["GAHC010000022025"]


@pytest.mark.parametrize("priority", [41, 50])
def test_fresh_case_never_waits_on_a_dossier_row_left_by_other_work(api, world, priority):
    """A fresh case's dossier row left pending by the load (41-46) or the weekly sweep (50) is not the request's item:
    its details read Done and the request finishes once its order PDFs are stored."""
    cnr = "GAHC010000032025"
    with world.Session() as s:
        fresh = _held(s, cnr, age=timedelta(minutes=2))
        _orders(s, fresh, 1)
        fresh_ref = fresh.ref_no
        queue.enqueue(s, FetchKind.DOSSIER, cnr, priority, lane=FetchLane.LOAD)
        s.commit()
    h = ds.login(api, "root")
    r = api.post("/admin/data-load/collect", json={"kind": "cases", "refs": [fresh_ref]}, headers=h)
    assert r.status_code == 202, r.text
    rid = r.json()["request_id"]
    assert _row(world, FetchKind.DOSSIER, cnr).priority == priority  # the other work's row is left alone
    d = api.get(f"/admin/data-load/requests/{rid}", headers=h).json()
    assert d["cases"] == 1 and d["ref"] == cnr
    assert d["steps"]["details"] == {s: 0 for s in collect.ITEM_STATES}
    assert [i["kind"] for i in d["items"]] == ["order_pdf"] and not d["finished"]
    assert d["results"][0]["details"] == "done" and d["results"][0]["orders"]["waiting"] == 1
    # the order PDF is stored: the request is finished though the dossier row still waits for its own work
    with world.Session() as s:
        s.execute(
            sa.update(FetchQueueItem)
            .where(FetchQueueItem.kind == FetchKind.ORDER_PDF)
            .values(status=FetchStatus.DONE, finished_at=datetime.now(UTC))
        )
        s.commit()
    assert _row(world, FetchKind.DOSSIER, cnr).status == FetchStatus.PENDING
    d = api.get(f"/admin/data-load/requests/{rid}", headers=h).json()
    assert d["finished"] and d["results"][0]["details"] == "done"
    listed = api.get("/admin/data-load/requests", headers=h).json()
    assert listed["active"] == 0


def test_collect_cases_caps_at_20(api, world):
    h = ds.login(api, "root")
    refs = [f"GAHC0100000{i:05d}" for i in range(21)]
    r = api.post("/admin/data-load/collect", json={"kind": "cases", "refs": refs}, headers=h)
    assert r.status_code == 400 and _err(r)["code"] == "too_many"
    r = api.post("/admin/data-load/collect", json={"kind": "cases", "refs": []}, headers=h)
    assert r.status_code == 400 and _err(r)["code"] == "bad_input"
    with world.Session() as s:
        court = s.scalar(sa.select(Court).where(Court.est_code == "GAHC01"))
        bare = Case(court_id=court.id, ref_no=allocate_case_ref_no(s, court), is_provisional=True)
        s.add(bare)
        s.flush()
        bare_ref = bare.ref_no
        s.commit()
    r = api.post(
        "/admin/data-load/collect", json={"kind": "cases", "refs": ["GAHC019999992025", bare_ref]}, headers=h
    )
    assert r.status_code == 400 and _err(r)["code"] == "nothing_to_fetch"
    reasons = {x["ref"]: x["reason"] for x in _err(r)["left_out"]}
    assert reasons == {"GAHC019999992025": "not_held", bare_ref: "no_reference"}
    assert _audits(world, collect.COLLECT_ACTION) == [] and _rows(world) == []
    # twenty cases are accepted
    with world.Session() as s:
        refs = [make_case(s).ref_no for _ in range(20)]
        s.commit()
    r = api.post("/admin/data-load/collect", json={"kind": "cases", "refs": refs}, headers=h)
    assert r.status_code == 202 and r.json()["to_fetch"] == 20


# ------------------------------------------------------------------------------------------------ Several Cases


def _merged(s, holder: Case) -> Case:
    court = s.scalar(sa.select(Court).where(Court.est_code == "GAHC01"))
    merged = Case(
        court_id=court.id,
        case_no_text=holder.case_no_text,
        ref_no=allocate_case_ref_no(s, court),
        is_provisional=True,
    )
    s.add(merged)
    s.flush()
    case_dedupe.merge_provisional(s, merged, holder, Actor.system("test"))
    return merged


def _list_world(world) -> dict[str, str]:
    with world.Session() as s:
        bare = make_case(s, cnr="GAHC010000112025", case_no="WP(C)/11/2025")
        held = _held(s, "GAHC010000122025", case_no="WP(C)/12/2025")
        make_case(s, cnr="GAHC010000132025", case_no="WA/13/2025")
        make_case(s, cnr="GAHC010000142025", case_no="CRL.A/14/2025")
        make_case(s, cnr="GAHC010000152025", case_no="CRL.A/14/2025")  # the same printed number twice
        holder = make_case(s, cnr="GAHC010000162025", case_no="WA/16/2025")
        merged = _merged(s, holder)
        refs = {"bare": bare.ref_no, "held": held.cnr, "merged": merged.ref_no, "holder": holder.ref_no}
        s.commit()
    return refs


def test_check_list_reads_cnr_reference_number_and_refuses_text(api, world):
    refs = _list_world(world)
    h = ds.login(api, "root")
    lines = [
        refs["bare"],
        refs["held"],
        "WA 13/2025",
        "WP(C) 999/2025",
        "CRL.A/14/2025",
        "hello world",
        "GAHC019999992025",
        refs["merged"],
        "  ",
        refs["bare"],  # repeated
    ]
    before = (len(_rows(world)), len(_audits(world, collect.COLLECT_ACTION)))
    r = api.post("/admin/data-load/collect/list/check", json={"lines": lines}, headers=h)
    assert r.status_code == 200, r.text
    out = r.json()
    states = {x["line"]: x["state"] for x in out["items"]}
    assert states == {
        refs["bare"]: "will_fetch",
        refs["held"]: "already_has_details",
        "WA 13/2025": "will_fetch",
        "WP(C) 999/2025": "not_held",
        "CRL.A/14/2025": "several_match",
        "hello world": "not_a_reference",
        "GAHC019999992025": "will_fetch",
        refs["merged"]: "merged",
    }
    by_line = {x["line"]: x for x in out["items"]}
    assert (
        by_line["GAHC019999992025"]["case"] is None
        and by_line["GAHC019999992025"]["cnr"] == "GAHC019999992025"
    )
    assert by_line[refs["merged"]]["merged_into_ref_no"] == refs["holder"]
    assert by_line[refs["held"]]["details_fetched_at"] is not None
    assert by_line["CRL.A/14/2025"]["matches"] == 2
    assert out["to_fetch"] == 3 and out["counts"]["will_fetch"] == 3
    assert out["plan"]["calls"] >= 3 and out["bulk"] is None
    r = api.post("/admin/data-load/collect/list/check", json={"lines": lines, "force": True}, headers=h)
    assert r.json()["to_fetch"] == 4
    assert (len(_rows(world)), len(_audits(world, collect.COLLECT_ACTION))) == before  # writes nothing


def test_collect_list_unknown_cnr_queued_unknown_number_not_held(api, world):
    refs = _list_world(world)
    h = ds.login(api, "root")
    lines = [refs["bare"], refs["held"], "GAHC019999992025", "WP(C) 999/2025"]
    r = api.post("/admin/data-load/collect", json={"kind": "list", "lines": lines}, headers=h)
    assert r.status_code == 202, r.text
    out = r.json()
    assert out["priority"] == NOW_BULK and out["to_fetch"] == 2 and out["queued"] == 2
    assert {x["ref"]: x["reason"] for x in out["left_out"]} == {
        refs["held"]: "already_has_details",
        "WP(C) 999/2025": "not_held",
    }
    new = _row(world, FetchKind.DOSSIER, "GAHC019999992025")
    assert (new.priority, new.lane) == (
        NOW_BULK,
        FetchLane.REQUEST,
    )  # the court's own identifier, not a guess
    assert _row(world, FetchKind.DOSSIER, refs["held"]) is None
    with world.Session() as s:
        assert s.scalar(sa.select(Case).where(Case.cnr == "GAHC019999992025")) is None  # no case made up
    # with force the case with details is fetched too (after the first bulk request is stopped)
    api.post(f"/admin/data-load/requests/{out['request_id']}/stop", headers=h)
    r = api.post("/admin/data-load/collect", json={"kind": "list", "lines": lines, "force": True}, headers=h)
    assert r.status_code == 202 and r.json()["to_fetch"] == 3
    assert _row(world, FetchKind.DOSSIER, refs["held"]).priority == NOW_BULK


def test_collect_list_caps_at_200(api, world):
    """More than 200 lines are refused by the request model, before any line is read or de-duplicated (row 174
    review): 201 distinct lines, and 400 lines that are only two cases repeated."""
    h = ds.login(api, "root")
    lines = [f"GAHC0100{i:08d}" for i in range(201)]
    repeated = ["GAHC010000000001", "GAHC010000000002"] * 200
    for body_lines in (lines, repeated):
        for path, body in (
            ("/admin/data-load/collect/list/check", {"lines": body_lines}),
            ("/admin/data-load/collect", {"kind": "list", "lines": body_lines}),
        ):
            r = api.post(path, json=body, headers=h)
            assert r.status_code == 422, (path, r.text)
            assert r.json()["detail"][0]["type"] == "too_long"
    assert _rows(world) == [] and _audits(world, collect.COLLECT_ACTION) == []
    # the service keeps its own limit for other callers (the CLI)
    with world.Session() as s, pytest.raises(collect.CollectInputError) as too_many:
        collect.check_list(s, Settings(_env_file=None), lines)
    assert too_many.value.code == "too_many"
    r = api.post("/admin/data-load/collect/list/check", json={"lines": lines[:200]}, headers=h)
    assert r.status_code == 200 and r.json()["to_fetch"] == 200
    assert api.post("/admin/data-load/collect/list/check", json={"lines": []}, headers=h).status_code == 422


# ------------------------------------------------------------------------------------------------ a day


def _day_world(world, d: date) -> dict[str, Case]:
    with world.Session() as s:
        cases = {
            "never": make_case(s, cnr="GAHC010000212025"),
            "old": _held(s, "GAHC010000222025", age=timedelta(days=2)),
            "recent": _held(s, "GAHC010000232025", age=timedelta(hours=2)),
            "provisional": make_case(s, cnr="", case_no="WA/24/2025"),
        }
        cases["provisional"].cnr = None
        court = s.scalar(sa.select(Court).where(Court.est_code == "GAHC01"))
        bare = Case(court_id=court.id, ref_no=allocate_case_ref_no(s, court), is_provisional=True)
        s.add(bare)
        s.flush()
        cases["bare"] = bare
        for c in cases.values():
            add_listing(s, c, d)
        add_listing(s, cases["never"], d, court_no="5")  # listed twice: counted once
        s.commit()
        return cases


def test_check_day_counts_and_writes_nothing(api, world):
    d = today_ist() - timedelta(days=1)
    _day_world(world, d)
    h = ds.login(api, "root")
    r = api.get("/admin/data-load/collect/day", params={"date": d.isoformat()}, headers=h)
    assert r.status_code == 200, r.text
    out = r.json()
    assert (out["lists"], out["cases_listed"], out["with_details"], out["never_fetched"]) == (1, 5, 2, 3)
    assert (out["refreshed_recently"], out["no_reference"], out["to_fetch"]) == (1, 1, 2)
    assert out["details_from"] < out["details_to"]
    r = api.get("/admin/data-load/collect/day", params={"date": d.isoformat(), "scope": "all"}, headers=h)
    assert r.json()["to_fetch"] == 3  # never fetched (2) and the case refreshed two days ago
    assert _rows(world) == [] and _audits(world, collect.COLLECT_ACTION) == []


def test_collect_day_never_and_all_with_the_6_hour_rule(api, world):
    d = today_ist()
    cases = _day_world(world, d)
    h = ds.login(api, "root")
    r = api.post("/admin/data-load/collect", json={"kind": "day", "date": d.isoformat()}, headers=h)
    assert r.status_code == 202, r.text
    out = r.json()
    assert out["priority"] == NOW_BULK and out["to_fetch"] == 2
    queued = {r.ref for r in _rows(world)}
    assert queued == {"GAHC010000212025", "GAHC01|WA/24/2025"}
    reasons = {x["reason"]: x["count"] for x in out["left_out"]}
    assert reasons == {"already_has_details": 2, "no_reference": 1}
    api.post(f"/admin/data-load/requests/{out['request_id']}/stop", headers=h)
    r = api.post(
        "/admin/data-load/collect", json={"kind": "day", "date": d.isoformat(), "scope": "all"}, headers=h
    )
    assert r.status_code == 202, r.text
    assert r.json()["to_fetch"] == 3 and r.json()["already_waiting"] == 2
    queued = {r.ref for r in _rows(world)}
    assert cases["old"].cnr in queued and cases["recent"].cnr not in queued  # refreshed 2 hours ago: left out
    (audit, second) = _audits(world, collect.COLLECT_ACTION)
    assert second.after["scope"] == "all" and second.after["date"] == d.isoformat()


def test_collect_day_uses_current_lists_only(api, world):
    d = today_ist() - timedelta(days=2)
    with world.Session() as s:
        listed = make_case(s, cnr="GAHC010000312025")
        dropped = make_case(s, cnr="GAHC010000322025")
        court = s.scalar(sa.select(Court).where(Court.est_code == "GAHC01"))
        old = Causelist(
            court_id=court.id,
            list_date=d,
            list_type=ListType.DAILY,
            source=ListSource.NAPIX,
            superseded_at=datetime.now(UTC),
        )
        s.add(old)
        s.flush()
        s.add(
            CauselistEntry(
                causelist_id=old.id,
                sr_no=1,
                cnr=dropped.cnr,
                case_id=dropped.id,
                source=EntrySource.PDF_PARSE,
            )
        )
        add_listing(s, listed, d)
        s.commit()
    h = ds.login(api, "root")
    r = api.get("/admin/data-load/collect/day", params={"date": d.isoformat()}, headers=h)
    assert (r.json()["lists"], r.json()["cases_listed"], r.json()["to_fetch"]) == (1, 1, 1)
    r = api.post("/admin/data-load/collect", json={"kind": "day", "date": d.isoformat()}, headers=h)
    assert {r.ref for r in _rows(world)} == {"GAHC010000312025"}


def test_collect_day_refuses_no_lists_future_and_over_2000(api, world, monkeypatch):
    h = ds.login(api, "root")
    future = (
        today_ist() + timedelta(days=2)
    ).isoformat()  # worked out when the test runs, so a run past midnight holds
    for params in ({"date": future}, {"date": (today_ist() - timedelta(days=9)).isoformat()}):
        r = api.get("/admin/data-load/collect/day", params=params, headers=h)
        assert r.status_code == 400
        r2 = api.post("/admin/data-load/collect", json={"kind": "day", **params}, headers=h)
        assert r2.status_code == 400 and _err(r2)["code"] == _err(r)["code"]
    assert _err(api.get("/admin/data-load/collect/day", params={"date": future}, headers=h))["code"] == (
        "date_in_future"
    )
    d = today_ist() - timedelta(days=9)
    assert _err(api.get("/admin/data-load/collect/day", params={"date": d.isoformat()}, headers=h))[
        "code"
    ] == ("no_lists")
    _day_world(world, d)
    monkeypatch.setattr(collect, "DAY_MAX", 1)
    r = api.get("/admin/data-load/collect/day", params={"date": d.isoformat()}, headers=h)
    assert r.status_code == 400 and _err(r)["code"] == "too_many"
    r = api.post("/admin/data-load/collect", json={"kind": "day", "date": d.isoformat()}, headers=h)
    assert r.status_code == 400 and _err(r)["code"] == "too_many"
    # a day whose cases all have details: nothing to fetch, nothing written
    monkeypatch.setattr(collect, "DAY_MAX", 2000)
    with world.Session() as s:
        s.execute(sa.text("UPDATE cases SET last_full_refresh_at = now() - interval '1 day'"))
        s.commit()
    r = api.get("/admin/data-load/collect/day", params={"date": d.isoformat()}, headers=h)
    assert r.status_code == 200 and r.json()["to_fetch"] == 0
    r = api.post("/admin/data-load/collect", json={"kind": "day", "date": d.isoformat()}, headers=h)
    assert r.status_code == 400 and _err(r)["code"] == "nothing_to_fetch"
    assert _audits(world, collect.COLLECT_ACTION) == []


# ------------------------------------------------------------------------------------------------ one at a time


def test_second_bulk_is_409_bulk_running_one_case_still_allowed(api, world):
    refs = _list_world(world)
    h = ds.login(api, "root")
    r = api.post("/admin/data-load/collect", json={"kind": "list", "lines": [refs["bare"]]}, headers=h)
    assert r.status_code == 202
    first = r.json()["request_id"]
    r = api.post("/admin/data-load/collect", json={"kind": "list", "lines": ["GAHC019999992025"]}, headers=h)
    assert r.status_code == 409 and _err(r)["code"] == "bulk_running"
    assert _err(r)["request_id"] == first and _err(r)["asked_by"] == "Root" and _err(r)["kind"] == "list"
    assert _err(r)["asked_at"]
    assert _row(world, FetchKind.DOSSIER, "GAHC019999992025") is None
    # one case goes first, always
    r = api.post("/admin/data-load/collect", json={"kind": "cases", "refs": ["GAHC010000132025"]}, headers=h)
    assert r.status_code == 202 and r.json()["priority"] == NOW_ONE
    # the overview and the checks name the bulk request
    ov = api.get("/admin/data-load/overview", headers=h).json()
    assert ov["bulk"]["request_id"] == first and ov["bulk"]["using_everything"]
    chk = api.post("/admin/data-load/collect/list/check", json={"lines": [refs["bare"]]}, headers=h).json()
    assert chk["bulk"]["request_id"] == first
    pulse = api.get("/admin/data-load/pulse", headers=h).json()
    assert pulse["requests_active"] == 2
    # once its rows are done the bulk request has finished and another may start
    with world.Session() as s:
        s.execute(sa.text("UPDATE fetch_queue SET status = 'done' WHERE priority = :p"), {"p": NOW_BULK})
        s.commit()
    assert api.get("/admin/data-load/overview", headers=h).json()["bulk"] is None
    r = api.post("/admin/data-load/collect", json={"kind": "list", "lines": ["GAHC019999992025"]}, headers=h)
    assert r.status_code == 202


def test_collect_writes_one_audit_row_with_refs(api, world):
    with world.Session() as s:
        a = make_case(s, cnr="GAHC010000412025")
        b = make_case(s, cnr="GAHC010000422025")
        refs = [a.ref_no, b.cnr]
        s.commit()
    h = ds.login(api, "root")
    r = api.post("/admin/data-load/collect", json={"kind": "cases", "refs": refs}, headers=h)
    (audit,) = _audits(world, collect.COLLECT_ACTION)
    assert audit.id == uuid.UUID(r.json()["request_id"])
    assert audit.actor_name == "Root" and audit.entity_type == "fetch_queue"
    assert (
        audit.after["kind"] == "cases" and audit.after["bulk"] is False and audit.after["priority"] == NOW_ONE
    )
    assert audit.after["refs"] == [
        {"kind": "dossier", "ref": "GAHC010000412025"},
        {"kind": "dossier", "ref": "GAHC010000422025"},
    ]
    assert audit.after["to_fetch"] == 2 and audit.after["queued"] == 2


def test_collect_needs_admin_data_load(api, world):
    refs = _list_world(world)
    day = (today_ist() - timedelta(days=1)).isoformat()
    for key in ("central_op", "oversight", "edu_off1"):
        h = ds.login(api, key)
        writes = [
            api.post("/admin/data-load/collect", json={"kind": "cases", "refs": [refs["bare"]]}, headers=h),
            api.post("/admin/data-load/collect", json={"kind": "list", "lines": [refs["bare"]]}, headers=h),
            api.post("/admin/data-load/collect/list/check", json={"lines": [refs["bare"]]}, headers=h),
            api.get("/admin/data-load/collect/day", params={"date": day}, headers=h),
            api.post(f"/admin/data-load/requests/{uuid.uuid4()}/stop", headers=h),
        ]
        assert [w.status_code for w in writes] == [403] * 5, key
        reads = api.get("/admin/data-load/requests", headers=h).status_code
        assert reads == (403 if key == "edu_off1" else 200), key
    assert _rows(world) == [] and _audits(world, collect.COLLECT_ACTION) == []
    assert api.get("/admin/data-load/requests").status_code == 401


# ------------------------------------------------------------------------------------------------ stop


def test_stop_moves_pending_bulk_rows_to_30_lets_running_rows_finish_and_audits(api, world):
    with world.Session() as s:
        cases = [make_case(s, cnr=f"GAHC0100005{i}2025") for i in range(3)]
        lines = [c.cnr for c in cases]
        s.commit()
    h = ds.login(api, "root")
    rid = api.post("/admin/data-load/collect", json={"kind": "list", "lines": lines}, headers=h).json()[
        "request_id"
    ]
    with world.Session() as s:
        s.execute(
            sa.text("UPDATE fetch_queue SET status = 'running', started_at = now() WHERE ref = :r"),
            {"r": lines[0]},
        )
        s.commit()
    r = api.post(f"/admin/data-load/requests/{rid}/stop", headers=h)
    assert r.status_code == 200, r.text
    assert r.json() == {"request_id": rid, "moved": 2}
    rows = {r.ref: r for r in _rows(world)}
    # the running row finishes its run, at the normal turn, so what it spawns does too (row 174 review)
    assert (rows[lines[0]].status, rows[lines[0]].priority) == (FetchStatus.RUNNING, 30)
    assert {(rows[c].status, rows[c].priority, rows[c].lane) for c in lines[1:]} == {
        (FetchStatus.PENDING, 30, FetchLane.REQUEST)
    }
    (audit,) = _audits(world, collect.STOP_ACTION)
    assert audit.after == {"request_id": rid, "moved": 2, "running": 1} and audit.entity_id == uuid.UUID(rid)
    d = api.get(f"/admin/data-load/requests/{rid}", headers=h).json()
    assert d["stopped"] and d["stopped_by"] == "Root" and not d["using_everything"]
    assert api.get("/admin/data-load/overview", headers=h).json()["bulk"] is None


def test_stop_needs_admin_data_load_and_a_running_bulk(api, world):
    refs = _list_world(world)
    h = ds.login(api, "root")
    one = api.post(
        "/admin/data-load/collect", json={"kind": "cases", "refs": [refs["bare"]]}, headers=h
    ).json()
    r = api.post(f"/admin/data-load/requests/{one['request_id']}/stop", headers=h)
    assert r.status_code == 409 and _err(r)["code"] == "not_running"
    bulk = api.post(
        "/admin/data-load/collect", json={"kind": "list", "lines": ["WA 13/2025"]}, headers=h
    ).json()
    r = api.post(f"/admin/data-load/requests/{bulk['request_id']}/stop", headers=ds.login(api, "central_op"))
    assert r.status_code == 403
    assert api.post(f"/admin/data-load/requests/{bulk['request_id']}/stop", headers=h).status_code == 200
    r = api.post(f"/admin/data-load/requests/{bulk['request_id']}/stop", headers=h)
    assert r.status_code == 409 and _err(r)["code"] == "not_running"
    r = api.post(f"/admin/data-load/requests/{uuid.uuid4()}/stop", headers=h)
    assert r.status_code == 404 and _err(r)["code"] == "not_found"
    # a finished bulk request is not running either
    other = api.post(
        "/admin/data-load/collect", json={"kind": "list", "lines": ["GAHC019999992025"]}, headers=h
    )
    with world.Session() as s:
        s.execute(sa.text("UPDATE fetch_queue SET status = 'done'"))
        s.commit()
    r = api.post(f"/admin/data-load/requests/{other.json()['request_id']}/stop", headers=h)
    assert r.status_code == 409 and _err(r)["code"] == "not_running"
    assert len(_audits(world, collect.STOP_ACTION)) == 1


# ------------------------------------------------------------------------------------------------ requests


def test_requests_list_states_and_spawned_order_pdfs(api, world):
    with world.Session() as s:
        case = _held(s, "GAHC010000612025")
        orders = _orders(s, case, 4)
        # an order PDF fetched long before the request is not one of its items
        s.add(
            FetchQueueItem(
                kind=FetchKind.ORDER_PDF,
                ref=f"{case.cnr}|{orders[3].order_no}|{orders[3].order_date.isoformat()}",
                status=FetchStatus.DONE,
                priority=40,
                lane=FetchLane.REQUEST,
            )
        )
        ref = case.ref_no
        s.commit()
    h = ds.login(api, "root")
    rid = api.post("/admin/data-load/collect", json={"kind": "cases", "refs": [ref]}, headers=h).json()[
        "request_id"
    ]
    # the worker fetches the dossier, which queues the missing order PDFs at the same priority with the request's id;
    # one is fetching, one failed and waits for its retry, one is stored
    with world.Session() as s:
        s.execute(
            sa.text("UPDATE fetch_queue SET status = 'done', finished_at = now() WHERE kind = 'dossier'")
        )
        for o in orders[:3]:
            queue.enqueue(
                s,
                FetchKind.ORDER_PDF,
                f"{case.cnr}|{o.order_no}|{o.order_date.isoformat()}",
                NOW_ONE,
                lane=FetchLane.REQUEST,
                request_ids=[rid],
            )
        s.flush()
        pdf = [
            r
            for r in s.scalars(
                sa.select(FetchQueueItem).where(FetchQueueItem.kind == FetchKind.ORDER_PDF)
            ).all()
        ]
        by_no = {r.ref.split("|")[1]: r for r in pdf}
        by_no["1"].status = FetchStatus.RUNNING
        by_no["2"].status, by_no["2"].not_before = FetchStatus.PENDING, datetime.now(UTC) + timedelta(hours=1)
        by_no["3"].status, by_no["3"].finished_at = FetchStatus.DONE, datetime.now(UTC)
        s.commit()
    out = api.get("/admin/data-load/requests", headers=h).json()
    (item,) = out["items"]
    assert item["request_id"] == rid and item["kind"] == "cases" and item["asked_by"] == "Root"
    assert item["counts"] == {
        "waiting": 0,
        "waiting_retry": 1,
        "fetching": 1,
        "done": 2,
        "not_found": 0,
        "failed": 0,
    }
    assert item["total"] == 4 and not item["finished"] and item["retry_at"] is not None
    assert out["active"] == 1 and out["bulk"] is None
    assert out["collector"]["now_waiting"] is False and out["window"]["limit_used_up"] is False
    d = api.get(f"/admin/data-load/requests/{rid}", params={"limit": 2}, headers=h).json()
    assert [i["kind"] for i in d["items"]] == ["dossier", "order_pdf"] and d["limit"] == 2
    page2 = api.get(f"/admin/data-load/requests/{rid}", params={"limit": 2, "offset": 2}, headers=h).json()
    assert len(page2["items"]) == 2
    assert {i["state"] for i in d["items"] + page2["items"]} == {"done", "fetching", "waiting_retry"}
    (res,) = d["results"]
    assert res["orders"]["waiting"] == 1 and res["orders"]["retry_at"] is not None
    assert api.get(f"/admin/data-load/requests/{uuid.uuid4()}", headers=h).status_code == 404


def test_request_finished_when_nothing_ready_or_running(api, world):
    with world.Session() as s:
        ref = make_case(s, cnr="GAHC010000712025").ref_no
        s.commit()
    h = ds.login(api, "root")
    rid = api.post("/admin/data-load/collect", json={"kind": "cases", "refs": [ref]}, headers=h).json()[
        "request_id"
    ]
    assert not api.get(f"/admin/data-load/requests/{rid}", headers=h).json()["finished"]
    with world.Session() as s:
        s.execute(sa.text("UPDATE fetch_queue SET not_before = now() + interval '1 hour', attempts = 1"))
        s.commit()
    d = api.get(f"/admin/data-load/requests/{rid}", headers=h).json()
    assert d["finished"] and d["counts"]["waiting_retry"] == 1  # waiting for a retry does not hold the result
    with world.Session() as s:
        s.execute(sa.text("UPDATE fetch_queue SET status = 'skipped', not_before = NULL"))
        s.commit()
    d = api.get(f"/admin/data-load/requests/{rid}", headers=h).json()
    assert d["finished"] and d["counts"]["not_found"] == 1


def test_requests_include_refetch_and_masters_rows(api, world):
    with world.Session() as s:
        case = make_case(s, cnr="GAHC010000812025")
        ref = case.ref_no
        s.commit()
    h = ds.login(api, "central_op")
    day = (today_ist() - timedelta(days=3)).isoformat()
    assert api.post("/admin/napix/refetch/day", json={"date": day}, headers=h).status_code == 202
    assert api.post("/admin/napix/sync-masters", json={}, headers=h).status_code == 202
    assert api.post("/admin/napix/refetch/case", json={"case": ref}, headers=h).status_code == 202
    hr = ds.login(api, "root")
    assert api.post("/admin/data-load/fetch-details", json={"cases": [ref]}, headers=hr).status_code == 200
    items = api.get("/admin/data-load/requests", headers=h).json()["items"]
    assert [i["kind"] for i in items] == ["details", "refetch_case", "masters", "refetch_day"]
    by_kind = {i["kind"]: i for i in items}
    assert by_kind["refetch_day"]["ref"] == day and by_kind["refetch_day"]["counts"]["waiting"] == 1
    assert by_kind["masters"]["asked_by"] == "Central Op"
    assert by_kind["details"]["total"] == 1  # the same dossier row
    (details,) = _audits(world, "data_load.details_requested")
    assert details.after["queue_refs"] == [{"kind": "dossier", "ref": "GAHC010000812025"}]


def test_refetch_and_sync_masters_queue_at_now_one(api, world):
    with world.Session() as s:
        case = _held(s, "GAHC010000912025")
        (order,) = _orders(s, case, 1)
        order.download_status = DownloadStatus.NOT_AVAILABLE
        ref, order_id = case.ref_no, str(order.id)
        s.commit()
    h = ds.login(api, "central_op")
    day = (today_ist() - timedelta(days=4)).isoformat()
    answers = [
        api.post("/admin/napix/refetch/day", json={"date": day}, headers=h),
        api.post("/admin/napix/sync-masters", json={}, headers=h),
        api.post("/admin/napix/refetch/case", json={"case": ref, "force": True}, headers=h),
        api.post("/admin/napix/refetch/order", json={"case": ref, "order_id": order_id}, headers=h),
    ]
    assert [a.status_code for a in answers] == [202] * 4, [a.text for a in answers]
    assert {(a.json()["priority"], a.json()["lane"]) for a in answers} == {(NOW_ONE, "request")}
    audits = _audits(world, "napix.refetch_requested") + _audits(world, "napix.masters_sync_requested")
    assert {str(a.id) for a in audits} == {a.json()["request_id"] for a in answers}
    assert {r.priority for r in _rows(world)} == {NOW_ONE}


def test_court_search_refusal_names_the_active_bulk_request(api, world):
    refs = _list_world(world)
    settings = Settings(_env_file=None, napix_search_floor=50)
    with world.Session() as s:
        s.add(
            NapixCallLog(
                api="hc-cnr-api/CNR",
                params_sha256="x" * 64,
                ok=True,
                rate_limit_remaining=20,
                called_at=datetime.now(UTC),
            )
        )
        s.commit()
    with world.Session() as s:
        user = world.user(s, "edu_off1")
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(Settings, "napix_configured", property(lambda self: True))
            with pytest.raises(CourtSearchUnavailable) as plain:
                court_search.guard(s, user, settings)
    assert plain.value.code == "napix_budget" and "data collection request" not in str(plain.value)
    h = ds.login(api, "root")
    assert (
        api.post(
            "/admin/data-load/collect", json={"kind": "list", "lines": [refs["bare"]]}, headers=h
        ).status_code
        == 202
    )
    with world.Session() as s:
        user = world.user(s, "edu_off1")
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(Settings, "napix_configured", property(lambda self: True))
            with pytest.raises(CourtSearchUnavailable) as named:
                court_search.guard(s, user, settings)
    assert named.value.code == "napix_budget"
    assert "in use by a data collection request" in str(named.value)


# ------------------------------------------------------------------------------------------------ after the request


def _run_now_rows(world, *, fail_first: bool = False) -> None:
    """The worker's "now" claim and the end of each row, as the runner does it (`queue.claim`, `complete`/`fail`)."""
    with world.Session() as s:
        first = True
        while (item := queue.claim(s, max_priority=NOW_BULK)) is not None:
            if fail_first and first:
                queue.fail(s, item, "court busy")
            else:
                queue.complete(s, item)
            first = False
        s.commit()


def test_later_system_requeue_drops_the_now_priority_and_keeps_the_request_finished(api, world):
    from aslms.services import tracking

    with world.Session() as s:
        cases = [make_case(s, cnr=f"GAHC0100008{i}2025") for i in range(3)]
        lines = [c.cnr for c in cases]
        s.commit()
    h = ds.login(api, "root")
    rid = api.post("/admin/data-load/collect", json={"kind": "list", "lines": lines}, headers=h).json()[
        "request_id"
    ]
    _run_now_rows(world)
    d = api.get(f"/admin/data-load/requests/{rid}", headers=h).json()
    assert d["finished"] and not d["using_everything"] and d["counts"]["done"] == 3
    # the weekly sweep re-queues the same dossiers: ordinary work at its own priority and lane, not "now" work
    with world.Session() as s:
        assert tracking.enqueue_weekly_dossier_sweep(s) >= 3
        assert not queue.has_now(s)
        s.commit()
    rows = {r.ref: r for r in _rows(world) if r.kind == FetchKind.DOSSIER}
    assert {(rows[c].status, rows[c].priority, rows[c].lane, rows[c].requested_by) for c in lines} == {
        (FetchStatus.PENDING, queue.PRIORITY["dossier_refetch"], FetchLane.DAILY, None)
    }
    # and the request stays finished: the re-queued rows are later work, done for this request
    d = api.get(f"/admin/data-load/requests/{rid}", headers=h).json()
    assert d["finished"] and not d["using_everything"] and d["counts"]["done"] == 3
    assert {i["state"] for i in d["items"]} == {"done"}
    assert api.get("/admin/data-load/overview", headers=h).json()["bulk"] is None
    with world.Session() as s:
        s.execute(sa.text("UPDATE fetch_queue SET status = 'running', started_at = now(), attempts = 1"))
        s.commit()
    assert api.get(f"/admin/data-load/requests/{rid}", headers=h).json()["finished"]
    r = api.post("/admin/data-load/collect", json={"kind": "list", "lines": ["GAHC019999982025"]}, headers=h)
    assert r.status_code == 202, r.text


def test_a_retry_of_the_request_still_belongs_to_it_a_later_retry_does_not(api, world):
    with world.Session() as s:
        cnr = make_case(s, cnr="GAHC010000892025").cnr
        s.commit()
    h = ds.login(api, "root")
    rid = api.post("/admin/data-load/collect", json={"kind": "list", "lines": [cnr]}, headers=h).json()[
        "request_id"
    ]
    _run_now_rows(world, fail_first=True)
    row = _row(world, FetchKind.DOSSIER, cnr)
    assert (row.status, row.attempts, row.priority) == (FetchStatus.PENDING, 1, NOW_BULK)
    with world.Session() as s:
        s.execute(sa.text("UPDATE fetch_queue SET not_before = now() - interval '1 minute'"))
        s.commit()
    d = api.get(f"/admin/data-load/requests/{rid}", headers=h).json()
    assert not d["finished"] and d["using_everything"] and d["counts"]["waiting"] == 1
    _run_now_rows(world)
    assert api.get(f"/admin/data-load/requests/{rid}", headers=h).json()["finished"]
    # a later system run of the same dossier that fails is not this request's retry
    with world.Session() as s:
        queue.enqueue(s, FetchKind.DOSSIER, cnr, queue.PRIORITY["dossier_refetch"], requeue=True)
        item = queue.claim(s)
        queue.fail(s, item, "court busy")
        s.execute(sa.text("UPDATE fetch_queue SET not_before = now() - interval '1 minute'"))
        s.commit()
    d = api.get(f"/admin/data-load/requests/{rid}", headers=h).json()
    assert d["finished"] and d["counts"]["done"] == 1


def test_update_now_masters_then_the_schedule_queues_at_10(api, world):
    from aslms.services import schedules

    h = ds.login(api, "central_op")
    assert api.post("/admin/napix/sync-masters", json={}, headers=h).status_code == 202
    assert _row(world, FetchKind.MASTERS, "all").priority == NOW_ONE
    _run_now_rows(world)
    with world.Session() as s:
        assert schedules.enqueue_masters(s)
        s.commit()
    row = _row(world, FetchKind.MASTERS, "all")
    assert (row.status, row.priority, row.lane) == (FetchStatus.PENDING, 10, FetchLane.DAILY)


def test_retry_failed_brings_a_failed_now_row_back_at_30(api, world):
    with world.Session() as s:
        cnr = make_case(s, cnr="GAHC010000882025").cnr
        s.commit()
    h = ds.login(api, "root")
    api.post("/admin/data-load/collect", json={"kind": "list", "lines": [cnr]}, headers=h)
    with world.Session() as s:
        s.execute(sa.text("UPDATE fetch_queue SET status = 'failed', attempts = 6"))
        s.commit()
    r = api.post("/admin/napix/queue/retry-failed", json={"kind": "dossier"}, headers=h)
    assert r.status_code in (200, 202), r.text
    row = _row(world, FetchKind.DOSSIER, cnr)
    assert (row.status, row.priority, row.requested_by) == (FetchStatus.PENDING, 30, None)


# ------------------------------------------------------------------------------------------------ the CLI


def test_cli_collect_day_and_stop(world, monkeypatch):
    from contextlib import contextmanager

    from typer.testing import CliRunner

    from aslms.cli import data_load as cli

    @contextmanager
    def scope():
        s = world.Session()
        try:
            yield s
            s.commit()
        finally:
            s.close()

    monkeypatch.setattr(cli, "session_scope", scope)
    monkeypatch.setattr(cli, "get_settings", lambda: Settings(_env_file=None, redis_url=None))
    d = today_ist() - timedelta(days=1)
    _day_world(world, d)
    runner = CliRunner()
    r = runner.invoke(cli.data_load_app, ["collect", "--date", d.isoformat(), "--dry-run"])
    assert r.exit_code == 0, r.output
    assert "to fetch (never): 2" in " ".join(r.output.split()) and _rows(world) == []
    r = runner.invoke(cli.data_load_app, ["collect", "--date", d.isoformat(), "--all"])
    assert r.exit_code == 0, r.output
    (audit,) = _audits(world, collect.COLLECT_ACTION)
    assert audit.after["scope"] == "all" and audit.actor_user_id == world.users["root"].id
    assert {r.priority for r in _rows(world)} == {NOW_BULK} and len(_rows(world)) == 3
    r = runner.invoke(cli.data_load_app, ["collect", "--date", d.isoformat()])
    assert r.exit_code != 0 and "bulk_running" in " ".join(r.output.split())
    r = runner.invoke(cli.data_load_app, ["stop", str(audit.id)])
    assert r.exit_code == 0, r.output
    assert {r.priority for r in _rows(world)} == {30}
    assert runner.invoke(cli.data_load_app, ["stop", "not-an-id"]).exit_code != 0
