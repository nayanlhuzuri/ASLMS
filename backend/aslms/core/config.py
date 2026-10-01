"""Central settings. Every value comes from the environment or `.env`; nothing is hard-coded.
Variable names match `.env.example` and `docs/napix_integration_notes.md` §1 (case-insensitive)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # --- runtime --------------------------------------------------------------------
    app_env: str = Field("dev", description="dev | test | prod")
    log_level: str = "INFO"
    timezone: str = "Asia/Kolkata"

    # --- database / queue (used from migration 0001 onwards) --------------------------
    database_url_sync: str = "postgresql+psycopg://aslms:aslms@localhost:5433/aslms"
    aslms_migrate_url: str | None = None
    redis_url: str | None = None

    # --- NAPIX eCourts High Court API (docs/napix_integration_notes.md §1) -------------
    napix_enabled: bool = False  # master switch: no call leaves the server until this is true
    napix_client_id: str | None = None
    napix_client_secret: SecretStr | None = None
    napix_dept_id: str | None = None
    napix_auth_key: SecretStr | None = None  # 16-byte AES key and IV, used as trimmed UTF-8 text
    napix_hash_key: str = "15081947"  # fixed, published in the spec
    napix_base_url: str = Field(
        "https://delhigw.napix.gov.in/nic/ecourts",
        validation_alias=AliasChoices("NAPIX_BASE_URL", "NAPIX_BASE"),
    )
    napix_est_code: str = Field(
        "GAHC01", validation_alias=AliasChoices("NAPIX_EST_CODE", "NAPIX_HC_EST_CODE")
    )
    napix_version: str = "v1.0"
    napix_state_code: str = "6"  # Assam; verify with the state master
    napix_rate_limit_per_min: int = 60
    napix_timeout_seconds: float = 40.0
    napix_token_ttl_seconds: int = 3300  # when the token response carries no expires_in (manual: one hour)

    # --- SourceTrace ---------------------------------------------------------------------
    sourcetrace_base_url: str | None = None
    sourcetrace_api_key: SecretStr | None = None
    sourcetrace_enabled: bool = False

    @property
    def is_prod(self) -> bool:
        return self.app_env == "prod"

    @property
    def migrate_url(self) -> str:
        return self.aslms_migrate_url or self.database_url_sync

    @property
    def napix_configured(self) -> bool:
        """Credentials present *and* the master switch on."""
        return self.napix_enabled and all(
            [self.napix_client_id, self.napix_client_secret, self.napix_dept_id, self.napix_auth_key]
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
