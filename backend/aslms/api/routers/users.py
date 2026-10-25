"""`/admin/users/*`: logins in the caller's scope and their memberships (design `user-memberships`): creation
with a first membership, login-level edits (name, contact, password, enable/disable) over the **primary**
membership's office, the membership actions (add, change, end with the per-item exit, reactivate, make
primary), per-membership functions, exact e-mail lookup, and the orders linked to a membership. Every write
goes through `services/access.py` or `services/memberships.py`, which enforce the delegation rule and audit."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from aslms.api import schemas
from aslms.api.deps import actor_of, get_mailer, get_session, require, require_any
from aslms.api.errors import HANDLED, http_error
from aslms.api.routers.auth import user_out
from aslms.domain.org import Office, PermissionEffect, User, UserMembership
from aslms.domain.reference import Permission, Role
from aslms.services import access, memberships, tickets
from aslms.services.mailer import Mailer
from aslms.services.users import create_user, set_password, update_profile

router = APIRouter(prefix="/admin/users", tags=["users"])


def _scope_roots(session: Session, user: User) -> list[Office] | None:
    """None = everything (super admin or State-wide view); else the offices of the caller's memberships that
    hold `users.view` (`access.user_scope_roots`, shared with the user-type cards' counts)."""
    return access.user_scope_roots(session, user)


def _in_roots(office: Office, roots: list[Office] | None) -> bool:
    return roots is None or any(access.subtree_contains(r, office) for r in roots)


def _visible(session: Session, caller: User, user: User) -> bool:
    roots = _scope_roots(session, caller)
    if roots is None:
        return True
    for m in access.active_memberships(session, user):
        if _in_roots(session.get(Office, m.office_id), roots):
            return True
    return False


def _load(session: Session, caller: User, user_id: uuid.UUID) -> User:
    user = session.get(User, user_id)
    if user is None or not _visible(session, caller, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such user")
    return user


def _membership(session: Session, user: User, membership_id: uuid.UUID) -> UserMembership:
    m = session.get(UserMembership, membership_id)
    if m is None or m.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such membership")
    return m


def _office(session: Session, code: str) -> Office:
    office = session.scalar(select(Office).where(Office.code == code.strip().upper()))
    if office is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "no such office")
    return office


def _m_out(session: Session, m: UserMembership, *, functions: bool = False) -> schemas.MembershipOut:
    return schemas.MembershipOut(**memberships.membership_out(session, m, functions=functions))


# ------------------------------------------------------------------------------------------------ logins


def _bad_field(message: str) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, {"code": "bad_field", "message": message})


def _like(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


@router.get("", response_model=list[schemas.UserOut])
def list_users(
    response: Response,
    office: str | None = None,
    q: str | None = None,
    role: Role | None = None,
    status_: Literal["active", "not_signed_in", "off"] | None = Query(None, alias="status"),
    include_ended: bool = False,
    limit: int | None = None,
    offset: int = 0,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.USERS_VIEW)),
) -> list[schemas.UserOut]:
    """Logins with an active membership in the caller's scope (optionally under `office`), each with all of its
    memberships (decision 8). Design `portal-shell`, decision 16b: `q` (2+ characters, name or e-mail), `role`
    (of an active membership in scope), `include_ended` (State-wide scope only: logins with no active membership
    too), `limit` (1-200) and `offset`; `X-Total-Count` counts the same filters. Without `limit` every row.
    Design case-workspace-admin, decision 23: `status` — `active` (sign-in on and signed in at least once),
    `not_signed_in` (on, never signed in) or `off` (sign-in turned off)."""
    if q is not None and len(q.strip()) < 2:
        raise _bad_field("q needs at least 2 characters")
    if limit is not None and not 1 <= limit <= 200:
        raise _bad_field("limit must be between 1 and 200")
    if offset < 0:
        raise _bad_field("offset must be 0 or more")
    roots = _scope_roots(session, caller)
    if include_ended and roots is not None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            {"code": "scope", "message": "only a State-wide view lists logins without an active membership"},
        )
    if roots is not None and not roots:
        response.headers["X-Total-Count"] = "0"
        return []
    membership = (
        select(UserMembership.id)
        .join(Office, Office.id == UserMembership.office_id)
        .where(UserMembership.user_id == User.id, UserMembership.is_active.is_(True))
    )
    filtered = membership
    if office:
        root = session.scalar(select(Office).where(Office.code == office.strip().upper()))
        if root is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no such office")
        filtered = filtered.where((Office.id == root.id) | Office.path.like(root.path + "/%"))
    if roots is not None:
        filtered = filtered.where(
            or_(*[(Office.id == r.id) | Office.path.like(r.path + "/%") for r in roots])
        )
    if role is not None:
        filtered = filtered.where(UserMembership.role == role)
    condition = filtered.exists()
    if include_ended and not office and role is None:
        condition = condition | ~membership.exists()
    stmt = select(User).where(condition)
    if q is not None:
        pattern = _like(q.strip())
        stmt = stmt.where(User.full_name.ilike(pattern, escape="\\") | User.email.ilike(pattern, escape="\\"))
    if status_ == "active":
        stmt = stmt.where(User.is_active.is_(True), User.last_login_at.is_not(None))
    elif status_ == "not_signed_in":
        stmt = stmt.where(User.is_active.is_(True), User.last_login_at.is_(None))
    elif status_ == "off":
        stmt = stmt.where(User.is_active.is_(False))
    total = session.scalar(select(func.count()).select_from(stmt.subquery()))
    response.headers["X-Total-Count"] = str(total)
    stmt = stmt.order_by(User.email, User.id)
    if limit is not None:
        stmt = stmt.limit(limit).offset(offset)
    elif offset:
        stmt = stmt.offset(offset)
    return [user_out(session, u) for u in session.scalars(stmt).all()]


@router.get("/lookup", response_model=schemas.UserLookupOut)
def lookup(
    email: str,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.USERS_CREATE)),
) -> schemas.UserLookupOut:
    """A person by exact e-mail, to add a membership for one's own offices to someone from elsewhere: the id,
    name and memberships (office code, designation, type); 404 otherwise. No list of other departments' users."""
    user = memberships.lookup(session, email)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such user")
    items = []
    for m in access.active_memberships(session, user):
        items.append(
            schemas.LookupMembershipOut(
                office_code=session.get(Office, m.office_id).code, designation=m.designation, role=m.role
            )
        )
    return schemas.UserLookupOut(id=user.id, full_name=user.full_name, memberships=items)


@router.post("", response_model=schemas.UserOut, status_code=status.HTTP_201_CREATED)
def create(
    body: schemas.UserCreateIn,
    request: Request,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.USERS_CREATE)),
) -> schemas.UserOut:
    office = session.scalar(
        select(Office).where(Office.code == body.office_code.strip().upper(), Office.is_active.is_(True))
    )
    if office is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "no such office")
    try:
        if body.role.value == "super_admin":
            raise access.Forbidden(
                "the super admin is created only from the server's command line", "super_admin_cli_only"
            )
        if body.role.value == "dept_head":
            raise access.Conflict(
                "use_head_change", "a department head is set through the head-change request"
            )
        member = access.assert_can_manage(
            session,
            caller,
            "create",
            target_office=office,
            target_role=body.role,
            functions=set(body.functions) or None,
        )
        if body.functions:
            access.require(session, caller, Permission.USERS_GRANT)
        actor = access.actor_as(actor_of(request, caller, session), member)
        user = create_user(
            session,
            actor,
            email=body.email,
            password=body.password,
            full_name=body.full_name,
            role=body.role,
            office=office,
            designation=body.designation,
            designation_id=body.designation_id,
            mobile=body.mobile,
        )
        for perm in body.functions:
            access.set_override(
                session, actor, caller, user, perm, PermissionEffect.GRANT, reason="granted at creation"
            )
    except HANDLED as exc:
        raise http_error(exc) from exc
    return user_out(session, user)


@router.get("/{user_id}", response_model=schemas.UserOut)
def get_user(
    user_id: uuid.UUID,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.USERS_VIEW)),
) -> schemas.UserOut:
    user = session.get(User, user_id)
    if user is None or not _visible(session, caller, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such user")
    return user_out(session, user)


@router.patch("/{user_id}", response_model=schemas.UserOut)
def patch_user(
    user_id: uuid.UUID,
    body: schemas.UserPatchIn,
    request: Request,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.USERS_EDIT)),
    mailer: Mailer = Depends(get_mailer),
) -> schemas.UserOut:
    """Login-level fields (name, mobile, e-mail; `designation` changes the primary membership's): the super admin
    or a caller whose scope covers the primary membership's office. An e-mail change (design `otp-and-profile`,
    decision 13) ends the login's sessions and mails a notice to the old address; 409 `email_taken`; the super
    admin's own login 403 `super_admin_cli_only`."""
    user = _load(session, caller, user_id)
    fields = body.model_dump(exclude_unset=True)
    try:
        if access.is_super_admin(user) and (not access.is_super_admin(caller) or fields.get("email")):
            raise access.Forbidden(
                "the super admin is changed only from the server's command line", "super_admin_cli_only"
            )
        member = access.login_scope_member(session, caller, user, "edit")
        update_profile(
            session,
            access.actor_as(actor_of(request, caller, session), member),
            user,
            mailer=mailer,
            **fields,
        )
    except HANDLED as exc:
        raise http_error(exc) from exc
    return user_out(session, user)


@router.post("/{user_id}/enable", response_model=schemas.UserOut)
def enable(
    user_id: uuid.UUID,
    request: Request,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.USERS_ENABLE_DISABLE)),
) -> schemas.UserOut:
    return _toggle(user_id, True, request, session, caller)


@router.post("/{user_id}/disable", response_model=schemas.UserOut)
def disable(
    user_id: uuid.UUID,
    request: Request,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.USERS_ENABLE_DISABLE)),
) -> schemas.UserOut:
    return _toggle(user_id, False, request, session, caller)


def _toggle(
    user_id: uuid.UUID, enabled: bool, request: Request, session: Session, caller: User
) -> schemas.UserOut:
    user = _load(session, caller, user_id)
    try:
        access.set_enabled(session, actor_of(request, caller, session), caller, user, enabled)
    except HANDLED as exc:
        raise http_error(exc) from exc
    return user_out(session, user)


@router.put("/{user_id}/type", response_model=schemas.UserOut)
def set_type(
    user_id: uuid.UUID,
    body: schemas.TypeIn,
    request: Request,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.USERS_SET_TYPE)),
) -> schemas.UserOut:
    """Compatibility: changes the type of the login's primary membership (same limits)."""
    user = _load(session, caller, user_id)
    try:
        access.set_type(session, actor_of(request, caller, session), caller, user, body.role)
    except HANDLED as exc:
        raise http_error(exc) from exc
    return user_out(session, user)


@router.post("/{user_id}/password", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(
    user_id: uuid.UUID,
    body: schemas.PasswordIn,
    request: Request,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.USERS_RESET_PASSWORD)),
) -> None:
    """Login-level: the super admin or a caller whose scope covers the primary membership's office. Sets
    `must_change_password` and ends the login's sessions (design `otp-and-profile`, decisions 9, 14); 422
    `weak_password`."""
    user = _load(session, caller, user_id)
    try:
        if access.is_super_admin(user) and not access.is_super_admin(caller):
            raise access.Forbidden(
                "the super admin is changed only from the server's command line", "super_admin_cli_only"
            )
        member = access.login_scope_member(session, caller, user, "reset_password")
        set_password(
            session, access.actor_as(actor_of(request, caller, session), member), user, body.password
        )
    except HANDLED as exc:
        raise http_error(exc) from exc


# ------------------------------------------------------------------------------------------------ functions


def _functions_out(session: Session, user: User) -> schemas.UserFunctionsOut:
    primary = next((m for m in access.active_memberships(session, user) if m.is_primary), None)
    overrides = memberships.overrides_out(session, primary) if primary is not None else []
    return schemas.UserFunctionsOut(
        user_id=user.id,
        role=primary.role if primary is not None else user.role,  # display
        functions=sorted(access.membership_functions(session, primary, user)) if primary is not None else [],
        overrides=[schemas.OverrideOut(**o) for o in overrides],
    )


@router.get("/{user_id}/permissions", response_model=schemas.UserFunctionsOut)
def get_functions(
    user_id: uuid.UUID,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.USERS_VIEW)),
) -> schemas.UserFunctionsOut:
    """Compatibility: the primary membership's functions and overrides."""
    return _functions_out(session, _load(session, caller, user_id))


@router.put("/{user_id}/permissions/{permission}", response_model=schemas.UserFunctionsOut)
def set_function(
    user_id: uuid.UUID,
    permission: Permission,
    body: schemas.OverrideIn,
    request: Request,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.USERS_GRANT)),
) -> schemas.UserFunctionsOut:
    """Compatibility: an override on the primary membership."""
    user = _load(session, caller, user_id)
    effect = PermissionEffect(body.effect) if body.effect else None
    try:
        access.set_override(
            session, actor_of(request, caller, session), caller, user, permission, effect, reason=body.reason
        )
    except HANDLED as exc:
        raise http_error(exc) from exc
    return _functions_out(session, user)


# ------------------------------------------------------------------------------------------------ memberships


@router.get("/{user_id}/memberships", response_model=list[schemas.MembershipOut])
def list_memberships(
    user_id: uuid.UUID,
    include_ended: bool = False,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.USERS_VIEW)),
) -> list[schemas.MembershipOut]:
    user = session.get(User, user_id)
    if user is None or not _visible(session, caller, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such user")
    return [
        _m_out(session, m) for m in memberships.memberships_of(session, user, include_ended=include_ended)
    ]


@router.post(
    "/{user_id}/memberships", response_model=schemas.MembershipOut, status_code=status.HTTP_201_CREATED
)
def add_membership(
    user_id: uuid.UUID,
    body: schemas.MembershipIn,
    request: Request,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.USERS_CREATE)),
) -> schemas.MembershipOut:
    """Decision 8: a membership for an office the caller's membership covers, of a delegable type (the super
    admin: any but `super_admin`); 409 `one_per_department`, `super_admin_single`, `one_dept_admin`,
    `use_head_change` (a head is set through the head-change request)."""
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such user")
    office = _office(session, body.office)
    try:
        m = memberships.add(
            session,
            actor_of(request, caller, session),
            caller,
            user,
            office=office,
            role=body.role,
            designation=body.designation,
            designation_id=body.designation_id,
        )
    except HANDLED as exc:
        raise http_error(exc) from exc
    return _m_out(session, m)


@router.patch("/{user_id}/memberships/{membership_id}", response_model=schemas.MembershipOut)
def patch_membership(
    user_id: uuid.UUID,
    membership_id: uuid.UUID,
    body: schemas.MembershipPatchIn,
    request: Request,
    session: Session = Depends(get_session),
    caller: User = Depends(require_any(Permission.USERS_EDIT, Permission.USERS_SET_TYPE)),
) -> schemas.MembershipOut:
    """Designation (`users.edit`) or type (`users.set_type`); 409 `use_head_change` for a change to
    `dept_head`, `head_required` for the current head's type."""
    user = _load(session, caller, user_id)
    m = _membership(session, user, membership_id)
    fields = body.model_dump(exclude_unset=True)
    try:
        memberships.update(
            session,
            actor_of(request, caller, session),
            caller,
            m,
            designation=fields.get("designation", memberships.UNSET),
            designation_id=fields.get("designation_id", memberships.UNSET),
            role=fields.get("role", memberships.UNSET),
        )
    except HANDLED as exc:
        raise http_error(exc) from exc
    return _m_out(session, m)


@router.get("/{user_id}/memberships/{membership_id}/exit-preview", response_model=schemas.ExitPreviewOut)
def exit_preview(
    user_id: uuid.UUID,
    membership_id: uuid.UUID,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.USERS_ENABLE_DISABLE)),
) -> schemas.ExitPreviewOut:
    """Decision 22: every allotted case and held file of the membership, the counts, the fingerprint and the
    eligible officers of the department; writes nothing."""
    user = _load(session, caller, user_id)
    m = _membership(session, user, membership_id)
    try:
        return schemas.ExitPreviewOut(**memberships.exit_preview(session, caller, m))
    except HANDLED as exc:
        raise http_error(exc) from exc


@router.post("/{user_id}/memberships/{membership_id}/end", response_model=schemas.MembershipEndOut)
def end_membership(
    user_id: uuid.UUID,
    membership_id: uuid.UUID,
    body: schemas.MembershipEndIn,
    request: Request,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.USERS_ENABLE_DISABLE)),
) -> schemas.MembershipEndOut:
    """Decision 21: ends the membership once every item has a target officer (empty list when nothing is held);
    409 `unassigned_items`, `stale_exit`, `head_required`; 400 `bad_target`, `duplicate_item`."""
    user = _load(session, caller, user_id)
    m = _membership(session, user, membership_id)
    try:
        result = memberships.end(
            session,
            actor_of(request, caller, session),
            caller,
            m,
            reason=body.reason,
            assignments=[a.model_dump(mode="json") for a in body.assignments],
            items_fingerprint=body.items_fingerprint,
        )
    except HANDLED as exc:
        raise http_error(exc) from exc
    return schemas.MembershipEndOut(
        membership=_m_out(session, result.membership),
        reassigned=[schemas.ReassignedOut(**r) for r in result.reassigned],
        counts=schemas.ExitResultCountsOut(**result.counts),
    )


@router.post("/{user_id}/memberships/{membership_id}/reactivate", response_model=schemas.MembershipOut)
def reactivate_membership(
    user_id: uuid.UUID,
    membership_id: uuid.UUID,
    request: Request,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.USERS_ENABLE_DISABLE)),
) -> schemas.MembershipOut:
    user = _load(session, caller, user_id)
    m = _membership(session, user, membership_id)
    try:
        memberships.reactivate(session, actor_of(request, caller, session), caller, m)
    except HANDLED as exc:
        raise http_error(exc) from exc
    return _m_out(session, m)


@router.put("/{user_id}/primary-membership", response_model=schemas.UserOut)
def make_primary(
    user_id: uuid.UUID,
    body: schemas.PrimaryMembershipIn,
    request: Request,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.USERS_EDIT)),
) -> schemas.UserOut:
    user = _load(session, caller, user_id)
    m = _membership(session, user, body.membership)
    try:
        memberships.make_primary(session, actor_of(request, caller, session), caller, user, m)
    except HANDLED as exc:
        raise http_error(exc) from exc
    return user_out(session, user)


def _membership_functions_out(session: Session, m: UserMembership) -> schemas.MembershipFunctionsOut:
    return schemas.MembershipFunctionsOut(
        membership_id=m.id,
        role=m.role,
        type_functions=sorted(access.role_functions(session, m.role)),
        overrides=[schemas.OverrideOut(**o) for o in memberships.overrides_out(session, m)],
        effective=sorted(access.membership_functions(session, m)),
    )


@router.get(
    "/{user_id}/memberships/{membership_id}/permissions", response_model=schemas.MembershipFunctionsOut
)
def membership_functions(
    user_id: uuid.UUID,
    membership_id: uuid.UUID,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.USERS_VIEW)),
) -> schemas.MembershipFunctionsOut:
    user = session.get(User, user_id)
    if user is None or not _visible(session, caller, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such user")
    m = _membership(session, user, membership_id)
    if not _in_roots(session.get(Office, m.office_id), _scope_roots(session, caller)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such membership")
    return _membership_functions_out(session, m)


@router.put(
    "/{user_id}/memberships/{membership_id}/permissions/{permission}",
    response_model=schemas.MembershipFunctionsOut,
)
def set_membership_function(
    user_id: uuid.UUID,
    membership_id: uuid.UUID,
    permission: Permission,
    body: schemas.OverrideIn,
    request: Request,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.USERS_GRANT)),
) -> schemas.MembershipFunctionsOut:
    """Decision 8: an override on one membership, only within the caller's scope over it and only functions held
    in the acting membership; 400 `reserved_function` for `admin.tickets`."""
    user = _load(session, caller, user_id)
    m = _membership(session, user, membership_id)
    effect = PermissionEffect(body.effect) if body.effect else None
    try:
        access.set_override(
            session, actor_of(request, caller, session), caller, m, permission, effect, reason=body.reason
        )
    except HANDLED as exc:
        raise http_error(exc) from exc
    return _membership_functions_out(session, m)


@router.get(
    "/{user_id}/memberships/{membership_id}/documents", response_model=list[schemas.MembershipDocumentOut]
)
def membership_documents(
    user_id: uuid.UUID,
    membership_id: uuid.UUID,
    session: Session = Depends(get_session),
    caller: User = Depends(require_any(Permission.USERS_PROPOSE_HEAD, Permission.ADMIN_TICKETS)),
) -> list[schemas.MembershipDocumentOut]:
    """Decision 20: the orders that authorised the membership's changes; 404 unless the caller is the super
    admin or holds `users.propose_head` in its department."""
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such user")
    m = _membership(session, user, membership_id)
    try:
        return [schemas.MembershipDocumentOut(**d) for d in tickets.membership_documents(session, caller, m)]
    except HANDLED as exc:
        raise http_error(exc) from exc
