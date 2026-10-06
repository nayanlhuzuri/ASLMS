"""Document storage: content-addressed files under `STORAGE_DIR` (`<sha256[:2]>/<sha256>.<ext>`), the only way
code reads or writes stored files (so the store can move to a volume or an object store by configuration)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from aslms.core.config import get_settings

EXT_FOR_MIME = {
    "application/pdf": "pdf",
    "image/png": "png",
    "image/jpeg": "jpg",
    "text/plain": "txt",
    "application/msword": "doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
}


@dataclass(frozen=True)
class StoredFile:
    sha256: str
    key: str
    size: int
    existed: bool


class LocalStore:
    def __init__(self, root: str | Path | None = None):
        self.root = Path(root or get_settings().storage_dir)

    def put(self, data: bytes, mime: str = "application/pdf") -> StoredFile:
        sha = hashlib.sha256(data).hexdigest()
        ext = EXT_FOR_MIME.get(mime, "bin")
        key = f"{sha[:2]}/{sha}.{ext}"
        path = self.root / key
        existed = path.exists()
        if not existed:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".part")
            tmp.write_bytes(data)
            tmp.replace(path)
        return StoredFile(sha, key, len(data), existed)

    def path(self, key: str) -> Path:
        return self.root / key

    def get(self, key: str) -> bytes:
        return self.path(key).read_bytes()
