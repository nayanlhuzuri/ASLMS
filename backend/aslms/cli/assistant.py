"""`aslms assistant` (design `assistant`, "API"): `status` (the mode, the state, conversations and questions of the
last 24 h, and in ollama mode the engine); `ask --user EMAIL (--case REF | --my-cases | --research) [--no-related]
[--conversation ID] [--json] "question"` (as that user, with their visibility; stored under the user with
`model_info.via = "cli"`, audited as the system actor `cli` with `after.as_user_id`; refused with `APP_ENV=prod`, exit
2); `check` (the five counts of design `assistant-ollama`, "Data"; all must be 0, exit 1 otherwise).

Design `assistant-ollama`: `warm` loads the local model now; `include-internal --user EMAIL --case REF
[--conversation ID]` switches on that user's case-tab conversation's internal records (dev and test only, refused in
prod with exit 2; audited as the system actor `cli` with `as_user_id`). `ask --case` reads internal records only in a
conversation switched on, with the named user's own sight."""

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
from aslms.integration.ollama import OllamaClient
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
    if svc.portal_mode(settings) == "ollama":
        state = OllamaClient(settings.assistant_ollama_url).state_sync(settings.assistant_ollama_model)
        readiness = "ready" if state.ready else ("loading" if state.held and state.local else "unavailable")
        rprint(
            f"engine: ollama  model: {settings.assistant_ollama_model}  readiness: {readiness}"
            f"  reason: {state.reason or '-'}  version: {state.version or '-'}  on GPU: {state.on_gpu or '-'}"
        )
    rprint(f"last 24 h: {conversations} new conversation(s), {questions} question(s)")


@assistant_app.command("warm")
def warm_cmd() -> None:
    """Load the local model now and keep it loaded (ASSISTANT_OLLAMA_KEEP_ALIVE); waits up to 300 s."""
    settings = get_settings()
    if svc.portal_mode(settings) != "ollama":
        rprint(
            "[yellow]ASSISTANT_MODE is not ollama (or the model setting is refused); nothing to warm[/yellow]"
        )
        raise typer.Exit(code=1)
    from aslms.services.assistant_ollama import OllamaConnector

    connector = OllamaConnector(get_sessionmaker(), settings)
    try:
        state = connector.warm()
    except Exception as exc:  # noqa: BLE001 - the class name only (a message could carry the address)
        rprint(f"[red]the model could not be loaded:[/red] {type(exc).__name__}")
        raise typer.Exit(code=1) from exc
    rprint(
        f"model {settings.assistant_ollama_model}: loaded={state.loaded} on GPU={state.on_gpu or '-'} "
        f"version={state.version or '-'}"
    )
    if not state.loaded:
        raise typer.Exit(code=1)


def _print_answer(out: dict) -> None:
    answer = out["answer"]
    rprint(f"outcome: [bold]{answer['outcome']}[/bold]  mode: {answer['mode']}")
    if answer.get("content"):
        typer.echo(answer["content"])  # plain: the excerpts carry [[ ]] highlights
    elif answer.get("hidden_reason"):
        rprint(f"[yellow]{answer['hidden_reason']}[/yellow]")
    for i, c in enumerate(answer.get("citations") or [], start=1):
        if c.get("label"):  # a local-model answer: label, kind and whether it is cited
            mark = "cited" if c.get("cited", True) else "not cited"
            internal = " (Internal)" if c.get("internal") else ""
            where = (c.get("case") or {}).get("case_no_text") or (c.get("case") or {}).get("cnr") or "-"
            typer.echo(
                f"[{c['label']}] {c.get('source_kind')}{internal} {mark} - {where} {c.get('doc_date') or '-'}"
            )
            continue
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
    if out["answer"].get("suggest_internal"):
        rprint("[cyan]suggest_internal: this may be in the case's internal records (include-internal)[/cyan]")


@assistant_app.command("include-internal")
def include_internal_cmd(
    user: str = typer.Option(..., "--user", help="the e-mail of the login whose conversation it is"),
    case: str = typer.Option(..., "--case", help="the case: id, ref_no or CNR"),
    conversation: str | None = typer.Option(
        None, "--conversation", help="the user's case-tab conversation (a new empty one when left out)"
    ),
) -> None:
    """Switch on "Include This Case's Internal Records" for the user's case-tab conversation (design
    assistant-ollama, decision 4). Dev and test only: refused with APP_ENV=prod (exit 2). Audited as the system
    actor `cli` with `as_user_id`."""
    settings = get_settings()
    if settings.is_prod:
        rprint("[red]refused:[/red] `aslms assistant include-internal` is not run with APP_ENV=prod")
        raise typer.Exit(code=2)
    Session = get_sessionmaker()
    with Session() as s:
        login = s.scalar(select(User).where(func.lower(User.email) == user.strip().lower()))
        if login is None or not login.is_active:
            raise typer.BadParameter(f"no active login {user}")
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
    mode = svc.mode_of(connector) if connector is not None else "off"
    try:
        out = svc.include_internal(
            Session, Actor.system("cli"), login, case=case_id, conversation_id=conversation_id, mode=mode
        )
    except svc.AssistantError as exc:
        rprint(f"[red]{exc.code}:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    except (NotVisibleCase, svc.ConversationNotFound) as exc:
        rprint(f"[red]not_found:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    new = "  (new conversation)" if out["new_conversation"] else ""
    rprint(
        f"conversation: {out['conversation_id']}  internal records included at {out['internal_included_at']}{new}"
    )


@assistant_app.command("check")
def check_cmd() -> None:
    """Every count must be 0; exit code 1 otherwise."""
    with session_scope() as s:
        result = svc.check(s)
    for k, v in result.items():
        rprint(f"{k}: {'[green]' if v == 0 else '[red]'}{v}[/]")
    if any(result.values()):
        raise typer.Exit(code=1)
