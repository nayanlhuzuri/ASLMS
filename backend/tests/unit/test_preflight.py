"""Design deployment-checklist, decision 3: `aslms ops preflight` refuses weak settings in prod, only warns in dev,
and never prints a value."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from aslms.cli.main import app
from aslms.core.config import Settings
from aslms.services import preflight

PG = "pg-0123456789abcdef0123"
APP = "app-0123456789abcdef0123"
REDIS = "rd-0123456789abcdef01234"
RO = "ro-0123456789abcdef0123"
GRAFANA = "grafana admin pass 0123"
FLOWER = "ops:flower-0123456789abcdef"
JWT = "j" * 48


def good(**over) -> Settings:
    values = dict(
        app_env="prod",
        aslms_jwt_secret=JWT,
        postgres_user="aslms",
        postgres_password=PG,
        aslms_app_password=APP,
        redis_password=REDIS,
        aslms_readonly_password=RO,
        grafana_admin_password=GRAFANA,
        flower_basic_auth=FLOWER,
        compose_profiles="monitoring",
        ops_alert_email="ops@example.gov.in",
        redis_url=f"redis://:{REDIS}@redis:6379/0",
        portal_base_url="https://aslms.example.internal",
        cookie_secure=True,
        mail_backend="smtp",
        smtp_host="relay.example.internal",
        smtp_from="aslms@example.gov.in",
    )
    values.update(over)
    return Settings(_env_file=None, **values)


def variables(settings: Settings) -> set[str]:
    return {f.variable for f in preflight.check(settings) if f.level == preflight.ERROR}


def test_preflight_passes_good_prod_settings():
    assert preflight.check(good()) == []
    preflight.raise_on_errors(preflight.check(good()), True)


def test_preflight_refuses_short_jwt_secret():
    assert variables(good(aslms_jwt_secret="x" * 31)) == {"ASLMS_JWT_SECRET"}
    assert "ASLMS_JWT_SECRET" in variables(good(aslms_jwt_secret=None))


@pytest.mark.parametrize(
    "default", ["aslms", "aslms_app", "aslms_readonly", "postgres", "password", "changeme"]
)
@pytest.mark.parametrize(
    "field,var",
    [
        ("postgres_password", "POSTGRES_PASSWORD"),
        ("aslms_app_password", "ASLMS_APP_PASSWORD"),
        ("redis_password", "REDIS_PASSWORD"),
    ],
)
def test_preflight_refuses_each_default_password(default, field, var):
    assert var in variables(good(**{field: default}))


def test_preflight_refuses_short_and_missing_passwords():
    assert "REDIS_PASSWORD" in variables(good(redis_password="short-password"))
    assert "POSTGRES_PASSWORD" in variables(good(postgres_password=None))


def test_preflight_refuses_password_equal_to_its_user_or_another():
    assert "POSTGRES_PASSWORD" in variables(
        good(postgres_user="clusteradmin12345", postgres_password="clusteradmin12345")
    )
    assert "REDIS_PASSWORD" in variables(good(redis_password=APP, redis_url=f"redis://:{APP}@redis:6379/0"))
    # a read-only password, when set, must differ from the others too
    assert "ASLMS_READONLY_PASSWORD" in variables(good(aslms_readonly_password=APP))
    assert preflight.check(good(aslms_readonly_password="ro-another-0123456789")) == []


def test_preflight_refuses_redis_url_without_password():
    assert variables(good(redis_url="redis://redis:6379/0")) == {"REDIS_URL"}


def test_preflight_refuses_http_portal_and_insecure_cookies():
    assert variables(good(portal_base_url="http://aslms.example.internal")) == {"PORTAL_BASE_URL"}
    assert variables(good(cookie_secure=False)) == {"COOKIE_SECURE"}


def test_preflight_refuses_console_mail():
    assert variables(good(mail_backend="console")) == {"MAIL_BACKEND"}
    # auto with nothing configured resolves to the console
    assert variables(good(mail_backend="auto", smtp_host=None)) == {"MAIL_BACKEND"}
    assert variables(good(mail_backend="")) == {"MAIL_BACKEND"}


def test_preflight_refuses_mailtrap_sandbox():
    s = good(
        mail_backend="api",
        mailtrap_api_token="tok-abc",
        mailtrap_api_url="https://sandbox.api.mailtrap.io/api/send/123",
    )
    assert variables(s) == {"MAILTRAP_API_URL"}
    ok = good(
        mail_backend="api",
        mailtrap_api_token="tok-abc",
        mailtrap_api_url="https://send.api.mailtrap.io/api/send",
    )
    assert variables(ok) == set()


def test_preflight_only_warns_in_dev():
    s = good(app_env="dev", postgres_password="aslms", cookie_secure=False, mail_backend="console")
    findings = preflight.check(s)
    assert findings and all(f.level == preflight.WARNING for f in findings)
    preflight.raise_on_errors(findings, False)
    with pytest.raises(preflight.PreflightFailed):
        preflight.raise_on_errors(preflight.check(good(postgres_password="aslms")), True)


def test_preflight_never_prints_a_secret(monkeypatch):
    weak = good(
        aslms_jwt_secret="tiny-secret-value",
        postgres_password="pw-shared-value-1",
        aslms_app_password="pw-shared-value-1",
        redis_password="redis-weak",
        redis_url="redis://:redis-weak@redis:6379/0",
    )
    monkeypatch.setattr("aslms.cli.ops.get_settings", lambda: weak)
    res = CliRunner().invoke(app, ["ops", "preflight"])
    assert res.exit_code == 1
    assert "ASLMS_JWT_SECRET" in res.output and "ASLMS_APP_PASSWORD" in res.output
    for secret in ("tiny-secret-value", "pw-shared-value-1", "redis-weak"):
        assert secret not in res.output
    for f in preflight.check(weak):
        assert "pw-shared" not in f.message and "redis-weak" not in f.message


def test_preflight_cli_passes_in_dev(monkeypatch):
    monkeypatch.setattr("aslms.cli.ops.get_settings", lambda: good(app_env="dev", cookie_secure=False))
    res = CliRunner().invoke(app, ["ops", "preflight"])
    assert res.exit_code == 0
    assert "preflight passed" in res.output


def test_preflight_refuses_passwords_that_break_a_url():
    assert "REDIS_PASSWORD" in variables(
        good(redis_password="abc@def/ghi:jkl#mnop", redis_url="redis://:x@redis:6379/0")
    )
    assert "POSTGRES_PASSWORD" in variables(good(postgres_password="has space in it 123456"))


# ------------------------------------------------------------------------------------------------ Part B (row 77)


def test_preflight_requires_the_readonly_password():
    """Part B: the exporters connect as aslms_readonly, so its password is required."""
    assert "ASLMS_READONLY_PASSWORD" in variables(good(aslms_readonly_password=None))
    assert "ASLMS_READONLY_PASSWORD" in variables(good(aslms_readonly_password="aslms_readonly"))


def test_preflight_refuses_weak_monitoring_passwords():
    assert "GRAFANA_ADMIN_PASSWORD" in variables(good(grafana_admin_password=None))
    assert "GRAFANA_ADMIN_PASSWORD" in variables(good(grafana_admin_password="admin"))
    assert "GRAFANA_ADMIN_PASSWORD" in variables(good(grafana_admin_password="short-one"))
    assert "GRAFANA_ADMIN_PASSWORD" in variables(good(grafana_admin_password=APP))
    assert "FLOWER_BASIC_AUTH" in variables(good(flower_basic_auth=None))
    assert "FLOWER_BASIC_AUTH" in variables(good(flower_basic_auth="no-colon-in-this-value"))
    assert "FLOWER_BASIC_AUTH" in variables(good(flower_basic_auth="ops:short"))
    assert "FLOWER_BASIC_AUTH" in variables(good(flower_basic_auth=":nouser-0123456789abcdef"))
    assert "FLOWER_BASIC_AUTH" in variables(good(flower_basic_auth="ops:" + GRAFANA))
    assert "FLOWER_BASIC_AUTH" in variables(good(flower_basic_auth=f"{FLOWER},second:tiny"))
    assert variables(good(flower_basic_auth=f"{FLOWER},second:second-0123456789abcd")) == set()


def test_preflight_refuses_prod_without_the_monitoring_profile():
    assert variables(good(compose_profiles="")) == {"COMPOSE_PROFILES"}
    assert variables(good(compose_profiles="ops")) == {"COMPOSE_PROFILES"}
    assert variables(good(compose_profiles="ops, monitoring")) == set()
    dev = preflight.check(good(app_env="dev", compose_profiles=""))
    assert [f.level for f in dev if f.variable == "COMPOSE_PROFILES"] == [preflight.WARNING]


def test_preflight_only_warns_without_an_alert_recipient_or_relay():
    for s, var in (
        (good(ops_alert_email=None), "OPS_ALERT_EMAIL"),
        (
            good(
                mail_backend="api",
                mailtrap_api_token="tok-abc",
                mailtrap_api_url="https://send.api.mailtrap.io/api/send",
                smtp_host=None,
            ),
            "SMTP_HOST",
        ),
    ):
        findings = preflight.check(s)
        assert [(f.level, f.variable) for f in findings] == [(preflight.WARNING, var)]
        preflight.raise_on_errors(findings, True)


def test_preflight_never_prints_a_monitoring_secret(monkeypatch):
    weak = good(grafana_admin_password="grafana-weak", flower_basic_auth="ops:flower-weak")
    monkeypatch.setattr("aslms.cli.ops.get_settings", lambda: weak)
    res = CliRunner().invoke(app, ["ops", "preflight"])
    assert res.exit_code == 1
    assert "GRAFANA_ADMIN_PASSWORD" in res.output and "FLOWER_BASIC_AUTH" in res.output
    assert "grafana-weak" not in res.output and "flower-weak" not in res.output
