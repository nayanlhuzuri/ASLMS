"""Who receives an alert (design `alerts-notifications`, decisions 11–14), resolved when the alert is raised
or upgraded and always filtered by visibility.

For a case alert: the custody holder (the holder user; when the custody is with an office and no user, that
office's active users holding `alerts.acknowledge` — except a Department-tier office, where only its users
holding `cases.allot` receive), the primary owner (the allotted officer; else the allotted unit's users
holding `alerts.acknowledge`; else the department's users holding `cases.allot`) and each watcher (its
officer, else that department's users holding `cases.allot`). The set is de-duplicated; inactive users, the
user whose action caused the event, and anyone who cannot see the case (or, for `new_document`, the
document) are removed. Standing counsel are not recipients. Function checks are per membership (design
`user-memberships`, decision 11): an office's users are the logins with an active membership **at that office**
whose membership holds the function; cached for the run."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from aslms.domain.cases import Case
from aslms.domain.org import Office, User, UserMembership
from aslms.domain.ownership import (
    CaseOwnership,
    OwnershipRole,
    OwnershipStatus,
    OwnershipTransfer,
    Recommendation,
)
from aslms.domain.reference import Permission, Role
from aslms.domain.workflow import Custody
from aslms.services import access, visibility
from aslms.services.offices import find_office

# ownership events whose recipient decision 13 names although the case is not (or no longer) visible to
# them: the officer a case was taken from, the department asked to take it, the department told of the
# decision (deviation 1 of the design note)
NAMED_RECIPIENT_EVENTS = frozenset(
    {
        "case_taken_over",
        "transfer_requested",
        "transfer_decided",
        "recommendation_closed",  # the closed department lost sight (design ownership-refinements, decision 10)
    }
)
# workflow alerts whose recipient the design names although the case is no longer visible to them: the officer a
# file was taken from (design custody-workflow, decision 23b)
NAMED_WORKFLOW_EVENTS = frozenset({"file_recalled"})


def owning_office(session: Session, case: Case | uuid.UUID) -> Office | None:
    """The active primary owner's department (the office a case alert is addressed to)."""
    case_id = case if isinstance(case, uuid.UUID) else case.id
    office_id = session.scalar(
        select(CaseOwnership.office_id).where(
            CaseOwnership.case_id == case_id,
            CaseOwnership.status == OwnershipStatus.ACTIVE,
            CaseOwnership.role == OwnershipRole.PRIMARY,
        )
    )
    return session.get(Office, office_id) if office_id else None


class Resolver:
    """Recipient resolution with per-run caches of users per office and functions per user."""

    def __init__(self, session: Session):
        self.session = session
        self._perms: dict[uuid.UUID, set[Permission]] = {}
        self._office_members: dict[uuid.UUID, list[access.Member]] = {}
        self._users: dict[uuid.UUID, User | None] = {}

    # ------------------------------------------------------------------------------------------ primitives
    def perms(self, user: User) -> set[Permission]:
        if user.id not in self._perms:
            self._perms[user.id] = access.effective_permissions(self.session, user)
        return self._perms[user.id]

    def holds(self, user: User, permission: Permission) -> bool:
        return permission in self.perms(user)

    def user(self, user_id: Any) -> User | None:
        if user_id is None:
            return None
        uid = user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))
        if uid not in self._users:
            self._users[uid] = self.session.get(User, uid)
        return self._users[uid]

    def office_users(self, office: Office | uuid.UUID | None, permission: Permission) -> list[User]:
        """The active logins with an active membership at `office` (that office alone, not its subtree) whose
        membership holds the function; each person once."""
        if office is None:
            return []
        office_id = office if isinstance(office, uuid.UUID) else office.id
        if office_id not in self._office_members:
            rows = self.session.execute(
                select(UserMembership, User)
                .join(User, User.id == UserMembership.user_id)
                .where(
                    UserMembership.office_id == office_id,
                    UserMembership.is_active.is_(True),
                    User.is_active.is_(True),
                )
                .order_by(User.email)
            ).all()
            self._office_members[office_id] = [access.member_of(self.session, m, u) for m, u in rows]
        out: list[User] = []
        for m in self._office_members[office_id]:
            if m.holds(permission) and all(u.id != m.user.id for u in out):
                out.append(m.user)
        return out

    def department_holders(self, office: Office | None, permission: Permission) -> list[User]:
        """The users of the office's Department-tier ancestor holding the function (the nodal officers:
        department admin and head for `cases.allot`)."""
        dept = visibility.department_of(self.session, office)
        return self.office_users(dept, permission) if dept is not None else []

    # ------------------------------------------------------------------------------------------ rules
    def custody_holders(self, case: Case) -> list[User]:
        """Decision 14's custody-holder rule: the holder user; when the custody is with an office and no user,
        that office's users holding `alerts.acknowledge` (a Department-tier office: those holding
        `cases.allot`)."""
        custody = self.session.get(Custody, case.id)
        if custody is None:
            return []
        holder = self.user(custody.holder_user_id)
        if holder is not None:
            return [holder]
        office = self.session.get(Office, custody.holder_office_id)
        if visibility.is_department(office):
            return self.office_users(office, Permission.CASES_ALLOT)
        return self.office_users(office, Permission.ALERTS_ACKNOWLEDGE)

    def department_trackers(self, department: Office | None) -> list[User]:
        """The active logins whose membership in the department holds `custody.track` (design custody-workflow,
        decision 24a), each once."""
        if department is None:
            return []
        rows = self.session.execute(
            select(UserMembership, User)
            .join(User, User.id == UserMembership.user_id)
            .where(
                UserMembership.department_id == department.id,
                UserMembership.is_active.is_(True),
                User.is_active.is_(True),
            )
            .order_by(User.email)
        ).all()
        out: list[User] = []
        for m, u in rows:
            if access.member_of(self.session, m, u).holds(Permission.CUSTODY_TRACK) and all(
                x.id != u.id for x in out
            ):
                out.append(u)
        return out

    def case_recipients(self, case: Case) -> list[User]:
        """Decision 14, before the final filter: custody holder, primary owner, watchers."""
        out: list[User] = list(self.custody_holders(case))
        rows = self.session.scalars(
            select(CaseOwnership).where(
                CaseOwnership.case_id == case.id, CaseOwnership.status == OwnershipStatus.ACTIVE
            )
        ).all()
        for row in rows:
            officer = self.user(row.officer_user_id)
            if officer is not None:
                out.append(officer)
                continue
            if OwnershipRole(row.role) == OwnershipRole.PRIMARY and row.unit_office_id is not None:
                unit_users = self.office_users(row.unit_office_id, Permission.ALERTS_ACKNOWLEDGE)
                if unit_users:
                    out += unit_users
                    continue
            out += self.office_users(row.office_id, Permission.CASES_ALLOT)
        return out

    def for_recommendation(self, rec: Recommendation) -> list[User]:
        return self.office_users(rec.office_id, Permission.CASES_CLAIM)

    def for_ownership_event(self, event_type: str, payload: dict[str, Any]) -> list[User]:
        """Decision 13: `allotted` → the officer, else the unit's users; `case_taken_over` → the previous
        officer; `transfer_requested` → the receiving department's deciders; `transfer_decided` → the
        requesting department's requesters; `recommendation_closed` → the closed department's claimers."""
        if event_type == "allotted":
            officer = self.user(payload.get("officer_user_id"))
            if officer is not None:
                return [officer]
            unit = (
                find_office(self.session, payload.get("unit_code") or "")
                if payload.get("unit_code")
                else None
            )
            return self.office_users(unit, Permission.ALERTS_ACKNOWLEDGE) if unit is not None else []
        if event_type == "case_taken_over":
            previous = self.user(payload.get("from_user_id"))
            return [previous] if previous is not None else []
        if event_type == "transfer_requested":
            target = find_office(self.session, payload.get("to_office_code") or "")
            return self.office_users(target, Permission.CASES_TRANSFER_DECIDE) if target is not None else []
        if event_type == "transfer_decided":
            transfer_id = payload.get("transfer_id")
            t = self.session.get(OwnershipTransfer, uuid.UUID(str(transfer_id))) if transfer_id else None
            if t is None:
                return []
            return self.office_users(t.from_office_id, Permission.CASES_TRANSFER_REQUEST)
        if event_type == "recommendation_closed":  # design ownership-refinements, decision 10
            closed = find_office(self.session, payload.get("office_code") or "")
            return self.office_users(closed, Permission.CASES_CLAIM) if closed is not None else []
        return []

    def finalise(
        self,
        users: list[User],
        case: Case,
        *,
        exclude_user_id: Any = None,
        document_id: uuid.UUID | None = None,
        require_case_access: bool = True,
    ) -> list[User]:
        """The final filter: de-duplicate; drop inactive users, the actor, standing counsel, anyone who
        cannot see the case (unless the design names them as the recipient) and (for `new_document`) anyone who
        cannot see the document."""
        excluded = uuid.UUID(str(exclude_user_id)) if exclude_user_id else None
        seen: set[uuid.UUID] = set()
        out: list[User] = []
        for u in users:
            if u is None or u.id in seen or not u.is_active or u.id == excluded:
                continue
            seen.add(u.id)
            roles = {m.role for m in access.members(self.session, u)}
            if roles and roles <= {Role.STANDING_COUNSEL}:
                continue
            if require_case_access and not visibility.can_view_case(self.session, u, case):
                continue
            if document_id is not None and not visibility.can_view_document(self.session, u, document_id):
                continue
            out.append(u)
        return out
