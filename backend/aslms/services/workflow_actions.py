"""What the caller may do on a case's workflow (design `portal-workflow`, decisions 4 and 20a): the `workflow`
block of `GET /cases/{ref}`. Computed by the same checks the writes run, so the portal never decides from `/me`
functions alone whether the caller holds the file, works on the case or may set the stage:

- `note_mode`: `None` unless the case has an active primary owner and the caller has a membership with a working
  basis that holds `notes.add` (`visibility.acting_member_for_case`); `"draft"` when that membership holds the
  file (`custody.holder_membership_id`), else `"permanent"` — the choice `notes.add_note` makes.
- `upload`: a membership with a working basis holding `documents.upload` (the rule of `documents.upload`).
- `set_stage`: the case is owned and a membership with a working basis holds `stages.set`.

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
    return {"note_mode": note_mode, "upload": upload, "set_stage": set_stage}
