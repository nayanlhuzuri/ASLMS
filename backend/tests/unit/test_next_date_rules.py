"""The next-date rules (design `next-date-extraction`, decision 3), over short excerpts of public court orders: each
listing form, the window, conflicting dates, returnable dates, periods with their counting, precedence, unclear and
none readings, no text, and a hostile text read in linear time."""

from __future__ import annotations

import time
from datetime import date

import pytest

from aslms.services import next_date_rules as r

OD = date(2026, 9, 8)  # the order date of most excerpts


def read(text: str, od: date = OD, **kw) -> r.Reading:
    return r.read_order_text(text, od, **kw)


@pytest.mark.parametrize(
    ("text", "od", "expected"),
    [
        (
            "42. List this matter on 14.10.2026 for further consideration. 43. Copies be sent.",
            OD,
            date(2026, 10, 14),
        ),
        (
            "List the matter again on 12.08.2026. 3. Meanwhile file affidavits.",
            date(2026, 6, 17),
            date(2026, 8, 12),
        ),
        ("The prayer is allowed; let this be listed again on 10.09.2026.", OD, date(2026, 9, 10)),
        (
            "Awaiting the report regarding service of notice on respondent No.11, this case is adjourned to 06.04.2026.",
            date(2026, 2, 25),
            date(2026, 4, 6),
        ),
        (
            "As prayed for on behalf of the appellant, re-notify on 12.11.2025.",
            date(2025, 10, 1),
            date(2025, 11, 12),
        ),
        (
            "Let these set of cases come up for consideration under the same heading on 04.08.2026.",
            date(2026, 6, 2),
            date(2026, 8, 4),
        ),
        ("By consent, this Court is fixing the matter on 30.09.2026 for hearing.", OD, date(2026, 9, 30)),
        ("List all these matters on 24th September, 2026.", OD, date(2026, 9, 24)),
        ("Let the matter be listed on 25th of september, 2026.", OD, date(2026, 9, 25)),
        ("List the matter on September 28, 2026.", OD, date(2026, 9, 28)),
        ("List the matter on 16-07-2025.", date(2025, 7, 1), date(2025, 7, 16)),
        ("List the matter on 08/04/2026.", date(2026, 3, 1), date(2026, 4, 8)),
        (
            "ORDER 31.08 .2026 As agreed to by the learned counsel for the parties matter be listed on 01 .10.2026.",
            date(2026, 8, 31),
            date(2026, 10, 1),
        ),
        ("List the matter on 14.10.26.", OD, date(2026, 10, 14)),
        ("Re-post on 15.07.2026.", date(2026, 6, 5), date(2026, 7, 15)),
    ],
)
def test_each_listing_form_gives_the_written_date(text, od, expected):
    out = read(text, od)
    assert (out.status, out.rule, out.date) == ("specific", "list_on_date", expected)
    # the text alone never makes a date firm (owner's decision of 17 Oct 2026, second): the service compares it with
    # the court's own date
    assert out.needs_review and out.confidence == 1.0
    assert out.phrase and len(out.phrase) <= r.PHRASE_MAX


def test_dates_outside_the_window_are_ignored():
    # the order's own date, an affidavit date, a date before the order, one more than 548 days ahead
    text = (
        "ORDER Date : 25.05.2026. Seen the affidavit dated 17.10.2025. The matter was listed on 20.05.2026. "
        "List the matter on 20.05.2026."
    )
    out = read(text, date(2026, 5, 25))
    assert out.status == "unclear" and out.rule == "no_countable_date"
    far = read("List the matter on 01.06.2028.", date(2026, 5, 25))
    assert far.status == "unclear"
    near = read("List the matter on 01.06.2027.", date(2026, 5, 25))
    assert near.status == "specific" and near.date == date(2027, 6, 1)
    assert read("List the matter on 01.06.2027.", date(2026, 5, 25), max_ahead_days=90).status == "unclear"


def test_conflicting_and_repeated_dates():
    two = read("List WP(C) 1/2026 on 12.10.2026. List WP(C) 2/2026 on 19.10.2026.")
    assert (two.status, two.rule, two.date) == ("unclear", "conflicting_dates", None)
    assert two.needs_review and "12.10.2026" in two.phrase
    same = read("List on 12.10.2026. Notice returnable on 12.10.2026. 4. List on 12.10.2026.")
    assert (same.status, same.date) == ("specific", date(2026, 10, 12))


def test_returnable_date_alone_needs_review():
    out = read(
        "The appeal is admitted. Issue notice upon the respondents by registered post within 3(three) days. "
        "Notice is returnable by 25.3.2015.",
        date(2015, 2, 11),
    )
    assert (out.status, out.rule, out.date) == ("specific", "returnable_date", date(2015, 3, 25))
    assert out.needs_review and out.confidence == 0.8


@pytest.mark.parametrize(
    ("text", "od", "expected"),
    [
        ("List this matter after four weeks.", date(2025, 11, 10), date(2025, 12, 8)),
        ("List the matter after two (2) weeks.", OD, date(2026, 9, 22)),
        ("List the matter after two weeks.", OD, date(2026, 9, 22)),
        ("Call for the trial court records. List after 4(four) weeks.", OD, date(2026, 10, 6)),
        ("List the matter after 2 [two] weeks.", OD, date(2026, 9, 22)),
        (
            "All the respondents are served; list the case after a week in the admission column.",
            OD,
            date(2026, 9, 15),
        ),
        ("List after 10 days.", OD, date(2026, 9, 18)),
        ("List the matter after a fortnight.", OD, date(2026, 9, 22)),
        ("The matter is adjourned for further 3 (three) weeks.", OD, date(2026, 9, 29)),
        ("List the matter after two months.", date(2025, 12, 31), date(2026, 2, 28)),
        ("List the matter after two months.", date(2027, 12, 31), date(2028, 2, 29)),
    ],
)
def test_periods_are_counted_from_the_order_date(text, od, expected):
    out = read(text, od)
    assert (out.status, out.rule, out.date) == ("period", "list_after_period", expected)
    assert out.needs_review and out.confidence == 0.6


def test_after_the_returnable_date():
    within = read(
        "Issue notice, returnable within four weeks. Steps be taken within a week. "
        "Accordingly, list this matter after the returnable date."
    )
    assert (within.status, within.rule, within.date) == (
        "period",
        "after_returnable_period",
        date(2026, 10, 6),
    )
    on = read("Issue notice returnable on 20.10.2026. Matter be listed after the returnable date.")
    assert (on.status, on.rule, on.date) == ("specific", "returnable_date", date(2026, 10, 20))
    bare = read("Steps within a week. Matter be listed after the returnable date.")
    assert (bare.status, bare.rule) == ("unclear", "no_countable_date")
    alone = read("Issue notice, returnable within 4 (four) weeks.")
    assert (alone.status, alone.rule, alone.date) == ("period", "returnable_period", date(2026, 10, 6))


def test_the_written_date_wins_over_a_period_but_is_confirmed():
    """The court's written date is the one suggested, but with a period in the order it is never firm (review of 17
    Oct 2026: a period is always confirmed)."""
    out = read(
        "Respondents to file affidavit within four weeks. List the matter after 2 weeks, i.e. on 25.09.2026."
    )
    assert (out.status, out.rule, out.date) == ("specific", "qualified_date", date(2026, 9, 25))
    assert out.needs_review
    out = read("List the matter after 2 (two) weeks, on 25.09.2026.")
    assert (out.status, out.rule, out.date) == ("specific", "qualified_date", date(2026, 9, 25))
    out = read("List the matter after 2 weeks. Let the connected case also be listed on 30.09.2026.")
    assert (out.status, out.rule, out.date) == ("specific", "qualified_date", date(2026, 9, 30))
    # even when the written date is the counted one
    out = read("List the matter after 2 weeks. Let the connected case also be listed on 22.09.2026.")
    assert (out.status, out.rule, out.needs_review) == ("specific", "qualified_date", True)
    out = read("List the matter on 25.09.2026, i.e. after 2 weeks.")
    assert (out.rule, out.needs_review) == ("qualified_date", True)


REVIEW_OD = date(2026, 10, 10)  # the review of 17 Oct 2026: its scenarios, read on an order of 10.10.2026


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # another person's act between the verb and the date: the period is the direction (+14 days, pending)
        (
            "List after two weeks, and the respondents to file their reply on 20.11.2026.",
            ("period", "list_after_period", date(2026, 10, 24)),
        ),
        (
            "List after 2 weeks, and the petitioner to appear on 20.11.2026.",
            ("period", "list_after_period", date(2026, 10, 24)),
        ),
        (
            "List the matter after vacation, with liberty to mention on 20.11.2026.",
            ("unclear", "no_countable_date", None),
        ),
        (
            "List the matter, and the petitioner to appear on 20.11.2026.",
            ("unclear", "no_countable_date", None),
        ),
        # an interim order's expiry, "subsequent to", "prior to": no plain listing date
        (
            "List the matter after 2 weeks and the interim order is extended up to 20.11.2026.",
            ("period", "list_after_period", date(2026, 10, 24)),
        ),
        (
            "List after 2 weeks with the interim order extended to 20.11.2026.",
            ("period", "list_after_period", date(2026, 10, 24)),
        ),
        ("List the matter subsequent to 20.11.2026.", ("specific", "qualified_date", date(2026, 11, 20))),
        ("List the matter prior to 20.11.2026.", ("unclear", "no_countable_date", None)),
        ("List the matter upto 20.11.2026.", ("unclear", "no_countable_date", None)),
        ("List the matter to 20.11.2026.", ("specific", "qualified_date", date(2026, 11, 20))),
        # another matter's date in the usual Gauhati High Court forms
        (
            "Await the decision in WA 5/2026 listed for 20.11.2026. List thereafter.",
            ("unclear", "no_countable_date", None),
        ),
        (
            "List the matter with WA 5/2026, which stands fixed on 20.11.2026.",
            ("unclear", "conflicting_dates", None),
        ),
        (
            "List this matter along with WP(C) 1234/2026 listed on 20.11.2026.",
            ("unclear", "conflicting_dates", None),
        ),
        (
            "List this matter along with WA 5/2026, which will come up on 20.11.2026.",
            ("unclear", "conflicting_dates", None),
        ),
        (
            "List this matter thereafter, as the connected writ appeal has been adjourned to 20.11.2026.",
            ("unclear", "conflicting_dates", None),
        ),
        (
            "List the matter along with the connected case fixed on 20.11.2026.",
            ("unclear", "conflicting_dates", None),
        ),
        (
            "List this matter with the connected matter listed on 20.11.2026.",
            ("unclear", "conflicting_dates", None),
        ),
        # still plain directions of this case
        (
            "List this matter along with WP(C) 1234/2026 on 20.11.2026.",
            ("specific", "list_on_date", date(2026, 11, 20)),
        ),
        (
            "Matter stands adjourned and list the matter again on 20.11.2026.",
            ("specific", "list_on_date", date(2026, 11, 20)),
        ),
        ("This case is adjourned to 20.11.2026.", ("specific", "list_on_date", date(2026, 11, 20))),
    ],
)
def test_the_words_between_the_verb_and_the_date_count(text, expected):
    """Review of 17 Oct 2026: a firm date needs only the matter listed between the verb and the date."""
    out = read(text, REVIEW_OD)
    assert (out.status, out.rule, out.date) == expected
    assert out.needs_review


def test_reported_dates_of_other_matters_are_not_directions():
    out = read(
        "The connected appeal is fixed on 17.10.2026 before the Division Bench. Interim order to continue."
    )
    assert out.status == "none"
    out = read("The case is posted on 13.10.2026 before the Trial Court. List the matter after vacation.")
    assert (out.status, out.rule) == ("unclear", "no_countable_date")
    out = read("List the matter after 2 weeks; the respondents shall file their affidavit by 12.10.2026.")
    assert (out.status, out.rule, out.date) == ("period", "list_after_period", date(2026, 9, 22))


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # "stands / stood" right before the verb reports another matter's date (third review of 17 Oct 2026)
        ("The connected appeal stands fixed on 20.11.2026.", ("none", None, None)),
        ("WA 5/2026 stands fixed on 20.11.2026.", ("none", None, None)),
        ("The connected writ appeal stood fixed on 20.11.2026.", ("none", None, None)),
        (
            "List this matter along with WA 5/2026 that stands fixed on 20.11.2026.",
            ("unclear", "conflicting_dates", None),
        ),
        # this matter's own "stands posted" is still its direction
        ("The matter stands posted on 20.11.2026.", ("specific", "list_on_date", date(2026, 11, 20))),
        ("This case stands fixed on 20.11.2026.", ("specific", "list_on_date", date(2026, 11, 20))),
    ],
)
def test_stands_or_stood_fixed_reports_another_matters_date(text, expected):
    out = read(text, OWNER_OD)
    assert (out.status, out.rule, out.date) == expected
    assert out.needs_review == (expected[0] != "none")


def test_no_control_characters_in_the_rules_source():
    """A literal backspace once stood where a regex word boundary was meant; ruff does not see it."""
    raw = open(r.__file__, "rb").read()
    assert not [b for b in raw if b < 32 and b not in (9, 10, 13)]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # the noun "list" and a filing deadline do not hide the order's real direction
        (
            "Let the petitioner file a list of documents by 20.10.2026. List after 3 weeks.",
            ("period", "list_after_period", date(2026, 10, 22)),
        ),
        (
            "The petitioner is allowed to come up with a fresh representation by 10.10.2026. List after 2 weeks.",
            ("period", "list_after_period", date(2026, 10, 15)),
        ),
        ("The time fixed for filing the affidavit-in-opposition ends on 20.10.2026.", ("none", None, None)),
        ("The time fixed for filing the affidavit-in-opposition is 20.10.2026.", ("none", None, None)),
        ("The petitioner may come up with a fresh representation by 10.10.2026.", ("none", None, None)),
        ("Let the parties exchange the list of dates on 12.10.2026.", ("none", None, None)),
        ("The parties shall file a list of witnesses on 12.10.2026.", ("none", None, None)),
        ("The matter appears in the cause list on 12.10.2026.", ("none", None, None)),
        ("The period fixed for compliance is extended up to 12.10.2026.", ("none", None, None)),
        ("Some time is fixed for filing reply on 12.10.2026.", ("none", None, None)),
        (
            "The matter is adjourned to enable the State to file its reply by 12.10.2026.",
            ("unclear", "no_countable_date", None),
        ),
        (
            "List after the respondents file their affidavit within 12.10.2026.",
            ("unclear", "no_countable_date", None),
        ),
        # "fix a date ... on or before": a deadline set for someone else (dev order of 10.06.2026)
        (
            "The Respondents shall fix a date for giving a personal hearing to the Petitioner on or before "
            "01.11.2026. Issue notice making it returnable on 07.11.2026.",
            ("specific", "returnable_date", date(2026, 11, 7)),
        ),
        (
            "It is submitted that the next date fixed for filing the amended plaint is 14.10.2026.",
            ("none", None, None),
        ),
        # still directions with the court's own written date
        (
            "At the request of the counsel, this list matter again on 18th of October, 2026.",
            ("specific", "list_on_date", date(2026, 10, 18)),
        ),
        ("Let the matter come up on 12.10.2026.", ("specific", "list_on_date", date(2026, 10, 12))),
        (
            "The matter shall be fixed for hearing on 12.10.2026.",
            ("specific", "list_on_date", date(2026, 10, 12)),
        ),
        (
            "Registry to list the matter before the Division Bench on 12.10.2026.",
            ("specific", "list_on_date", date(2026, 10, 12)),
        ),
        (
            "File a list of documents by 09.10.2026. List the matter on 20.10.2026.",
            ("specific", "list_on_date", date(2026, 10, 20)),
        ),
    ],
)
def test_nouns_and_deadlines_are_not_listing_dates(text, expected):
    out = read(text, date(2026, 10, 1))
    assert (out.status, out.rule, out.date) == expected
    assert out.needs_review == (expected[0] != "none")


OWNER_OD = date(
    2026, 10, 17
)  # the owner's decision of 17 Oct 2026: its examples, read on an order of that day


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("List the matter after 15.12.2026.", date(2026, 12, 15)),
        ("List on or after 20.11.2026.", date(2026, 11, 20)),
        ("List the matter from 20.11.2026 onwards.", date(2026, 11, 20)),
        ("List the matter in the week commencing 16.11.2026.", date(2026, 11, 16)),
        ("List the matter after the vacation, i.e. after 02.01.2027.", date(2027, 1, 2)),
        ("List the matter not before 20.11.2026.", date(2026, 11, 20)),
        ("List the matter on 20.11.2026 onwards.", date(2026, 11, 20)),
        ("List the matter on 20.11.2026 or thereafter.", date(2026, 11, 20)),
        ("Let the matter be listed in the week commencing from 16th November, 2026.", date(2026, 11, 16)),
        # any other word before the date is no plain direction either
        ("List tomorrow, i.e., 18.10.2026.", date(2026, 10, 18)),
        ("List the matter on Monday, 16.11.2026 or thereafter.", date(2026, 11, 16)),
        # "or any date thereafter" counts as "on or after" (owner's decision of 17 Oct 2026, second, point 4)
        ("List the matter on 20.11.2026 or any date thereafter.", date(2026, 11, 20)),
        ("List on 20.11.2026 or on any subsequent date.", date(2026, 11, 20)),
        ("List the matter on 20.11.2026, or on any other date thereafter.", date(2026, 11, 20)),
    ],
)
def test_a_not_before_date_needs_confirming(text, expected):
    """Point 2: a date after "after", "on or after", "from", "not before", "commencing", or before "onwards", is a
    suggested date (`order_specific`, 0.800, reviewed), never a firm listing date."""
    out = read(text, OWNER_OD)
    assert (out.status, out.rule, out.date) == ("specific", "qualified_date", expected)
    assert out.needs_review and out.confidence == 0.8


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # a period in the sentence still wins over another matter's date
        (
            "List after 3 weeks since the connected appeal before the Division Bench is fixed on 20.11.2026.",
            ("period", "list_after_period", date(2026, 11, 7)),
        ),
        # another matter's date, whichever verb is nearest
        (
            "List the matter thereafter, since the connected appeal before the Division Bench is fixed on "
            "20.11.2026.",
            ("unclear", "conflicting_dates", None),
        ),
        (
            "List this matter on 27.11.2026 as the writ appeal against the same order is fixed on 20.11.2026.",
            ("unclear", "conflicting_dates", None),
        ),
        (
            "List this matter on 20.11.2026 as the writ appeal against the same order is fixed on 20.11.2026.",
            ("unclear", "conflicting_dates", None),
        ),
        (
            "Let the matter be listed along with the connected appeal fixed on 20.11.2026.",
            ("unclear", "conflicting_dates", None),
        ),
        # two different dates in one direction
        (
            "List the matter on 20.11.2026 and, if not reached, on 27.11.2026.",
            ("unclear", "conflicting_dates", None),
        ),
        (
            "List the matter on 30.10.2026 and the respondents shall file their affidavit by 20.10.2026.",
            ("unclear", "conflicting_dates", None),
        ),
        # the conflict stops the reading whatever else matches
        (
            "List along with WA 5/2026 which is fixed on 20.11.2026. List on 20.11.2026.",
            ("unclear", "conflicting_dates", None),
        ),
        # a report in a sentence of its own does not disturb a plain direction
        (
            "The connected appeal is fixed on 17.11.2026 before the Division Bench. List this matter on "
            "20.11.2026.",
            ("specific", "list_on_date", date(2026, 11, 20)),
        ),
        # a reported date with no direction of its own asks for a date rather than reading none
        ("This matter is to be listed on 20.11.2026.", ("unclear", "no_countable_date", None)),
    ],
)
def test_another_matters_date_or_two_dates_read_unclear(text, expected):
    """Point 3."""
    out = read(text, OWNER_OD)
    assert (out.status, out.rule, out.date) == expected
    assert out.needs_review


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("List on 15.11.2026.", date(2026, 11, 15)),
        ("List the matter on 15.11.2026 for hearing.", date(2026, 11, 15)),
        ("Fix 20.11.2026 for hearing.", date(2026, 11, 20)),
        ("Put up on 20.11.2026.", date(2026, 11, 20)),
        ("Next date: 20.11.2026.", date(2026, 11, 20)),
        ("List the matter on the 20th November, 2026.", date(2026, 11, 20)),
        # a date on or before the order date in the sentence is no other listing date
        ("Heard on 15.10.2026. Order dated 17.10.2026, list the matter on 20.11.2026.", date(2026, 11, 20)),
        # forms seen on the dev orders: a weekday, only the matter listed, "listed again", a page header between
        ("List this matter for consideration on Friday, i.e., 20.11.2026.", date(2026, 11, 20)),
        ("Registry to list this matter again 20.11.2026.", date(2026, 11, 20)),
        ("Let this matter listed again on 20.11.2026.", date(2026, 11, 20)),
        ("Let these cases be listed again on Page No.# 14/14 20.11.2026.", date(2026, 11, 20)),
        (
            "The Registry shall list the matter before the said Bench, and the matter listed on 20.11.2026.",
            date(2026, 11, 20),
        ),
    ],
)
def test_only_plain_directions_are_firm(text, expected):
    """Point 4 of the first decision: a listing verb, `on` / `for` (or nothing) and one date, no qualifier, no other
    date reads `list_on_date`; since the second decision even that is only a suggestion until the court's own date
    agrees (`needs_review` here; `next_dates.read_order` decides)."""
    out = read(text, OWNER_OD)
    assert (out.status, out.rule, out.date) == ("specific", "list_on_date", expected)
    assert out.needs_review and out.confidence == 1.0


SECOND_OD = date(
    2026, 10, 10
)  # the owner's second decision of 17 Oct 2026 and the reviews: an order of 10.10.2026


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("The matter is adjourned by 2 weeks.", date(2026, 10, 24)),
        ("Adjourned by 10 days.", date(2026, 10, 20)),
        ("List the matter after 30 (thirty) days.", date(2026, 11, 9)),
        ("List after 3 (three weeks).", date(2026, 10, 31)),
        ("List the matter after twenty one days.", date(2026, 10, 31)),
        ("List the matter after thirty-five days.", date(2026, 11, 14)),
        ("List the matter after twenty (20) days.", date(2026, 10, 30)),
        ("List after fourteen (14) days.", date(2026, 10, 24)),
        ("List the matter on the expiry of four weeks.", date(2026, 11, 7)),
        ("List the matter after the expiry of 2 (two) weeks.", date(2026, 10, 24)),
        ("List the matter on completion of 3 weeks from today.", date(2026, 10, 31)),
        ("List the matter 2 weeks hence.", date(2026, 10, 24)),
        ("List this matter again three weeks thereafter.", date(2026, 10, 31)),
    ],
)
def test_more_period_wordings_are_counted_and_confirmed(text, expected):
    """Point 3 of the second decision: the period wordings the review found missed, counted from the order date and
    always sent for confirmation."""
    out = read(text, SECOND_OD)
    assert (out.status, out.rule, out.date) == ("period", "list_after_period", expected)
    assert out.needs_review and out.confidence == 0.6


def test_returnable_within_thirty_days():
    out = read("Issue notice, returnable within 30 (thirty) days.", SECOND_OD)
    assert (out.status, out.rule, out.date) == ("period", "returnable_period", date(2026, 11, 9))
    # the two spellings must still agree, in either bracket form
    assert read("List after 3 (four weeks).", SECOND_OD).status == "unclear"
    assert read("List after twenty one (12) days.", SECOND_OD).status == "unclear"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # another matter's date: "is slated / likely to be listed on", "the connected case stands fixed on"
        ("The connected writ appeal is slated to be listed on 20.11.2026.", ("unclear", "no_countable_date")),
        (
            "List this matter thereafter, as the connected writ appeal is likely to be listed on 20.11.2026.",
            ("unclear", "conflicting_dates"),
        ),
        (
            "List this matter thereafter, as the connected writ appeal is slated to be listed on 20.11.2026.",
            ("unclear", "conflicting_dates"),
        ),
        ("The connected writ appeal is likely to come up on 20.11.2026.", ("unclear", "no_countable_date")),
        ("The connected case stands fixed on 20.11.2026.", ("none", None)),
        ("The other matters stood fixed on 20.11.2026.", ("none", None)),
        (
            "List this matter thereafter as the connected case stands fixed on 20.11.2026.",
            ("unclear", "conflicting_dates"),
        ),
        # negations: a listing the court does not direct
        ("The matter shall not be listed on 20.11.2026.", ("unclear", "no_countable_date")),
        ("The matter need not be listed on 20.11.2026.", ("unclear", "no_countable_date")),
        # a counsel's prayer the court has not granted in the sentence
        (
            "Learned counsel for the petitioner prays that the matter be listed on 20.11.2026.",
            ("unclear", "no_countable_date"),
        ),
        (
            "Mr. A, learned counsel for the respondents, submits that the matter may be listed on 20.11.2026.",
            ("unclear", "no_countable_date"),
        ),
    ],
)
def test_review_examples_never_give_this_cases_date(text, expected):
    """The reviews of 17 Oct 2026: sentences that carry another matter's date, a negation or a prayer give no date of
    this case (and since the second decision no date is firm on the text alone anyway)."""
    out = read(text, SECOND_OD)
    assert (out.status, out.rule, out.date) == (*expected, None)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # the sentence no longer splits after "No." / "Nos."
        ("List this matter along with WP(C) No. 1234/2026 on 20.11.2026.", date(2026, 11, 20)),
        ("List this matter along with WP(C) Nos. 1234/2026 and 12/2026 on 20.11.2026.", date(2026, 11, 20)),
        # a granted prayer, "as prayed for" and "at the request of" leave the court's direction
        (
            "Learned counsel prays for time, which is allowed, and list the matter on 20.11.2026.",
            date(2026, 11, 20),
        ),
        ("As prayed for, list the matter on 20.11.2026.", date(2026, 11, 20)),
        # a negation in an earlier sentence does not touch this one
        ("The matter could not be taken up today. List on 20.11.2026.", date(2026, 11, 20)),
    ],
)
def test_review_examples_that_keep_the_written_date(text, expected):
    out = read(text, SECOND_OD)
    assert (out.status, out.rule, out.date) == ("specific", "list_on_date", expected)
    assert out.needs_review  # a suggestion until the court's own date agrees


@pytest.mark.parametrize(
    "text",
    [
        "Put up after the vacation.",
        "Put up again before this Bench.",
        "Next date: to be fixed by the Registry.",
        "List the matter from the first week of the next month.",
        "List not earlier than the reopening of the Court.",
    ],
)
def test_a_direction_the_patterns_miss_is_unclear_not_none(text):
    """Point 4: a clear direction without a readable date is an *enter* item."""
    out = read(text, OWNER_OD)
    assert (out.status, out.rule, out.date) == ("unclear", "no_countable_date", None)


@pytest.mark.parametrize(
    "text",
    [
        "On the prayer made by the parties, list the matter after winter vacation.",
        "Let this matter be listed in the 3rd week of August, 2026, on a date to be fixed by the Registry.",
        "List the matter after service of notice.",
        "List the matter accordingly.",
    ],
)
def test_directions_without_a_countable_date_are_unclear(text):
    out = read(text, date(2026, 6, 1))
    assert (out.status, out.rule, out.date) == ("unclear", "no_countable_date", None)
    assert out.needs_review


@pytest.mark.parametrize(
    "text",
    [
        "The appeal is adjourned sine die.",
        "Since the LCR has already been received, list the matter for hearing in due course.",
        "List these matters before any other bench without me.",
        "The Registry to verify the matter and thereafter, to list the case before the appropriate Bench.",
        "The accused shall be released on bail. The bail application stands disposed of.",
        "Passed over for the day.",
    ],
)
def test_no_date_by_design_or_no_direction_is_none(text):
    out = read(text)
    assert (out.status, out.date) == ("none", None)
    assert not out.needs_review


@pytest.mark.parametrize("text", [None, "", "   \n\f  "])
def test_no_text(text):
    out = read(text)
    assert out.status == "no_text" and out.needs_review


def test_helpers():
    assert r.parse_dates("listed on 31.08 .2026 and 1st October, 2026 or 31.02.2026") == [
        date(2026, 8, 31),
        date(2026, 10, 1),
    ]
    assert r.count_period(date(2026, 1, 31), 1, "month") == date(2026, 2, 28)
    assert r.count_period(date(2026, 1, 10), 2, "fortnights") == date(2026, 2, 7)
    assert r.count_period(date(2026, 1, 10), 3, "days") == date(2026, 1, 13)
    assert r.count_period(date(2026, 11, 30), 3, "months") == date(2027, 2, 28)
    with pytest.raises(ValueError):
        r.count_period(date(2026, 1, 1), 1, "years")
    assert r.WORD_NUMBERS["twelve"] == 12
    # a period whose two spellings disagree is not counted
    assert read("List the matter after 2 (three) weeks.").status == "unclear"


def test_the_phrase_is_capped_and_long_text_is_read_from_its_end():
    long_sentence = "List the matter on 14.10.2026 " + "with the connected cases " * 40 + "."
    out = read(long_sentence)
    assert out.status == "specific" and len(out.phrase) <= r.PHRASE_MAX
    text = "Recorded. " * 60_000 + "List the matter on 14.10.2026."
    assert len(text) > r.MAX_TEXT
    assert read(text).date == date(2026, 10, 14)


def test_hostile_text_reads_quickly():
    chunks = [
        "list list listed fix on " * 4_000,
        "after after for further " * 4_000,
        "1.1.1.1.1.1.1.1 " * 4_000,
        "returnable on returnable within " * 3_000,
        "a" * 100_000,
        "list the matter after (((((( [[[[ " * 3_000,
        "prays that the matter be listed on allowed not " * 2_000,
        "after twenty-one (twenty one (thirty " * 2_000,
    ]
    text = " ".join(chunks)[: r.MAX_TEXT]
    assert len(text) >= 450_000
    t0 = time.perf_counter()
    out = read(text)
    assert time.perf_counter() - t0 < 1.0
    assert out.status in {"specific", "period", "unclear", "none"}
