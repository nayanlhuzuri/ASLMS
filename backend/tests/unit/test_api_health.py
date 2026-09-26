from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from aslms import __version__
from aslms.api.main import app


def test_health_does_not_need_database() -> None:
    with TestClient(app) as client:
        r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__


def test_app_error_handler_shape() -> None:
    from fastapi import APIRouter

    from aslms.core.errors import NotFoundError

    router = APIRouter()

    @router.get("/__boom")
    async def boom() -> None:
        raise NotFoundError("no such case", cnr="GAHC010000000000")

    app.include_router(router, prefix="/api/v1")
    with TestClient(app) as client:
        r = client.get("/api/v1/__boom")
    assert r.status_code == 404
    assert r.json() == {
        "error": "not_found",
        "message": "no such case",
        "details": {"cnr": "GAHC010000000000"},
    }


def test_login_accepts_reserved_domains_used_by_seed_accounts() -> None:
    """Regression: EmailStr rejected `.local`, so the seeded operator account could never sign in."""
    from pydantic import ValidationError

    from aslms.api.schemas import LoginIn

    assert LoginIn(email=" Admin@ASLMS.local ", password="x").email == "admin@aslms.local"
    with pytest.raises(ValidationError):
        LoginIn(email="not-an-address", password="x")
