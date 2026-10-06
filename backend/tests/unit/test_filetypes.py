"""Permitted types decided by content (design documents-uploads, decision 3) and the file-name sanitiser."""

from __future__ import annotations

import pytest

from aslms.services import filetypes
from aslms.services.filetypes import EmptyFile, TypeNotAllowed, detect, safe_filename
from tests import samplefiles as sf


@pytest.mark.parametrize(
    "data, name, mime, ext, extractable",
    [
        (sf.text_pdf(), "petition.pdf", filetypes.PDF_MIME, "pdf", True),
        (sf.text_pdf(), "PETITION.PDF", filetypes.PDF_MIME, "pdf", True),
        (sf.docx(), "comments.docx", filetypes.DOCX_MIME, "docx", True),
        (sf.doc(), "old.DOC", filetypes.DOC_MIME, "doc", False),
        (sf.jpeg(), "scan.jpg", filetypes.JPEG_MIME, "jpg", False),
        (sf.jpeg(), "scan.jpeg", filetypes.JPEG_MIME, "jpg", False),
        (sf.png(), "scan.png", filetypes.PNG_MIME, "png", False),
    ],
)
def test_detects_permitted_types_from_bytes(data, name, mime, ext, extractable):
    ft = detect(data, name)
    assert (ft.mime, ft.ext, ft.extractable) == (mime, ext, extractable)


def test_pdf_signature_may_sit_after_a_small_preamble():
    assert detect(b"\n" * 100 + sf.text_pdf(), "x.pdf").mime == filetypes.PDF_MIME
    with pytest.raises(TypeNotAllowed) as exc:
        detect(b"\n" * 2000 + sf.text_pdf(), "x.pdf")
    assert exc.value.reason == "unknown_type"


@pytest.mark.parametrize(
    "data, name, reason, detected",
    [
        (sf.text_pdf(), "petition.docx", "extension_mismatch", "pdf"),
        (sf.html(), "page.pdf", "unknown_type", None),
        (sf.plain_zip(), "archive.docx", "not_word", "zip"),
        (sf.docx(with_vba=True), "macro.docx", "macro_enabled", "docx"),
        (sf.docx(), "macro.docm", "extension_mismatch", "docx"),
        (sf.exe(), "setup.exe", "unknown_type", None),
        (sf.exe(), "setup.pdf", "unknown_type", None),
        (sf.png(), "scan.jpg", "extension_mismatch", "png"),
        (sf.text_pdf(), "noextension", "extension_mismatch", "pdf"),
    ],
)
def test_refuses_mismatches_macros_and_unknown_types(data, name, reason, detected):
    with pytest.raises(TypeNotAllowed) as exc:
        detect(data, name)
    assert exc.value.reason == reason and exc.value.detected == detected


def test_empty_file_is_refused_separately():
    with pytest.raises(EmptyFile):
        detect(b"", "x.pdf")


def test_safe_filename_strips_directories_controls_and_length():
    assert safe_filename(r"..\..\x.pdf") == "x.pdf"
    assert safe_filename("/etc/x.pdf") == "x.pdf"
    assert safe_filename("C:\\Users\\me\\Desktop\\reply.docx") == "reply.docx"
    assert safe_filename("re\x00ply\x1f\x7f.pdf ") == "reply.pdf"
    assert safe_filename("") == "file" and safe_filename(None) == "file" and safe_filename("...") == "file"
    long = "a" * 300 + ".pdf"
    out = safe_filename(long)
    assert len(out) == 200 and out.endswith(".pdf")
    assert len(safe_filename("b" * 300)) == 200
