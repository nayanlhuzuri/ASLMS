"""Department discovery without a database (design `department-discovery`, "Tests" unit; owner's decisions of 14 Oct
2026): which rule texts may be sent to the court's party-name search, the sweep years (2025 to the current year,
newest first), the queue ref format, the discovery lane's priorities, the runner's share of the window and the two
settings' ranges."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from aslms.core.config import Settings
from aslms.domain.ops import FetchLane
from aslms.domain.ownership import PatternKind
from aslms.services import discovery
from aslms.services.load_policy import QueueOrigin
from aslms.services.runner import QueueRunner
from aslms.services.storage import LocalStore


@pytest.mark.parametrize(
    "text", ["PRITAM SAIKIA", "DIRECTOR OF SECONDARY EDUCATION", "M/S S K & CO (P) LTD-1"]
)
def test_discoverable_accepts_names(text):
    assert discovery.discoverable(text)
    assert discovery.discoverable(text, PatternKind.EXACT)
    assert discovery.discoverable(text, "prefix")


@pytest.mark.parametrize(
    "text", ["AB", "A" * 201, "PRITAM|SAIKIA", "NAME=X", "100%", "", None, "pritam saikia"]
)
def test_discoverable_refuses_bad_texts(text):
    assert not discovery.discoverable(text)


def test_a_regex_is_never_discoverable():
    assert not discovery.discoverable("PRITAM SAIKIA", PatternKind.REGEX)
    assert not discovery.discoverable("^PRITAM", "regex")


def test_sweep_years_from_2025_newest_first():
    assert discovery.sweep_years(date(2026, 10, 14), 2025) == [2026, 2025]
    assert discovery.sweep_years(date(2027, 1, 2), 2025) == [2027, 2026, 2025]
    assert discovery.sweep_years(date(2026, 10, 14), 2000)[:2] == [2026, 2025]
    assert len(discovery.sweep_years(date(2026, 10, 14), 2000)) == 27
    assert discovery.sweep_years(date(2026, 10, 14), 2026) == [2026]


def test_ref_round_trips():
    ref = discovery.make_ref("GAHC01", 2025, "PRITAM SAIKIA")
    assert ref == "GAHC01|P|2025|PRITAM SAIKIA"
    assert discovery.parse_ref(ref) == ("GAHC01", 2025, "PRITAM SAIKIA")
    for bad in (
        "GAHC01|D|2025|PRITAM SAIKIA",
        "GAHC01|P|year|PRITAM SAIKIA",
        "GAHC01|P|2025",
        "GAHC01|P|2025|a=b",
    ):
        with pytest.raises(ValueError):
            discovery.parse_ref(bad)


def test_discovery_lane_priorities():
    origin = QueueOrigin(FetchLane.DISCOVERY)
    assert origin.dossier_priority() == 41
    assert origin.order_pdf_priority(True) == 49
    assert origin.order_pdf_priority(False) == 49
    # the other lanes are unchanged
    assert QueueOrigin(FetchLane.DAILY).dossier_priority() == 40
    assert QueueOrigin(FetchLane.REQUEST).dossier_priority() == 30


def _runner(tmp_path, **kw) -> QueueRunner:
    settings = Settings(_env_file=None, storage_dir=str(tmp_path / "store"), **kw)
    return QueueRunner(
        None, None, settings=settings, store=LocalStore(settings.storage_dir), causelist_dir=tmp_path
    )


def test_budget_lanes_with_the_share(tmp_path):
    r = _runner(tmp_path)
    r.recorder.last_remaining = 500
    r.discovery_used = 10
    assert r.budget_lanes() == (True, None)  # every lane, discovery included
    r.discovery_used = 100
    assert r.budget_lanes() == (True, [FetchLane.REQUEST, FetchLane.DAILY, FetchLane.LOAD])
    r.recorder.last_remaining = None  # unknown: as the top band
    assert r.budget_lanes() == (True, [FetchLane.REQUEST, FetchLane.DAILY, FetchLane.LOAD])
    for used in (0, 100):
        r.discovery_used = used
        r.recorder.last_remaining = 120  # below the rate reserve: never discovery, whatever the share
        assert r.budget_lanes() == (True, [FetchLane.REQUEST, FetchLane.DAILY])
        r.recorder.last_remaining = 50
        assert r.budget_lanes() == (False, None)


def test_share_zero_never_claims_discovery(tmp_path):
    r = _runner(tmp_path, napix_discovery_share=0)
    r.recorder.last_remaining = 900
    assert r.share_left() == 0
    assert FetchLane.DISCOVERY not in (r.budget_lanes()[1] or [])
    assert r.budget_lanes()[1] is not None


def test_discovery_settings_ranges():
    s = Settings(_env_file=None)
    assert (s.napix_discovery_share, s.discovery_from_year) == (100, 2025)
    Settings(_env_file=None, napix_discovery_share=0, discovery_from_year=1950)
    Settings(_env_file=None, napix_discovery_share=1000, discovery_from_year=date.today().year)
    for bad in (
        {"napix_discovery_share": -1},
        {"napix_discovery_share": 1001},
        {"discovery_from_year": 1949},
        {"discovery_from_year": date.today().year + 1},
    ):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, **bad)
