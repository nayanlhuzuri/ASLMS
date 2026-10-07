"""`/admin/tickets/*`: the admin ticket panel (design `user-memberships`, decisions 15-20): head-change requests
with their government orders, the list and counts (oldest first), detail, approve, reject, withdraw, and the
supporting documents (attach while open, download, archive). Visibility is decided in SQL by
`services/tickets.py`; a ticket the caller may not see is 404.

The head-change request is multipart: the `request` form field holds the JSON request
(`{department, operation, incoming?, outgoing?, request_remark?, files?: [{doc_type, doc_date?, description?}]}`,
`files` describing the uploaded parts in order) and `files` the uploaded parts (at most 5)."""

from __future__ import annotations

import json
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session

from aslms.api import schemas
from aslms.api.deps import actor_of, get_scanner, get_session, require_any
from aslms.api.errors import HANDLED, http_error
from aslms.api.routers.documents import _serve, dispatch_extract
from aslms.domain.org import User
from aslms.domain.reference import Permission
from aslms.domain.tickets import TicketStatus
from aslms.services import tickets
from aslms.services.documents import FileMissing, UploadRefused
from aslms.services.scanner import Scanner
from aslms.services.storage import LocalStore

router = APIRouter(prefix="/admin/tickets", tags=["tickets"])
panel = require_any(Permission.ADMIN_TICKETS, Permission.USERS_PROPOSE_HEAD)


def _upload_http(exc: UploadRefused) -> HTTPException:
    return HTTPException(exc.http_status, {"code": exc.code, "message": str(exc), **exc.extra})


def _ticket(session: Session, user: User, ref: str):
    try:
        return tickets.get(session, user, ref)
    except tickets.TicketError as exc:
        raise http_error(exc) from exc


def _detail(session: Session, user: User, t) -> schemas.TicketDetailOut:
    return schemas.TicketDetailOut(**tickets.ticket_out(session, user, t))


def _read(upload: UploadFile, max_bytes: int) -> bytes:
    data = upload.file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            {"code": "too_large", "message": f"the file exceeds {max_bytes} bytes"},
        )
    return data


@router.post("/head-change", status_code=status.HTTP_202_ACCEPTED, response_model=schemas.TicketDetailOut)
def request_head_change(
    request: Request,
    body: str = Form(..., alias="request"),
    files: list[UploadFile] | None = File(None),
    session: Session = Depends(get_session),
    user: User = Depends(require_any(Permission.USERS_PROPOSE_HEAD, Permission.ADMIN_TICKETS)),
    scanner: Scanner = Depends(get_scanner),
):
    """A department admin's request → 202 with an open ticket (nothing changes until the super admin
    approves); the super admin's → 201 with the ticket already `approved` and the change applied. `end` (leave
    the department without a head) is the super admin's only (403 `super_admin_only`)."""
    settings = request.app.state.settings
    max_bytes = settings.upload_max_bytes
    try:
        raw = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, {"code": "bad_field", "message": "request is not JSON"}
        ) from exc
    if not isinstance(raw, dict):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, {"code": "bad_field", "message": "request is an object"}
        )
    meta = raw.pop("files", None) or []
    remark = raw.pop("request_remark", None)
    if "department" in raw and "department_code" not in raw:
        raw["department_code"] = raw.pop("department")
    uploads = files or []
    incoming_files = []
    for i, up in enumerate(uploads):
        info = meta[i] if i < len(meta) and isinstance(meta[i], dict) else {}
        doc_date = info.get("doc_date")
        incoming_files.append(
            tickets.IncomingFile(
                data=_read(up, max_bytes),
                filename=up.filename or "",
                doc_type=info.get("doc_type") or "government_order",
                doc_date=date.fromisoformat(doc_date) if doc_date else None,
                description=info.get("description"),
            )
        )
    try:
        t = tickets.request_head_change(
            session,
            actor_of(request, user, session),
            user,
            raw,
            request_remark=remark,
            files=incoming_files,
            scanner=scanner,
            store=LocalStore(settings.storage_dir),
            max_bytes=max_bytes,
        )
    except UploadRefused as exc:
        if exc.audited:
            session.commit()  # the refusal's audit row survives; no ticket was written
        raise _upload_http(exc) from exc
    except HANDLED as exc:
        raise http_error(exc) from exc
    out = _detail(session, user, t)
    doc_ids = [d.id for d in out.documents]
    session.commit()
    for doc_id in doc_ids:
        dispatch_extract(settings, doc_id)
    code = (
        status.HTTP_201_CREATED
        if TicketStatus(t.status) == TicketStatus.APPROVED
        else status.HTTP_202_ACCEPTED
    )
    return JSONResponse(status_code=code, content=json.loads(out.model_dump_json()))


@router.get("", response_model=schemas.TicketListOut)
def list_tickets(
    status_: str | None = Query("open", alias="status"),
    kind: str | None = None,
    department: str | None = None,
    mine: bool = False,
    limit: int = 50,
    offset: int = 0,
    session: Session = Depends(get_session),
    user: User = Depends(panel),
) -> schemas.TicketListOut:
    """Oldest first; `status` = `open` (default), `approved`, `rejected`, `withdrawn` or `all`."""
    try:
        items, total = tickets.list_tickets(
            session,
            user,
            status=status_,
            kind=kind,
            department=department,
            mine=mine,
            limit=limit,
            offset=offset,
        )
        counts = tickets.counts(session, user)
    except HANDLED as exc:
        raise http_error(exc) from exc
    return schemas.TicketListOut(items=items, total=total, counts=schemas.TicketCountsOut(**counts))


@router.get("/counts", response_model=schemas.TicketCountsOut)
def ticket_counts(
    session: Session = Depends(get_session), user: User = Depends(panel)
) -> schemas.TicketCountsOut:
    """For the dashboard panel; `departments_without_head` only for the super admin (decision 24)."""
    return schemas.TicketCountsOut(**tickets.counts(session, user))


@router.get("/{ref}", response_model=schemas.TicketDetailOut)
def get_ticket(
    ref: str, session: Session = Depends(get_session), user: User = Depends(panel)
) -> schemas.TicketDetailOut:
    return _detail(session, user, _ticket(session, user, ref))


@router.post("/{ref}/approve", response_model=schemas.TicketDetailOut)
def approve(
    ref: str,
    request: Request,
    body: schemas.TicketRemarkIn | None = None,
    session: Session = Depends(get_session),
    user: User = Depends(panel),
) -> schemas.TicketDetailOut:
    """The super admin applies exactly what was proposed; 409 `ticket_closed`, `ticket_stale` (with the
    reason; audited, the ticket stays open)."""
    t = _ticket(session, user, ref)
    try:
        tickets.approve(session, actor_of(request, user, session), user, t, body.remark if body else None)
    except tickets.TicketStale as exc:
        session.commit()  # the refusal's audit row survives
        raise http_error(exc) from exc
    except HANDLED as exc:
        raise http_error(exc) from exc
    return _detail(session, user, t)


@router.post("/{ref}/reject", response_model=schemas.TicketDetailOut)
def reject(
    ref: str,
    body: schemas.TicketRejectIn,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(panel),
) -> schemas.TicketDetailOut:
    t = _ticket(session, user, ref)
    try:
        tickets.reject(session, actor_of(request, user, session), user, t, body.remark)
    except HANDLED as exc:
        raise http_error(exc) from exc
    return _detail(session, user, t)


@router.post("/{ref}/withdraw", response_model=schemas.TicketDetailOut)
def withdraw(
    ref: str,
    request: Request,
    body: schemas.TicketRemarkIn | None = None,
    session: Session = Depends(get_session),
    user: User = Depends(panel),
) -> schemas.TicketDetailOut:
    t = _ticket(session, user, ref)
    try:
        tickets.withdraw(session, actor_of(request, user, session), user, t, body.remark if body else None)
    except HANDLED as exc:
        raise http_error(exc) from exc
    return _detail(session, user, t)


@router.post(
    "/{ref}/documents", status_code=status.HTTP_201_CREATED, response_model=schemas.TicketDocumentOut
)
def attach_document(
    ref: str,
    request: Request,
    file: UploadFile = File(...),
    doc_type: str = Form("government_order"),
    doc_date: date | None = Form(None),
    description: str | None = Form(None),
    session: Session = Depends(get_session),
    user: User = Depends(panel),
    scanner: Scanner = Depends(get_scanner),
) -> schemas.TicketDocumentOut:
    """While the ticket is open (409 `ticket_closed` after any decision); the kind's types only."""
    settings = request.app.state.settings
    t = _ticket(session, user, ref)
    data = _read(file, settings.upload_max_bytes)
    try:
        doc = tickets.attach_document(
            session,
            actor_of(request, user, session),
            user,
            t,
            data=data,
            filename=file.filename or "",
            doc_type=doc_type,
            doc_date=doc_date,
            description=description,
            scanner=scanner,
            store=LocalStore(settings.storage_dir),
            max_bytes=settings.upload_max_bytes,
        )
    except UploadRefused as exc:
        if exc.audited:
            session.commit()
        raise _upload_http(exc) from exc
    except HANDLED as exc:
        raise http_error(exc) from exc
    item = next(d for d in tickets.documents_of_ticket(session, t) if d["id"] == doc.id)
    session.commit()
    dispatch_extract(settings, doc.id)
    return schemas.TicketDocumentOut(**item)


@router.get("/{ref}/documents/{doc}/file")
def document_file(
    ref: str,
    doc: str,
    request: Request,
    disposition: str = Query("attachment", pattern="^(inline|attachment)$"),
    session: Session = Depends(get_session),
    user: User = Depends(panel),
) -> FileResponse:
    """The file, audited (`document.downloaded`)."""
    settings = request.app.state.settings
    t = _ticket(session, user, ref)
    try:
        d = tickets.ticket_document(session, user, t, doc)
        served = tickets.open_document(
            session,
            actor_of(request, user, session),
            user,
            d,
            store=LocalStore(settings.storage_dir),
            disposition=disposition,
        )
    except FileMissing as exc:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, {"code": "file_missing", "message": str(exc)}
        ) from exc
    except HANDLED as exc:
        raise http_error(exc) from exc
    return _serve(served)


@router.post("/{ref}/documents/{doc}/archive", response_model=schemas.TicketDocumentOut)
def archive_document(
    ref: str,
    doc: str,
    body: schemas.TicketArchiveIn,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(panel),
) -> schemas.TicketDocumentOut:
    """The uploader or the super admin, while the ticket is open; the document stays, listed as archived."""
    t = _ticket(session, user, ref)
    try:
        d = tickets.ticket_document(session, user, t, doc)
        tickets.archive_document(session, actor_of(request, user, session), user, t, d, body.reason)
    except HANDLED as exc:
        raise http_error(exc) from exc
    item = next(x for x in tickets.documents_of_ticket(session, t) if x["id"] == d.id)
    return schemas.TicketDocumentOut(**item)
