from __future__ import annotations

import pytest

from aslms.core.errors import ValidationError
from aslms.domain.documents import DocGroup, DocType, Visibility
from aslms.integration.antivirus import EICAR, NoScanner
from aslms.services.documents import UploadRequest, group_for, validate


def req(name: str, content: bytes, doc_type: DocType = DocType.WRIT_PETITION) -> UploadRequest:
    return UploadRequest(name, content, doc_type, None, None, Visibility.CASE_SCOPE)


def test_accepts_pdf_word_images() -> None:
    assert validate(req("petition.pdf", b"%PDF-1.7 ...")) == "application/pdf"
    assert validate(req("reply.docx", b"PK\x03\x04...")).endswith("wordprocessingml.document")
    assert validate(req("scan.png", b"\x89PNG....")) == "image/png"


def test_rejects_other_types_and_mismatched_content() -> None:
    with pytest.raises(ValidationError):
        validate(req("script.exe", b"MZ..."))
    with pytest.raises(ValidationError):
        validate(req("fake.pdf", b"MZ not a pdf"))
    with pytest.raises(ValidationError):
        validate(req("empty.pdf", b""))
    with pytest.raises(ValidationError):
        validate(req("order.pdf", b"%PDF", DocType.ORDER))  # court orders come from the court, not uploads


def test_groups() -> None:
    assert group_for(DocType.AFFIDAVIT_IN_OPPOSITION, None) == DocGroup.COURT_FILING
    assert group_for(DocType.PARAWISE_COMMENTS, None) == DocGroup.INTERNAL
    assert group_for(DocType.OTHER, None) == DocGroup.INTERNAL
    assert group_for(DocType.OTHER, False) == DocGroup.COURT_FILING


def test_no_scanner_still_catches_eicar() -> None:
    assert NoScanner().scan(b"%PDF " + EICAR)[0] == "infected"
    assert NoScanner().scan(b"%PDF clean")[0] == "failed"
