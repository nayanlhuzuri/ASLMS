"""Design github-and-ci, decision 14: the CI workflow is tested like code. It fails on drift from the Dockerfiles and
compose.yml, and on a missing safety setting (read-only token, NAPIX off with empty credentials, no secrets, SHA
pins, the database tests required, the docs-only list, the one required check)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = ROOT / ".github" / "workflows"
CI = WORKFLOWS / "ci.yml"
NAPIX_CREDENTIALS = ("NAPIX_CLIENT_ID", "NAPIX_CLIENT_SECRET", "NAPIX_DEPT_ID", "NAPIX_AUTH_KEY")
SHA_RE = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")


@pytest.fixture(scope="module")
def ci() -> dict:
    return yaml.safe_load(CI.read_text(encoding="utf-8"))


def _triggers(doc: dict) -> dict:
    # PyYAML reads the bare key `on` as the boolean True
    return doc.get("on", doc.get(True))


def test_ci_parses_and_runs_on_the_agreed_events(ci):
    on = _triggers(ci)
    assert on["pull_request"]["branches"] == ["main"]
    assert on["push"]["branches"] == ["main"]
    assert "workflow_dispatch" in on


def test_token_is_read_only(ci):
    assert ci["permissions"] == {"contents": "read"}
    for name, job in ci["jobs"].items():
        assert "permissions" not in job or job["permissions"] in ({"contents": "read"}, {}), name


def test_napix_off_and_credentials_empty(ci):
    env = ci["env"]
    assert env["NAPIX_ENABLED"] == "false"
    for var in NAPIX_CREDENTIALS:
        assert env[var] == "", var
    assert env["SOURCETRACE_ENABLED"] == "false"
    assert env["MAIL_BACKEND"] == "console"
    for name, job in ci["jobs"].items():
        for var in (*NAPIX_CREDENTIALS, "NAPIX_ENABLED"):
            assert var not in (job.get("env") or {}), (name, var)


def test_no_secrets_reference_in_any_workflow():
    files = sorted(WORKFLOWS.glob("*.y*ml"))
    assert CI in files
    for f in files:
        text = f.read_text(encoding="utf-8")
        assert not re.search(r"\$\{\{[^}]*\bsecrets\b", text), f.name


def _uses(doc) -> list[str]:
    out = []
    if isinstance(doc, dict):
        for k, v in doc.items():
            if k == "uses" and isinstance(v, str):
                out.append(v)
            else:
                out += _uses(v)
    elif isinstance(doc, list):
        for v in doc:
            out += _uses(v)
    return out


def test_every_action_is_pinned_to_a_full_sha():
    for f in sorted(WORKFLOWS.glob("*.y*ml")):
        uses = _uses(yaml.safe_load(f.read_text(encoding="utf-8")))
        assert uses, f.name
        for u in uses:
            if u.startswith("./"):
                continue
            assert SHA_RE.match(u), f"{f.name}: {u} is not pinned to a 40-hex commit SHA"


def _steps(ci: dict, job: str) -> list[dict]:
    return ci["jobs"][job]["steps"]


def _with(ci: dict, job: str, action: str) -> dict:
    step = next(s for s in _steps(ci, job) if s.get("uses", "").startswith(action + "@"))
    return step.get("with") or {}


def _dockerfile_from(path: Path) -> str:
    return re.search(r"^FROM\s+(\S+)", path.read_text(encoding="utf-8"), re.M).group(1)


def test_python_version_matches_the_backend_image(ci):
    image = _dockerfile_from(ROOT / "backend" / "Dockerfile")  # python:3.12.15-slim
    major_minor = ".".join(re.search(r":(\d+\.\d+)", image).group(1).split(".")[:2])
    assert str(_with(ci, "backend", "actions/setup-python")["python-version"]) == major_minor


def test_node_major_matches_the_portal_image(ci):
    image = _dockerfile_from(ROOT / "frontend" / "Dockerfile")  # node:22.23.3-alpine
    major = re.search(r":(\d+)", image).group(1)
    assert str(_with(ci, "frontend", "actions/setup-node")["node-version"]) == major


def test_postgres_service_matches_compose(ci):
    compose = yaml.safe_load((ROOT / "compose.yml").read_text(encoding="utf-8"))
    assert ci["jobs"]["backend"]["services"]["postgres"]["image"] == compose["services"]["postgres"]["image"]


def test_backend_requires_the_database(ci):
    env = ci["jobs"]["backend"]["env"]
    assert env["ASLMS_TEST_REQUIRE_DB"] == "1"
    assert env["ASLMS_TEST_DATABASE_URL"].endswith("@127.0.0.1:5432/aslms_test")
    runs = " ".join(s.get("run", "") for s in _steps(ci, "backend"))
    assert "-c backend/constraints-ci.txt" in runs and (ROOT / "backend" / "constraints-ci.txt").is_file()
    assert "ruff check ." in runs and "ruff format --check ." in runs and "pytest -q" in runs


def test_docs_only_list_holds_no_path_a_test_reads(ci):
    script = next(s["run"] for s in _steps(ci, "changes") if s.get("id") == "diff")
    for path in ("docs/operations.md", "docs/schema", "docs/specs", "backend/", "frontend/", ".github/"):
        assert path not in script, path
    for path in (
        "docs/design/",
        "docs/reports/",
        "docs/audits/",
        "docs/team/",
        "docs/backlog.md",
        "CLAUDE.md",
    ):
        assert path in script, path


def test_code_jobs_depend_on_changes(ci):
    for job in ("backend", "frontend", "compose"):
        assert ci["jobs"][job]["needs"] == "changes"
        assert ci["jobs"][job]["if"] == "needs.changes.outputs.code == 'true'"


def test_ci_ok_needs_every_other_job(ci):
    ok = ci["jobs"]["ci-ok"]
    assert set(ok["needs"]) == set(ci["jobs"]) - {"ci-ok"}
    assert ok["if"] == "always()"


def test_every_job_has_a_timeout_and_runs_on_ubuntu(ci):
    for name, job in ci["jobs"].items():
        assert job["runs-on"] == "ubuntu-latest", name
        assert isinstance(job.get("timeout-minutes"), int), name


def test_concurrency_never_cancels_main(ci):
    conc = ci["concurrency"]
    assert conc["group"] == "ci-${{ github.ref }}"
    assert "pull_request" in str(conc["cancel-in-progress"])


def test_compose_job_writes_no_env_file_and_starts_only_web(ci):
    runs = "\n".join(s.get("run", "") for s in _steps(ci, "compose"))
    assert ".env" not in runs.replace("GITHUB_ENV", "")
    assert "docker compose up -d --wait --no-deps web" in runs
    assert "add-mask" in runs
    assert "docker compose down -v" in runs


def test_secret_scan_is_weekly():
    doc = yaml.safe_load((WORKFLOWS / "secret-scan.yml").read_text(encoding="utf-8"))
    on = _triggers(doc)
    assert on["schedule"] == [{"cron": "0 21 * * 0"}]
    assert "workflow_dispatch" in on
    assert doc["permissions"] == {"contents": "read"}


def test_dependabot_watches_the_action_pins():
    doc = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8"))
    assert [u["package-ecosystem"] for u in doc["updates"]] == ["github-actions"]
