"""HTTP mapping of the access, membership and ticket errors (design `user-memberships`): 403 for a missing
function, scope or a reserved path, 409 with a machine-readable `code` for a state conflict, 400 for bad input,
404 for what the caller may not see. A plain `Forbidden` keeps its message as the detail (as before)."""

from __future__ import annotations

from fastapi import HTTPException, status

from aslms.services.access import Conflict, Forbidden, ReservedFunction
from aslms.services.memberships import MembershipError
from aslms.services.offices import AdminExists, DuplicateCode, HeadRequired, OfficeError, OfficeInUse
from aslms.services.tickets import TicketError
from aslms.services.users import EmailTaken, UserError, WeakPassword

HANDLED = (
    Forbidden,
    Conflict,
    ReservedFunction,
    MembershipError,
    TicketError,
    OfficeError,
    UserError,
)


def detail(code: str, message: str, **extra) -> dict:
    return {"code": code, "message": message, **extra}


def http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, Forbidden):
        if exc.code == "forbidden":
            return HTTPException(status.HTTP_403_FORBIDDEN, str(exc))
        return HTTPException(status.HTTP_403_FORBIDDEN, detail(exc.code, str(exc)))
    if isinstance(exc, Conflict):
        return HTTPException(status.HTTP_409_CONFLICT, detail(exc.code, str(exc), **exc.extra))
    if isinstance(exc, ReservedFunction):
        return HTTPException(status.HTTP_400_BAD_REQUEST, detail(exc.code, str(exc)))
    if isinstance(exc, MembershipError):
        return HTTPException(status.HTTP_400_BAD_REQUEST, detail(exc.code, str(exc), **exc.extra))
    if isinstance(exc, TicketError):
        return HTTPException(exc.http_status, detail(exc.code, str(exc), **exc.extra))
    if isinstance(exc, AdminExists):
        return HTTPException(status.HTTP_409_CONFLICT, detail("admin_exists", str(exc)))
    if isinstance(exc, HeadRequired):
        return HTTPException(status.HTTP_400_BAD_REQUEST, detail("head_required", str(exc)))
    if isinstance(exc, OfficeInUse):
        return HTTPException(status.HTTP_409_CONFLICT, {"message": str(exc), "counts": exc.counts})
    if isinstance(exc, DuplicateCode):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc))
    if isinstance(exc, WeakPassword):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail("weak_password", str(exc)))
    if isinstance(exc, EmailTaken):
        return HTTPException(status.HTTP_409_CONFLICT, detail("email_taken", str(exc)))
    if isinstance(exc, OfficeError | UserError):
        return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    raise exc
