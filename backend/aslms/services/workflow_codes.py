"""The codes the workflow screens need, in one read (design `custody-workflow`, `GET /workflow/codes`): note
kinds with `selectable`, pending actions with their labels (`domain/workflow.py::PENDING_ACTION_LABELS`), stages
with phase, response modes and custody reasons."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from aslms.domain.workflow import (
    CUSTODY_REASON_LABELS,
    CUSTODY_REASONS,
    PENDING_ACTION_LABELS,
    PendingAction,
    ResponseMode,
)
from aslms.services import notes, stages
from aslms.services.workflow_common import RESPONSE_MODE_LABELS


def codes(session: Session) -> dict[str, Any]:
    return {
        "note_kinds": notes.kinds(session),
        "pending_actions": [
            {"code": a.value, "label": PENDING_ACTION_LABELS[a], "sendable": a != PendingAction.NONE}
            for a in PendingAction
        ],
        "stages": [
            {"code": s.code, "label": s.label, "phase": s.phase, "sort_order": s.sort_order}
            for s in stages.catalogue(session)
        ],
        "response_modes": [{"code": m.value, "label": RESPONSE_MODE_LABELS[m]} for m in ResponseMode],
        "custody_reasons": [{"code": r, "label": CUSTODY_REASON_LABELS[r]} for r in CUSTODY_REASONS],
    }
