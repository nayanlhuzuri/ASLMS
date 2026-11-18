"""State Insights, the static guards (design `state-insights`, "Tests", unit): the export field registry is the owner's
list, the seed lists equal the lists frozen in migration 0039, the Insights modules never read internal records, the
three functions have their defaults, and the filters' words and dates are labelled on the server."""

from __future__ import annotations

import importlib.util
import re
from datetime import date
from pathlib import Path

from aslms.domain.reference import Permission, Role
from aslms.services import access, insights_export, insights_groups
from aslms.services import insights_filters as F
from aslms.services.access_seed import DEFAULT_MATRIX, PERMISSION_GROUPS, PERMISSION_LABELS

BACKEND = Path(__file__).resolve().parents[2]
MIGRATION = BACKEND / "migrations" / "versions" / "0039_state_insights.py"
INSIGHTS_MODULES = [
    BACKEND / "aslms" / "services" / name
    for name in (
        "insights.py",
        "insights_export.py",
        "insights_facts.py",
        "insights_filters.py",
        "insights_groups.py",
        "insights_rules.py",
        "insights_scope.py",
    )
] + [BACKEND / "aslms" / "api" / "routers" / "insights.py", BACKEND / "aslms" / "cli" / "insights.py"]


def _migration():
    spec = importlib.util.spec_from_file_location("m0039", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_export_fields_registry_owner_list():
    numbers = [f.number for f in insights_export.FIELDS]
    assert numbers == list(range(1, 34))
    defaults = {f.number for f in insights_export.FIELDS if f.default}
    assert defaults == {1, 2, 4, 6, 8, 9, 10, 11, 12, 13, 16, 18, 19, 23, 27, 28, 29, 30}
    assert [f.key for f in insights_export.FIELDS if f.excel_only] == ["link"]
    assert {f.group for f in insights_export.FIELDS} == {g for g, _ in insights_export.GROUPS}
    reg = insights_export.registry()
    assert len(reg) == 34 and reg[-1]["key"] == "applications_pending" and reg[-1]["number"] is None


def test_export_fields_parse():
    f = F.InsightFilters()
    keys = [fd.key for fd in insights_export.parse_fields(None, "xlsx", f)]
    assert keys[:-1] == list(insights_export.DEFAULT_KEYS) and keys[-1] == "applications_pending"
    assert [
        fd.key for fd in insights_export.parse_fields("link,cnr", "pdf", F.InsightFilters(include_ia=True))
    ] == ["cnr"]
    assert [
        fd.key for fd in insights_export.parse_fields("link,cnr", "xlsx", F.InsightFilters(include_ia=True))
    ] == [
        "cnr",
        "link",
    ]
    try:
        insights_export.parse_fields("cnr,notes", "xlsx", f)
    except insights_export.BadField as exc:
        assert exc.key == "notes" and exc.code == "bad_field"
    else:  # pragma: no cover
        raise AssertionError("an unknown field is refused")


def test_pending_for_and_hearing_words():
    assert insights_export.pending_for(date(2024, 2, 10), date(2026, 5, 9)) == "2 Years 2 Months"
    assert insights_export.pending_for(date(2026, 5, 1), date(2026, 5, 9)) == "0 Months"
    assert insights_export.pending_for(None, date(2026, 5, 9)) == ""
    today = date(2026, 11, 14)
    assert insights_export.hearing_words(today, "pending", today) == "14-11-2026 (Today)"
    assert insights_export.hearing_words(date(2026, 11, 19), "pending", today) == "19-11-2026 (In 5 Days)"
    assert insights_export.hearing_words(date(2026, 11, 1), "pending", today) == "01-11-2026 (Date Passed)"
    assert insights_export.hearing_words(None, "pending", today) == "No Date Yet"
    assert insights_export.hearing_words(today, "disposed", today) == "Disposed"


def test_seed_lists_equal_migration_lists():
    m = _migration()
    assert insights_groups.SEED_SUBJECT_GROUPS == m.SUBJECT_GROUPS
    assert insights_groups.SEED_FAMILY_GROUPS == m.FAMILY_GROUPS
    assert insights_groups.SEED_CATEGORIES == m.CATEGORIES
    assert insights_groups.SEED_CASE_TYPES == m.CASE_TYPES
    assert insights_groups.RESERVED_GROUPS == m.RESERVED
    assert len(m.SUBJECT_GROUPS) == 15 and len(m.FAMILY_GROUPS) == 20
    assert len(m.CATEGORIES) == 235 and len({c for c, _, _ in m.CATEGORIES}) == 235
    assert len(m.CASE_TYPES) == 57
    subject_codes = {c for c, _ in m.SUBJECT_GROUPS}
    family_codes = {c for c, _ in m.FAMILY_GROUPS}
    assert {g for _, _, g in m.CATEGORIES} <= subject_codes
    assert {g for _, g in m.CASE_TYPES} <= family_codes
    assert set(m.RESERVED) == {
        ("family", "contempt"),
        ("family", "ia"),
        ("family", "other"),
        ("subject", "contempt"),
    }
    # decision 5: the interlocutory applications are the types 218, 220 and 221; contempt 142, 229, 174 and 228
    assert sorted(c for c, g in m.CASE_TYPES if g == "ia") == [218, 220, 221]
    assert sorted(c for c, g in m.CASE_TYPES if g == "contempt") == [142, 174, 228, 229]


FORBIDDEN = (
    (re.compile(r"\bcase_notes\b|\bCaseNote\b"), "case_notes"),
    (re.compile(r"\bcase_note_drafts\b|\bCaseNoteDraft\b"), "case_note_drafts"),
    (re.compile(r"custody_history\.remark|CustodyHistory\.remark|\.remark\b"), "custody remark"),
    (re.compile(r"documents\.description|Document\.description"), "document description"),
)


def test_no_internal_records_in_insights_modules():
    """Decision 20: no note, draft, custody remark or document description; `document_text` only in the one order-text
    reader of the fact builder (`_order_texts` and its statements)."""
    offenders = []
    for path in INSIGHTS_MODULES:
        text_ = path.read_text("utf-8")
        for rx, name in FORBIDDEN:
            if rx.search(text_):
                offenders.append(f"{path.name}: {name}")
        if "document_text" in text_ or "DocumentText" in text_:
            if path.name != "insights_facts.py":
                offenders.append(f"{path.name}: document_text")
    assert offenders == []
    facts = (BACKEND / "aslms" / "services" / "insights_facts.py").read_text("utf-8")
    allowed = {"TITLE_SQL", "EARLIEST_SQL"}
    for name in re.findall(r"^([A-Z_]+_SQL) = ", facts, re.M):
        block = facts.split(f"{name} = ", 1)[1].split('"""', 2)[1]
        if "document_text" in block:
            assert name in allowed, name


def test_permissions_seed_defaults():
    holders = {
        p: {role for role, perms in DEFAULT_MATRIX.items() if p in perms}
        for p in (Permission.INSIGHTS_STATE, Permission.INSIGHTS_DEPARTMENT, Permission.ADMIN_INSIGHTS_GROUPS)
    }
    assert holders[Permission.INSIGHTS_STATE] == {Role.STATE_OVERSIGHT}
    assert holders[Permission.INSIGHTS_DEPARTMENT] == {Role.DEPT_HEAD, Role.DEPT_ADMIN}
    assert holders[Permission.ADMIN_INSIGHTS_GROUPS] == set()
    assert Permission.ADMIN_INSIGHTS_GROUPS in access.RESERVED_FUNCTIONS
    for p in (Permission.INSIGHTS_STATE, Permission.INSIGHTS_DEPARTMENT, Permission.ADMIN_INSIGHTS_GROUPS):
        label, description = PERMISSION_LABELS[p]
        assert label and len(description) <= 120
    reports = next(members for code, _, members in PERMISSION_GROUPS if code == "reports")
    assert reports.index(Permission.INSIGHTS_STATE) == reports.index(Permission.DASHBOARD_STATE) + 1
    assert list(Permission)[-3:] == [
        Permission.INSIGHTS_STATE,
        Permission.INSIGHTS_DEPARTMENT,
        Permission.ADMIN_INSIGHTS_GROUPS,
    ]


def test_date_chip_words():
    f = F.InsightFilters(date_of="registration", from_=date(2026, 1, 1), to=date(2026, 11, 13))
    assert F.date_words(f) == "Registered: 1 Jan 2026 to 13 Nov 2026"
    assert (
        F.date_words(F.InsightFilters(date_of="disposal", from_=date(2026, 1, 1)))
        == "Disposed: From 1 Jan 2026"
    )
    assert (
        F.date_words(F.InsightFilters(date_of="next_hearing", to=date(2026, 2, 3)))
        == "Next Hearing: Up to 3 Feb 2026"
    )
    assert F.date_words(F.InsightFilters()) is None
    assert F.InsightFilters(kind="writ", from_=date(2026, 1, 2)).as_params() == {
        "status": "pending",
        "state_only": True,
        "include_ia": False,
        "kind": "writ",
        "from": "2026-01-02",
    }
