"""Every reading path of a `new_note` alert applies the note rule (design alerts-visibility-roles, decision 4): the
case's Alerts tab, the detail and acknowledge (404), the caller's own list and counts, and the timeline's
`alert_raised` row; an alert whose note id is unknown or missing is hidden."""

from __future__ import annotations

import uuid

import pytest

from aslms.domain.alerts import Severity
from aslms.domain.cases import Case
from aslms.domain.ownership import CaseOwnership, OwnershipRole
from aslms.domain.reference import AlertKind
from aslms.services import alerts, case_detail
from tests.db import alerts_support as h
from tests.db import docs_support as ds
from tests.db import workflow_support as w


@pytest.fixture()
def scene(world):
    """An EDU case allotted to off1, held by the EDU-DHE directorate user, watched by HEALTH, with a private and a
    case-scope note by the EDU admin, both alerted."""
    w.widen(world)
    with world.Session() as s:
        case = w.claimed_case(s, world)
        w.send(s, world, "edu_off1", case, "dhe_user")
        s.add(
            CaseOwnership(case_id=case.id, office_id=world.offices["HEALTH"].id, role=OwnershipRole.WATCHER)
        )
        private, _ = w.note(s, world, "edu_admin", case, body="office only", visibility_="private_to_office")
        shared, _ = w.note(s, world, "edu_admin", case, body="for all", visibility_="case_scope")
        s.commit()
        alerts.scan_events(s, now=h.now_utc())
        s.commit()
        by_note = {a.data["note_id"]: a for a in h.alerts_of(s, case, AlertKind.NEW_NOTE)}
        return {
            "case": case.id,
            "private": by_note[str(private.id)].ref_no,
            "shared": by_note[str(shared.id)].ref_no,
        }


def tab_refs(s, world, key, case_id) -> set[str]:
    _, user = world.actor(s, key)
    page = alerts.alerts_for_case(s, user, s.get(Case, case_id), limit=200)
    return {i["ref_no"] for i in page.items if i["kind"] == "new_note"}


def test_private_note_alert_hidden_from_department_reader_who_cannot_read_it(world, scene, tmp_path):
    with world.Session() as s:
        # the EDU-DHE holder works on the case and the alert is addressed to EDU, but the note is EDU's own
        assert tab_refs(s, world, "dhe_user", scene["case"]) == {scene["shared"]}
        assert tab_refs(s, world, "edu_off1", scene["case"]) == {scene["shared"], scene["private"]}
        _, dhe = world.actor(s, "dhe_user")
        with pytest.raises(alerts.AlertNotFound):
            alerts.get_for_user(s, dhe, scene["private"])
        assert alerts.get_for_user(s, dhe, scene["shared"]) is not None
    api = ds.make_api(world, tmp_path)
    try:
        headers = w.login(api, "dhe_user")
        url_ref = scene["private"].replace("/", "-")
        assert api.get(f"/alerts/{url_ref}", headers=headers).status_code == 404
        assert api.post(f"/alerts/{url_ref}/acknowledge", headers=headers, json={}).status_code == 404
        shared_ref = scene["shared"].replace("/", "-")
        assert api.get(f"/alerts/{shared_ref}", headers=headers).status_code == 200
    finally:
        api.__exit__(None, None, None)


def test_private_note_alert_raised_row_hidden_on_timeline(world, scene):
    with world.Session() as s:
        case = s.get(Case, scene["case"])

        def alert_rows(key: str) -> set[str]:
            _, user = world.actor(s, key)
            items = case_detail.timeline(s, user, case, limit=200).items
            return {i["payload"]["ref_no"] for i in items if i["type"] == "alert_raised"}

        assert scene["private"] not in alert_rows("dhe_user")
        assert scene["shared"] in alert_rows("dhe_user")
        assert scene["private"] not in alert_rows("oversight")
        assert scene["private"] in alert_rows("edu_off1")
        assert scene["private"] in alert_rows("edu_auditor")


def test_private_note_alert_hidden_from_state_oversight_alerts_tab(world, scene):
    with world.Session() as s:
        for key in ("oversight", "central_op"):
            assert tab_refs(s, world, key, scene["case"]) == {scene["shared"]}, key
        for key in ("edu_auditor", "root"):
            assert tab_refs(s, world, key, scene["case"]) == {scene["shared"], scene["private"]}, key


def test_alert_with_unknown_note_id_is_hidden(world, scene):
    with world.Session() as s:
        case = s.get(Case, scene["case"])
        off1 = world.user(s, "edu_off1")
        made = []
        for n, data in enumerate(({"note_id": str(uuid.uuid4())}, {})):
            alert, _ = alerts.raise_alert(
                s,
                case=case,
                kind=AlertKind.NEW_NOTE,
                key=f"new_note:test-{n}",
                office=world.office(s, "EDU"),
                severity=Severity.NORMAL,
                data=data,
                recipients=[off1],
            )
            made.append(alert.ref_no)
        s.commit()
        listed = {i["ref_no"] for i in alerts.list_for_user(s, off1, limit=200).items}
        assert not set(made) & listed
        assert scene["shared"] in listed
        counts = alerts.counts_for_user(s, off1)
        assert sum(counts["open"].values()) == len(
            [i for i in alerts.list_for_user(s, off1, status="open,acknowledged", limit=200).items]
        )
        assert not set(made) & tab_refs(s, world, "edu_off1", scene["case"])
        for ref in made:
            with pytest.raises(alerts.AlertNotFound):
                alerts.get_for_user(s, off1, ref)
