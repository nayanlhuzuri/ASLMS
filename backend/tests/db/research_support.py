"""Helpers for the research index tests (design `research-index`, "Tests", database): court orders with stored text
read by row 250's job, research settings, and a scripted embedding model (`FakeOllama` with `embed_model`, a bag of
words hashed into 768 buckets; never a real model)."""

from __future__ import annotations

from datetime import date

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aslms.core.config import Settings
from aslms.domain.cases import Case
from aslms.domain.documents import Order, OrderKind, OrderSection
from aslms.domain.research import ResearchChunk, ResearchEmbedding
from aslms.services import order_sections
from aslms.services import research_chunks as rc
from tests.db import next_dates_support as h
from tests.db import order_sections_support as o
from tests.fakes.ollama import EMBED_MODEL, FakeOllama

PROFILE = rc.EMBED_PROFILES["embeddinggemma"]
KEY = "embeddinggemma:300m@85462619ee72"
SYNONYMS = {"pension": "retire", "retiral": "retire", "superannuation": "retire", "gratuity": "retire"}

JUDGMENT_BODY = o.JUDGMENT_BODY
PENSION_BODY = (
    "1.      Heard learned counsel for the parties.\n"
    "2.      The petitioner retired as a teacher and his retiral benefits were withheld by the department for\n"
    "want of a vigilance clearance.\n"
    "3.      In view of the above, the respondents are directed to release the retiral benefits of the petitioner\n"
    "within 60 (sixty) days from the date of receipt of a certified copy of this order.\n"
)


def settings(**over) -> Settings:
    base = {
        "assistant_mode": "ollama",
        "assistant_timeout_seconds": 10.0,
        "assistant_ollama_timeout_seconds": 5.0,
        "assistant_ollama_url": "http://127.0.0.1:9",
        "research_index_enabled": True,
        "research_embed_model": EMBED_MODEL,
        "research_job_seconds": 30,
    }
    base.update(over)
    return Settings(_env_file=None, **base)


def fake(**kw) -> FakeOllama:
    kw.setdefault("embed_model", EMBED_MODEL)
    kw.setdefault("synonyms", SYNONYMS)
    return FakeOllama(**kw)


def court_order(
    s: Session,
    case: Case,
    *,
    body: str = o.BODY,
    heading: str = "ORDER",
    kind: OrderKind = OrderKind.INTERIM,
    day: date = date(2026, 1, 28),
    order_no: str | None = None,
) -> Order:
    """A stored court order of `case` with text on the court's template (unique PDF)."""
    text = o.order_text(
        cnr=case.cnr, case_no=case.case_no_text, heading=heading, body=body, day=day.strftime("%d.%m.%Y")
    )
    order = h.order_with_text(s, case, text, order_date=day, order_no=order_no)
    order.kind = kind
    s.flush()
    return order


def read_orders(s: Session) -> dict:
    """Row 250's job, so every order has its current reading."""
    return order_sections.run_job(s)


def reading(s: Session, order: Order) -> OrderSection:
    return order_sections.current_for(s, order.id)


def chunks(s: Session, *, current: bool = True, kind: str | None = None) -> list[ResearchChunk]:
    stmt = sa.select(ResearchChunk).order_by(ResearchChunk.created_at, ResearchChunk.seq)
    if current:
        stmt = stmt.where(ResearchChunk.retired_at.is_(None))
    if kind:
        stmt = stmt.where(ResearchChunk.kind == kind)
    return list(s.scalars(stmt.execution_options(populate_existing=True)).all())


def vectors(s: Session, *, current: bool = True) -> list[ResearchEmbedding]:
    stmt = sa.select(ResearchEmbedding).order_by(ResearchEmbedding.created_at)
    if current:
        stmt = stmt.where(ResearchEmbedding.retired_at.is_(None))
    return list(s.scalars(stmt.execution_options(populate_existing=True)).all())
