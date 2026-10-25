"""`PERMISSION_GROUPS` (design case-workspace-admin, decisions 21 and 26): every active function is in exactly one group,
no retired or unknown code is in any group, `permission_group` gives the group and the 1-based place the API returns,
and every active function has a label and a one-line description of at most 120 characters. The API side is in
tests/db/test_access_defaults_overview.py."""

from __future__ import annotations

from collections import Counter

from aslms.domain.reference import RETIRED_PERMISSIONS, Permission
from aslms.services.access import ACTIVE_FUNCTIONS
from aslms.services.access_seed import PERMISSION_GROUPS, PERMISSION_LABELS, permission_group

EXPECTED_SIZES = {
    "People and access": 11,
    "Cases and ownership": 12,
    "Case work": 8,
    "Documents": 3,
    "Alerts": 2,
    "Reports": 4,
    "Administration": 11,
}


def test_every_active_function_is_in_exactly_one_group():
    counts = Counter(p for _, _, members in PERMISSION_GROUPS for p in members)
    assert set(counts) == set(ACTIVE_FUNCTIONS)
    assert all(n == 1 for n in counts.values()), [p for p, n in counts.items() if n > 1]
    assert len(ACTIVE_FUNCTIONS) == 51


def test_no_retired_or_unknown_code_in_a_group():
    for _, _, members in PERMISSION_GROUPS:
        for p in members:
            assert isinstance(p, Permission)
            assert p not in RETIRED_PERMISSIONS


def test_groups_in_order_with_their_sizes():
    assert [(label, len(members)) for _, label, members in PERMISSION_GROUPS] == list(EXPECTED_SIZES.items())
    codes = [code for code, _, _ in PERMISSION_GROUPS]
    assert len(codes) == len(set(codes))


def test_permission_group_gives_the_place_in_the_group():
    for code, label, members in PERMISSION_GROUPS:
        for i, p in enumerate(members, start=1):
            assert permission_group(p) == (code, label, i)
    for p in RETIRED_PERMISSIONS:
        assert permission_group(p) is None


def test_every_active_function_has_a_one_line_label_and_description():
    for p in ACTIVE_FUNCTIONS:
        label, description = PERMISSION_LABELS[p]
        assert label.strip() and "\n" not in label, p
        assert description.strip() and "\n" not in description, p
        assert len(description) <= 120, (p, len(description))
