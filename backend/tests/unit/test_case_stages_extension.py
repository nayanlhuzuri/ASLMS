"""Design `case-stages-extension`: seven stages appended to `Stage` after `closed`, the seed's phase and label for
each (the same rows as migration 0016), and the new appeal / contempt stages never counted as gaps."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from aslms.domain.reference import RefCaseStage, Stage
from aslms.services.seed import _extra_columns, _label
from aslms.services.stages import StageInfo, compute_gaps

MIGRATION = Path(__file__).resolve().parents[2] / "migrations" / "versions" / "0016_case_stages.py"

# design decision 1: (code, label, phase, sort_order)
EXPECTED = [
    ("review_petition_filed", "Review petition filed", "appeal", 180),
    ("appeal_dismissed", "Appeal or review dismissed", "appeal", 190),
    ("appeal_allowed", "Appeal or review allowed", "appeal", 200),
    ("further_appeal_filed", "Further appeal filed (higher court)", "appeal", 210),
    ("complied_after_dismissal", "Complied after dismissal of appeal or review", "appeal", 220),
    ("vakalatnama_submitted", "Vakalatnama submitted", "contempt", 230),
    ("contempt_disposed", "Contempt disposed", "contempt", 240),
]
# the 17 stages before the extension and their seed output (phase only; the label is generated)
BEFORE = {
    "notice_received": "main",
    "parawise_comments_sought": "main",
    "parawise_comments_received": "main",
    "counsel_briefed": "counsel",
    "affidavit_drafted": "counsel",
    "affidavit_vetted": "counsel",
    "affidavit_filed": "main",
    "hearing_pending": "main",
    "order_received": "main",
    "order_under_examination": "main",
    "compliance_in_progress": "main",
    "compliance_reported": "main",
    "appeal_under_consideration": "appeal",
    "appeal_filed": "appeal",
    "contempt_notice": "contempt",
    "contempt_reply_filed": "contempt",
    "closed": "main",
}


def _seed_row(order: int, member: Stage) -> tuple[str, str, str, int]:
    """What `seed_ref_tables` inserts for a missing stage."""
    cols = {"code": member.value, "label": _label(member.value), "sort_order": order * 10}
    cols.update(_extra_columns(RefCaseStage, member))
    return cols["code"], cols["label"], cols["phase"], cols["sort_order"]


def _migration():
    spec = importlib.util.spec_from_file_location("m0016", MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_stage_enum_appends_seven_codes_after_closed():
    members = list(Stage)
    assert len(members) == 24
    assert [m.value for m in members[:17]] == list(BEFORE)
    assert members[16] is Stage.CLOSED
    assert [m.value for m in members[17:]] == [code for code, _, _, _ in EXPECTED]
    assert all(len(m.value) <= 40 for m in members)


def test_seed_phase_and_labels_for_new_stages():
    rows = [_seed_row(order, m) for order, m in enumerate(Stage, start=1)]
    assert rows[17:] == EXPECTED
    for i, (code, label, phase, sort_order) in enumerate(rows[:17], start=1):
        assert sort_order == i * 10  # not renumbered
        assert phase == BEFORE[code]
        assert label == _label(code)  # unchanged: generated from the code
        assert _extra_columns(RefCaseStage, Stage(code)) == {"phase": BEFORE[code]}
    assert rows[16] == ("closed", "Closed", "main", 170)


def test_migration_rows_equal_the_seed():
    mod = _migration()
    assert mod.revision == "0016" and mod.down_revision == "0015"
    assert list(mod.NEW_STAGES) == EXPECTED
    rows = [_seed_row(order, m) for order, m in enumerate(Stage, start=1)]
    assert list(mod.NEW_STAGES) == rows[17:]


def test_new_stages_never_count_as_gaps():
    cat = [
        StageInfo(m.value, _label(m.value), BEFORE[m.value], (i + 1) * 10)
        for i, m in enumerate(list(Stage)[:17])
    ]
    cat += [StageInfo(code, label, phase, order) for code, label, phase, order in EXPECTED]
    new_codes = {code for code, _, _, _ in EXPECTED}
    for code in new_codes:
        assert compute_gaps(cat, set(), code) == []
        assert compute_gaps(cat, {"notice_received"}, code) == []
    for current in ("hearing_pending", "closed"):
        gaps = compute_gaps(cat, set(), current)
        assert gaps and not (set(gaps) & new_codes)
        assert all(BEFORE[g] == "main" for g in gaps)
