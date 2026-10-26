"""The matching engine without a database: code normalisation, the noisy-OR combination, bands at default and
custom thresholds, and `score_case` over hand-built rule sets and evidence."""

from __future__ import annotations

import re
import uuid

import pytest

from aslms.domain.ownership import ScoreBand
from aslms.services import scoring_settings as ss
from aslms.services.matching import (
    CaseEvidence,
    LinkedCase,
    Rule,
    RuleSet,
    _word_regex,
    band_of,
    combine,
    engine_version,
    normalise_counsel_code,
    normalise_term,
    score_case,
    validate_regex,
)

EDU, HEALTH, DSE = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


def rule(
    kind,
    text,
    *,
    weight=None,
    office=EDU,
    office_code="EDU",
    depth=1,
    pattern_kind=None,
    regex=None,
    settings=ss.DEFAULTS,
    dept=EDU,
    dept_code="EDU",
):
    if kind == "keyword" and regex is None:
        regex = _word_regex(text)
    return Rule(
        id=uuid.uuid4(),
        kind=kind,
        text=text,
        office_id=office,
        office_code=office_code,
        office_depth=depth,
        department_id=dept,
        department_code=dept_code,
        weight=weight if weight is not None else settings.weights[kind],
        pattern_kind=pattern_kind,
        regex=regex,
    )


def ruleset(*rules, settings=ss.DEFAULTS, generic=()):
    rs = RuleSet(settings=settings, departments={EDU: "EDU", HEALTH: "HEALTH"})
    rs.generic_codes = set(generic)
    for r in rules:
        if r.kind == "counsel_code":
            rs.codes[r.text] = r
        elif r.kind == "keyword":
            rs.keywords.append(r)
        elif r.kind == "name_pattern":
            rs.patterns.append(r)
        elif r.kind == "watchlist":
            rs.watch.setdefault(r.text, []).append(r)
    return rs


ENTRY_REF = {"list_date": "2025-01-06", "sr_no": 4}


@pytest.mark.parametrize(
    "raw, expected",
    [("SC,EDU", "SC, EDU"), ("sc , edu", "SC, EDU"), ("SC, EDU,", "SC, EDU"), ("DY.S.G.I.", "DY.S.G.I.")],
)
def test_normalise_counsel_code(raw, expected):
    assert normalise_counsel_code(raw) == expected


def test_combine():
    assert combine({"counsel_code": 0.95}) == 0.95
    assert combine({"name_pattern": 0.8, "keyword": 0.4}) == 0.88
    assert combine({"keyword": 0.4, "linked_case": 0.7}) == 0.82
    assert combine({k: 1.0 for k in ss.KINDS}) == 1.0
    assert combine({k: 0.99 for k in ss.KINDS}) <= 1.0


def test_two_keywords_do_not_add_up():
    rs = ruleset(rule("keyword", "EDUCATION"), rule("keyword", "SCHOOL"))
    ev = CaseEvidence(names=[("DIRECTOR OF SCHOOL EDUCATION", "case_summary", {})])
    out = score_case(rs, ev)
    assert out[EDU].score == 0.4
    assert band_of(out[EDU].score, ss.DEFAULTS) is None


def test_band_of_default_and_custom():
    d = ss.DEFAULTS
    assert band_of(0.499, d) is None
    assert band_of(0.500, d) == ScoreBand.MEDIUM
    assert band_of(0.849, d) == ScoreBand.MEDIUM
    assert band_of(0.850, d) == ScoreBand.HIGH
    custom = ss.Settings(version=3, weights=dict(d.weights), threshold_strong=0.9, threshold_possible=0.6)
    assert band_of(0.599, custom) is None
    assert band_of(0.600, custom) == ScoreBand.MEDIUM
    assert band_of(0.899, custom) == ScoreBand.MEDIUM
    assert band_of(0.900, custom) == ScoreBand.HIGH


def test_counsel_code_scores_high_with_signal():
    r = rule("counsel_code", "SC, EDU")
    out = score_case(ruleset(r), CaseEvidence(entry_codes=[("SC, EDU", ENTRY_REF)]))
    assert out[EDU].score == 0.95
    assert band_of(out[EDU].score, ss.DEFAULTS) == ScoreBand.HIGH
    sig = out[EDU].signals[0]
    assert sig == {
        "kind": "counsel_code",
        "rule_id": str(r.id),
        "rule_office_code": "EDU",
        "weight": 0.95,
        "matched": "SC, EDU",
        "where": "causelist_entry",
        "ref": ENTRY_REF,
    }


def test_generic_code_scores_nothing():
    out = score_case(ruleset(generic={"GA, ASSAM"}), CaseEvidence(entry_codes=[("GA, ASSAM", ENTRY_REF)]))
    assert out == {}


def test_directorate_rule_rolls_up_with_suggested_unit():
    r = rule("counsel_code", "SC, DSE", office=DSE, office_code="EDU-DSE", depth=2)
    out = score_case(ruleset(r), CaseEvidence(advocate_codes=[("SC, DSE", {"side": "respondent"})]))
    assert set(out) == {EDU}
    assert out[EDU].signals[-1] == {"kind": "suggested_unit", "office_code": "EDU-DSE"}
    assert out[EDU].signals[0]["where"] == "case_advocates"


def test_keywords_match_whole_words_only():
    rs = ruleset(rule("keyword", "EDUCATION"))
    assert score_case(rs, CaseEvidence(names=[("DEPT OF EDUCATION", "case_parties", {})]))
    assert score_case(rs, CaseEvidence(names=[("REEDUCATIONAL TRUST", "case_parties", {})])) == {}


def test_name_patterns():
    exact = rule("name_pattern", "STATE OF ASSAM", pattern_kind="exact")
    prefix = rule(
        "name_pattern",
        "THE DIRECTOR OF SECONDARY",
        pattern_kind="prefix",
        dept=HEALTH,
        dept_code="HEALTH",
        office=HEALTH,
        office_code="HEALTH",
    )
    assert (
        score_case(ruleset(exact), CaseEvidence(names=[("STATE OF ASSAM", "case_parties", {})]))[EDU].score
        == 0.8
    )
    assert score_case(ruleset(exact), CaseEvidence(names=[("THE STATE OF ASSAM", "case_parties", {})])) == {}
    out = score_case(ruleset(prefix), CaseEvidence(names=[("THE DIRECTOR OF SECONDARY EDUCATION", "x", {})]))
    assert out[HEALTH].score == 0.8
    rx = rule(
        "name_pattern",
        r"COMMISSIONER.*EDUCATION",
        pattern_kind="regex",
        regex=re.compile(r"COMMISSIONER.*EDUCATION", re.I),
    )
    assert score_case(ruleset(rx), CaseEvidence(names=[("THE COMMISSIONER AND SECY EDUCATION", "x", {})]))


def test_pattern_plus_keyword_is_strong():
    rs = ruleset(
        rule("name_pattern", "DIRECTOR OF SECONDARY EDUCATION", pattern_kind="exact"),
        rule("keyword", "EDUCATION"),
    )
    out = score_case(rs, CaseEvidence(names=[("DIRECTOR OF SECONDARY EDUCATION", "case_parties", {})]))
    assert out[EDU].score == 0.88
    assert band_of(out[EDU].score, ss.DEFAULTS) == ScoreBand.HIGH


def test_linked_case_and_watchlist():
    rs = ruleset(rule("watchlist", "ASHC010001232025"))
    ev = CaseEvidence(
        cnr="ASHC010001232025",
        linked=[LinkedCase(uuid.uuid4(), "ASLMS/GOA/CASE/2026/000001", "WP(C)/1/2025", {EDU})],
    )
    out = score_case(rs, ev)
    kinds = {s["kind"] for s in out[EDU].signals}
    assert kinds == {"linked_case", "watchlist"}
    assert out[EDU].score == combine({"linked_case": 0.7, "watchlist": 0.75})


def test_effective_weight_override_and_setting():
    custom = ss.Settings(
        version=2,
        weights={**ss.DEFAULTS.weights, "keyword": 0.5},
        threshold_strong=0.85,
        threshold_possible=0.5,
    )
    rs = ruleset(rule("keyword", "EDUCATION", settings=custom), settings=custom)
    out = score_case(rs, CaseEvidence(names=[("EDUCATION", "case_summary", {})]))
    assert out[EDU].score == 0.5
    assert band_of(out[EDU].score, custom) == ScoreBand.MEDIUM
    assert out[EDU].signals[0]["weight"] == 0.5
    overridden = ruleset(rule("keyword", "EDUCATION", weight=0.6))
    assert score_case(overridden, CaseEvidence(names=[("EDUCATION", "x", {})]))[EDU].score == 0.6
    assert engine_version(custom) == "2.2"  # design partial-code-match, decision 17
    assert engine_version(ss.DEFAULTS) == "2.0"


def test_inactive_office_rules_are_not_in_the_ruleset():
    """RuleSet.load drops rules of inactive offices; an empty rule set scores nothing."""
    assert score_case(ruleset(), CaseEvidence(entry_codes=[("SC, EDU", ENTRY_REF)])) == {}


@pytest.mark.parametrize("bad", ["(unclosed", "A" * 301, ".*"])
def test_regex_validation(bad):
    with pytest.raises(ValueError):
        validate_regex(bad)


def test_normalise_term():
    assert normalise_term("  The  Dir. of Sec.Education ") == "THE DIR OF SEC EDUCATION"
