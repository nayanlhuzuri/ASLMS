"""The alert rules without a database (design alerts-notifications, "Tests", unit): hearing severity around
48 hours, request and compliance severity, the recency window, the e-mail preference rules and their
defaults, dedupe keys, and the rendering rules (titles ≤ 300 characters, no document description)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

from aslms.domain.alerts import Severity
from aslms.domain.org import Channel, DigestMode, UserNotificationPreference
from aslms.domain.reference import AlertKind
from aslms.services import alert_rules as r

NOW = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)  # 14:30 IST


def test_hearing_due_at_is_ten_thirty_ist():
    due = r.hearing_due_at(date(2026, 10, 8))
    assert due.hour == 10 and due.minute == 30 and due.tzinfo is r.IST
    assert due.astimezone(UTC).hour == 5  # 10:30 IST = 05:00 UTC
    assert r.hearing_due_at(date(2026, 10, 8), "11:00").hour == 11


def test_hearing_severity_around_48_hours():
    assert r.severity_for_hearing(NOW + timedelta(hours=47), NOW) == Severity.CRITICAL
    assert r.severity_for_hearing(NOW + timedelta(hours=49), NOW) == Severity.HIGH
    assert r.severity_for_hearing(NOW + timedelta(hours=48), NOW) == Severity.CRITICAL
    assert r.severity_for_hearing(NOW - timedelta(minutes=1), NOW) is None
    assert r.hearing_expired(NOW - timedelta(hours=13), NOW)
    assert not r.hearing_expired(NOW - timedelta(hours=11), NOW)


def test_request_severity():
    today = date(2026, 10, 6)
    assert r.severity_for_due(today + timedelta(days=3), today) is None
    assert r.severity_for_due(today + timedelta(days=2), today) == Severity.HIGH
    assert r.severity_for_due(today + timedelta(days=1), today) == Severity.HIGH
    assert r.severity_for_due(today, today) == Severity.CRITICAL
    assert r.severity_for_due(today - timedelta(days=5), today) == Severity.CRITICAL


def test_compliance_severity():
    today = date(2026, 10, 6)
    assert r.severity_for_compliance(today + timedelta(days=8), today) is None
    assert r.severity_for_compliance(today + timedelta(days=7), today) == Severity.HIGH
    assert r.severity_for_compliance(today + timedelta(days=3), today) == Severity.HIGH
    assert r.severity_for_compliance(today + timedelta(days=2), today) == Severity.CRITICAL
    assert r.severity_for_compliance(today, today) == Severity.CRITICAL
    assert r.severity_for_compliance(today - timedelta(days=10), today) == Severity.CRITICAL


def test_is_recent_window():
    today = date(2026, 10, 6)
    assert r.is_recent(today - timedelta(days=14), today)
    assert not r.is_recent(today - timedelta(days=15), today)
    assert r.is_recent(today + timedelta(days=30), today)
    assert not r.is_recent(None, today)
    assert not r.is_recent(date(2025, 1, 10), today)


def _pref(enabled=True, digest=DigestMode.DAILY, critical_only=False, channel=Channel.EMAIL):
    return UserNotificationPreference(
        channel=channel, enabled=enabled, digest=digest, critical_only=critical_only
    )


def test_preference_defaults_and_email_rules():
    assert r.effective_preferences([]) == r.Prefs(True, DigestMode.DAILY, False)
    assert r.effective_preferences(None) == r.Prefs()
    # an in_app row alone does not change the e-mail defaults
    assert r.effective_preferences([_pref(channel=Channel.IN_APP)]) == r.Prefs()
    default = r.Prefs()
    assert r.immediate_email(default, Severity.CRITICAL)
    assert not r.immediate_email(default, Severity.HIGH)
    assert r.wants_digest(default)
    none = r.effective_preferences([_pref(digest=DigestMode.NONE)])
    assert r.immediate_email(none, Severity.NORMAL) and r.immediate_email(none, Severity.CRITICAL)
    assert not r.wants_digest(none)
    crit_none = r.effective_preferences([_pref(digest=DigestMode.NONE, critical_only=True)])
    assert r.immediate_email(crit_none, Severity.CRITICAL) and not r.immediate_email(crit_none, Severity.HIGH)
    crit_daily = r.effective_preferences([_pref(critical_only=True)])
    assert r.immediate_email(crit_daily, Severity.CRITICAL) and not r.immediate_email(
        crit_daily, Severity.HIGH
    )
    assert r.wants_digest(crit_daily)
    off = r.effective_preferences([_pref(enabled=False, digest=DigestMode.NONE)])
    assert not r.immediate_email(off, Severity.CRITICAL) and not r.wants_digest(off)


def test_dedupe_keys():
    assert r.dedupe_key(AlertKind.HEARING_DUE, "c1", date(2026, 10, 8)) == "hearing_due:c1:2026-10-08"
    assert r.notification_key("a", "u", Channel.EMAIL, Severity.HIGH) == "n:a:u:email:high"
    assert len(r.dedupe_key(AlertKind.NEW_ORDER, "x" * 400)) == 300
    assert r.higher(Severity.CRITICAL, Severity.HIGH) and not r.higher(Severity.HIGH, Severity.HIGH)


CASE = SimpleNamespace(
    case_no_text="WP(C)/123/2025", cnr="GAHC010000012025", ref_no="ASLMS/GHC/CASE/2026/000001"
)


def test_render_alert_titles():
    title, body = r.render_alert(
        AlertKind.HEARING_DUE,
        CASE,
        {"hearing_date": "2026-10-08", "source": "causelist", "item_no": 12, "court_no": "3"},
    )
    assert title == "Hearing on 08 Oct 2026: WP(C)/123/2025"
    assert "cause list of 08 Oct 2026, item 12, court 3" in body
    _, body = r.render_alert(
        AlertKind.HEARING_DUE, CASE, {"hearing_date": "2026-10-08", "source": "current_status"}
    )
    assert body == "Next date per court records."
    title, _ = r.render_alert(AlertKind.NEW_ORDER, CASE, {"order_no": "2", "order_date": "2026-10-01"})
    assert title.startswith("New order of 01 Oct 2026")
    title, _ = r.render_alert(
        AlertKind.STATUS_CHANGED, CASE, {"status": "disposed", "disposal_date": "2026-10-01"}
    )
    assert title.startswith("Case disposed on 01 Oct 2026")
    long_case = SimpleNamespace(case_no_text="X" * 500, cnr=None, ref_no="R")
    for kind in AlertKind:
        title, _ = r.render_alert(kind, long_case, {})
        assert len(title) <= 300, kind


def test_new_document_alert_names_only_the_type():
    title, body = r.render_alert(
        AlertKind.NEW_DOCUMENT,
        CASE,
        {
            "doc_type": "legal_opinion",
            "doc_type_label": "Legal opinion",
            "office_code": "EDU",
            "description": "SECRET memo",
        },
    )
    assert "SECRET" not in title and "SECRET" not in body
    assert title == "New Legal opinion uploaded: WP(C)/123/2025"


def test_render_mail_and_digest_carry_link_not_text():
    alert = SimpleNamespace(
        title="Hearing on 08 Oct 2026: WP(C)/123/2025",
        body="Next date per court records.",
        severity=Severity.CRITICAL,
        due_at=datetime(2026, 10, 8, 5, 0, tzinfo=UTC),
    )
    subject, text = r.render_mail(
        alert, CASE, "Gauhati High Court", "http://portal/", "ASLMS-GHC-CASE-2026-000001"
    )
    assert subject.startswith("[ASLMS CRITICAL]")
    assert "GAHC010000012025" in text and "http://portal/cases/ASLMS-GHC-CASE-2026-000001" in text
    assert "08 Oct 2026 10:30 IST" in text
    subject, text = r.render_digest(
        date(2026, 10, 6),
        [
            (
                "New order",
                [
                    {
                        "title": "New order of 01 Oct 2026: WP(C)/1/2025",
                        "case_ref": "ASLMS-GHC-CASE-2026-000001",
                    }
                ],
            )
        ],
        [{"date": date(2026, 10, 8), "case_label": "WP(C)/1/2025", "source": "causelist", "case_ref": "X"}],
        3,
        4,
        "http://portal",
    )
    assert "digest - 06 Oct 2026" in subject
    assert "New order (1)" in text and "and 2 more" in text and "Possible matches" in text and ": 4" in text


# ------------------------------------------------------------------ design alerts-visibility-roles, decisions 5, 7, 9


LISTED_CASE = SimpleNamespace(case_no_text="WP(C)/123/2026", cnr=None, ref_no="ASLMS/GHC/CASE/2026/000001")


def test_new_note_text_names_kind_ref_and_author_only():
    data = {
        "note_id": "0199",
        "ref_no": "ASLMS/EDU/NOTE/2026/000042",
        "seq_no": 4,
        "kind": "hearing",
        "kind_label": "Hearing note",
        "visibility": "case_scope",
        "office_code": "EDU",
        "author_name": "Edu Off1",
        "author_designation": "Under Secretary",
        "supersedes_ref_no": None,
        "finalised": False,
    }
    title, body = r.render_alert(AlertKind.NEW_NOTE, LISTED_CASE, data)
    assert title == "New hearing note: WP(C)/123/2026"
    assert (
        body
        == "Note ASLMS/EDU/NOTE/2026/000042 (Hearing note) by Under Secretary, EDU. Open the case to read it."
    )
    title, body = r.render_alert(
        AlertKind.NEW_NOTE, LISTED_CASE, {**data, "supersedes_ref_no": "ASLMS/EDU/NOTE/2026/000040"}
    )
    assert title == "Note corrected: WP(C)/123/2026"
    assert "ASLMS/EDU/NOTE/2026/000040" in body and "Open the case to read it." in body
    title, _ = r.render_alert(AlertKind.NEW_NOTE, LISTED_CASE, {**data, "kind_label": "General"})
    assert title == "New general note: WP(C)/123/2026"
    # the rendering reads only the listed keys: a body planted in data never appears
    title, body = r.render_alert(AlertKind.NEW_NOTE, LISTED_CASE, {**data, "body": "SECRET-MARKER"})
    assert "SECRET-MARKER" not in title + body


def test_listed_tomorrow_text_lists_court_and_printed_item():
    one = {
        "hearing_date": "2026-10-22",
        "entries": [{"list_type": "daily", "court_no": "3", "item_no": "14", "bench_text": "X"}],
        "entries_total": 1,
    }
    title, body = r.render_alert(AlertKind.LISTED_TOMORROW, LISTED_CASE, one)
    assert title == "Listed tomorrow, 22 Oct 2026, court 3 item 14: WP(C)/123/2026"
    assert body == "Listed in the daily cause list of 22 Oct 2026: court 3, item 14."
    two = {
        **one,
        "entries": one["entries"]
        + [{"list_type": "supplementary", "court_no": "5", "item_no": "2", "bench_text": None}],
        "entries_total": 2,
    }
    title, body = r.render_alert(AlertKind.LISTED_TOMORROW, LISTED_CASE, two)
    assert title == "Listed tomorrow, 22 Oct 2026, court 3 item 14 +1 more: WP(C)/123/2026"
    assert body == (
        "Listed in the daily cause list of 22 Oct 2026: court 3, item 14; supplementary list: court 5, item 2."
    )
    many = {**one, "entries": one["entries"] * 5, "entries_total": 7}
    _, body = r.render_alert(AlertKind.LISTED_TOMORROW, LISTED_CASE, many)
    assert body.endswith("; and 2 more.")
    assert r.listing_text([{"court_no": None, "item_no": "9"}]) == ["item 9"]
    assert r.listing_text([{"court_no": "3", "item_no": "14"}], sep=" ") == ["court 3 item 14"]


def test_new_note_is_informational_and_listed_is_not():
    assert AlertKind.NEW_NOTE in r.INFO_KINDS and AlertKind.NEW_NOTE in r.CASE_KINDS
    assert AlertKind.LISTED_TOMORROW not in r.INFO_KINDS and AlertKind.LISTED_TOMORROW in r.CASE_KINDS


def test_hearing_due_from_the_one_next_hearing():
    """Design next-date-direct, decision 10: around, an exact order date, a confirmed and a manual date; court and
    cause-list texts unchanged."""
    base = {"hearing_date": "2026-03-11", "source": "next_date", "order_date": "2026-02-18"}
    title, body = r.render_alert(
        AlertKind.HEARING_DUE, CASE, {**base, "basis": "around", "basis_words": "after 3 weeks"}
    )
    assert title == "Hearing around 11 Mar 2026: WP(C)/123/2025"
    assert body == (
        "Counted from the order of 18 Feb 2026 (after 3 weeks). The court's own date will replace it when it is known."
    )
    title, body = r.render_alert(AlertKind.HEARING_DUE, CASE, {**base, "basis": "order"})
    assert (
        title == "Hearing on 11 Mar 2026: WP(C)/123/2025"
        and body == "Date given in the order of 18 Feb 2026."
    )
    _, body = r.render_alert(AlertKind.HEARING_DUE, CASE, {**base, "basis": "confirmed"})
    assert body == "Date from the order of 18 Feb 2026."
    _, body = r.render_alert(AlertKind.HEARING_DUE, CASE, {**base, "basis": "manual", "order_date": None})
    assert body == "Date entered by hand; the court has given no date."
    # an old alert without a basis keeps its text
    _, body = r.render_alert(
        AlertKind.HEARING_DUE, CASE, {"hearing_date": "2026-03-11", "source": "next_date"}
    )
    assert body == "Next date entered or read from an order."
    _, body = r.render_alert(
        AlertKind.HEARING_DUE, CASE, {"hearing_date": "2026-03-11", "source": "current_status"}
    )
    assert body == "Next date per court records."


def test_next_date_review_and_reported_texts():
    title, body = r.render_alert(AlertKind.NEXT_DATE_REVIEW, CASE, {"order_date": "2026-10-12"})
    assert title == "Enter the next date: WP(C)/123/2025"
    assert body == "Enter the next date: the order of 12 Oct 2026 gives no next date."
    title, body = r.render_alert(
        AlertKind.NEXT_DATE_REPORTED,
        CASE,
        {
            "hearing_date": "2026-11-20",
            "order_date": "2026-10-12",
            "reporter_name": "Off One",
            "reporter_office_code": "EDU",
            "reason": "the order says four weeks",
        },
    )
    assert (
        title == "Next date reported as wrong: 20 Nov 2026 read from the order of 12 Oct 2026: WP(C)/123/2025"
    )
    assert body == "Reported by Off One, EDU: the order says four weeks"
