"""Head changes (design `user-memberships`, decisions 15-18, 24): a department admin requests and the super admin
approves; the super admin changes the head at once; one head per department; the outgoing head is retyped or
exited item by item; stale proposals are refused at approval; the membership endpoints never make or remove a
head; tickets are frozen once closed and visible only to the panel's holders."""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from aslms.domain.events import AuditLog
from aslms.domain.org import UserMembership
from aslms.domain.ownership import CaseOwnership, OwnershipStatus
from aslms.domain.reference import Role, TicketKind
from aslms.domain.tickets import AdminTicket, MembershipDocument, TicketStatus
from aslms.services import access, memberships, tickets
from aslms.services import ownership as own
from aslms.services.access import Conflict, Forbidden
from aslms.services.scanner import FakeScanner
from aslms.services.storage import LocalStore
from tests import samplefiles as sf
from tests.db.world import add_membership, make_case

MAX = 20 * 1024 * 1024


@pytest.fixture()
def io(tmp_path):
    return {"scanner": FakeScanner(), "store": LocalStore(tmp_path / "store"), "max_bytes": MAX}


def order_file(text: str = "Government order appointing the head") -> tickets.IncomingFile:
    return tickets.IncomingFile(data=sf.text_pdf([text]), filename="order.pdf")


def actions(s, ticket_id) -> list[str]:
    return list(
        s.scalars(
            sa.select(AuditLog.action)
            .where(AuditLog.entity_id == ticket_id)
            .order_by(AuditLog.created_at, AuditLog.id)
        )
    )


def test_department_admin_sets_a_head_by_email_with_an_order_and_the_super_admin_approves(world, io):
    with world.Session() as s:
        h_actor, h_admin = world.actor(s, "health_admin")
        person = world.user(s, "edu_off1")
        t = tickets.request_head_change(
            s,
            h_actor,
            h_admin,
            {
                "operation": "set",
                "department_code": "HEALTH",
                "incoming": {"email": "off1.edu@example.org", "designation": "Secretary"},
            },
            request_remark="as per the order",
            files=[order_file()],
            **io,
        )
        assert t.status == TicketStatus.OPEN and t.ref_no.startswith("ASLMS/HEALTH/TKT/")
        assert len(tickets.documents_of_ticket(s, t)) == 1
        assert [m.department_id for m in access.active_memberships(s, person)] == [world.office(s, "EDU").id]
        assert memberships.head_of(s, world.office(s, "HEALTH")) is None  # nothing changes until approval
        r_actor, root = world.actor(s, "root")
        tickets.approve(s, r_actor, root, t, "approved")
        head = memberships.head_of(s, world.office(s, "HEALTH"))
        assert (
            head.user_id == person.id
            and head.role == Role.DEPT_HEAD
            and head.office_id == world.office(s, "HEALTH").id
        )
        assert (
            t.status == TicketStatus.APPROVED and t.target_membership_id == head.id and t.result["incoming"]
        )
        added = s.scalars(
            sa.select(AuditLog).where(AuditLog.action == "membership.added", AuditLog.entity_id == head.id)
        ).one()
        assert added.after["ticket_ref"] == t.ref_no
        assert s.scalars(
            sa.select(MembershipDocument).where(MembershipDocument.membership_id == head.id)
        ).one()
        assert actions(s, t.id) == ["ticket.document_attached", "ticket.opened", "ticket.approved"]
        # a second set for HEALTH → head_exists
        with pytest.raises(Conflict) as exc:
            tickets.request_head_change(
                s,
                h_actor,
                h_admin,
                {
                    "operation": "set",
                    "department_code": "HEALTH",
                    "incoming": {"email": "off2.edu@example.org"},
                },
                **io,
            )
        assert exc.value.code == "head_exists"


def test_set_with_an_existing_officer_membership(world, io):
    with world.Session() as s:
        h_actor, h_admin = world.actor(s, "health_admin")
        m = world.membership(s, "health_off")
        t = tickets.request_head_change(
            s,
            h_actor,
            h_admin,
            {"operation": "set", "department_code": "HEALTH", "incoming": {"membership_id": str(m.id)}},
            **io,
        )
        assert t.payload["incoming"]["role_from"] == "dept_officer"
        r_actor, root = world.actor(s, "root")
        tickets.approve(s, r_actor, root, t)
        s.refresh(m)
        assert m.role == Role.DEPT_HEAD and world.user(s, "health_off").role == Role.DEPT_HEAD  # the mirror


def test_one_head_per_department_service_and_index(world):
    with world.Session() as s:
        with pytest.raises(Conflict) as exc:
            memberships.insert_membership(
                s,
                access.actor_for(world.user(s, "root")),
                world.user(s, "health_off"),
                office=world.office(s, "EDU"),
                role=Role.DEPT_HEAD,
            )
        assert exc.value.code == "one_dept_head"
        s.rollback()
    with world.Session() as s:
        edu = world.office(s, "EDU")
        s.add(
            UserMembership(
                user_id=world.user(s, "health_off").id,
                office_id=edu.id,
                department_id=edu.id,
                role=Role.DEPT_HEAD,
            )
        )
        with pytest.raises(sa.exc.IntegrityError, match="ix_user_memberships_one_dept_head"):
            s.flush()


def test_replace_with_retype_keeps_the_old_head_as_an_officer(world, io):
    with world.Session() as s:
        a_actor, admin = world.actor(s, "edu_admin")
        old_head = world.user(s, "edu_head")
        case = make_case(s)
        own.claim(s, a_actor, admin, case, officer_user_id=old_head.id)
        incoming = world.membership(s, "edu_off1")
        t = tickets.request_head_change(
            s,
            a_actor,
            admin,
            {
                "operation": "replace",
                "department_code": "EDU",
                "incoming": {"membership_id": str(incoming.id)},
                "outgoing": {"mode": "retype"},
            },
            **io,
        )
        r_actor, root = world.actor(s, "root")
        tickets.approve(s, r_actor, root, t)
        old_m = world.membership(s, "edu_head")
        assert old_m.role == Role.DEPT_OFFICER and old_m.is_active
        assert memberships.head_of(s, world.office(s, "EDU")).id == incoming.id
        assert s.scalars(sa.select(CaseOwnership.officer_user_id)).one() == old_head.id  # keeps the allotment


def test_replace_with_exit_and_a_stale_exit_at_approval(world, io):
    with world.Session() as s:
        a_actor, admin = world.actor(s, "edu_admin")
        head = world.user(s, "edu_head")
        c1, c2 = make_case(s), make_case(s)
        own.claim(s, a_actor, admin, c1, officer_user_id=head.id)
        head_m = world.membership(s, "edu_head")
        p = memberships.exit_preview(s, admin, head_m)
        off2 = world.membership(s, "edu_off2")
        outgoing = {
            "mode": "exit",
            "reason": "transferred",
            "items_fingerprint": p["items_fingerprint"],
            "assignments": [{"key": i["key"], "to_membership": str(off2.id)} for i in p["items"]],
        }
        payload = {
            "operation": "replace",
            "department_code": "EDU",
            "incoming": {"membership_id": str(world.membership(s, "edu_off1").id)},
            "outgoing": outgoing,
        }
        t = tickets.request_head_change(s, a_actor, admin, payload, **io)
        # the world moves: another case is allotted to the head after the request
        own.claim(s, a_actor, admin, c2, officer_user_id=head.id)
        r_actor, root = world.actor(s, "root")
        with pytest.raises(tickets.TicketStale) as exc:
            tickets.approve(s, r_actor, root, t)
        assert exc.value.code == "ticket_stale"
        assert t.status == TicketStatus.OPEN and "ticket.approve_refused" in actions(s, t.id)
        assert world.membership(s, "edu_head").role == Role.DEPT_HEAD
        tickets.reject(s, r_actor, root, t, "items changed; request again")
        # a fresh request with the current preview is applied
        p = memberships.exit_preview(s, admin, head_m)
        outgoing.update(
            items_fingerprint=p["items_fingerprint"],
            assignments=[{"key": i["key"], "to_membership": str(off2.id)} for i in p["items"]],
        )
        t2 = tickets.request_head_change(s, a_actor, admin, payload, **io)
        tickets.approve(s, r_actor, root, t2)
        assert not head_m.is_active
        assert set(
            s.scalars(
                sa.select(CaseOwnership.officer_user_id).where(CaseOwnership.status == OwnershipStatus.ACTIVE)
            )
        ) == {off2.user_id}
        assert memberships.head_of(s, world.office(s, "EDU")).user_id == world.user(s, "edu_off1").id


def test_end_is_the_super_admins_and_replace_needs_a_head(world, io):
    with world.Session() as s:
        a_actor, admin = world.actor(s, "edu_admin")
        h_actor, h_admin = world.actor(s, "health_admin")
        with pytest.raises(Conflict) as exc:
            tickets.request_head_change(
                s,
                h_actor,
                h_admin,
                {
                    "operation": "replace",
                    "department_code": "HEALTH",
                    "incoming": {"email": "off1.edu@example.org"},
                    "outgoing": {"mode": "retype"},
                },
                **io,
            )
        assert exc.value.code == "no_head"
        with pytest.raises(Forbidden) as exc2:
            tickets.request_head_change(
                s,
                a_actor,
                admin,
                {"operation": "end", "department_code": "EDU", "outgoing": {"mode": "retype"}},
                **io,
            )
        assert exc2.value.code == "super_admin_only"
        r_actor, root = world.actor(s, "root")
        t = tickets.request_head_change(
            s,
            r_actor,
            root,
            {"operation": "end", "department_code": "EDU", "outgoing": {"mode": "retype"}},
            **io,
        )
        assert t.status == TicketStatus.APPROVED and t.decided_by_user_id == root.id
        assert memberships.head_of(s, world.office(s, "EDU")) is None
        assert world.membership(s, "edu_head").role == Role.DEPT_OFFICER
        assert "EDU" in [o.code for o in tickets.departments_without_head(s)]


def test_end_with_exit_by_the_super_admin(world, io):
    with world.Session() as s:
        r_actor, root = world.actor(s, "root")
        head_m = world.membership(s, "edu_head")
        fp = memberships.fingerprint(memberships.exit_items(s, head_m))
        t = tickets.request_head_change(
            s,
            r_actor,
            root,
            {
                "operation": "end",
                "department_code": "EDU",
                "outgoing": {"mode": "exit", "assignments": [], "items_fingerprint": fp, "reason": "retired"},
            },
            **io,
        )
        assert t.status == TicketStatus.APPROVED and not head_m.is_active
        assert access.active_memberships(s, world.user(s, "edu_head")) == []


def test_membership_endpoints_never_make_or_remove_a_head(world):
    with world.Session() as s:
        for key in ("edu_admin", "root"):
            actor, who = world.actor(s, key)
            head_m = world.membership(s, "edu_head")
            with pytest.raises(Conflict) as e1:
                memberships.update(s, actor, who, head_m, role=Role.DEPT_OFFICER)
            with pytest.raises(Conflict) as e2:
                memberships.end(
                    s, actor, who, head_m, reason="moving", assignments=[], items_fingerprint=None
                )
            with pytest.raises(Conflict) as e3:
                access.set_enabled(s, actor, who, world.user(s, "edu_head"), False)
            assert {e1.value.code, e2.value.code, e3.value.code} == {"head_required"}
        actor, root = world.actor(s, "root")
        with pytest.raises(Conflict) as e4:
            memberships.update(s, actor, root, world.membership(s, "health_off"), role=Role.DEPT_HEAD)
        assert e4.value.code == "use_head_change"


def test_super_admin_direct_replace_supersedes_an_open_ticket(world, io):
    with world.Session() as s:
        a_actor, admin = world.actor(s, "edu_admin")
        open_t = tickets.request_head_change(
            s,
            a_actor,
            admin,
            {
                "operation": "replace",
                "department_code": "EDU",
                "incoming": {"membership_id": str(world.membership(s, "edu_off1").id)},
                "outgoing": {"mode": "retype"},
            },
            **io,
        )
        # one open ticket per department
        with pytest.raises(Conflict) as exc:
            tickets.request_head_change(
                s,
                a_actor,
                admin,
                {
                    "operation": "replace",
                    "department_code": "EDU",
                    "incoming": {"membership_id": str(world.membership(s, "edu_off2").id)},
                    "outgoing": {"mode": "retype"},
                },
                **io,
            )
        assert exc.value.code == "ticket_open"
        r_actor, root = world.actor(s, "root")
        direct = tickets.request_head_change(
            s,
            r_actor,
            root,
            {
                "operation": "replace",
                "department_code": "EDU",
                "incoming": {"membership_id": str(world.membership(s, "edu_off2").id)},
                "outgoing": {"mode": "retype"},
            },
            files=[order_file("Notification of the new head")],
            **io,
        )
        assert direct.status == TicketStatus.APPROVED and direct.decided_at is not None
        assert open_t.status == TicketStatus.REJECTED and direct.ref_no in open_t.decision_remark
        head = memberships.head_of(s, world.office(s, "EDU"))
        assert head.user_id == world.user(s, "edu_off2").id
        assert s.scalars(
            sa.select(MembershipDocument).where(MembershipDocument.membership_id == head.id)
        ).all()
        assert actions(s, direct.id) == ["ticket.document_attached", "ticket.opened", "ticket.approved"]


def test_reject_withdraw_and_the_frozen_closed_ticket(world, io):
    with world.Session() as s:
        a_actor, admin = world.actor(s, "edu_admin")
        payload = {
            "operation": "replace",
            "department_code": "EDU",
            "incoming": {"membership_id": str(world.membership(s, "edu_off1").id)},
            "outgoing": {"mode": "retype"},
        }
        t = tickets.request_head_change(s, a_actor, admin, payload, **io)
        r_actor, root = world.actor(s, "root")
        with pytest.raises(tickets.TicketError):
            tickets.reject(s, r_actor, root, t, "")
        with pytest.raises(Forbidden):
            tickets.approve(s, a_actor, admin, t)  # the department admin does not decide
        tickets.reject(s, r_actor, root, t, "no order yet")
        assert t.status == TicketStatus.REJECTED and world.membership(s, "edu_head").role == Role.DEPT_HEAD
        with pytest.raises(tickets.TicketError) as exc:
            tickets.approve(s, r_actor, root, t)
        assert exc.value.code == "ticket_closed"
        t2 = tickets.request_head_change(s, a_actor, admin, payload, **io)
        with pytest.raises(Forbidden):
            tickets.withdraw(s, r_actor, root, t2)  # the proposer only
        tickets.withdraw(s, a_actor, admin, t2, "sent in error")
        assert t2.status == TicketStatus.WITHDRAWN and t2.decided_by_user_id == admin.id
        assert actions(s, t2.id) == ["ticket.opened", "ticket.withdrawn"]
        s.flush()
        with pytest.raises(sa.exc.DBAPIError, match="closed"):
            with s.begin_nested():
                s.execute(
                    sa.update(AdminTicket).where(AdminTicket.id == t.id).values(request_remark="changed")
                )


def test_open_ticket_index_refuses_a_race(world, io):
    with world.Session() as s:
        a_actor, admin = world.actor(s, "edu_admin")
        t = tickets.request_head_change(
            s,
            a_actor,
            admin,
            {
                "operation": "replace",
                "department_code": "EDU",
                "incoming": {"membership_id": str(world.membership(s, "edu_off1").id)},
                "outgoing": {"mode": "retype"},
            },
            **io,
        )
        twin = AdminTicket(
            ref_no="ASLMS/EDU/TKT/2026/999999",
            kind=TicketKind.HEAD_CHANGE,
            status=TicketStatus.OPEN,
            department_id=t.department_id,
            requested_by_user_id=admin.id,
            requested_by_membership_id=t.requested_by_membership_id,
            payload=t.payload,
        )
        s.add(twin)
        with pytest.raises(sa.exc.IntegrityError, match="ix_admin_tickets_one_open_head_change"):
            s.flush()


def test_requester_limits_and_visibility(world, io):
    with world.Session() as s:
        a_actor, admin = world.actor(s, "edu_admin")
        # the department admin cannot make a dept_admin membership (themselves) the head
        with pytest.raises(Forbidden) as exc:
            tickets.request_head_change(
                s,
                a_actor,
                admin,
                {
                    "operation": "replace",
                    "department_code": "EDU",
                    "incoming": {"membership_id": str(world.membership(s, "edu_admin").id)},
                    "outgoing": {"mode": "retype"},
                },
                **io,
            )
        assert exc.value.code == "not_delegable"
        # nor act in another department
        with pytest.raises(Forbidden):
            tickets.request_head_change(
                s,
                a_actor,
                admin,
                {
                    "operation": "set",
                    "department_code": "HEALTH",
                    "incoming": {"email": "off1.edu@example.org"},
                },
                **io,
            )
        t = tickets.request_head_change(
            s,
            a_actor,
            admin,
            {
                "operation": "replace",
                "department_code": "EDU",
                "incoming": {"membership_id": str(world.membership(s, "edu_off1").id)},
                "outgoing": {"mode": "retype"},
            },
            **io,
        )
        assert tickets.get(s, admin, t.ref_no.replace("/", "-")).id == t.id
        assert tickets.get(s, world.user(s, "root"), str(t.id)).id == t.id
        for key in ("health_admin", "edu_off1", "edu_head"):
            with pytest.raises(tickets.TicketNotFound):
                tickets.get(s, world.user(s, key), t.ref_no)
        items, total = tickets.list_tickets(s, world.user(s, "health_admin"))
        assert total == 0 and items == []
        items, total = tickets.list_tickets(s, admin)
        assert total == 1 and items[0]["ref_no"] == t.ref_no and items[0]["target"]["role_to"] == "dept_head"
        counts = tickets.counts(s, world.user(s, "root"))
        assert (
            counts["open"] == 1
            and counts["open_by_department"] == {"EDU": 1}
            and "departments_without_head" in counts
        )
        assert "departments_without_head" not in tickets.counts(s, admin)
        # a membership in the department added for a person elsewhere can be proposed (by e-mail it is refused:
        # the person already has a membership there)
        add_membership(s, world.user(s, "health_off"), world.office(s, "EDU-DSE"), Role.DIRECTORATE_USER)
        r_actor, root = world.actor(s, "root")
        tickets.reject(s, r_actor, root, t, "x" * 5)
        with pytest.raises(Conflict) as exc2:
            tickets.request_head_change(
                s,
                a_actor,
                admin,
                {
                    "operation": "replace",
                    "department_code": "EDU",
                    "incoming": {"email": "off.health@example.org"},
                    "outgoing": {"mode": "retype"},
                },
                **io,
            )
        assert exc2.value.code == "one_per_department"
