"""`REF_NO_RE` reads hyphenated office codes up to 20 characters (design `offices-import`, decision 6)."""

from __future__ import annotations

from aslms.services.refno import current_case_ref_no, format_ref_no, parse_ref_no


def test_parse_ref_no_accepts_hyphenated_office():
    assert parse_ref_no("ASLMS/SEC-EDU/TKT/2026/000001") == ("SEC-EDU", "TKT", 2026, 1)
    assert parse_ref_no("ASLMS/HFW-DME/NOTE/2026/000042") == ("HFW-DME", "NOTE", 2026, 42)
    code = "ABCDEFGHIJKLMNOPQ"  # 17, the longest office code
    ref = format_ref_no(code, "NOTE", 2026, 1)
    assert len(ref) <= 40 and parse_ref_no(ref) == (code, "NOTE", 2026, 1)
    assert parse_ref_no("ASLMS/" + "A" * 21 + "/NOTE/2026/000001") is None
    assert parse_ref_no("ASLMS/GHC/CASE/2026/054584") == ("GHC", "CASE", 2026, 54584)
    assert current_case_ref_no("ASLMS/SEC-EDU/TKT/2026/000001") == "ASLMS/SEC-EDU/TKT/2026/000001"
