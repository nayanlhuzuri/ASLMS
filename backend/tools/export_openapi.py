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


def openapi_text() -> str:
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    from aslms.api.main import create_app
    from aslms.core.config import Settings

    settings = Settings(_env_file=None)
    app = create_app(settings, session_factory=lambda: None)
    return json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> None:
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(openapi_text(), encoding="utf-8", newline="\n")
    print(f"wrote {TARGET}")


if __name__ == "__main__":
    main()
