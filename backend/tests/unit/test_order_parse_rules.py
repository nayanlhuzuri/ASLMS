"""The order reader's pattern table (design `order-sections`, decisions 7, 11, 12, 15 and 17): each pattern matches the
measured variant it names, and only that."""

from __future__ import annotations

import pytest

from aslms.services import order_parse_rules as R


@pytest.mark.parametrize(
    "line", ["Page No.# 1/2", "\fPage No.# 12/40 ", "Page No. # 3 / 4", "Page 5 of 195 "]
)
def test_page_marks(line):
    assert R.PAGE_MARK.match(line)


def test_page_mark_is_a_whole_line():
    assert not R.PAGE_MARK.match("See Page No.# 1/2 of the paper book")


def test_cnr_line_and_citation_line():
    assert R.CNR_LINE.match("GAHC010121712025").group(1) == "GAHC010121712025"
    assert not R.CNR_LINE.match("GAHC01XXXXXX2025")
    assert not R.CNR_LINE.match("GAHC0101217120251")
    assert R.UNDEFINED.match("  undefined  ")
    assert R.NEUTRAL_CITATION.match("2026:GAU-AS:7666").group(1) == "2026:GAU-AS:7666"


@pytest.mark.parametrize(
    "line",
    [
        "BEFORE",
        ":::BEFORE:::",
        "B E F O R E",
        "� B E F O R E �",
        "– B E F O R E –",
        "-BEFORE-",
        ":: BEFORE ::",
    ],
)
def test_coram_markers(line):
    assert R.CORAM_MARK.match(line)


def test_coram_inline_and_judge_lines():
    assert R.CORAM_INLINE.match("CORAM : HON'BLE MR. JUSTICE JUDGE A")
    for judge in ("HONOURABLE MR. JUSTICE A", "HON'BLE THE CHIEF JUSTICE", "HON�BLE MRS. JUSTICE B"):
        assert R.JUDGE_LINE.search(judge)
    assert R.REGISTRAR_CORAM.search("JOINT REGISTRAR (JUDL.) MR. OFFICER A")


@pytest.mark.parametrize(
    ("line", "heading"),
    [
        ("ORDER", "ORDER"),
        ("                    ORDER", "ORDER"),
        ("JUDGMENT & ORDER (CAV)", "JUDGMENT & ORDER"),
        ("JUDGMENT&ORDER (CAV)", "JUDGMENT&ORDER"),
        ("JUDGMENT AND ORDER (ORAL)", "JUDGMENT AND ORDER"),
        ("JUDGEMENT", "JUDGEMENT"),
        ("COMMON ORDER", "COMMON ORDER"),
        ("ORDER [ORAL]", "ORDER"),
        ("O R D E R", "O R D E R"),
        ("JUDGMENT (Judge A, J.)", "JUDGMENT"),
    ],
)
def test_headings(line, heading):
    m = R.HEADING.match(line)
    assert m and m.group("h") == heading


def test_heading_with_date_before_it_and_not_a_sentence():
    m = R.HEADING.match("        29.05.2024                                        O R D E R")
    assert m and m.group("date") and m.group("h") == "O R D E R"
    assert not R.HEADING.match("ORDER dated 12.03.2024 is set aside")
    assert not R.HEADING.match("The order is stayed.")


def test_judgment_date_lines():
    m = R.JUDGMENT_DATE_LINE.match("Date on which judgment is reserved : 03.02.2025")
    assert m and R.RESERVED_WORDS.search(m.group(0))
    m = R.JUDGMENT_DATE_LINE.match("Date of pronouncement of judgment : 25.03.2025")
    assert m and R.PRONOUNCED_WORDS.search(m.group(0))
    assert R.JUDGMENT_DATE_LINE.match(" Date of Judgment                          : 05.03.2025")
    assert not R.JUDGMENT_DATE_LINE.match("Date on which Judgment is reserved: NA")


def test_signoff_and_trailer():
    for line in (
        "JUDGE",
        "JUDGE                    CHIEF   JUSTICE",
        "Joint Registrar (Judicial) ",
        "DEPUTY REGISTRAR",
    ):
        assert R.SIGNOFF_LINE.match(line) and R.SIGNOFF_WORD.search(line)
    assert not R.SIGNOFF_LINE.match("The judge heard the matter.")
    assert R.TRAILER.match("Comparing Assistant ")


def test_paragraph_starts():
    for line, label in (
        ("2.  Heard", "2."),
        ("2) Heard", "2)"),
        ("(2) Heard", "(2)"),
        ("2.1 The", "2.1"),
        ("[2] The", "[2]"),
    ):
        assert R.PARA_START.match(line).group("label") == label
    assert not R.PARA_START.match("27.06.2022, submitted her option")
    assert R.SUBLIST_START.match("(ii) to pay").group("label") == "(ii)"
    assert R.LIST_INTRO_END.search("as follows:") and R.LIST_INTRO_END.search("in the following manner: -")
    assert R.REFERENCE_END.search("the respondent No.")


def test_outcome_patterns_and_withdrawal():
    def value(sentence):
        for v, rx in R.OUTCOME_PATTERNS:
            if rx.search(sentence):
                return v
        return None

    assert value("these writ petitions stand closed without interfering") == "closed"
    assert value("the instant petition stands disposed of.") == "disposed_of"
    assert value("this bail application stands disposed of.") == "disposed_of"
    assert value("The writ appeal is partly allowed.") == "partly_allowed"
    assert R.WITHDRAW_PATTERN.search("The petitioner is permitted to withdraw the writ petition")


def test_period_and_from():
    m = R.PERIOD.search(
        "within a period of 60 (sixty) days from the date of receipt of a certified copy of this order"
    )
    assert m.group("n") == "60" and m.group("unit") == "days" and R.FROM_RECEIPT.search(m.group("from"))
    m = R.PERIOD.search("within two weeks from today")
    assert m.group("n") == "two" and R.FROM_ORDER_DATE.match(m.group("from"))
    assert R.NUMBER_WORDS["two"] == 2


def test_addressees_and_procedural_acts():
    for text in (
        "the respondent No. 2",
        "the State respondents",
        "the competent authority",
        "the Commissioner",
    ):
        assert R.ADDRESSEES.search(text), text
    assert not R.ADDRESSEES.search("the principal amount")
    assert not R.ADDRESSEES.fullmatch("Government Advocate")
    assert R.PROCEDURAL_DIRECTION_ACTS.search("shall file an affidavit")
    assert R.PROCEDURAL_DIRECTION_ACTS.search("to produce the relevant records")
    assert not R.PROCEDURAL_DIRECTION_ACTS.search("to release the arrears")


def test_reporters_seen_in_the_data():
    cases = {
        "SCC": "(2010) 2 SCC 607",
        "SCC OnLine": "2022 SCC OnLine SC 881",
        "AIR": "AIR 1990 SC 405",
        "SCR": "(1962) 3 SCR 842",
        "GLT": "2003 (3) GLT 522",
        "GLR": "(2005) 2 GLR 459",
        "GauLT": "2014 (2) GauLT 101",
        "LLJ": "(1998) II LLJ 13",
        "INSC": "2024 INSC 579",
        "neutral": "2025:GAU-AS:4917",
    }
    for reporter, citation in cases.items():
        rx = dict(R.REPORTER_PATTERNS)[reporter]
        assert rx.search(citation), reporter
