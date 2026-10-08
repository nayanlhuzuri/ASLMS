"""The audit search service (design `audit-screens`, decisions 1-4): rows written by the real services are found by
actor, case and date; the IST day boundary; rows about a login; merged cases; the office subtree; keyset paging
without gaps or repeats; the action list; the note-text digest only."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
import sqlalchemy as sa

from aslms.domain.events import AuditLog
from aslms.domain.reference import Role
from aslms.services import access, memberships
from aslms.services import audit_search as svc
from aslms.services.cases import CaseNotFound
from aslms.services.reporting_common import today_ist
from aslms.services.workflow_common import digest
from tests import samplefiles as sf
from tests.db import docs_support as ds
from tests.db import workflow_support as w
from tests.db.world import make_case


@pytest.fixture()
def api(world, tmp_path):
    client = ds.make_api(world, tmp_path)
    yield client
    client.__exit__(None, None, None)


def _row(
    s, at: datetime, *, action="test.row", actor=None, office=None, case_id=None, entity_type="test", **kw
):
    row = AuditLog(
        created_at=at,
        action=action,
        entity_type=entity_type,
        entity_id=kw.get("entity_id"),
        case_id=case_id,
        actor_user_id=actor,
        actor_name=kw.get("name", "Test Actor"),
        actor_office_code=office,
    )
    s.add(row)
    s.flush()
    return row


def _search(s, world, key="edu_auditor", **kw):
    return svc.search(s, world.user(s, key), svc.AuditQuery(**kw))


def _ids(page) -> list[uuid.UUID]:
    return [i["id"] for i in page.items]


@pytest.fixture()
def scene(world, api):
    """A claimed EDU case (claim), a custody send, a note and an upload through the real services and the API."""
    with world.Session() as s:
        case = w.claimed_case(s, world)
        w.send(s, world, "edu_off1", case, "edu_off2", remark="secret remark text")
        w.note(s, world, "edu_off1", case, body="the confidential note body")  # not the holder: a note
        s.commit()
        case_id, ref_no, cnr = case.id, case.ref_no, case.cnr
    r = ds.upload(api, ds.login(api, "edu_off2"), case_id, sf.text_pdf(["a petition"]))
    assert r.status_code == 201, r.text
    return {"case_id": case_id, "ref_no": ref_no, "cnr": cnr}


def test_search_by_user_case_and_date_combined(world, scene):
    with world.Session() as s:
        today = today_ist()
        everything = _search(s, world, case_ref=scene["ref_no"], from_=today, to=today, limit=200)
        actions = [i["action"] for i in everything.items]
        for code in ("ownership.claim", "custody.sent", "note.added", "document.uploaded"):
            assert code in actions, actions
        created = [i["at"] for i in everything.items]
        assert created == sorted(created, reverse=True)  # newest first
        # actor alone: the EDU officer's own rows
        off1 = _search(s, world, user_email="OFF1.edu@example.org", limit=200)
        assert {i["action"] for i in off1.items} >= {"custody.sent", "note.added"}
        assert "document.uploaded" not in {i["action"] for i in off1.items}
        assert all(i["actor"]["user_id"] == world.users["edu_off1"].id for i in off1.items)
        # actor AND case AND date AND action prefix
        both = _search(
            s,
            world,
            user_id=world.users["edu_off1"].id,
            case_ref=scene["cnr"],
            from_=today,
            to=today,
            action="note.",
        )
        assert [i["action"] for i in both.items] == ["note.added"]
        assert both.items[0]["case"]["ref_no"] == scene["ref_no"]
        # a day with nothing
        assert _search(s, world, case_ref=scene["ref_no"], to=today - timedelta(days=1)).items == []
        # the actor's name text
        named = _search(s, world, actor_text="off2", case_ref=scene["ref_no"])
        assert [i["action"] for i in named.items] == ["document.uploaded"]
        assert named.items[0]["actor"]["name"] == "Edu Off2"


def test_rows_carry_no_note_text(world, scene):
    with world.Session() as s:
        page = _search(s, world, case_ref=scene["ref_no"], limit=200)
        note = next(i for i in page.items if i["action"] == "note.added")
        sent = next(i for i in page.items if i["action"] == "custody.sent")
        assert note["after"]["body"] == digest("the confidential note body")
        assert sent["after"]["remark"] == digest("secret remark text")
        blob = repr([i["before"] for i in page.items] + [i["after"] for i in page.items])
        assert "confidential note body" not in blob and "secret remark text" not in blob


def test_ist_day_boundary(world):
    with world.Session() as s:
        last = _row(s, datetime(2026, 10, 8, 18, 29, 59, tzinfo=UTC), action="test.boundary")  # 23:59:59 IST
        nxt = _row(s, datetime(2026, 10, 8, 18, 30, tzinfo=UTC), action="test.boundary")  # 00:00 IST, 9 Oct
        first = _row(s, datetime(2026, 10, 7, 18, 30, tzinfo=UTC), action="test.boundary")  # 00:00 IST, 8 Oct
        before = _row(s, datetime(2026, 10, 7, 18, 29, 59, tzinfo=UTC), action="test.boundary")
        on_8 = _ids(_search(s, world, action="test.boundary", from_=date(2026, 10, 8), to=date(2026, 10, 8)))
        assert on_8 == [last.id, first.id]
        assert _ids(_search(s, world, action="test.boundary", from_=date(2026, 10, 9))) == [nxt.id]
        assert _ids(_search(s, world, action="test.boundary", to=date(2026, 10, 7))) == [before.id]
        with pytest.raises(svc.AuditInputError) as exc:
            _search(s, world, from_=date(2026, 10, 9), to=date(2026, 10, 8))
        assert exc.value.code == "bad_period"
        s.rollback()


def test_about_user_includes_membership_rows(world):
    with world.Session() as s:
        actor, root = world.actor(s, "root")
        target = world.user(s, "edu_off1")
        access.set_enabled(s, actor, root, target, False)
        access.set_enabled(s, actor, root, target, True)
        added = memberships.insert_membership(
            s, actor, target, office=world.office(s, "HEALTH"), role=Role.DEPT_OFFICER, audit=True
        )
        other = world.user(s, "edu_off2")
        access.set_enabled(s, actor, root, other, False)
        page = _search(s, world, about_user_email="off1.edu@example.org", limit=200)
        got = {(i["action"], i["entity_type"], i["entity_id"]) for i in page.items}
        assert ("user.disable", "user", target.id) in got and ("user.enable", "user", target.id) in got
        assert ("membership.added", "user_membership", added.id) in got
        assert all(i["entity_id"] != other.id for i in page.items)
        by_id = _search(s, world, about_user_id=target.id, limit=200)
        assert _ids(by_id) == _ids(page)
        s.rollback()


def test_case_filter_includes_merged_duplicates(world):
    with world.Session() as s:
        survivor = make_case(s)
        duplicate = make_case(s)
        stranger = make_case(s)
        duplicate.merged_into_case_id = survivor.id
        s.flush()
        now = datetime.now(UTC)
        a = _row(s, now - timedelta(seconds=3), case_id=survivor.id)
        b = _row(s, now - timedelta(seconds=2), case_id=duplicate.id)
        _row(s, now - timedelta(seconds=1), case_id=stranger.id)
        assert _ids(_search(s, world, case_ref=survivor.ref_no)) == [b.id, a.id]
        # the duplicate alone: only its own rows
        assert _ids(_search(s, world, case_ref=duplicate.ref_no)) == [b.id]
        s.rollback()


def test_case_by_ref_no_and_cnr(world):
    with world.Session() as s:
        case = make_case(s)
        row = _row(s, datetime.now(UTC), case_id=case.id)
        for ref in (case.ref_no, case.ref_no.replace("/", "-"), case.cnr, str(case.id)):
            assert _ids(_search(s, world, case_ref=ref)) == [row.id], ref
        with pytest.raises(CaseNotFound):
            _search(s, world, case_ref="ASHC019999992099")
        s.rollback()


def test_office_filter_covers_subtree(world):
    with world.Session() as s:
        now = datetime.now(UTC)
        edu = _row(s, now - timedelta(seconds=3), office="EDU", action="test.office")
        dse = _row(s, now - timedelta(seconds=2), office="EDU-DSE", action="test.office")
        _row(s, now - timedelta(seconds=1), office="HEALTH", action="test.office")
        assert _ids(_search(s, world, office_code="edu", action="test.office")) == [dse.id, edu.id]
        assert _ids(_search(s, world, office_code="EDU-DSE", action="test.office")) == [dse.id]
        with pytest.raises(svc.AuditInputError) as exc:
            _search(s, world, office_code="NOWHERE")
        assert exc.value.code == "bad_office"
        s.rollback()


def test_keyset_paging_has_no_gaps_or_repeats(world):
    with world.Session() as s:
        base = datetime(2026, 10, 1, 6, 0, tzinfo=UTC)
        rows = [_row(s, base + timedelta(minutes=i), action="test.page") for i in range(3)]
        same = base + timedelta(minutes=10)
        rows += [_row(s, same, action="test.page") for _ in range(5)]  # five rows share one created_at
        rows += [_row(s, base + timedelta(minutes=20), action="test.page")]
        expected = [r.id for r in sorted(rows, key=lambda r: (r.created_at, r.id), reverse=True)]
        seen: list[uuid.UUID] = []
        cursor = None
        pages = 0
        while True:
            page = _search(s, world, action="test.page", limit=2, cursor=cursor)
            seen += _ids(page)
            pages += 1
            cursor = page.next_cursor
            if cursor is None:
                break
        assert seen == expected and len(set(seen)) == len(rows) == 9
        assert pages == 5
        with pytest.raises(svc.AuditInputError) as exc:
            _search(s, world, cursor="garbage")
        assert exc.value.code == "bad_cursor"
        s.rollback()


def test_actions_lists_distinct_codes(world):
    with world.Session() as s:
        now = datetime.now(UTC)
        for code in ("test.b", "test.a", "test.b", "custody.sent"):
            _row(s, now, action=code)
        codes = svc.actions(s, world.user(s, "edu_auditor"))
        assert codes == sorted(set(codes))
        assert {"test.a", "test.b", "custody.sent"} <= set(codes)
        assert codes.count("test.b") == 1
        s.rollback()


def test_unknown_user_and_row_detail(world):
    with world.Session() as s:
        with pytest.raises(svc.AuditInputError) as exc:
            _search(s, world, user_email="nobody@example.org")
        assert exc.value.code == "unknown_user"
        with pytest.raises(svc.AuditInputError):
            _search(s, world, about_user_id=uuid.uuid4())
        row = _row(s, datetime.now(UTC), action="test.detail", office="EDU", name="Detail Person")
        got = svc.get(s, world.user(s, "edu_auditor"), row.id)
        assert got["id"] == row.id and got["actor"]["name"] == "Detail Person" and got["case"] is None
        with pytest.raises(svc.AuditNotFound):
            svc.get(s, world.user(s, "edu_auditor"), uuid.uuid4())
        s.rollback()


def test_reading_writes_nothing(world, scene):
    with world.Session() as s:
        before = s.scalar(sa.select(sa.func.count()).select_from(AuditLog))
        page = _search(s, world, case_ref=scene["ref_no"])
        svc.get(s, world.user(s, "edu_auditor"), page.items[0]["id"])
        svc.actions(s, world.user(s, "edu_auditor"))
        _search(s, world, key="root")
        s.commit()
    with world.Session() as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(AuditLog)) == before


def test_search_timeout_answers_search_timeout(world, monkeypatch):
    """A cancelled statement becomes `SearchTimeout` (503 `search_timeout` at the API)."""
    from aslms.services import audit_search

    def slow(session, seconds):
        session.execute(sa.text("SET LOCAL statement_timeout = 1"))

    monkeypatch.setattr(audit_search, "with_timeout", slow)
    with world.Session() as s:
        s.execute(sa.text("SELECT 1"))
        real_execute = s.execute

        def execute(stmt, *a, **kw):
            if not isinstance(stmt, sa.TextClause):
                real_execute(sa.text("SELECT pg_sleep(0.05)"))
            return real_execute(stmt, *a, **kw)

        monkeypatch.setattr(s, "execute", execute)
        with pytest.raises(svc.SearchTimeout):
            _search(s, world)
        s.rollback()
