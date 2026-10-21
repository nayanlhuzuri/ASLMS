"""Owner decision (21 Oct 2026): ASLMS names only itself and the Government of Assam, never the agencies that build it.
Nothing the backend sends or shows (e-mails, exports, API titles, CLI text) may name SeMT or AMTRON."""

import re
from pathlib import Path

AGENCIES = re.compile(r"semt|amtron", re.IGNORECASE)
PACKAGE = Path(__file__).resolve().parents[2] / "aslms"


def test_no_backend_source_names_the_agencies():
    offenders = [
        str(path.relative_to(PACKAGE))
        for path in PACKAGE.rglob("*")
        if path.is_file()
        and path.suffix in {".py", ".html", ".txt", ".j2", ".json", ".md"}
        and AGENCIES.search(path.read_text(encoding="utf-8", errors="ignore"))
    ]
    assert offenders == []
