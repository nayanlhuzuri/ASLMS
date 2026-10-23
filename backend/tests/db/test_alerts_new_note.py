"""The new-note alert (design alerts-visibility-roles, decisions 1-7): one `new_note` alert per permanent note, to the
people working on the case who can read it (custody holder, primary owner chain, watchers), never the author and never
standing counsel; drafts alert only when the file move makes them permanent, excluding their author but not the mover;
a correction says so; an unowned case raises nothing; a re-scan raises nothing twice; and the note text is in no alert,
notification, mail, digest or event."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
import sqlalchemy as sa

from aslms.domain.alerts import Digest, Notification, Severity
from aslms.domain.cases import Case
from aslms.domain.events import Event
from aslms.domain.org import Channel, DigestMode
from aslms.domain.ownership import CaseOwnership, OwnershipRole
from aslms.domain.reference import AlertKind, EventType
from aslms.services import alerts
from aslms.services import notifications as notif
from aslms.services.mailer import RecordingMailer
from tests.db import alerts_support as h
from tests.db import workflow_support as w
from tests.db.test_notifications import set_email_prefs
from tests.db.world import USERS, make_case

MARKER = "ZEBRA-7Q-NOTE-MARKER"


def email(key: str) -> str:
    return w.email_of(key) if key in w.EXTRA else USERS[key][0]


@pytest.fixture()
def scene(world):
    """An EDU case allotted to off1 who sent the file to the EDU-DHE directorate user; HEALTH watches it."""
    w.widen(world)
    with world.Session() as s:
        case = w.claimed_case(s, world)
        w.send(s, world, "edu_off1", case, "dhe_user")
        s.add(
            CaseOwnership(case_id=case.id, office_id=world.offices["HEALTH"].id, role=OwnershipRole.WATCHER)
        )
        s.commit()
        return case.id


def scan(s) -> dict:
    counters = alerts.scan_events(s, now=h.now_utc())
    s.commit()
    return counters


def note_alerts(s, case_id) -> list:
    return h.alerts_of(s, s.get(Case, case_id), AlertKind.NEW_NOTE)


def test_case_scope_note_alerts_holder_owner_and_watchers_not_the_author(world, scene):
    with world.Session() as s:
        note, is_draft = w.note(
            s, world, "edu_admin", s.get(Case, scene), body="hearing went well", kind="hearing"
        )
        assert not is_draft
        s.commit()
        scan(s)
        [alert] = note_alerts(s, scene)
        assert alert.dedupe_key == f"new_note:{note.id}"
        assert alert.office_id == world.offices["EDU"].id
        assert Severity(alert.severity) == Severity.NORMAL
        assert h.recipient_emails(s, alert) == {email("edu_off1"), email("dhe_user"), email("health_admin")}
        assert alert.title.startswith("New hearing note: ")
        assert alert.data["note_id"] == str(note.id) and alert.data["ref_no"] == note.ref_no
        assert alert.data["kind_label"] == "Hearing note" and alert.data["office_code"] == "EDU"
        assert alert.data["visibility"] == "case_scope" and alert.data["finalised"] is False
        assert "hearing went well" not in alert.title + alert.body + str(alert.data)


def test_private_note_alerts_only_those_who_can_read_it(world, scene):
    with world.Session() as s:
        w.note(s, world, "edu_admin", s.get(Case, scene), body="office only", visibility_="private_to_office")
        s.commit()
        scan(s)
        [alert] = note_alerts(s, scene)
        # the EDU-DHE holder (another unit), the HEALTH watcher and standing counsel get nothing
        assert h.recipient_emails(s, alert) == {email("edu_off1")}


def test_counsel_shared_note_skips_counsel_as_for_every_case_alert(world):
    w.widen(world)
    with world.Session() as s:
        case = w.claimed_case(s, world)
        w.send(s, world, "edu_off1", case, "edu_counsel", pending_action_="opinion")
        w.note(s, world, "edu_admin", case, body="for counsel", visibility_="counsel_shared")
        s.commit()
        scan(s)
        [alert] = h.alerts_of(s, case, AlertKind.NEW_NOTE)
        assert h.recipient_emails(s, alert) == {email("edu_off1")}


def test_draft_alerts_nothing_until_the_file_moves(world, scene):
    with world.Session() as s:
        case = s.get(Case, scene)
        _, is_draft = w.note(s, world, "dhe_user", case, body="draft of the holder")
        assert is_draft
        s.commit()
        scan(s)
        assert note_alerts(s, scene) == []
        assert w.events(s, scene, EventType.NOTE_ADDED) == []  # a draft emits no event
        w.send(s, world, "dhe_user", case, "edu_off1")
        s.commit()
        scan(s)
        [alert] = note_alerts(s, scene)
        assert alert.data["finalised"] is True
        assert email("dhe_user") not in h.recipient_emails(s, alert)
        assert email("edu_off1") in h.recipient_emails(s, alert)


def test_finalised_drafts_alert_once_each_excluding_their_author_not_the_mover(world, scene):
    with world.Session() as s:
        case = s.get(Case, scene)
        w.note(s, world, "dhe_user", case, body="first draft")
        w.note(s, world, "dhe_user", case, body="second draft")
        s.commit()
        w.recall(s, world, "edu_admin", case)
        s.commit()
        scan(s)
        found = note_alerts(s, scene)
        assert len(found) == 2 and all(a.data["finalised"] for a in found)
        assert [a.data["seq_no"] for a in found] == sorted(a.data["seq_no"] for a in found)
        for a in found:
            got = h.recipient_emails(s, a)
            assert email("edu_admin") in got  # the recaller never saw the drafts and is told of them
            assert email("dhe_user") not in got  # their author
        scan(s)
        assert len(note_alerts(s, scene)) == 2


def test_correction_alert_says_note_corrected(world, scene):
    with world.Session() as s:
        case = s.get(Case, scene)
        original, _ = w.note(s, world, "edu_admin", case, body="first version")
        w.note(s, world, "edu_admin", case, body="second version", supersedes=original.ref_no)
        s.commit()
        scan(s)
        found = note_alerts(s, scene)
        assert len(found) == 2
        correction = next(a for a in found if a.data["supersedes_ref_no"])
        assert correction.data["supersedes_ref_no"] == original.ref_no
        assert correction.title.startswith("Note corrected: ")


def test_note_on_unowned_case_raises_nothing(world):
    with world.Session() as s:
        case = make_case(s)
        h.event(s, case, EventType.NOTE_ADDED, {"note_id": str(uuid.uuid4())}, scoped=True)
        s.commit()
        counters = scan(s)
        assert counters["skipped_unowned"] >= 1 and counters["alerts_new"] == 0
        assert h.alerts_of(s, case, AlertKind.NEW_NOTE) == []


def test_rescan_does_not_raise_twice(world, scene):
    with world.Session() as s:
        w.note(s, world, "edu_admin", s.get(Case, scene), body="once")
        s.commit()
        scan(s)
        assert len(note_alerts(s, scene)) == 1
        # the overlap re-reads the event
        again = alerts.scan_events(s, now=h.now_utc() + timedelta(minutes=5))
        s.commit()
        assert again["alerts_new"] == 0 and len(note_alerts(s, scene)) == 1


def test_note_text_never_in_alert_notification_mail_or_digest(world, scene):
    with world.Session() as s:
        set_email_prefs(s, world.user(s, "edu_off1"), digest=DigestMode.NONE)  # an immediate mail
        set_email_prefs(s, world.user(s, "health_admin"), digest=DigestMode.DAILY)  # the digest
        w.note(s, world, "edu_admin", s.get(Case, scene), body=f"confidential {MARKER} advice")
        s.commit()
        scan(s)
        [alert] = note_alerts(s, scene)
        assert MARKER not in f"{alert.title} {alert.body} {alert.data}"
        rows = list(s.scalars(sa.select(Notification).where(Notification.alert_id == alert.id)).all())
        assert any(Channel(n.channel) == Channel.EMAIL for n in rows)
        assert all(MARKER not in f"{n.title} {n.body}" for n in rows)
        mailer = RecordingMailer()
        notif.send_pending(s, mailer, now=h.now_utc())
        notif.build_digests(s, now=h.now_utc() + timedelta(minutes=1))
        s.commit()
        assert mailer.sent and all(MARKER not in f"{m.subject} {m.text}" for m in mailer.sent)
        digests = list(s.scalars(sa.select(Digest)).all())
        assert digests and all(MARKER not in (d.body or "") for d in digests)
        payloads = s.scalars(sa.select(Event.payload).where(Event.case_id == scene)).all()
        assert all(MARKER not in str(p) for p in payloads)
