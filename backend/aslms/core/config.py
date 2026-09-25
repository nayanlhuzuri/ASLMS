"""Central settings. Every value comes from the environment or `.env`; nothing is hard-coded.
Variable names match `.env.example` at the repository root (case-insensitive)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # --- runtime --------------------------------------------------------------------
    app_env: str = Field("dev", description="dev | test | prod")
    log_level: str = "INFO"
    timezone: str = "Asia/Kolkata"
    secret_key: SecretStr = SecretStr("change-me-in-production")
    public_base_url: str = "http://localhost:3000"

    # --- database / queue ----------------------------------------------------------
    database_url: str = "postgresql+asyncpg://aslms:aslms@localhost:5433/aslms"
    database_url_sync: str = "postgresql+psycopg://aslms:aslms@localhost:5433/aslms"
    db_pool_size: int = 5
    db_max_overflow: int = 10
    redis_url: str = "redis://localhost:6379/0"

    # --- document storage and uploads --------------------------------------------
    storage_root: Path = Path("./data/storage")
    upload_max_mb: int = 25
    clamav_host: str | None = None
    clamav_port: int = 3310

    # --- cause-list PDFs on disk ------------------------------------------------------
    cause_list_dir: Path = Path("./data/causelists")

    # --- NAPIX eCourts High Court API (primary source) ----------------------------
    napix_base: str = "https://delhigw.napix.gov.in/nic/ecourts"
    napix_client_id: str | None = None
    napix_client_secret: SecretStr | None = None
    napix_dept_id: str | None = None
    napix_auth_key: SecretStr | None = None
    napix_auth_key_mode: str = Field("text", description="text | hex | base64")
    napix_hash_key: str = "15081947"
    napix_version: str = "v1.0"
    napix_state_code: str = "6"
    napix_hc_est_code: str = "GAHC01"
    napix_rate_limit_per_min: int = 60
    napix_timeout_seconds: float = 40.0

    # --- GHC website (supplementary) ----------------------------------------------------
    ghc_causelist_base: str = "https://ghconline.gov.in"

    # --- SourceTrace (in-house RAG) ------------------------------------------------------
    sourcetrace_base_url: str | None = None
    sourcetrace_api_key: SecretStr | None = None
    sourcetrace_enabled: bool = False

    # --- notifications ------------------------------------------------------------------
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from: str = "no-reply@aslms.assam.gov.in"
    sms_gateway_url: str | None = None
    sms_gateway_key: SecretStr | None = None

    # --- auth -----------------------------------------------------------------------------
    access_token_minutes: int = 15
    refresh_token_days: int = 14
    otp_expiry_minutes: int = 10
    otp_max_attempts: int = 5

    # --- ownership scoring ------------------------------------------------------------------
    score_strong_threshold: float = 0.85
    score_possible_threshold: float = 0.50

    # --- bootstrap ------------------------------------------------------------------------------
    seed_admin_email: str = "admin@aslms.local"
    seed_admin_password: SecretStr = SecretStr("change-me")

    @property
    def is_prod(self) -> bool:
        return self.app_env == "prod"

    @property
    def napix_configured(self) -> bool:
        return all([self.napix_client_id, self.napix_client_secret, self.napix_dept_id, self.napix_auth_key])


@lru_cache
def get_settings() -> Settings:
    return Settings()
