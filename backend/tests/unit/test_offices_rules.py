"""The office rules without a database: code normalisation, the placement table of design decision 3, the
tier derived from the path."""

from __future__ import annotations

import pytest

from aslms.domain.org import Office
from aslms.domain.reference import OfficeKind as K
from aslms.services.offices import (
    DELEGABLE_KINDS,
    PLACEMENT,
    OfficeError,
    child_path,
    depth_of,
    normalise_code,
    normalise_designation_code,
    tier_of,
)


@pytest.mark.parametrize(
    ("raw", "code"), [("edu", "EDU"), (" EDU-DSE ", "EDU-DSE"), ("a1", "A1"), ("X" * 40, "X" * 40)]
)
def test_codes_are_upper_cased_and_trimmed(raw, code):
    assert normalise_code(raw) == code


@pytest.mark.parametrize("raw", ["", "E", "X" * 41, "EDU DSE", "EDU_DSE", "-EDU", "édu", "edu/dse", None])
def test_bad_codes_are_refused(raw):
    with pytest.raises(OfficeError):
        normalise_code(raw)


def test_designation_codes_allow_underscores_as_the_seed_does():
    assert normalise_designation_code("cs_sec") == "CS_SEC"
    with pytest.raises(OfficeError):
        normalise_designation_code("CS SEC")


EXPECTED = {(K.STATE, parent): False for parent in K} | {
    (K.DEPARTMENT, K.STATE): True,
    (K.CENTRAL, K.STATE): True,
    (K.ADVOCATE_GENERAL, K.STATE): True,
    (K.DIRECTORATE, K.DEPARTMENT): True,
    (K.UNIT, K.DEPARTMENT): True,
    (K.UNIT, K.DIRECTORATE): True,
    (K.UNIT, K.CENTRAL): True,
    (K.UNIT, K.ADVOCATE_GENERAL): True,
}


@pytest.mark.parametrize("child", list(K))
@pytest.mark.parametrize("parent", list(K))
def test_placement_table_matches_decision_3(child, parent):
    assert (parent in PLACEMENT[child]) is EXPECTED.get((child, parent), False)


def test_state_is_never_creatable_and_only_two_kinds_are_delegable():
    assert PLACEMENT[K.STATE] == frozenset()
    assert set(PLACEMENT) == set(K)
    assert DELEGABLE_KINDS == {K.DIRECTORATE, K.UNIT}


def test_tier_and_depth_from_a_synthetic_path():
    goa = Office(code="GOA", name="Government of Assam", kind=K.STATE, path="GOA")
    edu = Office(code="EDU", name="Education", kind=K.DEPARTMENT, path="GOA/EDU")
    dse = Office(code="EDU-DSE", name="DSE", kind=K.DIRECTORATE, path="GOA/EDU/EDU-DSE")
    unit = Office(code="EDU-DSE-LEGAL", name="Legal cell", kind=K.UNIT, path="GOA/EDU/EDU-DSE/EDU-DSE-LEGAL")
    assert [tier_of(o) for o in (goa, edu, dse, unit)] == [
        "state",
        "department",
        "directorate",
        "directorate",
    ]
    assert [depth_of(o) for o in (goa, edu, dse, unit)] == [0, 1, 2, 3]
    assert child_path(edu, "EDU-DSE") == "GOA/EDU/EDU-DSE"
    deep = Office(code="X", name="x", kind=K.UNIT, path="GOA/" + "A" * 390)
    with pytest.raises(OfficeError):
        child_path(deep, "TOO-DEEP-CODE")
