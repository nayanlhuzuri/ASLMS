"""Permitted upload types, decided by the file's bytes (design `documents-uploads`, decision 3). The first
bytes decide the type, the file name's extension must agree, the declared `Content-Type` is never consulted.
PDF, Word (`.docx` without macros, `.doc`), JPEG and PNG; anything else, a mismatch or a macro-enabled Word
file is refused. Pure functions, no I/O."""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass

PDF_MIME = "application/pdf"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
DOC_MIME = "application/msword"
JPEG_MIME = "image/jpeg"
PNG_MIME = "image/png"

OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff"
ZIP_MAGIC = b"PK\x03\x04"
PDF_WINDOW = 1024

MAX_FILENAME = 200
INLINE_MIMES = frozenset({PDF_MIME, JPEG_MIME, PNG_MIME})


@dataclass(frozen=True)
class FileType:
    mime: str
    ext: str  # the canonical extension (pdf, docx, doc, jpg, png)
    extractable: bool  # text can be extracted without OCR (PDF, DOCX)
    allowed_extensions: tuple[str, ...]


PDF = FileType(PDF_MIME, "pdf", True, ("pdf",))
DOCX = FileType(DOCX_MIME, "docx", True, ("docx",))
DOC = FileType(DOC_MIME, "doc", False, ("doc",))
JPEG = FileType(JPEG_MIME, "jpg", False, ("jpg", "jpeg"))
PNG = FileType(PNG_MIME, "png", False, ("png",))


class EmptyFile(ValueError):
    """No bytes at all (HTTP 400)."""


class TypeNotAllowed(ValueError):
    """`reason`: `unknown_type`, `extension_mismatch`, `macro_enabled`, `not_word`; `detected`: what the bytes
    look like (`pdf`, `docx`, `doc`, `jpg`, `png`, `zip` or None)."""

    def __init__(self, reason: str, detected: str | None, extension: str | None = None):
        super().__init__(f"{reason} (detected={detected}, extension={extension})")
        self.reason = reason
        self.detected = detected
        self.extension = extension


def extension_of(filename: str) -> str | None:
    name = safe_filename(filename)
    if "." not in name:
        return None
    return name.rsplit(".", 1)[1].lower() or None


def _zip_kind(data: bytes) -> str:
    """`docx`, `macro` (a Word file carrying VBA) or `zip` (some other archive)."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = set(zf.namelist())
    except (zipfile.BadZipFile, OSError, ValueError):
        return "zip"
    if "word/vbaProject.bin" in names:
        return "macro"
    if "word/document.xml" in names and "[Content_Types].xml" in names:
        return "docx"
    return "zip"


def sniff(data: bytes) -> str | None:
    """What the bytes look like, or None."""
    if data.startswith(PNG_MAGIC):
        return "png"
    if data.startswith(JPEG_MAGIC):
        return "jpg"
    if data.startswith(OLE2_MAGIC):
        return "doc"
    if b"%PDF-" in data[:PDF_WINDOW]:
        return "pdf"
    if data.startswith(ZIP_MAGIC):
        return _zip_kind(data)
    return None


def detect(data: bytes, filename: str) -> FileType:
    """The permitted type of `data` named `filename`; raises `EmptyFile` or `TypeNotAllowed`."""
    if not data:
        raise EmptyFile("empty file")
    ext = extension_of(filename)
    kind = sniff(data)
    if kind == "macro":
        raise TypeNotAllowed("macro_enabled", "docx", ext)
    if kind == "zip":
        raise TypeNotAllowed("not_word", "zip", ext)
    ftype = {"pdf": PDF, "docx": DOCX, "doc": DOC, "jpg": JPEG, "png": PNG}.get(kind or "")
    if ftype is None:
        raise TypeNotAllowed("unknown_type", None, ext)
    if ext not in ftype.allowed_extensions:
        raise TypeNotAllowed("extension_mismatch", kind, ext)
    return ftype


_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def safe_filename(name: str | None) -> str:
    """The base name without directories or control characters, trimmed, at most 200 characters."""
    s = (name or "").replace("\\", "/").rsplit("/", 1)[-1]
    s = _CONTROL.sub("", s).strip().strip(".")
    if len(s) > MAX_FILENAME:
        stem, dot, ext = s.rpartition(".")
        if dot and 0 < len(ext) <= 10:
            s = stem[: MAX_FILENAME - len(ext) - 1] + "." + ext
        else:
            s = s[:MAX_FILENAME]
    return s or "file"
