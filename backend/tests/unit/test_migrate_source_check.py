"""`migrate` refuses an image built from other code than ./backend (design `followups-oct`, decision 26): identical
trees pass; a migration only in the source, or a changed package file, stops with exit 5 naming both newest
migrations; a missing source tree continues with the note; `__pycache__` and `*.pyc` are ignored."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from aslms.cli.main import app
from aslms.services import source_check


def _tree(root: Path, heads=("0021", "0022")) -> Path:
    (root / "aslms" / "services").mkdir(parents=True)
    (root / "aslms" / "__init__.py").write_text("")
    (root / "aslms" / "services" / "ops.py").write_text("X = 1\n")
    versions = root / "migrations" / "versions"
    versions.mkdir(parents=True)
    (root / "migrations" / "env.py").write_text("# env\n")
    for head in heads:
        (versions / f"{head}_step.py").write_text(f"revision = '{head}'\n")
    return root


def test_identical_trees_pass(tmp_path):
    image, src = _tree(tmp_path / "app"), _tree(tmp_path / "src")
    check = source_check.image_matches_source(image, src)
    assert check.ok and "0022" in check.message


def test_a_migration_only_in_the_source_is_exit_5_with_both_heads(tmp_path):
    image, src = _tree(tmp_path / "app"), _tree(tmp_path / "src", heads=("0021", "0022", "0023"))
    check = source_check.image_matches_source(image, src)
    assert not check.ok
    assert "image migrations up to 0022, ./backend up to 0023" in check.message
    assert "migrations differ" in check.message and "aslms package" not in check.message
    assert "docker compose --profile ops build migrate" in check.message


def test_a_changed_package_file_is_exit_5(tmp_path):
    image, src = _tree(tmp_path / "app"), _tree(tmp_path / "src")
    (src / "aslms" / "services" / "ops.py").write_text("X = 1  # a comment\n")
    check = source_check.image_matches_source(image, src)
    assert not check.ok and "aslms package differs" in check.message
    assert "image migrations up to 0022, ./backend up to 0022" in check.message


def test_a_missing_source_continues_with_the_note(tmp_path):
    image = _tree(tmp_path / "app")
    for src in (tmp_path / "absent", tmp_path / "empty"):
        if src.name == "empty":
            src.mkdir()
        check = source_check.image_matches_source(image, src)
        assert check.ok
        assert check.message == "migrate: no source tree to compare; this image's newest migration is 0022"


def test_pycache_is_ignored(tmp_path):
    image, src = _tree(tmp_path / "app"), _tree(tmp_path / "src")
    cache = src / "aslms" / "services" / "__pycache__"
    cache.mkdir()
    (cache / "ops.cpython-312.pyc").write_bytes(b"\x00compiled")
    (src / "migrations" / "stray.pyc").write_bytes(b"\x00")
    assert source_check.image_matches_source(image, src).ok


def test_the_command_exits_5_before_any_backup(tmp_path, monkeypatch):
    from aslms.services import backups, db_guard

    image, src = _tree(tmp_path / "app"), _tree(tmp_path / "src", heads=("0021", "0022", "0023"))
    monkeypatch.setattr(source_check, "image_root", lambda: image)
    monkeypatch.setattr(source_check, "SOURCE_ROOT", src)

    def never(*args, **kwargs):
        pytest.fail("no connection check and no backup before the source check")

    monkeypatch.setattr(db_guard, "count_app_sessions", never)
    monkeypatch.setattr(backups, "run_backup", never)
    result = CliRunner().invoke(app, ["ops", "migrate"])
    assert result.exit_code == 5, result.output
    assert "./backend up to 0023" in result.output
