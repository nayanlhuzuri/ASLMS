"""The Current Status batch respects the gateway's query-string limit (live probe 7 Oct 2026: 300 CNRs accepted,
350 refused with HTTP 414): the setting defaults to 250 and cannot exceed 300, and the API wrapper refuses more."""

from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from aslms.core.config import Settings
from aslms.integration.napix.hc import NapixHighCourt


def test_status_batch_default_and_cap():
    assert Settings(_env_file=None).napix_status_batch == 250
    assert Settings(_env_file=None, napix_status_batch=300).napix_status_batch == 300
    with pytest.raises(ValidationError):
        Settings(_env_file=None, napix_status_batch=500)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, napix_status_batch=0)


def test_current_status_refuses_more_than_300_cnrs():
    hc = NapixHighCourt(client=None, est_code="GAHC01", state_code="18")  # refused before any call
    cnrs = [f"GAHC01{n:010d}" for n in range(301)]
    with pytest.raises(ValueError, match="at most 300"):
        asyncio.run(hc.current_status(cnrs))
