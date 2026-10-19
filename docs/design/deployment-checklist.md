# Design: Deployment checklist: a closed-network pilot that is safe to run and recover

```
slug: deployment-checklist
status: approved
author: architect
date: 2026-10-18
approved_by: owner (nayanlhuzuri) on 2026-10-18, with the recommended defaults of the open questions
```

## Context
This is backlog row 16: "Load counts and the sample-of-20 CNR check in the decisions log, `pg_dump` / restore
procedure, PgBouncer and monitoring services in Compose, the deployment runbook; Redis hardening (owner, 11 Oct 2026:
Redis holds the shared NAPIX token: no published host port, a password, optionally the token stored encrypted)". The
independent audit of 18 Oct 2026 (`docs/audits/2026-10-18-independent-audit.md`) moved it to the top. Its Top 2,
Top 5, Top 6, Top 8 and the Area 3 operations findings are this item's input.

What the sources require:
- **Plan §2.2 (Table 3):** "PostgreSQL, with PgBouncer for connection pooling"; "Prometheus and Grafana for system
  health; Flower for background jobs"; "Docker containers (Docker Compose)".
- **Plan §8.2:** first a pilot server with a small number of departments, then the State Data Centre. "Regular
  database and document backups, and system monitoring through Prometheus and Grafana, will be in place from the
  pilot stage."
- **Plan §8.1:** all data stays on government infrastructure, NAPIX credentials are never exposed, and every upload
  is scanned.
- **DB_STANDARD §8:** `aslms_owner` runs migrations, `aslms_app` serves the API and workers, and `aslms_readonly`
  serves Grafana and reports. **§11 step 7** names `docs/operations.md`, which documents the roles and
  `DATABASE_URL`. **§6** leaves retention to the owner.
- **Decisions log, 1 Oct 2026 (product owner):** the pilot runs on the owner's machine as one Compose stack with
  "Postgres, PgBouncer, Redis, API, workers, beat, frontend and monitoring on one host". Every connection comes from
  `.env`, and Postgres and the document store are the only stateful services. The later two-VM on-premise layout is
  deferred and stays deferred here.
- **CLAUDE.md "Next" item 2:** the load counts and the sample-of-20 check go in the decisions log, and the dev
  database gets a `pg_dump`, before deployment.

What `compose.yml` on `main` does today, checked against the file: `postgres` is published on
`0.0.0.0:${POSTGRES_HOST_PORT:-5433}` with the default password `aslms`. `redis` is published on `6379`, has no
password and keeps a persistent volume; it holds `napix:token` (`integration/napix/client.py` `TokenCache`). `api`
is published on `8000` and serves `/docs`, `/redoc` and `/openapi.json`. `web` is published on `3000` over plain
HTTP. There is no proxy, no TLS, no per-IP limit, no backup and no monitoring. `init` runs
`alembic upgrade head && aslms seed` on every `up`. Postgres runs on container defaults (128 MB `shared_buffers`,
64 MB `/dev/shm`). Container logs are not rotated. `clamav` uses the floating `stable` tag and downloads signatures
from the internet. The backend image runs as root. `job_runs` keeps rows marked `running` after a restart (8 on
the dev database). The web server takes the **first** `X-Forwarded-For` entry (`frontend/src/server/api.ts`
`clientAddress`), and a browser can choose that entry. The `infra/` folder named in the decisions log does not
exist.

Depends on **row 76 `safety-fixes` item (1)**: `api`, `worker` and `scheduler` connect as `aslms_app` with a
password from `.env`, and only `init` uses the owner role. Row 76 is being built at the same time. This item is built
after row 76 merges, because both change the same `compose.yml` lines. Rows 76 (2) and (3) are not touched.

Not covered: retention and pruning of rows (DB_STANDARD §6, rows 33 and 70, which need the owner's rule); which mail
relay to use and its live test (row 27; the plan for mail failure, SMS or a break-glass procedure, audit Top 5, is
the owner's decision); auth hardening and neutral answers (row 35); continuous WAL archiving / point-in-time
recovery (decision 14 proposes it as a follow-up if the owner wants a smaller loss window); CI (row 15); the
two-VM on-premise layout (deferred on 1 Oct).

**Split.** The whole deployment is decided in this one note, so the owner approves it once. The build is in three
backlog rows, as was done for rows 50, 55 and 73:
- **Part A, row 16 `deployment-checklist`** (decisions 1-21): Compose hardening and secrets, the proxy with TLS,
  explicit migrations, backups and restore, Postgres settings, ClamAV signatures, the `job_runs` repair, load
  counts and the sample check, the runbook and the README.
- **Part B, new row 77 `deployment-monitoring`** (decisions 22-28): Prometheus, Alertmanager, Grafana, Flower, the
  exporters, the ASLMS operations metrics and the alert rules.
- **Part C, new row 78 `deployment-pgbouncer`** (decision 29): PgBouncer in front of the application's connections.

All three must be done before the first department signs in. The pilot go-live checklist (decision 20) lists them.
Part A also closes row 24 (proxy body limit, ClamAV notes, the EICAR test through Compose), the per-IP throttling
in row 33, the single `web` process and `X-Forwarded-For` points in row 43, and row 44 item 3. The scribe updates
those rows when Part A merges.

## Decisions

### Part A: row 16

1. **One Compose stack on one host. The same files serve the owner's machine and a State Data Centre VM.** Only the
   proxy is reachable from the network. Where the pilot runs is an owner check (Open questions 1). The 1 Oct
   decision says the owner's machine, and on a closed office network that means other PCs reach it by its LAN
   address. *Alternatives:* a separate pilot server layout (rejected: deferred by the 1 Oct decision; this design
   moves to a VM unchanged); Kubernetes or Swarm (rejected: the plan says Docker Compose).

2. **No published ports except the proxy's.** In the base `compose.yml`, `postgres`, `redis`, `api`, `web` and
   `clamav` have no `ports:` entry. `proxy` publishes `${PROXY_BIND:-0.0.0.0}:${PROXY_HTTPS_PORT:-443}` and
   `${PROXY_BIND}:${PROXY_HTTP_PORT:-80}`, and port 80 only redirects. In Part B the monitoring interfaces are
   published on `127.0.0.1` only. A new `compose.dev.yml` is used for development only. It publishes `postgres`
   on `127.0.0.1:${POSTGRES_HOST_PORT:-5433}` (the host-run `pytest` and `psql`), `api` on `127.0.0.1:8000`
   (OpenAPI, CLI checks) and `web` on `127.0.0.1:3000`, and it sets `TRUST_PROXY_HEADERS=false` for `web`. Every
   binding is loopback, so the development layout cannot reach the LAN either. A developer's `.env` sets
   `COMPOSE_FILE=compose.yml:compose.dev.yml`, which Compose reads from `.env`, so `docker compose up -d` stays
   one command (the owner's standing preference). Redis is never published, not even for development: host-run
   CLI commands go through `docker compose exec`. *Alternatives:* `127.0.0.1` bindings in the base file
   (rejected: a pilot host has no reason to reach the database from the host, and loopback publishing has had
   Linux routing exposures); a firewall rule only (rejected: one mistaken rule exposes the database).

3. **Real secrets from `.env` only, refused when missing or weak.** In `compose.yml`, `POSTGRES_PASSWORD`,
   `ASLMS_APP_PASSWORD`, `REDIS_PASSWORD` and `PORTAL_BASE_URL` use the required form `${NAME:?set NAME in .env}`.
   They have no default, so Compose refuses to start without them. `.env.example` leaves them blank and shows how
   to generate them (`openssl rand -hex 32` or `python -c "import secrets;print(secrets.token_hex(32))"`). A new
   command, `aslms ops preflight`, checks the settings and names failing variables without ever printing a value.
   It runs first in `init`, so with errors nothing else starts. When `APP_ENV=prod` it refuses:
   - `ASLMS_JWT_SECRET` shorter than 32 characters;
   - any of `POSTGRES_PASSWORD`, `ASLMS_APP_PASSWORD` or `REDIS_PASSWORD` shorter than 16 characters, equal to a
     known default (`aslms`, `aslms_app`, `aslms_readonly`, `postgres`, `password`, `changeme`) or to its user
     name, or equal to another of them;
   - a `REDIS_URL` without a password;
   - a `PORTAL_BASE_URL` that does not start with `https://`;
   - `COOKIE_SECURE=false`;
   - a mail service that cannot deliver a sign-in code: `MAIL_BACKEND` resolving to `console`, an unset backend,
     or a `MAILTRAP_API_URL` that points at the sandbox (`sandbox.api.mailtrap.io`, which catches mail and never
     delivers it).

   It warns, without refusing, when `ASLMS_SUPERADMIN_PASSWORD` is still set after the super admin exists (the
   runbook says to clear it after the first sign-in). With `APP_ENV` set to `dev` or `test`, every check above is
   a warning. *Alternatives:* Docker secrets (rejected: CLAUDE.md says secrets come from `.env`, and a single host
   gains nothing); checking in each service (rejected: the `init` gate covers every service, because each one
   depends on `init` finishing successfully).

4. **`APP_ENV=prod` for the pilot. The API documentation is served only in development.** `create_app` passes
   `docs_url`, `redoc_url` and `openapi_url` only when `settings.app_env == "dev"`. Otherwise all three are `None`,
   so `/docs`, `/redoc` and `/openapi.json` answer 404. `app.openapi()` still works, so
   `backend/tools/export_openapi.py` and `test_openapi_snapshot` are unaffected. `prod` also switches logs to JSON
   and refuses the console mailer, both of which already exist. The relay's deny list for `/docs`, `/redoc` and
   `/openapi.json` stays as a second guard.

5. **No application process runs as a superuser in production.** When `APP_ENV=prod`, the API lifespan, the
   `queue-worker` start and the scheduler's Celery `worker_ready` signal each run
   `SELECT rolsuper FROM pg_roles WHERE rolname = current_user`. If the answer is true, the process logs
   `refusing to run as a database superuser` and exits. This turns row 76's fix into a guarantee that holds at
   every start. *Alternative:* trusting the Compose file (rejected: the audit found the file and the decisions log
   disagreeing for weeks).

6. **Redis gets a password and keeps nothing on disk.** The service runs `redis-server --requirepass
   ${REDIS_PASSWORD} --save "" --appendonly no --protected-mode yes --maxmemory 256mb --maxmemory-policy
   noeviction`. The `redisdata_v3` volume is dropped, so the NAPIX token never reaches disk. Every service gets
   `REDIS_URL=redis://:${REDIS_PASSWORD}@redis:6379/0`, built in `compose.yml`. The health check runs `redis-cli
   ping` with `REDISCLI_AUTH`, so the password does not appear in the process list.
   - **Losing the data on a Redis restart is safe.** Redis holds the token, which is fetched again on the next call,
     and Celery messages. Beat repeats every scheduled job. The durable work is in `fetch_queue` in Postgres, and
     the upload-time `extract_document_text` dispatch is covered by the 5-minute `extract-text` sweep.
   - **The token is not encrypted in Redis** (the owner's 11 Oct "optionally"). Redis is unpublished,
     password-protected, on the internal network and memory-only, and the token lives an hour. Every service that
     reads it would hold the decryption key from the same `.env`, so encryption adds a key without adding a barrier.

7. **An nginx reverse proxy with TLS sits in front of `web`.** A new `proxy` service uses the official nginx alpine
   image at a pinned version. It joins only a new `edge` network with `web` and cannot reach `api`, `postgres` or
   `redis`. It serves:
   - TLS 1.2 and 1.3 only, a modern cipher list and `ssl_session_tickets off`;
   - `Strict-Transport-Security: max-age=31536000`, without `includeSubDomains` or `preload`, and
     `server_tokens off`;
   - port 80 answering 301 to `https://`;
   - any `Host` other than the one in `PORTAL_BASE_URL` answering 444, the connection closed.

   The certificate and key are read from `./infra/proxy/certs/fullchain.pem` and `privkey.pem`. The folder is
   git-ignored and already covered by `*.pem`/`*.key`. For a closed network the default source is an internal
   certificate authority made by a new command, `aslms ops make-cert --host <name> [--ip <address>] --out
   infra/proxy/certs`. It uses the existing `cryptography` dependency, writes a CA certificate and key plus a
   server certificate with the host name and address as SANs, valid for 825 days, and tells the operator to move
   `ca.key` off the host. The CA certificate is installed once on each pilot PC (runbook). A certificate from
   NIC or the SDC simply replaces the two files. The certificate source is an owner check (Open questions 2).
   *Alternatives:* Caddy or Traefik with automatic certificates (rejected: ACME does not work on a closed network,
   nginx is what the SDC knows, and row 24 already names `client_max_body_size`); TLS inside Next.js (rejected:
   it mixes edge concerns into the BFF).

8. **The trusted hop for `X-Forwarded-For` (audit Top 8, rows 43 and 44 item 3).** The proxy **overwrites** the
   header and never appends to it: `proxy_set_header X-Forwarded-For $remote_addr`, plus `X-Forwarded-Proto
   https` and `X-Forwarded-Host`. `web` reads `X-Forwarded-For` only when its new environment variable
   `TRUST_PROXY_HEADERS=true` is set. Compose sets that because `web` is reachable only through the proxy. It then
   takes the **rightmost** entry, the one written by the trusted hop, never the first, and drops the `x-real-ip`
   fallback. With `false` (the default, and `compose.dev.yml`), `web` sends no `X-Forwarded-For`, and the API
   records `web`'s own address. The API keeps trusting the header only from `WEB_IP` (portal-shell decision 7).
   At the SDC there may be a load balancer in front of the proxy. In that case `PROXY_TRUSTED_UPSTREAM` (a CIDR,
   empty by default) turns on `set_real_ip_from` with `real_ip_header X-Forwarded-For` and `real_ip_recursive on`,
   so `$remote_addr` becomes the client address the load balancer reports.

9. **Request body limits match the API's own limits.** The default `client_max_body_size` is `1m`, enough for every
   JSON body. Three location groups get the upload limits, computed when the proxy starts from the same `.env`
   values the API reads (`UPLOAD_MAX_BYTES`, `ATTACHMENTS_MAX_FILES`). This is the same formula as
   `api/routers/documents.py` `_body_limit` plus `MULTIPART_OVERHEAD`:
   - `~ ^/api/backend/.+/documents$` (case uploads and ticket documents): `UPLOAD_MAX_BYTES + 65536`;
   - `~ ^/api/backend/cases/[^/]+/notes$` and `= /api/backend/admin/tickets/head-change`:
     `ATTACHMENTS_MAX_FILES × UPLOAD_MAX_BYTES + 65536`. The API has no file-count cap on head-change today, so the
     proxy bounds it.

   A start-up script in `/docker-entrypoint.d/` writes the limits snippet. Those locations also use
   `proxy_request_buffering off`, so unscanned upload bytes are never spooled to the proxy's disk; the API scans
   them before storing (documents-uploads). A body over the limit gets a JSON 413
   `{"detail":{"code":"too_large","message":"…"}}`, which the portal already explains. `proxy_read_timeout` is
   `RELAY_TIMEOUT_SECONDS + 30`.

10. **Per-IP throttling at the proxy (audit Top 6, row 33).** Two zones are keyed on `$binary_remote_addr`:
    - `session` covers `location /api/session/` (sign-in, code, resend, reset): `${PROXY_SESSION_RATE:-20r/m}`
      with burst `${PROXY_SESSION_BURST:-20}` and `nodelay`;
    - `api` covers `/api/backend/`: `${PROXY_API_RATE:-30r/s}` with burst `${PROXY_API_BURST:-100}`;
    - `limit_conn` allows `${PROXY_CONN_PER_IP:-50}` connections per address.

    Refusals answer 429 with `Retry-After: 60` and the JSON body
    `{"detail":{"code":"throttled","message":"Too many requests from this address. Wait a minute and try again.","retry_after":60}}`.
    The portal gets a `throttled` message in `messages.ts`. A government office usually sits behind one NAT
    address, so the defaults allow a whole office's morning sign-ins; Open questions 6 asks the owner to confirm
    the numbers. The per-login lock (`LOGIN_MAX_FAILURES`) stays as it is. The neutral answer for a locked login
    stays in row 35.

11. **One `web` process (row 43).** The refresh single-flight assumes one process (portal-shell decision 4), so
    `web` has no `deploy.replicas` and is not scaled. A test asserts this, and the runbook says so.

12. **Migrations are an explicit step with a backup first (audit Area 3).**
    - **`init`** runs `aslms ops preflight && aslms ops db-guard && aslms ops role-passwords && aslms seed`.
      `db-guard` connects with the migrate URL and compares the database revision with the code's Alembic head:
      - no `alembic_version` table and no table in `public` (a fresh install): it runs `alembic upgrade head`, so
        the first installation is still one command;
      - at head: it does nothing;
      - behind head: it exits 3 with `The database is at <rev>; this build needs <head>. Stop the application and
        run: docker compose --profile ops run --rm migrate (it backs the database up first).`
      - ahead of head, or an unknown revision: it exits 4 with `The database is newer than this build`.

      `role-passwords` applies `ASLMS_APP_PASSWORD` (and, from Part B, `ASLMS_READONLY_PASSWORD`) to the roles
      with `ALTER ROLE`, using the same quoting as 0001's `_set_role_passwords`, under `SET LOCAL log_statement =
      'none'` and never printed. A changed `.env` password then reaches the database at the next start. If row 76
      already builds this step, Part A extends that step instead of adding a second one.
    - **`migrate`** is a new service in profile `ops`, so `up` never starts it. It uses the backend image and the
      migrate URL and runs `aslms ops preflight && aslms ops migrate`, which:
      1. refuses while other sessions of `aslms_app` are connected (`pg_stat_activity`), unless `--force`;
      2. takes a backup tagged `pre-migrate` (decision 13) and checks it with `pg_restore --list`;
      3. runs `alembic upgrade head` and `aslms seed`;
      4. writes the audit row `system.migrated` (system actor; before: `{revision}`; after: `{revision, backup}`).

    The runbook's upgrade procedure is: build, `docker compose stop api worker scheduler web`, run `migrate`, `up
    -d`. **Change of behaviour:** an upgrade no longer migrates on `up` (owner check 9). *Alternative:* a dump inside
    `init` before every automatic upgrade (rejected: the audit asks for an explicit step, and a large dump at every
    start delays every restart).

13. **Backups: database, roles and document store, every 6 hours.** A new `backup` service runs the backend image.
    The image gains `postgresql-client-16` from the PostgreSQL apt repository, so `pg_dump` matches the server's
    major version. The service runs a loop, `aslms ops backup-scheduler`, and does not use Celery, so the owner
    credentials stay out of the `scheduler` container. Only `init`, `migrate` and `backup` receive
    `ASLMS_MIGRATE_URL`. Each run, at minute 30 of every `BACKUP_INTERVAL_HOURS` (6) hours, IST, which is 00:30,
    06:30, 12:30 and 18:30, writes under `BACKUP_DIR`:
    - `db/aslms-<YYYYMMDD-HHMM>[-<tag>].dump`: `pg_dump -Fc -Z 6` of the whole database;
    - `db/roles-<…>.sql`: `pg_dumpall --roles-only`, file mode 600, because it holds password hashes. The 29 Sep
      decision already asked for this;
    - `db/manifest-<…>.json`: start and end time, Alembic revision, server and `pg_dump` versions, dump size and
      sha256, row counts of `cases`, `causelist_entries`, `orders`, `documents`, `case_notes`, `custody_history`,
      `case_ownership`, `audit_log`, `users`, `offices`, and the file count and size of the store;
    - `store/`: an add-only mirror of `STORAGE_DIR`. Store files are named by their sha256 and are never changed or
      deleted (documents are archived, never removed), so copying the missing files is a complete copy. Each newly
      copied file is checked against its name. The mirror runs **after** the dump, so every file the dump refers to
      is in the mirror.

    Every run writes a `job_runs` row (`backup`, counters: sizes, files copied, seconds), so the existing
    data-health screen shows the last backup with no screen change. It also writes the files `status/last.json` and
    `status/last-success.json`. Those are readable when the database is down, and Part B reads them.

    **Retention** (owner check, Open questions 4) prunes dump sets only, never the store mirror. It keeps:
    - everything from the last `BACKUP_KEEP_RECENT_HOURS` (48);
    - the first set of each day for `BACKUP_KEEP_DAILY` (14) days;
    - each Sunday for `BACKUP_KEEP_WEEKLY` (8) weeks;
    - the 1st of each month for `BACKUP_KEEP_MONTHLY` (12) months;
    - the last `BACKUP_KEEP_PREMIGRATE` (5) `pre-migrate` sets.

    `BACKUP_DIR` is a bind mount, `./backups` by default and git-ignored. The runbook tells the owner to point it
    at a second physical disk and to copy it weekly to an encrypted external drive kept away from the machine. On
    Docker Desktop the named volumes live inside the Docker VM disk, which a Docker reset erases, so backups must
    sit on the host disk. The worst-case loss is about 6 hours of user work. *Alternatives:* continuous WAL archiving
    and base backups for point-in-time recovery (deferred: more moving parts and a harder restore for a pilot; a
    follow-up row if the owner wants a loss window under 6 hours, Open questions 5); daily dumps only (rejected:
    up to a day of departments' notes and custody moves lost); shell scripts in the `postgres` image (rejected:
    untestable retention logic; Python is tested like the rest).

14. **The restore procedure is tested every week and on demand.** `aslms ops restore-check [--dump <file>]`
    runs on Sunday at 04:30 IST from the backup scheduler, and by hand. It restores the latest dump into a scratch
    database. The command refuses any name other than `aslms_restore_check`, and drops and recreates it. It then
    compares the Alembic revision and the manifest's row counts, and checks 50 random `documents` rows: the stored
    file exists in the store mirror and its sha256 matches. It drops the scratch database and writes a `job_runs`
    row (`restore_check`) and `status/restore-check.json`. The operator needs free disk about twice the database
    size (runbook).

    The full disaster restore is `aslms ops restore --dump <file> --roles <file> --confirm-overwrite aslms`. It
    refuses while any `aslms_app` session is connected. It restores the roles, recreates the database from the
    dump and restores the store from the mirror (`--store-from <dir>`, add-only). Afterwards, in the restored
    database, it writes the audit row `system.restored` (dump name, manifest revision). The runbook gives the steps
    and the expected checks. The integrator rehearses the whole procedure once in a separate Compose project
    (Verification step 10) and records the time it took in the decisions log.

15. **Postgres is tuned for the host.** The `postgres` command sets these flags from `.env`. The defaults assume
    8 GB of memory given to Docker and SSD storage:
    - `shared_buffers=${PG_SHARED_BUFFERS:-1GB}`, `effective_cache_size=${PG_EFFECTIVE_CACHE_SIZE:-4GB}`;
    - `work_mem=${PG_WORK_MEM:-16MB}`, `maintenance_work_mem=${PG_MAINTENANCE_WORK_MEM:-256MB}`,
      `max_connections=${PG_MAX_CONNECTIONS:-100}`;
    - `min_wal_size=1GB`, `max_wal_size=4GB`, `checkpoint_timeout=15min`, `checkpoint_completion_target=0.9`,
      `wal_compression=on`;
    - `random_page_cost=1.1`, `effective_io_concurrency=200`, `track_io_timing=on`;
    - `log_min_duration_statement=2000`, `log_lock_waits=on`, `log_temp_files=10MB`;
    - `idle_in_transaction_session_timeout=15min`;
    - `shm_size: 1gb` on the container.

    The runbook gives the sizing rule: `shared_buffers` about 25 % of Docker's memory and `effective_cache_size`
    50-75 %. The owner's RAM is an owner check (Open questions 1). `archive_mode` stays off (decision 13).

16. **Containers are hardened.** The backend image runs as an unprivileged user (uid 10001). On a Linux host the
    runbook has `./data` and `BACKUP_DIR` chown'd to 10001; Docker Desktop bind mounts are writable as they are.
    Every service gets `security_opt: [no-new-privileges:true]`. `api`, `worker`, `scheduler`, `web`, `backup` and
    `migrate` also get `cap_drop: [ALL]`. Every service gets a logging anchor, `json-file`, `max-size: 20m`,
    `max-file: 5`, so logs cannot fill the disk. Every image is pinned to a specific version tag (decision 21).

17. **ClamAV signatures work without general internet access (row 24).** There are three modes, chosen by a
    Compose override listed in `COMPOSE_FILE`:
    - **internet** (the default, as today): `freshclam` in the `clamav` container reaches the ClamAV database
      servers. NAPIX already needs internet access, so on the owner's machine this changes nothing. At the SDC it
      needs one egress rule for that container.
    - **mirror** (`compose.clamav-mirror.yml`): mounts `infra/clamav/freshclam.conf` with `PrivateMirror
      ${CLAMAV_MIRROR}`, an internal HTTP mirror that `cvdupdate` (the ClamAV project's tool) fills on a machine
      with internet access.
    - **offline** (`compose.clamav-offline.yml`): sets `CLAMAV_NO_FRESHCLAMD=true`. A new
      `infra/clamav/import-signatures.sh <dir>` copies `main.cvd`, `daily.cvd` and `bytecode.cvd` into the
      `clamdb_v3` volume and restarts `clamav`.

    The runbook covers the first start: signatures download for minutes, and uploads answer 503
    `scanner_unavailable` until the health check passes. It also covers the memory ClamAV needs (about 1.5 GB, more
    during a reload) and the EICAR check (`aslms documents scan-check`, which exists). Part B alerts when the
    signatures are more than 3 days old. The runbook lists the egress allowlist for the SDC: the NAPIX gateway host
    from `NAPIX_BASE_URL`, the mail relay, the ClamAV servers unless a mirror or offline mode is used, and image
    registries at build time only (or `docker save` / `docker load`, decision 21).

18. **`job_runs` is repaired at start-up (audit Area 3).** A new module, `services/job_repair.py`, provides
    `repair_interrupted(session, jobs, before, reason)`. It sets `status = failed`, `finished_at = now()` and
    appends `interrupted: <reason>` to `error`, for every `running` row whose `job` is in `jobs` and whose
    `started_at < before`. Three processes call it at start, each for its own jobs only:
    - `queue-worker`, for `WORKER_JOBS = {"queue-run"}`;
    - the scheduler's `worker_ready` signal, for `SCHEDULER_JOBS` (every job name written by the Celery tasks:
      `extract_text`, `dedupe-sweep`, `rescore`, the alerts jobs, `notifications_send`, `digests`,
      `sourcetrace_ingest`, `next_dates_read`);
    - the backup scheduler, for `{"backup", "restore_check"}`.

    `before` is the process's start time. A test checks that every `JobRun(job=…)` name in the code belongs to
    exactly one set. A new command, `aslms ops repair-jobs [--older-than 6h] [--job NAME] [--dry-run]`, does the
    same by hand. No audit row is written: `job_runs` is a derived housekeeping table and the repair is logged.
    `fetch_queue` is not touched: `queue.requeue_stale` already re-queues rows left `running` for 30 minutes, and
    the API runs `request`-lane rows itself, so a worker restart must not re-queue them at once. Known limit: a
    hand-run `aslms queue-run` that overlaps a worker restart is reported as interrupted. The runbook says not to
    run it during a restart.

19. **Load counts and the sample-of-20 CNR check, defined.** Neither had a definition in the repository, only a
    name. Two read-only commands make them repeatable. Neither calls NAPIX.
    - `aslms ops load-report [--format md|json]` prints:
      - the period covered: first and last cause-list date held;
      - cause-list days loaded, skipped (no list), failed and pending; list PDFs stored; entries;
      - cases: total, with CNR, provisional with or without a CNR, pending and disposed;
      - dossiers applied, failed and never fetched;
      - parties, advocates and order references; order PDFs stored, pending, not available and failed; documents
        with text;
      - NAPIX calls in total and by outcome, and the average per day over the last 7 days;
      - `fetch_queue` rows by lane and status; open `source_failures` by kind;
      - database size; store files and bytes.

      It reuses `services/data_load.py` and `services/data_health.py` where they already compute a figure.
    - `aslms ops sample-cnrs [--pending 10] [--disposed 10] [--seed N] [--format md]` draws, reproducibly
      (`ORDER BY md5(cnr || seed)`), cases with a CNR and an applied dossier. For each case it prints the CNR; the
      case type, number and year; the first petitioner and respondent; the status; the filing and registration
      dates; the next date; the last listed or disposal date; the orders held (count and latest order date); and
      whether the latest order PDF is stored. Two blank columns follow: "court shows" and "match".

    The integrator or the owner compares each row by hand against the Gauhati High Court's public case status for
    that CNR. The check passes when every field matches, or when each difference is explained by a court-side
    change after the case's last refresh and confirmed with a re-fetch. More than two unexplained differences open a
    defect row, and deployment waits for it. The report, the seed and the filled table go into the decisions log
    under "Load counts and sample check (date)".

20. **The runbook, the README and the go-live checklist.** A new `docs/operations.md`, the file DB_STANDARD §11
    step 7 names, covers:
    - what runs: services, networks, volumes, ports;
    - host requirements: CPU, memory given to Docker, disk (database ~2 GB growing, order store tens of GB, backups
      roughly twice both), the egress allowlist;
    - first installation: `.env` with generated secrets, `APP_ENV=prod`, `PORTAL_BASE_URL`, the certificate and the
      CA on pilot PCs, `docker compose up -d`, the super admin's first sign-in, then clearing
      `ASLMS_SUPERADMIN_PASSWORD`;
    - database roles and URLs (`aslms` cluster superuser, `aslms_owner`, `aslms_app`, `aslms_readonly`,
      `DATABASE_URL_SYNC`, `ASLMS_MIGRATE_URL`);
    - secret rotation: a JWT change signs everyone out; role passwords through `role-passwords`; Redis; the cluster
      superuser's `ALTER ROLE`, because `POSTGRES_PASSWORD` applies only when a cluster is first created;
    - upgrading (decision 12); backups and the off-machine copy (13); restore check and disaster restore (14);
    - ClamAV modes (17); the NAPIX switch and the load (pause and resume on the Data collection screen, never
      switching NAPIX on in files); mail;
    - routine checks: daily (data-health screen, last backup), weekly (restore check, disk), monthly (certificate
      expiry, image updates);
    - troubleshooting: preflight refusals, "database behind head", uploads 503, sign-in 429, stuck jobs, disk full;
    - monitoring (filled by Part B).

    It ends with the **pilot go-live checklist**:
    - rows 76, 16, 77 and 78 merged;
    - preflight passes with `APP_ENV=prod`;
    - no port other than 443 and 80 reachable from another PC;
    - TLS checked from a pilot PC;
    - throttling checked;
    - EICAR refused through the proxy;
    - first backup and restore check passed; the restore drill time recorded;
    - load counts and the sample check in the decisions log;
    - the government mail relay live-checked with a real sign-in (row 27);
    - the owner's browser checklists (rows 53 and 56);
    - the mapping data for the pilot department entered (audit Top 10).

    `README.md` is rewritten to the current state: what the system is, the development quick start with
    `compose.dev.yml`, the pilot pointer to `docs/operations.md` and the main commands. `.env.example` gains
    sections for the proxy, Redis, backups, Postgres tuning, `COMPOSE_FILE` and `COMPOSE_PROFILES`. Its "aslms:aslms"
    defaults become blanks with generation hints. Row 76 corrects the role comment.

21. **Images are pinned, and there is a way to supply an offline host.** Every image uses an exact version tag
    chosen at build time and written in `compose.yml` (`postgres:16.<n>`, `redis:7.<n>-alpine`,
    `nginx:1.<n>-alpine`, `clamav/clamav:1.<n>`, and the Part B and C images). The backup image's `pg_dump` and
    the server must keep the same major version. No floating `stable` or `latest` tag is used. The runbook gives
    `docker compose build` on a connected machine, `docker save` of every image into one archive, and `docker
    load` on the target. Updates follow the upgrade procedure.

### Part B: row 77, `deployment-monitoring`

22. **Monitoring services run in profile `monitoring`, and `.env` sets `COMPOSE_PROFILES=monitoring` on the pilot.**
    The services are `prometheus` (30-day retention, own volume), `alertmanager`, `grafana`, `flower`,
    `postgres-exporter`, `redis-exporter` and `ops-exporter`. Images are pinned (decision 21). Their interfaces are
    published on `127.0.0.1` only: Grafana `127.0.0.1:3001`, Prometheus `9090`, Alertmanager `9093`, Flower `5555`.
    They are opened on the host, or through an SSH tunnel at the SDC, and never through the portal's proxy.
    `GRAFANA_ADMIN_PASSWORD` and `FLOWER_BASIC_AUTH` come from `.env`, use the required form and are checked by
    preflight. Grafana has anonymous access and sign-up off, and its only data source is Prometheus. No SQL data
    source is configured, because `aslms_readonly` can read every table, including password hashes, so Grafana
    never queries the database. When `APP_ENV=prod`, preflight refuses a `COMPOSE_PROFILES` without `monitoring`
    (plan §8.2). *Alternative:* Grafana through the proxy at `/grafana` (rejected for the pilot: more attack
    surface for an operators-only tool; Open questions 10).

23. **ASLMS operations metrics come from one read-only exporter.** `aslms ops metrics --port 9108` runs in the
    backend image as `aslms_readonly`, with a 10-second statement timeout and results cached for 60 seconds. It
    reuses `services/data_health.py` (`queue_depths`, `jobs`, `mail`, `napix_health`, `window_block`) and
    `services/napix_window.py`. It exposes these gauges:
    - `aslms_queue_rows{lane,kind,status}` and `aslms_queue_oldest_pending_seconds{lane}`;
    - `aslms_job_last_success_timestamp{job}`, `aslms_job_running{job}`, `aslms_job_running_oldest_seconds{job}`,
      and `aslms_worker_last_pass_timestamp` (the latest `queue-run` start, which is the worker's liveness; Flower
      sees only the Celery side);
    - `aslms_napix_calls_last_hour{outcome}`, `aslms_napix_window_remaining`, `aslms_napix_switch_on`;
    - `aslms_source_failures_open{kind}`, `aslms_notifications{status}`, `aslms_sourcetrace_documents{status}`;
    - `aslms_backup_last_success_timestamp`, `aslms_backup_last_size_bytes`,
      `aslms_restore_check_last_success_timestamp` (from `BACKUP_DIR/status`, mounted read-only);
    - `aslms_disk_free_bytes{path}` for `/data` and `/backups`;
    - `aslms_clamav_up` and `aslms_clamav_signature_timestamp` (clamd `VERSION`);
    - `aslms_probe_up{target}` for `portal` (`https://proxy/api/health`), `web` and `api`, and
      `aslms_tls_cert_expiry_timestamp`;
    - `aslms_scrape_errors`.

    No label carries case data.

24. **API request metrics.** `prometheus-client` joins the backend's dependencies. A middleware counts requests
    and measures their duration by method, **route template** (never the raw path, which carries case references)
    and status class. The API lifespan serves these metrics on port 9100. The proxy and the relay cannot reach that
    port: the relay only calls `api:8000`, and the proxy only reaches `web`. No `Permission` is needed, because
    the port is not exposed.

25. **Alert rules are Prometheus rules, tested with `promtool test rules` and e-mailed by Alertmanager.** Mail goes
    through the `SMTP_*` settings to `OPS_ALERT_EMAIL`. Without a mail relay the alerts are visible in Grafana and
    Alertmanager only. Rules:

    | Alert | Fires when |
    |---|---|
    | ServiceDown | `up == 0`, 5 minutes |
    | PortalDown | portal probe down, 5 minutes |
    | WorkerStalled | no worker pass for 2 hours while the queue has runnable rows |
    | JobStuck | a job `running` for more than 6 hours |
    | JobLate | no success within: notifications and alert scan 30 minutes; text extraction and next-dates reader 1 hour; dedupe sweep and digests 26 hours |
    | BackupMissing | no backup success for 13 hours |
    | RestoreCheckMissing | no restore-check success for 8 days |
    | DiskLow | under 15 % or under 10 GB free |
    | ClamAVDown | 5 minutes |
    | ClamAVSignaturesOld | older than 3 days |
    | NapixErrorsHigh | more than 100 failed calls in the last hour |
    | MailFailing | more than 10 failed notifications in an hour, or the oldest pending over 30 minutes |
    | CertExpiring | under 21 days |
    | PostgresConnectionsHigh | over 80 % of `max_connections` |
    | RedisDown | 5 minutes |

    The runbook says what to do for each.

26. **Grafana dashboards are provisioned from files** in `infra/grafana/`:
    - "ASLMS overview": services and probes, queue by lane, the NAPIX window, jobs, mail, SourceTrace, backups,
      disk, certificate;
    - "PostgreSQL": the community exporter dashboard, trimmed;
    - "Redis and Celery".

27. **`aslms_readonly` gets `pg_monitor`. This is a small, flagged extension of DB_STANDARD §8.** The postgres
    exporter needs the statistics views (`pg_stat_activity` of other roles, `pg_stat_bgwriter`, database sizes).
    A new migration grants the predefined role `pg_monitor` to `aslms_readonly`. It gives statistics only: no table
    rights beyond the SELECT the role already has and no write. *Alternatives:* a separate `aslms_monitor` login
    role (rejected: a fourth role and password for the same read-only purpose); running the exporter as the
    superuser (rejected: the reason this item exists).

28. **Host metrics are optional.** A `monitoring-host` profile adds `node-exporter` and `cadvisor` for a Linux VM
    at the SDC. They are not used on Docker Desktop, where they would describe Docker's VM, not the machine. On
    Docker Desktop, disk space comes from the ops exporter (decision 23).

### Part C: row 78, `deployment-pgbouncer`

29. **PgBouncer in transaction mode for `api`, `worker` and `scheduler`.** The plan's stack and the owner's 1 Oct
    decision both name it.
    - **Image:** a small one built from pinned Alpine with `pgbouncer` at 1.21 or later (`infra/pgbouncer/`). The
      entrypoint writes `pgbouncer.ini` and a mode-600 `userlist.txt` for `aslms_app` from `.env` at start.
    - **Settings:** `pool_mode=transaction`, `max_client_conn=200`, `default_pool_size=20`,
      `max_prepared_statements=200` (psycopg 3 prepares statements at the protocol level; PgBouncer 1.21+ tracks
      them), `auth_type=scram-sha-256`, `server_reset_query` empty. It listens on `6432` on the internal network
      only.
    - **Who goes through it:** the three services' `DATABASE_URL_SYNC` points at `pgbouncer:6432`. `init`,
      `migrate`, `backup` and the exporters connect directly to `postgres`, because they need session features,
      DDL or a view that does not depend on the pool.
    - **Compatibility, checked in the code:** the application uses only transaction-scoped features
      (`pg_advisory_xact_lock` in `case_dedupe.py`, `SET LOCAL statement_timeout` in the report, dashboard and
      audit queries), with no `LISTEN`, no session `SET` and no temporary tables. Transaction pooling is therefore
      safe. The design adds a test that fails on any session-level `SET`, `pg_advisory_lock(` or `LISTEN` in
      `backend/aslms`.
    - **Monitoring:** `pgbouncer-exporter` joins Part B's scrape list, with an alert when clients wait more than
      5 minutes.
    - **Migrations:** `migrate`'s "no `aslms_app` session" check (decision 12) sees PgBouncer's server
      connections, so the runbook's upgrade procedure also stops `pgbouncer`.

    At pilot load (about 10-20 connections) PgBouncer gains little. It is designed because the plan and the owner
    put it in the pilot stack. The owner may defer row 78 to the SDC move, which would be recorded as a deviation
    (owner check 7).

## Data
**Part A: no table, no column, no reference code, no migration.** New audit actions are free-text action codes, as
elsewhere: `system.migrated` (decision 12) and `system.restored` (decision 14). `job_runs` gains new `job` values
`backup` and `restore_check` (free text, no schema change).

**Part B: one migration** with the next free number when row 77 is built, after 0018 and after any migration row 76
adds:
- upgrade: `GRANT pg_monitor TO aslms_readonly`;
- downgrade: `REVOKE pg_monitor FROM aslms_readonly`.

Paragraph for `docs/schema/schema.md`, Conventions, the **Roles** bullet (replacing its last clause):

> `aslms_readonly` (SELECT on every table; member of the predefined role `pg_monitor` for the statistics views read
> by the Prometheus postgres exporter, migration 00NN, design deployment-checklist decision 27; no write and no DDL).
> The cluster superuser (`POSTGRES_USER`) is used only by `init`, `migrate` and `backup`; the application never
> connects as it (design deployment-checklist decision 5).

**Part C: none.**

## Services
Part A (row 16):
- `backend/aslms/services/preflight.py`: `check(settings, component) -> list[Finding]`, where a `Finding` is
  `(level: error|warning, variable, message)`. The rules are in decision 3. Messages never contain a value.
  `raise_on_errors(findings, is_prod)`.
- `backend/aslms/services/db_guard.py`: `state(conn, script_dir) -> fresh|at_head|behind|ahead`, a pure comparison
  of `alembic_version` against `ScriptDirectory.get_current_head()`; `guard(url)` runs `upgrade head` only on
  `fresh`. Plus `role_passwords(url, settings)` (decision 12).
- `backend/aslms/services/job_repair.py`: `WORKER_JOBS`, `SCHEDULER_JOBS`, `BACKUP_JOBS`,
  `repair_interrupted(...)` (decision 18).
- `backend/aslms/services/backups.py`:
  - `dump(url, backup_dir, tag) -> Manifest` (runs `pg_dump` and `pg_dumpall` by subprocess with the password
    passed through `PGPASSWORD` in the child environment only, never on the command line);
  - `mirror_store(store_dir, mirror_dir) -> (copied, bytes)`;
  - `select_keep(sets, now, policy) -> set` (pure);
  - `prune(...)`;
  - `restore_check(url, backup_dir, dump=None) -> Result`;
  - `restore(...)`;
  - `scheduler_loop(settings)`.

  It writes the `job_runs` rows and the status files.
- `backend/aslms/services/load_report.py`: `report(session) -> dict` and `sample(session, pending, disposed, seed)
  -> list[dict]`, with Markdown renderers (decision 19). Read-only.
- `backend/aslms/cli/ops.py`: the `aslms ops` group. Its commands are `preflight`, `db-guard`, `role-passwords`,
  `migrate`, `backup [--tag]`, `backup-scheduler`, `backup-status`, `restore-check`, `restore`, `repair-jobs`,
  `load-report`, `sample-cnrs` and `make-cert`. It is registered in `cli/main.py`, whose docstring lists it.
- `backend/aslms/api/main.py`: documentation URLs by `APP_ENV` (decision 4); superuser refusal in the lifespan when
  in prod (decision 5).
- `backend/aslms/cli/pipeline.py` `queue_worker`, and `backend/aslms/jobs/celery_app.py` (a `worker_ready`
  handler): repair at start and the superuser refusal.
- `backend/aslms/core/config.py`: `backup_dir`, `backup_interval_hours` (1-24), `backup_keep_recent_hours`,
  `backup_keep_daily`, `backup_keep_weekly`, `backup_keep_monthly`, `backup_keep_premigrate`, `mail` checks reused
  from `services/otp.py`. `REDIS_PASSWORD`, the proxy settings and the `PG_*` settings are read by Compose only.
- `backend/Dockerfile`: `postgresql-client-16` from the PostgreSQL apt repository; user 10001.
- `frontend/src/server/config.ts` (`trustProxyHeaders` from `TRUST_PROXY_HEADERS`); `frontend/src/server/api.ts`
  `clientAddress` (decision 8); `frontend/src/lib/messages.ts` (`throttled`).
- Infrastructure files:
  - `compose.yml`, `compose.dev.yml`, `compose.clamav-mirror.yml`, `compose.clamav-offline.yml`;
  - `infra/proxy/aslms.conf.template` and `infra/proxy/15-aslms-limits.sh`;
  - `infra/clamav/freshclam.conf.example` and `infra/clamav/import-signatures.sh`;
  - `.gitignore` gains `backups/` and `infra/proxy/certs/`.
- Documents: `docs/operations.md`, `README.md`, `.env.example`.

Part B (row 77):
- `backend/aslms/services/ops_metrics.py` (decision 23) and `aslms ops metrics`.
- `backend/aslms/api/metrics.py` (decision 24).
- `infra/prometheus/prometheus.yml`, `rules.yml`, `rules.test.yml`; `infra/alertmanager/alertmanager.yml.template`;
  `infra/grafana/provisioning/*`, `dashboards/*.json`.
- The migration and `schema.md` (Data).

Part C (row 78): `infra/pgbouncer/Dockerfile` and `entrypoint.sh`; the Compose service and URLs.

Audit: `system.migrated` and `system.restored` through `services/audit.py` `write_audit` with `Actor.system("ops")`.
The audit screen's action grouping (frontend) gains a "System" group for the `system.` prefix if it groups by
prefix. Nothing else in this item is a significant user action. Backups, checks and repairs are recorded in
`job_runs`. Reading reports is not audited (the owner's decision).

## API
No new endpoint and no new `Permission`.

- `GET /docs`, `GET /redoc`, `GET /openapi.json` answer **404 unless `APP_ENV=dev`** (decision 4). They were never
  reachable through the relay.
- **Part B:** API metrics on port 9100, inside the Compose network only (decision 24). This is not a route of the
  public API, the relay or the proxy.
- **Proxy-level answers the portal must understand:** 429 `{"detail":{"code":"throttled","message","retry_after"}}`
  on `/api/session/*` and `/api/backend/*`, and 413 `{"detail":{"code":"too_large","message"}}`. Visibility rules
  are unchanged; every query is still filtered on the server.

## Jobs
- **Backup scheduler** (Part A; the `backup` service; not Celery):
  - `backup` at minute 30 every `BACKUP_INTERVAL_HOURS` hours IST, `job_runs.job = "backup"`, counters `{db_bytes,
    roles_bytes, store_files_copied, store_bytes_copied, seconds, pruned_sets}`;
  - `restore_check` on Sunday at 04:30 IST, `job_runs.job = "restore_check"`, counters `{revision, tables_compared,
    mismatches, files_checked, files_bad, seconds}`;
  - a failed run writes `status = failed` with the error, never a secret.
- **Start-up repair** (Part A): `queue-worker`, the scheduler's `worker_ready` and the backup scheduler (decision
  18).
- No change to the Celery beat schedule. No NAPIX call is added anywhere in this item. The NAPIX master switch is
  not touched in any file.

## Tests
Unit tests (`backend/tests/unit/`). The Compose tests parse the YAML, as `test_compose_web.py` does:
- `test_compose_publishes_only_the_proxy`: in `compose.yml` only `proxy` has `ports`. In Part B, every monitoring
  port starts with `127.0.0.1:`.
- `test_compose_dev_override_binds_loopback_only`: every port in `compose.dev.yml` starts with `127.0.0.1:`, and it
  sets `TRUST_PROXY_HEADERS=false`.
- `test_compose_required_secrets_have_no_default`: `POSTGRES_PASSWORD`, `ASLMS_APP_PASSWORD`, `REDIS_PASSWORD` and
  `PORTAL_BASE_URL` appear only in the `${X:?…}` form. No `:-aslms` default remains for a password.
- `test_compose_redis_password_and_no_persistence`: the `requirepass`, `--save ""` and `--appendonly no` flags; no
  Redis volume; every `REDIS_URL` carries the password.
- `test_compose_init_guards_instead_of_migrating`: the `init` command contains `ops preflight`, `ops db-guard` and
  `seed`, and not `alembic upgrade`. `migrate` is in profile `ops`, and its command runs `ops migrate`.
- `test_compose_owner_url_only_in_ops_services`: `ASLMS_MIGRATE_URL` and the superuser credentials appear only in
  `init`, `migrate` and `backup`.
- `test_compose_logging_and_hardening`: every service has the rotated logging and `no-new-privileges`; the listed
  services have `cap_drop: [ALL]`; no image tag is `latest` or `stable`.
- `test_compose_postgres_tuning`: the `PG_*` flags and `shm_size`.
- `test_compose_single_web_process`: `web` has no `deploy.replicas` and no `scale`.
- `test_compose_web` (updated): `web`'s environment adds `TRUST_PROXY_HEADERS`. `web` is on the `portal` and
  `edge` networks and `proxy` only on `edge`.
- `test_proxy_body_limits_match_the_api`: the limits written by `15-aslms-limits.sh` for sample values (run with
  `sh` when available, or the same arithmetic parsed from the script) equal `_body_limit(...) +
  MULTIPART_OVERHEAD` for a document upload, a note and head-change.
- `test_proxy_overwrites_forwarded_for`: the template sets `X-Forwarded-For $remote_addr` and never uses
  `$proxy_add_x_forwarded_for`.
- `test_proxy_throttles_session_and_answers_json`: the `limit_req` zones on `/api/session/` and `/api/backend/`,
  `limit_req_status 429`, and a JSON body with code `throttled`.
- `test_api_docs_only_in_dev`: with `app_env=prod`, `/docs`, `/redoc` and `/openapi.json` answer 404; with `dev`
  they answer 200. `app.openapi()` works in both.
- `test_preflight_refuses_*` in prod: a short JWT secret; each default password; a password equal to its user or to
  another; a Redis URL without a password; an `http://` portal address; `COOKIE_SECURE=false`; console mail; the
  Mailtrap sandbox URL. Also `test_preflight_only_warns_in_dev` and `test_preflight_never_prints_a_secret` (the
  output is captured and must not contain any value).
- `test_db_guard_states`: the pure comparison for fresh, at head, behind and ahead, with the exit codes and
  messages.
- `test_job_repair_sets_cover_every_job_name`: every `JobRun(job=…)` literal and job constant in `backend/aslms`
  belongs to exactly one of the three sets.
- `test_backup_select_keep`: the retention policy over a synthetic 15-month series (recent, daily, weekly,
  monthly, pre-migrate; the store is never pruned).
- `test_backup_mirror_is_add_only_and_verified`: in a temporary directory, files are copied once, an existing file
  is not overwritten, and a file whose content does not match its name is reported, not copied.
- `test_backup_never_passes_password_on_command_line`: the subprocess arguments do not contain the password; it is
  passed through the environment.
- `test_restore_check_refuses_other_names` and `test_restore_refuses_with_app_sessions` (with a fake connection).
- `test_queue_worker_repairs_at_start` and `test_scheduler_worker_ready_repairs` (monkeypatched), and
  `test_superuser_refused_in_prod` (a fake `rolsuper` answer).
- `test_make_cert_has_sans_and_validity` (`cryptography` reads the result back).
- Frontend (Vitest), `src/server/api.test.ts`: `clientAddress` returns the rightmost entry with
  `TRUST_PROXY_HEADERS=true`, ignores a forged leftmost entry, and returns null with `false`. `messages`:
  `throttled` has a text.

Database tests (`backend/tests/db/`):
- `test_repair_interrupted_marks_only_own_jobs_before_start`: `running` rows of other jobs, rows started after the
  start time, and finished rows are untouched.
- `test_load_report_counts`: on a seeded fixture of cases, entries, orders and queue rows, every figure equals a
  direct count.
- `test_sample_cnrs_reproducible_and_stratified`: the same seed gives the same rows, and the requested numbers of
  pending and disposed cases come back, all with a CNR and an applied dossier.
- `test_superuser_check_reads_current_role`: under `SET ROLE aslms_app`, `rolsuper` is false; as the test superuser
  it is true.
- `test_audit_system_migrated_row`: `ops migrate`'s audit helper writes `system.migrated` with the before and after
  revisions. The Alembic run itself is stubbed.

Part B: `promtool test rules infra/prometheus/rules.test.yml` (run in the Prometheus image in Verification);
`test_ops_metrics_exposes_gauges` (database: every gauge is present and no label value contains a CNR or a case
number); `test_api_metrics_use_route_templates`; `test_compose_monitoring_profile`; the migration upgrade, downgrade
and upgrade cycle (the existing migration test pattern).

Part C: `test_no_session_level_postgres_features` (a source scan); `test_compose_pgbouncer_urls` (the app services
go through `pgbouncer:6432`; init, migrate, backup and the exporters go direct).

## Verification
The integrator runs these steps for Part A. They run in a **separate Compose project** (`-p aslms-pilotcheck`,
its own `.env` copy with `APP_ENV=prod` and generated secrets, its own volumes, `BACKUP_DIR` and `./data` copy), so
the dev database and the running historical load are not disturbed until step 14.
1. `pytest -q` (unit, and the database tests against `aslms_test`), `ruff check`, frontend `npm test` and
   `npm run lint`: all green.
2. `docker compose -p aslms-pilotcheck config` renders. Then `docker compose -p aslms-pilotcheck up -d --wait` from
   empty volumes: `init` runs preflight, migrates the fresh database to head and seeds, and every service is
   healthy. With one password set to `aslms`, `init` exits with the preflight message naming the variable, and
   nothing else starts.
3. From another PC on the LAN, or from the host using its LAN address: `https://<host>/` loads the portal with the
   internal CA installed; `http://<host>/` answers 301; a different `Host` header is refused; ports 5433, 6379,
   8000, 3000 and 3310 are closed (`Test-NetConnection` or `nc -z`).
4. `https://<host>/api/backend/docs` and `/openapi.json` answer 404 through the relay. Inside the network, `docker
   compose exec api python -c "…urlopen('http://127.0.0.1:8000/docs')"` answers 404.
5. `docker compose exec redis redis-cli ping` without the password answers `NOAUTH`. After 10 minutes the beat jobs
   have written `job_runs` rows, so the broker works with the password. NAPIX stays off for the whole run.
6. Sign-in throttling: 30 quick `POST /api/session/login` requests from one address give 429 `throttled` after the
   burst, and the portal shows the message. A sign-in sent with a forged `X-Forwarded-For: 1.2.3.4` writes an
   audit row with the real client address.
7. Uploads through the proxy: a 19 MB PDF is stored; a 21 MB file is refused 413 `too_large`; a note with five
   19 MB attachments passes the proxy; `aslms documents scan-check` passes; an EICAR file uploaded through the
   portal is refused (`infected`) and audited.
8. Migration guard: `docker compose -p aslms-pilotcheck run --rm migrate alembic downgrade -1` (owner URL), then
   `up -d`: `init` exits 3 with the "run migrate" message and `api` does not start. `docker compose -p
   aslms-pilotcheck stop api worker scheduler web`, then `--profile ops run --rm migrate`: a `pre-migrate` dump
   appears and is listed by `pg_restore --list`, the database returns to head, a `system.migrated` audit row
   exists, and `up -d` starts everything.
9. `docker compose exec backup aslms ops backup` writes the dump, roles file, manifest, store mirror and a
   `job_runs` row shown on the data-health screen. `aslms ops restore-check` passes with zero mismatches.
   `aslms ops backup-status` prints both.
10. Restore drill: on a second empty project (`-p aslms-restoretest`), `aslms ops restore` from step 9's dump,
    roles and mirror; start; the super admin signs in; `aslms ops load-report` equals the manifest's counts. Record
    the time from empty to signed in.
11. `job_runs` repair: with a `queue-run` row `running`, `docker compose restart worker` marks it `failed` with
    `interrupted`. The same for a scheduler job and `docker compose restart scheduler`.
12. ClamAV offline mode: with `compose.clamav-offline.yml`, import signatures from a `cvdupdate` folder; `clamav`
    turns healthy with `freshclam` not running, and `scan-check` passes.
13. Container hardening: `docker compose exec api id -u` prints 10001. On the scratch project an upload and an
    order-PDF store write still succeed.
14. Dev cut-over (the owner's machine; after row 76 is live there):
    - `ALTER ROLE aslms PASSWORD …` in `psql`, then the new `.env` values with `COMPOSE_FILE` including
      `compose.dev.yml`;
    - `docker compose up -d`; `init` passes (the dev database is at head);
    - the historical load continues: `aslms data-load status` before and after, with `fetch_queue` pending
      decreasing;
    - the first backup of the dev database is the `pg_dump` CLAUDE.md asks for.
15. Load counts and the sample: `aslms ops load-report --format md` and `aslms ops sample-cnrs --seed 20261018
    --format md` on the dev database. The 20 rows are checked by hand against the court's public case status, and
    the report, seed, table and verdict go in the decisions log (decision 19).

Part B adds:
- `docker compose --profile monitoring up -d --wait`;
- every Prometheus target is up; `promtool test rules` passes;
- Grafana at `127.0.0.1:3001` shows the overview with live figures;
- stopping `clamav` fires ClamAVDown within 5 minutes and Alertmanager sends the e-mail (when a mail relay is
  configured);
- Flower lists the beat tasks;
- the migration's upgrade, downgrade and upgrade cycle.

Part C adds:
- the API smoke (sign-in, case list, claim, a note, an upload) through PgBouncer;
- `SHOW POOLS` shows `aslms_app` traffic;
- `pg_stat_activity` shows the app's server connections from `pgbouncer`;
- the report and audit screens (`SET LOCAL statement_timeout`) and a court-number dedupe path
  (`pg_advisory_xact_lock`) work.

## Open questions
These are owner checks. Each has a recommended default, and none blocks the design: every default can be built
and changed later in `.env`. They are listed for the owner to confirm at approval.

1. **Where the pilot runs, and the host's size.** Default: the owner's machine on the office LAN, per the 1 Oct
   decision, with at least 8 GB of memory given to Docker and 200 GB free (database, order store, backups). The
   same files serve an SDC VM.
2. **The portal's address and certificate source.** Default: the machine's name on the closed network (or its
   fixed address), with a certificate from the internal CA made by `aslms ops make-cert` and the CA installed on
   pilot PCs. A NIC- or SDC-issued certificate replaces the two files when the SDC address exists. The address is
   not invented in this note; the owner gives it in `.env` (`PORTAL_BASE_URL`).
3. **The government mail relay.** Default: the State's government relay (NIC or SDC) with a sender on an
   `assam.gov.in` domain, live-checked under row 27. Until it exists, Mailtrap's sending service (not the
   sandbox) with a verified domain. Preflight refuses the sandbox when `APP_ENV=prod`, because nobody could sign
   in. The SMS or break-glass question of audit Top 5 stays with the owner.
4. **Backup retention and the off-machine copy.** Default: every 6 hours; everything for 48 hours, 14 daily,
   8 weekly, 12 monthly and 5 pre-migrate sets; the store mirror kept for ever. `BACKUP_DIR` on a second physical
   disk, with a weekly copy to an encrypted external drive (BitLocker To Go) kept away from the machine. At the
   SDC, their backup service. Measure the first dump's size and adjust.
5. **The acceptable loss window.** Default: up to 6 hours of user work for the pilot. If less is needed, a
   follow-up row adds WAL archiving with point-in-time recovery.
6. **Sign-in throttling numbers.** Default: 20 requests a minute per address with a burst of 20 on
   `/api/session/*`, and 30 a second with a burst of 100 on the rest. This is generous because a whole office may
   share one NAT address.
7. **PgBouncer for the pilot (row 78) or at the SDC move.** Recommendation: build it now, as the plan and the
   1 Oct decision say. Deferring it is a recorded deviation.
8. **`APP_ENV=prod` on the pilot.** Recommendation: yes. It gives JSON logs, refuses console mail, turns off the API
   documentation and makes preflight strict.
9. **Upgrades become an explicit `migrate` step.** `up` no longer migrates, except on a fresh database.
   Recommendation: yes; the audit asks for it.
10. **Who receives monitoring alerts and how the monitoring screens are reached.** Default: `OPS_ALERT_EMAIL` = the
    super admin's mailbox, with Grafana, Prometheus, Alertmanager and Flower on the host's loopback only (an SSH
    tunnel at the SDC).
11. **Row numbering.** Rows 77 and 78 are added below row 16. If the concurrent `safety-fixes` cycle also adds rows
    77 or 78, the integrator renumbers them at merge.

## Deviations
- **Monitoring and PgBouncer are built in rows 77 and 78, after row 16.** The plan (§8.2) and the 1 Oct decision
  want monitoring in place from the pilot stage, so both rows are on the go-live checklist. The split is a build
  order, not a change of scope.
- **`aslms_readonly` is a member of `pg_monitor`** (decision 27): it gains read-only statistics beyond DB_STANDARD
  §8's "SELECT".
- **The monitoring interfaces are not served through the portal's proxy** (decision 22). They are loopback only.
- **`docker compose up` no longer applies migrations to an existing database** (decision 12). This changes the
  "one command migrates and seeds" note at the top of `compose.yml` and the 1 Oct Compose decision; the decisions
  log records it when the item is built.

### Deviations made while building Part A (developer, 19 Oct 2026)
- **Role passwords:** row 76 built `aslms db-roles`, so Part A extends that step and adds no second one (decision 12
  allows this). `init` runs `aslms ops preflight && aslms ops db-guard && aslms db-roles && aslms seed`.
  `aslms ops role-passwords` calls the same function. The `ALTER ROLE` now runs under
  `SET LOCAL log_statement = 'none'`.
- **Preflight reads four more settings:** `POSTGRES_USER`, `POSTGRES_PASSWORD`, `REDIS_PASSWORD` and `COOKIE_SECURE`
  are `Settings` fields, so preflight can check them. The design said Compose alone reads them. Compose passes them
  to `init` and `migrate` explicitly.
- **URL-safe passwords:** preflight also refuses a database or Redis password with a character other than letters,
  digits, `_` and `-`, because Compose puts the passwords into URLs unencoded. This is the rule `aslms db-roles`
  already applies (safety-fixes).
- **The read-only password:** preflight also checks `ASLMS_READONLY_PASSWORD` when it is set, with the same rules,
  and requires it to differ from the others. Part B makes it required.
- **The owner's credentials are blanked in the application services:** `api`, `worker` and `scheduler` read `.env`
  through `env_file`. Compose therefore sets their `POSTGRES_PASSWORD` and `ASLMS_MIGRATE_URL` to empty strings, so
  the owner's credentials never reach them (row 82).
- **Image tags:** `nginx:1.28-alpine` is pinned at the minor version, so it takes nginx's security patches; that is
  the `nginx:1.<n>-alpine` form of decision 21. The other images, and the two Dockerfile base images
  (`python:3.12.15-slim`, `node:22.23.3-alpine`), are pinned at the exact version found on the dev machine.
- **The proxy in development:** `compose.dev.yml` puts `proxy` in profile `proxy`, because development has no
  certificate. Without this, the proxy would restart in a loop on every `docker compose up -d`.
- **`COMPOSE_PATH_SEPARATOR=:`** is in `.env.example` next to `COMPOSE_FILE`. On Windows, Compose otherwise splits
  `COMPOSE_FILE` on `;`.
- **ClamAV mirror mode:** the operator sets the `PrivateMirror` line in `infra/clamav/freshclam.conf`, copied from
  the example. There is no `${CLAMAV_MIRROR}` variable, because freshclam does not expand variables.
- **Small additions:**
  - The proxy has a loopback-only `/nginx-health` on its port-80 default server, for its health check.
  - `redis` has a health check, and `worker` and `scheduler` wait for it to be healthy.
  - `backup` mounts the store read-only. `aslms ops restore` runs through the `migrate` service, which mounts the
    store read-write.
  - `ops migrate` exits 2 while `aslms_app` is connected.
  - A backup whose store mirror finds a mismatched file is recorded as `partial`.
  - The restore check runs `pg_restore --no-owner` into the scratch database.
  - The internal CA uses EC P-256 keys.
- **Beat's schedule file is in `/tmp`** (review fix): the image runs as uid 10001 and `/app` is root-owned, so the
  scheduler runs `worker -B -s /tmp/celerybeat-schedule`. The file is lost when the container is recreated; beat
  then starts fresh and each entry fires at its next due time, which is what the crontab schedule already does.
- **Documents left to the scribe:** the decisions log entry (including the change of behaviour "`up` no longer
  migrates an existing database"), `CLAUDE.md` "Current focus" and the backlog rows 16, 24, 33, 43, 44, 80 and 82.
