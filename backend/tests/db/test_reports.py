"""Reports (design `reports-dashboards`, "Tests", database): the four builders, the grouping by current owner,
the scope rules, visibility of the case rows, the statement timeout and that the builders only read."""

from __future__ import annotations

import io
import zipfile
from datetime import date, datetime, time, timedelta

import pymupdf
import pytest
import sqlalchemy as sa

from aslms.domain.alerts import AlertStatus
from aslms.domain.cases import CaseHearing, CaseStatus
from aslms.domain.causelists import Causelist, ListSource, ListType, ParseStatus
from aslms.domain.courts import Court
from aslms.domain.ops import FetchKind, FetchQueueItem, FetchStatus, NapixCallLog, SourceFailure
from aslms.domain.org import PermissionEffect
from aslms.domain.ownership import OwnershipRole, OwnershipTransfer
from aslms.domain.reference import Permission, Role
from aslms.domain.workflow import SourcetraceIngestion
from aslms.services import ownership as own
from aslms.services import report_export, reports
from aslms.services.access import Forbidden
from aslms.services.reporting_common import IST_ZONE, ReportConfig, ReportError, years_before
from aslms.services.storage import LocalStore
from tests.db.alerts_support import recommend
from tests.db.report_support import (
    claim,
    compliance_alert,
    dispose,
    listing,
    new_case,
    override,
    own_directly,
    row_counts,
    set_due,
    today,
)
from tests.db.st_support import upload_row
from tests.db.workflow_support import send
from tests.db.world import add_membership


def _xlsx_text(content: bytes) -> str:
    z = zipfile.ZipFile(io.BytesIO(content))
    return "".join(z.read(n).decode("utf-8", "replace") for n in z.namelist())


def _pdf_text(content: bytes) -> str:
    return "".join(p.get_text(flags=0) for p in pymupdf.open("pdf", content))


def _scope(s, world, key, report="pending-cases", department=None):
    return reports.resolve_scope(s, world.user(s, key), report, department)


def _section(report, key):
    return next(sec for sec in report.sections if sec.key == key)


def _row(section, **match):
    return next(r for r in section.rows if all(r[k] == v for k, v in match.items()))


def test_pending_cases_state_groups_by_department_court_age(world):
    with world.Session() as s:
        t = today()
        old = new_case(s)
        old.registration_date = years_before(t, 4)
        claim(s, world, old)
        unknown = new_case(s, status=CaseStatus.UNKNOWN)
        unknown.filing_date = t - timedelta(days=10)
        claim(s, world, unknown)
        provisional = new_case(s, cnr="")
        provisional.cnr = None
        provisional.is_provisional = True
        claim(s, world, provisional)  # no date at all: age not known
        watched = new_case(s)
        claim(s, world, watched, by="health_admin")
        own_directly(s, world, watched, "EDU", role=OwnershipRole.WATCHER)
        merged = new_case(s)
        claim(s, world, merged)
        merged.merged_into_case_id = old.id
        claimed_then_disposed = new_case(s)
        claim(s, world, claimed_then_disposed)
        dispose(s, claimed_then_disposed)
        rec = new_case(s)
        recommend(s, world, rec, "EDU")
        new_case(s)  # never owned, no recommendation
        s.flush()
        rep = reports.pending_cases(s, world.user(s, "oversight"), _scope(s, world, "oversight"), today=t)
        by_group = _section(rep, "by_group")
        edu = _row(by_group, group_code="EDU")
        assert edu["total"] == 3 and edu["pending"] == 2 and edu["unknown"] == 1
        assert edu["provisional"] == 1 and edu["watching"] == 1
        assert edu["age_3_5"] == 1 and edu["age_lt_1"] == 1 and edu["age_unknown"] == 1
        health = _row(by_group, group_code="HEALTH")
        assert health["total"] == 1 and health["watching"] == 0
        assert _row(by_group, group_code="NC-REC")["total"] == 1
        assert _row(by_group, group_code="NC-NONE")["total"] == 1
        assert [r["group_code"] for r in by_group.rows][-2:] == ["NC-REC", "NC-NONE"]
        assert _row(by_group, group_code="CENTRAL")["total"] == 0  # every Department-tier office has a row
        assert by_group.totals["total"] == 6  # merged and disposed excluded; the watched case counted once
        assert (
            by_group.totals["total"]
            == s.execute(
                sa.text(
                    "select count(*) from cases where status in ('pending','unknown') and merged_into_case_id is null"
                )
            ).scalar()
        )
        courts = _section(rep, "by_group_court")
        assert {r["court_code"] for r in courts.rows} == {"GAHC01"}
        assert courts.totals["total"] == 6
        assert rep.scope == "state" and rep.generated_by["name"] == "Oversight"


def test_pending_cases_department_groups_by_unit(world):
    with world.Session() as s:
        claim(s, world, new_case(s), unit="EDU-DSE")
        claim(s, world, new_case(s), unit="EDU-DSE")
        claim(s, world, new_case(s), officer="edu_off1")  # an officer at the department office
        claim(s, world, new_case(s))
        claim(s, world, new_case(s), by="health_admin")
        rep = reports.pending_cases(s, world.user(s, "edu_admin"), _scope(s, world, "edu_admin"))
        assert rep.scope == "department" and rep.department_code == "EDU"
        rows = {r["group_code"]: r["total"] for r in _section(rep, "by_group").rows}
        assert rows == {"DEPT": 2, "EDU-DSE": 2}
        assert _section(rep, "by_group").rows[0]["group"] == "Whole department (no responsible unit)"


def test_reports_unit_grouping_labels(world):
    """Design claim-assign-wording, decision 7: the department-scope grouping columns name the responsible unit and
    the `DEPT` row reads "Whole department (no responsible unit)"; the code `DEPT` stays."""
    with world.Session() as s:
        claim(s, world, new_case(s), unit="EDU-DSE")
        claim(s, world, new_case(s))
        rep = reports.pending_cases(s, world.user(s, "edu_admin"), _scope(s, world, "edu_admin"))
        section = _section(rep, "by_group")
        labels = {c.key: c.label for c in section.columns}
        assert labels["group_code"] == "Responsible unit code" and labels["group"] == "Responsible unit"
        dept = next(r for r in section.rows if r["group_code"] == "DEPT")
        assert dept["group"] == "Whole department (no responsible unit)"
        assert not any("allot" in c.label.lower() for c in section.columns)


def test_transferred_case_counts_for_current_owner(world):
    with world.Session() as s:
        case = new_case(s, next_hearing=today() + timedelta(days=1))
        claim(s, world, case)
        actor, admin = world.actor(s, "edu_admin")
        t = own.request_transfer(s, actor, admin, case, to_office_code="HEALTH", reason="theirs, not ours")
        actor_h, health = world.actor(s, "health_admin")
        own.decide_transfer(s, actor_h, health, s.get(OwnershipTransfer, t.id), accept=True)
        listing(s, case, today() - timedelta(days=1))
        rep = reports.pending_cases(s, world.user(s, "oversight"), _scope(s, world, "oversight"))
        sec = _section(rep, "by_group")
        assert _row(sec, group_code="HEALTH")["total"] == 1 and _row(sec, group_code="EDU")["total"] == 0
        hd = reports.hearings_disposals(
            s,
            world.user(s, "oversight"),
            _scope(s, world, "oversight"),
            from_=today() - timedelta(days=5),
            to=today(),
        )
        assert _row(_section(hd, "by_group"), group_code="HEALTH")["listings"] == 1


def test_hearings_disposals_counts_listings_proceedings_disposals_and_months(world):
    with world.Session() as s:
        jan, feb = date(2025, 1, 10), date(2025, 2, 3)
        a, b = new_case(s), new_case(s)
        claim(s, world, a)
        claim(s, world, b, unit="EDU-DSE")
        listing(s, a, jan, sr_no=1)
        listing(s, a, jan, sr_no=2, court_no="2")  # same case and date twice: one listing
        listing(s, a, feb, sr_no=1)
        listing(s, b, feb, sr_no=2)
        listing(s, None, feb, sr_no=3)  # an unresolved entry
        unowned = new_case(s)
        listing(s, unowned, jan, sr_no=3)
        listing(s, b, date(2025, 3, 5), sr_no=1)  # outside the period
        s.add_all(
            [
                CaseHearing(case_id=a.id, business_date=jan, purpose="ADMISSION"),
                CaseHearing(case_id=a.id, business_date=jan, purpose="ORDERS"),
                CaseHearing(case_id=b.id, business_date=feb, purpose="HEARING"),
            ]
        )
        dispose(s, b, date(2025, 2, 20))
        dispose(s, new_case(s), date(2025, 1, 15))  # unowned, disposed in the period
        s.flush()
        state = reports.hearings_disposals(
            s,
            world.user(s, "oversight"),
            _scope(s, world, "oversight"),
            from_=date(2025, 1, 1),
            to=date(2025, 2, 28),
        )
        edu = _row(_section(state, "by_group"), group_code="EDU")
        assert edu == edu | {"listings": 3, "cases_heard": 2, "proceedings": 2, "disposed": 1}
        nc = _row(_section(state, "by_group"), group_code="NC-NONE")
        assert nc["listings"] == 1 and nc["disposed"] == 1
        months = _section(state, "by_month")
        assert [r["month"] for r in months.rows] == ["2025-01", "2025-02"]
        assert months.rows[0]["listings"] == 2 and months.rows[0]["cases_heard"] == 2
        assert months.rows[1]["listings"] == 2 and months.rows[1]["cases_heard"] == 2
        assert months.totals["listings"] == 4 and months.totals["cases_heard"] == 3  # case a once
        assert months.totals["disposed"] == 2
        dept = reports.hearings_disposals(
            s,
            world.user(s, "edu_admin"),
            _scope(s, world, "edu_admin"),
            from_=date(2025, 1, 1),
            to=date(2025, 2, 28),
        )
        rows = {r["group_code"]: r for r in _section(dept, "by_group").rows}
        assert rows["DEPT"]["listings"] == 2 and rows["EDU-DSE"]["listings"] == 1
        assert rows["EDU-DSE"]["disposed"] == 1
        with pytest.raises(ReportError) as e:
            reports.hearings_disposals(
                s,
                world.user(s, "oversight"),
                _scope(s, world, "oversight"),
                from_=date(2025, 1, 1),
                to=date(2026, 6, 1),
            )
        assert e.value.http_status == 422


def _files(s, world):
    """Three EDU files with a pending action: held in EDU (overdue 4 days), in HEALTH (due tomorrow) and in EDU
    with no due date; and an EDU file with no pending action (allotted only)."""
    late, soon, open_ = new_case(s), new_case(s), new_case(s)
    for c in (late, soon, open_):
        claim(s, world, c, officer="edu_off1")
    send(s, world, "edu_off1", late, "edu_off2", due_date=today() + timedelta(days=9))
    set_due(s, late, -4)
    send(s, world, "edu_off1", soon, "health_off", due_date=today() + timedelta(days=1))
    send(s, world, "edu_off1", open_, "edu_off2", remark="secret remark text, never in a report")
    claim(s, world, new_case(s), officer="edu_off1")  # pending action `none`
    return late, soon, open_


def test_pending_actions_by_holder_office_and_officer(world):
    with world.Session() as s:
        _files(s, world)
        rep = reports.pending_actions(
            s, world.user(s, "edu_admin"), _scope(s, world, "edu_admin", "pending-actions")
        )
        sec = _section(rep, "by_holder")
        assert sec.totals["held"] == 3  # the `none` file is left out
        edu = _row(sec, holder_department_code="EDU")
        assert edu["officer"] == "Edu Off2" and edu["held"] == 2 and edu["overdue"] == 1
        assert edu["no_due_date"] == 1 and edu["max_overdue_days"] == 4
        health = _row(sec, holder_department_code="HEALTH")
        assert health["office_code"] == "HEALTH" and health["due_soon"] == 1 and health["overdue"] == 0
        assert health["holder_department"] == "Health" and health["officer"] == "Health Off"
        only = reports.pending_actions(
            s,
            world.user(s, "edu_admin"),
            _scope(s, world, "edu_admin", "pending-actions"),
            holder_department="HEALTH",
        )
        assert [r["holder_department_code"] for r in _section(only, "by_holder").rows] == ["HEALTH"]
        # HEALTH's own report has none of EDU's files
        hrep = reports.pending_actions(
            s, world.user(s, "health_admin"), _scope(s, world, "health_admin", "pending-actions")
        )
        assert _section(hrep, "by_holder").rows == []


def test_overdue_compliance_by_addressed_office(world):
    with world.Session() as s:
        case = new_case(s)
        claim(s, world, case)
        compliance_alert(s, world, case, today() - timedelta(days=3))
        compliance_alert(s, world, case, today() + timedelta(days=1), office="EDU-DSE")
        compliance_alert(s, world, case, today() - timedelta(days=9), status=AlertStatus.DONE)
        compliance_alert(s, world, case, today() - timedelta(days=40), status=AlertStatus.EXPIRED)
        other = new_case(s)
        claim(s, world, other, by="health_admin")
        compliance_alert(s, world, other, today() - timedelta(days=1), office="HEALTH")
        rep = reports.pending_actions(
            s, world.user(s, "edu_admin"), _scope(s, world, "edu_admin", "pending-actions")
        )
        rows = {r["office_code"]: r for r in _section(rep, "compliance").rows}
        assert set(rows) == {"EDU", "EDU-DSE"}
        assert rows["EDU"]["open"] == 1 and rows["EDU"]["overdue"] == 1
        assert rows["EDU-DSE"]["due_soon"] == 1 and rows["EDU-DSE"]["department_code"] == "EDU"
        state = reports.pending_actions(
            s, world.user(s, "oversight"), _scope(s, world, "oversight", "pending-actions")
        )
        assert _section(state, "compliance").totals["open"] == 3


def test_include_cases_respects_visibility_and_never_shows_remark(world):
    with world.Session() as s:
        late, soon, open_ = _files(s, world)
        mine = new_case(s)
        claim(s, world, mine, unit="EDU-DSE")
        send(s, world, "edu_admin", mine, "dse_user", due_date=today() + timedelta(days=2))
        override(s, world, "dse_user", Permission.REPORTS_DEPARTMENT, PermissionEffect.GRANT)
        dse = world.user(s, "dse_user")
        scope = reports.resolve_scope(s, dse, "pending-actions", None)
        rep = reports.pending_actions(s, dse, scope, include_cases=True)
        assert _section(rep, "by_holder").totals["held"] == 4  # the department's counts
        files = _section(rep, "files")
        assert [r["ref_no"] for r in files.rows] == [mine.ref_no]  # only the case dse_user may open
        assert files.rows[0]["pending_action"] == "Parawise comments"
        admin = world.user(s, "edu_admin")
        full = reports.pending_actions(
            s, admin, _scope(s, world, "edu_admin", "pending-actions"), include_cases=True, row_cap=2
        )
        f = _section(full, "files")
        assert (
            f.total_rows == 4 and len(f.rows) == 2 and f.truncated and f.note.startswith("First 2 of 4 rows.")
        )
        assert f.rows[0]["ref_no"] == late.ref_no and f.rows[0]["overdue_days"] == 4
        blobs = [
            str(full.to_dict()),
            _xlsx_text(report_export.to_xlsx(full)),
            _pdf_text(report_export.to_pdf(full)),
        ]
        assert full.rows and late.ref_no in blobs[1] and late.ref_no in blobs[2]
        uncapped = reports.pending_actions(
            s, admin, _scope(s, world, "edu_admin", "pending-actions"), include_cases=True
        )
        blobs.append(str(uncapped.to_dict()))
        for blob in blobs:
            assert "secret remark" not in blob


def test_data_health_per_date(world, tmp_path):
    with world.Session() as s:
        d1, d2 = today() - timedelta(days=2), today() - timedelta(days=1)
        s.add_all(
            [
                FetchQueueItem(
                    kind=FetchKind.CAUSELIST_DAY, ref=d1.isoformat(), status=FetchStatus.DONE, attempts=1
                ),
                FetchQueueItem(
                    kind=FetchKind.CAUSELIST_DAY, ref=d2.isoformat(), status=FetchStatus.FAILED, attempts=3
                ),
                FetchQueueItem(
                    kind=FetchKind.STATUS_BATCH, ref=f"{d1.isoformat()}:0", status=FetchStatus.DONE
                ),
                FetchQueueItem(
                    kind=FetchKind.STATUS_BATCH, ref=f"{d1.isoformat()}:1", status=FetchStatus.FAILED
                ),
            ]
        )
        late_evening = datetime.combine(d1, time(23, 30), IST_ZONE)  # 18:00 UTC: still d1 in IST
        s.add_all(
            [
                FetchQueueItem(
                    kind=FetchKind.DOSSIER,
                    ref="ASHC010000012025",
                    status=FetchStatus.DONE,
                    finished_at=late_evening,
                ),
                FetchQueueItem(
                    kind=FetchKind.ORDER_PDF,
                    ref="order-1",
                    status=FetchStatus.FAILED,
                    finished_at=late_evening,
                ),
            ]
        )
        listing(s, new_case(s), d1, sr_no=1)
        listing(s, None, d1, sr_no=2)
        court = s.scalar(sa.select(Court).where(Court.est_code == "GAHC01"))
        s.add(
            Causelist(
                court_id=court.id,
                list_date=d1,
                list_type=ListType.SUPPLEMENTARY,
                source=ListSource.GHC_WEBSITE,
                parse_status=ParseStatus.FAILED,
            )
        )
        for ok, family, ms in (
            (True, None, 100),
            (True, None, 300),
            (False, "timeout", 900),
            (False, "http", 50),
        ):
            s.add(
                NapixCallLog(
                    api="cnr",
                    params_sha256="0" * 64,
                    ok=ok,
                    error_family=family,
                    duration_ms=ms,
                    called_at=late_evening,
                )
            )
        s.add(SourceFailure(kind="dossier", ref="X", error="boom", first_seen=late_evening))
        s.add(SourceFailure(kind="dossier", ref="Y", error="old", resolved_at=late_evening))
        doc = upload_row(s, LocalStore(str(tmp_path)), new_case(s), world.office(s, "EDU"))
        s.add_all(
            [
                SourcetraceIngestion(
                    document_id=doc.id,
                    ok=True,
                    connector="fake",
                    reference="r1",
                    metadata_sent={},
                    created_at=late_evening,
                ),
                SourcetraceIngestion(
                    document_id=doc.id,
                    attempt=2,
                    ok=False,
                    connector="fake",
                    error="down",
                    error_family="unavailable",
                    metadata_sent={},
                    created_at=late_evening,
                ),
            ]
        )
        s.flush()
        rep = reports.data_health(s, world.user(s, "oversight"), from_=d1, to=d2)
        days = _section(rep, "by_date")
        assert [r["date"] for r in days.rows] == [d1, d2]
        r1, r2 = days.rows
        assert r1["causelist_day_status"] == "done" and r2["causelist_day_status"] == "failed"
        assert r2["causelist_day_attempts"] == 3
        assert r1["lists_stored"] == 2 and r1["entries_parsed"] == 2 and r1["lists_parse_failed"] == 1
        assert r1["status_batches_done"] == 1 and r1["status_batches_failed"] == 1
        assert r1["napix_calls"] == 4 and r1["napix_failed"] == 2
        assert r1["napix_error_families"] == "http 1, timeout 1"
        assert r1["dossiers_done"] == 1 and r1["order_pdfs_failed"] == 1
        assert r1["sourcetrace_ok"] == 1 and r1["sourcetrace_failed"] == 1
        assert r2["napix_calls"] == 0 and r2["lists_stored"] == 0
        api = _section(rep, "napix_by_api").rows
        assert api == [{"api": "cnr", "calls": 4, "failed": 2, "median_ms": 200}]
        assert _section(rep, "source_failures").rows == [
            {"kind": "dossier", "open": 1, "oldest_first_seen": d1}
        ]
        st = {r["measure"]: r["count"] for r in _section(rep, "sourcetrace").rows}
        assert st["documents pending"] >= 0 and "due now" in st
        assert "first live call" in rep.as_of_note


def test_report_scope_rules(world):
    with world.Session() as s:
        admin = world.user(s, "edu_admin")
        assert reports.resolve_scope(s, admin, "pending-cases", "EDU").department.code == "EDU"
        assert reports.resolve_scope(s, admin, "pending-cases", None).department.code == "EDU"
        with pytest.raises(Forbidden):
            reports.resolve_scope(s, admin, "pending-cases", "HEALTH")
        with pytest.raises(Forbidden):
            reports.resolve_scope(s, world.user(s, "edu_off1"), "pending-cases", None)
        with pytest.raises(Forbidden):
            reports.resolve_scope(s, admin, "data-health", None)  # reports.state only
        add_membership(s, admin, world.office(s, "HEALTH"), Role.DEPT_OFFICER)
        s.flush()
        override(
            s, world, "edu_admin", Permission.REPORTS_DEPARTMENT, PermissionEffect.GRANT, office="HEALTH"
        )
        with pytest.raises(ReportError) as e:
            reports.resolve_scope(s, world.user(s, "edu_admin"), "pending-cases", None)
        assert e.value.code == "department_required" and e.value.extra["candidates"] == ["EDU", "HEALTH"]
        oversight = world.user(s, "oversight")
        assert reports.resolve_scope(s, oversight, "pending-cases", None).kind == "state"
        assert reports.resolve_scope(s, oversight, "pending-actions", "HEALTH").department.code == "HEALTH"
        central = world.user(s, "central_op")
        assert reports.resolve_scope(s, central, "data-health", None).kind == "state"
        with pytest.raises(ReportError) as e:
            reports.resolve_scope(s, central, "data-health", "EDU")
        assert e.value.code == "department_not_allowed" and e.value.http_status == 400
        with pytest.raises(ReportError) as e:
            reports.resolve_scope(s, oversight, "pending-cases", "EDU-DSE")
        assert e.value.code == "bad_department"
        cat = {c["key"]: c for c in reports.catalogue_for(s, admin)["reports"]}
        assert cat["pending-cases"]["scopes"] == ["department"] and "data-health" not in cat
        assert cat["pending-cases"]["departments"] == ["EDU", "HEALTH"]
        cat = {c["key"]: c for c in reports.catalogue_for(s, oversight)["reports"]}
        assert cat["data-health"]["scopes"] == ["state"] and "EDU" in cat["pending-cases"]["departments"]
        with pytest.raises(Forbidden):
            reports.catalogue_for(s, world.user(s, "edu_off1"))


def test_statement_timeout_is_set(world):
    with world.Session() as s:
        cfg = ReportConfig(statement_timeout_seconds=17)
        reports.pending_cases(s, world.user(s, "oversight"), _scope(s, world, "oversight"), config=cfg)
        assert s.execute(sa.text("SHOW statement_timeout")).scalar() == "17s"
        s.rollback()
        assert (
            s.execute(sa.text("SHOW statement_timeout")).scalar() != "17s"
        )  # SET LOCAL: this transaction only


def test_builders_do_not_write(world):
    with world.Session() as s:
        _files(s, world)
        claim(s, world, new_case(s, next_hearing=today() + timedelta(days=1)))
        s.commit()
        before = row_counts(s)
        oversight = world.user(s, "oversight")
        for key in ("pending-cases", "hearings-disposals", "pending-actions", "data-health"):
            reports.build(
                s,
                oversight,
                key,
                from_=today() - timedelta(days=30),
                to=today(),
                include_cases=True,
            )
        reports.build(s, world.user(s, "edu_admin"), "pending-actions", include_cases=True)
        assert not s.new and not s.dirty and not s.deleted
        assert row_counts(s) == before
