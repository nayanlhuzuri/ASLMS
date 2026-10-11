"""The data-load console without a database (design `data-load-console`): decision 3's priority table, decision 8's
estimate formula and its reasons, and the ordered reserves of decision 4."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from pydantic import ValidationError

from aslms.core.config import Settings
from aslms.domain.ops import FetchKind, FetchLane, LoadOrder
from aslms.services.data_load import Basis, compute_estimate, day_tree_calls
from aslms.services.load_policy import DEFAULTS, LoadSettings, QueueOrigin, load_priority

D, P, O = FetchKind.CAUSELIST_DAY, FetchKind.DOSSIER, FetchKind.ORDER_PDF
JAN = date(2025, 1, 15)
MAR = date(2025, 3, 15)


def _settings(order: LoadOrder, forward: tuple[date, date] | None = None) -> LoadSettings:
    return LoadSettings(
        version=1,
        paused=False,
        load_order=order,
        first_from=forward[0] if forward else None,
        first_to=forward[1] if forward else None,
    )


def test_load_priority_table():
    expected = {
        LoadOrder.CASES_FIRST: {P: (41, 44), D: (42, 46), O: (43, 48)},
        LoadOrder.LISTS_FIRST: {D: (41, 44), P: (42, 46), O: (43, 48)},
        LoadOrder.CASES_WITH_ORDERS: {P: (41, 44), O: (42, 46), D: (43, 48)},
    }
    seen = set()
    for order, kinds in expected.items():
        s = _settings(order, (date(2025, 1, 1), date(2025, 1, 31)))
        for kind, (fwd, other) in kinds.items():
            assert load_priority(s, kind, JAN) == fwd, (order, kind)
            assert load_priority(s, kind, MAR) == other, (order, kind)
            assert load_priority(s, kind, None) == other
            assert load_priority(_settings(order), kind, JAN) == other
            seen.update({fwd, other})
    assert seen == {41, 42, 43, 44, 46, 48}
    assert all(40 < p < 50 for p in seen)  # behind today's dossiers (40), ahead of the weekly sweep (50)
    assert load_priority(DEFAULTS, P, JAN) == 44 and load_priority(DEFAULTS, D, JAN) == 46
    with pytest.raises(ValueError):
        load_priority(DEFAULTS, FetchKind.MASTERS, JAN)


def test_origin_priorities():
    assert QueueOrigin().dossier_priority() == 40
    assert QueueOrigin().order_pdf_priority(True) == 40 and QueueOrigin().order_pdf_priority(False) == 80
    req = QueueOrigin(FetchLane.REQUEST)
    assert req.dossier_priority() == 30 and req.order_pdf_priority(False) == 40
    load = QueueOrigin(FetchLane.LOAD, JAN, _settings(LoadOrder.LISTS_FIRST))
    assert load.dossier_priority() == 46 and load.order_pdf_priority(True) == 48


NOW = datetime(2026, 10, 11, 10, 0, tzinfo=UTC)


def _basis(**kw) -> Basis:
    base = dict(
        window_days=7,
        calls_per_item={"causelist_day": 6.0, "dossier": 1.5, "order_pdf": 1.0},
        finished={"causelist_day": 10, "dossier": 200, "order_pdf": 400},
        calls={"causelist_day": 60, "dossier": 300, "order_pdf": 400},
        dossiers_per_day=20.0,
        pdfs_per_dossier=2.0,
        calls_per_hour=500.0,
        pending={"causelist_day": 100, "dossier": 50, "order_pdf": 30},
        history_hours=72.0,
        calls_last_hour=480,
    )
    base.update(kw)
    return Basis(**base)


def test_estimate_formula_and_reasons():
    b = _basis()
    est = compute_estimate(b, paused=False, now=NOW)
    # pending: 100*6 + 50*1.5 + 30*1 = 705; days: 100 * (20 * (1.5 + 2*1)) = 7000; dossiers: 50 * 2 * 1 = 100
    assert est.calls_needed == 7805.0
    assert est.hours == round(7805 / 500, 2)
    assert est.finish_at == NOW + timedelta(hours=7805 / 500)
    assert est.reason is None and est.basis["calls_per_hour"] == 500.0
    assert day_tree_calls(b) == 6.0 + 20.0 * (1.5 + 2.0 * 1.0)

    assert compute_estimate(b, paused=True, now=NOW).reason == "paused"
    young = compute_estimate(_basis(history_hours=23.5), paused=False, now=NOW)
    assert young.reason == "not_enough_history" and young.finish_at is None
    idle = compute_estimate(_basis(calls_last_hour=0), paused=False, now=NOW)
    assert idle.reason == "no_recent_calls" and idle.calls_needed is None
    # a kind with work pending but nothing finished in the window: no rate, no estimate
    unmeasured = _basis(calls_per_item={"causelist_day": 6.0, "dossier": None, "order_pdf": 1.0})
    assert compute_estimate(unmeasured, paused=False, now=NOW).reason == "not_enough_history"
    done = compute_estimate(
        _basis(pending={"causelist_day": 0, "dossier": 0, "order_pdf": 0}), paused=False, now=NOW
    )
    assert done.calls_needed == 0 and done.reason is None


def test_reserve_settings_validated():
    Settings(_env_file=None, napix_search_floor=50, napix_live_reserve=100, napix_rate_reserve=150)
    Settings(_env_file=None, napix_search_floor=50, napix_live_reserve=50, napix_rate_reserve=50)
    for floor, live, rate in ((50, 40, 150), (50, 160, 150), (120, 100, 150)):
        with pytest.raises(ValidationError):
            Settings(
                _env_file=None, napix_search_floor=floor, napix_live_reserve=live, napix_rate_reserve=rate
            )
    with pytest.raises(ValidationError):
        Settings(_env_file=None, data_load_estimate_window_days=0)
