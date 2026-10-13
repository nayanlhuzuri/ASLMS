"""Documents (design `documents-uploads`): the Documents tab of a case, uploads scanned before storage,
metadata, file serving with download controls, order PDFs from the store, visibility changes, archiving,
the uploadable types and the content search. `{ref}` is a case id, `ref_no` or CNR; `{doc}` a document id or
`ref_no` (slash or dash form). Unknown and not-visible both answer 404. Errors carry `{code, message}`.
`/documents/types` and `/documents/search` are declared before `/documents/{doc}`. Nothing deletes."""

from __future__ import annotations

import logging
import uuid
from datetime import date
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session

from aslms.api import schemas
from aslms.api.deps import actor_of, get_scanner, get_session, require, require_any
from aslms.core.config import Settings
from aslms.domain.cases import Case
from aslms.domain.org import User
from aslms.domain.reference import Permission
from aslms.services import documents as svc
from aslms.services import filetypes
from aslms.services.cases import CaseNotFound, resolve_case_ref
from aslms.services.documents import (
    DocumentError,
    FileMissing,
    OrderNotStored,
    ServedFile,
    UploadRefused,
)
from aslms.services.scanner import Scanner
from aslms.services.storage import LocalStore
from aslms.services.visibility import NotVisibleCase, NotVisibleDocument

log = logging.getLogger(__name__)
router = APIRouter(tags=["documents"])

MULTIPART_OVERHEAD = 64 * 1024
EXTRACT_TASK = "aslms.extract_document_text"
NOT_FOUND = (NotVisibleCase, NotVisibleDocument, CaseNotFound)
file_access = require_any(Permission.DOCUMENTS_VIEW, Permission.DOCUMENTS_DOWNLOAD)


def _body_limit(request: Request) -> int | None:
    """The largest body a POST may declare: one file on an upload, `ATTACHMENTS_MAX_FILES` files on a note
    (design custody-workflow, decision 18; each file is still counted against `UPLOAD_MAX_BYTES` by the
    endpoint)."""
    if request.method != "POST":
        return None
    settings = request.app.state.settings
    path = request.url.path.rstrip("/")
    if path.endswith("/documents"):
        return settings.upload_max_bytes
    if path.startswith("/cases/") and path.endswith("/notes"):
        return settings.attachments_max_files * settings.upload_max_bytes
    return None


def upload_size_guard(app):
    """Decision 4: a `Content-Length` above the limit + 64 KB of multipart overhead is refused with 413 before
    the body is read (FastAPI parses the form before any endpoint code runs, so this is middleware). The
    endpoint counts the bytes too, for a client that omits or understates the header."""

    @app.middleware("http")
    async def _guard(request: Request, call_next):
        limit = _body_limit(request)
        if limit is not None:
            declared = request.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > limit + MULTIPART_OVERHEAD:
                return JSONResponse(
                    {"detail": {"code": "too_large", "message": f"the request exceeds {limit} bytes"}},
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                )
        return await call_next(request)

    return app


def _error(code: str, message: str, http_status: int, **extra) -> HTTPException:
    return HTTPException(http_status, {"code": code, "message": message, **extra})


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, NotVisibleDocument):
        return _error("not_found", "no such document", status.HTTP_404_NOT_FOUND)
    if isinstance(exc, NOT_FOUND):
        return _error("not_found", str(exc) or "no such case", status.HTTP_404_NOT_FOUND)
    if isinstance(exc, OrderNotStored):
        return _error("not_stored", str(exc), status.HTTP_404_NOT_FOUND, download_status=exc.download_status)
    if isinstance(exc, UploadRefused):
        return _error(exc.code, str(exc), exc.http_status, **exc.extra)
    if isinstance(exc, DocumentError):
        return _error(exc.code, str(exc), exc.http_status)
    if isinstance(exc, FileMissing):
        return _error("file_missing", str(exc), status.HTTP_500_INTERNAL_SERVER_ERROR)
    if isinstance(exc, ValueError):
        return _error("bad_field", str(exc), status.HTTP_400_BAD_REQUEST)
    raise exc


HANDLED = (
    NotVisibleCase,
    NotVisibleDocument,
    CaseNotFound,
    OrderNotStored,
    DocumentError,
    FileMissing,
    ValueError,
)


def _keep_failure(session: Session, exc: Exception) -> None:
    """A missing stored file is recorded in `source_failures` (decision 14); the row must survive the 500."""
    if isinstance(exc, FileMissing):
        session.commit()


def _case(session: Session, ref: str) -> Case:
    try:
        return resolve_case_ref(session, ref)
    except CaseNotFound as exc:
        raise _http(exc) from exc


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _store(request: Request) -> LocalStore:
    return LocalStore(_settings(request).storage_dir)


def _serve(served: ServedFile) -> FileResponse:
    ascii_name = served.filename.encode("ascii", "replace").decode("ascii").replace('"', "")
    disposition = (
        f"{served.disposition}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(served.filename)}"
    )
    headers = {
        "Content-Disposition": disposition,
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store",
    }
    if served.disposition == "inline":
        headers["Content-Security-Policy"] = "sandbox"
    return FileResponse(served.path, media_type=served.mime, headers=headers)


def dispatch_extract(settings: Settings, document_id: uuid.UUID) -> bool:
    """Best effort after the commit: the five-minute sweep catches the document when the broker is down."""
    if not settings.redis_url:
        return False
    try:
        from aslms.jobs.celery_app import app as celery_app

        celery_app.send_task(EXTRACT_TASK, args=[str(document_id)], retry=False)
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("could not dispatch %s: %s", EXTRACT_TASK, exc)
        return False


# ------------------------------------------------------------------------------------------------ the case tab


@router.get("/cases/{ref}/documents", response_model=schemas.DocumentListOut)
def list_case_documents(
    ref: str,
    group: str | None = None,
    doc_type: str | None = None,
    include_archived: bool = False,
    limit: int = 50,
    offset: int = 0,
    session: Session = Depends(get_session),
    user: User = Depends(require(Permission.DOCUMENTS_VIEW)),
) -> schemas.DocumentListOut:
    """The uploads of the case and the stored PDFs of its orders, newest `doc_date` first, each one passed
    through the document visibility rule; archived ones only with `include_archived=true`."""
    case = _case(session, ref)
    try:
        page = svc.list_for_case(
            session,
            user,
            case,
            group=group,
            doc_type=doc_type,
            include_archived=include_archived,
            limit=limit,
            offset=offset,
        )
    except HANDLED as exc:
        raise _http(exc) from exc
    return schemas.DocumentListOut(items=page.items, total=page.total)


@router.post(
    "/cases/{ref}/documents",
    response_model=schemas.DocumentOut,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": schemas.ErrorOut},
        403: {"model": schemas.ErrorOut},
        409: {"model": schemas.ErrorOut},
        413: {"model": schemas.ErrorOut},
        415: {"model": schemas.ErrorOut},
        422: {"model": schemas.ErrorOut},
        503: {"model": schemas.ErrorOut},
    },
)
def upload_document(
    ref: str,
    request: Request,
    file: UploadFile = File(...),
    doc_type: str = Form(...),
    doc_date: date = Form(...),
    description: str = Form(...),
    visibility: str = Form(...),
    doc_group: str | None = Form(None),
    session: Session = Depends(get_session),
    user: User = Depends(require(Permission.DOCUMENTS_UPLOAD)),
    scanner: Scanner = Depends(get_scanner),
) -> schemas.DocumentOut:
    """Upload a court filing or an internal document to a case the caller works on (owner, allotted, custody,
    request or appearing counsel). The bytes decide the type (PDF, Word, JPEG, PNG), the size limit is
    `UPLOAD_MAX_BYTES`, and the file is scanned by ClamAV before anything is stored: `infected` → 422,
    scanner down → 503, nothing written. Audited; `document_uploaded` joins the timeline."""
    settings = _settings(request)
    max_bytes = settings.upload_max_bytes
    case = _case(session, ref)
    data = file.file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise _error(
            "too_large", f"the file exceeds {max_bytes} bytes", status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
        )
    actor = actor_of(request, user, session)
    try:
        doc = svc.upload(
            session,
            actor,
            user,
            case,
            data=data,
            filename=file.filename or "",
            doc_type=doc_type,
            doc_group=doc_group,
            doc_date=doc_date,
            description=description,
            visibility=visibility,
            scanner=scanner,
            store=_store(request),
            max_bytes=max_bytes,
        )
    except UploadRefused as exc:
        if exc.audited:
            session.commit()  # the rejection's audit row survives the error
        raise _http(exc) from exc
    except HANDLED as exc:
        raise _http(exc) from exc
    out = svc.document_out(session, user, doc, case=case)
    session.commit()
    dispatch_extract(settings, doc.id)
    return schemas.DocumentOut(**out)


@router.get("/cases/{ref}/orders/{order_id}/file", responses={404: {"model": schemas.ErrorOut}})
def order_file(
    ref: str,
    order_id: uuid.UUID,
    request: Request,
    disposition: str = Query("attachment", pattern="^(inline|attachment)$"),
    session: Session = Depends(get_session),
    user: User = Depends(file_access),
) -> FileResponse:
    """The order's PDF from the store; 404 `not_stored` (with `download_status`) when the court has not
    published it or the fetch is still pending. Court records are not audited on download."""
    case = _case(session, ref)
    actor = actor_of(request, user, session)
    try:
        served = svc.order_file(
            session, actor, user, case, order_id, store=_store(request), disposition=disposition
        )
    except HANDLED as exc:
        _keep_failure(session, exc)
        raise _http(exc) from exc
    return _serve(served)


# ------------------------------------------------------------------------------------------------ documents


@router.get("/documents/types", response_model=schemas.DocumentTypesOut)
def document_types(
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(require(Permission.DOCUMENTS_VIEW)),
) -> schemas.DocumentTypesOut:
    """The uploadable document types with their group; `other` lets the uploader choose the group. `upload`:
    the size limit and the permitted extensions, for the portal's checks before sending (the API still decides
    by content)."""
    return schemas.DocumentTypesOut(
        items=svc.upload_types(session),
        upload={
            "max_bytes": request.app.state.settings.upload_max_bytes,
            "extensions": filetypes.permitted_extensions(),
        },
    )


@router.get("/documents/search", response_model=schemas.DocumentSearchOut)
def search_documents(
    q: str = Query(..., min_length=svc.MIN_QUERY),
    case: str | None = None,
    group: str | None = None,
    doc_type: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = svc.MAX_SEARCH_LIMIT,
    offset: int = 0,
    session: Session = Depends(get_session),
    user: User = Depends(require(Permission.DOCUMENTS_VIEW)),
) -> schemas.DocumentSearchOut:
    """Word search over the extracted text of orders and uploads the caller may see, with a snippet."""
    try:
        page = svc.search(
            session,
            user,
            q=q,
            case=case,
            group=group,
            doc_type=doc_type,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=offset,
        )
    except HANDLED as exc:
        raise _http(exc) from exc
    return schemas.DocumentSearchOut(items=page.items, total=page.total)


@router.get(
    "/documents/{doc}", response_model=schemas.DocumentOut, responses={404: {"model": schemas.ErrorOut}}
)
def document_detail(
    doc: str,
    session: Session = Depends(get_session),
    user: User = Depends(require(Permission.DOCUMENTS_VIEW)),
) -> schemas.DocumentOut:
    try:
        row = svc.get(session, user, doc)
    except HANDLED as exc:
        raise _http(exc) from exc
    return schemas.DocumentOut(**svc.document_out(session, user, row))


@router.get(
    "/documents/{doc}/file", responses={400: {"model": schemas.ErrorOut}, 404: {"model": schemas.ErrorOut}}
)
def document_file(
    doc: str,
    request: Request,
    disposition: str = Query("attachment", pattern="^(inline|attachment)$"),
    session: Session = Depends(get_session),
    user: User = Depends(file_access),
) -> FileResponse:
    """The file: `inline` (PDF, JPEG, PNG; `documents.view`) or `attachment` (`documents.download`), under the
    document's visibility. Downloads of uploaded documents are audited."""
    actor = actor_of(request, user, session)
    try:
        row = svc.resolve_document_ref(session, doc)
        served = svc.open_file(session, actor, user, row, store=_store(request), disposition=disposition)
    except HANDLED as exc:
        _keep_failure(session, exc)
        raise _http(exc) from exc
    return _serve(served)


@router.patch(
    "/documents/{doc}",
    response_model=schemas.DocumentOut,
    responses={
        400: {"model": schemas.ErrorOut},
        403: {"model": schemas.ErrorOut},
        409: {"model": schemas.ErrorOut},
    },
)
def change_visibility(
    doc: str,
    body: schemas.DocumentVisibilityIn,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(require(Permission.DOCUMENTS_UPLOAD)),
) -> schemas.DocumentOut:
    """Change the visibility (the uploader, the department's head or admin, the super admin). A court filing
    widened from private becomes pending for SourceTrace; one already ingested cannot be narrowed (409)."""
    actor = actor_of(request, user, session)
    try:
        row = svc.get(session, user, doc)
        row = svc.change_visibility(session, actor, user, row, body.visibility)
    except HANDLED as exc:
        raise _http(exc) from exc
    return schemas.DocumentOut(**svc.document_out(session, user, row))


@router.post(
    "/documents/{doc}/archive",
    response_model=schemas.DocumentOut,
    responses={
        400: {"model": schemas.ErrorOut},
        403: {"model": schemas.ErrorOut},
        409: {"model": schemas.ErrorOut},
    },
)
def archive_document(
    doc: str,
    body: schemas.DocumentArchiveIn,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(require(Permission.DOCUMENTS_UPLOAD)),
) -> schemas.DocumentOut:
    """Archive with a reason: hidden from the tab, still readable, never deleted, never unarchived."""
    actor = actor_of(request, user, session)
    try:
        row = svc.get(session, user, doc)
        row = svc.archive(session, actor, user, row, body.reason)
    except HANDLED as exc:
        raise _http(exc) from exc
    return schemas.DocumentOut(**svc.document_out(session, user, row))
