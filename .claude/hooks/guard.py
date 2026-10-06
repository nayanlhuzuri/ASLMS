"""PreToolUse guard for ASLMS (CLAUDE.md rules the harness enforces, not prompts).

Blocks: any access to `.env` / `.env.*` except `.env.example`; edits to applied migrations under
`backend/migrations/versions/`; writing `NAPIX_ENABLED=true` into a file; writing to, copying from or importing
anything under `ASLMS-legacy`. Reads stdin JSON; prints a permission decision; always exits 0."""

from __future__ import annotations

import json
import os
import re
import shlex
import sys

FILE_TOOLS = {"Read", "Edit", "Write", "MultiEdit", "NotebookEdit"}
NAPIX_ON_RE = re.compile(r"NAPIX_ENABLED\s*[=:]\s*[\"']?true", re.I)
NAPIX_PY_RE = re.compile(r"napix_enabled\s*(:\s*bool\s*)?=\s*True")
DOC_SUFFIXES = (".md", ".txt", ".rst", ".docx")
WRITES_RE = re.compile(r"(>>?|\btee\b|sed\s+-i|\bcp\b|\bmv\b|\brsync\b|Set-Content|Out-File|Add-Content)")
LEGACY = "aslms-legacy"
QUOTED_RE = re.compile(r'"(?:\\.|[^"\\])*"|\'[^\']*\'', re.S)


def deny(reason: str) -> None:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": f"ASLMS guard: {reason}",
                }
            }
        )
    )
    sys.exit(0)


def is_env_path(path: str) -> bool:
    name = os.path.basename(path.replace("\\", "/"))
    return name.startswith(".env") and name != ".env.example"


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:  # noqa: BLE001
        return
    tool = payload.get("tool_name", "")
    inp = payload.get("tool_input") or {}

    if tool in FILE_TOOLS:
        path = str(inp.get("file_path") or inp.get("notebook_path") or "")
        norm = path.replace("\\", "/")
        if is_env_path(path):
            deny(".env files hold secrets and are never read or written by the assistant (CLAUDE.md)")
        if LEGACY in norm.lower() and tool != "Read":
            deny("nothing under ASLMS-legacy is edited; it is read-only reference")
        if tool != "Read" and "/migrations/versions/" in norm and os.path.exists(path):
            deny("an applied migration is never edited; add a new migration instead (CLAUDE.md, Database)")
        if tool in {"Edit", "Write", "MultiEdit"} and not norm.lower().endswith(DOC_SUFFIXES):
            # configuration and code only: documentation may mention the switch
            text = " ".join(
                str(inp.get(k) or "") for k in ("content", "new_string", "new_source")
            ) + " ".join(str(e.get("new_string") or "") for e in inp.get("edits") or [])
            if (NAPIX_ON_RE.search(text) or NAPIX_PY_RE.search(text)) and not norm.endswith("guard.py"):
                deny(
                    "the NAPIX master switch is never turned on in a file (config or code); "
                    "the owner passes it on the command line for a live run"
                )
        return

    if tool in {"Bash", "PowerShell"}:
        cmd = str(inp.get("command") or "")
        low = cmd.lower()
        # a `.env` file as a command operand (cat .env, cp .env …, source .env, >> .env) is blocked;
        # the words inside a quoted string (a commit message mentioning .env) are not operands
        try:
            tokens = shlex.split(cmd, posix=True)
        except ValueError:
            tokens = cmd.split()
        for t in tokens:
            base = os.path.basename(t.replace("\\", "/").rstrip("/"))
            if base.startswith(".env") and base != ".env.example" and not base.startswith(".env.example."):
                deny(".env files hold secrets; commands may not read, copy or edit them")
        # operands are single-line tokens; a quoted multi-line text (a commit message) is not an operand
        operands = [t for t in tokens if "\n" not in t]
        unquoted = QUOTED_RE.sub('""', cmd)
        # redirections to /dev/null are not file writes (`2>/dev/null`, `>/dev/null`)
        unquoted_writes = re.sub(r"\d?>>?\s*/dev/null|\d?>&\d", "", unquoted)  # also `2>&1`
        redirects = any(t in {">", ">>", "tee"} for t in tokens) or bool(re.search(r">>?", unquoted_writes))
        writes = bool(WRITES_RE.search(unquoted)) or redirects
        legacy_operands = [t for t in operands if LEGACY in t.lower()]
        if legacy_operands and writes:
            deny("nothing is copied or moved from ASLMS-legacy (read-only reference)")
        if legacy_operands and ("import" in unquoted.lower() or any("import" in t.lower() for t in operands)):
            deny("nothing is imported from ASLMS-legacy")
        napix_on = NAPIX_ON_RE.search(unquoted) or any(NAPIX_ON_RE.search(t) for t in operands)
        if napix_on and writes:
            deny("the NAPIX master switch is never written into a file")
        migration_operands = [t for t in operands if "migrations/versions/" in t.replace("\\", "/").lower()]
        if migration_operands and (re.search(r"sed\s+-i|Set-Content|Out-File", unquoted) or redirects):
            deny("applied migrations are never edited in place")


if __name__ == "__main__":
    main()
