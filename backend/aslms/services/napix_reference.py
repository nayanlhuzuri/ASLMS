"""The in-app NAPIX reference of the System health console (design `system-health-inspector`, decisions 4, 8, 12):
pure constants and lookups, no database and no call.

- `STATUS`: every NAPIX status and HTTP outcome with its plain meaning, from the specification's per-API
  "Errors/Status" tables and Annexure C, corrected by `docs/napix_integration_notes.md` where live behaviour differs.
- `INPUTS`: per court API, the plain parameters in the order `hc.py` sends them, transcribed from the
  specification's "Request String" tables (mandatory or optional, format, meaning), with ASLMS's notes and the
  console's validation rule (decision 8). A test checks the names and order against the preview of `hc.py`.
- `OUTPUTS`: the field inventory's paths and types per section (`docs/specs/napix_field_inventory.md`, no examples:
  they include party names). A test checks it against the inventory file.
- `DOCS`, `DOC_PAGES`, `GENERAL_LINKS`, `TOKEN_LINKS`: the three NAPIX documents (pinned by SHA-256) and the PDF page
  of each API's section, verified on the PDFs (a test checks each heading on its page).
- `BUILD_STEPS`, `READ_STEPS`: how a request is built and how an answer is read, notes §3 and §4 in plain words."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# ------------------------------------------------------------------------------------------------ status meanings

NAPIX_MEANINGS: dict[int, tuple[str, str]] = {
    600: (
        "INVALID_CNR",
        'The CNR is not in the prescribed format. ASLMS reads it as "answered, nothing found".',
    ),
    601: ("INVALID_DATE", "The business or order date is not valid."),
    602: ("INVALID_ORDER_NO", "The order number is not valid."),
    603: ("INVALID_EST_CODE", "The court code is not valid (for example GAHC01)."),
    604: ("INVALID_CASE_TYPE", "The case type is not valid."),
    605: ("INVALID_REG_NO", "The registration number is not valid."),
    606: (
        "INVALID_REG_YEAR",
        "The registration year is not valid. Also the court's answer to a blank year in the party and advocate "
        "searches (notes §7).",
    ),
    607: ("INVALID_FIL_NO", "The filing number is not valid."),
    608: ("INVALID_FIL_YEAR", "The filing year is not valid."),
    609: ("INVALID_PEND_DISP", "The pending / disposed value is not P or D."),
    610: ("INVALID_LITIGANT_NAME", "The party name is not valid."),
    614: ("INVALID_ADVOCATE_NAME", "The advocate name is not valid."),
    616: ("INVALID_CAUSELIST_DATE", "The cause-list date is not valid."),
    624: ("INVALID_STATE_CODE", "The state code is not valid."),
    626: (
        "INVALID_TOKEN",
        "The request did not decrypt: the Authentication Key in .env is not the court's key for this dept_id "
        "(notes §3).",
    ),
    627: ("INVALID_DEPT_ID", "The Department ID is not valid."),
    628: ("RECORD_NOT_FOUND", "A valid request with no data. Not an error for ASLMS."),
    629: ("UNEXPECTED_ERROR", "The court's service did not respond."),
    631: ("API_ACCESS_NOT_ALLOWED", "The subscription does not include this API."),
    632: ("INVALID_VERSION", "The version is not valid."),
    633: ("INVALID_BENCH_ID", "The bench ID is not valid."),
    634: ("INVALID_CAUSELIST_ID", "The cause-list ID is not valid."),
}

HTTP_ROWS: tuple[tuple[str, str], ...] = (
    ("HTTP 200", "Everything is normal: the gateway answered."),
    ("HTTP 401", "The access token was missing or expired; ASLMS renewed it and repeated the call once."),
    (
        "HTTP 404 + httpCode body",
        "The gateway found no such path, or the API is not subscribed; the court was never reached.",
    ),
    (
        "HTTP 405 / 414",
        "Wrong method on Current Status / more than about 300 CNRs in one call (notes §7).",
    ),
    ("HTTP 429, 500, 502, 503, 504", "The gateway or court was unavailable."),
    ("HTTP 200, empty body", "The gateway's known intermittent fault (notes §5)."),
)


def napix_meaning(code: int | None) -> str | None:
    if code is None:
        return None
    row = NAPIX_MEANINGS.get(code)
    return f"{row[0]}: {row[1]}" if row else "A status the specification does not list."


def http_meaning(status: int | None, error_family: str | None = None) -> str | None:
    """The plain meaning of an HTTP status of a court call (decision 4)."""
    if status is None:
        return None
    if status == 200:
        if error_family == "NapixEmptyResponse":
            return HTTP_ROWS[5][1]
        return HTTP_ROWS[0][1]
    if status == 401:
        return HTTP_ROWS[1][1]
    if status == 404:
        return HTTP_ROWS[2][1]
    if status in (405, 414):
        return HTTP_ROWS[3][1]
    if status in (429, 500, 502, 503, 504):
        return HTTP_ROWS[4][1]
    return f"The gateway answered HTTP {status}."


# the codes each API's "Errors/Status" table lists in the specification (PDF pages of DOC_PAGES)
SPEC_CODES: dict[str, tuple[int, ...]] = {
    "overview": (626, 627, 629),
    "cnr": (600, 626, 627, 628, 629, 632),
    "show_business": (600, 601, 626, 627, 628, 629, 632),
    "order": (600, 601, 602, 626, 627, 628, 629, 632),
    "current_status": (600, 626, 627, 628, 629, 632),
    "case_search": (603, 604, 605, 606, 626, 627, 628, 629, 632),
    "filing": (603, 604, 607, 608, 626, 627, 628, 629, 632),
    "party_name": (603, 606, 609, 610, 626, 627, 628, 629, 632),
    "advocate_name": (603, 606, 609, 614, 626, 627, 628, 629, 632),
    "causelist_bench": (603, 616, 626, 627, 628, 629, 632),
    "causelist_details": (603, 616, 626, 627, 628, 629, 632, 633),
    "show_causelist": (603, 616, 626, 627, 628, 629, 632, 633, 634),
    "state": (626, 627, 628, 629, 632),
    "district": (624, 626, 627, 628, 629, 632),
    "bench_master": (626, 627, 628, 629, 632, 633),
    "act": (626, 627, 628, 629, 632),
    "case_type": (603, 626, 627, 628, 629, 632),
}


def statuses(key: str | None = None) -> list[dict[str, Any]]:
    """The status table, the codes the specification lists for `key` first (`listed`), then the HTTP rows."""
    listed = SPEC_CODES.get(key or "", ())
    codes = list(listed) + [c for c in sorted(NAPIX_MEANINGS) if c not in listed]
    out = [
        {"code": str(c), "name": NAPIX_MEANINGS[c][0], "meaning": NAPIX_MEANINGS[c][1], "listed": c in listed}
        for c in codes
    ]
    out += [{"code": code, "name": None, "meaning": meaning, "listed": False} for code, meaning in HTTP_ROWS]
    return out


# ------------------------------------------------------------------------------------------------ inputs


@dataclass(frozen=True)
class InputSpec:
    name: str
    mandatory: bool  # as the specification says
    format: str
    meaning: str
    rule: str  # the console's validation rule (napix_inspect.validate)
    note: str | None = None  # ASLMS's note where live behaviour differs
    required: bool = True  # the console needs a value (all parameters today)


_EST = InputSpec(
    "est_code",
    True,
    "6 characters, letters and digits (e.g. GAHC01)",
    "The court (establishment) code, from the Bench API.",
    "est_code",
    "One of the court codes ASLMS holds from the bench master (GAHC01 to GAHC04).",
)
_STATE = InputSpec(
    "state_code",
    True,
    "2 digits",
    "The state code from the High Court State Master.",
    "state_code",
    "18 is the Gauhati High Court; 6 is Chhattisgarh (notes §1).",
)
_CINO = InputSpec("cino", True, "16 letters and digits", "The case's CNR.", "cnr")


def _date(name: str, meaning: str) -> InputSpec:
    return InputSpec(name, True, "yyyy-mm-dd", meaning, "date")


_LIST_DATE = _date("causelist_date", "The cause-list date.")
_BENCH = InputSpec(
    "bench_id", True, "4 digit bench ID (spec)", "The bench, from the Causelist Bench API.", "digits6",
    "ASLMS accepts 1 to 6 digits.",
)  # fmt: skip
_CASE_TYPE = InputSpec(
    "case_type",
    True,
    "Integer (e.g. 15)",
    "The case type code, from the Case Type Master API.",
    "case_type",
    "The master's numeric code (case_type_id in a dossier), held for the court named by est_code.",
)
_PEND = InputSpec(
    "pend_disp", True, "P or D", "P for pending cases, D for disposed cases.", "pend_disp",
    "Must match the case: P does not find a disposed case (notes §7).",
)  # fmt: skip
_REG_YEAR = InputSpec("reg_year", True, "4 digits (e.g. 2019)", "The registration year of the case.", "year")


def _year_needed(spec: InputSpec) -> InputSpec:
    return InputSpec(
        spec.name, spec.mandatory, spec.format, spec.meaning, spec.rule,
        "Mandatory: a blank year gives 606 INVALID_REG_YEAR (notes §7).",
    )  # fmt: skip


INPUTS: dict[str, tuple[InputSpec, ...]] = {
    "overview": (),
    "state": (),
    "district": (_STATE,),
    "bench_master": (_STATE,),
    "case_type": (_EST,),
    "act": (),
    "causelist_bench": (_EST, _LIST_DATE),
    "causelist_details": (_EST, _LIST_DATE, _BENCH),
    "show_causelist": (
        _EST,
        _BENCH,
        InputSpec(
            "causelist_id",
            True,
            "4 digit cause-list ID (spec)",
            "The list, from the Causelist API.",
            "digits6",
            "ASLMS accepts 1 to 6 digits.",
        ),
        _LIST_DATE,
    ),  # fmt: skip
    "cnr": (_CINO,),
    "current_status": (
        InputSpec(
            "cino",
            True,
            "16 letters and digits; the spec allows up to 500, comma separated",
            "The CNR of each case.",
            "cnr",
            "The console sends one CNR; the gateway refuses more than about 300 (notes §7).",
        ),
    ),  # fmt: skip
    "order": (
        _CINO,
        InputSpec("order_no", True, "Order number", "The order's number, from the case's orders.", "digits5"),
        _date("order_date", "The date of the order or judgment."),
    ),
    "show_business": (
        _CINO,
        _date("business_date", "The date of the court proceedings (from the case history)."),
    ),
    "case_search": (
        _EST,
        _CASE_TYPE,
        InputSpec(
            "reg_no",
            False,
            "Integer, up to 7 digits (e.g. 234)",
            "The registration number of the case.",
            "digits7",
            "Optional in the spec (without it every case of the type and year is listed); required by the console "
            "so one send never lists a whole case type and year.",
        ),
        _REG_YEAR,
    ),  # fmt: skip
    "filing": (
        _EST,
        _CASE_TYPE,
        InputSpec(
            "fil_no", True, "Integer, up to 7 digits (e.g. 234)", "The filing number of the case.", "digits7"
        ),
        InputSpec("fil_year", True, "4 digits (e.g. 2019)", "The filing year of the case.", "year"),
    ),
    "party_name": (
        _EST,
        _PEND,
        InputSpec(
            "litigant_name",
            True,
            "3 to 99 characters",
            "The petitioner's or respondent's name.",
            "name",
            "The court matches the whole phrase in the petitioner or respondent name (notes §7).",
        ),
        _year_needed(_REG_YEAR),
    ),  # fmt: skip
    "advocate_name": (
        _EST,
        _PEND,
        InputSpec(
            "advocate_name",
            True,
            "3 to 99 characters",
            "The advocate's name.",
            "name",
            "The court matches part of a name; the honorific does not matter (notes §7).",
        ),
        _year_needed(_REG_YEAR),
    ),  # fmt: skip
}

# a NAPIX parameter name -> the key the held sample (napix_samples) and the catalogue's `invoke` use
PARAM_KEYS: dict[str, str] = {
    "cino": "cnr",
    "causelist_date": "list_date",
    "litigant_name": "name",
    "advocate_name": "name",
}


def sample_key(param: str) -> str:
    return PARAM_KEYS.get(param, param)


def input_specs(key: str) -> tuple[InputSpec, ...]:
    return INPUTS[key]


# ------------------------------------------------------------------------------------------------ documents

DOCS: dict[str, dict[str, Any]] = {
    "hc_spec": {
        "file": "HighCourt_Open_API_Specifications_1.0_NAPIX_07.09.2023-1-1-1.pdf",
        "title": "High Court Open API Specification v1.0",
        "pages": 85,
        "sha256": "b84822ab39abe058f2334378a9c6c7f199a8993975a344802dd09e9fd5ec9c1b",
    },
    "subscriber_manual": {
        "file": "NAPIX Subscriber UM V1.5 22.04.2025-4-1-1.pdf",
        "title": "NAPIX Subscriber Manual v1.5",
        "pages": 23,
        "sha256": "4407afc09c50199f1bd963a774573277536d498a071a18fc09b5fe3ce9065be9",
    },
    "ecourts_spec": {
        "file": "eCourts_Open_API_Specifications_NAPIX_1.3_22.04.2025-1-1-1.pdf",
        "title": "eCourts (District Courts) Open API Specification v1.3",
        "pages": 152,
        "sha256": "0943dd47ca83ddfe6eeb5eb0b067cd4204622df139e31973477334bab14141ab",
    },
}

# the High Court specification's PDF page (printed number = PDF page index) and section of each court API
DOC_PAGES: dict[str, tuple[int, str]] = {
    "overview": (10, "5.1 Overview API"),
    "cnr": (12, "6.1 Search by CNR API"),
    "show_business": (20, "6.2 Show Business API"),
    "order": (23, "6.3 Show Orders API"),
    "current_status": (24, "6.4 Search by CNR (Current Case Status) API"),
    "case_search": (29, "6.5 Search by Case Number API"),
    "filing": (31, "6.6 Search by Filing Number API"),
    "party_name": (33, "6.7 Search by Party Name API"),
    "advocate_name": (35, "6.8 Search by Advocate Name API"),
    "causelist_bench": (42, "7.1 Causelist Bench API"),
    "causelist_details": (44, "7.2 Causelist API"),
    "show_causelist": (46, "7.3 Show Causelist API"),
    "state": (56, "9.1 High Court State Master API"),
    "district": (58, "9.2 District Master API"),
    "bench_master": (60, "9.3 Bench API"),
    "act": (63, "10.1 Acts Master API"),
    "case_type": (65, "10.2 Case Type Master API"),
}

# (doc, PDF page, label, a heading printed on that page)
GENERAL_LINKS: tuple[tuple[str, int, str, str], ...] = (
    ("hc_spec", 5, "List of eCourt APIs", "List of eCourt APIs"),
    ("hc_spec", 8, "URL structure", "https://delhigw.napix.gov.in/nic/"),
    ("hc_spec", 9, "Service Request API", "Service Request API"),
    ("hc_spec", 68, "Annexure A: encryption and hash", "Annexure-A"),
    ("hc_spec", 71, "Annexure B: response", "Annexure-B"),
    ("hc_spec", 78, "Using Postman", "API Consumption using Postman"),
    ("hc_spec", 85, "Annexure C: HTTP status codes", "Annexure-C"),
    ("subscriber_manual", 10, "Token generation", "Token Generation"),
    ("subscriber_manual", 16, "Test response", "Test Response"),
    ("subscriber_manual", 20, "Possible errors", "Possible errors"),
    ("subscriber_manual", 22, "Token expired", "token has expired"),
    ("subscriber_manual", 23, "Annexures A and B (fixed and per-user keys)", "Annexure B"),
)
# the token modal's Documentation tab (decision 10)
TOKEN_LINKS: tuple[tuple[str, int, str, str], ...] = (
    ("subscriber_manual", 10, "Token generation", "Token Generation"),
    ("subscriber_manual", 22, "Token expired", "token has expired"),
    ("subscriber_manual", 23, "Annexures A and B (fixed and per-user keys)", "Annexure B"),
    ("hc_spec", 78, "Using Postman", "API Consumption using Postman"),
)
TOKEN_DOC: tuple[str, int, str] = ("subscriber_manual", 10, "2.2 Token Generation")


def doc_link(key: str) -> dict[str, Any]:
    page, section = DOC_PAGES[key]
    return {"doc": "hc_spec", "page": page, "section": section}


def links(rows: tuple[tuple[str, int, str, str], ...]) -> list[dict[str, Any]]:
    return [{"doc": doc, "page": page, "label": label} for doc, page, label, _heading in rows]


# ------------------------------------------------------------------------------------------------ how it works

BUILD_STEPS: tuple[str, ...] = (
    "The plain string: the parameters as key=value pairs joined with |, in the order the specification lists for "
    "the API, with no spaces (e.g. est_code=GAHC01|causelist_date=2026-09-24). An API with no input sends the empty "
    "string.",
    "request_str: the plain string encrypted with AES-128-CBC; the key and the IV are the Authentication Key "
    "trimmed and cut or zero-padded to 16 bytes; PKCS7 padding; Base64. The empty string is encrypted too.",
    "request_token: HMAC-SHA256 of the plain string (not the encrypted one) with the published hash key 15081947, "
    "in lowercase hex.",
    "The four query parameters on every call: dept_id, request_str (URL-encoded), request_token and version. Current "
    "Status is a POST, but its four parameters also travel in the query string.",
    "The header Authorization: Bearer with the access token from the token endpoint (renewed when it expires).",
)
READ_STEPS: tuple[str, ...] = (
    "The gateway answers with Content-Type text/html even for JSON; the body is read as JSON, tolerating text around "
    "it.",
    "Success is {response_str, response_token, version}: response_str is decrypted with the same key and IV into "
    "JSON.",
    "The signature: HMAC-SHA256 of the decrypted text with 15081947 should equal response_token. PDF answers do not "
    "always match (notes §4); a mismatch is recorded, never fatal.",
    "Collections arrive as objects keyed case1, case2, … (or sr_no1, state1, …), not as arrays; ASLMS sorts them "
    "by number. The field inventory writes them as [].",
    "Order and cause-list PDFs arrive as a JSON string of Base64 inside response_str.",
    'Errors come as a PHP print_r text, an encrypted {"status": …}, a gateway {"httpCode": …} body, an HTTP status, '
    "or an empty 200 body (the gateway's intermittent fault).",
)

PDF_APIS = frozenset({"order", "show_causelist"})
# the inventory section of each court API (the masters are named *_master there)
INVENTORY_SECTION: dict[str, str] = {
    "overview": "overview",
    "state": "state_master",
    "district": "district_master",
    "bench_master": "bench_master",
    "case_type": "case_type_master",
    "act": "act_master",
    "causelist_bench": "causelist_bench",
    "causelist_details": "causelist_details",
    "cnr": "cnr",
    "current_status": "current_status",
    "show_business": "show_business",
    "case_search": "case_search",
    "filing": "filing",
    "party_name": "party_name",
    "advocate_name": "advocate_name",
}


def outputs(key: str) -> dict[str, Any]:
    if key in PDF_APIS:
        return {"kind": "pdf", "note": "a PDF (Base64 inside response_str)", "paths": []}
    section = INVENTORY_SECTION.get(key)
    rows = OUTPUTS.get(section or "", ())
    return {"kind": "json", "note": None, "paths": [{"path": p, "type": t} for p, t in rows]}


def inventory_paths(key: str) -> list[str]:
    return [p for p, _t in OUTPUTS.get(INVENTORY_SECTION.get(key, ""), ())]


def reference(key: str) -> dict[str, Any]:
    """`ReferenceOut` of one court API."""
    return {
        "api": key,
        "inputs": [
            {
                "name": i.name,
                "mandatory": i.mandatory,
                "required": i.required,
                "format": i.format,
                "meaning": i.meaning,
                "note": i.note,
            }
            for i in INPUTS[key]
        ],
        "outputs": outputs(key),
        "statuses": statuses(key),
        "build_steps": list(BUILD_STEPS),
        "read_steps": list(READ_STEPS),
        "doc": doc_link(key),
        "general_links": links(GENERAL_LINKS),
    }


TOKEN_OUTPUTS: tuple[tuple[str, str], ...] = (
    ("access_token", "str"),
    ("token_type", "str"),
    ("scope", "str"),
    ("consented_on", "int"),
    ("expires_in", "int"),
)


def token_reference() -> dict[str, Any]:
    """The token modal's reference (`GET …/napix/token/reference`): no inputs; the token answer's fields (notes §2;
    the value of `access_token` is never shown); the HTTP rows; the Subscriber Manual links."""
    doc, page, section = TOKEN_DOC
    return {
        "api": "token",
        "inputs": [],
        "outputs": {
            "kind": "json",
            "note": None,
            "paths": [{"path": p, "type": t} for p, t in TOKEN_OUTPUTS],
        },
        "statuses": [
            {"code": code, "name": None, "meaning": m, "listed": False} for code, m in HTTP_ROWS[:5]
        ],
        "build_steps": [
            "POST to the token endpoint with Basic authentication (the client key and secret from .env).",
            "Body grant_type=client_credentials&scope=napix as application/x-www-form-urlencoded.",
            "The answer carries access_token, token_type Bearer, scope and expires_in (3600 s).",
        ],
        "read_steps": [],
        "doc": {"doc": doc, "page": page, "section": section},
        "general_links": links(TOKEN_LINKS),
    }


# ------------------------------------------------------------------------------------------------ the field inventory
# Generated from docs/specs/napix_field_inventory.md (paths and types; never the examples). A test keeps it equal to
# the file: regenerate this block when `aslms napix-fields` changes the inventory.
OUTPUTS: dict[str, tuple[tuple[str, str], ...]] = {
    "act_master": (
        ("[].actname", "str"),
        ("[].national_act_code", "str"),
    ),
    "advocate_name": (
        ("casenos[].cino", "str"),
        ("casenos[].pet_name", "str"),
        ("casenos[].reg_no", "str"),
        ("casenos[].reg_year", "str"),
        ("casenos[].res_name", "str"),
        ("casenos[].type_name", "str"),
        ("establishment_name", "str"),
    ),
    "bench_master": (
        ("benches[].bench_id", "str"),
        ("benches[].bench_name", "str"),
        ("benches[].est_code", "str"),
    ),
    "case_search": (
        ("casenos[].cino", "str"),
        ("casenos[].pet_name", "str"),
        ("casenos[].police_st_code", "str"),
        ("casenos[].reg_no", "str"),
        ("casenos[].reg_year", "str"),
        ("casenos[].res_name", "str"),
        ("casenos[].type_name", "str"),
        ("establishment_name", "str"),
    ),
    "case_type_master": (
        ("[].case_type", "str"),
        ("[].type_name", "str"),
    ),
    "causelist_bench": (
        ("[].bench_id", "int"),
        ("[].judge_name", "str"),
    ),
    "causelist_details": (
        ("[].bench", "str"),
        ("[].bench_id", "int"),
        ("[].cause_list_type", "str"),
        ("[].causelist_id", "int"),
    ),
    "cnr": (
        ("acts[].actname", "str"),
        ("acts[].section", "str"),
        ("bench_id", "int"),
        ("bench_name", "str"),
        ("bench_type", "int"),
        ("case_type_id", "int"),
        ("category_details.category", "str"),
        ("cino", "str"),
        ("coram", "str"),
        ("court_est_name", "str"),
        ("date_filing_disp", "str"),
        ("date_first_list", "str"),
        ("date_judgement_pronounced", "null"),
        ("date_judgement_reserved", "null"),
        ("date_last_list", "str"),
        ("date_next_list", "str"),
        ("date_of_decision", "null, str"),
        ("date_of_filing", "str"),
        ("desgname", "str"),
        ("disposal_type", "null, str"),
        ("dist_name", "str"),
        ("document_details.case_dist_code", "int"),
        ("document_details.case_state_code", "int"),
        ("dt_regis", "str"),
        ("est_code", "str"),
        ("fil_no", "str"),
        ("fil_year", "str"),
        ("finalorder", "empty-list"),
        ("finalorder[].date_judgement_pronounced", "null"),
        ("finalorder[].date_judgement_reserved", "null"),
        ("finalorder[].order_date", "str"),
        ("finalorder[].order_details", "str"),
        ("finalorder[].order_judge_name", "str"),
        ("finalorder[].order_no", "str"),
        ("fir_no", "null"),
        ("fir_year", "null"),
        ("historyofcasehearing[].business_date", "str"),
        ("historyofcasehearing[].causelist_type", "str"),
        ("historyofcasehearing[].hearing_date", "str"),
        ("historyofcasehearing[].judge_name", "str"),
        ("historyofcasehearing[].purpose_of_listing", "str"),
        ("iafiling", "empty-list"),
        ("interimorder", "empty-list"),
        ("interimorder[].date_judgement_pronounced", "null"),
        ("interimorder[].date_judgement_reserved", "null"),
        ("interimorder[].order_date", "str"),
        ("interimorder[].order_details", "str"),
        ("interimorder[].order_judge_name", "str"),
        ("interimorder[].order_no", "int"),
        ("judicial_branch", "str"),
        ("lower_court_caseno", "int"),
        ("lower_court_dec_dt", "str"),
        ("lower_court_name", "null"),
        ("main_matter", "str"),
        ("main_matter_cino", "str"),
        ("objections", "empty-list"),
        ("pend_disp", "str"),
        ("pet_adv", "str"),
        ("pet_extra_party", "empty-list"),
        ("pet_extra_party.party_no1", "str"),
        ("pet_extra_party.party_no10", "str"),
        ("pet_extra_party.party_no11", "str"),
        ("pet_extra_party.party_no12", "str"),
        ("pet_extra_party.party_no13", "str"),
        ("pet_extra_party.party_no14", "str"),
        ("pet_extra_party.party_no15", "str"),
        ("pet_extra_party.party_no16", "str"),
        ("pet_extra_party.party_no17", "str"),
        ("pet_extra_party.party_no18", "str"),
        ("pet_extra_party.party_no19", "str"),
        ("pet_extra_party.party_no2", "str"),
        ("pet_extra_party.party_no20", "str"),
        ("pet_extra_party.party_no21", "str"),
        ("pet_extra_party.party_no22", "str"),
        ("pet_extra_party.party_no23", "str"),
        ("pet_extra_party.party_no24", "str"),
        ("pet_extra_party.party_no25", "str"),
        ("pet_extra_party.party_no26", "str"),
        ("pet_extra_party.party_no27", "str"),
        ("pet_extra_party.party_no28", "str"),
        ("pet_extra_party.party_no29", "str"),
        ("pet_extra_party.party_no3", "str"),
        ("pet_extra_party.party_no30", "str"),
        ("pet_extra_party.party_no31", "str"),
        ("pet_extra_party.party_no32", "str"),
        ("pet_extra_party.party_no33", "str"),
        ("pet_extra_party.party_no34", "str"),
        ("pet_extra_party.party_no35", "str"),
        ("pet_extra_party.party_no36", "str"),
        ("pet_extra_party.party_no37", "str"),
        ("pet_extra_party.party_no38", "str"),
        ("pet_extra_party.party_no39", "str"),
        ("pet_extra_party.party_no4", "str"),
        ("pet_extra_party.party_no40", "str"),
        ("pet_extra_party.party_no41", "str"),
        ("pet_extra_party.party_no42", "str"),
        ("pet_extra_party.party_no43", "str"),
        ("pet_extra_party.party_no44", "str"),
        ("pet_extra_party.party_no45", "str"),
        ("pet_extra_party.party_no46", "str"),
        ("pet_extra_party.party_no47", "str"),
        ("pet_extra_party.party_no48", "str"),
        ("pet_extra_party.party_no49", "str"),
        ("pet_extra_party.party_no5", "str"),
        ("pet_extra_party.party_no50", "str"),
        ("pet_extra_party.party_no51", "str"),
        ("pet_extra_party.party_no52", "str"),
        ("pet_extra_party.party_no53", "str"),
        ("pet_extra_party.party_no54", "str"),
        ("pet_extra_party.party_no55", "str"),
        ("pet_extra_party.party_no56", "str"),
        ("pet_extra_party.party_no57", "str"),
        ("pet_extra_party.party_no58", "str"),
        ("pet_extra_party.party_no59", "str"),
        ("pet_extra_party.party_no6", "str"),
        ("pet_extra_party.party_no60", "str"),
        ("pet_extra_party.party_no61", "str"),
        ("pet_extra_party.party_no62", "str"),
        ("pet_extra_party.party_no63", "str"),
        ("pet_extra_party.party_no64", "str"),
        ("pet_extra_party.party_no65", "str"),
        ("pet_extra_party.party_no66", "str"),
        ("pet_extra_party.party_no7", "str"),
        ("pet_extra_party.party_no8", "str"),
        ("pet_extra_party.party_no9", "str"),
        ("pet_legal_heir", "str"),
        ("pet_name", "str"),
        ("police_st_code", "null"),
        ("police_station", "null"),
        ("purpose_name", "str"),
        ("reason_for_rej", "str"),
        ("reg_no", "str"),
        ("reg_year", "str"),
        ("res_adv", "str"),
        ("res_extra_party.party_no1", "str"),
        ("res_extra_party.party_no10", "str"),
        ("res_extra_party.party_no11", "str"),
        ("res_extra_party.party_no12", "str"),
        ("res_extra_party.party_no13", "str"),
        ("res_extra_party.party_no2", "str"),
        ("res_extra_party.party_no3", "str"),
        ("res_extra_party.party_no4", "str"),
        ("res_extra_party.party_no5", "str"),
        ("res_extra_party.party_no6", "str"),
        ("res_extra_party.party_no7", "str"),
        ("res_extra_party.party_no8", "str"),
        ("res_extra_party.party_no9", "str"),
        ("res_legal_heir", "str"),
        ("res_name", "str"),
        ("short_order", "null, str"),
        ("state_name", "str"),
        ("transfer", "empty-list"),
        ("trial_lower_court_caseno", "str"),
        ("trial_lower_court_dec_dt", "null"),
        ("trial_lower_court_name", "null"),
        ("type_name_fil", "str"),
        ("type_name_reg", "str"),
        ("uniform_code", "null"),
        ("writinfo", "empty-list"),
    ),
    "current_status": (
        ("[].bench_id", "str"),
        ("[].bench_name", "str"),
        ("[].case_type_id", "null"),
        ("[].cino", "str"),
        ("[].coram", "str"),
        ("[].date_first_list", "str"),
        ("[].date_last_list", "str"),
        ("[].date_next_list", "str"),
        ("[].date_of_decision", "str"),
        ("[].date_of_filing", "str"),
        ("[].desgname", "str"),
        ("[].disp_nature", "null, str"),
        ("[].dt_regis", "str"),
        ("[].fil_no", "str"),
        ("[].fil_year", "str"),
        ("[].goshwara_no", "str"),
        ("[].judicial_branch", "str"),
        ("[].pend_disp", "str"),
        ("[].pet_name", "str"),
        ("[].purpose_name", "str"),
        ("[].reg_no", "str"),
        ("[].reg_year", "str"),
        ("[].res_name", "str"),
        ("[].type_name", "str"),
    ),
    "district_master": (
        ("[].dist_code", "int"),
        ("[].dist_name", "str"),
    ),
    "filing": (
        ("casenos[].cino", "str"),
        ("casenos[].fil_no", "str"),
        ("casenos[].fil_year", "str"),
        ("casenos[].pet_name", "str"),
        ("casenos[].res_name", "str"),
        ("casenos[].type_name", "str"),
        ("establishment_name", "str"),
    ),
    "overview": (
        ("consumes", "str"),
        ("contact", "str"),
        ("license", "str"),
        ("overview", "str"),
        ("produces", "str"),
        ("uri_scheme", "str"),
        ("version", "str"),
    ),
    "party_name": (
        ("casenos[].case_type_id", "str"),
        ("casenos[].cino", "str"),
        ("casenos[].pet_name", "str"),
        ("casenos[].police_st_code", "str"),
        ("casenos[].reg_no", "str"),
        ("casenos[].reg_year", "str"),
        ("casenos[].res_name", "str"),
        ("casenos[].type_name", "str"),
        ("casenos[].uniform_code", "null"),
        ("establishment_name", "str"),
    ),
    "show_business": (
        ("business", "str"),
        ("business_date", "str"),
        ("case_number", "str"),
        ("desgname", "str"),
        ("short_order_det", "null, str"),
    ),
    "state_master": (
        ("state[].state_code", "int"),
        ("state[].state_name", "str"),
    ),
}
