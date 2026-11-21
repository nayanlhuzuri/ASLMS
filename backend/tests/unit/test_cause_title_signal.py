"""The cause-title signal without a database (design `state-insights`, round 3, decisions 36 to 40, and design
`cause-title-signal-review-advisories`, decisions 1 to 6): at most one `named_in_title` signal per active department of
the fact row, its phrase, source and reason, the global weight inside the possible band, the combinations of decision
37, no double counting of a respondent already scored by a keyword or name pattern of the same department, the stored
positions as the engine's only source, the settings band rule and the dry run's "without the signal" band."""

from __future__ import annotations

import re
import uuid
from datetime import date

import pytest

from aslms.domain.ownership import ScoreBand
from aslms.services import insights_rules
from aslms.services import scoring_settings as ss
from aslms.services.insights_facts import CaseInput, Maps, read_case
from aslms.services.matching import (
    CaseEvidence,
    RuleSet,
    ScoredOffice,
    _band_without_named,
    band_of,
    combine,
    named_reason,
    normalise_term,
    score_case,
)
from tests.unit.test_matching_rules import DSE, EDU, HEALTH, rule, ruleset

FIN = uuid.uuid4()
ORDER = uuid.uuid4()
FIN_ROW = "COMMISSIONER AND SECRETARY, FINANCE DEPARTMENT"


def maps() -> Maps:
    return Maps(
        explicit={"SECONDARY EDUCATION": EDU, "PWD": FIN},
        cores={"EDUCATION": EDU, "HEALTH": HEALTH, "FINANCE": FIN},
    )


def rules(*extra, settings=ss.DEFAULTS) -> RuleSet:
    rs = ruleset(*extra, settings=settings)
    rs.departments[FIN] = "FIN"
    return rs


def fin(kind, text, **kw):
    if kind == "name_pattern" and kw.get("pattern_kind") == "regex":
        kw.setdefault("regex", re.compile(text))
    return rule(kind, text, office=FIN, office_code="FIN", dept=FIN, dept_code="FIN", **kw)


def add_respondent(ev: CaseEvidence, name: str) -> int:
    """A current respondent party row, as `CaseEvidence.gather` records it."""
    idx = len(ev.names)
    party_no = len(ev.respondent_rows) + 1
    ev.names.append((normalise_term(name), "case_parties", {"role": "respondent", "party_no": party_no}))
    ev.respondent_name_idx.add(idx)
    if ev.first_respondent_idx is None:
        ev.first_respondent_idx = idx
    found = frozenset(insights_rules.department_phrases(name))
    ev.respondent_rows.append((idx, found))
    ev.respondent_phrases = ev.respondent_phrases | found
    return idx


def evidence(
    phrases, *, order=ORDER, day=date(2026, 10, 12), respondents=(), respondent_texts=(), **kw
) -> CaseEvidence:
    """The fact row's departments and positions from the stored phrases (as the builder derives them), current
    respondent rows, and respondent-side texts (`(text, where, ref)`: the summary or a cause-list entry)."""
    ids, positions = maps().phrase_positions(list(phrases))
    ev = CaseEvidence(
        title_department_ids=ids,
        title_phrases=list(phrases),
        title_positions=positions,
        title_order_id=order,
        title_order_date=day if order else None,
        **kw,
    )
    for name in respondents:
        add_respondent(ev, name)
    for t, where, ref in respondent_texts:
        ev.respondent_name_idx.add(len(ev.names))
        ev.names.append((normalise_term(t), where, ref))
    return ev


def named(out, dept):
    return [s for s in out[dept].signals if s["kind"] == "named_in_title"]


def test_alone_a_possible_match_with_the_cause_title_reason():
    out = score_case(rules(), evidence(["EDUCATION"]))
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
    out = score_case(rules(), evidence(["EDUCATION"], respondents=["THE SECRETARY, EDUCATION DEPARTMENT"]))
    (sig,) = named(out, EDU)
    assert sig["source"] == "party" and "order_date" not in sig and sig["ref"] == {"role": "respondent"}
    assert sig["reason"] == "Department named among the respondents: EDUCATION"
    # no titled order: the phrase came from the party names
    (sig,) = named(score_case(rules(), evidence(["EDUCATION"], order=None)), EDU)
    assert sig["source"] == "party"


def test_explicit_mapping_phrase_and_each_department_once():
    ev = evidence(["FINANCE", "SECONDARY EDUCATION", "EDUCATION"], respondents=[FIN_ROW])
    out = score_case(rules(), ev)
    assert named(out, FIN)[0]["phrase"] == "FINANCE" and named(out, FIN)[0]["source"] == "party"
    (edu,) = named(out, EDU)
    assert edu["phrase"] == "SECONDARY EDUCATION" and edu["source"] == "cause_title"


@pytest.mark.parametrize(
    ("extra", "evidence_kw", "score", "band"),
    [
        ((), {}, 0.6, ScoreBand.MEDIUM),
        (
            (rule("keyword", "EDUCATION"),),
            {"names": [("EDUCATION", "case_summary", {"field": "petitioner_summary"})]},
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
            {"names": [("DIRECTOR OF SECONDARY EDUCATION", "case_parties", {"role": "petitioner"})]},
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
    out = score_case(rules(*extra), evidence(["EDUCATION"], **evidence_kw))
    assert out[EDU].score == score and band_of(score, ss.DEFAULTS) == band
    assert combine({"named_in_title": 0.6}) == 0.6


def test_departments_left_out():
    rs = rules()
    # not an active Department-tier office of the rule set
    other = uuid.uuid4()
    ev = CaseEvidence(title_department_ids=[other], title_phrases=["XYZ"], title_positions=[1])
    assert score_case(rs, ev) == {}
    # no departments on the fact row
    assert score_case(rs, CaseEvidence(title_phrases=["EDUCATION"], title_positions=[0])) == {}


# ------------------------------------------------------------------ no double counting (decisions 1 to 4)


def test_same_respondent_row_matched_by_a_pattern_gives_no_named_signal():
    """The reviewer's example: a FINANCE name pattern (0.8) on the respondent row that the readings also name stays
    0.8, a possible match, not 0.92."""
    stats: dict[str, int] = {}
    out = score_case(
        rules(fin("name_pattern", "FINANCE DEPARTMENT", pattern_kind="regex")),
        evidence(["FINANCE"], respondents=[FIN_ROW]),
        stats,
    )
    assert out[FIN].score == 0.8 and band_of(out[FIN].score, ss.DEFAULTS) == ScoreBand.MEDIUM
    assert named(out, FIN) == []
    assert stats == {"named_withheld": 1}


def test_same_row_matched_by_a_keyword_of_a_directorate_withholds_for_its_department():
    dse = rule("keyword", "SECONDARY EDUCATION", office=DSE, office_code="EDU-DSE", depth=2)
    out = score_case(
        rules(dse),
        evidence(["SECONDARY EDUCATION"], respondents=["THE SECRETARY, SECONDARY EDUCATION DEPARTMENT"]),
    )
    assert out[EDU].score == 0.4 and named(out, EDU) == []
    assert {"kind": "suggested_unit", "office_code": "EDU-DSE"} in out[EDU].signals


def test_every_matched_row_counts_not_only_the_first_signal():
    """One keyword matches rows 1 and 3; the engine keeps one keyword signal (row 1), but row 3, the only row giving
    the phrase, is scored too, so the phrase is withheld."""
    ev = evidence(
        ["EDUCATION"],
        respondents=["THE SECRETARY TO THE GOVERNOR", "RAM DAS", "THE SECRETARY, EDUCATION DEPARTMENT"],
    )
    out = score_case(rules(rule("keyword", "SECRETARY")), ev)
    assert [s["ref"]["party_no"] for s in out[EDU].signals if s["kind"] == "keyword"] == [1]
    assert out[EDU].score == 0.4 and named(out, EDU) == []


def test_another_unscored_respondent_row_naming_the_department_counts_and_is_shown():
    ev = evidence(["FINANCE"], respondents=[FIN_ROW, "THE PRINCIPAL SECRETARY, FINANCE DEPTT."])
    out = score_case(rules(fin("name_pattern", FIN_ROW, pattern_kind="exact")), ev)
    (sig,) = named(out, FIN)
    assert sig["phrase"] == "FINANCE" and sig["source"] == "party"
    assert out[FIN].score == 0.92


def test_the_first_phrase_that_counts_is_shown():
    # PWD (explicit) is printed only in the cause title; FINANCE by the scored row. With respondent evidence scored,
    # neither counts; without the pattern, PWD (first in stored order) is shown from the cause title
    ev = evidence(["PWD", "FINANCE"], respondents=[FIN_ROW])
    assert ev.title_positions == [1, 1]
    out = score_case(rules(fin("name_pattern", FIN_ROW, pattern_kind="exact")), ev)
    assert named(out, FIN) == []
    (sig,) = named(score_case(rules(), ev), FIN)
    assert sig["phrase"] == "PWD" and sig["source"] == "cause_title"


def test_a_row_scored_for_another_department_does_not_withhold():
    out = score_case(rules(rule("keyword", "COMMISSIONER")), evidence(["FINANCE"], respondents=[FIN_ROW]))
    assert out[EDU].score == 0.4
    (sig,) = named(out, FIN)
    assert sig["source"] == "party" and out[FIN].score == 0.6


@pytest.mark.parametrize(
    ("where", "ref"),
    [
        ("case_summary", {"field": "respondent_summary"}),
        ("causelist_entry", {"list_date": "2026-10-12", "sr_no": 3}),
    ],
)
def test_summary_or_cause_list_respondent_match_scores_party_row_one(where, ref):
    text = "FINANCE DEPARTMENT AND 2 ORS"
    pattern = fin("name_pattern", text, pattern_kind="exact")
    ev = evidence(
        ["FINANCE"],
        respondents=[FIN_ROW, "THE DIRECTOR OF HEALTH SERVICES"],
        respondent_texts=[(text, where, ref)],
    )
    out = score_case(rules(pattern), ev)
    assert out[FIN].score == 0.8 and named(out, FIN) == []
    # a second row giving the phrase is not party row 1: it still counts
    ev = evidence(
        ["FINANCE"],
        respondents=["THE DIRECTOR OF HEALTH SERVICES", FIN_ROW],
        respondent_texts=[(text, where, ref)],
    )
    assert named(score_case(rules(pattern), ev), FIN)[0]["source"] == "party"


def test_petitioner_side_match_never_withholds():
    union = "FINANCE DEPARTMENT EMPLOYEES UNION"
    ev = evidence(["FINANCE"], respondents=[FIN_ROW], names=[(union, "case_parties", {"role": "petitioner"})])
    out = score_case(rules(fin("name_pattern", union, pattern_kind="exact")), ev)
    assert out[FIN].score == 0.92 and named(out, FIN)[0]["source"] == "party"
    ev = evidence(["FINANCE"], names=[(union, "case_summary", {"field": "petitioner_summary"})])
    assert score_case(rules(fin("name_pattern", union, pattern_kind="exact")), ev)[FIN].score == 0.92


def test_cause_title_only_phrase_withheld_when_any_respondent_evidence_is_scored():
    ev = evidence(["FINANCE"], respondents=["THE ACCOUNTANT GENERAL (A&E), ASSAM"])
    stats: dict[str, int] = {}
    out = score_case(rules(fin("keyword", "ACCOUNTANT GENERAL")), ev, stats)
    assert out[FIN].score == 0.4 and named(out, FIN) == [] and stats == {"named_withheld": 1}


def test_cause_title_only_phrase_counts_with_the_order_date_when_none_is():
    ev = evidence(["FINANCE"], respondents=["THE ACCOUNTANT GENERAL (A&E), ASSAM"])
    (sig,) = named(score_case(rules(), ev), FIN)
    assert sig["source"] == "cause_title" and sig["order_date"] == "2026-10-12"


def test_withheld_signals_are_counted_in_stats():
    ev = evidence(["FINANCE", "EDUCATION"], respondents=[FIN_ROW, "THE SECRETARY, EDUCATION DEPARTMENT"])
    stats: dict[str, int] = {}
    rs = rules(fin("name_pattern", "FINANCE DEPARTMENT", pattern_kind="regex"), rule("keyword", "EDUCATION"))
    out = score_case(rs, ev, stats)
    assert named(out, FIN) == [] and named(out, EDU) == []
    assert stats == {"named_withheld": 2}
    # an inactive department is not counted
    rs.departments.pop(EDU)
    stats = {}
    score_case(rs, ev, stats)
    assert stats == {"named_withheld": 1}
    # no stats given: nothing breaks
    assert score_case(rs, ev)[FIN].score == 0.8


# ------------------------------------------------------------------ the fact row as the only source (decisions 5, 6)


def test_engine_uses_stored_positions_and_no_map():
    rs = rules()
    assert not hasattr(rs, "title_maps") and not hasattr(rs, "title_department")
    # a department the row names without any phrase position gets no signal
    ev = CaseEvidence(
        title_department_ids=[EDU, HEALTH],
        title_phrases=["EDUCATION"],
        title_positions=[1],
        title_order_id=ORDER,
    )
    out = score_case(rs, ev)
    assert named(out, EDU) and HEALTH not in out
    # the phrase follows the stored position, whatever its words
    ev = CaseEvidence(title_department_ids=[HEALTH], title_phrases=["EDUCATION"], title_positions=[1])
    assert named(score_case(rs, ev), HEALTH)[0]["phrase"] == "EDUCATION"
    # empty positions with phrases (not derived since 0041): no signal
    ev = CaseEvidence(title_department_ids=[EDU], title_phrases=["EDUCATION"], title_positions=[])
    assert score_case(rs, ev) == {}


def test_phrase_positions_follow_phrase_departments():
    m = maps()
    phrases = ["EDUCATION", "NOWHERE", "PWD", "SECONDARY EDUCATION", "FINANCE"]
    assert m.phrase_positions(phrases) == ([EDU, FIN], [1, 0, 2, 1, 2])
    assert m.phrase_departments(phrases) == [EDU, FIN]
    assert m.phrase_positions([]) == ([], [])
    # an explicit mapping wins over the name core
    assert Maps(explicit={"HEALTH": EDU}, cores={"HEALTH": HEALTH}).phrase_positions(["HEALTH"]) == (
        [EDU],
        [1],
    )


def test_read_case_derives_from_the_stored_clipped_phrases():
    names = [f"THE SECRETARY, ZONE {a}{b} DEPARTMENT" for a in "ABCDEFGHIJ" for b in "ABCDEFGHIJ"]
    inp = CaseInput(
        id=uuid.uuid4(),
        court_id=uuid.uuid4(),
        category=None,
        category_code=None,
        contempt=False,
        respondents=[*names, "THE SECRETARY, HEALTH DEPARTMENT", "THE SECRETARY, EDUCATION DEPARTMENT"],
    )
    row = read_case(inp, maps(), today=date(2026, 11, 21))
    assert len(row["title_phrases"]) == 100 and "HEALTH" not in row["title_phrases"]
    # a department named only past the hundredth phrase is not named, as the re-derivation reads the row
    assert row["named_title_department_ids"] == []
    assert row["title_phrase_department_pos"] == [0] * 100
    inp.respondents = ["THE SECRETARY, HEALTH DEPARTMENT", "RAM", "THE SECRETARY, EDUCATION DEPARTMENT"]
    row = read_case(inp, maps(), today=date(2026, 11, 21))
    assert row["title_phrases"] == ["HEALTH", "EDUCATION"]
    assert row["named_title_department_ids"] == [HEALTH, EDU] and row["title_phrase_department_pos"] == [1, 2]
    assert maps().phrase_positions(row["title_phrases"]) == (
        row["named_title_department_ids"],
        row["title_phrase_department_pos"],
    )


# ------------------------------------------------------------------ settings and the dry run


def test_global_weight_from_the_settings_and_the_default_for_older_versions():
    custom = ss.Settings(2, {**ss.DEFAULTS.weights, "named_in_title": 0.55}, 0.85, 0.5)
    out = score_case(rules(settings=custom), evidence(["EDUCATION"]))
    assert out[EDU].score == 0.55 and named(out, EDU)[0]["weight"] == 0.55
    older = ss.Settings(1, {k: v for k, v in ss.DEFAULTS.weights.items() if k != "named_in_title"}, 0.85, 0.5)
    assert score_case(rules(settings=older), evidence(["EDUCATION"]))[EDU].score == 0.6


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
