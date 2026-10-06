"""`aslms documents extract [--retry-failed] [--document REF] [--batch N]` runs the text extraction by hand;
`aslms documents scan-check` sends the EICAR string (built at run time) and a clean string to the configured
`clamd` and prints the verdicts — the integrator's probe (design documents-uploads)."""

from __future__ import annotations

import typer
from rich import print as rprint

from aslms.core.config import get_settings
from aslms.db.session import session_scope
from aslms.services import text_extract
from aslms.services.documents import resolve_document_ref
from aslms.services.scanner import ScannerUnavailable, eicar_test_string, get_scanner
from aslms.services.storage import LocalStore
from aslms.services.visibility import NotVisibleDocument

documents_app = typer.Typer(no_args_is_help=True, help="Documents: text extraction, scanner probe")


@documents_app.command("extract")
def extract(
    retry_failed: bool = typer.Option(False, "--retry-failed", help="also retry documents marked failed"),
    document: str | None = typer.Option(None, "--document", help="one document: id or ref_no"),
    batch: int = typer.Option(None, "--batch", min=1, max=5000, help="documents per run"),
) -> None:
    """Extract the text of pending (and optionally failed) PDF and DOCX documents into `document_text`."""
    settings = get_settings()
    store = LocalStore(settings.storage_dir)
    with session_scope() as s:
        doc_id = None
        if document:
            try:
                doc_id = resolve_document_ref(s, document).id
            except NotVisibleDocument as exc:
                raise typer.BadParameter(str(exc)) from exc
        counters = text_extract.extract_pending(
            s,
            store,
            batch=batch or settings.text_extract_batch,
            retry_failed=retry_failed or doc_id is not None,
            document_id=doc_id,
        )
    rprint(
        f"claimed {counters['claimed']}: [green]{counters['extracted']} extracted[/green], "
        f"{counters['none']} without text, [red]{counters['failed']} failed[/red]"
    )


@documents_app.command("scan-check")
def scan_check() -> None:
    """Probe the configured clamd with the EICAR test string and a clean string."""
    settings = get_settings()
    scanner = get_scanner(settings)
    rprint(f"clamd at {settings.clamav_host}:{settings.clamav_port}")
    try:
        eicar = scanner.scan(eicar_test_string())
        clean = scanner.scan(b"The writ petition is allowed. No costs.")
    except ScannerUnavailable as exc:
        rprint(f"[red]scanner unavailable:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    rprint(
        f"eicar: {'[red]infected[/red] (' + str(eicar.signature) + ')' if not eicar.clean else '[red]NOT DETECTED[/red]'}"
    )
    rprint(
        f"clean: {'[green]ok[/green]' if clean.clean else '[red]flagged (' + str(clean.signature) + ')[/red]'}"
    )
    if eicar.clean or not clean.clean:
        raise typer.Exit(code=1)
