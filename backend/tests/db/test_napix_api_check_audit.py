"""The audit rows of the System health actions are always written (design `followups-oct`, decision 6): an unexpected
exception after the call (in the outcome, the structure or the summary) still leaves `napix.api_tested`, built from
the attempts, with `unexpected` naming the exception's class only; the connectivity check records an unexpected
exception in `napix.health_checked` the same way. The error then propagates (500)."""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from aslms.domain.events import AuditLog
from tests.db import docs_support as ds

# ruff: noqa: F811 — the fixtures `api`, `gw`, `held` and `switch_on` are imported and requested by name
from tests.db.test_api_system_health import (  # noqa: F401
    _audits,
    _calls,
    _post,
    api,
    gw,
    held,
    switch_on,
)

MINIMAL = {"api", "path", "attempts", "http_status", "napix_status", "error_family", "ok", "params_sha256"}


def test_exception_in_summary_still_writes_api_tested(api, world, gw, held, switch_on, monkeypatch):
    from aslms.services import napix_api_check

    def broken(*args, **kwargs):
        raise LookupError("summary defect with a CNR in its text")

    monkeypatch.setattr(napix_api_check, "_summary", broken)
    with pytest.raises(LookupError):
        _post(api, "state", ds.login(api, "root"))
    assert len(_calls(world)) == 1
    (row,) = _audits(world)
    assert MINIMAL <= set(row.after)
    assert row.after["unexpected"] == "LookupError" and row.after["summary"] is None
    assert row.after["ok"] is True and row.after["attempts"] == 1
    assert "CNR" not in str(row.after), "the class only, never the text"


def test_exception_in_structure_still_writes_api_tested_with_unexpected(
    api, world, gw, held, switch_on, monkeypatch
):
    from aslms.services import napix_inspect

    def broken(*args, **kwargs):
        raise ValueError("structure defect")

    monkeypatch.setattr(napix_inspect, "structure", broken)
    with pytest.raises(ValueError, match="structure defect"):
        _post(api, "state", ds.login(api, "root"))
    assert len(_calls(world)) == 1
    (row,) = _audits(world)
    assert MINIMAL <= set(row.after)
    assert row.after["unexpected"] == "ValueError"
    assert row.after["api"] == "state" and row.after["path"] == "hc-state-api/state"
    assert row.after["http_status"] == 200 and row.after["error_family"] is None
    assert "summary_error" not in row.after, "the summary never ran"


def test_health_check_unexpected_exception_writes_health_checked(api, world, gw, switch_on):
    factory = api.app.state.napix_factory

    def breaking():
        client, hc = factory()
        real = client.call

        async def call(*args, **kwargs):
            await real(*args, **kwargs)
            raise KeyError("after the hook")

        client.call = call
        return client, hc

    api.app.state.napix_factory = breaking
    with pytest.raises(KeyError):
        api.post("/admin/napix/health/check", headers=ds.login(api, "root"))
    assert [(c.api, c.ok) for c in _calls(world)] == [("overview/overview", True)]
    with world.Session() as s:
        (row,) = s.scalars(sa.select(AuditLog).where(AuditLog.action == "napix.health_checked")).all()
    assert row.after["ok"] is False and row.after["unexpected"] == "KeyError"
    assert row.after["attempts"] == 1
    assert "after the hook" not in str(row.after)


def _breaking_factory(api, exc: Exception, method: str = "call"):
    """The gateway's client with `method` doing its real work (the call or the token request is logged) and then
    raising `exc`: a defect of ASLMS's own inside the call, not a court failure."""
    factory = api.app.state.napix_factory

    def breaking():
        client, hc = factory()
        real = getattr(client, method)

        async def broken(*args, **kwargs):
            await real(*args, **kwargs)
            raise exc

        setattr(client, method, broken)
        return client, hc

    return breaking


@pytest.mark.parametrize("body", [None, {"values": {}}], ids=["test_now", "console_send"])
def test_unexpected_exception_in_the_call_still_writes_api_tested(api, world, gw, held, switch_on, body):
    api.app.state.napix_factory = _breaking_factory(api, KeyError("call defect with a CNR in its text"))
    h = ds.login(api, "root")
    with pytest.raises(KeyError):
        if body is None:
            _post(api, "state", h)
        else:
            api.post("/admin/system-health/napix/state/test", headers=h, json=body)
    assert [(c.api, c.ok) for c in _calls(world)] == [("hc-state-api/state", True)]
    (row,) = _audits(world)
    assert MINIMAL <= set(row.after)
    assert row.after["unexpected"] == "KeyError"
    assert row.after["ok"] is False and row.after["attempts"] == 1 and row.after["http_status"] == 200
    # nothing of the answer is read: no summary run, no structure, no response named
    assert row.after["summary"]["facts"] == [] and "summary_error" not in row.after
    assert row.after["structure"] is None and row.after["response_id"] is None
    assert "CNR" not in str(row.after), "the class only, never the text"


def test_token_check_unexpected_exception_writes_token_checked(api, world, gw, switch_on):
    api.app.state.napix_factory = _breaking_factory(api, RuntimeError("token defect"), "renew_token")
    with pytest.raises(RuntimeError):
        api.post("/admin/system-health/token/check", headers=ds.login(api, "root"))
    with world.Session() as s:
        (row,) = s.scalars(sa.select(AuditLog).where(AuditLog.action == "napix.token_checked")).all()
    assert row.after["ok"] is False and row.after["unexpected"] == "RuntimeError"
    assert row.after["http_status"] == 200 and row.after["error_family"] is None, "the request's own outcome"
    assert "token defect" not in str(row.after)
