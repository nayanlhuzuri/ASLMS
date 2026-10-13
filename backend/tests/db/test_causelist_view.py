"""The Cause list screen's service (design `portal-causelist`): dates and day states, benches in court order, the
day's entries as published in court order with the portal's facts scoped per caller, `claimable` equal to the
per-case claim rule, the filters and counts, validation, and reading writes nothing."""

from __future__ import annotations

from datetime import date

import pytest
import sqlalchemy as sa

from aslms.domain.cases import Case
from aslms.domain.events import AuditLog, Event
from aslms.domain.ops import FetchKind, FetchQueueItem, NapixCallLog
from aslms.services import causelist_view as cv
from aslms.services import ownership as own
from aslms.services import queue
from aslms.services.storage import LocalStore
from tests.db.causelist_support import D1, D2, D3, build

ROLES = ("edu_admin", "health_admin", "edu_off1", "dse_user", "edu_counsel", "central_op", "root")


@pytest.fixture()
def cl(world, tmp_path):
    return build(world, LocalStore(tmp_path / "store"))


def rows(s, world, key, d=D2, **kw):
    return cv.entries(s, world.user(s, key), d, limit=500, **kw)


def by_entry(page) -> dict:
    return {str(i["id"]): i for i in page["items"]}


def set_queue(s, d: date, status: str) -> None:
    queue.enqueue(s, FetchKind.CAUSELIST_DAY, d.isoformat(), 20)
    s.execute(
        sa.text(
            "UPDATE fetch_queue SET status = CAST(:st AS fetch_queue_status) WHERE kind = 'causelist_day' AND ref = :r"
        ),
        {"st": status, "r": d.isoformat()},
    )


# ------------------------------------------------------------------------------------------------ dates


def test_dates_default_is_first_held_on_or_after_today_else_latest(world, cl):
    with world.Session() as s:
        assert cv.dates(s, today=D2)["default_date"] == D2
        assert cv.dates(s, today=date(2026, 10, 14))["default_date"] == D3
        assert cv.dates(s, today=date(2026, 10, 1))["default_date"] == D1
        assert cv.dates(s, today=date(2026, 12, 1))["default_date"] == D3


def test_dates_states_held_loading_no_list_failed(world, cl):
    with world.Session() as s:
        set_queue(s, D1, "done")
        set_queue(s, date(2026, 10, 14), "pending")
        set_queue(s, date(2026, 10, 15), "skipped")
        set_queue(s, date(2026, 10, 16), "failed")
        set_queue(s, date(2026, 10, 17), "running")
        out = cv.dates(s, date_from=date(2026, 10, 1), date_to=date(2026, 10, 31), today=D2)
        states = {i["date"]: i["state"] for i in out["items"]}
        assert states == {
            D1: "held",
            D2: "held",
            date(2026, 10, 14): "loading",
            date(2026, 10, 15): "no_list",
            date(2026, 10, 16): "failed",
            date(2026, 10, 17): "loading",
            D3: "held",
        }
        d2 = next(i for i in out["items"] if i["date"] == D2)
        assert (d2["lists"], d2["benches"], d2["entries"]) == (4, 4, 9)
        assert cv.day_state(s, date(2026, 10, 18))[0] == "not_loaded"
        s.rollback()


def test_dates_range_bounds_and_reversed_400(world, cl):
    with world.Session() as s:
        out = cv.dates(s, today=D2)
        assert (out["from"], out["to"], out["today"]) == (date(2026, 8, 14), date(2026, 10, 20), D2)
        with pytest.raises(cv.CauselistViewError):
            cv.dates(s, date_from=D2, date_to=D1)
        with pytest.raises(cv.CauselistViewError):
            cv.dates(s, date_from=date(2025, 1, 1), date_to=date(2026, 2, 6))
        assert cv.dates(s, date_from=date(2025, 1, 1), date_to=date(2026, 2, 5))["items"] == []
        alone = cv.dates(s, date_from=D2, today=D2)
        assert alone["to"] == date(2026, 12, 19)


# ------------------------------------------------------------------------------------------------ one day


def test_day_benches_ordered_by_court_number_then_bench(world, cl):
    with world.Session() as s:
        out = cv.day(s, D2)
        assert [b["bench_id"] for b in out["benches"]] == [777, 1854, 2048, 3000]
        assert [b["court_nos"] for b in out["benches"]] == [["2"], ["10"], ["111"], []]
        assert out["totals"] == {"benches": 4, "lists": 4, "entries": 9}
        assert out["state"] == "held"


def test_day_lists_in_type_order_with_pdf_flag(world, cl):
    with world.Session() as s:
        bench = next(b for b in cv.day(s, D2)["benches"] if b["bench_id"] == 1854)
        assert [x["list_type"] for x in bench["lists"]] == ["daily", "supplementary"]
        assert [x["has_pdf"] for x in bench["lists"]] == [True, False]
        assert bench["lists"][1]["fetch_status"] == "not_available"
        assert [x["entries_stored"] for x in bench["lists"]] == [6, 1]
        assert bench["entries"] == 7
        assert bench["label"].startswith("HONOURABLE THE CHIEF JUSTICE")


def test_day_includes_bench_day_without_list(world, cl):
    with world.Session() as s:
        bench = next(b for b in cv.day(s, D2)["benches"] if b["bench_id"] == 3000)
        assert bench["lists"] == [] and bench["entries"] == 0
        assert bench["label"] == "HONOURABLE MR. JUSTICE MANISH CHOUDHURY"


def test_day_website_file_is_its_own_bench(world, cl):
    with world.Session() as s:
        out = cv.day(s, D3)
        assert len(out["benches"]) == 1
        bench = out["benches"][0]
        assert bench["bench_id"] is None and bench["source"] == "ghc_website"
        assert [str(x["id"]) for x in bench["lists"]] == [str(cl.lists["website"])]
        assert bench["court_nos"] == ["5"]


def test_day_without_anything_is_empty_with_state(world, cl):
    with world.Session() as s:
        out = cv.day(s, date(2026, 10, 18))
        assert out["state"] == "not_loaded" and out["benches"] == []
        assert out["totals"] == {"benches": 0, "lists": 0, "entries": 0}
        set_queue(s, date(2026, 10, 18), "skipped")
        out = cv.day(s, date(2026, 10, 18))
        assert (out["state"], out["queue_status"]) == ("no_list", "skipped")
        s.rollback()


def test_day_previous_and_next_held_dates(world, cl):
    with world.Session() as s:
        out = cv.day(s, D2)
        assert (out["previous_date"], out["next_date"]) == (D1, D3)
        out = cv.day(s, D1)
        assert (out["previous_date"], out["next_date"]) == (None, D2)
        out = cv.day(s, date(2026, 10, 15))
        assert (out["previous_date"], out["next_date"]) == (D2, D3)


# ------------------------------------------------------------------------------------------------ entries


def test_entries_in_court_order_with_sections_and_connected_rows(world, cl):
    with world.Session() as s:
        page = rows(s, world, "edu_admin")
        order = [str(i["id"]) for i in page["items"]]
        e = {k: str(v) for k, v in cl.entries.items()}
        assert order == [
            e["e_court2"],
            e["e_pool"],
            e["e_rec_both"],
            e["e_connected"],
            e["e_health"],
            e["e_nocase"],
            e["e_merged"],
            e["e_supp"],
            e["e_lawazima"],
        ]
        connected = by_entry(page)[e["e_connected"]]
        assert connected["is_connected"] and connected["printed_sr_no"] is None
        assert connected["with_text"] == "with WP(C) 2087/2025"
        assert [i["section"] for i in page["items"][1:7]] == ["ORDERS"] * 3 + ["FOR ADMISSION"] * 3
        assert page["total"] == 9


def test_entries_every_row_for_a_directorate_user(world, cl):
    with world.Session() as s:
        page = rows(s, world, "dse_user")
        assert page["total"] == 9
        items = by_entry(page)
        owned = items[str(cl.entries["e_connected"])]
        assert owned["visible"] is False
        assert owned["owner_office_code"] == "EDU"
        assert owned["recommendations"] == [] and owned["claimable"] is False
        assert owned["case"]["id"] == cl.cases["edu_owned"]
        health = items[str(cl.entries["e_health"])]
        assert (health["visible"], health["owner_office_code"]) == (False, "HEALTH")
        both = items[str(cl.entries["e_rec_both"])]
        assert [r["office_code"] for r in both["recommendations"]] == ["EDU"]
        assert all(i["claimable"] is False for i in page["items"])


def test_entries_recommendations_only_own_departments(world, cl):
    with world.Session() as s:
        edu = by_entry(rows(s, world, "edu_admin"))[str(cl.entries["e_rec_both"])]
        assert edu["recommendations"] == [{"office_code": "EDU", "band": "high", "score": 0.95}]
        health = by_entry(rows(s, world, "health_admin"))[str(cl.entries["e_rec_both"])]
        assert health["recommendations"] == [{"office_code": "HEALTH", "band": "medium", "score": 0.62}]
        health_row = by_entry(rows(s, world, "health_admin"))[str(cl.entries["e_health"])]
        assert health_row["recommendations"] == []


def test_entries_recommendations_all_for_view_all(world, cl):
    with world.Session() as s:
        for key in ("central_op", "oversight", "root"):
            item = by_entry(rows(s, world, key))[str(cl.entries["e_rec_both"])]
            assert [r["office_code"] for r in item["recommendations"]] == ["EDU", "HEALTH"], key
            assert item["visible"] is True


def test_entries_owner_and_held_by_you_primary_and_watcher(world, cl):
    with world.Session() as s:
        a_edu, u_edu = world.actor(s, "edu_admin")
        own.claim(s, a_edu, u_edu, s.get(Case, cl.cases["health_rec_edu"]))
        s.flush()
        edu = by_entry(rows(s, world, "edu_admin"))
        assert edu[str(cl.entries["e_health"])]["held_by_you"] == "watcher"
        assert edu[str(cl.entries["e_health"])]["owner_office_code"] == "HEALTH"
        assert edu[str(cl.entries["e_connected"])]["held_by_you"] == "primary"
        assert edu[str(cl.entries["e_pool"])]["held_by_you"] is None
        health = by_entry(rows(s, world, "health_admin"))
        assert health[str(cl.entries["e_health"])]["held_by_you"] == "primary"
        assert health[str(cl.entries["e_connected"])]["held_by_you"] is None
        root = by_entry(rows(s, world, "root"))
        assert root[str(cl.entries["e_health"])]["held_by_you"] is None
        s.rollback()


def test_claimable_matches_available_actions(world, cl):
    mismatches = []
    with world.Session() as s:
        for key in ROLES:
            user = world.user(s, key)
            for item in cv.entries(s, user, D2, limit=500)["items"]:
                if item["case"] is None:
                    want = False
                else:
                    want = own.available_actions(s, user, s.get(Case, item["case"]["id"]))["claim"]
                if item["claimable"] != want:
                    mismatches.append((key, item["case_no_text"], item["claimable"], want))
    assert mismatches == []


def test_recommended_case_owned_elsewhere_is_claimable_as_watcher(world, cl):
    with world.Session() as s:
        item = by_entry(rows(s, world, "edu_admin"))[str(cl.entries["e_health"])]
        assert item["claimable"] is True and item["in_pool"] is False
        a_edu, u_edu = world.actor(s, "edu_admin")
        row = own.claim(s, a_edu, u_edu, s.get(Case, cl.cases["health_rec_edu"]))
        assert row.role == "watcher"
        s.flush()
        item = by_entry(rows(s, world, "edu_admin"))[str(cl.entries["e_health"])]
        assert item["claimable"] is False and item["held_by_you"] == "watcher"
        s.rollback()


def test_row_without_case_never_claimable(world, cl):
    with world.Session() as s:
        for key in ROLES:
            item = by_entry(rows(s, world, key))[str(cl.entries["e_nocase"])]
            assert item["case"] is None and item["claimable"] is False and item["visible"] is False
            assert item["in_pool"] is False and item["owner_office_code"] is None


def test_merged_case_rows_point_to_survivor(world, cl):
    with world.Session() as s:
        item = by_entry(rows(s, world, "edu_admin"))[str(cl.entries["e_merged"])]
        assert item["case"]["id"] == cl.cases["survivor"]
        assert item["claimable"] is True  # the survivor is in the pool
        survivor = s.get(Case, cl.cases["survivor"])
        survivor.merged_into_case_id = cl.cases["pool2"]  # a chain: the row's case is merged again
        s.flush()
        item = by_entry(rows(s, world, "edu_admin"))[str(cl.entries["e_merged"])]
        assert item["claimable"] is False
        s.rollback()


def test_only_filters_each_value(world, cl):
    e = {k: str(v) for k, v in cl.entries.items()}
    with world.Session() as s:

        def got(key, only):
            return {str(i["id"]) for i in rows(s, world, key, only=only)["items"]}

        assert got("edu_admin", "recommended") == {e["e_rec_both"], e["e_health"]}
        assert got("edu_admin", "mine") == {e["e_connected"]}
        assert got("edu_admin", "claimable") == {
            e["e_court2"],
            e["e_pool"],
            e["e_rec_both"],
            e["e_health"],
            e["e_merged"],
            e["e_supp"],
            e["e_lawazima"],
        }
        assert got("edu_admin", "unclaimed") == got("edu_admin", "claimable") - {e["e_health"]}
        assert got("edu_admin", "claimed") == {e["e_connected"], e["e_health"]}
        assert got("dse_user", "visible") == set()
        assert len(got("central_op", "visible")) == 8  # every row with a case
        assert got("edu_off1", "claimable") == set()


def test_counts_ignore_q_and_only(world, cl):
    with world.Session() as s:
        full = rows(s, world, "edu_admin")
        narrowed = rows(s, world, "edu_admin", q="ANIMA", only="claimable")
        assert narrowed["total"] == 1
        assert narrowed["counts"] == full["counts"]
        assert full["counts"] == {
            "entries": 9,
            "recommended": 2,
            "mine": 1,
            "claimable": 7,
            "claimed": 2,
            "unclaimed": 6,
        }
        bench = rows(s, world, "edu_admin", bench_id=1854)
        assert bench["counts"]["entries"] == 7 and bench["total"] == 7


def test_words_cnr_case_number_and_prefixes_on_printed_text(world, cl):
    e = {k: str(v) for k, v in cl.entries.items()}
    with world.Session() as s:

        def got(q):
            return {str(i["id"]) for i in rows(s, world, "edu_admin", q=q)["items"]}

        assert got("SC, REV") == {e["e_pool"]}
        assert got("sc rev") == {e["e_pool"]}
        assert got("VENUE") == set()
        assert got("deka") == {e["e_pool"]}  # advocate text, after a line break
        assert got("bora") == {e["e_pool"], e["e_rec_both"]}  # a word prefix: BORA and BORAH
        assert got("anima bor") == {e["e_rec_both"]}
        pool = s.get(Case, cl.cases["pool"])
        assert got(pool.cnr) == {e["e_pool"], e["e_lawazima"]}
        assert got(pool.case_no_text) == {e["e_pool"], e["e_lawazima"]}
        assert got("WP(C)/999/2026") == {e["e_nocase"]}
        assert got(pool.ref_no) == {e["e_pool"], e["e_lawazima"]}
        assert got("no case petitioner") == {e["e_nocase"]}
        for bad in ("ab", "  ", "%%%"):
            if bad.strip():
                with pytest.raises(cv.CauselistViewError):
                    rows(s, world, "edu_admin", q=bad)


def test_bench_and_list_filters_and_conflict_400(world, cl):
    with world.Session() as s:
        assert rows(s, world, "edu_admin", bench_id=2048)["total"] == 1
        assert rows(s, world, "edu_admin", list_id=cl.lists["supp"])["total"] == 1
        assert rows(s, world, "edu_admin", bench_id=1854, list_type="supplementary")["total"] == 1
        assert rows(s, world, "edu_admin", court_no=" 111 ")["total"] == 1
        assert rows(s, world, "edu_admin", court_no="2")["total"] == 1
        assert rows(s, world, "edu_admin", D3, list_id=cl.lists["website"])["total"] == 1
        with pytest.raises(cv.CauselistViewError):
            rows(s, world, "edu_admin", bench_id=1854, list_id=cl.lists["daily"])
        with pytest.raises(cv.CauselistViewError):
            rows(s, world, "edu_admin", list_type="weekly")
        with pytest.raises(cv.CauselistViewError):
            rows(s, world, "edu_admin", only="everything")
        with pytest.raises(cv.CauselistViewError):
            rows(s, world, "edu_admin", court_no="1" * 21)


def test_list_of_another_date_400(world, cl):
    with world.Session() as s:
        with pytest.raises(cv.CauselistViewError):
            rows(s, world, "edu_admin", D2, list_id=cl.lists["prev"])


def test_limit_and_offset_bounds(world, cl):
    with world.Session() as s:
        user = world.user(s, "edu_admin")
        first = cv.entries(s, user, D2, limit=4)
        second = cv.entries(s, user, D2, limit=4, offset=4)
        assert first["total"] == second["total"] == 9
        assert len(first["items"]) == 4 and len(second["items"]) == 4
        assert {i["id"] for i in first["items"]}.isdisjoint({i["id"] for i in second["items"]})
        assert len(cv.entries(s, user, D2)["items"]) == 9
        for bad in ({"limit": 0}, {"limit": 501}, {"offset": -1}):
            with pytest.raises(cv.CauselistViewError):
                cv.entries(s, user, D2, **bad)


def test_reading_writes_nothing(world, cl, tmp_path):
    def counts(s):
        return tuple(
            int(s.scalar(sa.select(sa.func.count()).select_from(t)) or 0)
            for t in (AuditLog, Event, NapixCallLog, FetchQueueItem)
        )

    store = LocalStore(tmp_path / "store")
    with world.Session() as s:
        before = counts(s)
        for key in ROLES:
            user = world.user(s, key)
            cv.dates(s, today=D2)
            cv.day(s, D2)
            cv.day(s, date(2026, 10, 18))
            for only in (None, *cv.ONLY_VALUES):
                cv.entries(s, user, D2, only=only, q="party")
            cv.list_file(s, user, cl.lists["daily"], store=store, disposition="inline")
        s.flush()
        assert counts(s) == before
