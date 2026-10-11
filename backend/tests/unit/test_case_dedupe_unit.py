"""The case number key of design `data-load-console` (decision 13), without a database."""

from __future__ import annotations

import uuid

from aslms.services.case_dedupe import compact, number_key

COURT = uuid.uuid4()
OTHER_COURT = uuid.uuid4()
WPC = uuid.uuid4()
WA = uuid.uuid4()


def test_number_key():
    printed = number_key(court_id=COURT, case_no_text="WP(C)/4326/2025", case_type_id=WPC)
    spaced = number_key(court_id=COURT, case_no_text="WP (C)/4326/2025")
    by_type = number_key(court_id=COURT, case_type_id=WPC, reg_no=4326, reg_year=2025)
    assert printed.compact == spaced.compact == "WP(C)/4326/2025"
    assert printed.matches(spaced) and spaced.matches(printed)
    assert printed.matches(by_type) and by_type.matches(printed)
    assert (printed.reg_no, printed.reg_year) == (4326, 2025)
    # the same number from the type text, number and year (a dossier's fields)
    assert number_key(court_id=COURT, case_type_text="WP(C)", reg_no="4326", reg_year="2025").matches(spaced)
    # another type, number, year or court is another key
    assert not printed.matches(number_key(court_id=COURT, case_no_text="WA/4326/2025", case_type_id=WA))
    assert not by_type.matches(number_key(court_id=COURT, case_type_id=WA, reg_no=4326, reg_year=2025))
    assert not printed.matches(number_key(court_id=COURT, case_no_text="WP(C)/4326/2024"))
    assert not printed.matches(number_key(court_id=OTHER_COURT, case_no_text="WP(C)/4326/2025"))
    # an empty key matches nothing
    empty = number_key(court_id=COURT)
    assert not empty.usable and not empty.matches(empty)
    assert compact("  wp ( c )/1/2025 ") == "WP(C)/1/2025" and compact(None) is None


def test_unregistered_number_key_unusable():
    """NAPIX gives a filed but unregistered case reg_no 0 and reg_year 0 (`WA/0/0`): no key, so no match."""
    printed = number_key(court_id=COURT, case_no_text="WA/0/0", case_type_id=WA)
    by_type = number_key(court_id=COURT, case_type_id=WA, reg_no=0, reg_year=0)
    from_text = number_key(court_id=COURT, case_type_text="WA", reg_no="0", reg_year="0")
    for key in (printed, by_type, from_text):
        assert not key.usable and not key.matches(key)
        assert key.compact is None and not key.by_type
    assert not printed.matches(by_type)
    # a zero number or a zero year alone is enough
    assert not number_key(court_id=COURT, case_no_text="WA/0/2026").usable
    assert not number_key(court_id=COURT, case_no_text="WA/15/0").usable
    assert not number_key(court_id=COURT, case_type_id=WA, reg_no=15, reg_year=0).usable
    assert not number_key(court_id=COURT, case_type_id=WA, reg_no=-1, reg_year=2026).usable
    # a given positive number does not rescue a zero printed one, nor the reverse
    assert not number_key(
        court_id=COURT, case_no_text="WA/0/0", case_type_id=WA, reg_no=15, reg_year=2026
    ).usable
    assert not number_key(
        court_id=COURT, case_no_text="WA/15/2026", case_type_id=WA, reg_no=0, reg_year=0
    ).usable
    # a registered number is still a key
    assert number_key(court_id=COURT, case_no_text="WA/15/2026", case_type_id=WA).usable
