"""Server file storage, content-addressed by sha256 (plan §2.2: files on disk, a link to each in the database).
Layout: <STORAGE_ROOT>/<kind>/<yyyy>/<sha[:2]>/<sha><ext>. Writing the same bytes twice is a no-op."""

from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from aslms.core.config import get_settings
from aslms.core.time import now_utc
from aslms.domain.documents import (
    DocGroup,
    DocType,
    Document,
    DocumentKind,
    SourceTraceStatus,
    TextStatus,
    VirusScanStatus,
    Visibility,
)

EXT_BY_MIME = {
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/tiff": ".tif",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def root() -> Path:
    r = Path(get_settings().storage_root)
    r.mkdir(parents=True, exist_ok=True)
    return r


def write_blob(data: bytes, kind: str, mime: str) -> tuple[str, str]:
    """Returns (sha256, storage_key). The key is relative to STORAGE_ROOT."""
    sha = sha256_bytes(data)
    ext = EXT_BY_MIME.get(mime) or mimetypes.guess_extension(mime) or ".bin"
    key = f"{kind}/{now_utc():%Y}/{sha[:2]}/{sha}{ext}"
    path = root() / key
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".part")
        tmp.write_bytes(data)
        tmp.replace(path)
    return sha, key


def read_blob(storage_key: str) -> bytes:
    path = (root() / storage_key).resolve()
    if root().resolve() not in path.parents:
        raise ValueError("storage key escapes the storage root")
    return path.read_bytes()


def blob_path(storage_key: str) -> Path:
    path = (root() / storage_key).resolve()
    if root().resolve() not in path.parents:
        raise ValueError("storage key escapes the storage root")
    return path


def store_system_document(
    session: Session,
    data: bytes,
    *,
    kind: DocumentKind,
    doc_type: DocType,
    mime: str = "application/pdf",
    filename: str | None = None,
    case_id=None,
    doc_date=None,
    description: str | None = None,
) -> tuple[Document, bool]:
    """Stores a document collected by the system (court order, cause-list PDF). Deduplicates on sha256.
    Returns (document, created). Court records are not virus-scanned (they come from the court gateway)
    and become SourceTrace candidates in Phase 2."""
    sha = sha256_bytes(data)
    existing = session.scalar(select(Document).where(Document.sha256 == sha))
    if existing:
        return existing, False
    sha, key = write_blob(data, kind.value, mime)
    doc = Document(
        sha256=sha,
        storage_key=key,
        mime=mime,
        size_bytes=len(data),
        original_filename=filename,
        kind=kind,
        doc_type=doc_type,
        doc_group=DocGroup.COURT_RECORD,
        case_id=case_id,
        doc_date=doc_date,
        description=description,
        visibility=Visibility.CASE_SCOPE,
        virus_scan_status=VirusScanStatus.NOT_APPLICABLE,
        text_status=TextStatus.PENDING if mime == "application/pdf" else TextStatus.NOT_APPLICABLE,
        sourcetrace_status=SourceTraceStatus.NOT_APPLICABLE,
    )
    session.add(doc)
    session.flush()
    return doc, True
