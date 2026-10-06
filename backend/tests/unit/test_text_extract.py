"""`text_extract.extract` over generated files (design documents-uploads, decision 10)."""

from __future__ import annotations

from aslms.domain.documents import TextStatus
from aslms.services import filetypes
from aslms.services.text_extract import extract
from tests import samplefiles as sf


def test_text_pdf_is_extracted_with_pages():
    out = extract(sf.text_pdf(["The writ petition is allowed.", "No costs."], pages=3), filetypes.PDF_MIME)
    assert out.status == TextStatus.EXTRACTED and out.page_count == 3
    assert "writ petition is allowed" in out.text and out.text.count("No costs") == 3


def test_image_only_pdf_has_no_text_but_keeps_the_page_count():
    out = extract(sf.image_pdf(pages=2), filetypes.PDF_MIME)
    assert out.status == TextStatus.NONE and out.page_count == 2


def test_docx_paragraphs_are_joined_by_new_lines():
    out = extract(sf.docx(["First paragraph.", "Second paragraph."]), filetypes.DOCX_MIME)
    assert out.status == TextStatus.EXTRACTED and out.page_count is None
    assert out.text == "First paragraph.\nSecond paragraph."


def test_docx_declaring_more_than_50mb_fails(monkeypatch):
    import zipfile

    big = sf.docx(["x"])
    real = zipfile.ZipFile.getinfo

    def lying(self, name):
        info = real(self, name)
        info.file_size = 51 * 1024 * 1024
        return info

    monkeypatch.setattr(zipfile.ZipFile, "getinfo", lying)
    out = extract(big, filetypes.DOCX_MIME)
    assert out.status == TextStatus.FAILED and "50 MB" in out.error


def test_images_and_doc_get_none():
    for data, mime in (
        (sf.png(), filetypes.PNG_MIME),
        (sf.jpeg(), filetypes.JPEG_MIME),
        (sf.doc(), filetypes.DOC_MIME),
    ):
        out = extract(data, mime)
        assert out.status == TextStatus.NONE and out.text is None and out.page_count is None


def test_corrupt_pdf_and_corrupt_docx_fail_without_raising():
    out = extract(b"%PDF-1.4 garbage", filetypes.PDF_MIME)
    assert out.status == TextStatus.FAILED and out.error
    out = extract(b"PK\x03\x04 not a zip", filetypes.DOCX_MIME)
    assert out.status == TextStatus.FAILED and out.error
