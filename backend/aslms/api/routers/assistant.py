"""The Case Assistant (design `assistant`, "API"): the status, a question with its answer, the caller's own
conversations, the court-record view of a cited court order, and (design `assistant-ollama`) the switch "Include This
Case's Internal Records". Every endpoint needs `assistant.use`. Errors carry `{code, message}`; 429 and the 503s
`assistant_loading` and `assistant_busy` add `retry_after` and `Retry-After`. Unknown and not visible both answer 404.

A question runs in three short steps (`services/assistant.py`): the request's own transaction is committed before the
connector is called, so no transaction is held while a person waits (decision 9). Conversations are private: no
endpoint reads another user's conversations, whoever asks (decision 8)."""

from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from aslms.api import schemas
from aslms.api.deps import actor_of, get_session, require
from aslms.api.routers.documents import _serve
from aslms.domain.assistant import AssistantConversation
from aslms.domain.org import User
from aslms.domain.reference import Permission
from aslms.services import assistant as svc
from aslms.services import visibility
from aslms.services.cases import CaseNotFound, resolve_case_ref
from aslms.services.documents import DocumentError, FileMissing
from aslms.services.storage import LocalStore
from aslms.services.visibility import NotVisibleCase

router = APIRouter(prefix="/assistant", tags=["assistant"])
use = require(Permission.ASSISTANT_USE)

NOT_FOUND = (NotVisibleCase, CaseNotFound, svc.ConversationNotFound, svc.CourtOrderNotFound)
HANDLED = (*NOT_FOUND, svc.AssistantError, DocumentError, FileMissing)
ERRORS = {
    403: {"model": schemas.ErrorOut},
    404: {"model": schemas.ErrorOut},
    409: {"model": schemas.ErrorOut},
    422: {"model": schemas.ErrorOut},
    429: {"model": schemas.ErrorOut},
    503: {"model": schemas.ErrorOut},
}


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, svc.AssistantLimit | svc.AssistantLoading | svc.AssistantBusy):
        return HTTPException(
            exc.http_status,
            {"code": exc.code, "message": str(exc), "retry_after": exc.retry_after},
            headers={"Retry-After": str(exc.retry_after)},
        )
    if isinstance(exc, svc.AssistantError):
        return HTTPException(exc.http_status, {"code": exc.code, "message": str(exc), **exc.extra})
    if isinstance(exc, NOT_FOUND):
        return HTTPException(
            status.HTTP_404_NOT_FOUND, {"code": "not_found", "message": str(exc) or "not found"}
        )
    if isinstance(exc, FileMissing):
        return HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, {"code": "file_missing", "message": str(exc)}
        )
    if isinstance(exc, DocumentError):
        return HTTPException(exc.http_status, {"code": exc.code, "message": str(exc)})
    raise exc


def _connector(request: Request):
    """The connector: a test double on `app.state.assistant_connector`, else the configured one (None while off)."""
    override = getattr(request.app.state, "assistant_connector", None)
    if override is not None:
        return override
    return svc.assistant_connector(request.app.state.settings, request.app.state.session_factory)


def _config(request: Request) -> svc.AssistantConfig:
    override = getattr(request.app.state, "assistant_config", None)
    return override if override is not None else svc.AssistantConfig.from_settings(request.app.state.settings)


@router.get("/status", response_model=schemas.AssistantStatusOut)
def get_status(
    request: Request, session: Session = Depends(get_session), user: User = Depends(use)
) -> schemas.AssistantStatusOut:
    """The mode, the state (`not_implemented` while SourceTrace is chosen and no connector exists), the banner, the
    limits with the caller's questions of the last hour, the scopes, and in ollama mode the local model's readiness
    (`engine`; reading it may start loading the model) and `internal_records` `switch`."""
    return schemas.AssistantStatusOut(
        **svc.status(session, user, request.app.state.settings, connector=_connector(request))
    )


@router.post("/ask", response_model=schemas.AssistantAskOut, responses=ERRORS)
def ask(
    body: schemas.AssistantAskIn,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(use),
) -> schemas.AssistantAskOut:
    """Ask a question in one of three scopes: `case` (one case the caller can see; court orders of other cases too
    with `include_related`), `my_cases` (the caller's own cases) or `research` (every court order, and the court
    filings the caller may see). Court orders are court-public; court filings follow the document visibility; notes
    and internal documents are never searched or sent. A connector failure is still 200, with `answer.outcome`
    `failed` and `answer.error`. Refused before anything is stored: 503 `assistant_off`; 422 `scope_mismatch` (a
    `case` outside the case scope, refused before the case is looked up, or a scope or case other than the
    conversation's); 404 (a case unknown or not visible, answered alike, or a conversation not the caller's); 422
    `bad_question` (length, control characters with `reason` `control_characters`); 409 `question_in_flight` (one
    unanswered question per user across all conversations) / `conversation_full`; 429 `assistant_limit`. In ollama
    mode: 503 `assistant_loading` (`Retry-After` 30), `assistant_unavailable` and `assistant_busy` (`Retry-After` 5),
    none stored or counted; internal records only for a case-scope conversation switched on through
    `POST /assistant/internal-records` (extra fields are refused with 422). Audited without the text."""
    case_id: uuid.UUID | None = None
    try:
        if body.case and body.scope != "case":
            raise svc.ScopeMismatch("only a case-scope question names a case")
        if body.case:
            case_row = resolve_case_ref(session, body.case)
            if not visibility.can_view_case(session, user, case_row):
                raise CaseNotFound("no such case")  # exactly as an unknown case
            case_id = case_row.id
    except HANDLED as exc:
        raise _http(exc) from exc
    actor = actor_of(request, user, session)
    connector = _connector(request)
    config = _config(request)
    session.commit()  # decision 9: no transaction is held across the connector call
    try:
        result = asyncio.run(
            svc.ask(
                request.app.state.session_factory,
                actor,
                user,
                question=body.question,
                scope=body.scope,
                case=case_id,
                conversation_id=body.conversation_id,
                include_related=body.include_related,
                connector=connector,
                config=config,
            )
        )
        conv = session.get(AssistantConversation, result.conversation_id)
        return schemas.AssistantAskOut(
            conversation=svc.conversation_out(session, conv),
            question=svc.message(session, user, result.question_id),
            answer=svc.message(session, user, result.answer_id),
        )
    except HANDLED as exc:
        raise _http(exc) from exc


@router.post("/internal-records", response_model=schemas.AssistantInternalOut, responses=ERRORS)
def include_internal(
    body: schemas.AssistantInternalIn,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(use),
) -> schemas.AssistantInternalOut:
    """Switch on "Include This Case's Internal Records" for the caller's own case-tab conversation of `case`
    (`conversation_id`), or for a new empty one (design assistant-ollama, decision 4). From then on that conversation's
    questions also read the case's notes, file movement with remarks, pending actions and department documents the
    caller may open on the case page (never drafts, never another case's). It cannot be switched off: a court-only
    conversation is a new conversation. Idempotent (200 with the existing time, no second audit row). 422
    `internal_unavailable` outside ollama mode; 404 when the case is unknown or not visible, or the conversation is not
    the caller's; 422 `scope_mismatch` for a conversation of another case or scope; 403 `internal_not_permitted`
    without `cases.view_scope` or `cases.view_all`; 422 `no_internal_records` when the caller can open none. No model
    call. Audited `assistant.internal_included` (ids only)."""
    connector = _connector(request)
    mode = svc.mode_of(connector) if connector is not None else "off"
    try:
        if mode != "ollama":
            raise svc.InternalUnavailable(
                "internal records can be included only when the local model answers"
            )
        case_row = resolve_case_ref(session, body.case)
        if not visibility.can_view_case(session, user, case_row):
            raise CaseNotFound("no such case")
        case_id = case_row.id
    except HANDLED as exc:
        raise _http(exc) from exc
    actor = actor_of(request, user, session)
    session.commit()
    try:
        out = svc.include_internal(
            request.app.state.session_factory,
            actor,
            user,
            case=case_id,
            conversation_id=body.conversation_id,
            mode=mode,
        )
    except HANDLED as exc:
        raise _http(exc) from exc
    return schemas.AssistantInternalOut(**out)


@router.get("/conversations", response_model=schemas.AssistantConversationListOut, responses=ERRORS)
def list_conversations(
    scope: str | None = Query(None, pattern="^(case|my_cases|research)$"),
    case: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
    user: User = Depends(use),
) -> schemas.AssistantConversationListOut:
    """The caller's own conversations, newest first; case conversations of cases the caller can no longer see are
    left out. Nobody reads another user's conversations."""
    case_row = None
    if case:
        try:
            case_row = resolve_case_ref(session, case)
        except CaseNotFound:
            return schemas.AssistantConversationListOut(total=0, items=[])
    try:
        page = svc.conversations(session, user, scope=scope, case=case_row, limit=limit, offset=offset)
    except HANDLED as exc:
        raise _http(exc) from exc
    return schemas.AssistantConversationListOut(total=page.total, items=page.items)


@router.get("/conversations/{conversation_id}", response_model=schemas.AssistantThreadOut, responses=ERRORS)
def read_conversation(
    conversation_id: uuid.UUID,
    before: uuid.UUID | None = None,
    limit: int = Query(50, ge=1, le=200),
    session: Session = Depends(get_session),
    user: User = Depends(use),
) -> schemas.AssistantThreadOut:
    """One of the caller's conversations with its messages, oldest first (the latest `limit` before the message
    `before`). Court-filing citations are re-checked against the caller's current document visibility: one that no
    longer passes shows unavailable and hides its answer's text. 404 when the conversation is not the caller's, or
    is a case conversation whose case they can no longer see. Writes nothing."""
    try:
        return schemas.AssistantThreadOut(
            **svc.conversation(session, user, conversation_id, before=before, limit=limit)
        )
    except HANDLED as exc:
        raise _http(exc) from exc


@router.get("/court-orders/{order_id}", response_model=schemas.AssistantCourtOrderViewOut, responses=ERRORS)
def court_order(
    order_id: uuid.UUID,
    request: Request,
    message: uuid.UUID | None = None,
    session: Session = Depends(get_session),
    user: User = Depends(use),
) -> schemas.AssistantCourtOrderViewOut:
    """The court's public record of a cited order: the order (number, date, kind, judge) and the case's court-public
    facts, whoever owns the case. 404 unless the order is a court record in the assistant's corpus and the caller's
    own answer `message` cites it. Never the owner, custody, stage, notes, documents or `ref_no`. Audited
    (`assistant.court_order_opened`)."""
    actor = actor_of(request, user, session)
    try:
        return schemas.AssistantCourtOrderViewOut(
            **svc.court_order_view(session, actor, user, order_id, message)
        )
    except HANDLED as exc:
        raise _http(exc) from exc


@router.get("/court-orders/{order_id}/file", responses={**ERRORS, 400: {"model": schemas.ErrorOut}})
def court_order_file(
    order_id: uuid.UUID,
    request: Request,
    message: uuid.UUID | None = None,
    disposition: str = Query("inline", pattern="^(inline|attachment)$"),
    session: Session = Depends(get_session),
    user: User = Depends(use),
) -> FileResponse:
    """The cited order's PDF from the store, with the headers of the documents file route (`inline` only for PDF).
    The same rule as the court-record view; audited."""
    actor = actor_of(request, user, session)
    try:
        served = svc.court_order_file(
            session,
            actor,
            user,
            order_id,
            message,
            store=LocalStore(request.app.state.settings.storage_dir),
            disposition=disposition,
        )
    except HANDLED as exc:
        if isinstance(exc, FileMissing):
            session.commit()  # the source_failures row survives the 500
        raise _http(exc) from exc
    return _serve(served)
