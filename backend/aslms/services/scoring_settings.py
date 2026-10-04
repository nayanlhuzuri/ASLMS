"""Scoring settings (design `recommend-and-claim`, decision 21): the five signal-kind weights and the two band
thresholds of the matching engine, edited by the super admin (function `admin.scoring`).

`scoring_settings` is a versioned master table: each save inserts a new version (`is_current = true`) and
closes the previous one (`is_current = false`, `valid_to`); values are never updated in place and rows are
never deleted, so every score names the settings it used (`engine_version = "<engine>.<version>"`). An empty
table means the plan's defaults as version 0; `aslms seed` inserts them as version 1."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aslms.domain.ownership import ScoringSettings
from aslms.domain.reference import EventType, Permission
from aslms.services import access
from aslms.services.audit import Actor, write_audit

KINDS = ("counsel_code", "name_pattern", "watchlist", "linked_case", "keyword")
DEFAULT_REASON = "Plan §4.2 defaults"


class SettingsError(ValueError):
    """Invalid weights, thresholds or reason (HTTP 400)."""


class StaleSettings(SettingsError):
    """`expected_version` is not the current version (HTTP 409)."""


@dataclass(frozen=True)
class Settings:
    version: int
    weights: dict[str, float] = field(hash=False)
    threshold_strong: float
    threshold_possible: float


DEFAULTS = Settings(
    version=0,
    weights={
        "counsel_code": 0.950,
        "name_pattern": 0.800,
        "watchlist": 0.750,
        "linked_case": 0.700,
        "keyword": 0.400,
    },
    threshold_strong=0.850,
    threshold_possible=0.500,
)


def _f(value) -> float:
    return round(float(value), 3)


def from_row(row: ScoringSettings) -> Settings:
    return Settings(
        version=row.version,
        weights={k: _f(getattr(row, f"weight_{k}")) for k in KINDS},
        threshold_strong=_f(row.threshold_strong),
        threshold_possible=_f(row.threshold_possible),
    )


def current_row(session: Session, *, lock: bool = False) -> ScoringSettings | None:
    stmt = select(ScoringSettings).where(ScoringSettings.is_current.is_(True))
    if lock:
        stmt = stmt.with_for_update()
    return session.scalar(stmt)


def current(session: Session) -> Settings:
    row = current_row(session)
    return from_row(row) if row is not None else DEFAULTS


def history(
    session: Session, actor_user, *, limit: int = 50, offset: int = 0
) -> tuple[list[ScoringSettings], int]:
    access.require(session, actor_user, Permission.ADMIN_SCORING)
    total = int(session.scalar(select(func.count()).select_from(ScoringSettings)) or 0)
    rows = session.scalars(
        select(ScoringSettings).order_by(ScoringSettings.version.desc()).limit(limit).offset(offset)
    ).all()
    return list(rows), total


def summary(settings: Settings) -> dict:
    return {
        "version": settings.version,
        "weights": dict(settings.weights),
        "threshold_strong": settings.threshold_strong,
        "threshold_possible": settings.threshold_possible,
    }


def validate(
    weights: dict[str, float], threshold_strong: float, threshold_possible: float, reason: str | None
):
    missing = [k for k in KINDS if k not in weights]
    if missing:
        raise SettingsError("missing weights: " + ", ".join(missing))
    extra = [k for k in weights if k not in KINDS]
    if extra:
        raise SettingsError("unknown weights: " + ", ".join(extra))
    for k in KINDS:
        w = weights[k]
        if w is None or not (0 < float(w) <= 1):
            raise SettingsError(f"the weight of {k} must be greater than 0 and at most 1")
    if not (0 < float(threshold_possible) < float(threshold_strong) <= 1):
        raise SettingsError("thresholds must satisfy 0 < possible < strong <= 1")
    if not (reason or "").strip():
        raise SettingsError("a reason is required")


def _insert(
    session: Session,
    version: int,
    weights: dict[str, float],
    strong: float,
    possible: float,
    reason: str,
    user_id,
) -> ScoringSettings:
    row = ScoringSettings(
        version=version,
        threshold_strong=Decimal(str(round(float(strong), 3))),
        threshold_possible=Decimal(str(round(float(possible), 3))),
        reason=reason,
        is_current=True,
        created_by=user_id,
        updated_by=user_id,
        **{f"weight_{k}": Decimal(str(round(float(weights[k]), 3))) for k in KINDS},
    )
    session.add(row)
    session.flush()
    return row


def update(
    session: Session,
    actor: Actor,
    actor_user,
    *,
    weights: dict[str, float],
    threshold_strong: float,
    threshold_possible: float,
    reason: str,
    expected_version: int,
) -> tuple[Settings, bool]:
    """Saves a new version. Returns (the current settings, changed). An identical save writes nothing."""
    from aslms.services.cases import emit_event

    access.require(session, actor_user, Permission.ADMIN_SCORING)
    validate(weights, threshold_strong, threshold_possible, reason)
    row = current_row(session, lock=True)
    before = from_row(row) if row is not None else DEFAULTS
    if expected_version != before.version:
        raise StaleSettings(
            f"the settings changed meanwhile: the current version is {before.version}, not {expected_version}"
        )
    proposed = Settings(
        version=before.version,
        weights={k: _f(weights[k]) for k in KINDS},
        threshold_strong=_f(threshold_strong),
        threshold_possible=_f(threshold_possible),
    )
    if (
        proposed.weights == before.weights
        and proposed.threshold_strong == before.threshold_strong
        and proposed.threshold_possible == before.threshold_possible
    ):
        return before, False
    now = datetime.now(UTC)
    if row is not None:
        row.is_current = False
        row.valid_to = now
        row.updated_by = actor.user_id
        session.flush()
    new_row = _insert(
        session,
        before.version + 1,
        proposed.weights,
        proposed.threshold_strong,
        proposed.threshold_possible,
        reason.strip(),
        actor.user_id,
    )
    after = from_row(new_row)
    write_audit(
        session,
        actor,
        "scoring_settings.update",
        "scoring_settings",
        new_row.id,
        before=summary(before),
        after={**summary(after), "reason": new_row.reason},
    )
    emit_event(
        session,
        EventType.CONFIG_CHANGED,
        None,
        {"entity": "scoring_settings", "id": str(new_row.id), "action": "update", "version": after.version},
        dedupe=f"scoring_settings:{new_row.id}",
        scoped=True,
    )
    session.flush()
    return after, True


def seed_default(session: Session, report) -> None:
    """Version 1 with the plan's defaults, when the table is empty."""
    if session.scalar(select(func.count()).select_from(ScoringSettings)):
        return
    _insert(
        session,
        1,
        DEFAULTS.weights,
        DEFAULTS.threshold_strong,
        DEFAULTS.threshold_possible,
        DEFAULT_REASON,
        None,
    )
    report.add("scoring_settings")
