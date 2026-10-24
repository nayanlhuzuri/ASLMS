"""`NapixRecorder.flush_apart` (design `followups-oct`, decision 7): `response_ids` names the responses written by the
last flush, an empty flush included."""

from __future__ import annotations

import uuid

from aslms.services.napix_store import NapixRecorder


def test_empty_flush_apart_resets_response_ids():
    rec = NapixRecorder()
    rec.response_ids = {("hc-cnr-api/CNR", "0" * 64): uuid.uuid4()}  # left by an earlier flush

    def factory():  # never opened: nothing is pending
        raise AssertionError("an empty flush opens no session")

    assert rec.flush_apart(factory) == 0
    assert rec.response_ids == {}
