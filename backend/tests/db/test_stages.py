"""Case stages (design custody-workflow, decision 19): any stage set by a `stages.set` holder with a working basis
on a claimed case; the response mode carried over; the same stage and mode again → 409; history and gaps; the
personal holder from another department may set a stage; refusals."""

from __future__ import annotations

import pytest

from aslms.domain.reference import EventType
from aslms.services import stages
from aslms.services.workflow_common import WorkflowError
from tests.db import workflow_support as w
from tests.db.world import make_case


@pytest.fixture()
def wide(world):
    return w.widen(world)


def _set(s, world, key, case, stage, **kw):
    actor, user = world.actor(s, key)
    return stages.set_stage(s, actor, user, case, stage=stage, **kw)


def test_set_history_and_gaps(wide):
    with wide.Session() as s:
        case = w.claimed_case(s, wide)
        row = _set(
            s, wide, "edu_off1", case, "notice_received", response_mode="counsel", note="served on 3 Oct"
        )
        assert row.office_id == wide.offices["EDU"].id
        row2 = _set(s, wide, "edu_admin", case, "affidavit_drafted")
        mode = row2.response_mode.value if hasattr(row2.response_mode, "value") else row2.response_mode
        assert mode == "counsel"  # carried over
        with pytest.raises(WorkflowError) as e:
            _set(s, wide, "edu_admin", case, "affidavit_drafted")
        assert e.value.code == "unchanged" and e.value.http_status == 409
        _, admin = wide.actor(s, "edu_admin")
        out = stages.history_with_gaps(s, admin, case)
        assert out["gaps"] == []  # the current stage is a counsel-phase one
        _set(s, wide, "edu_admin", case, "hearing_pending")
        out = stages.history_with_gaps(s, admin, case)
        assert out["current"]["stage"] == "hearing_pending"
        assert [h["stage"] for h in out["history"]] == [
            "hearing_pending",
            "affidavit_drafted",
            "notice_received",
        ]
        assert out["gaps"] == ["parawise_comments_sought", "parawise_comments_received", "affidavit_filed"]
        assert len(w.events(s, case.id, EventType.STAGE_SET)) == 3
        audit = w.audits(s, "stage.set", case.id)
        assert len(audit) == 3 and "served on 3 Oct" not in str(audit[0].after)
        s.rollback()


def test_holder_from_another_department_sets_a_stage(wide):
    with wide.Session() as s:
        case = w.claimed_case(s, wide)
        w.send(s, wide, "edu_off1", case, "health_off")
        row = _set(s, wide, "health_off", case, "parawise_comments_received")
        assert row.office_id == wide.offices["HEALTH"].id
        s.rollback()


def test_refusals(wide):
    with wide.Session() as s:
        pool = make_case(s)
        with pytest.raises(WorkflowError) as e:
            _set(s, wide, "root", pool, "notice_received")
        assert e.value.code == "not_owned"
        case = w.claimed_case(s, wide)
        with pytest.raises(WorkflowError):
            _set(s, wide, "edu_admin", case, "no_such_stage")
        with pytest.raises(WorkflowError):
            _set(s, wide, "edu_admin", case, "notice_received", note="x" * 2001)
        # a reader without stages.set
        with pytest.raises(WorkflowError) as e:
            _set(s, wide, "oversight", case, "notice_received")
        assert e.value.http_status == 403
        s.rollback()
