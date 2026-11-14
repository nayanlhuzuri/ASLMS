"""`aslms offices …`: departments, directorates and units from the command line, so a fresh deployment can be
bootstrapped without the portal. Acts as the single active super admin (required: every office write is
attributed and audited to a user). A department is created with its head (`--head-email`, an existing login,
including one created with `aslms users create --no-office`; design `office-head-picker`, decision 21);
`list --missing-head` lists departments without one. `import` reads the owner's workbook of departments, offices and
their people (design `offices-import`): a dry run by default, `--apply --expect FINGERPRINT` to write."""

from __future__ import annotations

import sys
from pathlib import Path

import typer
from rich import print as rprint
from rich.markup import escape
from rich.tree import Tree

from aslms.cli.users import _actor, _office
from aslms.db.session import get_sessionmaker, session_scope
from aslms.domain.reference import OfficeKind
from aslms.services import memberships, offices
from aslms.services.access import Conflict, Forbidden
from aslms.services.memberships import MembershipError
from aslms.services.offices import DEPARTMENT_TIER_KINDS, OfficeError
from aslms.services.tickets import TicketError
from aslms.services.users import UserError

offices_app = typer.Typer(no_args_is_help=True, help="Offices: create, list, deactivate")


def _super_admin(session):
    actor, actor_user = _actor(session)
    if actor_user is None:
        raise typer.BadParameter("there is no super admin yet; run `aslms users create-super-admin` first")
    return actor, actor_user


@offices_app.command("create")
def create(
    code: str = typer.Option(..., "--code", help="the Secretariat's code, e.g. EDU or EDU-DSE"),
    name: str = typer.Option(..., "--name"),
    kind: str = typer.Option(..., "--kind", help="one of: " + ", ".join(k.value for k in OfficeKind)),
    parent: str = typer.Option(..., "--parent", help="parent office code (GOA for a department)"),
    notes: str | None = typer.Option(None, "--notes"),
    head_email: str | None = typer.Option(
        None, "--head-email", help="the head, an existing login (required for a department)"
    ),
    head_designation: str | None = typer.Option(None, "--head-designation"),
) -> None:
    """Create an office under a parent (acting as the super admin). A Department-tier office needs its head: an
    existing login by e-mail, including one with no office yet."""
    with session_scope() as s:
        actor, actor_user = _super_admin(s)
        head = None
        try:
            dept_tier = OfficeKind(kind) in DEPARTMENT_TIER_KINDS
        except ValueError:
            dept_tier = False
        if dept_tier:
            if not head_email:
                raise typer.BadParameter(
                    "head_required: a department is created with its head (--head-email)"
                )
            if memberships.lookup(s, head_email) is None:
                raise typer.BadParameter(
                    f"no login {head_email}: add the person first with `aslms users create --no-office`"
                )
            head = {"email": head_email, "designation": head_designation}
        try:
            office = offices.create_office(
                s,
                actor,
                actor_user,
                code=code,
                name=name,
                kind=kind,
                parent=_office(s, parent),
                notes=notes,
                head={k: v for k, v in head.items() if v is not None} if head else None,
            )
        except (OfficeError, Forbidden, Conflict, MembershipError, TicketError, UserError) as exc:
            raise typer.BadParameter(str(exc)) from exc
        rprint(f"[green]created {office.code} ({office.kind.value}) at {office.path}[/green]")


@offices_app.command("list")
def list_offices(
    root: str = typer.Option("GOA", "--root", help="office code to start from"),
    include_inactive: bool = typer.Option(True, "--all/--active-only", help="show deactivated offices"),
    missing_head: bool = typer.Option(False, "--missing-head", help="only departments without a head"),
) -> None:
    """Print the office tree; deactivated offices are marked. `--missing-head`: the departments without a
    head (design `user-memberships`, decision 24)."""
    with session_scope() as s:
        if missing_head:
            rows = offices.departments_without_head(s)
            for o in rows:
                rprint(f"{o.code}  {o.name}")
            rprint(f"[bold]{len(rows)}[/bold] department(s) without a head")
            return
        top = offices.office_tree(s, [_office(s, root)], include_inactive=include_inactive)

        def add(branch: Tree, node: offices.OfficeNode) -> None:
            o = node.office
            state = "" if o.is_active else " [red](inactive)[/red]"
            users = f" [dim]{node.users_active} users[/dim]" if node.users_active else ""
            leaf = branch.add(
                f"[bold]{o.code}[/bold] {o.name} [dim]({o.kind.value}, {node.tier})[/dim]{users}{state}"
            )
            for child in node.children:
                add(leaf, child)

        for node in top:
            tree = Tree(
                f"[bold]{node.office.code}[/bold] {node.office.name} [dim]({node.office.kind.value})[/dim]"
                + ("" if node.office.is_active else " [red](inactive)[/red]")
            )
            for child in node.children:
                add(tree, child)
            rprint(tree)


@offices_app.command("deactivate")
def deactivate(code: str) -> None:
    """Deactivate an office (refused while children, memberships, ownership or custody still point at it)."""
    with session_scope() as s:
        actor, actor_user = _super_admin(s)
        try:
            office = offices.deactivate_office(s, actor, actor_user, _office(s, code))
        except (OfficeError, Forbidden) as exc:
            raise typer.BadParameter(str(exc)) from exc
        rprint(f"[yellow]{office.code} deactivated (valid_to {office.valid_to})[/yellow]")


# ------------------------------------------------------------------------------------------------ import
# design offices-import, decisions 7, 20 and 22. Exit codes: 0 done (or a clean dry run), 1 errors, 2 a bad file,
# 3 the fingerprint does not match, 4 mail is not ready, 5 no super admin.
EXIT_ERRORS, EXIT_FILE, EXIT_FINGERPRINT, EXIT_MAIL, EXIT_NO_SUPER_ADMIN = 1, 2, 3, 4, 5


def _session_factory():
    """The session factory of the import (tests point it at their database)."""
    return get_sessionmaker()


def _mailer(settings):
    """The configured mailer (tests give a recording one)."""
    from aslms.services.mailer import get_mailer

    return get_mailer(settings)


def _read_file(file: str) -> bytes:
    from aslms.services.offices_import import MAX_BYTES

    if file == "-":
        data = sys.stdin.buffer.read(MAX_BYTES + 1)
    else:
        path = Path(file)
        if not path.is_file():
            rprint(f"[red]no file {escape(file)}[/red]")
            raise typer.Exit(EXIT_FILE)
        if path.stat().st_size > MAX_BYTES:
            rprint("[red]bad file: the file is larger than 5 MB[/red]")
            raise typer.Exit(EXIT_FILE)
        data = path.read_bytes()
    return data


def _print_plan(plan, fp: str) -> None:
    """Problems by sheet, row and column (masked e-mails only, never a name or a mobile), the plan and the
    fingerprint."""
    for title, colour, items in (("Errors", "red", plan.errors), ("Notices", "yellow", plan.notices)):
        if items:
            rprint(f"[bold {colour}]{title} ({len(items)})[/bold {colour}]")
            for p in items:
                rprint(f"  {escape(p.where())}: {escape(p.message)} [dim]({p.code})[/dim]")
    if plan.skips:
        by_code: dict[str, list[str]] = {}
        for p in plan.skips:
            by_code.setdefault(p.code, []).append(f"{p.sheet.split()[0]} {p.row}")
        rprint(f"[bold]Skipped ({len(plan.skips)})[/bold]")
        for code, rows in sorted(by_code.items()):
            rprint(f"  {code}: {len(rows)} row(s): {escape(', '.join(rows))}")
    c = plan.counts()
    created = [a.code for a in plan.departments if a.action == "create"]
    offices_created = [a.code for a in plan.offices if a.action == "create"]
    rprint("[bold]Plan[/bold]")
    rprint(
        f"  departments: {c['departments_created']} to create ({c['departments_no_head_yet']} with No Head Yet), "
        f"{c['departments_matched']} already there, {c['departments_renamed']} to rename"
    )
    if created:
        rprint(f"    {escape(', '.join(created))}")
    rprint(
        f"  offices: {c['offices_created']} to create, {c['offices_matched']} already there, "
        f"{c['offices_renamed']} to rename"
    )
    if offices_created:
        rprint(f"    {escape(', '.join(offices_created))}")
    rprint(f"  logins: {c['logins_created']} to create, {c['logins_matched']} already there")
    rprint(
        f"  heads: {c['heads']}, Department Administrators: {c['admins']}, office heads: {c['office_heads']}"
    )
    rprint(f"  designations to add: {c['designations_created']}")
    for d in plan.new_designations:
        rprint(f"    {escape(d.code)}: {escape(d.name)}")
    if not plan.has_changes:
        rprint("  nothing to change")
    rprint(f"[bold]Fingerprint: {fp}[/bold]")


@offices_app.command("import")
def import_offices(
    file: str = typer.Argument(..., help="the workbook (.xlsx), or - to read it from standard input"),
    apply: bool = typer.Option(False, "--apply", help="write; needs --expect with the dry run's fingerprint"),
    expect: str | None = typer.Option(None, "--expect", help="the fingerprint the dry run printed"),
    no_welcome: bool = typer.Option(False, "--no-welcome", help="send no welcome e-mails in this run"),
) -> None:
    """Check the workbook of departments, offices and their people (a dry run that writes nothing), or with
    `--apply --expect FINGERPRINT` import it in one audited run (acting as the Super Administrator)."""
    import uuid6

    from aslms.core.config import get_settings
    from aslms.services import offices_import as imp
    from aslms.services.mailer import MailError
    from aslms.services.otp import MailNotConfigured, ensure_mail_ready

    if apply and not expect:
        raise typer.BadParameter("--apply needs --expect with the fingerprint of the dry run")
    data = _read_file(file)
    try:
        wb = imp.read_workbook(data)
    except imp.ImportFileError as exc:
        rprint(f"[red]bad file: {escape(str(exc))}[/red]")
        raise typer.Exit(EXIT_FILE) from exc
    factory = _session_factory()
    if not apply:
        with factory() as s:
            try:
                imp.import_actor(s, uuid6.uuid7())
            except imp.NoSuperAdmin as exc:
                rprint(f"[red]{escape(str(exc))}[/red]")
                raise typer.Exit(EXIT_NO_SUPER_ADMIN) from exc
            plan = imp.check(s, wb)
            s.rollback()
        _print_plan(plan, imp.fingerprint(wb.sha256, plan))
        if plan.errors:
            rprint("[red]dry run: errors found; fix the workbook and run the dry run again[/red]")
            raise typer.Exit(EXIT_ERRORS)
        rprint("dry run: nothing was written. To import, run again with --apply --expect <fingerprint>.")
        return
    settings = get_settings()
    mailer = None
    if not no_welcome:
        try:
            mailer = _mailer(settings)
            ensure_mail_ready(mailer, settings)
        except (MailError, MailNotConfigured) as exc:
            rprint(
                f"[red]mail is not ready ({exc.__class__.__name__}): new logins could not sign in; set up mail or "
                "run with --no-welcome[/red]"
            )
            raise typer.Exit(EXIT_MAIL) from exc
    run_id = uuid6.uuid7()
    try:
        result = imp.run_apply(factory, wb, expect=expect, run_id=run_id, mailer=mailer, settings=settings)
    except imp.NoSuperAdmin as exc:
        rprint(f"[red]{escape(str(exc))}[/red]")
        raise typer.Exit(EXIT_NO_SUPER_ADMIN) from exc
    except imp.ImportErrors as exc:
        _print_plan(exc.plan, imp.fingerprint(wb.sha256, exc.plan))
        rprint(f"[red]{escape(str(exc))}[/red]")
        raise typer.Exit(EXIT_ERRORS) from exc
    except imp.PlanChanged as exc:
        rprint(f"[red]{escape(str(exc))}[/red]")
        raise typer.Exit(EXIT_FINGERPRINT) from exc
    if not result.changed:
        rprint("nothing to change")
        return
    c = result.counts
    rprint(
        f"[green]imported (run {run_id}): {c['departments_created']} department(s) and {c['offices_created']} "
        f"office(s) created, {c['logins_created']} login(s) created, {c['heads']} head(s), {c['admins']} "
        f"administrator(s), {c['office_heads']} office head(s), {c['designations_created']} designation(s) "
        "added[/green]"
    )
    rprint(f"Audit Log: user agent `{imp.USER_AGENT} {run_id}`")
    if result.welcome:
        rprint(f"welcome e-mails: {result.welcome['sent']} sent, {result.welcome['failed']} not sent")
        if result.welcome["failed"]:
            rprint("[yellow]send the rest with `aslms users welcome --pending`[/yellow]")
    elif no_welcome and result.created_login_ids:
        rprint(
            "[yellow]no welcome e-mails sent (--no-welcome); send them with `aslms users welcome --pending`[/yellow]"
        )
