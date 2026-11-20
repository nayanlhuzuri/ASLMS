"""The cause-title signal without a database (design `state-insights`, round 3, decisions 36 to 40): one
`named_in_title` signal per active department of the fact row, its phrase, source and reason, the global weight inside
the possible band, the combinations of decision 37, the departments left out, the settings band rule and the dry run's
"without the signal" band."""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from aslms.domain.ownership import ScoreBand
from aslms.services import scoring_settings as ss
from aslms.services.insights_facts import Maps
from aslms.services.matching import (
    CaseEvidence,
    RuleSet,
    ScoredOffice,
    _band_without_named,
    band_of,
    combine,
    named_reason,
    score_case,
)
from tests.unit.test_matching_rules import EDU, HEALTH, rule, ruleset

FIN = uuid.uuid4()
ORDER = uuid.uuid4()


def maps() -> Maps:
    return Maps(explicit={"SECONDARY EDUCATION": EDU, "PWD": FIN}, cores={"EDUCATION": EDU, "HEALTH": HEALTH})


def rules(*extra, settings=ss.DEFAULTS) -> RuleSet:
    rs = ruleset(*extra, settings=settings)
    rs.departments[FIN] = "FIN"
    rs.title_maps = maps()
    return rs


def evidence(
    departments, phrases, *, order=ORDER, day=date(2026, 10, 12), respondents=(), **kw
) -> CaseEvidence:
    return CaseEvidence(
        title_department_ids=list(departments),
        title_phrases=list(phrases),
        title_order_id=order,
        title_order_date=day if order else None,
        respondent_phrases=frozenset(respondents),
        **kw,
    )


def named(out, dept):
    return [s for s in out[dept].signals if s["kind"] == "named_in_title"]


def test_alone_a_possible_match_with_the_cause_title_reason():
    out = score_case(rules(), evidence([EDU], ["EDUCATION"]))
    assert out[EDU].score == 0.6 and band_of(0.6, ss.DEFAULTS) == ScoreBand.MEDIUM
    (sig,) = named(out, EDU)
    assert sig == {
        "kind": "named_in_title",
        "rule_id": None,
        "rule_office_code": "EDU",
        "weight": 0.6,
        "matched": "EDUCATION",
        "phrase": "EDUCATION",
        "source": "cause_title",
        "order_date": "2026-10-12",
        "where": "insight_case_facts",
        "ref": {"order_id": str(ORDER), "order_date": "2026-10-12"},
        "reason": "Department named in the cause title of the order of 12 Oct 2026: EDUCATION",
    }
    assert [s["kind"] for s in out[EDU].signals] == ["named_in_title"]  # no suggested unit from this signal


def test_a_phrase_among_the_respondents_reads_as_party():
    out = score_case(rules(), evidence([EDU], ["EDUCATION"], respondents=["EDUCATION"]))
    (sig,) = named(out, EDU)
    assert sig["source"] == "party" and "order_date" not in sig and sig["ref"] == {"role": "respondent"}
    assert sig["reason"] == "Department named among the respondents: EDUCATION"
    # no titled order: the phrase came from the party names
    (sig,) = named(score_case(rules(), evidence([EDU], ["EDUCATION"], order=None)), EDU)
    assert sig["source"] == "party"


def test_explicit_mapping_phrase_and_each_department_once():
    out = score_case(
        rules(), evidence([FIN, EDU], ["PWD", "SECONDARY EDUCATION", "EDUCATION"], respondents=["PWD"])
    )
    assert named(out, FIN)[0]["phrase"] == "PWD" and named(out, FIN)[0]["source"] == "party"
    (edu,) = named(out, EDU)
    assert edu["phrase"] == "SECONDARY EDUCATION" and edu["source"] == "cause_title"


@pytest.mark.parametrize(
    ("extra", "evidence_kw", "score", "band"),
    [
        ((), {}, 0.6, ScoreBand.MEDIUM),
        (
            (rule("keyword", "EDUCATION"),),
            {"names": [("EDUCATION", "case_summary", {})]},
            0.76,
            ScoreBand.MEDIUM,
        ),
        (
            (rule("counsel_code", "SC, EDU"),),
            {"entry_codes": [("SC, EDU, DSE", {"list_date": "2026-10-12", "sr_no": 1})]},
            0.84,
            ScoreBand.MEDIUM,
        ),
        (
            (rule("name_pattern", "DIRECTOR OF SECONDARY EDUCATION", pattern_kind="exact"),),
            {"names": [("DIRECTOR OF SECONDARY EDUCATION", "case_parties", {})]},
            0.92,
            ScoreBand.HIGH,
        ),
        (
            (rule("counsel_code", "SC, EDU"),),
            {"entry_codes": [("SC, EDU", {"list_date": "2026-10-12", "sr_no": 1})]},
            0.98,
            ScoreBand.HIGH,
        ),
    ],
)
def test_combinations_of_decision_37(extra, evidence_kw, score, band):
    out = score_case(rules(*extra), evidence([EDU], ["EDUCATION"], **evidence_kw))
    assert out[EDU].score == score and band_of(score, ss.DEFAULTS) == band
    assert combine({"named_in_title": 0.6}) == 0.6


def test_departments_left_out():
    rs = rules()
    # not an active Department-tier office of the rule set
    assert score_case(rs, evidence([uuid.uuid4()], ["EDUCATION"])) == {}
    # no stored phrase names it under the current maps any longer
    assert score_case(rs, evidence([HEALTH], ["EDUCATION"])).get(HEALTH) is None
    # no maps loaded: no signal
    rs.title_maps = None
    assert score_case(rs, evidence([EDU], ["EDUCATION"])) == {}
    # no departments on the fact row
    assert score_case(rules(), evidence([], ["EDUCATION"])) == {}


def test_global_weight_from_the_settings_and_the_default_for_older_versions():
    custom = ss.Settings(2, {**ss.DEFAULTS.weights, "named_in_title": 0.55}, 0.85, 0.5)
    out = score_case(rules(settings=custom), evidence([EDU], ["EDUCATION"]))
    assert out[EDU].score == 0.55 and named(out, EDU)[0]["weight"] == 0.55
    older = ss.Settings(1, {k: v for k, v in ss.DEFAULTS.weights.items() if k != "named_in_title"}, 0.85, 0.5)
    assert score_case(rules(settings=older), evidence([EDU], ["EDUCATION"]))[EDU].score == 0.6


def test_reason_without_a_date():
    assert (
        named_reason("FINANCE", "cause_title", None)
        == "Department named in the cause title of an order: FINANCE"
    )
    assert named_reason("FINANCE", "cause_title", "2026-10-12") == (
        "Department named in the cause title of the order of 12 Oct 2026: FINANCE"
    )


def test_band_without_the_signal():
    so = ScoredOffice(
        EDU,
        "EDU",
        0.76,
        [
            {"kind": "named_in_title", "weight": 0.6},
            {"kind": "keyword", "weight": 0.4},
            {"kind": "suggested_unit", "office_code": "EDU-DSE"},
        ],
    )
    assert _band_without_named(so, ss.DEFAULTS) is None
    so.signals.append({"kind": "name_pattern", "weight": 0.8})
    assert _band_without_named(so, ss.DEFAULTS) == ScoreBand.HIGH  # 0.4 and 0.8 give 0.880
    assert (
        _band_without_named(
            ScoredOffice(EDU, "EDU", 0.6, [{"kind": "named_in_title", "weight": 0.6}]), ss.DEFAULTS
        )
        is None
    )


def _weights(**kw):
    return {**ss.DEFAULTS.weights, **kw}


def test_settings_band_rule():
    ss.validate(_weights(), 0.85, 0.5, "ok")
    ss.validate(_weights(named_in_title=0.5), 0.85, 0.5, "ok")  # at Possible
    for bad in (0.49, 0.85, 0.9):
        with pytest.raises(ss.SettingsError, match="cause title weight"):
            ss.validate(_weights(named_in_title=bad), 0.85, 0.5, "ok")
    with pytest.raises(ss.SettingsError, match="missing weights: named_in_title"):
        ss.validate({k: v for k, v in _weights().items() if k != "named_in_title"}, 0.85, 0.5, "ok")
    assert ss.DEFAULTS.weights["named_in_title"] == 0.6 and "named_in_title" in ss.KINDS
