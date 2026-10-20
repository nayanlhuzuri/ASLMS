"""`aslms ops`: deployment and operations commands (design deployment-checklist, Part A).

`preflight`, `store-check` (design pre-pilot-hardening), `db-guard`, `role-passwords`, `migrate`, `backup`,
`backup-scheduler`, `backup-status`, `restore-check`, `restore`, `repair-jobs`, `load-report`, `sample-cnrs`, `make-cert` and, from Part B, `metrics` (the operations
exporter). None calls NAPIX; none prints a secret."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import typer
from rich import print as rprint

from aslms.core.config import APP_ENV_FATAL, get_settings, is_app_env_error

ops_app = typer.Typer(
    no_args_is_help=True, help="Deployment and operations: preflight, migrations, backups, checks"
)


def _duration(value: str) -> timedelta:
    m = re.fullmatch(r"(\d+)\s*([mhd])", value.strip().lower())
    if not m:
        raise typer.BadParameter(f"not a duration: {value} (use 30m, 6h or 2d)")
    n, unit = int(m[1]), m[2]
    return timedelta(minutes=n) if unit == "m" else timedelta(hours=n) if unit == "h" else timedelta(days=n)


# ------------------------------------------------------------------------------------------------ preflight


@ops_app.command("preflight")
def preflight_cmd(
    component: str = typer.Option("init", "--component", help="init | migrate | backup"),
) -> None:
    """Check the settings (decision 3). With APP_ENV=prod an error stops the start (exit 1); otherwise every finding
    is a warning. A fatal finding (an unknown APP_ENV, a libpq older than 17) stops the start at every APP_ENV
    (design pre-pilot-hardening, decisions 2 and 6). Names the variables, never their values."""
    from pydantic import ValidationError

    from aslms.services import preflight

    try:
        settings = get_settings()
    except ValidationError as exc:
        if is_app_env_error(exc):
            rprint(f"[red]{APP_ENV_FATAL}[/red]")
            raise typer.Exit(1) from None
        raise
    findings = preflight.check(settings, component)
    if settings.aslms_superadmin_password and settings.aslms_superadmin_password.get_secret_value():
        try:
            from aslms.db.session import session_scope

            with session_scope(settings.database_url_sync) as s:
                left = preflight.superadmin_password_left(s, settings)
            if left:
                findings.append(left)
        except Exception:  # noqa: BLE001 — a fresh or unreachable database: the warning does not apply yet
            pass
    for f in findings:
        colour = "red" if f.level in (preflight.FATAL, preflight.ERROR) else "yellow"
        rprint(f"[{colour}]preflight {f.line()}[/{colour}]")
    try:
        preflight.raise_on_errors(findings, settings.is_prod)
    except preflight.PreflightFailed as exc:
        rprint(f"[red]preflight refused the start: {exc}[/red]")
        raise typer.Exit(1) from None
    rprint(f"[green]preflight passed (APP_ENV={settings.app_env}, {len(findings)} warning(s))[/green]")


@ops_app.command("store-check")
def store_check_cmd() -> None:
    """Check that this process (uid 10001 in the image) can write the document store, STORAGE_DIR, and every
    first-level folder in it (design pre-pilot-hardening, decision 3). Creates a missing store. Exit 1 at every
    APP_ENV when a folder is not writable, with the two remedies."""
    from aslms.services import store_check

    result = store_check.check(get_settings().storage_dir)
    if result.ok:
        rprint(f"[green]store-check: {result.root} writable ({result.folders_checked} folders)[/green]")
        return
    rprint(
        f"[red]store-check: {len(result.failed)} folder(s) of {result.root} are not writable by this process; "
        f"the first is {result.failed[0]}[/red]"
    )
    for line in store_check.remedy_lines():
        typer.echo(line)
    raise typer.Exit(1)


# ------------------------------------------------------------------------------------------------ migrations


@ops_app.command("db-guard")
def db_guard_cmd() -> None:
    """Compare the database revision with this build's head (decision 12): migrate a fresh database, pass at head,
    exit 3 when behind (run the `migrate` service), exit 4 when the database is newer."""
    from aslms.services import db_guard

    result = db_guard.guard(get_settings().migrate_url)
    colour = "green" if result.exit_code == 0 else "red"
    rprint(f"[{colour}]db-guard: {result.message}[/{colour}]")
    if result.exit_code:
        raise typer.Exit(result.exit_code)


@ops_app.command("role-passwords")
def role_passwords_cmd() -> None:
    """Set the aslms_app (and, when set, aslms_readonly) password from the environment; the same step as
    `aslms db-roles` (design safety-fixes), which the Compose `init` service runs."""
    from aslms.cli.db import db_roles

    db_roles()


@ops_app.command("migrate")
def migrate_cmd(
    force: bool = typer.Option(False, "--force", help="migrate even while aslms_app sessions are connected"),
) -> None:
    """The explicit upgrade (decision 12): refuse while the application is connected, back up (tag pre-migrate,
    checked with pg_restore --list), `alembic upgrade head`, seed, and the audit row `system.migrated`."""
    from aslms.cli.db import seed
    from aslms.db.session import session_scope
    from aslms.services import backups, db_guard

    settings = get_settings()
    url = settings.migrate_url
    sessions = db_guard.count_app_sessions(url)
    if sessions and not force:
        rprint(
            f"[red]migrate: {sessions} aslms_app session(s) are connected. Run: docker compose stop api worker "
            "scheduler web pgbouncer (or pass --force)[/red]"
        )
        raise typer.Exit(2)
    before = db_guard.current_revision(url)
    try:
        record = backups.run_backup(
            url,
            settings.backup_dir,
            settings.storage_dir,
            backups.RetentionPolicy.from_settings(settings),
            tag=backups.PREMIGRATE,
        )
    except backups.BackupError as exc:
        rprint(f"[red]migrate: the backup failed, nothing was migrated: {exc}[/red]")
        raise typer.Exit(1) from None
    rprint(f"backup {record['set']} written and listed by pg_restore")
    db_guard.upgrade_head(url)
    seed(url=url)
    after = db_guard.current_revision(url)
    with session_scope(url) as s:
        db_guard.write_migrated_audit(s, before, after, record["set"])
    rprint(f"[green]migrate: {before} -> {after}; audit row system.migrated written[/green]")


# ------------------------------------------------------------------------------------------------ backups


@ops_app.command("backup")
def backup_cmd(
    tag: str | None = typer.Option(None, "--tag", help="a label for the set (e.g. before-upgrade)"),
) -> None:
    """One backup now: database dump, roles, manifest, store mirror, retention, status files and a job_runs row."""
    from aslms.services import backups

    s = get_settings()
    try:
        record = backups.run_backup(
            s.migrate_url, s.backup_dir, s.storage_dir, backups.RetentionPolicy.from_settings(s), tag=tag
        )
    except backups.BackupError as exc:
        rprint(f"[red]backup failed: {exc}[/red]")
        raise typer.Exit(1) from None
    rprint(f"[green]backup {record['set']} {record['status']}[/green] {json.dumps(record['counters'])}")


@ops_app.command("backup-scheduler")
def backup_scheduler_cmd() -> None:
    """The `backup` service: backups at minute 30 every BACKUP_INTERVAL_HOURS hours (IST) and the restore check on
    Sunday at 04:30 IST, for ever."""
    from aslms.services import backups

    backups.scheduler_loop(get_settings())


@ops_app.command("backup-status")
def backup_status_cmd() -> None:
    """The last backup, the last successful one and the last restore check (from BACKUP_DIR/status)."""
    from aslms.services import backups

    s = get_settings()
    for name in ("last", "last-success", "restore-check"):
        data = backups.read_status(s.backup_dir, name)
        if data is None:
            rprint(f"{name}: none")
            continue
        rprint(
            f"{name}: {data.get('status')} at {data.get('finished_at')} "
            f"{data.get('set') or data.get('dump') or ''} {json.dumps(data.get('counters') or {})}"
        )
        if data.get("error"):
            rprint(f"  error: {data['error']}")


@ops_app.command("restore-check")
def restore_check_cmd(
    dump: Path | None = typer.Option(None, "--dump", help="default: the latest dump"),
) -> None:
    """Restore a dump into the scratch database aslms_restore_check and compare it with its manifest (decision 14)."""
    from aslms.services import backups

    s = get_settings()
    try:
        result = backups.restore_check(s.migrate_url, s.backup_dir, dump)
    except backups.BackupError as exc:
        rprint(f"[red]restore check failed: {exc}[/red]")
        raise typer.Exit(1) from None
    rprint(
        f"restore check of {result.dump}: revision {result.revision}, {result.tables_compared} tables compared, "
        f"{len(result.mismatches)} mismatch(es), {result.files_checked} files checked, {result.files_bad} bad, "
        f"{result.seconds} s"
    )
    for m in result.mismatches:
        rprint(f"  [red]{m}[/red]")
    if not result.ok:
        raise typer.Exit(1)


@ops_app.command("restore")
def restore_cmd(
    dump: Path = typer.Option(..., "--dump"),
    roles: Path = typer.Option(..., "--roles"),
    confirm_overwrite: str = typer.Option(..., "--confirm-overwrite", help="the database name, to confirm"),
    store_from: Path | None = typer.Option(
        None, "--store-from", help="the store mirror to copy back (add-only)"
    ),
) -> None:
    """The disaster restore (decision 14): roles, the database from the dump, the store from the mirror, and the audit
    row system.restored. Refused while aslms_app is connected."""
    from aslms.services import backups

    s = get_settings()
    try:
        out = backups.restore(
            s.migrate_url,
            dump,
            roles,
            confirm_overwrite=confirm_overwrite,
            store_from=store_from,
            store_dir=s.storage_dir if store_from else None,
        )
    except backups.BackupError as exc:
        rprint(f"[red]restore refused or failed: {exc}[/red]")
        raise typer.Exit(1) from None
    rprint(
        f"[green]restored {out['dump']} (revision {out['revision']}); {out['store_files_copied']} store files[/green]"
    )


# ------------------------------------------------------------------------------------------------ housekeeping


@ops_app.command("repair-jobs")
def repair_jobs_cmd(
    older_than: str = typer.Option("6h", "--older-than", help="only rows started longer ago than this"),
    job: str | None = typer.Option(None, "--job", help="one job name (default: every known job)"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Mark `job_runs` rows left `running` as failed (decision 18). Do not run it while a job is genuinely running."""
    from aslms.db.session import session_scope
    from aslms.services.job_repair import ALL_SETS, repair_interrupted

    jobs = {job} if job else set().union(*ALL_SETS.values())
    before = datetime.now(UTC) - _duration(older_than)
    with session_scope() as s:
        n = repair_interrupted(s, jobs, before, "repaired by hand (aslms ops repair-jobs)", dry_run=dry_run)
    rprint(f"{'would repair' if dry_run else 'repaired'} {n} row(s)")


@ops_app.command("load-report")
def load_report_cmd(fmt: str = typer.Option("md", "--format", help="md | json")) -> None:
    """The load counts (decision 19). Read-only; no NAPIX call."""
    from aslms.db.session import session_scope
    from aslms.services import load_report

    with session_scope() as s:
        r = load_report.report(s, store_dir=get_settings().storage_dir)
    print(json.dumps(r, indent=2, default=str) if fmt == "json" else load_report.report_markdown(r))


@ops_app.command("sample-cnrs")
def sample_cnrs_cmd(
    pending: int = typer.Option(10, "--pending"),
    disposed: int = typer.Option(10, "--disposed"),
    seed: int = typer.Option(0, "--seed"),
    fmt: str = typer.Option("md", "--format", help="md | json"),
) -> None:
    """A reproducible sample of cases to check by hand against the court's public case status (decision 19)."""
    from aslms.db.session import session_scope
    from aslms.services import load_report

    with session_scope() as s:
        rows = load_report.sample(s, pending, disposed, seed)
    print(
        json.dumps(rows, indent=2, default=str) if fmt == "json" else load_report.sample_markdown(rows, seed)
    )


@ops_app.command("make-cert")
def make_cert_cmd(
    host: str = typer.Option(..., "--host", help="the portal's host name on the network"),
    ip: list[str] = typer.Option([], "--ip", help="an address of the host (repeatable)"),
    out: Path = typer.Option(Path("infra/proxy/certs"), "--out"),
) -> None:
    """An internal CA and a server certificate for the proxy (decision 7)."""
    from aslms.services.certs import make_cert

    try:
        files = make_cert(host, out, ip)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from None
    rprint(f"[green]wrote {files.fullchain}, {files.privkey}, {files.ca_cert} and {files.ca_key}[/green]")
    rprint(
        "Install ca.crt once on each pilot PC (Trusted Root Certification Authorities), then move ca.key off this "
        "host to safe storage: it can sign certificates every pilot PC trusts."
    )


# ------------------------------------------------------------------------------------------------ monitoring


@ops_app.command("metrics")
def metrics_cmd(
    port: int = typer.Option(9108, "--port", help="the port Prometheus scrapes"),
    addr: str = typer.Option("0.0.0.0", "--addr", help="the address to listen on"),
    once: bool = typer.Option(False, "--once", help="print one reading and exit"),
) -> None:
    """The operations exporter (Part B, decision 23): queue, jobs, worker liveness, NAPIX window, mail, backups,
    disk, ClamAV signatures, portal probe and certificate expiry, as Prometheus gauges. Read-only: run it as
    aslms_readonly (the Compose `ops-exporter` service). Readings are cached for OPS_METRICS_CACHE_SECONDS."""
    from aslms.db.session import get_sessionmaker
    from aslms.services import ops_metrics

    settings = get_settings()
    if once:
        collector = ops_metrics.OpsCollector(settings, get_sessionmaker(settings.database_url_sync))
        typer.echo(ops_metrics.render(collector), nl=False)
        return
    rprint(f"ops metrics on {addr}:{port} (cache {settings.ops_metrics_cache_seconds} s)")
    ops_metrics.serve(settings, port, addr)
