"""Pure parts of the Cause list screen's service (design `portal-causelist`): the court order and the value sets."""

from __future__ import annotations

from aslms.domain.causelists import ListType
from aslms.services import causelist_view as cv


def test_court_sort_key():
    courts = ["111", None, "10", "2", "CJ", " 3 ", "", "2A"]
    ordered = sorted(courts, key=cv.court_sort_key)
    assert ordered == ["2", "2A", " 3 ", "10", "111", "", "CJ", None]
    assert cv.court_sort_key(" 10 ") == cv.court_sort_key("10")


def test_only_and_list_type_values():
    assert cv.ONLY_VALUES == ("recommended", "mine", "claimable", "unclaimed", "claimed", "visible")
    assert cv.ORDER_OF_LIST_TYPE == ("daily", "supplementary", "lawazima", "vacation", "other")
    assert set(cv.LIST_TYPES) == {t.value for t in ListType}
    assert [cv.list_type_rank(t) for t in ("daily", "other", "unknown")] == [0, 4, 5]
    assert cv.DAY_STATES == ("held", "loading", "no_list", "failed", "not_loaded")
