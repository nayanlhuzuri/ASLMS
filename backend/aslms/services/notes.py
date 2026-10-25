"""The case notes trail (design `custody-workflow`, decisions 12-18, 20, 21, 26).

- **Drafts of the holder** (decision 12, the owner's exception to "no deletion"): a note written by the caller
  whose membership holds the file is a draft in `case_note_drafts` — visible only to its author, editable and
  deletable while that membership holds the case, with links to documents already on the case (no new files),
  no `ref_no` and no `seq_no`, at most `NOTE_DRAFTS_MAX` per holder per case.
- **Finalisation** (decision 13): `finalise_drafts`, called by `custody.move_custody` under the case row lock in
  the move's transaction, turns each draft of the previous holder membership (oldest first) into a permanent
  `case_notes` row (next `seq_no`, `ref_no` on the membership's office, the leg it was written in, `drafted_at`,
  the draft's author snapshot), its links into `case_note_attachments`, and deletes the draft rows. A draft
  correcting a note corrected meanwhile supersedes the latest note of that chain.
- **Notes by others are permanent at once** (decision 14): `notes.add` in the acting membership with a working
  basis; files (checked and scanned before anything is written) and links.
- **Corrections** (decision 16): same case, visible, not already superseded (409 `already_superseded`); only the
  author or a whole-department membership of the original note's department (403 `not_author`); the original's
  kind and visibility (and its office, so the audience is the same).
- Every read applies `visibility.note_visible_condition` in SQL; drafts are read only by their author.
- Events and audit rows carry references, codes and the body's length and SHA-256, never the text. Drafts write
  audit rows but no event."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import Select, and_, delete, exists, func, literal, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from aslms.domain.cases import Case
from aslms.domain.documents import DocKind, Document, Visibility
from aslms.domain.org import Office, User, UserMembership
from aslms.domain.reference import EventType, NoteKind, Permission, RecordType, RefNoteKind
from aslms.domain.workflow import (
    CaseNote,
    CaseNoteAttachment,
    CaseNoteDraft,
    CaseNoteDraftDocument,
    Custody,
    CustodyHistory,
    NoteSource,
)
from aslms.services import access, attachments, inbox, visibility
from aslms.services.access import Member
from aslms.services.attachments import Prepared
from aslms.services.audit import Actor, snapshot, write_audit
from aslms.services.cases import emit_event, ref_no_from_url
from aslms.services.refno import allocate_ref_no
from aslms.services.scanner import Scanner
from aslms.services.storage import LocalStore
from aslms.services.visibility import NotVisibleNote, document_visible_condition, note_visible_condition
from aslms.services.workflow_common import (
    acting_member,
    bad,
    conflict,
    digest,
    forbidden,
    lock_case,
    primary_owner,
    require_function,
    require_owned,
    require_visible_basis,
    value,
)

DEFAULT_NOTE_MAX = 20_000
DEFAULT_DRAFTS_MAX = 20
RETIRED_KINDS = frozenset({NoteKind.CORRECTION})


class DraftNotFound(LookupError):
    """No such draft, or not the caller's (HTTP 404)."""


class _Unset:
    pass


UNSET: Any = _Unset()


# ------------------------------------------------------------------------------------------------ checks


def check_kind(session: Session, raw: str | None) -> NoteKind:
    try:
        kind = NoteKind(str(raw or "").strip().lower())
    except ValueError as exc:
        raise bad(f"unknown note kind {raw!r}") from exc
    row = session.get(RefNoteKind, kind.value)
    if row is None or not row.is_active or kind in RETIRED_KINDS:
        raise bad(f"note kind {kind.value} cannot be chosen")
    return kind


def check_body(body: str | None, max_chars: int) -> str:
    text_ = (body or "").strip()
    if not text_:
        raise bad("the note body is required")
    if len(text_) > max_chars:
        raise bad(f"the note body is at most {max_chars} characters")
    return text_


def check_visibility(raw: str | None) -> Visibility:
    if raw is None or str(raw).strip() == "":
        raise bad("visibility is required (case_scope, counsel_shared or private_to_office)")
    try:
        return Visibility(str(raw).strip().lower())
    except ValueError as exc:
        raise bad("visibility must be case_scope, counsel_shared or private_to_office") from exc


def resolve_note_ref(session: Session, ref: str) -> CaseNote:
    s = (ref or "").strip()
    note = None
    try:
        note = session.get(CaseNote, uuid.UUID(s))
    except ValueError:
        ref_no = ref_no_from_url(s)
        if ref_no is not None:
            note = session.scalar(select(CaseNote).where(CaseNote.ref_no == ref_no))
    if note is None:
        raise NotVisibleNote("no such note")
    return note


def _may_correct(session: Session, user: User | Member, original: CaseNote) -> bool:
    """Decision 16: the original author, or a whole-department membership of the original note's department."""
    if original.actor_user_id == user.id:
        return True
    office = session.get(Office, original.office_id)
    return office is not None and any(
        m.department is not None
        and visibility.whole_department(session, m)
        and visibility.in_subtree(office, m.department)
        for m in access.members(session, user)
    )


def _superseded(session: Session, note_id: uuid.UUID) -> bool:
    return bool(session.scalar(select(exists().where(CaseNote.supersedes_id == note_id))))


def _correction_target(
    session: Session, user: User | Member, case: Case, supersedes: str, kind: str | None, vis: Visibility
) -> CaseNote:
    try:
        original = resolve_note_ref(session, supersedes)
    except NotVisibleNote as exc:
        raise bad(f"no such note {supersedes!r}") from exc
    if original.case_id != case.id or not visibility.can_view_note(session, user, original):
        raise bad(f"no such note {supersedes!r}")
    if _superseded(session, original.id):
        raise conflict(
            "already_superseded", f"{original.ref_no} is already corrected; correct the latest note"
        )
    if not _may_correct(session, user, original):
        raise forbidden(
            "not_author", "only the author or the department's nodal officer may correct this note"
        )
    if kind and str(kind).strip().lower() != value(original.kind):
        raise bad("a correction keeps the original note's kind")
    if vis != Visibility(original.visibility):
        raise bad("a correction keeps the original note's visibility")
    return original


def _is_holder(custody: Custody | None, member: Member) -> bool:
    return custody is not None and custody.holder_membership_id == member.membership_id


# ------------------------------------------------------------------------------------------------ writing


def add_note(
    session: Session,
    actor: Actor,
    user: User | Member,
    case: Case,
    *,
    kind: str | None,
    body: str | None,
    visibility_: str | None,
    supersedes: str | None = None,
    files: Sequence[tuple[bytes, str]] = (),
    doc_types: Sequence[str | None] = (),
    document_refs: Sequence[str] = (),
    scanner: Scanner | None = None,
    store: LocalStore | None = None,
    max_files: int = 5,
    max_bytes: int = 20 * 1024 * 1024,
    max_chars: int = DEFAULT_NOTE_MAX,
    max_drafts: int = DEFAULT_DRAFTS_MAX,
) -> tuple[CaseNote | CaseNoteDraft, bool]:
    """Decisions 12, 14, 16, 18. Returns (row, is_draft). Order: function → fields → visible (404) → lock →
    claimed (409) → acting membership (403) → holder? → correction → links → files (checked before writing)."""
    require_function(session, user, Permission.NOTES_ADD)
    vis = check_visibility(visibility_)
    text_ = check_body(body, max_chars)
    note_kind = None if supersedes else check_kind(session, kind)
    require_visible_basis(session, user, case)
    lock_case(session, case)
    require_owned(session, case)
    member = acting_member(session, user, case, Permission.NOTES_ADD)
    actor = access.actor_as(actor, member)
    custody = session.get(Custody, case.id)
    draft = _is_holder(custody, member)
    if draft and files:
        raise bad(
            "while the case is with you, notes are drafts and take links only: upload the document to the case first",
            "drafts_take_links_only",
        )
    original = _correction_target(session, user, case, supersedes, kind, vis) if supersedes else None
    if original is not None:
        note_kind = NoteKind(original.kind)
    links = attachments.resolve_links(session, user, case, document_refs, max_links=max_files)
    if draft:
        return _save_draft(
            session, actor, member, case, custody, note_kind, text_, vis, original, links, max_drafts
        ), True
    prepared = attachments.prepare(
        session, actor, case, files, doc_types, scanner=scanner, max_files=max_files, max_bytes=max_bytes
    )
    note = _insert_note(
        session,
        actor,
        member,
        case,
        custody,
        kind=note_kind,
        body=text_,
        vis=vis,
        original=original,
        prepared=prepared,
        links=links,
        store=store,
    )
    return note, False


def _next_seq(session: Session, case: Case) -> int:
    return int(session.scalar(select(func.max(CaseNote.seq_no)).where(CaseNote.case_id == case.id)) or 0) + 1


def _insert_note(
    session: Session,
    actor: Actor,
    member: Member,
    case: Case,
    custody: Custody | None,
    *,
    kind: NoteKind,
    body: str,
    vis: Visibility,
    original: CaseNote | None,
    prepared: Sequence[Prepared],
    links: Sequence[Document],
    store: LocalStore | None,
) -> CaseNote:
    office = member.office
    # a correction keeps the original's audience: it is scoped to the original note's office (what
    # `private_to_office` reads by); the reference number and author snapshot stay the corrector's
    scope_office = session.get(Office, original.office_id) if original is not None else office
    note = CaseNote(
        ref_no=allocate_ref_no(session, office.code, RecordType.NOTE.value),
        case_id=case.id,
        seq_no=_next_seq(session, case),
        kind=kind,
        body=body,
        visibility=vis,
        office_id=scope_office.id,
        author_role=member.role.value,
        custody_leg_id=custody.current_leg_id if custody is not None else None,
        supersedes_id=original.id if original is not None else None,
        source=NoteSource.USER,
        **snapshot(actor),
    )
    try:
        with session.begin_nested():
            session.add(note)
            session.flush()
    except IntegrityError as exc:
        if original is not None:
            raise conflict("already_superseded", f"{original.ref_no} is already corrected") from exc
        raise conflict("concurrent_change", "another note was added at the same time; try again") from exc
    new_docs = attachments.create_all(
        session,
        actor,
        member,
        case,
        prepared,
        visibility=vis,
        description=f"Attachment to {note.ref_no}",
        office=scope_office,
        store=store,
    )
    for doc in [*new_docs, *links]:
        session.add(CaseNoteAttachment(note_id=note.id, document_id=doc.id))
    session.flush()
    payload = _event_payload(note, kind, vis, scope_office, original, finalised=False)
    emit_event(
        session,
        EventType.NOTE_ADDED,
        case,
        payload,
        dedupe=f"note_added:{note.id}",
        scoped=True,
        actor_user_id=actor.user_id,
    )
    write_audit(
        session,
        actor,
        "note.added",
        "case_note",
        note.id,
        case_id=case.id,
        after={
            **{k: v for k, v in payload.items() if k != "note_id"},
            "body": digest(body),
            "attachments": [d.ref_no for d in new_docs],
            "linked": [d.ref_no for d in links],
        },
    )
    return note


def _event_payload(
    note: CaseNote,
    kind: NoteKind,
    vis: Visibility,
    office: Office,
    original: CaseNote | None,
    *,
    finalised: bool,
) -> dict[str, Any]:
    return {
        "note_id": str(note.id),
        "ref_no": note.ref_no,
        "seq_no": note.seq_no,
        "kind": NoteKind(kind).value,
        "visibility": vis.value,
        "office_code": office.code,
        "supersedes_ref_no": original.ref_no if original is not None else None,
        "finalised": finalised,
    }


def _save_draft(
    session: Session,
    actor: Actor,
    member: Member,
    case: Case,
    custody: Custody,
    kind: NoteKind,
    body: str,
    vis: Visibility,
    original: CaseNote | None,
    links: Sequence[Document],
    max_drafts: int,
) -> CaseNoteDraft:
    count = int(
        session.scalar(
            select(func.count(CaseNoteDraft.id)).where(
                CaseNoteDraft.case_id == case.id, CaseNoteDraft.membership_id == member.membership_id
            )
        )
        or 0
    )
    if count >= max_drafts:
        raise conflict(
            "too_many_drafts", f"at most {max_drafts} drafts per case; send the case or delete one"
        )
    draft = CaseNoteDraft(
        case_id=case.id,
        membership_id=member.membership_id,
        author_user_id=member.id,
        custody_leg_id=custody.current_leg_id,
        kind=kind,
        body=body,
        visibility=vis,
        supersedes_id=original.id if original is not None else None,
        **snapshot(actor),
    )
    session.add(draft)
    session.flush()
    for doc in links:
        session.add(CaseNoteDraftDocument(draft_id=draft.id, document_id=doc.id))
    session.flush()
    write_audit(
        session,
        actor,
        "note.draft_saved",
        "case_note_draft",
        draft.id,
        case_id=case.id,
        after=_draft_audit(draft, original, links),
    )
    return draft


def _draft_audit(
    draft: CaseNoteDraft, original: CaseNote | None, links: Sequence[Document]
) -> dict[str, Any]:
    return {
        "kind": value(draft.kind),
        "visibility": value(draft.visibility),
        "body": digest(draft.body),
        "supersedes_ref_no": original.ref_no if original is not None else None,
        "documents": [d.ref_no for d in links],
    }


def _load_own_draft(session: Session, user: User | Member, draft_id: Any) -> CaseNoteDraft:
    try:
        did = draft_id if isinstance(draft_id, uuid.UUID) else uuid.UUID(str(draft_id))
    except ValueError as exc:
        raise DraftNotFound("no such draft") from exc
    draft = session.get(CaseNoteDraft, did)
    if draft is None or draft.author_user_id != user.id:
        raise DraftNotFound("no such draft")
    return draft


def _relock_draft(session: Session, user: User | Member, draft: CaseNoteDraft) -> tuple[Case, Member]:
    """Decision 26: take the case row lock, then re-read the draft (a send may have finalised it meanwhile →
    409 `draft_finalised`) and check that its membership still holds the file and still belongs to the
    caller."""
    case = session.get(Case, draft.case_id)
    draft_id, membership_id = draft.id, draft.membership_id
    lock_case(session, case)
    fresh = session.execute(
        select(CaseNoteDraft).where(CaseNoteDraft.id == draft_id).execution_options(populate_existing=True)
    ).scalar_one_or_none()
    custody = session.execute(
        select(Custody).where(Custody.case_id == case.id).execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if fresh is None or custody is None or custody.holder_membership_id != membership_id:
        raise conflict("draft_finalised", "the case has moved; the draft is now a permanent note")
    member = next((m for m in access.members(session, user) if m.membership_id == membership_id), None)
    if member is None:
        raise conflict("draft_finalised", "the membership that wrote the draft no longer acts")
    return case, member


def update_draft(
    session: Session,
    actor: Actor,
    user: User | Member,
    draft_id: Any,
    *,
    kind: Any = UNSET,
    body: Any = UNSET,
    visibility_: Any = UNSET,
    supersedes: Any = UNSET,
    document_refs: Any = UNSET,
    max_chars: int = DEFAULT_NOTE_MAX,
    max_links: int = 5,
) -> CaseNoteDraft:
    draft = _load_own_draft(session, user, draft_id)
    case, member = _relock_draft(session, user, draft)
    draft = session.get(CaseNoteDraft, draft.id)
    actor = access.actor_as(actor, member)
    before = _draft_audit(
        draft,
        session.get(CaseNote, draft.supersedes_id) if draft.supersedes_id else None,
        _draft_docs(session, draft),
    )
    vis = check_visibility(visibility_) if visibility_ is not UNSET else Visibility(draft.visibility)
    text_ = check_body(body, max_chars) if body is not UNSET else draft.body
    original: CaseNote | None
    if supersedes is not UNSET:
        original = _correction_target(session, user, case, supersedes, None, vis) if supersedes else None
    else:
        original = session.get(CaseNote, draft.supersedes_id) if draft.supersedes_id else None
        if original is not None and vis != Visibility(original.visibility):
            raise bad("a correction keeps the original note's visibility")
    if original is not None:
        if kind is not UNSET and kind and str(kind).strip().lower() != value(original.kind):
            raise bad("a correction keeps the original note's kind")
        new_kind = NoteKind(original.kind)
    else:
        new_kind = check_kind(session, kind) if kind is not UNSET else NoteKind(draft.kind)
    draft.kind, draft.body, draft.visibility = new_kind, text_, vis
    draft.supersedes_id = original.id if original is not None else None
    if document_refs is not UNSET:
        links = attachments.resolve_links(session, user, case, document_refs or [], max_links=max_links)
        session.execute(delete(CaseNoteDraftDocument).where(CaseNoteDraftDocument.draft_id == draft.id))
        for doc in links:
            session.add(CaseNoteDraftDocument(draft_id=draft.id, document_id=doc.id))
    else:
        links = _draft_docs(session, draft)
    for k, v in snapshot(actor).items():
        setattr(draft, k, v)
    session.flush()
    write_audit(
        session,
        actor,
        "note.draft_updated",
        "case_note_draft",
        draft.id,
        case_id=case.id,
        before=before,
        after=_draft_audit(draft, original, links),
    )
    return draft


def delete_draft(session: Session, actor: Actor, user: User | Member, draft_id: Any) -> None:
    """The only delete in a case's records (owner's rule): the author, while their membership holds the case."""
    draft = _load_own_draft(session, user, draft_id)
    case, member = _relock_draft(session, user, draft)
    draft = session.get(CaseNoteDraft, draft.id)
    actor = access.actor_as(actor, member)
    original = session.get(CaseNote, draft.supersedes_id) if draft.supersedes_id else None
    before = _draft_audit(draft, original, _draft_docs(session, draft))
    did = draft.id
    session.execute(delete(CaseNoteDraftDocument).where(CaseNoteDraftDocument.draft_id == did))
    session.delete(draft)
    session.flush()
    write_audit(session, actor, "note.draft_deleted", "case_note_draft", did, case_id=case.id, before=before)


def _draft_docs(session: Session, draft: CaseNoteDraft) -> list[Document]:
    return list(
        session.scalars(
            select(Document)
            .join(CaseNoteDraftDocument, CaseNoteDraftDocument.document_id == Document.id)
            .where(CaseNoteDraftDocument.draft_id == draft.id)
            .order_by(CaseNoteDraftDocument.created_at, Document.ref_no)
        ).all()
    )


def _latest_of_chain(session: Session, note_id: uuid.UUID) -> CaseNote:
    current = session.get(CaseNote, note_id)
    while True:
        nxt = session.scalar(select(CaseNote).where(CaseNote.supersedes_id == current.id))
        if nxt is None:
            return current
        current = nxt


def finalise_drafts(session: Session, actor: Actor, case: Case, membership_id: uuid.UUID) -> list[str]:
    """Decision 13: every draft of `membership_id` on the case, oldest first, becomes a permanent note; the draft
    and its links are deleted. The caller (`move_custody`) holds the case row lock; a failure fails the move.
    Returns the new notes' `ref_no`."""
    drafts = list(
        session.scalars(
            select(CaseNoteDraft)
            .where(CaseNoteDraft.case_id == case.id, CaseNoteDraft.membership_id == membership_id)
            .order_by(CaseNoteDraft.created_at, CaseNoteDraft.id)
        ).all()
    )
    if not drafts:
        return []
    membership = session.get(UserMembership, membership_id)
    office = session.get(Office, membership.office_id)
    refs: list[str] = []
    for d in drafts:
        original = None
        retargeted = False
        if d.supersedes_id is not None:
            original = _latest_of_chain(session, d.supersedes_id)
            retargeted = original.id != d.supersedes_id
        scope_office = session.get(Office, original.office_id) if original is not None else office
        note = CaseNote(
            ref_no=allocate_ref_no(session, office.code, RecordType.NOTE.value),
            case_id=case.id,
            seq_no=_next_seq(session, case),
            kind=NoteKind(d.kind),
            body=d.body,
            visibility=Visibility(d.visibility),
            office_id=scope_office.id,
            author_role=value(membership.role),
            custody_leg_id=d.custody_leg_id,
            supersedes_id=original.id if original is not None else None,
            source=NoteSource.USER,
            drafted_at=d.created_at,
            actor_user_id=d.author_user_id,
            actor_name=d.actor_name,
            actor_designation=d.actor_designation,
            actor_office_code=d.actor_office_code,
        )
        session.add(note)
        session.flush()
        docs = _draft_docs(session, d)
        for doc in docs:
            session.add(CaseNoteAttachment(note_id=note.id, document_id=doc.id))
        session.execute(delete(CaseNoteDraftDocument).where(CaseNoteDraftDocument.draft_id == d.id))
        draft_id = d.id
        session.delete(d)
        session.flush()
        payload = _event_payload(
            note, NoteKind(note.kind), Visibility(note.visibility), scope_office, original, finalised=True
        )
        emit_event(
            session,
            EventType.NOTE_ADDED,
            case,
            payload,
            dedupe=f"note_added:{note.id}",
            scoped=True,
            actor_user_id=d.author_user_id,
        )
        write_audit(
            session,
            actor,
            "note.finalised",
            "case_note",
            note.id,
            case_id=case.id,
            after={
                **{k: v for k, v in payload.items() if k != "note_id"},
                "draft_id": str(draft_id),
                "author_user_id": str(d.author_user_id),
                "membership_id": str(membership_id),
                "body": digest(note.body),
                "linked": [doc.ref_no for doc in docs],
                "supersedes_retargeted": retargeted,
            },
        )
        refs.append(note.ref_no)
    return refs


# ------------------------------------------------------------------------------------------------ reading


def _kind_labels(session: Session) -> dict[str, str]:
    return {r.code: r.label for r in session.scalars(select(RefNoteKind)).all()}


def may_write(session: Session, user: User | Member, case: Case) -> bool:
    """Design portal-workflow, decision 20b: the caller may write a note on the case (claimed, and a membership
    with a working basis holds `notes.add`) — the checks of `add_note`, without locking or writing."""
    return (
        primary_owner(session, case) is not None
        and visibility.acting_member_for_case(session, user, case, Permission.NOTES_ADD) is not None
    )


def note_out(
    session: Session,
    user: User | Member,
    note: CaseNote,
    *,
    labels: dict[str, str] | None = None,
    writer: bool | None = None,
) -> dict[str, Any]:
    """`writer`: whether the caller may write a note on the note's case (`may_write`), computed once per list;
    `can_correct` adds the note's own rules (not superseded, `_may_correct`)."""
    labels = labels if labels is not None else _kind_labels(session)
    sup = session.get(CaseNote, note.supersedes_id) if note.supersedes_id else None
    by = session.scalar(
        select(CaseNote).where(CaseNote.supersedes_id == note.id, note_visible_condition(session, user))
    )
    if writer is None:
        writer = may_write(session, user, session.get(Case, note.case_id))
    can_correct = bool(writer) and not _superseded(session, note.id) and _may_correct(session, user, note)
    leg = session.get(CustodyHistory, note.custody_leg_id) if note.custody_leg_id else None
    docs = session.scalars(
        select(Document)
        .join(CaseNoteAttachment, CaseNoteAttachment.document_id == Document.id)
        .where(CaseNoteAttachment.note_id == note.id, document_visible_condition(session, user))
        .order_by(CaseNoteAttachment.created_at, Document.ref_no)
    ).all()
    own_desc = f"Attachment to {note.ref_no}"
    return {
        "id": note.id,
        "ref_no": note.ref_no,
        "seq_no": note.seq_no,
        "kind": value(note.kind),
        "kind_label": labels.get(value(note.kind), value(note.kind)),
        "body": note.body,
        "visibility": value(note.visibility),
        "author": {
            "name": note.actor_name,
            "designation": note.actor_designation,
            "office_code": note.actor_office_code,
            "role": note.author_role,
        },
        "created_at": note.created_at,
        "drafted_at": note.drafted_at,
        "custody_leg_seq_no": leg.seq_no if leg else None,
        "supersedes": {"ref_no": sup.ref_no, "seq_no": sup.seq_no} if sup else None,
        "superseded_by": {"ref_no": by.ref_no, "seq_no": by.seq_no} if by else None,
        "attachments": [
            {
                "id": d.id,
                "ref_no": d.ref_no,
                "original_filename": d.original_filename,
                "doc_type": value(d.doc_type),
                "mime": d.mime,
                "size_bytes": d.size_bytes,
                "linked": not (DocKind(d.kind) == DocKind.ATTACHMENT and d.description == own_desc),
            }
            for d in docs
        ],
        "can_correct": can_correct,
        "draft": False,
    }


def draft_out(session: Session, draft: CaseNoteDraft) -> dict[str, Any]:
    sup = session.get(CaseNote, draft.supersedes_id) if draft.supersedes_id else None
    return {
        "id": draft.id,
        "kind": value(draft.kind),
        "body": draft.body,
        "visibility": value(draft.visibility),
        "supersedes": {"ref_no": sup.ref_no, "seq_no": sup.seq_no} if sup else None,
        "documents": [
            {
                "id": d.id,
                "ref_no": d.ref_no,
                "original_filename": d.original_filename,
                "doc_type": value(d.doc_type),
                "mime": d.mime,
            }
            for d in _draft_docs(session, draft)
        ],
        "created_at": draft.created_at,
        "updated_at": draft.updated_at,
        "draft": True,
    }


def _list_stmt(
    session: Session, user: User | Member, case: Case, *, kind: str | None, include_superseded: bool
) -> Select:
    stmt = select(CaseNote).where(CaseNote.case_id == case.id, note_visible_condition(session, user))
    if kind:
        try:
            stmt = stmt.where(CaseNote.kind == NoteKind(kind.strip().lower()))
        except ValueError as exc:
            raise bad(f"unknown note kind {kind!r}") from exc
    if not include_superseded:
        later = aliased(CaseNote)
        stmt = stmt.where(
            ~exists(select(literal(1)).select_from(later).where(later.supersedes_id == CaseNote.id))
        )
    return stmt


def list_for_case(
    session: Session,
    user: User | Member,
    case: Case,
    *,
    kind: str | None = None,
    include_superseded: bool = True,
    limit: int | None = None,
    offset: int | None = None,
) -> inbox.Page:
    visibility.require_visible(session, user, case)
    stmt = _list_stmt(session, user, case, kind=kind, include_superseded=include_superseded)
    limit = 50 if limit is None else max(1, min(int(limit), 200))
    offset = max(0, int(offset or 0))
    total = int(session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0)
    rows = session.scalars(stmt.order_by(CaseNote.seq_no).limit(limit).offset(offset)).all()
    labels = _kind_labels(session)
    writer = may_write(session, user, case)
    return inbox.Page([note_out(session, user, n, labels=labels, writer=writer) for n in rows], total)


def list_drafts(session: Session, user: User | Member, case: Case) -> list[dict[str, Any]]:
    """The caller's own drafts on the case (any of their memberships), oldest first."""
    visibility.require_visible(session, user, case)
    rows = session.scalars(
        select(CaseNoteDraft)
        .where(CaseNoteDraft.case_id == case.id, CaseNoteDraft.author_user_id == user.id)
        .order_by(CaseNoteDraft.created_at, CaseNoteDraft.id)
    ).all()
    return [draft_out(session, d) for d in rows]


def my_draft_count(session: Session, user: User | Member, case: Case) -> int:
    return int(
        session.scalar(
            select(func.count(CaseNoteDraft.id)).where(
                CaseNoteDraft.case_id == case.id, CaseNoteDraft.author_user_id == user.id
            )
        )
        or 0
    )


def get(session: Session, user: User | Member, ref: str) -> CaseNote:
    note = resolve_note_ref(session, ref)
    if not visibility.can_view_note(session, user, note):
        raise NotVisibleNote("no such note")
    return note


def visible_count(session: Session, user: User | Member, case: Case) -> int:
    stmt = select(CaseNote.id).where(and_(CaseNote.case_id == case.id, note_visible_condition(session, user)))
    return int(session.scalar(select(func.count()).select_from(stmt.subquery())) or 0)


def kinds(session: Session) -> list[dict[str, Any]]:
    """Note kinds with `selectable` (the retired `correction` is listed, not selectable)."""
    rows = session.scalars(select(RefNoteKind).order_by(RefNoteKind.sort_order)).all()
    return [
        {
            "code": r.code,
            "label": r.label,
            "selectable": bool(r.is_active) and NoteKind(r.code) not in RETIRED_KINDS,
        }
        for r in rows
    ]
