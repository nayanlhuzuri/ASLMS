"""`aslms orders` (design `order-sections`, "CLI"): court orders read into their parts by rules, with no AI.

- `parse [--backfill] [--full] [--order <uuid>] [--limit N] [--batch N] [--pause-ms N] [--dry-run]`: without
  `--backfill`, one light batch, as the 5-minute job does between its daily full checks; with it, light batches until
  none is left, then the full check's sets and the retries, one commit per batch and a pause between them (stopped
  and started again, it carries on). `--full` runs one batch with the full check (changed documents, changed texts by
  hash, texts gone, stale failures) and the retries at once: the step after any manual re-extraction (design
  `order-sections-review-advisories`, decision 6). `--order` checks every set for that one order. `--dry-run` parses
  and counts (layout, form, flags, citations by reporter, the time) and writes nothing.
- `status`: the data-health block (`timed_out` names a part that ran out of time).
- `show <order uuid | CNR|order_no|YYYY-MM-DD> [--text]`: the layout, spans with pages, paragraphs with part and page,
  facts, flags and live checks; `--text` also prints the body. When the stored text changed since the reading, the
  pages are replaced by a note (decision 11).
- `checks [--check <name>] [--limit N]`: the check list (identifiers and printed values only).

No NAPIX call and no audit row: system work on derived data, as `aslms next-dates read`."""

from __future__ import annotations

import json
import uuid

import typer
from rich import print as rprint

from aslms.core.config import get_settings
from aslms.db.session import get_sessionmaker, session_scope
from aslms.domain.documents import DocumentText
from aslms.services import order_parse, order_sections
from aslms.services.reporting_common import with_timeout

orders_app = typer.Typer(
    no_args_is_help=True, help="Court orders read into their parts by rules: parse, status, show"
)


def _jsonable(obj):
    return json.loads(json.dumps(obj, default=str))


@orders_app.command("parse")
def parse(
    backfill: bool = typer.Option(False, "--backfill", help="every order waiting, batch after batch"),
    full: bool = typer.Option(
        False,
        "--full",
        help="one batch with the daily full check and the retries now (after a re-extraction)",
    ),
    order: str | None = typer.Option(None, "--order", help="one order (its id)"),
    limit: int | None = typer.Option(None, "--limit", min=1, help="at most this many orders"),
    batch: int | None = typer.Option(
        None, "--batch", min=1, max=5000, help="orders per batch (ORDER_SECTIONS_BATCH)"
    ),
    pause_ms: int = typer.Option(200, "--pause-ms", min=0, max=60000, help="pause between batches"),
    dry_run: bool = typer.Option(False, "--dry-run", help="parse and count; write nothing"),
) -> None:
    """Read court orders' stored text into their parts (one savepoint per order)."""
    size = batch or get_settings().order_sections_batch
    order_id = None
    if order:
        try:
            order_id = uuid.UUID(order)
        except ValueError as exc:
            raise typer.BadParameter("--order takes an order id") from exc
    if dry_run:
        order_sections.DRY_STATS.reset()
        totals = order_sections.backfill(
            get_sessionmaker(),
            batch=min(size, limit or size),
            pause_ms=0,
            limit=limit or size,
            dry_run=True,
            echo=rprint if backfill else None,
        )
        stats = order_sections.DRY_STATS.as_dict()
        per_1000 = round(stats["seconds"] / max(totals["parsed"], 1) * 1000, 2)
        rprint({"dry_run": True, **totals, **stats, "seconds_per_1000": per_1000})
        return
    if order_id is not None:
        with session_scope() as s:
            rprint(order_sections.read_batch(s, batch=1, order_id=order_id))
        return
    if full and not backfill:
        with session_scope() as s:
            rprint(order_sections.read_batch(s, batch=min(size, limit or size), full=True, retry=True))
        return
    if backfill:
        totals = order_sections.backfill(
            get_sessionmaker(), batch=size, pause_ms=pause_ms, limit=limit, echo=rprint
        )
        rprint(totals)
        return
    with session_scope() as s:
        rprint(order_sections.read_batch(s, batch=min(size, limit or size)))


@orders_app.command("status")
def status() -> None:
    """The order readings' block of the data-health screen."""
    with session_scope() as s:
        cfg = get_settings()
        with_timeout(s, cfg.report_statement_timeout_seconds)
        rprint(
            _jsonable(
                order_sections.status(
                    s,
                    timeout_s=cfg.order_sections_status_timeout_seconds,
                    restore_s=cfg.report_statement_timeout_seconds,
                )
            )
        )


@orders_app.command("show")
def show(
    ref: str = typer.Argument(..., help="an order id, or CNR|order_no|YYYY-MM-DD"),
    text: bool = typer.Option(False, "--text", help="also print the body"),
) -> None:
    """One order's current reading: spans with pages, paragraphs, facts, flags and the live checks."""
    with session_scope() as s:
        order = order_sections.resolve_order(s, ref)
        if order is None:
            rprint("[red]no such order[/red]")
            raise typer.Exit(1)
        row = order_sections.current_for(s, order.id)
        if row is None:
            rprint("[yellow]this order has not been read yet[/yellow]")
            raise typer.Exit(1)
        stored = s.get(DocumentText, row.document_id)
        full_text = stored.full_text if stored is not None else None
        same = order_sections.text_matches(row, full_text)
        pm = order_parse.pages(full_text or "") if same else None
        changed = "text changed since this reading; run `aslms orders parse --full`"
        spans = {
            name: {"src": span, "page": pm.page(span[0]) if pm else changed}
            for name, span in (row.spans or {}).items()
        }
        out = {
            "order_id": order.id,
            "document_id": row.document_id,
            "pdf_sha256": row.pdf_sha256[:12],
            "parser_version": row.parser_version,
            "layout": row.layout,
            "form": row.form,
            "heading": row.heading,
            "printed": {
                "cnr": row.printed_cnr,
                "case_no": row.printed_case_no,
                "date": row.printed_date,
                "reserved_on": row.printed_reserved_on,
                "pronounced_on": row.printed_pronounced_on,
                "neutral_citation": row.neutral_citation,
                "author": row.author,
            },
            "registrar": row.registrar,
            "procedural": row.procedural,
            "outcome": row.outcome,
            "flags": list(row.flags or []),
            "checks": order_sections.checks_for(s, order.id),
            "spans": spans,
            "linked_cases": row.linked_cases,
            "paragraphs": [
                {k: p.get(k) for k in ("i", "label", "part", "page", "page_to", "src", "txt")}
                for p in row.paragraphs
            ],
            "parts": row.parts,
            "facts": row.facts,
        }
        rprint(_jsonable(out))
        if text:
            print(row.body_text)


@orders_app.command("checks")
def checks(
    check: str | None = typer.Option(None, "--check", help="one check or flag name"),
    limit: int = typer.Option(50, "--limit", min=1, max=200),
) -> None:
    """The readings that differ from what is held, or carry a flag about the text."""
    with session_scope() as s:
        with_timeout(s, get_settings().report_statement_timeout_seconds)
        try:
            total, counts, items = order_sections.check_rows(s, check=check, limit=limit)
        except order_sections.CheckInputError as exc:
            raise typer.BadParameter(str(exc)) from exc
    rprint({"total": total, "counts": counts})
    for it in items:
        rprint(
            f"{it['case']['ref_no']}  {it['case']['cnr'] or '-'}  order {it['order_no']} of {it['order_date']}  "
            f"{', '.join(it['checks'] + it['flags'])}  printed {it['printed']['cnr'] or '-'} / "
            f"{it['printed']['case_no'] or '-'} / {it['printed']['date'] or '-'}"
        )
