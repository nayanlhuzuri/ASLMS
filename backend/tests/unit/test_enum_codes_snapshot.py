"""Design `portal-names-and-labels`, decision 15: the committed `frontend/src/lib/enumCodes.json` holds the codes the
backend can send (domain enums, audit actions, case Details keys); a backend change that alters them regenerates it
(`backend/tools/export_enum_codes.py`) in the same change. The same contract as `test_openapi_snapshot.py`."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _tool():
    spec = importlib.util.spec_from_file_location(
        "export_enum_codes", ROOT / "backend" / "tools" / "export_enum_codes.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_committed_enum_codes_match_the_backend():
    committed = (ROOT / "frontend" / "src" / "lib" / "enumCodes.json").read_text("utf-8")
    assert committed == _tool().enum_codes_text(), (
        "frontend/src/lib/enumCodes.json is stale: run backend/tools/export_enum_codes.py"
    )


def test_enum_codes_carry_domain_enums_by_import():
    doc = json.loads(_tool().enum_codes_text())
    from aslms.domain.cases import CaseStatus
    from aslms.domain.reference import Role

    assert doc["enums"]["CaseStatus"] == [s.value for s in CaseStatus]
    assert doc["enums"]["Role"] == [r.value for r in Role]
    assert "OrderKind" in doc["enums"] and "LowerCourtLevel" in doc["enums"]
    assert doc["case_detail_fields"]["acts"] == ["act_name_as_listed", "national_act_code", "section"]
    assert "ownership.claim" in doc["audit_actions"]
