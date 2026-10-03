"""`/admin/users/*`: users in the caller's scope, creation with a type, type changes, enable/disable, per-user
functions, passwords. Every write goes through `services/access.py`, which enforces the delegation rule and
audits."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from aslms.api import schemas
from aslms.api.deps import actor_of, get_session, require
from aslms.api.routers.auth import user_out
from aslms.domain.org import Office, PermissionEffect, User, UserPermission
from aslms.domain.reference import Permission
from aslms.services import access
from aslms.services.access import Forbidden
from aslms.services.users import UserError, create_user, set_password, update_profile

router = APIRouter(prefix="/admin/users", tags=["users"])


def _forbidden(exc: Forbidden) -> HTTPException:
    return HTTPException(status.HTTP_403_FORBIDDEN, str(exc))


def _scope_offices(session: Session, user: User) -> list[uuid.UUID] | None:
    """None = everything (super admin or State-wide view); else the ids of the caller's office subtree."""
    if access.is_super_admin(user) or access.has(session, user, Permission.CASES_VIEW_ALL):
        return None
    return [o.id for o in access.office_subtree(session, user.office_id)]


def _load(session: Session, caller: User, user_id: uuid.UUID) -> User:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such user")
    scope = _scope_offices(session, caller)
    if scope is not None and user.office_id not in scope:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such user")
    return user


@router.get("", response_model=list[schemas.UserOut])
def list_users(
    office: str | None = None,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.USERS_VIEW)),
) -> list[schemas.UserOut]:
    stmt = select(User).order_by(User.email)
    scope = _scope_offices(session, caller)
    if office:
        root = session.scalar(select(Office).where(Office.code == office.strip().upper()))
        if root is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no such office")
        ids = [o.id for o in access.office_subtree(session, root.id)]
        if scope is not None:
            ids = [i for i in ids if i in scope]
        stmt = stmt.where(User.office_id.in_(ids))
    elif scope is not None:
        stmt = stmt.where(User.office_id.in_(scope))
    return [user_out(session, u) for u in session.scalars(stmt).all()]


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
        access.assert_can_manage(
            session,
            caller,
            "create",
            target_office=office,
            target_role=body.role,
            functions=set(body.functions) or None,
        )
        if body.functions:
            access.require(session, caller, Permission.USERS_GRANT)
        actor = actor_of(request, caller, session)
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
    except Forbidden as exc:
        raise _forbidden(exc) from exc
    except UserError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return user_out(session, user)


@router.get("/{user_id}", response_model=schemas.UserOut)
def get_user(
    user_id: uuid.UUID,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.USERS_VIEW)),
) -> schemas.UserOut:
    return user_out(session, _load(session, caller, user_id))


@router.patch("/{user_id}", response_model=schemas.UserOut)
def patch_user(
    user_id: uuid.UUID,
    body: schemas.UserPatchIn,
    request: Request,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.USERS_EDIT)),
) -> schemas.UserOut:
    user = _load(session, caller, user_id)
    try:
        access.assert_can_manage(
            session, caller, "edit", target_office=session.get(Office, user.office_id), target_role=user.role
        )
        update_profile(
            session, actor_of(request, caller, session), user, **body.model_dump(exclude_unset=True)
        )
    except Forbidden as exc:
        raise _forbidden(exc) from exc
    except UserError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
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
    except Forbidden as exc:
        raise _forbidden(exc) from exc
    return user_out(session, user)


@router.put("/{user_id}/type", response_model=schemas.UserOut)
def set_type(
    user_id: uuid.UUID,
    body: schemas.TypeIn,
    request: Request,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.USERS_SET_TYPE)),
) -> schemas.UserOut:
    user = _load(session, caller, user_id)
    try:
        access.set_type(session, actor_of(request, caller, session), caller, user, body.role)
    except Forbidden as exc:
        raise _forbidden(exc) from exc
    return user_out(session, user)


@router.post("/{user_id}/password", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(
    user_id: uuid.UUID,
    body: schemas.PasswordIn,
    request: Request,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.USERS_RESET_PASSWORD)),
) -> None:
    user = _load(session, caller, user_id)
    try:
        access.assert_can_manage(
            session,
            caller,
            "reset_password",
            target_office=session.get(Office, user.office_id),
            target_role=user.role,
        )
        set_password(session, actor_of(request, caller, session), user, body.password)
    except Forbidden as exc:
        raise _forbidden(exc) from exc
    except UserError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


def _functions_out(session: Session, user: User) -> schemas.UserFunctionsOut:
    rows = session.scalars(select(UserPermission).where(UserPermission.user_id == user.id)).all()
    return schemas.UserFunctionsOut(
        user_id=user.id,
        role=user.role,
        functions=sorted(access.effective_permissions(session, user)),
        overrides=[
            schemas.OverrideOut(
                permission=r.permission,
                effect=r.effect.value,
                is_active=r.is_active,
                granted_by_user_id=r.granted_by_user_id,
                reason=r.reason,
                valid_to=r.valid_to,
            )
            for r in rows
        ],
    )


@router.get("/{user_id}/permissions", response_model=schemas.UserFunctionsOut)
def get_functions(
    user_id: uuid.UUID,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.USERS_VIEW)),
) -> schemas.UserFunctionsOut:
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
    user = _load(session, caller, user_id)
    effect = PermissionEffect(body.effect) if body.effect else None
    try:
        access.set_override(
            session, actor_of(request, caller, session), caller, user, permission, effect, reason=body.reason
        )
    except Forbidden as exc:
        raise _forbidden(exc) from exc
    return _functions_out(session, user)
