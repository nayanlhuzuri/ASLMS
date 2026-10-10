"""`/reference/labels` (design `portal-shell`, decision 16a): labels of user types, office kinds and ticket kinds,
each user type with `assignable` for the caller. Reachable during the first-sign-in steps (`/welcome/profile`)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from aslms.api import schemas
from aslms.api.deps import current_user_pending, get_session
from aslms.domain.org import User
from aslms.services import reference

router = APIRouter(prefix="/reference", tags=["reference"])


@router.get("/labels", response_model=schemas.ReferenceLabelsOut)
def labels(
    session: Session = Depends(get_session), user: User = Depends(current_user_pending)
) -> schemas.ReferenceLabelsOut:
    return schemas.ReferenceLabelsOut(**reference.labels(session, user))
