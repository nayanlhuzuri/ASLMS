"""Design `portal-shell`, decision 19: the committed `frontend/openapi.json` is the app's contract; a backend change
that alters it regenerates it (`backend/tools/export_openapi.py`, then `npm run gen:api`) in the same change."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _tool():
    spec = importlib.util.spec_from_file_location(
        "export_openapi", ROOT / "backend" / "tools" / "export_openapi.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_committed_openapi_matches_the_app():
    committed = (ROOT / "frontend" / "openapi.json").read_text("utf-8")
    assert committed == _tool().openapi_text(), (
        "frontend/openapi.json is stale: run backend/tools/export_openapi.py and npm run gen:api"
    )


def test_screen_fixes_read_only_additions_are_in_the_contract():
    """Design portal-screen-fixes-work: `PoolCaseOut.best_band`, `NoteRefOut.created_at` and `AlertItemOut.summary`
    are additions only; `summary` is required, the other two default to null."""
    import json

    schemas = json.loads(_tool().openapi_text())["components"]["schemas"]
    band = schemas["PoolCaseOut"]["properties"]["best_band"]
    assert {"enum": ["high", "medium"], "type": "string"} in band["anyOf"] and band.get("default") is None
    assert "best_band" not in schemas["PoolCaseOut"].get("required", [])
    created = schemas["NoteRefOut"]["properties"]["created_at"]
    assert {"format": "date-time", "type": "string"} in created["anyOf"]
    assert "created_at" not in schemas["NoteRefOut"].get("required", [])
    assert schemas["AlertItemOut"]["properties"]["summary"]["type"] == "string"
    assert "summary" in schemas["AlertItemOut"]["required"]


def test_unmapped_example_case_number_is_in_the_contract():
    """Design portal-screen-fixes-oversight, decision 12: `UnmappedCodeOut.example_case_no` is an addition only, a
    nullable string defaulting to null and not required."""
    import json

    schemas = json.loads(_tool().openapi_text())["components"]["schemas"]
    number = schemas["UnmappedCodeOut"]["properties"]["example_case_no"]
    assert {"type": "string"} in number["anyOf"] and number.get("default") is None
    assert "example_case_no" not in schemas["UnmappedCodeOut"].get("required", [])
    assert "example_case_ref" in schemas["UnmappedCodeOut"]["required"]
