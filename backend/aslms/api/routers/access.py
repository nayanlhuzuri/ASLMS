"""`/admin/permissions` (the functions, with their plain-language groups) and `/admin/access/*` (the type matrix, the
seed defaults, the user-type cards and the one-batch save). Offices live in `routers/offices.py`."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from aslms.api import schemas
from aslms.api.deps import actor_of, current_user, get_session, require
from aslms.domain.org import User
from aslms.domain.reference import RETIRED_PERMISSIONS, Permission, RefPermission, Role
from aslms.services import access
from aslms.services.access import Forbidden
from aslms.services.access_seed import permission_group

router = APIRouter(prefix="/admin", tags=["access"])


@router.get("/permissions", response_model=list[schemas.PermissionOut])
def list_permissions(
    session: Session = Depends(get_session), _user: User = Depends(current_user)
) -> list[schemas.PermissionOut]:
    rows = session.scalars(select(RefPermission).order_by(RefPermission.sort_order)).all()
    out = []
    for r in rows:
        code = Permission(r.code)
        group = permission_group(code) if code not in RETIRED_PERMISSIONS else None
        out.append(
            schemas.PermissionOut(
                code=code,
                module=r.module,
                label=r.label,
                description=r.description,
                is_active=r.is_active,
                group=group[0] if group else None,
                group_label=group[1] if group else None,
                sort_in_group=group[2] if group else None,
            )
        )
    return out


@router.get("/access/defaults", response_model=dict[str, dict[str, bool]])
def get_defaults(_user: User = Depends(require(Permission.USERS_VIEW))) -> dict[str, dict[str, bool]]:
    """The seed's default functions per user type over the active functions (the super admin all on): what "Changed
    from default" and "Reset to default" measure against (design case-workspace-admin, decision 27)."""
    return access.defaults()


@router.get("/access/overview", response_model=list[schemas.UserTypeCardOut])
def get_overview(
    session: Session = Depends(get_session), caller: User = Depends(require(Permission.USERS_VIEW))
) -> list[schemas.UserTypeCardOut]:
    """Per user type: the logins with an active membership of the type in the caller's scope (as `GET /admin/users`),
    the functions on, the active functions in all and how many differ from the defaults."""
    return [schemas.UserTypeCardOut(**row) for row in access.overview(session, caller)]


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


@router.put(
    "/access/types/{role}",
    response_model=dict[str, bool],
    responses={400: {"model": schemas.ErrorOut}, 403: {"model": schemas.ErrorOut}},
)
def set_role_functions(
    role: Role,
    body: schemas.MatrixBatchIn,
    request: Request,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.ACCESS_MANAGE_TYPES)),
) -> dict[str, bool]:
    """Several functions of one user type in one transaction (design case-workspace-admin, decision 27): each changed
    function writes its own `access.matrix` audit row and `access_changed` event; unchanged entries are skipped; a
    refusal (the super admin type 403, `admin.tickets` or a retired function 400) saves nothing."""
    try:
        return access.set_matrix_batch(
            session,
            actor_of(request, caller, session),
            caller,
            role,
            [(c.permission, c.enabled) for c in body.changes],
        )
    except Forbidden as exc:
        session.rollback()
        raise HTTPException(status.HTTP_403_FORBIDDEN, {"code": exc.code, "message": str(exc)}) from exc
    except access.ReservedFunction as exc:
        session.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, {"code": exc.code, "message": str(exc)}) from exc


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
    except access.ReservedFunction as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, {"code": exc.code, "message": str(exc)}) from exc
    return access.matrix(session, role).get(role.value, {})
