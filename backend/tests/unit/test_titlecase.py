"""The Title Case helper (design portal-ui-polish-2, decision 2): the same pinned examples as
`frontend/src/lib/titleCase.test.ts`."""

from __future__ import annotations

import pytest

from aslms.core.titlecase import ACRONYMS, SMALL_WORDS, is_title_case, title_case

PINNED = [
    # the mockup's Before and After table
    ("Case inbox", "Case Inbox"),
    ("Sent by me", "Sent by Me"),
    ("Send case", "Send Case"),
    ("user types", "User Types"),
    ("Napix call log", "NAPIX Call Log"),
    # the note's own examples
    ("Working on", "Working On"),
    ("Search the court", "Search the Court"),
    ("Include logins without an active office", "Include Logins Without an Active Office"),
    ("Court search / discovery", "Court Search / Discovery"),
]


@pytest.mark.parametrize(("before", "after"), PINNED)
def test_pinned_examples(before: str, after: str) -> None:
    assert title_case(before) == after
    assert is_title_case(after)
    assert not is_title_case(before)


def test_small_words_lower_in_the_middle_capital_first_and_last() -> None:
    assert title_case("the case of the day") == "The Case of the Day"
    assert title_case("what it is for") == "What It Is For"
    assert title_case("Sign In To") == "Sign in To"
    assert title_case("A Case") == "A Case"
    for word in ("a", "an", "the", "and", "or", "of", "by", "to", "in", "on", "for", "at", "with"):
        assert word in SMALL_WORDS


def test_from_and_without_are_capitalised() -> None:
    assert title_case("changed from default") == "Changed From Default"
    assert title_case("cases without owner") == "Cases Without Owner"


def test_acronyms_stay_in_capitals() -> None:
    assert title_case("cnr and pdf") == "CNR and PDF"
    assert title_case("court apis") == "Court APIs"
    assert title_case("Court APIs") == "Court APIs"
    assert title_case("otp sent by sms") == "OTP Sent by SMS"
    assert title_case("aslms services") == "ASLMS Services"
    assert title_case("napix json url") == "NAPIX JSON URL"
    assert title_case("ist ip id csv ai njdg") == "IST IP ID CSV AI NJDG"
    assert "cnr" in ACRONYMS


def test_hyphenated_words_capitalise_only_the_first_part() -> None:
    assert title_case("sign-in off") == "Sign-in Off"
    assert title_case("e-mail") == "E-mail"
    assert title_case("read office-only notes") == "Read Office-only Notes"
    assert title_case("include sub-offices") == "Include Sub-offices"


def test_segments_split_at_slash_and_middle_dot() -> None:
    assert title_case("search / the court") == "Search / The Court"
    assert title_case("hearings · by date") == "Hearings · By Date"
    assert title_case("cause list: the day") == "Cause List: The Day"
    assert title_case("load — of the day") == "Load — Of the Day"


def test_words_with_digits_or_inner_capitals_are_left_alone() -> None:
    assert title_case("wp(c) 24h") == "Wp(c) 24h"
    assert title_case("the WP(C) list") == "The WP(C) List"
    assert title_case("use cURL and eCourts") == "Use cURL and eCourts"
    assert title_case("last 7days") == "Last 7days"


def test_punctuation_around_a_word_is_kept() -> None:
    assert title_case("(retired) the day") == "(Retired) the Day"
    assert title_case("what is it?") == "What Is It?"
    assert title_case('"quoted" word') == '"Quoted" Word'
    assert title_case("the  double space") == "The  Double Space"
    assert title_case("") == ""
