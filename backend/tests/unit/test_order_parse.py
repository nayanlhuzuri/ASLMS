"""The order reader (design `order-sections`, decisions 7 to 17 and 19; "Tests", unit): the template's parts located on
masked copies of real orders (`tests/fixtures/orders/`), the clean-up with its offsets, the pages, the paragraphs and
parts, the facts read by rules, the tags and flags, the body hash and the next-date span. No database, no network."""

from __future__ import annotations

import random
import re
from datetime import date
from pathlib import Path

import pytest

from aslms.services import order_parse as P
from aslms.services import order_parse_rules as R

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "orders"
# a synthetic CNR in place of the fixtures' mask (never a real case's)
TEST_CNR_PREFIX = "GAHC01000001"


def load(name: str) -> str:
    """The fixture as text extraction leaves it: pages joined by a form feed, the whole stripped."""
    text = (FIXTURES / f"{name}.txt").read_text(encoding="utf-8").replace("\r\n", "\n")
    return text.replace("<FF>", "\f").replace("GAHC01XXXXXX", TEST_CNR_PREFIX).strip()


def span_text(text: str, span) -> str:
    return text[span[0] : span[1]]


def _strip_ignored(src: str) -> str:
    """The cleaned form of a stretch of `full_text`, for the round trip: page markers, form feeds and whitespace
    gone."""
    src = R.PAGE_MARK.sub("", src)
    return re.sub(r"\s+", "", src.replace("\f", ""))


def assert_invariants(text: str, r: P.Parsed) -> None:
    """The invariants of `order_parse` ("Services")."""
    body = r.body_text
    b0, b1 = r.spans.get("body", [0, len(text)])
    prev_end = -1
    prev_page = 0
    for p in r.paragraphs:
        s0, s1 = p["src"]
        t0, t1 = p["txt"]
        assert b0 <= s0 < s1 <= len(text), p
        assert 0 <= t0 < t1 <= len(body), p
        assert t0 > prev_end, "paragraphs are in order and do not overlap"
        prev_end = t1
        assert _strip_ignored(body[t0:t1]) == _strip_ignored(text[s0:s1]), p
        assert p["page"] <= p["page_to"] and p["page"] >= prev_page, "pages never decrease"
        prev_page = p["page"]
    if r.paragraphs:  # the paragraphs cover the body
        assert r.paragraphs[0]["txt"][0] == 0 and r.paragraphs[-1]["txt"][1] == len(body)
    for part in r.parts:  # parts never cut a paragraph
        first = r.paragraphs[part["first"]]
        last = r.paragraphs[part["last"]]
        assert part["txt"] == [first["txt"][0], last["txt"][1]]
        assert part["src"] == [first["src"][0], last["src"][1]]
        assert all(r.paragraphs[i]["part"] == part["part"] for i in range(part["first"], part["last"] + 1))
    items = []
    if r.facts["outcome"]:
        items.append(r.facts["outcome"])
    for key in ("directions", "acts", "judgments"):
        items.extend(r.facts[key])
    for it in items:
        s0, s1 = it["src"]
        t0, t1 = it["txt"]
        assert b0 <= s0 < s1 <= b1, it
        assert 0 <= t0 < t1 <= len(body), it
        assert _strip_ignored(body[t0:t1]) == _strip_ignored(text[s0:s1]), it


# ------------------------------------------------------------------------------------------------ the template


def test_template_interim_header_spans_and_body():
    text = load("interim_template")
    r = P.parse(text, order_date=date(2026, 1, 28), napix_kind="interim")
    assert r.layout == "template" and r.form == "interim" and r.heading == "ORDER"
    assert r.printed_cnr == "GAHC010000012025"
    assert r.printed_case_no == "WP(C)/XXXX/2025"
    assert r.printed_date == date(2026, 1, 28)
    assert span_text(text, r.spans["cnr"]) == "GAHC010000012025"
    assert span_text(text, r.spans["cause_title"]).startswith("PETITIONER A")
    assert span_text(text, r.spans["cause_title"]).endswith("GUWAHATI-19")
    assert span_text(text, r.spans["advocates"]).startswith("Advocate for the Petitioner")
    assert span_text(text, r.spans["coram"]) == "BEFORE\nHONOURABLE MR. JUSTICE JUDGE A"
    assert span_text(text, r.spans["heading"]) == "ORDER"
    assert span_text(text, r.spans["date"]) == "Date :  28.01.2026"
    assert span_text(text, r.spans["signoff"]) == "JUDGE\nComparing Assistant"
    # the body excludes the title, the addresses, the advocates and the sign-off
    assert r.body_text.startswith("Heard Mr. Advocate A, learned counsel for the petitioner.")
    assert r.body_text.endswith("List this matter on 04.03.2026.")
    for absent in ("PETITIONER A", "PIN-000000", "Advocate for", "JUDGE", "Comparing Assistant", "Page No."):
        assert absent not in r.body_text
    assert r.flags == [] and r.registrar is False and r.procedural is True
    assert_invariants(text, r)


def test_page_markers_undefined_and_trailer_removed_and_lines_rejoined_across_pages():
    text = load("final_directions")
    r = P.parse(text, order_date=date(2025, 3, 10), napix_kind="final")
    assert "undefined" not in r.body_text and "Page No." not in r.body_text
    assert "Comparing Assistant" not in r.body_text and "\f" not in r.body_text
    # paragraph 2 runs over the page break and is one paragraph, joined with one space
    para2 = r.paragraphs[1]
    assert para2["label"] == "2." and para2["page"] == 1 and para2["page_to"] == 2
    t = r.body_text[para2["txt"][0] : para2["txt"][1]]
    assert "before the respondent authorities, which remains undisposed of." in t
    assert "  " not in r.body_text
    assert "\n\n" in r.body_text  # paragraphs separated by a blank line
    assert_invariants(text, r)


def test_order_date_broken_across_lines_and_registrar_date_form():
    variants = P.parse(load("interim_variants"))
    assert variants.printed_date == date(2026, 7, 29)
    assert variants.spans["date"]
    registrar = P.parse(load("registrar"))
    assert registrar.printed_date == date(2026, 7, 29)


def test_judgment_dates_block_neutral_citation_and_author():
    text = load("judgment_parts")
    r = P.parse(text, napix_kind="judgment")
    assert r.neutral_citation == "2025:GAU-AS:9999"
    assert r.printed_reserved_on == date(2025, 2, 3)
    assert r.printed_pronounced_on == date(2025, 3, 25)
    assert r.printed_date == date(2025, 3, 25)  # read from the pronouncement line
    assert r.author == "Judge D, J"
    assert r.heading == "JUDGMENT & ORDER" and r.cav is True and r.oral is False
    assert span_text(text, r.spans["judgment_dates"]).startswith("Date on which judgment is reserved")
    assert "2025:GAU-AS:9999" not in r.body_text


def test_variants_before_hon_ble_lowercase_advocates_judgment_and_order_cav():
    text = load("interim_variants")
    r = P.parse(text)
    assert r.layout == "template"
    assert span_text(text, r.spans["coram"]).startswith(":::BEFORE:::\nHON'BLE")
    assert span_text(text, r.spans["advocates"]).startswith("Advocate for the petitioner")
    assert r.heading == "JUDGMENT&ORDER" and r.cav is True
    assert r.form == "judgment"
    spaced = (
        "Page No.# 1/1\nGAHC010000012025\n"
        + "Case No. : WP(C)/1/2025\nA\nVERSUS\nB\n"
        + ("� B E F O R E �\nHON�BLE THE CHIEF JUSTICE\nJUDGMENT AND ORDER (ORAL)\n12-04-2023\nHeard.\nJUDGE")
    )
    s = P.parse(spaced)
    assert s.layout == "template" and s.oral is True and s.printed_date == date(2023, 4, 12)


def test_linked_case_entries_as_printed_with_their_spans():
    """The row 258 contract (b): each `Linked Case :` entry as printed, the span of its block and of its title."""
    text = load("common_order")
    r = P.parse(text)
    assert r.heading == "COMMON ORDER"
    assert [lc["case_no"] for lc in r.linked_cases] == ["WP(C)/YYYY/2023", None]
    first, second = r.linked_cases
    assert span_text(text, first["src"]).startswith("Linked Case : WP(C)/YYYY/2023")
    assert span_text(text, first["title"]) == (
        "PETITIONER F\nS/O PARENT G\n R/O MASKED\n VERSUS\nTHE STATE OF ASSAM AND 2 ORS"
    )
    assert span_text(text, second["title"]) == "PETITIONER G\n VERSUS\nTHE STATE OF ASSAM"
    assert "Linked Case" not in r.body_text and "PETITIONER F" not in r.body_text


def test_cause_title_span_ends_at_advocates_linked_case_or_coram():
    """The row 258 contract (a)."""
    at_advocates = load("interim_template")
    r = P.parse(at_advocates)
    assert span_text(at_advocates, r.spans["cause_title"]).endswith("KAHILIPARA, GUWAHATI-19")
    at_linked = load("common_order").replace(
        "Advocate for the Petitioner     : MR. ADVOCATE L \nAdvocate for the Respondent : SC, REVENUE  \n", ""
    )
    r = P.parse(at_linked)
    assert span_text(at_linked, r.spans["cause_title"]).endswith("REVENUE DEPARTMENT")
    at_coram = "\n".join(
        ["Page No.# 1/1", "GAHC010000012025", "Case No. : WP(C)/1/2025", "PARTY A", "VERSUS", "PARTY B", "BEFORE",
         "HONOURABLE MR. JUSTICE JUDGE A", "ORDER", "01.02.2025", "List on 03.03.2025.", "JUDGE"]
    )  # fmt: skip
    r = P.parse(at_coram)
    assert span_text(at_coram, r.spans["cause_title"]) == "PARTY A\nVERSUS\nPARTY B"


def test_off_template_kept_whole_with_flag_and_no_title_span():
    """The row 258 contract (c)."""
    text = load("off_template")
    r = P.parse(text)
    assert r.layout == "whole" and "off_template" in r.flags
    assert not {"cause_title", "advocates", "coram", "heading"} & set(r.spans)
    assert r.printed_cnr == "GAHC010000012020" and r.printed_case_no == "Cont.Cas(C)/XXX/2020"
    assert "List after two weeks." in r.body_text
    assert "Comparing Assistant" not in r.body_text and "THE GAUHATI HIGH COURT" not in r.body_text
    assert_invariants(text, r)
    # a coram marker found, but no heading and no date after it: still `whole`, and the three spans are absent
    with_coram = "\n".join(
        ["Page No.# 1/1", "GAHC010000012025", "Case No. : WP(C)/1/2025", "PARTY A", "VERSUS", "PARTY B",
         "Advocate for the Petitioner : MR. ADVOCATE A", "Advocate for the Respondent : SC, REVENUE", "BEFORE",
         "HONOURABLE MR. JUSTICE JUDGE A", "", "Heard the learned counsel for the parties.",
         "List after two weeks.", "JUDGE"]
    )  # fmt: skip
    r = P.parse(with_coram)
    assert r.layout == "whole" and "off_template" in r.flags
    assert not {"cause_title", "advocates", "coram", "heading"} & set(r.spans)
    assert r.printed_cnr == "GAHC010000012025" and r.printed_case_no == "WP(C)/1/2025"
    assert "List after two weeks." in r.body_text
    assert_invariants(with_coram, r)


def test_pages_from_printed_markers_and_form_feeds_and_leading_blank_page_flag():
    text = load("final_directions")
    pm = P.pages(text)
    assert [n for _, n in pm.marks] == [1, 2, 3] and len(pm.feeds) == 2 and pm.differ is False
    assert pm.page(0) == 1 and pm.page(text.index("authorities, which")) == 2
    # no printed markers: the form feeds count
    bare = "first page text\n\fsecond page text\n\fthird"
    pm = P.pages(bare)
    assert pm.page(0) == 1 and pm.page(bare.index("second")) == 2 and pm.page(bare.index("third")) == 3
    # a blank first page lost by extraction's strip: the printed marker wins and the reading is flagged
    lead = load("leading_blank")
    r = P.parse(lead)
    assert "page_marks_differ" in r.flags
    assert r.paragraphs[0]["page"] == 3


def test_offsets_round_trip_src_and_txt_for_every_paragraph_and_fact():
    for name in (
        "interim_template",
        "interim_variants",
        "registrar",
        "final_directions",
        "judgment_parts",
        "common_order",
        "off_template",
        "leading_blank",
    ):
        text = load(name)
        r = P.parse(text, order_date=date(2025, 3, 10))
        assert_invariants(text, r)
        for p in r.paragraphs:  # PostgreSQL's substr(full_text, s + 1, e - s) is text[s:e]
            s, e = p["src"]
            assert text[s:e] == text[s : s + (e - s)]


def test_paragraphs_numbered_sublists_and_unnumbered_bodies():
    r = P.parse(load("judgment_parts"))
    assert [p["label"] for p in r.paragraphs] == ["1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9."]
    sub = "\n".join(
        ["Page No.# 1/1", "GAHC010000012025", "Case No. : WP(C)/1/2025", "A", "VERSUS", "B", "BEFORE",
         "HONOURABLE MR. JUSTICE JUDGE A", "ORDER", "01.02.2025",
         "1. The respondents are directed as follows:", "(a) to pay the arrears;", "(b) to file a report.",
         "2. List on 03.03.2025.", "JUDGE"]
    )  # fmt: skip
    r = P.parse(sub)
    assert [p["label"] for p in r.paragraphs] == ["1.", "(a)", "(b)", "2."]
    unnumbered = "\n".join(
        ["Page No.# 1/1", "GAHC010000012025", "Case No. : WP(C)/1/2025", "A", "VERSUS", "B", "BEFORE",
         "HONOURABLE MR. JUSTICE JUDGE A", "ORDER", "01.02.2025",
         "Heard Mr. Advocate A, learned counsel for the petitioner, and the learned",
         "Standing Counsel for the respondents at some length today.",
         "Perused the records.",
         "The respondents seek time to obtain instructions in the matter before the",
         "next date of hearing, which is allowed in the interest of justice.",
         "JUDGE"]
    )  # fmt: skip
    r = P.parse(unnumbered)
    assert len(r.paragraphs) == 2 and all(p["label"] is None for p in r.paragraphs)
    assert r.body_text.split("\n\n")[0].endswith("Perused the records.")


def test_interim_body_is_one_part_never_split():
    r = P.parse(load("interim_template"), napix_kind="interim")
    assert [p["part"] for p in r.parts] == ["body"]
    r = P.parse(load("registrar"), napix_kind="interim")
    assert len(r.paragraphs) == 2 and [p["part"] for p in r.parts] == ["body"]


def test_judgment_parts_from_headings_and_phrases_never_cut_a_paragraph():
    text = load("judgment_parts")
    r = P.parse(text, napix_kind="judgment")
    assert [p["part"] for p in r.parts] == [
        "opening",
        "facts",
        "petitioner_submissions",
        "respondent_submissions",
        "issues",
        "reasoning",
        "conclusion",
    ]
    reasoning = next(p for p in r.parts if p["part"] == "reasoning")
    assert (reasoning["first"], reasoning["last"], reasoning["page"]) == (5, 6, 3)
    assert_invariants(text, r)
    # a heading word opens a part too
    headed = text.replace("5.      The question that arises", "5.      ISSUES. The question that arises")
    assert "issues" in [p["part"] for p in P.parse(headed, napix_kind="judgment").parts]


def test_outcome_main_matter_only_not_ia_and_last_sentence_wins():
    def outcome(body: str) -> str | None:
        text = "\n".join(
            ["Page No.# 1/1", "GAHC010000012025", "Case No. : WP(C)/1/2025", "A", "VERSUS", "B", "BEFORE",
             "HONOURABLE MR. JUSTICE JUDGE A", "ORDER", "01.02.2025", body, "JUDGE"]
        )  # fmt: skip
        return P.parse(text).outcome

    assert outcome("The I.A. stands disposed of.") is None
    assert outcome("The interlocutory application is allowed.") is None
    assert outcome("Misc. Case No. 12/2025 stands dismissed.") is None
    assert outcome("The writ petition is accordingly dismissed.") == "dismissed"
    assert outcome("The writ petition is dismissed as withdrawn.") == "withdrawn"
    assert outcome("The petitioner is permitted to withdraw the writ petition.") == "withdrawn"
    assert outcome("The appeal is allowed in part.") == "partly_allowed"
    assert outcome("The contempt proceeding is closed.") == "closed"
    assert outcome("The contempt petition is not dismissed for default.") is None
    # the last sentence about the main matter wins
    assert outcome("The writ petition was dismissed earlier. Now the writ petition is allowed.") == "allowed"
    r = P.parse(load("final_directions"))
    assert r.outcome == "disposed_of" and r.form == "final"
    assert r.facts["outcome"]["text"] == "6. With the above direction, the writ petition stands disposed of."


def test_directions_compliance_vs_procedural_period_and_due_on_only_from_order_date():
    r = P.parse(load("final_directions"), order_date=date(2025, 3, 10))
    compliance, procedural = r.facts["directions"]
    assert compliance["kind"] == "compliance" and compliance["addressee"] == "the respondent No. 2"
    assert compliance["period"] == {
        "n": 30,
        "unit": "days",
        "from": "order_date",
        "phrase": "within a period of 30 (thirty) days from the date of this order",
    }
    assert compliance["due_on"] == "2025-04-09" and compliance["page"] == 2
    assert procedural["kind"] == "procedural" and procedural["period"] is None
    j = P.parse(load("judgment_parts"), order_date=date(2025, 3, 25))
    (d,) = j.facts["directions"]
    assert (
        d["kind"] == "compliance"
        and d["period"]["from"] == "receipt_of_copy"
        and d["period"]["unit"] == "months"
    )
    assert d["due_on"] is None  # receipt of a certified copy is not known
    # the registrar's direction to the petitioner is not a direction to the State
    assert P.parse(load("registrar")).facts["directions"] == []


def test_acts_and_provisions_with_counts():
    r = P.parse(load("judgment_parts"))
    acts = {(a["act_key"], a["kind"]): a for a in r.facts["acts"]}
    pay = acts[("assam services pay act 2017", "section")]
    assert pay["act"] == "Assam Services (Pay) Act, 2017" and pay["provisions"] == ["3"] and pay["count"] == 2
    assert pay["page"] == 2
    assert acts[("constitution of india", "article")]["provisions"] == ["14"]
    short = (
        "Page No.# 1/1\nGAHC010000012025\nCase No. : X\nA\nBEFORE\nHONOURABLE MR. JUSTICE J\nORDER\n01.02.2025\n"
        + (
            "Bail is sought under Section 483 of the BNSS, 2023 in a case under Section 21(b)/29 of NDPS Act and "
            "Sections 302 and 34 IPC; Order 39 Rule 1 CPC is cited.\nJUDGE"
        )
    )
    got = {(a["act_key"], tuple(a["provisions"]), a["kind"]) for a in P.parse(short).facts["acts"]}
    assert ("bnss 2023", ("483",), "section") in got
    assert ("ndps act", ("21(b)/29",), "section") in got
    assert ("ipc", ("302 and 34",), "section") in got
    assert ("cpc", ("Order 39 Rule 1",), "order") in got


def test_judgments_cited_reporters_and_case_name():
    r = P.parse(load("judgment_parts"))
    cited = {j["citation"]: j for j in r.facts["judgments"]}
    scc = cited["(2015) 4 SCC 123"]
    assert scc["reporter"] == "SCC" and scc["year"] == 2015 and scc["count"] == 2
    assert scc["case_name"] == "State of Assam v. Party K"
    assert cited["AIR 2010 SC 456"]["case_name"] == "Party L vs. Union of India"
    glt = cited["2018 (3) GLT 789"]
    assert glt["reporter"] == "GLT" and glt["case_name"] is None
    assert {j["reporter"] for j in r.facts["judgments"]} == {"SCC", "AIR", "GLT"}


def test_form_judgment_final_interim_and_registrar_procedural_rules():
    assert P.form("JUDGMENT & ORDER", None, False) == "judgment"
    assert P.form("ORDER", "judgment", False) == "judgment"
    assert P.form("ORDER", "final", False) == "final"
    assert P.form("ORDER", None, True) == "final"
    assert P.form("ORDER", "interim", False) == "interim"
    reg = P.parse(load("registrar"), napix_kind="interim")
    assert reg.registrar is True and reg.procedural is True
    # a Lawazima dismissal for default: final with an outcome, still registrar and procedural
    default = load("registrar").replace(
        "Let the matter be listed before the Lawazima Court again on 15.09.2026.",
        "The writ petition stands dismissed for default.",
    )
    r = P.parse(default, napix_kind="final")
    assert (r.form, r.outcome, r.registrar, r.procedural) == ("final", "dismissed", True, True)
    assert P.parse(load("interim_template"), napix_kind="interim").procedural is True
    # a stay is substantive
    stay = load("interim_template").replace(
        "Issue notice", "Issue notice. Till then, status quo shall be maintained"
    )
    assert P.parse(stay, napix_kind="interim").procedural is False
    # judgments and final orders are substantive
    assert P.parse(load("final_directions"), napix_kind="final").procedural is False


def test_body_hash_ignores_whitespace_only():
    assert P.body_hash("List  after\n\nfour weeks. ") == P.body_hash("List after four weeks.")
    assert P.body_hash("List after four weeks.") != P.body_hash("list after four weeks.")
    assert P.body_hash("List after four weeks.") != P.body_hash("List after four weeks")
    a = P.parse(load("interim_template"))
    b = P.parse(load("interim_template").replace("PETITIONER A", "PETITIONER Z"))
    assert a.body_sha256 == b.body_sha256  # the title is not the body


def test_capped_and_empty_body_flags():
    text = load("interim_template")
    big = text.replace("Issue notice", "Issue notice " + "x " * (R.MAX_PARSE_CHARS // 2))
    r = P.parse(big)
    assert "capped" in r.flags and r.text_chars == len(big)
    empty = "\n".join(
        ["Page No.# 1/1", "GAHC010000012025", "Case No. : WP(C)/1/2025", "A", "VERSUS", "B", "BEFORE",
         "HONOURABLE MR. JUSTICE JUDGE A", "ORDER", "01.02.2025", "JUDGE", "Comparing Assistant"]
    )  # fmt: skip
    r = P.parse(empty)
    assert r.body_text == "" and "empty_body" in r.flags and r.paragraphs == [] and r.parts == []


def test_next_date_span_tolerant_match_and_not_found():
    r = P.parse(load("interim_template"))
    span = P.next_date_span(r.body_text, "List this matter on 04.03.2026.")
    assert span is not None and r.body_text[span[0] : span[1]] == "List this matter on 04.03.2026"
    # whitespace and punctuation differences still match
    assert (
        P.next_date_span("List  this\nmatter on 04 . 03 . 2026", "List this matter on 04.03.2026") is not None
    )
    assert P.next_date_span(r.body_text, "List the matter after vacation.") is None
    assert P.next_date_span(r.body_text, None) is None and P.next_date_span("", "x") is None


def test_parse_never_raises_on_garbage_text():
    rng = random.Random(250)
    alphabet = "abcXYZ 0123456789.:/()\n\f\t#-–’�"
    samples = ["", " ", "\f\f", "Page No.# 1/1", "BEFORE\nORDER\nJUDGE", "\x00\x01\x02binary\xff"]
    samples += ["".join(rng.choice(alphabet) for _ in range(rng.randint(1, 3000))) for _ in range(150)]
    samples.append(load("judgment_parts")[::-1])
    for s in samples:
        r = P.parse(s)
        assert r.layout in ("template", "whole")
        assert r.form in ("interim", "final", "judgment")
        if r.outcome:
            assert r.form != "interim"
        if r.registrar:
            assert r.procedural
        if r.layout == "whole":
            assert "off_template" in r.flags


def test_no_model_or_network_import():
    """Decision 1: the reader is pure Python; it imports neither the integration layer nor any HTTP or model
    library, and touches no database."""
    for module in ("order_parse.py", "order_parse_rules.py"):
        src = (Path(P.__file__).parent / module).read_text(encoding="utf-8")
        imports = re.findall(r"^\s*(?:from|import)\s+([\w.]+)", src, re.M)
        for name in imports:
            assert not name.startswith("aslms.integration"), name
            assert name.split(".")[0] not in {
                "httpx",
                "requests",
                "urllib",
                "socket",
                "sqlalchemy",
                "psycopg",
                "torch",
                "transformers",
                "ollama",
                "openai",
                "anthropic",
            }, name
            assert name in {"__future__", "re", "bisect", "hashlib", "statistics", "dataclasses", "datetime",
                            "typing", "aslms.services"}, name  # fmt: skip


@pytest.mark.parametrize(
    "variant", ["Date :  --19.03.2025", "Date : -19.03.2025", "19-03-2025", "19/03/2025"]
)
def test_order_date_line_variants(variant):
    text = "\n".join(
        ["Page No.# 1/1", "GAHC010000012025", "Case No. : WP(C)/1/2025", "A", "VERSUS", "B", "BEFORE",
         "HONOURABLE MR. JUSTICE JUDGE A", "ORDER", variant, "List on 03.04.2025.", "JUDGE"]
    )  # fmt: skip
    assert P.parse(text).printed_date == date(2025, 3, 19)
