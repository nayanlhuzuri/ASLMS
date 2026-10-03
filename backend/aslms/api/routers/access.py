"""`/admin/permissions` (the functions), `/admin/access/types` (the type matrix), `/admin/offices` (for pickers)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from aslms.api import schemas
from aslms.api.deps import actor_of, current_user, get_session, require
from aslms.domain.org import Office, User
from aslms.domain.reference import Permission, RefPermission, Role
from aslms.services import access
from aslms.services.access import Forbidden

router = APIRouter(prefix="/admin", tags=["access"])


@router.get("/permissions", response_model=list[schemas.PermissionOut])
def list_permissions(
    session: Session = Depends(get_session), _user: User = Depends(current_user)
) -> list[schemas.PermissionOut]:
    rows = session.scalars(select(RefPermission).order_by(RefPermission.sort_order)).all()
    return [
        schemas.PermissionOut(
            code=Permission(r.code),
            module=r.module,
            label=r.label,
            description=r.description,
            is_active=r.is_active,
        )
        for r in rows
    ]


@router.get("/access/types", response_model=dict[str, dict[str, bool]])
def get_matrix(
    session: Session = Depends(get_session), _user: User = Depends(require(Permission.USERS_VIEW))
) -> dict[str, dict[str, bool]]:
    return access.matrix(session)


@router.get("/access/types/{role}", response_model=dict[str, bool])
def get_role_matrix(
    role: Role, session: Session = Depends(get_session), _user: User = Depends(require(Permission.USERS_VIEW))
) -> dict[str, bool]:
    return access.matrix(session, role).get(role.value, {})


@router.put("/access/types/{role}/{permission}", response_model=dict[str, bool])
def set_role_function(
    role: Role,
    permission: Permission,
    body: schemas.MatrixEntryIn,
    request: Request,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.ACCESS_MANAGE_TYPES)),
) -> dict[str, bool]:
    try:
        access.set_matrix(session, actor_of(request, caller, session), caller, role, permission, body.enabled)
    except Forbidden as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    return access.matrix(session, role).get(role.value, {})


@router.get("/offices", response_model=list[schemas.OfficeOut])
def list_offices(
    session: Session = Depends(get_session), user: User = Depends(require(Permission.USERS_VIEW))
) -> list[schemas.OfficeOut]:
    if access.is_super_admin(user) or access.has(session, user, Permission.CASES_VIEW_ALL):
        rows = session.scalars(select(Office).where(Office.is_active.is_(True)).order_by(Office.path)).all()
    else:
        rows = sorted(access.office_subtree(session, user.office_id), key=lambda o: o.path)
    return [
        schemas.OfficeOut(id=o.id, code=o.code, name=o.name, kind=str(o.kind.value), path=o.path)
        for o in rows
    ]
