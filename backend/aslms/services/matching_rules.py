"""Rule administration for the matching engine (design `recommend-and-claim`, decisions 13, 14, 21):
counsel codes (`admin.counsel_codes`), keywords and name patterns (`admin.keywords`), the watchlist
(`admin.watchlist`).

- A non-super-admin acts only on rules whose office is in their subtree. Generic State codes are mapped to the
  root `GOA`, so only the super admin creates them.
- A rule's `weight` is an optional override of its kind's setting (NULL = the setting); setting or clearing it
  also requires `admin.scoring`.
- Uniqueness as in the schema; re-adding a deactivated rule reactivates it. Rules are deactivated, never
  deleted. Every change writes an audit row and one `config_changed` event; an update that changes nothing
  writes nothing. Rule edits reach the scores through the dirty rescore (within 15 minutes); watchlist writes
  rescore their case inline.
- Keywords and exact / prefix name patterns carry `discover` ("Search the court", design `department-discovery`,
  decision 1): on create it defaults to whether the text is discoverable; asking it for a text that is not (or a
  regex) is `not_discoverable` (400). Every save hands the rule to `discovery.on_rule_saved`, which queues a new
  term's first sweep in the same transaction."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from aslms.domain.cases import Case
from aslms.domain.ops import FetchKind
from aslms.domain.org import Office, User
from aslms.domain.ownership import (
    CounselCode,
    OfficeKeyword,
    OfficeNamePattern,
    OfficeWatchlist,
    PatternKind,
    RecommendationOrigin,
)
from aslms.domain.reference import EventType, Permission
from aslms.services import access, matching, queue
from aslms.services import scoring_settings as ss
from aslms.services.audit import Actor, snapshot, write_audit
from aslms.services.cases import emit_event


class RuleError(ValueError):
    """Bad input or a refused placement (HTTP 400)."""


class DuplicateRule(RuleError):
    """The rule already exists and is active (HTTP 409)."""


class NotDiscoverable(RuleError):
    """`discover: true` for a text that cannot be sent to the court's party-name search, or for a regex (HTTP 400
    `not_discoverable`)."""

    code = "not_discoverable"


class _Unset:
    def __repr__(self) -> str:
        return "UNSET"


UNSET: Any = _Unset()
APPLIES_WITHIN_MINUTES = 15


# ------------------------------------------------------------------------------------------------ helpers


def _now() -> datetime:
    return datetime.now(UTC)


def _scope(session: Session, actor_user: User, office: Office, permission: Permission | None = None) -> None:
    """The caller's membership covering `office` must hold the function (design `user-memberships`,
    decision 6)."""
    if not access.in_scope(session, actor_user, office, permission=permission):
        raise access.Forbidden("the office is outside your offices")


def _scope_roots(session: Session, actor_user: User, permission: Permission) -> list[Office]:
    """The offices of the caller's memberships holding the function."""
    return [m.office for m in access.holders_in(session, actor_user, permission)]


def _active_office(office: Office | None) -> Office:
    if office is None:
        raise RuleError("no such office")
    if not office.is_active:
        raise RuleError(f"the office {office.code} is inactive")
    return office


def _weight(session: Session, actor_user: User, weight: Any) -> Any:
    """UNSET → no change; None → clear the override; a number → the override. Needs `admin.scoring`."""
    if weight is UNSET:
        return UNSET
    access.require(session, actor_user, Permission.ADMIN_SCORING)
    if weight is None:
        return None
    try:
        w = float(weight)
    except (TypeError, ValueError) as exc:
        raise RuleError("the weight must be a number") from exc
    if not (0 < w <= 1):
        raise RuleError("the weight must be greater than 0 and at most 1")
    return Decimal(str(round(w, 3)))


def _w(value) -> float | None:
    return None if value is None else round(float(value), 3)


def effective_weight(row, kind: str, settings: ss.Settings) -> float:
    return _w(row.weight) if row.weight is not None else settings.weights[kind]


def _config_event(session: Session, actor: Actor, entity: str, row_id: uuid.UUID, action: str) -> None:
    emit_event(
        session,
        EventType.CONFIG_CHANGED,
        None,
        {"entity": entity, "id": str(row_id), "action": action},
        dedupe=f"config:{entity}:{row_id}:{action}:{_now().isoformat()}",
        scoped=True,
        actor_user_id=actor.user_id,
    )


def _record(
    session: Session, actor: Actor, entity: str, row, action: str, before: Any, after: Any, case_id=None
) -> None:
    session.flush()
    write_audit(
        session, actor, f"{entity}.{action}", entity, row.id, before=before, after=after, case_id=case_id
    )
    _config_event(session, actor, entity, row.id, action)


def _office_code(session: Session, office_id) -> str | None:
    o = session.get(Office, office_id)
    return o.code if o else None


def _set_active(row, enabled: bool) -> None:
    row.is_active = enabled
    row.deactivated_at = None if enabled else _now()


def _discover(value: str, kind: PatternKind | None, discover: Any, current: bool | None = None) -> bool:
    """UNSET → the current value, or on create whether the text is discoverable; True → refused unless it is."""
    from aslms.services.discovery import discoverable

    ok = discoverable(value, kind)
    if discover is UNSET or discover is None:
        return ok if current is None else (current and ok)
    if bool(discover) and not ok:
        if kind is not None and PatternKind(kind) == PatternKind.REGEX:
            raise NotDiscoverable(
                "a regular expression cannot be searched at the court; untick Search the court"
            )
        raise NotDiscoverable(
            "only 3 to 200 letters, digits, spaces and . , ' & ( ) / - can be searched at the court"
        )
    return bool(discover)


def _discovery_saved(session: Session, value: str, row) -> None:
    from aslms.services import discovery

    discovery.on_rule_saved(session, value, is_active_rule=bool(row.is_active), discover=bool(row.discover))


# ------------------------------------------------------------------------------------------------ counsel codes


def counsel_code_summary(session: Session, row: CounselCode) -> dict:
    return {
        "code": row.code,
        "office_code": _office_code(session, row.office_id),
        "weight": _w(row.weight),
        "is_generic_state": row.is_generic_state,
        "notes": row.notes,
        "is_active": row.is_active,
    }


def _check_code_office(office: Office, is_generic_state: bool) -> None:
    is_root = office.parent_id is None
    if is_generic_state and not is_root:
        raise RuleError("a generic State code is mapped to the root office")
    if not is_generic_state and is_root:
        raise RuleError("only generic State codes are mapped to the root office; choose a department")


def create_counsel_code(
    session: Session,
    actor: Actor,
    actor_user: User,
    *,
    code: str,
    office: Office,
    weight: Any = UNSET,
    is_generic_state: bool = False,
    notes: str | None = None,
) -> CounselCode:
    access.require(session, actor_user, Permission.ADMIN_COUNSEL_CODES)
    office = _active_office(office)
    _scope(session, actor_user, office, Permission.ADMIN_COUNSEL_CODES)
    w = _weight(session, actor_user, weight)
    norm = matching.normalise_counsel_code(code)
    if not norm or len(norm) > 60:
        raise RuleError("a counsel code is 1 to 60 characters")
    _check_code_office(office, is_generic_state)
    row = session.scalar(select(CounselCode).where(CounselCode.code == norm))
    if row is not None:
        if row.is_active:
            raise DuplicateRule(
                f"the code {norm} is already mapped to {_office_code(session, row.office_id)}"
            )
        old_office = session.get(Office, row.office_id)
        if old_office is not None and not access.in_scope(
            session, actor_user, old_office, permission=Permission.ADMIN_COUNSEL_CODES
        ):
            raise DuplicateRule(f"the code {norm} belongs to another office")
        before = counsel_code_summary(session, row)
        _set_active(row, True)
        row.office_id, row.is_generic_state = office.id, is_generic_state
        if w is not UNSET:
            row.weight = w
        if notes is not None:
            row.notes = notes.strip() or None
        row.updated_by = actor.user_id
        _record(session, actor, "counsel_code", row, "reactivate", before, counsel_code_summary(session, row))
        return row
    row = CounselCode(
        code=norm,
        office_id=office.id,
        weight=None if w is UNSET else w,
        is_generic_state=is_generic_state,
        notes=(notes or "").strip() or None,
        created_by=actor.user_id,
        updated_by=actor.user_id,
    )
    session.add(row)
    _record(session, actor, "counsel_code", row, "create", None, counsel_code_summary(session, row))
    return row


def update_counsel_code(
    session: Session,
    actor: Actor,
    actor_user: User,
    row: CounselCode,
    *,
    office: Office | None = None,
    weight: Any = UNSET,
    notes: str | None = None,
) -> CounselCode:
    access.require(session, actor_user, Permission.ADMIN_COUNSEL_CODES)
    _scope(session, actor_user, session.get(Office, row.office_id), Permission.ADMIN_COUNSEL_CODES)
    w = _weight(session, actor_user, weight)
    before = counsel_code_summary(session, row)
    if office is not None and office.id != row.office_id:
        office = _active_office(office)
        _scope(session, actor_user, office, Permission.ADMIN_COUNSEL_CODES)
        _check_code_office(office, row.is_generic_state)
        row.office_id = office.id
    if w is not UNSET and _w(w) != _w(row.weight):
        row.weight = w
    if notes is not None and (notes.strip() or None) != row.notes:
        row.notes = notes.strip() or None
    after = counsel_code_summary(session, row)
    if after == before:
        return row
    row.updated_by = actor.user_id
    _record(session, actor, "counsel_code", row, "update", before, after)
    return row


def set_counsel_code_active(
    session: Session, actor: Actor, actor_user: User, row: CounselCode, enabled: bool
) -> CounselCode:
    access.require(session, actor_user, Permission.ADMIN_COUNSEL_CODES)
    office = session.get(Office, row.office_id)
    _scope(session, actor_user, office, Permission.ADMIN_COUNSEL_CODES)
    if row.is_active == enabled:
        raise RuleError(f"the code is already {'active' if enabled else 'inactive'}")
    if enabled:
        _active_office(office)
    before = counsel_code_summary(session, row)
    _set_active(row, enabled)
    row.updated_by = actor.user_id
    action = "reactivate" if enabled else "deactivate"
    _record(session, actor, "counsel_code", row, action, before, counsel_code_summary(session, row))
    return row


def list_counsel_codes(
    session: Session,
    actor_user: User,
    *,
    office: Office | None = None,
    q: str | None = None,
    include_inactive: bool = False,
) -> list[CounselCode]:
    """Rules whose office is in the caller's subtree, plus the generic codes (read-only); all for the super
    admin."""
    access.require(session, actor_user, Permission.ADMIN_COUNSEL_CODES)
    stmt = select(CounselCode).join(Office, Office.id == CounselCode.office_id)
    if not access.is_super_admin(actor_user):
        roots = _scope_roots(session, actor_user, Permission.ADMIN_COUNSEL_CODES)
        stmt = stmt.where(
            or_(
                CounselCode.is_generic_state.is_(True),
                *[or_(Office.id == r.id, Office.path.like(r.path + "/%")) for r in roots],
            )
        )
    if office is not None:
        stmt = stmt.where(or_(Office.id == office.id, Office.path.like(office.path + "/%")))
    if q:
        stmt = stmt.where(CounselCode.code.ilike(f"%{matching.normalise_counsel_code(q)}%"))
    if not include_inactive:
        stmt = stmt.where(CounselCode.is_active.is_(True))
    return list(session.scalars(stmt.order_by(CounselCode.code)).all())


# ------------------------------------------------------------------------------------------------ keywords


def keyword_summary(session: Session, row: OfficeKeyword) -> dict:
    from aslms.services.discovery import discoverable

    return {
        "keyword": row.keyword,
        "office_code": _office_code(session, row.office_id),
        "weight": _w(row.weight),
        "is_active": row.is_active,
        "discover": bool(row.discover),
        "discoverable": discoverable(row.keyword),
    }


def create_keyword(
    session: Session,
    actor: Actor,
    actor_user: User,
    *,
    keyword: str,
    office: Office,
    weight: Any = UNSET,
    discover: Any = UNSET,
) -> OfficeKeyword:
    access.require(session, actor_user, Permission.ADMIN_KEYWORDS)
    office = _active_office(office)
    _scope(session, actor_user, office, Permission.ADMIN_KEYWORDS)
    w = _weight(session, actor_user, weight)
    norm = matching.normalise_term(keyword)
    if not norm or len(norm) > 200:
        raise RuleError("a keyword is 1 to 200 characters")
    row = session.scalar(
        select(OfficeKeyword).where(OfficeKeyword.office_id == office.id, OfficeKeyword.keyword == norm)
    )
    if row is not None:
        if row.is_active:
            raise DuplicateRule(f"the keyword {norm} already exists for {office.code}")
        before = keyword_summary(session, row)
        disc = _discover(norm, None, discover, bool(row.discover))
        _set_active(row, True)
        row.discover = disc
        if w is not UNSET:
            row.weight = w
        row.updated_by = actor.user_id
        _record(session, actor, "keyword", row, "reactivate", before, keyword_summary(session, row))
        _discovery_saved(session, row.keyword, row)
        return row
    row = OfficeKeyword(
        office_id=office.id,
        keyword=norm,
        weight=None if w is UNSET else w,
        discover=_discover(norm, None, discover),
        is_active=True,
        created_by=actor.user_id,
        updated_by=actor.user_id,
    )
    session.add(row)
    _record(session, actor, "keyword", row, "create", None, keyword_summary(session, row))
    _discovery_saved(session, row.keyword, row)
    return row


def update_keyword(
    session: Session,
    actor: Actor,
    actor_user: User,
    row: OfficeKeyword,
    *,
    weight: Any = UNSET,
    discover: Any = UNSET,
) -> OfficeKeyword:
    access.require(session, actor_user, Permission.ADMIN_KEYWORDS)
    _scope(session, actor_user, session.get(Office, row.office_id), Permission.ADMIN_KEYWORDS)
    w = _weight(session, actor_user, weight)
    disc = _discover(row.keyword, None, discover, bool(row.discover))
    before = keyword_summary(session, row)
    if w is not UNSET and _w(w) != _w(row.weight):
        row.weight = w
    row.discover = disc
    after = keyword_summary(session, row)
    if after == before:
        return row
    row.updated_by = actor.user_id
    _record(session, actor, "keyword", row, "update", before, after)
    _discovery_saved(session, row.keyword, row)
    return row


def set_keyword_active(
    session: Session, actor: Actor, actor_user: User, row: OfficeKeyword, enabled: bool
) -> OfficeKeyword:
    access.require(session, actor_user, Permission.ADMIN_KEYWORDS)
    office = session.get(Office, row.office_id)
    _scope(session, actor_user, office, Permission.ADMIN_KEYWORDS)
    if row.is_active == enabled:
        raise RuleError(f"the keyword is already {'active' if enabled else 'inactive'}")
    if enabled:
        _active_office(office)
    before = keyword_summary(session, row)
    _set_active(row, enabled)
    row.updated_by = actor.user_id
    action = "reactivate" if enabled else "deactivate"
    _record(session, actor, "keyword", row, action, before, keyword_summary(session, row))
    _discovery_saved(session, row.keyword, row)
    return row


# ------------------------------------------------------------------------------------------------ name patterns


def pattern_summary(session: Session, row: OfficeNamePattern) -> dict:
    from aslms.services.discovery import discoverable

    return {
        "pattern": row.pattern,
        "kind": PatternKind(row.kind).value,
        "office_code": _office_code(session, row.office_id),
        "weight": _w(row.weight),
        "is_active": row.is_active,
        "discover": bool(row.discover),
        "discoverable": discoverable(row.pattern, row.kind),
    }


def _pattern_text(pattern: str, kind: PatternKind) -> str:
    if kind == PatternKind.REGEX:
        try:
            matching.validate_regex(pattern)
        except ValueError as exc:
            raise RuleError(str(exc)) from exc
        return pattern
    norm = matching.normalise_term(pattern)
    if not norm or len(norm) > 300:
        raise RuleError("a pattern is 1 to 300 characters")
    return norm


def create_name_pattern(
    session: Session,
    actor: Actor,
    actor_user: User,
    *,
    pattern: str,
    kind: PatternKind | str,
    office: Office,
    weight: Any = UNSET,
    discover: Any = UNSET,
) -> OfficeNamePattern:
    access.require(session, actor_user, Permission.ADMIN_KEYWORDS)
    office = _active_office(office)
    _scope(session, actor_user, office, Permission.ADMIN_KEYWORDS)
    try:
        kind = PatternKind(kind)
    except ValueError as exc:
        raise RuleError(f"unknown pattern kind {kind!r}") from exc
    w = _weight(session, actor_user, weight)
    text = _pattern_text(pattern, kind)
    row = session.scalar(
        select(OfficeNamePattern).where(
            OfficeNamePattern.office_id == office.id,
            OfficeNamePattern.pattern == text,
            OfficeNamePattern.kind == kind,
        )
    )
    if row is not None:
        if row.is_active:
            raise DuplicateRule(f"the pattern already exists for {office.code}")
        before = pattern_summary(session, row)
        disc = _discover(text, kind, discover, bool(row.discover))
        _set_active(row, True)
        row.discover = disc
        if w is not UNSET:
            row.weight = w
        row.updated_by = actor.user_id
        _record(session, actor, "name_pattern", row, "reactivate", before, pattern_summary(session, row))
        _discovery_saved(session, row.pattern, row)
        return row
    row = OfficeNamePattern(
        office_id=office.id,
        pattern=text,
        kind=kind,
        weight=None if w is UNSET else w,
        discover=_discover(text, kind, discover),
        is_active=True,
        created_by=actor.user_id,
        updated_by=actor.user_id,
    )
    session.add(row)
    _record(session, actor, "name_pattern", row, "create", None, pattern_summary(session, row))
    _discovery_saved(session, row.pattern, row)
    return row


def update_name_pattern(
    session: Session,
    actor: Actor,
    actor_user: User,
    row: OfficeNamePattern,
    *,
    weight: Any = UNSET,
    discover: Any = UNSET,
) -> OfficeNamePattern:
    access.require(session, actor_user, Permission.ADMIN_KEYWORDS)
    _scope(session, actor_user, session.get(Office, row.office_id), Permission.ADMIN_KEYWORDS)
    w = _weight(session, actor_user, weight)
    disc = _discover(row.pattern, PatternKind(row.kind), discover, bool(row.discover))
    before = pattern_summary(session, row)
    if w is not UNSET and _w(w) != _w(row.weight):
        row.weight = w
    row.discover = disc
    after = pattern_summary(session, row)
    if after == before:
        return row
    row.updated_by = actor.user_id
    _record(session, actor, "name_pattern", row, "update", before, after)
    _discovery_saved(session, row.pattern, row)
    return row


def set_name_pattern_active(
    session: Session, actor: Actor, actor_user: User, row: OfficeNamePattern, enabled: bool
) -> OfficeNamePattern:
    access.require(session, actor_user, Permission.ADMIN_KEYWORDS)
    office = session.get(Office, row.office_id)
    _scope(session, actor_user, office, Permission.ADMIN_KEYWORDS)
    if row.is_active == enabled:
        raise RuleError(f"the pattern is already {'active' if enabled else 'inactive'}")
    if enabled:
        _active_office(office)
    before = pattern_summary(session, row)
    _set_active(row, enabled)
    row.updated_by = actor.user_id
    action = "reactivate" if enabled else "deactivate"
    _record(session, actor, "name_pattern", row, action, before, pattern_summary(session, row))
    _discovery_saved(session, row.pattern, row)
    return row


def list_rules(
    session: Session,
    actor_user: User,
    model,
    permission: Permission,
    *,
    office=None,
    include_inactive=False,
    discover: bool | None = None,
) -> list:
    """Keywords, name patterns or watchlist rows whose office is in the caller's subtree (all for the super
    admin); `discover` keeps the rules ticked (or not) "Search the court" (keywords and name patterns)."""
    access.require(session, actor_user, permission)
    stmt = select(model).join(Office, Office.id == model.office_id)
    if not access.is_super_admin(actor_user):
        roots = _scope_roots(session, actor_user, permission)
        if not roots:
            return []
        stmt = stmt.where(or_(*[or_(Office.id == r.id, Office.path.like(r.path + "/%")) for r in roots]))
    if office is not None:
        stmt = stmt.where(or_(Office.id == office.id, Office.path.like(office.path + "/%")))
    if not include_inactive:
        stmt = stmt.where(model.is_active.is_(True))
    if discover is not None and hasattr(model, "discover"):
        stmt = stmt.where(model.discover.is_(bool(discover)))
    return list(session.scalars(stmt.order_by(Office.path, model.created_at)).all())


# ------------------------------------------------------------------------------------------------ watchlist


def watch_summary(session: Session, row: OfficeWatchlist) -> dict:
    return {
        "cnr": row.cnr,
        "office_code": _office_code(session, row.office_id),
        "case_id": str(row.case_id) if row.case_id else None,
        "reason": row.reason,
        "weight": _w(row.weight),
        "is_active": row.is_active,
    }


def _rescore_watch(session: Session, row: OfficeWatchlist) -> None:
    if row.case_id is not None:
        matching.score_cases(session, [row.case_id], origin=RecommendationOrigin.WATCHLIST)


def add_watch(
    session: Session,
    actor: Actor,
    actor_user: User,
    *,
    cnr: str,
    office: Office | None = None,
    reason: str | None = None,
    weight: Any = UNSET,
) -> tuple[OfficeWatchlist, bool]:
    """Returns (row, dossier_queued). An unknown CNR queues a `dossier` row (the NAPIX call happens in the
    runner, through the integration layer); a held case is scored at once."""
    access.require(session, actor_user, Permission.ADMIN_WATCHLIST)
    cnr = (cnr or "").strip().upper()
    if not matching.CNR_RE.match(cnr):
        raise RuleError("a CNR is four letters and twelve digits")
    if office is None:
        depts = [
            m.department
            for m in access.holders_in(session, actor_user, Permission.ADMIN_WATCHLIST)
            if m.department is not None
        ]
        if not depts:
            raise RuleError("office_code is required: you do not belong to a department")
        if len({d.id for d in depts}) > 1:
            raise RuleError("office_code is required: you work in " + ", ".join(d.code for d in depts))
        office = depts[0]
    office = _active_office(office)
    _scope(session, actor_user, office, Permission.ADMIN_WATCHLIST)
    if office.parent_id is None:
        raise RuleError("a watchlist entry belongs to a department or one of its offices")
    w = _weight(session, actor_user, weight)
    case = session.scalar(select(Case).where(Case.cnr == cnr))
    row = session.scalar(
        select(OfficeWatchlist).where(OfficeWatchlist.office_id == office.id, OfficeWatchlist.cnr == cnr)
    )
    action = "create"
    before = None
    if row is not None:
        if row.is_active:
            raise DuplicateRule(f"{cnr} is already on the watchlist of {office.code}")
        before = watch_summary(session, row)
        _set_active(row, True)
        action = "reactivate"
        if w is not UNSET:
            row.weight = w
        if reason is not None:
            row.reason = reason.strip() or None
    else:
        row = OfficeWatchlist(
            office_id=office.id,
            cnr=cnr,
            reason=(reason or "").strip() or None,
            weight=None if w is UNSET else w,
        )
        session.add(row)
    row.case_id = case.id if case else row.case_id
    for k, v in snapshot(actor).items():
        setattr(row, k, v)
    _record(
        session, actor, "watchlist", row, action, before, watch_summary(session, row), case_id=row.case_id
    )
    queued = False
    if case is None:
        queued = queue.enqueue(session, FetchKind.DOSSIER, cnr, queue.PRIORITY["dossier_new"])
    else:
        _rescore_watch(session, row)
    return row, queued


def update_watch(
    session: Session,
    actor: Actor,
    actor_user: User,
    row: OfficeWatchlist,
    *,
    reason: str | None = None,
    weight: Any = UNSET,
) -> OfficeWatchlist:
    access.require(session, actor_user, Permission.ADMIN_WATCHLIST)
    _scope(session, actor_user, session.get(Office, row.office_id), Permission.ADMIN_WATCHLIST)
    w = _weight(session, actor_user, weight)
    before = watch_summary(session, row)
    if w is not UNSET and _w(w) != _w(row.weight):
        row.weight = w
    if reason is not None and (reason.strip() or None) != row.reason:
        row.reason = reason.strip() or None
    after = watch_summary(session, row)
    if after == before:
        return row
    for k, v in snapshot(actor).items():
        setattr(row, k, v)
    _record(session, actor, "watchlist", row, "update", before, after, case_id=row.case_id)
    _rescore_watch(session, row)
    return row


def set_watch_active(
    session: Session, actor: Actor, actor_user: User, row: OfficeWatchlist, enabled: bool
) -> OfficeWatchlist:
    access.require(session, actor_user, Permission.ADMIN_WATCHLIST)
    office = session.get(Office, row.office_id)
    _scope(session, actor_user, office, Permission.ADMIN_WATCHLIST)
    if row.is_active == enabled:
        raise RuleError(f"the watchlist entry is already {'active' if enabled else 'inactive'}")
    if enabled:
        _active_office(office)
    before = watch_summary(session, row)
    _set_active(row, enabled)
    for k, v in snapshot(actor).items():
        setattr(row, k, v)
    action = "reactivate" if enabled else "deactivate"
    _record(
        session, actor, "watchlist", row, action, before, watch_summary(session, row), case_id=row.case_id
    )
    _rescore_watch(session, row)
    return row
