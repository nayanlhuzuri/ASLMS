"""Membership rules without a database (design `user-memberships`, decisions 2, 5, 6): the department derived
from an office path, the union gate against the per-membership check, and the order in which the acting
membership is chosen."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from aslms.domain.reference import OfficeKind, Permission, Role
from aslms.services import access
from aslms.services import ownership as own
from aslms.services.access import Member


def office(code: str, path: str, kind: OfficeKind) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), code=code, path=path, kind=kind, is_active=True)


GOA = office("GOA", "GOA", OfficeKind.STATE)
EDU = office("EDU", "GOA/EDU", OfficeKind.DEPARTMENT)
DSE = office("EDU-DSE", "GOA/EDU/EDU-DSE", OfficeKind.DIRECTORATE)
HEALTH = office("HEALTH", "GOA/HEALTH", OfficeKind.DEPARTMENT)
CENTRAL = office("CENTRAL", "GOA/CENTRAL", OfficeKind.CENTRAL)


class FakeSession:
    """Answers `department_of`'s lookup of the second path segment."""

    def __init__(self, offices):
        self.by_code = {o.code: o for o in offices}

    def scalar(self, stmt):
        code = stmt.whereclause.right.value
        return self.by_code.get(code)


def member(office_, dept, role: Role, functions: set[Permission], *, primary=False, user=None) -> Member:
    user = user or SimpleNamespace(id=uuid.uuid4(), full_name="P", is_active=True, email="p@example.org")
    m = SimpleNamespace(id=uuid.uuid4(), is_active=True, is_primary=primary, designation=None, role=role)
    return Member(
        user=user, membership=m, office=office_, department=dept, role=role, functions=frozenset(functions)
    )


def test_department_derived_from_the_path():
    s = FakeSession([GOA, EDU, DSE, HEALTH, CENTRAL])
    assert access.department_of(s, EDU) is EDU
    assert access.department_of(s, DSE) is EDU
    assert access.department_of(s, CENTRAL) is CENTRAL  # Department-tier kinds include central
    assert access.department_of(s, GOA) is None  # the State tier has no department
    assert access.department_of(s, None) is None


def test_union_gate_and_per_membership_check(monkeypatch):
    person = SimpleNamespace(id=uuid.uuid4(), full_name="Dual", is_active=True, email="d@example.org")
    edu_admin = member(
        EDU, EDU, Role.DEPT_ADMIN, {Permission.CASES_ALLOT, Permission.CASES_CLAIM}, primary=True, user=person
    )
    health_officer = member(HEALTH, HEALTH, Role.DEPT_OFFICER, {Permission.NOTES_ADD}, user=person)
    monkeypatch.setattr(access, "members", lambda session, user: [edu_admin, health_officer])
    # the gate: the person holds cases.allot somewhere
    assert access.has(None, person, Permission.CASES_ALLOT)
    assert access.effective_permissions(None, person) == {
        Permission.CASES_ALLOT,
        Permission.CASES_CLAIM,
        Permission.NOTES_ADD,
    }
    # the check in the membership that acts
    assert edu_admin.holds(Permission.CASES_ALLOT) and not health_officer.holds(Permission.CASES_ALLOT)
    # acting for HEALTH: the HEALTH membership relates to the case but lacks the function → Forbidden
    with pytest.raises(access.Forbidden):
        own.acting_member(None, person, None, Permission.CASES_ALLOT, relation=lambda d: d is HEALTH)
    # acting for EDU: the EDU membership qualifies
    m, dept = own.acting_member(None, person, None, Permission.CASES_ALLOT, relation=lambda d: d is EDU)
    assert m is edu_admin and dept is EDU
    # nothing related → not visible
    with pytest.raises(own.NotVisible):
        own.acting_member(None, person, None, Permission.CASES_ALLOT, relation=lambda d: False)


def test_acting_membership_preference(monkeypatch):
    person = SimpleNamespace(id=uuid.uuid4(), full_name="Two", is_active=True, email="t@example.org")
    a = member(EDU, EDU, Role.DEPT_ADMIN, {Permission.CASES_CLAIM}, primary=True, user=person)
    b = member(HEALTH, HEALTH, Role.DEPT_ADMIN, {Permission.CASES_CLAIM}, user=person)
    monkeypatch.setattr(access, "members", lambda session, user: [a, b])
    # the primary membership's department when it qualifies
    assert own.acting_member(None, person, None, Permission.CASES_CLAIM)[0] is a
    # else the single qualifying membership
    monkeypatch.setattr(
        access,
        "members",
        lambda session, user: [member(EDU, EDU, Role.DEPT_OFFICER, set(), primary=True, user=person), b],
    )
    assert own.acting_member(None, person, None, Permission.CASES_CLAIM)[0] is b
    # several qualify and the primary does not → 400 office_required with the candidates
    c = member(CENTRAL, CENTRAL, Role.DEPT_OFFICER, {Permission.NOTES_ADD}, primary=True, user=person)
    monkeypatch.setattr(access, "members", lambda session, user: [c, a, b])
    with pytest.raises(own.OfficeRequired) as exc:
        own.acting_member(None, person, None, Permission.CASES_CLAIM)
    assert exc.value.candidates == ["EDU", "HEALTH"]


def test_member_covers_its_subtree_and_the_super_admin_everything():
    dse_user = member(DSE, EDU, Role.DIRECTORATE_USER, set())
    assert dse_user.covers(DSE) and not dse_user.covers(EDU) and not dse_user.covers(HEALTH)
    root = member(GOA, None, Role.SUPER_ADMIN, set(Permission))
    assert root.covers(HEALTH) and root.is_super_admin
