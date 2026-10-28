"""`next_hearing.words` (design `next-date-direct`, Services): one plain line of the case's one next hearing for the
Case Assistant and the alert texts, the owner's form for an around date."""

from __future__ import annotations

from datetime import date

from aslms.services import next_hearing as nh

ORDER = {"id": "o", "order_no": "4", "order_date": date(2026, 2, 18), "document_id": None}


def test_words_for_each_basis():
    assert nh.words(None) == "No next hearing known"
    assert nh.words({}) == "No next hearing known"
    around = {"date": date(2026, 3, 11), "basis": "around", "basis_words": "after 3 weeks", "order": ORDER}
    assert nh.words(around) == "Around 11 Mar 2026 (after 3 weeks, order of 18 Feb 2026)"  # the owner's form
    assert nh.words({**around, "basis_words": None}) == "Around 11 Mar 2026 (order of 18 Feb 2026)"
    assert (
        nh.words({"date": date(2026, 11, 25), "basis": "court", "order": None})
        == "25 Nov 2026 (court's records)"
    )
    exact = {
        "date": date(2026, 11, 20),
        "basis": "order",
        "order": {**ORDER, "order_date": date(2026, 10, 12)},
    }
    assert nh.words(exact) == "20 Nov 2026 (order of 12 Oct 2026)"
    assert nh.words({**exact, "basis": "confirmed"}) == "20 Nov 2026 (order of 12 Oct 2026)"
    assert nh.words({"date": date(2026, 12, 1), "basis": "manual", "order": None}) == (
        "01 Dec 2026 (entered by hand; the court has given no date)"
    )
    # the API's ISO strings read the same
    assert nh.words({"date": "2026-03-11", "basis": "around", "order": {"order_date": "2026-02-18"}}) == (
        "Around 11 Mar 2026 (order of 18 Feb 2026)"
    )


def test_reading_basis():
    assert nh.reading_basis("order_specific", "not_needed", "list_on_date").value == "order"
    assert nh.reading_basis("order_specific", "not_needed", "qualified_date").value == "around"
    assert nh.reading_basis("order_specific", "pending", "returnable_date").value == "around"
    assert nh.reading_basis("order_period", "not_needed", "list_after_period").value == "around"
    assert nh.reading_basis("order_period", "confirmed", "list_after_period").value == "confirmed"
    assert nh.reading_basis("order_specific", "not_needed", None).value == "order"
    assert nh.reading_basis("order_period", "not_needed", None).value == "around"
