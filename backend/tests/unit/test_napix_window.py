"""The detected quota window (design `napix-window`, decisions 1-5), pure: resets from jumps, precision, the phase
from precise resets only, the four states, `resume_at` / `retry_after`, the 11 Oct evidence and the settings' bounds."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from aslms.core.config import Settings
from aslms.services.napix_window import LOOKBACK, PRECISE_GAP, Reading, assess, detect

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "napix_readings_2026-10-11.json"
IST_OFFSET = timedelta(hours=5, minutes=30)
T0 = datetime(2026, 10, 11, 7, 0, tzinfo=UTC)  # 12:30 IST


def ist(hh: int, mm: int, ss: int = 0) -> datetime:
    """An IST wall-clock time on 11 Oct 2026, as an aware UTC datetime."""
    return datetime(2026, 10, 11, hh, mm, ss, tzinfo=UTC) - IST_OFFSET


def seq(start: datetime, counts: list[int], step: float = 1.0) -> list[Reading]:
    return [Reading(start + timedelta(seconds=i * step), n) for i, n in enumerate(counts)]


def state(readings, now, **kw):
    return assess(readings, now, window_seconds=3600, margin=60, probe=180, jump=50, **kw)


# ------------------------------------------------------------------------------------------------ decision 1


def test_jump_detects_reset_and_ignores_upticks():
    readings = seq(T0, [822, 823, 821, 999, 998])
    resets = detect(readings, 50)
    assert len(resets) == 1
    (r,) = resets
    assert (r.observed_at, r.previous_remaining, r.remaining) == (readings[3].at, 821, 999)
    assert detect(seq(T0, [512, 513, 515, 514, 516]), 50) == []  # +1 and +2 rises are noise
    assert detect(seq(T0, [100, 149]), 50) == [] and len(detect(seq(T0, [100, 150]), 50)) == 1


def test_jumps_within_quarter_window_are_one_reset():
    readings = seq(T0, [822, 999, 820, 998])  # an old-window answer interleaved: one reset
    (r,) = detect(readings, 50)
    assert r.observed_at == readings[1].at and r.previous_remaining == 822
    # a jump 15 minutes or more after the reset is a new reset
    later = readings + [
        Reading(T0 + timedelta(minutes=16), 700),
        Reading(T0 + timedelta(minutes=16, seconds=1), 999),
    ]
    assert len(detect(later, 50)) == 2


def test_two_real_resets_minutes_apart_are_kept():
    """A window seen late (imprecise) that ends minutes later (precise): two resets, as on 11 Oct at 12:30:07 and
    12:34:30 IST (the deviation recorded in the design note)."""
    readings = [Reading(ist(11, 30, 7), 148)] + seq(ist(12, 30, 7), list(range(999, 769, -1)), step=1.0)
    readings.append(Reading(ist(12, 34, 30), 999))
    resets = detect(readings, 50)
    assert [(r.observed_at, r.precise) for r in resets] == [(ist(12, 30, 7), False), (ist(12, 34, 30), True)]


def test_precise_needs_previous_reading_within_300s():
    (late,) = detect([Reading(T0, 148), Reading(T0 + timedelta(seconds=3600), 999)], 50)
    assert late.precise is False
    (seen,) = detect([Reading(T0, 769), Reading(T0 + timedelta(seconds=7), 999)], 50)
    assert seen.precise is True
    (edge,) = detect([Reading(T0, 769), Reading(T0 + timedelta(seconds=PRECISE_GAP), 999)], 50)
    assert edge.precise is True
    (over,) = detect([Reading(T0, 769), Reading(T0 + timedelta(seconds=PRECISE_GAP + 1), 999)], 50)
    assert over.precise is False


# ------------------------------------------------------------------------------------------------ decisions 2-3


def _anchored(anchor: datetime) -> list[Reading]:
    """A precise reset at `anchor` (the previous reading 7 s before)."""
    return [Reading(anchor - timedelta(seconds=7), 300), Reading(anchor, 999)]


def test_expected_reset_from_anchor_not_from_imprecise_reset():
    anchor = ist(12, 34, 30)
    readings = _anchored(anchor) + [
        Reading(ist(12, 50), 150),
        Reading(ist(14, 35, 30), 999),  # imprecise: the previous reading is 1 h 45 min older
        Reading(ist(14, 40), 990),
    ]
    w = state(readings, ist(14, 50))
    assert w.anchor_at == anchor and w.observed_at == ist(14, 35, 30)
    assert w.next_reset_at == ist(15, 34, 30)
    assert w.status == "current" and w.started_at == ist(14, 34, 30) and w.remaining == 990
    assert [r.precise for r in w.recent_resets] == [False, True]  # newest first


def test_imprecise_reset_late_in_a_window_does_not_skip_the_next_reset():
    """Review of 12 Oct: the load resumes 36 minutes into a window (after a pause, a restart or idle time). The first
    reading (999) is an imprecise reset whose true time was the phase point before it; the next reset is the very
    next phase point, not one a whole window later."""
    anchor = ist(15, 34, 30)
    readings = _anchored(anchor) + [
        Reading(ist(15, 50), 148),
        Reading(ist(17, 10), 999),  # imprecise: 1 h 20 min after the previous reading; true reset 16:34:30
        Reading(ist(17, 25), 149),
    ]
    w = state(readings, ist(17, 26))
    assert w.status == "current"
    assert w.started_at == ist(16, 34, 30) and w.next_reset_at == ist(17, 34, 30)
    # the same when S lands a minute or two before the phase point (the gateway's jitter)
    early = _anchored(anchor) + [
        Reading(ist(15, 50), 148),
        Reading(ist(16, 33, 0), 999),
        Reading(ist(16, 40), 700),
    ]
    assert state(early, ist(16, 41)).next_reset_at == ist(17, 34, 30)


def test_states():
    anchor = ist(12, 34, 30)
    e = anchor + timedelta(hours=1)
    # current: before E + margin, the latest reading counts however old (here 40 minutes)
    current = state(_anchored(anchor) + [Reading(ist(12, 55), 148)], ist(13, 35, 29))
    assert (current.status, current.remaining, current.next_reset_at) == ("current", 148, e)
    assert current.seconds_to_reset(ist(13, 35, 29)) == -59
    # reset_due: E + margin passed and no reading since E
    due = state(_anchored(anchor) + [Reading(ist(12, 55), 148)], ist(13, 35, 30))
    assert (due.status, due.remaining, due.started_at, due.observed_at) == ("reset_due", None, e, None)
    # overdue: a reading after E showed no jump; it counts while younger than the probe interval
    readings = _anchored(anchor) + [Reading(ist(12, 55), 148), Reading(ist(13, 36), 140)]
    young = state(readings, ist(13, 38, 59))
    assert (young.status, young.remaining, young.started_at) == ("overdue", 140, anchor)
    old = state(readings, ist(13, 39))  # 180 s old: not younger than the probe interval
    assert (old.status, old.remaining) == ("overdue", None)
    # unknown: no precise reset in the lookback
    readings = [Reading(ist(12, 0), 148), Reading(ist(13, 0), 999), Reading(ist(13, 10), 900)]
    fresh = state(readings, ist(13, 12))
    assert (fresh.status, fresh.remaining, fresh.next_reset_at, fresh.started_at) == (
        "unknown",
        900,
        None,
        ist(13, 0),
    )
    assert state(readings, ist(13, 13)).remaining is None
    nothing = state([], ist(13, 0))
    assert (nothing.status, nothing.remaining, nothing.started_at, nothing.last_reading_at) == (
        "unknown",
        None,
        None,
        None,
    )
    # an anchor older than the lookback is no anchor
    gone = state(_anchored(anchor) + [Reading(ist(12, 55), 148)], anchor + LOOKBACK + timedelta(seconds=1))
    assert gone.status == "unknown" and gone.anchor_at is None


def test_resume_at_and_retry_after():
    anchor = ist(12, 34, 30)
    current = state(_anchored(anchor) + [Reading(ist(13, 30), 148)], ist(13, 31))
    assert current.resume_at(ist(13, 31)) == ist(13, 35, 30)  # E + margin
    assert current.retry_after(ist(13, 31)) == 270
    readings = _anchored(anchor) + [Reading(ist(12, 55), 148), Reading(ist(13, 36), 140)]
    overdue = state(readings, ist(13, 37))
    assert overdue.resume_at(ist(13, 37)) == ist(13, 39)  # the latest reading + the probe interval
    assert overdue.retry_after(ist(13, 37)) == 180
    unknown = state([Reading(ist(13, 0), 120)], ist(13, 1))
    assert unknown.resume_at(ist(13, 1)) == ist(13, 3) and unknown.retry_after(ist(13, 1)) == 180


def test_evidence_sequence_11_oct():
    """The 11 Oct log: at 15:30 IST with 147 left the window is current, the next reset about 15:34 IST, and the
    worker resumes before 15:36 IST. The old rule (sleep to the next UTC hour) gave 16:30 IST."""
    doc = json.loads(FIXTURE.read_text(encoding="utf-8"))
    readings = [Reading(datetime.fromisoformat(at), n) for at, n in doc["readings"]]
    last = readings[-1]
    assert last.remaining in (147, 148) and ist(15, 30) <= last.at < ist(15, 30, 30)
    now = last.at + timedelta(seconds=1)
    w = state(readings, now)
    assert w.status == "current" and w.remaining == last.remaining
    assert ist(15, 33) <= w.next_reset_at <= ist(15, 35)
    assert w.resume_at(now) < ist(15, 36)
    old_rule = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    assert old_rule == ist(16, 30) and w.resume_at(now) < old_rule
    # every reset observed that day falls between HH:30 and HH:35 IST
    assert all(30 <= (r.observed_at + IST_OFFSET).minute <= 35 for r in w.recent_resets)
    assert any(r.precise for r in w.recent_resets)


def test_window_settings_validated():
    s = Settings(_env_file=None)
    assert (s.napix_window_margin_seconds, s.napix_window_probe_seconds, s.napix_window_reset_jump) == (
        60,
        180,
        50,
    )
    for name, bad in (
        ("napix_window_margin_seconds", -1),
        ("napix_window_margin_seconds", 601),
        ("napix_window_probe_seconds", 59),
        ("napix_window_probe_seconds", PRECISE_GAP + 1),  # capped at the precise gap
        ("napix_window_reset_jump", 9),
        ("napix_window_reset_jump", 501),
    ):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, **{name: bad})
    assert Settings(_env_file=None, napix_window_probe_seconds=PRECISE_GAP).napix_window_probe_seconds == 300


def test_worker_sleeps_until_resume_at_not_the_clock_hour():
    """`queue-worker` (design napix-window, decision 4): until `resume_at` (at least 5 s), capped by the idle time
    when only the load lane is blocked; printed in IST."""
    from aslms.cli.pipeline import worker_wait
    from aslms.services.runner import RunReport

    anchor = ist(14, 33, 27)
    window = state(_anchored(anchor) + [Reading(ist(15, 30, 6), 148)], ist(15, 30, 7))
    now = ist(15, 30, 7)
    full = RunReport(resume_at=window.resume_at(now), window=window)
    wait, line = worker_wait(full, 60, now)
    assert wait == (ist(15, 34, 27) - now).total_seconds()
    assert line == "waiting for the window reset at about 15:33:27 IST (+60 s)"
    load = RunReport(resume_at=window.resume_at(now), window=window, load_only=True, processed=3)
    assert worker_wait(load, 60, now)[0] == 60
    overdue = state(_anchored(anchor) + [Reading(ist(15, 0), 148), Reading(ist(15, 35), 140)], ist(15, 35, 1))
    wait, line = worker_wait(RunReport(resume_at=ist(15, 38), window=overdue), 60, ist(15, 35, 1))
    assert wait == 179 and line == "reset overdue: probing in 179 s"
    assert worker_wait(RunReport(resume_at=now - timedelta(seconds=30), window=overdue), 60, now)[0] == 5
    assert worker_wait(RunReport(processed=0), 60, now) == (60, None)
    assert worker_wait(RunReport(processed=4), 60, now) == (None, None)
