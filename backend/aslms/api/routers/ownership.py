"""`/cases/{ref}/ownership`, `/cases/{ref}/claim|dismiss|suggest|allot|take-over|stop-watching|transfers`
and `/transfers/{trf}/accept|decline|withdraw`: the human ownership decisions (design `recommend-and-claim`,
decisions 6-11 and 22). `{ref}` is a case id, `ref_no` (slash or dash form) or CNR; `{trf}` a transfer id or
`ref_no`. A case another department owns is 404 to the caller (not visible), never 403. Every write goes
through `services/ownership.py`, which locks the case row, checks the state, audits, emits the event and moves
custody. There is no release endpoint for a primary owner: a claimed case never returns to the pool."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from aslms.api import schemas
from aslms.api.deps import actor_of, get_session, require
from aslms.domain.cases import Case
from aslms.domain.org import User
from aslms.domain.ownership import CaseOfficeScore, CaseOwnership, OwnershipTransfer, Recommendation
from aslms.domain.reference import Permission
from aslms.services import inbox
from aslms.services import ownership as own
from aslms.services.access import Forbidden
from aslms.services.cases import CaseNotFound, resolve_case_ref
from aslms.services.ownership import UNSET, NotVisible, OwnershipConflict, OwnershipError

router = APIRouter(tags=["ownership"])


# ------------------------------------------------------------------------------------------------ helpers


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, Forbidden):
        return HTTPException(status.HTTP_403_FORBIDDEN, str(exc))
    if isinstance(exc, NotVisible | CaseNotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, "no such case")
    if isinstance(exc, OwnershipConflict):
        return HTTPException(status.HTTP_409_CONFLICT, {"code": exc.code, "message": str(exc)})
    if isinstance(exc, own.OfficeRequired):
        return HTTPException(
            status.HTTP_400_BAD_REQUEST,
            {"code": "office_required", "message": str(exc), "candidates": exc.candidates},
        )
    if isinstance(exc, IntegrityError):
        return HTTPException(
            status.HTTP_409_CONFLICT,
            {"code": "concurrent_change", "message": "another change to this case happened at the same time"},
        )
    if isinstance(exc, OwnershipError | ValueError):
        return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    raise exc


HANDLED = (Forbidden, NotVisible, CaseNotFound, OwnershipConflict, OwnershipError, IntegrityError)


def _case(session: Session, ref: str) -> Case:
    try:
        return resolve_case_ref(session, ref)
    except CaseNotFound as exc:
        raise _http(exc) from exc


def _transfer(session: Session, ref: str) -> OwnershipTransfer:
    try:
        return own.resolve_transfer(session, ref)
    except NotVisible as exc:
        raise _http(exc) from exc


def _ownership_out(session: Session, row: CaseOwnership) -> schemas.OwnershipOut:
    return schemas.OwnershipOut(**inbox.ownership_item(session, row))


def _recommendation_out(session: Session, rec: Recommendation) -> schemas.RecommendationOut:
    case = session.get(Case, rec.case_id)
    summary = inbox.summaries(session, [case])[case.id]
    owner = inbox.primary_codes(session, [case.id]).get(case.id)
    score = session.scalar(
        select(CaseOfficeScore).where(
            CaseOfficeScore.case_id == rec.case_id, CaseOfficeScore.office_id == rec.office_id
        )
    )
    return schemas.RecommendationOut(**inbox.recommendation_item(session, rec, summary, owner, score))


def _transfer_out(session: Session, t: OwnershipTransfer) -> schemas.TransferOut:
    return schemas.TransferOut(**inbox.transfer_item(session, t))


# ------------------------------------------------------------------------------------------------ reading


@router.get("/cases/{ref}/ownership", response_model=schemas.CaseOwnershipViewOut)
def case_ownership(
    ref: str,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.CASES_VIEW_SCOPE)),
) -> schemas.CaseOwnershipViewOut:
    """Primary owner, watchers, recommendations and the open transfer of a case. Visible when the caller's
    department owns, watches or is recommended the case, the case is in the pool and the caller holds
    `cases.claim`, or the caller holds `cases.view_all`; other departments' recommendations only with
    `cases.view_all`. `actions` says which ownership actions the caller may take now."""
    case = _case(session, ref)
    try:
        view = own.case_ownership_view(session, caller, case)
    except HANDLED as exc:
        raise _http(exc) from exc
    return schemas.CaseOwnershipViewOut(
        primary=_ownership_out(session, view["primary"]) if view["primary"] else None,
        watchers=[_ownership_out(session, r) for r in view["watchers"]],
        recommendations=[_recommendation_out(session, r) for r in view["recommendations"]],
        open_transfer=_transfer_out(session, view["open_transfer"]) if view["open_transfer"] else None,
        actions=schemas.OwnershipActionsOut(**own.available_actions(session, caller, case)),
    )


# ------------------------------------------------------------------------------------------------ decisions


@router.post("/cases/{ref}/claim", response_model=schemas.OwnershipOut, status_code=status.HTTP_201_CREATED)
def claim(
    ref: str,
    body: schemas.ClaimIn,
    request: Request,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.CASES_CLAIM)),
) -> schemas.OwnershipOut:
    """Claim for the caller's department (the super admin names `office_code`): primary when the case has no
    primary owner, else watcher. `unit_code` / `officer_user_id` allot in the same step (needs `cases.allot`)."""
    case = _case(session, ref)
    try:
        row = own.claim(
            session,
            actor_of(request, caller, session),
            caller,
            case,
            office_code=body.office_code,
            unit_code=body.unit_code,
            officer_user_id=body.officer_user_id,
            note=body.note,
        )
        session.flush()
    except HANDLED as exc:
        raise _http(exc) from exc
    return _ownership_out(session, row)


@router.post("/cases/{ref}/dismiss", response_model=schemas.RecommendationOut)
def dismiss(
    ref: str,
    body: schemas.DismissIn,
    request: Request,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.CASES_DISMISS)),
) -> schemas.RecommendationOut:
    """Dismiss the recommendation of the caller's department; `office_code` names which of the caller's
    departments (the inbox sends the one on screen), else decision 6 picks it."""
    case = _case(session, ref)
    try:
        rec = own.dismiss(
            session,
            actor_of(request, caller, session),
            caller,
            case,
            reason=body.reason,
            office_code=body.office_code,
        )
        session.flush()
    except HANDLED as exc:
        raise _http(exc) from exc
    return _recommendation_out(session, rec)


@router.post("/cases/{ref}/suggest", response_model=schemas.SuggestOut)
def suggest(
    ref: str,
    body: schemas.SuggestIn,
    request: Request,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.CASES_SUGGEST_ELSEWHERE)),
) -> schemas.SuggestOut:
    """Suggest another department: the caller's recommendation (if any) closes as `suggested_elsewhere` and
    the target receives a `suggestion` recommendation."""
    case = _case(session, ref)
    try:
        result = own.suggest(
            session,
            actor_of(request, caller, session),
            caller,
            case,
            office_code=body.office_code,
            reason=body.reason,
        )
        session.flush()
    except HANDLED as exc:
        raise _http(exc) from exc
    return schemas.SuggestOut(
        own=_recommendation_out(session, result.own) if result.own else None,
        target=_recommendation_out(session, result.target),
        target_already_recommended=result.target_already_recommended,
    )


@router.post("/cases/{ref}/allot", response_model=schemas.OwnershipOut)
def allot(
    ref: str,
    body: schemas.AllotIn,
    request: Request,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.CASES_ALLOT)),
) -> schemas.OwnershipOut:
    """Allot the department's row to a unit and/or an officer; a field left out is unchanged, `null` clears.
    `office_code` names which of the caller's departments acts (the inbox sends the one on screen)."""
    case = _case(session, ref)
    given = body.model_fields_set
    try:
        row = own.allot(
            session,
            actor_of(request, caller, session),
            caller,
            case,
            unit_code=body.unit_code if "unit_code" in given else UNSET,
            officer_user_id=body.officer_user_id if "officer_user_id" in given else UNSET,
            office_code=body.office_code,
        )
        session.flush()
    except HANDLED as exc:
        raise _http(exc) from exc
    return _ownership_out(session, row)


@router.post("/cases/{ref}/take-over", response_model=schemas.TakeOverOut)
def take_over(
    ref: str,
    body: schemas.TakeOverIn,
    request: Request,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.CASES_TAKE_OVER)),
) -> schemas.TakeOverOut:
    """Take over a case allotted to a colleague of the same department; the unit follows the taker."""
    case = _case(session, ref)
    try:
        result = own.take_over(
            session,
            actor_of(request, caller, session),
            caller,
            case,
            expected_officer_user_id=body.expected_officer_user_id,
            reason=body.reason,
        )
        session.flush()
    except HANDLED as exc:
        raise _http(exc) from exc
    prev = result.previous
    return schemas.TakeOverOut(
        **inbox.ownership_item(session, result.ownership),
        taken_from=schemas.UserRefOut(id=prev.id, full_name=prev.full_name) if prev else None,
    )


@router.post("/cases/{ref}/stop-watching", response_model=schemas.OwnershipOut)
def stop_watching(
    ref: str,
    body: schemas.StopWatchingIn,
    request: Request,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.CASES_RELEASE)),
) -> schemas.OwnershipOut:
    """End the department's watcher role. On a primary row → 409 `primary_cannot_release`."""
    case = _case(session, ref)
    try:
        row = own.stop_watching(session, actor_of(request, caller, session), caller, case, reason=body.reason)
        session.flush()
    except HANDLED as exc:
        raise _http(exc) from exc
    return _ownership_out(session, row)


# ------------------------------------------------------------------------------------------------ transfers


@router.post(
    "/cases/{ref}/transfers", response_model=schemas.TransferOut, status_code=status.HTTP_201_CREATED
)
def request_transfer(
    ref: str,
    body: schemas.TransferRequestIn,
    request: Request,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.CASES_TRANSFER_REQUEST)),
) -> schemas.TransferOut:
    """The primary owner asks another department to take the case; one open request per case."""
    case = _case(session, ref)
    try:
        t = own.request_transfer(
            session,
            actor_of(request, caller, session),
            caller,
            case,
            to_office_code=body.to_office_code,
            reason=body.reason,
            stay_as_watcher=body.stay_as_watcher,
        )
        session.flush()
    except HANDLED as exc:
        raise _http(exc) from exc
    return _transfer_out(session, t)


@router.post("/transfers/{trf}/accept", response_model=schemas.TransferOut)
def accept_transfer(
    trf: str,
    body: schemas.TransferDecisionIn,
    request: Request,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.CASES_TRANSFER_DECIDE)),
) -> schemas.TransferOut:
    return _decide(trf, True, body, request, session, caller)


@router.post("/transfers/{trf}/decline", response_model=schemas.TransferOut)
def decline_transfer(
    trf: str,
    body: schemas.TransferDecisionIn,
    request: Request,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.CASES_TRANSFER_DECIDE)),
) -> schemas.TransferOut:
    return _decide(trf, False, body, request, session, caller)


def _decide(trf, accept, body, request, session, caller) -> schemas.TransferOut:
    t = _transfer(session, trf)
    try:
        own.decide_transfer(
            session, actor_of(request, caller, session), caller, t, accept=accept, note=body.note
        )
        session.flush()
    except HANDLED as exc:
        raise _http(exc) from exc
    return _transfer_out(session, t)


@router.post("/transfers/{trf}/withdraw", response_model=schemas.TransferOut)
def withdraw_transfer(
    trf: str,
    request: Request,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.CASES_TRANSFER_REQUEST)),
) -> schemas.TransferOut:
    t = _transfer(session, trf)
    try:
        own.withdraw_transfer(session, actor_of(request, caller, session), caller, t)
        session.flush()
    except HANDLED as exc:
        raise _http(exc) from exc
    return _transfer_out(session, t)
