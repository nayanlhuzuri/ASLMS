from __future__ import annotations

import pytest

from aslms.integration.napix.crypto import (
    KNOWN_ANSWER_PLAIN,
    KNOWN_ANSWER_TOKEN,
    NapixCrypto,
    build_plain,
    key_bytes,
)


def test_known_answer_from_subscriber_manual() -> None:
    c = NapixCrypto("0123456789abcdef")
    assert c.token(KNOWN_ANSWER_PLAIN) == KNOWN_ANSWER_TOKEN
    assert c.self_test()


def test_encrypt_decrypt_roundtrip_and_base64_shape() -> None:
    c = NapixCrypto("0123456789abcdef")
    plain = build_plain({"cino": "GAHC010153612024", "order_no": "3", "order_date": "2024-09-25"})
    assert plain == "cino=GAHC010153612024|order_no=3|order_date=2024-09-25"
    enc = c.encrypt(plain)
    assert enc != plain and c.decrypt(enc) == plain
    # PHP openssl escapes slashes in JSON; the decoder tolerates that
    assert c.decrypt(enc.replace("/", "\\/")) == plain


def test_key_modes_and_padding() -> None:
    assert key_bytes("abc") == b"abc" + b"\0" * 13
    assert key_bytes("0123456789abcdef0123") == b"0123456789abcdef"
    assert key_bytes("30313233343536373839616263646566", "hex") == b"0123456789abcdef"
    assert key_bytes("MDEyMzQ1Njc4OWFiY2RlZg==", "base64") == b"0123456789abcdef"
    with pytest.raises(ValueError):
        key_bytes("x", "rot13")


def test_wrong_key_fails_cleanly() -> None:
    enc = NapixCrypto("0123456789abcdef").encrypt("state_code=6")
    with pytest.raises(ValueError, match="NAPIX_AUTH_KEY"):
        NapixCrypto("fedcba9876543210").decrypt(enc)


def test_fingerprint_is_short_and_stable() -> None:
    a, b = NapixCrypto("0123456789abcdef"), NapixCrypto("0123456789abcdef")
    assert a.fingerprint == b.fingerprint and len(a.fingerprint) == 8
