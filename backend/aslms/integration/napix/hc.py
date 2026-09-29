"""NAPIX High Court APIs mapped onto the `CourtSource` protocol, plus the masters.

Input parameter names and order follow the HC Open API v1.0 spec (`docs/specs/napix/hc/`, PDF pending):
  bench master            state_code
  case type master        est_code
  causelist bench         est_code | causelist_date
  causelist details       est_code | causelist_date | bench_id
  show causelist          est_code | bench_id | causelist_id | causelist_date
  CNR                     cino
  current status (POST)   cino=<comma-separated, up to 500>
  show business           cino | business_date
  order                   cino | order_no | order_date
  case search             est_code | case_type | reg_no | reg_year
  filing                  est_code | fil_no | fil_year   (confirm)
  party / advocate name   est_code | <name key> | reg_year | pend_disp   (confirm key names in the live test)

Response field names used below are the documented ones (cino, reg_no, date_next_list, interimorder, …).
The gateway JSON stubs do not define them, so `aslms napix-check` records real samples for review.
Parsing is defensive: a missing or renamed field yields None, never an exception."""

from __future__ import annotations

from datetime import date
from typing import Any

from aslms.core.errors import SourceNotFound
from aslms.core.logging import get_logger
from aslms.core.time import now_utc, parse_date
from aslms.integration.base import (
    BenchRef,
    CaseRecord,
    CauseListRef,
    CauseListRow,
    OrderRef,
    PartyRef,
    StatusRecord,
)
from aslms.integration.napix.client import NapixClient, NapixResult, nested_list

log = get_logger(__name__)

API = {
    "overview": "overview/overview",
    "state": "hc-state-api/state",
    "district": "hc-district-api/district",
    "bench": "hc-bench-master-api/bench",
    "case_type": "hc-case-type-master-api/casetypemaster",
    "act": "hc-act-master-api/actMaster",
    "causelist_bench": "hc-causelist-bench-api/causelistbench",
    "causelist_details": "hc-causelist-details-api/causelistdetails",
    "show_causelist": "hc-show-causelist-api/showcauselist",
    "cnr": "hc-cnr-api/CNR",
    "current_status": "hc-current-status-api/currentStatus",
    "show_business": "hc-show-business-api/showBusiness",
    "order": "hc-order-api/order",
    "case_search": "hc-case-search-api/casesearch",
    "filing": "hc-filing-api/Filing",
    "party_name": "hc-party-name-api/partyname",
    "advocate_name": "hc-advocate-name-api/advocatename",
}

ROW_KEYS = ("cino", "case_no", "case_number", "caseno", "reg_no")
LIST_KEYS = ("causelist_id", "cause_list_id", "cause_list_type", "causelist_type", "list_type")


def _s(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _i(v: Any) -> int | None:
    s = _s(v)
    return int(s) if s and s.isdigit() else None


def _fmt(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def _list_type(label: str | None) -> str:
    u = (label or "").upper()
    if "SUPPL" in u:
        return "supplementary"
    if "LAWAZIMA" in u:
        return "lawazima"
    if "VACATION" in u:
        return "vacation"
    if "DAILY" in u or not u:
        return "daily"
    return "other"


class NapixHighCourt:
    """`CourtSource` for one High Court establishment (Gauhati HC Principal Seat = GAHC01)."""

    name = "napix_hc"

    def __init__(self, client: NapixClient, est_code: str, state_code: str):
        self.client = client
        self.est_code = est_code
        self.state_code = state_code

    # ------------------------------------------------------------------ masters
    async def overview(self) -> NapixResult:
        return await self.client.call(API["overview"])

    async def state_master(self) -> list[dict[str, Any]]:
        return nested_list((await self.client.call(API["state"])).data)

    async def district_master(self) -> list[dict[str, Any]]:
        return nested_list((await self.client.call(API["district"], {"state_code": self.state_code})).data)

    async def bench_master(self) -> list[dict[str, Any]]:
        return nested_list((await self.client.call(API["bench"], {"state_code": self.state_code})).data)

    async def case_type_master(self) -> list[dict[str, Any]]:
        return nested_list((await self.client.call(API["case_type"], {"est_code": self.est_code})).data)

    async def act_master(self) -> list[dict[str, Any]]:
        """Act Master takes no input string (decisions log, 25 Sep)."""
        return nested_list((await self.client.call(API["act"])).data)

    # ------------------------------------------------------------------ cause lists
    async def causelist_benches(self, list_date: date) -> list[BenchRef]:
        try:
            res = await self.client.call(
                API["causelist_bench"], {"est_code": self.est_code, "causelist_date": _fmt(list_date)}
            )
        except SourceNotFound:
            return []
        out = []
        for b in nested_list(res.data):
            bench_id = _s(b.get("bench_id") or b.get("benchid"))
            if bench_id:
                out.append(
                    BenchRef(
                        bench_id=bench_id,
                        judge_names=_s(b.get("judge_name") or b.get("bench") or b.get("judges")),
                        raw=b,
                    )
                )
        return out

    async def _details(self, list_date: date, bench_id: str) -> list[dict[str, Any]]:
        try:
            res = await self.client.call(
                API["causelist_details"],
                {"est_code": self.est_code, "causelist_date": _fmt(list_date), "bench_id": bench_id},
            )
        except SourceNotFound:
            return []
        return nested_list(res.data)

    async def causelists_for_bench(self, list_date: date, bench_id: str) -> list[CauseListRef]:
        """Cause List Details may return the cause lists of the bench (ids + types) or the listed cases
        themselves — the live test decides. Both shapes are handled: rows are cached on a synthetic ref."""
        items = await self._details(list_date, bench_id)
        if not items:
            return []
        if _looks_like_rows(items):
            return [
                CauseListRef(
                    list_date=list_date,
                    bench_id=bench_id,
                    causelist_id="",
                    list_type="daily",
                    label=f"bench {bench_id} (rows from details)",
                    raw={"rows": items},
                )
            ]
        refs = []
        for cl in items:
            cl_id = _s(cl.get("causelist_id") or cl.get("cause_list_id")) or ""
            cl_type = _s(cl.get("cause_list_type") or cl.get("causelist_type") or cl.get("list_type"))
            refs.append(
                CauseListRef(
                    list_date=list_date,
                    bench_id=bench_id,
                    causelist_id=cl_id,
                    list_type=_list_type(cl_type),
                    label=_s(cl.get("bench") or cl.get("judge_name") or cl_type),
                    raw=cl,
                )
            )
        return refs

    async def causelist_rows(self, ref: CauseListRef) -> list[CauseListRow] | None:
        items = ref.raw.get("rows") if isinstance(ref.raw, dict) else None
        if items is None:
            items = await self._details(ref.list_date, ref.bench_id)
            if not _looks_like_rows(items):
                return None
        rows = []
        for n, it in enumerate(items, start=1):
            rows.append(
                CauseListRow(
                    sr_no=_i(it.get("sr_no") or it.get("srno") or it.get("serial_no")) or n,
                    cnr=(_s(it.get("cino")) or "").upper() or None,
                    case_no_text=_s(it.get("case_no") or it.get("case_number") or it.get("caseno")),
                    court_no=_s(it.get("court_no") or it.get("courtno")),
                    petitioner_text=_s(it.get("pet_name") or it.get("petitioner")),
                    respondent_text=_s(it.get("res_name") or it.get("respondent")),
                    pet_advocate_text=_s(it.get("pet_adv") or it.get("petitioner_advocate")),
                    res_advocate_text=_s(it.get("res_adv") or it.get("respondent_advocate")),
                    with_text=_s(it.get("connected") or it.get("with")),
                    remarks=_s(it.get("remarks") or it.get("purpose")),
                    raw=it,
                )
            )
        return rows

    async def causelist_pdf(self, ref: CauseListRef) -> bytes | None:
        if not ref.causelist_id:
            return None
        try:
            res = await self.client.call(
                API["show_causelist"],
                {
                    "est_code": self.est_code,
                    "bench_id": ref.bench_id,
                    "causelist_id": ref.causelist_id,
                    "causelist_date": _fmt(ref.list_date),
                },
            )
        except SourceNotFound:
            return None
        return res.pdf

    # ------------------------------------------------------------------ cases
    async def case_by_cnr(self, cnr: str) -> CaseRecord | None:
        cnr = cnr.strip().upper()
        try:
            res = await self.client.call(API["cnr"], {"cino": cnr})
        except SourceNotFound:
            return None
        c = res.data
        if not isinstance(c, dict):
            return None
        return parse_case_record(c, cnr)

    async def current_status(self, cnrs: list[str]) -> list[StatusRecord]:
        out: list[StatusRecord] = []
        clean = [c.strip().upper() for c in cnrs if c and c.strip()]
        for i in range(0, len(clean), 500):
            batch = clean[i : i + 500]
            try:
                res = await self.client.call(API["current_status"], {"cino": ",".join(batch)}, method="POST")
            except SourceNotFound:
                continue
            for c in nested_list(res.data) or (
                [res.data] if isinstance(res.data, dict) and res.data.get("cino") else []
            ):
                out.append(
                    StatusRecord(
                        cnr=(_s(c.get("cino")) or "").upper(),
                        status=_pend(c.get("pend_disp")),
                        next_hearing_date=parse_date(c.get("date_next_list")),
                        next_purpose=_s(c.get("purpose_name")),
                        last_hearing_date=parse_date(c.get("date_last_list")),
                        disposal_date=parse_date(c.get("date_of_decision")),
                        disposal_nature=_s(c.get("disp_nature")),
                        raw=c,
                    )
                )
        return out

    async def order_pdf(self, cnr: str, order: OrderRef) -> bytes | None:
        if not order.order_date:
            return None
        try:
            res = await self.client.call(
                API["order"],
                {"cino": cnr.upper(), "order_no": order.order_no, "order_date": _fmt(order.order_date)},
            )
        except SourceNotFound:
            return None
        return res.pdf

    async def business(self, cnr: str, business_date: date) -> dict[str, Any] | None:
        try:
            res = await self.client.call(
                API["show_business"], {"cino": cnr.upper(), "business_date": _fmt(business_date)}
            )
        except SourceNotFound:
            return None
        return res.data if isinstance(res.data, dict) else {"items": res.data}

    # ------------------------------------------------------------------ search
    async def search_case_number(
        self, case_type_code: int, reg_no: int | None, reg_year: int
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"est_code": self.est_code, "case_type": case_type_code}
        if reg_no is not None:
            params["reg_no"] = reg_no
        params["reg_year"] = reg_year
        try:
            return nested_list((await self.client.call(API["case_search"], params)).data)
        except SourceNotFound:
            return []

    async def search_party(
        self, name: str, reg_year: int | None = None, pending: bool | None = True
    ) -> list[dict[str, Any]]:
        """Search by Party Name. Key names follow the spec draft; confirm with `napix-check` samples."""
        params: dict[str, Any] = {"est_code": self.est_code, "litigant_name": name}
        if reg_year:
            params["reg_year"] = reg_year
        if pending is not None:
            params["pend_disp"] = "P" if pending else "D"
        try:
            return nested_list((await self.client.call(API["party_name"], params)).data)
        except SourceNotFound:
            return []

    async def search_advocate(
        self, name: str, reg_year: int | None = None, pending: bool | None = True
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"est_code": self.est_code, "advocate_name": name}
        if reg_year:
            params["reg_year"] = reg_year
        if pending is not None:
            params["pend_disp"] = "P" if pending else "D"
        try:
            return nested_list((await self.client.call(API["advocate_name"], params)).data)
        except SourceNotFound:
            return []

    async def search_filing(self, case_type_code: int, fil_no: int, fil_year: int) -> list[dict[str, Any]]:
        params = {
            "est_code": self.est_code,
            "case_type": case_type_code,
            "fil_no": fil_no,
            "fil_year": fil_year,
        }
        try:
            return nested_list((await self.client.call(API["filing"], params)).data)
        except SourceNotFound:
            return []


def _yes(v: Any) -> bool:
    return str(v or "").strip().upper() in ("Y", "YES", "1", "TRUE")


def _pend(v: Any) -> str:
    u = (_s(v) or "").upper()
    return "disposed" if u.startswith("D") else "pending" if u.startswith("P") else "unknown"


def _looks_like_rows(items: list[dict[str, Any]]) -> bool:
    if not items:
        return False
    first = items[0]
    has_row = any(k in first for k in ROW_KEYS)
    has_list = any(k in first for k in LIST_KEYS)
    return has_row and not has_list


def _party_names(obj: Any) -> list[str]:
    """`pet_extra_party` may be a dict `{party_no1: name, ...}`, a list, or a single string."""
    if isinstance(obj, dict):
        return [str(v).strip() for _, v in sorted(obj.items()) if isinstance(v, str) and v.strip()]
    if isinstance(obj, list):
        return [str(v).strip() for v in obj if isinstance(v, str) and v.strip()]
    if isinstance(obj, str) and obj.strip():
        return [obj.strip()]
    return []


def parse_case_record(c: dict[str, Any], cnr: str) -> CaseRecord:
    """Pure mapping from the CNR API dict to `CaseRecord`; unit-tested with recorded samples."""
    reg_type = _s(c.get("type_name_reg") or c.get("type_name"))
    reg_no, reg_year = _i(c.get("reg_no")), _i(c.get("reg_year"))
    fil_type = _s(c.get("type_name_fil")) or reg_type
    fil_no, fil_year = _s(c.get("fil_no")), _s(c.get("fil_year"))
    filing_no_text = f"{fil_type}/{fil_no}/{fil_year}" if fil_type and fil_no and fil_year else None

    parties: list[PartyRef] = []
    if _s(c.get("pet_name")):
        parties.append(PartyRef("petitioner", 1, str(c["pet_name"]).strip()))
    for i, name in enumerate(_party_names(c.get("pet_extra_party")), start=2):
        parties.append(PartyRef("petitioner", i, name))
    if _s(c.get("res_name")):
        parties.append(PartyRef("respondent", 1, str(c["res_name"]).strip()))
    for i, name in enumerate(_party_names(c.get("res_extra_party")), start=2):
        parties.append(PartyRef("respondent", i, name))

    orders: list[OrderRef] = []
    for o in nested_list(c.get("interimorder")):
        orders.append(OrderRef(str(o.get("order_no", "")), parse_date(o.get("order_date")), "interim", o))
    for o in nested_list(c.get("finalorder")):
        orders.append(OrderRef(str(o.get("order_no", "")), parse_date(o.get("order_date")), "final", o))

    acts = [
        {
            "act": _s(a.get("actname") or a.get("act_name")),
            "section": _s(a.get("section")),
            "code": _s(a.get("act_code") or a.get("national_act_code") or a.get("actcode")),
        }
        for a in nested_list(c.get("acts") or c.get("act"))
    ]
    applications = []
    for ia in nested_list(c.get("iafiling") or c.get("ia_filing")):
        no = _s(ia.get("ia_no") or ia.get("ia_number") or ia.get("ia_regno") or ia.get("application_no"))
        if no:
            applications.append(
                {
                    "ia_number": no[:64],
                    "party_name": _s(ia.get("party") or ia.get("party_name") or ia.get("ia_party")),
                    "status": (_s(ia.get("ia_status") or ia.get("status")) or "")[:64] or None,
                    "filing_date": parse_date(
                        ia.get("dt_filing") or ia.get("filing_date") or ia.get("ia_date")
                    ),
                    "raw": ia,
                }
            )
    lower_courts = []
    for level, prefix in (("appellate", "lower_court"), ("trial", "trial_lower_court")):
        name = _s(c.get(f"{prefix}_name") or c.get(f"{prefix}_court") or c.get(prefix))
        no = _s(c.get(f"{prefix}_case_no") or c.get(f"{prefix}_caseno") or c.get(f"{prefix}_no"))
        dec = parse_date(
            c.get(f"{prefix}_dec_dt") or c.get(f"{prefix}_decision_date") or c.get(f"{prefix}_date")
        )
        if name or no or dec:
            lower_courts.append(
                {
                    "level": level,
                    "court_name": name,
                    "case_no_text": no[:120] if no else None,
                    "decision_date": dec,
                    "raw": {k: v for k, v in c.items() if str(k).startswith(prefix)},
                }
            )
    objections = []
    for ob in nested_list(c.get("objections") or c.get("objection")):
        sd = parse_date(ob.get("scrutiny_date") or ob.get("dt_scrutiny") or ob.get("scrutiny_dt"))
        if sd:
            objections.append(
                {
                    "objection": _s(ob.get("objection") or ob.get("objection_text") or ob.get("remarks")),
                    "scrutiny_date": sd,
                    "compliance_by_date": parse_date(ob.get("compliance_by_date") or ob.get("dt_compliance")),
                    "receipt_date": parse_date(ob.get("receipt_date") or ob.get("dt_receipt")),
                    "raw": ob,
                }
            )
    links = nested_list(c.get("link_cases") or c.get("linked_cases"))
    category = c.get("category_details")
    category_text = _s(category.get("category")) if isinstance(category, dict) else _s(category)

    return CaseRecord(
        cnr=(_s(c.get("cino")) or cnr).upper(),
        case_type_text=reg_type,
        reg_no=reg_no,
        reg_year=reg_year,
        filing_no_text=filing_no_text,
        filing_date=parse_date(c.get("date_of_filing")),
        registration_date=parse_date(c.get("dt_regis")),
        status=_pend(c.get("pend_disp")),
        disposal_date=parse_date(c.get("date_of_decision")),
        disposal_nature=_s(c.get("disp_nature")),
        next_hearing_date=parse_date(c.get("date_next_list")),
        next_purpose=_s(c.get("purpose_name")),
        last_hearing_date=parse_date(c.get("date_last_list")),
        bench_id=_s(c.get("bench_id")),
        coram=_s(c.get("coram") or c.get("bench_name")),
        category=category_text,
        judicial_branch=_s(c.get("judicial_branch")),
        petitioner_summary=_s(c.get("pet_name")),
        respondent_summary=_s(c.get("res_name")),
        pet_advocate=_s(c.get("pet_adv")),
        res_advocate=_s(c.get("res_adv")),
        parties=parties,
        acts=acts,
        orders=orders,
        hearings=nested_list(c.get("historyofcasehearing") or c.get("history")),
        linked_case_nos=[
            str(lc.get("case_number") or lc.get("case_no"))
            for lc in links
            if lc.get("case_number") or lc.get("case_no")
        ],
        linked_cnrs=[str(c["main_matter_cino"]).upper()] if _s(c.get("main_matter_cino")) else [],
        fetched_at=now_utc(),
        raw=c,
        applications=applications,
        lower_courts=lower_courts,
        objections=objections,
        pet_legal_heir=_yes(c.get("pet_legal_heir")),
        res_legal_heir=_yes(c.get("res_legal_heir")),
        date_first_list=parse_date(c.get("date_first_list")),
        filing_case_type_text=_s(c.get("type_name_fil")),
        disposal_type=_s(c.get("disposal_type")),
        short_order=_s(c.get("short_order")),
        date_filing_disp=parse_date(c.get("date_filing_disp")),
        reason_for_rej=_s(c.get("reason_for_rej")),
        sub_category=_s(c.get("sub_category")),
        fir_no=_s(c.get("fir_no")),
        fir_year=_i(c.get("fir_year")),
        police_station=_s(c.get("police_station")),
        state_name=_s(c.get("state_name")),
        dist_name=_s(c.get("dist_name")),
    )
