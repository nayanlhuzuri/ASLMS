"""The case detail endpoints (design cases-api, decisions 7, 8, 11, 15) on a case loaded from
`cnr_pending.json`: every typed column of the overview, the child lists, ownership and custody, the former
parties, the paginated tabs newest first, links and the graph, the timeline rule, 404 for unknown or
non-visible cases, 401 without a token."""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient

from aslms.api.main import create_app
from aslms.core.config import Settings
from aslms.domain.cases import Case, CaseLink, LinkKind, LinkSource
from aslms.domain.events import Event, EventVisibility
from aslms.domain.reference import EventType
from aslms.services import ownership as own
from aslms.services.cases import apply_dossier, refresh_search_vector
from aslms.services.orders import enqueue_order_pdfs
from tests.db.auth_support import bearer
from tests.db.conftest import sample
from tests.db.test_matching import entry, load_list
from tests.db.world import PW, USERS, make_case

PENDING = "cnr_pending.json"
CNR = "GAHC010129772026"
GROUPS = ("identity", "status", "classification", "place", "parties_as_printed", "portal")


@pytest.fixture()
def api(world):
    settings = Settings(
        _env_file=None,
        aslms_jwt_secret="test-secret-of-at-least-thirty-two-characters",
        aslms_access_token_minutes=5,
    )
    app = create_app(settings, world.Session)
    with TestClient(app) as client:
        yield client


def login(api: TestClient, key: str) -> dict:
    return bearer(api, USERS[key][0], PW)


@pytest.fixture()
def loaded(world):
    """The pending sample applied to a case EDU owns (allotted to off1), listed twice, with events."""
    with world.Session() as s:
        case = make_case(s, cnr=CNR, case_no="WP(C)/3600/2026")
        apply_dossier(s, case, sample(PENDING))
        enqueue_order_pdfs(s, case)  # as the runner and the court search do: order_found events, queue rows
        actor, admin = world.actor(s, "edu_admin")
        own.claim(s, actor, admin, case, officer_user_id=world.user(s, "edu_off1").id)
        load_list(s, [entry(1, CNR, "WP(C)/3600/2026")], list_date=date(2025, 1, 6))
        load_list(s, [entry(2, CNR, "WP(C)/3600/2026")], list_date=date(2025, 1, 8))
        s.commit()
        return case.id


def flat(body: dict) -> dict:
    out = {}
    for g in GROUPS:
        out.update(body[g])
    return out


# ------------------------------------------------------------------------------------------------ overview


def test_overview_carries_every_typed_column(api, world, loaded):
    r = api.get(f"/cases/{loaded}", headers=login(api, "edu_admin"))
    assert r.status_code == 200, r.text
    body = r.json()
    columns = {c.name for c in Case.__table__.columns} - {"id", "ref_no", "court_id", "raw", "search_vector"}
    f = flat(body)
    assert columns <= set(f), columns - set(f)
    # the sample's values are where the coverage table says
    assert (
        f["cnr"] == CNR
        and f["case_no_text"] == "WP(C)/3600/2026"
        and f["filing_no_text"] == "WP(C)/7451/2026"
    )
    assert f["filing_date"] == "2026-06-22" and f["registration_date"] == "2026-07-09"
    assert (
        f["status"] == "pending" and f["next_purpose"] == "ORDERS" and f["last_hearing_date"] == "2026-09-23"
    )
    assert (
        f["bench_name"] == "Single Bench"
        and f["napix_bench_id"] == 1854
        and f["coram_designation"] == "JUDGE"
    )
    assert f["category_code"] == 10160 and f["filing_state_code"] == 18 and f["filing_district_code"] == 100
    assert f["district_name_as_listed"] == "Dima Hasao" and f["state_name_as_listed"] == "Assam"
    assert f["petitioner_summary"] == "PROSANJIT NUNISA AND 66 ORS" and f["res_advocate"] == "DY.S.G.I."
    assert f["is_provisional"] is False and f["first_seen_source"] == "causelist"
    assert body["court"] == {"est_code": "GAHC01", "name": body["court"]["name"]} and body["court"]["name"]
    assert body["bench"]["bench_id"] == 1854 and body["bench"]["bench_name"] == "Single Bench"
    assert len(body["parties"]) == 81 and body["parties"][0]["name"] == "PROSANJIT NUNISA AND 66 ORS"
    assert {a["name_as_listed"] for a in body["advocates"]} == {"MR. A I KATHAR", "DY.S.G.I."}
    assert len(body["acts"]) == 1 and body["lower_courts"] == [] and body["applications"] == []
    assert body["objections"] == [] and body["court_transfers"] == [] and body["writ_info"] == []
    assert body["ownership"]["primary"]["office_code"] == "EDU"
    assert body["ownership"]["primary"]["officer"]["full_name"] == "Edu Off1"
    assert body["ownership"]["watchers"] == []
    assert (
        body["custody"]["holder_office"]["code"] == "EDU"
        and body["custody"]["holder_user"]["full_name"] == "Edu Off1"
    )
    assert body["custody"]["pending_action"] == "none"
    assert body["access_basis"] == ["owner", "custody"] and body["claimable"] is False
    assert body["dossier_status"] == "fetched" and body["merged_into_ref_no"] is None
    assert body["counts"] == {
        "hearings": 3,
        "orders": 3,
        "listings": 2,
        "links": 0,
        "documents": 0,
        "timeline": body["counts"]["timeline"],
        "notes": 0,
        "my_drafts": 0,
    }
    assert body["counts"]["timeline"] >= 3  # case_created, claimed, allotted, custody_moved, order_found…
    # by ref_no in the URL form and by CNR
    assert (
        api.get(f"/cases/{body['ref_no'].replace('/', '-')}", headers=login(api, "edu_admin")).status_code
        == 200
    )
    assert api.get(f"/cases/{CNR}", headers=login(api, "edu_off1")).json()["access_basis"] == [
        "allotted",
        "custody",
    ]


def test_overview_of_a_pool_and_a_merged_case(api, world):
    with world.Session() as s:
        pool = make_case(s, pet="POOL CASE")
        main = make_case(s)
        merged = make_case(s)
        actor, admin = world.actor(s, "edu_admin")
        own.claim(s, actor, admin, merged)
        merged.merged_into_case_id = main.id
        s.commit()
        pool_id, main_ref, merged_id = pool.id, main.ref_no, merged.id
    admin = login(api, "edu_admin")
    body = api.get(f"/cases/{pool_id}", headers=admin).json()
    assert (
        body["claimable"] is True
        and body["access_basis"] == ["pool"]
        and body["dossier_status"] == "not_fetched"
    )
    assert body["ownership"] == {"primary": None, "watchers": []} and body["custody"] is None
    body = api.get(f"/cases/{merged_id}", headers=admin).json()
    assert body["merged_into_ref_no"] == main_ref and body["access_basis"] == ["owner", "custody"]
    # the merged case never appears in search or the list
    assert str(merged_id) not in {
        i["case"]["id"] for i in api.get("/cases?limit=200", headers=admin).json()["items"]
    }


# ------------------------------------------------------------------------------------------------ parties


def test_former_parties_only_on_request(api, world, loaded):
    with world.Session() as s:
        case = s.get(Case, loaded)
        data = sample(PENDING)
        data["pet_extra_party"] = {"party_no1": "ONLY ONE EXTRA PARTY NOW"}
        apply_dossier(s, case, data)
        s.commit()
    headers = login(api, "edu_admin")
    current = api.get(f"/cases/{loaded}/parties", headers=headers).json()
    former = api.get(f"/cases/{loaded}/parties?include_former=true", headers=headers).json()
    assert len(current["parties"]) == 1 + 1 + 14  # pet_name + one extra + the 14 respondents
    assert all(p["is_current"] for p in current["parties"])
    assert len(former["parties"]) == 81 and sum(not p["is_current"] for p in former["parties"]) == 65
    assert len(current["advocates"]) == 2 and len(former["advocates"]) == 2


# ------------------------------------------------------------------------------------------------ tabs


def test_hearings_orders_listings_newest_first_and_paged(api, world, loaded):
    headers = login(api, "edu_head")
    h = api.get(f"/cases/{loaded}/hearings?limit=2", headers=headers).json()
    assert h["total"] == 3 and len(h["items"]) == 2
    dates = [i["business_date"] for i in h["items"]]
    assert dates == sorted(dates, reverse=True) and h["items"][0]["business_date"] == "2026-09-23"
    assert h["items"][0]["purpose"] == "ORDERS" and h["items"][0]["source"] == "dossier"
    h2 = api.get(f"/cases/{loaded}/hearings?limit=2&offset=2", headers=headers).json()
    assert len(h2["items"]) == 1
    o = api.get(f"/cases/{loaded}/orders", headers=headers).json()
    assert o["total"] == 3 and [i["order_no"] for i in o["items"]] == ["3", "2", "1"]
    assert o["items"][0]["download_status"] == "pending" and o["items"][0]["document_id"] is None
    assert o["items"][0]["kind"] == "interim" and "file" not in o["items"][0]
    lst = api.get(f"/cases/{loaded}/listings", headers=headers).json()
    assert lst["total"] == 2 and [i["list_date"] for i in lst["items"]] == ["2025-01-08", "2025-01-06"]
    assert lst["items"][0]["list_type"] == "daily" and lst["items"][0]["source"] == "pdf_parse"
    assert lst["items"][0]["counsel_codes"] == [] and lst["items"][0]["sr_no"] == 2
    assert (
        api.get(f"/cases/{loaded}/listings?limit=1&offset=1", headers=headers).json()["items"][0]["sr_no"]
        == 1
    )


# ------------------------------------------------------------------------------------------------ links


def test_links_and_graph(api, world, loaded):
    with world.Session() as s:
        case = s.get(Case, loaded)
        health_case = make_case(s, pet="HEALTH MAIN MATTER")
        h_actor, h_admin = world.actor(s, "health_admin")
        own.claim(s, h_actor, h_admin, health_case)
        s.add(
            CaseLink(
                from_case_id=case.id,
                to_case_id=None,
                to_case_no_text=health_case.case_no_text,
                to_cnr=health_case.cnr,  # resolved through the CNR
                kind=LinkKind.MAIN_MATTER,
                source=LinkSource.DOSSIER,
            )
        )
        s.add(
            CaseLink(
                from_case_id=case.id,
                to_case_no_text="WP(C)/999/2010",
                kind=LinkKind.LINKED,
                source=LinkSource.DOSSIER,
                filing_number_text="WP(C)/555/2010",
            )
        )
        incoming = make_case(s, pet="INCOMING")
        s.add(
            CaseLink(
                from_case_id=incoming.id,
                to_case_id=case.id,
                to_case_no_text="WP(C)/3600/2026",
                kind=LinkKind.WITH,
            )
        )
        # a third level behind the health case
        third = make_case(s, pet="THIRD LEVEL")
        s.add(
            CaseLink(
                from_case_id=health_case.id,
                to_case_id=third.id,
                to_case_no_text=third.case_no_text,
                kind=LinkKind.CONNECTED,
            )
        )
        refresh_search_vector(s, [case.id, health_case.id, incoming.id, third.id])
        s.commit()
        health_id, incoming_id, third_id = str(health_case.id), str(incoming.id), str(third.id)
    headers = login(api, "edu_admin")
    body = api.get(f"/cases/{loaded}/links", headers=headers).json()
    by_kind = {i["kind"]: i for i in body["items"]}
    assert set(by_kind) == {"main_matter", "linked", "with"}
    mm = by_kind["main_matter"]
    assert mm["direction"] == "out" and mm["case"]["id"] == health_id and mm["visible"] is False
    assert mm["case"]["petitioner_summary"] == "HEALTH MAIN MATTER"  # summary only
    assert by_kind["linked"]["case"] is None and by_kind["linked"]["filing_number_text"] == "WP(C)/555/2010"
    assert by_kind["with"]["direction"] == "in" and by_kind["with"]["case"]["id"] == incoming_id
    assert by_kind["with"]["visible"] is True  # a pool case: the EDU admin may claim it
    g = api.get(f"/cases/{loaded}/links/graph?depth=1", headers=headers).json()
    keys = {n["key"] for n in g["nodes"]}
    assert keys == {str(loaded), health_id, incoming_id, "no:WP(C)/999/2010"} and not g["truncated"]
    assert {(e["from"], e["to"], e["kind"]) for e in g["edges"]} == {
        (str(loaded), health_id, "main_matter"),
        (str(loaded), "no:WP(C)/999/2010", "linked"),
        (incoming_id, str(loaded), "with"),
    }
    leaf = next(n for n in g["nodes"] if n["key"].startswith("no:"))
    assert leaf["case"] is None and leaf["case_no_text"] == "WP(C)/999/2010" and leaf["visible"] is False
    g2 = api.get(f"/cases/{loaded}/links/graph", headers=headers).json()  # depth 2 reaches the third level
    assert third_id in {n["key"] for n in g2["nodes"]}
    assert api.get(f"/cases/{loaded}/links/graph?depth=4", headers=headers).status_code == 422
    # the auditor sees the health case as visible
    g3 = api.get(f"/cases/{loaded}/links/graph?depth=1", headers=login(api, "edu_auditor")).json()
    assert next(n for n in g3["nodes"] if n["key"] == health_id)["visible"] is True


def test_graph_stops_at_two_hundred_nodes(api, world):
    with world.Session() as s:
        root = make_case(s, pet="GRAPH ROOT")
        for n in range(205):
            other = make_case(s, pet=f"GRAPH LEAF {n}")
            s.add(
                CaseLink(
                    from_case_id=root.id,
                    to_case_id=other.id,
                    to_case_no_text=other.case_no_text,
                    kind=LinkKind.CONNECTED,
                )
            )
        s.commit()
        root_id = root.id
    g = api.get(f"/cases/{root_id}/links/graph", headers=login(api, "oversight")).json()
    assert g["truncated"] is True and len(g["nodes"]) == 200


# ------------------------------------------------------------------------------------------------ timeline


def test_timeline_rule(api, world, loaded):
    with world.Session() as s:
        for office, n in (("HEALTH", 1), ("EDU", 2)):
            s.add(
                Event(
                    case_id=loaded,
                    type=EventType.RECOMMENDATION_MADE,
                    payload={"office_code": office, "score": 0.9, "band": "high"},
                    dedupe_key=f"test-rec-{office}-{n}-{uuid.uuid4()}",
                    visibility=EventVisibility.SCOPED,
                )
            )
        s.add(
            Event(
                case_id=loaded,
                type=EventType.NOTE_ADDED,
                payload={"note_id": str(uuid.uuid4())},  # no such note: hidden
                dedupe_key=f"test-note-{uuid.uuid4()}",
                visibility=EventVisibility.SCOPED,
            )
        )
        s.commit()
    edu = api.get(f"/cases/{loaded}/timeline?limit=100", headers=login(api, "edu_admin")).json()
    types = [i["type"] for i in edu["items"]]
    # court events (order_found) and ownership events (claimed, allotted, custody_moved); the world inserts
    # cases directly, so no case_created event exists here
    assert {"claimed", "allotted", "custody_moved", "order_found"} <= set(types)
    recs = [i for i in edu["items"] if i["type"] == "recommendation_made"]
    assert [r["payload"]["office_code"] for r in recs] == ["EDU"]
    assert "note_added" not in types
    assert all(i["label"] for i in edu["items"])
    at = [i["occurred_at"] for i in edu["items"]]
    assert at == sorted(at, reverse=True)
    claimed = next(i for i in edu["items"] if i["type"] == "claimed")
    assert claimed["actor_name"] == "Edu Admin"
    auditor = api.get(f"/cases/{loaded}/timeline?limit=100", headers=login(api, "edu_auditor")).json()
    recs = [i for i in auditor["items"] if i["type"] == "recommendation_made"]
    assert sorted(r["payload"]["office_code"] for r in recs) == ["EDU", "HEALTH"]
    assert auditor["total"] == edu["total"] + 1
    page = api.get(f"/cases/{loaded}/timeline?limit=1&offset=1", headers=login(api, "edu_auditor")).json()
    assert len(page["items"]) == 1 and page["total"] == auditor["total"]


# ------------------------------------------------------------------------------------------------ negatives


@pytest.mark.parametrize(
    "path", ["", "/parties", "/hearings", "/orders", "/listings", "/links", "/links/graph", "/timeline"]
)
def test_detail_endpoints_answer_404_and_401(api, world, loaded, path):
    health = login(api, "health_off")
    assert api.get(f"/cases/{loaded}{path}", headers=health).status_code == 404
    assert api.get(f"/cases/{uuid.uuid4()}{path}", headers=health).status_code == 404
    assert api.get(f"/cases/ASLMS-GOA-CASE-2099-000001{path}", headers=health).status_code == 404
    assert api.get(f"/cases/{loaded}{path}").status_code == 401
    assert api.get(f"/cases/{loaded}{path}", headers=login(api, "edu_off1")).status_code == 200


def test_reading_needs_a_case_function(api, world):
    with world.Session() as s:
        from aslms.domain.org import PermissionEffect
        from aslms.domain.reference import Permission
        from aslms.services import access

        actor, root = world.actor(s, "root")
        access.set_override(
            s, actor, root, world.user(s, "dse_user"), Permission.CASES_VIEW_SCOPE, PermissionEffect.DENY
        )
        s.commit()
    headers = login(api, "dse_user")
    assert api.get("/cases", headers=headers).status_code == 403
    assert api.get("/cases/search?q=state", headers=headers).status_code == 403
    assert api.get("/cases/search?q=st", headers=login(api, "edu_admin")).status_code == 422  # q too short
    assert api.get("/cases/search?q=state&status=open", headers=login(api, "edu_admin")).status_code == 400
    assert api.get("/cases?case_state=nope", headers=login(api, "edu_admin")).status_code == 400
    assert api.get("/cases?q=st", headers=login(api, "edu_admin")).status_code == 400
