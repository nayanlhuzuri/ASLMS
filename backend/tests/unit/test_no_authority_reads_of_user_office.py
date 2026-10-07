"""Design `user-memberships`, decision 11: `users.office_id` and `users.role` mirror the primary membership and
are never read for authorisation. This scan keeps it so: in `services/` and `api/`, a read of `.office_id` or
`.role` off a variable that names a login is allowed only in the files that write or display the mirror
(`users.py`, `memberships.py`) or on a line marked `# display`."""

from __future__ import annotations

import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "aslms"
SCANNED = ("services", "api")
ALLOWED_FILES = {"services/users.py", "services/memberships.py"}
# variables that hold a login (User) in this code base
LOGIN_NAMES = (
    r"(?:user|actor_user|caller|u|target_user|holder|person|leaver|login|sup|admin|officer|previous)"
)
READ = re.compile(rf"\b{LOGIN_NAMES}\.(office_id|role)\b(?!\s*=[^=])")


def _offences() -> list[str]:
    out = []
    for folder in SCANNED:
        for path in sorted((BACKEND / folder).rglob("*.py")):
            rel = path.relative_to(BACKEND).as_posix()
            if rel in ALLOWED_FILES:
                continue
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                code = line.split("#", 1)[0]
                if "# display" in line:
                    continue
                if READ.search(code):
                    out.append(f"{rel}:{n}: {line.strip()}")
    return out


def test_no_authority_reads_of_the_login_mirror():
    assert _offences() == []


def test_the_scan_catches_a_read():
    assert READ.search("office = session.get(Office, user.office_id)")
    assert READ.search("if Role(caller.role) == Role.SUPER_ADMIN:")
    assert not READ.search("member.office.id == office.id")
    assert not READ.search("user.office_id = m.office_id")  # a write (the mirror), not a read
