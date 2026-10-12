"""The NAPIX quota window, detected from the call log, never assumed (design `napix-window`, decisions 1-6).

The gateway gives 1,000 calls per one-hour window, but the window does not reset on the clock hour: the reset is at a
fixed minute of the hour that is only known by watching `X-RateLimit-Remaining` jump back up (notes §6). Nothing is
stored: the readings are the `napix_call_log` rows that carry `rate_limit_remaining`, ordered by the attempt's own
time (`called_at`, decision 7).

- **A reset** is a reading whose count exceeds the previous reading's by at least `NAPIX_WINDOW_RESET_JUMP`. Jumps less
  than a quarter window apart are one reset, timed by the first, when an answer from the old window came in between
  (a fall of at least the jump from one reading to the next: an in-flight call answered across the boundary); without
  such a fall they are two resets, as when a window seen late (an imprecise jump) ends minutes later (a precise one:
  11 Oct, 12:30:07 and 12:34:30 IST). See the design note's deviations. A reset is **precise** when the previous
  reading is at most `PRECISE_GAP` seconds older; otherwise it only says a new window began since the previous
  reading.
- **The phase** comes only from precise resets: the anchor is the latest precise reset in `LOOKBACK`; S is the latest
  reset of any kind; the expected next reset E = anchor + k x window for the smallest k with E later than S + half a
  window. Without an anchor E is unknown.
- **Four states** (`assess`, pure): `current` (now < E + margin; the latest reading counts), `reset_due` (E + margin
  passed, no reading since E; remaining unknown), `overdue` (a reading after E showed no jump; the latest reading
  counts only while younger than the probe interval) and `unknown` (no anchor; the same freshness rule). An unknown
  remaining means "the next call will tell": the guards allow work, and the runner probes first.

`current(session, settings)` is what every guard and figure reads: the court-search and connectivity-check guards, the
runner's seed, the health block and the console's allowance card (decision 6). Read-only; never calls NAPIX."""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from aslms.core.config import Settings
from aslms.domain.ops import NapixCallLog
from aslms.domain.org import User
from aslms.integration.napix.hc import API
from aslms.services.audit_search import to_ist

PRECISE_GAP = 300  # seconds: a reset is precise when the previous reading is at most this much older
LOOKBACK = timedelta(hours=6)  # readings, resets and the anchor are taken from this far back
PHASE_JITTER = (
    180  # seconds: resets seen up to this much before the phase point (11 Oct: HH:33:18 to HH:34:53)
)
STATUSES = ("current", "reset_due", "overdue", "unknown")
LANES = ("load", "daily", "request")


@dataclass(frozen=True)
class Reading:
    at: datetime
    remaining: int


@dataclass(frozen=True)
class Reset:
    observed_at: datetime
    previous_at: datetime
    previous_remaining: int
    remaining: int
    precise: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "observed_at": to_ist(self.observed_at),
            "previous_at": to_ist(self.previous_at),
            "previous_remaining": self.previous_remaining,
            "remaining": self.remaining,
            "precise": self.precise,
        }


@dataclass(frozen=True)
class WindowState:
    """The window as the call log shows it at one moment. `remaining` is what the guards use (None = unknown).
    `started_at` is E - window in `current` / `overdue`, E in `reset_due` and S in `unknown`; `observed_at` is S (None
    in `reset_due`); `next_reset_at` is E (None when unknown)."""

    status: str
    remaining: int | None
    started_at: datetime | None
    observed_at: datetime | None
    next_reset_at: datetime | None
    anchor_at: datetime | None
    last_reading_at: datetime | None
    recent_resets: tuple[Reset, ...] = field(default_factory=tuple)  # newest first
    window_seconds: int = 3600
    margin: int = 60
    probe: int = 180

    def seconds_to_reset(self, now: datetime) -> int | None:
        """Seconds to E; negative while the reset is due or overdue; None when E is unknown."""
        if self.next_reset_at is None:
            return None
        return math.floor((self.next_reset_at - now).total_seconds())

    def resume_at(self, now: datetime) -> datetime:
        """Decision 4: when the bands block, `current` waits for E + margin; otherwise the next probe is due one probe
        interval after the latest reading."""
        if self.status == "current" and self.next_reset_at is not None:
            return self.next_reset_at + timedelta(seconds=self.margin)
        base = self.last_reading_at or now
        return base + timedelta(seconds=self.probe)

    def retry_after(self, now: datetime) -> int:
        """Decision 6: a `napix_budget` refusal's wait: to E + margin in `current`, the probe interval otherwise."""
        if self.status == "current" and self.next_reset_at is not None:
            wait = (self.next_reset_at + timedelta(seconds=self.margin) - now).total_seconds()
            return max(1, math.ceil(wait))
        return self.probe

    def describe(self) -> str:
        """`window current, next reset about 15:34 IST` and the like, for the runner's stopped reason."""
        e = _hhmm(self.next_reset_at)
        if self.status == "current":
            return f"window current, next reset about {e} IST"
        if self.status == "reset_due":
            return f"window reset due at about {e} IST, no call since"
        if self.status == "overdue":
            return f"window reset expected at about {e} IST not seen yet"
        return "window timing not known yet"

    def as_dict(self, now: datetime) -> dict[str, Any]:
        return {
            "status": self.status,
            "started_at": to_ist(self.started_at),
            "observed_at": to_ist(self.observed_at),
            "next_reset_at": to_ist(self.next_reset_at),
            "seconds_to_next_reset": self.seconds_to_reset(now),
            "anchor_at": to_ist(self.anchor_at),
            "remaining": self.remaining,
            "last_reading_at": to_ist(self.last_reading_at),
            "recent_resets": [r.as_dict() for r in self.recent_resets],
            "window_seconds": self.window_seconds,
            "margin_seconds": self.margin,
            "probe_seconds": self.probe,
        }


def _hhmm(value: datetime | None) -> str:
    return f"{to_ist(value):%H:%M}" if value is not None else "?"


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(UTC)


# ------------------------------------------------------------------------------------------------ the pure part


def detect(readings: list[Reading], jump: int, *, window_seconds: int = 3600) -> list[Reset]:
    """Decision 1: the resets in a list of readings ordered by time, oldest first. A jump within a quarter window of
    the previous reset is part of it only when a reading fell back by at least `jump` in between (the old window
    answering late)."""
    cluster = timedelta(seconds=window_seconds / 4)
    out: list[Reset] = []
    prev: Reading | None = None
    fell_back = False  # since the latest reset, a reading fell by at least `jump` from its predecessor
    for r in readings:
        if prev is not None and prev.remaining - r.remaining >= jump:
            fell_back = True
        if prev is not None and r.remaining - prev.remaining >= jump:
            same = bool(out) and r.at - out[-1].observed_at < cluster and fell_back
            if not same:
                fell_back = False
                out.append(
                    Reset(
                        observed_at=r.at,
                        previous_at=prev.at,
                        previous_remaining=prev.remaining,
                        remaining=r.remaining,
                        precise=(r.at - prev.at).total_seconds() <= PRECISE_GAP,
                    )
                )
        prev = r
    return out


def assess(
    readings: list[Reading],
    now: datetime,
    *,
    window_seconds: int = 3600,
    margin: int = 60,
    probe: int = 180,
    jump: int = 50,
) -> WindowState:
    """Decisions 2 and 3: the state of the window at `now` from the readings (any order; those outside the lookback or
    after `now` are ignored)."""
    w = timedelta(seconds=window_seconds)
    rs = sorted((r for r in readings if now - LOOKBACK <= r.at <= now), key=lambda r: r.at)
    resets = detect(rs, jump, window_seconds=window_seconds)
    last = rs[-1] if rs else None
    s_at = resets[-1].observed_at if resets else None
    precise = [r for r in resets if r.precise]
    anchor = precise[-1].observed_at if precise else None
    common = dict(
        anchor_at=anchor,
        last_reading_at=last.at if last else None,
        recent_resets=tuple(reversed(resets)),
        window_seconds=window_seconds,
        margin=margin,
        probe=probe,
    )

    def fresh() -> int | None:
        if last is not None and (now - last.at).total_seconds() < probe:
            return last.remaining
        return None

    if anchor is None or s_at is None:
        return WindowState("unknown", fresh(), s_at, s_at, None, **common)
    # The window in progress began at the last phase point at or before S (a reset is never observed before it
    # happens, apart from the gateway's jitter of a minute or two around the phase). Rounding S to the nearest
    # phase point instead put E one whole window late whenever an imprecise S came in the second half of a window
    # (after a restart, a pause or idle time) and the worker slept through a real reset (review of 12 Oct 2026).
    k = math.floor(((s_at - anchor) + timedelta(seconds=PHASE_JITTER)) / w) + 1
    expected = anchor + k * w
    if now < expected + timedelta(seconds=margin):
        remaining = last.remaining if last is not None and now - last.at <= w else None
        return WindowState("current", remaining, expected - w, s_at, expected, **common)
    if last is None or last.at < expected:
        return WindowState("reset_due", None, expected, None, expected, **common)
    return WindowState("overdue", fresh(), expected - w, s_at, expected, **common)


# ------------------------------------------------------------------------------------------------ the database part


def readings(session: Session, now: datetime | None = None) -> list[Reading]:
    """The call-log readings of the lookback, ordered by (called_at, id): one range query on the `called_at` index."""
    now = _now(now)
    rows = session.execute(
        text(
            "SELECT called_at, rate_limit_remaining FROM napix_call_log "
            "WHERE called_at >= :since AND called_at <= :now AND rate_limit_remaining IS NOT NULL "
            "ORDER BY called_at, id"
        ),
        {"since": now - LOOKBACK, "now": now},
    ).all()
    return [Reading(at, int(rem)) for at, rem in rows]


def current(session: Session, settings: Settings, now: datetime | None = None) -> WindowState:
    """The window now: `readings` + `assess`, read-only."""
    now = _now(now)
    return assess(
        readings(session, now),
        now,
        window_seconds=settings.napix_rate_window_seconds,
        margin=settings.napix_window_margin_seconds,
        probe=settings.napix_window_probe_seconds,
        jump=settings.napix_window_reset_jump,
    )


def calls_since(session: Session, start: datetime | None, *, lane_split: bool = False) -> dict[str, Any]:
    """Calls and failures since `start` (S; nothing when it is None, as in `reset_due`), split by lane when asked
    (`outside_queue` = NULL lane: searches, checks and probes)."""
    out: dict[str, Any] = {"calls": 0, "failed": 0}
    if lane_split:
        out["by_lane"] = {**{lane: 0 for lane in LANES}, "outside_queue": 0}
    if start is None:
        return out
    rows = session.execute(
        select(NapixCallLog.lane, func.count(), func.count().filter(NapixCallLog.ok.is_(False)))
        .where(NapixCallLog.called_at >= start)
        .group_by(NapixCallLog.lane)
    ).all()
    for lane, n, failed in rows:
        out["calls"] += int(n)
        out["failed"] += int(failed)
        if lane_split:
            key = getattr(lane, "value", lane) if lane is not None else "outside_queue"
            out["by_lane"][key] += int(n)
    return out


def by_user(session: Session, start: datetime | None, limit: int = 10) -> list[dict[str, Any]]:
    """Calls by the person who caused them since `start`, most calls first: `{user_id, name, calls, failed}`."""
    if start is None:
        return []
    n = func.count()
    rows = session.execute(
        select(NapixCallLog.user_id, User.full_name, n, func.count().filter(NapixCallLog.ok.is_(False)))
        .join(User, User.id == NapixCallLog.user_id)
        .where(NapixCallLog.user_id.isnot(None), NapixCallLog.called_at >= start)
        .group_by(NapixCallLog.user_id, User.full_name)
        .order_by(n.desc(), User.full_name)
        .limit(max(1, int(limit)))
    ).all()
    return [
        {"user_id": uid, "name": name, "calls": int(calls), "failed": int(failed)}
        for uid, name, calls, failed in rows
    ]


def probes_since(session: Session, start: datetime) -> int:
    """The runner's window probes since `start`: Overview calls made inside a pass (they carry its `job_run_id`)."""
    return int(
        session.scalar(
            select(func.count()).where(
                NapixCallLog.api == API["overview"],
                NapixCallLog.job_run_id.isnot(None),
                NapixCallLog.called_at >= start,
            )
        )
        or 0
    )


def user_id_of(user: Any) -> uuid.UUID | None:
    """The login id of a `User` or an access `Member` (None for the `system` actor)."""
    return getattr(user, "id", None) if user is not None else None  # a Member's `id` is its login's
