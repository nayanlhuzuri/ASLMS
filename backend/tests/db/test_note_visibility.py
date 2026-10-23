"""Note visibility (design custody-workflow, decisions 17, 20): the three visibilities across types, the two
switches (`notes.view_private_office`, `notes.view_counsel_shared` for counsel), a two-membership reader seeing the
private notes of both offices, a reader without sight of the case seeing nothing, and the timeline following the
same rule. Design alerts-visibility-roles (decisions 13-14): State oversight and the central operator no longer read
`private_to_office` notes; the Auditor and the super admin keep that sight through `cases.view_private_all`, which the
super admin may grant to or deny from one membership and which does nothing without `cases.view_all`."""

from __future__ import annotations

import pytest

from aslms.domain.org import PermissionEffect
from aslms.domain.reference import Permission, Role
from aslms.services import access, case_detail, notes
from aslms.services import ownership as own
from aslms.services.visibility import NotVisibleCase, NotVisibleNote
from tests.db import workflow_support as w
from tests.db.world import add_membership, make_case


@pytest.fixture()
def scene(world):
    """An EDU case allotted to off1, held by the EDU standing counsel, with three notes by the EDU admin."""
    w.widen(world)
    with world.Session() as s:
        case = w.claimed_case(s, world)
        w.send(s, world, "edu_off1", case, "edu_counsel", pending_action_="opinion")
        for vis in ("case_scope", "counsel_shared", "private_to_office"):
            w.note(s, world, "edu_admin", case, body=vis, visibility_=vis)
        s.commit()
        return case.id


def _bodies(s, world, key, case_id) -> set[str]:
    from aslms.domain.cases import Case

    _, user = world.actor(s, key)
    try:
        return {n["body"] for n in notes.list_for_case(s, user, s.get(Case, case_id)).items}
    except NotVisibleCase:
        return set()


ALL = {"case_scope", "counsel_shared", "private_to_office"}
NOT_PRIVATE = ALL - {"private_to_office"}


def test_three_visibilities_by_type(world, scene):
    with world.Session() as s:
        assert _bodies(s, world, "oversight", scene) == NOT_PRIVATE
        assert _bodies(s, world, "central_op", scene) == NOT_PRIVATE
        assert _bodies(s, world, "edu_auditor", scene) == ALL
        assert _bodies(s, world, "root", scene) == ALL
        assert _bodies(s, world, "edu_admin", scene) == ALL
        assert _bodies(s, world, "edu_off1", scene) == ALL
        assert _bodies(s, world, "edu_counsel", scene) == {"counsel_shared"}
        assert _bodies(s, world, "health_off", scene) == set()  # no sight of the case
        assert _bodies(s, world, "dhe_user", scene) == set()


def test_the_two_switches(world, scene):
    with world.Session() as s:
        actor, root = world.actor(s, "root")
        access.set_override(
            s,
            actor,
            root,
            world.membership(s, "edu_off1"),
            Permission.NOTES_VIEW_PRIVATE_OFFICE,
            PermissionEffect.DENY,
        )
        access.set_override(
            s,
            actor,
            root,
            world.membership(s, "edu_counsel"),
            Permission.NOTES_VIEW_COUNSEL_SHARED,
            PermissionEffect.DENY,
        )
        assert _bodies(s, world, "edu_off1", scene) == {"case_scope", "counsel_shared"}
        assert _bodies(s, world, "edu_counsel", scene) == set()
        s.rollback()


def test_author_always_reads_own_note(world, scene):
    from aslms.domain.cases import Case

    with world.Session() as s:
        case = s.get(Case, scene)
        actor, root = world.actor(s, "root")
        w.recall(s, world, "edu_admin", case)
        w.send(s, world, "edu_admin", case, "fin_off")
        w.note(s, world, "edu_off1", case, body="off1 private", visibility_="private_to_office")
        access.set_override(
            s,
            actor,
            root,
            world.membership(s, "edu_off1"),
            Permission.NOTES_VIEW_PRIVATE_OFFICE,
            PermissionEffect.DENY,
        )
        assert "off1 private" in _bodies(s, world, "edu_off1", scene)
        assert "private_to_office" not in _bodies(s, world, "edu_off1", scene)
        assert "off1 private" not in _bodies(s, world, "fin_off", scene)
        s.rollback()


def test_two_membership_reader_sees_private_notes_of_both_offices(world, scene):
    from aslms.domain.cases import Case

    with world.Session() as s:
        add_membership(
            s, world.user(s, "edu_admin"), world.office(s, "HEALTH"), Role.DEPT_OFFICER, "Under Secretary"
        )
        h_actor, h_admin = world.actor(s, "health_admin")
        hcase = make_case(s)
        own.claim(s, h_actor, h_admin, hcase, officer_user_id=world.user(s, "health_off").id)
        w.send(s, world, "health_off", hcase, "edu_admin", to_office="HEALTH")
        w.note(s, world, "health_admin", hcase, body="health private", visibility_="private_to_office")
        assert _bodies(s, world, "edu_admin", hcase.id) == {"health private"}
        assert "private_to_office" in _bodies(s, world, "edu_admin", scene)
        assert _bodies(s, world, "edu_off1", hcase.id) == set()
        _, person = world.actor(s, "edu_admin")
        assert notes.get(s, person, [n for n in w.case_notes(s, hcase.id)][0].ref_no)
        s.rollback()
        assert s.get(Case, scene) is not None


def test_timeline_follows_the_note_rule(world, scene):
    from aslms.domain.cases import Case

    with world.Session() as s:
        case = s.get(Case, scene)

        def note_events(key):
            _, user = world.actor(s, key)
            page = case_detail.timeline(s, user, case, limit=200)
            return sorted(i["payload"]["visibility"] for i in page.items if i["type"] == "note_added")

        assert note_events("oversight") == sorted(NOT_PRIVATE)
        assert note_events("edu_auditor") == sorted(ALL)
        assert note_events("edu_counsel") == ["counsel_shared"]
        # custody moves are on everyone's timeline who sees the case
        _, counsel = world.actor(s, "edu_counsel")
        types = {i["type"] for i in case_detail.timeline(s, counsel, case, limit=200).items}
        assert "custody_moved" in types


# ------------------------------------------------------------------ design alerts-visibility-roles, decisions 13-14


def _private_ref(s, case_id) -> str:
    return next(n.ref_no for n in w.case_notes(s, case_id) if n.body == "private_to_office")


def _override(s, world, key: str, permission: Permission, effect: PermissionEffect) -> None:
    actor, root = world.actor(s, "root")
    access.set_override(s, actor, root, world.membership(s, key), permission, effect)


def test_state_oversight_and_central_operator_do_not_read_private_notes(world, scene):
    from aslms.domain.cases import Case

    with world.Session() as s:
        case = s.get(Case, scene)
        ref = _private_ref(s, scene)
        for key in ("oversight", "central_op"):
            _, user = world.actor(s, key)
            assert "private_to_office" not in _bodies(s, world, key, scene), key
            with pytest.raises(NotVisibleNote):
                notes.get(s, user, ref)
            assert notes.visible_count(s, user, case) == 2, key
            timeline = case_detail.timeline(s, user, case, limit=200).items
            assert "private_to_office" not in {
                i["payload"]["visibility"] for i in timeline if i["type"] == "note_added"
            }, key


def test_auditor_and_super_admin_read_private_notes(world, scene):
    from aslms.domain.cases import Case

    with world.Session() as s:
        case = s.get(Case, scene)
        ref = _private_ref(s, scene)
        for key in ("edu_auditor", "root"):
            _, user = world.actor(s, key)
            assert notes.get(s, user, ref).body == "private_to_office"
            assert notes.visible_count(s, user, case) == 3, key


def test_view_private_all_has_no_effect_without_view_all(world, scene):
    with world.Session() as s:
        _override(s, world, "edu_counsel", Permission.CASES_VIEW_PRIVATE_ALL, PermissionEffect.GRANT)
        assert access.has(s, world.user(s, "edu_counsel"), Permission.CASES_VIEW_PRIVATE_ALL)
        assert _bodies(s, world, "edu_counsel", scene) == {"counsel_shared"}
        assert _bodies(s, world, "health_off", scene) == set()
        s.rollback()


def test_granted_view_private_all_gives_one_oversight_officer_the_sight(world, scene):
    with world.Session() as s:
        _override(s, world, "oversight", Permission.CASES_VIEW_PRIVATE_ALL, PermissionEffect.GRANT)
        assert _bodies(s, world, "oversight", scene) == ALL
        assert _bodies(s, world, "central_op", scene) == NOT_PRIVATE  # one named officer, not the type
        s.rollback()


def test_denied_view_private_all_removes_it_from_an_auditor(world, scene):
    with world.Session() as s:
        _override(s, world, "edu_auditor", Permission.CASES_VIEW_PRIVATE_ALL, PermissionEffect.DENY)
        assert _bodies(s, world, "edu_auditor", scene) == NOT_PRIVATE
        _, auditor = world.actor(s, "edu_auditor")
        with pytest.raises(NotVisibleNote):
            notes.get(s, auditor, _private_ref(s, scene))
        s.rollback()


def test_oversight_still_reads_case_scope_and_counsel_shared_notes(world, scene):
    with world.Session() as s:
        _, user = world.actor(s, "oversight")
        for n in w.case_notes(s, scene):
            if n.body != "private_to_office":
                assert notes.get(s, user, n.ref_no).body == n.body
        # a private note written in the oversight officer's own office (or by them) stays readable to them
        assert {"case_scope", "counsel_shared"} <= _bodies(s, world, "oversight", scene)
