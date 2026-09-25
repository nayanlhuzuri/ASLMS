"""Password hashing (argon2), JWT access tokens, rotating refresh tokens and OTP codes.
Pure functions over settings; no database access here."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from aslms.core.config import get_settings
from aslms.core.time import now_utc

_hasher = PasswordHasher()
JWT_ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False
    except Exception:  # noqa: BLE001 — malformed hash
        return False


def create_access_token(
    user_id: uuid.UUID, role: str, office_path: str, *, minutes: int | None = None
) -> str:
    settings = get_settings()
    exp = now_utc() + timedelta(minutes=minutes or settings.access_token_minutes)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "role": role,
        "office_path": office_path,
        "iat": int(now_utc().timestamp()),
        "exp": int(exp.timestamp()),
        "jti": secrets.token_hex(8),
    }
    return jwt.encode(payload, settings.secret_key.get_secret_value(), algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """Raises jwt.PyJWTError on any problem (expired, tampered, wrong key)."""
    return jwt.decode(token, get_settings().secret_key.get_secret_value(), algorithms=[JWT_ALGORITHM])


def sha256_hex(value: str | bytes) -> str:
    data = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(data).hexdigest()


def new_refresh_token() -> tuple[str, str, datetime]:
    """Returns (raw token for the client, sha256 to store, expiry)."""
    raw = secrets.token_urlsafe(48)
    return raw, sha256_hex(raw), now_utc() + timedelta(days=get_settings().refresh_token_days)


def generate_otp() -> tuple[str, str, datetime]:
    """Returns (6-digit code, sha256 to store, expiry)."""
    code = f"{secrets.randbelow(1_000_000):06d}"
    return code, sha256_hex(code), now_utc() + timedelta(minutes=get_settings().otp_expiry_minutes)
