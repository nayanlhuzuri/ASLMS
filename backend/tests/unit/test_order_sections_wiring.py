"""Design `order-sections` ("Jobs", "CLI", "Services"): the `order-sections` beat at minutes 3, 8, … in the scheduler,
its job name in the scheduler's repair set, the `ORDER_SECTIONS_BATCH` setting, and the `aslms orders` group in the CLI
help with its four commands. No database."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from aslms.core.config import Settings
from aslms.services.job_repair import SCHEDULER_JOBS


def test_beat_entry_and_repair_set():
    from aslms.jobs.celery_app import app

    entry = app.conf.beat_schedule["order-sections"]
    assert entry["task"] == "aslms.order_sections_read"
    assert entry["schedule"].minute == set(range(3, 60, 5))
    assert "order_sections" in SCHEDULER_JOBS
    assert "aslms.order_sections_read" in app.tasks


def test_batch_setting_default_and_bounds():
    assert Settings(_env_file=None).order_sections_batch == 500
    with pytest.raises(ValueError):
        Settings(_env_file=None, order_sections_batch=0)
    with pytest.raises(ValueError):
        Settings(_env_file=None, order_sections_batch=5001)


def test_cli_help_lists_orders_and_its_commands():
    from aslms.cli.main import app

    r = CliRunner().invoke(app, ["--help"])
    assert r.exit_code == 0 and "orders" in r.output
    r = CliRunner().invoke(app, ["orders", "--help"])
    assert r.exit_code == 0
    for command in ("parse", "status", "show", "checks"):
        assert command in r.output
    r = CliRunner().invoke(app, ["orders", "parse", "--help"])
    for option in ("--backfill", "--order", "--limit", "--batch", "--pause-ms", "--dry-run"):
        assert option in r.output
