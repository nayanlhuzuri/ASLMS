"""What never reaches the remote (design github-and-ci, decision 9).

    python backend/tools/repo_policy.py tree             # the tracked files (git ls-files)
    python backend/tools/repo_policy.py range A..B       # every path and every added line in those commits
    python backend/tools/repo_policy.py range -- SHA --not --remotes=origin   # any git revision list
    python backend/tools/repo_policy.py history          # every commit reachable from main

Rules: (1) forbidden paths (.env files, keys and certificates, backups, local data, dumps, unreviewed NAPIX output,
local Claude settings, Postman environments, document stores); (2) a non-empty secret value in an example env file;
(3) the NAPIX master switch turned on in configuration; (4) a private-key block; (5) a literal NAPIX credential;
(6) a file over 20 MB. A finding prints the path, the line and the rule, never the matched value. Exit status 0 when
clean, 1 with findings, 2 on a usage or git error. Standard library only.

The switch-on and private-key patterns are assembled from pieces at import time: the repository's guard hook refuses
any file that holds them literally."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

MAX_BYTES = 20 * 1024 * 1024

SECRET_VARS = (
    "POSTGRES_PASSWORD",
    "ASLMS_APP_PASSWORD",
    "ASLMS_READONLY_PASSWORD",
    "REDIS_PASSWORD",
    "ASLMS_JWT_SECRET",
    "ASLMS_SUPERADMIN_PASSWORD",
    "GRAFANA_ADMIN_PASSWORD",
    "FLOWER_BASIC_AUTH",
    "NAPIX_CLIENT_ID",
    "NAPIX_CLIENT_SECRET",
    "NAPIX_DEPT_ID",
    "NAPIX_AUTH_KEY",
    "MAILTRAP_API_TOKEN",
    "SMTP_PASSWORD",
    "SOURCETRACE_API_KEY",
)
NAPIX_CREDENTIALS = ("NAPIX_CLIENT_ID", "NAPIX_CLIENT_SECRET", "NAPIX_DEPT_ID", "NAPIX_AUTH_KEY")

_ON = "(?:" + "tr" + "ue|1|yes|on)"
SWITCH_ON_RE = re.compile(r"\bNAPIX_ENABLED\b[\"']?\s*[=:]\s*[\"']?" + _ON + r"[\"']?\s*(?:#.*)?$", re.I)
FIELD_ON_RE = re.compile(
    r"\bnapix_enabled\s*(?::\s*bool\s*)?=\s*(?:Field\(\s*(?:default\s*=\s*)?)?" + "Tr" + r"ue\b"
)
_PK = "-----" + "BEGIN " + r"(?:[A-Z0-9]+ )*" + "PRIVATE " + "KEY-----"
PRIVATE_KEY_LINE_RE = re.compile(r"^\s*" + _PK + r"\s*$")
PRIVATE_KEY_ESCAPED_RE = re.compile(_PK + r"(?:\\r)?\\n[A-Za-z0-9+/=]{20,}")
ENV_LINE_RE = re.compile(r"^\s*(?:export\s+)?(" + "|".join(SECRET_VARS) + r")\s*=(.*)$")
CREDENTIAL_RE = re.compile(r"\b(" + "|".join(NAPIX_CREDENTIALS) + r")\b\s*[=:]\s*(.*)$")
PLACEHOLDER_RE = re.compile(r"^(?:|\"\"|''|\$\{\{[^}]*\}\}|\$\{[^}]*\}|<[^>]*>|\{\{[^}]*\}\})$")


def _norm(path: str) -> str:
    p = path.replace("\\", "/")
    return p[2:] if p.startswith("./") else p


def is_example_env(path: str) -> bool:
    return PurePosixPath(_norm(path)).name == ".env.example"


def is_switch_config(path: str) -> bool:
    """The configuration files where the switch may never be on (documentation is not configuration)."""
    p = _norm(path)
    name = PurePosixPath(p).name
    return (
        name == ".env.example"
        or bool(re.fullmatch(r"compose[^/]*\.ya?ml", name))
        or p.startswith((".github/", "infra/"))
        or name == "Dockerfile"
        or name.startswith("Dockerfile.")
        or p in {"backend/pyproject.toml", "backend/alembic.ini"}
    )


# --------------------------------------------------------------------------------------------- rule 1: paths
def check_path(path: str) -> list[str]:
    """The forbidden-path rules a path breaks (an empty list when it may be pushed)."""
    p = _norm(path)
    parts = PurePosixPath(p).parts
    name = parts[-1] if parts else ""
    dirs = parts[:-1]
    out: list[str] = []
    if name.startswith(".env") and name != ".env.example":
        out.append("env-file")
    if PurePosixPath(name).suffix.lower() in {".pem", ".key", ".p12", ".pfx"}:
        out.append("key-or-certificate")
    if p.startswith("backups/"):
        out.append("backups")
    if "data" in dirs and not p.startswith("frontend/src/"):
        out.append("local-data")
    if p.startswith("infra/proxy/certs/") or p == "infra/clamav/freshclam.conf":
        out.append("deployment-secret")
    if p.startswith("docs/specs/napix/hc/samples/"):
        out.append("unreviewed-napix-output")
    if name.lower().endswith(".dump") or re.fullmatch(r"roles-.*\.sql", name):
        out.append("database-dump")
    if p == ".claude/settings.local.json" or p.startswith(".claude/worktrees/"):
        out.append("local-claude-settings")
    if name.endswith(".postman_environment.json"):
        out.append("postman-environment")
    if {"cause-list-directory", "case_documents", "order_documents"} & set(dirs):
        out.append("document-store")
    return out


# -------------------------------------------------------------------------------------- rules 2-5: contents
def _value(raw: str) -> str:
    v = raw.strip()
    if v.startswith(("#", "`")):  # a comment, or the end of a Markdown code span (`NAME=`): no value
        return ""
    if v and v[0] not in "\"'":
        v = re.split(r"\s+#", v, maxsplit=1)[0].strip()  # an inline comment after an unquoted value
    v = v.rstrip(",;").strip()
    if not v.strip("\"'`,;)]} "):  # only the closing punctuation of a string or a call: an empty assignment
        return ""
    return v


def check_line(path: str, line: str) -> list[str]:
    """The content rules one line of `path` breaks."""
    out: list[str] = []
    if is_example_env(path):
        m = ENV_LINE_RE.match(line)
        if m and _value(m.group(2)) not in {"", '""', "''"}:
            out.append(f"example-env-secret-value ({m.group(1)})")
    if is_switch_config(path) and SWITCH_ON_RE.search(line):
        out.append("napix-switch-on")
    p = _norm(path)
    if p.startswith("backend/aslms/") and p.endswith(".py") and FIELD_ON_RE.search(line):
        out.append("napix-switch-on (settings default)")
    if PRIVATE_KEY_LINE_RE.search(line) or PRIVATE_KEY_ESCAPED_RE.search(line):
        out.append("private-key-block")
    m = CREDENTIAL_RE.search(line)
    if m and not (is_example_env(path) and "example-env-secret-value" in " ".join(out)):
        if not PLACEHOLDER_RE.match(_value(m.group(2))):
            out.append(f"napix-credential ({m.group(1)})")
    return out


def check_text(path: str, text: str) -> list[tuple[int, str]]:
    """(line number, rule) for every content finding in `text`."""
    return [(n, rule) for n, line in enumerate(text.splitlines(), start=1) for rule in check_line(path, line)]


def check_size(size: int) -> list[str]:
    return ["file-over-20mb"] if size > MAX_BYTES else []


def is_binary(data: bytes) -> bool:
    return b"\0" in data[:8192]


# Findings in history that are known and accepted, one entry per (commit, path, rule), each with its reason. Only
# the range and history modes use it: the tree must be clean without exceptions.
HISTORY_ALLOWLIST: dict[tuple[str, str, str], str] = {
    # The first .env.example carried the old development default `aslms` for the Compose cluster. Flagged by the
    # independent audit; `aslms ops preflight` refuses it in production (services/preflight.py, weak values).
    (
        "6f238048f171e208437f9c8147964882f8e24353",
        ".env.example",
        "example-env-secret-value (POSTGRES_PASSWORD)",
    ): "old development default, refused by preflight",
    # DB-1 step 6 named the role passwords `aslms_app` / `aslms_readonly` as development defaults; both are on
    # preflight's weak list and were emptied later.
    (
        "ec1254cb1f57f6ceaffae6931948687d29891114",
        ".env.example",
        "example-env-secret-value (ASLMS_APP_PASSWORD)",
    ): "old development default, refused by preflight",
    (
        "ec1254cb1f57f6ceaffae6931948687d29891114",
        ".env.example",
        "example-env-secret-value (ASLMS_READONLY_PASSWORD)",
    ): "old development default, refused by preflight",
}


def allowed_in_history(commit: str, path: str, rule: str) -> bool:
    return any(c.startswith(commit) and p == path and r == rule for c, p, r in HISTORY_ALLOWLIST)


# --------------------------------------------------------------------------------------------- git plumbing
@dataclass(frozen=True)
class Finding:
    where: str  # "path" or "path:line", with "@<commit>" in range mode
    rule: str

    def __str__(self) -> str:
        return f"{self.where}: {self.rule}"


def git(root: Path, *args: str) -> bytes:
    proc = subprocess.run(["git", *args], cwd=root, capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:2])} failed: {proc.stderr.decode(errors='replace').strip()}")
    return proc.stdout


def repo_root() -> Path:
    return Path(git(Path.cwd(), "rev-parse", "--show-toplevel").decode().strip())


def scan_tree(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for raw in git(root, "ls-files", "-z").split(b"\0"):
        if not raw:
            continue
        path = raw.decode("utf-8", errors="replace")
        findings += [Finding(path, r) for r in check_path(path)]
        file = root / path
        if not file.is_file():
            continue
        findings += [Finding(path, r) for r in check_size(file.stat().st_size)]
        data = file.read_bytes()
        if is_binary(data):
            continue
        text = data.decode("utf-8", errors="replace")
        findings += [Finding(f"{path}:{n}", r) for n, r in check_text(path, text)]
    return findings


HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def _added_lines(patch: bytes) -> Iterator[tuple[str, str, int, str]]:
    """(commit, path, line number, text) for every added line of `git log -p -U0` output."""
    commit, path, lineno = "", "", 0
    for raw in patch.split(b"\n"):
        line = raw.decode("utf-8", errors="replace")
        if line.startswith("commit:"):
            commit, path = line[7:15], ""
        elif line.startswith("+++ "):
            target = line[4:]
            path = target[2:] if target.startswith("b/") else ""
        elif line.startswith("@@"):
            m = HUNK_RE.match(line)
            lineno = int(m.group(1)) if m else 0
        elif line.startswith("+") and path:
            yield commit, path, lineno, line[1:]
            lineno += 1


def scan_revisions(root: Path, revs: Iterable[str]) -> list[Finding]:
    revs = list(revs)
    findings: list[Finding] = []
    raw = git(root, "log", "--no-renames", "--raw", "--no-abbrev", "-z", "--format=commit:%H", *revs, "--")
    blobs: dict[str, tuple[str, str]] = {}
    commit = ""
    tokens = raw.split(b"\0")
    i = 0
    while i < len(tokens):
        tok = tokens[i].decode("utf-8", errors="replace").strip("\n")
        if tok.startswith("commit:"):
            commit = tok[7:15]
        elif tok.startswith(":") and i + 1 < len(tokens):
            fields = tok[1:].split()
            status, path = fields[-1], tokens[i + 1].decode("utf-8", errors="replace")
            i += 1
            if status[0] in "AMCT":
                findings += [Finding(f"{path}@{commit}", r) for r in check_path(path)]
                blobs.setdefault(fields[3], (path, commit))
        i += 1
    if blobs:
        proc = subprocess.run(
            ["git", "cat-file", "--batch-check=%(objectname) %(objectsize)"],
            cwd=root,
            input="\n".join(blobs).encode(),
            capture_output=True,
            check=True,
        )
        for line in proc.stdout.decode().splitlines():
            sha, _, size = line.partition(" ")
            if size.isdigit() and sha in blobs:
                path, c = blobs[sha]
                findings += [Finding(f"{path}@{c}", r) for r in check_size(int(size))]
    patch = git(
        root, "log", "--no-renames", "-p", "-U0", "--no-color", "--no-ext-diff", "--format=commit:%H", *revs
    )
    for c, path, n, text in _added_lines(patch):
        findings += [
            Finding(f"{path}:{n}@{c}", r)
            for r in check_line(path, text)
            if not allowed_in_history(c, path, r)
        ]
    return findings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="mode", required=True)
    sub.add_parser("tree", help="the tracked files")
    rng = sub.add_parser("range", help="the commits of a range, A..B (more git revisions after --)")
    rng.add_argument("spec", nargs="+")
    hist = sub.add_parser("history", help="every commit reachable from a branch (main)")
    hist.add_argument("--branch", default="main")
    args = ap.parse_args(argv)
    try:
        root = repo_root()
        if args.mode == "tree":
            findings = scan_tree(root)
        elif args.mode == "range":
            findings = scan_revisions(root, args.spec)
        else:
            findings = scan_revisions(root, [args.branch])
    except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        print(f"repo_policy: {exc}", file=sys.stderr)
        return 2
    for f in findings:
        print(f)
    if findings:
        print(f"repo_policy {args.mode}: {len(findings)} finding(s); nothing above may reach the remote")
        return 1
    print(f"repo_policy {args.mode}: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
