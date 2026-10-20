"""Case visibility — one rule, written once, as named SQL conditions (design `cases-api`, decisions 1–3; the
ownership predicates come from `recommend-and-claim`, decisions 15, 16, 23).

- `department_of(session, office)`: the Department-tier ancestor of an office (the second segment of
  `offices.path`), or None for the State root.
- `claimed_conditions(...)`: the Claimed-tab predicate over `case_ownership` joined to `cases`: the whole
  department for a membership holding `cases.claim` or `cases.allot` (or reading another office with
  `cases.view_all`); otherwise the rows allotted to the person, or to a unit in the membership's subtree when
  the membership sits below the department.
- `owned_case_filter(session, user)`: the same predicate as a filter on `cases.id`.
- `visibility_bases(session, user)`: every basis on which the caller may see a case, each a name and a boolean
  condition over `cases` (correlated `EXISTS` subqueries): `state`, `owner`, `recommended`, `transfer_in`
  (sight only, design `portal-ui-redesign` A5), `pool`, `allotted`, `custody`, `counsel` (`request` removed by `custody-workflow`; the personal custody basis follows the holder
  membership). `visible_case_condition` ORs them (a filter for lists, a selected column for
  search); `access_basis` evaluates them for one case; `can_view_case` / `require_visible` decide the detail.
  Nothing is filtered in the portal; nothing is filtered after the query.
- Documents (design `documents-uploads`, decision 7): `record_visibility_condition` is the per-record rule
  shared with notes (court records and `counsel_shared` to everyone on the case, `case_scope` to everyone but
  standing counsel, `private_to_office` to the office itself, its department-wide callers and the author;
  State-wide readers see all); `document_case_condition` is "a visible case the document belongs to, directly
  or through an order"; `document_visible_condition` requires the function, the case and the record rule of
  one and the same membership (OR over memberships);
  `works_on_case` is the upload rule (a working basis, not merely sight).
- Alerts (design `alerts-notifications`, decision 14, review of 2026-10-06): a `new_document` alert names
  its document (id, type, uploading office), so every read of an alert applies the document rule as well:
  `alert_document_condition` over `alerts`, `can_view_alert_document` for one row.
- Memberships (design `user-memberships`, decision 7): every basis is computed per active membership
  (`member_bases`) and the caller's set is the OR over their memberships; `record_visibility_condition` and the
  alert office rule are OR-ed the same way. `basis_by_member` says which membership produced each basis, and
  `acting_member_for_case` picks the membership that writes on a case (decision 6). Everything stays in SQL.
- Notes (design `custody-workflow`, decision 17): `note_visible_condition` over `case_notes` — a case visible
  through a membership and `record_visibility_condition` of the same membership, with `notes.view_private_office`
  and (for standing counsel) `notes.view_counsel_shared` as switches; drafts are never in this rule."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from sqlalchemy import (
    ColumnElement,
    Select,
    and_,
    case,
    cast,
    exists,
    false,
    literal,
    or_,
    select,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Session

from aslms.domain.alerts import Alert, Notification
from aslms.domain.cases import Case, CaseStatus
from aslms.domain.documents import DocGroup, Document, Order, Visibility
from aslms.domain.org import Office, User
from aslms.domain.ownership import (
    CaseOwnership,
    CounselCode,
    OwnershipRole,
    OwnershipStatus,
    OwnershipTransfer,
    Recommendation,
    RecommendationStatus,
    TransferStatus,
)
from aslms.domain.reference import AlertKind, Permission, Role
from aslms.domain.workflow import CaseNote, Custody
from aslms.services import access
from aslms.services.access import DEPARTMENT_TIER_KINDS as DEPARTMENT_TIER_KINDS
from aslms.services.access import Member
from aslms.services.access import department_of as department_of
from aslms.services.access import is_department as is_department

CaseState = Literal["active", "disposed", "all"]
Basis = tuple[str, ColumnElement[bool]]

# the SQL twin of matching.normalise_counsel_code: upper case, whitespace collapsed, ", " after commas,
# trailing commas and spaces stripped (recommend-and-claim deviation 3)
NORMALISED_CODE_SQL = "rtrim(regexp_replace(regexp_replace(upper(btrim({col})), '\\s+', ' ', 'g'), '\\s*,\\s*', ', ', 'g'), ', ')"


class NotVisibleCase(LookupError):
    """The case exists but the caller may not see it (HTTP 404 "no such case")."""


def departments(session: Session, user: User | Member) -> list[Office]:
    """The departments the caller works in, one per active membership with a department (primary first)."""
    return access.departments(session, user)


def claim_departments(session: Session, user: User | Member) -> list[Office]:
    """The departments where the caller's membership holds `cases.claim`."""
    return [
        m.department
        for m in access.members(session, user)
        if m.department is not None and m.holds(Permission.CASES_CLAIM)
    ]


def in_subtree(office: Office, root: Office) -> bool:
    return office.id == root.id or office.path.startswith(root.path + "/")


def subtree_ids(root: Office) -> Select:
    """`offices.id` of the root and its descendants (path prefix, in SQL)."""
    return select(Office.id).where(or_(Office.id == root.id, Office.path.like(root.path + "/%")))


def case_state_condition(case_state: CaseState):
    if case_state == "active":
        return Case.status.in_([CaseStatus.PENDING, CaseStatus.UNKNOWN])
    if case_state == "disposed":
        return Case.status == CaseStatus.DISPOSED
    return None


def whole_department(session: Session, member: Member | User) -> bool:
    """The membership sees its whole department (holds `cases.claim` or `cases.allot`). For a login: any of its
    memberships does (a gate only)."""
    return access.has(session, member, Permission.CASES_CLAIM) or access.has(
        session, member, Permission.CASES_ALLOT
    )


def claimed_conditions(
    session: Session,
    user: User | Member,
    department: Office,
    *,
    case_state: CaseState = "active",
    whole: bool | None = None,
) -> list:
    """Conditions over `CaseOwnership` (and `Case`, which the caller joins) for the department's active
    ownership rows the caller may see in the Claimed tab, through their membership in that department."""
    conds = [CaseOwnership.office_id == department.id, CaseOwnership.status == OwnershipStatus.ACTIVE]
    member = user if isinstance(user, Member) else access.member_in_department(session, user, department)
    if whole is None:
        whole = member is not None and whole_department(session, member)
    if not whole:
        own = member.office if member is not None else None
        if own is None or not in_subtree(own, department):
            return [false()]
        if own.id == department.id:
            conds.append(CaseOwnership.officer_user_id == member.id)
        else:
            conds.append(
                or_(
                    CaseOwnership.officer_user_id == member.id,
                    CaseOwnership.unit_office_id.in_(subtree_ids(own)),
                )
            )
    state = case_state_condition(case_state)
    if state is not None:
        conds.append(state)
    return conds


def owned_case_filter(session: Session, user: User | Member, *, case_state: CaseState = "active"):
    """A filter on `Case.id`: the cases of the caller's departments that they may see by ownership (OR over
    their memberships)."""
    conds = []
    for member in access.members(session, user):
        if member.department is None:
            continue
        sub = (
            select(CaseOwnership.case_id)
            .join(Case, Case.id == CaseOwnership.case_id)
            .where(*claimed_conditions(session, member, member.department, case_state=case_state))
        )
        conds.append(Case.id.in_(sub))
    if not conds:
        return false()
    return conds[0] if len(conds) == 1 else or_(*conds)


# ------------------------------------------------------------------------------------------------ the bases


def never_owned() -> Any:
    """The pool predicate on `Case`: no primary ownership row ever (recommend-and-claim decision 10)."""
    return ~exists().where(CaseOwnership.case_id == Case.id, CaseOwnership.role == OwnershipRole.PRIMARY)


def codes_condition(codes: list[str]) -> ColumnElement[bool]:
    """One of `codes` (already normalised) appears, after the SQL normalisation, in a cause-list entry's
    `counsel_codes` or in a current advocate row's `counsel_code` of the case."""
    if not codes:
        return false()
    entry_cond = exists(
        select(literal(1))
        .select_from(text("causelist_entries e CROSS JOIN LATERAL unnest(e.counsel_codes) AS c(code)"))
        .where(
            text(
                f"e.case_id = cases.id AND {NORMALISED_CODE_SQL.format(col='c.code')} = ANY(:codes)"
            ).bindparams(codes=codes)
        )
    )
    adv_cond = exists(
        select(literal(1))
        .select_from(text("case_advocates a"))
        .where(
            text(
                "a.case_id = cases.id AND a.is_current AND a.counsel_code IS NOT NULL AND "
                f"{NORMALISED_CODE_SQL.format(col='a.counsel_code')} = ANY(:codes2)"
            ).bindparams(codes2=codes)
        )
    )
    return or_(entry_cond, adv_cond)


def counsel_department_codes(session: Session, department: Office) -> list[str]:
    """The active, non-generic counsel codes mapped to an office of the department's subtree, normalised."""
    from aslms.services.matching import normalise_counsel_code

    rows = session.scalars(
        select(CounselCode.code).where(
            CounselCode.is_active.is_(True),
            CounselCode.is_generic_state.is_(False),
            CounselCode.office_id.in_(subtree_ids(department)),
        )
    ).all()
    return sorted({normalise_counsel_code(c) for c in rows if c})


def _state_wide_member(member: Member) -> bool:
    return member.is_super_admin or member.holds(Permission.CASES_VIEW_ALL)


def member_bases(session: Session, member: Member) -> list[Basis]:
    """Decision 2 of `cases-api`, for one membership: empty without `cases.view_scope` (or outside every
    department); `[("state", true)]` for a State-wide membership."""
    if _state_wide_member(member):
        return [("state", true())]
    if not member.holds(Permission.CASES_VIEW_SCOPE):
        return []
    own = member.office
    dept = member.department
    if own is None or dept is None:
        return []
    whole = whole_department(session, member)
    role = member.role
    bases: list[Basis] = []
    if whole:
        bases.append(
            (
                "owner",
                exists().where(
                    CaseOwnership.case_id == Case.id,
                    CaseOwnership.office_id == dept.id,
                    CaseOwnership.status == OwnershipStatus.ACTIVE,
                ),
            )
        )
        bases.append(
            (
                "recommended",
                exists().where(
                    Recommendation.case_id == Case.id,
                    Recommendation.office_id == dept.id,
                    Recommendation.status == RecommendationStatus.RECOMMENDED,
                ),
            )
        )
        # design portal-ui-redesign, A5 (owner's answer to question 1): sight only while a transfer to the
        # department is requested; never a working basis, lost on decline or withdraw
        bases.append(
            (
                "transfer_in",
                exists().where(
                    OwnershipTransfer.case_id == Case.id,
                    OwnershipTransfer.to_office_id == dept.id,
                    OwnershipTransfer.status == TransferStatus.REQUESTED,
                ),
            )
        )
    if member.holds(Permission.CASES_CLAIM):
        bases.append(("pool", never_owned()))
    if not whole:
        bases.append(
            (
                "allotted",
                exists().where(
                    CaseOwnership.case_id == Case.id,
                    *claimed_conditions(session, member, dept, case_state="all", whole=False),
                ),
            )
        )
    # custody: personal (the holder membership itself) or office-wide over a subtree (decision 2 of cases-api;
    # custody-workflow decision 9: the holder membership, from any department, works on the case while holding)
    personal = role == Role.REFERRAL_REVIEWER or (own.id == dept.id and not whole)
    holds = Custody.holder_membership_id == member.membership_id
    if personal:
        custody_cond = exists().where(Custody.case_id == Case.id, holds)
    else:
        root = dept if whole else own
        custody_cond = exists().where(
            Custody.case_id == Case.id, or_(holds, Custody.holder_office_id.in_(subtree_ids(root)))
        )
    bases.append(("custody", custody_cond))
    if role == Role.STANDING_COUNSEL:
        bases.append(("counsel", codes_condition(counsel_department_codes(session, dept))))
    return bases


def visibility_bases(session: Session, user: User | Member) -> list[Basis]:
    """Decision 7: the OR over the caller's active memberships of each one's bases, one entry per basis name
    (the same name from two memberships is OR-ed). `[("state", true)]` when any membership is State-wide."""
    merged: dict[str, list[ColumnElement[bool]]] = {}
    for member in access.members(session, user):
        for name, cond in member_bases(session, member):
            if name == "state":
                return [("state", true())]
            merged.setdefault(name, []).append(cond)
    return [(name, conds[0] if len(conds) == 1 else or_(*conds)) for name, conds in merged.items()]


def visible_case_condition(session: Session, user: User | Member) -> ColumnElement[bool]:
    """The OR of the caller's bases: a filter for every list, a selected boolean column for search."""
    bases = visibility_bases(session, user)
    if not bases:
        return false()
    if len(bases) == 1:
        return bases[0][1]
    return or_(*[cond for _, cond in bases])


def _evaluate(session: Session, bases: list[Basis], case_id: uuid.UUID) -> list[str]:
    if not bases:
        return []
    row = session.execute(
        select(*[cond.label(name) for name, cond in bases]).select_from(Case).where(Case.id == case_id)
    ).one_or_none()
    if row is None:
        return []
    return [name for (name, _), value in zip(bases, row, strict=True) if value]


def access_basis(session: Session, user: User | Member, case: Case | uuid.UUID) -> list[str]:
    """The names of the bases that make `case` visible to `user` (one SELECT evaluating every basis)."""
    case_id = case if isinstance(case, uuid.UUID) else case.id
    return _evaluate(session, visibility_bases(session, user), case_id)


def basis_by_member(
    session: Session, user: User | Member, case: Case | uuid.UUID
) -> list[tuple[Member, list[str]]]:
    """For each active membership, the names of its bases that make `case` visible (decision 6 uses it to pick
    the membership that acts)."""
    case_id = case if isinstance(case, uuid.UUID) else case.id
    return [(m, _evaluate(session, member_bases(session, m), case_id)) for m in access.members(session, user)]


def can_view_case(session: Session, user: User | Member, case: Case | uuid.UUID) -> bool:
    return bool(access_basis(session, user, case))


def require_visible(session: Session, user: User | Member, case: Case) -> list[str]:
    basis = access_basis(session, user, case)
    if not basis:
        raise NotVisibleCase("no such case")
    return basis


# ------------------------------------------------------------------------------------------------ documents

WORKING_BASES = frozenset({"owner", "allotted", "custody", "counsel"})
STATE_WIDE_PERMISSIONS = (Permission.CASES_VIEW_ALL,)


class NotVisibleDocument(LookupError):
    """The document exists but the caller may not see it (HTTP 404 "no such document")."""


def acting_member_for_case(
    session: Session, user: User | Member, case: Case, permission: Permission
) -> Member | None:
    """Decision 6, a write on a case: the membership with a working basis on the case that holds the function —
    the one holding custody personally first, then the one in the owning department, then any other."""
    custody = session.get(Custody, case.id)
    ranked: list[tuple[int, int, Member]] = []
    for order, (member, names) in enumerate(basis_by_member(session, user, case)):
        if not (WORKING_BASES & set(names)) or not member.holds(permission):
            continue
        holds_file = custody is not None and custody.holder_membership_id == member.membership_id
        rank = 0 if holds_file else (1 if "owner" in names else 2)
        ranked.append((rank, order, member))
    ranked.sort(key=lambda t: (t[0], t[1]))
    return ranked[0][2] if ranked else None


def member_working_condition(session: Session, member: Member) -> ColumnElement[bool] | None:
    """The OR of one membership's working bases (owner, allotted, custody, counsel) over `cases`; None when it has
    none (a State-wide membership has only `state`, which is sight, not work)."""
    conds = [c for name, c in member_bases(session, member) if name in WORKING_BASES]
    if not conds:
        return None
    return conds[0] if len(conds) == 1 else or_(*conds)


def working_condition_for(
    session: Session, user: User | Member, permission: Permission
) -> ColumnElement[bool]:
    """Design `next-date-extraction`, decision 10: the cases on which a membership holding `permission` has a
    working basis (the rule of `acting_member_for_case` as a list filter); `false()` when there is none."""
    conds = [
        c
        for m in access.members(session, user)
        if m.holds(permission) and (c := member_working_condition(session, m)) is not None
    ]
    if not conds:
        return false()
    return conds[0] if len(conds) == 1 else or_(*conds)


def state_wide(session: Session, user: User | Member) -> bool:
    """A State-wide reader: a membership of the super admin or holding `cases.view_all` (oversight, central
    operator, auditor). Sees every case and every document, private ones included."""
    return any(_state_wide_member(m) for m in access.members(session, user))


def works_on_case(session: Session, user: User | Member, case: Case | uuid.UUID) -> bool:
    """Decision 5: the case is visible through a working basis (not only `state`, `recommended` or `pool`)."""
    return bool(WORKING_BASES & set(access_basis(session, user, case)))


def _record_condition_for(
    session: Session, member: Member, *, visibility: Any, office_id: Any, author_user_id: Any, group: Any
) -> ColumnElement[bool]:
    dept = member.department
    whole = dept is not None and whole_department(session, member)
    counsel = member.role == Role.STANDING_COUNSEL
    author = author_user_id == member.id
    private_office = [office_id == member.office.id, author]
    if whole:
        private_office.append(office_id.in_(subtree_ids(dept)))
    conds = [
        (visibility == Visibility.COUNSEL_SHARED, true()),
        (visibility == Visibility.CASE_SCOPE, author if counsel else true()),
        (visibility == Visibility.PRIVATE_TO_OFFICE, or_(*private_office)),
    ]
    if group is not None:
        conds.insert(0, (group == DocGroup.COURT_RECORD, true()))
    return case(*conds, else_=false())


def record_visibility_condition(
    session: Session,
    user: User | Member,
    *,
    visibility: Any,
    office_id: Any,
    author_user_id: Any,
    group: Any = None,
) -> ColumnElement[bool]:
    """Part (c) of the document rule, generic over the record's visibility, office and author columns (notes
    reuse it), OR-ed over the caller's memberships. `group` is the `doc_group` column when the record has one:
    court records are open to all."""
    if state_wide(session, user):
        return true()
    conds = [
        _record_condition_for(
            session, m, visibility=visibility, office_id=office_id, author_user_id=author_user_id, group=group
        )
        for m in access.members(session, user)
    ]
    if not conds:
        return false()
    return conds[0] if len(conds) == 1 else or_(*conds)


def _case_of_document(visible: ColumnElement[bool]) -> ColumnElement[bool]:
    """A case passing `visible` that the document belongs to — `documents.case_id`, or the case of any order
    whose PDF this document is (one order PDF may serve connected cases)."""
    direct = exists(select(literal(1)).select_from(Case).where(Case.id == Document.case_id, visible))
    via_order = exists(
        select(literal(1))
        .select_from(Order)
        .join(Case, Case.id == Order.case_id)
        .where(Order.document_id == Document.id, visible)
    )
    return or_(direct, via_order)


def document_case_condition(session: Session, user: User | Member) -> ColumnElement[bool]:
    """Part (b): a case visible to the caller (any membership) that the document belongs to. A document with no
    case (an `admin` document of a ticket) never passes. On its own it is not the document rule: see
    `document_visible_condition`, which requires (b) and (c) of the same membership."""
    return _case_of_document(visible_case_condition(session, user))


def _member_document_condition(session: Session, member: Member) -> ColumnElement[bool]:
    """(b) and (c) for one membership: a case visible through this membership's own bases, and the record
    setting passed by this same membership (so one membership's counsel rule is never lifted by another
    membership that cannot see the case)."""
    bases = member_bases(session, member)
    if not bases:
        return false()
    visible = bases[0][1] if len(bases) == 1 else or_(*[cond for _, cond in bases])
    record = _record_condition_for(
        session,
        member,
        visibility=Document.visibility,
        office_id=Document.office_id,
        author_user_id=Document.actor_user_id,
        group=Document.doc_group,
    )
    return and_(_case_of_document(visible), record)


def document_visible_condition(
    session: Session, user: User | Member, *, permission: Permission = Permission.DOCUMENTS_VIEW
) -> ColumnElement[bool]:
    """Decision 7, over `documents`: the OR over the caller's memberships of (a) the function held by that
    membership, (b) a case visible through that membership and (c) the record's setting for that membership
    (`user-memberships` decision 7, review fix). A State-wide membership holding the function passes every
    document that has a case."""
    conds: list[ColumnElement[bool]] = []
    for member in access.members(session, user):
        if not member.holds(permission):
            continue
        if _state_wide_member(member):
            return _case_of_document(true())
        conds.append(_member_document_condition(session, member))
    if not conds:
        return false()
    return conds[0] if len(conds) == 1 else or_(*conds)


def can_view_document(
    session: Session,
    user: User | Member,
    doc: Document | uuid.UUID,
    *,
    permission: Permission = Permission.DOCUMENTS_VIEW,
) -> bool:
    doc_id = doc if isinstance(doc, uuid.UUID) else doc.id
    cond = document_visible_condition(session, user, permission=permission)
    return bool(session.scalar(select(cond).select_from(Document).where(Document.id == doc_id)))


def require_visible_document(
    session: Session,
    user: User | Member,
    doc: Document,
    *,
    permission: Permission = Permission.DOCUMENTS_VIEW,
) -> None:
    if not can_view_document(session, user, doc, permission=permission):
        raise NotVisibleDocument("no such document")


# ------------------------------------------------------------------------------------------------ notes


class NotVisibleNote(LookupError):
    """The note exists but the caller may not see it (HTTP 404 "no such note")."""


def _member_note_condition(session: Session, member: Member) -> ColumnElement[bool]:
    """Decision 17 for one membership: a case visible through this membership's bases, the record rule of the
    same membership, and the two note functions as switches (the author always reads their own note)."""
    bases = member_bases(session, member)
    if not bases:
        return false()
    visible = bases[0][1] if len(bases) == 1 else or_(*[cond for _, cond in bases])
    case_ok = exists(select(literal(1)).select_from(Case).where(Case.id == CaseNote.case_id, visible))
    record = _record_condition_for(
        session,
        member,
        visibility=CaseNote.visibility,
        office_id=CaseNote.office_id,
        author_user_id=CaseNote.actor_user_id,
        group=None,
    )
    author = CaseNote.actor_user_id == member.id
    conds: list[ColumnElement[bool]] = [case_ok, record]
    if not member.holds(Permission.NOTES_VIEW_PRIVATE_OFFICE):
        conds.append(or_(CaseNote.visibility != Visibility.PRIVATE_TO_OFFICE, author))
    if member.role == Role.STANDING_COUNSEL and not member.holds(Permission.NOTES_VIEW_COUNSEL_SHARED):
        conds.append(or_(CaseNote.visibility != Visibility.COUNSEL_SHARED, author))
    return and_(*conds)


def note_visible_condition(session: Session, user: User | Member) -> ColumnElement[bool]:
    """Decision 17, over `case_notes`: the OR over the caller's memberships; every note for a State-wide
    reader. Drafts are never in this rule."""
    if state_wide(session, user):
        return true()
    conds = [_member_note_condition(session, m) for m in access.members(session, user)]
    if not conds:
        return false()
    return conds[0] if len(conds) == 1 else or_(*conds)


def can_view_note(session: Session, user: User | Member, note: CaseNote | uuid.UUID) -> bool:
    note_id = note if isinstance(note, uuid.UUID) else note.id
    cond = note_visible_condition(session, user)
    return bool(session.scalar(select(cond).select_from(CaseNote).where(CaseNote.id == note_id)))


# ------------------------------------------------------------------------------------------------ alerts


def alert_document_condition(session: Session, user: User | Member) -> ColumnElement[bool]:
    """Over `alerts`: any kind but `new_document` passes; a `new_document` alert passes only when the document
    it names (`data.document_id`) is visible to the caller under `document_visible_condition`. An alert whose
    document id is missing or unknown is hidden, never shown."""
    doc_id = cast(Alert.data["document_id"].astext, PG_UUID(as_uuid=True))
    visible_doc = exists(
        select(literal(1))
        .select_from(Document)
        .where(Document.id == doc_id, document_visible_condition(session, user))
    )
    return or_(Alert.kind != AlertKind.NEW_DOCUMENT, visible_doc)


def alert_office_condition(session: Session, user: User | Member) -> ColumnElement[bool]:
    """Over `alerts`: an alert is addressed to one office (`alerts.office_id`). A State-wide reader passes
    every alert; anyone else passes an alert addressed to an office of one of their departments (the department
    or any office under it) or one they were themselves notified of. An alert addressed to another
    department (`recommendation` for a different department, `transfer_requested` to the receiving
    department) is hidden although the caller works on the case (review of 2026-10-06, blocking)."""
    if state_wide(session, user):
        return true()
    notified = exists(
        select(literal(1))
        .select_from(Notification)
        .where(Notification.alert_id == Alert.id, Notification.user_id == user.id)
    )
    depts = departments(session, user)
    if not depts:
        return notified
    return or_(*[Alert.office_id.in_(subtree_ids(d)) for d in depts], notified)


def addressed_to_department(session: Session, user: User | Member, alert: Alert) -> bool:
    """`alert_office_condition` without the notification branch, for one alert, in Python: a State-wide
    reader, or the alert's office under one of the caller's departments."""
    if state_wide(session, user):
        return True
    office = session.get(Office, alert.office_id)
    return office is not None and any(in_subtree(office, d) for d in departments(session, user))


def can_view_alert_document(session: Session, user: User | Member, alert: Alert) -> bool:
    """`alert_document_condition` for one alert, in Python."""
    if AlertKind(alert.kind) != AlertKind.NEW_DOCUMENT:
        return True
    raw = (alert.data or {}).get("document_id")
    try:
        doc_id = uuid.UUID(str(raw)) if raw else None
    except ValueError:
        doc_id = None
    return doc_id is not None and can_view_document(session, user, doc_id)
