"""Administration (plan §5.11) and the audit log (§5.13).

Who may do what:
  central_operator   everything, State-wide
  dept_admin         offices, users, counsel codes, patterns, keywords and watchlist of their own department
  auditor, state_oversight   read-only: audit log, lists"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select

from aslms.api import schemas as S
from aslms.api.deps import Ctx, current_ctx, roles
from aslms.core.errors import ForbiddenError, NotFoundError, ValidationError
from aslms.core.time import IST
from aslms.domain.events import AuditLog
from aslms.domain.ops import SourceFailure
from aslms.domain.org import Office, OfficeKind, Role, User
from aslms.domain.ownership import CounselCode, OfficeKeyword, OfficeNamePattern, OfficeWatchlist, PatternKind
from aslms.domain.reference import CaseType
from aslms.services import admin as admin_svc
from aslms.services import audit
from aslms.services.scope import can_admin_office, require_write

router = APIRouter(tags=["administration"])
ADMINS = (Role.CENTRAL_OPERATOR, Role.DEPT_ADMIN)
READERS = (Role.CENTRAL_OPERATOR, Role.DEPT_ADMIN, Role.DEPT_HEAD, Role.STATE_OVERSIGHT, Role.AUDITOR)


def _require_office_admin(ctx: Ctx, office_id: uuid.UUID) -> None:
    if not can_admin_office(ctx.db, ctx.principal, office_id):
        raise ForbiddenError("you can administer only your own department")


# ------------------------------------------------------------------ offices
@router.get("/offices", response_model=list[S.OfficeOut])
def offices(
    kind: str | None = None,
    active: bool = True,
    include_inactive: bool = False,
    ctx: Ctx = Depends(current_ctx),
) -> list[S.OfficeOut]:
    """Every signed-in user can list offices (needed to suggest a department or transfer).
    `include_inactive=true` returns active and inactive offices together."""
    stmt = select(Office)
    if kind:
        stmt = stmt.where(Office.kind == OfficeKind(kind))
    if not include_inactive:
        stmt = stmt.where(Office.is_active.is_(active))
    return [S.OfficeOut.model_validate(o) for o in ctx.db.scalars(stmt.order_by(Office.path))]


@router.post("/offices", response_model=S.OfficeOut, status_code=201)
def create_office(body: S.OfficeIn, ctx: Ctx = Depends(roles(*ADMINS))) -> S.OfficeOut:
    kind = OfficeKind(body.kind)
    if ctx.principal.role == Role.DEPT_ADMIN:
        if body.parent_id is None or not can_admin_office(ctx.db, ctx.principal, body.parent_id):
            raise ForbiddenError("a department admin can add offices only under their own department")
        if kind not in (OfficeKind.DIRECTORATE, OfficeKind.SECTION, OfficeKind.COUNSEL_OFFICE):
            raise ForbiddenError("a department admin can add directorates, sections and counsel offices")
    return S.OfficeOut.model_validate(
        admin_svc.create_office(
            ctx.db, ctx.actor, code=body.code, name=body.name, kind=kind, parent_id=body.parent_id
        )
    )


@router.patch("/offices/{office_id}", response_model=S.OfficeOut)
def update_office(
    office_id: uuid.UUID, body: S.OfficePatch, ctx: Ctx = Depends(roles(*ADMINS))
) -> S.OfficeOut:
    _require_office_admin(ctx, office_id)
    office = ctx.db.get(Office, office_id)
    return S.OfficeOut.model_validate(
        admin_svc.update_office(ctx.db, ctx.actor, office, name=body.name, is_active=body.is_active)
    )


# ------------------------------------------------------------------ users
@router.get("/users", response_model=S.Page[S.UserOut])
def users(
    office_id: uuid.UUID | None = None,
    role: str | None = None,
    q: str | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    ctx: Ctx = Depends(roles(*READERS)),
):
    stmt = select(User).join(Office, Office.id == User.office_id)
    if not ctx.principal.is_state_tier:
        p = ctx.principal.department_path
        stmt = stmt.where(or_(Office.path == p, Office.path.like(p + "/%")))
    if office_id:
        stmt = stmt.where(User.office_id == office_id)
    if role:
        stmt = stmt.where(User.role == Role(role))
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(or_(func.lower(User.full_name).like(like), func.lower(User.email).like(like)))
    total = ctx.db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = ctx.db.scalars(stmt.order_by(Office.path, User.full_name).offset((page - 1) * size).limit(size))
    return S.Page(total=total, page=page, size=size, items=[S.UserOut.model_validate(u) for u in rows])


@router.get("/offices/{office_id}/officers", response_model=list[S.UserOut])
def officers(office_id: uuid.UUID, ctx: Ctx = Depends(current_ctx)) -> list[S.UserOut]:
    """Users of an office and its sub-offices (to allot a case). Limited to your own department."""
    office = ctx.db.get(Office, office_id)
    if office is None:
        raise NotFoundError("office not found")
    if not ctx.principal.is_state_tier and office.path.split("/")[0] != ctx.principal.department_path:
        raise ForbiddenError("outside your department")
    rows = ctx.db.scalars(
        select(User)
        .join(Office, Office.id == User.office_id)
        .where(
            User.is_active.is_(True), or_(Office.path == office.path, Office.path.like(office.path + "/%"))
        )
        .order_by(User.full_name)
    )
    return [S.UserOut.model_validate(u) for u in rows]


@router.post("/users", response_model=S.UserOut, status_code=201)
def create_user(body: S.UserIn, ctx: Ctx = Depends(roles(*ADMINS))) -> S.UserOut:
    _require_office_admin(ctx, body.office_id)
    role = Role(body.role)
    if ctx.principal.role == Role.DEPT_ADMIN and role in (
        Role.STATE_OVERSIGHT,
        Role.CENTRAL_OPERATOR,
        Role.AUDITOR,
    ):
        raise ForbiddenError("a department admin cannot create State-level users")
    return S.UserOut.model_validate(
        admin_svc.create_user(
            ctx.db,
            ctx.actor,
            email=body.email,
            full_name=body.full_name,
            office_id=body.office_id,
            role=role,
            password=body.password,
            designation=body.designation,
            mobile=body.mobile,
        )
    )


@router.patch("/users/{user_id}", response_model=S.UserOut)
def update_user(user_id: uuid.UUID, body: S.UserPatch, ctx: Ctx = Depends(roles(*ADMINS))) -> S.UserOut:
    user = ctx.db.get(User, user_id)
    if user is None:
        raise NotFoundError("user not found")
    _require_office_admin(ctx, user.office_id)
    changes = body.model_dump(exclude_none=True)
    if "office_id" in changes:
        _require_office_admin(ctx, changes["office_id"])
    if "role" in changes:
        changes["role"] = Role(changes["role"])
        if ctx.principal.role == Role.DEPT_ADMIN and changes["role"] in (
            Role.STATE_OVERSIGHT,
            Role.CENTRAL_OPERATOR,
            Role.AUDITOR,
        ):
            raise ForbiddenError("a department admin cannot grant State-level roles")
    if user.id == ctx.user.id and changes.get("is_active") is False:
        raise ValidationError("you cannot disable your own account")
    return S.UserOut.model_validate(admin_svc.update_user(ctx.db, ctx.actor, user, **changes))


# ------------------------------------------------------------------ mapping
def _mapping_scope(ctx: Ctx, stmt, col):
    if ctx.principal.is_state_tier:
        return stmt
    p = ctx.principal.department_path
    return stmt.where(col.in_(select(Office.id).where(or_(Office.path == p, Office.path.like(p + "/%")))))


@router.get("/mapping/codes", response_model=list[S.CounselCodeOut])
def codes(ctx: Ctx = Depends(roles(*READERS))) -> list[S.CounselCodeOut]:
    stmt = _mapping_scope(ctx, select(CounselCode), CounselCode.office_id)
    return [S.CounselCodeOut.model_validate(c) for c in ctx.db.scalars(stmt.order_by(CounselCode.code))]


@router.post("/mapping/codes", response_model=S.CounselCodeOut)
def upsert_code(body: S.CounselCodeIn, ctx: Ctx = Depends(roles(*ADMINS))) -> S.CounselCodeOut:
    _require_office_admin(ctx, body.office_id)
    existing = ctx.db.scalar(select(CounselCode).where(CounselCode.code == body.code.strip().upper()))
    if existing and not can_admin_office(ctx.db, ctx.principal, existing.office_id):
        raise ForbiddenError("this code is mapped to another department; ask the central operator")
    if body.is_generic_state and ctx.principal.role != Role.CENTRAL_OPERATOR:
        raise ForbiddenError("only the central operator marks generic State codes")
    row = admin_svc.upsert_counsel_code(
        ctx.db,
        ctx.actor,
        code=body.code,
        office_id=body.office_id,
        weight=body.weight,
        is_generic_state=body.is_generic_state,
        notes=body.notes,
    )
    # recommendations follow the mapping at once for the cases that carry this code
    admin_svc.rescore_for_code(ctx.db, row.code)
    return S.CounselCodeOut.model_validate(row)


@router.delete("/mapping/codes/{code_id}", response_model=S.Ok)
def deactivate_code(code_id: uuid.UUID, ctx: Ctx = Depends(roles(*ADMINS))) -> S.Ok:
    row = ctx.db.get(CounselCode, code_id)
    if row is None:
        raise NotFoundError("code not found")
    _require_office_admin(ctx, row.office_id)
    row.is_active = False
    audit.record(
        ctx.db, ctx.actor, "mapping.counsel_code.deactivate", "counsel_code", row.id, after={"code": row.code}
    )
    ctx.db.flush()
    admin_svc.rescore_for_code(ctx.db, row.code)
    return S.Ok()


@router.get("/mapping/unmapped-codes", response_model=list[S.UnmappedCodeOut])
def unmapped(limit: int = Query(100, le=500), ctx: Ctx = Depends(roles(*READERS))) -> list[S.UnmappedCodeOut]:
    return [S.UnmappedCodeOut(**r) for r in admin_svc.unmapped_codes(ctx.db, limit)]


@router.get("/mapping/patterns", response_model=list[S.PatternOut])
def patterns(ctx: Ctx = Depends(roles(*READERS))) -> list[S.PatternOut]:
    stmt = _mapping_scope(ctx, select(OfficeNamePattern), OfficeNamePattern.office_id)
    return [S.PatternOut.model_validate(p) for p in ctx.db.scalars(stmt.order_by(OfficeNamePattern.pattern))]


@router.post("/mapping/patterns", response_model=S.PatternOut, status_code=201)
def add_pattern(body: S.PatternIn, ctx: Ctx = Depends(roles(*ADMINS))) -> S.PatternOut:
    _require_office_admin(ctx, body.office_id)
    kind = PatternKind(body.kind)
    if kind == PatternKind.REGEX:
        import re

        try:
            re.compile(body.pattern)
        except re.error as e:
            raise ValidationError(f"invalid regular expression: {e}") from e
    row = ctx.db.scalar(
        select(OfficeNamePattern).where(
            OfficeNamePattern.office_id == body.office_id, OfficeNamePattern.pattern == body.pattern.strip()
        )
    )
    if row is None:
        row = OfficeNamePattern(
            office_id=body.office_id, pattern=body.pattern.strip(), kind=kind, weight=body.weight
        )
        ctx.db.add(row)
    else:
        row.kind, row.weight, row.is_active = kind, body.weight, True
    ctx.db.flush()
    audit.record(
        ctx.db,
        ctx.actor,
        "mapping.pattern",
        "office_name_pattern",
        row.id,
        after=body.model_dump(mode="json"),
    )
    admin_svc.queue_rescore_all()
    return S.PatternOut.model_validate(row)


@router.delete("/mapping/patterns/{pattern_id}", response_model=S.Ok)
def remove_pattern(pattern_id: uuid.UUID, ctx: Ctx = Depends(roles(*ADMINS))) -> S.Ok:
    row = ctx.db.get(OfficeNamePattern, pattern_id)
    if row is None:
        raise NotFoundError("pattern not found")
    _require_office_admin(ctx, row.office_id)
    row.is_active = False
    audit.record(ctx.db, ctx.actor, "mapping.pattern.deactivate", "office_name_pattern", row.id)
    return S.Ok()


@router.get("/mapping/keywords", response_model=list[S.KeywordOut])
def keywords(ctx: Ctx = Depends(roles(*READERS))) -> list[S.KeywordOut]:
    stmt = _mapping_scope(ctx, select(OfficeKeyword), OfficeKeyword.office_id)
    return [S.KeywordOut.model_validate(k) for k in ctx.db.scalars(stmt.order_by(OfficeKeyword.keyword))]


@router.post("/mapping/keywords", response_model=S.KeywordOut, status_code=201)
def add_keyword(body: S.KeywordIn, ctx: Ctx = Depends(roles(*ADMINS))) -> S.KeywordOut:
    _require_office_admin(ctx, body.office_id)
    if not 0 <= body.weight <= 0.6:
        raise ValidationError("keyword weight must be between 0 and 0.6")
    row = ctx.db.scalar(
        select(OfficeKeyword).where(
            OfficeKeyword.office_id == body.office_id, OfficeKeyword.keyword == body.keyword.strip()
        )
    )
    if row is None:
        row = OfficeKeyword(office_id=body.office_id, keyword=body.keyword.strip(), weight=body.weight)
        ctx.db.add(row)
    else:
        row.weight, row.is_active = body.weight, True
    ctx.db.flush()
    audit.record(
        ctx.db, ctx.actor, "mapping.keyword", "office_keyword", row.id, after=body.model_dump(mode="json")
    )
    admin_svc.queue_rescore_all()
    return S.KeywordOut.model_validate(row)


@router.delete("/mapping/keywords/{keyword_id}", response_model=S.Ok)
def remove_keyword(keyword_id: uuid.UUID, ctx: Ctx = Depends(roles(*ADMINS))) -> S.Ok:
    row = ctx.db.get(OfficeKeyword, keyword_id)
    if row is None:
        raise NotFoundError("keyword not found")
    _require_office_admin(ctx, row.office_id)
    row.is_active = False
    audit.record(ctx.db, ctx.actor, "mapping.keyword.deactivate", "office_keyword", row.id)
    return S.Ok()


@router.get("/mapping/watchlist", response_model=list[S.WatchOut])
def watchlist(ctx: Ctx = Depends(current_ctx)) -> list[S.WatchOut]:
    stmt = _mapping_scope(
        ctx, select(OfficeWatchlist).where(OfficeWatchlist.is_active.is_(True)), OfficeWatchlist.office_id
    )
    return [
        S.WatchOut.model_validate(w) for w in ctx.db.scalars(stmt.order_by(OfficeWatchlist.created_at.desc()))
    ]


@router.post("/mapping/watchlist", response_model=S.WatchOut, status_code=201)
def add_watch(
    body: S.WatchIn, ctx: Ctx = Depends(roles(Role.DEPT_ADMIN, Role.DEPT_HEAD, Role.CENTRAL_OPERATOR))
) -> S.WatchOut:
    office_id = body.office_id or ctx.principal.department_id
    if office_id is None:
        raise ValidationError("office_id is required")
    if ctx.principal.role != Role.CENTRAL_OPERATOR and office_id != ctx.principal.department_id:
        raise ForbiddenError("you can watch cases only for your own department")
    return S.WatchOut.model_validate(admin_svc.watch(ctx.db, ctx.actor, office_id, body.cnr, body.reason))


@router.delete("/mapping/watchlist/{watch_id}", response_model=S.Ok)
def remove_watch(
    watch_id: uuid.UUID, ctx: Ctx = Depends(roles(Role.DEPT_ADMIN, Role.DEPT_HEAD, Role.CENTRAL_OPERATOR))
) -> S.Ok:
    row = ctx.db.get(OfficeWatchlist, watch_id)
    if row is None:
        raise NotFoundError("watch not found")
    if ctx.principal.role != Role.CENTRAL_OPERATOR and row.office_id != ctx.principal.department_id:
        raise ForbiddenError("not your department")
    row.is_active = False
    audit.record(ctx.db, ctx.actor, "mapping.watch.remove", "office_watchlist", row.id)
    return S.Ok()


# ------------------------------------------------------------------ masters & operations
@router.get("/masters/case-types", response_model=list[S.CaseTypeOut])
def case_types(ctx: Ctx = Depends(current_ctx)) -> list[S.CaseTypeOut]:
    return [
        S.CaseTypeOut.model_validate(c) for c in ctx.db.scalars(select(CaseType).order_by(CaseType.type_name))
    ]


@router.get("/ops/failures", response_model=list[S.FailureOut])
def failures(
    open_only: bool = True, ctx: Ctx = Depends(roles(Role.CENTRAL_OPERATOR, Role.AUDITOR))
) -> list[dict]:
    stmt = select(SourceFailure)
    if open_only:
        stmt = stmt.where(SourceFailure.resolved_at.is_(None))
    return [
        {
            "id": str(f.id),
            "kind": f.kind.value,
            "ref": f.ref,
            "error": f.error,
            "attempts": f.attempts,
            "first_seen": f.first_seen.isoformat(),
            "last_seen": f.last_seen.isoformat(),
            "resolved_at": f.resolved_at.isoformat() if f.resolved_at else None,
        }
        for f in ctx.db.scalars(stmt.order_by(SourceFailure.last_seen.desc()).limit(500))
    ]


@router.post("/ops/failures/{failure_id}/resolve", response_model=S.Ok)
def resolve_failure(failure_id: uuid.UUID, ctx: Ctx = Depends(roles(Role.CENTRAL_OPERATOR))) -> S.Ok:
    from aslms.core.time import now_utc

    f = ctx.db.get(SourceFailure, failure_id)
    if f is None:
        raise NotFoundError("failure not found")
    f.resolved_at = now_utc()
    audit.record(ctx.db, ctx.actor, "ops.failure.resolve", "source_failure", f.id, after={"ref": f.ref})
    return S.Ok()


@router.post("/ops/jobs", response_model=S.Ok, status_code=202)
def run_job(body: S.JobIn, ctx: Ctx = Depends(roles(Role.CENTRAL_OPERATOR))) -> S.Ok:
    """Queues a background job on the Celery queues (runs in the workers, not in the API)."""
    require_write(ctx.principal)
    from aslms.jobs import tasks

    jobs = {
        "daily_cycle": lambda: tasks.ingest_daily_cycle.delay((body.list_date or date.today()).isoformat()),
        "status_refresh": lambda: tasks.track_status_refresh.delay(),
        "full_refresh": lambda: tasks.track_full_refresh.delay(),
        "master_sync": lambda: tasks.ops_master_sync.delay(),
        "discovery": lambda: tasks.track_discovery.delay(),
        "rescore": lambda: tasks.ops_rescore_all.delay(),
        "alerts": lambda: tasks.notify_alerts.delay(),
        "sourcetrace": lambda: tasks.documents_sourcetrace.delay(),
    }
    if body.job not in jobs:
        raise ValidationError("unknown job", available=list(jobs))
    result = jobs[body.job]()
    audit.record(
        ctx.db,
        ctx.actor,
        "ops.job",
        "job",
        None,
        after={"job": body.job, "list_date": str(body.list_date or ""), "task_id": str(result.id)},
    )
    return S.Ok(detail=str(result.id))


# ------------------------------------------------------------------ audit log
@router.get("/audit", response_model=S.Page[S.AuditOut])
def audit_log(
    user_id: uuid.UUID | None = None,
    case_id: uuid.UUID | None = None,
    action: str | None = None,
    start: date | None = Query(None, alias="from"),
    end: date | None = Query(None, alias="to"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=500),
    ctx: Ctx = Depends(
        roles(Role.AUDITOR, Role.CENTRAL_OPERATOR, Role.STATE_OVERSIGHT, Role.DEPT_ADMIN, Role.DEPT_HEAD)
    ),
):
    stmt = select(AuditLog)
    if not ctx.principal.is_state_tier:
        # department admins/heads see actions by their own department's users
        p = ctx.principal.department_path
        stmt = stmt.where(
            AuditLog.actor_user_id.in_(
                select(User.id)
                .join(Office, Office.id == User.office_id)
                .where(or_(Office.path == p, Office.path.like(p + "/%")))
            )
        )
    if user_id:
        stmt = stmt.where(AuditLog.actor_user_id == user_id)
    if case_id:
        stmt = stmt.where(AuditLog.case_id == case_id)
    if action:
        stmt = stmt.where(AuditLog.action.like(f"{action}%"))
    if start:
        stmt = stmt.where(AuditLog.created_at >= datetime.combine(start, time.min, tzinfo=IST))
    if end:
        stmt = stmt.where(AuditLog.created_at <= datetime.combine(end, time.max, tzinfo=IST))
    total = ctx.db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = ctx.db.scalars(stmt.order_by(AuditLog.created_at.desc()).offset((page - 1) * size).limit(size))
    items = [
        S.AuditOut(
            id=a.id,
            created_at=a.created_at,
            actor_name=a.actor_name,
            actor_designation=a.actor_designation,
            actor_office_code=a.actor_office_code,
            action=a.action,
            entity_type=a.entity_type,
            entity_id=a.entity_id,
            case_id=a.case_id,
            ip=str(a.ip) if a.ip else None,
            before=a.before,
            after=a.after,
        )
        for a in rows
    ]
    return S.Page(total=total, page=page, size=size, items=items)
