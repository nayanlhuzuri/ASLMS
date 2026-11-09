"""Design dependency-locks, decisions 7 and 8: `backend/tools/deps.py` builds its uv and pip command lines with pure
functions, so they are tested here without the network or a real uv."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest
from packaging.markers import Marker

BACKEND = Path(__file__).resolve().parents[2]
PY = sys.executable
EXPORT_FLAGS = [
    "--frozen",
    "--format",
    "requirements.txt",
    "--no-emit-project",
    "--no-header",
    "--no-default-groups",
]
BODY = b"kombu==5.6.2 ; sys_platform == 'linux' \\\r\n    --hash=sha256:" + b"a" * 64 + b"\r\n"


@pytest.fixture(scope="module")
def deps():
    spec = importlib.util.spec_from_file_location("aslms_tools_deps", BACKEND / "tools" / "deps.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


class FakeRunner:
    def __init__(self, fail: tuple[str, ...] = (), body: bytes = BODY):
        self.calls: list[list[str]] = []
        self.fail, self.body = fail, body

    def __call__(self, cmd, capture=False):
        self.calls.append(list(cmd))
        code = 1 if any(word in cmd for word in self.fail) else 0
        return subprocess.CompletedProcess(cmd, code, self.body if capture else None, b"")


@pytest.mark.parametrize(
    "args,lock_flags",
    [
        ((False, []), []),
        ((True, []), ["--upgrade"]),
        ((False, ["kombu"]), ["--upgrade-package", "kombu"]),
    ],
    ids=["plain", "upgrade", "upgrade-package"],
)
def test_lock_command_builds_uv_lock_then_both_exports(deps, tmp_path, monkeypatch, args, lock_flags):
    monkeypatch.setattr(deps, "REQUIREMENTS", tmp_path / "requirements")
    run = FakeRunner()
    assert deps.cmd_lock(*args, run=run) == 0
    assert run.calls == [
        [PY, "-m", "uv", "lock", *lock_flags],
        [PY, "-m", "uv", "export", *EXPORT_FLAGS, "--extra", "redis", "--group", "build"],
        [PY, "-m", "uv", "export", *EXPORT_FLAGS, "--extra", "dev", "--extra", "redis", "--group", "build"],
    ]
    for name in ("image.txt", "dev.txt"):
        written = (tmp_path / "requirements" / name).read_bytes()
        assert written == deps.HEADER.encode() + BODY.replace(b"\r\n", b"\n")
    assert deps.export_path("image.txt") == tmp_path / "requirements" / "image.txt"


def test_a_failed_uv_lock_writes_no_export(deps, tmp_path, monkeypatch):
    monkeypatch.setattr(deps, "REQUIREMENTS", tmp_path / "requirements")
    run = FakeRunner(fail=("lock",))
    assert deps.cmd_lock(False, [], run=run) == 1
    assert len(run.calls) == 1 and not (tmp_path / "requirements").exists()


def test_check_names_the_stale_file_and_the_fix(deps, capsys):
    current = deps.HEADER.encode() + BODY.replace(b"\r\n", b"\n")

    # uv.lock no longer matches pyproject.toml
    run = FakeRunner(fail=("--locked",))
    assert deps.cmd_check(run=run, read=lambda p: current) == 1
    err = capsys.readouterr().err
    assert "backend/uv.lock" in err and "python tools/deps.py lock" in err
    assert run.calls == [[PY, "-m", "uv", "lock", "--locked"]]

    # one export differs from the lock
    def read(path: Path) -> bytes | None:
        return b"# edited by hand\n" if path.name == "image.txt" else current

    assert deps.cmd_check(run=FakeRunner(), read=read) == 1
    err = capsys.readouterr().err
    assert "backend/requirements/image.txt differs from uv.lock" in err and "python tools/deps.py lock" in err
    assert "dev.txt" not in err

    # a missing export is stale too
    assert deps.cmd_check(run=FakeRunner(), read=lambda p: None) == 1
    err = capsys.readouterr().err
    assert "image.txt" in err and "dev.txt" in err

    # everything current
    assert deps.cmd_check(run=FakeRunner(), read=lambda p: current) == 0


def test_sync_installs_hash_checked_then_the_project(deps):
    assert deps.sync_install_cmds() == [
        [
            PY,
            "-m",
            "pip",
            "install",
            "--require-hashes",
            "--only-binary",
            ":all:",
            "-r",
            "requirements/dev.txt",
        ],
        [PY, "-m", "pip", "install", "--no-deps", "--no-build-isolation", "-e", "."],
    ]


WINDOWS = {
    "sys_platform": "win32",
    "platform_system": "Windows",
    "os_name": "nt",
    "platform_machine": "AMD64",
    "python_version": "3.13",
    "python_full_version": "3.13.0",
    "implementation_name": "cpython",
    "platform_python_implementation": "CPython",
}

EXPORT = """# header
kombu==5.6.2 ; sys_platform == 'linux' or sys_platform == 'win32' \\
    --hash=sha256:aaaa
    # via aslms
colorama==0.4.6 ; sys_platform == 'win32' \\
    --hash=sha256:bbbb
uvloop==0.23.0 ; platform_python_implementation != 'PyPy' and sys_platform == 'linux' \\
    --hash=sha256:cccc
Typing_Extensions==4.16.0 \\
    --hash=sha256:dddd
"""


def test_sync_prunes_only_what_the_lock_does_not_name_for_this_platform(deps):
    pins = deps.parse_pins(EXPORT)
    assert [p.name for p in pins] == ["kombu", "colorama", "uvloop", "typing-extensions"]
    locked = deps.applicable(pins, lambda m: Marker(m).evaluate(WINDOWS))
    assert locked == {"kombu": "5.6.2", "colorama": "0.4.6", "typing-extensions": "4.16.0"}

    installed = {
        "kombu": "5.6.2",
        "colorama": "0.4.6",
        "typing-extensions": "4.16.0",
        "pip": "24.2",
        "aslms": "3.0.0a0",
        "wheel": "0.45.1",
    }
    diff = deps.compare(locked, installed)
    assert diff.missing == [] and diff.wrong == []  # uvloop is Linux only, so not missing on Windows
    assert diff.extra == ["wheel"]  # never pip or aslms
    assert deps.prune_cmd(["pip", "aslms", "wheel"]) == [PY, "-m", "pip", "uninstall", "-y", "wheel"]
    assert deps.prune_cmd(["pip", "aslms"]) is None

    diff = deps.compare(locked, {**installed, "kombu": "5.7.0"})
    assert "kombu installed 5.7.0, lock 5.6.2" in diff.wrong


def test_sync_check_reports_and_fails_on_a_difference(deps, monkeypatch, capsys):
    monkeypatch.setattr(deps, "installed_distributions", lambda: {"aslms": "3.0.0a0", "wheel": "0.45"})
    monkeypatch.setattr(deps, "broken_leftovers", lambda: [])
    assert deps.cmd_sync(check_only=True, run=FakeRunner()) == 1
    out = capsys.readouterr().out
    assert "missing  kombu==" in out and "extra    wheel" in out and "python tools/deps.py sync" in out
