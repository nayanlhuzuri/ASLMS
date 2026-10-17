"""The High Court methods send the documented input strings to the documented paths (notes §7)."""

from __future__ import annotations

from datetime import date

import httpx
import pytest

from aslms.core.errors import NapixInputError
from aslms.integration.base import CauseListRef
from aslms.integration.napix.client import NapixClient
from aslms.integration.napix.hc import NapixHighCourt
from tests.unit.conftest import Gateway


async def test_paths_and_input_order(client: NapixClient, gateway: Gateway) -> None:
    hc = NapixHighCourt(client, "GAHC01", "6")
    gateway.responses.append(
        lambda p, q, r: gateway.envelope({"case1": {"bench_id": 2048, "judge_name": "J"}})
    )
    async with client:
        benches = await hc.causelist_benches(date(2026, 9, 3))
        await hc.causelist_details(date(2026, 9, 3), "2048")
        await hc.show_causelist(CauseListRef(date(2026, 9, 3), "2048", "77", "daily"))
        await hc.current_status(["gahc010153612024", "GAHC010000012024"])
        await hc.show_order("GAHC010153612024", "1", date(2026, 9, 1))
        await hc.show_business("GAHC010153612024", date(2026, 9, 1))
        await hc.search_case_number(3, 1536, 2024)
        await hc.search_party("STATE OF ASSAM", 2024)
        await hc.district_master()
        await hc.case_type_master()
        await hc.act_master()
    assert benches[0].bench_id == "2048" and benches[0].judge_name == "J"
    assert [(s["path"], s["plain"], s["method"]) for s in gateway.seen] == [
        ("hc-causelist-bench-api/causelistbench", "est_code=GAHC01|causelist_date=2026-09-03", "GET"),
        (
            "hc-causelist-details-api/causelistdetails",
            "est_code=GAHC01|causelist_date=2026-09-03|bench_id=2048",
            "GET",
        ),
        (
            "hc-show-causelist-api/showcauselist",
            "est_code=GAHC01|bench_id=2048|causelist_id=77|causelist_date=2026-09-03",
            "GET",
        ),
        ("hc-current-status-api/currentStatus", "cino=GAHC010153612024,GAHC010000012024", "POST"),
        ("hc-order-api/order", "cino=GAHC010153612024|order_no=1|order_date=2026-09-01", "GET"),
        ("hc-show-business-api/showBusiness", "cino=GAHC010153612024|business_date=2026-09-01", "GET"),
        ("hc-case-search-api/casesearch", "est_code=GAHC01|case_type=3|reg_no=1536|reg_year=2024", "GET"),
        (
            "hc-party-name-api/partyname",
            "est_code=GAHC01|pend_disp=P|litigant_name=STATE OF ASSAM|reg_year=2024",
            "GET",
        ),
        ("hc-district-api/district", "state_code=6", "GET"),
        ("hc-case-type-master-api/casetypemaster", "est_code=GAHC01", "GET"),
        ("hc-act-master-api/actMaster", "", "GET"),
    ]


async def test_cnr_falls_back_to_lowercase_path_on_gateway_404(client: NapixClient, gateway: Gateway) -> None:
    hc = NapixHighCourt(client, "GAHC01", "6")
    gateway.responses.append(
        lambda p, q, r: httpx.Response(200, json={"httpCode": "404", "httpMessage": "Not Found"})
    )
    gateway.responses.append(lambda p, q, r: gateway.envelope({"cino": "GAHC010153612024"}))
    async with client:
        rec = await hc.case_by_cnr("gahc010153612024")
    assert rec["cino"] == "GAHC010153612024"
    assert [s["path"] for s in gateway.seen] == ["hc-cnr-api/CNR", "hc-cnr-api/cnr"]


def test_causelist_refs_dedupe_by_list_id() -> None:
    rows = [
        {"causelist_id": "11", "causelist_type": "Daily", "cino": "A"},
        {"causelist_id": "11", "causelist_type": "Daily", "cino": "B"},
        {"causelist_id": "12", "causelist_type": "Supplementary"},
    ]
    refs = NapixHighCourt.causelist_refs(date(2026, 9, 3), "2048", rows)
    assert [(r.causelist_id, r.list_type) for r in refs] == [("11", "Daily"), ("12", "Supplementary")]


async def test_advocate_and_filing_searches_send_the_spec_input(
    client: NapixClient, gateway: Gateway
) -> None:
    """Design `search-court-advocate-filing`: spec §6.8 and §6.6 input order, the gateway stub paths; an empty
    year (probe P2 only) is sent as `reg_year=`."""
    hc = NapixHighCourt(client, "GAHC01", "6")
    async with client:
        await hc.search_advocate("A I KATHAR", 2025)
        await hc.search_advocate("A I KATHAR", None, pend_disp="D")
        await hc.search_filing(111, 7451, 2026)
    assert [(s["path"], s["plain"], s["method"]) for s in gateway.seen] == [
        (
            "hc-advocate-name-api/advocatename",
            "est_code=GAHC01|pend_disp=P|advocate_name=A I KATHAR|reg_year=2025",
            "GET",
        ),
        (
            "hc-advocate-name-api/advocatename",
            "est_code=GAHC01|pend_disp=D|advocate_name=A I KATHAR|reg_year=",
            "GET",
        ),
        ("hc-filing-api/Filing", "est_code=GAHC01|case_type=111|fil_no=7451|fil_year=2026", "GET"),
    ]


async def test_advocate_name_with_pair_separators_is_refused_before_sending(
    client: NapixClient, gateway: Gateway
) -> None:
    hc = NapixHighCourt(client, "GAHC01", "6")
    async with client:
        for bad in ("KATHAR|reg_year=2020", "A=B"):
            with pytest.raises(NapixInputError):
                await hc.search_advocate(bad, 2025)
    assert gateway.seen == []
