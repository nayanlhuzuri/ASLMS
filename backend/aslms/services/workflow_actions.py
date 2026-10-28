"""What the caller may do on a case's workflow (design `portal-workflow`, decisions 4 and 20a): the `workflow`
block of `GET /cases/{ref}`. Computed by the same checks the writes run, so the portal never decides from `/me`
functions alone whether the caller holds the file, works on the case or may set the stage:

- `note_mode`: `None` unless the case has an active primary owner and the caller has a membership with a working
  basis that holds `notes.add` (`visibility.acting_member_for_case`); `"draft"` when that membership holds the
  file (`custody.holder_membership_id`), else `"permanent"` — the choice `notes.add_note` makes.
- `upload`: a membership with a working basis holding `documents.upload` (the rule of `documents.upload`).
- `set_stage`: the case is owned and a membership with a working basis holds `stages.set`.
- `next_dates`: the case is owned and a membership with a working basis holds `next_dates.review` — the rule
  `next_dates._check_write` runs before every confirm, reject and enter (design `portal-next-dates`, decision 3) —
  and the court has given no next date; `next_dates_blocked` is `court_date_fixed` when it has (design
  `next-date-direct`, decision 6, recomputed for the case as the writes do).
- `next_date_report` / `next_date_correct` (next-date-direct, decision 19): the caller holds
  `next_dates.report_wrong` / `next_dates.correct`, may see the case, and the latest order's reading can be reported.

Reading only: no lock, no write, no audit row."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from aslms.domain.cases import Case
from aslms.domain.org import User
from aslms.domain.reference import Permission
from aslms.domain.workflow import Custody
from aslms.services.access import Member
from aslms.services.visibility import acting_member_for_case
from aslms.services.workflow_common import primary_owner


def available(session: Session, user: User | Member, case: Case) -> dict[str, Any]:
    owned = primary_owner(session, case) is not None
    note_mode: str | None = None
    if owned:
        member = acting_member_for_case(session, user, case, Permission.NOTES_ADD)
        if member is not None:
            custody = session.get(Custody, case.id)
            holds = custody is not None and custody.holder_membership_id == member.membership_id
            note_mode = "draft" if holds else "permanent"
    upload = acting_member_for_case(session, user, case, Permission.DOCUMENTS_UPLOAD) is not None
    set_stage = owned and acting_member_for_case(session, user, case, Permission.STAGES_SET) is not None
    from aslms.services import access, next_hearing
    from aslms.services import next_dates as nd

    may_enter = (
        owned and acting_member_for_case(session, user, case, Permission.NEXT_DATES_REVIEW) is not None
    )
    fixed = next_hearing.court_given(session, case)
    reportable = None
    report = access.has(session, user, Permission.NEXT_DATES_REPORT_WRONG)
    correct = access.has(session, user, Permission.NEXT_DATES_CORRECT)
    if report or correct:
        reportable = nd.reportable_row(session, case)
    return {
        "note_mode": note_mode,
        "upload": upload,
        "set_stage": set_stage,
        "next_dates": may_enter and not fixed,
        "next_dates_blocked": "court_date_fixed" if fixed else None,
        "next_date_report": bool(report and reportable is not None),
        "next_date_correct": bool(correct and reportable is not None),
    }
