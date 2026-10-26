"""Case reference numbers carry the court's code (design `case-ref-court-prefix`, decisions 17, 18 and 24): an old
`GOA` case number maps to the `GHC` number with the same year and number, every other value is left alone, the shared
filter reads an old number as the current one, and no code outside the allow-list names a `GOA` case number."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from aslms.services.case_filters import parse, parse_query
from aslms.services.cases import ref_no_from_url
from aslms.services.refno import LEGACY_CASE_PREFIX, current_case_ref_no

ROOT = Path(__file__).resolve().parents[3]
OLD = "ASLMS/GOA/CASE/2026/054584"
NEW = "ASLMS/GHC/CASE/2026/054584"


def test_current_case_ref_no_maps_goa_to_ghc_with_same_year_and_number():
    assert LEGACY_CASE_PREFIX == ("GOA", "GHC")
    assert current_case_ref_no(OLD) == NEW
    assert current_case_ref_no("ASLMS/GOA/CASE/2025/000001") == "ASLMS/GHC/CASE/2025/000001"
    # the dash form of a mail link, after the URL reading
    assert current_case_ref_no(ref_no_from_url("ASLMS-GOA-CASE-2026-054584")) == NEW
    assert current_case_ref_no(ref_no_from_url("aslms-goa-case-2026-054584")) == NEW


@pytest.mark.parametrize(
    "value",
    [
        NEW,
        "ASLMS/EDU/NOTE/2026/000042",
        "ASLMS/EDU-DSE/DOC/2026/000007",
        "ASLMS/GOA/ALR/2026/000003",  # alerts stay on GOA and are not case numbers
        "ASLMS/GOA/NOTE/2026/000001",
        "ASLMS/GOA/CASE/2026/12345",  # not the format: left alone
        "WP(C)/4189/2016",
        "GAHC010277142024",
        "",
    ],
)
def test_current_case_ref_no_leaves_other_numbers_alone(value):
    assert current_case_ref_no(value) == value


def test_case_filters_ref_no_kind_uses_current_number():
    for q in (OLD, "ASLMS-GOA-CASE-2026-054584", NEW, "ASLMS-GHC-CASE-2026-054584"):
        parsed = parse_query(q)
        assert (parsed.kind, parsed.ref_no) == ("ref_no", NEW), q
    assert parse(q=OLD).parsed.ref_no == NEW
    # a note number keeps its own number
    assert parse_query("ASLMS/EDU/NOTE/2026/000042").ref_no == "ASLMS/EDU/NOTE/2026/000042"


# decision 24: the old prefix lives only in the alias constant, the renumbering migration and the alias tests
GOA_CASE_RE = re.compile(r"GOA(\\?/|-|%2F)CASE", re.IGNORECASE)  # slash, dash, URL-encoded, regex-escaped
SCANNED = ("backend/aslms", "frontend/src", "frontend/e2e")
SUFFIXES = {".py", ".ts", ".tsx", ".js", ".mjs", ".json", ".css", ".md"}
ALLOWED = {
    "backend/aslms/services/refno.py",
    "frontend/src/lib/refs.test.ts",
    "frontend/src/components/case/caseRefRedirect.test.tsx",
    "frontend/e2e/fixtures/legacy.ts",
}


def test_no_goa_case_numbers_in_code():
    found = []
    for top in SCANNED:
        base = ROOT / top
        if not base.exists():
            continue
        for path in base.rglob("*"):
            rel = path.relative_to(ROOT).as_posix()
            if (
                not path.is_file()
                or path.suffix not in SUFFIXES
                or "node_modules" in rel
                or "__pycache__" in rel
            ):
                continue
            if rel in ALLOWED:
                continue
            if GOA_CASE_RE.search(path.read_text(encoding="utf-8", errors="ignore")):
                found.append(rel)
    assert found == [], f"GOA case numbers outside the allow-list: {found}"
    # the renumbering migration is outside the scanned trees and keeps the old prefix on purpose
    migration = ROOT / "backend/migrations/versions/0028_case_ref_court_prefix.py"
    assert GOA_CASE_RE.search(migration.read_text(encoding="utf-8"))
