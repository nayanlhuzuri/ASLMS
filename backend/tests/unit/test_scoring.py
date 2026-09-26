from __future__ import annotations

import uuid

import pytest

from aslms.services.scoring import (
    CaseFacts,
    CodeRule,
    KeywordRule,
    MatchConfig,
    OfficeRef,
    PatternRule,
    band_for,
    score_case,
)

EDU = OfficeRef(uuid.UUID(int=1), "EDU", uuid.UUID(int=1))
DSE = OfficeRef(uuid.uuid4(), "DSE", EDU.id)
HEALTH = OfficeRef(uuid.UUID(int=2), "HEALTH", uuid.UUID(int=2))
HOME = OfficeRef(uuid.UUID(int=3), "HOME", uuid.UUID(int=3))


def cfg() -> MatchConfig:
    return MatchConfig(
        codes={
            "SC, SEC. EDU.": CodeRule("SC, SEC. EDU.", EDU, 0.95),
            "SC, HEALTH": CodeRule("SC, HEALTH", HEALTH, 0.95),
            "PP, ASSAM": CodeRule("PP, ASSAM", HOME, 0.95, is_generic_state=True),
        },
        patterns=[PatternRule("DIRECTOR OF SECONDARY EDUCATION", "exact", DSE, 0.80)],
        keywords=[KeywordRule("HEALTH SERVICES", HEALTH, 0.40)],
        watchlist={"GAHC010000012024": [(HEALTH, 0.75)]},
    )


def test_counsel_code_is_the_strongest_signal() -> None:
    res = score_case(CaseFacts("GAHC010000022024", ("SC, SEC. EDU.",), ("RAM vs THE STATE OF ASSAM",)), cfg())
    assert [(r.department_id, r.score) for r in res] == [(EDU.id, 0.95)]
    assert band_for(res[0].score, 0.85, 0.50) == "high"


def test_signals_combine_by_noisy_or_and_roll_up_to_the_department() -> None:
    facts = CaseFacts(None, ("SC, SEC. EDU.",), ("THE DIRECTOR OF SECONDARY EDUCATION, ASSAM",))
    res = score_case(facts, cfg())
    assert len(res) == 1 and res[0].department_id == EDU.id
    assert res[0].score == pytest.approx(1 - 0.05 * 0.20, abs=1e-3)
    assert res[0].suggested_unit_id == DSE.id  # the directorate that matched is suggested as the unit
    assert {s.kind for s in res[0].signals} == {"counsel_code", "name_pattern"}


def test_generic_state_codes_add_nothing() -> None:
    assert score_case(CaseFacts(None, ("PP, ASSAM",), ()), cfg()) == []


def test_keyword_alone_is_below_possible_threshold() -> None:
    res = score_case(CaseFacts(None, (), ("DIRECTOR OF HEALTH SERVICES",)), cfg())
    assert res[0].department_id == HEALTH.id and res[0].score == 0.40
    assert band_for(0.40, 0.85, 0.50) is None


def test_watchlist_and_link_history() -> None:
    res = score_case(CaseFacts("GAHC010000012024", (), (), linked_owner_departments=(EDU.id,)), cfg())
    by = {r.department_id: r for r in res}
    assert by[HEALTH.id].score == 0.75 and by[EDU.id].score == 0.70
    assert band_for(0.70, 0.85, 0.50) == "medium"


def test_same_code_twice_counts_once_and_multiple_departments_rank() -> None:
    res = score_case(
        CaseFacts(None, ("SC, SEC. EDU.", "SC, SEC. EDU.", "SC, HEALTH"), ("HEALTH SERVICES",)), cfg()
    )
    assert res[0].department_id == HEALTH.id  # 0.95 ⊕ 0.40 beats 0.95
    assert res[1].score == 0.95
