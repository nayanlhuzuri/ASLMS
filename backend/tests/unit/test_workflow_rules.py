"""Pure rules of custody-workflow: the reasons equal the CHECK (model and migration), every pending action has a
label, stage gaps, note-kind selectability, retired functions out of the active set, text and date checks."""

from __future__ import annotations

import importlib.util
from datetime import date, timedelta
from pathlib import Path

import pytest

from aslms.domain.reference import (
    RETIRED_CODES,
    RETIRED_PERMISSIONS,
    AlertKind,
    NoteKind,
    Permission,
)
from aslms.domain.workflow import (
    CUSTODY_REASON_LABELS,
    CUSTODY_REASONS,
    PENDING_ACTION_LABELS,
    REMARK_REASONS,
    CustodyHistory,
    PendingAction,
)
from aslms.services import access, alert_rules
from aslms.services import custody as custody_svc
from aslms.services.stages import StageInfo, compute_gaps
from aslms.services.workflow_common import WorkflowError, check_due, clean_text, digest, pending_action

MIGRATION = Path(__file__).resolve().parents[2] / "migrations" / "versions" / "0009_workflow.py"


def _migration():
    spec = importlib.util.spec_from_file_location("m0009", MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _check(name: str) -> str:
    for c in CustodyHistory.__table__.constraints:
        if getattr(c, "name", None) and str(c.name).endswith(name):
            return str(c.sqltext)
    raise AssertionError(name)


def test_reasons_equal_the_check_list():
    assert "reassigned_on_exit" in CUSTODY_REASONS
    assert set(custody_svc.REASONS) == set(CUSTODY_REASONS)
    reason_sql = _check("reason")
    for r in CUSTODY_REASONS:
        assert f"'{r}'" in reason_sql
    m = _migration()
    assert tuple(m.REASONS) == tuple(CUSTODY_REASONS)
    assert tuple(m.REMARK_REASONS) == tuple(REMARK_REASONS)
    assert set(CUSTODY_REASON_LABELS) == set(CUSTODY_REASONS)
    remark_sql = _check("remark")
    assert all(f"'{r}'" in remark_sql for r in REMARK_REASONS)


def test_pending_action_labels_cover_every_member():
    assert set(PENDING_ACTION_LABELS) == set(PendingAction)
    assert all(PENDING_ACTION_LABELS[a] for a in PendingAction)
    assert set(_migration().NEW_PENDING_ACTIONS) == {
        "parawise_comments",
        "report",
        "documents",
        "opinion",
        "instructions",
        "clarification",
        "other",
    }


def test_stage_gaps():
    cat = [
        StageInfo("a", "A", "main", 1),
        StageInfo("b", "B", "main", 2),
        StageInfo("c", "C", "main", 3),
        StageInfo("x", "X", "appeal", 4),
    ]
    assert compute_gaps(cat, {"c"}, "c") == ["a", "b"]
    assert compute_gaps(cat, {"a", "c"}, "c") == ["b"]
    assert compute_gaps(cat, {"x"}, "x") == []  # current not a main stage
    assert compute_gaps(cat, set(), None) == []


def test_note_kinds_and_retired_codes():
    assert NoteKind.OPINION.value == "opinion" and NoteKind.HAND_OVER.value == "hand_over"
    assert NoteKind.CORRECTION.value in RETIRED_CODES["ref_note_kind"]
    assert NoteKind.HAND_OVER.value not in RETIRED_CODES["ref_note_kind"]
    assert AlertKind.REQUEST_DUE.value in RETIRED_CODES["ref_alert_kind"]
    assert AlertKind.WORKFLOW.value not in RETIRED_CODES["ref_alert_kind"]


def test_retired_functions_excluded_from_the_active_set():
    assert RETIRED_PERMISSIONS == {Permission.REQUESTS_SEND, Permission.REQUESTS_ANSWER}
    assert not (access.ACTIVE_FUNCTIONS & RETIRED_PERMISSIONS)
    assert {Permission.CUSTODY_RECALL, Permission.CUSTODY_TRACK} <= access.ACTIVE_FUNCTIONS
    assert len(Permission) == 51 and len(access.ACTIVE_FUNCTIONS) == 49


def test_send_field_checks():
    today = date(2026, 10, 7)
    assert check_due(None, today=today) is None
    assert check_due(today, today=today) == today
    assert check_due(today + timedelta(days=365), today=today)
    for bad_due in (today - timedelta(days=1), today + timedelta(days=366)):
        with pytest.raises(WorkflowError) as e:
            check_due(bad_due, today=today)
        assert e.value.code == "bad_due_date" and e.value.http_status == 400
    with pytest.raises(WorkflowError):
        pending_action("none")
    with pytest.raises(WorkflowError):
        pending_action("nonsense")
    assert pending_action("Parawise_Comments") == PendingAction.PARAWISE_COMMENTS
    with pytest.raises(WorkflowError):
        clean_text("ab", "remark", min_len=3, max_len=2000)
    with pytest.raises(WorkflowError):
        clean_text("x" * 2001, "remark", min_len=3, max_len=2000)
    assert clean_text("  ok then ", "remark", min_len=3, max_len=2000) == "ok then"


def test_digest_never_carries_the_text():
    d = digest("a secret remark")
    assert d["length"] == 15 and len(d["sha256"]) == 64 and "secret" not in str(d)


def test_custody_due_severity():
    today = date(2026, 10, 7)
    f = alert_rules.severity_for_custody_due
    assert f(today + timedelta(days=3), today, 2) is None
    assert f(today + timedelta(days=2), today, 2).value == "high"
    assert f(today, today, 2).value == "high"
    assert f(today - timedelta(days=1), today, 2).value == "critical"
