"""Design research-index-portal, decision 10: the portal sends a typed act as row 250's `_act_key` would read it. The
table of cases is shared with the frontend's `actKey` test (`frontend/src/components/assistant/actKeyCases.json`)."""

from __future__ import annotations

import json
from pathlib import Path

from aslms.services import order_parse

CASES = (
    Path(__file__).resolve().parents[3] / "frontend" / "src" / "components" / "assistant" / "actKeyCases.json"
)


def test_act_key_rule_cases():
    cases = json.loads(CASES.read_text("utf-8"))
    assert len(cases) >= 6
    for raw, key in cases:
        assert order_parse._act_key(raw) == key, raw
