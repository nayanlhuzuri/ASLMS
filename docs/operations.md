# ASLMS operations runbook

How to install, run, upgrade, back up and restore the ASLMS pilot. Written for the design
[deployment-checklist](design/deployment-checklist.md) (Part A, backlog row 16). DB_STANDARD §11 step 7 names this
file. Monitoring (Part B, row 77) and PgBouncer (Part C, row 78) add their own sections when they are built.

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
| `redis` | `redis:7.4.10-alpine` | the NAPIX token and Celery messages; password, memory only | none |
| `clamav` | `clamav/clamav:1.5.4` | virus scan of every upload | none |

Networks:
- `default`: postgres, redis, clamav and the backend services.
- `portal`: api and web. It has a fixed subnet, and the api trusts `X-Forwarded-For` only from `WEB_IP`.
- `edge`: web and proxy. The proxy cannot reach api, postgres or redis.

Volumes:
- `pgdata_v3`: the database. On Docker Desktop it lives inside the Docker VM disk, which a Docker reset erases. The
  backups therefore go to a host folder.
- `clamdb_v3`: ClamAV signatures.
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
   - `APP_ENV=prod`;
   - `COMPOSE_FILE=compose.yml`. The development override must not be used on the pilot;
   - generate each secret separately with `openssl rand -hex 32` (or
     `python -c "import secrets;print(secrets.token_hex(32))"`): `POSTGRES_PASSWORD`, `ASLMS_APP_PASSWORD`,
     `ASLMS_READONLY_PASSWORD`, `REDIS_PASSWORD`, `ASLMS_JWT_SECRET`. Every value must be different;
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
| `aslms_app` | `api`, `worker`, `scheduler` | DB_STANDARD §8 grants; no delete of legal records |
| `aslms_readonly` | reports and, from Part B, monitoring | SELECT |

- In production (`APP_ENV=prod`), the api, the worker and the scheduler refuse to start if their connection is a
  superuser (decision 5). Their `POSTGRES_PASSWORD` and `ASLMS_MIGRATE_URL` are blanked by Compose.
- `DATABASE_URL_SYNC` is the application's URL. Compose builds it for each service from the passwords.
  `ASLMS_MIGRATE_URL` is the owner's URL, for the host-run `alembic` and `aslms db-roles` in development.
- `aslms db-roles` (also `aslms ops role-passwords`) sets the `aslms_app` and `aslms_readonly` passwords from `.env`
  at every `init` run, so a changed password reaches the database at the next start.

## 5. Secret rotation

- **`ASLMS_JWT_SECRET`:** change it in `.env`, then `docker compose up -d`. Everyone is signed out.
- **`ASLMS_APP_PASSWORD` / `ASLMS_READONLY_PASSWORD`:** change it in `.env`, then `docker compose up -d`. `init`
  applies it before the application services restart.
- **`REDIS_PASSWORD`:** change it in `.env`, then `docker compose up -d`. Redis restarts empty, which is safe: the
  token is fetched again and beat repeats its jobs.
- **`POSTGRES_PASSWORD`:** it applies only when a cluster is first created. First run, in psql:
  `docker compose exec postgres psql -U aslms -d aslms -c "ALTER ROLE aslms PASSWORD '<new>'"`. Then change `.env`
  and `docker compose up -d`.
- **NAPIX credentials and mail secrets:** change them in `.env`, then `docker compose up -d`.

**Upgrading a machine that ran an older layout (before the backend ran as uid 10001):** the document folders under `./data` were created by root and the application cannot write them (order PDFs fail with `PermissionError`). Run once:
`docker compose run --rm --no-deps -u root --entrypoint sh worker -c "chmod -R a+rwX /data/store /data/causelists /data/storage"`
(on Windows `chown` to 10001 is refused, so use `chmod`; on Linux prefer `chown -R 10001:10001` on the same folders).

## 6. Upgrading (decision 12)

`docker compose up` no longer migrates an existing database. When a build needs a newer schema, `init` exits with
code 3 and the message "The database is at X; this build needs Y". Nothing else starts. The procedure:

1. `git pull` (or copy the new release), then `docker compose build`.
2. `docker compose stop api worker scheduler web`.
3. `docker compose --profile ops run --rm migrate`. It runs preflight and refuses while an `aslms_app` session is
   connected. It writes a `pre-migrate` backup and checks it with `pg_restore --list`, then runs
   `alembic upgrade head` and seed, and writes the audit row `system.migrated`.
4. `docker compose up -d`.

If `init` exits with code 4 ("The database is newer than this build"), the code is older than the database: deploy
the matching build, never downgrade by hand.

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
2. Make sure no application service runs: `docker compose stop api worker scheduler web backup`.
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
  `.env`, `compose.yml` or code.
- Pause and resume the backdated load on the portal's Data collection screen (or `aslms data-load pause --reason ...` /
  `resume`). Do not stop the worker for that.
- `job_runs` rows left `running` by a restart are marked failed (`interrupted`) when the worker, the scheduler and
  the backup service start (decision 18). Never run `aslms queue-run` by hand during a restart. For an old stuck row:
  `docker compose exec api aslms ops repair-jobs --older-than 6h [--job NAME] [--dry-run]`.

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

- **Daily:** the data-health screen (queue, jobs, mail, the last `backup` job); `aslms ops backup-status`.
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

A developer's `.env` keeps `APP_ENV=dev`, `COMPOSE_PATH_SEPARATOR=:` and
`COMPOSE_PATH_SEPARATOR=:` and `COMPOSE_FILE=compose.yml:compose.dev.yml` (Docker on Windows separates the files with `;` unless `COMPOSE_PATH_SEPARATOR=:` is set). The override publishes postgres (`127.0.0.1:5433`), api
(`127.0.0.1:8000`, with `/docs`) and web (`http://localhost:3000`) on loopback only. The proxy starts only with
`--profile proxy`. Redis is never published: run host-side commands that need it through
`docker compose exec api …`. The database tests use `ASLMS_TEST_DATABASE_URL`, by default
`postgresql+psycopg://aslms:aslms@localhost:5433/aslms_test`. After the cluster password changes, set that variable
in the shell that runs `pytest`.

## 17. Monitoring

Filled by Part B (row 77): Prometheus, Alertmanager, Grafana and Flower on `127.0.0.1` only, the alert rules and what
to do for each.

## Pilot go-live checklist

- [ ] Rows 76, 16, 77 and 78 merged.
- [ ] `aslms ops preflight` passes with `APP_ENV=prod`.
- [ ] No port other than 443 and 80 reachable from another PC (5433, 6379, 8000, 3000 and 3310 closed).
- [ ] TLS checked from a pilot PC (the internal CA installed; `http://` redirects; another host name refused).
- [ ] Throttling checked (30 quick sign-ins give 429 `throttled`).
- [ ] EICAR refused through the proxy.
- [ ] First backup and restore check passed; the restore drill time recorded.
- [ ] Load counts and the sample check in the decisions log (`aslms ops load-report --format md`,
      `aslms ops sample-cnrs --seed <n> --format md`).
- [ ] The government mail relay live-checked with a real sign-in (row 27).
- [ ] The owner's browser checklists (rows 53 and 56).
- [ ] The mapping data for the pilot department entered.
