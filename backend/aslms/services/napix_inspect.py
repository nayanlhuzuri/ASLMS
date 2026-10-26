"""The System health request console (design `system-health-inspector`, decisions 2-9): the pre-filled form of one
court API, the request built from the code that sends it (no call), its validation, the answer's structure against
the field inventory, the last send, the latest stored answer and the full decrypted answer for State-wide viewers.

- **Never calls NAPIX.** The request comes from `integration/napix/preview.py`; sending is `napix_api_check.run`.
- **No secret** in anything returned (decision 3): the access token, the client key and secret, the Authentication Key
  and `request_str` are never built or read here; `dept_id` is masked to its first two characters.
- **Pre-filled values** follow decision 6: a name, a CNR, a case or a filing number of a case the caller cannot see is
  left empty with a hint, so every value sent was seen or typed by the sender.
- **The structure** of an answer is field paths, types and counts, never values, in the field inventory's notation
  (numbered blocks whose values are objects, and lists, become `[]`)."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from aslms.core.config import Settings
from aslms.domain.cases import Case
from aslms.domain.courts import CaseType, Court, HighCourt
from aslms.domain.org import User
from aslms.domain.reference import Permission
from aslms.integration.napix.client import nested_list
from aslms.integration.napix.crypto import DEFAULT_HASH_KEY, build_plain
from aslms.integration.napix.preview import RequestPreview, display_url, preview, token_url
from aslms.services import access, napix_reference, napix_samples, napix_window, system_health
from aslms.services.access import Forbidden, Member
from aslms.services.audit import Actor, write_audit
from aslms.services.audit_search import to_ist
from aslms.services.case_filters import CNR_RE
from aslms.services.napix_reference import INPUTS, PDF_APIS, InputSpec, sample_key
from aslms.services.napix_samples import NoSample, Sample
from aslms.services.refno import current_case_ref_no
from aslms.services.reporting_common import with_timeout
from aslms.services.visibility import access_basis

TEST_ACTION = system_health.TEST_ACTION
VIEW_ACTION = "napix.response_viewed"
FORM_LABEL = "The values in the form"
NUMBERED = re.compile(r"^[A-Za-z_]+\d+$")  # as `aslms napix-fields` collapses numbered blocks
MAX_PATH = 120
PLACEHOLDERS = {
    "party_name": "‹type a name›",
    "advocate_name": "‹type a name›",
    "cnr": "‹type a CNR›",
    "date": "‹type a date›",
}
HINT_HIDDEN = {
    "party_name": "Type a name (the held sample belongs to a case you cannot see)",
    "advocate_name": "Type a name (the held sample belongs to a case you cannot see)",
    "cnr": "Type a CNR (the held sample belongs to a case you cannot see)",
}
HINT_HIDDEN_OTHER = "Type a value (the held sample belongs to a case you cannot see)"
NOT_SHOWN = "‹not shown›"  # a past send's case value the viewer may not see
NOT_SHOWN_TOKEN = "Bearer ‹access token, not shown›"
ACCEPT = "application/json, application/pdf"
METHOD_NOTE_POST = "The four parameters travel in the query string, as for GET (verified live, notes §3)."
NO_INPUT_NOTE = "This API takes no input. The empty string is still encrypted and sent (notes §3)."
TEMPLATE_NOTE = (
    "These do not run as they are. Fill in the placeholders from your NAPIX subscription (the same values as your "
    "Postman environment). ASLMS never shows them."
)
NOT_SAVED = "Shown, not saved to cases. Use Search to add a case."
FULL_ANSWER_DENIED = "The full answer is shown only to users who can see every case"
TOKEN_ENDPOINT_BODY = "grant_type=client_credentials&scope=napix"
TOKEN_CONTENT_TYPE = "application/x-www-form-urlencoded"
TOKEN_AUTH_NOTE = "Basic authentication with the client key and secret from .env (not shown)"


class InvalidInput(ValueError):
    """422 `invalid_input`: one message per parameter name."""

    def __init__(self, errors: dict[str, str]) -> None:
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))
        self.errors = errors


class NoResponse(LookupError):
    """404 `no_response`: no stored answer for this request."""


class TooLarge(ValueError):
    """413 `too_large`: the stored answer is over `HEALTH_RAW_MAX_BYTES`."""

    def __init__(self, size: int, limit: int) -> None:
        super().__init__(f"the answer is {size} bytes; the limit is {limit}")
        self.size, self.limit = size, limit


class DocMissing(LookupError):
    """404 `doc_missing`: the NAPIX document is not installed, or is not the pinned edition."""


# ------------------------------------------------------------------------------------------------ structure (pure)


def _type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, dict):
        return "dict"
    if isinstance(value, list):
        return "list"
    return type(value).__name__


def _numbered(d: dict[str, Any]) -> bool:
    return bool(d) and all(NUMBERED.match(str(k)) and isinstance(v, dict) for k, v in d.items())


def _walk(data: Any, max_depth: int) -> tuple[dict[str, dict[str, Any]], bool]:
    found: dict[str, dict[str, Any]] = {}
    deep = False

    def add(path: str, kind: str) -> None:
        entry = found.setdefault((path or "(root)")[:MAX_PATH], {"types": set(), "count": 0})
        entry["types"].add(kind)
        entry["count"] += 1

    def walk(obj: Any, path: str, depth: int) -> None:
        nonlocal deep
        if isinstance(obj, dict | list) and not obj:
            add(path, _type(obj))
            return
        if isinstance(obj, dict | list) and depth >= max_depth:
            deep = True
            add(path, _type(obj))
            return
        if isinstance(obj, dict):
            if _numbered(obj):
                for row in nested_list(obj):
                    walk(row, f"{path}[]", depth + 1)
                return
            for k, v in obj.items():
                walk(v, f"{path}.{k}" if path else str(k), depth + 1)
            return
        if isinstance(obj, list):
            for v in obj:
                walk(v, f"{path}[]", depth + 1)
            return
        add(path, _type(obj))

    walk(data, "", 0)
    return found, deep


def structure_paths(data: Any, max_depth: int = 6) -> list[str]:
    """Every field path of the answer (no limit on the count), sorted."""
    return sorted(_walk(data, max_depth)[0])


def structure(data: Any, max_paths: int = 200, max_depth: int = 6) -> dict[str, Any]:
    """Field paths, types and counts of a decrypted answer, never a value (decision 5): numbered blocks
    (`case1`…`caseN` with object values) and lists collapse to `[]`, the inventory's type words, at most `max_depth`
    levels and `max_paths` paths, each cut to 120 characters."""
    found, deep = _walk(data, max_depth)
    paths = sorted(found)
    shown = paths[:max_paths]
    return {
        "paths": [
            {"path": p, "type": ", ".join(sorted(found[p]["types"])), "count": found[p]["count"]}
            for p in shown
        ],
        "total": len(paths),
        "more": len(paths) - len(shown),
        "depth_limited": deep,
    }


def inventory_diff(key: str, paths: list[str]) -> dict[str, Any]:
    """`new`: paths of the answer the field inventory does not hold for this API (a field without a home in the
    schema: report it); `absent`: inventory paths not in this answer (information). A path is known when the
    inventory holds it or a field below it (an empty block), and an inventory path is present when the answer holds it
    or a field below it."""
    if key in PDF_APIS or key not in napix_reference.INVENTORY_SECTION:
        return {"checked": False, "new": [], "absent": []}
    inv = napix_reference.inventory_paths(key)
    inv_set = set(inv)

    def below(parent: str, child: str) -> bool:
        return child.startswith(parent + "[]") or child.startswith(parent + ".")

    new = [p for p in paths if p not in inv_set and not any(below(p, i) for i in inv)]
    have = set(paths)
    absent = [i for i in inv if i not in have and not any(below(i, p) for p in paths)]
    return {"checked": True, "new": new, "absent": absent}


# ------------------------------------------------------------------------------------------------ masks and templates


def mask_dept_id(value: str | None) -> str:
    """The first two characters and `…`; fewer than 6 characters in all: fully masked."""
    v = (value or "").strip()
    if not v:
        return "not set"
    if len(v) < 6:
        return "••••••"
    return v[:2] + "…"


def envelope(settings: Settings, p: RequestPreview) -> list[dict[str, Any]]:
    """The four query parameters as shown (decision 2): never `request_str` itself."""
    if p.placeholders:
        token_shown = "not shown until every value is typed"
    elif p.request_token is None:
        token_shown = "not shown (a different hash key is configured)"
    else:
        token_shown = p.request_token
    return [
        {
            "name": "dept_id",
            "shown": mask_dept_id(settings.napix_dept_id),
            "note": "Department ID from .env (NAPIX_DEPT_ID), masked",
            "length": None,
        },
        {
            "name": "request_str",
            "shown": f"encrypted, {p.request_str_length} characters, not shown",
            "note": "AES-128-CBC of the plain string with the Authentication Key (.env)",
            "length": p.request_str_length,
        },
        {
            "name": "request_token",
            "shown": token_shown,
            "note": f"HMAC-SHA256 of the plain string with the published hash key {DEFAULT_HASH_KEY} (spec Annexure A)",
            "length": None,
        },
        {"name": "version", "shown": settings.napix_version, "note": "from NAPIX_VERSION", "length": None},
    ]


def headers() -> list[dict[str, str]]:
    return [{"name": "Authorization", "shown": NOT_SHOWN_TOKEN}, {"name": "Accept", "shown": ACCEPT}]


def curl_template(p: RequestPreview, token_shown: bool, version: str = "v1.0") -> str:
    """A cURL template with placeholders (decision 9): it does not run as it is."""
    token = (
        p.request_token
        if token_shown and p.request_token
        else f"<REQUEST_TOKEN: HMAC-SHA256 of the plain string with {DEFAULT_HASH_KEY}>"
    )
    first = "curl -G -X POST" if p.method == "POST" else "curl -G"
    return "\n".join(
        [
            f"# plain string: {p.plain}",
            f"{first} '{p.url}' \\",
            "  -H 'Authorization: Bearer <ACCESS_TOKEN>' \\",
            f"  -H 'Accept: {ACCEPT}' \\",
            "  --data-urlencode 'dept_id=<DEPT_ID>' \\",
            "  --data-urlencode 'request_str=<REQUEST_STR: the plain string encrypted with your Authentication Key>' \\",
            f"  --data-urlencode 'request_token={token}' \\",
            f"  --data-urlencode 'version={version}'",
        ]
    )


def curl_token(settings: Settings) -> str:
    return (
        f"curl -X POST '{token_url(settings.napix_base_url)}' -u '<CLIENT_KEY>:<CLIENT_SECRET>' "
        f"-H 'Content-Type: {TOKEN_CONTENT_TYPE}' -d '{TOKEN_ENDPOINT_BODY}'"
    )


def token_endpoint(settings: Settings) -> dict[str, str]:
    return {
        "method": "POST",
        "url": token_url(settings.napix_base_url),
        "body": TOKEN_ENDPOINT_BODY,
        "content_type": TOKEN_CONTENT_TYPE,
        "auth_note": TOKEN_AUTH_NOTE,
    }


def _url_parts(url: str) -> dict[str, Any]:
    scheme, rest = url.split("://", 1)
    host, _, path = rest.partition("/")
    return {"protocol": scheme, "host": host.split("."), "path": path.split("/")}


def postman_collection(settings: Settings, p: RequestPreview, label: str) -> dict[str, Any]:
    """A Postman v2.1 collection for this one API (decision 9): the token request as in `docs/postman`, this API's
    request with `input=<plain string>` and the collection's scripts (encrypt from `input`, decrypt and verify the
    answer). The secret variables are empty: the collection holds no secret."""
    tok = token_url(settings.napix_base_url)
    query = [
        {"key": "input", "value": p.plain},
        {"key": "dept_id", "value": "{{dept_id}}"},
        {"key": "request_str", "value": "{{request_str}}"},
        {"key": "request_token", "value": "{{request_token}}"},
        {"key": "version", "value": "{{version}}"},
    ]
    raw_query = "&".join(f"{q['key']}={q['value']}" for q in query)
    return {
        "info": {
            "name": f"ASLMS NAPIX: {label}",
            "description": TEMPLATE_NOTE,
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "item": [
            {
                "name": "00 Access Token",
                "event": [{"listen": "test", "script": {"type": "text/javascript", "exec": TOKEN_TEST_EXEC}}],
                "request": {
                    "auth": {
                        "type": "basic",
                        "basic": [
                            {"key": "password", "value": "{{client_secret}}", "type": "string"},
                            {"key": "username", "value": "{{client_key}}", "type": "string"},
                        ],
                    },
                    "method": "POST",
                    "header": [{"key": "Content-Type", "value": TOKEN_CONTENT_TYPE, "type": "text"}],
                    "body": {
                        "mode": "urlencoded",
                        "urlencoded": [
                            {"key": "grant_type", "value": "client_credentials", "type": "text"},
                            {"key": "scope", "value": "napix", "type": "text"},
                        ],
                    },
                    "url": {"raw": tok, **_url_parts(tok)},
                },
                "response": [],
            },
            {
                "name": f"01 {label}",
                "request": {
                    "method": p.method,
                    "header": [
                        {"key": "Authorization", "value": "Bearer {{access_token}}", "type": "text"},
                        {"key": "Accept", "value": ACCEPT, "type": "text"},
                    ],
                    "url": {"raw": f"{p.url}?{raw_query}", **_url_parts(p.url), "query": query},
                },
                "response": [],
            },
        ],
        "event": POSTMAN_SCRIPTS,
        "variable": [
            {"key": "client_key", "value": ""},
            {"key": "client_secret", "value": ""},
            {"key": "dept_id", "value": ""},
            {"key": "auth_key", "value": ""},
            {"key": "access_token", "value": ""},
            {"key": "hash_key", "value": DEFAULT_HASH_KEY},
            {"key": "version", "value": settings.napix_version},
        ],
    }


# ------------------------------------------------------------------------------------------------ validation


class HeldMasters:
    """The masters a typed code must be one of (decision 8: never an invented code), read from the database once per
    check. Tests may pass a stand-in."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self._est: list[str] | None = None
        self._states: set[int] | None = None

    def est_codes(self) -> list[str]:
        if self._est is None:
            rows = self.session.scalars(select(Court.est_code).where(Court.est_code.is_not(None))).all()
            self._est = sorted(c for c in rows if c)
        return self._est

    def state_codes(self) -> set[int]:
        if self._states is None:
            rows = self.session.scalars(select(HighCourt.napix_state_code)).all()
            self._states = {int(c) for c in rows if c is not None}
        return self._states

    def case_type_held(self, est_code: str, code: int) -> bool:
        found = self.session.scalar(
            select(CaseType.id)
            .join(Court, Court.id == CaseType.court_id)
            .where(Court.est_code == est_code, CaseType.case_type_code == code)
            .limit(1)
        )
        return found is not None


def _date_ok(text_value: str, today: date) -> date | str:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text_value):
        return "A date as yyyy-mm-dd"
    try:
        d = date.fromisoformat(text_value)
    except ValueError:
        return "Not a real date"
    if d < date(1950, 1, 1) or d > today + timedelta(days=60):
        return "A date from 1950-01-01 to 60 days from today"
    return d


def _check(
    masters: HeldMasters, spec: InputSpec, value: str, form: dict[str, str], settings: Settings, today: date
) -> tuple[Any, str | None]:
    """(the typed value, an error message or None) for one parameter (decision 8)."""
    rule = spec.rule
    if rule == "est_code":
        code = value.upper()
        held = masters.est_codes()
        if code not in held:
            listed = ", ".join(held) if held else "none held yet"
            return code, f"Not a court code ASLMS holds ({listed})"
        return code, None
    if rule == "state_code":
        if not re.fullmatch(r"\d{1,3}", value) or int(value) not in masters.state_codes():
            return value, "Not a state code ASLMS holds from the state master"
        return str(int(value)), None
    if rule == "cnr":
        cnr = value.upper()
        if not CNR_RE.match(cnr):
            return cnr, "A CNR is 4 letters and 12 digits; one CNR per send"
        return cnr, None
    if rule == "date":
        out = _date_ok(value, today)
        return (None, out) if isinstance(out, str) else (out, None)
    if rule in ("digits5", "digits6", "digits7"):
        n = int(rule[-1])
        if not re.fullmatch(rf"\d{{1,{n}}}", value):
            return value, f"1 to {n} digits"
        return (int(value) if spec.name in ("reg_no", "fil_no") else value), None
    if rule == "case_type":
        if not re.fullmatch(r"\d{1,6}", value):
            return value, "The case type's number from the Case Type Master"
        est = (form.get("est_code") or settings.napix_est_code or "").strip().upper()
        if est not in masters.est_codes():
            return int(value), "Choose a court code ASLMS holds first"
        if not masters.case_type_held(est, int(value)):
            return int(value), f"Not a case type ASLMS holds for {est}"
        return int(value), None
    if rule == "year":
        if not re.fullmatch(r"\d{4}", value) or not 1950 <= int(value) <= today.year:
            return value, f"A year from 1950 to {today.year}"
        return int(value), None
    if rule == "pend_disp":
        v = value.upper()
        return (v, None) if v in ("P", "D") else (v, "P (pending) or D (disposed)")
    if rule == "party_name":
        # the sample picker's cap (no NAPIX limit is documented for party names; court search sends them unbounded),
        # so a held party sample is sendable unedited (design followups-oct, decision 10)
        if not napix_samples.name_passes(value, napix_samples.MAX_PARTY):
            return value, "3 to 200 letters, digits, spaces and . , ' & ( ) / -, not only X"
        return value, None
    if rule == "advocate_name":  # HC spec §6.8
        if not napix_samples.name_passes(value, napix_samples.MAX_ADVOCATE):
            return value, "3 to 99 letters, digits, spaces and . , ' & ( ) / -, not only X"
        return value, None
    return value, None  # pragma: no cover — every rule is listed above


def _today(now: datetime | None = None) -> date:
    from aslms.services.reporting_common import today_ist

    return today_ist(now)


def check_values(
    session: Session,
    settings: Settings,
    key: str,
    values: dict[str, Any],
    masters: HeldMasters | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """The form's values typed and checked (decision 8), keyed by the sample's names; raises `InvalidInput`."""
    masters = masters or HeldMasters(session)
    specs = INPUTS[key]
    names = [s.name for s in specs]
    form = {str(k): ("" if v is None else str(v).strip()) for k, v in (values or {}).items()}
    errors: dict[str, str] = {k: "This API does not take this parameter" for k in form if k not in names}
    typed: dict[str, Any] = {}
    today = today or _today()
    for spec in specs:
        value = form.get(spec.name, "")
        if not value:
            errors[spec.name] = "Required"
            continue
        out, error = _check(masters, spec, value, form, settings, today)
        if error:
            errors[spec.name] = error
        else:
            typed[sample_key(spec.name)] = out
    if errors:
        raise InvalidInput(errors)
    return typed


def validate(
    session: Session,
    settings: Settings,
    key: str,
    values: dict[str, Any],
    held: Sample | NoSample | None = None,
) -> Sample:
    """The form's values as a `Sample` labelled "The values in the form" (decision 8); `edited` when its plain string
    differs from the held sample's. An unedited form keeps the held sample's source (its case and stored copy). The
    typed form is compared only with a sample whose case the sender may see: against a hidden sample it is always
    `edited`, with no source case, so neither the answer nor the audit row says whether a guess matched (design
    followups-oct, decision 12)."""
    typed = check_values(session, settings, key, values)
    e = system_health.entry(key)
    plain = preview(settings, key, e.invoke, typed).plain
    if (
        isinstance(held, Sample)
        and held.case_visible
        and preview(settings, key, e.invoke, held.values).plain == plain
    ):
        return Sample(
            values=typed,
            label=held.label,
            source_case_id=held.source_case_id,
            source_ref_no=held.source_ref_no,
            stored_sha256=held.stored_sha256,
            source_cnr=held.source_cnr,
            case_visible=held.case_visible,
            edited=False,
        )
    return Sample(values=typed, label=FORM_LABEL, edited=True)


# ------------------------------------------------------------------------------------------------ the form


def _text_of(value: Any) -> str:
    return value.isoformat() if isinstance(value, date) else ("" if value is None else str(value))


def _dummy(spec: InputSpec) -> Any:
    """A stand-in that lets the API's method build its request while a value is not typed yet; the plain string
    shows the placeholder instead (never a value that is sent)."""
    if spec.rule == "date":
        return _today()
    if spec.rule in ("case_type", "year") or spec.name in ("reg_no", "fil_no"):
        return 0
    return ""


def form(
    settings: Settings, key: str, chosen: Sample | NoSample
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, str]]:
    """(the form's rows, the values for the preview, the placeholders) of the held sample (decision 6)."""
    hidden = chosen.hidden_from_caller() if isinstance(chosen, Sample) else frozenset()
    rows: list[dict[str, Any]] = []
    values: dict[str, Any] = {}
    marks: dict[str, str] = {}
    for spec in INPUTS[key]:
        skey = sample_key(spec.name)
        hint = spec.note
        if isinstance(chosen, Sample) and skey in chosen.values and skey not in hidden:
            value, source, prefilled = chosen.values[skey], "held", True
            if spec.name in ("est_code", "state_code"):
                source = "settings"
        elif spec.name == "est_code":
            value, source, prefilled = settings.napix_est_code, "settings", True
        elif spec.name == "state_code":
            value, source, prefilled = settings.napix_state_code, "settings", True
        else:
            value, source, prefilled = None, "empty", False
            if isinstance(chosen, Sample) and skey in hidden:
                hint = HINT_HIDDEN.get(spec.rule, HINT_HIDDEN_OTHER)
            elif isinstance(chosen, NoSample):
                hint = chosen.reason
        if prefilled:
            values[skey] = value
        else:
            values[skey] = _dummy(spec)
            marks[spec.name] = PLACEHOLDERS.get(spec.rule, "‹type a value›")
        rows.append(
            {
                "name": spec.name,
                "value": _text_of(value) if prefilled else "",
                "prefilled": prefilled,
                "source": source,
                "editable": True,
                "mandatory": spec.mandatory,
                "required": spec.required,
                "format": spec.format,
                "meaning": spec.meaning,
                "hint": hint,
            }
        )
    return rows, values, marks


def request_part(settings: Settings, e: system_health.ApiEntry, p: RequestPreview) -> dict[str, Any]:
    """The request of the console for one preview: method, URL, plain string, envelope, headers, cURL template."""
    return {
        "api": e.key,
        "label": e.label,
        "method": p.method,
        "method_note": METHOD_NOTE_POST if p.method == "POST" else None,
        "url": p.url,
        "plain": p.plain,
        "plain_sha256": p.plain_sha256,
        "plain_complete": p.complete,
        "no_input_note": NO_INPUT_NOTE if not INPUTS[e.key] else None,
        "envelope": envelope(settings, p),
        "headers": headers(),
        "request_token": p.request_token,
        "templates": {
            "curl": curl_template(p, p.request_token is not None, settings.napix_version),
            "note": TEMPLATE_NOTE,
        },
    }


def preview_values(
    session: Session, settings: Settings, key: str, values: dict[str, Any]
) -> tuple[system_health.ApiEntry, RequestPreview]:
    """The checked form's preview (`POST …/preview` and `…/postman`); raises `InvalidInput`."""
    e = system_health.entry(key)
    typed = check_values(session, settings, key, values)
    return e, preview(settings, key, e.invoke, typed)


# ------------------------------------------------------------------------------------------------ the last send


def _who(user_id: uuid.UUID | None, me: uuid.UUID | None) -> str:
    return "you" if me is not None and user_id == me else "person"


def _plain_of(key: str, params: dict[str, Any]) -> str:
    order = [s.name for s in INPUTS[key]]
    ordered = {k: params[k] for k in order if k in params}
    ordered.update({k: v for k, v in params.items() if k not in ordered})
    return build_plain({k: str(v) for k, v in ordered.items()})


def _status(ok: bool | None, answered: bool | None) -> str:
    if ok:
        return "ok"
    return "warn" if answered else "down"


def case_params(key: str) -> frozenset[str]:
    """The plain parameters of this API that carry case data: a name, a CNR, a case or a filing number."""
    keys = napix_samples.CASE_KEYS | napix_samples.NAME_KEYS
    return frozenset(s.name for s in INPUTS[key] if sample_key(s.name) in keys)


def params_shown(
    session: Session, user: User | Member | None, actor_id: uuid.UUID | None, after: dict[str, Any]
) -> bool:
    """Whether a past send's case values may be shown to this viewer (the Visibility paragraph; decision 6): the
    viewer sent them, or holds `cases.view_all`, or they are the held sample of a case the viewer can see, or a held
    sample with no source case (a discovery term, shown since row 109). Typed values of another person are not."""
    if user is None:
        return False
    if actor_id is not None and actor_id == napix_window.user_id_of(user):
        return True
    if full_answer_allowed(session, user):
        return True
    if after.get("edited") is not False:
        return False
    ref_no = (after.get("sample") or {}).get("case_ref_no")
    if not ref_no:
        return True
    # a send recorded before the renumbering of 25 Oct 2026 names the case by its old number (case-ref-court-prefix)
    case_id = session.scalar(select(Case.id).where(Case.ref_no == current_case_ref_no(ref_no)))
    return case_id is not None and bool(access_basis(session, user, case_id))


def last_send(
    session: Session,
    settings: Settings,
    user: User | Member | None,
    key: str,
    form_sha256: str | None = None,
    reset_at: datetime | None = None,
) -> dict[str, Any] | None:
    """The latest `napix.api_tested` row of this API, anyone's (decision 5). Rows written before this item carry no
    parameters: their new facts are None and `recorded` is false. A name, a CNR, a case or a filing number the viewer
    may not see (`params_shown`) reads `‹not shown›` in the plain string, and `params_sha256` is then None (a hash
    of a name can be checked against guesses)."""
    row = session.execute(
        text(
            """
            SELECT created_at, actor_user_id, after FROM audit_log
            WHERE action = :action AND after->>'api' = :api
            ORDER BY created_at DESC, id DESC LIMIT 1
            """
        ),
        {"action": TEST_ACTION, "api": key},
    ).first()
    if row is None:
        return None
    created_at, actor_id, after = row
    after = after or {}
    e = system_health.entry(key)
    recorded = "params" in after
    params = after.get("params") if recorded else None
    ps = after.get("params_sha256")
    ps_out = ps
    plain = None
    if isinstance(params, dict):
        hidden = case_params(key) & params.keys()
        if hidden and not params_shown(session, user, actor_id, after):
            params = {k: (NOT_SHOWN if k in hidden else v) for k, v in params.items()}
            ps_out = None
        plain = _plain_of(key, params)
    st = after.get("structure") if recorded else None
    paths = [x["path"] for x in (st or {}).get("paths", [])]
    rid = after.get("response_id")
    url = display_url(settings.napix_base_url, after.get("path") or e.path)
    return {
        "at": to_ist(created_at),
        "by": _who(actor_id, napix_window.user_id_of(user) if user is not None else None),
        "recorded": recorded,
        "edited": after.get("edited") if recorded else None,
        "ok": bool(after.get("ok")),
        "answered": bool(after.get("answered")),
        "status": _status(after.get("ok"), after.get("answered")),
        "reason": system_health.plain_reason(
            None if after.get("ok") else after.get("error_family"),
            after.get("napix_status"),
            None if after.get("ok") else after.get("http_status"),
        ),
        "method": e.method,
        "url": url,
        "plain": plain,
        "params_sha256": ps_out,
        "http_status": after.get("http_status"),
        "http_meaning": napix_reference.http_meaning(after.get("http_status"), after.get("error_family")),
        "napix_status": after.get("napix_status"),
        "napix_meaning": napix_reference.napix_meaning(after.get("napix_status")),
        "error_family": after.get("error_family"),
        "duration_ms": int(after.get("duration_ms") or 0),
        "attempts": int(after.get("attempts") or 0),
        "remaining": after.get("remaining"),
        "rate_limit": after.get("rate_limit") if recorded else None,
        "window_reset_at": to_ist(reset_at),
        "token_verified": after.get("token_verified") if recorded else None,
        "summary": after.get("summary"),
        "structure": st,
        "inventory_diff": inventory_diff(key, paths) if st else None,
        "response_id": rid,
        "response_available": rid is not None,
        "same_plain_as_form": (ps == form_sha256) if (ps and form_sha256) else None,
    }


def latest_answer(
    session: Session, settings: Settings, user: User | Member | None, key: str, now: datetime | None = None
) -> dict[str, Any] | None:
    """The latest stored answer of this API in 7 days (decision 5): the newest `ok` call-log row and its
    `napix_responses` row by `(api, params_sha256)`, newest `last_seen_at`. The structure is computed on read."""
    e = system_health.entry(key)
    now = now or datetime.now(UTC)
    call = session.execute(
        text(
            """
            SELECT params_sha256, called_at, user_id FROM napix_call_log
            WHERE api = :api AND ok AND called_at >= :since
            ORDER BY called_at DESC, id DESC LIMIT 1
            """
        ),
        {"api": e.path, "since": now - system_health.WINDOW},
    ).first()
    if call is None:
        return None
    ps, called_at, user_id = call
    # the size first, in the database: the payload is read only when it is within HEALTH_RAW_MAX_BYTES (design
    # followups-oct, decision 9)
    stored = session.execute(
        text(
            """
            SELECT id, octet_length(payload::text) AS bytes FROM napix_responses
            WHERE api = :api AND params_sha256 = :ps
            ORDER BY last_seen_at DESC, id DESC LIMIT 1
            """
        ),
        {"api": e.path, "ps": ps},
    ).first()
    me = napix_window.user_id_of(user) if user is not None else None
    by = "background" if user_id is None else _who(user_id, me)
    if stored is None:
        return {
            "at": to_ist(called_at),
            "by": by,
            "structure": None,
            "inventory_diff": None,
            "response_id": None,
            "response_available": False,
            "response_too_large": False,
        }
    rid, size = stored
    if int(size or 0) > settings.health_raw_max_bytes:
        return {
            "at": to_ist(called_at),
            "by": by,
            "structure": None,
            "inventory_diff": None,
            "response_id": rid,
            "response_available": True,
            "response_too_large": True,
        }
    payload = session.scalar(text("SELECT payload FROM napix_responses WHERE id = :id"), {"id": rid})
    return {
        "at": to_ist(called_at),
        "by": by,
        "structure": structure(payload),
        "inventory_diff": inventory_diff(key, structure_paths(payload)),
        "response_id": rid,
        "response_available": True,
        "response_too_large": False,
    }


# ------------------------------------------------------------------------------------------------ the console


def full_answer_allowed(session: Session, user: User | Member | None) -> bool:
    """Decision 7: the full decrypted answer needs `cases.view_all` (State-wide case visibility) as well."""
    return user is not None and access.has(session, user, Permission.CASES_VIEW_ALL)


def console(
    session: Session, settings: Settings, user: User | Member | None, key: str, now: datetime | None = None
) -> dict[str, Any]:
    """`ConsoleOut` (decision 2): the pre-filled form, the request built from `hc.py`, the Send state, the last send,
    the latest stored answer and the documentation link. Never calls NAPIX; not audited. Raises `UnknownApi`."""
    e = system_health.entry(key)
    now = now or datetime.now(UTC)
    with_timeout(session, settings.report_statement_timeout_seconds)
    chosen = napix_samples.choose(session, settings, key, user)
    rows, values, marks = form(settings, key, chosen)
    p = preview(settings, key, e.invoke, values, marks)
    window = napix_window.current(session, settings, now)
    send = system_health.send_state(session, settings, user, key, now)
    doc = napix_reference.doc_link(key)
    return {
        **request_part(settings, e, p),
        "fields": rows,
        "sample": {
            "available": isinstance(chosen, Sample),
            "label": chosen.label if isinstance(chosen, Sample) else None,
            "reason": chosen.reason if isinstance(chosen, NoSample) else None,
        },
        "send": send,
        "last_send": last_send(session, settings, user, key, p.plain_sha256, window.next_reset_at),
        "latest_answer": latest_answer(session, settings, user, key, now),
        "doc": {**doc, "available": doc_available(settings, doc["doc"])},
        "full_answer_allowed": full_answer_allowed(session, user),
        "not_saved_note": NOT_SAVED,
        "full_answer_note": None if full_answer_allowed(session, user) else FULL_ANSWER_DENIED,
    }


# ------------------------------------------------------------------------------------------------ the full answer


def stored_response(
    session: Session,
    settings: Settings,
    user: User | Member | None,
    key: str,
    source: str,
    response_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """The verbatim decrypted answer of a send (`source=send`, by its id) or the latest stored answer
    (`source=latest`) (decision 7): `Forbidden` without `cases.view_all`; `NoResponse`; `TooLarge` over
    `HEALTH_RAW_MAX_BYTES` (measured in the database before the payload is read)."""
    e = system_health.entry(key)
    if not full_answer_allowed(session, user):
        raise Forbidden(FULL_ANSWER_DENIED, code="forbidden")
    if source == "send":
        if response_id is None:
            raise NoResponse("no stored answer for this send")
        rid = response_id
    elif source == "latest":
        latest = latest_answer(session, settings, user, key)
        if latest is None or latest["response_id"] is None:
            raise NoResponse("no stored answer for this API in the last 7 days")
        rid = latest["response_id"]
    else:
        raise NoResponse("unknown source")
    meta = session.execute(
        text(
            """
            SELECT id, fetched_at, last_seen_at, token_verified, octet_length(payload::text) AS bytes
            FROM napix_responses WHERE id = :id AND api = :api
            """
        ),
        {"id": rid, "api": e.path},
    ).first()
    if meta is None:
        raise NoResponse("no stored answer for this request")
    if int(meta.bytes) > settings.health_raw_max_bytes:
        raise TooLarge(int(meta.bytes), settings.health_raw_max_bytes)
    payload = session.scalar(text("SELECT payload FROM napix_responses WHERE id = :id"), {"id": rid})
    return {
        "api": key,
        "source": source,
        "response_id": meta.id,
        "fetched_at": to_ist(meta.fetched_at),
        "last_seen_at": to_ist(meta.last_seen_at),
        "token_verified": meta.token_verified,
        "bytes": int(meta.bytes),
        "payload": payload,
    }


def record_view(session: Session, actor: Actor, key: str, body: dict[str, Any]) -> None:
    """The audit row of an opening of the full answer (`napix.response_viewed`): never the payload."""
    write_audit(
        session,
        actor,
        VIEW_ACTION,
        "napix",
        None,
        after={
            "api": key,
            "response_id": str(body["response_id"]),
            "source": body["source"],
            "bytes": body["bytes"],
        },
    )


# ------------------------------------------------------------------------------------------------ the documents

_PIN_CACHE: dict[tuple[str, int, int], bool] = {}


def doc_path(settings: Settings, doc: str) -> Path:
    """The pinned NAPIX document on this server; `KeyError` for an unknown id, `DocMissing` when the file is absent
    or its SHA-256 differs from the pin (decision 12)."""
    meta = napix_reference.DOCS[doc]
    path = Path(settings.napix_docs_dir) / meta["file"]
    try:
        st = path.stat()
    except OSError:
        raise DocMissing("The NAPIX documents are not installed on this server") from None
    cache_key = (str(path), st.st_size, st.st_mtime_ns)
    ok = _PIN_CACHE.get(cache_key)
    if ok is None:
        ok = hashlib.sha256(path.read_bytes()).hexdigest() == meta["sha256"]
        _PIN_CACHE[cache_key] = ok
    if not ok:
        raise DocMissing("The NAPIX documents are not installed on this server")
    return path


def doc_available(settings: Settings, doc: str) -> bool:
    try:
        doc_path(settings, doc)
    except DocMissing:
        return False
    return True


def docs_list(settings: Settings) -> list[dict[str, Any]]:
    return [
        {
            "doc": doc,
            "title": meta["title"],
            "pages": meta["pages"],
            "available": doc_available(settings, doc),
        }
        for doc, meta in napix_reference.DOCS.items()
    ]


def dumps(value: Any) -> str:
    return json.dumps(value, default=str)


# ------------------------------------------------------------------------------------------------ the Postman scripts
# The collection-level scripts of `docs/postman/NAPIX eCourt APIs.postman_collection.json` (encrypt from `input`;
# decrypt and verify the answer) and its token request's test script. A test keeps them equal to the file.
POSTMAN_SCRIPTS: list[dict[str, Any]] = [
    {
        "listen": "prerequest",
        "script": {
            "type": "text/javascript",
            "packages": {},
            "requests": {},
            "exec": [
                "const CryptoJS = require('crypto-js');\r",
                "\r",
                "// AES-128 needs exactly 16 bytes: cut longer keys, pad shorter ones with zero bytes\r",
                "function napixKey(k) {\r",
                "  const bytes = CryptoJS.enc.Utf8.parse((k || '').trim());\r",
                "  const words = bytes.words.slice(0, 4);\r",
                "  while (words.length < 4) words.push(0);\r",
                "  return CryptoJS.lib.WordArray.create(words, 16);\r",
                "}\r",
                "\r",
                "const q = pm.request.url.query.toObject(true);\r",
                "if (Object.prototype.hasOwnProperty.call(q, 'input')) {\r",
                "  const input = pm.variables.replaceIn(q.input || '');\r",
                "  const key = napixKey(pm.environment.get('auth_key'));\r",
                "  const reqStr = CryptoJS.AES.encrypt(CryptoJS.enc.Utf8.parse(input), key, {\r",
                "    iv: key, mode: CryptoJS.mode.CBC, padding: CryptoJS.pad.Pkcs7\r",
                "  }).toString();\r",
                "  const token = CryptoJS.HmacSHA256(input, pm.environment.get('hash_key'))\r",
                "                        .toString(CryptoJS.enc.Hex);\r",
                "  pm.variables.set('request_str_raw', reqStr);\r",
                "  pm.variables.set('request_str', encodeURIComponent(reqStr));\r",
                "  pm.variables.set('request_token', token);\r",
                "  pm.request.removeQueryParams('input');\r",
                "  console.log('Input string:', input);\r",
                "}",
            ],
        },
    },
    {
        "listen": "test",
        "script": {
            "type": "text/javascript",
            "packages": {},
            "requests": {},
            "exec": [
                "const CryptoJS = require('crypto-js');\r",
                "\r",
                "function napixKey(k) {\r",
                "  const bytes = CryptoJS.enc.Utf8.parse((k || '').trim());\r",
                "  const words = bytes.words.slice(0, 4);\r",
                "  while (words.length < 4) words.push(0);\r",
                "  return CryptoJS.lib.WordArray.create(words, 16);\r",
                "}\r",
                "\r",
                "// Decrypts a NAPIX Base64 string; throws a clear error if it cannot\r",
                "function decryptNapix(cipherText) {\r",
                "  const key = napixKey(pm.environment.get('auth_key'));\r",
                "  const clean = String(cipherText).replace(/\\s+/g, '');\r",
                "  const bytes = CryptoJS.AES.decrypt(\r",
                "    { ciphertext: CryptoJS.enc.Base64.parse(clean) }, key,\r",
                "    { iv: key, mode: CryptoJS.mode.CBC, padding: CryptoJS.pad.Pkcs7 });\r",
                "  if (bytes.sigBytes <= 0) throw new Error('decryption gave no data (wrong key or "
                "damaged response)');\r",
                "  try { return CryptoJS.enc.Utf8.stringify(bytes); }\r",
                "  catch (e) { throw new Error('decrypted data is not readable text (wrong key?)'); }\r",
                "}\r",
                "\r",
                "// Read the body even if the server adds extra text around the JSON\r",
                "const raw = pm.response.text();\r",
                "let body = null;\r",
                "try { body = JSON.parse(raw); } catch (e) {\r",
                "  const s = raw.indexOf('{'), t = raw.lastIndexOf('}');\r",
                "  if (s >= 0 && t > s) { try { body = JSON.parse(raw.slice(s, t + 1)); } catch (e2) { "
                "body = null; } }\r",
                "}\r",
                "\r",
                "let output;\r",
                "if (body && body.access_token) {\r",
                "  output = 'Access token received.';\r",
                "} else if (body && body.response_str) {\r",
                "  try {\r",
                "    const plain = decryptNapix(body.response_str);\r",
                "    pm.test('Response decrypted', () => {});\r",
                "    const check = CryptoJS.HmacSHA256(plain, "
                "pm.environment.get('hash_key')).toString(CryptoJS.enc.Hex);\r",
                "    pm.test('Response token matches (data not altered)', () => "
                "pm.expect(check).to.eql(body.response_token));\r",
                "    try { output = JSON.stringify(JSON.parse(plain), null, 2); } catch (e) { output = "
                "plain; }\r",
                "  } catch (e) {\r",
                "    pm.test('Response decrypted', () => { throw e; });\r",
                "    output = 'Could not decrypt: ' + e.message;\r",
                "  }\r",
                "} else if (body && typeof body.status === 'string') {\r",
                "  try { output = 'Server status (decrypted): ' + decryptNapix(body.status); }\r",
                "  catch (e) { output = 'Server status (could not decrypt, ' + e.message + '): ' + "
                "body.status; }\r",
                "} else {\r",
                "  output = 'Not an encrypted response:\\n' + raw;\r",
                "}\r",
                "\r",
                "console.log(output);\r",
                "pm.visualizer.set('<pre "
                'style="white-space:pre-wrap;font-family:monospace">{{data}}</pre>\', { data: output '
                "});",
            ],
        },
    },
]

TOKEN_TEST_EXEC: list[str] = [
    "// ===== TOKEN · saves the NAPIX access token (Subscriber Manual §2.2) =====\r",
    "const j = pm.response.json();\r",
    'pm.test("access_token received", () => pm.expect(j.access_token).to.be.a("string"));\r',
    'pm.environment.set("access_token", j.access_token);\r',
    'console.log("════ TOKEN ════");\r',
    'console.log("[T] HTTP", pm.response.code, "| token_type:", j.token_type, "| scope:", j.scope,\r',
    '  "| expires_in:", j.expires_in, "s | X-Global-Transaction-ID:", '
    'pm.response.headers.get("X-Global-Transaction-ID"));',
]
