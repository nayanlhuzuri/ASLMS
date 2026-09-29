"""DB_STANDARD §3 / Appendix C: reference numbers are `ASLMS/<OFFICE>/<TYPE>/<YYYY>/<NNNNNN>`, counted per
office, type and year, distinct across concurrent sessions, and accepted by the API wherever an id is."""

from __future__ import annotations

import re
import threading

import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from aslms.core.time import now_ist
from aslms.domain.cases import Case
from aslms.services import cases as case_svc
from aslms.services.refno import RecordType, allocate_ref_no, from_slug, is_ref_no, parse_ref_no, ref_no_slug
from tests.integration.helpers import auth, login

FORMAT = re.compile(r"^ASLMS/[A-Z0-9-]{1,20}/[A-Z]{2,10}/\d{4}/\d{6}$")


def test_format_and_sequence_per_office_type_year(db: Session) -> None:
    year = now_ist().year
    a = allocate_ref_no(db, "GOA", RecordType.CASE)
    b = allocate_ref_no(db, "GOA", RecordType.CASE)
    c = allocate_ref_no(db, "GOA", RecordType.ALR)
    d = allocate_ref_no(db, "SEC-EDU", RecordType.REQ)
    assert a == f"ASLMS/GOA/CASE/{year}/000001" and b == f"ASLMS/GOA/CASE/{year}/000002"
    assert c == f"ASLMS/GOA/ALR/{year}/000001" and d == f"ASLMS/SEC-EDU/REQ/{year}/000001"
    assert all(FORMAT.match(x) for x in (a, b, c, d))
    assert parse_ref_no(d) == {"office": "SEC-EDU", "type": "REQ", "year": year, "n": 1}
    assert from_slug(ref_no_slug(d)) == d and is_ref_no(from_slug("aslms-sec-edu-req-2026-000001"))
    assert not is_ref_no("GAHC010153612024") and not is_ref_no("WP(C)/1/2024")
    db.commit()
    assert (
        db.scalar(
            sa.text("SELECT last_value FROM ref_sequences WHERE office_code='GOA' AND record_type='CASE'")
        )
        == 2
    )


def test_two_concurrent_sessions_get_distinct_numbers(db: Session) -> None:
    """The first session holds the sequence row until it commits; the second waits on it and continues."""
    from aslms.db.session import sync_engine

    engine = sync_engine()
    first = Session(engine)
    n1 = allocate_ref_no(first, "GOA", RecordType.NOTE)
    got: list[str] = []
    started = threading.Event()

    def other() -> None:
        with Session(engine) as s:
            started.set()
            got.append(allocate_ref_no(s, "GOA", RecordType.NOTE))
            s.commit()

    t = threading.Thread(target=other)
    t.start()
    started.wait(5)
    assert not got, "the second allocation must wait for the first to commit"
    first.commit()
    first.close()
    t.join(10)
    year = now_ist().year
    assert got and got[0] != n1
    assert {n1, got[0]} == {f"ASLMS/GOA/NOTE/{year}/000001", f"ASLMS/GOA/NOTE/{year}/000002"}


def test_every_case_has_a_reference_number(world, db: Session) -> None:
    rows = db.execute(sa.select(Case.ref_no, Case.cnr)).all()
    assert rows and all(FORMAT.match(r.ref_no) and r.ref_no.startswith("ASLMS/GOA/CASE/") for r in rows)
    assert len({r.ref_no for r in rows}) == len(rows)


def test_api_resolves_id_ref_no_and_cnr(client: TestClient, world, db: Session) -> None:
    case = db.scalar(sa.select(Case).where(Case.cnr.isnot(None)).limit(1))
    tokens = login(client, "edu.admin@t.in")
    by_id = client.get(f"/api/v1/cases/{case.id}", headers=auth(tokens))
    by_ref = client.get(f"/api/v1/cases/{ref_no_slug(case.ref_no)}", headers=auth(tokens))
    by_cnr = client.get(f"/api/v1/cases/{case.cnr}", headers=auth(tokens))
    assert by_id.status_code == by_ref.status_code == by_cnr.status_code == 200, (
        by_id.status_code,
        by_ref.status_code,
        by_cnr.status_code,
        ref_no_slug(case.ref_no),
        case.cnr,
    )
    assert by_id.json()["id"] == by_ref.json()["id"] == by_cnr.json()["id"] == str(case.id)
    assert by_ref.json()["ref_no"] == case.ref_no
    assert case_svc.resolve_case_ref(db, "ASLMS-NOWHERE-CASE-2026-999999") is None
    assert client.get("/api/v1/cases/ASLMS-NOWHERE-CASE-2026-999999", headers=auth(tokens)).status_code == 404
    hits = client.get(
        "/api/v1/search", params={"q": case.ref_no, "live": "false"}, headers=auth(tokens)
    ).json()
    assert hits["total"] == 1 and hits["items"][0]["id"] == str(case.id)
