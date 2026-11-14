"""`aslms offices import` against the test database (design `offices-import`, decisions 7-22): the dry run writes
nothing; `--apply` with the dry run's fingerprint creates departments, heads, administrators, offices and office heads
in one transaction with one summary row and the run's user agent on every row; a wrong fingerprint or any error writes
nothing; a second run changes nothing; existing logins and offices are matched, never duplicated; the head and admin
rules; No Head Yet only through the import; new designations; logins with no usable password; welcome mails only after
the commit, audited, and sent again by `aslms users welcome --pending`; mail readiness; no names or mobiles printed."""

from __future__ import annotations

import re
import uuid
from contextlib import contextmanager

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from typer.testing import CliRunner
from uuid6 import uuid7

from aslms.cli.main import app as cli_app
from aslms.core.config import Settings
from aslms.domain.events import AuditLog
from aslms.domain.org import Designation, Office, User, UserMembership
from aslms.domain.reference import OfficeKind, Role
from aslms.services import memberships, offices
from aslms.services import offices_import as imp
from aslms.services.mailer import MailError, RecordingMailer, UnconfiguredMailer
from aslms.services.offices import HeadRequired
from aslms.services.users import authenticate, welcome_pending
from tests.offices_workbook import admin, build, dept, head, office, office_head

SETTINGS = Settings(_env_file=None, aslms_jwt_secret="test-secret-of-at-least-thirty-two-characters")
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
ENV = {"COLUMNS": "250", "NO_COLOR": "1", "TERM": "dumb"}

ASHA = head("Asha Das", "asha@example.gov.in", mobile="9864012345")
BINA = admin("Bina Roy", "bina@example.gov.in", mobile="+91 98640 12346")
CHANDAN = head("Chandan Bora", "chandan@example.gov.in")
DIPA = office_head(
    "Dipa Nath", "dipa@example.gov.in", user_type="Department Officer", designation="Managing Director"
)


def workbook(**over) -> bytes:
    departments = over.get(
        "departments",
        [
            dept("Transport", "TRANS", website="https://transport.assam.gov.in", **ASHA, **BINA),
            dept("Tourism", "TOURISM", **admin("Health Officer", "off.health@example.org", has_login="Yes")),
            dept("Health", "HEALTH", **CHANDAN),
            dept("Sports & Youth Welfare", "SYW", include="No"),
        ],
    )
    offices_ = over.get(
        "offices",
        [
            office(
                "Transport", "Assam State Transport Corporation", "Board / Corporation", "TRANS-ASTC", **DIPA
            ),
            office("Transport", "Directorate of Transport", "Directorate / Commissionerate", "TRANS-DOT"),
            office("Tourism", "Tourism Development Corporation", "Board / Corporation", "TOURISM-TDC"),
            office(
                "Sports & Youth Welfare",
                "Sports Authority",
                "Statutory Authority / Commission",
                "SYW-SA",
                "No",
            ),
        ],
    )
    return build(departments, offices_)


def counts(world) -> dict[str, int]:
    with world.Session() as s:
        return {
            t: int(s.execute(sa.text(f"select count(*) from {t}")).scalar())
            for t in ("offices", "users", "user_memberships", "designations", "audit_log", "admin_tickets")
        }


def dry(world, data: bytes) -> tuple[imp.ImportPlan, str]:
    wb = imp.read_workbook(data)
    with world.Session() as s:
        plan = imp.check(s, wb)
        s.rollback()
    return plan, imp.fingerprint(data, plan)


def apply(world, data: bytes, mailer=None, expect: str | None = None) -> imp.ImportResult:
    plan, fp = dry(world, data)
    return imp.run_apply(
        world.Session,
        imp.read_workbook(data),
        expect=expect or fp,
        run_id=uuid7(),
        mailer=mailer,
        settings=SETTINGS,
    )


def office_of(world, code: str) -> Office | None:
    with world.Session() as s:
        return s.scalar(sa.select(Office).where(Office.code == code))


def user_of(world, email: str) -> User | None:
    with world.Session() as s:
        return s.scalar(sa.select(User).where(User.email == email))


def roles_at(world, code: str) -> dict[str, str]:
    """email -> type of the active memberships at the office."""
    with world.Session() as s:
        rows = s.execute(
            sa.select(User.email, UserMembership.role)
            .join(UserMembership, UserMembership.user_id == User.id)
            .join(Office, Office.id == UserMembership.office_id)
            .where(Office.code == code, UserMembership.is_active.is_(True))
        ).all()
    return {e: (r.value if isinstance(r, Role) else r) for e, r in rows}


def patch_cli(world, monkeypatch, mailer=None) -> RecordingMailer:
    from aslms.cli import offices as cli_offices
    from aslms.cli import users as cli_users

    mailer = mailer if mailer is not None else RecordingMailer()
    monkeypatch.setattr(cli_offices, "_session_factory", lambda: world.Session)
    monkeypatch.setattr(cli_offices, "_mailer", lambda settings: mailer)
    monkeypatch.setattr(cli_users, "_welcome_session_factory", lambda: world.Session)
    monkeypatch.setattr(cli_users, "_welcome_mailer", lambda settings: mailer)

    @contextmanager
    def scope():
        s = world.Session()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    monkeypatch.setattr(cli_users, "session_scope", scope)
    return mailer


def cli(*args: str, data: bytes | None = None, tmp_path=None):
    argv = ["offices", "import", *args]
    if data is not None and tmp_path is not None:
        path = tmp_path / "offices.xlsx"
        path.write_bytes(data)
        argv = ["offices", "import", str(path), *args]
        return CliRunner(env=ENV).invoke(cli_app, argv)
    return CliRunner(env=ENV).invoke(cli_app, [*argv[:2], "-", *args], input=data)


def fingerprint_of(output: str) -> str:
    return re.search(r"Fingerprint: ([0-9a-f]{12})", _ANSI.sub("", output)).group(1)


# ------------------------------------------------------------------------------------------------ the run


def test_dry_run_writes_nothing(world, monkeypatch, tmp_path):
    patch_cli(world, monkeypatch)
    before = counts(world)
    r = cli(data=workbook(), tmp_path=tmp_path)
    assert r.exit_code == 0, r.output
    assert "nothing was written" in r.output and fingerprint_of(r.output)
    r = cli(data=workbook())  # from standard input
    assert r.exit_code == 0, r.output
    assert counts(world) == before


def test_apply_creates_departments_heads_admins_offices_and_office_heads(world, monkeypatch, tmp_path):
    mailer = patch_cli(world, monkeypatch)
    data = workbook()
    before = counts(world)
    fp = fingerprint_of(cli(data=data, tmp_path=tmp_path).output)
    r = cli("--apply", "--expect", fp, data=data, tmp_path=tmp_path)
    assert r.exit_code == 0, r.output
    after = counts(world)
    assert after["offices"] == before["offices"] + 5
    assert after["users"] == before["users"] + 4  # asha, bina, chandan, dipa; off.health reused
    assert after["designations"] == before["designations"] + 1
    trans, tourism = office_of(world, "TRANS"), office_of(world, "TOURISM")
    assert trans.kind == OfficeKind.DEPARTMENT and trans.path == "GOA/TRANS"
    assert (
        trans.notes == "From the Assam State Portal department list. Website: https://transport.assam.gov.in"
    )
    assert office_of(world, "TRANS-ASTC").kind == OfficeKind.BOARD_CORPORATION
    assert office_of(world, "TRANS-ASTC").path == "GOA/TRANS/TRANS-ASTC"
    assert office_of(world, "SYW") is None and office_of(world, "SYW-SA") is None
    assert roles_at(world, "TRANS") == {
        "asha@example.gov.in": "dept_head",
        "bina@example.gov.in": "dept_admin",
    }
    assert roles_at(world, "TOURISM") == {"off.health@example.org": "dept_admin"}
    assert roles_at(world, "HEALTH")["chandan@example.gov.in"] == "dept_head"
    assert roles_at(world, "TRANS-ASTC") == {"dipa@example.gov.in": "dept_officer"}
    with world.Session() as s:
        assert offices.has_no_head(s, s.get(Office, tourism.id))
        assert not offices.has_no_head(s, s.get(Office, trans.id))
        bina = s.scalar(sa.select(User).where(User.email == "bina@example.gov.in"))
        assert bina.mobile == "9864012346" and bina.must_change_password
        md = s.scalar(sa.select(Designation).where(Designation.code == "MANAGING_DIRECTOR"))
        assert md is not None and md.name == "Managing Director"
        summary = s.scalars(sa.select(AuditLog).where(AuditLog.action == "office_import.applied")).all()
        assert len(summary) == 1
        run_agent = summary[0].user_agent
        assert run_agent.startswith("aslms offices import ") and summary[0].entity_id == summary[0].id
        after_json = summary[0].after
        assert after_json["counts"]["departments_created"] == 2 and after_json["counts"]["heads"] == 2
        assert sorted(after_json["codes_created"]) == [
            "TOURISM",
            "TOURISM-TDC",
            "TRANS",
            "TRANS-ASTC",
            "TRANS-DOT",
        ]
        assert "asha@example.gov.in" not in str(after_json) and "Asha" not in str(after_json)
        run_rows = s.scalars(sa.select(AuditLog).where(AuditLog.user_agent == run_agent)).all()
        actions = {a.action for a in run_rows}
        assert {
            "office.create",
            "designation.create",
            "user.create",
            "ticket.approved",
            "office.admin_added",
            "membership.added",
            "office_import.applied",
            "user.welcome_sent",
        } <= actions
        no_head = [a for a in run_rows if a.action == "office.create" and a.after["code"] == "TOURISM"][
            0
        ].after
        assert no_head["head"] is None and no_head["no_head_yet"] is True
        created = [a for a in run_rows if a.action == "user.create"]
        assert len(created) == 4 and all(a.after["password"] == "unset" for a in created)
    assert sorted(m.to for m in mailer.sent) == [
        "asha@example.gov.in",
        "bina@example.gov.in",
        "chandan@example.gov.in",
        "dipa@example.gov.in",
    ]
    assert all(m.subject == "Your ASLMS Sign-In Is Ready" for m in mailer.sent)
    asha_mail = next(m for m in mailer.sent if m.to == "asha@example.gov.in").text
    assert "Transport: Head of Department" in asha_mail and "/forgot" in asha_mail


def test_apply_refuses_without_matching_fingerprint(world, monkeypatch, tmp_path):
    patch_cli(world, monkeypatch)
    before = counts(world)
    data = workbook()
    with pytest.raises(imp.PlanChanged):
        apply(world, data, expect="000000000000")
    # the file changed after the dry run the owner approved
    _, fp_other = dry(world, workbook(offices=[]))
    with pytest.raises(imp.PlanChanged):
        apply(world, data, expect=fp_other)
    r = cli("--apply", "--expect", "abcdefabcdef", data=data, tmp_path=tmp_path)
    assert r.exit_code == 3, r.output
    r = cli("--apply", data=data, tmp_path=tmp_path)
    assert r.exit_code != 0 and "--expect" in _ANSI.sub("", r.output)
    assert counts(world) == before


def test_apply_refuses_when_any_error(world, monkeypatch, tmp_path):
    patch_cli(world, monkeypatch)
    data = workbook(
        offices=[
            office("Transport", "Directorate of Transport", "Directorate / Commissionerate", "TRANS-DOT"),
            office("Transport", "Bad", "Directorate / Commissionerate", "TRANS-ABCDEFGHIJKLMN"),
        ]
    )
    before = counts(world)
    plan, fp = dry(world, data)
    assert [p.code for p in plan.errors] == ["code_too_long"]
    with pytest.raises(imp.ImportErrors):
        apply(world, data, expect=fp)
    r = cli(data=data, tmp_path=tmp_path)
    assert r.exit_code == 1 and "code_too_long" in r.output
    r = cli("--apply", "--expect", fp, data=data, tmp_path=tmp_path)
    assert r.exit_code == 1, r.output
    assert counts(world) == before


def test_second_apply_changes_nothing(world, monkeypatch, tmp_path):
    patch_cli(world, monkeypatch)
    data = workbook()
    first = apply(world, data, mailer=RecordingMailer())
    assert first.changed
    before = counts(world)
    plan, fp = dry(world, data)
    assert not plan.has_changes and not plan.errors
    second = apply(world, data, mailer=RecordingMailer())
    assert not second.changed and second.summary_id is None
    out = cli(data=data, tmp_path=tmp_path).output
    assert "nothing to change" in out
    r = cli("--apply", "--expect", fingerprint_of(out), data=data, tmp_path=tmp_path)
    assert r.exit_code == 0 and "nothing to change" in r.output
    assert counts(world) == before


def test_existing_login_reused_never_duplicated(world):
    data = workbook(
        departments=[
            dept("Transport", "TRANS", **head("", "off.health@example.org", has_login="No")),
            dept("Tourism", "TOURISM", **head("Eka Paul", "eka@example.gov.in", has_login="Yes")),
        ],
        offices=[],
    )
    plan, _ = dry(world, data)
    assert [p.code for p in plan.errors] == ["login_missing"]
    assert "login_exists" in [p.code for p in plan.notices]
    data = workbook(
        departments=[dept("Transport", "TRANS", **head("", "OFF.health@example.org", has_login="No"))],
        offices=[],
    )
    before = counts(world)
    apply(world, data)
    assert counts(world)["users"] == before["users"]
    assert roles_at(world, "TRANS") == {"off.health@example.org": "dept_head"}
    health_off = user_of(world, "off.health@example.org")
    assert health_off.full_name == "Health Off"  # never changed by the import


def test_existing_office_matched_and_renamed_kind_or_parent_mismatch_refused(world):
    data = workbook(
        departments=[dept("Health and Family Welfare", "HEALTH"), dept("Central", "CENTRAL")],
        offices=[
            office(
                "Health and Family Welfare", "Secondary Education", "Directorate / Commissionerate", "EDU-DSE"
            ),
            office("Education", "Secondary Education", "Board / Corporation", "EDU-DSE"),
        ],
    )
    plan, _ = dry(world, data)
    assert sorted(p.code for p in plan.errors) == [
        "duplicate_code_in_file",
        "kind_mismatch",
        "parent_mismatch",
    ]
    data = workbook(
        departments=[dept("Health and Family Welfare", "HEALTH")],
        offices=[office("Education", "Directorate of Secondary Education", "Directorate", "EDU-DSE")],
    )
    plan, _ = dry(world, data)
    assert not plan.errors and {p.code for p in plan.notices} >= {"rename"}
    apply(world, data)
    assert office_of(world, "HEALTH").name == "Health and Family Welfare"
    assert office_of(world, "EDU-DSE").name == "Directorate of Secondary Education"
    with world.Session() as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(Office).where(Office.code == "HEALTH")) == 1


def test_possible_duplicate_by_name_refused(world):
    """The SEC-EDU / SCH-EDU case: a new code beside an existing office of the same name is refused."""
    data = workbook(departments=[dept("Department of Education", "SCH-EDU", **ASHA)], offices=[])
    plan, _ = dry(world, data)
    dup = [p for p in plan.errors if p.code == "possible_duplicate"]
    assert len(dup) == 1 and "EDU" in dup[0].message
    data = workbook(departments=[dept("School Education", "EDU")], offices=[])
    plan, _ = dry(world, data)
    assert not plan.errors and plan.departments[0].rename_to == "School Education"


def test_head_and_admin_same_person_refused(world):
    data = workbook(
        departments=[dept("Transport", "TRANS", **ASHA, **admin("Asha Das", "asha@example.gov.in"))],
        offices=[],
    )
    plan, _ = dry(world, data)
    assert [p.code for p in plan.errors] == ["same_person_head_admin"]
    assert "name another administrator" in plan.errors[0].message


def test_office_head_in_department_where_person_already_member_refused(world):
    data = workbook(
        departments=[],
        offices=[
            office(
                "Education",
                "Education Board",
                "Board / Corporation",
                "EDU-BOARD",
                **office_head("Edu Off1", "off1.edu@example.org", has_login="Yes"),
            )
        ],
    )
    plan, _ = dry(world, data)
    assert [p.code for p in plan.errors] == ["one_per_department"]


def test_existing_department_head_never_replaced(world):
    data = workbook(departments=[dept("Education", "EDU", **ASHA)], offices=[])
    plan, _ = dry(world, data)
    assert "head_differs" in [p.code for p in plan.notices] and not plan.errors
    apply(world, data)
    assert roles_at(world, "EDU").get("head.edu@example.org") == "dept_head"
    assert "asha@example.gov.in" not in roles_at(world, "EDU")


def test_no_head_yet_department_created_only_by_import(world):
    from aslms.api.main import create_app
    from tests.db.auth_support import bearer, ready_all

    with world.Session() as s:
        actor, root = world.actor(s, "root")
        with pytest.raises(HeadRequired):
            offices.create_office(
                s,
                actor,
                root,
                code="NOHEAD",
                name="No Head",
                kind="department",
                parent=world.office(s, "GOA"),
            )
        s.rollback()
        ready_all(s)
        s.commit()
    with TestClient(create_app(SETTINGS, world.Session)) as api:
        r = api.post(
            "/admin/offices",
            json={"code": "NOHEAD", "name": "No Head", "kind": "department", "parent_code": "GOA"},
            headers=bearer(api, "root@example.org", "correct-horse-battery-7"),
        )
        assert r.status_code == 400 and r.json()["detail"]["code"] == "head_required", r.text
    apply(world, workbook(departments=[dept("No Head", "NOHEAD")], offices=[]))
    with world.Session() as s:
        assert offices.has_no_head(s, s.scalar(sa.select(Office).where(Office.code == "NOHEAD")))
        assert "NOHEAD" in [o.code for o in offices.departments_without_head(s)]


def test_no_head_yet_then_head_filled_by_second_run(world):
    apply(world, workbook(departments=[dept("Tourism", "TOURISM")], offices=[]))
    before = counts(world)
    result = apply(world, workbook(departments=[dept("Tourism", "TOURISM", **ASHA)], offices=[]))
    assert result.counts["heads"] == 1 and result.counts["departments_created"] == 0
    assert roles_at(world, "TOURISM") == {"asha@example.gov.in": "dept_head"}
    assert counts(world)["admin_tickets"] == before["admin_tickets"] + 1
    with world.Session() as s:
        tourism = s.scalar(sa.select(Office).where(Office.code == "TOURISM"))
        assert not offices.has_no_head(s, tourism)
        actor, root = world.actor(s, "root")
        with pytest.raises(Exception, match="already has a head"):
            offices.set_missing_head(s, actor, root, tourism, {"email": "off.health@example.org"})
        s.rollback()


def test_new_designation_created_and_audited(world):
    result = apply(
        world,
        workbook(
            departments=[
                dept("Transport", "TRANS", **head("Asha Das", "asha@example.gov.in", "Mission Director"))
            ],
            offices=[],
        ),
    )
    with world.Session() as s:
        d = s.scalar(sa.select(Designation).where(Designation.code == "MISSION_DIRECTOR"))
        assert d is not None and d.name == "Mission Director"
        row = s.scalar(
            sa.select(AuditLog).where(AuditLog.action == "designation.create", AuditLog.entity_id == d.id)
        )
        assert row is not None and row.user_agent == f"aslms offices import {result.run_id}"
        m = s.scalar(
            sa.select(UserMembership)
            .join(User, User.id == UserMembership.user_id)
            .where(User.email == "asha@example.gov.in")
        )
        assert m.designation_id == d.id and m.designation == "Mission Director"


def test_new_login_has_unusable_password_and_must_change(world):
    from aslms.api.main import create_app
    from tests.db.auth_support import last_code, mailer_of, sign_in

    apply(world, workbook(departments=[dept("Transport", "TRANS", **ASHA)], offices=[]))
    asha = user_of(world, "asha@example.gov.in")
    assert asha.must_change_password and asha.must_confirm_profile and asha.password_changed_at is None
    with world.Session() as s:
        for guess in ("", "unset", "correct-horse-battery-7", "aslms12345"):
            assert authenticate(s, "asha@example.gov.in", guess) is None
        assert [u.email for u in welcome_pending(s)] == ["asha@example.gov.in"]
    with TestClient(create_app(SETTINGS, world.Session)) as api:
        mailer_of(api)
        r = api.post("/auth/password-reset/request", json={"email": "asha@example.gov.in"})
        assert r.status_code == 202, r.text
        r = api.post(
            "/auth/password-reset/confirm",
            json={
                "challenge_id": r.json()["challenge_id"],
                "code": last_code(api, "asha@example.gov.in"),
                "new_password": "my-own-password-42",
            },
        )
        assert r.status_code == 204, r.text
        answer = sign_in(api, "asha@example.gov.in", "my-own-password-42")
        assert answer["access_token"]
    asha = user_of(world, "asha@example.gov.in")
    assert not asha.must_change_password and asha.password_changed_at is not None
    with world.Session() as s:
        assert welcome_pending(s) == []


def test_welcome_sent_after_commit_only(world, monkeypatch):
    mailer = RecordingMailer()
    before = counts(world)

    def boom(*args, **kwargs):
        raise RuntimeError("forced failure in the office-head step")

    monkeypatch.setattr(imp.memberships, "add", boom)
    with pytest.raises(RuntimeError, match="forced failure"):
        apply(world, workbook(), mailer=mailer)
    assert mailer.sent == []
    assert counts(world) == before


def test_welcome_failure_audited_and_resent_by_pending(world, monkeypatch):
    failing = RecordingMailer(fail_with=MailError("smtp down"))
    result = apply(
        world, workbook(departments=[dept("Transport", "TRANS", **ASHA, **BINA)], offices=[]), failing
    )
    assert result.welcome == {"sent": 0, "failed": 2}
    with world.Session() as s:
        rows = s.scalars(sa.select(AuditLog).where(AuditLog.action == "user.welcome_sent")).all()
        assert sorted((r.after["sent"], r.after["reason"]) for r in rows) == [(False, "MailError")] * 2
        assert "smtp down" not in str([r.after for r in rows])
        assert {u.email for u in welcome_pending(s)} == {"asha@example.gov.in", "bina@example.gov.in"}
    mailer = patch_cli(world, monkeypatch)
    r = CliRunner(env=ENV).invoke(cli_app, ["users", "welcome", "--pending"])
    assert r.exit_code == 0, r.output
    assert sorted(m.to for m in mailer.sent) == ["asha@example.gov.in", "bina@example.gov.in"]
    assert "asha@example.gov.in" not in r.output and "a***@example.gov.in" in r.output
    with world.Session() as s:
        assert welcome_pending(s) == []
    r = CliRunner(env=ENV).invoke(cli_app, ["users", "welcome", "--email", "asha@example.gov.in"])
    assert r.exit_code == 0 and len(mailer.sent) == 3
    r = CliRunner(env=ENV).invoke(cli_app, ["users", "welcome"])
    assert r.exit_code != 0


def test_apply_refuses_when_mail_not_ready_unless_no_welcome(world, monkeypatch, tmp_path):
    patch_cli(world, monkeypatch, mailer=UnconfiguredMailer())
    data = workbook()
    before = counts(world)
    fp = fingerprint_of(cli(data=data, tmp_path=tmp_path).output)
    r = cli("--apply", "--expect", fp, data=data, tmp_path=tmp_path)
    assert r.exit_code == 4, r.output
    assert counts(world) == before
    r = cli("--apply", "--expect", fp, "--no-welcome", data=data, tmp_path=tmp_path)
    assert r.exit_code == 0, r.output
    assert "aslms users welcome --pending" in _ANSI.sub("", r.output)
    with world.Session() as s:
        assert (
            s.scalar(
                sa.select(sa.func.count()).select_from(AuditLog).where(AuditLog.action == "user.welcome_sent")
            )
            == 0
        )
        assert len(welcome_pending(s)) == 4


def test_output_has_no_names_or_mobiles(world, monkeypatch, tmp_path):
    patch_cli(world, monkeypatch)
    data = workbook(
        departments=[
            dept("Transport", "TRANS", **ASHA, **BINA),
            dept("Tourism", "TOURISM", **head("Asha Devi", "asha@example.gov.in", mobile="9864012399")),
            dept("Soil", "SOIL", **head("Gita Saikia", "gita@example.gov.in", mobile="12345")),
        ],
        offices=[
            office(
                "Transport", "Directorate of Transport", "Directorate / Commissionerate", "TRANS-DOT", **DIPA
            )
        ],
    )
    r = cli(data=data, tmp_path=tmp_path)
    out = _ANSI.sub("", r.output)
    assert r.exit_code == 1
    for secret in ("Asha", "Bina", "Gita", "Dipa", "9864012345", "9864012346", "9864012399", "12345"):
        assert secret not in out, secret
    for email in ("asha@example.gov.in", "bina@example.gov.in", "gita@example.gov.in", "dipa@example.gov.in"):
        assert email not in out
    assert "a***@example.gov.in" in out
    assert re.search(r"Departments row \d+ \(TOURISM\)", out)


def test_no_super_admin_exit_5(world, monkeypatch, tmp_path):
    patch_cli(world, monkeypatch)
    with world.Session() as s:
        s.execute(sa.text("UPDATE users SET is_active = false WHERE email = 'root@example.org'"))
        s.commit()
    r = cli(data=workbook(), tmp_path=tmp_path)
    assert r.exit_code == 5, r.output


def test_bad_file_exit_2(world, monkeypatch, tmp_path):
    patch_cli(world, monkeypatch)
    r = cli(data=b"not a workbook", tmp_path=tmp_path)
    assert r.exit_code == 2 and "bad file" in r.output
    assert uuid.UUID(str(uuid7()))  # the run ids are UUID v7
    with world.Session() as s:
        assert memberships.super_admin_membership(s) is not None


def test_stdin_dry_run_and_apply_with_fingerprint(world, monkeypatch):
    """Decision 7: `FILE` of `-` reads the workbook from standard input; `--apply` needs `--expect`."""
    patch_cli(world, monkeypatch)
    data = workbook()
    before = counts(world)
    r = cli(data=data)
    assert r.exit_code == 0, r.output
    assert counts(world) == before
    fp = fingerprint_of(r.output)
    refused = cli("--apply", data=data)
    assert refused.exit_code != 0 and counts(world) == before
    wrong = cli("--apply", "--expect", "0" * 12, data=data)
    assert wrong.exit_code == 3 and counts(world) == before
    done = cli(
        "--apply",
        "--expect",
        fp,
        data=data,
    )
    assert done.exit_code == 0, done.output
    assert office_of(world, "TRANS") is not None


def test_inactive_existing_office_is_an_error(world):
    """Decision 10: an inactive office matched by code is refused ("reactivate it in Administration first")."""
    with world.Session() as s:
        s.execute(sa.text("UPDATE offices SET is_active = false WHERE code = 'EDU-DSE'"))
        s.commit()
    data = workbook(
        departments=[dept("Education", "EDU")],
        offices=[
            office(
                "Education", "Directorate of Secondary Education", "Directorate / Commissionerate", "EDU-DSE"
            )
        ],
    )
    plan, _ = dry(world, data)
    assert "office_inactive" in {p.code for p in plan.errors}
