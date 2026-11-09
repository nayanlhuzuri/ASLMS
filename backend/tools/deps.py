"""The backend's dependency lock and the development environment (design `dependency-locks`, decisions 1, 7 and 8).

`backend/uv.lock` is the one lock, made by uv for Linux and Windows and every Python the project allows. It is exported,
never edited by hand, to two hashed requirement files that plain pip installs:

- `requirements/image.txt`: the runtime dependencies, the `redis` extra and the `build` group (the Dockerfile);
- `requirements/dev.txt`: the same plus the `dev` extra (CI and the development `.venv`).

Commands (run with the environment's own Python, from anywhere):

    python tools/deps.py lock                          after adding or changing a requirement in pyproject.toml
    python tools/deps.py lock --upgrade-package NAME   upgrade one package (repeatable)
    python tools/deps.py lock --upgrade                upgrade everything
    python tools/deps.py check                         the lock matches pyproject.toml and both exports match the lock
    python tools/deps.py sync [--check]                make this environment exactly dev.txt for its platform

uv runs as `python -m uv` (it is pinned in the `dev` extra); `sync` needs only pip. Standard library only; the
markers of `sync` are read with pip's own `packaging` when the installed one is absent. Nothing from the environment
is printed."""

from __future__ import annotations

import argparse
import importlib.metadata
import re
import site
import subprocess
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
LOCK = BACKEND / "uv.lock"
REQUIREMENTS = BACKEND / "requirements"
FIX = "python tools/deps.py lock"
SYNC = "python tools/deps.py sync"
PROJECT = "aslms"
NEVER_PRUNED = frozenset({"pip", PROJECT})

# the two exports: file name -> the extras and groups it holds
EXPORTS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "image.txt": (("redis",), ("build",)),
    "dev.txt": (("dev", "redis"), ("build",)),
}
HEADER = "# Generated from backend/uv.lock by `python tools/deps.py lock` (design dependency-locks). Do not edit by hand.\n"

Runner = Callable[..., subprocess.CompletedProcess]


def _run(cmd: Sequence[str], capture: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(list(cmd), cwd=BACKEND, capture_output=capture, check=False)


def uv(*args: str) -> list[str]:
    return [sys.executable, "-m", "uv", *args]


def pip(*args: str) -> list[str]:
    return [sys.executable, "-m", "pip", *args]


def uv_lock_cmd(
    upgrade: bool = False, upgrade_packages: Iterable[str] = (), locked: bool = False
) -> list[str]:
    cmd = uv("lock")
    if locked:
        return [*cmd, "--locked"]
    if upgrade:
        cmd.append("--upgrade")
    for name in upgrade_packages:
        cmd += ["--upgrade-package", name]
    return cmd


def uv_export_cmd(name: str) -> list[str]:
    extras, groups = EXPORTS[name]
    cmd = uv(
        "export",
        "--frozen",
        "--format",
        "requirements.txt",
        "--no-emit-project",
        "--no-header",
        "--no-default-groups",
    )
    for extra in extras:
        cmd += ["--extra", extra]
    for group in groups:
        cmd += ["--group", group]
    return cmd


def export_path(name: str) -> Path:
    return REQUIREMENTS / name


def export_text(name: str, run: Runner = _run) -> str:
    done = run(uv_export_cmd(name), capture=True)
    if done.returncode != 0:
        raise SystemExit(f"deps: `uv export` failed for requirements/{name} (exit {done.returncode})")
    body = done.stdout.decode("utf-8").replace("\r\n", "\n")
    return HEADER + body


def cmd_lock(upgrade: bool, upgrade_packages: Sequence[str], run: Runner = _run) -> int:
    done = run(uv_lock_cmd(upgrade, upgrade_packages))
    if done.returncode != 0:
        print(f"deps: `uv lock` failed (exit {done.returncode})", file=sys.stderr)
        return 1
    REQUIREMENTS.mkdir(exist_ok=True)
    for name in EXPORTS:
        export_path(name).write_bytes(export_text(name, run).encode("utf-8"))
        print(f"deps: wrote requirements/{name}")
    return 0


def stale_exports(run: Runner = _run, read: Callable[[Path], bytes | None] | None = None) -> list[str]:
    def _read(p: Path) -> bytes | None:
        return p.read_bytes() if p.is_file() else None

    read = read or _read
    return [name for name in EXPORTS if read(export_path(name)) != export_text(name, run).encode("utf-8")]


def cmd_check(run: Runner = _run, read: Callable[[Path], bytes | None] | None = None) -> int:
    if run(uv_lock_cmd(locked=True)).returncode != 0:
        print(f"deps: backend/uv.lock does not match pyproject.toml. Fix: {FIX}", file=sys.stderr)
        return 1
    stale = stale_exports(run, read)
    for name in stale:
        print(f"deps: backend/requirements/{name} differs from uv.lock. Fix: {FIX}", file=sys.stderr)
    if stale:
        return 1
    print("deps: uv.lock matches pyproject.toml and both exports match the lock")
    return 0


# --- sync -------------------------------------------------------------------------------------------------------------

_REQ = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;\\]+)\s*(?:;\s*([^\\]+?))?\s*\\?$")


def canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


@dataclass(frozen=True)
class Pin:
    name: str
    version: str
    marker: str | None


def parse_pins(text: str) -> list[Pin]:
    """Each `name==version ; marker` line of an export (hash and comment lines are skipped)."""
    pins = []
    for line in text.splitlines():
        m = _REQ.match(line.strip())
        if m:
            pins.append(Pin(canonical(m[1]), m[2], m[3].strip() if m[3] else None))
    return pins


def _marker_evaluator() -> Callable[[str], bool]:
    try:
        from packaging.markers import Marker
    except ImportError:  # a bare environment: pip carries its own copy
        from pip._vendor.packaging.markers import Marker  # type: ignore[no-redef]
    return lambda marker: Marker(marker).evaluate()


def applicable(pins: Iterable[Pin], evaluate: Callable[[str], bool]) -> dict[str, str]:
    return {p.name: p.version for p in pins if p.marker is None or evaluate(p.marker)}


@dataclass
class Difference:
    missing: list[str] = field(default_factory=list)  # "name==version" not installed
    wrong: list[str] = field(default_factory=list)  # "name installed X, lock Y"
    extra: list[str] = field(default_factory=list)  # installed, not in the lock for this platform

    def __bool__(self) -> bool:
        return bool(self.missing or self.wrong or self.extra)


def _same_version(a: str, b: str) -> bool:
    if a == b:
        return True
    try:
        from packaging.version import Version
    except ImportError:
        from pip._vendor.packaging.version import Version  # type: ignore[no-redef]
    try:
        return Version(a) == Version(b)
    except Exception:
        return False


def compare(locked: dict[str, str], installed: dict[str, str]) -> Difference:
    diff = Difference()
    for name, version in sorted(locked.items()):
        have = installed.get(name)
        if have is None:
            diff.missing.append(f"{name}=={version}")
        elif not _same_version(have, version):
            diff.wrong.append(f"{name} installed {have}, lock {version}")
    diff.extra = sorted(n for n in installed if n not in locked and n not in NEVER_PRUNED)
    return diff


def installed_distributions() -> dict[str, str]:
    out: dict[str, str] = {}
    for dist in importlib.metadata.distributions():
        name = dist.metadata["Name"] if dist.metadata else None
        if name:
            out[canonical(name)] = dist.version
    return out


def broken_leftovers() -> list[Path]:
    """Folders pip leaves half-renamed (`~name`), which it cannot uninstall; reported for removal by hand."""
    roots = {Path(p) for p in site.getsitepackages() if Path(p).name == "site-packages"}
    return sorted(p for root in roots if root.is_dir() for p in root.iterdir() if p.name.startswith("~"))


def sync_install_cmds() -> list[list[str]]:
    return [
        pip("install", "--require-hashes", "--only-binary", ":all:", "-r", "requirements/dev.txt"),
        pip("install", "--no-deps", "--no-build-isolation", "-e", "."),
    ]


def prune_cmd(names: Sequence[str]) -> list[str] | None:
    names = [n for n in names if n not in NEVER_PRUNED]
    return pip("uninstall", "-y", *names) if names else None


def _report(diff: Difference) -> None:
    for line in diff.missing:
        print(f"  missing  {line}")
    for line in diff.wrong:
        print(f"  version  {line}")
    for name in diff.extra:
        print(f"  extra    {name} (not in the lock for this platform)")


def cmd_sync(check_only: bool, run: Runner = _run) -> int:
    evaluate = _marker_evaluator()
    locked = applicable(parse_pins(export_path("dev.txt").read_text(encoding="utf-8")), evaluate)
    if check_only:
        diff = compare(locked, installed_distributions())
        project_missing = PROJECT not in installed_distributions()
        for p in broken_leftovers():  # not an installed package, so not a difference from the lock
            print(
                f"deps: note: {p.name} in site-packages is a half-removed package; delete the folder by hand"
            )
        if not diff and not project_missing:
            print("deps: this environment matches requirements/dev.txt")
            return 0
        print("deps: this environment differs from requirements/dev.txt:")
        _report(diff)
        if project_missing:
            print(f"  missing  {PROJECT} (the project, editable)")
        print(f"Fix: {SYNC}")
        return 1
    for cmd in sync_install_cmds():
        if run(cmd).returncode != 0:
            print("deps: pip install failed", file=sys.stderr)
            return 1
    importlib.invalidate_caches()
    extra = compare(locked, installed_distributions()).extra
    cmd = prune_cmd(extra)
    if cmd:
        print(f"deps: removing {len(extra)} package(s) the lock does not name: {', '.join(extra)}")
        if run(cmd).returncode != 0:
            print("deps: pip uninstall failed", file=sys.stderr)
            return 1
    for p in broken_leftovers():
        print(
            f"deps: cannot remove {p.name} in site-packages (a half-removed package); delete the folder by hand"
        )
    return 0 if run(pip("check")).returncode == 0 else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="deps.py", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    lock = sub.add_parser("lock", help="resolve uv.lock and write both exports")
    group = lock.add_mutually_exclusive_group()
    group.add_argument("--upgrade", action="store_true", help="upgrade every package")
    group.add_argument(
        "--upgrade-package", action="append", default=[], metavar="NAME", help="upgrade one package"
    )
    sub.add_parser("check", help="fail when uv.lock or an export is stale")
    sync = sub.add_parser("sync", help="make this environment match requirements/dev.txt")
    sync.add_argument(
        "--check", action="store_true", help="only list the differences; exit 1 when there are any"
    )
    args = parser.parse_args(argv)
    if args.command == "lock":
        return cmd_lock(args.upgrade, args.upgrade_package)
    if args.command == "check":
        return cmd_check()
    return cmd_sync(args.check)


if __name__ == "__main__":
    raise SystemExit(main())
