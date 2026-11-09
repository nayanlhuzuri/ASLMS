"""Design dependency-locks: one lock (`backend/uv.lock`) and its two hashed exports, used by CI and the images alike.

Offline: nothing here touches the network. `test_lock_records_the_pyproject_requirements` is the offline half of the CI
guard (`python tools/deps.py check`), so a local `pytest -q` catches a requirement changed without a refresh."""

from __future__ import annotations

import importlib.metadata
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

import pytest
from packaging.markers import Marker
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.tags import Tag, compatible_tags, cpython_tags
from packaging.utils import canonicalize_name, parse_wheel_filename
from packaging.version import Version

BACKEND = Path(__file__).resolve().parents[2]
ROOT = BACKEND.parent
LOCK = BACKEND / "uv.lock"
IMAGE = BACKEND / "requirements" / "image.txt"
DEV = BACKEND / "requirements" / "dev.txt"
PYPROJECT = BACKEND / "pyproject.toml"
DOCKERFILE = BACKEND / "Dockerfile"


@dataclass(frozen=True)
class Pin:
    name: str
    version: str
    marker: str | None
    hashes: tuple[str, ...]
    line: str


def _logical_lines(text: str) -> list[str]:
    out, cur = [], ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        cur += " " + line[:-1].strip() if line.endswith("\\") else " " + line
        if not line.endswith("\\"):
            out.append(cur.strip())
            cur = ""
    if cur:
        out.append(cur.strip())
    return out


def _pins(path: Path) -> dict[str, Pin]:
    pins: dict[str, Pin] = {}
    for line in _logical_lines(path.read_text(encoding="utf-8")):
        head = line.split(" --hash=")[0].strip()
        req, _, marker = head.partition(";")
        m = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9._-]*)==(\S+)", req.strip())
        assert m, f"{path.name}: not a pinned requirement: {line[:120]}"
        hashes = tuple(re.findall(r"--hash=(\S+)", line))
        pins[canonicalize_name(m[1])] = Pin(
            canonicalize_name(m[1]), m[2], marker.strip() or None, hashes, line
        )
    return pins


def _pyproject() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def _norm(name: str, extras, specifier: str, marker: str | None) -> tuple:
    return (
        canonicalize_name(name),
        tuple(sorted(extras or ())),
        tuple(sorted(str(s) for s in SpecifierSet(specifier or ""))),
        str(Marker(marker)) if marker else "",
    )


def _from_pyproject() -> list[tuple]:
    doc = _pyproject()
    out = []
    for text in doc["project"]["dependencies"]:
        r = Requirement(text)
        out.append(_norm(r.name, r.extras, str(r.specifier), str(r.marker) if r.marker else None))
    for extra, reqs in doc["project"]["optional-dependencies"].items():
        for text in reqs:
            r = Requirement(text)
            out.append(_norm(r.name, r.extras, str(r.specifier), f"extra == '{extra}'"))
    for group, reqs in doc["dependency-groups"].items():
        for text in reqs:
            r = Requirement(text)
            out.append((f"group:{group}", *_norm(r.name, r.extras, str(r.specifier), None)))
    return sorted(out)


def _lock() -> dict:
    return tomllib.loads(LOCK.read_text(encoding="utf-8"))


def _from_lock() -> list[tuple]:
    project = next(p for p in _lock()["package"] if p["name"] == "aslms")
    meta = project["metadata"]
    out = [
        _norm(r["name"], r.get("extras"), r.get("specifier", ""), r.get("marker"))
        for r in meta["requires-dist"]
    ]
    for group, reqs in meta.get("requires-dev", {}).items():
        for r in reqs:
            out.append(
                (
                    f"group:{group}",
                    *_norm(r["name"], r.get("extras"), r.get("specifier", ""), r.get("marker")),
                )
            )
    return sorted(out)


def test_lock_records_the_pyproject_requirements():
    assert _from_lock() == _from_pyproject(), (
        "backend/uv.lock does not record pyproject.toml's requirements; run: python tools/deps.py lock"
    )


@pytest.mark.parametrize("path", [IMAGE, DEV], ids=lambda p: p.name)
def test_exports_are_pinned_and_hashed(path):
    text = path.read_text(encoding="utf-8")
    pins = _pins(path)
    assert pins
    for pin in pins.values():
        assert pin.hashes and all(h.startswith("sha256:") and len(h) == 7 + 64 for h in pin.hashes), pin.name
        assert "://" not in pin.line and " @ " not in pin.line, pin.name
    for line in _logical_lines(text):
        assert not line.startswith(("-e", "-c", "-r", "--index-url", "--extra-index-url", "--find-links")), (
            line
        )
    assert "aslms" not in pins


def test_image_set_is_inside_the_ci_set_with_the_same_versions():
    image, dev = _pins(IMAGE), _pins(DEV)
    for name, pin in image.items():
        assert name in dev, f"{name} is in image.txt but not in dev.txt"
        assert (dev[name].version, dev[name].marker) == (pin.version, pin.marker), name
        assert set(dev[name].hashes) == set(pin.hashes), name


def test_every_direct_requirement_is_exported_and_satisfied():
    doc = _pyproject()
    image, dev = _pins(IMAGE), _pins(DEV)
    runtime = [*doc["project"]["dependencies"], *doc["project"]["optional-dependencies"]["redis"]]
    build = doc["dependency-groups"]["build"]
    checks = [(t, image) for t in [*runtime, *build]]
    checks += [(t, dev) for t in [*runtime, *build, *doc["project"]["optional-dependencies"]["dev"]]]
    for text, pins in checks:
        r = Requirement(text)
        name = canonicalize_name(r.name)
        assert name in pins, f"{name} is not exported"
        assert r.specifier.contains(pins[name].version, prereleases=True), (
            name,
            pins[name].version,
            str(r.specifier),
        )


def test_packaging_is_a_runtime_dependency():
    # design dependency-locks, decision 11: kombu's Redis transport imports it without declaring it
    assert "packaging" in _pins(IMAGE)
    assert any(
        canonicalize_name(Requirement(t).name) == "packaging" for t in _pyproject()["project"]["dependencies"]
    )


def _env(platform: str, version: str) -> dict[str, str]:
    linux = platform == "linux"
    return {
        "sys_platform": platform,
        "platform_system": "Linux" if linux else "Windows",
        "os_name": "posix" if linux else "nt",
        "platform_machine": "x86_64" if linux else "AMD64",
        "platform_release": "",
        "platform_version": "",
        "python_version": ".".join(version.split(".")[:2]),
        "python_full_version": version,
        "implementation_name": "cpython",
        "implementation_version": version,
        "platform_python_implementation": "CPython",
        "extra": "",
    }


def _tags(platforms: list[str], version: tuple[int, int]) -> set[Tag]:
    interp = f"cp{version[0]}{version[1]}"
    return set(cpython_tags(version, platforms=platforms)) | set(
        compatible_tags(version, interpreter=interp, platforms=platforms)
    )


LINUX_PLATFORMS = [f"manylinux_2_{n}_x86_64" for n in range(41, 4, -1)] + [
    "manylinux2014_x86_64",
    "manylinux2010_x86_64",
    "manylinux1_x86_64",
    "linux_x86_64",
]
TARGETS = {
    "image (Linux x86_64, CPython 3.12)": (_env("linux", "3.12.15"), _tags(LINUX_PLATFORMS, (3, 12))),
    ".venv (Windows AMD64, CPython 3.13)": (_env("win32", "3.13.0"), _tags(["win_amd64"], (3, 13))),
}


@pytest.mark.parametrize("target", list(TARGETS))
def test_lock_has_wheels_for_linux_and_windows(target):
    env, supported = TARGETS[target]
    locked = {p["name"]: p for p in _lock()["package"]}
    missing = []
    for name, pin in _pins(DEV).items():
        if pin.marker and not Marker(pin.marker).evaluate(env):
            continue
        wheels = locked[name].get("wheels", [])
        tags = set()
        for w in wheels:
            tags |= set(parse_wheel_filename(w["url"].rsplit("/", 1)[-1])[3])
        if not tags & supported:
            missing.append(f"{name}=={pin.version}")
    assert not missing, f"no wheel for {target}: {missing}"


def test_installed_versions_match_the_lock():
    installed = {}
    for dist in importlib.metadata.distributions():
        if dist.metadata and dist.metadata["Name"]:
            installed[canonicalize_name(dist.metadata["Name"])] = dist.version
    wrong = []
    for name, pin in _pins(DEV).items():
        if pin.marker and not Marker(pin.marker).evaluate():
            continue
        have = installed.get(name)
        if have is None or Version(have) != Version(pin.version):
            wrong.append(f"{name} {have or 'missing'} (lock {pin.version})")
    assert not wrong, f"this environment differs from the lock: {wrong}; run: python tools/deps.py sync"


def test_constraints_ci_is_retired():
    assert not (BACKEND / "constraints-ci.txt").exists()
    for f in (ROOT / ".github" / "workflows").glob("*.y*ml"):
        assert "constraints-ci" not in f.read_text(encoding="utf-8"), f.name


def test_dockerfile_installs_only_from_the_lock():
    text = DOCKERFILE.read_text(encoding="utf-8")
    copy_lock = text.index("COPY requirements/image.txt ./requirements/image.txt")
    assert copy_lock < text.index("COPY aslms ./aslms")
    assert "pip install --no-cache-dir --require-hashes --only-binary :all: -r requirements/image.txt" in text
    assert "pip install --no-cache-dir --no-deps --no-build-isolation ." in text
    assert "&& pip check" in text
    smoke = re.search(r'python -c "import ([^"]+)"', text)
    assert smoke
    modules = {m.strip() for m in smoke[1].split(",")}
    assert {"kombu.transport.redis", "aslms.jobs.celery_app", "aslms.api.main", "aslms.cli.main"} <= modules
    assert not re.search(r'pip install(?!.*--no-deps)[^\n]*"\.\[', text)
    assert ".[redis]" not in text
