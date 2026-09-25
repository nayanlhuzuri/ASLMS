from __future__ import annotations

import uuid

import jwt
import pytest

from aslms.core.security import (
    create_access_token,
    decode_access_token,
    generate_otp,
    hash_password,
    new_refresh_token,
    sha256_hex,
    verify_password,
)


def test_password_hash_roundtrip() -> None:
    h = hash_password("s3cret-pass")
    assert h.startswith("$argon2")
    assert verify_password("s3cret-pass", h)
    assert not verify_password("wrong", h)
    assert not verify_password("s3cret-pass", "not-a-hash")


def test_access_token_roundtrip_and_expiry() -> None:
    uid = uuid.uuid4()
    token = create_access_token(uid, "dept_admin", "EDU")
    payload = decode_access_token(token)
    assert payload["sub"] == str(uid)
    assert payload["role"] == "dept_admin"
    assert payload["office_path"] == "EDU"
    expired = create_access_token(uid, "dept_admin", "EDU", minutes=-1)
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(expired)


def test_refresh_token_and_otp_shapes() -> None:
    raw, hashed, exp = new_refresh_token()
    assert hashed == sha256_hex(raw) and len(hashed) == 64
    code, code_hash, otp_exp = generate_otp()
    assert len(code) == 6 and code.isdigit()
    assert code_hash == sha256_hex(code)
    assert otp_exp < exp
