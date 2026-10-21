"""The pure parts of the System health screen (design `api-health-checker`): the catalogue against the integration
layer, the status rules, the overall line, the plain reasons and the summaries of every JSON sample and both PDFs."""

from __future__ import annotations

import hashlib
import inspect
import json
from datetime import date

import pytest

from aslms.integration.napix.hc import API, NapixHighCourt
from aslms.services import napix_api_check as check
from aslms.services import napix_samples, system_health
from aslms.services.system_health import CATALOGUE, card_status, overall, plain_reason
from tests.db.conftest import SAMPLES

NAME_FIELDS = ("pet_name", "res_name", "pet_adv", "res_adv", "judge_name", "bench", "coram", "name")


def test_catalogue_matches_hc_methods():
    keys = [e.key for e in CATALOGUE]
    assert len(keys) == 17 and len(set(keys)) == 17
    assert set(keys) <= set(API)
    assert not {"advocate_bar_reg", "act_details", "neutral_citation", "cnr_alt"} & set(keys)
    assert set(API) - set(keys) == {"advocate_bar_reg", "act_details", "neutral_citation", "cnr_alt"}
    assert [g for g, _ in system_health.GROUPS] == ["masters", "causelists", "cases", "searches"]
    assert {e.group for e in CATALOGUE} == {"masters", "causelists", "cases", "searches"}
    assert [e.key for e in CATALOGUE if e.method == "POST"] == ["current_status"]
    assert set(napix_samples.CHOOSERS) == set(keys)
    # case_by_cnr gained `fallback` (default True keeps every other caller's behaviour)
    assert inspect.signature(NapixHighCourt.case_by_cnr).parameters["fallback"].default is True


@pytest.mark.parametrize(
    ("last", "h24", "expected"),
    [
        (None, {"calls": 0, "answered": 0}, "unknown"),
        ({"answered": True}, {"calls": 10, "answered": 10, "p95_ms": 800}, "ok"),
        ({"answered": False}, {"calls": 10, "answered": 9}, "warn"),
        ({"answered": False, "last3_all_failed": True}, {"calls": 10, "answered": 7}, "down"),
        ({"answered": False}, {"calls": 4, "answered": 1}, "down"),
        (
            {"answered": False},
            {"calls": 2, "answered": 0},
            "warn",
        ),  # fewer than 3 calls, not 3 failed in a row
        ({"answered": True}, {"calls": 5, "answered": 4}, "warn"),
        ({"answered": True}, {"calls": 4, "answered": 3}, "ok"),  # fewer than 5 calls
        ({"answered": True}, {"calls": 2, "answered": 2, "p95_ms": 20_001}, "warn"),
        ({"answered": True}, {"calls": 2, "answered": 2, "p95_ms": 20_000}, "ok"),
    ],
)
def test_card_status_rules(last, h24, expected):
    assert card_status(last, h24) == expected


def test_overall_counts_court_cards_at_most_as_warn():
    line = overall(["down"] * 3 + ["ok"] * 14, ["ok"] * 10)
    assert line["status"] == "warn" and line["sentence_key"] == "need_attention"
    assert line["counts"] == {
        "court_working": 14,
        "court_total": 17,
        "services_working": 10,
        "services_total": 10,
        "attention": 3,
        "not_working": 0,
    }
    assert overall(["ok"] * 17, ["ok"] * 9 + ["down"])["sentence_key"] == "not_working"
    assert overall(["unknown"] * 17, ["ok"] * 9 + ["unknown"])["status"] == "ok"
    assert overall(["unknown"] * 17, ["ok"] * 10)["sentence_key"] == "everything_working"
    assert overall(["unknown"], ["unknown"])["sentence_key"] == "not_known"


def test_plain_reason_covers_every_error_family():
    families = [
        "NapixNotFound",
        "NapixInputError",
        "NapixUnavailable",
        "NapixEmptyResponse",
        "NapixGatewayError",
        "NapixAuthError",
        "NapixProtocolError",
        "ConnectError",
        None,
    ]
    reasons = [plain_reason(f, 628 if f == "NapixNotFound" else None) for f in families]
    assert len(set(reasons)) == len(reasons)
    assert all(r and "Napix" not in r for r in reasons)
    assert plain_reason(None) == "The court answered"
    assert plain_reason("NapixUnavailable", 629).endswith("(court status 629)")
    assert "HTTP 503" in plain_reason("NapixUnavailable", None, 503)
    assert "renewed" in plain_reason(None, None, 401)


SAMPLE_KEYS = {
    "act_master_2026-09-03.json": "act",
    "advocate_name_2026-10-18-p1.json": "advocate_name",
    "bench_master_2026-09-03.json": "bench_master",
    "case_search_2026-09-03.json": "case_search",
    "case_type_master_2026-09-03.json": "case_type",
    "causelist_bench_2026-09-03.json": "causelist_bench",
    "causelist_details_bench2048_2026-09-03.json": "causelist_details",
    "cnr_pending.json": "cnr",
    "cnr_2026-09-03.json": "cnr",
    "current_status_pending.json": "current_status",
    "district_master_2026-09-03.json": "district",
    "filing_2026-10-18-p5.json": "filing",
    "overview_2026-09-03.json": "overview",
    "party_name_2026-09-03.json": "party_name",
    "show_business_pending.json": "show_business",
    "state_master_2026-09-03.json": "state",
}


def _names(data) -> set[str]:
    out: set[str] = set()
    if isinstance(data, dict):
        for k, v in data.items():
            if k in NAME_FIELDS and isinstance(v, str) and len(v.strip()) > 3:
                out.add(v.strip())
            out |= _names(v)
    elif isinstance(data, list):
        for v in data:
            out |= _names(v)
    return out


def test_every_sample_file_has_a_card():
    files = {p.name for p in SAMPLES.glob("*.json")} - {"overview_response.json"}  # the encrypted envelope
    prefixes = {name.removesuffix(".json").rsplit("_2026", 1)[0].removesuffix("_pending") for name in files}
    keys = {
        "act_master": "act",
        "advocate_name": "advocate_name",
        "bench_master": "bench_master",
        "case_search": "case_search",
        "case_type_master": "case_type",
        "causelist_bench": "causelist_bench",
        "causelist_details_bench2048": "causelist_details",
        "causelist_details_bench2109": "causelist_details",
        "causelist_details_bench2178": "causelist_details",
        "cnr": "cnr",
        "current_status": "current_status",
        "district_master": "district",
        "filing": "filing",
        "overview": "overview",
        "party_name": "party_name",
        "show_business": "show_business",
        "state_master": "state",
    }
    assert prefixes <= set(keys)


@pytest.mark.parametrize(("name", "key"), sorted(SAMPLE_KEYS.items()))
def test_summarisers_on_samples(name, key):
    data = json.loads((SAMPLES / name).read_text(encoding="utf-8"))
    values = (
        {"cnr": data.get("cino", ""), "business_date": date(2026, 7, 13)} if isinstance(data, dict) else {}
    )
    if key == "current_status":
        values = {"cnr": data["cases1"]["cino"]}
    summary = check.summarise_payload(key, data, values, source_cnr="GAHC010277142024")
    entry = system_health.BY_KEY[key]
    assert summary["kind"] == entry.kind
    rows = check.payload_rows(key, data)
    if entry.kind == "rows":
        assert summary["row_count"] == len(rows) > 0
        assert summary["field_names"] == sorted({k for r in rows for k in r})[: check.MAX_FIELDS]
    else:
        record = data["cases1"] if key == "current_status" else data
        assert summary["row_count"] == len(record)
        assert summary["field_names"] == sorted(record)[: check.MAX_FIELDS]
    dumped = json.dumps(summary)
    assert not [n for n in _names(data) if n in dumped], key
    assert all(set(f) == {"label", "value"} for f in summary["facts"])


def test_record_facts_on_samples():
    cnr = json.loads((SAMPLES / "cnr_pending.json").read_text(encoding="utf-8"))
    facts = {
        f["label"]: f["value"] for f in check.summarise_payload("cnr", cnr, {"cnr": cnr["cino"]})["facts"]
    }
    assert facts["The CNR in the answer is the one asked"] == "yes" and facts["Case status"] == "pending"
    assert facts["Hearings in the answer"] == "3" and facts["Orders in the answer"] == "3"
    other = check.summarise_payload("cnr", cnr, {"cnr": "GAHC019999992099"})["facts"]
    assert {"label": "The CNR in the answer is the one asked", "value": "no"} in other
    overview = json.loads((SAMPLES / "overview_2026-09-03.json").read_text(encoding="utf-8"))
    assert check.summarise_payload("overview", overview, {})["facts"] == [
        {"label": "Version", "value": "v1.0"}
    ]
    search = json.loads((SAMPLES / "case_search_2026-09-03.json").read_text(encoding="utf-8"))
    facts = check.summarise_payload("case_search", search, {}, source_cnr="GAHC019999992099")["facts"]
    assert {"label": "The source case is among the rows", "value": "no"} in facts


@pytest.mark.parametrize("name", ["order_2026-09-03.pdf", "show_causelist_bench2048_2026-09-03.pdf"])
def test_pdf_summaries(name):
    pdf = (SAMPLES / name).read_bytes()
    same = check.summarise_pdf(pdf, hashlib.sha256(pdf).hexdigest())
    facts = {f["label"]: f["value"] for f in same["facts"]}
    assert same["kind"] == "pdf" and same["row_count"] is None and same["field_names"] == []
    assert (
        facts["Same as the stored copy"] == "yes"
        and int(facts["Pages"]) >= 1
        and facts["Size"].endswith("KB")
    )
    other = {f["label"]: f["value"] for f in check.summarise_pdf(pdf, "0" * 64)["facts"]}
    assert other["Same as the stored copy"] == "no"
    broken = check.summarise_pdf(b"%PDF-1.4 broken", None)
    assert [f["label"] for f in broken["facts"]] == ["Size"]  # no page count, no stored copy to compare


def test_public_values_hide_names_and_case_numbers():
    s = napix_samples.Sample(
        {
            "name": "A PERSON",
            "reg_year": 2024,
            "pend_disp": "P",
            "cnr": "GAHC010277142024",
            "d": date(2025, 1, 6),
        },
        "label",
        case_visible=True,
    )
    assert s.public_values() == {
        "reg_year": 2024,
        "pend_disp": "P",
        "cnr": "GAHC010277142024",
        "d": "2025-01-06",
    }
    assert s.public_values(case_visible=False) == {"reg_year": 2024, "pend_disp": "P", "d": "2025-01-06"}


def test_name_rules():
    assert napix_samples.name_passes("THE STATE OF ASSAM", 200)
    assert not napix_samples.name_passes("XXXXXXX", 200)
    assert not napix_samples.name_passes("AB", 200)
    assert not napix_samples.name_passes("A" * 100, 99)
    assert not napix_samples.name_passes("RAM@HOME", 200)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("5000-01-01", "no"),
        ("1900-01-01", "no"),
        ("0000-00-00", "no"),
        ("", "no"),
        (None, "no"),
        ("Next Date Not Given", "no"),
        ("2026-11-03", "yes"),
    ],
)
def test_next_date_sentinels_read_absent(value, expected):
    """Design api-health-checker-followups, decision 8: the court's sentinels read as no date."""
    cnr = json.loads((SAMPLES / "cnr_pending.json").read_text(encoding="utf-8"))
    cnr["date_next_list"] = value
    facts = {
        f["label"]: f["value"] for f in check.summarise_payload("cnr", cnr, {"cnr": cnr["cino"]})["facts"]
    }
    assert facts["A next hearing date is present"] == expected


def test_business_text_presence_is_a_text_check():
    asked = {"business_date": "2026-07-13"}
    for business, expected in (
        ("Heard. List after two weeks.", "yes"),
        ("  ", "no"),
        (None, "no"),
        ("0", "yes"),
    ):
        record = {"business_date": "2026-07-13", "business": business}
        facts = {
            f["label"]: f["value"] for f in check.summarise_payload("show_business", record, asked)["facts"]
        }
        assert facts["Business text is present"] == expected, business
    assert not hasattr(check, "final_attempt") and not hasattr(check, "_present")
