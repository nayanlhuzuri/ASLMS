"""Design github-and-ci, decision 9: `backend/tools/repo_policy.py`, what never reaches the remote.

The switch-on strings are built at run time by concatenation: the guard hook refuses any file that holds them
literally."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("repo_policy", ROOT / "backend" / "tools" / "repo_policy.py")
rp = importlib.util.module_from_spec(SPEC)
sys.modules["repo_policy"] = rp
SPEC.loader.exec_module(rp)

ON = "tr" + "ue"
SWITCH = "NAPIX_ENABLED"
PK_BEGIN = "-----" + "BEGIN PRIVATE " + "KEY-----"
SECRET = "s3cr3t-Value-9f8e7d"
# the credential names are assembled too, so this file holds no literal `NAME=value` for the policy to find
AUTH_KEY, CLIENT_ID, CLIENT_SECRET, DEPT_ID = (
    "NAPIX_" + n for n in ("AUTH_KEY", "CLIENT_ID", "CLIENT_SECRET", "DEPT_ID")
)
HAS_GIT = shutil.which("git") is not None


@pytest.mark.parametrize(
    ("path", "rule"),
    [
        (".env", "env-file"),
        (".env.prod", "env-file"),
        ("frontend/.env.local", "env-file"),
        ("backups/x.dump", "backups"),
        ("backups/x.dump", "database-dump"),
        ("data/store/a.pdf", "local-data"),
        ("backend/data/causelists/a.pdf", "local-data"),
        ("infra/proxy/certs/privkey.pem", "key-or-certificate"),
        ("infra/proxy/certs/privkey.pem", "deployment-secret"),
        ("infra/clamav/freshclam.conf", "deployment-secret"),
        ("server.key", "key-or-certificate"),
        ("client.p12", "key-or-certificate"),
        ("client.pfx", "key-or-certificate"),
        ("docs/specs/napix/hc/samples/cnr.json", "unreviewed-napix-output"),
        ("roles-2026-10-20.sql", "database-dump"),
        (".claude/settings.local.json", "local-claude-settings"),
        (".claude/worktrees/agent-1/x.py", "local-claude-settings"),
        ("docs/postman/live.postman_environment.json", "postman-environment"),
        ("cause-list-directory/2025/a.pdf", "document-store"),
        ("case_documents/a.pdf", "document-store"),
        ("order_documents/a.pdf", "document-store"),
    ],
)
def test_forbidden_paths(path, rule):
    assert rule in rp.check_path(path)


@pytest.mark.parametrize(
    "path",
    [
        ".env.example",
        "frontend/.env.example",
        "frontend/src/app/data/page.tsx",
        "frontend/src/app/(portal)/data/load/page.tsx",
        "frontend/src/components/data/Queue.tsx",
        "backend/aslms/services/backups.py",
        "docs/postman/ASLMS.postman_collection.json",
        "backend/tests/fixtures/causelists/napix_lawazima_bench2048_2025-01-06.pdf",
    ],
)
def test_allowed_paths(path):
    assert rp.check_path(path) == []


def test_switch_on_in_configuration_fires():
    for path, line in [
        ("compose.yml", f"      {SWITCH}: {ON}"),
        ("compose.dev.yml", f'      {SWITCH}: "{ON}"'),
        (".env.example", f"{SWITCH}={ON}"),
        (".github/workflows/ci.yml", f'  {SWITCH}: "{ON}"'),
        ("infra/x/y.env.tmpl", f"{SWITCH}=1"),
        ("backend/Dockerfile", f"ENV {SWITCH}={ON}"),
        ("backend/pyproject.toml", f'{SWITCH} = "{ON}"'),
    ]:
        assert "napix-switch-on" in rp.check_line(path, line), (path, line)


def test_settings_field_defaulting_on_fires():
    on = "Tr" + "ue"
    for line in (f"    napix_enabled: bool = {on}", f"    napix_enabled: bool = Field(default={on})"):
        assert "napix-switch-on (settings default)" in rp.check_line("backend/aslms/core/config.py", line)
    assert rp.check_line("backend/aslms/core/config.py", "    napix_enabled: bool = False") == []


def test_switch_off_and_documentation_do_not_fire():
    assert rp.check_line("compose.yml", f"      {SWITCH}: ${{{SWITCH}:-false}}") == []
    assert rp.check_line(".github/workflows/ci.yml", f'  {SWITCH}: "false"') == []
    # the owner's shell prefix in a design note or a docstring is documentation, not configuration
    assert rp.check_line("docs/design/x.md", f"Run `{SWITCH}={ON} aslms napix-check`") == []
    assert rp.check_line("backend/aslms/cli/napix_check.py", f"  {SWITCH}={ON} aslms napix-check") == []


def test_example_env_secret_value_fires_and_empty_passes():
    assert rp.check_line(".env.example", f"{AUTH_KEY}={SECRET}") == [f"example-env-secret-value ({AUTH_KEY})"]
    assert rp.check_line("frontend/.env.example", f"POSTGRES_PASSWORD='{SECRET}'")
    assert rp.check_line(".env.example", "FLOWER_BASIC_AUTH=ops:x")
    for line in (
        f"{AUTH_KEY}=",
        f'{AUTH_KEY}=""',
        f"{AUTH_KEY}=   # the 16-byte key from the NAPIX portal",
        "POSTGRES_PASSWORD=",
        "POSTGRES_USER=aslms",
        "NAPIX_ENABLED=false",
    ):
        assert rp.check_line(".env.example", line) == [], line


def test_private_key_block_fires_and_a_mention_does_not():
    assert rp.check_line("x/notes.txt", PK_BEGIN) == ["private-key-block"]
    assert rp.check_line("x/k.json", '"key": "' + PK_BEGIN + "\\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASC" + '"') == [
        "private-key-block"
    ]
    text = f"line one\n{PK_BEGIN}\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASC\n"
    assert rp.check_text("a/b.txt", text) == [(2, "private-key-block")]
    # an assertion about a generated key, and a design note naming the block
    assert rp.check_line("t.py", f'    assert data.startswith(b"{PK_BEGIN}")') == []
    assert rp.check_line("d.md", "a `-----BEGIN … PRIVATE KEY-----` block") == []


def test_literal_napix_credential_fires_and_placeholders_pass():
    for path, line in [
        ("docs/notes.md", f"{CLIENT_ID}={SECRET}"),
        ("compose.yml", f"      {CLIENT_SECRET}: {SECRET}"),
        ("backend/x.py", f'{DEPT_ID} = "{SECRET}"'),
    ]:
        assert any(r.startswith("napix-credential") for r in rp.check_line(path, line)), line
    for line in (
        f"{AUTH_KEY}=",
        f'{AUTH_KEY}: ""',
        f'"{AUTH_KEY}=",',
        f"{AUTH_KEY}: ${{{{ env.X }}}}",
        f"{AUTH_KEY}: ${{{AUTH_KEY}}}",
        f"{CLIENT_ID}=<from the NAPIX portal>",
        f"{CLIENT_ID}={{{{client_id}}}}",
        f"a non-empty `{AUTH_KEY}=` in `.env.example`",
    ):
        assert rp.check_line("docs/x.md", line) == [], line


def test_size_limit():
    assert rp.check_size(21 * 1024 * 1024) == ["file-over-20mb"]
    assert rp.check_size(20 * 1024 * 1024) == []


def test_messages_never_hold_the_value():
    lines = [
        f"{AUTH_KEY}={SECRET}",
        f"POSTGRES_PASSWORD={SECRET}",
        f"{CLIENT_SECRET}: {SECRET}",
    ]
    for path in (".env.example", "compose.yml", "docs/x.md"):
        for n, rule in rp.check_text(path, "\n".join(lines)):
            assert SECRET not in rule
            assert SECRET not in str(rp.Finding(f"{path}:{n}", rule))


# ------------------------------------------------------------------------------------------ the git modes
def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.org", "-c", "commit.gpgsign=false", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _run(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "backend" / "tools" / "repo_policy.py"), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.mark.skipif(not HAS_GIT, reason="git is not installed")
def test_range_and_history_find_a_file_added_then_removed(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "one")
    base = _git(repo, "rev-parse", "HEAD").strip()
    (repo / "secrets.env.example").write_text("x\n", encoding="utf-8")
    sub = repo / "conf"
    sub.mkdir()
    (sub / ".env.example").write_text(f"{AUTH_KEY}={SECRET}\n", encoding="utf-8")
    (repo / "server.pem").write_text("x\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "two")
    _git(repo, "rm", "-q", "server.pem")
    (sub / ".env.example").write_text(f"{AUTH_KEY}=\n", encoding="utf-8")
    _git(repo, "commit", "-qam", "three")

    tree = _run(repo, "tree")
    assert tree.returncode == 0, tree.stdout + tree.stderr

    for args in (("range", f"{base}..HEAD"), ("history",)):
        res = _run(repo, *args)
        assert res.returncode == 1, res.stdout + res.stderr
        assert "server.pem@" in res.stdout and "key-or-certificate" in res.stdout
        assert "conf/.env.example:1@" in res.stdout and f"example-env-secret-value ({AUTH_KEY})" in res.stdout
        assert SECRET not in res.stdout + res.stderr


@pytest.mark.skipif(not HAS_GIT, reason="git is not installed")
def test_tree_mode_reports_a_tracked_env_file(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / ".env").write_text(f"ASLMS_JWT_SECRET={SECRET}\n", encoding="utf-8")
    _git(repo, "add", "-f", ".env")
    res = _run(repo, "tree")
    assert res.returncode == 1
    assert ".env: env-file" in res.stdout
    assert SECRET not in res.stdout


def test_tree_mode_on_this_checkout_is_clean():
    if not HAS_GIT or not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    res = _run(ROOT, "tree")
    assert res.returncode == 0, res.stdout + res.stderr
