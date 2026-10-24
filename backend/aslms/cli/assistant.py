"""`aslms assistant` (design `assistant`, "API"): `status` (the mode, the state, conversations and questions of the
last 24 h); `ask --user EMAIL (--case REF | --my-cases | --research) [--no-related] [--conversation ID] [--json]
"question"` (as that user, with their visibility; stored under the user with `model_info.via = "cli"`, audited as the
system actor `cli` with `after.as_user_id`; refused with `APP_ENV=prod`, exit 2); `check` (stored citations outside the
rule and case conversations without a case; both must be 0, exit 1 otherwise)."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import timedelta

import typer
from rich import print as rprint
from sqlalchemy import func, select

from aslms.core.config import get_settings
from aslms.db.session import get_sessionmaker, session_scope
from aslms.domain.assistant import AssistantConversation, AssistantMessage, MessageRole
from aslms.domain.org import User
from aslms.integration.sourcetrace import connector_state
from aslms.services import assistant as svc
from aslms.services.audit import Actor
from aslms.services.cases import CaseNotFound, resolve_case_ref
from aslms.services.visibility import NotVisibleCase

assistant_app = typer.Typer(no_args_is_help=True, help="The Case Assistant: status, ask, check")


@assistant_app.command("status")
def status_cmd() -> None:
    """The mode, the state, and the conversations and questions of the last 24 hours."""
    settings = get_settings()
    with session_scope() as s:
        now = s.scalar(select(func.now()))
        since = now - timedelta(hours=24)
        conversations = int(
            s.scalar(
                select(func.count())
                .select_from(AssistantConversation)
                .where(AssistantConversation.created_at > since)
            )
            or 0
        )
        questions = int(
            s.scalar(
                select(func.count())
                .select_from(AssistantMessage)
                .where(AssistantMessage.role == MessageRole.USER, AssistantMessage.created_at > since)
            )
            or 0
        )
    rprint(
        f"mode: [bold]{settings.assistant_mode}[/bold]  state: [bold]{svc.assistant_state(settings)}[/bold]"
    )
    rprint(f"SourceTrace connector: {connector_state(settings)}")
    rprint(f"last 24 h: {conversations} new conversation(s), {questions} question(s)")


def _print_answer(out: dict) -> None:
    answer = out["answer"]
    rprint(f"outcome: [bold]{answer['outcome']}[/bold]  mode: {answer['mode']}")
    if answer.get("content"):
        typer.echo(answer["content"])  # plain: the excerpts carry [[ ]] highlights
    elif answer.get("hidden_reason"):
        rprint(f"[yellow]{answer['hidden_reason']}[/yellow]")
    for i, c in enumerate(answer.get("citations") or [], start=1):
        what = c.get("doc_type_label") or c.get("source_kind")
        when = c.get("doc_date") or "-"
        number = f" No. {c['order_no']}" if c.get("order_no") else ""
        page = f", page {c['page']}" if c.get("page") else ""
        case = (c.get("case") or {}).get("case_no_text") or (c.get("case") or {}).get("cnr") or "-"
        related = " (related order in another case)" if c.get("related") else ""
        typer.echo(f"[{i}] {what} of {when}{number}{page} - {case}{related}")
        if c.get("passage"):
            typer.echo(f"    {c['passage']}")


@assistant_app.command("ask")
def ask_cmd(
    question: str = typer.Argument(..., help="the question (3 to ASSISTANT_QUESTION_MAX_CHARS characters)"),
    user: str = typer.Option(..., "--user", help="the e-mail of the login to ask as"),
    case: str | None = typer.Option(None, "--case", help="case scope: id, ref_no or CNR"),
    my_cases: bool = typer.Option(False, "--my-cases", help="the user's own cases"),
    research: bool = typer.Option(False, "--research", help="every court order"),
    no_related: bool = typer.Option(False, "--no-related", help="case scope: leave out other cases' orders"),
    conversation: str | None = typer.Option(
        None, "--conversation", help="continue a conversation of the user"
    ),
    as_json: bool = typer.Option(False, "--json", help="print the stored answer as JSON"),
) -> None:
    """Ask as a user, with their visibility. Refused with APP_ENV=prod (exit 2)."""
    settings = get_settings()
    if settings.is_prod:
        rprint("[red]refused:[/red] `aslms assistant ask` is not run with APP_ENV=prod")
        raise typer.Exit(code=2)
    if sum([bool(case), my_cases, research]) != 1:
        raise typer.BadParameter("give exactly one of --case, --my-cases or --research")
    scope = "case" if case else ("my_cases" if my_cases else "research")
    Session = get_sessionmaker()
    with Session() as s:
        login = s.scalar(select(User).where(func.lower(User.email) == user.strip().lower()))
        if login is None or not login.is_active:
            raise typer.BadParameter(f"no active login {user}")
        case_id = None
        if case:
            try:
                case_id = resolve_case_ref(s, case).id
            except CaseNotFound as exc:
                raise typer.BadParameter(str(exc)) from exc
        s.expunge(login)
    try:
        conversation_id = uuid.UUID(conversation) if conversation else None
    except ValueError as exc:
        raise typer.BadParameter("--conversation is a conversation id") from exc
    connector = svc.assistant_connector(settings, Session)
    try:
        result = asyncio.run(
            svc.ask(
                Session,
                Actor.system("cli"),
                login,
                question=question,
                scope=scope,
                case=case_id,
                conversation_id=conversation_id,
                include_related=not no_related,
                connector=connector,
                config=svc.AssistantConfig.from_settings(settings),
                via="cli",
            )
        )
    except svc.AssistantError as exc:
        rprint(f"[red]{exc.code}:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    except (NotVisibleCase, svc.ConversationNotFound) as exc:
        rprint(f"[red]not_found:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    with Session() as s:
        out = {
            "conversation_id": str(result.conversation_id),
            "question": svc.message(s, login, result.question_id),
            "answer": svc.message(s, login, result.answer_id),
        }
    if as_json:
        typer.echo(json.dumps(out, default=str, indent=2))
        return
    rprint(f"conversation: {out['conversation_id']}")
    _print_answer(out)


@assistant_app.command("check")
def check_cmd() -> None:
    """Both counts must be 0; exit code 1 otherwise."""
    with session_scope() as s:
        result = svc.check(s)
    for k, v in result.items():
        rprint(f"{k}: {'[green]' if v == 0 else '[red]'}{v}[/]")
    if any(result.values()):
        raise typer.Exit(code=1)
