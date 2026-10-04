"""The envelope as the live service accepted it (docs/napix_integration_notes.md §3–§4)."""

from __future__ import annotations

import base64

import pytest

from aslms.integration.napix.crypto import KNOWN_ANSWERS, NapixCrypto, build_plain, key_bytes

KEY = "abcdefghijklmnop"  # 16 characters; not a real key


def test_known_answers_subscriber_manual_and_empty_input() -> None:
    c = NapixCrypto(KEY)
    assert c.token("state_code=27") == KNOWN_ANSWERS["state_code=27"]
    assert c.token("") == KNOWN_ANSWERS[""]
    assert c.self_test()


def test_key_is_trimmed_cut_or_zero_padded_to_16_bytes() -> None:
    assert key_bytes("  short ") == b"short" + b"\0" * 11
    assert key_bytes("0123456789abcdefXYZ") == b"0123456789abcdef"
    assert len(key_bytes("")) == 16


def test_encrypt_decrypt_roundtrip_including_empty_string() -> None:
    c = NapixCrypto(KEY)
    for plain in ("est_code=GAHC01|causelist_date=2026-09-24", "", "cino=GAHC010153612024"):
        enc = c.encrypt(plain)
        base64.b64decode(enc, validate=True)  # plain Base64, no "Salted__" prefix
        assert c.decrypt(enc) == plain
    assert c.encrypt("") != ""  # the empty string is still a full AES block


def test_decrypt_tolerates_whitespace_and_fails_cleanly_on_wrong_key() -> None:
    c = NapixCrypto(KEY)
    enc = c.encrypt("x=1")
    assert c.decrypt(enc[:10] + "\n" + enc[10:]) == "x=1"
    with pytest.raises(ValueError, match="NAPIX_AUTH_KEY"):
        NapixCrypto("another-key-0000").decrypt(enc)


def test_build_plain_keeps_order_and_values_verbatim() -> None:
    assert (
        build_plain({"est_code": "GAHC01", "causelist_date": "2026-09-24"})
        == "est_code=GAHC01|causelist_date=2026-09-24"
    )
    assert build_plain({}) == ""


def test_build_plain_refuses_values_that_would_add_or_change_a_pair() -> None:
    from aslms.core.errors import NapixInputError

    for bad in ("ASSAM|est_code=XXHC01", "A=B", "x|y"):
        with pytest.raises(NapixInputError):
            build_plain({"est_code": "GAHC01", "litigant_name": bad})
    with pytest.raises(NapixInputError):
        build_plain({"a|b": "c"})
    assert (
        build_plain({"litigant_name": "DR. JANIFA KAIFEE AHMED"}) == "litigant_name=DR. JANIFA KAIFEE AHMED"
    )


def test_fingerprint_is_short_and_reveals_nothing() -> None:
    f = NapixCrypto(KEY).fingerprint
    assert len(f) == 8 and KEY not in f
