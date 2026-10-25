"""`/admin/offices/*` and `/admin/designations/*`: the government hierarchy (list, tree, detail, create, edit,
deactivate, reactivate), the first department admins of a department, and the State-wide designation list.
Reads are filtered to the caller's office subtree on the server; every write goes through
`services/offices.py`, which enforces the delegation rule and audits. Since `user-memberships`: a department
is created and reactivated with its head, has at most one admin (`POST .../admins` → 409 `admin_exists`;
`PUT .../admin` is the super admin's swap), and `missing_head=true` lists departments without a head."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from aslms.api import schemas
from aslms.api.deps import actor_of, current_user, get_session, require
from aslms.api.errors import http_error
from aslms.api.routers.auth import user_out
from aslms.domain.org import Designation, Office, User
from aslms.domain.reference import OfficeKind, Permission
from aslms.services import access, memberships, offices
from aslms.services.access import Conflict, Forbidden
from aslms.services.memberships import MembershipError
from aslms.services.offices import OfficeError, OfficeNode
from aslms.services.tickets import TicketError
from aslms.services.users import UserError

router = APIRouter(prefix="/admin", tags=["offices"])


# ------------------------------------------------------------------------------------------------ helpers


def _http(exc: Exception) -> HTTPException:
    return http_error(exc)


HANDLED = (Forbidden, Conflict, OfficeError, UserError, MembershipError, TicketError)


def _sees_everything(session: Session, user: User) -> bool:
    return access.is_super_admin(user) or access.has(session, user, Permission.CASES_VIEW_ALL)


def _scope_roots(session: Session, user: User) -> list[Office]:
    """The roots of what the caller may see: the root office(s) for a State-wide view, else their own office."""
    if _sees_everything(session, user):
        return list(session.scalars(select(Office).where(Office.parent_id.is_(None)).order_by(Office.path)))
    roots: list[Office] = []
    for m in access.members(session, user):
        if all(not access.subtree_contains(r, m.office) for r in roots):
            roots = [r for r in roots if not access.subtree_contains(m.office, r)] + [m.office]
    return sorted(roots, key=lambda o: o.path)


def _may_see_inactive(session: Session, user: User, include_inactive: bool) -> bool:
    if include_inactive and not access.has(session, user, Permission.OFFICES_MANAGE):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "offices.manage is needed to list inactive offices")
    return include_inactive


def _load_office(session: Session, caller: User, code: str) -> Office:
    """The office by code when it is inside the caller's scope; inactive offices only for holders of
    `offices.manage`. Unknown and out-of-scope are both 404."""
    office = offices.find_office(session, code)
    visible = office is not None and (
        access.in_scope(session, caller, office) or _sees_everything(session, caller)
    )
    if not visible:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such office")
    if not office.is_active and not access.has(session, caller, Permission.OFFICES_MANAGE):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such office")
    return office


def _detail(session: Session, office: Office) -> schemas.OfficeDetailOut:
    parent = session.get(Office, office.parent_id) if office.parent_id else None
    return schemas.OfficeDetailOut(
        **schemas.OfficeOut.from_office(office).model_dump(),
        tier=offices.tier_of(office),
        depth=offices.depth_of(office),
        parent_code=parent.code if parent else None,
        notes=office.notes,
        deactivated_at=office.deactivated_at,
        valid_from=office.valid_from,
        valid_to=office.valid_to,
        created_at=office.created_at,
        updated_at=office.updated_at,
        counts=schemas.OfficeCountsOut(**offices.dependents(session, office)),
    )


def _node(node: OfficeNode) -> schemas.OfficeNodeOut:
    return schemas.OfficeNodeOut(
        **schemas.OfficeOut.from_office(node.office).model_dump(),
        tier=node.tier,
        depth=node.depth,
        users_active=node.users_active,
        children=[_node(c) for c in node.children],
    )


def _designation_out(d: Designation) -> schemas.DesignationOut:
    return schemas.DesignationOut(
        id=d.id, code=d.code, name=d.name, sort_order=d.sort_order, is_active=d.is_active
    )


def _load_designation(session: Session, code: str) -> Designation:
    d = offices.find_designation(session, code)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such designation")
    return d


# ------------------------------------------------------------------------------------------------ offices


@router.get("/offices", response_model=list[schemas.OfficeOut])
def list_offices(
    kind: OfficeKind | None = None,
    include_inactive: bool = False,
    missing_head: bool = False,
    session: Session = Depends(get_session),
    user: User = Depends(require(Permission.USERS_VIEW)),
) -> list[schemas.OfficeOut]:
    """The offices in the caller's scope, ordered by path. `missing_head=true` (`offices.manage`): the active
    departments without a head (design `user-memberships`, decision 24)."""
    if missing_head:
        if not access.has(session, user, Permission.OFFICES_MANAGE):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "offices.manage is needed to list departments without a head"
            )
        return [schemas.OfficeOut.from_office(o) for o in offices.departments_without_head(session)]
    inactive = _may_see_inactive(session, user, include_inactive)
    roots = _scope_roots(session, user)

    def walk(nodes: list[OfficeNode]):
        for n in nodes:
            yield n.office
            yield from walk(n.children)

    rows = sorted(walk(offices.office_tree(session, roots, include_inactive=inactive)), key=lambda o: o.path)
    if kind is not None:
        rows = [o for o in rows if o.kind == kind]
    return [schemas.OfficeOut.from_office(o) for o in rows]


@router.get("/offices/tree", response_model=list[schemas.OfficeNodeOut])
def office_tree(
    include_inactive: bool = False,
    session: Session = Depends(get_session),
    user: User = Depends(require(Permission.USERS_VIEW)),
) -> list[schemas.OfficeNodeOut]:
    """The caller's scope as a tree: the root office(s) for a State-wide view, else the caller's own office."""
    inactive = _may_see_inactive(session, user, include_inactive)
    return [
        _node(n) for n in offices.office_tree(session, _scope_roots(session, user), include_inactive=inactive)
    ]


ChoicePurpose = Literal[
    "users", "membership", "office_parent", "counsel_codes", "keywords", "watchlist", "audit"
]


@router.get("/offices/choices", response_model=schemas.OfficeChoicesOut)
def office_choices(
    purpose: ChoicePurpose,
    include_inactive: bool = False,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> schemas.OfficeChoicesOut:
    """The offices one Office Picker may offer (design `portal-ui-polish-2`, decision 29), in tree order: `users`
    (`users.view`, the scope of `GET /admin/users`), `membership` (`users.create`), `office_parent`
    (`offices.manage`), `counsel_codes` / `keywords` / `watchlist` (that mapping function), each the subtrees of
    the caller's memberships holding the function (everything for the super admin), active only; `audit`
    (`audit.view` in a State-wide membership, else 403 `audit_scope`): every office, inactive ones included.
    `include_inactive=true` needs `offices.manage` and widens `users` only. Reads only."""
    try:
        items = offices.choices(session, user, purpose, include_inactive=include_inactive)
    except HANDLED as exc:
        raise _http(exc) from exc
    return schemas.OfficeChoicesOut(
        purpose=purpose, items=[schemas.OfficeChoiceOut(**vars(i)) for i in items]
    )


@router.post("/offices", response_model=schemas.OfficeDetailOut, status_code=status.HTTP_201_CREATED)
def create_office(
    body: schemas.OfficeCreateIn,
    request: Request,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.OFFICES_MANAGE)),
) -> schemas.OfficeDetailOut:
    parent = offices.find_office(session, body.parent_code)
    if parent is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "no such parent office")
    try:
        office = offices.create_office(
            session,
            actor_of(request, caller, session),
            caller,
            code=body.code,
            name=body.name,
            kind=body.kind,
            parent=parent,
            notes=body.notes,
            valid_from=body.valid_from,
            head=body.head.model_dump(exclude_none=True) if body.head else None,
        )
    except HANDLED as exc:
        raise _http(exc) from exc
    return _detail(session, office)


@router.get("/offices/{code}", response_model=schemas.OfficeDetailOut)
def get_office(
    code: str, session: Session = Depends(get_session), caller: User = Depends(require(Permission.USERS_VIEW))
) -> schemas.OfficeDetailOut:
    return _detail(session, _load_office(session, caller, code))


@router.patch("/offices/{code}", response_model=schemas.OfficeDetailOut)
def patch_office(
    code: str,
    body: schemas.OfficePatchIn,
    request: Request,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.OFFICES_MANAGE)),
) -> schemas.OfficeDetailOut:
    office = _load_office(session, caller, code)
    try:
        offices.update_office(
            session, actor_of(request, caller, session), caller, office, **body.model_dump(exclude_unset=True)
        )
    except HANDLED as exc:
        raise _http(exc) from exc
    return _detail(session, office)


@router.post("/offices/{code}/deactivate", response_model=schemas.OfficeDetailOut)
def deactivate_office(
    code: str,
    request: Request,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.OFFICES_MANAGE)),
) -> schemas.OfficeDetailOut:
    office = _load_office(session, caller, code)
    try:
        offices.deactivate_office(session, actor_of(request, caller, session), caller, office)
    except HANDLED as exc:
        raise _http(exc) from exc
    return _detail(session, office)


@router.post("/offices/{code}/reactivate", response_model=schemas.OfficeDetailOut)
def reactivate_office(
    code: str,
    request: Request,
    body: schemas.OfficeReactivateIn | None = None,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.OFFICES_MANAGE)),
) -> schemas.OfficeDetailOut:
    """A Department-tier office is reactivated with its head (`head`, as in creation)."""
    office = _load_office(session, caller, code)
    head = body.head.model_dump(exclude_none=True) if body is not None and body.head else None
    try:
        offices.reactivate_office(session, actor_of(request, caller, session), caller, office, head=head)
    except HANDLED as exc:
        raise _http(exc) from exc
    return _detail(session, office)


# ------------------------------------------------------------------------------------------------ admins


@router.get("/offices/{code}/admins", response_model=list[schemas.UserOut])
def list_department_admins(
    code: str, session: Session = Depends(get_session), caller: User = Depends(require(Permission.USERS_VIEW))
) -> list[schemas.UserOut]:
    """Who runs this department: its admin (zero or one)."""
    office = _load_office(session, caller, code)
    return [user_out(session, u) for u in offices.department_admins(session, office)]


@router.post("/offices/{code}/admins", response_model=schemas.UserOut, status_code=status.HTTP_201_CREATED)
def add_department_admin(
    code: str,
    body: schemas.DepartmentAdminIn,
    request: Request,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.USERS_CREATE)),
) -> schemas.UserOut:
    """The first department admin (type `dept_admin`) of a Department-tier office; super admin only; 409
    `admin_exists` when the department has one (use the swap)."""
    office = _load_office(session, caller, code)
    try:
        user = offices.add_department_admin(
            session, actor_of(request, caller, session), caller, office, **body.model_dump()
        )
    except HANDLED as exc:
        raise _http(exc) from exc
    return user_out(session, user)


# ------------------------------------------------------------------------------------------------ designations


@router.get("/designations", response_model=list[schemas.DesignationOut])
def list_designations(
    include_inactive: bool = False,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> list[schemas.DesignationOut]:
    """The State-wide designation list, for profile and user-creation pickers."""
    if include_inactive and not access.has(session, user, Permission.ADMIN_DESIGNATIONS):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "admin.designations is needed to list inactive designations"
        )
    stmt = select(Designation).order_by(Designation.sort_order, Designation.name)
    if not include_inactive:
        stmt = stmt.where(Designation.is_active.is_(True))
    return [_designation_out(d) for d in session.scalars(stmt).all()]


@router.post("/designations", response_model=schemas.DesignationOut, status_code=status.HTTP_201_CREATED)
def create_designation(
    body: schemas.DesignationCreateIn,
    request: Request,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.ADMIN_DESIGNATIONS)),
) -> schemas.DesignationOut:
    try:
        row = offices.create_designation(
            session,
            actor_of(request, caller, session),
            caller,
            code=body.code,
            name=body.name,
            sort_order=body.sort_order,
        )
    except HANDLED as exc:
        raise _http(exc) from exc
    return _designation_out(row)


@router.patch("/designations/{code}", response_model=schemas.DesignationOut)
def patch_designation(
    code: str,
    body: schemas.DesignationPatchIn,
    request: Request,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.ADMIN_DESIGNATIONS)),
) -> schemas.DesignationOut:
    row = _load_designation(session, code)
    try:
        offices.update_designation(
            session, actor_of(request, caller, session), caller, row, **body.model_dump(exclude_unset=True)
        )
    except HANDLED as exc:
        raise _http(exc) from exc
    return _designation_out(row)


@router.post("/designations/{code}/deactivate", response_model=schemas.DesignationOut)
def deactivate_designation(
    code: str,
    request: Request,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.ADMIN_DESIGNATIONS)),
) -> schemas.DesignationOut:
    return _set_designation(code, False, request, session, caller)


@router.post("/designations/{code}/reactivate", response_model=schemas.DesignationOut)
def reactivate_designation(
    code: str,
    request: Request,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.ADMIN_DESIGNATIONS)),
) -> schemas.DesignationOut:
    return _set_designation(code, True, request, session, caller)


def _set_designation(
    code: str, enabled: bool, request: Request, session: Session, caller: User
) -> schemas.DesignationOut:
    row = _load_designation(session, code)
    try:
        offices.set_designation_active(session, actor_of(request, caller, session), caller, row, enabled)
    except HANDLED as exc:
        raise _http(exc) from exc
    return _designation_out(row)


@router.put("/offices/{code}/admin", response_model=schemas.AdminSwapOut)
def replace_department_admin(
    code: str,
    body: schemas.AdminSwapIn,
    request: Request,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.USERS_CREATE)),
) -> schemas.AdminSwapOut:
    """The super admin's swap (design `user-memberships`, decision 14): the outgoing admin becomes an officer
    (`dept_officer`, default) or leaves through the per-item exit (`end`, with `assignments` and the
    `items_fingerprint` of the exit preview), then the incoming admin is made; 403 for anyone else."""
    office = _load_office(session, caller, code)
    try:
        admin, out = memberships.replace_department_admin(
            session,
            actor_of(request, caller, session),
            caller,
            office,
            incoming=body.incoming,
            outgoing=body.outgoing,
            reason=body.reason,
            assignments=[a.model_dump(mode="json") for a in body.assignments or []],
            items_fingerprint=body.items_fingerprint,
        )
    except HANDLED as exc:
        raise _http(exc) from exc
    return schemas.AdminSwapOut(
        admin=schemas.MembershipOut(**memberships.membership_out(session, admin)),
        outgoing=schemas.AdminSwapOutgoingOut(
            membership=out["membership"],
            reassigned=[schemas.ReassignedOut(**r) for r in out["reassigned"]] if out["reassigned"] else None,
        ),
    )
