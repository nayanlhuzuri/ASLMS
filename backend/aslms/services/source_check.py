"""`migrate` refuses an image built from other code than the code on disk (design `followups-oct`, decision 26; row 133:
on 22 Oct 2026 the upgrade ran an old `migrate` image).

An image cannot know that a newer one exists, and `api` is stopped while `migrate` runs, so the comparison is with the
source tree: Compose mounts `./backend` read-only into `migrate` at `/src`. `image_matches_source()` hashes the code
the image was built from (`/app/aslms` and `/app/migrations`, the trees the Dockerfile copied and pip installed) and
`/src/aslms` and `/src/migrations`: SHA-256 over the sorted relative paths and the file bytes, skipping `__pycache__`
and `*.pyc` as `backend/.dockerignore` does. A difference stops `aslms ops migrate` with exit 5 before any backup or
connection check. Without a source tree (a pilot loaded with `docker load`) it says so and lets the upgrade go on.
There is no override: an old image never has a reason to migrate. `aslms ops restore` is not gated."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import aslms

SOURCE_ROOT = Path("/src")
IMAGE_ROOT = Path("/app")
EXIT_MISMATCH = 5
REBUILD = (
    "Build it: `docker compose build && docker compose --profile ops build migrate`, then run migrate again."
)
_MIGRATION = re.compile(r"^(\d{4})_.+\.py$")


def _files(root: Path) -> list[Path]:
    return sorted(
        (p for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"),
        key=lambda p: p.relative_to(root).as_posix(),
    )


def tree_digest(root: Path) -> str | None:
    """SHA-256 over each file's relative path and bytes, in path order; None when the directory is missing."""
    if not root.is_dir():
        return None
    h = hashlib.sha256()
    for p in _files(root):
        h.update(p.relative_to(root).as_posix().encode())
        h.update(b"\0")
        h.update(p.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def newest_migration(root: Path) -> str | None:
    """The highest `NNNN` of `migrations/versions/NNNN_*.py` (or of `root` itself when it holds the files)."""
    versions = root / "versions" if (root / "versions").is_dir() else root
    if not versions.is_dir():
        return None
    found = [m[1] for p in versions.iterdir() if (m := _MIGRATION.match(p.name))]
    return max(found) if found else None


def image_root() -> Path:
    """The tree this image was built from: `/app` in the image; elsewhere the backend directory of the imported
    package (a host run, which has no `/src`)."""
    if (IMAGE_ROOT / "aslms").is_dir() and (IMAGE_ROOT / "migrations").is_dir():
        return IMAGE_ROOT
    return Path(aslms.__file__).resolve().parents[1]


@dataclass(frozen=True)
class SourceCheck:
    ok: bool
    message: str


def image_matches_source(image: Path | None = None, source: Path | None = None) -> SourceCheck:
    image = image or image_root()
    source = source or SOURCE_ROOT
    image_head = newest_migration(image / "migrations") or "none"
    src_pkg, src_mig = source / "aslms", source / "migrations"
    if not source.is_dir() or not src_pkg.is_dir() or not any(source.iterdir()):
        return SourceCheck(
            True, f"migrate: no source tree to compare; this image's newest migration is {image_head}"
        )
    differs = []
    if tree_digest(image / "aslms") != tree_digest(src_pkg):
        differs.append("aslms package differs")
    if tree_digest(image / "migrations") != tree_digest(src_mig):
        differs.append("migrations differ")
    if not differs:
        return SourceCheck(True, f"migrate: the image matches ./backend (migrations up to {image_head})")
    src_head = newest_migration(src_mig) or "none"
    return SourceCheck(
        False,
        "migrate: this image was built from other code than ./backend (image migrations up to "
        f"{image_head}, ./backend up to {src_head}; {', '.join(differs)}). {REBUILD}",
    )
