"""The `party_search` handler through the queue runner against the scripted gateway (design `department-discovery`,
decisions 6-9 and 11): the sample's three rows are stored as discovery cases with their `ref_no` on the term's
department (on `GOA` when two departments share the term), recorded as hits (a second run only bumps
`last_found_at`), their dossiers queued in the discovery lane at 41; the call is logged in the discovery lane with no
person and the response kept; no audit row; a 628 is a done row with no rows; a term without an active rule ends
`skipped` with no call; a malformed `cino` is counted, never stored; after the dossier the engine recommends with
origin `discovery`; the share stops discovery claims while daily work still runs."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import sqlalchemy as sa

from aslms.core.config import Settings
from aslms.domain.cases import Case, FirstSeenSource
from aslms.domain.events import AuditLog
from aslms.domain.ops import FetchKind, FetchLane, FetchQueueItem, FetchStatus, NapixCallLog, NapixResponse
from aslms.domain.ownership import (
    CaseOfficeScore,
    DiscoveryHit,
    DiscoveryTerm,
    Recommendation,
    RecommendationOrigin,
    ScoreBand,
)
from aslms.services import discovery, queue
from aslms.services import matching_rules as mr
from aslms.services.napix_store import NapixRecorder
from aslms.services.runner import QueueRunner
from aslms.services.storage import LocalStore
from tests.db.conftest import router
from tests.db.discovery_support import party_rows, ref, years

SAMPLE_CNRS = {"GAHC010257252024", "GAHC010277142024", "GAHC010271682024"}
PARTY_API = "hc-party-name-api/partyname"
THIRD_RESPONDENT = "THE NORTH CACHAR HILLS AUTONOMOUS COUNCIL"  # res_extra_party of the dossier sample


def processed(rows: list[FetchQueueItem]) -> FetchQueueItem:
    """The one row the runner took (max_items=1). Rows queued in one transaction share created_at and priority, so
    which year the runner takes first is not fixed: find the row that is no longer pending."""
    taken = [r for r in rows if r.status != FetchStatus.PENDING]
    assert len(taken) == 1, [(r.ref, r.status) for r in rows]
    return taken[0]


def _runner(Session, hc, tmp_path, recorder, **kw) -> QueueRunner:
    settings = Settings(
        _env_file=None, storage_dir=str(tmp_path / "store"), causelist_dir=str(tmp_path / "lists"), **kw
    )
    return QueueRunner(
        Session,
        hc,
        settings=settings,
        store=LocalStore(settings.storage_dir),
        causelist_dir=tmp_path / "lists",
        recorder=recorder,
    )


def _run(Session, napix, tmp_path, *, kinds, max_items=None, **kw):
    gw, client, hc = napix
    recorder = NapixRecorder()
    client.on_call = recorder.on_call

    async def go():
        async with client:
            return await _runner(Session, hc, tmp_path, recorder, **kw).run(max_items=max_items, kinds=kinds)

    return asyncio.run(go())


def _rule(world, key: str, office: str, text: str, kind: str | None = "prefix"):
    with world.Session() as s:
        actor, admin = world.actor(s, key)
        if kind is None:
            row = mr.create_keyword(s, actor, admin, keyword=text, office=world.office(s, office))
        else:
            row = mr.create_name_pattern(
                s, actor, admin, pattern=text, kind=kind, office=world.office(s, office)
            )
        s.commit()
        return row.id


def _party_calls(s) -> list[NapixCallLog]:
    return list(s.scalars(sa.select(NapixCallLog).where(NapixCallLog.api.like("%party%"))))


def test_a_search_stores_records_and_queues_dossiers(world, napix, tmp_path):
    _rule(world, "edu_admin", "EDU-DSE", "Janifa Kaifee Ahmed")
    with world.Session() as s:
        audits = s.scalar(sa.select(sa.func.count()).select_from(AuditLog))
    rep = _run(world.Session, napix, tmp_path, kinds=[FetchKind.PARTY_SEARCH], max_items=1)
    assert rep.done == 1, rep.items
    with world.Session() as s:
        first = processed(party_rows(s, "JANIFA KAIFEE AHMED"))
        assert (
            first.ref in {ref(y, "JANIFA KAIFEE AHMED") for y in years()} and first.status == FetchStatus.DONE
        )
        assert (
            first.result["rows"] == 3
            and first.result["created"] == 3
            and first.result["dossiers_queued"] == 3
        )
        cases = s.scalars(sa.select(Case).where(Case.cnr.in_(SAMPLE_CNRS))).all()
        assert len(cases) == 3  # the I.A. row included
        assert {FirstSeenSource(c.first_seen_source) for c in cases} == {FirstSeenSource.DISCOVERY}
        assert all(c.ref_no.startswith("ASLMS/EDU/CASE/") for c in cases)
        term = s.scalar(sa.select(DiscoveryTerm).where(DiscoveryTerm.term == "JANIFA KAIFEE AHMED"))
        assert (term.searches_done, term.cases_found) == (1, 3) and term.last_searched_at is not None
        hits = s.scalars(sa.select(DiscoveryHit).where(DiscoveryHit.term_id == term.id)).all()
        assert len(hits) == 3 and {h.reg_year for h in hits} == {discovery.parse_ref(first.ref)[1]}
        dossiers = s.scalars(sa.select(FetchQueueItem).where(FetchQueueItem.kind == FetchKind.DOSSIER)).all()
        assert {d.ref for d in dossiers} == SAMPLE_CNRS
        assert {(d.lane, d.priority) for d in dossiers} == {(FetchLane.DISCOVERY, 41)}
        calls = _party_calls(s)
        assert len(calls) == 1 and calls[0].lane == FetchLane.DISCOVERY and calls[0].user_id is None
        assert s.scalar(sa.select(sa.func.count()).where(NapixResponse.api.like("%party%"))) == 1
        assert (
            s.scalar(sa.select(sa.func.count()).select_from(AuditLog)) == audits
        )  # system work: no audit row
        first_found = {h.case_id: h.last_found_at for h in hits}
    # the next year's search returns the same rows: only `last_found_at` moves
    if len(years()) > 1:
        rep = _run(world.Session, napix, tmp_path, kinds=[FetchKind.PARTY_SEARCH], max_items=1)
        assert rep.done == 1, rep.items
        with world.Session() as s:
            hits = s.scalars(sa.select(DiscoveryHit)).all()
            assert len(hits) == 3
            assert all(h.last_found_at >= first_found[h.case_id] for h in hits)
            term = s.scalar(sa.select(DiscoveryTerm))
            assert (term.searches_done, term.cases_found) == (2, 3)
            assert s.scalar(sa.select(sa.func.count()).where(Case.cnr.in_(SAMPLE_CNRS))) == 3


def test_two_departments_allocate_on_goa(world, napix, tmp_path):
    _rule(world, "edu_admin", "EDU", "JANIFA KAIFEE AHMED", kind=None)
    _rule(world, "health_admin", "HEALTH", "JANIFA KAIFEE AHMED", kind="exact")
    rep = _run(world.Session, napix, tmp_path, kinds=[FetchKind.PARTY_SEARCH], max_items=1)
    assert rep.done == 1, rep.items
    with world.Session() as s:
        cases = s.scalars(sa.select(Case).where(Case.cnr.in_(SAMPLE_CNRS))).all()
        assert len(cases) == 3 and all(c.ref_no.startswith("ASLMS/GOA/CASE/") for c in cases)


def test_a_held_case_is_only_recorded(world, napix, tmp_path):
    from tests.db.world import make_case

    with world.Session() as s:
        held = make_case(s, cnr="GAHC010257252024", case_no="WP(C)/6434/2024")
        held.last_full_refresh_at = datetime.now(UTC)
        held_ref = held.ref_no
        s.commit()
    _rule(world, "edu_admin", "EDU", "JANIFA KAIFEE AHMED", kind=None)
    rep = _run(world.Session, napix, tmp_path, kinds=[FetchKind.PARTY_SEARCH], max_items=1)
    assert rep.done == 1, rep.items
    with world.Session() as s:
        held = s.scalar(sa.select(Case).where(Case.cnr == "GAHC010257252024"))
        assert (
            held.ref_no == held_ref and FirstSeenSource(held.first_seen_source) == FirstSeenSource.CAUSELIST
        )
        assert s.scalar(sa.select(sa.func.count()).where(DiscoveryHit.case_id == held.id)) == 1
        dossiers = {
            d.ref
            for d in s.scalars(sa.select(FetchQueueItem).where(FetchQueueItem.kind == FetchKind.DOSSIER))
        }
        assert dossiers == SAMPLE_CNRS - {"GAHC010257252024"}  # it has its dossier already


def test_628_is_an_empty_done_row(world, napix, tmp_path):
    gw, client, hc = napix
    base = router(gw)

    def handle(path, q, request):
        if path == PARTY_API:
            return gw.encrypted_status(628)
        return base(path, q, request)

    gw.responses = [handle] * 100
    _rule(world, "edu_admin", "EDU", "NOBODY AT ALL", kind=None)
    rep = _run(world.Session, napix, tmp_path, kinds=[FetchKind.PARTY_SEARCH], max_items=1)
    assert rep.done == 1, rep.items
    with world.Session() as s:
        row = processed(party_rows(s, "NOBODY AT ALL"))
        assert row.status == FetchStatus.DONE and row.result["rows"] == 0 and row.result["stored"] == 0
        term = s.scalar(sa.select(DiscoveryTerm))
        assert term.last_searched_at is not None and term.searches_done == 1 and term.cases_found == 0


def test_a_term_without_an_active_rule_is_skipped_without_a_call(world, napix, tmp_path):
    rule_id = _rule(world, "edu_admin", "EDU", "JANIFA KAIFEE AHMED", kind=None)
    with world.Session() as s:
        actor, admin = world.actor(s, "edu_admin")
        from aslms.domain.ownership import OfficeKeyword

        mr.update_keyword(s, actor, admin, s.get(OfficeKeyword, rule_id), discover=False)
        s.commit()
    rep = _run(world.Session, napix, tmp_path, kinds=[FetchKind.PARTY_SEARCH])
    assert rep.skipped == len(years()) and rep.done == 0, rep.items
    with world.Session() as s:
        assert {r.status for r in party_rows(s)} == {FetchStatus.SKIPPED}
        assert _party_calls(s) == []


def test_a_malformed_cino_is_counted_not_stored(world, napix, tmp_path):
    gw, client, hc = napix
    base = router(gw)

    def handle(path, q, request):
        if path == PARTY_API:
            return gw.envelope(
                {
                    "casenos": {
                        "case1": {
                            "cino": "NOT-A-CNR",
                            "type_name": "WP(C)",
                            "reg_no": "1",
                            "reg_year": "2026",
                        },
                        "case2": {
                            "cino": "GAHC010000012026",
                            "type_name": "WP(C)",
                            "reg_no": "2",
                            "reg_year": "2026",
                        },
                    }
                }
            )
        return base(path, q, request)

    gw.responses = [handle] * 100
    _rule(world, "edu_admin", "EDU", "SOME OFFICER", kind=None)
    rep = _run(world.Session, napix, tmp_path, kinds=[FetchKind.PARTY_SEARCH], max_items=1)
    assert rep.done == 1, rep.items
    with world.Session() as s:
        row = processed(party_rows(s, "SOME OFFICER"))
        assert (row.result["rows"], row.result["stored"], row.result["unmatched"]) == (2, 1, 1)
        assert s.scalar(sa.select(sa.func.count()).select_from(Case)) == 1


def test_the_dossier_scores_with_origin_discovery(world, napix, tmp_path):
    """After the dossier of a discovered case, a name pattern matching its third respondent recommends it with origin
    `discovery`, band medium, 0.800; a keyword-only department stays in the pool."""
    _rule(world, "edu_admin", "EDU", THIRD_RESPONDENT, kind="prefix")
    _rule(world, "health_admin", "HEALTH", "PRINCIPAL CHIEF CONSERVATOR", kind=None)
    rep = _run(
        world.Session, napix, tmp_path, kinds=[FetchKind.PARTY_SEARCH, FetchKind.DOSSIER], max_items=2 + 3
    )
    assert rep.failed == 0, rep.items
    with world.Session() as s:
        edu, health = world.office(s, "EDU"), world.office(s, "HEALTH")
        case = s.scalar(sa.select(Case).where(Case.cnr == "GAHC010257252024"))
        assert case.last_full_refresh_at is not None
        rec = s.scalar(sa.select(Recommendation).where(Recommendation.case_id == case.id))
        assert rec.office_id == edu.id
        assert (rec.origin, rec.band, float(rec.score)) == (
            RecommendationOrigin.DISCOVERY,
            ScoreBand.MEDIUM,
            0.8,
        )
        scores = s.scalars(sa.select(CaseOfficeScore).where(CaseOfficeScore.case_id == case.id)).all()
        kinds = {sig["kind"] for sc in scores for sig in sc.signals}
        assert kinds <= {
            "counsel_code",
            "keyword",
            "name_pattern",
            "linked_case",
            "watchlist",
            "suggested_unit",
        }
        health_score = next(sc for sc in scores if sc.office_id == health.id)
        assert float(health_score.score) == 0.4
        assert s.scalar(sa.select(sa.func.count()).where(Recommendation.office_id == health.id)) == 0


def _log_call(s, remaining: int, lane: str | None = None) -> None:
    s.add(
        NapixCallLog(
            api="hc-cnr-api/CNR",
            params_sha256="x" * 64,
            ok=True,
            rate_limit_remaining=remaining,
            lane=lane,
            called_at=datetime.now(UTC),
        )
    )


def test_the_share_stops_discovery_claims(world, napix, tmp_path):
    _rule(world, "edu_admin", "EDU", "JANIFA KAIFEE AHMED", kind=None)
    with world.Session() as s:
        for _ in range(4):
            _log_call(s, 900, "discovery")
        queue.enqueue(s, FetchKind.CAUSELIST_DAY, "2025-01-06", 20)
        s.commit()
    rep = _run(world.Session, napix, tmp_path, kinds=None, napix_discovery_share=4)
    assert rep.load_only and rep.stopped_reason.startswith("discovery share spent: 4 of 4"), (
        rep.stopped_reason
    )
    with world.Session() as s:
        day = s.scalar(sa.select(FetchQueueItem).where(FetchQueueItem.kind == FetchKind.CAUSELIST_DAY))
        assert day.status == FetchStatus.DONE  # the daily row ran
        assert {r.status for r in party_rows(s)} == {FetchStatus.PENDING}
        assert _party_calls(s) == []


def test_below_the_reserve_no_discovery_row_is_claimed(world, napix, tmp_path):
    _rule(world, "edu_admin", "EDU", "JANIFA KAIFEE AHMED", kind=None)
    with world.Session() as s:
        _log_call(s, 120)  # between the live reserve (100) and the rate reserve (150)
        s.commit()
    rep = _run(world.Session, napix, tmp_path, kinds=None)
    assert rep.processed == 0 and rep.load_only, rep.stopped_reason
    with world.Session() as s:
        assert {r.status for r in party_rows(s)} == {FetchStatus.PENDING}


def test_with_share_left_discovery_runs_and_counts(world, napix, tmp_path):
    _rule(world, "edu_admin", "EDU", "JANIFA KAIFEE AHMED", kind=None)
    rep = _run(world.Session, napix, tmp_path, kinds=[FetchKind.PARTY_SEARCH], napix_discovery_share=1)
    # one discovery call allowed: one search runs, the rest wait for the next window
    assert rep.done == 1, rep.items
    assert rep.load_only and "discovery share spent: 1 of 1" in rep.stopped_reason
    with world.Session() as s:
        assert sum(1 for r in party_rows(s) if r.status == FetchStatus.PENDING) == len(years()) - 1
        assert discovery.discovery_calls(s, discovery.napix_window.current(s, Settings(_env_file=None))) == 1
