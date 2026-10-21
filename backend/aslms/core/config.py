"""Central settings. Every value comes from the environment or `.env`; nothing is hard-coded.
Variable names match `.env.example` and `docs/napix_integration_notes.md` §1 (case-insensitive)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # --- runtime --------------------------------------------------------------------
    # design pre-pilot-hardening, decision 2: exactly dev, test or prod; anything else stops every process at load
    app_env: Literal["dev", "test", "prod"] = Field("dev", description="dev | test | prod")
    log_level: str = "INFO"
    timezone: str = "Asia/Kolkata"

    # --- database / queue (used from migration 0001 onwards) --------------------------
    database_url_sync: str = "postgresql+psycopg://aslms:aslms@127.0.0.1:5433/aslms"
    aslms_migrate_url: str | None = None
    aslms_app_password: SecretStr | None = (
        None  # set on the aslms_app role by `aslms db-roles` (safety-fixes)
    )
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
    napix_rate_window_seconds: int = 3600  # window length; the phase is detected (design napix-window)
    # the detected quota window (design napix-window, decisions 1-5): wait this long after the expected reset; probe
    # at most this often while the reset is late or the timing unknown (<= the 300 s precise gap); a rise of at least
    # this many remaining calls between two readings is a reset
    napix_window_margin_seconds: int = Field(60, ge=0, le=600)
    napix_window_probe_seconds: int = Field(180, ge=60, le=300)
    napix_window_reset_jump: int = Field(50, ge=10, le=500)
    napix_rate_reserve: int = 150  # calls kept for the daily cycle; the load queue stops below this
    # below this remaining hourly quota the runner claims nothing at all; between it and the rate reserve only the
    # daily and request lanes (design data-load-console, decision 4): load >= 150 > daily >= 100 > searches >= 50
    napix_live_reserve: int = 100
    # Current Status sends the CNRs in the query string: the gateway answers HTTP 414 above ~300 CNRs (live probe
    # 7 Oct 2026: 300 ok, 350 -> 414, 400+ -> 405); 250 leaves margin. The spec's maximum is 500.
    napix_status_batch: int = Field(250, ge=1, le=300)
    napix_timeout_seconds: float = 40.0
    napix_token_ttl_seconds: int = 3300  # when the token response carries no expires_in (manual: one hour)
    # user court searches (design cases-api, decision 13): refused below this remaining hourly quota, at most
    # this many per user per hour, and the whole request (retries included) within this many seconds
    napix_search_floor: int = 50
    napix_search_per_user_hour: int = 30
    napix_search_timeout_seconds: float = 60.0
    # the data-health connectivity check (design audit-screens, decision 10): one Overview call at most this often
    napix_health_check_min_seconds: int = Field(60, ge=10, le=3600)
    # the runner pauses after this many items in a row failed with NapixUnavailable, for this many seconds (design
    # safety-fixes, decision 8)
    napix_fault_streak: int = Field(5, ge=3, le=50)
    napix_fault_pause_seconds: int = Field(300, ge=60, le=3600)
    # an advocate court search stores this many new cases in the request; when the court's distinct cases number at
    # most STORE_MAX the rest are stored in the background, otherwise not at all (design safety-fixes, decision 12)
    napix_advocate_store_now: int = Field(25, ge=1, le=100)
    napix_advocate_store_max: int = Field(300, ge=25, le=2000)

    # --- authentication and the first super admin ------------------------------------------
    aslms_jwt_secret: SecretStr | None = None  # required to issue tokens; the API refuses to start without it
    aslms_access_token_minutes: int = 30
    aslms_refresh_token_days: int = 14
    aslms_superadmin_email: str | None = None  # created by `aslms seed` when both are set; never logged
    aslms_superadmin_password: SecretStr | None = None
    # e-mailed sign-in codes (design otp-and-profile, decisions 2-4): a code at every sign-in, no device trust
    otp_ttl_minutes: int = 10
    otp_max_attempts: int = 5
    otp_resend_seconds: int = 120  # a new code for the same login and purpose at most this often
    otp_max_per_hour: int = 10  # codes per login per hour across purposes
    login_max_failures: int = 10  # failed passwords or codes per login inside the window lock it
    login_lock_minutes: int = 15

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

    # --- SourceTrace (design sourcetrace-connector, decisions 2, 7, 14, 15) ------------------
    sourcetrace_base_url: str | None = None
    sourcetrace_api_key: SecretStr | None = None  # never logged, never stored in an ingestion record
    sourcetrace_enabled: bool = False  # off: nothing is sent; on: still nothing until a real connector exists
    sourcetrace_batch: int = Field(20, ge=1, le=1000)  # documents per 5-minute run
    sourcetrace_run_seconds: float = Field(240.0, gt=0)  # a run stops claiming after this
    sourcetrace_timeout_seconds: float = Field(60.0, gt=0)  # one send, the document row locked meanwhile
    sourcetrace_max_attempts: int = Field(5, ge=1, le=20)  # then the document is `failed`

    # --- dashboards and reports (design reports-dashboards, decisions 2, 5, 12) ------------------
    report_max_range_days: int = Field(366, ge=1, le=1000)  # hearings-disposals period
    report_health_max_days: int = Field(92, ge=1, le=1000)  # data-health period
    report_xlsx_max_rows: int = Field(5000, ge=1, le=50_000)  # case rows per Excel section
    report_pdf_max_rows: int = Field(1000, ge=1, le=50_000)  # case rows per PDF section
    report_statement_timeout_seconds: int = Field(30, ge=1, le=300)  # SET LOCAL statement_timeout
    dashboard_list_size: int = Field(10, ge=1, le=50)  # rows in each dashboard list

    # --- the data-load console (design data-load-console, decision 8) ------------------------
    data_load_estimate_window_days: int = Field(7, ge=1, le=30)  # rates measured over this many days

    # --- department discovery (design department-discovery, decisions 5, 6 and 14; owner's decisions of 14 Oct 2026)
    # calls per detected quota window that discovery-lane rows may make (0 stops discovery claims; rows wait)
    napix_discovery_share: int = Field(100, ge=0, le=1000)
    # automatic sweeps cover registration years from this one to the current year; older years only on request
    discovery_from_year: int = Field(2025, ge=1950)

    # --- next dates from orders (design next-date-extraction, decision 20) ------------------
    next_date_batch: int = Field(500, ge=1, le=5000)  # orders read per 5-minute `next-dates-read` run
    next_date_unclear_days: int = Field(
        30, ge=7, le=120
    )  # an unclear current order asks for a date this long
    next_date_max_ahead_days: int = Field(
        548, ge=90, le=1095
    )  # a read or entered date at most this far ahead

    # --- deployment (design deployment-checklist, decisions 3 and 13) ------------------------
    # read by `aslms ops preflight` only: the cluster superuser, the Redis password and the portal's cookie flag;
    # the api, worker and scheduler get POSTGRES_PASSWORD blanked by Compose
    postgres_user: str = "aslms"
    postgres_password: SecretStr | None = None
    redis_password: SecretStr | None = None
    cookie_secure: bool = True
    # the backup service (`aslms ops backup-scheduler`): dumps, roles and the store mirror under BACKUP_DIR at minute 30
    # of every BACKUP_INTERVAL_HOURS hours (IST); retention prunes dump sets only, never the store mirror
    backup_dir: str = "backups"
    backup_interval_hours: int = Field(6, ge=1, le=24)
    backup_keep_recent_hours: int = Field(48, ge=1, le=24 * 30)
    backup_keep_daily: int = Field(14, ge=0, le=366)
    backup_keep_weekly: int = Field(8, ge=0, le=520)
    backup_keep_monthly: int = Field(12, ge=0, le=240)
    backup_keep_premigrate: int = Field(5, ge=1, le=100)

    # --- monitoring (design deployment-checklist, Part B, decisions 22-25) ----------------------------
    # read by preflight: the Grafana admin and Flower passwords (Compose passes them to those services), the active
    # Compose profiles (prod refuses a stack without `monitoring`) and the address Alertmanager mails
    grafana_admin_password: SecretStr | None = None
    flower_basic_auth: SecretStr | None = None  # user:password[,user:password]
    compose_profiles: str = ""
    ops_alert_email: str | None = None
    # the API's request metrics (decision 24): served by the API lifespan on this port inside the Compose network
    # only (Compose sets 9100); 0, the default for host runs and tests, opens no listener (the counting still runs)
    api_metrics_port: int = Field(0, ge=0, le=65535)
    # the operations exporter (`aslms ops metrics`, decision 23): readings cached this long, each database read
    # under this statement timeout; the probes and the disk paths it reports (a blank probe URL is not probed)
    ops_metrics_cache_seconds: int = Field(60, ge=5, le=600)
    ops_metrics_statement_timeout_seconds: int = Field(10, ge=1, le=60)
    ops_probe_portal_url: str = "https://proxy/api/health"
    ops_probe_web_url: str = "http://web:3000/api/health"
    ops_probe_api_url: str = "http://api:8000/health"
    ops_probe_timeout_seconds: float = Field(5.0, gt=0, le=30)
    ops_disk_paths: str = "/data,/backups"

    # --- the System health screen (design api-health-checker, decision 17) -----------------------------
    # a court API is tested at most once per HEALTH_TEST_API_MIN_SECONDS by anyone; a person makes at most
    # HEALTH_TEST_PER_USER_HOUR tests an hour; one test waits at most HEALTH_TEST_TIMEOUT_SECONDS for the court. The
    # pool card reads "connects directly" when DATABASE_URL_SYNC is not HEALTH_POOL_ADDRESS; the direct database card
    # probes HEALTH_POSTGRES_DIRECT_HOST:PORT without credentials
    health_test_api_min_seconds: int = Field(60, ge=10, le=3600)
    health_test_per_user_hour: int = Field(30, ge=1, le=200)
    health_test_timeout_seconds: float = Field(30.0, gt=0, le=40)
    health_pool_address: str = "pgbouncer:6432"
    health_postgres_direct_host: str = "postgres"
    health_postgres_direct_port: int = Field(5432, ge=1, le=65535)
    # --- the System health request console (design system-health-inspector, decision 17) ---------------
    # the NAPIX PDFs served behind admin.service_health (a read-only mount of docs/specs/pdf on the api); "Check token"
    # at most once per HEALTH_TOKEN_CHECK_MIN_SECONDS by anyone; the full decrypted answer up to HEALTH_RAW_MAX_BYTES
    napix_docs_dir: str = "/app/napix-docs"
    health_token_check_min_seconds: int = Field(600, ge=60, le=86400)
    health_raw_max_bytes: int = Field(2_000_000, ge=10_000, le=20_000_000)

    @model_validator(mode="after")
    def _reserves_ordered(self) -> Settings:
        """Decision 4: searches stop first, then the daily cycle, then the load."""
        if not (self.napix_search_floor <= self.napix_live_reserve <= self.napix_rate_reserve):
            raise ValueError(
                "NAPIX_SEARCH_FLOOR <= NAPIX_LIVE_RESERVE <= NAPIX_RATE_RESERVE must hold "
                f"({self.napix_search_floor}, {self.napix_live_reserve}, {self.napix_rate_reserve})"
            )
        return self

    @model_validator(mode="after")
    def _advocate_store_ordered(self) -> Settings:
        """NAPIX_ADVOCATE_STORE_NOW <= NAPIX_ADVOCATE_STORE_MAX (design safety-fixes, decision 12)."""
        if self.napix_advocate_store_now > self.napix_advocate_store_max:
            raise ValueError(
                "NAPIX_ADVOCATE_STORE_NOW <= NAPIX_ADVOCATE_STORE_MAX must hold "
                f"({self.napix_advocate_store_now}, {self.napix_advocate_store_max})"
            )
        return self

    @model_validator(mode="after")
    def _discovery_year(self) -> Settings:
        """DISCOVERY_FROM_YEAR lies between 1950 and the current year."""
        from datetime import date

        if self.discovery_from_year > date.today().year:
            raise ValueError(
                f"DISCOVERY_FROM_YEAR must not be after the current year ({self.discovery_from_year})"
            )
        return self

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


APP_ENV_FATAL = "preflight fatal: APP_ENV: must be dev, test or prod"


def is_app_env_error(exc: ValidationError) -> bool:
    """True when the settings failed because `APP_ENV` is not dev, test or prod (design pre-pilot-hardening,
    decision 2), so a command can print `APP_ENV_FATAL` instead of a traceback that echoes the value."""
    return any(tuple(err.get("loc") or ())[:1] == ("app_env",) for err in exc.errors())
