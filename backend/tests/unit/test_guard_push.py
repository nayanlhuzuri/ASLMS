"""Design github-and-ci, decision 9: the guard hook (`.claude/hooks/guard.py`) refuses forced, mirrored, all-branch
and deleting pushes, pushes to a remote other than `origin`, remote changes and the owner's `gh` commands, and lets
the integrator's two pushes through."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

GUARD = Path(__file__).resolve().parents[3] / ".claude" / "hooks" / "guard.py"
pytestmark = pytest.mark.skipif(not GUARD.exists(), reason="the guard hook is not in this checkout")


def decision(command: str, tool: str = "Bash") -> dict | None:
    proc = subprocess.run(
        [sys.executable, str(GUARD)],
        input=json.dumps({"tool_name": tool, "tool_input": {"command": command}}),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)["hookSpecificOutput"] if proc.stdout.strip() else None


def denied(command: str, tool: str = "Bash") -> bool:
    out = decision(command, tool)
    return bool(out) and out["permissionDecision"] == "deny"


@pytest.mark.parametrize(
    "command",
    [
        "git push --force origin main",
        "git push -f origin main",
        "git push origin main -f",
        "git push -uf origin main",
        "git push --force-with-lease origin main",
        "git push --force-with-lease=main:abc origin main",
        "git push --force-if-includes origin main",
        "git push --mirror origin",
        "git push --all origin",
        "git push --delete origin feature/x",
        "git push -d origin feature/x",
        "git push origin +main",
        "git push origin :feature/x",
        "git push origin main +refs/tags/feature/x-done",
        "git push upstream main",
        "git push https://github.com/someone/else.git main",
        "git push",
        "git push --repo=elsewhere main",
        "git -C backend push --force origin main",
        "cd backend && git push --force origin main",
        "git status; git push -f origin main",
        "GIT_TRACE=1 git push --force origin main",
        'bash -c "git push --force origin main"',
        "git remote add origin https://github.com/nayanlhuzuri/aslms.git",
        "git remote add x y",
        "git remote set-url origin https://example.org/x.git",
        "git remote remove origin",
        "git remote rm origin",
        "git config remote.origin.url https://example.org/x.git",
        "git config --unset remote.origin.pushurl",
        "gh secret set NAPIX_AUTH_KEY",
        "gh secret list",
        "gh repo create nayanlhuzuri/aslms --private",
        "gh repo delete nayanlhuzuri/aslms --yes",
        "gh repo edit --enable-issues",
        "gh repo rename other",
        "gh repo archive",
        "gh api repos/nayanlhuzuri/aslms",
        "gh api -X PUT repos/x/y/rulesets",
    ],
)
def test_denied(command):
    assert denied(command), command


def test_denied_through_powershell_too():
    assert denied("git push --force origin main", tool="PowerShell")


@pytest.mark.parametrize(
    "command",
    [
        "cd backend\ngit push --force origin main",
        "git push origin main\ngit push upstream main",
        "git push origin main\ngit remote add x y",
        "git push origin main\ngh secret set X",
        "git status\r\ngit push -f origin main",
        "git status\r\n\r\ngh api repos/x/y",
        "git push origin main \\\n  --force",
        "# don't push elsewhere\ngit push upstream main",
        "cat <<'EOF' > notes.txt\nit's a note\nEOF\ngit push upstream main",
        "git push origin main\n  git push origin +main",
        'bash -c "cd backend\ngit push --force origin main"',
    ],
)
def test_denied_on_any_line(command):
    assert denied(command), repr(command)


@pytest.mark.parametrize(
    "command",
    [
        "git push origin main `\n  --force",
        "Set-Location backend\ngit push upstream main",
        "$m = @'\nit's a note\n'@\ngit push --force origin main",
    ],
)
def test_denied_on_any_line_in_powershell(command):
    assert denied(command, tool="PowerShell"), repr(command)


@pytest.mark.parametrize(
    "command",
    [
        "git add guard.py\ngit status\ngit push origin main",
        "git push origin main\r\ngit push origin refs/tags/feature/x-done",
        'git commit -m "guard: refuse\n\ngit push --force origin main\ngh secret set X"',
        "git commit -F - <<'EOF'\nguard: it's done\ngit push upstream main\nEOF\ngit push origin main",
        "git commit -F - <<-EOF\n\tgh api repos/x/y\n\tEOF\ngit status",
    ],
)
def test_allowed_on_every_line(command):
    assert not denied(command), repr(command)


@pytest.mark.parametrize(
    "command",
    [
        "git push origin main",
        "git push origin refs/tags/feature/x-done",
        "git push -u origin main",
        "git remote get-url origin",
        "git remote -v",
        "git config --get user.name",
        "gh run list --branch main --limit 1",
        "gh run view 123",
        "gh auth status",
        "git status",
        'git commit -m "guard: deny git push --force and gh api"',
        "git log origin/main..main --oneline",
    ],
)
def test_allowed(command):
    assert not denied(command), command
