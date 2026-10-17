"""The two court-search kinds of design `search-court-advocate-filing` (decisions 4-6): the request union accepts
advocate and filing bodies and refuses the shapes the gateway would refuse or that could alter its `k=v|k=v`
input (422 before any call)."""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from aslms.api.schemas import CourtSearchAdvocateIn, CourtSearchFilingIn, CourtSearchIn

ADAPTER = TypeAdapter(CourtSearchIn)


def test_advocate_and_filing_bodies_are_accepted() -> None:
    adv = ADAPTER.validate_python({"kind": "advocate", "name": "MR. P J SAIKIA", "reg_year": 2025})
    assert isinstance(adv, CourtSearchAdvocateIn) and adv.pend_disp == "P"
    assert ADAPTER.validate_python(
        {"kind": "advocate", "name": "A" * 99, "reg_year": 2025, "pend_disp": "both"}
    )
    fil = ADAPTER.validate_python({"kind": "filing", "case_type": "WP(C)", "fil_no": 6780, "fil_year": 2025})
    assert isinstance(fil, CourtSearchFilingIn) and fil.fil_no == 6780
    assert ADAPTER.validate_python(
        {"kind": "filing", "case_type": "111", "fil_no": 9_999_999, "fil_year": 2025}
    )


@pytest.mark.parametrize(
    "body",
    [
        {"kind": "advocate", "name": "PJ", "reg_year": 2025},
        {"kind": "advocate", "name": "A" * 100, "reg_year": 2025},
        {"kind": "advocate", "name": "SAIKIA|reg_year=1999", "reg_year": 2025},
        {"kind": "advocate", "name": "SAIKIA=1", "reg_year": 2025},
        {"kind": "advocate", "name": "SAIKIA"},
        {"kind": "advocate", "name": "SAIKIA", "reg_year": 2025, "pend_disp": "X"},
        {"kind": "filing", "case_type": "WP(C)", "fil_no": 0, "fil_year": 2025},
        {"kind": "filing", "case_type": "WP(C)", "fil_no": 10_000_000, "fil_year": 2025},
        {"kind": "filing", "fil_no": 6780, "fil_year": 2025},
        {"kind": "filing", "case_type": "", "fil_no": 6780, "fil_year": 2025},
        {"kind": "filing", "case_type": "WP(C)", "fil_no": 6780, "fil_year": 1900},
        {"kind": "act", "name": "ARMS ACT"},
    ],
)
def test_bad_bodies_are_refused(body: dict) -> None:
    with pytest.raises(ValidationError):
        ADAPTER.validate_python(body)
