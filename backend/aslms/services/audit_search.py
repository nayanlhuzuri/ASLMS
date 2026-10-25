"""The audit log search (design `audit-screens`, decisions 1-4; plan §5.13: "searchable by user, case and date;
read-only for auditors").

- **Who** (decision 2): `audit.view` counts only in a State-wide membership (the super admin, or one holding
  `cases.view_all`); anyone else gets `Forbidden("audit_scope")`. The rows are read whole, never filtered per row.
- **What** (decision 1): filters by actor (login id or e-mail, or actor-name text), the login a row is about
  (`user` and `user_membership` rows), case (with the cases merged into it), actor office (its subtree, or the
  office alone with `office_subtree=False`, design `portal-ui-polish-2` decision 30), action
  (exact, or a prefix ending in `.`), entity type and id, and an IST date range. Newest first by
  `(created_at DESC, id DESC)` with an opaque keyset cursor; no total.
- **Cost** (decision 4): every search runs under `SET LOCAL statement_timeout`; a cancelled statement raises
  `SearchTimeout` (503 "narrow the search").
- **Reading writes nothing** (decision 3): no audit row, no event."""

from __future__ import annotations

import base64
import binascii
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import ColumnElement, and_, func, or_, select, text, tuple_
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from aslms.core.config import Settings, get_settings
from aslms.domain.cases import Case
from aslms.domain.events import AuditLog
from aslms.domain.org import Office, User, UserMembership
from aslms.domain.reference import Permission
from aslms.services import access
from aslms.services.access import Forbidden, Member
from aslms.services.cases import resolve_case_ref
from aslms.services.reporting_common import IST_ZONE, with_timeout

DEFAULT_LIMIT = 50
MAX_LIMIT = 200
ACTOR_TEXT_MIN, ACTOR_TEXT_MAX = 2, 100
QUERY_CANCELED = "57014"


class AuditInputError(ValueError):
    """A refused search (HTTP 400): `unknown_user`, `bad_office`, `bad_cursor`, `bad_period`, `bad_actor`."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class SearchTimeout(Exception):
    """The search ran past the statement timeout (HTTP 503 `search_timeout`)."""


class AuditNotFound(LookupError):
    """No audit row with that id (HTTP 404)."""


@dataclass
class AuditQuery:
    user_id: uuid.UUID | None = None
    user_email: str | None = None
    actor_text: str | None = None
    about_user_id: uuid.UUID | None = None
    about_user_email: str | None = None
    case_ref: str | None = None
    office_code: str | None = None
    office_subtree: bool = True
    action: str | None = None
    entity_type: str | None = None
    entity_id: uuid.UUID | None = None
    from_: date | None = None
    to: date | None = None
    cursor: str | None = None
    limit: int = DEFAULT_LIMIT


@dataclass
class AuditPage:
    items: list[dict[str, Any]]
    next_cursor: str | None


# ------------------------------------------------------------------------------------------------ who


def _state_wide(member: Member) -> bool:
    return member.is_super_admin or member.holds(Permission.CASES_VIEW_ALL)


def auditor_member(session: Session, user: User | Member) -> Member:
    """Decision 2: the first membership holding `audit.view` that is also State-wide."""
    for member in access.members(session, user):
        if member.holds(Permission.AUDIT_VIEW) and _state_wide(member):
            return member
    raise Forbidden(
        "the audit log is read only through a State-wide membership holding audit.view", "audit_scope"
    )


# ------------------------------------------------------------------------------------------------ pure helpers


def like_escape(value: str) -> str:
    """`%`, `_` and the escape character itself taken literally in a LIKE pattern (escape `\\`)."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def action_pattern(action: str) -> tuple[str, str]:
    """`("prefix", "custody.%")` for a code ending in `.`, else `("exact", code)`."""
    a = action.strip()
    if a.endswith("."):
        return "prefix", like_escape(a) + "%"
    return "exact", a


def day_bounds(from_: date | None, to: date | None) -> tuple[datetime | None, datetime | None]:
    """IST days to UTC bounds `[from 00:00 IST, to + 1 day 00:00 IST)`; `bad_period` when from is after to."""
    if from_ is not None and to is not None and from_ > to:
        raise AuditInputError("bad_period", "from must not be after to")
    start = datetime.combine(from_, time.min, IST_ZONE).astimezone(UTC) if from_ is not None else None
    end = (
        datetime.combine(to + timedelta(days=1), time.min, IST_ZONE).astimezone(UTC)
        if to is not None
        else None
    )
    return start, end


def encode_cursor(created_at: datetime, row_id: uuid.UUID) -> str:
    raw = f"{created_at.astimezone(UTC).isoformat()}|{row_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        at_s, id_s = base64.urlsafe_b64decode(padded.encode()).decode().split("|", 1)
        at = datetime.fromisoformat(at_s)
        row_id = uuid.UUID(id_s)
    except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
        raise AuditInputError("bad_cursor", "the cursor is not valid") from exc
    if at.tzinfo is None:
        raise AuditInputError("bad_cursor", "the cursor is not valid")
    return at, row_id


def to_ist(value: datetime | None) -> datetime | None:
    return value.astimezone(IST_ZONE) if value is not None else None


# ------------------------------------------------------------------------------------------------ filters


def _login(session: Session, user_id: uuid.UUID | None, email: str | None) -> User | None:
    if user_id is not None:
        found = session.get(User, user_id)
    elif email:
        found = session.scalar(select(User).where(func.lower(User.email) == email.strip().lower()))
    else:
        return None
    if found is None:
        raise AuditInputError("unknown_user", "no such user")
    return found


def _conditions(session: Session, q: AuditQuery) -> list[ColumnElement[bool]]:
    conds: list[ColumnElement[bool]] = []
    actor = _login(session, q.user_id, q.user_email)
    if actor is not None:
        conds.append(AuditLog.actor_user_id == actor.id)
    if q.actor_text is not None:
        t = q.actor_text.strip()
        if not ACTOR_TEXT_MIN <= len(t) <= ACTOR_TEXT_MAX:
            raise AuditInputError("bad_actor", f"actor is {ACTOR_TEXT_MIN} to {ACTOR_TEXT_MAX} characters")
        conds.append(AuditLog.actor_name.ilike(f"%{like_escape(t)}%", escape="\\"))
    about = _login(session, q.about_user_id, q.about_user_email)
    if about is not None:
        membership_ids = select(UserMembership.id).where(UserMembership.user_id == about.id)
        conds.append(
            or_(
                and_(AuditLog.entity_type == "user", AuditLog.entity_id == about.id),
                and_(AuditLog.entity_type == "user_membership", AuditLog.entity_id.in_(membership_ids)),
            )
        )
    if q.case_ref:
        case = resolve_case_ref(session, q.case_ref)  # CaseNotFound → 404
        merged = select(Case.id).where(Case.merged_into_case_id == case.id)
        conds.append(or_(AuditLog.case_id == case.id, AuditLog.case_id.in_(merged)))
    if q.office_code:
        root = session.scalar(select(Office).where(Office.code == q.office_code.strip().upper()))
        if root is None:
            raise AuditInputError("bad_office", f"{q.office_code!r} is not an office")
        if q.office_subtree:
            codes = select(Office.code).where(or_(Office.id == root.id, Office.path.like(root.path + "/%")))
            conds.append(AuditLog.actor_office_code.in_(codes))
        else:
            conds.append(AuditLog.actor_office_code == root.code)
    if q.action:
        kind, pattern = action_pattern(q.action)
        conds.append(
            AuditLog.action.like(pattern, escape="\\") if kind == "prefix" else AuditLog.action == pattern
        )
    if q.entity_type:
        conds.append(AuditLog.entity_type == q.entity_type.strip())
    if q.entity_id is not None:
        conds.append(AuditLog.entity_id == q.entity_id)
    start, end = day_bounds(q.from_, q.to)
    if start is not None:
        conds.append(AuditLog.created_at >= start)
    if end is not None:
        conds.append(AuditLog.created_at < end)
    return conds


def _select():
    return select(AuditLog, Case.id, Case.ref_no, Case.cnr, Case.case_no_text).join(
        Case, Case.id == AuditLog.case_id, isouter=True
    )


def _item(row: AuditLog, case_id, ref_no, cnr, case_no_text) -> dict[str, Any]:
    return {
        "id": row.id,
        "at": to_ist(row.created_at),
        "action": row.action,
        "entity_type": row.entity_type,
        "entity_id": row.entity_id,
        "case": (
            {"id": case_id, "ref_no": ref_no, "cnr": cnr, "case_no_text": case_no_text}
            if case_id is not None
            else None
        ),
        "actor": {
            "user_id": row.actor_user_id,
            "name": row.actor_name,
            "designation": row.actor_designation,
            "office_code": row.actor_office_code,
        },
        "ip": row.ip,
        "user_agent": row.user_agent,
        "before": row.before,
        "after": row.after,
    }


def _timed(session: Session, settings: Settings | None, fn):
    with_timeout(session, (settings or get_settings()).report_statement_timeout_seconds)
    try:
        return fn()
    except OperationalError as exc:
        if getattr(getattr(exc, "orig", None), "sqlstate", None) == QUERY_CANCELED:
            raise SearchTimeout("the search took too long; narrow the search") from exc
        raise


# ------------------------------------------------------------------------------------------------ reading


def search(
    session: Session, user: User | Member, q: AuditQuery, *, settings: Settings | None = None
) -> AuditPage:
    """Decision 1: the filters AND together; newest first; `limit + 1` rows decide `next_cursor`."""
    auditor_member(session, user)
    limit = max(1, min(int(q.limit or DEFAULT_LIMIT), MAX_LIMIT))
    conds = _conditions(session, q)
    if q.cursor:
        at, row_id = decode_cursor(q.cursor)
        conds.append(tuple_(AuditLog.created_at, AuditLog.id) < tuple_(at, row_id))

    def run():
        return session.execute(
            _select().where(*conds).order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit + 1)
        ).all()

    rows = _timed(session, settings, run)
    more = len(rows) > limit
    rows = rows[:limit]
    items = [_item(*r) for r in rows]
    next_cursor = encode_cursor(rows[-1][0].created_at, rows[-1][0].id) if more and rows else None
    return AuditPage(items=items, next_cursor=next_cursor)


def get(session: Session, user: User | Member, row_id: uuid.UUID) -> dict[str, Any]:
    auditor_member(session, user)
    row = session.execute(_select().where(AuditLog.id == row_id)).first()
    if row is None:
        raise AuditNotFound("no such audit row")
    return _item(*row)


SKIP_SCAN = text(
    """
    WITH RECURSIVE codes AS (
        (SELECT action FROM audit_log ORDER BY action LIMIT 1)
        UNION ALL
        SELECT (SELECT a.action FROM audit_log a WHERE a.action > codes.action ORDER BY a.action LIMIT 1)
        FROM codes WHERE codes.action IS NOT NULL
    )
    SELECT action FROM codes WHERE action IS NOT NULL
    """
)


def actions(session: Session, user: User | Member, *, settings: Settings | None = None) -> list[str]:
    """The distinct action codes, by a recursive skip-scan over `ix_audit_log_action` (one probe per code)."""
    auditor_member(session, user)
    return list(_timed(session, settings, lambda: session.execute(SKIP_SCAN).scalars().all()))
