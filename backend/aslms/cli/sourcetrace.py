"""`aslms sourcetrace` (design `sourcetrace-connector`, "API"): `status`; `run [--batch N] [--document ID]` (refused
unless a real connector is ready); `retry --document ID` / `retry --all-failed` (system actor `cli`, audited);
`check` (documents breaking the sending rule and ingestion rows of unsendable documents; both must be 0)."""

from __future__ import annotations

from dataclasses import replace

import typer
from rich import print as rprint

from aslms.core.config import get_settings
from aslms.db.session import get_sessionmaker, session_scope
from aslms.integration.sourcetrace import connector_state, get_connector
from aslms.services import sourcetrace_ingest as svc
from aslms.services.audit import Actor
from aslms.services.documents import resolve_document_ref
from aslms.services.storage import LocalStore
from aslms.services.visibility import NotVisibleDocument

sourcetrace_app = typer.Typer(no_args_is_help=True, help="SourceTrace ingestion: status, run, retry, check")


@sourcetrace_app.command("status")
def status_cmd() -> None:
    """The connector state, counts by status, filings waiting for a CNR, documents due now, the last run."""
    settings = get_settings()
    with session_scope() as s:
        st = svc.status(s, settings)
    rprint(f"state: [bold]{st['state']}[/bold]  connector: {st['connector'] or '-'}")
    c = st["counts"]
    rprint(
        f"pending {c['pending']}  ingested {c['ingested']}  failed {c['failed']}  "
        f"not_applicable {c['not_applicable']}  (orders and uploads)"
    )
    rprint(f"waiting for a CNR {st['waiting_cnr']}  due now {st['due_now']}")
    rprint(f"oldest pending: {st['oldest_pending_at'] or '-'}")
    last = st["last_run"]
    rprint(
        f"last run: {last['started_at']} {last['status']} {last['counters']}" if last else "last run: none"
    )


@sourcetrace_app.command("run")
def run_cmd(
    batch: int = typer.Option(None, "--batch", min=1, max=1000, help="documents in this run"),
    document: str | None = typer.Option(None, "--document", help="one document: id or ref_no"),
) -> None:
    """Send due documents now. Refused unless the state is `ready` (no connector exists yet)."""
    settings = get_settings()
    state = connector_state(settings)
    connector = get_connector(settings) if state == "ready" else None
    if connector is None:
        rprint(f"[red]refused:[/red] the SourceTrace connector is {state}; nothing was sent")
        raise typer.Exit(code=1)
    config = svc.IngestConfig.from_settings(settings)
    if batch:
        config = replace(config, batch=batch)
    doc_id = None
    if document:
        with session_scope() as s:
            try:
                doc_id = resolve_document_ref(s, document).id
            except NotVisibleDocument as exc:
                raise typer.BadParameter(str(exc)) from exc
    counters = svc.run(
        get_sessionmaker(), connector, LocalStore(settings.storage_dir), config, document_id=doc_id
    )
    rprint(counters)


@sourcetrace_app.command("retry")
def retry_cmd(
    document: str | None = typer.Option(None, "--document", help="one document: id or ref_no"),
    all_failed: bool = typer.Option(False, "--all-failed", help="every failed document"),
) -> None:
    """Put a failed document (or every failed document) back in the queue; audited."""
    if bool(document) == bool(all_failed):
        raise typer.BadParameter("give exactly one of --document or --all-failed")
    actor = Actor.system("cli")
    with session_scope() as s:
        if all_failed:
            n = svc.retry_all_failed(s, actor)
            rprint(f"{n} failed document(s) back to pending")
            return
        try:
            doc = resolve_document_ref(s, document)
        except NotVisibleDocument as exc:
            raise typer.BadParameter(str(exc)) from exc
        try:
            doc = svc.retry(s, actor, None, doc)
        except svc.NotRetryable as exc:
            rprint(f"[red]{exc}[/red]")
            raise typer.Exit(code=1) from exc
        rprint(f"{doc.ref_no or doc.id}: pending, attempts 0")


@sourcetrace_app.command("check")
def check_cmd() -> None:
    """Both counts must be 0; exit code 1 otherwise."""
    with session_scope() as s:
        result = svc.check(s)
    for k, v in result.items():
        rprint(f"{k}: {'[green]' if v == 0 else '[red]'}{v}[/]")
    if any(result.values()):
        raise typer.Exit(code=1)
