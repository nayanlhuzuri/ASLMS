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
