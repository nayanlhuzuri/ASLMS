"""Offices administration (design `offices-admin`): departments, directorates and units in the government
hierarchy, designations, and the first department admins.

- Placement follows the tiers of the plan (§8.1): Department-tier offices sit under the State root,
  directorates under a department, units inside any office below the root. The tier is derived from the
  depth of `offices.path` (`GOA/EDU/EDU-DSE`), which scope checks keep using unchanged.
- Codes are the Secretariat's own, upper-case, and immutable once created (they are embedded in every
  `ref_no` and actor snapshot). `kind` and `parent_id` are immutable too (no re-parenting).
- Writes need `offices.manage`. The super admin acts anywhere; anyone else only strictly inside their own
  office subtree and only on `directorate` and `unit` offices (the shape of the user-delegation rule).
- Deactivation never deletes and is refused while active children, users, ownership or custody point at the
  office. Every write is audited and office writes emit one `config_changed` event.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from aslms.domain.events import Event, EventVisibility
from aslms.domain.org import Designation, Office, User
from aslms.domain.ownership import CaseOwnership, OwnershipStatus
from aslms.domain.reference import EventType, OfficeKind, Permission, Role
from aslms.domain.workflow import Custody
from aslms.services import access
from aslms.services.audit import Actor, write_audit
from aslms.services.users import create_user

# ------------------------------------------------------------------------------------------------ rules


class OfficeError(ValueError):
    """Bad input, unknown or inactive parent, placement refused, immutable field."""


class DuplicateCode(OfficeError):
    """The code is already taken (HTTP 409)."""


class OfficeInUse(OfficeError):
    """Deactivation refused while something active depends on the office (HTTP 409)."""

    def __init__(self, counts: dict[str, int]) -> None:
        self.counts = counts
        used = ", ".join(f"{k}={v}" for k, v in counts.items() if v)
        super().__init__(f"the office is still in use ({used}); deactivate or move them first")


K = OfficeKind
# child kind -> the kinds its parent may have (design decision 3). `state` is the seeded root only.
PLACEMENT: dict[OfficeKind, frozenset[OfficeKind]] = {
    K.STATE: frozenset(),
    K.DEPARTMENT: frozenset({K.STATE}),
    K.CENTRAL: frozenset({K.STATE}),
    K.ADVOCATE_GENERAL: frozenset({K.STATE}),
    K.DIRECTORATE: frozenset({K.DEPARTMENT}),
    K.UNIT: frozenset({K.DEPARTMENT, K.DIRECTORATE, K.CENTRAL, K.ADVOCATE_GENERAL}),
}
DELEGABLE_KINDS = frozenset({K.DIRECTORATE, K.UNIT})
DEPARTMENT_TIER_KINDS = frozenset({K.DEPARTMENT, K.CENTRAL, K.ADVOCATE_GENERAL})

OFFICE_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9-]{1,39}$")
DESIGNATION_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9_-]{1,39}$")  # the seed uses `CS_SEC`, `LEGAL_OFFICER`
MAX_PATH = 400
TIERS = ("state", "department", "directorate")


def normalise_code(code: str, *, pattern: re.Pattern[str] = OFFICE_CODE_RE) -> str:
    code = (code or "").strip().upper()
    if not pattern.match(code):
        raise OfficeError(
            "a code is 2 to 40 characters: letters, digits and hyphens, starting with a letter or digit"
        )
    return code


def normalise_designation_code(code: str) -> str:
    return normalise_code(code, pattern=DESIGNATION_CODE_RE)


def _as_kind(value: OfficeKind | str) -> OfficeKind:
    try:
        return value if isinstance(value, OfficeKind) else OfficeKind(value)
    except ValueError as exc:
        raise OfficeError(f"unknown office kind {value!r}") from exc


def depth_of(office: Office) -> int:
    return office.path.count("/")


def tier_of(office: Office) -> str:
    """`state` for the root, `department` for a direct child of the root, `directorate` below that."""
    return TIERS[min(depth_of(office), 2)]


def child_path(parent: Office, code: str) -> str:
    path = f"{parent.path}/{code}"
    if len(path) > MAX_PATH:
        raise OfficeError("the office would sit too deep in the tree (path longer than 400 characters)")
    return path


def office_summary(office: Office) -> dict:
    return {
        "id": str(office.id),
        "code": office.code,
        "name": office.name,
        "kind": _as_kind(office.kind).value,
        "parent_id": str(office.parent_id) if office.parent_id else None,
        "path": office.path,
        "notes": office.notes,
        "is_active": office.is_active,
        "valid_from": office.valid_from,
        "valid_to": office.valid_to,
    }


def designation_summary(d: Designation) -> dict:
    return {
        "id": str(d.id),
        "code": d.code,
        "name": d.name,
        "sort_order": d.sort_order,
        "is_active": d.is_active,
    }


# ------------------------------------------------------------------------------------------------ access


def assert_can_manage_office(
    session: Session,
    actor_user: User,
    *,
    parent: Office | None = None,
    office: Office | None = None,
    kind: OfficeKind | str | None = None,
) -> None:
    """Raises Forbidden unless `actor_user` may create an office of `kind` under `parent`, or change
    `office`. A non-super-admin acts only strictly inside their own subtree (a child of their own office is
    inside it; their own office is not) and only on the delegable kinds."""
    access.require(session, actor_user, Permission.OFFICES_MANAGE)
    if access.is_super_admin(actor_user):
        return
    if kind is not None and _as_kind(kind) not in DELEGABLE_KINDS:
        raise access.Forbidden(
            f"only a super admin may create or change offices of kind {_as_kind(kind).value}"
        )
    if office is not None:
        if office.id == actor_user.office_id:
            raise access.Forbidden("you cannot change your own office")
        if not access.in_scope(session, actor_user, office):
            raise access.Forbidden("the office is outside your offices")
    elif parent is not None:
        if not access.in_scope(session, actor_user, parent):
            raise access.Forbidden("the parent office is outside your offices")
    else:
        raise access.Forbidden("no office to act on")


# ------------------------------------------------------------------------------------------------ reading


def dependents(session: Session, office: Office) -> dict[str, int]:
    """What still points at the office: active children, active users, active ownership (as owner or unit),
    custody held."""

    def count(stmt) -> int:
        return int(session.scalar(stmt) or 0)

    return {
        "children": count(
            select(func.count()).where(Office.parent_id == office.id, Office.is_active.is_(True))
        ),
        "users": count(select(func.count()).where(User.office_id == office.id, User.is_active.is_(True))),
        "ownership": count(
            select(func.count()).where(
                or_(CaseOwnership.office_id == office.id, CaseOwnership.unit_office_id == office.id),
                CaseOwnership.status == OwnershipStatus.ACTIVE,
            )
        ),
        "custody": count(select(func.count()).where(Custody.holder_office_id == office.id)),
    }


@dataclass
class OfficeNode:
    office: Office
    tier: str
    depth: int
    users_active: int
    children: list[OfficeNode] = field(default_factory=list)


def office_tree(session: Session, roots: list[Office], *, include_inactive: bool = False) -> list[OfficeNode]:
    """The subtrees of `roots`, nested by `parent_id`, each node carrying its active-user count. One query
    for the offices and one for the counts."""
    if not roots:
        return []
    stmt = select(Office).where(
        or_(*[or_(Office.id == r.id, Office.path.like(r.path + "/%")) for r in roots])
    )
    if not include_inactive:
        stmt = stmt.where(Office.is_active.is_(True))
    offices = {o.id: o for o in session.scalars(stmt.order_by(Office.path)).all()}
    counts = dict(
        session.execute(
            select(User.office_id, func.count())
            .where(User.office_id.in_(list(offices)), User.is_active.is_(True))
            .group_by(User.office_id)
        ).all()
    )
    nodes = {
        o.id: OfficeNode(office=o, tier=tier_of(o), depth=depth_of(o), users_active=int(counts.get(o.id, 0)))
        for o in offices.values()
    }
    top: list[OfficeNode] = []
    for node in nodes.values():
        parent = nodes.get(node.office.parent_id) if node.office.parent_id else None
        (parent.children if parent is not None else top).append(node)
    for node in nodes.values():
        node.children.sort(key=lambda n: n.office.code)
    top.sort(key=lambda n: n.office.path)
    return top


def find_office(session: Session, code: str) -> Office | None:
    return session.scalar(select(Office).where(Office.code == (code or "").strip().upper()))


def find_designation(session: Session, code: str) -> Designation | None:
    return session.scalar(select(Designation).where(Designation.code == (code or "").strip().upper()))


# ------------------------------------------------------------------------------------------------ changes


def _event(session: Session, office: Office, action: str) -> None:
    key = f"office:{office.id}:{action}:{datetime.now(UTC).isoformat()}"
    if session.scalar(select(Event.id).where(Event.dedupe_key == key)) is None:
        session.add(
            Event(
                type=EventType.CONFIG_CHANGED,
                payload={"entity": "office", "code": office.code, "action": action},
                dedupe_key=key,
                visibility=EventVisibility.SCOPED,
            )
        )


def create_office(
    session: Session,
    actor: Actor,
    actor_user: User,
    *,
    code: str,
    name: str,
    kind: OfficeKind | str,
    parent: Office,
    notes: str | None = None,
    valid_from: date | None = None,
) -> Office:
    kind = _as_kind(kind)
    assert_can_manage_office(session, actor_user, parent=parent, kind=kind)
    if kind == OfficeKind.STATE:
        raise OfficeError("the State office is the seeded root and cannot be created")
    code = normalise_code(code)
    name = (name or "").strip()
    if not name:
        raise OfficeError("a name is required")
    if not parent.is_active:
        raise OfficeError(f"the parent office {parent.code} is inactive")
    if _as_kind(parent.kind) not in PLACEMENT[kind]:
        allowed = ", ".join(sorted(k.value for k in PLACEMENT[kind]))
        raise OfficeError(
            f"a {kind.value} cannot be placed under a {_as_kind(parent.kind).value} (allowed: {allowed})"
        )
    if find_office(session, code) is not None:
        raise DuplicateCode(f"an office with code {code} already exists")
    office = Office(
        code=code,
        name=name[:200],
        kind=kind,
        parent_id=parent.id,
        path=child_path(parent, code),
        notes=(notes or None) and notes.strip() or None,
        created_by=actor.user_id,
        updated_by=actor.user_id,
    )
    if valid_from is not None:
        office.valid_from = valid_from
    session.add(office)
    session.flush()
    session.refresh(office)
    write_audit(session, actor, "office.create", "office", office.id, after=office_summary(office))
    _event(session, office, "create")
    session.flush()
    return office


def update_office(
    session: Session,
    actor: Actor,
    actor_user: User,
    office: Office,
    *,
    name: str | None = None,
    notes: str | None = None,
    valid_from: date | None = None,
) -> Office:
    """Only `name`, `notes` and `valid_from` change; `code`, `kind` and the parent are immutable. The audit
    row carries just the fields that were set."""
    assert_can_manage_office(session, actor_user, office=office, kind=office.kind)
    before: dict = {}
    after: dict = {}
    if name is not None:
        name = name.strip()
        if not name:
            raise OfficeError("a name is required")
        before["name"], after["name"] = office.name, name[:200]
        office.name = name[:200]
    if notes is not None:
        before["notes"], after["notes"] = office.notes, notes.strip() or None
        office.notes = notes.strip() or None
    if valid_from is not None:
        before["valid_from"], after["valid_from"] = office.valid_from, valid_from
        office.valid_from = valid_from
    if not after:
        return office
    office.updated_by = actor.user_id
    session.flush()
    write_audit(session, actor, "office.update", "office", office.id, before=before, after=after)
    _event(session, office, "update")
    session.flush()
    return office


def deactivate_office(session: Session, actor: Actor, actor_user: User, office: Office) -> Office:
    """Sets `is_active=false`, `deactivated_at`, `valid_to`; never deletes. Refused (OfficeInUse) while anything
    active depends on the office; the root and the actor's own office are never deactivated."""
    assert_can_manage_office(session, actor_user, office=office, kind=office.kind)
    if office.parent_id is None:
        raise OfficeError("the root office cannot be deactivated")
    if office.id == actor_user.office_id:
        raise access.Forbidden("you cannot deactivate your own office")
    if not office.is_active:
        raise OfficeError(f"the office {office.code} is already inactive")
    counts = dependents(session, office)
    if any(counts.values()):
        raise OfficeInUse(counts)
    before = office_summary(office)
    office.is_active = False
    office.deactivated_at = datetime.now(UTC)
    office.valid_to = date.today()
    office.updated_by = actor.user_id
    session.flush()
    write_audit(
        session, actor, "office.deactivate", "office", office.id, before=before, after=office_summary(office)
    )
    _event(session, office, "deactivate")
    session.flush()
    return office


def reactivate_office(session: Session, actor: Actor, actor_user: User, office: Office) -> Office:
    assert_can_manage_office(session, actor_user, office=office, kind=office.kind)
    if office.is_active:
        raise OfficeError(f"the office {office.code} is already active")
    parent = session.get(Office, office.parent_id) if office.parent_id else None
    if parent is None or not parent.is_active:
        raise OfficeError("the parent office is inactive; reactivate it first")
    before = office_summary(office)
    office.is_active = True
    office.deactivated_at = None
    office.valid_to = None
    office.updated_by = actor.user_id
    session.flush()
    write_audit(
        session, actor, "office.reactivate", "office", office.id, before=before, after=office_summary(office)
    )
    _event(session, office, "reactivate")
    session.flush()
    return office


def department_admins(session: Session, office: Office) -> list[User]:
    return list(
        session.scalars(
            select(User).where(User.office_id == office.id, User.role == Role.DEPT_ADMIN).order_by(User.email)
        ).all()
    )


def add_department_admin(
    session: Session,
    actor: Actor,
    actor_user: User,
    office: Office,
    *,
    email: str,
    password: str,
    full_name: str,
    designation: str | None = None,
    designation_id: uuid.UUID | None = None,
    mobile: str | None = None,
) -> User:
    """The first `dept_admin` of a Department-tier office. The same user row `POST /admin/users` would create,
    through `create_user`; the delegation rule admits only the super admin (`dept_admin` is not delegable)."""
    access.assert_can_manage(session, actor_user, "create", target_office=office, target_role=Role.DEPT_ADMIN)
    if not office.is_active:
        raise OfficeError(f"the office {office.code} is inactive")
    if tier_of(office) != "department" or _as_kind(office.kind) not in DEPARTMENT_TIER_KINDS:
        raise OfficeError(
            f"a department admin belongs to a Department-tier office; {office.code} is a "
            f"{_as_kind(office.kind).value} at the {tier_of(office)} tier"
        )
    user = create_user(
        session,
        actor,
        email=email,
        password=password,
        full_name=full_name,
        role=Role.DEPT_ADMIN,
        office=office,
        designation=designation,
        designation_id=designation_id,
        mobile=mobile,
        must_confirm_profile=True,
    )
    write_audit(
        session,
        actor,
        "office.admin_added",
        "office",
        office.id,
        after={"user_id": str(user.id), "email": user.email},
    )
    return user


# ------------------------------------------------------------------------------------------------ designations


def create_designation(
    session: Session,
    actor: Actor,
    actor_user: User,
    *,
    code: str,
    name: str,
    sort_order: int | None = None,
) -> Designation:
    access.require(session, actor_user, Permission.ADMIN_DESIGNATIONS)
    code = normalise_designation_code(code)
    name = (name or "").strip()
    if not name:
        raise OfficeError("a name is required")
    if find_designation(session, code) is not None:
        raise DuplicateCode(f"a designation with code {code} already exists")
    if sort_order is None:
        sort_order = int(session.scalar(select(func.max(Designation.sort_order))) or 0) + 10
    row = Designation(
        code=code, name=name[:200], sort_order=sort_order, created_by=actor.user_id, updated_by=actor.user_id
    )
    session.add(row)
    session.flush()
    session.refresh(row)
    write_audit(session, actor, "designation.create", "designation", row.id, after=designation_summary(row))
    return row


def update_designation(
    session: Session,
    actor: Actor,
    actor_user: User,
    designation: Designation,
    *,
    name: str | None = None,
    sort_order: int | None = None,
) -> Designation:
    access.require(session, actor_user, Permission.ADMIN_DESIGNATIONS)
    before: dict = {}
    after: dict = {}
    if name is not None:
        name = name.strip()
        if not name:
            raise OfficeError("a name is required")
        before["name"], after["name"] = designation.name, name[:200]
        designation.name = name[:200]
    if sort_order is not None:
        before["sort_order"], after["sort_order"] = designation.sort_order, sort_order
        designation.sort_order = sort_order
    if not after:
        return designation
    designation.updated_by = actor.user_id
    session.flush()
    write_audit(
        session, actor, "designation.update", "designation", designation.id, before=before, after=after
    )
    return designation


def set_designation_active(
    session: Session, actor: Actor, actor_user: User, designation: Designation, enabled: bool
) -> Designation:
    """Deactivated designations stay (users created with them keep resolving); the pickers hide them."""
    access.require(session, actor_user, Permission.ADMIN_DESIGNATIONS)
    if designation.is_active == enabled:
        state = "active" if enabled else "inactive"
        raise OfficeError(f"the designation {designation.code} is already {state}")
    before = designation_summary(designation)
    designation.is_active = enabled
    designation.deactivated_at = None if enabled else datetime.now(UTC)
    designation.valid_to = None if enabled else date.today()
    designation.updated_by = actor.user_id
    session.flush()
    write_audit(
        session,
        actor,
        "designation.reactivate" if enabled else "designation.deactivate",
        "designation",
        designation.id,
        before=before,
        after=designation_summary(designation),
    )
    return designation
