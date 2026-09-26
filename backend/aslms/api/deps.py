"""Request dependencies: database session, the signed-in user (bearer JWT), their scope principal, and the
frozen actor snapshot used for audit rows."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from aslms.core.errors import UnauthorizedError
from aslms.core.security import decode_access_token
from aslms.db.session import get_db
from aslms.domain.org import Role, User
from aslms.services.audit import Actor
from aslms.services.scope import Principal, principal_for, require_role

bearer = HTTPBearer(auto_error=False)


@dataclass
class Ctx:
    """Everything a handler needs about the caller."""

    db: Session
    user: User
    principal: Principal
    actor: Actor


def current_ctx(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> Ctx:
    if creds is None or creds.scheme.lower() != "bearer":
        raise UnauthorizedError("sign in required")
    try:
        payload = decode_access_token(creds.credentials)
        user_id = uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError) as e:
        raise UnauthorizedError("session expired or invalid") from e
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError("account disabled")
    ip = request.client.host if request.client else None
    return Ctx(db, user, principal_for(db, user), Actor.of(user, ip, request.headers.get("user-agent")))


def roles(*allowed: Role):
    """Dependency factory: `ctx: Ctx = Depends(roles(Role.DEPT_ADMIN, ...))`."""

    def dep(ctx: Ctx = Depends(current_ctx)) -> Ctx:
        require_role(ctx.principal, *allowed)
        return ctx

    return dep


def client_meta(request: Request) -> tuple[str | None, str | None]:
    return (request.client.host if request.client else None), request.headers.get("user-agent")
