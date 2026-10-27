"""The start-up safety check (design deployment-checklist, decision 3): `aslms ops preflight` runs first in the
Compose `init` and `migrate` services, so with an error nothing else starts.

With `APP_ENV=prod` every rule below is an error; with `dev` or `test` each is a warning:
- `ASLMS_JWT_SECRET` shorter than 32 characters;
- `POSTGRES_PASSWORD`, `ASLMS_APP_PASSWORD`, `REDIS_PASSWORD` and `ASLMS_READONLY_PASSWORD` (required from Part B: the
  exporters connect as `aslms_readonly`) shorter than 16 characters, a known default, equal to the role's user name,
  equal to another of them, or holding a character other than letters, digits, `_` and `-` (Compose puts them into
  URLs unencoded);
- a `REDIS_URL` without a password; a `PORTAL_BASE_URL` that is not `https://`; `COOKIE_SECURE=false`;
- a mail service that cannot deliver a sign-in code: the console backend, a backend that cannot be built, or the
  Mailtrap sandbox (`sandbox.api.mailtrap.io` catches mail and never delivers it);
- monitoring (Part B, decision 22): `GRAFANA_ADMIN_PASSWORD` and each password of `FLOWER_BASIC_AUTH` (`user:password`,
  comma-separated) missing, shorter than 16 characters, a known default, equal to its user name or to another
  password; a `FLOWER_BASIC_AUTH` entry without a user or a password; `COMPOSE_PROFILES` without `monitoring` (plan
  §8.2: monitoring from the pilot stage).
Without `OPS_ALERT_EMAIL` or `SMTP_HOST` the monitoring alerts are shown in Grafana and Alertmanager only: always a
warning (decision 25). A super admin password still set after the super admin exists is always a warning (`superadmin_password_left`).

Two rules are fatal at every `APP_ENV` (design pre-pilot-hardening, decisions 2 and 6): an `APP_ENV` other than `dev`,
`test` or `prod` (refused when the settings load; `aslms ops preflight` reports it by name), and a libpq older than 17
(`libpq_floor`: PgBouncer transaction pooling with protocol-level prepared statements needs it; a build defect).
A third is fatal everywhere too (design followups-oct, decision 25): `no_local_model`, an installed onnxruntime (or a
PyMuPDF add-on that brings one) or its marker bytes in the installed `pymupdf` package, and (design `assistant-ollama`,
decision 15) a model runtime (`llama-cpp-python`, `torch`, `transformers`, `vllm`, `gpt4all`, `ctransformers`): no
model inside ASLMS's processes; the only model is the Ollama server named by `ASSISTANT_OLLAMA_URL`
(ASSISTANT_MODE=ollama), on Government infrastructure. A fourth (decision 12): `no_cloud_model`, an
`ASSISTANT_OLLAMA_MODEL` naming a cloud model or an `ASSISTANT_OLLAMA_URL` on ollama.com, with user information or a
query. In ollama mode the address must resolve to loopback, private or link-local addresses only (an error in prod, a
warning otherwise; a name that does not resolve is a warning). The connection budget (`connection_budget`, decision 4)
is an error in prod and a warning otherwise.

A finding names the variable and the rule; it never carries a value."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

FATAL = "fatal"
ERROR = "error"
WARNING = "warning"
LIBPQ_MIN = 170000
JWT_MIN = 32
PASSWORD_MIN = 16
KNOWN_DEFAULTS = frozenset(
    {"aslms", "aslms_app", "aslms_readonly", "postgres", "password", "changeme", "admin", "flower"}
)
MAILTRAP_SANDBOX_HOST = "sandbox.api.mailtrap.io"
URL_SAFE_RE = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass(frozen=True)
class Finding:
    level: str  # fatal | error | warning
    variable: str
    message: str

    def line(self) -> str:
        return f"{self.level}: {self.variable}: {self.message}"


class PreflightFailed(RuntimeError):
    def __init__(self, findings: list[Finding]) -> None:
        self.findings = findings
        super().__init__(f"{len(findings)} preflight error(s): " + ", ".join(f.variable for f in findings))


def _secret(value: Any) -> str:
    if value is None:
        return ""
    getter = getattr(value, "get_secret_value", None)
    return getter() if getter else str(value)


def _passwords(settings: Any) -> list[tuple[str, str, str]]:
    """(variable, value, user name) for each database and Redis password the stack uses."""
    out = [
        (
            "POSTGRES_PASSWORD",
            _secret(getattr(settings, "postgres_password", None)),
            getattr(settings, "postgres_user", None) or "aslms",
        ),
        ("ASLMS_APP_PASSWORD", _secret(settings.aslms_app_password), "aslms_app"),
        ("REDIS_PASSWORD", _secret(getattr(settings, "redis_password", None)), "default"),
    ]
    out.append(
        (
            "ASLMS_READONLY_PASSWORD",
            _secret(getattr(settings, "aslms_readonly_password", None)),
            "aslms_readonly",
        )
    )
    return out


def _monitoring_passwords(settings: Any) -> tuple[list[tuple[str, str, str]], list[tuple[str, str]]]:
    """(variable, value, user name) for the Grafana admin and each Flower login, and the format findings of
    `FLOWER_BASIC_AUTH`. These go into no URL, so any character is allowed."""
    out = [("GRAFANA_ADMIN_PASSWORD", _secret(getattr(settings, "grafana_admin_password", None)), "admin")]
    found: list[tuple[str, str]] = []
    flower = _secret(getattr(settings, "flower_basic_auth", None)).strip()
    if not flower:
        out.append(("FLOWER_BASIC_AUTH", "", ""))
    for entry in [e.strip() for e in flower.split(",")] if flower else []:
        user, sep, password = entry.partition(":")
        if not sep or not user.strip() or not password:
            found.append(("FLOWER_BASIC_AUTH", "must be user:password (comma-separated for more logins)"))
            continue
        out.append(("FLOWER_BASIC_AUTH", password, user.strip()))
    return out, found


def _strength(name: str, value: str, user: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if not value:
        return [(name, "is not set")]
    if len(value) < PASSWORD_MIN:
        found.append((name, f"is shorter than {PASSWORD_MIN} characters"))
    if value.lower() in KNOWN_DEFAULTS:
        found.append((name, "is a known default"))
    if user and value.lower() == user.lower():
        found.append((name, "equals its user name"))
    return found


def _password_rules(settings: Any) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    pwds = _passwords(settings)
    for name, value, user in pwds:
        found.extend(_strength(name, value, user))
        if value and not URL_SAFE_RE.match(value):
            found.append((name, "may hold only letters, digits, _ and - (it goes into a URL unencoded)"))
    monitoring, format_findings = _monitoring_passwords(settings)
    for name, value, user in monitoring:
        found.extend(_strength(name, value, user))
    found.extend(format_findings)
    every = pwds + monitoring
    for i, (name, value, _user) in enumerate(every):
        for other, other_value, _other_user in every[i + 1 :]:
            if value and value == other_value:
                found.append((other, f"equals {name}; every password must be different"))
    return found


def _monitoring_rules(settings: Any) -> list[tuple[str, str]]:
    profiles = {p.strip() for p in (getattr(settings, "compose_profiles", "") or "").split(",")}
    if "monitoring" not in profiles:
        return [
            ("COMPOSE_PROFILES", "does not include monitoring (plan §8.2: monitoring from the pilot stage)")
        ]
    return []


def alert_mail_warning(settings: Any) -> Finding | None:
    """Decision 25: without a recipient or an SMTP relay the alerts are not mailed (a warning, never a refusal)."""
    if not (getattr(settings, "ops_alert_email", None) or "").strip():
        return Finding(WARNING, "OPS_ALERT_EMAIL", "is not set; monitoring alerts are shown in Grafana only")
    if not (getattr(settings, "smtp_host", None) or "").strip():
        return Finding(WARNING, "SMTP_HOST", "is not set; Alertmanager cannot mail the monitoring alerts")
    return None


def _mail_rule(settings: Any) -> tuple[str, str] | None:
    from aslms.services.mailer import MailError, get_mailer

    backend = (getattr(settings, "mail_backend", None) or "").strip().lower()
    if not backend:
        return ("MAIL_BACKEND", "is not set; sign-in codes cannot be sent")
    try:
        mailer = get_mailer(settings)
    except MailError as exc:
        return ("MAIL_BACKEND", f"cannot be built ({exc}); sign-in codes cannot be sent")
    name = getattr(mailer, "name", "")
    if name == "console":
        return (
            "MAIL_BACKEND",
            "resolves to the console, which delivers nothing; sign-in codes cannot be sent",
        )
    url = getattr(settings, "mailtrap_api_url", None) or ""
    if name == "api" and MAILTRAP_SANDBOX_HOST in url.lower():
        return ("MAILTRAP_API_URL", "points at the Mailtrap sandbox, which never delivers mail")
    return None


def check(settings: Any, component: str = "init") -> list[Finding]:
    """Every rule of decision 3. `component` names the caller (`init`, `migrate`, `backup`); every component checks the
    same rules. Errors only when `APP_ENV=prod`; warnings otherwise; the libpq floor is fatal everywhere."""
    del component  # one rule set for every component
    level = ERROR if getattr(settings, "app_env", "dev") == "prod" else WARNING
    raw: list[tuple[str, str]] = []
    jwt = _secret(settings.aslms_jwt_secret)
    if len(jwt) < JWT_MIN:
        raw.append(("ASLMS_JWT_SECRET", f"is shorter than {JWT_MIN} characters"))
    raw.extend(_password_rules(settings))
    redis_url = getattr(settings, "redis_url", None) or ""
    if not redis_url:
        raw.append(("REDIS_URL", "is not set"))
    elif not urlparse(redis_url).password:
        raw.append(("REDIS_URL", "carries no password"))
    if not (getattr(settings, "portal_base_url", "") or "").lower().startswith("https://"):
        raw.append(("PORTAL_BASE_URL", "does not start with https://"))
    if not getattr(settings, "cookie_secure", True):
        raw.append(("COOKIE_SECURE", "is false; session cookies would travel without Secure"))
    mail = _mail_rule(settings)
    if mail:
        raw.append(mail)
    raw.extend(_monitoring_rules(settings))
    findings = [Finding(level, variable, message) for variable, message in raw]
    findings.extend(assistant_rules(settings))
    findings.extend(ollama_rules(settings))
    warning = alert_mail_warning(settings)
    if warning:
        findings.append(warning)
    budget = connection_budget(settings)
    if budget:
        findings.append(budget)
    floor = libpq_floor()
    if floor:
        findings.append(floor)
    model = no_local_model()
    if model:
        findings.append(model)
    return findings


# "no local model" (CLAUDE.md: all AI goes through the Case Assistant connector interface; design followups-oct,
# decisions 24 and 25, and assistant-ollama, decision 15): no model inside ASLMS's processes — nothing that brings an
# onnxruntime or a model runtime may be installed, and the PDF library must not carry one linked into its native code;
# the only model is the Ollama server named by ASSISTANT_OLLAMA_URL (ASSISTANT_MODE=ollama), on Government
# infrastructure
MODEL_DISTRIBUTIONS = ("onnxruntime", "pymupdf-layout", "pymupdf4llm")
MODEL_MARKERS = (b"onnxruntime", b"OrtGetApiBase", b".onnx")
_CHUNK = 1 << 20


def _distribution_names() -> list[str]:
    from importlib import metadata

    names = []
    for dist in metadata.distributions():
        name = (dist.metadata.get("Name") or "").strip().lower().replace("_", "-")
        if name:
            names.append(name)
    return names


# design assistant-ollama, decision 15: model runtimes and libraries never run inside ASLMS's processes
RUNTIME_DISTRIBUTIONS = ("llama-cpp-python", "torch", "transformers", "vllm", "gpt4all", "ctransformers")


def runtime_distributions(names: list[str] | None = None) -> list[str]:
    """Installed distributions that are a model runtime (decision 15 of `assistant-ollama`)."""
    names = _distribution_names() if names is None else [n.lower().replace("_", "-") for n in names]
    return sorted(n for n in set(names) if n in RUNTIME_DISTRIBUTIONS)


def model_distributions(names: list[str] | None = None) -> list[str]:
    """Installed distributions whose name is `onnxruntime*`, `pymupdf-layout` / `pymupdf_layout` or `pymupdf4llm`."""
    names = _distribution_names() if names is None else [n.lower().replace("_", "-") for n in names]
    return sorted(n for n in set(names) if n.startswith("onnxruntime") or n in MODEL_DISTRIBUTIONS[1:])


def _pymupdf_dir():
    from importlib.util import find_spec
    from pathlib import Path

    spec = find_spec("pymupdf")
    if spec is None or not spec.submodule_search_locations:
        return None
    return Path(next(iter(spec.submodule_search_locations)))


def file_with_marker(root: Any) -> Any:
    """The first file under `root` (native libraries included) holding `onnxruntime`, `OrtGetApiBase` or `.onnx`:
    a runtime linked statically into MuPDF, which a `sys.modules` check cannot see. Read in 1 MB chunks."""
    from pathlib import Path

    if root is None or not Path(root).is_dir():
        return None
    keep = max(len(m) for m in MODEL_MARKERS) - 1
    for path in sorted(p for p in Path(root).rglob("*") if p.is_file()):
        tail = b""
        with path.open("rb") as fh:
            while chunk := fh.read(_CHUNK):
                block = tail + chunk
                if any(m in block for m in MODEL_MARKERS):
                    return path
                tail = block[-keep:]
    return None


def no_local_model(names: list[str] | None = None, pymupdf_root: Any = "default") -> Finding | None:
    """Fatal at every `APP_ENV`, like the libpq floor: an installed onnxruntime (or a PyMuPDF add-on that brings
    one), or the marker bytes in the installed `pymupdf` package. Names the file or distribution, never a value."""
    found = model_distributions(names)
    if found:
        return Finding(FATAL, "no_local_model", f"onnxruntime found in the installed distribution {found[0]}")
    runtimes = runtime_distributions(names)
    if runtimes:
        return Finding(
            FATAL, "no_local_model", f"a model runtime found in the installed distribution {runtimes[0]}"
        )
    hit = file_with_marker(_pymupdf_dir() if pymupdf_root == "default" else pymupdf_root)
    if hit is not None:
        return Finding(FATAL, "no_local_model", f"onnxruntime found in {hit}")
    return None


# the connection budget (design followups-oct, decision 4): what can hold a PgBouncer server connection at once
BUDGET_WORKER = 1
BUDGET_SCHEDULER = 1
BUDGET_RESERVE = 4


def budget_total(settings: Any) -> int:
    return (
        int(settings.napix_request_slots)
        + BUDGET_WORKER
        + BUDGET_SCHEDULER
        + int(settings.db_apart_pool_size)
        + BUDGET_RESERVE
    )


def connection_budget(settings: Any) -> Finding | None:
    """NAPIX_REQUEST_SLOTS + 1 worker + 1 scheduler + DB_APART_POOL_SIZE + a reserve of 4 must not exceed
    PGBOUNCER_DEFAULT_POOL_SIZE: an error at `APP_ENV=prod`, a warning otherwise. Names the variables, never their
    values."""
    if budget_total(settings) <= int(settings.pgbouncer_default_pool_size):
        return None
    level = ERROR if getattr(settings, "app_env", "dev") == "prod" else WARNING
    return Finding(
        level,
        "connection_budget",
        "NAPIX_REQUEST_SLOTS + 1 worker + 1 scheduler + DB_APART_POOL_SIZE + a reserve of 4 exceeds "
        "PGBOUNCER_DEFAULT_POOL_SIZE; raise PgBouncer's pool or lower the slots (docs/operations.md section 18)",
    )


def assistant_rules(settings: Any) -> list[Finding]:
    """Design `assistant`, decision 7: `ASSISTANT_MODE=preview` with `APP_ENV=prod` is an error (the preview is a word
    search for dev and test, never the Case Assistant of the pilot); `sourcetrace` while no SourceTrace connector is
    ready is a warning at every `APP_ENV` (the assistant stays off)."""
    mode = (getattr(settings, "assistant_mode", "off") or "off").strip().lower()
    if mode == "preview" and getattr(settings, "app_env", "dev") == "prod":
        return [
            Finding(
                ERROR,
                "ASSISTANT_MODE",
                "is preview, which is for dev and test only (a word search, not the Case Assistant); set off or "
                "sourcetrace",
            )
        ]
    if mode == "sourcetrace":
        from aslms.services.assistant import assistant_state

        if assistant_state(settings) != "ready":
            return [
                Finding(
                    WARNING,
                    "ASSISTANT_MODE",
                    "is sourcetrace but no SourceTrace connector is ready; the Case Assistant stays off",
                )
            ]
    return []


def _resolve(host: str) -> list[str] | None:
    import socket

    try:
        return sorted({info[4][0] for info in socket.getaddrinfo(host, None)})
    except (OSError, UnicodeError):
        return None


def _private(address: str) -> bool:
    import ipaddress

    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    if ip.is_loopback or ip.is_link_local:
        return True
    if ip.version == 4:
        return any(ip in ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))
    return ip in ipaddress.ip_network("fc00::/7")


def ollama_rules(settings: Any, resolve: Any = None) -> list[Finding]:
    """Design `assistant-ollama`, decision 12. `no_cloud_model` (fatal at every `APP_ENV`): a cloud model name or tag,
    or an address on ollama.com, with user information or a query. In ollama mode, the address must resolve only to
    loopback, private (RFC 1918, fc00::/7) or link-local addresses (an error in prod, a warning otherwise; a name that
    does not resolve is a warning), and `ASSISTANT_OLLAMA_TIMEOUT_SECONDS` above `ASSISTANT_TIMEOUT_SECONDS` less 5 is a
    warning (the model's share is cut). Lines name the variables, never their values."""
    from urllib.parse import urlsplit

    from aslms.services.assistant_ollama import cloud_problems

    findings = [Finding(FATAL, "no_cloud_model", f"{var} {why}") for var, why in cloud_problems(settings)]
    mode = (getattr(settings, "assistant_mode", "off") or "off").strip().lower()
    if mode != "ollama" or findings:
        return findings
    level = ERROR if getattr(settings, "app_env", "dev") == "prod" else WARNING
    host = urlsplit(settings.assistant_ollama_url).hostname or ""
    addresses = (resolve or _resolve)(host)
    if addresses is None:
        findings.append(
            Finding(
                WARNING,
                "ASSISTANT_OLLAMA_URL",
                "does not resolve; the Case Assistant model cannot be reached",
            )
        )
    elif not addresses or not all(_private(a) for a in addresses):
        findings.append(
            Finding(
                level,
                "ASSISTANT_OLLAMA_URL",
                "resolves to an address that is not loopback, private or link-local; the model must run on the "
                "ASLMS host or a Government server on the private network",
            )
        )
    if float(settings.assistant_ollama_timeout_seconds) > float(settings.assistant_timeout_seconds) - 5:
        findings.append(
            Finding(
                WARNING,
                "ASSISTANT_OLLAMA_TIMEOUT_SECONDS",
                "is more than ASSISTANT_TIMEOUT_SECONDS less 5; the model gets at most ASSISTANT_TIMEOUT_SECONDS less 5",
            )
        )
    return findings


def libpq_floor(version: int | None = None) -> Finding | None:
    """Decision 6: a fatal finding when libpq is older than 17. psycopg closes prepared statements with the protocol
    message `Close` (tracked by PgBouncer) only on libpq 17+; older ones send SQL `DEALLOCATE`, which PgBouncer does not
    track in transaction mode. Fatal at every `APP_ENV`: `api`, `worker` and `scheduler` always go through PgBouncer."""
    if version is None:
        import psycopg

        version = psycopg.pq.version()
    if version >= LIBPQ_MIN:
        return None
    return Finding(
        FATAL,
        "libpq",
        f"version {version} is older than 17; PgBouncer transaction pooling with prepared statements needs libpq "
        "17 or later — rebuild the image",
    )


def superadmin_password_left(session: Any, settings: Any) -> Finding | None:
    """A warning when `ASLMS_SUPERADMIN_PASSWORD` is still set although the super admin exists (the runbook says to
    clear it after the first sign-in)."""
    from aslms.services.memberships import super_admin_membership

    if not _secret(getattr(settings, "aslms_superadmin_password", None)):
        return None
    if super_admin_membership(session) is None:
        return None
    return Finding(
        WARNING, "ASLMS_SUPERADMIN_PASSWORD", "is still set although the super admin exists; clear it"
    )


def errors(findings: list[Finding]) -> list[Finding]:
    """The findings that can stop the start: fatal ones and errors."""
    return [f for f in findings if f.level in (FATAL, ERROR)]


def raise_on_errors(findings: list[Finding], is_prod: bool) -> None:
    """Raises `PreflightFailed` with every fatal finding (at every `APP_ENV`) and, when `is_prod`, the errors too
    (outside prod the rules are warnings)."""
    bad = [f for f in findings if f.level == FATAL or (is_prod and f.level == ERROR)]
    if bad:
        raise PreflightFailed(bad)
