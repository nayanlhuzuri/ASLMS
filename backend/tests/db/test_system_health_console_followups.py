"""System health console follow-ups (design `followups-oct`, decisions 9, 10 and 12): the latest answer's size is
checked in the database before any payload is read; party names up to the sample cap of 200 (advocate names still
99); a typed value never confirms a hidden sample."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa

from aslms.core.config import Settings
from aslms.domain.ops import NapixCallLog, NapixResponse
from aslms.services import napix_inspect
from aslms.services.napix_samples import Sample

SETTINGS = Settings(_env_file=None, health_raw_max_bytes=10_000)
NAME150 = ("RAMESH KUMAR " * 12)[:149] + "Z"
PARTY_FORM = {"est_code": "GAHC01", "pend_disp": "P", "litigant_name": NAME150, "reg_year": "2024"}


def _stored(s, payload, *, api="hc-state-api/state"):
    now = datetime.now(UTC)
    s.add(NapixCallLog(api=api, params_sha256="a" * 64, ok=True, http_status=200, called_at=now))
    s.add(
        NapixResponse(
            api=api,
            params_sha256="a" * 64,
            payload_sha256="b" * 64,
            payload=payload,
            fetched_at=now - timedelta(minutes=1),
            last_seen_at=now - timedelta(minutes=1),
        )
    )
    s.flush()


class Statements:
    def __init__(self, session):
        self.seen: list[str] = []
        self.conn = session.connection()
        sa.event.listen(self.conn, "before_cursor_execute", self._record)

    def _record(self, conn, cursor, statement, *args):
        self.seen.append(" ".join(statement.split()))

    def close(self):
        sa.event.remove(self.conn, "before_cursor_execute", self._record)


def test_latest_answer_over_limit_reads_no_payload(world):
    big = {"state": [{"state_code": i, "state_name": "A" * 200} for i in range(100)]}  # ~22 kB > 10 kB
    with world.Session() as s:
        _stored(s, big)
        spy = Statements(s)
        out = napix_inspect.latest_answer(s, SETTINGS, None, "state")
        spy.close()
        assert out["response_too_large"] is True
        assert out["structure"] is None and out["inventory_diff"] is None
        assert out["response_available"] is True and out["response_id"] is not None
        reads = [q for q in spy.seen if "napix_responses" in q]
        assert reads and all("octet_length(payload::text)" in q for q in reads), reads
        assert not any("SELECT payload" in q for q in spy.seen)
        s.rollback()


def test_latest_answer_within_limit_reads_the_structure(world):
    with world.Session() as s:
        _stored(s, {"state": [{"state_code": 18, "state_name": "Assam"}]})
        out = napix_inspect.latest_answer(s, SETTINGS, None, "state")
        assert out["response_too_large"] is False and out["structure"] is not None
        s.rollback()


def test_held_party_sample_of_150_chars_is_sendable_unedited(world):
    held = Sample(
        values={"est_code": "GAHC01", "pend_disp": "P", "name": NAME150, "reg_year": 2024},
        label="A party of a fetched case",
        source_case_id=uuid.uuid4(),
        case_visible=True,
    )
    with world.Session() as s:
        out = napix_inspect.validate(s, SETTINGS, "party_name", PARTY_FORM, held)
    assert len(NAME150) == 150
    assert out.edited is False and out.source_case_id == held.source_case_id
    assert out.values["name"] == NAME150


def test_party_name_over_200_is_refused(world):
    with world.Session() as s, pytest.raises(napix_inspect.InvalidInput) as exc:
        napix_inspect.check_values(s, SETTINGS, "party_name", {**PARTY_FORM, "litigant_name": "A" * 201})
    assert "200" in exc.value.errors["litigant_name"]


def test_advocate_name_still_capped_at_99(world):
    form = {"est_code": "GAHC01", "pend_disp": "P", "advocate_name": "A" * 100, "reg_year": "2024"}
    with world.Session() as s:
        with pytest.raises(napix_inspect.InvalidInput) as exc:
            napix_inspect.check_values(s, SETTINGS, "advocate_name", form)
        assert "99" in exc.value.errors["advocate_name"]
        typed = napix_inspect.check_values(s, SETTINGS, "advocate_name", {**form, "advocate_name": "A" * 99})
    assert typed["name"] == "A" * 99


def test_typed_value_equal_to_hidden_sample_is_edited(world):
    held = Sample(
        values={"est_code": "GAHC01", "pend_disp": "P", "name": NAME150, "reg_year": 2024},
        label="A party of a fetched case",
        source_case_id=uuid.uuid4(),
        source_ref_no="C-2026-000001",
        case_visible=False,
    )
    with world.Session() as s:
        out = napix_inspect.validate(s, SETTINGS, "party_name", PARTY_FORM, held)
    assert out.edited is True and out.label == napix_inspect.FORM_LABEL
    assert out.source_case_id is None and out.source_ref_no is None
