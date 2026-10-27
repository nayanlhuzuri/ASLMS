"""The plain schedule of the Automatic Collection tab is tied to the Celery beat schedule (design
`data-collection-redesign`, decision 40): every data-collection beat entry is described once, at the time it runs, and
every other beat entry is named as not data collection."""

from __future__ import annotations

import re

from aslms.services import schedules

DAYS = {"Sundays": 0, "Saturdays": 6}


def test_plain_schedule_matches_celery_beat_schedule():
    from aslms.jobs.celery_app import app

    beat = app.conf.beat_schedule
    described = {p["beat"] for p in schedules.PLAIN_SCHEDULE if p["beat"]}
    assert described | schedules.NOT_DATA_COLLECTION == set(beat)
    assert not described & schedules.NOT_DATA_COLLECTION
    for p in schedules.PLAIN_SCHEDULE:
        if p["beat"] is None:
            assert p["when"] == "Always"
            continue
        m = re.fullmatch(r"(?:(Sundays|Saturdays) )?(\d\d):(\d\d)", p["when"])
        assert m, p["when"]
        cron = beat[p["beat"]]["schedule"]
        assert cron.hour == {int(m.group(2))} and cron.minute == {int(m.group(3))}, p["key"]
        if m.group(1):
            assert cron.day_of_week == {DAYS[m.group(1)]}, p["key"]
        else:
            assert len(cron.day_of_week) == 7, p["key"]
    keys = [p["key"] for p in schedules.PLAIN_SCHEDULE]
    assert len(keys) == len(set(keys))
