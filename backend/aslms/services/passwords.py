"""Passwords (design `otp-and-profile`, decision 8): argon2id hashing and the one policy every path that sets a
password applies (administrator creation and reset, the CLI, reset by e-mail, the person's own change): at least
10 characters with at least one letter and one digit, and not the current password. No periodic expiry.

`UserError` lives here so `WeakPassword` is one of them: every caller that already refuses a `UserError` refuses
a weak password too; the API maps `WeakPassword` to 422 `weak_password`."""

from __future__ import annotations

import re

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_hasher = PasswordHasher()
MIN_PASSWORD = 10
MAX_PASSWORD = 200
_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)
_DIGIT = re.compile(r"\d")


class UserError(ValueError):
    """A request that cannot be honoured (bad input, duplicate email, unknown office)."""


class WeakPassword(UserError):
    """The new password breaks the policy (HTTP 422 `weak_password`)."""

    code = "weak_password"


def verify_password(password_hash: str | None, password: str) -> bool:
    if not password_hash:
        return False
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False
    except Exception:  # noqa: BLE001 — a malformed hash never authenticates
        return False


def check_policy(new: str, current_hash: str | None = None) -> None:
    """Raises `WeakPassword` with the first rule the password breaks."""
    if new is None or len(new) < MIN_PASSWORD:
        raise WeakPassword(f"password must be at least {MIN_PASSWORD} characters")
    if len(new) > MAX_PASSWORD:
        raise WeakPassword(f"password must be at most {MAX_PASSWORD} characters")
    if not _LETTER.search(new) or not _DIGIT.search(new):
        raise WeakPassword("password must contain at least one letter and one digit")
    if current_hash and verify_password(current_hash, new):
        raise WeakPassword("the new password must differ from the current one")


def hash_password(password: str) -> str:
    """The argon2id hash of a password that passes the policy (the current-password rule is checked by the
    caller that knows the current hash)."""
    check_policy(password)
    return _hasher.hash(password)


DUMMY_HASH = _hasher.hash("not-a-real-password-just-timing-1")
