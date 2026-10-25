"""Design `court-data-freshness`, "Tests / Unit": the IST clock and the ban on `date.today(`, the disposed-refresh cap,
the entries fingerprint, the new settings' ranges, the current-version source scan and the logging probe. No database,
no live call."""

from __future__ import annotations

import ast
import re
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from aslms.cli import napix_probe
from aslms.core.clock import ist_midnight, today_ist
from aslms.core.config import Settings
from aslms.integration.napix.client import NapixClient
from aslms.integration.napix.crypto import NapixCrypto
from aslms.parsing.causelist_pdf import Entry
from aslms.services.causelists import entries_fingerprint, entry_values, parsed_fingerprint
from aslms.services.napix_store import CallLogUnavailable, NapixRecorder
from aslms.services.tracking import disposed_refresh_cap
from tests.unit.conftest import KEY, Gateway

BACKEND = Path(__file__).resolve().parents[2]
SERVICES = BACKEND / "aslms" / "services"


# ------------------------------------------------------------------------------------------------ clock


def test_today_ist_gives_the_ist_date():
    assert today_ist(datetime(2026, 10, 22, 23, 0, tzinfo=UTC)) == date(2026, 10, 23)  # 04:30 IST next day
    assert today_ist(datetime(2026, 10, 22, 18, 0, tzinfo=UTC)) == date(2026, 10, 22)  # 23:30 IST
    assert today_ist(datetime(2026, 10, 22, 18, 30, tzinfo=UTC)) == date(2026, 10, 23)  # midnight IST
    assert today_ist(datetime(2026, 10, 22, 23, 0)) == date(2026, 10, 23)  # naive = UTC


def test_ist_midnight_is_1830_utc_the_day_before():
    m = ist_midnight(date(2026, 10, 23))
    assert m == datetime(2026, 10, 22, 18, 30, tzinfo=UTC) and m.utcoffset().total_seconds() == 0


def test_no_naive_today_in_the_application():
    offenders = [
        f"{p.relative_to(BACKEND)}:{i}"
        for p in (BACKEND / "aslms").rglob("*.py")
        for i, line in enumerate(p.read_text("utf-8").splitlines(), start=1)
        if "date.today(" in line and not line.lstrip().startswith("#") and p.name != "clock.py"
    ]
    assert offenders == [], f"use aslms.core.clock.today_ist(), not date.today(): {offenders}"


# the date of a UTC instant (`datetime.now(UTC).date()`, `datetime.utcnow().date()`, `_now().date()`): the UTC calendar
# date, a day behind IST between 00:00 and 05:30 IST. A line that really means the UTC date says so with `# utc-date`.
UTC_DATE = re.compile(r"\w*now\w*\([^()]*\)\.date\(\)")


def test_no_utc_date_for_today_in_the_application():
    assert UTC_DATE.search("datetime.now(UTC).date()") and UTC_DATE.search("datetime.utcnow().date()")
    assert UTC_DATE.search("_now().date()") and not UTC_DATE.search("today_ist(_now())")
    offenders = [
        f"{p.relative_to(BACKEND)}:{i}"
        for p in (BACKEND / "aslms").rglob("*.py")
        for i, line in enumerate(p.read_text("utf-8").splitlines(), start=1)
        if UTC_DATE.search(line.split("#", 1)[0]) and "# utc-date" not in line and p.name != "clock.py"
    ]
    assert offenders == [], f"use aslms.core.clock.today_ist() for the IST date: {offenders}"


def test_a_document_dated_today_is_accepted_just_after_ist_midnight(monkeypatch):
    from aslms.core import clock
    from aslms.services import documents

    monkeypatch.setattr(
        clock, "now_utc", lambda: datetime(2026, 10, 23, 19, 0, tzinfo=UTC)
    )  # 00:30 IST, 24 Oct
    assert documents._doc_date(date(2026, 10, 24)) == date(2026, 10, 24)
    with pytest.raises(documents.UploadRefused):
        documents._doc_date(date(2026, 10, 25))


# ------------------------------------------------------------------------------------------------ disposed refresh


def test_disposed_refresh_cap():
    assert disposed_refresh_cap(0, 1000) == 0
    assert disposed_refresh_cap(1, 1000) == 1
    assert disposed_refresh_cap(28, 1000) == 1
    assert disposed_refresh_cap(29, 1000) == 2
    assert disposed_refresh_cap(56_000, 1000) == 1000  # min(max, ceil(eligible / 28))
    assert disposed_refresh_cap(56_000, 0) == 0  # 0 switches the job off


# ------------------------------------------------------------------------------------------------ fingerprint


def _entry(**kw) -> Entry:
    base = dict(
        seq=1,
        printed_sr_no="1",
        case_no_text="WP(C)/100/2025",
        cnr=None,
        page=1,
        court_no="10",
        bench_text="HON'BLE MR. JUSTICE A",
        section="ORDERS",
        is_connected=False,
        parent_case_no=None,
        is_filing_number=False,
        remarks=None,
        petitioner_text="RAM",
        respondent_text="THE STATE OF ASSAM",
        pet_advocate_text="MR. X",
        res_advocate_text="SC, EDU",
        pet_advocates=["MR. X"],
        res_advocates=["SC, EDU"],
        pet_counsel_codes=[],
        res_counsel_codes=["SC, EDU"],
        raw_lines=["1 WP(C)/100/2025 RAM"],
    )
    base.update(kw)
    return Entry(**base)


class _Parsed:
    def __init__(self, entries):
        self.entries = entries


def test_entries_fingerprint_ignores_key_order_and_raw_lines():
    a = entry_values(_entry())
    b = dict(reversed(list(a.items())))
    assert entries_fingerprint([a]) == entries_fingerprint([b])
    assert parsed_fingerprint(_Parsed([_entry()])) == parsed_fingerprint(
        _Parsed([_entry(raw_lines=["1   WP(C)/100/2025    RAM  "])])
    )


@pytest.mark.parametrize(
    "change",
    [
        {"printed_sr_no": "2"},
        {"res_counsel_codes": ["SC, HEALTH"]},
        {"petitioner_text": "SHYAM"},
        {"court_no": "11"},
    ],
)
def test_entries_fingerprint_sees_a_changed_row(change):
    assert parsed_fingerprint(_Parsed([_entry()])) != parsed_fingerprint(_Parsed([_entry(**change)]))


def test_entries_fingerprint_matches_the_stored_truncation():
    long_court = "C" * 40
    stored = {**entry_values(_entry()), "court_no": long_court[:20]}
    assert parsed_fingerprint(_Parsed([_entry(court_no=long_court)])) == entries_fingerprint([stored])


# ------------------------------------------------------------------------------------------------ settings


@pytest.mark.parametrize(
    ("name", "bad"),
    [
        ("disposed_refresh_days", 89),
        ("disposed_refresh_days", 731),
        ("disposed_refresh_every_days", 6),
        ("disposed_refresh_every_days", 61),
        ("disposed_refresh_daily_max", -1),
        ("disposed_refresh_daily_max", 5001),
        ("causelist_recheck_fresh_minutes", 29),
        ("napix_call_log_keep_days", 364),
        ("napix_call_log_keep_days", 3651),
        ("napix_call_log_purge_batch", 499),
        ("napix_call_log_purge_max_seconds", 59),
    ],
)
def test_settings_ranges(name, bad):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{name: bad})


def test_settings_defaults():
    s = Settings(_env_file=None)
    assert (s.disposed_refresh_days, s.disposed_refresh_every_days, s.disposed_refresh_daily_max) == (
        365,
        28,
        1000,
    )
    assert (
        s.causelist_recheck_fresh_minutes == 180 and s.causelist_recheck_morning is True
    )  # owner's answer (a)
    assert (s.napix_call_log_keep_days, s.napix_call_log_purge_batch, s.napix_call_log_purge_max_seconds) == (
        730,
        5000,
        600,
    )


# ------------------------------------------------------------------------------------------------ current versions

JOIN = re.compile(
    r"Causelist\.id\s*==\s*CauselistEntry\.causelist_id|JOIN\s+causelists|e\.causelist_id\s*=\s*cl\.id"
    r"|cl\.id\s*=\s*e\.causelist_id|stored\.c\.causelist_id\s*==\s*Causelist\.id"
)
LIST_READ = re.compile(r"Causelist\.list_date|FROM causelists")
CURRENT = re.compile(r"CURRENT_LIST|superseded_at IS NULL|superseded_at\.is_\(None\)")
# decision 12's deliberate exceptions: an earlier version opened by its id, the case's listings (flagged), load counts
EXCEPTIONS = {
    ("case_detail", "listings"),
    ("causelist_view", "entries"),  # its place (`_place`) adds the rule unless a list is named
    ("causelist_view", "base"),
    ("causelist_view", "_validate"),
    ("load_report", "report"),
}


def _functions(path: Path):
    src = path.read_text("utf-8")
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            yield node.name, ast.get_source_segment(src, node) or ""


def test_every_cause_list_reader_takes_the_current_version():
    missing = [
        f"{p.stem}.{name}"
        for p in sorted(SERVICES.glob("*.py"))
        for name, seg in _functions(p)
        if (JOIN.search(seg) or LIST_READ.search(seg))
        and not CURRENT.search(seg)
        and (p.stem, name) not in EXCEPTIONS
    ]
    assert missing == [], (
        f"add CURRENT_LIST / `cl.superseded_at IS NULL` (design court-data-freshness): {missing}"
    )


def test_the_place_of_the_entries_adds_the_rule_without_a_list():
    seg = dict(_functions(SERVICES / "causelist_view.py"))["_place"]
    assert "CURRENT_LIST" in seg


# ------------------------------------------------------------------------------------------------ the probe


class FakeRecorder(NapixRecorder):
    """Commits nothing: counts the attempts it would write and the calls made when each flush happened."""

    def __init__(self, gateway: Gateway, fail_at: int | None = None):
        super().__init__(session_factory=object())  # any factory: flush_apart is replaced
        self.gateway = gateway
        self.fail_at = fail_at
        self.flushes: list[tuple[int, int]] = []  # (attempts written, calls seen by the gateway)

    def flush_apart(self, session_factory) -> int:
        if self.fail_at is not None and len(self.flushes) + 1 == self.fail_at:
            raise OSError("database gone")
        n = len(self.pending)
        self.flushes.append((n, len(self.gateway.seen)))
        self._clear()
        return n


def _factory(gateway: Gateway):
    def make(hook) -> NapixClient:
        return NapixClient(
            base_url="https://gw.test/nic/ecourts",
            client_id="key-test",
            client_secret="secret-test",
            dept_id="dept-test",
            crypto=NapixCrypto(KEY),
            transport=httpx.MockTransport(gateway.handle),
            on_call=hook,
            backoff_base=0.0,
        )

    return make


async def _no_sleep(_s: float) -> None:
    return None


async def test_napix_probe_flushes_every_attempt_after_its_call(gateway: Gateway):
    rec = FakeRecorder(gateway)
    n = await napix_probe.run(
        3, 0, client_factory=_factory(gateway), recorder=rec, check_db=lambda c: None, sleep=_no_sleep
    )
    assert n == 3 and rec.flushes == [(1, 1), (1, 2), (1, 3)]
    assert [s["path"] for s in gateway.seen] == ["overview/overview"] * 3


async def test_napix_probe_stops_on_a_failed_write(gateway: Gateway):
    rec = FakeRecorder(gateway, fail_at=2)
    with pytest.raises(napix_probe.RecordFailed):
        await napix_probe.run(
            5, 0, client_factory=_factory(gateway), recorder=rec, check_db=lambda c: None, sleep=_no_sleep
        )
    assert len(gateway.seen) == 2 and rec.flushes == [(1, 1)]  # no third call


async def test_napix_probe_refuses_to_start_without_the_call_log(gateway: Gateway):
    def unreachable(command: str) -> None:
        raise CallLogUnavailable(f"cannot reach the database; {command} logs every call in napix_call_log")

    made: list = []

    def factory(hook):
        made.append(hook)
        return _factory(gateway)(hook)

    with pytest.raises(CallLogUnavailable) as e:
        await napix_probe.run(
            3, 0, client_factory=factory, recorder=FakeRecorder(gateway), check_db=unreachable
        )
    assert "napix-probe-rate" in str(e.value) and made == [] and gateway.seen == []


def test_no_naive_today_in_the_tests():
    """Tests compare with dates the application takes in IST; `date.today()` is the container's UTC date, a day behind
    between 00:00 and 05:30 IST, which turned CI red on 25 Oct 2026."""
    tests = BACKEND / "tests"
    offenders = [
        f"{p.relative_to(BACKEND)}:{i}"
        for p in tests.rglob("*.py")
        for i, line in enumerate(p.read_text("utf-8").splitlines(), start=1)
        if "date.today(" in line
        and not line.lstrip().startswith("#")
        and p.name != "test_court_data_freshness_unit.py"
    ]
    assert offenders == [], f"use aslms.core.clock.today_ist(), not date.today(): {offenders}"
