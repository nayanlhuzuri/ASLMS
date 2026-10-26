"""Partial counsel-code matching without a database (design `partial-code-match`): code parts and respondent
markers, the owner's four examples, same parts, overlaps, whole parts only, the generic stop-list and its extension
by single-part generic codes, exact wins, one code family per department, several departments, the noisy OR, the
global weight over a rule's override, the reason texts, the candidate index and the engine version."""

from __future__ import annotations

import itertools
import random
import uuid

import pytest

from aslms.domain.ownership import ScoreBand
from aslms.services import scoring_settings as ss
from aslms.services.matching import (
    GENERIC_PARTS,
    CaseEvidence,
    Rule,
    RuleSet,
    _word_regex,
    band_of,
    code_parts,
    engine_version,
    partial_reason,
    partial_relation,
    score_case,
)

EDU, HEALTH, HIGHER = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
CODES = {EDU: "EDU", HEALTH: "HEALTH", HIGHER: "HIGHER"}
REF = {"list_date": "2026-10-23", "sr_no": 7}


def rule(kind, text, dept=EDU, *, weight=None):
    return Rule(
        id=uuid.uuid4(),
        kind=kind,
        text=text,
        office_id=dept,
        office_code=CODES[dept],
        office_depth=1,
        department_id=dept,
        department_code=CODES[dept],
        weight=weight if weight is not None else ss.DEFAULTS.weights[kind],
        regex=_word_regex(text) if kind == "keyword" else None,
    )


def ruleset(*rules, generic=()):
    rs = RuleSet(settings=ss.DEFAULTS, departments=dict(CODES))
    rs.generic_codes = set(generic)
    for r in rules:
        if r.kind == "counsel_code":
            rs.codes[r.text] = r
        elif r.kind == "keyword":
            rs.keywords.append(r)
        elif r.kind == "name_pattern":
            rs.patterns.append(r)
    return rs


def listed(*codes):
    return CaseEvidence(entry_codes=[(c, REF) for c in codes])


def kinds(scored):
    return [s["kind"] for s in scored.signals if s["kind"] != "suggested_unit"]


# ------------------------------------------------------------------------------------------------ parts


def test_code_parts_normalised_and_set():
    assert code_parts("sc , edu,") == {"SC", "EDU"}
    assert code_parts("SC, EDU, SC") == {"SC", "EDU"}
    assert code_parts("SC,, EDU, ,") == {"SC", "EDU"}
    assert code_parts("") == frozenset() and code_parts(None) == frozenset()


@pytest.mark.parametrize(
    "printed, parts",
    [
        ("SC, GHC (R- 2, 3)", {"SC", "GHC"}),
        ("SC, HEALTH(R-1, 2, 4)", {"SC", "HEALTH"}),
        ("SC, F.T (R2TO4, 7)", {"SC", "F.T"}),
        ("SC, BTC, (R- 3, 4&5", {"SC", "BTC"}),
        ("GA, ASSAM(R1, 3)", {"GA", "ASSAM"}),
        ("SC, GHC (R- 151, 152, 153)", {"SC", "GHC"}),
        ("SC, GHC (R 10, 11)", {"SC", "GHC"}),
        ("SC, GHC (R1-R5, R9)", {"SC", "GHC"}),
        ("SC, GHC (R-3 )", {"SC", "GHC"}),
        ("SC, AG (A AND E)", {"SC", "AG (A AND E)"}),
        ("SC, FINANCE(MR.H.RAHMAN, MS.J.HUDA)", {"SC", "FINANCE(MR.H.RAHMAN", "MS.J.HUDA)"}),
    ],
)
def test_code_parts_removes_respondent_markers(printed, parts):
    assert code_parts(printed) == parts


# ------------------------------------------------------------------------------------------------ the rule


@pytest.mark.parametrize(
    "printed, kind, weight, band, relation",
    [
        ("SC, EDU", "counsel_code", 0.95, ScoreBand.HIGH, None),
        ("SC, EDU, DSE", "counsel_code_partial", 0.6, ScoreBand.MEDIUM, "contained"),
        ("EDU", "counsel_code_partial", 0.6, ScoreBand.MEDIUM, "contains"),
        ("SC, HEALTH", None, None, None, None),
    ],
)
def test_owner_examples(printed, kind, weight, band, relation):
    out = score_case(ruleset(rule("counsel_code", "SC, EDU")), listed(printed))
    if kind is None:
        assert EDU not in out
        return
    assert out[EDU].score == weight and band_of(out[EDU].score, ss.DEFAULTS) == band
    (signal,) = out[EDU].signals
    assert signal["kind"] == kind and signal["weight"] == weight
    if relation:
        assert signal["relation"] == relation and signal["printed"] == printed
        assert signal["matched"] == "SC, EDU"


@pytest.mark.parametrize("printed", ["EDU, SC", "SC, GHC (R- 2, 3)", "SC, EDU, EDU"])
def test_same_parts_is_partial_not_exact(printed):
    rs = ruleset(rule("counsel_code", "SC, GHC"), rule("counsel_code", "SC, EDU", HEALTH))
    out = score_case(rs, listed(printed))
    (dept,) = out
    (signal,) = out[dept].signals
    assert signal["kind"] == "counsel_code_partial" and signal["relation"] == "same_parts"
    assert out[dept].score == 0.6


def test_overlap_without_subset_is_no_match():
    rs = ruleset(rule("counsel_code", "SC, EDU, HIGHER"))
    assert score_case(rs, listed("SC, EDU, DSE")) == {}
    assert partial_relation(code_parts("SC, EDU, HIGHER"), code_parts("SC, EDU, DSE"), GENERIC_PARTS) is None


def test_whole_parts_only():
    rs = ruleset(rule("counsel_code", "SC, EDU"))
    assert score_case(rs, listed("SC, ELEM. EDU", "SC, HIGHER EDU")) == {}
    dotted = ruleset(rule("counsel_code", "SC, SEC. EDU."))
    assert score_case(dotted, listed("SC, SEC. EDU")) == {}


def test_generic_parts_stop_list():
    rs = ruleset(
        rule("counsel_code", "SC, EDU"),
        rule("counsel_code", "SC, SCERT, ASSAM", HEALTH),
        rule("counsel_code", "SC, AG", HIGHER),
    )
    for token in sorted(GENERIC_PARTS):
        assert score_case(rs, listed(token)) == {}, token
    assert score_case(rs, listed("SC, ASSAM")) == {}
    assert score_case(rs, listed("AG")) == {}
    # a department code made only of generic parts never matches partially, but still exactly
    assert score_case(rs, listed("SC, AG, DSE")) == {}
    assert score_case(rs, listed("AG, SC")) == {}
    out = score_case(rs, listed("SC, AG"))
    assert list(out) == [HIGHER] and kinds(out[HIGHER]) == ["counsel_code"]


def test_single_part_generic_code_extends_stop_list():
    dept_rule = rule("counsel_code", "SR. GA ADV., FOREST")
    assert score_case(ruleset(dept_rule), listed("SR. GA ADV.")) == {}  # already in the list
    other = rule("counsel_code", "SC, LOTTERY BOARD")
    assert EDU in score_case(ruleset(other), listed("LOTTERY BOARD"))
    rs = ruleset(other, generic={"LOTTERY BOARD"})
    assert score_case(rs, listed("LOTTERY BOARD")) == {}  # a generic code, skipped
    assert score_case(rs, listed("LOTTERY BOARD (R-1, 2)")) == {}  # its single part is now generic
    assert "LOTTERY BOARD" in rs.generic_parts
    two_parts = ruleset(other, generic={"GA, LOTTERY BOARD"})
    assert EDU in score_case(two_parts, listed("LOTTERY BOARD (R-1, 2)")), "only single-part codes extend it"


def test_generic_state_code_skips_partial():
    rs = ruleset(
        rule("counsel_code", "GA, ASSAM, REVENUE"),
        rule("counsel_code", "PP, ASSAM, HOME", HEALTH),
        generic={"GA, ASSAM, REVENUE, X"},
    )
    for printed in ("GA, ASSAM", "PP, ASSAM", "SR. GA, ASSAM"):
        assert score_case(rs, listed(printed)) == {}, printed
    assert score_case(rs, listed("GA, ASSAM, REVENUE, X")) == {}
    assert rs.partial_matches("GA, ASSAM, REVENUE, X") == []


def test_exact_wins_over_partial_for_others():
    rs = ruleset(rule("counsel_code", "SC, EDU"), rule("counsel_code", "SC, EDU, DSE", HEALTH))
    out = score_case(rs, listed("SC, EDU"))
    assert list(out) == [EDU] and kinds(out[EDU]) == ["counsel_code"]
    assert rs.partial_matches("SC, EDU") == []


def test_exact_and_partial_same_department_counts_once():
    rs = ruleset(rule("counsel_code", "SC, EDU"))
    ev = CaseEvidence(entry_codes=[("SC, EDU", REF)], advocate_codes=[("EDU", {"side": "respondent"})])
    out = score_case(rs, ev)
    assert out[EDU].score == 0.95 and kinds(out[EDU]) == ["counsel_code"]


def test_several_departments_each_possible():
    rs = ruleset(
        rule("counsel_code", "SC, HIGHER EDU"), rule("counsel_code", "SC, COTTON UNIVERSITY", HEALTH)
    )
    out = score_case(rs, listed("SC, HIGHER EDU, SC, COTTON UNIVERSITY"))
    assert {d: (o.score, band_of(o.score, ss.DEFAULTS)) for d, o in out.items()} == {
        EDU: (0.6, ScoreBand.MEDIUM),
        HEALTH: (0.6, ScoreBand.MEDIUM),
    }
    rs2 = ruleset(rule("counsel_code", "SC, EDU"), rule("counsel_code", "SC, EDU, DSE", HEALTH))
    out2 = score_case(rs2, listed("EDU"))
    assert {d: o.score for d, o in out2.items()} == {EDU: 0.6, HEALTH: 0.6}
    assert [r.text for r, _ in rs2.partial_matches("EDU")] == ["SC, EDU", "SC, EDU, DSE"]


def test_several_codes_of_one_department_one_weight():
    rs = ruleset(rule("counsel_code", "SC, EDU"), rule("counsel_code", "SC, EDU, DSE"))
    out = score_case(rs, listed("EDU"))
    assert out[EDU].score == 0.6 and kinds(out[EDU]) == ["counsel_code_partial", "counsel_code_partial"]


def test_partial_combines_by_noisy_or():
    code = rule("counsel_code", "SC, EDU")
    ev = CaseEvidence(
        entry_codes=[("SC, EDU, DSE", REF)], names=[("DIRECTOR OF SCHOOL EDUCATION", "case_summary", {})]
    )
    out = score_case(ruleset(code, rule("keyword", "EDUCATION")), ev)
    assert out[EDU].score == 0.76 and band_of(0.76, ss.DEFAULTS) == ScoreBand.MEDIUM
    pattern = rule("name_pattern", "DIRECTOR OF SCHOOL EDUCATION")
    pattern = Rule(**{**pattern.__dict__, "pattern_kind": "exact"})
    out = score_case(ruleset(code, pattern), ev)
    assert out[EDU].score == 0.92 and band_of(0.92, ss.DEFAULTS) == ScoreBand.HIGH


def test_partial_ignores_rule_override():
    rs = ruleset(rule("counsel_code", "SC, EDU", weight=0.99))
    out = score_case(rs, listed("SC, EDU, DSE"))
    assert out[EDU].score == 0.6 and out[EDU].signals[0]["weight"] == 0.6
    custom = ss.Settings(
        version=4,
        weights={**ss.DEFAULTS.weights, "counsel_code_partial": 0.7},
        threshold_strong=0.85,
        threshold_possible=0.5,
    )
    rs.settings = custom
    assert score_case(rs, listed("SC, EDU, DSE"))[EDU].score == 0.7


# ------------------------------------------------------------------------------------------------ reason


def test_reason_texts():
    assert (
        partial_reason("SC, EDU", "SC, EDU, DSE", "contained", "causelist_entry", REF)
        == "Code SC, EDU found inside SC, EDU, DSE on the cause list of 23 Oct 2026"
    )
    assert (
        partial_reason("SC, EDU", "EDU", "contains", "causelist_entry", REF)
        == "Code EDU on the cause list of 23 Oct 2026 is part of SC, EDU"
    )
    assert (
        partial_reason("SC, GHC", "SC, GHC (R- 2, 3)", "same_parts", "causelist_entry", REF)
        == "Code SC, GHC (R- 2, 3) on the cause list of 23 Oct 2026 has the same parts as SC, GHC"
    )
    assert (
        partial_reason("SC, EDU", "EDU", "contains", "case_advocates", {"side": "respondent"})
        == "Code EDU in the case's advocate list (respondent side) is part of SC, EDU"
    )
    assert partial_reason("SC, EDU", "EDU", "contains", "causelist_entry", {"list_date": "2026-10-05"}) == (
        "Code EDU on the cause list of 5 Oct 2026 is part of SC, EDU"
    )
    rs = ruleset(rule("counsel_code", "SC, EDU"))
    ev = CaseEvidence(advocate_codes=[("SC, EDU, DSE", {"side": "respondent"})])
    (signal,) = score_case(rs, ev)[EDU].signals
    assert signal["printed"] == "SC, EDU, DSE" and signal["relation"] == "contained"
    assert signal["matched"] == "SC, EDU" and signal["where"] == "case_advocates"
    assert (
        signal["reason"]
        == "Code SC, EDU found inside SC, EDU, DSE in the case's advocate list (respondent side)"
    )


def test_most_recent_listing_gives_the_signal():
    rs = ruleset(rule("counsel_code", "SC, EDU"))
    ev = CaseEvidence(entry_codes=[("SC, EDU, DSE", REF), ("EDU", {"list_date": "2026-01-02", "sr_no": 1})])
    (signal,) = score_case(rs, ev)[EDU].signals
    assert signal["ref"] == REF and signal["relation"] == "contained"


# ------------------------------------------------------------------------------------------------ index


def test_partial_index_finds_all_candidates():
    rnd = random.Random(154)
    vocab = ["SC", "GA", "ASSAM", "AG", "EDU", "DSE", "HEALTH", "HIGHER", "GHC", "BTC", "PWD", "ELEM. EDU"]
    depts = [EDU, HEALTH, HIGHER]
    for _ in range(40):
        rules = {}
        for _ in range(rnd.randint(1, 12)):
            text = ", ".join(rnd.sample(vocab, rnd.randint(1, 4)))
            rules.setdefault(text, rule("counsel_code", text, rnd.choice(depts)))
        rs = ruleset(*rules.values())
        for n in range(1, 4):
            for combo in itertools.islice(itertools.permutations(vocab, n), 0, None, 7):
                printed = ", ".join(combo)
                got = [(r.text, rel) for r, rel in rs.partial_matches(printed)]
                expected = []
                if printed not in rs.codes and any(p not in GENERIC_PARTS for p in code_parts(printed)):
                    for r in rules.values():
                        rel = partial_relation(r.parts, code_parts(printed), GENERIC_PARTS)
                        if rel is not None:
                            expected.append((r.department_code, r.text, rel))
                assert got == [(t, rel) for _, t, rel in sorted(expected)], printed


def test_engine_version_two():
    assert engine_version(ss.DEFAULTS) == "2.0"
    assert engine_version(ss.Settings(3, dict(ss.DEFAULTS.weights), 0.85, 0.5)) == "2.3"
