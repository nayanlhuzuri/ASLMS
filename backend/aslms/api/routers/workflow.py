"""Custody and workflow (design `custody-workflow`): the custody card and the file's movement record, sending the
file and the owning department's recall, the send targets, the held / sent lists and the tracking summary, case
stages, and the notes trail with the holder's drafts.

`{ref}` is a case id, CNR or dash-form `ref_no`; `{note}` an id or dash-form `ref_no`; `{draft}` an id. Every
case-scoped endpoint applies the case visibility rule first (404 "no such case"); notes and drafts outside their
rules answer 404 too. A permanent note and its files are written in one `multipart/form-data` call (text fields
+ repeated `files`, `file_doc_types`, `document_refs`). Errors carry `{code, message}`. The only delete is a
draft by its author (the owner's rule of 7 Oct 2026)."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from aslms.api import schemas
from aslms.api.deps import actor_of, get_scanner, get_session, require, require_any
from aslms.api.filters import case_filter_query
from aslms.api.routers.documents import dispatch_extract
from aslms.core.config import Settings
from aslms.domain.cases import Case
from aslms.domain.org import User
from aslms.domain.reference import Permission
from aslms.domain.workflow import CaseNoteDraft
from aslms.services import access, attachments, notes, stages, visibility, workflow_codes
from aslms.services import custody as custody_svc
from aslms.services.case_filters import CaseFilters
from aslms.services.cases import CaseNotFound, resolve_case_ref
from aslms.services.documents import DocumentError, UploadRefused
from aslms.services.notes import DraftNotFound
from aslms.services.scanner import Scanner
from aslms.services.storage import LocalStore
from aslms.services.visibility import NotVisibleCase, NotVisibleDocument, NotVisibleNote
from aslms.services.workflow_common import WorkflowError

router = APIRouter(tags=["workflow"])
read = require_any(Permission.CASES_VIEW_SCOPE, Permission.CASES_VIEW_ALL)
ERRORS: dict[int | str, dict[str, Any]] = {
    400: {"model": schemas.ErrorOut},
    403: {"model": schemas.ErrorOut},
    404: {"model": schemas.ErrorOut},
    409: {"model": schemas.ErrorOut},
}
UPLOAD_ERRORS: dict[int | str, dict[str, Any]] = {
    **ERRORS,
    413: {"model": schemas.ErrorOut},
    415: {"model": schemas.ErrorOut},
    422: {"model": schemas.ErrorOut},
    503: {"model": schemas.ErrorOut},
}
HANDLED = (
    NotVisibleCase,
    NotVisibleDocument,
    NotVisibleNote,
    DraftNotFound,
    CaseNotFound,
    WorkflowError,
    UploadRefused,
    DocumentError,
    access.Forbidden,
    ValueError,
)


def _error(code: str, message: str, http_status: int, **extra) -> HTTPException:
    return HTTPException(http_status, {"code": code, "message": message, **extra})


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, NotVisibleNote):
        return _error("not_found", "no such note", status.HTTP_404_NOT_FOUND)
    if isinstance(exc, DraftNotFound):
        return _error("not_found", "no such draft", status.HTTP_404_NOT_FOUND)
    if isinstance(exc, NotVisibleDocument):
        return _error("not_found", "no such document", status.HTTP_404_NOT_FOUND)
    if isinstance(exc, NotVisibleCase | CaseNotFound):
        return _error("not_found", str(exc) or "no such case", status.HTTP_404_NOT_FOUND)
    if isinstance(exc, WorkflowError):
        return _error(exc.code, str(exc), exc.http_status)
    if isinstance(exc, UploadRefused):
        return _error(exc.code, str(exc), exc.http_status, **exc.extra)
    if isinstance(exc, DocumentError):
        return _error(exc.code, str(exc), exc.http_status)
    if isinstance(exc, access.Forbidden):
        return _error(exc.code, str(exc), status.HTTP_403_FORBIDDEN)
    if isinstance(exc, ValueError):
        return _error("bad_field", str(exc), status.HTTP_400_BAD_REQUEST)
    raise exc


def _fail(session: Session, exc: Exception) -> HTTPException:
    """A refused file's rejection audit row survives the error (as for uploads); nothing else was written
    (every file is checked before the first write)."""
    if isinstance(exc, UploadRefused) and exc.audited:
        session.commit()
    return _http(exc)


def _case(session: Session, ref: str) -> Case:
    try:
        return resolve_case_ref(session, ref)
    except CaseNotFound as exc:
        raise _http(exc) from exc


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _store(request: Request) -> LocalStore:
    return LocalStore(_settings(request).storage_dir)


def _read_files(request: Request, files: list[UploadFile]) -> list[tuple[bytes, str]]:
    settings = _settings(request)
    max_bytes = settings.upload_max_bytes
    if len(files) > settings.attachments_max_files:
        raise _error(
            "bad_field",
            f"at most {settings.attachments_max_files} files may be attached at once",
            status.HTTP_400_BAD_REQUEST,
        )
    out = []
    for f in files:
        data = f.file.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise _error(
                "too_large",
                f"{f.filename or 'a file'} exceeds {max_bytes} bytes",
                status.HTTP_413_CONTENT_TOO_LARGE,
            )
        out.append((data, f.filename or ""))
    return out


def _commit_and_extract(request: Request, session: Session) -> None:
    ids = attachments.take_new_document_ids(session)
    session.commit()
    for doc_id in ids:
        dispatch_extract(_settings(request), doc_id)


def _move_out(
    session: Session, user: User, case: Case, result: custody_svc.MoveResult
) -> schemas.CustodyMoveOut:
    bases = visibility.access_basis(session, user, case)
    return schemas.CustodyMoveOut(
        card=custody_svc.card(session, user, case, bases=bases) if bases else None,
        leg=custody_svc.leg_out(session, result.leg, show_remark=True),
        finalised_notes=result.finalised,
    )


# ------------------------------------------------------------------------------------------------ codes


@router.get("/workflow/codes", response_model=schemas.WorkflowCodesOut)
def codes(
    request: Request, session: Session = Depends(get_session), user: User = Depends(read)
) -> schemas.WorkflowCodesOut:
    """Note kinds (with `selectable`), pending actions with labels, stages with phase, response modes, custody
    reasons and the note limits (`note_max_chars`, `attachments_max_files`, `note_drafts_max`)."""
    return schemas.WorkflowCodesOut(**workflow_codes.codes(session, _settings(request)))


# ------------------------------------------------------------------------------------------------ custody


@router.get("/cases/{ref}/custody", response_model=schemas.CustodyHistoryOut, responses=ERRORS)
def custody_history(
    ref: str,
    limit: int = 50,
    offset: int = 0,
    order: Literal["asc", "desc"] = "asc",
    session: Session = Depends(get_session),
    user: User = Depends(read),
) -> schemas.CustodyHistoryOut:
    """The custody card and the legs by `seq_no` (the case's movement record), oldest first or with
    `order=desc` newest first; the remark only for callers working on the case and State-wide readers holding
    `cases.view_private_all`, which `remarks_shown` states."""
    case = _case(session, ref)
    try:
        out = custody_svc.history(session, user, case, limit=limit, offset=offset, order=order)
    except HANDLED as exc:
        raise _http(exc) from exc
    return schemas.CustodyHistoryOut(**out)


@router.get("/custody/recipients", response_model=schemas.RecipientListOut, responses=ERRORS)
def custody_recipients(
    department: str | None = None,
    q: str | None = Query(None, max_length=100),
    limit: int = 50,
    offset: int = 0,
    session: Session = Depends(get_session),
    user: User = Depends(require(Permission.CASES_VIEW_SCOPE)),
) -> schemas.RecipientListOut:
    """Without `department`: the departments a file may be sent to; with it: that department's officers (one
    row per membership, with the person's `user_id`; State-wide types excluded) and `units`, the active offices
    inside the department."""
    try:
        page = custody_svc.recipients(session, user, department=department, q=q, limit=limit, offset=offset)
    except HANDLED as exc:
        raise _http(exc) from exc
    if department:
        return schemas.RecipientListOut(items=page.items, total=page.total, units=page.extra.get("units", []))
    return schemas.RecipientListOut(departments=page.items, total=page.total)


@router.post(
    "/cases/{ref}/custody/send",
    response_model=schemas.CustodyMoveOut,
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
)
def custody_send(
    ref: str,
    body: schemas.CustodySendIn,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(require(Permission.CASES_VIEW_SCOPE)),
) -> schemas.CustodyMoveOut:
    """Send the file to an officer of any department with a remark, a pending action and an optional due date
    (and optionally record a stage). The holder sends without any function; a file held by an office alone is
    sent by a `custody.move` holder who controls that office. The holder's drafts become permanent notes."""
    case = _case(session, ref)
    try:
        result = custody_svc.send(
            session,
            actor_of(request, user, session),
            user,
            case,
            to_membership=body.to_membership,
            pending_action_=body.pending_action,
            due_date=body.due_date,
            remark=body.remark,
            stage=body.stage,
        )
        out = _move_out(session, user, case, result)
    except HANDLED as exc:
        raise _http(exc) from exc
    return out


@router.post(
    "/cases/{ref}/custody/recall",
    response_model=schemas.CustodyMoveOut,
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
)
def custody_recall(
    ref: str,
    body: schemas.CustodyRecallIn,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(read),
) -> schemas.CustodyMoveOut:
    """Call the file back from wherever it is (`custody.recall` in a membership of the owning department); the
    recaller becomes the holder with `examine` pending."""
    case = _case(session, ref)
    try:
        result = custody_svc.recall(session, actor_of(request, user, session), user, case, remark=body.remark)
        out = _move_out(session, user, case, result)
    except HANDLED as exc:
        raise _http(exc) from exc
    return out


@router.get("/custody/summary", response_model=schemas.CustodySummaryOut, responses=ERRORS)
def custody_summary(
    request: Request,
    department: str | None = None,
    session: Session = Depends(get_session),
    user: User = Depends(require(Permission.CUSTODY_TRACK)),
) -> schemas.CustodySummaryOut:
    """Counts only, per department the caller tracks: files held, due soon, overdue, by holder department and
    by holder office/officer."""
    try:
        out = custody_svc.summary(
            session, user, department=department, soon_days=_settings(request).request_due_soon_days
        )
    except HANDLED as exc:
        raise _http(exc) from exc
    return schemas.CustodySummaryOut(**out)


@router.get("/custody/held", response_model=schemas.HeldListOut, responses=ERRORS)
def custody_held(
    scope: str = Query("me", pattern="^(me|office|owned)$"),
    overdue: bool | None = None,
    holder_department: str | None = None,
    filters: CaseFilters = Depends(case_filter_query),
    limit: int = 50,
    offset: int = 0,
    session: Session = Depends(get_session),
    user: User = Depends(read),
) -> schemas.HeldListOut:
    """Files held by the caller (`me`), by their offices (`office`), or owned by a department they track
    (`owned`, needs `custody.track` there), ordered by due date then since; visible cases only."""
    try:
        page = custody_svc.held(
            session,
            user,
            scope=scope,
            overdue=overdue,
            holder_department=holder_department,
            filters=filters,
            limit=limit,
            offset=offset,
        )
    except HANDLED as exc:
        raise _http(exc) from exc
    return schemas.HeldListOut(items=page.items, total=page.total)


@router.get("/custody/sent", response_model=schemas.SentListOut, responses=ERRORS)
def custody_sent(
    still_out: bool = Query(
        False,
        description="true: only sends still the case's current leg, on a case you can open, not held by you; "
        "overdue first",
    ),
    filters: CaseFilters = Depends(case_filter_query),
    limit: int = 50,
    offset: int = 0,
    session: Session = Depends(get_session),
    user: User = Depends(read),
) -> schemas.SentListOut:
    """The legs the caller wrote (sends and recalls) with the case summary and `visible`: whether the caller can
    open the case now (the sender usually loses sight of a case sent on). The shared case filters narrow them.
    `still_out` keeps the files still out (design case-inbox-simplify, decisions 6 and 7)."""
    try:
        page = custody_svc.sent(
            session, user, still_out=still_out, filters=filters, limit=limit, offset=offset
        )
    except HANDLED as exc:
        raise _http(exc) from exc
    return schemas.SentListOut(items=page.items, total=page.total)


# ------------------------------------------------------------------------------------------------ stages


@router.get("/cases/{ref}/stages", response_model=schemas.StageHistoryOut, responses=ERRORS)
def stage_history(
    ref: str, session: Session = Depends(get_session), user: User = Depends(read)
) -> schemas.StageHistoryOut:
    """The current stage, the history (newest first) and the gaps (main-phase stages never recorded)."""
    case = _case(session, ref)
    try:
        out = stages.history_with_gaps(session, user, case)
    except HANDLED as exc:
        raise _http(exc) from exc
    return schemas.StageHistoryOut(**out)


@router.post(
    "/cases/{ref}/stages",
    response_model=schemas.StageSetOut,
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
)
def stage_set(
    ref: str,
    body: schemas.StageSetIn,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(require(Permission.STAGES_SET)),
) -> schemas.StageSetOut:
    """Record the case stage (any stage, guided not enforced) on a claimed case you work on."""
    case = _case(session, ref)
    try:
        row = stages.set_stage(
            session,
            actor_of(request, user, session),
            user,
            case,
            stage=body.stage,
            response_mode=body.response_mode,
            note=body.note,
        )
        out = stages.stage_out(session, row)
    except HANDLED as exc:
        raise _http(exc) from exc
    return schemas.StageSetOut(current=out)


# ------------------------------------------------------------------------------------------------ notes


@router.get("/cases/{ref}/notes", response_model=schemas.NoteListOut, responses=ERRORS)
def list_notes(
    ref: str,
    kind: str | None = None,
    include_superseded: bool = True,
    limit: int = 50,
    offset: int = 0,
    session: Session = Depends(get_session),
    user: User = Depends(read),
) -> schemas.NoteListOut:
    """The notes trail by `seq_no`, each note passed through the note visibility rule; drafts never listed."""
    case = _case(session, ref)
    try:
        page = notes.list_for_case(
            session,
            user,
            case,
            kind=kind,
            include_superseded=include_superseded,
            limit=limit,
            offset=offset,
        )
    except HANDLED as exc:
        raise _http(exc) from exc
    return schemas.NoteListOut(items=page.items, total=page.total)


@router.post(
    "/cases/{ref}/notes",
    response_model=schemas.NoteOut | schemas.DraftOut,
    status_code=status.HTTP_201_CREATED,
    responses=UPLOAD_ERRORS,
)
def add_note(
    ref: str,
    request: Request,
    kind: str | None = Form(None),
    body: str = Form(...),
    visibility: str = Form(...),
    supersedes: str | None = Form(None),
    files: list[UploadFile] = File(default=[]),
    file_doc_types: list[str] = Form(default=[]),
    document_refs: list[str] = Form(default=[]),
    session: Session = Depends(get_session),
    user: User = Depends(require(Permission.NOTES_ADD)),
    scanner: Scanner = Depends(get_scanner),
) -> schemas.NoteOut | schemas.DraftOut:
    """Write a note. The holder of the file writes a draft (`draft: true`; links to case documents only), made
    permanent when the file moves; anyone else working on the case writes a permanent note (`draft: false`)
    with optional files (checked and virus-scanned before anything is written) and links."""
    case = _case(session, ref)
    settings = _settings(request)
    data = _read_files(request, files)
    try:
        row, is_draft = notes.add_note(
            session,
            actor_of(request, user, session),
            user,
            case,
            kind=kind,
            body=body,
            visibility_=visibility,
            supersedes=supersedes,
            files=data,
            doc_types=file_doc_types,
            document_refs=document_refs,
            scanner=scanner,
            store=_store(request),
            max_files=settings.attachments_max_files,
            max_bytes=settings.upload_max_bytes,
            max_chars=settings.note_max_chars,
            max_drafts=settings.note_drafts_max,
        )
        out = notes.draft_out(session, row) if is_draft else notes.note_out(session, user, row)
    except HANDLED as exc:
        raise _fail(session, exc) from exc
    _commit_and_extract(request, session)
    return schemas.DraftOut(**out) if is_draft else schemas.NoteOut(**out)


@router.get("/cases/{ref}/notes/drafts", response_model=schemas.DraftListOut, responses=ERRORS)
def list_drafts(
    ref: str, session: Session = Depends(get_session), user: User = Depends(require(Permission.NOTES_ADD))
) -> schemas.DraftListOut:
    """The caller's own drafts on the case (nobody else, State-wide readers included, sees them)."""
    case = _case(session, ref)
    try:
        items = notes.list_drafts(session, user, case)
    except HANDLED as exc:
        raise _http(exc) from exc
    return schemas.DraftListOut(items=items)


@router.patch("/notes/drafts/{draft}", response_model=schemas.DraftOut, responses=ERRORS)
def update_draft(
    draft: uuid.UUID,
    body: schemas.DraftUpdateIn,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(require(Permission.NOTES_ADD)),
) -> schemas.DraftOut:
    """Edit your draft while your membership holds the file (404 for anyone else; 409 `draft_finalised` once the
    file has moved)."""
    fields = body.model_dump(exclude_unset=True)
    settings = _settings(request)
    try:
        row: CaseNoteDraft = notes.update_draft(
            session,
            actor_of(request, user, session),
            user,
            draft,
            kind=fields.get("kind", notes.UNSET),
            body=fields.get("body", notes.UNSET),
            visibility_=fields.get("visibility", notes.UNSET),
            supersedes=fields.get("supersedes", notes.UNSET),
            document_refs=fields.get("document_refs", notes.UNSET),
            max_chars=settings.note_max_chars,
            max_links=settings.attachments_max_files,
        )
        out = notes.draft_out(session, row)
    except HANDLED as exc:
        raise _http(exc) from exc
    return schemas.DraftOut(**out)


@router.delete(
    "/notes/drafts/{draft}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response, responses=ERRORS
)
def delete_draft(
    draft: uuid.UUID,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(require(Permission.NOTES_ADD)),
) -> Response:
    """Delete your draft while your membership holds the file: the only delete in a case's records."""
    try:
        notes.delete_draft(session, actor_of(request, user, session), user, draft)
    except HANDLED as exc:
        raise _http(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/notes/{note}", response_model=schemas.NoteOut, responses=ERRORS)
def get_note(
    note: str, session: Session = Depends(get_session), user: User = Depends(read)
) -> schemas.NoteOut:
    """One note by id or `ref_no` (404 when it is not visible to you)."""
    try:
        row = notes.get(session, user, note)
        out = notes.note_out(session, user, row)
    except HANDLED as exc:
        raise _http(exc) from exc
    return schemas.NoteOut(**out)
