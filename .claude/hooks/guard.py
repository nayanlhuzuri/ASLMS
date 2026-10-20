"""PreToolUse guard for ASLMS (CLAUDE.md rules the harness enforces, not prompts).

Blocks: any access to `.env` / `.env.*` except `.env.example`; edits to applied migrations under
`backend/migrations/versions/`; writing `NAPIX_ENABLED=true` into a file; writing to, copying from or importing
anything under `ASLMS-legacy`; the push, remote and `gh` forms of design github-and-ci, decision 9 (a forced,
mirrored, all-branch or deleting push, a refspec starting with `+` or `:`, a remote other than `origin`; adding,
changing or removing a remote; `gh secret`, `gh api` and the repository-changing `gh repo` commands: the remote and
the repository's settings are the owner's). Reads stdin JSON; prints a permission decision; always exits 0."""

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


SHELL_OPERATORS = {"&&", "||", ";", "|", "&", "(", ")", ";;", "|&"}  # and an unquoted line break (`segments`)
ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
SHELLS = {"bash", "sh", "zsh", "dash", "powershell", "pwsh", "powershell.exe", "pwsh.exe", "cmd", "cmd.exe"}
PUSH_FORCE_LONG = ("--force", "--mirror", "--all", "--delete", "--prune")
GIT_OPTS_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}
PUSH_OPTS_WITH_VALUE = {"--receive-pack", "--exec", "-o", "--push-option"}
GH_REPO_DENIED = {"create", "delete", "edit", "rename", "archive", "unarchive", "set-default"}


HEREDOC_RE = re.compile(r"""<<(-?)[ \t]*(?:'([^'\n]*)'|"([^"\n]*)"|\\?([A-Za-z0-9_.-]+))""")
WORD_START = " \t\n;&|()"


def _skip_heredoc_bodies(s: str, i: int, heredocs: list[tuple[str, bool]]) -> int:
    """The index after the bodies of the pending heredocs, which start at `i` (the line after their operator)."""
    n = len(s)
    for delim, strip_tabs in heredocs:
        while i < n:
            end = s.find("\n", i)
            line = s[i:] if end == -1 else s[i:end]
            i = n if end == -1 else end + 1
            if (line.lstrip("\t") if strip_tabs else line) == delim:
                break
    heredocs.clear()
    return i


def _logical_lines(cmd: str, backtick_joins: bool) -> str:
    """The command line with every unquoted line break turned into `;`, so each line is its own command.

    A backslash before the line break (and, when `backtick_joins`, PowerShell's backtick) continues the line; a line
    break inside quotes stays part of its word (a multi-line commit message). Comments, heredoc bodies and
    PowerShell here-strings are dropped, so a quote or a command-like line inside them is never read as a command.
    """
    s = cmd.replace("\r\n", "\n").replace("\r", "\n")
    out: list[str] = []
    heredocs: list[tuple[str, bool]] = []
    quote: str | None = None
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if quote == "'":
            out.append(c)
            quote = None if c == "'" else quote
            i += 1
        elif quote == '"':
            step = 2 if c == "\\" else 1
            out.append(s[i : i + step])
            quote = None if c == '"' else quote
            i += step
        elif c == "\\" and i + 1 < n:
            if s[i + 1] != "\n":
                out.append(s[i : i + 2])
            i += 2
        elif c == "`" and backtick_joins and s.startswith("`\n", i):
            out.append(" ")
            i += 2
        elif c in "'\"":
            quote = c
            out.append(c)
            i += 1
        elif c == "@" and s[i + 1 : i + 3] in ("'\n", '"\n'):
            end = s.find("\n" + s[i + 1] + "@", i + 2)
            out.append("''")
            i = n if end == -1 else end + 3
        elif c == "#" and (i == 0 or s[i - 1] in WORD_START):
            end = s.find("\n", i)
            i = n if end == -1 else end
        elif c == "<" and not s.startswith("<<<", i) and (m := HEREDOC_RE.match(s, i)):
            heredocs.append((next(g for g in m.group(2, 3, 4) if g is not None), bool(m.group(1))))
            out.append(" ")
            i = m.end()
        elif c == "\n":
            out.append(" ; ")
            i = _skip_heredoc_bodies(s, i + 1, heredocs)
        else:
            out.append(c)
            i += 1
    return "".join(out)


def segments(cmd: str) -> list[list[str]]:
    """The simple commands of a command line, split on the shell's control operators and on line breaks (quotes
    respected). A backtick before a line break continues the line in PowerShell but not in a POSIX shell, so such a
    command is read both ways and the commands of both readings are returned."""
    out = _split(_logical_lines(cmd, backtick_joins=True))
    if re.search(r"`\r?\n", cmd):
        out += _split(_logical_lines(cmd, backtick_joins=False))
    return out


def _split(cmd: str) -> list[list[str]]:
    """Split one logical command line on the shell's control operators (quotes respected)."""
    try:
        lex = shlex.shlex(cmd, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        tokens = list(lex)
    except ValueError:
        tokens = cmd.split()
    out: list[list[str]] = [[]]
    for t in tokens:
        if t in SHELL_OPERATORS:
            out.append([])
        else:
            out[-1].append(t)
    return [seg for seg in out if seg]


def _strip_env(seg: list[str]) -> list[str]:
    i = 0
    while i < len(seg) and ENV_ASSIGN_RE.match(seg[i]):
        i += 1
    return seg[i:]


def _git_subcommand(args: list[str]) -> tuple[str, list[str]]:
    """`git [-C dir] [-c k=v] <sub> <rest>` -> (sub, rest)."""
    i = 0
    while i < len(args) and args[i].startswith("-"):
        if args[i] in GIT_OPTS_WITH_VALUE:
            i += 1
        i += 1
    if i >= len(args):
        return "", []
    return args[i], args[i + 1 :]


def check_push(rest: list[str]) -> str | None:
    """Only `git push [-u] origin <ref>...` without force, mirror, all, delete or a `+` / `:` refspec."""
    positional: list[str] = []
    i = 0
    while i < len(rest):
        a = rest[i]
        if a == "--":
            positional += rest[i + 1 :]
            break
        if a.startswith("--"):
            name = a.split("=", 1)[0]
            if name.startswith(PUSH_FORCE_LONG):
                return f"`git push {name}` is never run (forced, mirrored, all-branch or deleting push)"
            if name == "--repo":
                return "`git push --repo` is never run; push to `origin` by name"
            if name in PUSH_OPTS_WITH_VALUE and "=" not in a:
                i += 1
        elif a.startswith("-") and len(a) > 1:
            if set(a[1:]) & {"f", "d"}:
                return f"`git push {a}` is never run (forced or deleting push)"
            if a == "-o":
                i += 1
        else:
            positional.append(a)
        i += 1
    if not positional:
        return "a push names its remote: `git push origin main` or `git push origin refs/tags/feature/<slug>-done`"
    if positional[0] != "origin":
        return f"pushes go to `origin` only, never to {positional[0]!r}"
    for ref in positional[1:]:
        if ref.startswith(("+", ":")):
            return "a refspec starting with `+` (forced) or `:` (deleting) is never pushed"
    return None


def check_git_gh(cmd: str, depth: int = 0) -> str | None:
    """The reason a command line is refused under design github-and-ci, decision 9, or None."""
    for seg in segments(cmd):
        seg = _strip_env(seg)
        if not seg:
            continue
        prog = os.path.basename(seg[0].replace("\\", "/")).lower()
        if prog in SHELLS and depth < 3:
            for i, t in enumerate(seg[1:], start=1):
                if t.lower() in {"-c", "-command", "/c"} and i + 1 < len(seg):
                    reason = check_git_gh(" ".join(seg[i + 1 :]), depth + 1)
                    if reason:
                        return reason
            continue
        if prog in {"git", "git.exe"}:
            sub, rest = _git_subcommand(seg[1:])
            if sub == "push":
                reason = check_push(rest)
                if reason:
                    return reason
            elif sub == "remote" and rest and rest[0] in {"add", "set-url", "remove", "rm", "rename"}:
                return (
                    f"`git remote {rest[0]}` is the owner's: the remote is set up by hand (operations.md 19)"
                )
            elif sub == "config" and any(a.lower().startswith("remote.") for a in rest):
                return "`git config remote.*` is the owner's: the remote is set up by hand (operations.md 19)"
        elif prog in {"gh", "gh.exe"}:
            words = [a for a in seg[1:] if not a.startswith("-")]
            if words[:1] == ["secret"]:
                return "`gh secret` is never run: CI holds no secrets (design github-and-ci, decision 6)"
            if words[:1] == ["api"]:
                return "`gh api` is never run by the assistant; the repository's settings are the owner's"
            if words[:1] == ["repo"] and len(words) > 1 and words[1] in GH_REPO_DENIED:
                return f"`gh repo {words[1]}` is the owner's"
    return None


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
        writes = bool(WRITES_RE.search(unquoted_writes)) or redirects
        legacy_operands = [t for t in operands if LEGACY in t.lower()]
        if legacy_operands and writes:
            deny("nothing is copied or moved from ASLMS-legacy (read-only reference)")
        if legacy_operands and ("import" in unquoted.lower() or any("import" in t.lower() for t in operands)):
            deny("nothing is imported from ASLMS-legacy")
        napix_on = NAPIX_ON_RE.search(unquoted) or any(NAPIX_ON_RE.search(t) for t in operands)
        if napix_on and writes:
            deny("the NAPIX master switch is never written into a file")
        git_reason = check_git_gh(cmd)
        if git_reason:
            deny(git_reason)
        migration_operands = [t for t in operands if "migrations/versions/" in t.replace("\\", "/").lower()]
        if migration_operands and (re.search(r"sed\s+-i|Set-Content|Out-File", unquoted) or redirects):
            deny("applied migrations are never edited in place")


if __name__ == "__main__":
    main()
