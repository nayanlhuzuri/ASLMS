"""Order sections in the database (design `order-sections`, "Tests", database): the job and its candidates, one parse
per shared PDF, court orders only, the replacements (text extracted again, parser version, text gone, document
changed) that keep the old rows, the trigger and the grants, the races, failures in `source_failures`, the live checks
with the common order, and the status block, check list and backfill."""

from __future__ import annotations

import hashlib
import uuid
from datetime import date

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

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
        counters = svc.read_batch(s, batch=10)
        assert counters["replaced_text_reextracted"] == 1
        old_row, new_row = o.readings(s, order)
        assert old_row.id == old.id and old_row.body_text == old_body
        assert old_row.replace_reason.value == "text_reextracted" and old_row.replaced_by_id == new_row.id
        assert old_row.replaced_at is not None and old_row.updated_at >= old_updated
        assert new_row.replaced_at is None and "Issue fresh notice" in new_row.body_text
        assert svc.read_batch(s, batch=10)["claimed"] == 0
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
        counters = svc.read_batch(s, batch=10)
        assert counters["text_gone"] == 1
        (row,) = o.readings(s, order)
        assert row.replace_reason.value == "text_gone" and row.replaced_by_id is None and row.replaced_at
        assert o.current(s, order) is None
        assert svc.read_batch(s, batch=10)["claimed"] == 0
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
        counters = svc.read_batch(s, batch=10)
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
        assert svc.read_batch(s, batch=10)["parsed"] == 1
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
    # batch 1: the two oldest fail for the first time and it goes on; batch 2: two readable orders (the failing ones
    # come last); batch 3: the last readable order and one retry; batch 4: two retries, none read, so it ends
    assert total["parsed"] == 3 and total["failed"] == 5 and total["retried"] == 3, (total, lines)
    assert len(lines) == 4
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
        assert svc.read_batch(s, batch=10)["parsed"] == 2
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
