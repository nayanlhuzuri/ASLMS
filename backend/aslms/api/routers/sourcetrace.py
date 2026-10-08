"""SourceTrace ingestion administration (design `sourcetrace-connector`, "API"): the status, the failed documents
the caller may see, and a retry. Every endpoint needs `admin.sourcetrace`; the failure list and the retry apply the
document visibility rule (unknown and not visible both answer 404). The connector is reached only through
`services/sourcetrace_ingest.py`. Errors carry `{code, message}`."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from aslms.api import schemas
from aslms.api.deps import actor_of, get_session, require
from aslms.domain.org import User
from aslms.domain.reference import Permission
from aslms.services import sourcetrace_ingest as svc
from aslms.services.documents import resolve_document_ref
from aslms.services.visibility import NotVisibleDocument

router = APIRouter(prefix="/admin/sourcetrace", tags=["sourcetrace"])
admin_sourcetrace = require(Permission.ADMIN_SOURCETRACE)


@router.get("/status", response_model=schemas.SourcetraceStatusOut)
def get_status(
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(admin_sourcetrace),
) -> schemas.SourcetraceStatusOut:
    """The connector state, the counts by status (orders and uploads), the filings waiting for a CNR, the documents
    due now, the oldest pending document and the last run. Totals only, so no visibility filter."""
    return schemas.SourcetraceStatusOut(**svc.status(session, request.app.state.settings))


@router.get("/failed", response_model=schemas.SourcetraceFailedOut)
def list_failed(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
    user: User = Depends(admin_sourcetrace),
) -> schemas.SourcetraceFailedOut:
    """Failed documents of the cases the caller may see, with the latest attempt's error, family and time."""
    items, total = svc.failed(session, user, limit=limit, offset=offset)
    return schemas.SourcetraceFailedOut(total=total, items=items)


@router.post(
    "/documents/{doc}/retry",
    response_model=schemas.SourcetraceRetryOut,
    responses={404: {"model": schemas.ErrorOut}, 409: {"model": schemas.ErrorOut}},
)
def retry_document(
    doc: str,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(admin_sourcetrace),
) -> schemas.SourcetraceRetryOut:
    """A failed document (or one waiting on back-off) goes back to the queue with no attempts; audited."""
    actor = actor_of(request, user, session)
    try:
        row = resolve_document_ref(session, doc)
        row = svc.retry(session, actor, user, row)
    except NotVisibleDocument as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, {"code": "not_found", "message": "no such document"}
        ) from exc
    except svc.NotRetryable as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, {"code": exc.code, "message": str(exc)}) from exc
    return schemas.SourcetraceRetryOut(
        document_id=row.id,
        sourcetrace_status=row.sourcetrace_status.value
        if hasattr(row.sourcetrace_status, "value")
        else str(row.sourcetrace_status),
        sourcetrace_attempts=int(row.sourcetrace_attempts or 0),
    )
