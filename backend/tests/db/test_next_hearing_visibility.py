"""Review finding on design `next-date-direct`: `CaseSummaryOut` is court-public and is shown for cases the caller
cannot open (search, court search, cause lists, links, discovery, the Assistant's court-record view), so on such a
row `next_hearing` keeps only the tiers read from the court's record and order text; a department's own date (basis
`manual` or `confirmed`) and the discrepancy flag never reach another department (Deviation 15)."""

from __future__ import annotations

import uuid
from datetime import date

from aslms.domain.alerts import NextDate, NextDateSource, ReviewStatus
from aslms.services import case_search, inbox, next_hearing
from tests.db import next_dates_support as h
from tests.db.report_support import own_directly
from tests.db.world import make_case


def _manual(s, case, on: date) -> NextDate:
    row = NextDate(
        ref_no=f"T/NXT/{uuid.uuid4().hex[:10]}",
        case_id=case.id,
        next_date=on,
        source=NextDateSource.MANUAL,
        review_status=ReviewStatus.NOT_NEEDED,
    )
    s.add(row)
    s.flush()
    return row


def test_court_public_keeps_only_the_court_tiers() -> None:
    d = date(2026, 11, 20)
    assert next_hearing.court_public(None) is None
    for basis in ("manual", "confirmed"):
        assert next_hearing.court_public({"date": d, "basis": basis, "differs": None}) is None
    court = {"date": d, "basis": "court", "differs": {"date": d, "order": None}, "reported_at": "x"}
    assert next_hearing.court_public(court) == {
        "date": d,
        "basis": "court",
        "differs": None,
        "reported_at": None,
    }
    around = {"date": d, "basis": "around", "differs": None}
    assert next_hearing.court_public(around) == around


def test_a_manual_date_is_not_shown_on_a_row_the_caller_cannot_open(world) -> None:
    with world.Session() as s:
        edu = make_case(s, pet="MANUAL DATE CASE")
        own_directly(s, world, edu, "EDU")
        _manual(s, edu, h.days(20))
        court = make_case(s, pet="COURT DATE CASE", next_hearing=h.days(9))
        own_directly(s, world, court, "EDU")
        next_hearing.refresh(s, [edu.id, court.id])
        s.flush()

        mine = case_search.item_for(s, world.user(s, "edu_admin"), edu)
        assert mine["visible"] is True
        assert (mine["case"]["next_hearing"]["date"], mine["case"]["next_hearing"]["basis"]) == (
            h.days(20),
            "manual",
        )

        theirs = case_search.item_for(s, world.user(s, "health_off"), edu)
        assert theirs["visible"] is False and theirs["case"]["next_hearing"] is None
        many = case_search.items_for(s, world.user(s, "health_off"), [edu, court])
        assert many[0]["case"]["next_hearing"] is None
        # the court's own date is court-public and stays on the invisible row
        assert many[1]["visible"] is False
        assert (many[1]["case"]["next_hearing"]["date"], many[1]["case"]["next_hearing"]["basis"]) == (
            h.days(9),
            "court",
        )

        page = case_search.search(s, world.user(s, "health_off"), q=edu.cnr)
        (item,) = [i for i in page.items if i["case"]["id"] == edu.id]
        assert item["visible"] is False and item["case"]["next_hearing"] is None

        full = inbox.summaries(s, [edu])[edu.id]["next_hearing"]
        hidden = inbox.summaries(s, [edu], hidden={edu.id})[edu.id]["next_hearing"]
        assert full["basis"] == "manual" and hidden is None
