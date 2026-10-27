"""`aslms data-load status` (design data-collection-redesign, Services round 1): the Overview's headline and the two
estimate lines, in words, with no JSON."""

from datetime import datetime, timedelta, timezone

from aslms.cli.data_load import status_lines

IST = timezone(timedelta(hours=5, minutes=30))


def _overview(**over):
    ov = {
        "collection": "running",
        "napix_enabled": True,
        "position": {"working_on_month": "2026-01"},
        "days": {"collected": 306, "calendar": 664, "failed": 2},
        "cases": {"found": 59033, "with_details": 58924, "without_details": 109},
        "orders": {
            "stored": 137932,
            "referenced": 320869,
            "waiting": 182929,
            "not_available": 8,
            "failed": 0,
        },
        "left": {"total": 183229, "causelist_days": 267, "case_details": 33, "order_pdfs": 182929},
        "estimate": {
            "details": {
                "finish_at": datetime(2026, 10, 28, 14, 0, tzinfo=IST),
                "hours": 36.0,
                "calls_needed": 29520.0,
                "reason": None,
            },
            "all": {"finish_at": None, "hours": None, "calls_needed": None, "reason": "no_recent_calls"},
            "basis": {"calls_per_hour": 820.0, "hourly_limit": 1000},
        },
    }
    ov.update(over)
    return ov


def test_status_lines_headline_figures_and_two_estimate_lines():
    lines = status_lines(_overview())
    assert lines[0] == "Automatic collection: running, working on 2026-01; court connection on"
    assert "Cause lists: 306 of 664 days (2 failed)" in lines
    assert "Cases: 59,033 found, 58,924 with details, 109 without" in lines
    assert any(line.startswith("Order PDFs: 137,932 of 320,869 stored, 182,929 waiting") for line in lines)
    assert "Still to fetch: 183,229 (267 cause-list days, 33 case details, 182,929 order PDFs)" in lines
    assert "Cause lists and case details: about Wed 28 Oct 2026 14:00 IST (29,520 calls)" in lines
    assert "Every order PDF as well: no date: no court call in the last hour" in lines
    assert lines[-1] == "Pace: about 820 court calls an hour of the 1,000 the court allows"
    assert not any("{" in line for line in lines)


def test_status_lines_not_started_with_connection_off_and_nothing_left():
    est = {
        "details": {"finish_at": None, "hours": 0.0, "calls_needed": 0.0, "reason": None},
        "all": {"finish_at": None, "hours": None, "calls_needed": None, "reason": "connection_off"},
        "basis": {"calls_per_hour": 0.0, "hourly_limit": None},
    }
    lines = status_lines(
        _overview(
            collection="not_started",
            napix_enabled=False,
            position={"working_on_month": None},
            days=None,
            estimate=est,
        )
    )
    assert lines[0] == "Automatic collection: not started; court connection off"
    assert not any(line.startswith("Cause lists:") for line in lines)
    assert "Cause lists and case details: done" in lines
    assert "Every order PDF as well: no date: the court connection is off" in lines
    assert lines[-1] == "Pace: about 0 court calls an hour"
