"""The registry of audit action codes (design `portal-names-and-labels`, decision 22): every literal code passed to
`write_audit` or `write_audit_apart` in the backend is registered, and the registry is sorted with no duplicates.
The codes built at run time are caught by the `AuditLog` insert listener of the database suite."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from aslms.domain.audit_actions import AUDIT_ACTIONS

BACKEND = Path(__file__).resolve().parents[2]
CODE = re.compile(r"^[a-z_]+\.[a-z_]+$")


def _literal_actions() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for path in sorted((BACKEND / "aslms").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else fn.id if isinstance(fn, ast.Name) else None
            if name not in ("write_audit", "write_audit_apart"):
                continue
            arg = node.args[2] if len(node.args) > 2 else None
            if arg is None:
                arg = next((k.value for k in node.keywords if k.arg == "action"), None)
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                found.setdefault(arg.value, []).append(f"{path.relative_to(BACKEND)}:{node.lineno}")
    return found


def test_literal_audit_actions_are_registered():
    found = _literal_actions()
    assert len(found) > 90  # the scan reaches the code
    missing = {code: where for code, where in found.items() if code not in AUDIT_ACTIONS}
    assert missing == {}, f"register these in aslms/domain/audit_actions.py: {missing}"


def test_registry_has_no_duplicates_and_is_sorted():
    assert len(set(AUDIT_ACTIONS)) == len(AUDIT_ACTIONS)
    assert list(AUDIT_ACTIONS) == sorted(AUDIT_ACTIONS)
    bad = [c for c in AUDIT_ACTIONS if not CODE.match(c)]
    assert bad == []


def test_run_time_constants_are_registered():
    """The module constants the run-time codes come from."""
    from aslms.services import collect, court_search, discovery, retention, sessions, system_health
    from aslms.services.auth import FAILURE_ACTIONS
    from aslms.services.napix_inspect import VIEW_ACTION

    codes = {
        collect.COLLECT_ACTION,
        collect.STOP_ACTION,
        *collect.REQUEST_ACTIONS,
        *court_search.SEARCH_ACTIONS,
        discovery.SWEEP_ACTION,
        retention.ACTION,
        sessions.ACTION_IDLE,
        sessions.ACTION_LIMIT,
        *system_health.CAP_ACTIONS,
        *FAILURE_ACTIONS,
        VIEW_ACTION,
    }
    assert codes - set(AUDIT_ACTIONS) == set()
