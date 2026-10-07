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
    aslms_app_password: SecretStr | None = None  # set by migration 0001 on the aslms_app role
    aslms_readonly_password: SecretStr | None = None
    redis_url: str | None = None
    storage_dir: str = "data/store"  # document store root (a volume in Compose)
    causelist_dir: str = "data/causelists"  # GHC website PDFs on disk, <dd-mm-yyyy>/<Type>_<date>.pdf

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
    napix_state_code: str = "18"  # Gauhati High Court in the NAPIX state master (verified live, 1 Oct 2026)
    napix_rate_limit_per_min: int = 60
    napix_rate_window_seconds: int = 3600  # 1,000 calls per clock hour, measured 1 Oct 2026 (notes §6)
    napix_rate_reserve: int = 150  # calls kept for the daily cycle; the load queue stops below this
    napix_timeout_seconds: float = 40.0
    napix_token_ttl_seconds: int = 3300  # when the token response carries no expires_in (manual: one hour)
    # user court searches (design cases-api, decision 13): refused below this remaining hourly quota, at most
    # this many per user per hour, and the whole request (retries included) within this many seconds
    napix_search_floor: int = 50
    napix_search_per_user_hour: int = 30
    napix_search_timeout_seconds: float = 60.0

    # --- authentication and the first super admin ------------------------------------------
    aslms_jwt_secret: SecretStr | None = None  # required to issue tokens; the API refuses to start without it
    aslms_access_token_minutes: int = 30
    aslms_refresh_token_days: int = 14
    aslms_superadmin_email: str | None = None  # created by `aslms seed` when both are set; never logged
    aslms_superadmin_password: SecretStr | None = None

    # --- documents and uploads (design documents-uploads, decisions 1, 2, 4, 10) -----------------------
    upload_max_bytes: int = 20 * 1024 * 1024  # 20 MB per file, below ClamAV's default StreamMaxLength (25 MB)
    clamav_host: str = "localhost"  # Compose sets `clamav`
    clamav_port: int = 3310
    clamav_timeout_seconds: float = 30.0
    text_extract_batch: int = 50  # documents per `aslms.extract_pending_text` run

    # --- custody and workflow (design custody-workflow, decisions 12, 14, 18) ---------------------------
    attachments_max_files: int = 5  # new files per note, each within UPLOAD_MAX_BYTES
    note_max_chars: int = 20_000
    note_drafts_max: int = 20  # drafts per holder per case

    # --- mail and alerts (design alerts-notifications, decisions 2, 4, 6, 10, 11, 15, 17, 19) -------------
    mail_backend: str = (
        "auto"  # auto | api | smtp | console; auto prefers the API token, then SMTP, then console
    )
    mailtrap_api_token: SecretStr | None = None  # never logged
    mailtrap_api_url: str | None = None  # the sending or the sandbox URL
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: SecretStr | None = None  # never logged
    smtp_starttls: bool = True
    smtp_from: str | None = None  # the sender address (every backend), on a verified domain
    smtp_from_name: str = "ASLMS"
    mail_timeout_seconds: float = 20.0
    portal_base_url: str = "http://localhost:3000"  # links in mails: <base>/cases/<ref>
    alert_hearing_lookahead_days: int = 7
    alert_critical_hours: int = 48
    court_sitting_time: str = "10:30"  # IST; the hearing alert's due time on its date
    alert_event_max_age_days: int = 14  # an order or a disposal older than this raises no alert
    alert_event_overlap_minutes: int = 30  # the event scan re-reads this much of the previous run's window
    alert_info_expire_days: int = 14  # informational alerts expire after this
    alert_compliance_expire_days: int = 30
    request_due_soon_days: int = 2
    notify_max_attempts: int = 3
    notify_batch: int = 200

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
