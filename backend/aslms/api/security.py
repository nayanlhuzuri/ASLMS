"""Tokens: short-lived HS256 access tokens (`sub` = user id) and rotating refresh tokens stored hashed in
`refresh_tokens`. The signing secret is `ASLMS_JWT_SECRET`; without it the API refuses to start."""

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
        raise RuntimeError("ASLMS_JWT_SECRET is not set (at least 32 characters; e.g. `openssl rand -hex 32`)")
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


def read_access_token(token: str, settings: Settings | None = None) -> uuid.UUID | None:
    try:
        payload = jwt.decode(token, jwt_secret(settings), algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    if payload.get("typ") != "access":
        return None
    try:
        return uuid.UUID(str(payload.get("sub")))
    except ValueError:
        return None


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_refresh_token(
    session: Session, user: User, device_label: str | None = None, settings: Settings | None = None
) -> str:
    s = settings or get_settings()
    raw = secrets.token_urlsafe(48)
    session.add(
        RefreshToken(
            user_id=user.id,
            token_hash=_hash(raw),
            expires_at=datetime.now(UTC) + timedelta(days=s.aslms_refresh_token_days),
            device_label=(device_label or None) and device_label[:200],
        )
    )
    session.flush()
    return raw


def consume_refresh_token(session: Session, raw: str) -> User | None:
    """Validates and revokes a refresh token (rotation); returns its user when it was live."""
    row = session.scalar(select(RefreshToken).where(RefreshToken.token_hash == _hash(raw)))
    now = datetime.now(UTC)
    if row is None or row.revoked_at is not None or row.expires_at < now:
        return None
    row.revoked_at = now
    session.flush()
    user = session.get(User, row.user_id)
    return user if user is not None and user.is_active else None


def revoke_refresh_token(session: Session, raw: str) -> bool:
    row = session.scalar(select(RefreshToken).where(RefreshToken.token_hash == _hash(raw)))
    if row is None or row.revoked_at is not None:
        return False
    row.revoked_at = datetime.now(UTC)
    session.flush()
    return True
