"""Every NAPIX field has a home (CLAUDE.md): each path in `docs/specs/napix_field_inventory.md` must be mapped
in `docs/schema/napix_coverage.md` §B–§D, and every `table.column` named there must exist in the models.
A block the samples only show empty (📄, typed from the PDF specifications) is covered by its prefix."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import aslms.domain  # noqa: F401
from aslms.db.base import Base

ROOT = Path(__file__).resolve().parents[3]
INVENTORY = ROOT / "docs" / "specs" / "napix_field_inventory.md"
ADDENDUM = ROOT / "docs" / "schema" / "napix_coverage.md"

TICK = re.compile(r"`([^`]+)`")
# §C is one table for the dossier and Current Status; the other sections carry the API in the first column.
SECTION_C_APIS = ("cnr", "current_status")
# inventory API → the label the addendum uses
ALIASES = {"cnr": "cnr", "current_status": "current_status"}


def _rows(text: str) -> list[list[str]]:
    rows = []
    for line in text.splitlines():
        if (
            line.startswith("| ")
            and not line.startswith("|---")
            and not line.startswith("| path")
            and not line.startswith("| API")
            and not line.startswith("| Path")
        ):
            rows.append([c.strip() for c in line.strip().strip("|").split("|")])
    return rows


def load_inventory() -> dict[str, dict[str, str]]:
    """api → {path: type}."""
    out: dict[str, dict[str, str]] = {}
    api = None
    for line in INVENTORY.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            api = line[3:].strip()
            out[api] = {}
        elif api and line.startswith("| `"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            out[api][TICK.search(cells[0]).group(1)] = cells[1]
    return out


def _paths_in_cell(cell: str) -> list[str]:
    """`a`, `b` → [a, b]; `pfx[]` / `pfx2[]`: `x`, `y` → [pfx[].x, pfx[].y, pfx2[].x, …];
    `one, two, three` inside one pair of backticks → each."""
    cell = cell.replace("📄", "")
    if ":" in cell and "`" in cell.split(":", 1)[0]:
        left, right = cell.split(":", 1)
        prefixes = [p.strip() for p in TICK.findall(left)]
        leaves = [x.strip() for tok in TICK.findall(right) for x in tok.split(",")]
        return [f"{p}.{leaf}" for p in prefixes for leaf in leaves] + prefixes
    return [x.strip() for tok in TICK.findall(cell) for x in tok.split(",") if x.strip()]


def load_addendum() -> tuple[dict[str, set[str]], set[tuple[str, str]]]:
    """api → mapped path patterns; and the (table, column) targets named anywhere."""
    text = ADDENDUM.read_text(encoding="utf-8")
    mapped: dict[str, set[str]] = {}
    targets: set[tuple[str, str]] = set()
    section = None
    current_apis: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            section = line[3:4]
            current_apis = []
            continue
        if section not in ("B", "C", "D") or not line.startswith("| ") or line.startswith("|---"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if section == "C":
            if cells[0].startswith("Path"):
                continue
            path_cell, target_cell = cells[0], cells[1]
            apis = list(SECTION_C_APIS)
        else:
            if cells[0] in ("API", ""):
                apis = current_apis if cells[0] == "" else []
            else:
                apis = [a.strip() for a in cells[0].split(",")]
                current_apis = apis
            if cells[0] == "API" or len(cells) < 3:
                continue
            path_cell, target_cell = cells[1], cells[2]
        for api in apis:
            mapped.setdefault(api, set()).update(_paths_in_cell(path_cell))
        for table, column in re.findall(r"`([a-z_]+)\.([a-z_]+)`", target_cell):
            targets.add((table, column))
    return mapped, targets


def _norm(path: str) -> str:
    """`acts[].actname` and `acts.actname` are the same home; an empty block `acts` is covered by its prefix."""
    return path.replace("[]", "")


def _pattern(mapped_path: str) -> re.Pattern[str]:
    esc = re.escape(_norm(mapped_path)).replace(r"\{n\}", r"\d+")
    return re.compile(rf"^{esc}(\..+)?$")


def _covered(path: str, kind: str, mapped: set[str], patterns: list[re.Pattern[str]]) -> bool:
    if any(p.match(path) for p in patterns):
        return True
    # a block the samples only show empty is covered by any mapped path inside it
    return kind == "empty-list" and any(_norm(m).startswith(path + ".") for m in mapped)


@pytest.fixture(scope="module")
def data():
    return load_inventory(), load_addendum()


def test_every_inventory_path_is_mapped(data):
    inventory, (mapped, _targets) = data
    missing: list[str] = []
    for api, paths in inventory.items():
        label = ALIASES.get(api, api)
        mapped_paths = mapped.get(label, set())
        patterns = [_pattern(p) for p in mapped_paths]
        for path, kind in paths.items():
            probe = _norm(path[3:] if api == "current_status" and path.startswith("[].") else path)
            if not _covered(probe, kind, mapped_paths, patterns):
                missing.append(f"{api}: {path} ({kind})")
    assert not missing, "NAPIX paths without a column:\n  " + "\n  ".join(missing)


def test_every_target_column_exists(data):
    _inventory, (_mapped, targets) = data
    tables = Base.metadata.tables
    bad = []
    for table, column in sorted(targets):
        if table not in tables:
            bad.append(f"{table} (no such table)")
        elif column not in tables[table].c:
            bad.append(f"{table}.{column}")
    assert not bad, "addendum names columns the models do not have:\n  " + "\n  ".join(bad)


def test_inventory_covers_the_verified_apis(data):
    inventory, _ = data
    assert {
        "cnr",
        "current_status",
        "causelist_bench",
        "causelist_details",
        "state_master",
        "bench_master",
    } <= set(inventory)
