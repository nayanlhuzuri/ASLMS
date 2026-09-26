from __future__ import annotations

from datetime import date

from aslms.services.orders import read_next_date

ORDER_DATE = date(2026, 9, 1)


def test_specific_numeric_date() -> None:
    r = read_next_date("Heard learned counsel. List the matter again on 15.10.2026 for hearing.", ORDER_DATE)
    assert r.kind == "specific" and r.next_date == date(2026, 10, 15)


def test_specific_word_date_and_last_direction_wins() -> None:
    text = (
        "The matter was listed on 12.08.2026. Let the matter be listed for admission on 3rd November, 2026. "
        "Interim order to continue."
    )
    r = read_next_date(text, ORDER_DATE)
    assert r.next_date == date(2026, 11, 3)


def test_dates_on_or_before_the_order_are_ignored() -> None:
    r = read_next_date("The matter was fixed on 20.08.2026 but could not be taken up.", ORDER_DATE)
    assert r.kind == "none"


def test_period_is_flagged_for_review_with_days() -> None:
    r = read_next_date("Issue notice. List after two weeks.", ORDER_DATE)
    assert r.kind == "period" and r.next_date is None and r.period_days == 14
    r = read_next_date("Reply to be filed within 4 (four) weeks.", ORDER_DATE)
    assert r.period_days == 28


def test_no_direction() -> None:
    assert read_next_date("Writ petition is disposed of.", ORDER_DATE).kind == "none"
