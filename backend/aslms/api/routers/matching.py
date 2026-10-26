"""`/admin/scoring-settings`, `/admin/counsel-codes`, `/admin/keywords`, `/admin/name-patterns`,
`/admin/watchlist` and `/admin/matching/cases/{ref}/scores`: the matching rules and the scoring settings
(design `recommend-and-claim`, decisions 13, 14, 19, 21). Reads are filtered to the caller's office subtree
on the server (generic State codes are readable by every holder of `admin.counsel_codes`); every write goes
through `services/matching_rules.py` or `services/scoring_settings.py`, which enforce scope, the
`admin.scoring` rule for weights, and audit. Rule edits take effect at the next rescore (within 15 minutes)."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from aslms.api import schemas
from aslms.api.deps import actor_of, current_user, get_session, require
from aslms.api.errors import detail
from aslms.core.config import Settings
from aslms.domain.cases import Case
from aslms.domain.org import Office, User
from aslms.domain.ownership import (
    CaseOfficeScore,
    CounselCode,
    OfficeKeyword,
    OfficeNamePattern,
    OfficeWatchlist,
    ScoringSettings,
)
from aslms.domain.reference import Permission
from aslms.services import access, matching, matching_rules
from aslms.services import scoring_settings as ss
from aslms.services.access import Forbidden
from aslms.services.cases import CaseNotFound, resolve_case_ref
from aslms.services.discovery import discoverable, rule_discovery
from aslms.services.matching_rules import UNSET, DuplicateRule, NotDiscoverable, RuleError, effective_weight
from aslms.services.offices import find_office
from aslms.services.scoring_settings import SettingsError, StaleSettings

log = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["matching"])
APPLIES_WITHIN_MINUTES = 15
RESCORE_TASK = "aslms.rescore_if_dirty"


# ------------------------------------------------------------------------------------------------ helpers


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, Forbidden):
        return HTTPException(status.HTTP_403_FORBIDDEN, str(exc))
    if isinstance(exc, DuplicateRule | StaleSettings):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc))
    if isinstance(exc, IntegrityError):
        return HTTPException(status.HTTP_409_CONFLICT, "another change happened at the same time")
    if isinstance(exc, CaseNotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, "no such case")
    if isinstance(exc, NotDiscoverable):
        return HTTPException(status.HTTP_400_BAD_REQUEST, detail(NotDiscoverable.code, str(exc)))
    if isinstance(exc, RuleError | SettingsError | ValueError):
        return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    raise exc


def _office_ref(session: Session, office_id) -> schemas.OfficeRefOut:
    o = session.get(Office, office_id)
    return schemas.OfficeRefOut(code=o.code if o else "?", name=o.name if o else "?")


def _office_by_code(session: Session, code: str) -> Office:
    office = find_office(session, code)
    if office is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"no such office {code!r}")
    return office


def _optional_office(session: Session, code: str | None) -> Office | None:
    return _office_by_code(session, code) if code else None


def _weight_arg(body: Any) -> Any:
    """`weight` left out → UNSET (no change); `null` → clear; a number → the override."""
    return body.weight if "weight" in body.model_fields_set else UNSET


def _discover_arg(body: Any) -> Any:
    """`discover` left out or null → UNSET (the default on create, unchanged on update)."""
    value = getattr(body, "discover", None)
    return UNSET if value is None else bool(value)


def _load_rule(session: Session, caller: User, model, rule_id: uuid.UUID):
    """A rule by id when its office is in the caller's subtree (generic codes for everyone holding the
    function). Unknown and out-of-scope are both 404."""
    row = session.get(model, rule_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such rule")
    office = session.get(Office, row.office_id)
    if office is None or not (
        access.in_scope(session, caller, office) or getattr(row, "is_generic_state", False)
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such rule")
    return row


def dispatch_rescore(settings: Settings) -> bool:
    """Dispatches the Celery task `aslms.rescore_if_dirty`; False when no broker is configured or the
    dispatch fails (the 15-minute beat picks the change up). Never raises."""
    if not settings.redis_url:
        log.info("scoring settings saved; no broker configured, the beat will rescore")
        return False
    try:
        from aslms.jobs.celery_app import app as celery_app

        celery_app.send_task(RESCORE_TASK, retry=False)
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("could not dispatch %s: %s", RESCORE_TASK, exc)
        return False


# ------------------------------------------------------------------------------------------------ scoring settings


def _settings_out(session: Session, row: ScoringSettings | None) -> schemas.ScoringSettingsOut:
    if row is None:
        s = ss.DEFAULTS
        return schemas.ScoringSettingsOut(
            version=s.version,
            weights=dict(s.weights),
            thresholds={"strong": s.threshold_strong, "possible": s.threshold_possible},
            reason=None,
            valid_from=None,
            engine_version=matching.engine_version(s),
        )
    s = ss.from_row(row)
    by = session.get(User, row.created_by) if row.created_by else None
    return schemas.ScoringSettingsOut(
        version=s.version,
        weights=dict(s.weights),
        thresholds={"strong": s.threshold_strong, "possible": s.threshold_possible},
        reason=row.reason,
        valid_from=row.valid_from,
        valid_to=row.valid_to,
        updated_by=schemas.UserRefOut(id=by.id, full_name=by.full_name) if by else None,
        engine_version=matching.engine_version(s),
    )


def _may_read_settings(session: Session, user: User) -> None:
    if not any(
        access.has(session, user, p)
        for p in (Permission.ADMIN_SCORING, Permission.ADMIN_COUNSEL_CODES, Permission.ADMIN_KEYWORDS)
    ):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "admin.scoring, admin.counsel_codes or admin.keywords is needed"
        )


@router.get("/scoring-settings", response_model=schemas.ScoringSettingsOut)
def get_scoring_settings(
    session: Session = Depends(get_session), user: User = Depends(current_user)
) -> schemas.ScoringSettingsOut:
    """The current weights and thresholds (State-wide); read-only without `admin.scoring`."""
    _may_read_settings(session, user)
    return _settings_out(session, ss.current_row(session))


@router.put("/scoring-settings", response_model=schemas.ScoringSettingsSavedOut)
def put_scoring_settings(
    body: schemas.ScoringSettingsIn,
    request: Request,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.ADMIN_SCORING)),
) -> schemas.ScoringSettingsSavedOut:
    """Saves a new settings version, then dispatches the rescore after the commit."""
    try:
        _, changed = ss.update(
            session,
            actor_of(request, caller, session),
            caller,
            weights=body.weights.model_dump(),
            threshold_strong=body.thresholds.strong,
            threshold_possible=body.thresholds.possible,
            reason=body.reason,
            expected_version=body.expected_version,
        )
    except (Forbidden, SettingsError, IntegrityError) as exc:
        session.rollback()
        raise _http(exc) from exc
    dispatched = False
    if changed:
        session.commit()
        dispatched = dispatch_rescore(request.app.state.settings)
    out = _settings_out(session, ss.current_row(session))
    return schemas.ScoringSettingsSavedOut(
        **out.model_dump(),
        changed=changed,
        rescore_dispatched=dispatched,
        applies_within_minutes=APPLIES_WITHIN_MINUTES,
    )


@router.get("/scoring-settings/history", response_model=schemas.ScoringSettingsHistoryOut)
def scoring_settings_history(
    limit: int = 50,
    offset: int = 0,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.ADMIN_SCORING)),
) -> schemas.ScoringSettingsHistoryOut:
    rows, total = ss.history(session, caller, limit=max(1, min(limit, 200)), offset=max(0, offset))
    return schemas.ScoringSettingsHistoryOut(items=[_settings_out(session, r) for r in rows], total=total)


# ------------------------------------------------------------------------------------------------ counsel codes


def _code_out(session: Session, row: CounselCode, settings: ss.Settings, **extra) -> schemas.CounselCodeOut:
    return schemas.CounselCodeOut(
        id=row.id,
        code=row.code,
        office=_office_ref(session, row.office_id),
        weight_override=None if row.weight is None else float(row.weight),
        effective_weight=effective_weight(row, "counsel_code", settings),
        is_generic_state=row.is_generic_state,
        notes=row.notes,
        is_active=row.is_active,
        updated_at=row.updated_at,
        **extra,
    )


@router.get("/counsel-codes/unmapped", response_model=list[schemas.UnmappedCodeOut])
def unmapped_counsel_codes(
    limit: int = 200,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.ADMIN_COUNSEL_CODES)),
) -> list[schemas.UnmappedCodeOut]:
    """Codes seen in cause lists and dossiers with no mapping, most frequent first, each with the mappings in the
    caller's office subtree that it partly matches. Nothing is mapped automatically."""
    return [
        schemas.UnmappedCodeOut(**u.__dict__)
        for u in matching.unmapped_codes(
            session, limit=max(1, min(limit, 1000)), scope=matching_rules.counsel_code_scope(session, caller)
        )
    ]


@router.get("/counsel-codes", response_model=schemas.CounselCodeListOut)
def list_counsel_codes(
    office: str | None = None,
    q: str | None = None,
    include_inactive: bool = False,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.ADMIN_COUNSEL_CODES)),
) -> schemas.CounselCodeListOut:
    rows = matching_rules.list_counsel_codes(
        session, caller, office=_optional_office(session, office), q=q, include_inactive=include_inactive
    )
    settings = ss.current(session)
    return schemas.CounselCodeListOut(items=[_code_out(session, r, settings) for r in rows], total=len(rows))


@router.post("/counsel-codes", response_model=schemas.CounselCodeOut, status_code=status.HTTP_201_CREATED)
def create_counsel_code(
    body: schemas.CounselCodeIn,
    request: Request,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.ADMIN_COUNSEL_CODES)),
) -> schemas.CounselCodeOut:
    try:
        row = matching_rules.create_counsel_code(
            session,
            actor_of(request, caller, session),
            caller,
            code=body.code,
            office=_office_by_code(session, body.office_code),
            weight=_weight_arg(body),
            is_generic_state=body.is_generic_state,
            notes=body.notes,
        )
        session.flush()
    except (Forbidden, RuleError, IntegrityError) as exc:
        raise _http(exc) from exc
    return _code_out(session, row, ss.current(session), applies_within_minutes=APPLIES_WITHIN_MINUTES)


@router.patch("/counsel-codes/{rule_id}", response_model=schemas.CounselCodeOut)
def patch_counsel_code(
    rule_id: uuid.UUID,
    body: schemas.CounselCodePatchIn,
    request: Request,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.ADMIN_COUNSEL_CODES)),
) -> schemas.CounselCodeOut:
    row = _load_rule(session, caller, CounselCode, rule_id)
    try:
        matching_rules.update_counsel_code(
            session,
            actor_of(request, caller, session),
            caller,
            row,
            office=_optional_office(session, body.office_code),
            weight=_weight_arg(body),
            notes=body.notes,
        )
        session.flush()
    except (Forbidden, RuleError, IntegrityError) as exc:
        raise _http(exc) from exc
    return _code_out(session, row, ss.current(session), applies_within_minutes=APPLIES_WITHIN_MINUTES)


@router.post("/counsel-codes/{rule_id}/deactivate", response_model=schemas.CounselCodeOut)
def deactivate_counsel_code(
    rule_id: uuid.UUID,
    request: Request,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.ADMIN_COUNSEL_CODES)),
) -> schemas.CounselCodeOut:
    return _set_code_active(rule_id, False, request, session, caller)


@router.post("/counsel-codes/{rule_id}/reactivate", response_model=schemas.CounselCodeOut)
def reactivate_counsel_code(
    rule_id: uuid.UUID,
    request: Request,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.ADMIN_COUNSEL_CODES)),
) -> schemas.CounselCodeOut:
    return _set_code_active(rule_id, True, request, session, caller)


def _set_code_active(rule_id, enabled, request, session, caller) -> schemas.CounselCodeOut:
    row = _load_rule(session, caller, CounselCode, rule_id)
    try:
        matching_rules.set_counsel_code_active(
            session, actor_of(request, caller, session), caller, row, enabled
        )
        session.flush()
    except (Forbidden, RuleError) as exc:
        raise _http(exc) from exc
    return _code_out(session, row, ss.current(session), applies_within_minutes=APPLIES_WITHIN_MINUTES)


# ------------------------------------------------------------------------------------------------ keywords


def _keyword_out(session: Session, row: OfficeKeyword, settings: ss.Settings, **extra) -> schemas.KeywordOut:
    return schemas.KeywordOut(
        id=row.id,
        keyword=row.keyword,
        office=_office_ref(session, row.office_id),
        weight_override=None if row.weight is None else float(row.weight),
        effective_weight=effective_weight(row, "keyword", settings),
        is_active=row.is_active,
        updated_at=row.updated_at,
        discover=bool(row.discover),
        discoverable=discoverable(row.keyword),
        discovery=rule_discovery(session, row.keyword, bool(row.discover)),
        **extra,
    )


@router.get("/keywords", response_model=schemas.KeywordListOut)
def list_keywords(
    office: str | None = None,
    include_inactive: bool = False,
    discover: bool | None = None,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.ADMIN_KEYWORDS)),
) -> schemas.KeywordListOut:
    rows = matching_rules.list_rules(
        session,
        caller,
        OfficeKeyword,
        Permission.ADMIN_KEYWORDS,
        office=_optional_office(session, office),
        include_inactive=include_inactive,
        discover=discover,
    )
    settings = ss.current(session)
    return schemas.KeywordListOut(items=[_keyword_out(session, r, settings) for r in rows], total=len(rows))


@router.post("/keywords", response_model=schemas.KeywordOut, status_code=status.HTTP_201_CREATED)
def create_keyword(
    body: schemas.KeywordIn,
    request: Request,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.ADMIN_KEYWORDS)),
) -> schemas.KeywordOut:
    try:
        row = matching_rules.create_keyword(
            session,
            actor_of(request, caller, session),
            caller,
            keyword=body.keyword,
            office=_office_by_code(session, body.office_code),
            weight=_weight_arg(body),
            discover=_discover_arg(body),
        )
        session.flush()
    except (Forbidden, RuleError, IntegrityError) as exc:
        raise _http(exc) from exc
    return _keyword_out(session, row, ss.current(session), applies_within_minutes=APPLIES_WITHIN_MINUTES)


@router.patch("/keywords/{rule_id}", response_model=schemas.KeywordOut)
def patch_keyword(
    rule_id: uuid.UUID,
    body: schemas.DiscoverRulePatchIn,
    request: Request,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.ADMIN_KEYWORDS)),
) -> schemas.KeywordOut:
    row = _load_rule(session, caller, OfficeKeyword, rule_id)
    try:
        matching_rules.update_keyword(
            session,
            actor_of(request, caller, session),
            caller,
            row,
            weight=_weight_arg(body),
            discover=_discover_arg(body),
        )
        session.flush()
    except (Forbidden, RuleError) as exc:
        raise _http(exc) from exc
    return _keyword_out(session, row, ss.current(session), applies_within_minutes=APPLIES_WITHIN_MINUTES)


@router.post("/keywords/{rule_id}/deactivate", response_model=schemas.KeywordOut)
def deactivate_keyword(
    rule_id: uuid.UUID,
    request: Request,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.ADMIN_KEYWORDS)),
) -> schemas.KeywordOut:
    return _set_keyword_active(rule_id, False, request, session, caller)


@router.post("/keywords/{rule_id}/reactivate", response_model=schemas.KeywordOut)
def reactivate_keyword(
    rule_id: uuid.UUID,
    request: Request,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.ADMIN_KEYWORDS)),
) -> schemas.KeywordOut:
    return _set_keyword_active(rule_id, True, request, session, caller)


def _set_keyword_active(rule_id, enabled, request, session, caller) -> schemas.KeywordOut:
    row = _load_rule(session, caller, OfficeKeyword, rule_id)
    try:
        matching_rules.set_keyword_active(session, actor_of(request, caller, session), caller, row, enabled)
        session.flush()
    except (Forbidden, RuleError) as exc:
        raise _http(exc) from exc
    return _keyword_out(session, row, ss.current(session), applies_within_minutes=APPLIES_WITHIN_MINUTES)


# ------------------------------------------------------------------------------------------------ name patterns


def _pattern_out(
    session: Session, row: OfficeNamePattern, settings: ss.Settings, **extra
) -> schemas.NamePatternOut:
    return schemas.NamePatternOut(
        id=row.id,
        pattern=row.pattern,
        kind=str(row.kind.value) if hasattr(row.kind, "value") else str(row.kind),
        office=_office_ref(session, row.office_id),
        weight_override=None if row.weight is None else float(row.weight),
        effective_weight=effective_weight(row, "name_pattern", settings),
        is_active=row.is_active,
        updated_at=row.updated_at,
        discover=bool(row.discover),
        discoverable=discoverable(row.pattern, row.kind),
        discovery=rule_discovery(session, row.pattern, bool(row.discover)),
        **extra,
    )


@router.get("/name-patterns", response_model=schemas.NamePatternListOut)
def list_name_patterns(
    office: str | None = None,
    include_inactive: bool = False,
    discover: bool | None = None,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.ADMIN_KEYWORDS)),
) -> schemas.NamePatternListOut:
    rows = matching_rules.list_rules(
        session,
        caller,
        OfficeNamePattern,
        Permission.ADMIN_KEYWORDS,
        office=_optional_office(session, office),
        include_inactive=include_inactive,
        discover=discover,
    )
    settings = ss.current(session)
    return schemas.NamePatternListOut(
        items=[_pattern_out(session, r, settings) for r in rows], total=len(rows)
    )


@router.post("/name-patterns", response_model=schemas.NamePatternOut, status_code=status.HTTP_201_CREATED)
def create_name_pattern(
    body: schemas.NamePatternIn,
    request: Request,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.ADMIN_KEYWORDS)),
) -> schemas.NamePatternOut:
    try:
        row = matching_rules.create_name_pattern(
            session,
            actor_of(request, caller, session),
            caller,
            pattern=body.pattern,
            kind=body.kind,
            office=_office_by_code(session, body.office_code),
            weight=_weight_arg(body),
            discover=_discover_arg(body),
        )
        session.flush()
    except (Forbidden, RuleError, IntegrityError) as exc:
        raise _http(exc) from exc
    return _pattern_out(session, row, ss.current(session), applies_within_minutes=APPLIES_WITHIN_MINUTES)


@router.patch("/name-patterns/{rule_id}", response_model=schemas.NamePatternOut)
def patch_name_pattern(
    rule_id: uuid.UUID,
    body: schemas.DiscoverRulePatchIn,
    request: Request,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.ADMIN_KEYWORDS)),
) -> schemas.NamePatternOut:
    row = _load_rule(session, caller, OfficeNamePattern, rule_id)
    try:
        matching_rules.update_name_pattern(
            session,
            actor_of(request, caller, session),
            caller,
            row,
            weight=_weight_arg(body),
            discover=_discover_arg(body),
        )
        session.flush()
    except (Forbidden, RuleError) as exc:
        raise _http(exc) from exc
    return _pattern_out(session, row, ss.current(session), applies_within_minutes=APPLIES_WITHIN_MINUTES)


@router.post("/name-patterns/{rule_id}/deactivate", response_model=schemas.NamePatternOut)
def deactivate_name_pattern(
    rule_id: uuid.UUID,
    request: Request,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.ADMIN_KEYWORDS)),
) -> schemas.NamePatternOut:
    return _set_pattern_active(rule_id, False, request, session, caller)


@router.post("/name-patterns/{rule_id}/reactivate", response_model=schemas.NamePatternOut)
def reactivate_name_pattern(
    rule_id: uuid.UUID,
    request: Request,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.ADMIN_KEYWORDS)),
) -> schemas.NamePatternOut:
    return _set_pattern_active(rule_id, True, request, session, caller)


def _set_pattern_active(rule_id, enabled, request, session, caller) -> schemas.NamePatternOut:
    row = _load_rule(session, caller, OfficeNamePattern, rule_id)
    try:
        matching_rules.set_name_pattern_active(
            session, actor_of(request, caller, session), caller, row, enabled
        )
        session.flush()
    except (Forbidden, RuleError) as exc:
        raise _http(exc) from exc
    return _pattern_out(session, row, ss.current(session), applies_within_minutes=APPLIES_WITHIN_MINUTES)


# ------------------------------------------------------------------------------------------------ watchlist


def _watch_out(session: Session, row: OfficeWatchlist, settings: ss.Settings, **extra) -> schemas.WatchOut:
    case_ref = session.scalar(select(Case.ref_no).where(Case.id == row.case_id)) if row.case_id else None
    return schemas.WatchOut(
        id=row.id,
        cnr=row.cnr,
        case_ref=case_ref,
        office=_office_ref(session, row.office_id),
        reason=row.reason,
        weight_override=None if row.weight is None else float(row.weight),
        effective_weight=effective_weight(row, "watchlist", settings),
        is_active=row.is_active,
        updated_at=row.updated_at,
        **extra,
    )


@router.get("/watchlist", response_model=schemas.WatchListOut)
def list_watchlist(
    office: str | None = None,
    include_inactive: bool = False,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.ADMIN_WATCHLIST)),
) -> schemas.WatchListOut:
    rows = matching_rules.list_rules(
        session,
        caller,
        OfficeWatchlist,
        Permission.ADMIN_WATCHLIST,
        office=_optional_office(session, office),
        include_inactive=include_inactive,
    )
    settings = ss.current(session)
    return schemas.WatchListOut(items=[_watch_out(session, r, settings) for r in rows], total=len(rows))


@router.post("/watchlist", response_model=schemas.WatchOut, status_code=status.HTTP_201_CREATED)
def add_watch(
    body: schemas.WatchIn,
    request: Request,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.ADMIN_WATCHLIST)),
) -> schemas.WatchOut:
    """Watch a CNR. An unknown CNR queues a dossier fetch (`dossier_queued`); a held case is scored at once."""
    try:
        row, queued = matching_rules.add_watch(
            session,
            actor_of(request, caller, session),
            caller,
            cnr=body.cnr,
            office=_optional_office(session, body.office_code),
            reason=body.reason,
            weight=_weight_arg(body),
        )
        session.flush()
    except (Forbidden, RuleError, IntegrityError) as exc:
        raise _http(exc) from exc
    return _watch_out(session, row, ss.current(session), dossier_queued=queued)


@router.patch("/watchlist/{rule_id}", response_model=schemas.WatchOut)
def patch_watch(
    rule_id: uuid.UUID,
    body: schemas.WatchPatchIn,
    request: Request,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.ADMIN_WATCHLIST)),
) -> schemas.WatchOut:
    row = _load_rule(session, caller, OfficeWatchlist, rule_id)
    try:
        matching_rules.update_watch(
            session,
            actor_of(request, caller, session),
            caller,
            row,
            reason=body.reason,
            weight=_weight_arg(body),
        )
        session.flush()
    except (Forbidden, RuleError) as exc:
        raise _http(exc) from exc
    return _watch_out(session, row, ss.current(session))


@router.post("/watchlist/{rule_id}/deactivate", response_model=schemas.WatchOut)
def deactivate_watch(
    rule_id: uuid.UUID,
    request: Request,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.ADMIN_WATCHLIST)),
) -> schemas.WatchOut:
    return _set_watch_active(rule_id, False, request, session, caller)


@router.post("/watchlist/{rule_id}/reactivate", response_model=schemas.WatchOut)
def reactivate_watch(
    rule_id: uuid.UUID,
    request: Request,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.ADMIN_WATCHLIST)),
) -> schemas.WatchOut:
    return _set_watch_active(rule_id, True, request, session, caller)


def _set_watch_active(rule_id, enabled, request, session, caller) -> schemas.WatchOut:
    row = _load_rule(session, caller, OfficeWatchlist, rule_id)
    try:
        matching_rules.set_watch_active(session, actor_of(request, caller, session), caller, row, enabled)
        session.flush()
    except (Forbidden, RuleError) as exc:
        raise _http(exc) from exc
    return _watch_out(session, row, ss.current(session))


# ------------------------------------------------------------------------------------------------ case scores


@router.get("/matching/cases/{ref}/scores", response_model=list[schemas.CaseScoreOut])
def case_scores(
    ref: str,
    session: Session = Depends(get_session),
    caller: User = Depends(require(Permission.CASES_VIEW_ALL)),
) -> list[schemas.CaseScoreOut]:
    """Every department's score for a case with the signals behind it; State-wide readers only."""
    try:
        case = resolve_case_ref(session, ref)
    except CaseNotFound as exc:
        raise _http(exc) from exc
    settings = ss.current(session)
    rows = session.scalars(
        select(CaseOfficeScore)
        .where(CaseOfficeScore.case_id == case.id)
        .order_by(CaseOfficeScore.score.desc())
    ).all()
    out = []
    for r in rows:
        band = matching.band_of(float(r.score), settings)
        out.append(
            schemas.CaseScoreOut(
                office=_office_ref(session, r.office_id),
                score=float(r.score),
                band=band.value if band else None,
                signals=list(r.signals or []),
                computed_at=r.computed_at,
                engine_version=r.engine_version,
            )
        )
    return out
