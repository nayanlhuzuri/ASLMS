"""Case visibility — one rule, written once, as named SQL conditions (design `cases-api`, decisions 1–3; the
ownership predicates come from `recommend-and-claim`, decisions 15, 16, 23).

- `department_of(session, office)`: the Department-tier ancestor of an office (the second segment of
  `offices.path`), or None for the State root.
- `claimed_conditions(...)`: the Claimed-tab predicate over `case_ownership` joined to `cases`: the whole
  department for callers holding `cases.claim` or `cases.allot` (or reading another office with
  `cases.view_all`); otherwise the rows allotted to the caller, or to a unit in the caller's subtree when the
  caller sits below the department.
- `owned_case_filter(session, user)`: the same predicate as a filter on `cases.id`.
- `visibility_bases(session, user)`: every basis on which the caller may see a case, each a name and a boolean
  condition over `cases` (correlated `EXISTS` subqueries): `state`, `owner`, `recommended`, `pool`, `allotted`,
  `custody`, `request`, `counsel`. `visible_case_condition` ORs them (a filter for lists, a selected column for
  search); `access_basis` evaluates them for one case; `can_view_case` / `require_visible` decide the detail.
  Nothing is filtered in the portal; nothing is filtered after the query.
- Documents (design `documents-uploads`, decision 7): `record_visibility_condition` is the per-record rule
  shared with notes (court records and `counsel_shared` to everyone on the case, `case_scope` to everyone but
  standing counsel, `private_to_office` to the office itself, its department-wide callers and the author;
  State-wide readers see all); `document_case_condition` is "a visible case the document belongs to, directly
  or through an order"; `document_visible_condition` ANDs the function, the case and the record rule;
  `works_on_case` is the upload rule (a working basis, not merely sight)."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from sqlalchemy import ColumnElement, Select, and_, case, exists, false, literal, or_, select, text, true
from sqlalchemy.orm import Session

from aslms.domain.cases import Case, CaseStatus
from aslms.domain.documents import DocGroup, Document, Order, Visibility
from aslms.domain.org import Office, User
from aslms.domain.ownership import (
    CaseOwnership,
    CounselCode,
    OwnershipRole,
    OwnershipStatus,
    Recommendation,
    RecommendationStatus,
)
from aslms.domain.reference import OfficeKind, Permission, Role
from aslms.domain.workflow import Custody, Request, RequestStatus
from aslms.services import access

DEPARTMENT_TIER_KINDS = frozenset({OfficeKind.DEPARTMENT, OfficeKind.CENTRAL, OfficeKind.ADVOCATE_GENERAL})
CaseState = Literal["active", "disposed", "all"]
Basis = tuple[str, ColumnElement[bool]]

# the SQL twin of matching.normalise_counsel_code: upper case, whitespace collapsed, ", " after commas,
# trailing commas and spaces stripped (recommend-and-claim deviation 3)
NORMALISED_CODE_SQL = "rtrim(regexp_replace(regexp_replace(upper(btrim({col})), '\\s+', ' ', 'g'), '\\s*,\\s*', ', ', 'g'), ', ')"


class NotVisibleCase(LookupError):
    """The case exists but the caller may not see it (HTTP 404 "no such case")."""


def is_department(office: Office | None) -> bool:
    return (
        office is not None
        and office.path.count("/") == 1
        and OfficeKind(office.kind) in DEPARTMENT_TIER_KINDS
    )


def department_of(session: Session, office: Office | None) -> Office | None:
    if office is None:
        return None
    parts = office.path.split("/")
    if len(parts) < 2:
        return None
    dept = office if len(parts) == 2 else session.scalar(select(Office).where(Office.code == parts[1]))
    return dept if is_department(dept) else None


def user_department(session: Session, user: User) -> Office | None:
    return department_of(session, session.get(Office, user.office_id))


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


def whole_department(session: Session, user: User) -> bool:
    return access.has(session, user, Permission.CASES_CLAIM) or access.has(
        session, user, Permission.CASES_ALLOT
    )


def claimed_conditions(
    session: Session,
    user: User,
    department: Office,
    *,
    case_state: CaseState = "active",
    whole: bool | None = None,
) -> list:
    """Conditions over `CaseOwnership` (and `Case`, which the caller joins) for the department's active
    ownership rows the user may see in the Claimed tab."""
    conds = [CaseOwnership.office_id == department.id, CaseOwnership.status == OwnershipStatus.ACTIVE]
    if whole is None:
        whole = whole_department(session, user)
    if not whole:
        own = session.get(Office, user.office_id)
        if own is None or not in_subtree(own, department):
            return [false()]
        if own.id == department.id:
            conds.append(CaseOwnership.officer_user_id == user.id)
        else:
            conds.append(
                or_(
                    CaseOwnership.officer_user_id == user.id,
                    CaseOwnership.unit_office_id.in_(subtree_ids(own)),
                )
            )
    state = case_state_condition(case_state)
    if state is not None:
        conds.append(state)
    return conds


def owned_case_filter(session: Session, user: User, *, case_state: CaseState = "active"):
    """A filter on `Case.id`: the cases of the user's own department that the user may see by ownership."""
    dept = user_department(session, user)
    if dept is None:
        return false()
    sub = (
        select(CaseOwnership.case_id)
        .join(Case, Case.id == CaseOwnership.case_id)
        .where(*claimed_conditions(session, user, dept, case_state=case_state))
    )
    return Case.id.in_(sub)


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


def visibility_bases(session: Session, user: User) -> list[Basis]:
    """Decision 2. Empty when the caller holds neither `cases.view_scope` nor `cases.view_all` (or belongs to
    no department); `[("state", true)]` for State-wide readers."""
    if access.is_super_admin(user) or access.has(session, user, Permission.CASES_VIEW_ALL):
        return [("state", true())]
    if not access.has(session, user, Permission.CASES_VIEW_SCOPE):
        return []
    own = session.get(Office, user.office_id)
    dept = department_of(session, own)
    if own is None or dept is None:
        return []
    whole = whole_department(session, user)
    role = Role(user.role)
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
    if access.has(session, user, Permission.CASES_CLAIM):
        bases.append(("pool", never_owned()))
    if not whole:
        bases.append(
            (
                "allotted",
                exists().where(
                    CaseOwnership.case_id == Case.id,
                    *claimed_conditions(session, user, dept, case_state="all", whole=False),
                ),
            )
        )
    # custody and requests: office-wide over a subtree, or personal (decision 2, table rows custody / request)
    personal = role == Role.REFERRAL_REVIEWER or (own.id == dept.id and not whole)
    if personal:
        custody_cond = exists().where(Custody.case_id == Case.id, Custody.holder_user_id == user.id)
        request_cond = exists().where(
            Request.case_id == Case.id,
            Request.status != RequestStatus.WITHDRAWN,
            Request.to_user_id == user.id,
        )
    else:
        root = dept if whole else own
        custody_cond = exists().where(
            Custody.case_id == Case.id, Custody.holder_office_id.in_(subtree_ids(root))
        )
        request_cond = exists().where(
            Request.case_id == Case.id,
            Request.status != RequestStatus.WITHDRAWN,
            Request.to_office_id.in_(subtree_ids(root)),
        )
    bases.append(("custody", custody_cond))
    bases.append(("request", request_cond))
    if role == Role.STANDING_COUNSEL:
        bases.append(("counsel", codes_condition(counsel_department_codes(session, dept))))
    return bases


def visible_case_condition(session: Session, user: User) -> ColumnElement[bool]:
    """The OR of the caller's bases: a filter for every list, a selected boolean column for search."""
    bases = visibility_bases(session, user)
    if not bases:
        return false()
    if len(bases) == 1:
        return bases[0][1]
    return or_(*[cond for _, cond in bases])


def access_basis(session: Session, user: User, case: Case | uuid.UUID) -> list[str]:
    """The names of the bases that make `case` visible to `user` (one SELECT evaluating every basis)."""
    bases = visibility_bases(session, user)
    if not bases:
        return []
    case_id = case if isinstance(case, uuid.UUID) else case.id
    row = session.execute(
        select(*[cond.label(name) for name, cond in bases]).select_from(Case).where(Case.id == case_id)
    ).one_or_none()
    if row is None:
        return []
    return [name for (name, _), value in zip(bases, row, strict=True) if value]


def can_view_case(session: Session, user: User, case: Case | uuid.UUID) -> bool:
    return bool(access_basis(session, user, case))


def require_visible(session: Session, user: User, case: Case) -> list[str]:
    basis = access_basis(session, user, case)
    if not basis:
        raise NotVisibleCase("no such case")
    return basis


# ------------------------------------------------------------------------------------------------ documents

WORKING_BASES = frozenset({"owner", "allotted", "custody", "request", "counsel"})
STATE_WIDE_PERMISSIONS = (Permission.CASES_VIEW_ALL,)


class NotVisibleDocument(LookupError):
    """The document exists but the caller may not see it (HTTP 404 "no such document")."""


def state_wide(session: Session, user: User) -> bool:
    """A State-wide reader: the super admin or a holder of `cases.view_all` (oversight, central operator,
    auditor). Sees every case and every document, private ones included."""
    return access.is_super_admin(user) or access.has(session, user, Permission.CASES_VIEW_ALL)


def works_on_case(session: Session, user: User, case: Case | uuid.UUID) -> bool:
    """Decision 5: the case is visible through a working basis (not only `state`, `recommended` or `pool`)."""
    return bool(WORKING_BASES & set(access_basis(session, user, case)))


def record_visibility_condition(
    session: Session,
    user: User,
    *,
    visibility: Any,
    office_id: Any,
    author_user_id: Any,
    group: Any = None,
) -> ColumnElement[bool]:
    """Part (c) of the document rule, generic over the record's visibility, office and author columns (notes
    reuse it). `group` is the `doc_group` column when the record has one: court records are open to all."""
    if state_wide(session, user):
        return true()
    own = session.get(Office, user.office_id)
    dept = department_of(session, own)
    whole = dept is not None and whole_department(session, user)
    counsel = Role(user.role) == Role.STANDING_COUNSEL
    author = author_user_id == user.id
    private_office = [office_id == user.office_id, author]
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


def document_case_condition(session: Session, user: User) -> ColumnElement[bool]:
    """Part (b): a visible case the document belongs to — `documents.case_id`, or the case of any order whose
    PDF this document is (one order PDF may serve connected cases)."""
    visible = visible_case_condition(session, user)
    direct = exists(select(literal(1)).select_from(Case).where(Case.id == Document.case_id, visible))
    via_order = exists(
        select(literal(1))
        .select_from(Order)
        .join(Case, Case.id == Order.case_id)
        .where(Order.document_id == Document.id, visible)
    )
    return or_(direct, via_order)


def document_visible_condition(
    session: Session, user: User, *, permission: Permission = Permission.DOCUMENTS_VIEW
) -> ColumnElement[bool]:
    """Decision 7, over `documents`: (a) the function, (b) a visible case, (c) the record's own setting."""
    if not access.has(session, user, permission):
        return false()
    return and_(
        document_case_condition(session, user),
        record_visibility_condition(
            session,
            user,
            visibility=Document.visibility,
            office_id=Document.office_id,
            author_user_id=Document.actor_user_id,
            group=Document.doc_group,
        ),
    )


def can_view_document(
    session: Session,
    user: User,
    doc: Document | uuid.UUID,
    *,
    permission: Permission = Permission.DOCUMENTS_VIEW,
) -> bool:
    doc_id = doc if isinstance(doc, uuid.UUID) else doc.id
    cond = document_visible_condition(session, user, permission=permission)
    return bool(session.scalar(select(cond).select_from(Document).where(Document.id == doc_id)))


def require_visible_document(
    session: Session, user: User, doc: Document, *, permission: Permission = Permission.DOCUMENTS_VIEW
) -> None:
    if not can_view_document(session, user, doc, permission=permission):
        raise NotVisibleDocument("no such document")
