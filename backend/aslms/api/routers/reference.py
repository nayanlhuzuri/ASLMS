"""`/reference/labels` (design `portal-shell`, decision 16a): labels of user types, office kinds and ticket kinds,
each user type with `assignable` for the caller. Reachable during the first-sign-in steps (`/welcome/profile`).
`/reference/case-types` (design `portal-cases`, decision 14e): the High Court's active case types, for case
readers."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from aslms.api import schemas
from aslms.api.deps import current_user_pending, get_session, require_any
from aslms.domain.org import User
from aslms.domain.reference import Permission
from aslms.services import reference

router = APIRouter(prefix="/reference", tags=["reference"])


@router.get("/labels", response_model=schemas.ReferenceLabelsOut)
def labels(
    session: Session = Depends(get_session), user: User = Depends(current_user_pending)
) -> schemas.ReferenceLabelsOut:
    return schemas.ReferenceLabelsOut(**reference.labels(session, user))


@router.get("/case-types", response_model=list[schemas.CaseTypeOut])
def case_types(
    session: Session = Depends(get_session),
    user: User = Depends(require_any(Permission.CASES_VIEW_SCOPE, Permission.CASES_VIEW_ALL)),
) -> list[schemas.CaseTypeOut]:
    """The active case types of the High Court master (code, short and full name, the master's name), for the
    search filter and the court search form. The same for every reader."""
    return [schemas.CaseTypeOut(**row) for row in reference.case_types(session)]
