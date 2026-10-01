"""Seed is idempotent and complete; reference numbers follow Appendix C; a code outside ref_* is rejected."""

from __future__ import annotations

import threading

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from aslms.domain.org import Office
from aslms.domain.reference import REF_TABLES, OfficeKind, RecordType
from aslms.services.refno import allocate_ref_no, parse_ref_no
from aslms.services.seed import ASSAM_DISTRICTS, DESIGNATIONS, GAUHATI_HC_COURTS, seed_all


def test_seed_twice_inserts_nothing_the_second_time(session):
    first = seed_all(session)
    assert first.total > 0
    second = seed_all(session)
    assert second.total == 0, second.inserted
    for table, (model, enum_cls) in REF_TABLES.items():
        assert session.scalar(sa.select(sa.func.count()).select_from(model)) == len(enum_cls), table
    assert first.inserted["designations"] == len(DESIGNATIONS) == 18
    assert first.inserted["districts"] == len(ASSAM_DISTRICTS) == 35
    assert first.inserted["courts"] == len(GAUHATI_HC_COURTS) == 4
    assert (
        first.inserted["high_courts"] == 1
        and first.inserted["states"] == 1
        and first.inserted["offices"] == 1
    )


def test_code_outside_the_ref_set_is_rejected(session):
    seed_all(session)
    with pytest.raises(sa.exc.IntegrityError):
        session.add(Office(code="X", name="x", kind="not_a_kind", path="X"))  # type: ignore[arg-type]
        session.flush()
    session.rollback()


def test_ref_no_format_and_sequence(session):
    seed_all(session)
    a = allocate_ref_no(session, "GOA", RecordType.CASE.value)
    b = allocate_ref_no(session, "GOA", RecordType.CASE.value)
    c = allocate_ref_no(session, "GOA", RecordType.REQ.value)
    assert parse_ref_no(a) is not None
    office, rtype, year, n = parse_ref_no(a)
    assert office == "GOA" and rtype == "CASE" and n == 1
    assert parse_ref_no(b)[3] == 2
    assert parse_ref_no(c)[3] == 1
    assert a == f"ASLMS/GOA/CASE/{year}/000001"


def test_unknown_record_type_is_rejected(session):
    seed_all(session)
    with pytest.raises(sa.exc.IntegrityError):
        allocate_ref_no(session, "GOA", "NOPE")
    session.rollback()


def test_concurrent_allocations_are_distinct(engine):
    """Two real connections allocate at the same time and never get the same number."""
    Session = sessionmaker(bind=engine)
    with Session() as s:
        seed_all(s)
        s.commit()
    results: list[str] = []
    errors: list[Exception] = []

    def worker() -> None:
        try:
            with Session() as s:
                for _ in range(20):
                    results.append(allocate_ref_no(s, "GOA", "NXT"))
                s.commit()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert len(results) == 80 and len(set(results)) == 80
    with engine.begin() as conn:
        conn.execute(sa.text("delete from ref_sequences where record_type = 'NXT'"))
        conn.execute(sa.text("delete from offices where code = 'GOA'"))


def test_office_kind_is_the_enum_in_python(session):
    seed_all(session)
    root = session.scalar(sa.select(Office).where(Office.code == "GOA"))
    assert root is not None and root.kind is OfficeKind.STATE
