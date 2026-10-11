"""The queue's lane and priority policy (design `data-load-console`, decisions 1, 3 and 5), kept apart from
`services/data_load.py` so the pipeline stages (`causelists`, `orders`, `court_search`) can import it without a
cycle.

- `LoadSettings` and `current_settings`: the current `data_load_settings` version, or the defaults (running,
  `cases_first`, nothing brought forward) when the table is empty.
- `load_priority(settings, kind, list_date)`: decision 3's table. The preset ranks the three load kinds; the 1st
  kind runs at 41 inside the period brought forward and 44 outside it, the 2nd at 42 / 46, the 3rd at 43 / 48.
- `QueueOrigin(lane, list_date)`: who asked for the work a stage is doing; the rows it spawns inherit the lane and
  the `list_date`. Daily: dossiers 40, order PDFs 40 (pending case) or 80 (disposed). Load: `load_priority`.
  Request: dossiers 30, order PDFs 40."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from aslms.domain.ops import DataLoadSettings, FetchKind, FetchLane, LoadOrder

# the order of the three load kinds per preset (decision 3)
PRESET_ORDER: dict[LoadOrder, tuple[FetchKind, FetchKind, FetchKind]] = {
    LoadOrder.CASES_FIRST: (FetchKind.DOSSIER, FetchKind.CAUSELIST_DAY, FetchKind.ORDER_PDF),
    LoadOrder.LISTS_FIRST: (FetchKind.CAUSELIST_DAY, FetchKind.DOSSIER, FetchKind.ORDER_PDF),
    LoadOrder.CASES_WITH_ORDERS: (FetchKind.DOSSIER, FetchKind.ORDER_PDF, FetchKind.CAUSELIST_DAY),
}
FORWARD = (41, 42, 43)  # rank 1, 2, 3 inside the period brought forward
OTHERWISE = (44, 46, 48)  # rank 1, 2, 3 otherwise
LOAD_KINDS = (FetchKind.CAUSELIST_DAY, FetchKind.DOSSIER, FetchKind.ORDER_PDF)

REQUEST_PRIORITY = 30
DAILY_DOSSIER = 40
LIVE_ORDER_PDF = 40
DISPOSED_ORDER_PDF = 80


@dataclass(frozen=True)
class LoadSettings:
    version: int
    paused: bool
    load_order: LoadOrder
    first_from: date | None
    first_to: date | None
    reason: str | None = None
    changed_at: datetime | None = None
    changed_by: str | None = None


DEFAULTS = LoadSettings(
    version=0, paused=False, load_order=LoadOrder.CASES_FIRST, first_from=None, first_to=None
)


def current_row(session: Session, *, lock: bool = False) -> DataLoadSettings | None:
    stmt = select(DataLoadSettings).where(DataLoadSettings.is_current.is_(True))
    if lock:
        stmt = stmt.with_for_update()
    return session.scalar(stmt.execution_options(populate_existing=True))


def from_row(session: Session, row: DataLoadSettings) -> LoadSettings:
    from aslms.domain.org import User

    who = session.get(User, row.created_by) if row.created_by else None
    return LoadSettings(
        version=row.version,
        paused=bool(row.paused),
        load_order=LoadOrder(row.load_order),
        first_from=row.first_from,
        first_to=row.first_to,
        reason=row.reason,
        changed_at=row.valid_from,
        changed_by=who.full_name if who is not None else None,
    )


def current_settings(session: Session) -> LoadSettings:
    row = current_row(session)
    return from_row(session, row) if row is not None else DEFAULTS


def rank(order: LoadOrder, kind: FetchKind) -> int:
    """0, 1 or 2: the place of the kind in the preset."""
    return PRESET_ORDER[LoadOrder(order)].index(kind)


def brought_forward(settings: LoadSettings, list_date: date | None) -> bool:
    return (
        list_date is not None
        and settings.first_from is not None
        and settings.first_to is not None
        and settings.first_from <= list_date <= settings.first_to
    )


def load_priority(settings: LoadSettings, kind: FetchKind, list_date: date | None) -> int:
    """Decision 3's table: 41-43 inside the period brought forward, 44 / 46 / 48 otherwise."""
    if kind not in LOAD_KINDS:
        raise ValueError(f"{kind.value} is not a load kind")
    r = rank(settings.load_order, kind)
    return FORWARD[r] if brought_forward(settings, list_date) else OTHERWISE[r]


@dataclass(frozen=True)
class QueueOrigin:
    """The lane and list date of the work in hand; spawned rows inherit both."""

    lane: FetchLane = FetchLane.DAILY
    list_date: date | None = None
    settings: LoadSettings | None = None  # the load settings (read once per item); defaults when absent

    def dossier_priority(self) -> int:
        if self.lane == FetchLane.LOAD:
            return load_priority(self.settings or DEFAULTS, FetchKind.DOSSIER, self.list_date)
        if self.lane == FetchLane.REQUEST:
            return REQUEST_PRIORITY
        return DAILY_DOSSIER

    def order_pdf_priority(self, pending_case: bool) -> int:
        if self.lane == FetchLane.LOAD:
            return load_priority(self.settings or DEFAULTS, FetchKind.ORDER_PDF, self.list_date)
        if self.lane == FetchLane.REQUEST:
            return LIVE_ORDER_PDF
        return LIVE_ORDER_PDF if pending_case else DISPOSED_ORDER_PDF


DAILY = QueueOrigin()
