# ASLMS operations runbook

How to install, run, upgrade, back up and restore the ASLMS pilot. Written for the design
[deployment-checklist](design/deployment-checklist.md) (Part A, backlog row 16). DB_STANDARD §11 step 7 names this
file. Monitoring (Part B, row 77) is section 17; PgBouncer (Part C, row 78) is section 18; the repository and CI
(design [github-and-ci](design/github-and-ci.md)) are section 19.

Never write the NAPIX master switch into a file. The owner sets it in the shell for the run that needs it
(`docs/napix_integration_notes.md`). Never print or paste a secret from `.env`.

## 1. What runs

One Docker Compose stack on one host. The same files serve the owner's machine and a State Data Centre VM.

| Service | Image | Role | Published |
|---|---|---|---|
| `proxy` | `nginx:1.28-alpine` | TLS, the host-name check, body limits, per-address throttling, `X-Forwarded-For` | 443 and 80 (80 only redirects) |
| `web` | built from `frontend/` | the portal (Next.js backend-for-frontend), one process | none |
| `api` | built from `backend/` | the HTTP API, as `aslms_app` | none |
| `worker` | built from `backend/` | the NAPIX load-and-refresh queue (`aslms queue-worker`), as `aslms_app` | none |
| `scheduler` | built from `backend/` | Celery beat and its jobs, as `aslms_app` | none |
| `init` | built from `backend/` | preflight, the migration guard, role passwords, seed; then exits | none |
| `backup` | built from `backend/` | dumps, the store mirror, retention, the weekly restore check | none |
| `migrate` | built from `backend/` | profile `ops`: the explicit upgrade (and `aslms ops restore`) | none |
| `postgres` | `postgres:16.15` | the database | none |
| `pgbouncer` | built from `infra/pgbouncer/` (Alpine 3.23.3, PgBouncer 1.25.1 pinned; 1.22+ required) | connection pooling in transaction mode for `api`, `worker` and `scheduler` (section 18) | none |
| `redis` | `redis:7.4.10-alpine` | the NAPIX token and Celery messages; password, memory only | none |
| `clamav` | `clamav/clamav:1.5.4` | virus scan of every upload | none |
| `prometheus` | `prom/prometheus:v3.7.2` | profile `monitoring`: scrapes, keeps 30 days, evaluates the alert rules | `127.0.0.1:9090` |
| `alertmanager` | `prom/alertmanager:v0.29.0` | profile `monitoring`: mails the alerts to `OPS_ALERT_EMAIL` | `127.0.0.1:9093` |
| `grafana` | `grafana/grafana:12.2.1` | profile `monitoring`: the dashboards; Prometheus is its only data source | `127.0.0.1:3001` |
| `flower` | `mher/flower:2.0.1` | profile `monitoring`: the Celery tasks of the scheduler | `127.0.0.1:5555` |
| `postgres-exporter` | `quay.io/prometheuscommunity/postgres-exporter:v0.18.1` | profile `monitoring`: database statistics, as `aslms_readonly` | none |
| `redis-exporter` | `oliver006/redis_exporter:v1.78.0` | profile `monitoring`: Redis and the Celery queue length | none |
| `pgbouncer-exporter` | `quay.io/prometheuscommunity/pgbouncer-exporter:v0.12.1` | profile `monitoring`: PgBouncer's pools, from its console as `aslms_readonly` | none |
| `ops-exporter` | built from `backend/` | profile `monitoring`: `aslms ops metrics`, the ASLMS operations gauges, as `aslms_readonly` | none |
| `node-exporter`, `cadvisor` | `prom/node-exporter:v1.10.2`, `gcr.io/cadvisor/cadvisor:v0.52.1` | profile `monitoring-host`: host and container metrics on a Linux VM | none |

Networks:
- `default`: postgres, pgbouncer, redis, clamav and the backend services.
- `portal`: api and web. It has a fixed subnet, and the api trusts `X-Forwarded-For` only from `WEB_IP`.
- `edge`: web and proxy. The proxy cannot reach api, postgres or redis.

Volumes:
- `pgdata_v3`: the database. On Docker Desktop it lives inside the Docker VM disk, which a Docker reset erases. The
  backups therefore go to a host folder.
- `clamdb_v3`: ClamAV signatures.
- `prometheus_v3`, `alertmanager_v3`, `grafana_v3`: monitoring history, silences and Grafana's own settings. Losing
  them loses no ASLMS data.
- Bind mounts: `./data` (the document store `data/store` and the cause-list PDFs), `BACKUP_DIR` (default
  `./backups`) and `infra/proxy/certs`.

Every container's logs are rotated (`json-file`, 20 MB × 5). The backend image runs as uid 10001. Every service has
`no-new-privileges`, and the application services drop every Linux capability.

## 2. Host requirements

- **CPU and memory:** 4 cores. Give Docker at least 8 GB: Postgres 1-2 GB, ClamAV about 1.5 GB (more during a
  signature reload), the rest for the API, the workers and the portal. With less memory, lower the `PG_*` values
  (section 9).
- **Disk:** the database is about 2 GB and grows with the load. The order store grows to tens of GB. Backups need
  roughly twice both. Plan 200 GB free, SSD. `BACKUP_DIR` belongs on a second physical disk.
- **Egress allowlist (SDC):**
  - the NAPIX gateway host from `NAPIX_BASE_URL` (HTTPS);
  - the mail relay (SMTP or the Mailtrap sending API);
  - the ClamAV database servers, unless the mirror or offline mode is used (section 12);
  - image registries at build time only, or none with `docker save` / `docker load` (section 8).
- **Inbound:** 443 and 80 to the proxy only, from the office network.

## 3. First installation

1. Install Docker (Docker Desktop on Windows, Docker Engine with the compose plugin on Linux) and clone the
   repository.
2. Copy `.env.example` to `.env` and fill it in:
   - `APP_ENV=prod`, exactly, in lower case: only `dev`, `test` and `prod` are accepted, and any other value
     (`production`, `Prod`) stops every service;
   - `COMPOSE_FILE=compose.yml`. The development override must not be used on the pilot;
   - generate each secret separately with `openssl rand -hex 32` (or
     `python -c "import secrets;print(secrets.token_hex(32))"`): `POSTGRES_PASSWORD`, `ASLMS_APP_PASSWORD`,
     `ASLMS_READONLY_PASSWORD`, `REDIS_PASSWORD`, `ASLMS_JWT_SECRET`, `GRAFANA_ADMIN_PASSWORD` and the password of
     `FLOWER_BASIC_AUTH` (`ops:<password>`). Every value must be different;
   - `COMPOSE_PROFILES=monitoring` and `OPS_ALERT_EMAIL` (section 17);
   - `PORTAL_BASE_URL=https://<host name or fixed address on the office network>`;
   - the mail service (section 13), `ASLMS_SUPERADMIN_EMAIL` and `ASLMS_SUPERADMIN_PASSWORD`;
   - the NAPIX credentials (never the switch);
   - `BACKUP_DIR` on the second disk, for example `E:/aslms-backups`.
3. Make the certificate. Use one from NIC or the SDC if there is one: copy it to
   `infra/proxy/certs/fullchain.pem` (with the chain) and `privkey.pem`. On a closed network, make an internal CA
   (on Linux, first `mkdir -p infra/proxy/certs && sudo chown 10001:10001 infra/proxy/certs`):

   ```
   docker compose run --rm --no-deps -v ./infra/proxy/certs:/certs init aslms ops make-cert --host <name> --ip <address> --out /certs
   ```

   Install `infra/proxy/certs/ca.crt` once on each pilot PC (Windows: open it, Install Certificate, Local Machine,
   "Trusted Root Certification Authorities"). Then **move `ca.key` off the host** to safe storage. It can sign
   certificates that every pilot PC trusts. The server certificate is valid for 825 days.
4. On a Linux host, give the containers' user the data folders: `sudo chown -R 10001:10001 data <BACKUP_DIR>`.
   Docker Desktop needs nothing.
5. `docker compose up -d`. `init` runs preflight. On a fresh database it migrates to head, sets the role passwords and
   seeds; then every service starts. Watch it with `docker compose ps` and `docker compose logs init`.
6. The super admin signs in at `https://<host>/` with the e-mailed code and changes the password. Then clear
   `ASLMS_SUPERADMIN_PASSWORD` in `.env` (preflight warns while it is set) and run `docker compose up -d` again.
7. Check: `docker compose exec backup aslms ops backup` writes the first backup;
   `docker compose exec backup aslms ops restore-check` passes; `aslms documents scan-check` passes inside `api`.

## 4. Database roles and URLs

| Role | Used by | Rights |
|---|---|---|
| `aslms` (`POSTGRES_USER`) | `init`, `migrate`, `backup` only | the cluster superuser: migrations, seed, role passwords, dumps |
| `aslms_owner` | owns the schema objects (migration 0001) | DDL |
| `aslms_app` | `api`, `worker`, `scheduler`, through `pgbouncer` | DB_STANDARD §8 grants; no delete of legal records |
| `aslms_readonly` | the postgres exporter and the ops exporter (Part B); the pgbouncer exporter on PgBouncer's console (Part C) | SELECT, and member of `pg_monitor` for the statistics views (migration 0020) |

- In production (`APP_ENV=prod`), the api, the worker and the scheduler refuse to start if their connection is a
  superuser (decision 5). Their `POSTGRES_PASSWORD` and `ASLMS_MIGRATE_URL` are blanked by Compose.
- `DATABASE_URL_SYNC` is the application's URL. Compose builds it for each service from the passwords. For `api`,
  `worker` and `scheduler` it points at `pgbouncer:6432`; `init`, `migrate`, `backup` and the exporters connect to
  `postgres:5432` directly (section 18).
  `ASLMS_MIGRATE_URL` is the owner's URL, for the host-run `alembic` and `aslms db-roles` in development.
- `aslms db-roles` (also `aslms ops role-passwords`) sets the `aslms_app` and `aslms_readonly` passwords from `.env`
  at every `init` run, so a changed password reaches the database at the next start. Each password is sent as a
  SCRAM-SHA-256 verifier computed in the process (libpq's `PQencryptPasswordConn`, the algorithm named), so the plain
  text never reaches the server, its logs or `pg_stat_activity` (design pre-pilot-hardening, decision 5). Check:
  `docker compose exec postgres psql -U aslms -d aslms -Atc "select rolname, left(rolpassword, 14) from pg_authid
  where rolname in ('aslms_app','aslms_readonly')"` shows `SCRAM-SHA-256$` for both.

## 5. Secret rotation

- **`ASLMS_JWT_SECRET`:** change it in `.env`, then `docker compose up -d`. Everyone is signed out.
- **`ASLMS_APP_PASSWORD` / `ASLMS_READONLY_PASSWORD`:** change it in `.env`, then `docker compose up -d`. `init`
  applies it before the application services restart. `pgbouncer` is recreated with the new value after `init`
  (its user list is written at start).
- **`REDIS_PASSWORD`:** change it in `.env`, then `docker compose up -d`. Redis restarts empty, which is safe: the
  token is fetched again and beat repeats its jobs.
- **`POSTGRES_PASSWORD`:** it applies only when a cluster is first created. First run, in psql:
  `docker compose exec postgres psql -U aslms -d aslms -c "ALTER ROLE aslms PASSWORD '<new>'"`. Then change `.env`
  and `docker compose up -d`.
- **NAPIX credentials and mail secrets:** change them in `.env`, then `docker compose up -d`.
- **`GRAFANA_ADMIN_PASSWORD`:** Grafana applies it only when its volume is first created. Change it in `.env`, then
  `docker compose exec grafana grafana cli admin reset-admin-password '<new>'`.
- **`FLOWER_BASIC_AUTH`:** change it in `.env`, then `docker compose up -d flower`.

## 6. Upgrading (decision 12)

`docker compose up` no longer migrates an existing database. When a build needs a newer schema, `init` exits with
code 3 and the message "The database is at X; this build needs Y". Nothing else starts. The procedure:

1. `git pull` (or copy the new release), then `docker compose build`.
2. `docker compose stop api worker scheduler web pgbouncer`. PgBouncer keeps its own `aslms_app` server connections
   open after the clients stop, so it is stopped too.
3. `docker compose --profile ops run --rm migrate`. It runs preflight and refuses while an `aslms_app` session is
   connected. It writes a `pre-migrate` backup and checks it with `pg_restore --list`, then runs
   `alembic upgrade head` and seed, and writes the audit row `system.migrated`.
4. `docker compose up -d`.

If `init` exits with code 4 ("The database is newer than this build"), the code is older than the database: deploy
the matching build, never downgrade by hand.

**The document store must be writable by uid 10001** (design pre-pilot-hardening, decision 3). `init` runs
`aslms ops store-check` right after preflight: it creates `/data/store` when missing and writes and removes a probe
file in the store and in every first-level folder. On success the log shows `store-check: /data/store writable
(N folders)`. A store created before the backend ran as uid 10001 is owned by root, and order PDFs would fail with
`PermissionError`; the check then stops the start (exit 1 at every `APP_ENV`), names how many folders failed and the
first one, and prints the remedy. Run it once, then `docker compose up -d`:
- on a Linux host: `sudo chown -R 10001:10001 ./data/store`;
- on Docker Desktop for Windows, where `chown` is refused on bind mounts:
  `docker compose run --rm --no-deps -u root --entrypoint sh worker -c "chmod -R a+rwX /data/store"`.

Only `/data/store` is written by the application; the cause-list folder is only read.

## 7. Backups (decision 13)

The `backup` service writes a backup at minute 30 of every `BACKUP_INTERVAL_HOURS` hours, IST (00:30, 06:30, 12:30
and 18:30 by default). Under `BACKUP_DIR`:

- `db/aslms-<date-time>[-tag].dump`: `pg_dump -Fc` of the whole database, taken in one snapshot with the counts;
- `db/roles-<…>.sql`: `pg_dumpall --roles-only`. It holds password hashes, so keep it as secret as `.env`;
- `db/manifest-<…>.json`: revision, versions, size and sha256, row counts, store files;
- `store/`: an add-only mirror of the document store. Each copied file is checked against its sha256 name;
- `status/last.json`, `status/last-success.json` and `status/restore-check.json`.

Each run also writes a `job_runs` row (`backup`), so the data-health screen shows the last backup.

- By hand: `docker compose exec backup aslms ops backup [--tag before-something]`.
- Status: `docker compose exec backup aslms ops backup-status`.

**Retention** prunes dump sets only, never the store mirror. It keeps everything from the last 48 hours, the first
set of each day for 14 days, each Sunday for 8 weeks, each 1st of the month for 12 months, and the last 5
`pre-migrate` sets (`BACKUP_KEEP_*`). Measure the first dump's size and adjust.

**Off-machine copy:** every week, copy `BACKUP_DIR` to an encrypted external drive (BitLocker To Go) and keep it away
from the machine. At the SDC, use their backup service. The worst-case loss is about 6 hours of user work. If less
is needed, WAL archiving with point-in-time recovery is a follow-up.

## 8. Images and an offline host (decision 21)

Every image is pinned (`compose.yml`, the two Dockerfiles). The backup image's `pg_dump` is PostgreSQL 16, matching
the server's major version; keep them together. To supply a host without registry access:

```
docker compose build
docker save -o aslms-images.tar postgres:16.15 redis:7.4.10-alpine nginx:1.28-alpine clamav/clamav:1.5.4 \
  aslms-init aslms-api aslms-worker aslms-scheduler aslms-web aslms-backup aslms-migrate
# on the target
docker load -i aslms-images.tar
```

Image updates follow the upgrade procedure (section 6).

## 9. Postgres settings (decision 15)

The `postgres` command sets these values from `.env`. The defaults assume 8 GB given to Docker and SSD storage:
`PG_SHARED_BUFFERS` (1GB, about 25 % of Docker's memory), `PG_EFFECTIVE_CACHE_SIZE` (4GB, 50-75 %), `PG_WORK_MEM`
(16MB), `PG_MAINTENANCE_WORK_MEM` (256MB) and `PG_MAX_CONNECTIONS` (100). WAL, checkpoint, planner and logging values
are fixed: statements over 2 s and lock waits are logged. `shm_size` is 1 GB. `archive_mode` stays off.

## 10. Restore check and disaster restore (decision 14)

**Restore check:** it runs every Sunday at 04:30 IST, and by hand with
`docker compose exec backup aslms ops restore-check [--dump <file>]`. It restores the latest dump into the scratch
database `aslms_restore_check` (no other name is accepted). It compares the revision and the manifest's row counts,
checks 50 random documents against the store mirror (file present, sha256 matches), drops the scratch database, and
writes a `job_runs` row and `status/restore-check.json`. Free disk of about twice the database size is needed.

**Disaster restore** (a new or wiped host):

1. Install as in section 3 with the same `.env` (or the same secrets), but do not start the stack. Run
   `docker compose up -d postgres` only.
2. Make sure no application service runs: `docker compose stop api worker scheduler web pgbouncer backup`.
3. Restore:

   ```
   docker compose --profile ops run --rm migrate aslms ops restore \
     --dump /backups/db/aslms-<…>.dump --roles /backups/db/roles-<…>.sql \
     --confirm-overwrite aslms --store-from /backups/store
   ```

   It refuses while an `aslms_app` session is connected. It restores the roles, recreates the database from the dump,
   copies the store back from the mirror (add-only), and writes the audit row `system.restored`.
4. `docker compose up -d`. `init` sees the database at head and sets the role passwords from `.env`.
5. Check: the super admin signs in. `docker compose exec api aslms ops load-report` matches the manifest's counts.
   The data-health screen loads.

The integrator rehearses this once in a separate Compose project (`-p aslms-restoretest`) and records the time from
empty to signed in in the decisions log.

## 11. The NAPIX switch and the load

- NAPIX calls happen only while the master switch is on. The owner sets it in the shell for the run, never in
  `.env`, `compose.yml` or code. Compose passes it to the `worker` (background fetching) and to the `api` (the
  portal's own court calls: court search, fetch from court, the data-load fetch, System health's Test now), so one
  `NAPIX_ENABLED=true docker compose up -d` turns both on, and a start without it leaves both off.
- Pause and resume the backdated load on the portal's Data collection screen (or `aslms data-load pause --reason ...` /
  `resume`). Do not stop the worker for that.
- `job_runs` rows left `running` by a restart are marked failed (`interrupted`) when the worker, the scheduler and
  the backup service start (decision 18). Never run `aslms queue-run` by hand during a restart. For an old stuck row:
  `docker compose exec api aslms ops repair-jobs --older-than 6h [--job NAME] [--dry-run]`.
- System health request console (design `system-health-inspector`, row 123): opening `/system` makes no court call
  and no token request. A card opens the console; Send makes one live call under the Test now guards; "Check token" is
  one audited token request, at most once per `HEALTH_TOKEN_CHECK_MIN_SECONDS` (600). The NAPIX PDFs are served from
  `NAPIX_DOCS_DIR` (`/app/napix-docs`, a read-only mount of `docs/specs/pdf` on the `api`); `docker compose exec api ls
  /app/napix-docs` lists three files. The owner-run live check (at most 6 requests, the master switch on for that run
  only, set in the shell) is in the design note's Verification, step 5.

## 12. ClamAV (decision 17)

- **internet** (default): `freshclam` in the container downloads signatures. At the SDC this needs one egress rule.
- **mirror:** add `compose.clamav-mirror.yml` to `COMPOSE_FILE`. Copy `infra/clamav/freshclam.conf.example` to
  `infra/clamav/freshclam.conf` and set `PrivateMirror` to the internal mirror, which `cvdupdate` fills on a
  connected machine.
- **offline:** add `compose.clamav-offline.yml` to `COMPOSE_FILE`. Copy `main.cvd`, `daily.cvd` and `bytecode.cvd`
  from a `cvdupdate` folder with `sh infra/clamav/import-signatures.sh <folder>`. Repeat at least weekly.
- On the first start, the signature download takes minutes. Until the health check passes, uploads answer 503
  `scanner_unavailable`.
- ClamAV needs about 1.5 GB of memory, more during a reload.
- Check with `docker compose exec api aslms documents scan-check` (EICAR).

## 13. Mail

Every sign-in needs an e-mailed code, so mail must work. Preflight refuses, in prod, the console backend, an
unconfigured backend and the Mailtrap sandbox (it never delivers). Use the State's government relay (`SMTP_*`,
backlog row 27) or Mailtrap's sending service with a verified domain. Test with
`docker compose exec api aslms alerts test-mail --to <address>`.

## 14. Routine checks

- **Daily:** the Grafana "ASLMS overview" dashboard and any firing alert (section 17); the data-health screen
  (queue, jobs, mail, the last `backup` job); `aslms ops backup-status`.
- **Weekly:** the restore check passed (`status/restore-check.json`); disk space of the host and of `BACKUP_DIR`;
  the off-machine copy.
- **Monthly:** certificate expiry
  (`openssl x509 -enddate -noout -in infra/proxy/certs/fullchain.pem`); image updates (section 8, then section 6).

## 15. Troubleshooting

- **`init` exits with a preflight error:** the message names the variable (never the value). Fix `.env` and run
  `docker compose up -d` again.
- **`init` exits 3, "database behind head":** run the upgrade procedure (section 6).
- **`init` exits 4, "database newer than this build":** deploy the matching build.
- **Uploads answer 503:** ClamAV is not ready (`docker compose ps clamav`, `docker compose logs clamav`). See
  section 12.
- **Sign-in answers 429 `throttled`:** many sign-ins from one address. Wait a minute. If a whole office is refused
  every morning, raise `PROXY_SESSION_RATE` / `PROXY_SESSION_BURST` and restart the proxy.
- **Upload refused 413 `too_large`:** the file is over `UPLOAD_MAX_BYTES`. The proxy and the API use the same limit.
- **A job shows `running` for hours:** `aslms ops repair-jobs --dry-run`, then without `--dry-run`.
- **Disk full:** check `BACKUP_DIR` (lower `BACKUP_KEEP_*`, never delete the store mirror), the store, and Docker's
  own disk (`docker system df`).
- **The proxy restarts:** `docker compose logs proxy`. A missing `fullchain.pem` / `privkey.pem` is named there.

## 16. Development

A developer's `.env` keeps `APP_ENV=dev`, `COMPOSE_PATH_SEPARATOR=:` and `COMPOSE_FILE=compose.yml:compose.dev.yml` (Docker on Windows separates the files with `;` unless `COMPOSE_PATH_SEPARATOR=:` is set). The override publishes postgres (`127.0.0.1:5433`), api
(`127.0.0.1:8000`, with `/docs`) and web (`http://localhost:3000`) on loopback only. The proxy starts only with
`--profile proxy`. Redis is never published: run host-side commands that need it through
`docker compose exec api …`. The database tests use `ASLMS_TEST_DATABASE_URL`, by default
`postgresql+psycopg://aslms:aslms@127.0.0.1:5433/aslms_test`: the server, the credentials and a base name. Each
`pytest` session creates its own database on that server, `<base>_<UTC yyyymmddHHMMSS>_<6 hex>` (for example
`aslms_test_20261020101500_a1b2c3`), migrates it to head and drops it at the end, so two sessions at once never
touch each other's data. A killed run leaves its database behind; the next run drops it after 24 hours (only names
of exactly that form, and only when nobody is connected). Changes to cluster-wide state (the three roles,
`pg_monitor`) are serialised by an advisory lock in the `postgres` database: the first migration and every test
marked `migration_cycle` take it. The URL's user needs `CREATEDB` (the Compose superuser `aslms` has it). Three
test-only variables, never application settings and never read from `.env`:

| Variable | Default | Meaning |
|---|---|---|
| `ASLMS_TEST_DB_PER_RUN` | `1` | `0` uses the named database as before (wipe, downgrade, upgrade), for debugging with `psql`; a name without `test` is refused, so a mistyped URL can never wipe `aslms`. |
| `ASLMS_TEST_KEEP_DB` | `0` | `1` keeps the run database at the end and prints its name; drop it by hand afterwards. |
| `ASLMS_TEST_REQUIRE_DB` | `0` | `1` makes an unreachable server a failure instead of a skip (CI sets it). |

The old shared `aslms_test` database is no longer used and may be dropped once by hand
(`docker compose exec postgres dropdb -U aslms aslms_test`). Use `127.0.0.1`, not `localhost`: on Windows
`localhost` resolves to `::1` first, nothing listens there, and every new connection waits seconds before falling
back to IPv4, which makes the database tests crawl. After the cluster password changes, set that variable
in the shell that runs `pytest`. Compose checks the variables of every service, profiles included, so a developer's
`.env` also needs `ASLMS_READONLY_PASSWORD`, `GRAFANA_ADMIN_PASSWORD` and `FLOWER_BASIC_AUTH`, even with
`COMPOSE_PROFILES` blank (preflight only warns in development).

## 17. Monitoring

Design deployment-checklist, Part B (row 77, decisions 22-28). The plan (§8.2) wants system monitoring from the pilot
stage, so the pilot's `.env` sets `COMPOSE_PROFILES=monitoring`, and with `APP_ENV=prod` preflight refuses a stack
without it.

**What runs.** `prometheus`, `alertmanager`, `grafana`, `flower`, `postgres-exporter`, `redis-exporter`,
`pgbouncer-exporter` (Part C) and `ops-exporter` (section 1). Prometheus scrapes every 30 seconds (the ops exporter every 60) and keeps
`PROMETHEUS_RETENTION` (30 days). The screens are published on the host's loopback only and are never served through
the proxy:

| Screen | Address | Sign-in |
|---|---|---|
| Grafana | `http://127.0.0.1:3001` | `admin` / `GRAFANA_ADMIN_PASSWORD` |
| Prometheus | `http://127.0.0.1:9090` | none (loopback only) |
| Alertmanager | `http://127.0.0.1:9093` | none (loopback only) |
| Flower | `http://127.0.0.1:5555` | `FLOWER_BASIC_AUTH` |

At the SDC, open them through an SSH tunnel, for example
`ssh -L 3001:127.0.0.1:3001 -L 9090:127.0.0.1:9090 -L 9093:127.0.0.1:9093 -L 5555:127.0.0.1:5555 <user>@<vm>`.

**Where the figures come from.**
- `ops-exporter` runs `aslms ops metrics --port 9108` as `aslms_readonly`: the queue by lane, kind and status and its
  oldest runnable row; each job's last success, running rows and the oldest running row; the queue worker's last pass
  (its liveness: the worker is not a Celery worker, so Flower does not see it); NAPIX calls in the last hour, the
  detected window's remaining calls and the master switch as the worker sees it; open source failures; e-mail
  notifications and the oldest queued; SourceTrace documents; the last backup and restore check (from
  `BACKUP_DIR/status`, read-only); free disk space of `/data` and `/backups`; ClamAV's state and signature date; the
  portal probe through the proxy, `web` and `api`; the certificate's expiry. Every database read runs read-only under a
  10-second statement timeout, and readings are cached for 60 seconds. No label carries case data.
  `docker compose exec ops-exporter aslms ops metrics --once` prints one reading.
- The api serves request counts and durations by route template on port 9100 inside the Compose network.
- `postgres-exporter` (as `aslms_readonly`, a member of `pg_monitor`) and `redis-exporter`.
- `pgbouncer-exporter` reads `SHOW POOLS`, `SHOW STATS` and the like from PgBouncer's `pgbouncer` console as
  `aslms_readonly`, a stats user there (section 18).
- Grafana's only data source is Prometheus. It never queries the database: `aslms_readonly` can read every table.

**Dashboards** (folder ASLMS, provisioned from `infra/grafana/dashboards`; edits in the UI are not kept):
"ASLMS overview", "PostgreSQL", "Redis and Celery". Change a dashboard by editing its JSON file.

**Alert rules** are in `infra/prometheus/rules.yml`, with unit tests in `rules.test.yml`. After any change run:

```
docker run --rm -v "$PWD/infra/prometheus:/p:ro" --entrypoint promtool prom/prometheus:v3.7.2 test rules /p/rules.test.yml
docker compose restart prometheus
```

Alertmanager mails the alerts to `OPS_ALERT_EMAIL` through the `SMTP_*` relay of section 13 (`SMTP_HOST`,
`SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_STARTTLS`). Without `SMTP_HOST` or `OPS_ALERT_EMAIL`
the alerts are shown in Grafana and Alertmanager only, and preflight warns. Critical alerts repeat every hour,
warnings every 4 hours. To silence an alert during planned work, use Alertmanager's "New silence".

**What to do for each alert.**
- **ServiceDown** (a scrape target, the database behind the postgres exporter, or PgBouncer behind its exporter,
  down for 5 minutes):
  `docker compose ps`, then `docker compose logs <service>`; `docker compose up -d` restarts it. If `postgres` is
  down, nothing works: check disk space and `docker compose logs postgres` first.
- **PortalDown** (the portal does not answer through the proxy): check `proxy`, `web` and `api` with
  `docker compose ps`; `docker compose logs proxy` names a missing certificate (section 15).
- **RedisDown** (Redis does not answer for 5 minutes): `docker compose logs redis`, then `docker compose up -d redis`. A restart loses nothing durable.
- **ClamAVDown** (uploads answer 503): section 12; `docker compose logs clamav`. After a restart the signature load
  takes minutes.
- **ClamAVSignaturesOld** (older than 3 days): `freshclam` cannot reach its source. Check the egress rule, the mirror,
  or import the offline signatures (section 12).
- **PostgresConnectionsHigh** (over 80 % of `max_connections`): look for a stuck client in
  `docker compose exec postgres psql -U aslms -d aslms -c "select usename, state, count(*) from pg_stat_activity group by 1, 2"`;
  raise `PG_MAX_CONNECTIONS` only after finding the cause.
- **PgBouncerClientsWaiting** (application clients queued for a PgBouncer server connection for 5 minutes): the pool
  is exhausted or Postgres is slow. Section 18: `SHOW POOLS` shows `cl_waiting` and `sv_active`; look for long
  transactions in `pg_stat_activity` (a slow report or a stuck worker). Raise `PGBOUNCER_DEFAULT_POOL_SIZE` (and keep
  it well under `PG_MAX_CONNECTIONS`) only after finding the cause, then `docker compose up -d pgbouncer`.
- **CertExpiring** (under 21 days): renew the certificate (section 3, step 3) and `docker compose restart proxy`.
- **DiskLow** (under 15 % or 10 GB free on `/data` or `/backups`): section 15, "Disk full". Never delete the store
  mirror or the order store.
- **WorkerStalled** (no queue worker activity, a pass start or a claimed row, for 2 hours while rows are runnable;
  `aslms_worker_alive_timestamp`, so a long load pass that keeps claiming rows does not fire it): `docker compose
  logs worker`, then
  `docker compose restart worker` (its interrupted rows are repaired at start, section 11).
- **JobStuck** (a job `running` for more than 6 hours): `aslms ops repair-jobs --dry-run`, then section 11.
- **JobLate** (a scheduled job has not succeeded in time: notifications and the alert scan 30 minutes, text extraction
  and the next-dates reader 1 hour, the dedupe sweep and digests 26 hours): `docker compose logs scheduler`; Flower
  shows the failing task; the data-health screen shows the job's last error.
- **BackupMissing** (no successful backup for 13 hours): `docker compose logs backup`,
  `docker compose exec backup aslms ops backup-status`; run `docker compose exec backup aslms ops backup` by hand
  once the cause is fixed (section 7).
- **RestoreCheckMissing** (none for 8 days): `docker compose exec backup aslms ops restore-check` (section 10).
- **NapixErrorsHigh** (more than 100 failed NAPIX calls in an hour): the data-health screen's NAPIX block and
  `/admin/napix/calls` show the error family. Pause the load (section 11) if the gateway is failing; never change the
  switch from a file.
- **MailFailing** (more than 10 failed e-mails in an hour, or the oldest queued over 30 minutes): sign-in codes may not
  arrive. `docker compose exec api aslms alerts test-mail --to <address>` and section 13.

**Test the alert path** (Verification, Part B): with mail configured, `docker compose stop clamav`; within about
10 minutes ClamAVDown fires and the e-mail arrives; then `docker compose up -d clamav`.

**Optional host metrics** (decision 28). On a Linux VM at the SDC, `COMPOSE_PROFILES=monitoring,monitoring-host` adds
`node-exporter` and `cadvisor` (cadvisor reads the Docker socket and runs privileged). They are not used on Docker
Desktop, where they would describe Docker's VM; there, disk space comes from the ops exporter.

## 18. PgBouncer

Design deployment-checklist, Part C (row 78, decision 29). `api`, `worker` and `scheduler` reach Postgres through
`pgbouncer:6432` inside the Compose network; the port is never published, not even in development.

**Settings** (written by `infra/pgbouncer/entrypoint.sh` at start into the container's tmpfs):
- `pool_mode = transaction`: a server connection serves a client for one transaction only;
- `max_client_conn = 200`, `default_pool_size = 20` (`PGBOUNCER_MAX_CLIENT_CONN`, `PGBOUNCER_DEFAULT_POOL_SIZE` in
  `.env`; keep the pool well under `PG_MAX_CONNECTIONS`, which also serves `init`, `backup` and the exporters);
- `max_prepared_statements = 200` (`PGBOUNCER_MAX_PREPARED_STATEMENTS`): psycopg 3 prepares statements at the
  protocol level, and PgBouncer 1.22+ (psycopg's documented minimum) tracks them per server connection;
- `server_reset_query` empty; `auth_type = hba` with SCRAM-SHA-256 on every line. `aslms_app` may reach the
  database; `aslms_readonly` only the `pgbouncer` console, as a stats user (`SHOW` only). Nobody is an admin user, so
  `PAUSE`, `RELOAD` and `SHUTDOWN` are refused on the console. The user list holds the two passwords from `.env`,
  mode 600, in the tmpfs.

**Versions** (design pre-pilot-hardening, decisions 6 and 7):
- PgBouncer is pinned exactly in `infra/pgbouncer/Dockerfile` (`pgbouncer=1.25.1-r0` on Alpine 3.23.3, with
  `postgresql16-client=16.15-r0` for the healthcheck). When Alpine republishes the package the build fails: change
  the pin on purpose, to a version 1.22 or later. The pilot gets built images through `docker save` / `docker load`
  (section 8), so a built image does not depend on the mirror.
- libpq 17 or later: psycopg closes prepared statements with the protocol message `Close`, which PgBouncer tracks,
  only on libpq 17+ (older ones send SQL `DEALLOCATE`, which it does not). Preflight stops the start at every
  `APP_ENV` when libpq is older (`preflight fatal: libpq: ...`: rebuild the image). Check:
  `docker compose exec api python -c "import psycopg; print(psycopg.pq.version())"` (180006 or higher today).

**Healthcheck** (decision 8): `infra/pgbouncer/healthcheck.sh` logs in through the pool as `aslms_app` and runs
`SELECT 1`, so "healthy" means the application can log in; a wrong `ASLMS_APP_PASSWORD` or an unreachable Postgres
turns it unhealthy, and `api`, `worker` and `scheduler` do not start. The password reaches psql only as `PGPASSWORD`
inside the container. `docker inspect --format '{{json .State.Health.Log}}' aslms-pgbouncer-1` shows psql's output
(`1`, or its error line, such as "password authentication failed for user aslms_app").

**Who connects directly** to `postgres:5432`: `init`, `migrate` and `backup` (DDL, `pg_dump`, role passwords, the
session checks) and the postgres and ops exporters (a view that does not depend on the pool). Host-run `pytest`,
`alembic` and `psql` in development also go to `127.0.0.1:5433` directly.

**What the application may not do.** Transaction pooling hands each transaction to any server connection. The code
uses only transaction-scoped features: `SET LOCAL statement_timeout` (reports, dashboards, the audit search, the data
health screen) and `pg_advisory_xact_lock` (the court-number dedupe). A session `SET`, `SET ROLE`, a session
advisory lock, `LISTEN`, a temporary table, `set_config(..., false)` or a cursor `WITH HOLD` would leak to the next
client or be lost, and so would `RESET`, `DISCARD` or SQL-level `PREPARE` / `DEALLOCATE`;
`backend/tests/unit/test_pgbouncer.py` scans `backend/aslms` (every SQL statement start in every string, and the
unambiguous patterns in every line) and fails on any of them.

**Upgrades and restores.** PgBouncer keeps `aslms_app` server connections open for a while after its clients stop,
and `migrate` and `ops restore` refuse while any `aslms_app` session is connected. Stop it with the application
services (sections 6 and 10). `docker compose up -d` starts it again after `init`.

**Checks.**

```
# the pools (cl_active, cl_waiting, sv_active, sv_idle, maxwait), as the stats user; psql asks for ASLMS_READONLY_PASSWORD
docker compose exec api psql -h pgbouncer -p 6432 -U aslms_readonly pgbouncer -c "SHOW POOLS"
# the application's server connections come from pgbouncer
docker compose exec postgres psql -U aslms -d aslms -c "select usename, client_addr, state from pg_stat_activity where usename = 'aslms_app'"
```

`docker compose logs pgbouncer` shows refused logins and pool errors.

**Deferring PgBouncer** (owner check 7): to run without it, the three services' `DATABASE_URL_SYNC` would point at
`postgres:5432` again. That is a recorded deviation in the design, never a quiet edit of `compose.yml`.

## 19. Repository and CI

Design [github-and-ci](design/github-and-ci.md) (backlog row 15).

**The remote.** A private GitHub repository, `nayanlhuzuri/aslms`, on the owner's personal account, where it stays.
Private because the repository holds personal data from public court records (see below) and the e-Committee
specification PDFs, whose licence for redistribution is unknown. Forking is off; collaborators are named people only.
The remote and the repository's settings are the owner's: the guard hook refuses `git remote add` / `set-url` /
`remove`, `git config remote.*`, `gh repo create|delete|edit|rename|archive`, `gh secret` and `gh api` from the
assistant.

**The first push** (owner, backlog row `github-first-push`), on the owner's machine with a clean `main`:
1. Create the private repository `nayanlhuzuri/aslms`, empty (no README, licence or `.gitignore`). Apply the
   settings and rulesets below that the plan offers.
2. `python backend/tools/repo_policy.py history`: clean.
3. A full-history gitleaks scan with the repository's configuration: clean.
   ```
   docker run --rm -v "$PWD:/repo" -e GIT_CONFIG_COUNT=1 -e GIT_CONFIG_KEY_0=safe.directory -e GIT_CONFIG_VALUE_0='*' \
     ghcr.io/gitleaks/gitleaks@sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f \
     git /repo --config /repo/.gitleaks.toml --redact --no-banner
   ```
4. `git remote add origin <url>`, `git push -u origin main`, `git push origin "refs/tags/feature/*"`. The old local
   `feature/*`, `design/*` and `worktree-agent-*` branches are not pushed: their work is on `main` as squash commits.
5. Watch the first `CI` run: every job green. Record its address and duration in the decisions log. A red job
   becomes a fix row.
6. `gh auth login` on the machine that runs cycles (the token stays in the Windows credential store, never in the
   repository or `.env`). `/team-status` then shows CI, and the integrator can check `main` before merging.

**What never reaches the remote, and why.** Enforced three times: `.gitignore`, `backend/tools/repo_policy.py`
(`tree`, `range A..B`, `history`; it prints the path, the line and the rule, never the value) and gitleaks
(`.gitleaks.toml`, every allowlist entry commented).
- `.env` and `.env.*` in any folder (only `.env.example` is tracked, with every secret empty); keys and
  certificates (`*.pem`, `*.key`, `*.p12`, `*.pfx`); `backups/`, `*.dump`, `roles-*.sql`; `data/` (the document
  store and cause-list PDFs; `frontend/src/**/data/` is source); `infra/proxy/certs/`, `infra/clamav/freshclam.conf`;
  `docs/specs/napix/hc/samples/` (unreviewed `aslms napix-check` output); `.claude/settings.local.json`,
  `.claude/worktrees/`; Postman environments; the old document folders.
- A non-empty secret in an example env file; the NAPIX switch on in configuration; a private-key block; a literal
  NAPIX credential; a file over 20 MB.
- `docs/specs/samples/` and `backend/tests/fixtures/causelists/` stay: the tests depend on them. They hold no token,
  key, client id or personal contact, but they do hold **personal data from public court records** (party, advocate
  and judge names, case numbers, CNRs, order and cause-list PDFs). That is acceptable in a private repository with
  named collaborators only. Making the repository public needs a separate redaction item first.
- Three old development defaults are in the history of `.env.example` (`POSTGRES_PASSWORD`, `ASLMS_APP_PASSWORD`,
  `ASLMS_READONLY_PASSWORD`); preflight refuses all three in production, and `repo_policy.py` lists them, commit by
  commit, in its history allowlist.

**No secrets in GitHub, ever.** No repository or environment secret is created: never a NAPIX credential, a mail
token, a JWT secret or a SourceTrace key. CI runs with the NAPIX switch off and empty credentials (a step fails the
job otherwise), the console mail backend and SourceTrace off. The test database password `aslms-ci` belongs to a
throwaway service container. The `compose` job generates its Compose values with `openssl rand`, masks them and
writes no `.env`; only `web` is started.

**What each CI job checks** (`.github/workflows/ci.yml`; on pull requests into `main`, pushes to `main` and by hand):

| Job | Checks | A red run means |
|---|---|---|
| `changes` | Whether anything outside the docs-only list changed (design notes, reports, audits, team docs, backlog, decisions log, `README.md`, `CLAUDE.md`, top-level `docs/*.docx`). | Rarely red; a git error. |
| `policy` | `repo_policy.py tree` and `range` (or `history` on a first push); gitleaks on the pushed commits; actionlint. | A forbidden file or value was committed (stop: see below), or a workflow error. |
| `backend` | ruff check, ruff format, pytest against a `postgres:16.15` service with `ASLMS_TEST_REQUIRE_DB=1`, installed with the development versions in `backend/constraints-ci.txt` (refresh it with `pip freeze --exclude-editable` when the `.venv` is upgraded). The JUnit report is an artifact (7 days). | A lint or test failure; open the JUnit artifact or the step log. |
| `frontend` | `npm ci`, lint, typecheck, test, build, and `gen:api` leaving no diff. | A portal failure, or `openapi.json` and `schema.d.ts` out of step. |
| `compose` | `docker compose config`, every image built (profiles included), `web` started, `portal_smoke.py`, `promtool test rules`. The web log is an artifact on failure. | An image does not build, a page does not render, or an alert rule test fails. |
| `ci-ok` | Every job passed or was skipped. | Look at the job that failed. |

A docs-only push runs `changes`, `policy` and `ci-ok` only. A red run on `main` stops the integrator's next merge.

**The weekly secret scan** (`.github/workflows/secret-scan.yml`, Sunday 21:00 UTC = Monday 02:30 IST, and by hand):
gitleaks and `repo_policy.py history` over the whole history. A failure e-mails the owner through GitHub. **On a
true finding: stop.** No agent "fixes" it. The owner rotates the key at its source first, then decides whether to
rewrite history (which needs every clone re-made).

**The pre-push hook** (optional): `git config core.hooksPath .githooks` once. `.githooks/pre-push` then runs
`repo_policy.py range` on the outgoing commits, and gitleaks when it is on `PATH`; a finding refuses the push.

**Pushes by the team.** The team merges locally; the integrator then runs exactly `git push origin main` and
`git push origin refs/tags/feature/<slug>-done`, fast-forward only. A refused push is reported, never forced; the
owner pushes later. The guard hook refuses `--force`, `-f`, `--force-with-lease`, `--mirror`, `--all`, `--delete`,
a `+` or `:` refspec and any remote other than `origin`. The narrow permissions in `.claude/settings.json` (allow
the two push forms and `gh run list` / `gh run view`; deny the force forms) are set by the owner.

**Rulesets and settings** (if the plan offers them for a private repository; on GitHub Free the guard hook and
gitleaks carry the load and the owner is the only person with write access):
- a ruleset on `main`: block force pushes and deletion, require linear history; pull requests and status checks are
  not required (a squash commit made locally has no checks yet);
- a tag ruleset on `feature/*-done`: block update and deletion;
- Actions limited to GitHub-made actions and `docker/*`; the default workflow token read-only; "Allow GitHub Actions
  to create and approve pull requests" off; Dependabot alerts on (`.github/dependabot.yml` updates the action pins
  monthly); forking off; GitHub secret scanning and push protection on if the plan offers them.

**The minutes budget.** A full run is about 25–35 billed minutes (backend about 15, frontend about 6, compose about
10, policy 1; about 15 minutes on the clock), a docs-only push about 2. Roughly 35–45 minutes per cycle: GitHub
Free's 2,000 private minutes a month cover about 45–60 cycles (check the account's billing page). Artifacts are kept
7 days.

## Pilot go-live checklist

- [ ] Rows 76, 16, 77 and 78 merged.
- [ ] `aslms ops preflight` passes with `APP_ENV=prod`.
- [ ] No port other than 443 and 80 reachable from another PC (5433, 6379, 8000, 3000 and 3310 closed).
- [ ] TLS checked from a pilot PC (the internal CA installed; `http://` redirects; another host name refused).
- [ ] Throttling checked (30 quick sign-ins give 429 `throttled`).
- [ ] EICAR refused through the proxy.
- [ ] First backup and restore check passed; the restore drill time recorded.
- [ ] PgBouncer in the path (section 18): `SHOW POOLS` lists `aslms_app` traffic, and the application's sessions in
      `pg_stat_activity` come from `pgbouncer`.
- [ ] Monitoring up (`COMPOSE_PROFILES=monitoring`): every Prometheus target up, `promtool test rules` passes, the
      Grafana overview shows live figures, a ClamAVDown test alert reached `OPS_ALERT_EMAIL` (section 17).
- [ ] Load counts and the sample check in the decisions log (`aslms ops load-report --format md`,
      `aslms ops sample-cnrs --seed <n> --format md`).
- [ ] The government mail relay live-checked with a real sign-in (row 27).
- [ ] The owner's browser checklists (rows 53 and 56).
- [ ] The mapping data for the pilot department entered.
