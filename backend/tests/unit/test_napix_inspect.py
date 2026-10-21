"""The console's pure parts (design `system-health-inspector`, decisions 2-9 and 12): the structure of an answer in
the field inventory's notation and never a value, the inventory check, the reference against `hc.py` and the
inventory file, the pinned NAPIX documents and their pages, the Postman scripts against the repository collection,
the templates with placeholders only, the dept_id mask and the validation rules."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import Path

import pytest

from aslms.cli.napix_fields import api_name
from aslms.core.config import Settings
from aslms.integration.napix.client import NAPIX_STATUS
from aslms.integration.napix.crypto import NapixCrypto
from aslms.integration.napix.preview import preview
from aslms.services import napix_inspect as ni
from aslms.services import napix_reference as ref
from aslms.services.system_health import BY_KEY
from tests.unit.test_napix_preview import VALUES

ROOT = Path(__file__).resolve().parents[3]
SAMPLES = ROOT / "docs" / "specs" / "samples"
INVENTORY = ROOT / "docs" / "specs" / "napix_field_inventory.md"
POSTMAN = ROOT / "docs" / "postman" / "NAPIX eCourt APIs.postman_collection.json"
PDFS = ROOT / "docs" / "specs" / "pdf"
SECTION_KEY = {v: k for k, v in ref.INVENTORY_SECTION.items()}


def settings(**kw) -> Settings:
    return Settings(_env_file=None, napix_base_url="https://delhigw.napix.gov.in/nic/ecourts", **kw)


def _values(obj, out: set[str]) -> None:
    if isinstance(obj, dict):
        for v in obj.values():
            _values(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _values(v, out)
    elif isinstance(obj, str):
        out.add(obj)


def _keys(obj, out: set[str]) -> None:
    if isinstance(obj, dict):
        out.update(str(k) for k in obj)
        for v in obj.values():
            _keys(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _keys(v, out)


# ------------------------------------------------------------------------------------------------ structure


@pytest.mark.parametrize("sample", sorted(p.name for p in SAMPLES.glob("*.json")))
def test_structure_collapses_numbered_collections(sample):
    data = json.loads((SAMPLES / sample).read_text(encoding="utf-8"))
    if isinstance(data, dict) and "response_str" in data:
        pytest.skip("an encrypted envelope saved by hand: the inventory skips it too")
    section = api_name(SAMPLES / sample)
    out = ni.structure(data, max_paths=10_000)
    paths = [p["path"] for p in out["paths"]]
    inventory = {p for p, _t in ref.OUTPUTS[section]}
    assert set(paths) <= inventory, set(paths) - inventory  # the inventory's notation
    assert ni.inventory_diff(SECTION_KEY[section], paths)["new"] == []
    # the output's only texts are paths and type words, and no answer value long enough to mean anything is one
    texts = {x["path"] for x in out["paths"]} | {x["type"] for x in out["paths"]}
    values: set[str] = set()
    _values(data, values)
    keys: set[str] = set()
    _keys(data, keys)
    meaningful = {v for v in values if len(v) >= 3 and not v.isdigit() and v not in keys}
    assert not texts & meaningful


def test_structure_counts_rows():
    data = json.loads((SAMPLES / "act_master_2026-09-03.json").read_text(encoding="utf-8"))
    rows = {p["path"]: p for p in ni.structure(data)["paths"]}
    assert rows["[].actname"]["count"] == 4677 and rows["[].actname"]["type"] == "str"
    search = json.loads((SAMPLES / "party_name_2026-09-03.json").read_text(encoding="utf-8"))
    rows = {p["path"]: p for p in ni.structure(search)["paths"]}
    assert rows["casenos[].cino"]["count"] == 3 and rows["casenos[].uniform_code"]["type"] == "null"
    assert rows["establishment_name"]["count"] == 1


def test_structure_never_holds_a_value():
    data = {"case1": {"pet_name": "SECRET PARTY NAME", "n": 3}, "case2": {"pet_name": "OTHER NAME", "n": 4.5}}
    out = ni.structure(data)
    assert "SECRET" not in json.dumps(out) and "OTHER" not in json.dumps(out)
    assert {p["path"]: p["type"] for p in out["paths"]} == {"[].n": "float, int", "[].pet_name": "str"}


def test_structure_limits_paths_and_depth():
    wide = {f"k{i:03d}x": i for i in range(250)}
    out = ni.structure(wide)
    assert len(out["paths"]) == 200 and out["total"] == 250 and out["more"] == 50
    deep: dict = {"v": 1}
    for i in range(10):
        deep = {f"level{i}x": deep}
    out = ni.structure(deep)
    assert out["depth_limited"] is True and out["paths"][0]["type"] == "dict"
    assert out["paths"][0]["path"].count(".") == 5
    long_key = {"x" * 300: 1}
    assert len(ni.structure(long_key)["paths"][0]["path"]) == 120
    assert ni.structure([])["paths"] == [{"path": "(root)", "type": "list", "count": 1}]


def test_inventory_diff_flags_a_new_path():
    data = json.loads((SAMPLES / "case_search_2026-09-03.json").read_text(encoding="utf-8"))
    data["casenos"]["case1"]["brand_new_field"] = "x"
    diff = ni.inventory_diff("case_search", ni.structure_paths(data))
    assert diff == {"checked": True, "new": ["casenos[].brand_new_field"], "absent": []}
    few = ni.inventory_diff("case_search", ["establishment_name"])
    assert "casenos[].cino" in few["absent"] and few["new"] == []
    empty_block = ni.inventory_diff("cnr", ["acts"])  # an empty block above known fields is not new
    assert empty_block["new"] == []
    assert ni.inventory_diff("order", ["anything"]) == {"checked": False, "new": [], "absent": []}


# ------------------------------------------------------------------------------------------------ reference


@pytest.mark.parametrize("key", list(VALUES))
def test_reference_inputs_match_the_captured_params(key):
    p = preview(settings(), key, BY_KEY[key].invoke, VALUES[key])
    assert [k for k, _v in p.params] == [i.name for i in ref.INPUTS[key]]
    body = ref.reference(key)
    assert body["doc"]["page"] == ref.DOC_PAGES[key][0]
    assert [s["code"] for s in body["statuses"] if s["listed"]] == [str(c) for c in ref.SPEC_CODES[key]]


def test_reference_outputs_match_the_field_inventory():
    parsed: dict[str, list[tuple[str, str]]] = {}
    current = None
    for line in INVENTORY.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^## (\w+)$", line)
        if m:
            current = m.group(1)
            parsed[current] = []
            continue
        m = re.match(r"^\| `([^`]*)` \| ([^|]*) \|", line)
        if m and current:
            parsed[current].append((m.group(1), m.group(2).strip()))
    assert {k: list(v) for k, v in ref.OUTPUTS.items()} == parsed
    assert set(ref.INVENTORY_SECTION.values()) <= set(parsed)
    assert ref.outputs("order")["kind"] == "pdf" and ref.outputs("show_causelist")["paths"] == []


def test_napix_status_names_cover_the_reference_table():
    assert set(NAPIX_STATUS) == set(ref.NAPIX_MEANINGS)
    for code, (name, _meaning) in ref.NAPIX_MEANINGS.items():
        assert NAPIX_STATUS[code] == name
    for key, codes in ref.SPEC_CODES.items():
        assert set(codes) <= set(ref.NAPIX_MEANINGS), key
    assert ref.http_meaning(200, "NapixEmptyResponse").startswith("The gateway's known intermittent fault")
    assert ref.napix_meaning(628).startswith("RECORD_NOT_FOUND")


def _pdf_text(doc: str, page: int) -> str:
    pymupdf = pytest.importorskip("pymupdf")
    with pymupdf.open(PDFS / ref.DOCS[doc]["file"]) as pdf:
        return " ".join(pdf[page - 1].get_text().split()).lower()


def test_doc_files_match_their_pins():
    pymupdf = pytest.importorskip("pymupdf")
    for doc, meta in ref.DOCS.items():
        raw = (PDFS / meta["file"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == meta["sha256"], doc
        with pymupdf.open(stream=raw, filetype="pdf") as pdf:
            assert pdf.page_count == meta["pages"], doc


def test_doc_pages_hold_their_headings():
    for key, (page, section) in ref.DOC_PAGES.items():
        assert " ".join(section.split()).lower() in _pdf_text("hc_spec", page), (key, page, section)
    for doc, page, _label, heading in ref.GENERAL_LINKS + ref.TOKEN_LINKS:
        assert heading.lower() in _pdf_text(doc, page), (doc, page, heading)


# ------------------------------------------------------------------------------------------------ templates


def test_postman_scripts_equal_the_repository_collection():
    coll = json.loads(POSTMAN.read_text(encoding="utf-8"))
    assert ni.POSTMAN_SCRIPTS == coll["event"]
    token = next(i for i in coll["item"] if i["name"] == "00 Access Token")
    assert ni.TOKEN_TEST_EXEC == next(e for e in token["event"] if e["listen"] == "test")["script"]["exec"]


SECRETS = ("key-test", "secret-test", "dept-test-123", "auth-key-16bytes")


def _secret_settings() -> Settings:
    return settings(
        napix_client_id=SECRETS[0],
        napix_client_secret=SECRETS[1],
        napix_dept_id=SECRETS[2],
        napix_auth_key=SECRETS[3],
    )


def test_postman_export_has_placeholders_only():
    s = _secret_settings()
    p = preview(s, "cnr", BY_KEY["cnr"].invoke, VALUES["cnr"])
    coll = ni.postman_collection(s, p, "Case details by CNR")
    text = json.dumps(coll)
    assert not [x for x in SECRETS if x in text]
    assert NapixCrypto(SECRETS[3]).encrypt(p.plain) not in text
    variables = {v["key"]: v["value"] for v in coll["variable"]}
    assert variables == {
        "client_key": "",
        "client_secret": "",
        "dept_id": "",
        "auth_key": "",
        "access_token": "",
        "hash_key": "15081947",
        "version": "v1.0",
    }
    api = coll["item"][1]["request"]
    assert api["method"] == "GET" and {"key": "input", "value": p.plain} in api["url"]["query"]
    assert {"key": "request_str", "value": "{{request_str}}"} in api["url"]["query"]
    assert api["header"][0]["value"] == "Bearer {{access_token}}"
    assert (
        coll["item"][0]["request"]["url"]["raw"] == "https://delhigw.napix.gov.in/nic/ecourts//oauth2/token"
    )
    assert coll["info"]["schema"].endswith("v2.1.0/collection.json")


def test_curl_template_has_placeholders_only():
    s = _secret_settings()
    p = preview(s, "current_status", BY_KEY["current_status"].invoke, VALUES["current_status"])
    curl = ni.curl_template(p, True, s.napix_version)
    assert curl.splitlines()[0] == f"# plain string: {p.plain}"
    assert (
        "curl -G -X POST 'https://delhigw.napix.gov.in/nic/ecourts/hc-current-status-api/currentStatus'"
        in curl
    )
    assert "<ACCESS_TOKEN>" in curl and "<DEPT_ID>" in curl and "<REQUEST_STR" in curl
    assert f"request_token={p.request_token}" in curl and "version=v1.0" in curl
    assert not [x for x in SECRETS if x in curl]
    assert "<REQUEST_TOKEN" in ni.curl_template(p, False)
    token = ni.curl_token(s)
    assert "<CLIENT_KEY>:<CLIENT_SECRET>" in token and "//oauth2/token" in token
    assert not [x for x in SECRETS if x in token]
    env = {e["name"]: e for e in ni.envelope(s, p)}
    assert env["dept_id"]["shown"] == "de…" and env["request_str"]["shown"].startswith(
        "encrypted, 44 characters"
    )
    assert env["request_token"]["shown"] == p.request_token and env["version"]["shown"] == "v1.0"


def test_mask_dept_id():
    assert ni.mask_dept_id("ASLMS12345") == "AS…"
    assert ni.mask_dept_id("abcdef") == "ab…"
    assert ni.mask_dept_id("abcde") == "••••••"
    assert ni.mask_dept_id(None) == "not set" and ni.mask_dept_id("") == "not set"


# ------------------------------------------------------------------------------------------------ validation


class Masters(ni.HeldMasters):
    def __init__(self) -> None:
        pass

    def est_codes(self) -> list[str]:
        return ["GAHC01", "GAHC02", "GAHC03", "GAHC04"]

    def state_codes(self) -> set[int]:
        return {18, 6}

    def case_type_held(self, est_code: str, code: int) -> bool:
        return (est_code, code) == ("GAHC01", 111)


TODAY = date(2026, 10, 22)
CNR = "GAHC010277142024"


def check(key: str, values: dict) -> dict | dict[str, str]:
    try:
        return ni.check_values(None, settings(), key, values, Masters(), TODAY)  # type: ignore[arg-type]
    except ni.InvalidInput as exc:
        return {"errors": exc.errors}


@pytest.mark.parametrize(
    ("key", "good", "bad", "field"),
    [
        ("case_type", {"est_code": "gahc02"}, {"est_code": "GAHC09"}, "est_code"),
        ("district", {"state_code": "18"}, {"state_code": "27"}, "state_code"),
        ("cnr", {"cino": CNR.lower()}, {"cino": f"{CNR},{CNR}"}, "cino"),
        ("causelist_bench", {"est_code": "GAHC01", "causelist_date": "2026-12-21"},
         {"est_code": "GAHC01", "causelist_date": "2026-12-22"}, "causelist_date"),
        ("show_business", {"cino": CNR, "business_date": "1950-01-01"},
         {"cino": CNR, "business_date": "2026-02-30"}, "business_date"),
        ("causelist_details", {"est_code": "GAHC01", "causelist_date": "2025-01-06", "bench_id": "204812"},
         {"est_code": "GAHC01", "causelist_date": "2025-01-06", "bench_id": "2048123"}, "bench_id"),
        ("show_causelist", {"est_code": "GAHC01", "bench_id": "1", "causelist_id": "1007",
                            "causelist_date": "2025-01-06"},
         {"est_code": "GAHC01", "bench_id": "1", "causelist_id": "10a", "causelist_date": "2025-01-06"},
         "causelist_id"),
        ("order", {"cino": CNR, "order_no": "12345", "order_date": "2026-07-13"},
         {"cino": CNR, "order_no": "123456", "order_date": "2026-07-13"}, "order_no"),
        ("case_search", {"est_code": "GAHC01", "case_type": "111", "reg_no": "7714", "reg_year": "2024"},
         {"est_code": "GAHC01", "case_type": "112", "reg_no": "7714", "reg_year": "2024"}, "case_type"),
        ("case_search", {"est_code": "GAHC01", "case_type": "111", "reg_no": "1234567", "reg_year": "2024"},
         {"est_code": "GAHC01", "case_type": "111", "reg_no": "", "reg_year": "2024"}, "reg_no"),
        ("filing", {"est_code": "GAHC01", "case_type": "111", "fil_no": "11883", "fil_year": "2026"},
         {"est_code": "GAHC01", "case_type": "111", "fil_no": "11883", "fil_year": "2027"}, "fil_year"),
        ("filing", {"est_code": "GAHC01", "case_type": "111", "fil_no": "11883", "fil_year": "1950"},
         {"est_code": "GAHC01", "case_type": "111", "fil_no": "12345678", "fil_year": "2025"}, "fil_no"),
        ("party_name", {"est_code": "GAHC01", "pend_disp": "d", "litigant_name": "ANIL BORA", "reg_year": "2024"},
         {"est_code": "GAHC01", "pend_disp": "X", "litigant_name": "ANIL BORA", "reg_year": "2024"},
         "pend_disp"),
        ("party_name", {"est_code": "GAHC01", "pend_disp": "P", "litigant_name": "O'BRIEN & SONS",
                        "reg_year": "2024"},
         {"est_code": "GAHC01", "pend_disp": "P", "litigant_name": "XXXXXXX", "reg_year": "2024"},
         "litigant_name"),
        ("advocate_name", {"est_code": "GAHC01", "pend_disp": "P", "advocate_name": "SAIKIA", "reg_year": "2024"},
         {"est_code": "GAHC01", "pend_disp": "P", "advocate_name": "A|B=C", "reg_year": "2024"}, "advocate_name"),
        ("advocate_name", {"est_code": "GAHC01", "pend_disp": "P", "advocate_name": "SAIKIA", "reg_year": "2024"},
         {"est_code": "GAHC01", "pend_disp": "P", "advocate_name": "SAIKIA", "reg_year": ""}, "reg_year"),
    ],
)  # fmt: skip
def test_validation_rules(key, good, bad, field):
    ok = check(key, good)
    assert "errors" not in ok, ok
    refused = check(key, bad)
    assert field in refused["errors"], refused


def test_validation_types_and_names():
    typed = check(
        "case_search", {"est_code": "gahc01", "case_type": "111", "reg_no": "7714", "reg_year": "2024"}
    )
    assert typed == {"est_code": "GAHC01", "case_type": 111, "reg_no": 7714, "reg_year": 2024}
    typed = check("cnr", {"cino": CNR.lower()})
    assert typed == {"cnr": CNR}
    typed = check("causelist_bench", {"est_code": "GAHC01", "causelist_date": "2025-01-06"})
    assert typed == {"est_code": "GAHC01", "list_date": date(2025, 1, 6)}
    refused = check("cnr", {"cino": CNR, "extra": "1"})
    assert refused["errors"] == {"extra": "This API does not take this parameter"}
    assert check("overview", {}) == {}
    assert (
        check("case_search", {"est_code": "GAHC09", "case_type": "111", "reg_no": "1", "reg_year": "2024"})[
            "errors"
        ]["case_type"]
        == "Choose a court code ASLMS holds first"
    )
