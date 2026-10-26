"""Case reference numbers carry the court's code (design `case-ref-court-prefix`): every creation path numbers a case
on its court's `ref_code` (discovery included, no longer on the term's department), a court without a code is
refused with no counter consumed, the CHECK on `cases.ref_no` and the constraints on `courts.ref_code` hold, an
office cannot take a court's code, an old `GOA` case number resolves to the case without widening visibility, the
audit and alert filters accept it, the timeline presents the current number, and the bench sync gives a new
establishment its High Court's code (or skips it)."""

from __future__ import annotations

import asyncio
import re
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from aslms.api.main import create_app
from aslms.core.clock import today_ist
from aslms.core.config import Settings
from aslms.domain.cases import Case, FirstSeenSource
from aslms.domain.courts import Court, HighCourt
from aslms.domain.events import AuditLog, Event
from aslms.domain.ops import FetchKind
from aslms.domain.reference import EventType, OfficeKind
from aslms.services import alerts, case_detail, napix_inspect, offices, queue
from aslms.services import matching_rules as mr
from aslms.services import ownership as own
from aslms.services.cases import get_or_create_case, resolve_case_ref
from aslms.services.court_search import store_search_rows
from aslms.services.masters import MasterReport, sync_bench_master
from aslms.services.napix_store import NapixRecorder
from aslms.services.refno import CourtCodeMissing, allocate_case_ref_no
from aslms.services.runner import QueueRunner, enqueue_days
from aslms.services.storage import LocalStore
from tests.db.auth_support import bearer
from tests.db.conftest import sample
from tests.db.world import PW, USERS, make_case

GHC_RE = re.compile(r"^ASLMS/GHC/CASE/[0-9]{4}/[0-9]{6}$")


def old_number(ref_no: str) -> str:
    """The number the case carried before the renumbering (DB_STANDARD §3a)."""
    assert ref_no.startswith("ASLMS/GHC/CASE/")
    return "ASLMS/GOA/CASE/" + ref_no.removeprefix("ASLMS/GHC/CASE/")


def dash(ref_no: str) -> str:
    return ref_no.replace("/", "-")


@pytest.fixture()
def api(world):
    settings = Settings(
        _env_file=None,
        aslms_jwt_secret="test-secret-of-at-least-thirty-two-characters",
        aslms_access_token_minutes=5,
    )
    with TestClient(create_app(settings, world.Session)) as client:
        yield client


def login(api: TestClient, key: str) -> dict:
    return bearer(api, USERS[key][0], PW)


def gahc01(s) -> Court:
    return s.scalar(sa.select(Court).where(Court.est_code == "GAHC01"))


# ------------------------------------------------------------------------------------------------ creation paths


def _run(world, napix, tmp_path, kinds) -> None:
    gw, client, hc = napix
    recorder = NapixRecorder()
    client.on_call = recorder.on_call
    settings = Settings(
        _env_file=None,
        storage_dir=str(tmp_path / "store"),
        causelist_dir=str(tmp_path / "lists"),
        napix_rate_reserve=0,
        napix_live_reserve=0,
        napix_search_floor=0,
    )

    async def go():
        async with client:
            runner = QueueRunner(
                world.Session,
                hc,
                settings=settings,
                store=LocalStore(settings.storage_dir),
                causelist_dir=tmp_path / "lists",
                recorder=recorder,
                reserve=0,
            )
            return await runner.run(kinds=kinds)

    rep = asyncio.run(go())
    assert rep.failed == 0, rep.items


def _causelist(world, napix, tmp_path) -> None:
    with world.Session() as s:
        queue.enqueue(s, FetchKind.MASTERS, "all", queue.PRIORITY["masters"])
        enqueue_days(s, date(2025, 1, 6), date(2025, 1, 6))
        s.commit()
    _run(world, napix, tmp_path, [FetchKind.MASTERS, FetchKind.CAUSELIST_DAY])


def _dossier(world, napix, tmp_path) -> None:
    with world.Session() as s:
        queue.enqueue(s, FetchKind.DOSSIER, "GAHC010000012025", queue.PRIORITY["dossier_new"])
        s.commit()
    _run(world, napix, tmp_path, [FetchKind.DOSSIER])


def _court_search(world, napix, tmp_path) -> None:
    with world.Session() as s:
        rows = list(sample("party_name_2026-09-03.json")["casenos"].values())
        store_search_rows(s, gahc01(s), rows)
        s.commit()


def _watchlist(world, napix, tmp_path) -> None:
    with world.Session() as s:
        actor, admin = world.actor(s, "edu_admin")
        _, queued = mr.add_watch(s, actor, admin, cnr="GAHC010000022025", office=world.office(s, "EDU"))
        assert queued
        s.commit()
    _run(world, napix, tmp_path, [FetchKind.DOSSIER])


def _data_load_single_fetch(world, napix, tmp_path) -> None:
    # a single case by its number (`<est>|<case number>`): Search by Case Number finds the CNR, then the dossier
    with world.Session() as s:
        queue.enqueue(s, FetchKind.MASTERS, "all", queue.PRIORITY["masters"])
        queue.enqueue(s, FetchKind.DOSSIER, "GAHC01|WA/435/2024", queue.PRIORITY["dossier_new"])
        s.commit()
    _run(world, napix, tmp_path, [FetchKind.MASTERS, FetchKind.DOSSIER])


def _discovery(world, napix, tmp_path) -> None:
    with world.Session() as s:
        actor, admin = world.actor(s, "edu_admin")
        mr.create_name_pattern(
            s, actor, admin, pattern="Janifa Kaifee Ahmed", kind="prefix", office=world.office(s, "EDU-DSE")
        )
        s.commit()
    _run(world, napix, tmp_path, [FetchKind.PARTY_SEARCH])


PATHS = {
    "causelist": _causelist,
    "dossier": _dossier,
    "court_search": _court_search,
    "watchlist": _watchlist,
    "data_load_single_fetch": _data_load_single_fetch,
    "discovery": _discovery,
}


@pytest.mark.parametrize("path", list(PATHS))
def test_every_creation_path_numbers_on_the_court(world, napix, tmp_path, path):
    with world.Session() as s:
        before = set(s.scalars(sa.select(Case.id)).all())
    PATHS[path](world, napix, tmp_path)
    with world.Session() as s:
        rows = s.execute(
            sa.select(Case.ref_no, Court.ref_code, Case.first_seen_source)
            .join(Court, Court.id == Case.court_id)
            .where(Case.id.notin_(before) if before else sa.true())
        ).all()
    assert rows, f"{path} created no case"
    for ref_no, court_code, _ in rows:
        assert GHC_RE.match(ref_no), ref_no
        assert ref_no.split("/")[1] == court_code == "GHC"
    if path == "discovery":
        assert {FirstSeenSource(r.first_seen_source) for r in rows} == {FirstSeenSource.DISCOVERY}
        assert not any("/EDU" in r.ref_no for r in rows)  # not on the term's department any more


def test_case_without_court_code_is_refused(world):
    with world.Session() as s:
        counters = s.execute(
            sa.text("SELECT office_code, record_type, year, last_value FROM ref_sequences")
        ).all()
        cases = s.scalar(sa.select(sa.func.count()).select_from(Case))
        # a court row without a code cannot exist (NOT NULL); an unsaved one stands for a court of a later item
        court = Court(id=uuid.uuid4(), est_code="ZZHC01", name="A court without a code")
        with pytest.raises(CourtCodeMissing):
            allocate_case_ref_no(s, court)
        with pytest.raises(CourtCodeMissing):
            get_or_create_case(s, court, cnr="ZZHC010000012025", case_no=None, source=FirstSeenSource.SEARCH)
        s.flush()
        assert s.scalar(sa.select(sa.func.count()).select_from(Case)) == cases
        assert (
            s.execute(sa.text("SELECT office_code, record_type, year, last_value FROM ref_sequences")).all()
            == counters
        )
        s.rollback()


# ------------------------------------------------------------------------------------------------ constraints


def _refused(s, sql: str, params: dict) -> None:
    with pytest.raises((sa.exc.IntegrityError, sa.exc.DataError)):
        with s.begin_nested():
            s.execute(sa.text(sql), params)


def test_ck_cases_ref_no_court_refuses_goa_and_bad_format(world):
    insert = (
        "INSERT INTO cases (court_id, ref_no, first_seen_source, is_provisional) "
        "VALUES (:court, :ref, 'search', true)"
    )
    with world.Session() as s:
        court = gahc01(s).id
        for ref in (
            "ASLMS/GOA/CASE/2026/900001",  # never a GOA case number again
            "ASLMS/GHC/NOTE/2026/900001",
            "ASLMS/ghc/CASE/2026/900001",
            "ASLMS/GHC/CASE/26/900001",
            "ASLMS/GHC/CASE/2026/9001",
            "GHC/CASE/2026/900001",
        ):
            _refused(s, insert, {"court": court, "ref": ref})
        with s.begin_nested():
            s.execute(sa.text(insert), {"court": court, "ref": "ASLMS/GHC/CASE/2026/900001"})
        s.rollback()


def test_courts_ref_code_format_and_one_code_per_court(world):
    insert = "INSERT INTO courts (est_code, name, high_court_id, ref_code) VALUES (:est, :name, :hc, :code) RETURNING id"
    with world.Session() as s:
        codes = dict(s.execute(sa.select(Court.est_code, Court.ref_code)).all())
        assert codes == {"GAHC01": "GHC", "GAHC02": "GHC", "GAHC03": "GHC", "GAHC04": "GHC"}
        gauhati = gahc01(s).high_court_id
        other = HighCourt(napix_state_code=99, name="Another High Court")
        s.add(other)
        s.flush()
        # a fifth establishment of the same High Court shares the code
        with s.begin_nested():
            s.execute(sa.text(insert), {"est": "GAHC05", "name": "Fifth", "hc": gauhati, "code": "GHC"})
        # another High Court's court cannot take it, nor can a court of record without a High Court
        _refused(s, insert, {"est": "OTHC01", "name": "Other", "hc": other.id, "code": "GHC"})
        _refused(s, insert, {"est": "SCI001", "name": "Top", "hc": None, "code": "GHC"})
        # format: never GOA, upper case, 2 to 10 characters
        for code in ("GOA", "ghc", "G", "1HC", "ABCDEFGHIJK"):
            _refused(s, insert, {"est": "OTHC02", "name": "Other", "hc": other.id, "code": code})
        with s.begin_nested():
            s.execute(sa.text(insert), {"est": "OTHC03", "name": "Other", "hc": other.id, "code": "OHC"})
            s.execute(
                sa.text(insert), {"est": "OTHC04", "name": "Other bench", "hc": other.id, "code": "OHC"}
            )
        # two courts without a High Court are two courts: one code each
        with s.begin_nested():
            s.execute(sa.text(insert), {"est": "SCI001", "name": "Supreme Court", "hc": None, "code": "SCI"})
        _refused(s, insert, {"est": "SCI002", "name": "Another", "hc": None, "code": "SCI"})
        s.rollback()


def test_office_code_equal_to_court_code_refused(world, api):
    with world.Session() as s:
        actor, root = world.actor(s, "root")
        with pytest.raises(offices.OfficeError, match="court's code"):
            offices.create_office(
                s,
                actor,
                root,
                code="ghc",
                name="High Court cell",
                kind=OfficeKind.UNIT,
                parent=world.office(s, "EDU"),
            )
        s.rollback()
    body = {"code": "GHC", "name": "High Court cell", "kind": "unit", "parent_code": "EDU"}
    r = api.post("/admin/offices", json=body, headers=login(api, "root"))
    assert r.status_code == 400 and "court's code" in r.text
    with world.Session() as s:
        assert offices.find_office(s, "GHC") is None


# ------------------------------------------------------------------------------------------------ old numbers


@pytest.fixture()
def claimed(world):
    """An EDU case claimed for the EDU officer `edu_off1`, with a hearing in three days and its date alert."""
    now = datetime.now(UTC)
    with world.Session() as s:
        case = make_case(s, cnr="GAHC010009992025", next_hearing=today_ist(now) + timedelta(days=3))
        actor, admin = world.actor(s, "edu_admin")
        own.claim(s, actor, admin, case, officer_user_id=world.users["edu_off1"].id)
        s.commit()
        alerts.sweep_dates(s, now=now)
        s.commit()
        return {"id": str(case.id), "ref_no": case.ref_no, "old": old_number(case.ref_no), "cnr": case.cnr}


def test_resolve_case_ref_accepts_old_number(world, api, claimed):
    with world.Session() as s:
        for ref in (claimed["old"], dash(claimed["old"]), dash(claimed["old"]).lower()):
            assert str(resolve_case_ref(s, ref).id) == claimed["id"], ref
    root = login(api, "root")
    for ref in (dash(claimed["old"]), dash(claimed["ref_no"])):
        r = api.get(f"/cases/{ref}", headers=root)
        assert r.status_code == 200, r.text
        assert r.json()["ref_no"] == claimed["ref_no"]
    # Search and the shared filter `q` find the case by its old number
    for route in ("/cases/search", "/cases"):
        r = api.get(route, params={"q": claimed["old"]}, headers=root)
        assert r.status_code == 200, r.text
        assert [str(i["case"]["id"]) for i in r.json()["items"]] == [claimed["id"]], route


def test_old_number_does_not_widen_visibility(api, claimed):
    health = login(api, "health_off")
    answers = [
        api.get(f"/cases/{ref}", headers=health)
        for ref in (dash(claimed["old"]), dash(claimed["ref_no"]), claimed["cnr"])
    ]
    assert [r.status_code for r in answers] == [404, 404, 404]
    assert len({r.text for r in answers}) == 1
    edu = login(api, "edu_off1")  # the officer the case is claimed for
    assert api.get(f"/cases/{dash(claimed['old'])}", headers=edu).status_code == 200


def test_audit_and_alert_filters_accept_old_number(world, api, claimed):
    root = login(api, "root")
    by_new = api.get("/audit", params={"case": dash(claimed["ref_no"])}, headers=root)
    by_old = api.get("/audit", params={"case": dash(claimed["old"])}, headers=root)
    assert by_new.status_code == by_old.status_code == 200, by_old.text
    assert by_new.json()["items"] and by_old.json() == by_new.json()
    with world.Session() as s:
        held = s.scalar(
            sa.select(sa.func.count())
            .select_from(AuditLog)
            .where(AuditLog.case_id == uuid.UUID(claimed["id"]))
        )
    assert len(by_new.json()["items"]) == held
    off1 = login(api, "edu_off1")
    for ref in (claimed["ref_no"], dash(claimed["ref_no"])):
        alerts_new = api.get("/alerts", params={"case": ref}, headers=off1)
        assert alerts_new.status_code == 200 and alerts_new.json()["total"] == 1, alerts_new.text
    for ref in (claimed["old"], dash(claimed["old"])):
        alerts_old = api.get("/alerts", params={"case": ref}, headers=off1)
        assert alerts_old.status_code == 200, alerts_old.text
        assert alerts_old.json() == alerts_new.json()


def test_timeline_shows_current_number_for_stored_payload(world, claimed):
    with world.Session() as s:
        case = s.get(Case, uuid.UUID(claimed["id"]))
        other = make_case(s, cnr="GAHC010009982025")
        stored = {
            "from_ref_no": claimed["old"],
            "to_ref_no": old_number(other.ref_no),
            "merged_ref_no": claimed["old"],
            "into_ref_no": old_number(other.ref_no),
            "note": "kept as recorded",
        }
        s.add(
            Event(
                type=EventType.CASE_LINKED, case_id=case.id, payload=dict(stored), dedupe_key=f"t:{case.id}"
            )
        )
        s.commit()
        root = world.user(s, "root")
        page = case_detail.timeline(s, root, case)
        (item,) = [i for i in page.items if i["type"] == "case_linked"]
        assert item["payload"]["from_ref_no"] == claimed["ref_no"]
        assert item["payload"]["to_ref_no"] == other.ref_no
        assert item["payload"]["merged_ref_no"] == claimed["ref_no"]
        assert item["payload"]["into_ref_no"] == other.ref_no
        assert item["payload"]["note"] == "kept as recorded"
        # the stored payload is untouched
        assert s.scalar(sa.select(Event.payload).where(Event.dedupe_key == f"t:{case.id}")) == stored


# ------------------------------------------------------------------------------------------------ bench sync


def test_bench_sync_gives_new_establishment_the_high_court_code(world):
    with world.Session() as s:
        hc = s.get(HighCourt, gahc01(s).high_court_id)
        rows = [
            {"est_code": est, "bench_id": no, "bench_name": name}
            for est, no, name in (
                ("GAHC01", 1, "Principal Seat at Guwahati"),
                ("GAHC02", 2, "Kohima Bench"),
                ("GAHC03", 3, "Aizawl Bench"),
                ("GAHC04", 4, "Itanagar Bench"),
                ("GAHC05", 5, "A New Bench"),
            )
        ]
        report = MasterReport()
        sync_bench_master(s, rows, hc, report)
        new = s.scalar(sa.select(Court).where(Court.est_code == "GAHC05"))
        assert new is not None and new.ref_code == "GHC" and new.high_court_id == hc.id
        assert report.errors == [] and report.counts["bench"]["inserted"] == 1
        s.rollback()


def test_bench_sync_skips_new_establishment_without_one(world):
    with world.Session() as s:
        other = HighCourt(napix_state_code=99, name="Another High Court")
        s.add(other)
        s.flush()
        report = MasterReport()
        sync_bench_master(
            s, [{"est_code": "OTHC01", "bench_id": 1, "bench_name": "Principal Seat"}], other, report
        )
        assert s.scalar(sa.select(Court).where(Court.est_code == "OTHC01")) is None
        assert report.counts["bench"]["inserted"] == 0
        assert (
            len(report.errors) == 1 and "OTHC01" in report.errors[0] and "no court code" in report.errors[0]
        )
        s.rollback()


def test_recorded_send_sample_with_old_number_keeps_its_visibility(world, claimed):
    """A System health send recorded before the renumbering names its sample case by the old number: its values stay
    visible to a reader of the case, and only to one."""
    after = {"edited": False, "sample": {"case_ref_no": claimed["old"]}}
    with world.Session() as s:
        assert napix_inspect.params_shown(s, world.user(s, "edu_off1"), None, after) is True
        assert napix_inspect.params_shown(s, world.user(s, "health_off"), None, after) is False
