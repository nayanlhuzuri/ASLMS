"""Writes the codes the backend can send to `frontend/src/lib/enumCodes.json` (design `portal-names-and-labels`,
decision 15): sorted keys, 2-space indent, a trailing newline, the same convention as `export_openapi.py`.

- `enums`: every `enum.StrEnum` defined in a module of `aslms.domain` (found by import, not by a hand list), each with
  its values in declaration order; a name defined in two modules is written `<module>.<Name>`;
- `audit_actions`: the registry `aslms.domain.audit_actions.AUDIT_ACTIONS` (decision 22);
- `case_detail_fields`: the keys of the case overview's blocks (`services/case_detail.py`, decision 18), with the keys
  the portal adds from `court` and `bench`.

The portal's `enumLabels.test.ts`, `auditNames.test.ts` and `caseFields.test.ts` read it. Run from anywhere:
`backend/.venv/Scripts/python backend/tools/export_enum_codes.py`. No database or secret is needed."""

from __future__ import annotations

import enum
import importlib
import inspect
import json
import pkgutil
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
TARGET = BACKEND.parent / "frontend" / "src" / "lib" / "enumCodes.json"


def _domain_enums() -> dict[str, list[str]]:
    import aslms.domain as domain

    found: list[tuple[str, str, list[str]]] = []
    for info in pkgutil.iter_modules(domain.__path__):
        module = importlib.import_module(f"aslms.domain.{info.name}")
        for name, obj in inspect.getmembers(module, inspect.isclass):
            if obj.__module__ != module.__name__ or not issubclass(obj, enum.StrEnum) or obj is enum.StrEnum:
                continue
            found.append((info.name, name, [m.value for m in obj]))
    names = [name for _m, name, _v in found]
    # a name defined in two modules (`FetchStatus` in causelists and ops) is written as `<module>.<Name>`
    return {(f"{m}.{name}" if names.count(name) > 1 else name): values for m, name, values in found}


def _case_detail_fields() -> dict[str, list[str]]:
    from aslms.services import case_detail as cd

    return {
        "identity": list(cd.IDENTITY),
        "status": list(cd.STATUS),
        "classification": list(cd.CLASSIFICATION),
        "place": list(cd.PLACE),
        "parties_as_printed": list(cd.PARTIES_AS_PRINTED),
        "portal": list(cd.PORTAL),
        "acts": list(cd.ACT_FIELDS),
        "lower_courts": list(cd.LOWER_COURT_FIELDS),
        "applications": list(cd.APPLICATION_FIELDS),
        "objections": list(cd.OBJECTION_FIELDS),
        "court_transfers": list(cd.TRANSFER_FIELDS),
        "writ_info": list(cd.WRIT_FIELDS),
        "portal_added": list(cd.PORTAL_ADDED_FIELDS),
    }


def enum_codes_text() -> str:
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    from aslms.domain.audit_actions import AUDIT_ACTIONS

    doc = {
        "audit_actions": list(AUDIT_ACTIONS),
        "case_detail_fields": _case_detail_fields(),
        "enums": _domain_enums(),
    }
    return json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> None:
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(enum_codes_text(), encoding="utf-8", newline="\n")
    print(f"wrote {TARGET}")


if __name__ == "__main__":
    main()
