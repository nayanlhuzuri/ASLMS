"""Tokens: short-lived HS256 access tokens (`sub` = user id, `iat` checked against `password_changed_at`) and
rotating refresh tokens stored hashed in `refresh_tokens`, tied to a device. The signing secret is
`ASLMS_JWT_SECRET`; without it the API refuses to start."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from aslms.core.config import Settings, get_settings
from aslms.domain.org import RefreshToken, User

ALGORITHM = "HS256"


def jwt_secret(settings: Settings | None = None) -> str:
    s = settings or get_settings()
    if s.aslms_jwt_secret is None or len(s.aslms_jwt_secret.get_secret_value()) < 32:
        raise RuntimeError(
            "ASLMS_JWT_SECRET is not set (at least 32 characters; e.g. `openssl rand -hex 32`)"
        )
    return s.aslms_jwt_secret.get_secret_value()


def issue_access_token(user: User, settings: Settings | None = None) -> tuple[str, int]:
    s = settings or get_settings()
    ttl = s.aslms_access_token_minutes * 60
    now = datetime.now(UTC)
    payload = {
        "sub": str(user.id),
        "typ": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl)).timestamp()),
    }
    return jwt.encode(payload, jwt_secret(s), algorithm=ALGORITHM), ttl


def read_access_claims(token: str, settings: Settings | None = None) -> tuple[uuid.UUID, int] | None:
    """The user id and the issue time (whole seconds) of a valid access token, else None."""
    try:
        payload = jwt.decode(token, jwt_secret(settings), algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    if payload.get("typ") != "access":
        return None
    try:
        return uuid.UUID(str(payload.get("sub"))), int(payload.get("iat") or 0)
    except (TypeError, ValueError):
        return None


def read_access_token(token: str, settings: Settings | None = None) -> uuid.UUID | None:
    claims = read_access_claims(token, settings)
    return claims[0] if claims else None


def issued_before(iat: int, changed_at: datetime | None) -> bool:
    """True when an access token issued at `iat` predates the login's last credential change (whole seconds:
    a token issued in the same second as the change is kept, so the fresh pair of a self-change works)."""
    return changed_at is not None and iat < int(changed_at.timestamp())


def token_hash(token: str) -> str:
    """SHA-256 hex of a refresh or device token (only the hash is stored)."""
    return hashlib.sha256(token.encode()).hexdigest()


_hash = token_hash


def issue_refresh_token(
    session: Session,
    user: User,
    device_label: str | None = None,
    settings: Settings | None = None,
    device_id: uuid.UUID | None = None,
) -> str:
    """A new refresh token tied to the device (design `otp-and-profile`, decision 6); rotation and reuse
    detection live in `services/auth.py::refresh`."""
    s = settings or get_settings()
    raw = secrets.token_urlsafe(48)
    session.add(
        RefreshToken(
            user_id=user.id,
            token_hash=_hash(raw),
            expires_at=datetime.now(UTC) + timedelta(days=s.aslms_refresh_token_days),
            device_label=(device_label or None) and device_label[:200],
            device_id=device_id,
        )
    )
    session.flush()
    return raw


def revoke_refresh_token(session: Session, raw: str, user_id: uuid.UUID) -> bool:
    """Logout: the token is revoked and its life ends at the same instant (`expires_at = revoked_at`). That
    marks it as logged out, so a later `refresh` with it answers plain `refresh_invalid` rather than reuse
    (a rotated token keeps `expires_at > revoked_at`; design `otp-and-profile`, deviation 11). Only a token of
    `user_id` (the caller) is revoked; another login's token is treated as not found."""
    row = session.scalar(select(RefreshToken).where(RefreshToken.token_hash == _hash(raw)))
    if row is None or row.user_id != user_id or row.revoked_at is not None:
        return False
    now = datetime.now(UTC)
    row.revoked_at = now
    row.expires_at = now
    session.flush()
    return True
