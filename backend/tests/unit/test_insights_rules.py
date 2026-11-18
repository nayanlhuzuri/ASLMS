"""The readings of State Insights by rule (design `state-insights`, "Tests", unit): the State tests, the department
phrases, the name cores, the posts, the original writ, the court's category, the outcomes, the hearing bands and the
age bands. Pure functions: no database, no network, no model."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from aslms.services import insights_rules as R
from aslms.services.reporting_common import AGE_BANDS, AGE_KEYS, AGE_UNKNOWN, age_band

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "insights" / "hearing_bands.json"


def test_state_party_pattern_forms():
    for text in (
        "THE STATE OF ASSAM AND 3 ORS",
        "GOVT. OF ASSAM",
        "GOVERNMENT OF ASSAM",
        "the state of assam",
    ):
        assert R.names_state(text), text
    for text in ("ASSAMESE", "STATE BANK OF INDIA", "STATE OF ASSAMESE TEA", "GOVERNMENT OF MEGHALAYA"):
        assert not R.names_state(text), text


def test_service_tag_whole_word():
    assert R.has_service_tag("SRI A. B. SARMA, IAS")
    assert R.has_service_tag("ACS")
    assert R.has_service_tag("SHRI X, ACS (RETD)")
    assert R.has_service_tag("THE DIRECTOR, IPS")
    for text in ("BASIS OF CLAIM", "IASI ROAD", "PLACES", "M/S ACSE LTD"):
        assert not R.has_service_tag(text), text


def test_government_code_forms():
    mapped = frozenset({"SC, EDU"})
    generic = frozenset({"SC, GOA"})
    assert R.is_government_code("GA, ASSAM", frozenset(), frozenset())
    assert R.is_government_code("PP, ASSAM", frozenset(), frozenset())
    assert R.is_government_code("SR. GA ADV.", frozenset(), frozenset())
    assert R.is_government_code("ga,assam", frozenset(), frozenset())
    assert R.is_government_code("SC, EDU", mapped, generic)
    assert not R.is_government_code("SC, EDU", frozenset(), frozenset())
    assert R.is_government_code("SC, GOA", frozenset(), generic)
    assert not R.is_government_code("GA, NAGALAND", frozenset(), frozenset())
    assert not R.is_government_code("SC, GAUHATI UNIVERSITY", frozenset(), frozenset())
    assert not R.is_government_code("", frozenset(), frozenset())


# fifteen respondent texts as printed in the dev data (14 Nov 2026) and the phrases read from them
REAL_TITLES = [
    ("THE COMMISSIONER AND SECRETARY TO THE GOVT. OF ASSAM, FINANCE DEPARTMENT", ["FINANCE"]),
    ("THE CHIEF ENGINEER, IRRIGATION DEPARTMENT", ["IRRIGATION"]),
    ("THE SECRETARY, PERSONNEL (B) DEPARTMENT, KARBI ANGLONG AUTONOMOUS COUNCIL", ["PERSONNEL"]),
    ("THE SECRETARY TO THE GOVERNMENT OF ASSAM, FINANCE DEPARTMENT, DISPUR", ["FINANCE"]),
    (
        "THE SECRETARY, DEPTT OF REVENUE AND DISASTER MANAGEMENT, GOVT. OF ASSAM",
        ["REVENUE AND DISASTER MANAGEMENT"],
    ),
    ("THE PRINCIPAL SECRETARY, DEPARTMENT OF SECONDARY EDUCATION, DISPUR", ["SECONDARY EDUCATION"]),
    ("THE COMMISSIONER & SECRETARY, HOME & POLITICAL DEPARTMENT", ["HOME AND POLITICAL"]),
    ("THE STATE OF ASSAM, REP. BY THE SECRETARY, P.W.D. (ROADS) DEPTT.", ["P.W.D. (ROADS)"]),
    ("THE DIRECTOR OF ELEMENTARY EDUCATION, ASSAM", []),
    (
        "THE SECRETARY TO THE GOVT OF ASSAM, HEALTH AND FAMILY WELFARE DEPTT., DISPUR",
        ["HEALTH AND FAMILY WELFARE"],
    ),
    ("THE DEPUTY COMMISSIONER, KAMRUP (M)", []),
    ("THE ADDL. CHIEF SECRETARY, DEPARTMENT OF FOREST AND ENVIRONMENT", ["FOREST AND ENVIRONMENT"]),
    (
        "THE COMMISSIONER, DEPARTMENT OF PANCHAYAT AND RURAL DEVELOPMENT AND ANR",
        ["PANCHAYAT AND RURAL DEVELOPMENT"],
    ),
    ("2: THE SECRETARY, EDUCATION DEPARTMENT 3: THE SAID DEPARTMENT", ["EDUCATION"]),
    ("THE STATE OF ASSAM AND 4 ORS", []),
]


@pytest.mark.parametrize(("text", "expected"), REAL_TITLES)
def test_department_phrases_real_titles(text, expected):
    assert R.department_phrases(text) == expected


def test_respondent_side_after_versus():
    title = "RAM KUMAR S/O LATE X VERSUS THE STATE OF ASSAM AND 2 ORS Page No.# 2/5 FINANCE DEPARTMENT"
    side = R.respondent_side(title)
    assert side.startswith("THE STATE OF ASSAM") and "PAGE NO" not in side and "RAM KUMAR" not in side
    assert R.respondent_side("NO SEPARATOR HERE") == ""


def test_office_name_core():
    assert R.office_name_core("Finance Department") == "FINANCE"
    assert (
        R.office_name_core("Department of Revenue and Disaster Management")
        == "REVENUE AND DISASTER MANAGEMENT"
    )
    assert R.office_name_core("Home & Political Department") == "HOME AND POLITICAL"
    assert R.office_name_core("The Health and Family Welfare Deptt.") == "HEALTH AND FAMILY WELFARE"
    assert R.office_name_core("FINANCE") == "FINANCE"


def test_normalise_phrase_and_validity():
    assert R.normalise_phrase(" the  personnel (b) ") == "PERSONNEL"
    assert R.normalise_phrase("Home & Political") == "HOME AND POLITICAL"
    assert R.valid_phrase("PWD (ROADS)")
    assert not R.valid_phrase("AB")
    assert not R.valid_phrase("FINANCE; DROP")


def test_posts_each_and_exclusions():
    assert R.posts("THE DIRECTOR GENERAL OF POLICE, ASSAM") == ["dgp"]
    assert R.posts("THE MANAGING DIRECTOR, ASSAM STATE TRANSPORT CORPORATION") == ["chief_executive"]
    assert R.posts("THE DIRECTOR OF SECONDARY EDUCATION") == ["director"]
    assert R.posts("THE COMMISSIONER AND SECRETARY, FINANCE") == ["commissioner_secretary"]
    assert R.posts("THE COMMISSIONER & SECRETARY, FINANCE") == ["commissioner_secretary"]
    assert R.posts("THE PRINCIPAL SECRETARY, HOME") == ["principal_secretary"]
    assert R.posts("THE ADDITIONAL CHIEF SECRETARY, HOME") == ["addl_chief_secretary"]
    assert R.posts("THE SECRETARY, EDUCATION AND THE PRINCIPAL SECRETARY, HOME") == [
        "principal_secretary",
        "secretary",
    ]
    assert R.posts("THE SUPERINTENDENT OF POLICE, KAMRUP; THE SP KAMRUP") == ["superintendent_police"]
    assert R.posts("THE DISTRICT ELEMENTARY EDUCATION OFFICER, NAGAON") == ["deeo"]
    assert R.posts("THE DEEO, NAGAON") == ["deeo"]
    assert R.posts("THE INSPECTOR OF SCHOOLS, CIRCLE OFFICER AND EXECUTIVE ENGINEER") == [
        "executive_engineer",
        "inspector_schools",
        "circle_officer",
    ]
    assert R.posts("THE CHIEF ENGINEER AND THE DEPUTY COMMISSIONER") == [
        "deputy_commissioner",
        "chief_engineer",
    ]
    assert set(R.POST_CODES) == set(R.POST_LABELS)


def test_writ_reference_forms():
    today = date(2026, 11, 14)
    assert R.writ_reference("in W.P.(C) No. 4326 of 2025 the court", today=today) == "WP(C) 4326/2025"
    assert R.writ_reference("WP(C) 123/2020", today=today) == "WP(C) 123/2020"
    assert R.writ_reference("WP(C)/4189/2016", today=today) == "WP(C) 4189/2016"
    assert R.writ_reference("WA 45/2019", today=today) == "WA 45/2019"
    assert R.writ_reference("W.P.(Crl.) 7/2021", today=today) == "WP(Crl) 7/2021"
    assert R.writ_reference("CRP 10/2020", today=today) is None
    assert R.writ_reference("WP(C) 12/2027", today=today) is None
    assert R.writ_reference("WP(C) 12/1949", today=today) is None
    assert R.writ_reference("WAS 2 OF 2020", today=today) is None
    assert R.writ_parts("WP(C) 4326/2025") == ("WP(C)", 4326, 2025)
    assert R.writ_parts("WP(Crl) 7/2021") == ("WP(CRL)", 7, 2021)
    assert R.writ_parts("nothing") is None


def test_parse_category():
    assert R.parse_category("10245 - Some label ( 12 )") == (10245, "Some label")
    assert R.parse_category("10301 - Interlocutory Application (Civil) ( 382 )") == (
        10301,
        "Interlocutory Application (Civil)",
    )
    assert R.parse_category("( 20240 )") is None
    assert R.parse_category(None) is None
    assert R.parse_category("") is None


# the 14 disposal_type values of the dev data (14 Nov 2026) and their buckets
DEV_DISPOSALS = [
    ("Disposed Of", "disposed_of"),
    ("Dismissed", "dismissed"),
    ("Allowed", "allowed"),
    ("Closed", "closed"),
    ("Dismissed On withdrawal no order for such liberty", "withdrawn"),
    ("Dismissed on withdrawal with liberty to approach again", "withdrawn"),
    ("Dismissed As infractuous", "infructuous"),
    ("Rejected", "rejected"),
    ("Dismissed For Non-prosecution", "dismissed_default"),
    ("", "other"),
    ("Dismissed For default", "dismissed_default"),
    ("Disposed On Motion date after hearing the both sides", "disposed_of"),
    ("Disposed On Motion date after hearing the Petitioner", "disposed_of"),
    ("Closed For Judgment - CAV", "closed"),
]


@pytest.mark.parametrize(("value", "key"), DEV_DISPOSALS)
def test_outcome_buckets_every_dev_value(value, key):
    assert R.outcome_key(value) == key
    assert key in R.OUTCOME_KEYS


def test_outcome_sql_names_every_rule():
    sql = R.outcome_case_sql("cases.disposal_type")
    for key, _ in R.OUTCOME_RULES:
        assert f"'{key}'" in sql
    assert sql.endswith("ELSE 'other' END)")


def test_hearing_band_twin_matches_portal_fixture():
    """The shared fixture (also for the portal's `hearingDate` test, round 2): days from today, status, the Insights
    band and the portal band it falls in."""
    rows = json.loads(FIXTURE.read_text("utf-8"))
    today = date(2026, 11, 14)
    assert len(rows) >= 10
    for row in rows:
        on = today + timedelta(days=row["days"]) if row["days"] is not None else None
        assert R.hearing_band(on, row["status"], today) == row["band"], row
        assert row["band"] in R.HEARING_BAND_KEYS


def test_age_keys_reuse_njdg():
    today = date(2026, 11, 14)
    assert R.age_key(None, today) == AGE_UNKNOWN[0]
    assert R.age_key(today - timedelta(days=30), today) == "age_lt_1"
    assert R.age_key(date(2020, 1, 1), today) == "age_5_10"
    assert R.age_key(date(2021, 11, 14), today) == age_band(date(2021, 11, 14), today)
    assert set(R.AGE_LABELS) == set(AGE_KEYS)
    assert [b[0] for b in AGE_BANDS][0] == "age_lt_1"


def test_clean_reads_ampersand_and_page_marks():
    assert R.clean("Home & Political  Page No.# 3/9 Department") == "HOME AND POLITICAL DEPARTMENT"
