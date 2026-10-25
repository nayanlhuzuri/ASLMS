"""The queue's lane and priority policy (design `data-load-console`, decisions 1, 3 and 5), kept apart from
`services/data_load.py` so the pipeline stages (`causelists`, `orders`, `court_search`) can import it without a
cycle.

- `LoadSettings` and `current_settings`: the current `data_load_settings` version, or the defaults (running,
  `cases_first`, nothing brought forward) when the table is empty.
- `load_priority(settings, kind, list_date)`: decision 3's table for the two detail kinds (cause-list days and
  dossiers). The preset ranks them; the 1st runs at 41 inside the period brought forward and 44 outside it, the 2nd
  at 42 / 46. `cases_first` and `cases_with_orders` put dossiers first, `lists_first` cause-list days first.
- Case details before order PDFs (owner, 24 Oct 2026): an order PDF outside the request lane waits behind every
  detail kind, whatever the preset: 60 for a pending case (after daily dossiers 40, the load 41-46, discovery 41-43,
  the weekly sweep 50 and the disposed refresh 55) and 80 for any other case (disposed or unknown).
  `load_priority` gives a load order PDF 60, so `cases_with_orders` no longer brings PDFs forward; it orders
  dossiers before cause-list days, as `cases_first` does.
- `QueueOrigin(lane, list_date)`: who asked for the work a stage is doing; the rows it spawns inherit the lane and
  the `list_date`. Daily: dossiers 40, order PDFs 60 (pending case) or 80 (disposed). Load: dossiers by
  `load_priority`, order PDFs 60 / 80. Request: dossiers 30, order PDFs 40, so a person's own case gets its orders
  quickly. Discovery (design `department-discovery`, decision 6): dossiers 41, order PDFs 60 / 80; its searches 42
  (weekly sweep and a user's requested years) and 43 (a new term's first sweep). A request origin also carries
  `requested_by`, the person who asked (design `napix-window`, decision 9); the rows it spawns inherit it."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from aslms.domain.ops import DataLoadSettings, FetchKind, FetchLane, LoadOrder

# the order of the two detail kinds per preset (decision 3); order PDFs come after both (owner, 24 Oct 2026)
PRESET_ORDER: dict[LoadOrder, tuple[FetchKind, FetchKind]] = {
    LoadOrder.CASES_FIRST: (FetchKind.DOSSIER, FetchKind.CAUSELIST_DAY),
    LoadOrder.LISTS_FIRST: (FetchKind.CAUSELIST_DAY, FetchKind.DOSSIER),
    LoadOrder.CASES_WITH_ORDERS: (FetchKind.DOSSIER, FetchKind.CAUSELIST_DAY),
}
FORWARD = (41, 42)  # rank 1, 2 inside the period brought forward
OTHERWISE = (44, 46)  # rank 1, 2 otherwise
LOAD_KINDS = (FetchKind.CAUSELIST_DAY, FetchKind.DOSSIER, FetchKind.ORDER_PDF)

REQUEST_PRIORITY = 30
DAILY_DOSSIER = 40
# a person's search, fetch from the court or claim refresh: ahead of the queue
REQUEST_ORDER_PDF = 40
# a pending case's order PDF in the daily, load and discovery lanes: after every detail kind
LIVE_ORDER_PDF = 60
DISPOSED_ORDER_PDF = 80
# the discovery lane (design department-discovery, decision 6)
DISCOVERY_DOSSIER = 41
DISCOVERY_RECENT = 42
DISCOVERY_FULL = 43


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
    """0 or 1: the place of a detail kind in the preset."""
    return PRESET_ORDER[LoadOrder(order)].index(kind)


def brought_forward(settings: LoadSettings, list_date: date | None) -> bool:
    return (
        list_date is not None
        and settings.first_from is not None
        and settings.first_to is not None
        and settings.first_from <= list_date <= settings.first_to
    )


def load_priority(settings: LoadSettings, kind: FetchKind, list_date: date | None) -> int:
    """Decision 3's table: 41 / 42 inside the period brought forward, 44 / 46 otherwise; an order PDF 60 in every
    preset (a pending case; `QueueOrigin.order_pdf_priority` gives any other case's 80)."""
    if kind not in LOAD_KINDS:
        raise ValueError(f"{kind.value} is not a load kind")
    if kind == FetchKind.ORDER_PDF:
        return LIVE_ORDER_PDF
    r = rank(settings.load_order, kind)
    return FORWARD[r] if brought_forward(settings, list_date) else OTHERWISE[r]


@dataclass(frozen=True)
class QueueOrigin:
    """The lane and list date of the work in hand; spawned rows inherit both."""

    lane: FetchLane = FetchLane.DAILY
    list_date: date | None = None
    settings: LoadSettings | None = None  # the load settings (read once per item); defaults when absent
    requested_by: uuid.UUID | None = None  # the person behind a request origin; None for system work

    def dossier_priority(self) -> int:
        if self.lane == FetchLane.LOAD:
            return load_priority(self.settings or DEFAULTS, FetchKind.DOSSIER, self.list_date)
        if self.lane == FetchLane.REQUEST:
            return REQUEST_PRIORITY
        if self.lane == FetchLane.DISCOVERY:
            return DISCOVERY_DOSSIER
        return DAILY_DOSSIER

    def order_pdf_priority(self, pending_case: bool) -> int:
        """Request 40; every other lane after the detail kinds: 60 for a pending case, 80 for any other (disposed or
        unknown)."""
        if self.lane == FetchLane.REQUEST:
            return REQUEST_ORDER_PDF
        return LIVE_ORDER_PDF if pending_case else DISPOSED_ORDER_PDF


DAILY = QueueOrigin()
