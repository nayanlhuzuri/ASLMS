"""Design `rolling-case-refresh` (unit): the levelled night quota (decision 4) and its cap (decision 5), the hearing
follow-up steps (decision 9), the order-PDF priorities left as they were (decision 11), the worker slots (decisions 16
and 18) and `queue-worker --slot`."""

from __future__ import annotations

import math
from datetime import date, timedelta

import typer
from typer.testing import CliRunner

from aslms.domain.ops import FetchKind, FetchLane
from aslms.services import queue
from aslms.services.job_repair import ALL_SETS, SCHEDULER_JOBS, WORKER2_JOBS, WORKER_JOBS
from aslms.services.load_policy import DEFAULTS, NOW_BULK, NOW_ONE, QueueOrigin, load_priority
from aslms.services.runner import SLOT_KINDS, slot_job
from aslms.services.tracking import followup_step, rolling_quota

# the dev database's ages on 12 Nov 2026 (design, Context): the Sunday sweep left the cases on three dates
DEV_AGES = {1: 6680, 2: 18996, 3: 11521}


def _simulate(ages: dict[int, int], nights: int, cap: int = 12000) -> list[int]:
    """Each night every age grows by one, the quota is refreshed oldest first and comes back at age 0."""
    out = []
    for _ in range(nights):
        ages = {a + 1: n for a, n in ages.items()}
        q = rolling_quota(ages, cap).quota
        out.append(q)
        left = q
        for a in sorted(ages, reverse=True):
            take = min(left, ages[a])
            ages[a] -= take
            left -= take
        ages = {a: n for a, n in ages.items() if n}
        ages[0] = ages.get(0, 0) + q
    return out


def test_rolling_quota_steady_state_is_the_due_count():
    steady = {age: 100 for age in range(7)}  # a seventh due each night
    plan = rolling_quota({**steady, 7: 100}, 12000)
    assert plan.due == 100 and plan.quota == 100 and not plan.over_cap
    # spread evenly, the simulation keeps a seventh a night and nothing is early
    assert set(_simulate({age: 100 for age in range(7)}, 21)) == {100}


def test_rolling_quota_levels_a_clump():
    total = sum(DEV_AGES.values())
    series = _simulate(DEV_AGES, 40)
    assert max(series) <= math.ceil(total / 4), series  # at most about a quarter of the clump on one night
    assert series[0] > 0, "the clump is met early, before it falls due"
    assert abs(series[-1] - total / 7) <= total * 0.02, "the nights settle near a seventh"
    # without levelling the clump would fall due on one night
    assert rolling_quota({7: 18996, 6: 11521, 8: 6680}, 50000).due == 18996 + 6680


def test_rolling_quota_never_below_due_unless_capped():
    for ages in ({7: 5}, {7: 5, 6: 40}, {9: 3, 4: 400}, {10: 1000, 5: 1}, DEV_AGES):
        plan = rolling_quota(ages, 50000)
        assert plan.quota >= plan.due, ages
        n3 = sum(n for a, n in ages.items() if a >= 4)
        assert plan.quota == max(
            math.ceil(sum(n for a, n in ages.items() if a >= 7 - k) / (k + 1)) for k in range(4)
        )
        assert plan.quota <= max(plan.due, n3)


def test_rolling_quota_cap_and_zero():
    plan = rolling_quota({8: 30, 7: 20}, 40)
    assert (plan.due, plan.quota, plan.cap, plan.over_cap) == (50, 40, 40, True)
    plan = rolling_quota({8: 30}, 40)
    assert (plan.quota, plan.over_cap) == (30, False)
    off = rolling_quota({8: 30}, 0)
    assert (off.due, off.quota, off.cap, off.over_cap) == (30, 0, 0, False)
    assert rolling_quota({}, 12000).quota == 0


def test_followup_step():
    h = date(2026, 11, 2)

    def on(n: int) -> date:
        return h + timedelta(days=n)

    assert followup_step(on(2), h, on(-5)) is None  # day 2: none
    assert followup_step(on(3), h, on(-5)) == 3  # day 3, refreshed before the hearing
    assert followup_step(on(3), h, on(2)) == 3  # refreshed before H + 3
    assert followup_step(on(3), h, on(3)) is None  # refreshed on the step's day
    assert followup_step(on(5), h, on(4)) is None  # refreshed on H + 4: not due on day 5
    assert followup_step(on(7), h, on(4)) == 7  # but due on day 7
    assert followup_step(on(13), h, on(7)) is None
    assert followup_step(on(14), h, on(7)) == 14
    assert followup_step(on(30), h, on(14)) == 30
    assert followup_step(on(31), h, on(30)) is None  # the 30-day step was made
    for day in range(31, 38):
        assert followup_step(on(day), h, on(20)) == 30, day  # catch-up when it was missed
    assert followup_step(on(38), h, on(20)) is None  # day 38: the weekly refresh alone
    assert followup_step(on(5), None, on(0)) is None
    assert followup_step(on(3), h, None) == 3


def test_order_pdf_priority_unchanged():
    for lane in (FetchLane.DAILY, FetchLane.LOAD, FetchLane.DISCOVERY):
        origin = QueueOrigin(lane)
        assert origin.order_pdf_priority(True) == 60, lane
        assert origin.order_pdf_priority(False) == 80, lane
    assert QueueOrigin(FetchLane.REQUEST).order_pdf_priority(True) == 40
    assert QueueOrigin(FetchLane.REQUEST, now_priority=NOW_ONE).order_pdf_priority(True) == 3
    assert QueueOrigin(FetchLane.REQUEST, now_priority=NOW_BULK).order_pdf_priority(False) == 5
    assert load_priority(DEFAULTS, FetchKind.ORDER_PDF, None) == 60
    # no PDF of a pending case is ever queued ahead of a routine refresh row
    assert max(queue.ROUTINE_PRIORITIES) < queue.PRIORITY["order_pdf_live"] == 60
    assert list(queue.ROUTINE_PRIORITIES) == [56, 57, 58, 59]
    assert (
        queue.PRIORITY["dossier_routine_claimed"],
        queue.PRIORITY["dossier_routine"],
        queue.PRIORITY["dossier_early_claimed"],
        queue.PRIORITY["dossier_early"],
    ) == (56, 57, 58, 59)
    assert queue.PRIORITY["dossier_refetch"] == 50 < queue.PRIORITY["dossier_disposed"] == 55


def test_slot_kinds():
    assert SLOT_KINDS["main"] is None
    second = set(SLOT_KINDS["second"])
    assert FetchKind.STATUS_BATCH not in second
    assert not second & queue.LOCAL_KINDS
    assert second == set(FetchKind) - {FetchKind.STATUS_BATCH} - set(queue.LOCAL_KINDS)
    assert (slot_job("main"), slot_job("second")) == ("queue-run", "queue-run-second")
    assert WORKER_JOBS == {"queue-run"} and WORKER2_JOBS == {"queue-run-second"}
    assert ALL_SETS["worker2"] == WORKER2_JOBS and not WORKER_JOBS & WORKER2_JOBS
    assert "nightly-refresh" in SCHEDULER_JOBS


def test_queue_worker_rejects_unknown_slot():
    from aslms.cli import pipeline

    app = typer.Typer()
    app.command(name="queue-worker")(pipeline.queue_worker)
    app.command(name="noop")(lambda: None)
    r = CliRunner().invoke(app, ["queue-worker", "--slot", "third"])
    assert r.exit_code == 2
    assert "unknown slot" in r.output


def test_queue_worker_second_slot_repairs_its_own_runs_and_passes_its_kinds(monkeypatch, capsys):
    import pytest

    from aslms.cli import pipeline
    from aslms.core.config import Settings

    calls: dict = {}
    monkeypatch.setattr(
        "aslms.services.job_repair.repair_at_start",
        lambda factory, jobs, started, who: calls.update(jobs=jobs, who=who) or 0,
    )
    monkeypatch.setattr("aslms.services.db_guard.refuse_superuser", lambda url, is_prod: None)
    monkeypatch.setattr(pipeline, "get_sessionmaker", lambda *a, **k: object())
    monkeypatch.setattr(
        pipeline, "get_settings", lambda: Settings(_env_file=None, app_env="test", redis_url=None)
    )

    def stop(factory, **kw):
        calls.update(run=kw)
        raise KeyboardInterrupt

    monkeypatch.setattr(pipeline, "run_queue", stop)
    with pytest.raises(KeyboardInterrupt):
        pipeline.queue_worker(idle_seconds=0, max_items=None, slot="second")
    assert calls["jobs"] == WORKER2_JOBS and calls["who"] == "queue-worker-second"
    assert calls["run"]["job"] == "queue-run-second"
    # the gateway is off in these settings: the second slot narrows to what can run without it
    assert calls["run"]["kinds"] == [FetchKind.CAUSELIST_DAY]
    assert "queue worker started (slot second, NAPIX off)" in capsys.readouterr().out
