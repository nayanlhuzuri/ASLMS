"""Quick facts from the case record, the pure rules (design `assistant-polish`, decisions 11 to 13, "Tests", unit):
recognising whole-question frames, the next-hearing wording before row 199, and the wording of the other five facts.
No database and no model."""

from __future__ import annotations

import ast
import re
from datetime import date
from pathlib import Path

import pytest

from aslms.services import assistant_facts as af

ASLMS = Path(__file__).resolve().parents[2] / "aslms"
TODAY = date(2026, 10, 28)  # a Wednesday


# ------------------------------------------------------------------------------------------------ recognising


def test_recognise_owner_questions():
    assert af.recognise("when is the next date") == ("next_hearing",)
    assert af.recognise("who are the parties") == ("parties",)
    assert af.recognise("when is the next hearing date as per the latest court order?") == ("next_hearing",)
    assert af.recognise("Who's the judge?") == ("bench",)
    assert af.recognise("parties and advocates") == ("parties", "advocates")


POSITIVES = {
    "next_hearing": [
        "What is the next hearing date?",
        "when is the date of hearing",
        "When is the listing date of this case?",
        "what is next listing",
        "When will the case be listed next?",
        "when will this matter be heard",
        "when is it coming up",
        "when will it be taken up next",
        "When will the matter come up?",
        "Next hearing?",
        "the next listing date",
        "next date",
        "The next date of hearing, please.",
        "Please tell me the next date in this case.",
        "When is the next date according to the last order?",
        "next hearing from the most recent court order",
        "Kindly let me know when will the case be heard",  # two fillers, then a frame
    ],
    "parties": [
        "Who are the petitioners?",
        "who is the respondent",
        "Who were the parties in this case?",
        "names of the parties",
        "list the respondents",
        "Name of petitioner",
        "parties",
        "the petitioners names",
        "Who filed the case?",
        "who has filed this case",
        "who brought the petition",
        "Who is the case against?",
        "who is it filed against",
        "May I know the parties of this matter?",
    ],
    "advocates": [
        "Who are the advocates?",
        "who is the lawyer for the petitioner",
        "Who is the counsel for the State?",
        "who were the counsels for the respondents",
        "Who appears for the government?",
        "who is appearing for the petitioners",
        "names of the advocates",
        "list of lawyers",
        "counsel",
        "the advocates names",
    ],
    "status": [
        "What is the status?",
        "What's the current case status of this case?",
        "status",
        "Is the case still pending?",
        "is it disposed",
        "is this case closed",
        "Is the matter over?",
        "Has the case been disposed of?",
        "was it decided",
        "has this case been closed",
        "pending or disposed?",
        "Is it disposed or pending?",
        "can you tell me the status",
    ],
    "last_order": [
        "When was the last order passed?",
        "what is the date of the latest order",
        "date of most recent order",
        "When was the previous order made?",
        "the last order date",
        "latest order date",
        "When did the court last pass an order?",
        "when did the court pass the latest order",
    ],
    "bench": [
        "Which bench?",
        "Which judge is the case before?",
        "what court is it in",
        "Which bench is this case listed before?",
        "Before which bench is it listed?",
        "before whom judge",  # the table's frame as written
        "before what bench is the case pending",
        "Who are the judges?",
        "who is the bench",
        "the coram",
        "judge",
        "Tell me the bench please.",
    ],
}


@pytest.mark.parametrize(
    ("fact", "question"), [(fact, q) for fact, qs in POSITIVES.items() for q in qs], ids=lambda v: str(v)[:40]
)
def test_recognise_each_frame(fact, question):
    assert af.recognise(question) == (fact,)


def test_recognise_two_facts_in_the_order_asked():
    assert af.recognise("Who is the judge and when is the next hearing?") == ("bench", "next_hearing")
    assert af.recognise("status and last order date") == ("status", "last_order")
    assert af.recognise("petitioners and respondents") == ("parties",)  # the same fact once


@pytest.mark.parametrize(
    "question",
    [
        "What did the last order direct?",
        "so me as the head of the department, what do i need to do?",
        "summarize the whole case.",
        "who are the parties and what did they argue",
        "next date and parties and status",
        "মোকৰ্দমাখনৰ পৰৱৰ্তী শুনানিৰ তাৰিখ কেতিয়া?",
        "Who is the owner department?",
        "what is the stage of the file",
        "the last order",
        "next date and",
        "and status",
        "",
        "   ",
        "please",
    ],
)
def test_recognise_refuses_partial_and_content_questions(question):
    assert af.recognise(question) is None


def test_normalise():
    assert af.normalise("Who’s the JUDGE?!") == "who is the judge"
    assert af.normalise("What's the court's  next-date") == "what is the court next date"


# ------------------------------------------------------------------------------------------------ next hearing


def _nh(
    *,
    court=None,
    purpose=None,
    basis=None,
    on=None,
    order_date=None,
    words=None,
    differs=None,
    differs_order=None,
    disposed=False,
    disposal=None,
):
    return af.NextHearing(
        court_date=court,
        purpose=purpose,
        basis=basis,
        date=on,
        order_date=order_date,
        basis_words=words,
        differs_on=differs,
        differs_order_date=differs_order,
        disposed=disposed,
        disposal_date=disposal,
    )


def _lines(**kw) -> list[str]:
    return af._next_lines(_nh(**kw), TODAY)


def test_next_hearing_wording_from_the_one_value():
    """Row 199 (design next-date-direct, decision 11): the quick fact states the case's one next hearing."""
    # disposed
    assert _lines(disposed=True, disposal=date(2026, 9, 1), basis="court", on=date(2026, 11, 2)) == [
        "The case was disposed of on 01 Sep 2026; no further hearing is listed [S1]."
    ]
    # the court's record, with its purpose
    assert _lines(court=date(2026, 11, 2), purpose="ADMISSION", basis="court", on=date(2026, 11, 2)) == [
        "Next hearing: Monday 02 Nov 2026, for ADMISSION (the court's record) [S1]."
    ]
    assert _lines(basis="court", on=date(2026, 11, 2)) == [
        "Next hearing: Monday 02 Nov 2026 (the court's record) [S1]."
    ]
    # the court's record and an exact order date that differs
    assert _lines(
        basis="court", on=date(2026, 11, 2), differs=date(2026, 11, 5), differs_order=date(2026, 10, 15)
    ) == [
        "Next hearing: Monday 02 Nov 2026 (the court's record) [S1].",
        "The order of 15 Oct 2026 gives 05 Nov 2026; the court's record is used [S1].",
    ]
    # an exact date read from the order (the owner's WP(C)/2615/2026)
    assert _lines(
        court=date(2026, 10, 15), basis="order", on=date(2026, 11, 5), order_date=date(2026, 10, 15)
    ) == ["Next hearing: Thursday 05 Nov 2026 (given in the order of 15 Oct 2026) [S1]."]
    # a period counted from the order, shown as around
    assert _lines(
        basis="around", on=date(2026, 12, 1), order_date=date(2026, 10, 1), words="after 2 months"
    ) == ["Next hearing: around Tuesday 01 Dec 2026 (after 2 months, the order of 01 Oct 2026) [S1]."]
    # a date entered by hand where the court gave none
    assert _lines(basis="manual", on=date(2026, 11, 9)) == [
        "Next hearing: Monday 09 Nov 2026 (entered by hand; the court has given no date) [S1]."
    ]
    # the court's last date, passed (an ultimatum)
    assert _lines(basis="court", on=date(2026, 10, 15)) == [
        "The last date the court fixed was 15 Oct 2026, which has passed; no later date is held yet [S1]."
    ]
    # nothing held
    assert _lines() == ["No next hearing date is held for this case yet [S1]."]
    # today and tomorrow, on the IST day
    assert _lines(basis="court", on=TODAY) == [
        "Next hearing: Wednesday 28 Oct 2026 (today) (the court's record) [S1]."
    ]
    assert _lines(basis="confirmed", on=date(2026, 10, 29), order_date=date(2026, 10, 1)) == [
        "Next hearing: Thursday 29 Oct 2026 (tomorrow) (given in the order of 01 Oct 2026) [S1]."
    ]


def test_next_hearing_passed_order_date_is_said_to_have_passed():
    assert _lines(basis="order", on=date(2026, 10, 1), order_date=date(2026, 9, 1)) == [
        "The date given in the order of 01 Sep 2026 was 01 Oct 2026, which has passed; no later date is held yet "
        "[S1]."
    ]


# ------------------------------------------------------------------------------------------------ the other facts


def _facts(**over):
    base = {
        "petitioner_summary": "DINAR AHMED AND 3 ORS",
        "respondent_summary": "THE STATE OF ASSAM AND 4 ORS",
        "petitioners": ["DINAR AHMED", "B", "C", "D"],
        "respondents": ["THE STATE OF ASSAM", "R2", "R3", "R4", "R5"],
        "pet_advocate": "MR. S BANIK, SR. ADV.",
        "res_advocate": "SC, SEC. EDU.",
        "pet_advocates": ["MR. S BANIK", "SR. ADV."],
        "res_advocates": ["SC, SEC. EDU."],
        "status": "pending",
        "disposal_date": None,
        "disposal_nature": None,
        "last_order": {"order_date": date(2026, 10, 15), "order_no": "4"},
        "coram": "HON'BLE MR. JUSTICE KALYAN RAI SURANA",
        "bench_name": "Single Bench",
        "bench_text": "HON'BLE MR. JUSTICE OTHER",
    }
    base.update(over)
    return base


def test_fact_wordings():
    lines = []
    # parties from the summaries, with counts by role
    p = af.parties_lines(_facts())
    assert p == [
        "DINAR AHMED AND 3 ORS versus THE STATE OF ASSAM AND 4 ORS [S1].",
        "4 petitioners and 5 respondents are listed on the Parties tab [S1].",
    ]
    lines += p
    # the fallback to the first party with "and N others"
    p = af.parties_lines(_facts(petitioner_summary=None, respondent_summary=None, respondents=["R1"]))
    assert p[0] == "DINAR AHMED and 3 others versus R1 [S1]."
    assert p[1] == "4 petitioners and 1 respondent are listed on the Parties tab [S1]."
    lines += p
    p = af.parties_lines(
        _facts(petitioner_summary=None, respondent_summary=None, petitioners=[], respondents=[])
    )
    assert p == ["No parties are recorded in the court record for this case [S1]."]
    lines += p
    # advocates from the printed fields, then the case_advocates fallback, then none recorded
    a = af.advocates_lines(_facts())
    assert a == ["For the petitioners: MR. S BANIK, SR. ADV.. For the respondents: SC, SEC. EDU. [S1]."]
    a2 = af.advocates_lines(_facts(pet_advocate=None, res_advocate=None, res_advocates=[]))
    assert a2 == ["For the petitioners: MR. S BANIK; SR. ADV.. For the respondents: none recorded [S1]."]
    lines += a + a2
    # status
    assert af.status_lines(_facts()) == ["Pending [S1]."]
    assert af.status_lines(
        _facts(status="disposed", disposal_date=date(2026, 9, 1), disposal_nature="DISMISSED")
    ) == ["Disposed of on 01 Sep 2026, DISMISSED [S1]."]
    assert af.status_lines(_facts(status="disposed", disposal_date=date(2026, 9, 1))) == [
        "Disposed of on 01 Sep 2026 [S1]."
    ]
    assert af.status_lines(_facts(status="unknown")) == [
        "The court record does not give the status yet [S1]."
    ]
    lines += af.status_lines(_facts(status="unknown"))
    # last order and none
    assert af.last_order_lines(_facts()) == ["The last order is dated 15 Oct 2026 (No. 4) [S1]."]
    assert af.last_order_lines(_facts(last_order=None)) == ["No court order is held for this case yet [S1]."]
    lines += af.last_order_lines(_facts(last_order=None))
    # bench from the coram, from bench_text, and neither
    assert af.bench_lines(_facts()) == ["Before HON'BLE MR. JUSTICE KALYAN RAI SURANA (Single Bench) [S1]."]
    assert af.bench_lines(_facts(coram=None)) == ["Before HON'BLE MR. JUSTICE OTHER [S1]."]
    assert af.bench_lines(_facts(coram=None, bench_text=None)) == [
        "The court record does not name the bench yet [S1]."
    ]
    lines += af.bench_lines(_facts(coram=None, bench_text=None))
    assert all(line.endswith("[S1].") for line in lines)


def test_facts_module_imports_no_connector():
    tree = ast.parse((ASLMS / "services" / "assistant_facts.py").read_text("utf-8"))
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
        elif isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
    assert not any(m.startswith(("aslms.integration", "aslms.services.assistant")) for m in mods), mods
    assert set(af.FACTS) == {"next_hearing", "parties", "advocates", "status", "last_order", "bench"}
    assert af.FACTS_VERSION == 1


# ------------------------------------------------------------------------------------------------ the source (S1)
# design assistant-polish-followups, decision 3: the facts form backs every value the six facts can state

_DATE = re.compile(r"\b\d{2} [A-Z][a-z]{2} \d{4}\b")


def _stated(text: str, names: list[str]) -> set[str]:
    """The dates, numbers and names a line states ("and N others" is a count derived from the Parties tab count)."""
    text = re.sub(r"\band \d+ others?\b", "", text)
    dates = set(_DATE.findall(text))
    numbers = set(re.findall(r"\b\d+\b", _DATE.sub("", text)))
    return dates | numbers | {n for n in names if n in text}


def _names(f: dict) -> list[str]:
    keys = ("petitioner_summary", "respondent_summary", "pet_advocate", "res_advocate", "coram", "bench_name")
    out = [f[k] for k in keys if f.get(k)]
    if f.get("bench_text"):
        out.append(f["bench_text"])
    for k in ("petitioners", "respondents", "pet_advocates", "res_advocates"):
        out += f.get(k) or []
    if f.get("disposal_nature"):
        out.append(f["disposal_nature"])
    return out


NH_CASES = {
    "court with a differing order": _nh(
        court=date(2026, 11, 2),
        purpose="ADMISSION",
        basis="court",
        on=date(2026, 11, 2),
        differs=date(2026, 11, 5),
        differs_order=date(2026, 10, 15),
    ),
    "order": _nh(
        court=date(2026, 10, 15), basis="order", on=date(2026, 11, 5), order_date=date(2026, 10, 15)
    ),
    "order, passed": _nh(basis="order", on=date(2026, 10, 1), order_date=date(2026, 9, 1)),
    "around": _nh(basis="around", on=date(2026, 12, 1), order_date=date(2026, 10, 1), words="after 2 months"),
    "confirmed": _nh(basis="confirmed", on=date(2026, 10, 29), order_date=date(2026, 10, 1)),
    "manual": _nh(basis="manual", on=date(2026, 11, 9)),
    "court, passed": _nh(basis="court", on=date(2026, 10, 15)),
    "none": _nh(),
    "disposed": _nh(disposed=True, disposal=date(2026, 9, 1), basis="court", on=date(2026, 11, 2)),
}

FACT_CASES = {
    "summaries": _facts(),
    "no summaries": _facts(petitioner_summary=None, respondent_summary=None, respondents=["R1"]),
    "no parties": _facts(petitioner_summary=None, respondent_summary=None, petitioners=[], respondents=[]),
    "advocate rows only": _facts(pet_advocate=None, res_advocate=None, res_advocates=[]),
    "disposed": _facts(status="disposed", disposal_date=date(2026, 9, 1), disposal_nature="DISMISSED"),
    "unknown status, no order, no coram": _facts(status="unknown", last_order=None, coram=None),
    "no bench at all": _facts(coram=None, bench_text=None, bench_name=None),
}


@pytest.mark.parametrize("nh_name", list(NH_CASES))
@pytest.mark.parametrize("f_name", list(FACT_CASES))
def test_source_text_lists_every_value(nh_name, f_name):
    f, nh = FACT_CASES[f_name], NH_CASES[nh_name]
    if f["status"] == "disposed":
        nh = af.NextHearing(**{**nh.__dict__, "disposed": True, "disposal_date": f["disposal_date"]})
    text = af.source_text(f, nh, today=TODAY)
    lines = (
        af._next_lines(nh, TODAY)
        + af.parties_lines(f)
        + af.advocates_lines(f)
        + af.status_lines(f)
        + af.last_order_lines(f)
        + af.bench_lines(f)
    )
    names = _names(f)
    for line in lines:
        missing = {v for v in _stated(line, names) if v not in text}
        assert not missing, (line, missing, text)


def test_source_text_wording():
    text = af.source_text(
        {
            **_facts(),
            "case_no_text": "WP(C)/2615/2026",
            "cnr": "GAHC010000012026",
            "court": "Gauhati High Court",
        },
        NH_CASES["court with a differing order"],
        today=TODAY,
    )
    assert text.splitlines() == [
        "Case number: WP(C)/2615/2026; CNR: GAHC010000012026; Court: Gauhati High Court",
        "Petitioners (as printed): DINAR AHMED AND 3 ORS",
        "Respondents (as printed): THE STATE OF ASSAM AND 4 ORS",
        "Parties tab: 4 petitioners, 5 respondents; first petitioner: DINAR AHMED; first respondent: THE STATE OF ASSAM",
        "Advocates for the petitioners (as printed): MR. S BANIK, SR. ADV.; listed: MR. S BANIK; SR. ADV.",
        "Advocates for the respondents (as printed): SC, SEC. EDU.; listed: SC, SEC. EDU.",
        "Status: Pending",
        "Last order: 15 Oct 2026 (No. 4)",
        "Bench: HON'BLE MR. JUSTICE KALYAN RAI SURANA (Single Bench)",
        "Latest hearing's bench: HON'BLE MR. JUSTICE OTHER",
        "Next hearing: Monday 02 Nov 2026, for ADMISSION (the court's record)",
        "Court's own record: 02 Nov 2026, for ADMISSION",
        "Order of 15 Oct 2026 gives 05 Nov 2026",
    ]
    bare = af.source_text(
        _facts(
            petitioner_summary=None,
            respondent_summary=None,
            petitioners=[],
            respondents=[],
            pet_advocate=None,
            res_advocate=None,
            pet_advocates=[],
            res_advocates=[],
            status="unknown",
            last_order=None,
            coram=None,
            bench_name=None,
            bench_text=None,
        ),
        NH_CASES["none"],
        today=TODAY,
    )
    assert bare.splitlines() == [
        "Case number: not recorded; CNR: not recorded; Court: not recorded",
        "Petitioners (as printed): not recorded",
        "Respondents (as printed): not recorded",
        "Parties tab: 0 petitioners, 0 respondents; first petitioner: none listed; first respondent: none listed",
        "Advocates for the petitioners (as printed): not recorded; listed: none listed",
        "Advocates for the respondents (as printed): not recorded; listed: none listed",
        "Status: not given",
        "Last order: none held",
        "Bench: coram not recorded",
        "Next hearing: none held",
    ]
    manual = af.source_text(_facts(), NH_CASES["manual"], today=TODAY)
    assert "Next hearing: Monday 09 Nov 2026 (entered by hand; the court has given no date)" in manual
