"""High Court APIs (docs/napix_integration_notes.md §7): one method per API, input strings in the documented
order, responses returned as decrypted (nested lists converted). Typed records come with the field-coverage
addendum (plan step 3); until then nothing is dropped because nothing is mapped."""

from __future__ import annotations

from datetime import date
from typing import Any

from aslms.core.errors import NapixGatewayError
from aslms.integration.base import BenchRef, CauseListRef
from aslms.integration.napix.client import NapixClient, NapixResult, nested_list

API: dict[str, str] = {
    "overview": "overview/overview",
    "state": "hc-state-api/state",
    "district": "hc-district-api/district",
    "bench_master": "hc-bench-master-api/bench",
    "case_type": "hc-case-type-master-api/casetypemaster",
    "act": "hc-act-master-api/actMaster",
    "causelist_bench": "hc-causelist-bench-api/causelistbench",
    "causelist_details": "hc-causelist-details-api/causelistdetails",
    "show_causelist": "hc-show-causelist-api/showcauselist",
    "cnr": "hc-cnr-api/CNR",
    "cnr_alt": "hc-cnr-api/cnr",
    "current_status": "hc-current-status-api/currentStatus",
    "order": "hc-order-api/order",
    "show_business": "hc-show-business-api/showBusiness",
    "case_search": "hc-case-search-api/casesearch",
    "filing": "hc-filing-api/Filing",
    "party_name": "hc-party-name-api/partyname",
    "advocate_name": "hc-advocate-name-api/advocatename",
    "advocate_bar_reg": "hc-advocate-bar-reg-api/advocatebarreg",
    "act_details": "hc-act-details-api/actdetails",
    "neutral_citation": "hc-nuetral-citation-number-api/neutralcitation",
}

LIST_TYPE_KEYS = ("causelist_type", "cause_list_type", "list_type", "type")
LIST_ID_KEYS = ("causelist_id", "cause_list_id", "list_id")


def _fmt(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def _s(v: Any) -> str | None:
    t = str(v).strip() if v is not None else ""
    return t or None


def rows_of(data: Any) -> list[dict[str, Any]]:
    """Master responses may wrap their numbered rows in one named key (`{"state": {"state1": …}}`,
    `{"benches": {"sr_no1": …}}`, verified live); flat numbered dicts and JSON lists pass through."""
    if isinstance(data, dict) and len(data) == 1:
        (inner,) = data.values()
        if isinstance(inner, dict | list):
            rows = nested_list(inner)
            if rows:
                return rows
    return nested_list(data)


def search_rows(data: Any) -> list[dict[str, Any]]:
    """Search APIs answer `{"establishment_name": …, "casenos": {"case1": {…}, …}}` (verified live)."""
    if isinstance(data, dict) and "casenos" in data:
        return nested_list(data["casenos"])
    return nested_list(data)


def advocate_rows(payload: Any) -> list[dict[str, Any]]:
    """The rows of a Search by Advocate Name response, in the court's order (`casenos`, verified live: probe P4).
    Pure: shared by `search_advocate` and the background storing of a capped search's rows (design `safety-fixes`,
    decision 13), which reads the payload kept in `napix_responses`."""
    return search_rows(payload)


class NapixHighCourt:
    """`CourtSource` for one High Court establishment (Gauhati HC Principal Seat = GAHC01)."""

    name = "napix_hc"

    def __init__(self, client: NapixClient, est_code: str, state_code: str):
        self.client, self.est_code, self.state_code = client, est_code, state_code
        self.last: NapixResult | None = None

    def for_codes(self, est_code: str | None = None, state_code: str | None = None) -> NapixHighCourt:
        """The same client for another court or state code: used only by the System health console, so an edited
        `est_code` or `state_code` reaches the same method (design `system-health-inspector`, decision 13). Every
        other caller keeps the configured codes."""
        if not est_code and not state_code:
            return self
        return NapixHighCourt(self.client, est_code or self.est_code, state_code or self.state_code)

    async def _get(self, key: str, params: dict[str, Any] | None = None, method: str = "GET") -> NapixResult:
        self.last = await self.client.call(API[key], params, method)
        return self.last

    # ------------------------------------------------------------------ masters (no input or state/est code)
    async def overview(self) -> dict[str, Any]:
        return (await self._get("overview")).data or {}

    async def state_master(self) -> list[dict[str, Any]]:
        return rows_of((await self._get("state")).data)

    async def district_master(self) -> list[dict[str, Any]]:
        return rows_of((await self._get("district", {"state_code": self.state_code})).data)

    async def bench_master(self) -> list[dict[str, Any]]:
        return rows_of((await self._get("bench_master", {"state_code": self.state_code})).data)

    async def case_type_master(self) -> list[dict[str, Any]]:
        return rows_of((await self._get("case_type", {"est_code": self.est_code})).data)

    async def act_master(self) -> list[dict[str, Any]]:
        return rows_of((await self._get("act")).data)

    # ------------------------------------------------------------------ cause lists
    async def causelist_benches(self, list_date: date) -> list[BenchRef]:
        res = await self._get(
            "causelist_bench", {"est_code": self.est_code, "causelist_date": _fmt(list_date)}
        )
        return [
            BenchRef(bench_id=str(b.get("bench_id", "")).strip(), judge_name=_s(b.get("judge_name")), raw=b)
            for b in nested_list(res.data)
            if _s(b.get("bench_id"))
        ]

    async def causelist_details(self, list_date: date, bench_id: str) -> list[dict[str, Any]]:
        """Rows or list metadata — what it returns is the first open question of the live test."""
        res = await self._get(
            "causelist_details",
            {"est_code": self.est_code, "causelist_date": _fmt(list_date), "bench_id": bench_id},
        )
        return nested_list(res.data)

    @staticmethod
    def causelist_refs(list_date: date, bench_id: str, details: list[dict[str, Any]]) -> list[CauseListRef]:
        """The cause-list references a details response describes (one per list the bench published)."""
        out: list[CauseListRef] = []
        seen: set[str | None] = set()
        for row in details:
            cid = next((_s(row.get(k)) for k in LIST_ID_KEYS if _s(row.get(k))), None)
            if cid in seen:
                continue
            seen.add(cid)
            lt = next((_s(row.get(k)) for k in LIST_TYPE_KEYS if _s(row.get(k))), None)
            out.append(CauseListRef(list_date, bench_id, cid, lt, raw=row))
        return out

    async def show_causelist(self, ref: CauseListRef) -> bytes | dict[str, Any]:
        res = await self._get(
            "show_causelist",
            {
                "est_code": self.est_code,
                "bench_id": ref.bench_id,
                "causelist_id": ref.causelist_id or "",
                "causelist_date": _fmt(ref.list_date),
            },
        )
        return res.pdf if res.pdf is not None else (res.data or {})

    # ------------------------------------------------------------------ case record
    async def case_by_cnr(self, cnr: str, *, fallback: bool = True) -> dict[str, Any]:
        """`fallback=False` (the System health test, design `api-health-checker`, decision 3) reports a gateway 404
        on `/CNR` as it is and never calls the known-404 `/cnr` path: one click, one call."""
        cino = cnr.strip().upper()
        try:
            res = await self._get("cnr", {"cino": cino})
        except NapixGatewayError:
            if not fallback:
                raise
            res = await self._get("cnr_alt", {"cino": cino})  # notes §7: path casing unverified
        return res.data or {}

    async def current_status(self, cnrs: list[str]) -> list[dict[str, Any]]:
        if len(cnrs) > 300:
            # the gateway answers HTTP 414 above ~300 (live probe 7 Oct 2026); notes §7
            raise ValueError("Current Status takes at most 300 CNRs per call through the gateway")
        res = await self._get("current_status", {"cino": ",".join(c.strip().upper() for c in cnrs)}, "POST")
        return nested_list(res.data) or ([res.data] if isinstance(res.data, dict) else [])

    async def show_order(self, cnr: str, order_no: str, order_date: date) -> bytes | dict[str, Any]:
        res = await self._get(
            "order", {"cino": cnr.strip().upper(), "order_no": order_no, "order_date": _fmt(order_date)}
        )
        return res.pdf if res.pdf is not None else (res.data or {})

    async def show_business(self, cnr: str, business_date: date) -> dict[str, Any]:
        res = await self._get(
            "show_business", {"cino": cnr.strip().upper(), "business_date": _fmt(business_date)}
        )
        return res.data or {}

    # ------------------------------------------------------------------ searches
    async def search_case_number(self, case_type: int, reg_no: int, reg_year: int) -> list[dict[str, Any]]:
        res = await self._get(
            "case_search",
            {"est_code": self.est_code, "case_type": case_type, "reg_no": reg_no, "reg_year": reg_year},
        )
        return search_rows(res.data)

    async def search_party(self, name: str, reg_year: int, pend_disp: str = "P") -> list[dict[str, Any]]:
        res = await self._get(
            "party_name",
            {"est_code": self.est_code, "pend_disp": pend_disp, "litigant_name": name, "reg_year": reg_year},
        )
        return search_rows(res.data)

    async def search_advocate(
        self, name: str, reg_year: int | None, pend_disp: str = "P"
    ) -> list[dict[str, Any]]:
        """Spec §6.8. `reg_year=None` sends an empty year: only the live probe uses it (design
        `search-court-advocate-filing`, decision 2, probe P2); the service always passes a year."""
        res = await self._get(
            "advocate_name",
            {
                "est_code": self.est_code,
                "pend_disp": pend_disp,
                "advocate_name": name,
                "reg_year": "" if reg_year is None else reg_year,
            },
        )
        return advocate_rows(res.data)

    async def search_filing(self, case_type: int, fil_no: int, fil_year: int) -> list[dict[str, Any]]:
        res = await self._get(
            "filing",
            {"est_code": self.est_code, "case_type": case_type, "fil_no": fil_no, "fil_year": fil_year},
        )
        return search_rows(res.data)
