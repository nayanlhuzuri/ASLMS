"""The exit step (design `user-memberships`, decisions 21-22): the preview lists every allotment and held file as
an item with a fingerprint and the eligible targets; the end call moves each item to the officer the admin chose,
in one transaction, or refuses (`unassigned_items`, `stale_exit`, `bad_target`, `duplicate_item`) writing
nothing; open alerts follow the targets; the primary flag passes on; the login stays active without membership."""

from __future__ import annotations

from datetime import timedelta

import pytest
import sqlalchemy as sa

from aslms.domain.alerts import AlertStatus, Notification, Severity
from aslms.domain.cases import Case
from aslms.domain.events import AuditLog
from aslms.domain.ownership import CaseOwnership, OwnershipStatus
from aslms.domain.reference import AlertKind, Permission, Role
from aslms.domain.workflow import Custody, CustodyHistory
from aslms.services import access, alerts, memberships
from aslms.services import ownership as own
from aslms.services.access import Conflict
from aslms.services.alert_rules import today_ist
from aslms.services.memberships import MembershipError
from tests.db.world import add_membership, make_case


def legs(s, case_id) -> list[CustodyHistory]:
    return list(
        s.scalars(
            sa.select(CustodyHistory).where(CustodyHistory.case_id == case_id).order_by(CustodyHistory.seq_no)
        )
    )


@pytest.fixture()
def two_cases(world):
    """Cases A and B claimed by EDU and allotted to EDU officer 1 (who therefore holds both files)."""
    with world.Session() as s:
        actor, admin = world.actor(s, "edu_admin")
        off1 = world.user(s, "edu_off1")
        a, b = make_case(s), make_case(s)
        for c in (a, b):
            own.claim(s, actor, admin, c, officer_user_id=off1.id)
        s.commit()
        return world, a.id, b.id


def plan(items, targets: dict[str, str], **per_key) -> list[dict]:
    out = []
    for item in items:
        a = {"key": item["key"], "to_membership": targets[item["key"]]}
        a.update(per_key.get(item["key"], {}))
        out.append(a)
    return out


def test_preview_lists_items_targets_and_fingerprint(two_cases):
    w, a_id, b_id = two_cases
    with w.Session() as s:
        _, admin = w.actor(s, "edu_admin")
        m = w.membership(s, "edu_off1")
        p = memberships.exit_preview(s, admin, m)
        kinds = sorted((str(i["case"]["ref_no"]), i["kind"]) for i in p["items"])
        assert len(kinds) == 4 and {k for _, k in kinds} == {"allotment", "file"}
        assert p["counts"] == {"allotments": 2, "files": 2, "drafts": 0, "open_alerts": 0}
        assert len(p["items_fingerprint"]) == 64
        names = {t["name"] for t in p["targets"]}
        assert "Edu Off2" in names and "Dse User" in names and "Edu Off1" not in names
        assert "Edu Auditor" not in names and "Health Off" not in names  # State-wide, another department
        assert all(i["case"]["visible"] for i in p["items"])
        assert p["primary_after"] is None  # the last membership: the login keeps none
        # the preview writes nothing
        assert not s.scalars(sa.select(AuditLog).where(AuditLog.action == "membership.exit")).all()


def test_end_moves_every_item_to_its_own_target(two_cases):
    w, a_id, b_id = two_cases
    with w.Session() as s:
        actor, admin = w.actor(s, "edu_admin")
        leaver = w.user(s, "edu_off1")
        m = w.membership(s, "edu_off1")
        x, y = w.membership(s, "edu_off2"), w.membership(s, "dse_user")
        # an open alert on case A addressed to EDU, notified to the leaver and acknowledged by them
        alert, _ = alerts.raise_alert(
            s,
            case=s.get(Case, a_id),
            kind=AlertKind.OWNERSHIP,
            key=f"test:exit:{a_id}",
            office=w.office(s, "EDU"),
            severity=Severity.HIGH,
            data={"event": "allotted"},
            recipients=[leaver],
        )
        l_actor, _ = w.actor(s, "edu_off1")
        alerts.acknowledge(s, l_actor, leaver, alert)
        p = memberships.exit_preview(s, admin, m)
        assert p["counts"]["open_alerts"] == 1
        due = today_ist(alerts._now()) + timedelta(days=10)
        targets = {
            i["key"]: str((x if i["case"]["ref_no"] == s.get(Case, a_id).ref_no else y).id)
            for i in p["items"]
        }
        b_file = next(
            i["key"] for i in p["items"] if i["kind"] == "file" and i["key"].startswith(f"file:{b_id}")
        )
        result = memberships.end(
            s,
            actor,
            admin,
            m,
            reason="transferred to Health",
            assignments=plan(
                p["items"],
                targets,
                **{b_file: {"pending_action": "examine", "due_date": due.isoformat(), "remark": "urgent"}},
            ),
            items_fingerprint=p["items_fingerprint"],
        )
        assert result.counts == {"allotments": 2, "files": 2, "notes_finalised": 0, "alerts": 1}
        rows = {
            r.case_id: r
            for r in s.scalars(sa.select(CaseOwnership).where(CaseOwnership.status == OwnershipStatus.ACTIVE))
        }
        assert rows[a_id].officer_user_id == x.user_id and rows[b_id].officer_user_id == y.user_id
        ca, cb = s.get(Custody, a_id), s.get(Custody, b_id)
        assert ca.holder_user_id == x.user_id and cb.holder_user_id == y.user_id
        assert cb.holder_office_id == w.office(s, "EDU-DSE").id
        assert cb.pending_action.value == "examine" and cb.due_date == due
        assert ca.pending_action.value == "none" and ca.due_date is None  # carried over
        for cid in (a_id, b_id):
            reasons = [leg.reason for leg in legs(s, cid)]
            assert (
                reasons[-1] == "reassigned_on_exit" and reasons.count("allotted") == 1
            )  # re-allot adds no leg
        # the alert went back to open and reached case A's target
        s.refresh(alert)
        assert alert.status == AlertStatus.OPEN
        notified = set(s.scalars(sa.select(Notification.user_id).where(Notification.alert_id == alert.id)))
        assert x.user_id in notified and leaver.id in notified
        exit_row = s.scalars(sa.select(AuditLog).where(AuditLog.action == "membership.exit")).one()
        assert len(exit_row.after["items"]) == 4 and exit_row.after["counts"]["files"] == 2
        assert {i["to_membership"] for i in exit_row.after["items"]} == {str(x.id), str(y.id)}
        assert (
            len(s.scalars(sa.select(AuditLog).where(AuditLog.action == "ownership.reallotted_on_exit")).all())
            == 2
        )
        # the login stays active, with no membership and no function
        assert leaver.is_active and access.active_memberships(s, leaver) == []
        assert access.effective_permissions(s, leaver) == set()
        # a department admin adds a membership, which becomes primary
        h_actor, h_admin = w.actor(s, "health_admin")
        new = memberships.add(
            s, h_actor, h_admin, leaver, office=w.office(s, "HEALTH"), role=Role.DEPT_OFFICER
        )
        assert new.is_primary and leaver.office_id == w.office(s, "HEALTH").id


def test_refusals_write_nothing(two_cases):
    w, a_id, b_id = two_cases
    with w.Session() as s:
        actor, admin = w.actor(s, "edu_admin")
        m = w.membership(s, "edu_off1")
        x = w.membership(s, "edu_off2")
        p = memberships.exit_preview(s, admin, m)
        full = plan(p["items"], {i["key"]: str(x.id) for i in p["items"]})
        fp = p["items_fingerprint"]
        with pytest.raises(Conflict) as exc:
            memberships.end(s, actor, admin, m, reason="moving", assignments=full[:3], items_fingerprint=fp)
        assert exc.value.code == "unassigned_items" and exc.value.extra["items"] == [full[3]["key"]]
        with pytest.raises(MembershipError) as exc2:
            memberships.end(
                s, actor, admin, m, reason="moving", assignments=full + [full[0]], items_fingerprint=fp
            )
        assert exc2.value.code == "duplicate_item"
        for bad in (
            w.membership(s, "health_off"),  # another department
            w.membership(s, "edu_auditor"),  # State-wide
            m,  # the leaver
        ):
            wrong = [{**full[0], "to_membership": str(bad.id)}] + full[1:]
            with pytest.raises(MembershipError) as exc3:
                memberships.end(s, actor, admin, m, reason="moving", assignments=wrong, items_fingerprint=fp)
            assert exc3.value.code == "bad_target"
        assert m.is_active
        assert not s.scalars(
            sa.select(AuditLog).where(AuditLog.action.in_(["membership.exit", "membership.ended"]))
        ).all()
        # an item moved by the admin after the preview → stale, with the current items
        own.allot(s, actor, admin, s.get(Case, a_id), officer_user_id=x.user_id)
        with pytest.raises(Conflict) as exc4:
            memberships.end(s, actor, admin, m, reason="moving", assignments=full, items_fingerprint=fp)
        assert exc4.value.code == "stale_exit" and len(exc4.value.extra["items"]) == 2


def test_items_reassigned_ahead_disappear_and_an_empty_exit_ends(two_cases):
    w, a_id, b_id = two_cases
    with w.Session() as s:
        actor, admin = w.actor(s, "edu_admin")
        m = w.membership(s, "edu_off1")
        off2 = w.user(s, "edu_off2")
        for cid in (a_id, b_id):
            own.allot(
                s, actor, admin, s.get(Case, cid), officer_user_id=off2.id
            )  # the file follows the allotment
        p = memberships.exit_preview(s, admin, m)
        assert p["items"] == []
        memberships.end(
            s, actor, admin, m, reason="retired", assignments=[], items_fingerprint=p["items_fingerprint"]
        )
        assert not m.is_active


def test_primary_passes_to_the_other_membership_and_health_is_untouched(world):
    with world.Session() as s:
        actor, admin = world.actor(s, "edu_admin")
        leaver = world.user(s, "edu_off1")
        health_m = add_membership(s, leaver, world.office(s, "HEALTH"), Role.DEPT_OFFICER, "Section Officer")
        m = world.membership(s, "edu_off1")
        assert m.is_primary
        fp = memberships.fingerprint(memberships.exit_items(s, m))
        memberships.end(s, actor, admin, m, reason="transferred", assignments=[], items_fingerprint=fp)
        s.refresh(health_m)
        assert health_m.is_active and health_m.is_primary
        assert leaver.office_id == world.office(s, "HEALTH").id and leaver.role == Role.DEPT_OFFICER
        assert leaver.designation == "Section Officer"
        assert s.scalars(sa.select(AuditLog).where(AuditLog.action == "membership.primary_changed")).all()
        assert Permission.NOTES_ADD in access.effective_permissions(s, leaver)


def test_a_failure_on_the_last_item_leaves_everything_unchanged(two_cases, monkeypatch):
    w, a_id, b_id = two_cases
    from aslms.services import custody as custody_svc

    real = custody_svc.move_custody
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("disk full")
        return real(*args, **kwargs)

    monkeypatch.setattr(custody_svc, "move_custody", flaky)
    with w.Session() as s:
        actor, admin = w.actor(s, "edu_admin")
        m = w.membership(s, "edu_off1")
        x = w.membership(s, "edu_off2")
        p = memberships.exit_preview(s, admin, m)
        with pytest.raises(RuntimeError):
            memberships.end(
                s,
                actor,
                admin,
                m,
                reason="moving",
                assignments=plan(p["items"], {i["key"]: str(x.id) for i in p["items"]}),
                items_fingerprint=p["items_fingerprint"],
            )
        s.rollback()
    with w.Session() as s:
        assert w.membership(s, "edu_off1").is_active
        off1 = w.user(s, "edu_off1")
        assert {s.get(Custody, c).holder_user_id for c in (a_id, b_id)} == {off1.id}
        assert set(s.scalars(sa.select(CaseOwnership.officer_user_id))) == {off1.id}
