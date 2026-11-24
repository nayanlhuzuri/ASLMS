"""The sentence checks of local-model answers (design `research-index`, decisions 23 to 29; "Tests", unit): sentence
splitting, quotes, uncited sentences, dates, numbers, case numbers and citations, names, outcomes, the removal note and
the withheld rules, and the module's purity. No database, no network, no model."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from aslms.services import answer_check_rules as K
from aslms.services import answer_checks as C

ASLMS = Path(__file__).resolve().parents[2] / "aslms"

SRC = {
    1: (
        "Court Order (Court Record) dated 12 Mar 2024, No. 5, WP(C)/7013/2024, page 2\n"
        "Heard Mr. A. K. Das, learned counsel. The respondents are directed to release the retiral benefits of the\n"
        "petitioner within four weeks. List on 12.04.2024. The petitioner Ramen Kalita relies on (2006) 4 SCC 1.\n"
        "The writ petition is allowed. An amount of Rs. 1,50,000 is payable."
    ),
    2: "Case Details (Court Record), WP(C)/7013/2024\nStatus: Pending; Next hearing: 12th April, 2024",
}


def texts(answer: str) -> list[str]:
    return [s.text for s in C.split_sentences(answer)]


def test_split_sentences_abbreviations():
    assert texts("Heard Mr. A. K. Das for the petitioner [S1]. The court allowed it [S1].") == [
        "Heard Mr. A. K. Das for the petitioner [S1].",
        "The court allowed it [S1].",
    ]
    assert texts("In W.P.(C) No. 7013 of 2024 the Hon'ble Court ruled [S1]. Next.") == [
        "In W.P.(C) No. 7013 of 2024 the Hon'ble Court ruled [S1].",
        "Next.",
    ]
    assert texts("See Crl.A. 12/2020 (decided vs. the State. Later) here [S1]. Then 4 weeks [S1].") == [
        "See Crl.A. 12/2020 (decided vs. the State. Later) here [S1].",
        "Then 4 weeks [S1].",
    ]
    # markers after the full stop belong to the sentence; a line break ends a sentence
    assert texts("It was allowed. [S1] The rest [S2].\nAnother line") == [
        "It was allowed. [S1]",
        "The rest [S2].",
        "Another line",
    ]
    assert texts("i.e. the order of e.g. 2024 stands [S1].") == ["i.e. the order of e.g. 2024 stands [S1]."]
    assert "u/s." in K.ABBREVIATIONS and "hon'ble." in K.ABBREVIATIONS


def test_quote_exact_with_whitespace_only():
    ok = C.check('The court said "release the retiral benefits of the petitioner" [S1].', SRC)
    assert ok.removed == [] and ok.withheld is None
    (span,) = ok.quotes["S1"]
    assert SRC[1][span[0] : span[1]].replace("\n", " ") == "release the retiral benefits of the petitioner"
    # a line break in the source still matches; a curly quote reads as straight
    assert C.check("It said “retiral benefits of the petitioner within four weeks” [S1].", SRC).removed == []
    # one changed letter fails
    bad = C.check('First fact [S2]. The court said "release the retirel benefits" [S1].', SRC)
    assert bad.removed == [(1, "quote")]


def test_uncited_sentence_rules():
    r = C.check("The petition is pending [S2]. Two orders deal with this.", SRC)
    assert r.removed == [] and r.text == "The petition is pending [S2]. Two orders deal with this."
    long = "This sentence has no marker and runs on for well over twelve words in all of its length."
    r = C.check(f"The petition is pending [S2]. {long}", SRC)
    assert r.removed == [(1, "uncited")]
    r = C.check("The petition is pending [S2]. It was listed on 12.04.2024.", SRC)
    assert r.removed == [(1, "uncited")]  # a date with no marker


def test_dates_numbers_words():
    assert C.check("Benefits are due within 4 weeks [S1].", SRC).removed == []  # "four weeks" backs "4 weeks"
    assert C.check("The case is listed on 12.04.2024 [S2].", SRC).removed == []  # "12th April, 2024"
    assert C.check("It was listed on 12 April 2024 [S1].", SRC).removed == []
    assert C.check("Listed on April 12, 2024 [S1].", SRC).removed == []
    assert C.check("Pay Rs 150000 [S1].", SRC).removed == []  # commas are ignored
    r = C.check("First [S1]. Benefits are due within 6 weeks [S1].", SRC)
    assert r.removed == [(1, "number")]
    r = C.check("First [S1]. The case is listed on 13.04.2024 [S1].", SRC)
    assert r.removed == [(1, "date")]
    assert C.dates("12.03.2024 and 12th March, 2024") == {(2024, 3, 12)}


def test_case_numbers_and_citations_compacted():
    assert C.check("The order in WP(C) 7013/2024 was passed [S1].", SRC).removed == []
    assert C.check("It relies on (2006) 4 SCC 1 [S1].", SRC).removed == []
    r = C.check("First [S1]. The order in WP(C)/7014/2024 was passed [S1].", SRC)
    assert r.removed == [(1, "case_no")]
    r = C.check("First [S1]. It relies on (2007) 4 SCC 1 [S1].", SRC)
    assert r.removed == [(1, "case_no")]
    assert C.compact("W.P.(C) No. 7013 of 2024") == C.compact("WP(C)/7013/2024") == "WP(C)70132024"
    assert not C.contains_compact("4SCC1", "(2006)4SCC12")


def test_names_reordered_pass_invented_fail():
    assert C.check("Kalita Ramen is the petitioner [S1].", SRC).removed == []
    assert C.check("Mr. Das argued [S1].", SRC).removed == []
    r = C.check("First [S1]. Bipin Saikia is the petitioner [S1].", SRC)
    assert r.removed == [(1, "name")]
    assert C.check("The High Court of Assam heard it [S1].", SRC).removed == []  # stop words only


def test_outcome_word_or_rule_outcome():
    assert C.check("The petition was allowed [S1].", SRC).removed == []
    r = C.check("First [S1]. The petition was dismissed [S1].", SRC)
    assert r.removed == [(1, "outcome")]
    src = {1: "Court Order (Court Record) dated 1 Jan 2024\nThe matter stands concluded in the above terms."}
    assert C.check("The petition was dismissed [S1].", src, rule_outcomes={1: "dismissed"}).removed == []
    # negation is not checked (decision 27)
    assert C.check("The petition was not dismissed [S1].", src, rule_outcomes={1: "dismissed"}).removed == []


def test_removal_note_and_withheld_rules():
    r = C.check("The petition was allowed [S1]. It is pending [S2]. Benefits within 9 weeks [S1].", SRC)
    assert r.withheld is None and r.removed == [(2, "number")]
    assert r.text == (
        "The petition was allowed [S1]. It is pending [S2].\n[Removed by ASLMS: 1 sentence whose quotes, dates, "
        "numbers, case numbers, names or outcomes were not found in the records they cite.]"
    )
    assert r.counts == {
        "version": 1,
        "sentences": 3,
        "kept": 2,
        "removed": {"uncited": 0, "quote": 0, "date": 0, "number": 1, "case_no": 0, "name": 0, "outcome": 0},
        "withheld": None,
    }
    assert (
        C.check("Benefits within 9 weeks [S1]. The petition was allowed [S1].", SRC).withheld
        == "first_sentence"
    )
    r = C.check("Fine [S1]. Within 9 weeks [S1]. Within 8 weeks [S1].", SRC)
    assert r.withheld == "majority" and r.text == ""
    assert C.check("Two orders deal with this.", SRC).withheld == "none_cited"
    # a marker naming no supplied source does not count as cited
    assert C.check("It was allowed [S9].", SRC).withheld == "first_sentence"


def test_line_breaks_kept_between_sentences():
    r = C.check("The petition was allowed [S1].\nIt is pending [S2].", SRC)
    assert r.text == "The petition was allowed [S1].\nIt is pending [S2]."


def test_checks_pure_imports():
    allowed = set(sys.stdlib_module_names) | {"aslms", "__future__"}
    for name in ("answer_checks.py", "answer_check_rules.py"):
        tree = ast.parse((ASLMS / "services" / name).read_text("utf-8"))
        mods = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods.add(node.module)
        assert {m.split(".")[0] for m in mods} - allowed == set(), name
        assert {m for m in mods if m.startswith("aslms")} <= {
            "aslms.services",
            "aslms.services.answer_check_rules",
            "aslms.services.order_parse_rules",
        }, name
