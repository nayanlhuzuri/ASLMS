"""The shared case filters' SQL over the test world (design portal-filters, decisions 1, 3 and 4): court and
bench read from the same cause-list entry as the date, the bench as "contains" (division benches included),
the next-hearing range, case types by the master's aliases, the owner as the active primary ownership only,
and words parsed as the Search box."""

from __future__ import annotations

from datetime import date

import sqlalchemy as sa

from aslms.domain.cases import Case
from aslms.domain.courts import CaseType, Court
from aslms.domain.ownership import CaseOwnership, OwnershipRole
from aslms.services import case_filters
from aslms.services import ownership as own
from aslms.services.cases import refresh_search_vector
from tests.db.world import DIVISION_BENCH, OTHER_BENCH, SINGLE_BENCH, add_listing, make_case

OCT1, OCT2 = date(2026, 10, 1), date(2026, 10, 2)


def matching(s, **values) -> set:
    f = case_filters.parse(**values)
    return set(s.scalars(sa.select(Case.id).where(*case_filters.conditions(s, f))).all())


def test_listing_date_court_bench_on_same_entry(world):
    with world.Session() as s:
        a = make_case(s)
        add_listing(s, a, OCT1, court_no="3", bench=SINGLE_BENCH)
        add_listing(s, a, OCT2, court_no="5", bench=OTHER_BENCH)
        assert matching(s, listed_from=OCT1, listed_to=OCT1, court_no="5") == set()
        assert matching(s, listed_from=OCT1, listed_to=OCT1, court_no="3") == {a.id}
        assert matching(s, listed_from=OCT2, listed_to=OCT2, bench="SAIKIA") == set()
        assert matching(s, listed_from=OCT2, listed_to=OCT2, bench="PHUKAN", court_no="5") == {a.id}
        assert matching(s, court_no="5", bench="SAIKIA") == set()  # two different entries
        assert matching(s, listed_from=OCT2) == {a.id} and matching(s, listed_to=date(2026, 9, 30)) == set()
        s.rollback()


def test_court_without_date_matches_any_listing(world):
    with world.Session() as s:
        a, b, c = make_case(s), make_case(s), make_case(s)
        add_listing(s, a, OCT1, court_no="3")
        add_listing(s, a, OCT2, court_no=" 5 ")  # printed with spaces: trimmed
        add_listing(s, b, OCT2, court_no="15")
        assert matching(s, court_no="5") == {a.id}
        assert matching(s, court_no="3") == {a.id}
        assert matching(s, court_no="15") == {b.id}
        assert c.id not in matching(s, court_no="1")
        s.rollback()


def test_bench_contains_finds_division_bench_listings(world):
    with world.Session() as s:
        single, division, other = make_case(s), make_case(s), make_case(s)
        add_listing(s, single, OCT1, bench=SINGLE_BENCH)
        add_listing(s, division, OCT1, bench=DIVISION_BENCH.replace(", ", ",\n  "))  # white space collapsed
        add_listing(s, other, OCT1, bench=OTHER_BENCH)
        assert matching(s, bench=SINGLE_BENCH) == {single.id, division.id}
        assert matching(s, bench="saikia") == {single.id, division.id}
        assert matching(s, bench="chief justice, honourable") == {division.id}
        assert matching(s, bench="SAI%IA") == set()  # a wildcard in the input matches literally
        assert matching(s, bench="JUSTICE") == {single.id, division.id, other.id}
        s.rollback()


def test_next_hearing_range(world):
    """Design next-date-direct, decision 11: the range reads the case's one next hearing."""
    from aslms.services import next_hearing
    from tests.db import next_dates_support as h

    with world.Session() as s:
        a = make_case(s, next_hearing=date(2026, 10, 20))
        b = make_case(s, next_hearing=date(2026, 11, 5))
        c = make_case(s)  # no court date: the date read from its order
        h.order_with_text(s, c, f"List this matter on {h.dmy(h.days(40))}.", order_date=h.days(-1))
        h.read(s)
        next_hearing.refresh(s, [a.id, b.id, c.id], today=date(2026, 10, 1))
        assert matching(s, next_from=date(2026, 10, 1), next_to=date(2026, 10, 31)) == {a.id}
        assert matching(s, next_from=date(2026, 10, 21), next_to=date(2026, 11, 30)) == {b.id}
        assert matching(s, next_to=date(2026, 10, 20)) == {a.id}
        assert c.id in matching(s, next_from=h.days(40), next_to=h.days(40))
        s.rollback()


def test_next_differs(world):
    from aslms.services import next_hearing
    from tests.db import next_dates_support as h

    with world.Session() as s:
        differs = make_case(s, next_hearing=h.days(12))
        h.order_with_text(s, differs, f"List this matter on {h.dmy(h.days(10))}.", order_date=h.days(-1))
        agrees = make_case(s, next_hearing=h.days(10))
        h.order_with_text(s, agrees, f"List this matter on {h.dmy(h.days(10))}.", order_date=h.days(-1))
        h.read(s)
        next_hearing.refresh(s, [differs.id, agrees.id])
        assert matching(s, next_differs=True) == {differs.id}
        assert matching(s, next_differs="true") == {differs.id}
        assert differs.id in matching(s, next_differs=False) and agrees.id in matching(s, next_differs=False)
        s.rollback()


def test_case_type_matches_master_alias(world):
    with world.Session() as s:
        court = s.scalar(sa.select(Court).where(Court.est_code == "GAHC01"))
        ct = CaseType(
            court_id=court.id, case_type_code=9101, type_name="WP(C)", short_name="WP(C)", aliases=["WPC"]
        )
        s.add(ct)
        s.flush()
        typed = make_case(s)
        typed.case_type_id = ct.id
        texted = make_case(s)
        texted.case_type_text = "WP (C)"
        other = make_case(s)
        other.case_type_text = "WA"
        s.flush()
        assert matching(s, case_type="wpc") == {typed.id}  # the alias names the master type
        assert matching(s, case_type="WP(C)") == {typed.id, texted.id}
        assert matching(s, case_type="wa") == {other.id}
        s.rollback()


def test_owner_is_active_primary_only(world):
    with world.Session() as s:
        a, b = make_case(s), make_case(s)
        actor, admin = world.actor(s, "edu_admin")
        own.claim(s, actor, admin, a)
        s.add(CaseOwnership(case_id=b.id, office_id=world.offices["EDU"].id, role=OwnershipRole.WATCHER))
        s.add(CaseOwnership(case_id=a.id, office_id=world.offices["HEALTH"].id, role=OwnershipRole.WATCHER))
        s.flush()
        assert matching(s, owner="edu") == {a.id}
        assert matching(s, owner="HEALTH") == set()
        for bad in ("EDU-DSE", "NOPE"):
            try:
                matching(s, owner=bad)
            except case_filters.CaseFilterError as exc:
                assert "is not a department" in str(exc)
            else:
                raise AssertionError(bad)
        s.rollback()


def test_words_parse_cnr_number_and_prefix(world):
    with world.Session() as s:
        a = make_case(s, case_no="WP(C)/4326/2025", pet="ASSAM TEA CORPORATION")
        b = make_case(s, pet="RAM KUMAR")
        refresh_search_vector(s, [a.id, b.id])
        assert matching(s, q=a.cnr) == {a.id}
        assert matching(s, q="WP(C) 4326/2025") == {a.id}
        assert matching(s, q="Assa") == {a.id}  # a prefix
        assert matching(s, q="ssam") == set()  # a fragment inside a word does not match
        assert matching(s, q=a.ref_no) == {a.id}
        s.rollback()
