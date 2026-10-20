"""The document-store check run by the Compose `init` service (design pre-pilot-hardening, decision 3).

`init` runs `aslms ops store-check` right after preflight. It works on `STORAGE_DIR` (`/data/store` in Compose), the
only folder the application writes: every write goes through `LocalStore.put` into `<sha[:2]>/`. A missing store is
created; then a real write probe (create and remove `.aslms-write-check-<random>`) runs in the store root and in every
first-level folder (at most 256). An `os.access` answer is not trusted (Docker Desktop bind mounts). Files are never
touched: they are written once through a temporary name and a rename, so only folder write access matters. Symbolic
links are skipped, never followed. A failure stops the start at every `APP_ENV`, with the two remedies of the runbook
(`docs/operations.md` section 6)."""

from __future__ import annotations

import errno
import os
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

PROBE_PREFIX = ".aslms-write-check-"
APP_UID = 10001


@dataclass
class StoreCheck:
    root: str
    folders_checked: int = 0
    failed: list[str] = field(default_factory=list)
    created: bool = False

    @property
    def ok(self) -> bool:
        return not self.failed


def write_probe(folder: Path) -> None:
    """Creates and removes one probe file in `folder`; raises `OSError` (usually `PermissionError`) when it cannot."""
    path = Path(folder) / f"{PROBE_PREFIX}{secrets.token_hex(8)}"
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(fd, b"ok")
    finally:
        os.close(fd)
    os.remove(path)


def _probe_ok(folder: Path, probe: Callable[[Path], None]) -> bool:
    try:
        probe(folder)
    except OSError as exc:
        if isinstance(exc, PermissionError) or exc.errno in (errno.EACCES, errno.EPERM, errno.EROFS):
            return False
        raise
    return True


def check(root: str | Path, *, probe: Callable[[Path], None] = write_probe) -> StoreCheck:
    """Creates the store when missing, then probes the root and each first-level folder (sorted)."""
    store = Path(root)
    result = StoreCheck(root=str(store))
    existed = store.is_dir()
    try:
        store.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        result.failed.append(str(store))
        return result
    result.created = not existed
    if not _probe_ok(store, probe):
        result.failed.append(str(store))
    try:
        folders = sorted(p for p in store.iterdir() if not p.is_symlink() and p.is_dir())
    except PermissionError:
        if str(store) not in result.failed:
            result.failed.append(str(store))
        return result
    for folder in folders:
        result.folders_checked += 1
        if not _probe_ok(folder, probe):
            result.failed.append(str(folder))
    return result


def remedy_lines() -> list[str]:
    """The two remedies and the runbook pointer: one source for the CLI and the tests."""
    return [
        f"On a Linux host, give the store to the application's user (uid {APP_UID}):",
        f"  sudo chown -R {APP_UID}:{APP_UID} ./data/store",
        "On Docker Desktop for Windows, where chown is refused on bind mounts:",
        '  docker compose run --rm --no-deps -u root --entrypoint sh worker -c "chmod -R a+rwX /data/store"',
        "Then start again. See docs/operations.md section 6.",
    ]
