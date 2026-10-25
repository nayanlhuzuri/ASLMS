"""Admin tickets (design `user-memberships`, decisions 15-20 and 24): requests that need the super admin's
decision, with their supporting documents and alerts.

- A generic mechanism: each kind is a handler in `KINDS` (`validate`, `check`, `apply`, `describe`, `doc_types`);
  `head_change` is the first. A ticket is `open` → `approved` | `rejected` | `withdrawn` (final; the database
  trigger refuses any later update). One open `head_change` ticket per department (partial unique index).
- A department admin's request (a membership holding `users.propose_head` in the department) opens a ticket and
  an `admin_ticket` alert to the super admin; until approval nothing changes. Approval locks the ticket, re-runs
  `check` and applies exactly what was proposed, or refuses with 409 `ticket_stale` (audited, the ticket stays
  open). The super admin's own request is applied at once and recorded as an already approved ticket.
- Supporting documents (kind `admin`, type `government_order`) come with the request or are attached while the
  ticket is open; on approval they are linked to every membership the ticket changed.
- Visibility in SQL: `admin.tickets` (the super admin only, reserved) sees every ticket; a holder of
  `users.propose_head` sees the tickets of the departments where they hold it. Others get 404."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, model_validator
from sqlalchemy import ColumnElement, and_, exists, false, func, or_, select, true
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from aslms.domain.alerts import Alert, AlertStatus
from aslms.domain.documents import DocKind, Document
from aslms.domain.org import Office, User, UserMembership
from aslms.domain.reference import AlertKind, DocType, Permission, RecordType, RefTicketKind, Role, TicketKind
from aslms.domain.tickets import AdminTicket, AdminTicketDocument, MembershipDocument, TicketStatus
from aslms.services import access, memberships
from aslms.services.access import DELEGABLE_ROLES, Conflict, Forbidden, Member
from aslms.services.audit import Actor, snapshot, write_audit
from aslms.services.memberships import MembershipError
from aslms.services.refno import allocate_ref_no

MAX_FILES = 5
MAX_REMARK = 2000
MIN_REJECT_REMARK = 3


class TicketError(ValueError):
    """A refused ticket action. `code` is machine-readable; `http_status` 400 / 403 / 404 / 409."""

    def __init__(self, code: str, message: str, http_status: int = 400, **extra: Any) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status
        self.extra = extra


class TicketNotFound(TicketError):
    def __init__(self) -> None:
        super().__init__("not_found", "no such ticket", 404)


class TicketStale(TicketError):
    """Approval refused because the world moved (409 `ticket_stale`); the refusal is audited, so the caller
    commits before answering."""

    def __init__(self, message: str, **extra: Any) -> None:
        super().__init__("ticket_stale", f"the ticket no longer applies: {message}", 409, **extra)
        self.audited = True


def _now() -> datetime:
    return datetime.now(UTC)


def _remark(value: str | None, *, required: bool = False) -> str | None:
    text = (value or "").strip() or None
    if required and (text is None or len(text) < MIN_REJECT_REMARK):
        raise TicketError(
            "bad_field", f"a remark of {MIN_REJECT_REMARK} to {MAX_REMARK} characters is required"
        )
    if text and len(text) > MAX_REMARK:
        raise TicketError("bad_field", f"the remark is at most {MAX_REMARK} characters")
    return text


# ------------------------------------------------------------------------------------------------ head change payload


class ExitAssignment(BaseModel):
    key: str = Field(min_length=1, max_length=200)
    to_membership: uuid.UUID
    pending_action: str | None = None
    due_date: date | None = None
    remark: str | None = Field(None, max_length=MAX_REMARK)


class HeadChangeIncoming(BaseModel):
    membership_id: uuid.UUID | None = None
    email: str | None = Field(None, max_length=254)
    designation: str | None = Field(None, max_length=200)
    designation_id: uuid.UUID | None = None
    role_from: str | None = None

    @model_validator(mode="after")
    def _one(self) -> HeadChangeIncoming:
        if (self.membership_id is None) == (not self.email):
            raise ValueError("incoming is a membership_id or an email")
        return self


class HeadChangeOutgoing(BaseModel):
    mode: Literal["retype", "exit"]
    role_to: Role | None = None
    assignments: list[ExitAssignment] | None = None
    items_fingerprint: str | None = None
    reason: str | None = Field(None, max_length=500)

    @model_validator(mode="after")
    def _shape(self) -> HeadChangeOutgoing:
        if self.mode == "retype":
            if self.role_to is not None and self.role_to not in DELEGABLE_ROLES:
                raise ValueError(
                    "the outgoing head becomes an officer type (never dept_admin or super_admin)"
                )
        else:
            if self.assignments is None or self.items_fingerprint is None:
                raise ValueError(
                    "an exit carries the full assignment list and the preview's items_fingerprint"
                )
            if not self.reason or len(self.reason.strip()) < 3:
                raise ValueError("an exit carries a reason")
        return self


class HeadChangePayload(BaseModel):
    operation: Literal["set", "replace", "end"]
    department_code: str = Field(min_length=1, max_length=40)
    incoming: HeadChangeIncoming | None = None
    outgoing: HeadChangeOutgoing | None = None

    @model_validator(mode="after")
    def _shape(self) -> HeadChangePayload:
        if self.operation == "set" and (self.incoming is None or self.outgoing is not None):
            raise ValueError("set names the incoming head only")
        if self.operation == "replace" and (self.incoming is None or self.outgoing is None):
            raise ValueError("replace names the incoming head and the outgoing head's fate")
        if self.operation == "end" and (self.outgoing is None or self.incoming is not None):
            raise ValueError("end names the outgoing head's fate only")
        return self


# ------------------------------------------------------------------------------------------------ the registry


@dataclass
class Checked:
    """What `check` resolved: the department, the current head, the incoming membership or login."""

    department: Office
    current_head: UserMembership | None = None
    incoming_membership: UserMembership | None = None
    incoming_user: User | None = None
    notes: dict[str, Any] = field(default_factory=dict)


class HeadChange:
    kind = TicketKind.HEAD_CHANGE
    label = "Head of department change"
    doc_types: frozenset[DocType] = frozenset({DocType.GOVERNMENT_ORDER})

    @staticmethod
    def validate(payload: dict[str, Any]) -> HeadChangePayload:
        try:
            return HeadChangePayload.model_validate(payload)
        except ValidationError as exc:
            msg = "; ".join(e.get("msg", "invalid") for e in exc.errors())
            raise TicketError("bad_field", f"the request is not valid: {msg}") from exc

    @staticmethod
    def check(
        session: Session, p: HeadChangePayload, *, super_admin: bool, stale_code: str = "stale_exit"
    ) -> Checked:
        """Decisions 15-16: the rules checked at request and again at approval (for the department admin's
        rules; the super admin is not limited by `not_delegable` nor by an open ticket)."""
        from aslms.services.offices import find_office

        dept = find_office(session, p.department_code)
        if dept is None or not dept.is_active or not access.is_department(dept):
            raise TicketError("bad_field", f"{p.department_code!r} is not an active department")
        out = Checked(department=dept, current_head=memberships.head_of(session, dept))
        if p.operation == "set" and out.current_head is not None:
            raise Conflict("head_exists", f"{dept.code} already has a head; request a replacement")
        if p.operation in ("replace", "end") and out.current_head is None:
            raise Conflict("no_head", f"{dept.code} has no head; request one with set")
        if p.incoming is not None:
            inc = p.incoming
            if inc.membership_id is not None:
                m = session.get(UserMembership, inc.membership_id)
                if m is None or m.department_id != dept.id:
                    raise TicketError(
                        "bad_field", f"the incoming membership is not a membership of {dept.code}"
                    )
                if m.office_id != dept.id:
                    raise MembershipError(
                        "head_at_department", "a Head of Department sits at the department office"
                    )
                role = Role(m.role)
                if role == Role.DEPT_HEAD and m.is_active:
                    raise Conflict("head_exists", "the incoming membership is already the head")
                if not super_admin and role not in DELEGABLE_ROLES:
                    raise Forbidden(
                        f"a Department Administrator cannot make a {role.value} membership the head",
                        "not_delegable",
                    )
                if role == Role.SUPER_ADMIN:
                    raise Conflict("super_admin_single", "the Super Administrator holds no other membership")
                user = session.get(User, m.user_id)
                if not m.is_active:
                    other = access.member_in_department(session, user, dept)
                    if other is not None:
                        raise Conflict(
                            "one_per_department", "the person already has an active membership there"
                        )
                out.incoming_membership, out.incoming_user = m, user
            else:
                user = memberships.lookup(session, inc.email or "")
                if user is None:
                    raise TicketError("bad_field", "no login with this e-mail")
                if access.member_in_department(session, user, dept) is not None or any(
                    m.department_id == dept.id for m in access.active_memberships(session, user)
                ):
                    raise Conflict(
                        "one_per_department",
                        "the person already has a membership in this department; name that membership",
                    )
                if any(Role(m.role) == Role.SUPER_ADMIN for m in access.active_memberships(session, user)):
                    raise Conflict("super_admin_single", "the Super Administrator holds no other membership")
                out.incoming_user = user
            if out.incoming_user is not None and not out.incoming_user.is_active:
                raise Conflict("login_inactive", "the incoming person's login is disabled")
        if p.outgoing is not None and out.current_head is not None:
            head_user = session.get(User, out.current_head.user_id)
            if head_user is not None and not head_user.is_active and p.outgoing.mode == "retype":
                raise Conflict("login_inactive", "the outgoing head's login is disabled")
            if p.outgoing.mode == "exit":
                items = memberships.exit_items(session, out.current_head)
                memberships._validate_assignments(
                    session,
                    out.current_head,
                    items,
                    [a.model_dump(mode="json") for a in p.outgoing.assignments or []],
                    p.outgoing.items_fingerprint,
                    stale_code=stale_code,
                )
        return out

    @staticmethod
    def apply(
        session: Session, actor: Actor, p: HeadChangePayload, ticket_ref: str, *, stale_code: str
    ) -> dict:
        from aslms.services.offices import find_office

        dept = find_office(session, p.department_code)
        incoming = None
        if p.incoming is not None:
            incoming = (
                {"membership": str(p.incoming.membership_id), "designation": p.incoming.designation}
                if p.incoming.membership_id
                else {
                    "email": p.incoming.email,
                    "designation": p.incoming.designation,
                    "designation_id": p.incoming.designation_id,
                }
            )
        outgoing = p.outgoing.model_dump(mode="json") if p.outgoing is not None else None
        return memberships.apply_head_change(
            session,
            actor,
            dept,
            operation=p.operation,
            incoming=incoming,
            outgoing=outgoing,
            ticket_ref=ticket_ref,
            stale_code=stale_code,
        )

    @staticmethod
    def describe(session: Session, ticket: AdminTicket) -> dict[str, Any]:
        p = ticket.payload or {}
        out: dict[str, Any] = {"operation": p.get("operation"), "department_code": p.get("department_code")}
        inc = p.get("incoming") or {}
        if inc.get("membership_id"):
            m = session.get(UserMembership, uuid.UUID(inc["membership_id"]))
            u = session.get(User, m.user_id) if m else None
            out["incoming"] = {
                "membership_id": inc["membership_id"],
                "user_name": u.full_name if u else None,
                "email": u.email if u else None,
                "designation": inc.get("designation") or (m.designation if m else None),
                "role_from": inc.get("role_from"),
            }
        elif inc.get("email"):
            u = memberships.lookup(session, inc["email"])
            out["incoming"] = {
                "email": inc["email"],
                "user_name": u.full_name if u else None,
                "designation": inc.get("designation"),
                "role_from": None,
            }
        if p.get("outgoing"):
            o = p["outgoing"]
            out["outgoing"] = {
                "mode": o.get("mode"),
                "role_to": o.get("role_to") or ("dept_officer" if o.get("mode") == "retype" else None),
                "assignments": o.get("assignments"),
                "reason": o.get("reason"),
            }
        return out


KINDS: dict[TicketKind, type[HeadChange]] = {TicketKind.HEAD_CHANGE: HeadChange}


def handler(kind: TicketKind | str) -> type[HeadChange]:
    return KINDS[TicketKind(kind)]


# ------------------------------------------------------------------------------------------------ visibility


def _propose_departments(session: Session, user: User | Member) -> list[Office]:
    return [
        m.department
        for m in access.members(session, user)
        if m.department is not None and m.holds(Permission.USERS_PROPOSE_HEAD)
    ]


def sees_all(session: Session, user: User | Member) -> bool:
    return access.has(session, user, Permission.ADMIN_TICKETS)


def visible_condition(session: Session, user: User | Member) -> ColumnElement[bool]:
    """Decision 18, over `admin_tickets`."""
    if sees_all(session, user):
        return true()
    ids = [d.id for d in _propose_departments(session, user)]
    if not ids:
        return false()
    return AdminTicket.department_id.in_(ids)


def admin_document_condition(session: Session, user: User | Member) -> ColumnElement[bool]:
    """Decision 20, over `documents`: an `admin` document is visible to `admin.tickets` holders and to holders
    of `users.propose_head` in the department of a ticket or membership it is linked to."""
    if sees_all(session, user):
        return Document.kind == DocKind.ADMIN
    ids = [d.id for d in _propose_departments(session, user)]
    if not ids:
        return false()
    via_ticket = exists(
        select(AdminTicketDocument.id)
        .join(AdminTicket, AdminTicket.id == AdminTicketDocument.ticket_id)
        .where(AdminTicketDocument.document_id == Document.id, AdminTicket.department_id.in_(ids))
    )
    via_membership = exists(
        select(MembershipDocument.id)
        .join(UserMembership, UserMembership.id == MembershipDocument.membership_id)
        .where(MembershipDocument.document_id == Document.id, UserMembership.department_id.in_(ids))
    )
    return and_(Document.kind == DocKind.ADMIN, or_(via_ticket, via_membership))


def resolve(session: Session, ref: str) -> AdminTicket:
    from aslms.services.cases import ref_no_from_url

    s = (ref or "").strip()
    t = None
    try:
        t = session.get(AdminTicket, uuid.UUID(s))
    except ValueError:
        ref_no = ref_no_from_url(s)
        if ref_no is not None:
            t = session.scalar(select(AdminTicket).where(AdminTicket.ref_no == ref_no))
    if t is None:
        raise TicketNotFound()
    return t


def get(session: Session, user: User | Member, ref: str) -> AdminTicket:
    t = resolve(session, ref)
    if not session.scalar(
        select(visible_condition(session, user)).select_from(AdminTicket).where(AdminTicket.id == t.id)
    ):
        raise TicketNotFound()
    return t


# ------------------------------------------------------------------------------------------------ alerts


def _kind_label(session: Session, kind: TicketKind | str) -> str:
    row = session.get(RefTicketKind, TicketKind(kind).value)
    return row.label if row else TicketKind(kind).value


def _department_code(session: Session, t: AdminTicket) -> str | None:
    d = session.get(Office, t.department_id) if t.department_id else None
    return d.code if d else None


def _raise_opened_alert(session: Session, t: AdminTicket) -> None:
    from aslms.services import alerts

    sa = memberships.super_admin_membership(session)
    recipients = [session.get(User, sa.user_id)] if sa is not None else []
    severity = alerts.default_severities(session).get(AlertKind.ADMIN_TICKET)
    from aslms.domain.alerts import Severity

    alerts.raise_alert(
        session,
        case=None,
        kind=AlertKind.ADMIN_TICKET,
        key=f"admin_ticket:{t.id}:opened",
        office=memberships.state_root(session),
        severity=severity or Severity.NORMAL,
        data={
            "ticket_id": str(t.id),
            "ticket_ref": t.ref_no,
            "kind": TicketKind(t.kind).value,
            "kind_label": _kind_label(session, t.kind),
            "department_code": _department_code(session, t),
            "requested_by": t.actor_name,
            "event": "opened",
        },
        recipients=[u for u in recipients if u is not None and u.is_active],
    )


def _close_opened_alert(session: Session, t: AdminTicket, actor_user_id: uuid.UUID | None) -> None:
    from aslms.services import alerts

    alert = session.scalar(select(Alert).where(Alert.dedupe_key == f"admin_ticket:{t.id}:opened"))
    if alert is not None and AlertStatus(alert.status) in (AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED):
        alerts.close_alert(
            session, alert, AlertStatus.DONE, f"ticket {t.status.value}", actor_user_id=actor_user_id
        )


def _raise_decided_alert(session: Session, t: AdminTicket) -> None:
    from aslms.domain.alerts import Severity
    from aslms.services import alerts

    proposer = session.get(User, t.requested_by_user_id)
    dept = session.get(Office, t.department_id) if t.department_id else memberships.state_root(session)
    status = TicketStatus(t.status).value
    severity = alerts.default_severities(session).get(AlertKind.ADMIN_TICKET) or Severity.NORMAL
    alerts.raise_alert(
        session,
        case=None,
        kind=AlertKind.ADMIN_TICKET,
        key=f"admin_ticket:{t.id}:{status}",
        office=dept,
        severity=severity,
        data={
            "ticket_id": str(t.id),
            "ticket_ref": t.ref_no,
            "kind": TicketKind(t.kind).value,
            "kind_label": _kind_label(session, t.kind),
            "department_code": _department_code(session, t),
            "event": status,
            "remark": t.decision_remark,
        },
        recipients=[proposer] if proposer is not None and proposer.is_active else [],
    )


# ------------------------------------------------------------------------------------------------ documents


@dataclass
class IncomingFile:
    data: bytes
    filename: str
    doc_type: str = DocType.GOVERNMENT_ORDER.value
    doc_date: date | None = None
    description: str | None = None


def _inspect_files(
    session: Session,
    actor: Actor,
    kind: type[HeadChange],
    files: list[IncomingFile],
    *,
    scanner,
    max_bytes: int,
) -> list[Any]:
    """Every file is checked (type by content, size) and scanned before anything is written; one refusal refuses
    the whole request (decision 20)."""
    from aslms.services import documents

    if len(files) > MAX_FILES:
        raise TicketError("bad_field", f"at most {MAX_FILES} files per request")
    if files and not kind.doc_types:
        raise TicketError("uploads_not_allowed", "this kind of ticket takes no documents", 409)
    shas: set[str] = set()
    out = []
    for f in files:
        try:
            dt = DocType(str(f.doc_type or "").strip().lower())
        except ValueError as exc:
            raise TicketError("bad_field", f"unknown doc_type {f.doc_type!r}") from exc
        if dt not in kind.doc_types:
            raise TicketError("bad_field", f"doc_type {dt.value} is not taken by this ticket")
        sha = hashlib.sha256(f.data).hexdigest()
        if sha in shas:
            raise TicketError("duplicate", "the same file is attached twice", 409)
        shas.add(sha)
        out.append(
            documents.inspect_file(
                session, actor, None, data=f.data, filename=f.filename, scanner=scanner, max_bytes=max_bytes
            )
        )
    return out


def _store_file(
    session: Session,
    actor: Actor,
    member: Member,
    t: AdminTicket,
    f: IncomingFile,
    *,
    scanner,
    store,
    max_bytes: int,
    inspected: Any = None,
) -> Document:
    from aslms.services import documents

    sha = hashlib.sha256(f.data).hexdigest()
    dup = session.scalar(
        select(Document.id)
        .join(AdminTicketDocument, AdminTicketDocument.document_id == Document.id)
        .where(AdminTicketDocument.ticket_id == t.id, Document.sha256 == sha, Document.archived_at.is_(None))
    )
    if dup is not None:
        raise TicketError("duplicate", "this file is already on the ticket", 409)
    doc = documents.upload(
        session,
        actor,
        member.user,
        None,
        data=f.data,
        filename=f.filename,
        doc_type=f.doc_type,
        doc_group=None,
        doc_date=f.doc_date,
        description=f.description,
        visibility="private_to_office",
        scanner=scanner,
        store=store,
        kind=DocKind.ADMIN,
        max_bytes=max_bytes,
        member=member,
        allowed_types=handler(t.kind).doc_types,
        inspected=inspected,
    )
    a = access.actor_as(actor, member)
    session.add(AdminTicketDocument(ticket_id=t.id, document_id=doc.id, **snapshot(a)))
    session.flush()
    write_audit(
        session,
        a,
        "ticket.document_attached",
        "admin_ticket",
        t.id,
        after={
            "ticket_ref": t.ref_no,
            "document_id": str(doc.id),
            "ref_no": doc.ref_no,
            "doc_type": f.doc_type,
        },
    )
    return doc


def _link_documents(session: Session, actor: Actor, t: AdminTicket, membership_ids: list[str]) -> None:
    doc_ids = session.scalars(
        select(AdminTicketDocument.document_id)
        .join(Document, Document.id == AdminTicketDocument.document_id)
        .where(AdminTicketDocument.ticket_id == t.id, Document.archived_at.is_(None))
    ).all()
    for mid in dict.fromkeys(membership_ids):
        for did in doc_ids:
            exists_ = session.scalar(
                select(MembershipDocument.id).where(
                    MembershipDocument.membership_id == uuid.UUID(mid), MembershipDocument.document_id == did
                )
            )
            if exists_ is None:
                session.add(
                    MembershipDocument(
                        membership_id=uuid.UUID(mid), document_id=did, ticket_id=t.id, **snapshot(actor)
                    )
                )
    session.flush()


# ------------------------------------------------------------------------------------------------ requests


def _decider_snapshot(t: AdminTicket, actor: Actor) -> None:
    t.decided_by_user_id = actor.user_id
    t.decided_by_name = actor.name[:200]
    t.decided_by_designation = (actor.designation or None) and actor.designation[:200]
    t.decided_by_office_code = (actor.office_code or None) and actor.office_code[:40]
    t.decided_at = _now()


def _requester(session: Session, user: User | Member, dept: Office) -> tuple[Member, bool]:
    sa = access.super_admin_member(session, user)
    if sa is not None:
        return sa, True
    m = access.member_in_department(session, user, dept)
    if m is None or not m.holds(Permission.USERS_PROPOSE_HEAD):
        if access.has(session, user, Permission.USERS_PROPOSE_HEAD):
            raise Forbidden(f"{dept.code} is outside your offices")
        raise Forbidden("users.propose_head is not enabled for you")
    return m, False


def request_head_change(
    session: Session,
    actor: Actor,
    user: User | Member,
    payload: dict[str, Any],
    *,
    request_remark: str | None = None,
    files: list[IncomingFile] | None = None,
    scanner=None,
    store=None,
    max_bytes: int = 20 * 1024 * 1024,
) -> AdminTicket:
    """Decision 15: a department admin's request opens a ticket (nothing changes until approval); the super
    admin's is applied at once and recorded as an approved ticket (closing a department admin's open ticket of
    the same department as superseded). Files are checked and scanned before anything is written."""
    kind = HeadChange
    p = kind.validate(payload)
    from aslms.services.offices import find_office

    dept = find_office(session, p.department_code)
    if dept is None or not dept.is_active or not access.is_department(dept):
        raise TicketError("bad_field", f"{p.department_code!r} is not an active department")
    member, is_super = _requester(session, user, dept)
    if p.operation == "end" and not is_super:
        raise Forbidden(
            "only the Super Administrator may end a head and leave the department without one",
            "super_admin_only",
        )
    remark = _remark(request_remark)
    files = files or []
    actor = access.actor_as(actor, member)
    open_ticket = session.scalar(
        select(AdminTicket).where(
            AdminTicket.department_id == dept.id,
            AdminTicket.kind == TicketKind.HEAD_CHANGE,
            AdminTicket.status == TicketStatus.OPEN,
        )
    )
    if open_ticket is not None and not is_super:
        raise Conflict(
            "ticket_open", f"{dept.code} already has an open head-change ticket ({open_ticket.ref_no})"
        )
    checked = kind.check(session, p, super_admin=is_super)
    inspected = _inspect_files(session, actor, kind, files, scanner=scanner, max_bytes=max_bytes)
    stored_payload = p.model_dump(mode="json")
    if checked.incoming_membership is not None and stored_payload.get("incoming"):
        stored_payload["incoming"]["role_from"] = Role(checked.incoming_membership.role).value
    ref = allocate_ref_no(session, dept.code, RecordType.TKT.value)
    target_user = checked.incoming_user or (
        session.get(User, checked.current_head.user_id) if checked.current_head else None
    )
    common = {
        "ref_no": ref,
        "kind": TicketKind.HEAD_CHANGE,
        "department_id": dept.id,
        "target_user_id": target_user.id if target_user else None,
        "target_membership_id": checked.incoming_membership.id
        if checked.incoming_membership
        else (checked.current_head.id if checked.current_head and p.operation == "end" else None),
        "requested_by_user_id": member.user.id,
        "requested_by_membership_id": member.membership_id,
        "payload": stored_payload,
        "request_remark": remark,
        **snapshot(actor),
    }
    if not is_super:
        t = AdminTicket(status=TicketStatus.OPEN, **common)
        _insert(session, t)
        for f, ins in zip(files, inspected, strict=True):
            _store_file(
                session, actor, member, t, f, scanner=scanner, store=store, max_bytes=max_bytes, inspected=ins
            )
        write_audit(
            session,
            actor,
            "ticket.opened",
            "admin_ticket",
            t.id,
            after={
                "ticket_ref": ref,
                "kind": "head_change",
                "payload": stored_payload,
                "request_remark": remark,
            },
        )
        _raise_opened_alert(session, t)
        return t
    # the super admin: no approval, no waiting; a department admin's open ticket is superseded
    if open_ticket is not None:
        _decide(
            session,
            actor,
            open_ticket,
            TicketStatus.REJECTED,
            f"superseded by the Super Administrator's change {ref}",
        )
    result = kind.apply(session, actor, p, ref, stale_code="stale_exit")
    incoming_id = (result.get("incoming") or {}).get("membership_id")
    if incoming_id:
        common["target_membership_id"] = uuid.UUID(incoming_id)
    t = AdminTicket(status=TicketStatus.APPROVED, result=result, **common)
    _decider_snapshot(t, actor)
    _insert(session, t)
    for f, ins in zip(files, inspected, strict=True):
        _store_file(
            session, actor, member, t, f, scanner=scanner, store=store, max_bytes=max_bytes, inspected=ins
        )
    _link_documents(session, actor, t, result.get("membership_ids", []))
    write_audit(
        session,
        actor,
        "ticket.opened",
        "admin_ticket",
        t.id,
        after={"ticket_ref": ref, "kind": "head_change", "payload": stored_payload, "request_remark": remark},
    )
    write_audit(
        session,
        actor,
        "ticket.approved",
        "admin_ticket",
        t.id,
        after={"ticket_ref": ref, "result": result, "direct": True},
    )
    return t


def record_direct_set(
    session: Session, actor: Actor, user: User | Member, department: Office, incoming: dict[str, Any]
) -> AdminTicket:
    """Decision 24: the head named when the super admin creates or reactivates a department — applied at once
    (a new login when the e-mail is unknown and a password is given) and recorded as an approved `set` ticket so
    an order can be attached later."""
    sa = access.super_admin_member(session, user)
    if sa is None:
        raise Forbidden("only the Super Administrator creates a department", "super_admin_only")
    actor = access.actor_as(actor, sa)
    if memberships.head_of(session, department) is not None:
        raise Conflict("head_exists", f"{department.code} already has a head")
    ref = allocate_ref_no(session, department.code, RecordType.TKT.value)
    result = memberships.apply_head_change(
        session, actor, department, operation="set", incoming=incoming, outgoing=None, ticket_ref=ref
    )
    head_id = uuid.UUID(result["incoming"]["membership_id"])
    head = session.get(UserMembership, head_id)
    payload = {
        "operation": "set",
        "department_code": department.code,
        "incoming": {
            "membership_id": None,
            "email": session.get(User, head.user_id).email,
            "designation": head.designation,
            "designation_id": str(head.designation_id) if head.designation_id else None,
            "role_from": None,
        },
        "outgoing": None,
    }
    t = AdminTicket(
        ref_no=ref,
        kind=TicketKind.HEAD_CHANGE,
        status=TicketStatus.APPROVED,
        department_id=department.id,
        target_user_id=head.user_id,
        target_membership_id=head.id,
        requested_by_user_id=sa.user.id,
        requested_by_membership_id=sa.membership_id,
        payload=payload,
        request_remark="head named when the department was created or reactivated",
        result=result,
        **snapshot(actor),
    )
    _decider_snapshot(t, actor)
    _insert(session, t)
    write_audit(
        session,
        actor,
        "ticket.approved",
        "admin_ticket",
        t.id,
        after={"ticket_ref": ref, "result": result, "direct": True},
    )
    return t


def _insert(session: Session, t: AdminTicket) -> None:
    try:
        with session.begin_nested():
            session.add(t)
            session.flush()
    except IntegrityError as exc:
        if "ix_admin_tickets_one_open_head_change" in str(exc.orig):
            raise Conflict("ticket_open", "the department already has an open head-change ticket") from exc
        raise


def _decide(session: Session, actor: Actor, t: AdminTicket, status: TicketStatus, remark: str | None) -> None:
    before = {"status": TicketStatus(t.status).value}
    t.status = status
    t.decision_remark = remark
    _decider_snapshot(t, actor)
    session.flush()
    _close_opened_alert(session, t, actor.user_id)
    action = {
        TicketStatus.APPROVED: "ticket.approved",
        TicketStatus.REJECTED: "ticket.rejected",
        TicketStatus.WITHDRAWN: "ticket.withdrawn",
    }[status]
    write_audit(
        session,
        actor,
        action,
        "admin_ticket",
        t.id,
        before=before,
        after={"ticket_ref": t.ref_no, "status": status.value, "remark": remark, "result": t.result},
    )
    if status in (TicketStatus.APPROVED, TicketStatus.REJECTED):
        _raise_decided_alert(session, t)


def _lock_open(session: Session, t: AdminTicket) -> None:
    session.execute(select(AdminTicket.id).where(AdminTicket.id == t.id).with_for_update())
    session.refresh(t)
    if TicketStatus(t.status) != TicketStatus.OPEN:
        raise TicketError("ticket_closed", f"the ticket is {TicketStatus(t.status).value}", 409)


def _super_admin(session: Session, user: User | Member) -> Member:
    sa = access.super_admin_member(session, user)
    if sa is None or not sa.holds(Permission.ADMIN_TICKETS):
        raise Forbidden("only the Super Administrator decides tickets", "super_admin_only")
    return sa


def approve(
    session: Session, actor: Actor, user: User | Member, t: AdminTicket, remark: str | None = None
) -> AdminTicket:
    """Decision 17: lock, re-check against the current state (the requester's rules), apply exactly what was
    proposed; a moved world → 409 `ticket_stale`, audited `ticket.approve_refused`, the ticket stays open."""
    sa = _super_admin(session, user)
    actor = access.actor_as(actor, sa)
    remark = _remark(remark)
    _lock_open(session, t)
    kind = handler(t.kind)
    p = kind.validate(t.payload)
    requester = session.get(UserMembership, t.requested_by_membership_id)
    try:
        with session.begin_nested():
            if requester is None or not requester.is_active:
                raise Conflict("requester_ended", "the requesting membership has ended")
            checked = kind.check(session, p, super_admin=False, stale_code="ticket_stale")
            if checked.incoming_membership is not None:
                for m_id in (checked.incoming_membership.id,):
                    session.execute(
                        select(UserMembership.id).where(UserMembership.id == m_id).with_for_update()
                    )
            result = kind.apply(session, actor, p, t.ref_no, stale_code="ticket_stale")
    except (Conflict, MembershipError, Forbidden, TicketError) as exc:
        reason = getattr(exc, "code", "stale")
        write_audit(
            session,
            actor,
            "ticket.approve_refused",
            "admin_ticket",
            t.id,
            after={"ticket_ref": t.ref_no, "reason": reason, "message": str(exc)},
        )
        raise TicketStale(str(exc), reason=reason, **(getattr(exc, "extra", {}) or {})) from exc
    t.result = result
    incoming_id = (result.get("incoming") or {}).get("membership_id")
    if incoming_id:
        t.target_membership_id = uuid.UUID(incoming_id)
    _decide(session, actor, t, TicketStatus.APPROVED, remark)
    _link_documents(session, actor, t, result.get("membership_ids", []))
    return t


def reject(
    session: Session, actor: Actor, user: User | Member, t: AdminTicket, remark: str | None
) -> AdminTicket:
    sa = _super_admin(session, user)
    remark = _remark(remark, required=True)
    _lock_open(session, t)
    _decide(session, access.actor_as(actor, sa), t, TicketStatus.REJECTED, remark)
    return t


def withdraw(
    session: Session, actor: Actor, user: User | Member, t: AdminTicket, remark: str | None = None
) -> AdminTicket:
    """The proposer (same login, while the proposing membership is active), while the ticket is open."""
    remark = _remark(remark)
    requester = session.get(UserMembership, t.requested_by_membership_id)
    if t.requested_by_user_id != user.id or requester is None or not requester.is_active:
        raise Forbidden("only the proposer may withdraw the ticket")
    _lock_open(session, t)
    member = access.member_of(session, requester)
    _decide(session, access.actor_as(actor, member), t, TicketStatus.WITHDRAWN, remark)
    return t


def _attach_member(session: Session, user: User | Member, t: AdminTicket) -> Member:
    sa = access.super_admin_member(session, user)
    if sa is not None:
        return sa
    dept = session.get(Office, t.department_id) if t.department_id else None
    m = access.member_in_department(session, user, dept)
    if m is None or not m.holds(Permission.USERS_PROPOSE_HEAD):
        raise TicketNotFound()
    return m


def attach_document(
    session: Session,
    actor: Actor,
    user: User | Member,
    t: AdminTicket,
    *,
    data: bytes,
    filename: str,
    doc_type: str,
    doc_date: date | None,
    description: str | None,
    scanner,
    store,
    max_bytes: int,
) -> Document:
    """Decision 20: while the ticket is open (409 `ticket_closed` after any decision), the kind's types only."""
    member = _attach_member(session, user, t)
    if TicketStatus(t.status) != TicketStatus.OPEN:
        raise TicketError("ticket_closed", f"the ticket is {TicketStatus(t.status).value}", 409)
    kind = handler(t.kind)
    if not kind.doc_types:
        raise TicketError("uploads_not_allowed", "this kind of ticket takes no documents", 409)
    f = IncomingFile(
        data=data, filename=filename, doc_type=doc_type, doc_date=doc_date, description=description
    )
    a = access.actor_as(actor, member)
    inspected = _inspect_files(session, a, kind, [f], scanner=scanner, max_bytes=max_bytes)
    return _store_file(
        session, a, member, t, f, scanner=scanner, store=store, max_bytes=max_bytes, inspected=inspected[0]
    )


def ticket_document(session: Session, user: User | Member, t: AdminTicket, doc_ref: str) -> Document:
    from aslms.services import documents

    try:
        doc = documents.resolve_document_ref(session, doc_ref)
    except LookupError as exc:
        raise TicketError("not_found", "no such document", 404) from exc
    linked = session.scalar(
        select(AdminTicketDocument.id).where(
            AdminTicketDocument.ticket_id == t.id, AdminTicketDocument.document_id == doc.id
        )
    )
    if linked is None:
        raise TicketError("not_found", "no such document", 404)
    return doc


def archive_document(
    session: Session, actor: Actor, user: User | Member, t: AdminTicket, doc: Document, reason: str | None
) -> Document:
    """The uploader or the super admin, while the ticket is open; never deleted (decision 20)."""
    if TicketStatus(t.status) != TicketStatus.OPEN:
        raise TicketError("ticket_closed", f"the ticket is {TicketStatus(t.status).value}", 409)
    sa = access.super_admin_member(session, user)
    if sa is None and doc.actor_user_id != user.id:
        raise Forbidden("only the uploader or the Super Administrator may archive this document")
    if doc.archived_at is not None:
        raise TicketError("bad_field", "the document is already archived")
    text = (reason or "").strip()
    if not 3 <= len(text) <= 500:
        raise TicketError("bad_field", "a reason of 3 to 500 characters is required")
    member = sa or access.primary_member(session, user)
    a = access.actor_as(actor, member)
    doc.archived_at = _now()
    doc.archive_reason = text
    session.flush()
    write_audit(
        session,
        a,
        "ticket.document_archived",
        "admin_ticket",
        t.id,
        after={"ticket_ref": t.ref_no, "document_id": str(doc.id), "ref_no": doc.ref_no, "reason": text},
    )
    return doc


def open_document(
    session: Session,
    actor: Actor,
    user: User | Member,
    doc: Document,
    *,
    store,
    disposition: str = "attachment",
):
    """A ticket or membership document as a file, under `admin_document_condition`; audited."""
    from aslms.services import documents
    from aslms.services.filetypes import INLINE_MIMES
    from aslms.services.storage import EXT_FOR_MIME

    disposition = (disposition or "attachment").strip().lower()
    if disposition not in ("inline", "attachment"):
        raise TicketError("bad_field", "disposition must be inline or attachment")
    ok = session.scalar(
        select(admin_document_condition(session, user)).select_from(Document).where(Document.id == doc.id)
    )
    if not ok:
        raise TicketError("not_found", "no such document", 404)
    if disposition == "inline" and doc.mime not in INLINE_MIMES:
        raise TicketError("inline_not_supported", "inline viewing is offered for PDF, JPEG and PNG only")
    path = store.path(doc.storage_key)
    if not path.is_file():
        raise documents.FileMissing(f"the stored file of {doc.ref_no or doc.id} is missing")
    write_audit(
        session,
        actor,
        "document.downloaded",
        "document",
        doc.id,
        after={"ref_no": doc.ref_no, "disposition": disposition, "original_filename": doc.original_filename},
    )
    name = (
        doc.original_filename
        or f"{(doc.ref_no or str(doc.id)).replace('/', '-')}.{EXT_FOR_MIME.get(doc.mime, 'bin')}"
    )
    return documents.ServedFile(path, doc.mime, documents.safe_filename(name), doc.size_bytes, disposition)


# ------------------------------------------------------------------------------------------------ reading


def departments_without_head(session: Session) -> list[Office]:
    from aslms.services.offices import departments_without_head as _dwh

    return _dwh(session)


def _filtered(
    session: Session,
    user: User | Member,
    *,
    status: str | None,
    kind: str | None,
    department: str | None,
    mine: bool,
):
    stmt = select(AdminTicket).where(visible_condition(session, user))
    if status is None or status == "open":
        stmt = stmt.where(AdminTicket.status == TicketStatus.OPEN)
    elif status != "all":
        try:
            stmt = stmt.where(AdminTicket.status == TicketStatus(status))
        except ValueError as exc:
            raise TicketError("bad_field", f"unknown status {status!r}") from exc
    if kind:
        try:
            stmt = stmt.where(AdminTicket.kind == TicketKind(kind))
        except ValueError as exc:
            raise TicketError("bad_field", f"unknown kind {kind!r}") from exc
    if department:
        from aslms.services.offices import find_office

        d = find_office(session, department)
        stmt = stmt.where(AdminTicket.department_id == (d.id if d else None))
    if mine:
        stmt = stmt.where(AdminTicket.requested_by_user_id == user.id)
    return stmt


def counts(session: Session, user: User | Member) -> dict[str, Any]:
    cond = and_(visible_condition(session, user), AdminTicket.status == TicketStatus.OPEN)
    total = int(session.scalar(select(func.count(AdminTicket.id)).where(cond)) or 0)
    by_kind = {
        TicketKind(k).value: int(n)
        for k, n in session.execute(
            select(AdminTicket.kind, func.count()).where(cond).group_by(AdminTicket.kind)
        ).all()
    }
    by_dept = {
        code: int(n)
        for code, n in session.execute(
            select(Office.code, func.count())
            .select_from(AdminTicket)
            .join(Office, Office.id == AdminTicket.department_id)
            .where(cond)
            .group_by(Office.code)
        ).all()
    }
    oldest = session.scalar(select(func.min(AdminTicket.created_at)).where(cond))
    out: dict[str, Any] = {
        "open": total,
        "open_by_kind": by_kind,
        "open_by_department": by_dept,
        "oldest_open_at": oldest,
    }
    if sees_all(session, user):
        out["departments_without_head"] = len(departments_without_head(session))
    return out


def list_tickets(
    session: Session,
    user: User | Member,
    *,
    status: str | None = "open",
    kind: str | None = None,
    department: str | None = None,
    mine: bool = False,
    limit: int | None = None,
    offset: int | None = None,
) -> tuple[list[dict[str, Any]], int]:
    limit = 50 if limit is None else max(1, min(int(limit), 200))
    offset = max(0, int(offset or 0))
    stmt = _filtered(session, user, status=status, kind=kind, department=department, mine=mine)
    total = int(session.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = session.scalars(
        stmt.order_by(AdminTicket.created_at, AdminTicket.id).limit(limit).offset(offset)
    ).all()
    return [ticket_item(session, t) for t in rows], total


def _documents_count(session: Session, t: AdminTicket) -> int:
    return int(
        session.scalar(
            select(func.count(AdminTicketDocument.id)).where(AdminTicketDocument.ticket_id == t.id)
        )
        or 0
    )


def ticket_item(session: Session, t: AdminTicket) -> dict[str, Any]:
    p = t.payload or {}
    desc = handler(t.kind).describe(session, t)
    inc = desc.get("incoming") or {}
    out = desc.get("outgoing") or {}
    target_user = session.get(User, t.target_user_id) if t.target_user_id else None
    now = _now()
    return {
        "ref_no": t.ref_no,
        "kind": TicketKind(t.kind).value,
        "status": TicketStatus(t.status).value,
        "department_code": _department_code(session, t),
        "operation": p.get("operation"),
        "target": {
            "user_name": inc.get("user_name") or (target_user.full_name if target_user else None),
            "designation": inc.get("designation"),
            "role_from": inc.get("role_from"),
            "role_to": "dept_head" if p.get("operation") in ("set", "replace") else out.get("role_to"),
        },
        "requested_by": {
            "name": t.actor_name,
            "designation": t.actor_designation,
            "office_code": t.actor_office_code,
        },
        "created_at": t.created_at,
        "age_days": max(0, (now - t.created_at).days) if t.created_at else 0,
        "documents_count": _documents_count(session, t),
        "decided_at": t.decided_at,
    }


def documents_of_ticket(session: Session, t: AdminTicket) -> list[dict[str, Any]]:
    rows = session.execute(
        select(Document, AdminTicketDocument)
        .join(AdminTicketDocument, AdminTicketDocument.document_id == Document.id)
        .where(AdminTicketDocument.ticket_id == t.id)
        .order_by(AdminTicketDocument.created_at)
    ).all()
    return [
        {
            "id": d.id,
            "ref_no": d.ref_no,
            "doc_type": d.doc_type.value if hasattr(d.doc_type, "value") else str(d.doc_type),
            "doc_date": d.doc_date,
            "description": d.description,
            "original_filename": d.original_filename,
            "mime": d.mime,
            "size_bytes": d.size_bytes,
            "archived": d.archived_at is not None,
            "archive_reason": d.archive_reason,
            "attached_by": link.actor_name,
            "attached_at": link.created_at,
            "uploaded_by_user_id": d.actor_user_id,
        }
        for d, link in rows
    ]


def ticket_out(session: Session, user: User | Member, t: AdminTicket) -> dict[str, Any]:
    item = ticket_item(session, t)
    is_sa = access.super_admin_member(session, user) is not None
    open_ = TicketStatus(t.status) == TicketStatus.OPEN
    out: dict[str, Any] = {
        **item,
        "payload": handler(t.kind).describe(session, t),
        "request_remark": t.request_remark,
        "decision_remark": t.decision_remark,
        "result": t.result,
        "decided_by": {
            "name": t.decided_by_name,
            "designation": t.decided_by_designation,
            "office_code": t.decided_by_office_code,
        }
        if t.decided_at
        else None,
        "documents": documents_of_ticket(session, t),
        "outgoing_detail": None,
        "can_approve": is_sa and open_,
        "can_withdraw": open_ and t.requested_by_user_id == user.id,
        "can_attach": open_ and bool(handler(t.kind).doc_types),
    }
    if is_sa and t.department_id:
        head = memberships.head_of(session, session.get(Office, t.department_id))
        if head is not None and (t.payload or {}).get("operation") in ("replace", "end"):
            items = memberships.exit_items(session, head)
            out["outgoing_detail"] = {
                "membership_id": head.id,
                "overrides": [o for o in memberships.overrides_out(session, head) if o["is_active"]],
                "files_held": sum(1 for i in items if i.kind == "file"),
                "allotments": sum(1 for i in items if i.kind == "allotment"),
            }
    return out


def membership_documents(session: Session, user: User | Member, m: UserMembership) -> list[dict[str, Any]]:
    """`GET .../memberships/{mid}/documents` (decision 20): the orders linked to a membership, for the super
    admin and the holders of `users.propose_head` in its department; else not found."""
    if not sees_all(session, user):
        ids = {d.id for d in _propose_departments(session, user)}
        if m.department_id not in ids:
            raise TicketError("not_found", "no such membership", 404)
    rows = session.execute(
        select(Document, MembershipDocument)
        .join(MembershipDocument, MembershipDocument.document_id == Document.id)
        .where(MembershipDocument.membership_id == m.id)
        .order_by(MembershipDocument.created_at)
    ).all()
    out = []
    for d, link in rows:
        t = session.get(AdminTicket, link.ticket_id) if link.ticket_id else None
        out.append(
            {
                "id": d.id,
                "ref_no": d.ref_no,
                "doc_type": d.doc_type.value if hasattr(d.doc_type, "value") else str(d.doc_type),
                "doc_date": d.doc_date,
                "description": d.description,
                "ticket_ref": t.ref_no if t else None,
                "archived": d.archived_at is not None,
                "attached_by": link.actor_name,
                "attached_at": link.created_at,
            }
        )
    return out
