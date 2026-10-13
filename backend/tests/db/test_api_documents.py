"""`GET /documents/types` (design portal-workflow, decision 20e): the uploadable types carry the upload limits
the portal checks before sending — `max_bytes` from the settings and the permitted extensions."""

from __future__ import annotations

import pytest

from tests.db import docs_support as ds

MAX = 1234567


@pytest.fixture()
def api(world, tmp_path):
    client = ds.make_api(world, tmp_path, upload_max_bytes=MAX)
    yield client
    client.__exit__(None, None, None)


def test_types_carry_upload_limits(api):
    r = api.get("/documents/types", headers=ds.login(api, "edu_off1"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["upload"]["max_bytes"] == MAX == api.settings.upload_max_bytes
    assert body["upload"]["extensions"] == ["pdf", "docx", "doc", "jpg", "jpeg", "png"]
    assert body["items"] and all("group_choosable" in t for t in body["items"])


def test_types_need_documents_view(api):
    assert api.get("/documents/types").status_code == 401
