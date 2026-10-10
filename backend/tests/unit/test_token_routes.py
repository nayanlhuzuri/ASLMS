"""Design `portal-shell`, decision 6: every API operation whose answer carries a token is listed in
`frontend/src/server/token-routes.json` (the relay refuses those paths), and nothing else is."""

from __future__ import annotations

import json
from pathlib import Path

from aslms.api.main import create_app
from aslms.core.config import Settings

ROOT = Path(__file__).resolve().parents[3]
TOKEN_FIELDS = {"access_token", "refresh_token", "device_token"}


def _carries_token(schema: dict, components: dict, seen: set[str]) -> bool:
    if not isinstance(schema, dict):
        return False
    ref = schema.get("$ref")
    if ref:
        name = ref.rsplit("/", 1)[-1]
        if name in seen:
            return False
        seen.add(name)
        return _carries_token(components.get(name, {}), components, seen)
    if TOKEN_FIELDS & set(schema.get("properties", {})):
        return True
    children = list(schema.get("properties", {}).values())
    for key in ("items", "additionalProperties"):
        if isinstance(schema.get(key), dict):
            children.append(schema[key])
    for key in ("anyOf", "oneOf", "allOf"):
        children.extend(schema.get(key, []))
    return any(_carries_token(c, components, seen) for c in children)


def token_operations(spec: dict) -> set[tuple[str, str]]:
    components = spec.get("components", {}).get("schemas", {})
    found = set()
    for path, item in spec["paths"].items():
        for method, op in item.items():
            for code, resp in op.get("responses", {}).items():
                if not str(code).startswith("2"):
                    continue
                for media in resp.get("content", {}).values():
                    if _carries_token(media.get("schema", {}), components, set()):
                        found.add((method.upper(), path))
    return found


def test_every_operation_returning_tokens_is_listed():
    spec = create_app(Settings(_env_file=None), session_factory=lambda: None).openapi()
    listed = json.loads((ROOT / "frontend" / "src" / "server" / "token-routes.json").read_text("utf-8"))
    declared = {(r["method"].upper(), r["path"]) for r in listed["routes"]}
    assert token_operations(spec) == declared
