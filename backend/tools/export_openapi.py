"""Writes the API's OpenAPI document to `frontend/openapi.json` (design `portal-shell`, decision 19): sorted keys,
2-space indent, a trailing newline. `npm run gen:api` turns it into the portal's types. Run from anywhere:
`backend/.venv/Scripts/python backend/tools/export_openapi.py`. No database or secret is needed: the app is only
built, never started."""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
TARGET = BACKEND.parent / "frontend" / "openapi.json"
# FastAPI describes a declared response that has no description by `http.HTTPStatus(code).phrase`, and Python 3.13
# renamed these phrases to RFC 9110's. The image and CI run Python 3.12, development 3.13: the document keeps RFC
# 9110's names whichever Python builds it (design github-and-ci, deviation 11).
OLD_PHRASES = {
    413: ("Request Entity Too Large", "Content Too Large"),
    414: ("Request-URI Too Long", "URI Too Long"),
    416: ("Requested Range Not Satisfiable", "Range Not Satisfiable"),
    422: ("Unprocessable Entity", "Unprocessable Content"),
}


def rfc9110_descriptions(doc: dict) -> dict:
    for operations in (doc.get("paths") or {}).values():
        for operation in operations.values():
            if not isinstance(operation, dict):
                continue
            for code, response in (operation.get("responses") or {}).items():
                old_new = OLD_PHRASES.get(int(code)) if str(code).isdigit() else None
                if old_new and isinstance(response, dict) and response.get("description") == old_new[0]:
                    response["description"] = old_new[1]
    return doc


def openapi_text() -> str:
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    from aslms.api.main import create_app
    from aslms.core.config import Settings

    settings = Settings(_env_file=None)
    app = create_app(settings, session_factory=lambda: None)
    return (
        json.dumps(rfc9110_descriptions(app.openapi()), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    )


def main() -> None:
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(openapi_text(), encoding="utf-8", newline="\n")
    print(f"wrote {TARGET}")


if __name__ == "__main__":
    main()
