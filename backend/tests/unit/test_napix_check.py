"""`aslms napix-check` as the probe tool (design `search-court-advocate-filing`, decision 2): the advocate and
filing steps run only with their inputs, `--max-calls` starts no new step, every attempt reaches the recorder,
and nothing is called without a reachable database. The unit gateway answers; no live call is made."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import httpx
import pytest
import typer

from aslms.cli import napix_check
from aslms.cli.napix_check import CallLogUnavailable, Probe, probe_from_options, run
from aslms.integration.napix.client import CallHook, NapixClient, NapixResult
from aslms.integration.napix.crypto import NapixCrypto
from aslms.services.napix_store import NapixRecorder
from tests.unit.conftest import KEY, Gateway

ADVOCATE = "hc-advocate-name-api/advocatename"
FILING = "hc-filing-api/Filing"
SEARCH_STEPS = {"advocate_name", "filing"}


def factory(gateway: Gateway, made: list[NapixClient] | None = None):
    def make(hook: CallHook) -> NapixClient:
        c = NapixClient(
            base_url="https://gw.test/nic/ecourts",
            client_id="key-test",
            client_secret="secret-test",
            dept_id="dept-test",
            crypto=NapixCrypto(KEY),
            transport=httpx.MockTransport(gateway.handle),
            on_call=hook,
            backoff_base=0.0,
        )
        if made is not None:
            made.append(c)
        return c

    return make


class Recorded:
    """Stands in for the database flush: keeps what the recorder collected."""

    def __init__(self) -> None:
        self.results: list[NapixResult] = []
        self.recorders: list[NapixRecorder] = []

    def __call__(self, recorder: NapixRecorder) -> int:
        self.recorders.append(recorder)
        self.results.extend(recorder.pending)
        n = len(recorder.pending)
        recorder.pending.clear()
        return n


async def _run(gateway: Gateway, tmp_path: Path, rec: Recorded, **kw) -> int:
    only = kw.pop("only", SEARCH_STEPS)
    return await run(
        date(2026, 10, 17),
        None,
        tmp_path,
        only,
        1,
        "t",
        client_factory=factory(gateway),
        check_db=lambda: None,
        record=rec,
        **kw,
    )


async def test_search_steps_run_only_with_their_inputs(gateway: Gateway, tmp_path: Path) -> None:
    rec = Recorded()
    failures = await _run(gateway, tmp_path, rec, probe=Probe())
    assert failures == 0 and gateway.seen == [] and rec.results == []

    await _run(gateway, tmp_path, rec, probe=Probe(advocate="A I KATHAR", reg_year=2025))
    assert [s["path"] for s in gateway.seen] == [ADVOCATE]
    assert gateway.seen[0]["plain"].endswith("|pend_disp=P|advocate_name=A I KATHAR|reg_year=2025")

    gateway.seen.clear()
    await _run(gateway, tmp_path, rec, probe=Probe(filing_type=111, fil_no=7451, fil_year=2026))
    assert [s["path"] for s in gateway.seen] == [FILING]
    assert gateway.seen[0]["plain"].endswith("|case_type=111|fil_no=7451|fil_year=2026")
    assert (tmp_path / "advocate_name_t.json").exists() and (tmp_path / "filing_t.json").exists()


async def test_blank_year_is_sent_empty(gateway: Gateway, tmp_path: Path) -> None:
    await _run(gateway, tmp_path, Recorded(), probe=Probe(advocate="A I KATHAR", reg_year=None, pend="D"))
    assert gateway.seen[0]["plain"].endswith("|pend_disp=D|advocate_name=A I KATHAR|reg_year=")


async def test_max_calls_starts_no_further_step(gateway: Gateway, tmp_path: Path) -> None:
    rec = Recorded()
    probe = Probe(advocate="A I KATHAR", reg_year=2025, filing_type=111, fil_no=7451, fil_year=2026)
    await _run(gateway, tmp_path, rec, probe=probe, max_calls=1)
    assert [s["path"] for s in gateway.seen] == [ADVOCATE]
    assert len(rec.results) == 1


async def test_every_attempt_retries_included_reaches_the_recorder(gateway: Gateway, tmp_path: Path) -> None:
    gateway.responses += [lambda p, q, r: httpx.Response(503)] * 2
    rec = Recorded()
    probe = Probe(advocate="A I KATHAR", reg_year=2025, filing_type=111, fil_no=7451, fil_year=2026)
    # the retries of the first step count: 3 attempts reach the limit, so the filing step does not start
    failures = await _run(gateway, tmp_path, rec, probe=probe, max_calls=3)
    assert failures == 0
    assert [r.api for r in rec.results] == [ADVOCATE] * 3
    assert [r.ok for r in rec.results] == [False, False, True]
    assert [r.http_status for r in rec.results] == [503, 503, 200]
    assert len(rec.recorders) == 1 and rec.recorders[0].user_id is None and rec.recorders[0].lane is None


async def test_failed_calls_are_recorded_and_counted(gateway: Gateway, tmp_path: Path) -> None:
    gateway.responses.append(lambda p, q, r: gateway.encrypted_status(628))
    rec = Recorded()
    failures = await _run(gateway, tmp_path, rec, probe=Probe(advocate="KATHAR", reg_year=2025))
    assert failures == 1
    assert len(rec.results) == 1 and rec.results[0].napix_status == 628 and not rec.results[0].ok


async def test_calls_are_recorded_when_the_run_breaks(gateway: Gateway, tmp_path: Path) -> None:
    def boom(p, q, r):
        raise RuntimeError("transport broke")

    gateway.responses.append(boom)
    rec = Recorded()
    with pytest.raises(RuntimeError):
        await _run(gateway, tmp_path, rec, probe=Probe(advocate="A I KATHAR", reg_year=2025))
    assert len(rec.recorders) == 1 and len(rec.results) == 1
    assert rec.results[0].error_family == "RuntimeError"


async def test_no_database_no_call(gateway: Gateway, tmp_path: Path, monkeypatch) -> None:
    from contextlib import contextmanager

    import aslms.db.session as db_session

    @contextmanager
    def unreachable(url=None):
        raise OSError("connection refused")
        yield  # pragma: no cover

    monkeypatch.setattr(db_session, "session_scope", unreachable)
    made: list[NapixClient] = []
    rec = Recorded()
    with pytest.raises(CallLogUnavailable) as e:
        await run(
            date(2026, 10, 17),
            None,
            tmp_path,
            SEARCH_STEPS,
            1,
            "t",
            probe=Probe(advocate="A I KATHAR", reg_year=2025),
            client_factory=factory(gateway, made),
            record=rec,
        )
    assert "napix_call_log" in str(e.value) and "connection refused" not in str(e.value)
    assert made == [] and gateway.seen == [] and rec.recorders == []


def test_database_ready_passes_when_the_call_log_answers(monkeypatch) -> None:
    from contextlib import contextmanager

    import aslms.db.session as db_session

    seen: list[str] = []

    class S:
        def execute(self, stmt):
            seen.append(str(stmt))

    @contextmanager
    def fine(url=None):
        yield S()

    monkeypatch.setattr(db_session, "session_scope", fine)
    napix_check.database_ready()
    assert seen == ["SELECT 1 FROM napix_call_log LIMIT 0"]


def test_probe_options() -> None:
    assert probe_from_options(None, None, "P", None, None, None) == Probe()
    assert probe_from_options(" A I KATHAR ", "2025", "p", None, None, None) == Probe("A I KATHAR", 2025, "P")
    assert probe_from_options("A I KATHAR", "blank", "D", None, None, None) == Probe("A I KATHAR", None, "D")
    assert probe_from_options(None, None, "P", 111, 7451, 2026) == Probe(None, None, "P", 111, 7451, 2026)
    for bad in (
        ("A I KATHAR", None, "P", None, None, None),  # the year must be given, or 'blank'
        ("AB", "2025", "P", None, None, None),
        ("X" * 100, "2025", "P", None, None, None),
        ("A I KATHAR", "25", "P", None, None, None),
        (None, "2025", "P", None, None, None),
        ("A I KATHAR", "2025", "B", None, None, None),
        (None, None, "P", 111, None, 2026),
        (None, None, "P", 111, 0, 2026),
        (None, None, "P", 111, 10_000_000, 2026),
        (None, None, "P", 0, 7451, 2026),
    ):
        with pytest.raises(typer.BadParameter):
            probe_from_options(*bad)
