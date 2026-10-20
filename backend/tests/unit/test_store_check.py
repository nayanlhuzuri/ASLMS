"""Design pre-pilot-hardening, decision 3: `aslms ops store-check` (run by `init` after preflight) proves that the
document store and each first-level folder are writable by this process, creates a missing store and names the two
remedies on failure."""

from __future__ import annotations

import functools
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from aslms.cli.main import app
from aslms.services import store_check


def _store(tmp_path: Path, folders=("ab", "cd", "ef")) -> Path:
    root = tmp_path / "store"
    for name in folders:
        (root / name).mkdir(parents=True)
    (root / "ab" / ("a" * 64 + ".pdf")).write_bytes(b"%PDF-1.4")
    return root


def _leftovers(root: Path) -> list[Path]:
    return [p for p in root.rglob(f"{store_check.PROBE_PREFIX}*")]


def test_writable_store_passes_and_counts_folders(tmp_path):
    root = _store(tmp_path)
    result = store_check.check(root)
    assert result.ok and result.failed == []
    assert result.folders_checked == 3
    assert result.created is False
    assert result.root == str(root)
    assert _leftovers(root) == [], "the probe files are removed"
    assert (root / "ab" / ("a" * 64 + ".pdf")).read_bytes() == b"%PDF-1.4", "files are never touched"


def test_missing_store_is_created(tmp_path):
    root = tmp_path / "data" / "store"
    result = store_check.check(root)
    assert result.ok and result.created
    assert root.is_dir() and result.folders_checked == 0


def test_unwritable_folders_are_reported(tmp_path):
    root = _store(tmp_path)
    seen: list[str] = []

    def probe(folder: Path) -> None:
        seen.append(folder.name)
        if folder.name in {"ab", "ef"}:
            raise PermissionError(13, "Permission denied")

    result = store_check.check(root, probe=probe)
    assert not result.ok
    assert result.failed == [str(root / "ab"), str(root / "ef")]
    assert result.folders_checked == 3
    assert seen == ["store", "ab", "cd", "ef"], "the root first, then the folders in order"


def test_other_os_errors_are_not_hidden(tmp_path):
    root = _store(tmp_path)

    def probe(folder: Path) -> None:
        raise OSError(28, "No space left on device")

    with pytest.raises(OSError):
        store_check.check(root, probe=probe)


def test_unwritable_root_is_reported_when_mkdir_fails(tmp_path, monkeypatch):
    root = tmp_path / "store"

    def refuse(self, *args, **kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(Path, "mkdir", refuse)
    result = store_check.check(root)
    assert not result.ok
    assert result.failed == [str(root)]
    assert result.folders_checked == 0


def test_symlinks_are_not_followed(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    root = _store(tmp_path, folders=("ab",))
    try:
        (root / "zz").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are not available here")
    seen: list[str] = []
    result = store_check.check(root, probe=lambda folder: seen.append(folder.name))
    assert result.ok and result.folders_checked == 1
    assert "zz" not in seen


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root writes anywhere")
def test_real_permission_denied_on_posix(tmp_path):
    root = _store(tmp_path)
    locked = root / "cd"
    locked.chmod(0o555)
    try:
        result = store_check.check(root)
    finally:
        locked.chmod(0o755)
    assert result.failed == [str(locked)]


def _invoke(monkeypatch, root: Path, probe=None):
    monkeypatch.setattr("aslms.cli.ops.get_settings", lambda: SimpleNamespace(storage_dir=str(root)))
    if probe is not None:
        monkeypatch.setattr(store_check, "check", functools.partial(store_check.check, probe=probe))
    return CliRunner().invoke(app, ["ops", "store-check"])


def test_cli_store_check_exits_1_with_both_remedies(tmp_path, monkeypatch):
    root = _store(tmp_path)

    def probe(folder: Path) -> None:
        if folder.name in {"cd", "ef"}:
            raise PermissionError(13, "Permission denied")

    res = _invoke(monkeypatch, root, probe)
    assert res.exit_code == 1
    assert "2 folder(s)" in res.output
    assert "cd" in res.output
    assert "sudo chown -R 10001:10001 ./data/store" in res.output
    assert 'chmod -R a+rwX /data/store"' in res.output
    assert "docs/operations.md section 6" in res.output
    assert store_check.remedy_lines()[1].strip() in res.output


def test_cli_store_check_passes_on_a_writable_store(tmp_path, monkeypatch):
    root = _store(tmp_path)
    res = _invoke(monkeypatch, root)
    assert res.exit_code == 0, res.output
    assert "writable (3 folders)" in res.output
    assert "chown" not in res.output
