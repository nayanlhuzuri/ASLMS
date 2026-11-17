"""Order sections in the database (design `order-sections`, "Tests", database): the job and its candidates, one parse
per shared PDF, court orders only, the replacements (text extracted again, parser version, text gone, document
changed) that keep the old rows, the trigger and the grants, the races, failures in `source_failures`, the live checks
with the common order, and the status block, check list and backfill."""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import date, datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from aslms.core import clock
from aslms.domain.cases import Case
from aslms.domain.documents import (
    DocGroup,
    DocKind,
    Document,
    DocumentText,
    Order,
    OrderKind,
    OrderSection,
    ScanStatus,
    SourcetraceStatus,
    TextStatus,
    Visibility,
)
from aslms.domain.ops import JobRun, SourceFailure
from aslms.domain.reference import DocType
from aslms.services import order_parse as parse_mod
from aslms.services import order_parse_rules as R
from aslms.services import order_sections as svc
from aslms.services.reporting_common import with_timeout
from tests.db import next_dates_support as h
from tests.db import order_sections_support as o
from tests.db.world import make_case

D = date(2026, 1, 28)


def _case_order(s, *, cnr=None, case_no=None, text=None, day=D, **kw):
    case = make_case(s, cnr=cnr, case_no=case_no)
    body = text if text is not None else o.order_text(cnr=case.cnr, case_no=case.case_no_text, **kw)
    order = h.order_with_text(s, case, body, order_date=day)
    return case, order


def test_job_reads_new_orders_once_and_writes_job_run(world):
    with world.Session() as s:
        _, order = _case_order(s)
        counters = svc.run_job(s)
        assert counters["claimed"] == 1 and counters["parsed"] == 1 and counters["template"] == 1
        (row,) = o.readings(s, order)
        assert (
            row.layout.value == "template"
            and row.form.value == "interim"
            and row.parser_version == R.PARSER_VERSION
        )
        doc = o.doc_of(s, order)
        assert row.document_id == doc.id and row.pdf_sha256 == doc.sha256
        full = s.get(DocumentText, doc.id).full_text
        assert row.text_sha256 == hashlib.sha256(full.encode()).hexdigest() and row.text_chars == len(full)
        assert row.body_text.startswith("Heard Mr. Advocate A") and "PETITIONER A" not in row.body_text
        run = s.scalar(sa.select(JobRun).where(JobRun.job == "order_sections"))
        assert run.status.value == "succeeded" and run.counters["parsed"] == 1
        # read once: the next run claims nothing
        assert svc.run_job(s)["claimed"] == 0
        assert len(o.readings(s, order)) == 1
        s.commit()  # the deferred self-reference is checked at commit


def test_shared_pdf_parsed_once_one_row_per_order(world, monkeypatch):
    calls = []
    real = parse_mod.parse

    def counting(text, **kw):
        calls.append(kw)
        return real(text, **kw)

    monkeypatch.setattr(parse_mod, "parse", counting)
    with world.Session() as s:
        case_a, order_a = _case_order(s)
        case_b = make_case(s)
        order_b = o.share_pdf(s, case_b, order_a)
        counters = svc.read_batch(s, batch=10)
        assert counters["parsed"] == 2 and len(calls) == 1
        ra, rb = o.current(s, order_a), o.current(s, order_b)
        assert ra.id != rb.id and ra.body_sha256 == rb.body_sha256 and ra.document_id == rb.document_id
        s.commit()


def test_only_court_orders_with_extracted_text_are_read(world):
    with world.Session() as s:
        case = make_case(s)
        text = o.order_text(cnr=case.cnr, case_no=case.case_no_text)
        pending = h.order_with_text(s, case, text, text_status=TextStatus.PENDING, order_no="p1")
        scanned = h.order_with_text(s, case, None, text_status=TextStatus.NONE, order_no="p2")
        filing = h.order_with_text(s, case, text, order_no="p3")
        o.doc_of(s, filing).doc_group = DocGroup.COURT_FILING
        listed = h.order_with_text(s, case, text, order_no="p4")
        cl = o.doc_of(s, listed)
        cl.kind = DocKind.CAUSELIST
        cl.sourcetrace_status = SourcetraceStatus.NOT_APPLICABLE
        s.flush()
        counters = svc.read_batch(s, batch=50)
        assert counters["claimed"] == 0
        for order in (pending, scanned, filing, listed):
            assert o.readings(s, order) == []
        s.rollback()


def test_reextracted_text_replaces_row_and_keeps_old(world):
    with world.Session() as s:
        _, order = _case_order(s)
        svc.read_batch(s, batch=10)
        s.commit()
        (old,) = o.readings(s, order)
        old_body, old_updated = old.body_text, old.updated_at
    with world.Session() as s:  # extraction runs again in a later transaction
        t = s.get(DocumentText, order.document_id)
        t.full_text = t.full_text.replace("Issue notice", "Issue fresh notice")
        s.commit()
    with world.Session() as s:
        assert svc.read_batch(s, batch=10)["claimed"] == 0  # a light run never looks at changed texts
        counters = svc.read_batch(s, batch=10, full=True)
        assert counters["replaced_text_reextracted"] == 1 and counters["full_check_found"] == 1
        old_row, new_row = o.readings(s, order)
        assert old_row.id == old.id and old_row.body_text == old_body
        assert old_row.replace_reason.value == "text_reextracted" and old_row.replaced_by_id == new_row.id
        assert old_row.replaced_at is not None and old_row.updated_at >= old_updated
        assert new_row.replaced_at is None and "Issue fresh notice" in new_row.body_text
        assert svc.read_batch(s, batch=10, full=True)["claimed"] == 0
        s.commit()


def test_parser_version_bump_replaces_gradually(world, monkeypatch):
    with world.Session() as s:
        _, first = _case_order(s)
        _, second = _case_order(s)
        svc.read_batch(s, batch=10)
        s.commit()
    monkeypatch.setattr(R, "PARSER_VERSION", R.PARSER_VERSION + 1)
    with world.Session() as s:
        assert svc.read_batch(s, batch=1)["replaced_parser_version"] == 1
        s.commit()
    with world.Session() as s:
        assert svc.read_batch(s, batch=1)["replaced_parser_version"] == 1
        assert svc.read_batch(s, batch=1)["claimed"] == 0
        for order in (first, second):
            old_row, new_row = o.readings(s, order)
            assert (
                old_row.parser_version == R.PARSER_VERSION - 1 and new_row.parser_version == R.PARSER_VERSION
            )
            assert old_row.replace_reason.value == "parser_version"
        s.commit()


def test_text_gone_marks_replaced_without_successor(world):
    with world.Session() as s:
        _, order = _case_order(s)
        svc.read_batch(s, batch=10)
        o.doc_of(s, order).text_status = TextStatus.NONE
        s.flush()
        assert svc.read_batch(s, batch=10)["claimed"] == 0
        counters = svc.read_batch(s, batch=10, full=True)
        assert counters["text_gone"] == 1
        (row,) = o.readings(s, order)
        assert row.replace_reason.value == "text_gone" and row.replaced_by_id is None and row.replaced_at
        assert o.current(s, order) is None
        assert svc.read_batch(s, batch=10, full=True)["claimed"] == 0
        s.commit()


def test_document_changed_guard(world):
    with world.Session() as s:
        case, order = _case_order(s)
        svc.read_batch(s, batch=10)
        other = h.order_with_text(
            s, case, o.order_text(cnr=case.cnr, case_no=case.case_no_text, day="29.01.2026")
        )
        s.execute(sa.update(Order).where(Order.id == order.id).values(document_id=other.document_id))
        s.flush()
        counters = svc.read_batch(s, batch=10, full=True)
        assert counters["replaced_document_changed"] == 1
        old_row, new_row = o.readings(s, order)
        assert old_row.replace_reason.value == "document_changed" and new_row.document_id == other.document_id
        s.commit()


def test_trigger_forbids_changing_fixed_columns_and_second_replacement(world):
    with world.Session() as s:
        _, order = _case_order(s)
        svc.read_batch(s, batch=10)
        row = o.current(s, order)
        s.commit()
    with world.Session() as s:
        with pytest.raises(DBAPIError, match="never changes"):
            s.execute(sa.update(OrderSection).where(OrderSection.id == row.id).values(body_text="edited"))
        s.rollback()
    with world.Session() as s:
        s.execute(
            sa.update(OrderSection)
            .where(OrderSection.id == row.id)
            .values(replaced_at=sa.func.now(), replace_reason="text_gone")
        )
        s.commit()
    with world.Session() as s:
        with pytest.raises(DBAPIError, match="replaced once"):
            s.execute(
                sa.update(OrderSection)
                .where(OrderSection.id == row.id)
                .values(replace_reason="parser_version")
            )
        s.rollback()


def test_app_role_cannot_delete_order_sections(engine):
    with engine.connect() as conn:
        priv = lambda p: conn.execute(  # noqa: E731
            sa.text("SELECT has_table_privilege('aslms_app', 'order_sections', :p)"), {"p": p}
        ).scalar()
        assert priv("SELECT") and priv("INSERT") and priv("UPDATE")
        assert not priv("DELETE")
        assert conn.execute(
            sa.text("SELECT has_table_privilege('aslms_readonly', 'order_sections', 'SELECT')")
        ).scalar()
        assert (
            conn.execute(sa.text("SELECT obj_description('order_sections'::regclass)")).scalar()
            == "class=derived"
        )


def test_partial_unique_one_current_row_and_race_counts_skipped(world, monkeypatch):
    with world.Session() as s:
        _, order = _case_order(s)
        stale = svc.candidates(s, batch=10)
        svc.read_batch(s, batch=10)  # another reader got there first
        s.commit()
    monkeypatch.setattr(svc, "candidates", lambda *_a, **_k: stale)
    with world.Session() as s:
        counters = svc.read_batch(s, batch=10)
        assert counters["skipped"] == 1 and counters["failed"] == 0
        assert len(o.readings(s, order)) == 1
        s.commit()
    monkeypatch.undo()
    # a replacement race: the current row was replaced by another reader before this one's update
    monkeypatch.setattr(R, "PARSER_VERSION", R.PARSER_VERSION + 1)
    with world.Session() as s:
        stale = svc.candidates(s, batch=10)
        svc.read_batch(s, batch=10)
        s.commit()
    monkeypatch.setattr(svc, "candidates", lambda *_a, **_k: stale)
    with world.Session() as s:
        counters = svc.read_batch(s, batch=10)
        assert counters["skipped"] == 1
        assert len(o.readings(s, order)) == 2
        s.commit()
    with world.Session() as s:  # one current row per order
        n = s.scalar(
            sa.select(sa.func.count())
            .select_from(OrderSection)
            .where(OrderSection.order_id == order.id, OrderSection.replaced_at.is_(None))
        )
        assert n == 1


def test_failure_recorded_in_source_failures_and_resolved_on_success(world, monkeypatch):
    real = parse_mod.parse

    def broken(text, **kw):
        raise RuntimeError("reader bug")

    with world.Session() as s:
        _, order = _case_order(s)
        monkeypatch.setattr(parse_mod, "parse", broken)
        counters = svc.run_job(s)
        assert counters["failed"] == 1
        run = s.scalar(sa.select(JobRun).where(JobRun.job == "order_sections"))
        assert run.status.value == "partial"
        fail = s.scalar(sa.select(SourceFailure).where(SourceFailure.kind == "order_parse"))
        assert fail.ref == str(order.id) and "reader bug" in fail.error and fail.resolved_at is None
        monkeypatch.setattr(parse_mod, "parse", real)
        assert svc.read_batch(s, batch=10)["claimed"] == 0  # a light run never retries
        assert svc.read_batch(s, batch=10, full=True, retry=True)["parsed"] == 1
        s.refresh(fail)
        assert fail.resolved_at is not None
        s.commit()


def test_live_checks_cnr_case_no_date_form_and_common_order_suppresses_mismatch(world):
    with world.Session() as s:
        # the printed CNR, case number and date of another order: three mismatches; a judgment held as interim
        case = make_case(s, cnr="GAHC010000112025", case_no="WP(C)/11/2025")
        text = o.order_text(
            cnr="GAHC010000992025",
            case_no="WP(C)/99/2025",
            day="27.01.2026",
            heading="JUDGMENT",
            body=o.JUDGMENT_BODY,
        )
        bad = h.order_with_text(s, case, text, order_date=D)
        # a common order: case B's order is on case A's PDF, which prints A's CNR and case number
        case_a = make_case(s, cnr="GAHC010000212025", case_no="WP(C)/21/2025")
        order_a = h.order_with_text(
            s,
            case_a,
            o.order_text(cnr=case_a.cnr, case_no=case_a.case_no_text, linked=["WP(C)/22/2025"]),
            order_date=D,
        )
        case_b = make_case(s, cnr="GAHC010000222025", case_no="WP (C)/22/2025")
        order_b = o.share_pdf(s, case_b, order_a)
        # a linked case on its own PDF: its number is among the printed Linked Case entries
        case_c = make_case(s, cnr="GAHC010000232025", case_no="WP(C)/23/2025")
        order_c = h.order_with_text(
            s,
            case_c,
            o.order_text(cnr="GAHC010000242025", case_no="WP(C)/24/2025", linked=["WP(C)/23/2025"]),
            order_date=D,
        )
        svc.read_batch(s, batch=50)
        assert set(svc.checks_for(s, bad.id)) == {
            "cnr_differs",
            "case_no_differs",
            "date_differs",
            "form_differs",
        }
        assert svc.checks_for(s, order_a.id) == []
        assert svc.checks_for(s, order_b.id) == ["common_order"]
        assert svc.checks_for(s, order_c.id) == ["common_order"]
        # the case number is compared compacted (no spaces, upper case)
        case_b.case_no_text = "wp(c)/21/2025"
        s.flush()
        assert "case_no_differs" not in svc.checks_for(s, order_b.id)
        s.rollback()


def test_checks_follow_a_corrected_case_without_rewriting_rows(world):
    with world.Session() as s:
        case = make_case(s, cnr="GAHC010000312025", case_no="WP(C)/31/2025")
        order = h.order_with_text(
            s, case, o.order_text(cnr="GAHC010000322025", case_no="WP(C)/31/2025"), order_date=D
        )
        svc.read_batch(s, batch=10)
        s.commit()
        row = o.current(s, order)
        before = (row.id, row.updated_at, row.printed_cnr)
        assert svc.checks_for(s, order.id) == ["cnr_differs"]
        s.execute(sa.update(Case).where(Case.id == case.id).values(cnr="GAHC010000322025"))
        s.commit()
        assert svc.checks_for(s, order.id) == []
        row = o.current(s, order)
        assert (row.id, row.updated_at, row.printed_cnr) == before


def test_orders_and_cases_never_written_by_the_reader(world):
    with world.Session() as s:
        case, order = _case_order(s, day=date(2026, 1, 1))  # the printed date differs from the held one
        s.commit()
        snap = lambda: (  # noqa: E731
            s.execute(sa.select(Order.__table__).where(Order.id == order.id)).one(),
            s.execute(sa.select(Case.__table__).where(Case.id == case.id)).one(),
        )
        before = snap()
        svc.run_job(s)
        s.commit()
        assert snap() == before
        assert "date_differs" in svc.checks_for(s, order.id)


def test_status_block_counts(world):
    with world.Session() as s:
        _case_order(s)
        _, judgment = _case_order(s, heading="JUDGMENT", body=o.JUDGMENT_BODY)
        _case_order(s, text=o.order_text(cnr=None, case_no=None, day="x").replace("BEFORE\n", ""))
        h.order_with_text(s, make_case(s), "Page No.# 1/1\nBEFORE\nJUDGE", text_status=TextStatus.PENDING)
        before = svc.status(s)
        assert before["orders_with_text"] == 3 and before["read"] == 0 and before["waiting"] == 3
        svc.run_job(s)
        st = svc.status(s)
        assert st["parser_version"] == R.PARSER_VERSION
        assert st["orders_with_text"] == 3 and st["read"] == 3 and st["waiting"] == 0 and st["failed"] == 0
        assert st["by_layout"] == {"template": 2, "whole": 1}
        assert st["by_form"]["judgment"] == 1 and st["by_form"]["interim"] == 2
        assert st["with_outcome"] == 1 and st["with_directions"] == 1
        assert st["procedural"] >= 1 and st["registrar"] == 0
        assert st["distinct_bodies"] == 3
        assert (
            st["flags"]["off_template"] == 1
            and st["flags"]["no_cnr_line"] == 1
            and st["flags"]["no_case_no"] == 1
        )
        assert set(st["checks"]) == set(svc.CHECKS)
        assert st["last_run"]["status"] == "succeeded" and st["last_run"]["counters"]["parsed"] == 3
        del judgment
        s.rollback()


def test_check_rows_paging_and_check_filter(world):
    with world.Session() as s:
        orders = []
        for n in range(3):
            case = make_case(s, cnr=f"GAHC0100004{n}2025", case_no=f"WP(C)/4{n}/2025")
            orders.append(
                h.order_with_text(
                    s,
                    case,
                    o.order_text(
                        cnr=f"GAHC0100005{n}2025", case_no=case.case_no_text, day=f"{10 + n}.01.2026"
                    ),
                    order_date=date(2026, 1, 10 + n),
                )
            )
        _case_order(s)  # clean: not listed
        _case_order(
            s, text=o.order_text(cnr=None, case_no="WP(C)/1/2026"), day=date(2026, 1, 1)
        )  # a flag only
        svc.read_batch(s, batch=50)
        total, counts, items = svc.check_rows(s, limit=2)
        assert total == 4 and len(items) == 2
        assert counts["cnr_differs"] == 3 and counts["no_cnr_line"] == 1
        assert items[0]["order_date"] == date(2026, 1, 12) and items[0]["checks"] == ["cnr_differs"]
        assert (
            items[0]["printed"]["cnr"] == "GAHC010000522025" and items[0]["held"]["cnr"] == "GAHC010000422025"
        )
        assert set(items[0]) == {
            "case",
            "order_id",
            "order_no",
            "order_date",
            "kind",
            "form",
            "checks",
            "flags",
            "printed",
            "held",
        }
        assert "body_text" not in str(items) and "PETITIONER" not in str(items)
        total, _, items = svc.check_rows(s, check="cnr_differs", limit=10, offset=1)
        assert total == 3 and len(items) == 2
        total, _, items = svc.check_rows(s, check="no_cnr_line")
        assert total == 1 and items[0]["flags"] == ["no_cnr_line"]
        with pytest.raises(svc.CheckInputError):
            svc.check_rows(s, check="nonsense")
        assert orders
        s.rollback()


def test_backfill_commits_per_batch_resumes_and_dry_run_writes_nothing(world):
    with world.Session() as s:
        for _ in range(5):
            _case_order(s)
        s.commit()
    lines: list[str] = []
    svc.DRY_STATS.reset()
    dry = svc.backfill(world.Session, batch=2, pause_ms=0, limit=5, dry_run=True, echo=lines.append)
    assert dry["claimed"] == 5 and dry["parsed"] == 5 and svc.DRY_STATS.as_dict()["by_form"] == {"interim": 5}
    with world.Session() as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(OrderSection)) == 0
    # stopped after one batch of two (a limit), then started again: it carries on
    first = svc.backfill(world.Session, batch=2, pause_ms=0, limit=2)
    assert first["parsed"] == 2
    with world.Session() as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(OrderSection)) == 2
    rest = svc.backfill(world.Session, batch=2, pause_ms=0, echo=lines.append)
    assert rest["parsed"] == 3 and any("batch:" in line for line in lines)
    with world.Session() as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(OrderSection)) == 5
        assert svc.status(s)["waiting"] == 0


def test_backfill_ends_when_only_failing_orders_are_left_and_they_never_starve_new_ones(world, monkeypatch):
    """An order whose text always makes the reader fail is claimed after every readable order, the backfill stops
    once only such orders are left, and the 5-minute job still reads newer orders past a full batch of them."""
    real = parse_mod.parse

    def flaky(text, **kw):
        if "UNREADABLE MARKER" in text:
            raise RuntimeError("reader bug")
        return real(text, **kw)

    monkeypatch.setattr(parse_mod, "parse", flaky)
    with world.Session() as s:
        broken = []
        for _ in range(2):  # the oldest orders: they would come first in set 1
            _, order = _case_order(s, body=o.BODY + " UNREADABLE MARKER.")
            broken.append(order.id)
        for _ in range(3):
            _case_order(s)
        s.commit()
    lines: list[str] = []
    total = svc.backfill(world.Session, batch=2, pause_ms=0, echo=lines.append)
    # light batches: 1, the two oldest fail for the first time and it goes on; 2, two readable orders (the failing
    # ones are left out); 3, the last readable order; 4, nothing. Then one full batch: the two retries, none read, so
    # it ends
    assert total["parsed"] == 3 and total["failed"] == 4 and total["retried"] == 2, (total, lines)
    assert len(lines) == 5 and lines[-1].startswith("full batch: 2 claimed")
    with world.Session() as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(OrderSection)) == 3
        st = svc.status(s)
        assert st["waiting"] == 0 and st["failed"] == 2
        refs = set(
            s.scalars(
                sa.select(SourceFailure.ref).where(
                    SourceFailure.kind == "order_parse", SourceFailure.resolved_at.is_(None)
                )
            )
        )
        assert refs == {str(i) for i in broken}
        # a full batch of failing orders does not keep a newer order out of the job
        _, newer = _case_order(s)
        counters = svc.run_job(s, cfg=svc.get_settings().model_copy(update={"order_sections_batch": 2}))
        assert counters["parsed"] == 1 and counters["failed"] == 1
        assert len(o.readings(s, newer)) == 1
        # once the reader is fixed, the failing orders are read and their failures resolved
        monkeypatch.setattr(parse_mod, "parse", real)
        assert svc.read_batch(s, batch=10, full=True, retry=True)["parsed"] == 2
        assert svc.status(s)["failed"] == 0
        s.commit()


def test_order_document_is_court_record_order_only(world):
    """A court record of another kind that an order cannot point at in practice (an upload's text) is never read."""
    with world.Session() as s:
        case = make_case(s)
        sha = hashlib.sha256(uuid.uuid4().bytes).hexdigest()
        doc = Document(
            sha256=sha,
            storage_key=f"sha256/{sha[:2]}/{sha}",
            mime="application/pdf",
            size_bytes=10,
            kind=DocKind.ORDER,
            doc_type=DocType.ORDER,
            doc_group=DocGroup.INTERNAL,
            case_id=case.id,
            visibility=Visibility.CASE_SCOPE,
            virus_scan_status=ScanStatus.SKIPPED,
            text_status=TextStatus.EXTRACTED,
            sourcetrace_status=SourcetraceStatus.NOT_APPLICABLE,
        )
        s.add(doc)
        s.flush()
        s.add(
            DocumentText(document_id=doc.id, full_text=o.order_text(cnr=case.cnr, case_no=case.case_no_text))
        )
        s.add(Order(case_id=case.id, order_no="1", order_date=D, kind=OrderKind.INTERIM, document_id=doc.id))
        s.flush()
        assert svc.read_batch(s, batch=10)["claimed"] == 0
        s.rollback()


# ------------------------------------------------------------------------------------------------ the job, version 2
# design `order-sections-review-advisories`, decisions 6 to 12


def _ist(day: date, hh: int, mm: int) -> datetime:
    return datetime(day.year, day.month, day.day, hh, mm, tzinfo=clock.IST)


TODAY = date(2026, 11, 16)
YESTERDAY = date(2026, 11, 15)


def _ymd(d: date) -> int:
    return d.year * 10000 + d.month * 100 + d.day


def _prev_run(s, counters: dict, at: datetime) -> None:
    s.add(
        JobRun(job="order_sections", run_date=at.date(), started_at=at, status="succeeded", counters=counters)
    )
    s.flush()


class _Statements:
    """The SQL statements run on the session's connection while the block runs."""

    def __init__(self, s):
        self.conn = s.connection()
        self.sql: list[str] = []

    def __enter__(self):
        sa.event.listen(self.conn, "before_cursor_execute", self._add)
        return self

    def __exit__(self, *exc):
        sa.event.remove(self.conn, "before_cursor_execute", self._add)

    def _add(self, conn, cursor, statement, params, context, many):
        self.sql.append(" ".join(statement.split()))

    def kinds(self) -> set[str]:
        out = set()
        for q in self.sql:
            if "FROM orders JOIN documents" in q and "order_sections_1.replaced_at IS NULL" in q:
                out.add("set1")
            if "order_sections.parser_version <" in q and "FROM order_sections JOIN orders" in q:
                out.add("set4")
            if "order_sections.document_id != orders.document_id" in q:
                out.add("set2or3")
            if "convert_to" in q:
                out.add("set3")
            if "document_text.document_id = orders.document_id" in q:
                out.add("set5")
            if q.startswith("SELECT 1 FROM source_failures"):
                out.add("retry_probe")
            if q.startswith("UPDATE source_failures SET resolved_at") and "NOT (EXISTS" in q:
                out.add("stale")
        return out


def test_light_run_queries_only_sets_1_and_4(world):
    """Decision 6: a light run (full check done today) issues set 1 and, while its gate is open, set 4; never set 2,
    3 or 5, the retry probe or the stale-failure update."""
    with world.Session() as s:
        _case_order(s)
        _prev_run(s, {"full_check_on": _ymd(TODAY)}, _ist(TODAY, 1, 33))
        with _Statements(s) as st:
            counters = svc.run_job(s, now=_ist(TODAY, 10, 3))
        assert counters["parsed"] == 1 and counters["full_check"] == 0
        assert st.kinds() == {"set1", "set4"}, st.sql
        assert counters["version_clear"] == R.PARSER_VERSION  # set 4 came back short
        with _Statements(s) as st:
            svc.run_job(s, now=_ist(TODAY, 10, 8))
        assert st.kinds() == {"set1"}, st.sql  # set 4 behind its gate now
        s.rollback()


def test_set_4_gate_skipped_after_a_clear_run_and_reopened_by_a_version_bump(world, monkeypatch):
    with world.Session() as s:
        _, order = _case_order(s)
        _prev_run(s, {"full_check_on": _ymd(TODAY)}, _ist(TODAY, 1, 33))
        first = svc.run_job(s, now=_ist(TODAY, 9, 3))
        assert first["parsed"] == 1 and first["version_clear"] == R.PARSER_VERSION
        asked: list[int] = []
        real = svc._set_current
        monkeypatch.setattr(svc, "_set_current", lambda n, *a, **k: asked.append(n) or real(n, *a, **k))
        second = svc.run_job(s, now=_ist(TODAY, 9, 8))
        assert asked == [] and second["version_clear"] == R.PARSER_VERSION and second["claimed"] == 0
        # a deploy that raises the version: the previous `version_clear` no longer equals it, so set 4 runs
        monkeypatch.setattr(R, "PARSER_VERSION", R.PARSER_VERSION + 1)
        third = svc.run_job(s, now=_ist(TODAY, 9, 13))
        assert asked == [4] and third["replaced_parser_version"] == 1
        assert third["version_clear"] == R.PARSER_VERSION
        old_row, new_row = o.readings(s, order)
        assert old_row.replace_reason.value == "parser_version" and new_row.parser_version == R.PARSER_VERSION
        s.rollback()


def test_full_check_once_a_day_after_0130_ist_repeated_while_batch_full(world):
    cfg = svc.get_settings().model_copy(update={"order_sections_batch": 1})
    with world.Session() as s:
        orders = [_case_order(s)[1] for _ in range(2)]
        svc.read_batch(s, batch=10)
        for order in orders:  # both texts change by hand
            t = s.get(DocumentText, order.document_id)
            t.full_text = t.full_text.replace("Issue notice", "Issue fresh notice")
        s.flush()
        _prev_run(s, {"full_check_on": _ymd(YESTERDAY), "version_clear": R.PARSER_VERSION}, _ist(TODAY, 0, 3))
        early = svc.run_job(s, cfg=cfg, now=_ist(TODAY, 1, 28))  # before 01:30: yesterday's check stands
        assert (
            early["full_check"] == 0 and early["claimed"] == 0 and early["full_check_on"] == _ymd(YESTERDAY)
        )
        due = svc.run_job(s, cfg=cfg, now=_ist(TODAY, 1, 33))
        assert (
            due["full_check"] == 1 and due["replaced_text_reextracted"] == 1 and due["full_check_found"] == 1
        )
        assert due["full_check_on"] == _ymd(YESTERDAY)  # it filled the batch: still due
        again = svc.run_job(s, cfg=cfg, now=_ist(TODAY, 1, 38))
        assert again["full_check"] == 1 and again["replaced_text_reextracted"] == 1
        assert again["full_check_on"] == _ymd(YESTERDAY)
        done = svc.run_job(s, cfg=cfg, now=_ist(TODAY, 1, 43))
        assert done["full_check"] == 1 and done["claimed"] == 0 and done["full_check_on"] == _ymd(TODAY)
        later = svc.run_job(s, cfg=cfg, now=_ist(TODAY, 1, 48))
        assert later["full_check"] == 0 and later["full_check_on"] == _ymd(TODAY)
        assert later["full_check_found"] == 0  # the last full check's figure, carried forward
        st = svc.status(s)
        assert st["full_check"] == {"last_on": TODAY, "found": 0}
        # the next day, at 01:33 again
        assert svc.run_job(s, cfg=cfg, now=_ist(date(2026, 11, 17), 1, 33))["full_check"] == 1
        s.rollback()


def test_full_check_runs_set_4_without_the_gate(world, monkeypatch):
    with world.Session() as s:
        _, order = _case_order(s)
        svc.read_batch(s, batch=10)
        monkeypatch.setattr(R, "PARSER_VERSION", R.PARSER_VERSION + 1)
        # a reading left below the version while the gate says clear (written by an older process during a deploy)
        _prev_run(s, {"full_check_on": _ymd(YESTERDAY), "version_clear": R.PARSER_VERSION}, _ist(TODAY, 0, 3))
        light = svc.run_job(s, now=_ist(TODAY, 1, 8))
        assert light["full_check"] == 0 and light["claimed"] == 0
        full = svc.run_job(s, now=_ist(TODAY, 1, 33))
        assert full["full_check"] == 1 and full["replaced_parser_version"] == 1
        assert o.current(s, order).parser_version == R.PARSER_VERSION
        s.rollback()


def test_same_text_reextracted_writes_no_new_row(world):
    with world.Session() as s:
        _, order = _case_order(s)
        svc.read_batch(s, batch=10)
        s.commit()
    with world.Session() as s:  # extracted again later with the same characters: a newer `updated_at`
        s.execute(
            sa.update(DocumentText)
            .where(DocumentText.document_id == order.document_id)
            .values(full_text=DocumentText.full_text, updated_at=sa.func.now() + sa.text("interval '1 hour'"))
        )
        s.commit()
    with world.Session() as s:
        assert svc.read_batch(s, batch=10, full=True)["claimed"] == 0
        assert len(o.readings(s, order)) == 1


def test_changed_text_committed_after_the_reading_is_found_by_hash(world):
    """The race of point 3: the extraction's transaction stamps `updated_at` before the reading is written and commits
    after it, so `updated_at` is older than the reading; the hash still finds the change."""
    with world.Session() as s:
        _, order = _case_order(s)
        s.commit()
    with world.Session() as extractor, world.Session() as reader:
        t = extractor.get(DocumentText, order.document_id)
        t.full_text = t.full_text.replace("Issue notice", "Issue fresh notice")
        extractor.flush()  # not committed yet
        assert svc.read_batch(reader, batch=10)["parsed"] == 1  # reads the old text
        reader.commit()
        extractor.commit()
    with world.Session() as s:
        (old,) = o.readings(s, order)
        assert s.get(DocumentText, order.document_id).updated_at < old.created_at
        counters = svc.read_batch(s, batch=10, full=True)
        assert counters["replaced_text_reextracted"] == 1
        old_row, new_row = o.readings(s, order)
        assert (
            old_row.replace_reason.value == "text_reextracted" and "Issue fresh notice" in new_row.body_text
        )
        s.commit()


def test_sql_text_hash_equals_python_hash_on_assamese_text_and_form_feeds(world):
    text = "Page No.# 1/2\nগুৱাহাটী উচ্চ ন্যায়ালয়  — “quoted”\n\fPage No.# 2/2\nমোকৰ্দমা ১২৩/২০২৬\tend"
    with world.Session() as s:
        case = make_case(s)
        order = h.order_with_text(s, case, text)
        sql = s.scalar(sa.select(svc._text_sha_sql()).where(DocumentText.document_id == order.document_id))
        assert sql == hashlib.sha256(text.encode("utf-8")).hexdigest()
        svc.read_batch(s, batch=10)
        assert o.current(s, order).text_sha256 == sql
        assert svc.read_batch(s, batch=10, full=True)["claimed"] == 0  # the hash agrees: nothing changed
        s.rollback()


def test_failing_order_retried_only_in_full_check_backfill_and_order_option(world, monkeypatch):
    calls: list[str] = []
    real = parse_mod.parse

    def broken(text, **kw):
        calls.append("parse")
        raise RuntimeError("reader bug")

    monkeypatch.setattr(parse_mod, "parse", broken)
    with world.Session() as s:
        _, order = _case_order(s)
        _prev_run(s, {"full_check_on": _ymd(TODAY), "version_clear": R.PARSER_VERSION}, _ist(TODAY, 1, 33))
        assert svc.run_job(s, now=_ist(TODAY, 9, 3))["failed"] == 1  # the first failure
        for minute in (8, 13, 18):  # light runs: never retried
            assert svc.run_job(s, now=_ist(TODAY, 9, minute))["claimed"] == 0
        assert len(calls) == 1
        nxt = svc.run_job(s, now=_ist(date(2026, 11, 17), 1, 33))  # the next day's full check retries it
        assert nxt["retried"] == 1 and nxt["failed"] == 1 and len(calls) == 2
        assert svc.read_batch(s, batch=10, order_id=order.id)["retried"] == 1 and len(calls) == 3
        monkeypatch.setattr(parse_mod, "parse", real)
        assert svc.read_batch(s, batch=10, order_id=order.id)["parsed"] == 1
        s.commit()
    with world.Session() as s:  # the backfill's full batches retry too
        _, other = _case_order(s)
        s.commit()
    monkeypatch.setattr(parse_mod, "parse", broken)
    svc.backfill(world.Session, batch=5, pause_ms=0)
    monkeypatch.setattr(parse_mod, "parse", real)
    total = svc.backfill(world.Session, batch=5, pause_ms=0)
    assert total["retried"] == 1 and total["parsed"] == 1
    del other


def test_first_failure_logs_traceback_retries_log_one_line(world, monkeypatch, caplog):
    def broken(text, **kw):
        raise RuntimeError("reader bug")

    monkeypatch.setattr(parse_mod, "parse", broken)
    monkeypatch.setattr(
        svc.log, "disabled", False
    )  # alembic's logging setup in the migrated fixture disables it
    with world.Session() as s:
        _, order = _case_order(s)
        with caplog.at_level(logging.WARNING, logger=svc.log.name):
            svc.read_batch(s, batch=10)
        (first,) = [r for r in caplog.records if r.name == svc.log.name]
        assert (
            first.levelno == logging.ERROR
            and first.exc_info is not None
            and str(order.id) in first.getMessage()
        )
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger=svc.log.name):
            svc.read_batch(s, batch=10, full=True, retry=True)
        (again,) = [r for r in caplog.records if r.name == svc.log.name]
        assert again.levelno == logging.WARNING and again.exc_info is None
        assert (
            again.getMessage() == f"order sections: order {order.id} failed again (attempt 2): RuntimeError"
        )
        fail = s.scalar(sa.select(SourceFailure).where(SourceFailure.kind == "order_parse"))
        assert fail.attempts == 2 and fail.resolved_at is None
        s.rollback()


def test_open_failure_resolved_when_the_text_is_gone(world, monkeypatch):
    def broken(text, **kw):
        raise RuntimeError("reader bug")

    monkeypatch.setattr(parse_mod, "parse", broken)
    with world.Session() as s:
        _, gone = _case_order(s)
        _, kept = _case_order(s)
        svc.read_batch(s, batch=10)
        o.doc_of(s, gone).text_status = TextStatus.FAILED  # its text went
        s.flush()
        counters = svc.read_batch(s, batch=10, full=True, retry=True)
        assert counters["failures_resolved"] == 1 and counters["retried"] == 1
        open_refs = set(
            s.scalars(
                sa.select(SourceFailure.ref).where(
                    SourceFailure.kind == "order_parse", SourceFailure.resolved_at.is_(None)
                )
            )
        )
        assert open_refs == {str(kept.id)}
        assert svc.resolve_stale_failures(s) == 0
        s.rollback()


def test_backfill_light_then_full_and_ends_with_only_failing_orders(world, monkeypatch):
    real = parse_mod.parse

    def flaky(text, **kw):
        if "UNREADABLE MARKER" in text:
            raise RuntimeError("reader bug")
        return real(text, **kw)

    with world.Session() as s:
        _case_order(s, body=o.BODY + " UNREADABLE MARKER.")
        for _ in range(2):
            _case_order(s)
        s.commit()
    phases: list[tuple[bool, bool]] = []
    real_batch = svc.read_batch

    def spy(sess, **kw):
        phases.append((kw.get("full", False), kw.get("retry", False)))
        return real_batch(sess, **kw)

    monkeypatch.setattr(parse_mod, "parse", flaky)
    monkeypatch.setattr(svc, "read_batch", spy)
    lines: list[str] = []
    total = svc.backfill(world.Session, batch=2, pause_ms=0, echo=lines.append)
    # light: 2 claimed (one fails), 1 read, then nothing; full: the one retry, none read, the end
    assert phases == [(False, False), (False, False), (False, False), (True, True)], (phases, lines)
    assert total["parsed"] == 2 and total["failed"] == 2 and total["retried"] == 1
    with world.Session() as s:
        st = svc.status(s)
        assert st["read"] == 2 and st["waiting"] == 0 and st["failed"] == 1


def test_src_text_returns_none_when_text_hash_differs(world):
    with world.Session() as s:
        _, order = _case_order(s)
        svc.read_batch(s, batch=10)
        row = o.current(s, order)
        full = s.get(DocumentText, order.document_id).full_text
        span = row.spans["case_no"]
        assert svc.src_text(row, full, span).startswith("Case No. :")
        assert svc.text_matches(row, full)
        changed = full.replace("Issue notice", "Issue fresh notice")
        assert svc.src_text(row, changed, span) is None and not svc.text_matches(row, changed)
        assert svc.src_text(row, None, span) is None
        s.rollback()


def test_status_part_timeout_gives_partial_block_and_outer_timeout_restored(world, monkeypatch):
    real = svc.checks_pass

    def slow(session):
        session.execute(sa.text("SELECT pg_sleep(2)"))
        return real(session)

    monkeypatch.setattr(svc, "checks_pass", slow)
    with world.Session() as s:
        _case_order(s)
        svc.read_batch(s, batch=10)
        with_timeout(s, 30)
        st = svc.status(s, timeout_s=1, restore_s=30)
        assert st["timed_out"] == ["checks"] and st["checks"] is None
        assert st["read"] == 1 and st["by_layout"]["template"] == 1 and st["failed"] == 0
        # the transaction goes on, under the report timeout again
        assert s.scalar(sa.text("SHOW statement_timeout")) == "30s"
        assert s.scalar(sa.text("SELECT 1 FROM pg_sleep(1.2)")) == 1
        s.rollback()


def test_status_counts_and_checks_equal_the_version_1_definitions(world):
    """On the readings of the fixtures, the single passes give the numbers of the version 1 statements
    (`check_columns` per check, grouped counts per layout, form and flag)."""
    with world.Session() as s:
        case = make_case(s, cnr="GAHC010000112025", case_no="WP(C)/11/2025")
        h.order_with_text(
            s,
            case,
            o.order_text(cnr="GAHC010000992025", case_no="WP(C)/99/2025", day="27.01.2026", heading="JUDGMENT",
                         body=o.JUDGMENT_BODY),
            order_date=D,
        )  # fmt: skip
        case_a = make_case(s, cnr="GAHC010000212025", case_no="WP(C)/21/2025")
        order_a = h.order_with_text(
            s,
            case_a,
            o.order_text(cnr=case_a.cnr, case_no=case_a.case_no_text, linked=["WP(C)/22/2025"]),
            order_date=D,
        )
        o.share_pdf(s, make_case(s, cnr="GAHC010000222025", case_no="WP (C)/22/2025"), order_a)
        _case_order(s, text=o.order_text(cnr=None, case_no=None, day="x").replace("BEFORE\n", ""))
        _case_order(s)
        svc.read_batch(s, batch=50)
        stmt, cols = svc._check_select()
        sub = stmt.subquery()
        v1_checks = dict(
            zip(
                svc.CHECKS,
                s.execute(sa.select(*[sa.func.count().filter(sub.c[n]) for n in svc.CHECKS])).one(),
            )
        )
        p = svc.checks_pass(s)
        assert {n: p["counts"][n] for n in svc.CHECKS} == v1_checks
        cur = OrderSection.replaced_at.is_(None)
        v1_flags = dict.fromkeys(svc.FLAGS, 0)
        flag = sa.func.unnest(OrderSection.flags).label("flag")
        fsub = sa.select(flag).where(cur).subquery()
        for f, n in s.execute(sa.select(fsub.c.flag, sa.func.count()).group_by(fsub.c.flag)).all():
            v1_flags[f.value if hasattr(f, "value") else f] = n
        assert {f: p["counts"][f] for f in svc.FLAGS} == v1_flags
        v1_any = s.scalar(
            sa.select(sa.func.count())
            .select_from(sub.join(OrderSection, OrderSection.id == sub.c.section_id))
            .where(
                sa.or_(
                    *[sub.c[n] for n in svc.CHECKS if n != "common_order"],
                    sa.func.cardinality(OrderSection.flags) > 0,
                )
            )
        )
        assert p["any"] == v1_any and v1_any >= 2
        st = svc.status(s)
        for col, key in ((OrderSection.layout, "by_layout"), (OrderSection.form, "by_form")):
            got = {k: v for k, v in st[key].items() if v}
            v1 = {
                (k.value if hasattr(k, "value") else k): n
                for k, n in s.execute(sa.select(col, sa.func.count()).where(cur).group_by(col)).all()
            }
            assert got == v1, key
        assert st["flags"] == v1_flags and st["checks"] == v1_checks
        assert st["read"] == s.scalar(sa.select(sa.func.count()).select_from(OrderSection).where(cur))
        total, counts, _ = svc.check_rows(s, limit=1)
        assert total == v1_any and counts == p["counts"]
        s.rollback()
