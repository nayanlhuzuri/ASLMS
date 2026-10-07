"""Uploads (design documents-uploads, decisions 1, 3–6, 8, 9, 12): the happy path with its ref_no, store
file, audit row and event; the SourceTrace status per group and visibility; infected and scanner-down
uploads store nothing; the size limit; the type rule; who may upload (a working relation, not sight); the
duplicate rule; the field rules; and an order PDF whose bytes equal an earlier upload."""

from __future__ import annotations

import asyncio
import uuid
from datetime import date, timedelta

import pytest
import sqlalchemy as sa

from aslms.domain.cases import Case
from aslms.domain.documents import Document, DocumentText, Order
from aslms.domain.events import Event
from aslms.domain.ownership import CounselCode, Recommendation, RecommendationOrigin, ScoreBand
from aslms.services import ownership as own
from aslms.services.orders import fetch_order_pdf
from aslms.services.scanner import eicar_test_string
from tests import samplefiles as sf
from tests.db import docs_support as ds
from tests.db.auth_support import forget_devices
from tests.db.test_case_visibility import entry_with_codes
from tests.db.world import make_case


@pytest.fixture()
def api(world, tmp_path):
    client = ds.make_api(world, tmp_path)
    yield client
    client.__exit__(None, None, None)


@pytest.fixture()
def owned(world):
    """A case EDU claimed and allotted to off1 at unit EDU-DSE; a pool case; a case only recommended to EDU."""
    with world.Session() as s:
        case = make_case(s, case_no="WP(C)/100/2025")
        actor, admin = world.actor(s, "edu_admin")
        own.claim(s, actor, admin, case, unit_code="EDU-DSE", officer_user_id=world.user(s, "edu_off1").id)
        pool = make_case(s, case_no="WP(C)/101/2025")
        rec = make_case(s, case_no="WP(C)/102/2025")
        s.add(
            Recommendation(
                case_id=rec.id,
                office_id=world.office(s, "EDU").id,
                score=0.95,
                band=ScoreBand.HIGH,
                origin=RecommendationOrigin.CAUSE_LIST,
                actor_name="matching",
            )
        )
        s.commit()
        return {"owned": case.id, "pool": pool.id, "recommended": rec.id}


def _doc(world, doc_id) -> Document:
    with world.Session() as s:
        return s.get(Document, uuid.UUID(str(doc_id)))


# ------------------------------------------------------------------------------------------------ happy path


def test_edu_admin_uploads_a_pdf(api, world, owned):
    pdf = sf.text_pdf(["Writ petition under Article 226."])
    r = ds.upload(api, ds.login(api, "edu_admin"), owned["owned"], pdf)
    assert r.status_code == 201, r.text
    body = r.json()
    year = date.today().year
    assert body["ref_no"] == f"ASLMS/EDU/DOC/{year}/000001"
    assert body["kind"] == "upload" and body["doc_type"] == "petition" and body["doc_group"] == "court_filing"
    assert body["virus_scan_status"] == "clean" and body["text_status"] == "pending"
    assert body["sourcetrace_status"] == "pending" and body["assistant_available"] is False
    assert body["mime"] == "application/pdf" and body["size_bytes"] == len(pdf)
    assert body["office"]["code"] == "EDU" and body["uploaded_by"]["name"] == "Edu Admin"
    assert body["case"]["case_no_text"] == "WP(C)/100/2025" and body["can_manage"] is True
    assert body["visibility"] == "case_scope" and body["original_filename"] == "petition.pdf"
    digest = ds.sha(pdf)
    assert api.store.path(f"{digest[:2]}/{digest}.pdf").read_bytes() == pdf
    assert api.scanner.seen == [len(pdf)]
    with world.Session() as s:
        doc = s.get(Document, uuid.UUID(body["id"]))
        assert doc.sha256 == digest and doc.office_id == world.office(s, "EDU").id
        assert doc.actor_user_id == world.users["edu_admin"].id and doc.scanned_at is not None
        rows = ds.audit_rows(s, "document.uploaded", entity_id=doc.id)
        assert len(rows) == 1 and rows[0].case_id == owned["owned"]
        assert rows[0].after["sha256"] == digest and rows[0].after["sourcetrace_status"] == "pending"
        ev = s.scalar(sa.select(Event).where(Event.dedupe_key == f"document_uploaded:{doc.id}"))
        assert ev is not None and ev.case_id == owned["owned"] and ev.visibility.value == "scoped"
        assert ev.payload["ref_no"] == doc.ref_no and ev.payload["office_code"] == "EDU"
        assert ev.actor_user_id == world.users["edu_admin"].id


def test_allotted_unit_user_uploads_on_its_own_office(api, world, owned):
    r = ds.upload(
        api,
        ds.login(api, "dse_user"),
        owned["owned"],
        sf.docx(),
        "comments.docx",
        doc_type="parawise_comments",
    )
    assert r.status_code == 201, r.text
    assert r.json()["ref_no"].startswith("ASLMS/EDU-DSE/DOC/")
    assert r.json()["doc_group"] == "internal" and r.json()["text_status"] == "pending"
    r = ds.upload(api, ds.login(api, "edu_off1"), owned["owned"], sf.png(), "scan.png", doc_type="annexure")
    assert r.status_code == 201 and r.json()["text_status"] == "none" and r.json()["mime"] == "image/png"


# ------------------------------------------------------------------------------------------------ sourcetrace


def test_sourcetrace_status_follows_group_and_visibility(api, world, owned):
    h = ds.login(api, "edu_admin")
    filing = ds.upload(api, h, owned["owned"], sf.text_pdf(["a"]), visibility="case_scope").json()
    assert filing["sourcetrace_status"] == "pending"
    internal = ds.upload(
        api, h, owned["owned"], sf.text_pdf(["b"]), doc_type="parawise_comments", visibility="case_scope"
    ).json()
    assert internal["doc_group"] == "internal" and internal["sourcetrace_status"] == "not_applicable"
    private = ds.upload(api, h, owned["owned"], sf.text_pdf(["c"]), visibility="private_to_office").json()
    assert private["doc_group"] == "court_filing" and private["sourcetrace_status"] == "not_applicable"
    widened = api.patch(f"/documents/{private['id']}", headers=h, json={"visibility": "counsel_shared"})
    assert widened.status_code == 200 and widened.json()["sourcetrace_status"] == "pending"
    with world.Session() as s:
        doc = s.get(Document, uuid.UUID(internal["id"]))
        doc.sourcetrace_status = "pending"
        with pytest.raises(sa.exc.IntegrityError, match="ck_documents_internal_not_sent"):
            s.flush()
        s.rollback()
        assert (
            s.scalar(
                sa.select(sa.func.count())
                .select_from(Document)
                .where(Document.doc_group == "internal", Document.sourcetrace_status != "not_applicable")
            )
            == 0
        )


# ------------------------------------------------------------------------------------------------ scan, size, type


def test_infected_upload_stores_nothing_and_audits(api, world, owned):
    h = ds.login(api, "edu_admin")
    bad = sf.text_pdf(["x"]) + b"\n%" + eicar_test_string()
    r = ds.upload(api, h, owned["owned"], bad, "bad.pdf")
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "infected" and r.json()["detail"]["signature"] == "Eicar-Signature"
    digest = ds.sha(bad)
    assert not api.store.path(f"{digest[:2]}/{digest}.pdf").exists()
    assert not list(api.store.root.rglob("*")) or not any(p.is_file() for p in api.store.root.rglob("*"))
    with world.Session() as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(Document)) == 0
        rows = ds.audit_rows(s, "document.upload_rejected")
        assert len(rows) == 1 and rows[0].entity_id is None and rows[0].case_id == owned["owned"]
        assert rows[0].after["reason"] == "infected" and rows[0].after["sha256"] == digest
        assert (
            rows[0].after["original_filename"] == "bad.pdf"
            and rows[0].after["signature"] == "Eicar-Signature"
        )


def test_scanner_down_is_503_and_nothing_is_written(api, world, owned):
    api.scanner.fail = True
    pdf = sf.text_pdf(["y"])
    r = ds.upload(api, ds.login(api, "edu_admin"), owned["owned"], pdf)
    assert r.status_code == 503 and r.json()["detail"]["code"] == "scanner_unavailable"
    assert not any(p.is_file() for p in api.store.root.rglob("*")) if api.store.root.exists() else True
    with world.Session() as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(Document)) == 0
        assert ds.audit_rows(s, "document.upload_rejected") == []
        assert ds.audit_rows(s, "document.uploaded") == []


def test_size_limit_before_and_after_reading(api, world, owned):
    h = ds.login(api, "edu_admin")
    big = sf.text_pdf(["z"]) + b"\n%" + b"0" * (21 * 1024 * 1024)
    r = ds.upload(api, h, owned["owned"], big)
    assert r.status_code == 413 and r.json()["detail"]["code"] == "too_large"
    assert api.scanner.seen == []
    # a client that understates the header: the endpoint counts the bytes it reads
    api.settings.upload_max_bytes = 10_000
    r = ds.upload(api, h, owned["owned"], sf.text_pdf(["w"]) + b"\n%" + b"1" * 20_000)
    assert r.status_code == 413 and r.json()["detail"]["code"] == "too_large"
    assert api.scanner.seen == []
    with world.Session() as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(Document)) == 0
        assert ds.audit_rows(s, "document.upload_rejected") == []


def test_type_decided_by_bytes_with_an_audit_row(api, world, owned):
    h = ds.login(api, "edu_admin")
    r = ds.upload(api, h, owned["owned"], sf.text_pdf(["p"]), "petition.docx")
    assert r.status_code == 415 and r.json()["detail"]["code"] == "type_not_allowed"
    assert r.json()["detail"]["detected"] == "pdf" and r.json()["detail"]["extension"] == "docx"
    r = ds.upload(api, h, owned["owned"], sf.exe(), "setup.pdf")
    assert r.status_code == 415
    r = ds.upload(api, h, owned["owned"], sf.docx(with_vba=True), "macro.docx")
    assert r.status_code == 415
    r = ds.upload(api, h, owned["owned"], b"", "empty.pdf")
    assert r.status_code == 400 and r.json()["detail"]["code"] == "bad_field"
    assert api.scanner.seen == []
    with world.Session() as s:
        rows = ds.audit_rows(s, "document.upload_rejected")
        assert [r.after["reason"] for r in rows] == ["type_not_allowed"] * 3
        assert rows[0].after["detected"] == "pdf" and rows[0].after["extension"] == "docx"
        assert s.scalar(sa.select(sa.func.count()).select_from(Document)) == 0


# ------------------------------------------------------------------------------------------------ who


def test_upload_needs_a_working_relation_not_sight(api, world, owned):
    h = ds.login(api, "edu_admin")
    for key in ("pool", "recommended"):
        r = ds.upload(api, h, owned[key], sf.text_pdf([key]))
        assert r.status_code == 403, r.text
        assert r.json()["detail"]["code"] == "not_working_on_case"
        assert key in r.json()["detail"]["access_basis"]
    assert ds.upload(api, ds.login(api, "edu_auditor"), owned["owned"], sf.text_pdf(["a"])).status_code == 403
    r = ds.upload(api, ds.login(api, "health_off"), owned["owned"], sf.text_pdf(["h"]))
    assert r.status_code == 404 and r.json()["detail"]["code"] == "not_found"
    assert ds.upload(api, h, uuid.uuid4(), sf.text_pdf(["n"])).status_code == 404
    assert ds.upload(api, {}, owned["owned"], sf.text_pdf(["n"])).status_code == 401
    with world.Session() as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(Document)) == 0


def test_standing_counsel_uploads_to_a_case_carrying_the_code(api, world):
    with world.Session() as s:
        s.add(CounselCode(code="SC, EDU", office_id=world.office(s, "EDU-SC").id))
        s.flush()
        case = make_case(s, case_no="WP(C)/200/2025")
        entry_with_codes(s, case, ["SC, EDU"])
        s.commit()
        case_id = case.id
    r = ds.upload(
        api,
        ds.login(api, "edu_counsel"),
        case_id,
        sf.text_pdf(["Written submission"]),
        "ws.pdf",
        doc_type="written_submission",
        visibility="counsel_shared",
    )
    assert r.status_code == 201, r.text
    assert r.json()["ref_no"].startswith("ASLMS/EDU-SC/DOC/")


# ------------------------------------------------------------------------------------------------ duplicates


def test_duplicate_rule_per_case_and_office(api, world, owned):
    h = ds.login(api, "edu_admin")
    pdf = sf.text_pdf(["same bytes"])
    first = ds.upload(api, h, owned["owned"], pdf)
    assert first.status_code == 201
    again = ds.upload(api, h, owned["owned"], pdf, "renamed.pdf", description="again")
    assert again.status_code == 409 and again.json()["detail"]["code"] == "duplicate"
    assert again.json()["detail"]["existing_ref_no"] == first.json()["ref_no"]
    by_dse = ds.upload(api, ds.login(api, "dse_user"), owned["owned"], pdf)
    assert by_dse.status_code == 201 and by_dse.json()["ref_no"] != first.json()["ref_no"]
    with world.Session() as s:
        other = make_case(s, case_no="WP(C)/103/2025")
        actor, admin = world.actor(s, "edu_admin")
        own.claim(s, actor, admin, other)
        s.commit()
        other_id = other.id
    elsewhere = ds.upload(api, h, other_id, pdf)
    assert elsewhere.status_code == 201
    with world.Session() as s:
        rows = s.scalars(sa.select(Document).where(Document.sha256 == ds.sha(pdf))).all()
        assert len(rows) == 3 and len({r.storage_key for r in rows}) == 1
    files = [p for p in api.store.root.rglob("*") if p.is_file()]
    assert len(files) == 1
    archived = api.post(f"/documents/{first.json()['id']}/archive", headers=h, json={"reason": "wrong file"})
    assert archived.status_code == 200
    assert ds.upload(api, h, owned["owned"], pdf).status_code == 201


# ------------------------------------------------------------------------------------------------ fields


@pytest.mark.parametrize(
    "kwargs, fragment",
    [
        ({"doc_type": "order"}, "cannot be uploaded"),
        ({"doc_type": "causelist"}, "cannot be uploaded"),
        ({"doc_type": "nonsense"}, "unknown doc_type"),
        ({"doc_type": "other"}, "doc_group is required"),
        ({"doc_type": "other", "doc_group": "court_record"}, "reserved"),
        ({"doc_type": "petition", "doc_group": "court_filing"}, "set by doc_type"),
        ({"doc_date": (date.today() + timedelta(days=1)).isoformat()}, "future"),
        ({"doc_date": "1949-12-31"}, "before"),
        ({"description": "ab"}, "description"),
        ({"description": "x" * 501}, "description"),
        ({"visibility": "everyone"}, "visibility"),
    ],
)
def test_field_rules(api, world, owned, kwargs, fragment):
    r = ds.upload(api, ds.login(api, "edu_admin"), owned["owned"], sf.text_pdf(["f"]), **kwargs)
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["code"] == "bad_field" and fragment in r.json()["detail"]["message"]
    assert api.scanner.seen == []


def test_other_with_a_chosen_group_and_missing_fields(api, world, owned):
    h = ds.login(api, "edu_admin")
    r = ds.upload(api, h, owned["owned"], sf.text_pdf(["o"]), doc_type="other", doc_group="internal")
    assert r.status_code == 201 and r.json()["doc_group"] == "internal"
    assert r.json()["sourcetrace_status"] == "not_applicable"
    r = api.post(f"/cases/{owned['owned']}/documents", headers=h, files={"file": ("x.pdf", sf.text_pdf())})
    assert r.status_code == 422  # the multipart fields are required
    types = api.get("/documents/types", headers=h).json()["items"]
    codes = {t["code"]: t for t in types}
    assert {"causelist", "order", "judgment"}.isdisjoint(codes)
    assert codes["other"]["group_choosable"] is True and codes["petition"]["group_choosable"] is False
    assert (
        codes["reply"]["doc_group"] == "court_filing"
        and codes["instructions_to_counsel"]["doc_group"] == "internal"
    )
    assert codes["counter_affidavit"]["label"] == "Affidavit-in-opposition (counter affidavit)"


# ------------------------------------------------------------------------------------------------ decision 8


class _Court:
    def __init__(self, pdf: bytes):
        self.pdf = pdf

    async def show_order(self, cnr, order_no, order_date):
        return self.pdf


def test_an_order_pdf_never_points_at_an_upload(api, world, owned):
    pdf = sf.text_pdf(["The same bytes as a later order"])
    r = ds.upload(api, ds.login(api, "edu_admin"), owned["owned"], pdf, visibility="private_to_office")
    assert r.status_code == 201
    with world.Session() as s:
        case = s.get(Case, owned["owned"])
        order = ds.pending_order(s, case, order_no="1", order_date=date(2025, 1, 10))
        order.download_status = "pending"
        s.flush()
        ref = f"{case.cnr}|1|2025-01-10"
        result, failed = asyncio.run(fetch_order_pdf(s, _Court(pdf), api.store, ref))
        assert not failed and result["new"] is True
        s.commit()
        order = s.get(Order, order.id)
        doc = s.get(Document, order.document_id)
        assert doc.kind.value == "order" and doc.id != uuid.UUID(r.json()["id"])
        assert doc.sha256 == ds.sha(pdf) and doc.visibility.value == "case_scope"
        rows = s.scalars(sa.select(Document).where(Document.sha256 == ds.sha(pdf))).all()
        assert sorted(d.kind.value for d in rows) == ["order", "upload"]
        # a second fetch of the same bytes reuses the order document, not the upload
        result, failed = asyncio.run(fetch_order_pdf(s, _Court(pdf), api.store, ref))
        assert result["already"] is True
        assert s.scalar(sa.select(sa.func.count()).select_from(DocumentText)) == 0


# ------------------------------------------------------------------------------------------------ migration 0006


def test_migration_0006_cycles_with_documents_and_refuses_duplicate_sha(api, world, owned):
    """Upgrade → downgrade → upgrade on a database holding an order PDF, a cause-list PDF and an upload (all
    distinct bytes), data intact; with two rows sharing a sha256 the downgrade stops without deleting."""
    from alembic import command

    from aslms.services.causelists import store_pdf
    from tests.db.conftest import TEST_URL, alembic_config

    pdf = sf.text_pdf(["An upload whose bytes nothing else shares"])
    r = ds.upload(api, ds.login(api, "edu_admin"), owned["owned"], pdf)
    assert r.status_code == 201
    with world.Session() as s:
        case = s.get(Case, owned["owned"])
        ds.stored_order(s, api.store, case, sf.text_pdf(["An order"]))
        store_pdf(s, api.store, sf.text_pdf(["A cause list"]), doc_date=date(2025, 1, 6), description="list")
        forget_devices(s)  # 0010's downgrade refuses while sign-in records exist
        s.commit()
    cfg = alembic_config(TEST_URL)
    command.downgrade(cfg, "0005")
    with world.Session() as s:
        assert s.execute(sa.text("select count(*) from documents")).scalar() == 3
        assert s.execute(sa.text("select version_num from alembic_version")).scalar() == "0005"
        assert (
            s.execute(
                sa.text("select count(*) from pg_indexes where indexname = 'ix_documents_system_sha'")
            ).scalar()
            == 0
        )
    command.upgrade(cfg, "head")
    from alembic.script import ScriptDirectory

    head = ScriptDirectory.from_config(cfg).get_current_head()
    with world.Session() as s:
        assert s.execute(sa.text("select version_num from alembic_version")).scalar() == head
        assert s.execute(sa.text("select count(*) from documents where archive_reason is null")).scalar() == 3
        assert (
            s.execute(
                sa.text("select count(*) from pg_constraint where conname like 'ck_documents_%'")
            ).scalar()
            == 5  # 0006's four, plus ck_documents_admin_file (0008, user-memberships)
        )
    # the same bytes uploaded by another office: two rows, one sha256 → the downgrade refuses
    assert ds.upload(api, ds.login(api, "dse_user"), owned["owned"], pdf).status_code == 201
    with world.Session() as s:
        forget_devices(s)
        s.commit()
    with pytest.raises(RuntimeError, match="cannot downgrade 0006"):
        command.downgrade(cfg, "0005")
    with world.Session() as s:
        assert s.execute(sa.text("select version_num from alembic_version")).scalar() == head
        assert s.execute(sa.text("select count(*) from documents")).scalar() == 4
