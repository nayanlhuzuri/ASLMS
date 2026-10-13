"""`aslms discovery` (design `department-discovery`, "Services"): `sweep --term` queues the term's years and is audited
`discovery.sweep` as the super admin; an unknown term is refused; `status` prints the Data collection block as JSON;
`terms` lists the term; the weekly Celery task queues every active term."""

from __future__ import annotations

import json
from contextlib import contextmanager

import sqlalchemy as sa
from typer.testing import CliRunner

from aslms.core.config import Settings
from aslms.domain.events import AuditLog
from aslms.domain.ops import FetchStatus
from aslms.services import matching_rules as mr
from tests.db.discovery_support import party_rows, years

CFG = Settings(_env_file=None)


def _scope(world):
    @contextmanager
    def scope():
        s = world.Session()
        try:
            yield s
            s.commit()
        finally:
            s.close()

    return scope


def test_cli_discovery(world, monkeypatch):
    import typer

    from aslms.cli import discovery as cli
    from aslms.cli import pipeline

    with world.Session() as s:
        actor, admin = world.actor(s, "edu_admin")
        mr.create_keyword(s, actor, admin, keyword="PRITAM SAIKIA", office=world.office(s, "EDU"))
        for r in party_rows(s):
            r.status = FetchStatus.DONE
        s.commit()
    monkeypatch.setattr(cli, "session_scope", _scope(world))
    monkeypatch.setattr(pipeline, "session_scope", _scope(world))
    monkeypatch.setattr(cli, "get_settings", lambda: CFG)
    app = typer.Typer()
    app.add_typer(cli.discovery_app, name="discovery")
    runner = CliRunner()
    r = runner.invoke(app, ["discovery", "sweep", "--term", "pritam saikia"])
    assert r.exit_code == 0, r.output
    assert f"queued {len(years())}" in r.output
    r = runner.invoke(app, ["discovery", "sweep", "--term", "NOBODY"])
    assert r.exit_code != 0
    r = runner.invoke(app, ["discovery", "status"])
    assert r.exit_code == 0, r.output
    out = json.loads(r.output)
    assert out["settings"]["share"] == 100 and out["terms"]["active"] == 1
    r = runner.invoke(app, ["discovery", "terms"], env={"COLUMNS": "200"})
    assert r.exit_code == 0 and "PRITAM SAIKIA" in r.output
    with world.Session() as s:
        audit = s.scalar(sa.select(AuditLog).where(AuditLog.action == "discovery.sweep"))
        assert audit.actor_user_id == world.users["root"].id and audit.after["scope"] == "term"
        assert {r.status for r in party_rows(s)} == {FetchStatus.PENDING}


def test_weekly_task(world, monkeypatch):
    from aslms.jobs import celery_app

    with world.Session() as s:
        actor, admin = world.actor(s, "edu_admin")
        mr.create_keyword(s, actor, admin, keyword="PRITAM SAIKIA", office=world.office(s, "EDU"))
        s.commit()
    monkeypatch.setattr(celery_app, "session_scope", _scope(world))
    assert celery_app.enqueue_discovery() == {"terms": 1, "rows_queued": len(years()), "years": len(years())}
    assert celery_app.app.conf.beat_schedule["discovery-weekly"]["task"] == "aslms.enqueue_discovery"
