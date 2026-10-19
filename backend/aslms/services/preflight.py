"""The start-up safety check (design deployment-checklist, decision 3): `aslms ops preflight` runs first in the
Compose `init` and `migrate` services, so with an error nothing else starts.

With `APP_ENV=prod` every rule below is an error; with `dev` or `test` each is a warning:
- `ASLMS_JWT_SECRET` shorter than 32 characters;
- `POSTGRES_PASSWORD`, `ASLMS_APP_PASSWORD`, `REDIS_PASSWORD` (and `ASLMS_READONLY_PASSWORD` when set) shorter than 16
  characters, a known default, equal to the role's user name, equal to another of them, or holding a character other
  than letters, digits, `_` and `-` (Compose puts them into URLs unencoded);
- a `REDIS_URL` without a password; a `PORTAL_BASE_URL` that is not `https://`; `COOKIE_SECURE=false`;
- a mail service that cannot deliver a sign-in code: the console backend, a backend that cannot be built, or the
  Mailtrap sandbox (`sandbox.api.mailtrap.io` catches mail and never delivers it).
A super admin password still set after the super admin exists is always a warning (`superadmin_password_left`).

A finding names the variable and the rule; it never carries a value."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

ERROR = "error"
WARNING = "warning"
JWT_MIN = 32
PASSWORD_MIN = 16
KNOWN_DEFAULTS = frozenset({"aslms", "aslms_app", "aslms_readonly", "postgres", "password", "changeme"})
MAILTRAP_SANDBOX_HOST = "sandbox.api.mailtrap.io"
URL_SAFE_RE = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass(frozen=True)
class Finding:
    level: str  # error | warning
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
    """(variable, value, user name) for each password the stack uses; the read-only one only when set."""
    out = [
        (
            "POSTGRES_PASSWORD",
            _secret(getattr(settings, "postgres_password", None)),
            getattr(settings, "postgres_user", None) or "aslms",
        ),
        ("ASLMS_APP_PASSWORD", _secret(settings.aslms_app_password), "aslms_app"),
        ("REDIS_PASSWORD", _secret(getattr(settings, "redis_password", None)), "default"),
    ]
    readonly = _secret(getattr(settings, "aslms_readonly_password", None))
    if readonly:
        out.append(("ASLMS_READONLY_PASSWORD", readonly, "aslms_readonly"))
    return out


def _password_rules(settings: Any) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    pwds = _passwords(settings)
    for name, value, user in pwds:
        if not value:
            found.append((name, "is not set"))
            continue
        if len(value) < PASSWORD_MIN:
            found.append((name, f"is shorter than {PASSWORD_MIN} characters"))
        if value.lower() in KNOWN_DEFAULTS:
            found.append((name, "is a known default"))
        if user and value.lower() == user.lower():
            found.append((name, "equals its user name"))
        if not URL_SAFE_RE.match(value):
            found.append((name, "may hold only letters, digits, _ and - (it goes into a URL unencoded)"))
    for i, (name, value, _user) in enumerate(pwds):
        for other, other_value, _other_user in pwds[i + 1 :]:
            if value and value == other_value:
                found.append((other, f"equals {name}; every password must be different"))
    return found


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
    same rules. Errors only when `APP_ENV=prod`; warnings otherwise."""
    del component  # one rule set for every component (Part B adds the monitoring rules)
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
    return [Finding(level, variable, message) for variable, message in raw]


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
    return [f for f in findings if f.level == ERROR]


def raise_on_errors(findings: list[Finding], is_prod: bool) -> None:
    """Raises `PreflightFailed` with the error findings; outside prod there are none (every rule is a warning)."""
    bad = errors(findings) if is_prod else []
    if bad:
        raise PreflightFailed(bad)
