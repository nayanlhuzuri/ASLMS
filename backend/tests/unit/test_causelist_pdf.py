"""Parser tests against real Gauhati High Court cause lists (tests/fixtures)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from aslms.integration.ghc.causelist_pdf import (
    date_from_filename,
    is_counsel_code,
    merge_advocates,
    normalise_counsel_code,
    parse_causelist,
)

FIX = Path(__file__).resolve().parents[1] / "fixtures"


def test_lawazima_list_parses_every_row_with_cnr() -> None:
    pl = parse_causelist(FIX / "ghc_lawazima_01-09-2025.pdf")
    assert pl.list_type == "lawazima"
    assert pl.list_date == date(2025, 9, 1)
    assert len(pl.rows) == 16
    assert all(r.cnr and len(r.cnr) == 16 and r.cnr.startswith("GAHC") for r in pl.rows)
    assert pl.warnings == []
    first = pl.rows[0]
    assert first.case_no_text == "WP(C)/7535/2017"
    assert first.petitioner_text == "NIZAM MUSAHARI"
    assert first.respondent_text.startswith("THE STATE OF ASSAM")
    assert first.court_no == "111"
    assert first.counsel_codes == ("GA, ASSAM",)
    assert first.section == "ORDERS"
    assert "CHINMOY BARUAH" in (first.bench_text or "")


def test_connected_matters_and_parent_cases() -> None:
    rows = parse_causelist(FIX / "ghc_lawazima_01-09-2025.pdf").rows
    ia = rows[1]
    assert ia.case_no_text == "I.A.(Civil)/3976/2018"
    assert ia.parent_case_no_text == "RSA/301/2018"
    connected = rows[2]
    assert connected.case_no_text == "RSA/301/2018"
    assert connected.connected_to == ia.sr_no
    assert sum(1 for r in rows if r.connected_to) == 3
    # sr_no is the position in the list and unique, the printed serial is kept separately
    assert [r.sr_no for r in rows] == list(range(1, 17))


def test_daily_list_single_entry() -> None:
    pl = parse_causelist(FIX / "ghc_daily_23-12-2024.pdf")
    assert pl.list_type == "daily" and pl.list_date == date(2024, 12, 23)
    assert [(r.cnr, r.case_no_text) for r in pl.rows] == [("GAHC010277142024", "WA/435/2024")]
    assert pl.rows[0].counsel_codes == ("DY.S.G.I.", "SC, HEALTH")


def test_parse_from_bytes_matches_path() -> None:
    path = FIX / "ghc_lawazima_01-09-2025.pdf"
    a = parse_causelist(path)
    b = parse_causelist(data=path.read_bytes())
    assert [r.cnr for r in a.rows] == [r.cnr for r in b.rows]


def test_counsel_codes() -> None:
    assert is_counsel_code("SC, EDU") and is_counsel_code("GA, ASSAM") and is_counsel_code("PP, ASSAM")
    assert is_counsel_code("SC, P AND R.D.") and is_counsel_code("DY.S.G.I.")
    assert not is_counsel_code("MR. N J KHATANIAR")
    assert normalise_counsel_code("sc ,  sec. edu.") == "SC, SEC. EDU."


def test_merge_advocates_joins_wrapped_names() -> None:
    assert merge_advocates(["MR. NAYAN JYOTI", "KHATANIAR"]) == ["MR. NAYAN JYOTI KHATANIAR"]
    assert merge_advocates(["MR H R A CHOUDHURY(R-", "1,2,3)", "GA, ASSAM"]) == [
        "MR H R A CHOUDHURY(R-1,2,3)",
        "GA, ASSAM",
    ]
    assert merge_advocates(["SC, FINANCE AND", "TAXATION", "SC, HDFC BANK"]) == [
        "SC, FINANCE AND TAXATION",
        "SC, HDFC BANK",
    ]
    assert merge_advocates(["MR. A Y CHOUDHURY", "I HASHMI", "SC, FOREST"]) == [
        "MR. A Y CHOUDHURY",
        "I HASHMI",
        "SC, FOREST",
    ]


def test_date_from_filename() -> None:
    assert date_from_filename("data/causelists/01-09-2025/Daily_01-09-2025.pdf") == date(2025, 9, 1)
    assert date_from_filename("nothing.pdf") is None
