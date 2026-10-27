"""The backend wording guard (design case-workspace-admin, decision 6): "file" must not reach what users read in the
custody sense. The `ast` scan reads every string constant and f-string piece of the listed modules (docstrings and bare
code constants such as "file" or "files" skipped); the rendered title and body of every workflow alert event are checked
too. A text containing `\\bfiles?\\b` fails unless an allow-list entry matches it, and a deny-list phrase fails even then.
The allow-list covers only the uploaded or exported computer-file sense and the legal verb ("File in court"); the
reviewer checks every entry. Internal code names (`custody`, `holder_*`, the `file` codes) are not text users read.

The second rule (design claim-assign-wording, decision 9): "allot" in any form (`\\ballot(s|ted|ting|ment|ments)?\\b`,
any case) fails in the same strings of the same modules plus `aslms/services/ownership.py`, with no allow-list; the
portal's word is "Assign". Code-like strings (`allotted`, `ownership.allot`) and docstrings are skipped as above, and a
dotted function code inside a sentence (`cases.allot is not enabled …`) is a code name, not a word users read."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
MODULES = [
    "aslms/services/alert_rules.py",
    "aslms/services/notifications.py",
    "aslms/services/dashboard.py",
    "aslms/services/reports.py",
    "aslms/services/access_seed.py",
    "aslms/services/seed.py",
    "aslms/domain/workflow.py",
    "aslms/services/custody.py",
    "aslms/services/notes.py",
    "aslms/services/workflow_common.py",
    "aslms/services/memberships.py",
    "aslms/cli/reports.py",
    "aslms/cli/users.py",
]

WORD = re.compile(r"\bfiles?\b", re.IGNORECASE)
CODE = re.compile(r"^[a-z0-9_.:{}]+$")
ALLOT = re.compile(r"\ballot(s|ted|ting|ment|ments)?\b", re.IGNORECASE)
DOTTED_CODE = re.compile(r"\b[a-z][a-z_]*\.[a-z][a-z_.]*\b")
ALLOT_MODULES = [*MODULES, "aslms/services/ownership.py"]

# (regex, reason): the computer-file sense and the legal verb only
ALLOW: list[tuple[str, str]] = [
    (r"\bfile type", "the type of an uploaded computer file"),
    (r"\b(PDF|Word|Excel|JSON) files?\b", "a computer file of that format"),
    (
        r"\bthe file (is larger|is empty|failed the virus scan|is already on the case|is uploaded)",
        "an uploaded computer file",
    ),
    (r"\b(Attach (a )?new files?|Up to \d+ files?|At most \d+ files?)", "files attached from disk"),
    (r"\bNo text in the file\b", "an uploaded computer file's text"),
    (r"\bFile \(PDF, Word or image\)", "the upload field"),
    (r"\bOld Word files\b", "a computer file format"),
    (r"\bFile in court\b", "the pending action: the legal verb"),
    (r"\bwrite the file here\b", "the exported report file (CLI --out)"),
]

DENY: list[str] = [
    r"file (is )?with",
    r"hold(s|ing)? (this |the )?file",
    r"send (the )?file",
    r"recall(ing)? (the )?files?",
    r"files? (received|recalled|holder|remark|moved|movement|due|overdue)",
    r"files with",
    r"department files",
]


def offends(text: str) -> bool:
    """True when `text` uses "file" in the custody sense: a deny phrase, or a "file" no allow entry explains."""
    if not WORD.search(text):
        return False
    if any(re.search(d, text, re.IGNORECASE) for d in DENY):
        return True
    stripped = text
    for pattern, _ in ALLOW:
        stripped = re.sub(pattern, "", stripped, flags=re.IGNORECASE)
    return bool(WORD.search(stripped))


def says_allot(text: str) -> bool:
    """True when `text` uses "allot" in any form outside a dotted function code (design claim-assign-wording)."""
    return bool(ALLOT.search(DOTTED_CODE.sub("", text)))


def _docstring_nodes(tree: ast.AST) -> set[int]:
    out: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                out.add(id(body[0].value))
    return out


def strings_of(source: str) -> list[tuple[int, str]]:
    """Every string constant and f-string piece but docstrings and bare code constants."""
    tree = ast.parse(source)
    skip = _docstring_nodes(tree)
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip:
            if CODE.match(node.value):
                continue
            out.append((node.lineno, node.value))
    return out


def test_self_check():
    assert offends("Send file")
    assert offends("the file is with the Under Secretary")
    assert offends("Files with me")
    assert offends("File received from EDU")
    assert not offends("The file is larger than the limit")
    assert not offends("File in court")
    assert not offends("Old Word files are refused")
    assert not offends("Case received from EDU")
    assert offends("the PDF file is with you")  # a deny phrase wins over an allow entry


@pytest.mark.parametrize("module", MODULES)
def test_module_strings(module):
    source = (BACKEND / module).read_text(encoding="utf-8")
    bad = [(line, text) for line, text in strings_of(source) if offends(text)]
    assert bad == [], f"{module}: custody-sense 'file' in user text: {bad}"


def test_allot_self_check():
    assert says_allot("Case allotted: WP(C)/1/2026")
    assert says_allot("Allot Cases")
    assert says_allot("Department office / not allotted")
    assert says_allot("2 allotments")
    assert not says_allot("Case assigned: WP(C)/1/2026")
    assert not says_allot("cases.allot is not enabled for you in EDU")
    assert not says_allot("ownership.reallotted_on_exit")
    assert CODE.match("allotted") and CODE.match("ownership.allot")


@pytest.mark.parametrize("module", ALLOT_MODULES)
def test_module_strings_no_allot(module):
    source = (BACKEND / module).read_text(encoding="utf-8")
    bad = [(line, text) for line, text in strings_of(source) if says_allot(text)]
    assert bad == [], f"{module}: 'allot' in user text (the portal's word is Assign): {bad}"


def _payloads() -> list[dict]:
    base = {
        "case_label": "WP(C)/1/2026",
        "case_id": "00000000-0000-0000-0000-000000000001",
        "from_office_code": "EDU",
        "holder_office_code": "EDU",
        "holder_designation": "Under Secretary",
        "holder_office_name": "Education",
        "reason": "sent",
        "reason_label": "Sent",
        "due_date": "2026-10-30",
    }
    return [
        {**base, "event": "file_received"},
        {**base, "event": "file_recalled", "reason": "recalled", "reason_label": "Recalled"},
        {**base, "event": "due", "overdue": False},
        {**base, "event": "due", "overdue": True},
    ]


def test_rendered_workflow_alerts():
    from aslms.services import alert_rules

    for payload in _payloads():
        title, body = alert_rules.render_workflow(payload, payload["case_label"])
        for text in (title, body or ""):
            assert not offends(text), (payload["event"], text)
            assert not says_allot(text), (payload["event"], text)
        assert "Case" in title, (payload["event"], title)
