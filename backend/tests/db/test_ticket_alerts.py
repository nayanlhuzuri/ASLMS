"""Ticket alerts (design `user-memberships`, decision 19): opening raises one case-less `admin_ticket` alert
(severity `normal`) to the super admin — in-app at once, e-mail through the digest unless they asked for no
digest; a decision closes it and alerts the proposer only; nobody else sees either; the mails name the ticket,
never the payload; only `admin_ticket` alerts may be case-less."""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from aslms.domain.alerts import Alert, AlertStatus, Notification
from aslms.domain.org import Channel
from aslms.domain.reference import AlertKind
from aslms.services import alerts, notifications, tickets
from aslms.services.mailer import RecordingMailer


def _request(s, world, remark="the minister's order of 1 Oct"):
    a_actor, admin = world.actor(s, "edu_admin")
    return tickets.request_head_change(
        s,
        a_actor,
        admin,
        {
            "operation": "replace",
            "department_code": "EDU",
            "incoming": {"membership_id": str(world.membership(s, "edu_off1").id)},
            "outgoing": {"mode": "retype"},
        },
        request_remark=remark,
    )


def _ticket_alerts(s, t) -> list[Alert]:
    return list(
        s.scalars(
            sa.select(Alert)
            .where(Alert.data["ticket_id"].astext == str(t.id))
            .order_by(Alert.created_at, Alert.id)
        )
    )


def test_opening_alerts_the_super_admin_and_approval_alerts_the_proposer(world):
    with world.Session() as s:
        t = _request(s, world)
        (opened,) = _ticket_alerts(s, t)
        assert (
            opened.case_id is None
            and opened.kind == AlertKind.ADMIN_TICKET
            and opened.severity.value == "normal"
        )
        assert t.ref_no in opened.title and "minister" not in (opened.body or "")
        root = world.user(s, "root")
        rows = s.scalars(sa.select(Notification).where(Notification.alert_id == opened.id)).all()
        assert {(n.user_id, n.channel) for n in rows} == {
            (root.id, Channel.IN_APP)
        }  # the digest, not a mail now
        page = alerts.list_for_user(s, root)
        assert [i["ticket_ref"] for i in page.items] == [t.ref_no] and page.items[0]["case"] is None
        assert alerts.counts_for_user(s, root)["open"]["normal"] == 1
        assert alerts.get_for_user(s, root, opened.ref_no).id == opened.id
        # nobody else sees it
        for key in ("edu_admin", "oversight", "edu_auditor", "health_admin"):
            u = world.user(s, key)
            assert alerts.list_for_user(s, u).total == 0
            with pytest.raises(alerts.AlertNotFound):
                alerts.get_for_user(s, u, opened.ref_no)
        r_actor, _ = world.actor(s, "root")
        tickets.approve(s, r_actor, root, t, "approved as proposed")
        s.refresh(opened)
        assert opened.status == AlertStatus.DONE
        decided = _ticket_alerts(s, t)[1]
        assert decided.data["event"] == "approved" and decided.office_id == world.office(s, "EDU").id
        admin = world.user(s, "edu_admin")
        assert {
            n.user_id for n in s.scalars(sa.select(Notification).where(Notification.alert_id == decided.id))
        } == {admin.id}
        assert [i["ticket_ref"] for i in alerts.list_for_user(s, admin).items] == [t.ref_no]
        assert alerts.list_for_user(s, world.user(s, "edu_off1")).total == 0
        # the proposer acknowledges it as any alert
        a_actor, _ = world.actor(s, "edu_admin")
        alerts.acknowledge(s, a_actor, admin, decided)
        assert decided.status == AlertStatus.ACKNOWLEDGED


def test_no_digest_means_an_immediate_mail_naming_the_ticket(world):
    with world.Session() as s:
        r_actor, root = world.actor(s, "root")
        notifications.set_preferences(s, r_actor, root, {"email": {"digest": "none"}})
        t = _request(s, world, remark="secret remark")
        (opened,) = _ticket_alerts(s, t)
        channels = {
            n.channel for n in s.scalars(sa.select(Notification).where(Notification.alert_id == opened.id))
        }
        assert channels == {Channel.IN_APP, Channel.EMAIL}
        mailer = RecordingMailer()
        counters = notifications.send_pending(s, mailer, record_run=False)
        assert counters["sent"] == 1
        mail = mailer.sent[0]
        assert mail.to == "root@example.org" and t.ref_no in mail.text and "EDU" in mail.text
        assert "secret remark" not in mail.text and "membership_id" not in mail.text
        assert "/admin/tickets/" in mail.text


def test_the_digest_names_the_ticket(world):
    with world.Session() as s:
        t = _request(s, world)
        counters = notifications.build_digests(s, record_run=False)
        assert counters["built"] >= 1
        from aslms.domain.alerts import Digest

        digest = s.scalars(sa.select(Digest).where(Digest.user_id == world.user(s, "root").id)).one()
        assert t.ref_no in digest.body and "/admin/tickets/" in digest.body


def test_only_admin_ticket_alerts_are_caseless(world):
    with world.Session() as s:
        s.add(
            Alert(
                case_id=None,
                kind=AlertKind.OWNERSHIP,
                office_id=world.office(s, "EDU").id,
                title="x",
                data={},
                dedupe_key="test:caseless",
                ref_no="ASLMS/GOA/ALR/2026/999998",
            )
        )
        with pytest.raises(sa.exc.IntegrityError, match="ck_alerts_case"):
            s.flush()
    with world.Session() as s, pytest.raises(alerts.AlertError):
        alerts.raise_alert(
            s, case=None, kind=AlertKind.OWNERSHIP, key="k", office=world.office(s, "EDU"), severity="normal"
        )
