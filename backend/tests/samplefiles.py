"""Generated sample files for the document tests: a text PDF, an image-only PDF, a DOCX, a DOCX carrying
VBA, a DOC, a JPEG and a PNG — built at run time so no binary fixture is checked in."""

from __future__ import annotations

import io
import zipfile

from aslms.services.filetypes import OLE2_MAGIC

CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.'
    'wordprocessingml.document.main+xml"/></Types>'
)


def text_pdf(lines: list[str] | None = None, pages: int = 1) -> bytes:
    import pymupdf

    lines = lines or ["The writ petition is allowed.", "Costs are not awarded."]
    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page()
        y = 72
        for line in lines:
            page.insert_text((72, y), line, fontsize=11)
            y += 16
    return doc.tobytes()


def png(width: int = 8, height: int = 8) -> bytes:
    import pymupdf

    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, width, height), 0)
    pix.clear_with(200)
    return pix.tobytes("png")


def jpeg(width: int = 8, height: int = 8) -> bytes:
    import pymupdf

    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, width, height), 0)
    pix.clear_with(120)
    return pix.tobytes("jpeg")


def image_pdf(pages: int = 1) -> bytes:
    import pymupdf

    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page()
        page.insert_image(pymupdf.Rect(72, 72, 272, 272), stream=png(64, 64))
    return doc.tobytes()


def docx(paragraphs: list[str] | None = None, *, with_vba: bool = False, document_xml: bytes | None = None):
    paragraphs = paragraphs or ["Parawise comments of the department.", "Paragraph two."]
    if document_xml is None:
        body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
        document_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f"<w:body>{body}</w:body></w:document>"
        ).encode()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", CONTENT_TYPES)
        zf.writestr("word/document.xml", document_xml)
        if with_vba:
            zf.writestr("word/vbaProject.bin", b"\x00" * 16)
    return buf.getvalue()


def plain_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("readme.txt", "not a word file")
    return buf.getvalue()


def doc() -> bytes:
    return OLE2_MAGIC + b"\x00" * 504


def exe() -> bytes:
    return b"MZ\x90\x00" + b"\x00" * 60


def html() -> bytes:
    return b"<!DOCTYPE html><html><body>hello</body></html>"
