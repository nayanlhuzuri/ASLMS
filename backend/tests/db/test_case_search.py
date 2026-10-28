"""Local search over `cases.search_vector` (design cases-api, decisions 5–6): the migration backfill, the
refresh after a dossier and a cause-list apply, provisional cases found through their cause-list entry, the
party / advocate weights, number search (spaced form, alias, filing number), the filters, merged cases, the
10,000 count cap, and the item fields (`owner_office_code`, `in_pool`, `claimable`)."""

from __future__ import annotations

from datetime import date

import pytest
import sqlalchemy as sa
from alembic import command

from aslms.domain.cases import Case, CaseStatus
from aslms.domain.courts import CaseType, Court
from aslms.services import case_search
from aslms.services import ownership as own
from aslms.services.cases import apply_dossier, refresh_search_vector
from tests.db.conftest import alembic_config, sample
from tests.db.test_matching import entry, load_list
from tests.db.world import make_case

PENDING = "cnr_pending.json"


def search(s, world, key, q, **kw):
    return case_search.search(s, world.user(s, key), q=q, **kw)


def names(page):
    return [i["case"]["case_no_text"] for i in page.items]


def court(s):
    return s.scalar(sa.select(Court).where(Court.est_code == "GAHC01"))


def add_case_type(s, code, short, aliases=()):
    ct = CaseType(
        court_id=court(s).id, case_type_code=code, type_name=short, short_name=short, aliases=list(aliases)
    )
    s.add(ct)
    s.flush()
    return ct


# ------------------------------------------------------------------------------------------------ vector upkeep


@pytest.mark.migration_cycle
def test_migration_backfill_fills_the_vector(world, engine):
    with world.Session() as s:
        c = make_case(s, pet="BACKFILL PARTY")
        s.commit()
        cid = c.id
    cfg = alembic_config(engine.url.render_as_string(hide_password=False))
    command.downgrade(cfg, "0004")
    with engine.connect() as conn:
        assert (
            conn.execute(sa.text("select search_vector from cases where id = :i"), {"i": cid}).scalar()
            is None
        )
    command.upgrade(cfg, "head")
    with engine.connect() as conn:
        vec = conn.execute(
            sa.text("select search_vector::text from cases where id = :i"), {"i": cid}
        ).scalar()
    assert vec and "'backfill':" in vec and "A" in vec


def test_apply_dossier_and_apply_entries_refresh_the_vector(world):
    with world.Session() as s:
        c = make_case(s, cnr="GAHC010129772026", case_no="WP(C)/3600/2026")
        s.flush()
        refresh_search_vector(s, [c.id])
        assert names(search(s, world, "root", "nunisa", field_="party")) == []
        apply_dossier(s, c, sample(PENDING))
        page = search(s, world, "root", "nunisa", field_="party")
        assert names(page) == ["WP(C)/3600/2026"] and page.items[0]["match"] == "party"
        # weights: the advocate "DY.S.G.I." is found as advocate, not as party; the petitioner "NUNISA" the
        # other way round; "KATHAR" is both the petitioners' advocate and petitioner no. 29
        assert names(search(s, world, "root", "dy.s", field_="advocate")) == ["WP(C)/3600/2026"]
        assert names(search(s, world, "root", "dy.s", field_="party")) == []
        assert names(search(s, world, "root", "nunisa", field_="advocate")) == []
        assert names(search(s, world, "root", "kathar", field_="advocate")) == ["WP(C)/3600/2026"]
        assert names(search(s, world, "root", "kathar", field_="party")) == ["WP(C)/3600/2026"]
        assert names(search(s, world, "root", "nunisa kathar")) == ["WP(C)/3600/2026"]  # text = both
        # a provisional case known only from a cause list is found by a petitioner word of its entry
        load_list(s, [entry(1, None, "WP(C)/77/2025", pet="BHUPEN HAZARIKA MEMORIAL TRUST")])
        page = search(s, world, "root", "hazarika")
        assert names(page) == ["WP(C)/77/2025"] and page.items[0]["case"]["is_provisional"]
        s.rollback()


# ------------------------------------------------------------------------------------------------ identifiers


def test_number_search_spaced_alias_and_filing_number(world):
    with world.Session() as s:
        add_case_type(s, 111, "WP(C)", aliases=["WPC", "W.P.(C)"])
        c = make_case(s, cnr="GAHC010129772026", case_no="WP(C)/3600/2026")
        apply_dossier(s, c, sample(PENDING))  # filing_no_text WP(C)/7451/2026
        make_case(s, case_no="WP(C)/4326/2025")
        for q in ("WP(C)/4326/2025", "wp(c) 4326/2025", "WPC 4326/2025", "w.p.(c) 4326 / 2025"):
            page = search(s, world, "root", q)
            assert names(page) == ["WP(C)/4326/2025"], q
            assert page.items[0]["match"] == "number"
        assert names(search(s, world, "root", "WP(C) 7451/2026")) == ["WP(C)/3600/2026"]  # filing number
        assert names(search(s, world, "root", "WA 4326/2025")) == []
        # CNR and ref_no
        page = search(s, world, "root", "gahc010129772026")
        assert names(page) == ["WP(C)/3600/2026"] and page.items[0]["match"] == "cnr"
        assert names(search(s, world, "root", c.ref_no.replace("/", "-"))) == ["WP(C)/3600/2026"]
        assert names(search(s, world, "root", str(c.id))) == ["WP(C)/3600/2026"]
        s.rollback()


# ------------------------------------------------------------------------------------------------ filters


def test_filters_and_merged_cases(world):
    with world.Session() as s:
        a = make_case(s, case_no="WP(C)/1/2024", pet="FILTER PARTY ONE", status=CaseStatus.PENDING)
        b = make_case(s, case_no="WA/2/2025", pet="FILTER PARTY TWO", status=CaseStatus.DISPOSED)
        c = make_case(s, case_no="WP(C)/3/2025", pet="FILTER PARTY THREE")
        merged = make_case(s, case_no="WP(C)/4/2025", pet="FILTER PARTY MERGED")
        merged.merged_into_case_id = a.id
        for case in (a, b, c):
            case.case_type_text, case.reg_year = (
                case.case_no_text.split("/")[0],
                int(case.case_no_text.split("/")[2]),
            )
        s.flush()
        refresh_search_vector(s, [a.id, b.id, c.id, merged.id])
        actor, admin = world.actor(s, "edu_admin")
        own.claim(s, actor, admin, a)
        load_list(s, [entry(1, b.cnr, b.case_no_text, pet="FILTER PARTY TWO")], list_date=date(2025, 1, 6))
        s.flush()
        all_ = search(s, world, "root", "filter party")
        assert set(names(all_)) == {"WP(C)/1/2024", "WA/2/2025", "WP(C)/3/2025"}  # merged never appears
        assert all_.total == 3 and not all_.total_capped
        assert names(search(s, world, "root", "filter party", status="disposed")) == ["WA/2/2025"]
        assert set(names(search(s, world, "root", "filter party", year=2025))) == {
            "WA/2/2025",
            "WP(C)/3/2025",
        }
        assert set(names(search(s, world, "root", "filter party", case_type="wp(c)"))) == {
            "WP(C)/1/2024",
            "WP(C)/3/2025",
        }
        assert names(search(s, world, "root", "filter party", office="EDU")) == ["WP(C)/1/2024"]
        assert names(search(s, world, "root", "filter party", listed_from=date(2025, 1, 1))) == ["WA/2/2025"]
        assert names(search(s, world, "root", "filter party", listed_to=date(2024, 12, 31))) == []
        assert names(
            search(s, world, "root", "filter party", listed_from=date(2025, 1, 6), listed_to=date(2025, 1, 6))
        ) == ["WA/2/2025"]
        # items carry owner / pool / claimable
        by_no = {i["case"]["case_no_text"]: i for i in all_.items}
        assert by_no["WP(C)/1/2024"]["owner_office_code"] == "EDU" and not by_no["WP(C)/1/2024"]["in_pool"]
        assert by_no["WP(C)/3/2025"]["owner_office_code"] is None and by_no["WP(C)/3/2025"]["in_pool"]
        assert by_no["WP(C)/3/2025"]["claimable"] is False  # root has no department
        edu = search(s, world, "edu_admin", "filter party")
        by_no = {i["case"]["case_no_text"]: i for i in edu.items}
        assert by_no["WP(C)/3/2025"]["claimable"] is True and by_no["WP(C)/3/2025"]["visible"] is True
        assert by_no["WP(C)/1/2024"]["claimable"] is False and by_no["WP(C)/1/2024"]["visible"] is True
        off = search(s, world, "edu_off1", "filter party")
        by_no = {i["case"]["case_no_text"]: i for i in off.items}
        assert by_no["WP(C)/3/2025"]["claimable"] is False and by_no["WP(C)/3/2025"]["visible"] is False
        assert len(off.items) == 3  # summaries of every case, none visible to the officer
        assert search(s, world, "edu_off1", "filter party", visible_only=True).items == []
        # bad filters
        for kw in ({"status": "open"}, {"office": "EDU-DSE"}, {"case_type": " "}, {"field_": "nope"}):
            try:
                search(s, world, "root", "filter party", **kw)
            except case_search.SearchError:
                pass
            else:
                raise AssertionError(kw)
        s.rollback()


def test_list_visible_filters_and_counts(world):
    with world.Session() as s:
        a = make_case(s, pet="LIST ONE", next_hearing=date(2026, 10, 20))
        b = make_case(s, pet="LIST TWO", status=CaseStatus.DISPOSED)
        make_case(s, pet="LIST THREE")
        actor, admin = world.actor(s, "edu_admin")
        own.claim(s, actor, admin, a)
        own.claim(s, actor, admin, b)
        refresh_search_vector(s, [a.id, b.id])
        from aslms.services import next_hearing  # the filters read the one next hearing (next-date-direct)

        next_hearing.refresh(s, [a.id, b.id])
        off1 = world.user(s, "edu_off1")
        own.allot(s, actor, admin, a, officer_user_id=off1.id)
        page = case_search.list_visible(s, off1)
        assert [i["case"]["id"] for i in page.items] == [a.id] and page.total == 1
        assert case_search.list_visible(s, off1, case_state="disposed").items == []
        page = case_search.list_visible(s, admin, case_state="all", q="list")
        assert {i["case"]["id"] for i in page.items} == {a.id, b.id}
        assert case_search.list_visible(s, admin, case_state="disposed").total == 1
        assert (
            case_search.list_visible(s, admin, next_from=date(2026, 10, 1), next_to=date(2026, 10, 31)).total
            == 1
        )
        assert case_search.list_visible(s, admin, next_from=date(2026, 11, 1)).total == 0
        assert all(i["visible"] for i in page.items)
        s.rollback()


def test_total_is_capped_at_ten_thousand(world):
    with world.Session() as s:
        c = court(s)
        s.execute(
            sa.text(
                """
                INSERT INTO cases (cnr, court_id, case_no_text, ref_no, status, petitioner_summary,
                                   first_seen_source, is_provisional, search_vector)
                SELECT 'CAPX' || lpad(g::text, 12, '0'), :court, 'WP(C)/' || g || '/2020',
                       'ASLMS/GHC/CASE/2020/' || lpad(g::text, 6, '0'), 'pending', 'CAPPED PARTY',
                       'causelist', false, setweight(to_tsvector('simple', 'capped party'), 'A')
                FROM generate_series(1, 10001) g
                """
            ),
            {"court": c.id},
        )
        page = search(s, world, "root", "capped party", limit=5)
        assert page.total == 10_000 and page.total_capped is True and len(page.items) == 5
        page = case_search.list_visible(s, world.user(s, "root"), limit=1)
        assert page.total == 10_000 and page.total_capped
        s.rollback()


def test_limit_is_clamped_and_offset_pages(world):
    with world.Session() as s:
        for n in range(3):
            make_case(s, pet=f"PAGE PARTY {n}")
        s.flush()
        refresh_search_vector(s, [c.id for c in s.scalars(sa.select(Case)).all()])
        page = search(s, world, "root", "page party", limit=5000, offset=0)
        assert page.total == 3 and len(page.items) == 3
        page2 = search(s, world, "root", "page party", limit=2, offset=2)
        assert len(page2.items) == 1 and page2.total == 3
        s.rollback()
