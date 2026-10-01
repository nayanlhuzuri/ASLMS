"""The cause-list parser on four real lists: two NAPIX Show Cause List PDFs (Lawazima, bench 2048), the first
three pages of a website Daily list (Division Bench-I: sections, WITH, applications, caveats, a page break inside
the block) and a website Vacation Court list. Expected values were read off the PDFs by hand."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from aslms.parsing.causelist_pdf import parse_causelist_pdf, split_advocates

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "causelists"


@pytest.fixture(scope="module")
def napix_2026():
    return parse_causelist_pdf(FIXTURES / "napix_lawazima_bench2048_2026-09-03.pdf")


@pytest.fixture(scope="module")
def napix_2025():
    return parse_causelist_pdf(FIXTURES / "napix_lawazima_bench2048_2025-01-06.pdf")


@pytest.fixture(scope="module")
def daily():
    return parse_causelist_pdf(FIXTURES / "website_daily_01-04-2025_p1-3.pdf")


@pytest.fixture(scope="module")
def vacation():
    return parse_causelist_pdf(FIXTURES / "website_vacation_01-07-2026.pdf")


def test_masthead_list_type_and_date(napix_2026, napix_2025, daily, vacation):
    assert (napix_2026.list_type, napix_2026.list_date) == ("lawazima", date(2026, 9, 3))
    assert (napix_2025.list_type, napix_2025.list_date) == ("lawazima", date(2025, 1, 6))
    assert (daily.list_type, daily.list_date) == ("daily", date(2025, 4, 1))
    assert (vacation.list_type, vacation.list_date) == ("vacation", date(2026, 7, 1))
    assert vacation.list_type_text == "VACATION COURT CAUSELIST"


def test_court_block(napix_2026, daily, vacation):
    (court,) = napix_2026.courts
    assert court.court_no == "111"
    assert court.bench_text == "JOINT REGISTRAR (JUDL.) MR. CHINMOY BARUAH"
    (court,) = daily.courts
    assert court.court_no == "1"
    assert court.judges == ["HONOURABLE THE CHIEF JUSTICE", "HONOURABLE MR. JUSTICE N. UNNI KRISHNAN NAIR"]
    assert court.notes == ["[DIVISION BENCH-I]"]
    (court,) = vacation.courts
    assert court.court_no == "15" and court.notes[0].startswith("[COURT PROCEEDING")


def test_every_entry_has_its_cnr_from_the_link(napix_2026, napix_2025, daily, vacation):
    for parsed, n in ((napix_2026, 7), (napix_2025, 9), (daily, 18), (vacation, 3)):
        assert len(parsed.entries) == n
        assert all(e.cnr for e in parsed.entries), [e.case_no_text for e in parsed.entries if not e.cnr]
        assert len({e.cnr for e in parsed.entries}) == n
        assert parsed.warnings == []
    e1 = napix_2026.entries[0]
    assert (e1.printed_sr_no, e1.case_no_text, e1.cnr) == ("1", "CRP/157/2025", "GAHC010231202025")
    assert (napix_2026.entries[1].case_no_text, napix_2026.entries[1].cnr) == (
        "WP(C)/1091/2026",
        "GAHC010018372026",
    )
    assert (napix_2025.entries[0].case_no_text, napix_2025.entries[0].cnr) == (
        "WP(C)/4189/2016",
        "GAHC010020342016",
    )


def test_parties_and_advocates(napix_2026):
    e = napix_2026.entries[1]
    assert e.petitioner_text == "BIREN DAS @ BIREN CH DAS"
    assert e.respondent_text == "THE STATE OF ASSAM AND 10 ORS"
    assert e.pet_advocates == ["MR. ANANTA RAM MEDHI", "MS. K MEDHI", "D NATH", "MD. K AHMED"]
    assert e.res_advocates == ["MR. D SARMA(R11)", "MR P DAS(R11)", "MR K J PATHAK(R11)", "MS N BARUAH(R11)"]
    assert e.res_counsel_codes == ["GA, ASSAM", "SC, REVENUE", "SC, PWD"]
    assert e.counsel_codes == ["GA, ASSAM", "SC, REVENUE", "SC, PWD"]
    assert e.section == "ORDERS"
    e5 = napix_2026.entries[4]
    assert e5.res_counsel_codes == ["DY.S.G.I."] and e5.res_advocates == []


def test_sections_with_and_applications(daily):
    by_seq = {e.seq: e for e in daily.entries}
    e1 = by_seq[1]
    assert e1.section == "PRONOUNCEMENT OF JUDGEMENT / ORDER"
    assert e1.case_no_text == "WP(C)/3589/2023" and e1.remarks == "CAVT. NO.06262/023,"
    assert e1.res_advocates == ["MR. S C KEYAL", "FOR CAVEATOR"]
    e2 = by_seq[2]
    assert e2.section == "FOR ORDERS"
    assert e2.case_no_text == "I.A.(Civil)/1427/2024"
    assert e2.parent_case_no == "WA/16001/2023" and e2.remarks == "FIXED | in WA/16001/2023"
    assert e2.res_counsel_codes == ["DY.S.G.I.", "SC, A A I"]
    e3 = by_seq[3]  # WITH, no serial: the parent appeal listed by its filing number
    assert e3.printed_sr_no is None and e3.is_connected and e3.is_filing_number
    assert e3.case_no_text == "WA/16001/2023" and e3.cnr == "GAHC010295372023"
    e4 = by_seq[4]
    assert e4.section == "HEARING" and e4.printed_sr_no == "3" and e4.remarks == "FIXED"
    assert e4.pet_counsel_codes == ["SC, REVENUE AND DISASTER MANAGEMENT DEPT"]
    assert e4.res_counsel_codes == ["GA, ASSAM"]
    assert "MR. P D NAIR (R1)" in e4.res_advocates and len(e4.res_advocates) == 8
    e6 = by_seq[6]
    assert e6.res_counsel_codes == ["SC, SEC. EDU.", "SR. GA, ASSAM", "SC, SEBA"]
    e7 = by_seq[7]
    assert e7.res_advocates == ["MS. D S NEOG"] and e7.res_counsel_codes == [
        "GA, ASSAM",
        "SC, IRRIGATION DEPTT.",
    ]


def test_page_break_inside_the_block_and_split_annotations(daily):
    by_seq = {e.seq: e for e in daily.entries}
    e8 = by_seq[8]
    assert e8.page == 2 and e8.printed_sr_no == "6" and e8.case_no_text == "WA/418/2023"
    assert e8.res_advocates[0] == "MR. M K CHOUDHURY (r-1,2,3)"
    e9 = by_seq[9]
    assert e9.is_connected and e9.printed_sr_no is None and e9.parent_case_no == "WA/418/2023"
    e10 = by_seq[10]  # WITH above a serial-numbered case
    assert e10.is_connected and e10.printed_sr_no == "7" and e10.case_no_text == "WP(C)/4338/2019"
    assert e10.res_counsel_codes == ["GA, ASSAM", "SC, AG", "SC, FINANCE"]
    e15 = by_seq[15]
    assert e15.res_counsel_codes == ["SC, AG (A AND E)", "SC, HEALTH", "SC, K A A C"]
    e16 = by_seq[16]  # the State as petitioner
    assert e16.pet_counsel_codes == ["GA, ASSAM"] and e16.pet_advocates == []
    e17 = by_seq[17]
    assert e17.res_counsel_codes == ["SC, INDUSTRIES AND COMMERCE"]
    assert by_seq[18].printed_sr_no == "15"


def test_vacation_list(vacation):
    e1, e2, e3 = vacation.entries
    assert e1.section == "DELIVERY OF JUDGEMENT" and e1.remarks == "(AT 10:30 AM)"
    assert e2.is_connected and e2.printed_sr_no == "2"
    assert e2.res_counsel_codes == ["SC, FOREST"] and e3.res_counsel_codes == ["SC, FOREST"]
    assert len(e2.pet_advocates) == 12


def test_split_advocates_rules():
    adv, codes = split_advocates(
        [
            "MS. D S NEOG, SC,",
            "IRRIGATION DEPTT.",
            "MR X",
            "SC, REVENUE AND",
            "DISASTER MANAGEMENT",
            "DEPT",
            "MR. M K CHOUDHURY (r-",
            "1,2,3)",
            "GA, ASSAM",
            "DY.S.G.I.",
        ]
    )
    assert adv == ["MS. D S NEOG", "MR X", "MR. M K CHOUDHURY (r-1,2,3)"]
    assert codes == [
        "SC, IRRIGATION DEPTT.",
        "SC, REVENUE AND DISASTER MANAGEMENT DEPT",
        "GA, ASSAM",
        "DY.S.G.I.",
    ]


def test_bytes_input(napix_2026):
    data = (FIXTURES / "napix_lawazima_bench2048_2026-09-03.pdf").read_bytes()
    parsed = parse_causelist_pdf(data)
    assert [e.cnr for e in parsed.entries] == [e.cnr for e in napix_2026.entries]
