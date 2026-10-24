"""Every router reaches NAPIX through `deps.napix_request` (design `followups-oct`, decision 3): no router calls
`napix_client(` itself, and every router that takes the client takes the apart factory for its recorder and audit."""

from __future__ import annotations

from pathlib import Path

ROUTERS = Path(__file__).resolve().parents[2] / "aslms" / "api" / "routers"
NAPIX_ROUTERS = {"cases.py", "data_load.py", "napix_admin.py", "system_health.py"}


def test_no_router_calls_napix_client():
    offenders = [p.name for p in ROUTERS.glob("*.py") if "napix_client(" in p.read_text(encoding="utf-8")]
    assert offenders == []


def test_the_napix_routers_use_napix_request_and_the_apart_factory():
    for name in NAPIX_ROUTERS:
        text = (ROUTERS / name).read_text(encoding="utf-8")
        assert "napix_request(request, session)" in text, name
        assert "apart_factory(request)" in text, name
        assert "app.state.session_factory" not in text, f"{name} writes apart rows on the main pool"
