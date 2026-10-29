"""Data Collection redesign, round 2 (design `data-collection-redesign`, decision 45): Problems and Fixes' Data Gaps.
The cases held without details with the state of their dossier row in any lane, the orders not available at the court
or failed, paging, the reader-only guard and the document-text block. Reads only: no row written, no court call."""

from __future__ import annotations

from datetime import date

import sqlalchemy as sa

from aslms.core.config import Settings
from aslms.domain.documents import DownloadStatus, Order, OrderKind
from aslms.domain.events import AuditLog
from aslms.domain.ops import FetchKind, FetchLane, FetchQueueItem, FetchStatus, NapixCallLog
from aslms.services import data_health, data_load
from tests.db import docs_support as ds
from tests.db.test_data_health import DOCUMENTS_TEXT, _seed_documents_text
from tests.db.world import make_case

CFG = Settings(_env_file=None)


def _dossier(s, ref: str, status: FetchStatus, *, lane=FetchLane.LOAD, last_error=None, attempts=0):
    s.add(
        FetchQueueItem(
            kind=FetchKind.DOSSIER,
            ref=ref,
            status=status,
            lane=lane,
            priority=41,
            last_error=last_error,
            attempts=attempts,
        )
    )
    s.flush()


def _order(s, case, no: str, d: date, status: DownloadStatus, *, document_id=None, last_error=None):
    order = Order(
        case_id=case.id,
        order_no=no,
        order_date=d,
        kind=OrderKind.INTERIM,
        download_status=status,
        document_id=document_id,
        last_error=last_error,
        download_attempts=2 if status == DownloadStatus.FAILED else 0,
    )
    s.add(order)
    s.flush()
    return order


def _by_ref(out) -> dict[str, dict]:
    return {i["case"]["ref_no"]: i for i in out["items"]}


def test_gaps_cases_states_being_fetched_not_found_failed_not_queued(world):
    with world.Session() as s:
        held = make_case(s)
        held.last_full_refresh_at = sa.func.now()
        none = make_case(s)  # no dossier row at all
        pending = make_case(s)
        _dossier(s, pending.cnr, FetchStatus.PENDING)
        running = make_case(s)
        _dossier(s, running.cnr, FetchStatus.RUNNING, lane=FetchLane.DAILY)
        skipped = make_case(s)
        _dossier(s, skipped.cnr, FetchStatus.SKIPPED, last_error="no record at the court")
        failed = make_case(s)
        _dossier(s, failed.cnr, FetchStatus.FAILED, last_error="NapixUnavailable: 502", attempts=5)
        done_no_details = make_case(s)  # a done row but no details: nothing waits for it
        _dossier(s, done_no_details.cnr, FetchStatus.DONE)
        # a provisional case is matched by `<est_code>|<case number>`, in the request lane
        prov = make_case(s)
        prov.cnr = None
        prov.is_provisional = True
        s.flush()
        _dossier(s, f"GAHC01|{prov.case_no_text}", FetchStatus.PENDING, lane=FetchLane.REQUEST)
        merged = make_case(s)
        merged.merged_into_case_id = held.id
        s.flush()

        out = data_load.gaps(s, CFG, "cases")
        assert out["kind"] == "cases"
        assert out["counts"] == {"being_fetched": 3, "not_found": 1, "failed": 1, "not_queued": 2}
        assert out["total"] == 7
        items = _by_ref(out)
        assert held.ref_no not in items and merged.ref_no not in items
        assert {ref: i["state"] for ref, i in items.items()} == {
            none.ref_no: "not_queued",
            pending.ref_no: "being_fetched",
            running.ref_no: "being_fetched",
            skipped.ref_no: "not_found",
            failed.ref_no: "failed",
            done_no_details.ref_no: "not_queued",
            prov.ref_no: "being_fetched",
        }
        assert items[failed.ref_no]["problem"] == "NapixUnavailable: 502"
        assert items[failed.ref_no]["attempts"] == 5
        assert items[skipped.ref_no]["problem"] == "no record at the court"
        assert items[pending.ref_no]["problem"] is None
        assert items[none.ref_no]["attempts"] is None
        assert items[prov.ref_no]["case"]["cnr"] is None
        assert items[none.ref_no]["first_seen_at"] is not None
        # the Overview's problem count is the same total
        assert data_load.overview(s, CFG)["problems"]["cases_without_details"] == out["total"]
        s.rollback()


def test_gaps_orders_not_available_and_failed(world, tmp_path):
    from tests.db.test_data_collection_overview import _stored_doc

    with world.Session() as s:
        a = make_case(s)
        b = make_case(s)
        na = _order(s, a, "1", date(2025, 3, 1), DownloadStatus.NOT_AVAILABLE)
        failed = _order(
            s, b, "2", date(2025, 4, 1), DownloadStatus.FAILED, last_error="HTTP 500 from the court"
        )
        _order(s, a, "3", date(2025, 5, 1), DownloadStatus.PENDING)  # waiting, not a gap
        doc = _stored_doc(s, tmp_path, date(2025, 6, 1))
        _order(s, a, "4", date(2025, 6, 1), DownloadStatus.STORED, document_id=doc.id)
        # a failed status with a stored PDF is not a gap
        _order(s, b, "5", date(2025, 6, 2), DownloadStatus.FAILED, document_id=doc.id)

        out = data_load.gaps(s, CFG, "orders")
        assert out["kind"] == "orders"
        assert out["counts"] == {"not_available": 1, "failed": 1}
        assert out["total"] == 2
        # latest order first
        assert [i["order_id"] for i in out["items"]] == [failed.id, na.id]
        first, second = out["items"]
        assert first == {
            "case": {"id": b.id, "ref_no": b.ref_no, "cnr": b.cnr, "case_no_text": b.case_no_text},
            "order_id": failed.id,
            "order_no": "2",
            "order_date": date(2025, 4, 1),
            "state": "failed",
            "attempts": 2,
            "problem": "HTTP 500 from the court",
        }
        assert second["state"] == "not_available" and second["problem"] is None
        ov = data_load.overview(s, CFG)["problems"]
        assert ov["orders_not_available"] + ov["orders_failed"] == out["total"]
        s.rollback()


def test_gaps_paged_and_reader_only(world, tmp_path):
    with world.Session() as s:
        cases = [make_case(s) for _ in range(5)]
        s.commit()
        refs = [c.ref_no for c in cases]
    with world.Session() as s:
        first = data_load.gaps(s, CFG, "cases", limit=2, offset=0)
        rest = data_load.gaps(s, CFG, "cases", limit=2, offset=2)
        last = data_load.gaps(s, CFG, "cases", limit=2, offset=4)
        assert first["total"] == rest["total"] == last["total"] == 5
        seen = [i["case"]["ref_no"] for page in (first, rest, last) for i in page["items"]]
        assert seen == list(reversed(refs))  # newest first, each once
        # the limit is clamped and a wrong kind is refused
        assert len(data_load.gaps(s, CFG, "cases", limit=10_000)["items"]) == 5
        try:
            data_load.gaps(s, CFG, "parties")
        except data_load.LoadInputError as exc:
            assert exc.code == "bad_input"
        else:  # pragma: no cover
            raise AssertionError("an unknown kind must be refused")

    def counts():
        with world.Session() as s:
            return (
                s.scalar(sa.select(sa.func.count()).select_from(FetchQueueItem)),
                s.scalar(sa.select(sa.func.count()).select_from(NapixCallLog)),
            )

    api = ds.make_api(world, tmp_path)
    try:
        before = counts()
        for key in ("root", "oversight", "central_op"):
            h = ds.login(api, key)
            r = api.get("/admin/data-load/gaps?kind=cases&limit=2&offset=2", headers=h)
            assert r.status_code == 200, (key, r.text)
            body = r.json()
            assert body["total"] == 5
            assert [i["case"]["ref_no"] for i in body["items"]] == list(reversed(refs))[2:4]
            r = api.get("/admin/data-load/gaps?kind=orders", headers=h)
            assert r.status_code == 200 and r.json()["items"] == [], key
        # a department user holds no reading function and gets nothing
        h = ds.login(api, "edu_off1")
        assert api.get("/admin/data-load/gaps", headers=h).status_code == 403
        assert api.get("/admin/data-load/gaps").status_code == 401
        h = ds.login(api, "root")
        assert api.get("/admin/data-load/gaps?kind=parties", headers=h).status_code == 422
        assert api.get("/admin/data-load/gaps?limit=201", headers=h).status_code == 422
        # the sign-ins write their own audit rows; the reads write nothing and call no court
        with world.Session() as s:
            audit_before = s.scalar(sa.select(sa.func.count()).select_from(AuditLog))
        assert api.get("/admin/data-load/gaps", headers=h).status_code == 200
        with world.Session() as s:
            assert s.scalar(sa.select(sa.func.count()).select_from(AuditLog)) == audit_before
        assert counts() == before
    finally:
        api.__exit__(None, None, None)


def test_gaps_include_documents_text(world):
    with world.Session() as s:
        empty = data_load.gaps(s, CFG, "orders")["documents_text"]
        assert empty == data_health.documents_text(s)
        assert set(empty) == {"order", "upload", "attachment"}
        _seed_documents_text(s, world)
        s.flush()
        for kind in ("cases", "orders"):
            assert data_load.gaps(s, CFG, kind)["documents_text"] == DOCUMENTS_TEXT
        s.rollback()


def test_gaps_slow_query_answers_503_search_timeout(world, tmp_path, monkeypatch):
    def slow(*_a, **_k):
        raise data_load.SearchTimeout("the data gaps took too long; try again")

    monkeypatch.setattr(data_load, "gaps", slow)
    api = ds.make_api(world, tmp_path)
    try:
        h = ds.login(api, "root")
        r = api.get("/admin/data-load/gaps?kind=cases", headers=h)
        assert r.status_code == 503, r.text
        assert "search_timeout" in r.text
    finally:
        api.__exit__(None, None, None)
